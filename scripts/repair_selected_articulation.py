from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from exercise_motion_pkg.bake_and_rank import (
    dense_loop_review_video_frame_indices,
    launch_chromium_browser,
    parse_review_video_fps,
    render_baked_wear_frames_with_playwright,
    repeated_review_frame_data_urls,
    source_pose_stationary_support_evidence,
    with_fixed_preview_camera_options,
    write_validated_review_video_from_data_urls,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.foot_contact_observation import add_observed_foot_contacts, observe_foot_landmarks
from exercise_motion_pkg.structural_refinement import (
    constrain_to_source_articulation_envelope,
    stabilize_forefoot_ground_contacts,
    stabilize_distal_foot_heading,
    suppress_post_ik_anatomical_spikes,
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def refresh_embedded_mesh_renderer(preview_path: Path) -> None:
    """A repaired skeleton must be reviewed with the current renderer too."""
    html = preview_path.read_text(encoding="utf-8")
    start_marker = "    // Direct JavaScript port of buildSingleLowPolyMesh in SkeletonMotionPreview.kt."
    end_marker = "    const perspectiveCamera = new THREE.PerspectiveCamera("
    start = html.find(start_marker)
    end = html.find(end_marker, start)
    if start < 0 or end < 0:
        raise ValueError(f"Cannot find embedded Wear mesh renderer in {preview_path}")
    renderer_path = Path(__file__).resolve().parents[1] / "exercise_motion_pkg" / "wear_exact_mesh.js"
    renderer = renderer_path.read_text(encoding="utf-8").rstrip()
    preview_path.write_text(html[:start] + renderer + "\n" + html[end:], encoding="utf-8")


def clip_from_frames(payload: dict[str, Any]) -> MotionClip:
    frames = payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Motion payload has no frames")
    motion_frames: list[MotionFrame] = []
    joint_names: set[str] = set()
    for index, frame in enumerate(frames):
        joints_value = frame.get("joints") if isinstance(frame, dict) else None
        if not isinstance(joints_value, dict):
            raise ValueError(f"Motion frame {index} has no joints")
        joints = {
            str(name): tuple(float(component) for component in point[:3])
            for name, point in joints_value.items()
            if isinstance(point, list) and len(point) >= 3
        }
        joint_names.update(joints)
        motion_frames.append(
            MotionFrame(
                time_sec=float(frame.get("timeSec", index)),
                joints=joints,
            )
        )
    return MotionClip(
        fps=float(payload.get("fps") or 30.0),
        joint_names=sorted(joint_names),
        frames=motion_frames,
    )


def candidate_raw_path(manifest: dict[str, Any], workspace: Path) -> Path:
    for result in manifest.get("candidateResults") or []:
        if not isinstance(result, dict):
            continue
        candidate_workspace = result.get("candidateWorkspace")
        if candidate_workspace and Path(candidate_workspace).resolve() == workspace.resolve():
            raw_path = result.get("rawMotionJsonPath")
            if raw_path:
                return Path(raw_path)
    return workspace / "raw" / "motion.raw.json"


def repair_manifest(manifest_path: Path, *, render: bool) -> dict[str, Any] | None:
    manifest = load_json(manifest_path)
    selected_results = manifest.get("selectedResults")
    if not isinstance(selected_results, list) or not selected_results:
        return None
    selected = selected_results[0]
    if not isinstance(selected, dict):
        return None
    skeleton_path = Path(selected["skeletonPath"])
    workspace = Path(selected["candidateWorkspace"])
    raw_path = candidate_raw_path(manifest, workspace)
    if not skeleton_path.exists() or not raw_path.exists():
        return None

    backup_path = skeleton_path.with_suffix(skeleton_path.suffix + ".pre-articulation-fix")
    skeleton = load_json(backup_path if backup_path.exists() else skeleton_path)
    raw = load_json(raw_path)
    refreshed_support_evidence = None
    source_pose_reference_path = workspace / "segment_detection" / "exact_source_pose_reference.json"
    if source_pose_reference_path.exists():
        source_pose_reference = load_json(source_pose_reference_path)
        source_pose_payload = source_pose_reference.get("pose")
        candidate = selected.get("candidate")
        exercise_motion_contract = (
            candidate.get("exerciseMotionContract")
            if isinstance(candidate, dict)
            else None
        )
        if isinstance(source_pose_payload, dict):
            refreshed_support_evidence = source_pose_stationary_support_evidence(
                source_pose_payload,
                exercise_motion_contract=exercise_motion_contract,
            )
            source_video = workspace / "input" / "selected_segment.mp4"
            if source_video.is_file():
                alignment = raw.get("metadata", {}).get("videoWorldAlignment", {})
                refreshed_support_evidence = add_observed_foot_contacts(
                    refreshed_support_evidence, observe_foot_landmarks(source_video), source_pose_payload,
                    alignment.get("cameraGroundPlane", {}).get("normal"),
                    alignment,
                )
            selected.setdefault("settingsOptions", {})[
                "sourceFootSupportEvidence"
            ] = refreshed_support_evidence
    proposed = clip_from_frames(skeleton)
    source = clip_from_frames(raw)
    orientation_metadata: dict[str, Any] = {
        "applied": False,
        "reason": "already_baked_source_guided_articulation",
    }
    existing_constraint = skeleton.get("postBakeArticulationConstraint")
    if (
        isinstance(existing_constraint, dict)
        and existing_constraint.get("strategy")
        == "source_3d_articulation_envelope_constraint"
    ):
        constrained = proposed
        metadata = existing_constraint
    else:
        constrained, metadata = constrain_to_source_articulation_envelope(source, proposed)
    constrained, spike_metadata = suppress_post_ik_anatomical_spikes(constrained)
    constrained, foot_heading_metadata = stabilize_distal_foot_heading(constrained)
    constrained, forefoot_contact_metadata = stabilize_forefoot_ground_contacts(
        constrained,
        refreshed_support_evidence,
    )
    if (
        not metadata.get("applied")
        and not orientation_metadata.get("applied")
        and not foot_heading_metadata.get("applied")
    ):
        return None

    if not backup_path.exists():
        shutil.copy2(skeleton_path, backup_path)
    for frame, constrained_frame in zip(skeleton["frames"], constrained.frames):
        for name, point in constrained_frame.joints.items():
            frame["joints"][name] = [float(value) for value in point]
    skeleton["postBakeArticulationConstraint"] = metadata
    skeleton["postBakeFootHeadingConstraint"] = foot_heading_metadata
    skeleton["postBakeForefootContactConstraint"] = forefoot_contact_metadata
    if refreshed_support_evidence is not None:
        skeleton["sourceFootSupportEvidence"] = refreshed_support_evidence
    skeleton["postBakeAnatomicalSpikeSuppression"] = spike_metadata
    skeleton.pop("postBakeContactSpikeSuppression", None)
    skeleton["postBakeSourceGuidedLegOrientation"] = orientation_metadata
    skeleton_path.write_text(json.dumps(skeleton, indent=2), encoding="utf-8")

    review_path = Path(selected["reviewVideoPath"])
    if render:
        review_backup = review_path.with_suffix(review_path.suffix + ".pre-articulation-fix")
        if review_path.exists() and not review_backup.exists():
            shutil.copy2(review_path, review_backup)
        preview_path = Path(selected["sourcePreviewHtmlPath"])
        refresh_embedded_mesh_renderer(preview_path)
        options = with_fixed_preview_camera_options(dict(selected.get("settingsOptions") or {}))
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = launch_chromium_browser(playwright)
            try:
                page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
                page.goto(preview_path.resolve().as_uri(), wait_until="networkidle")
                page.wait_for_function("() => window.exerciseMotionAutomation != null")
                frame_indices = dense_loop_review_video_frame_indices(skeleton)
                data_urls = render_baked_wear_frames_with_playwright(
                    page,
                    export_payload=skeleton,
                    frame_indices=frame_indices,
                    options=options,
                )
            finally:
                browser.close()
        repeated = repeated_review_frame_data_urls(data_urls, repeats=2)
        fps = parse_review_video_fps(skeleton, frame_count=len(data_urls))
        rendered_path, quality = write_validated_review_video_from_data_urls(
            repeated,
            review_path,
            fps=fps,
        )
        if rendered_path != review_path:
            raise RuntimeError(f"Repair changed review-video format: {rendered_path}")
        if not quality.get("passed"):
            raise RuntimeError(f"Repaired review video failed render validation: {quality}")

    if manifest_path.parent.name == "selected":
        promoted_skeletons = sorted(manifest_path.parent.glob("*_wear_skeleton.json"))
        if len(promoted_skeletons) == 1:
            shutil.copy2(skeleton_path, promoted_skeletons[0])
        if render:
            promoted_previews = sorted(manifest_path.parent.glob("*_selected_preview.webm"))
            if len(promoted_previews) == 1:
                shutil.copy2(review_path, promoted_previews[0])
            for interactive_preview in manifest_path.parent.glob("*_interactive_preview.html"):
                refresh_embedded_mesh_renderer(interactive_preview)

    if refreshed_support_evidence is not None:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "exercise": selected.get("exerciseName"),
        "skeleton": str(skeleton_path),
        "reviewVideo": str(review_path),
        **metadata,
    }


def promote_variant(manifest_path: Path, variant_id: str) -> None:
    manifest = load_json(manifest_path)
    matches = [
        item
        for item in manifest.get("reviewItems") or []
        if isinstance(item, dict)
        and item.get("settingsVariantId") == variant_id
        and int(item.get("loopIndex", -2)) == -1
    ]
    if len(matches) == 1:
        selected = dict(matches[0])
    else:
        current_results = manifest.get("selectedResults") or []
        if not current_results or not isinstance(current_results[0], dict):
            raise ValueError(f"No selected result is available in {manifest_path}")
        selected = dict(current_results[0])
        workspace = Path(selected["candidateWorkspace"])
        skeleton_matches = sorted(
            (workspace / "wear").glob(f"skeleton.baked.full-input.{variant_id}.json")
        )
        video_matches = sorted(
            (workspace / "review").glob(f"full-input.{variant_id}.webm")
        )
        if len(skeleton_matches) != 1 or len(video_matches) != 1:
            raise ValueError(
                f"Expected one retained full-input variant {variant_id!r} in {workspace}"
            )
        selected["skeletonPath"] = str(skeleton_matches[0])
        selected["selectedWearSkeletonPath"] = str(skeleton_matches[0])
        selected["reviewVideoPath"] = str(video_matches[0])
        selected["selectedReviewVideoPath"] = str(video_matches[0])
        selected["settingsVariantId"] = variant_id
        variant_payload = load_json(skeleton_matches[0])
        selected["settingsOptions"] = variant_payload.get("selectedPreviewSettings") or {}
    selected["selectedResultIndex"] = 0
    selected["manualSelectionLabel"] = "Option 1"
    manifest["selectedResultCount"] = 1
    manifest["selectedResults"] = [selected]
    manifest["selected"] = selected
    manifest["selectionStatus"] = "selected"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    exercise_root = manifest_path.parent.parent
    selected_dir = exercise_root / "selected"
    copied_skeletons = sorted(selected_dir.glob("*_wear_skeleton.json"))
    copied_videos = sorted(selected_dir.glob("*_selected_preview.webm"))
    if len(copied_skeletons) != 1 or len(copied_videos) != 1:
        raise ValueError(f"Selected artifact destinations are ambiguous in {selected_dir}")
    shutil.copy2(Path(selected["skeletonPath"]), copied_skeletons[0])
    shutil.copy2(Path(selected["reviewVideoPath"]), copied_videos[0])
    selected_manifest = selected_dir / "selection_manifest.json"
    selected_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair selected movements whose cleanup exceeds raw 3D articulation."
    )
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--exercise")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--promote-variant")
    args = parser.parse_args()
    repaired = []
    selected_items = []
    manifest_paths: list[Path] = []
    for exercise_workspace in sorted(path for path in args.workspace.iterdir() if path.is_dir()):
        promoted_manifest = exercise_workspace / "selected" / "selection_manifest.json"
        bake_manifest = exercise_workspace / "bake" / "selection_manifest.json"
        if promoted_manifest.exists():
            manifest_paths.append(promoted_manifest)
        elif bake_manifest.exists():
            manifest_paths.append(bake_manifest)
    for manifest_path in manifest_paths:
        if args.exercise:
            manifest_name = load_json(manifest_path).get("selectedResults") or []
            selected_name = (
                manifest_name[0].get("exerciseName")
                if manifest_name and isinstance(manifest_name[0], dict)
                else None
            )
            if selected_name != args.exercise:
                continue
        if args.promote_variant:
            promote_variant(manifest_path, args.promote_variant)
            print(f"Promoted {args.promote_variant}: {args.exercise or manifest_path.parent.parent.name}")
            continue
        result = None if args.report_only else repair_manifest(
            manifest_path,
            render=not args.no_render,
        )
        if result:
            repaired.append(result)
            print(
                f"Repaired: {result['exercise']} "
                f"({result['constrainedSampleCount']} samples, "
                f"max {result['maximumPreventedExcessDegrees']:.2f} deg)"
            )
        manifest = load_json(manifest_path)
        selected_results = manifest.get("selectedResults")
        if isinstance(selected_results, list) and selected_results and isinstance(selected_results[0], dict):
            selected = selected_results[0]
            exercise_id = selected.get("exerciseId")
            if not exercise_id:
                selected_workspace = selected.get("candidateWorkspace")
                for candidate_result in manifest.get("candidateResults") or []:
                    if (
                        isinstance(candidate_result, dict)
                        and candidate_result.get("candidateWorkspace") == selected_workspace
                    ):
                        exercise_id = candidate_result.get("exerciseId")
                        break
            selected_items.append(
                {
                    "exerciseId": exercise_id,
                    "exerciseName": selected.get("exerciseName"),
                    "status": "completed",
                    "workspace": str(manifest_path.parent.parent),
                    "selectedWearSkeletonPath": selected.get("skeletonPath"),
                }
            )
    if args.report:
        selected_items = []
        for selected_manifest_path in sorted(args.workspace.glob("*/selected/selection_manifest.json")):
            selected_manifest = load_json(selected_manifest_path)
            selected_results = selected_manifest.get("selectedResults") or []
            if not selected_results or not isinstance(selected_results[0], dict):
                continue
            selected = selected_results[0]
            exercise_id = None
            selected_workspace = selected.get("candidateWorkspace")
            for candidate_result in selected_manifest.get("candidateResults") or []:
                if (
                    isinstance(candidate_result, dict)
                    and candidate_result.get("candidateWorkspace") == selected_workspace
                ):
                    exercise_id = candidate_result.get("exerciseId")
                    break
            copied_skeletons = sorted(selected_manifest_path.parent.glob("*_wear_skeleton.json"))
            if len(copied_skeletons) != 1:
                continue
            selected_items.append(
                {
                    "exerciseId": exercise_id,
                    "exerciseName": selected.get("exerciseName"),
                    "status": "completed",
                    "workspace": str(selected_manifest_path.parent.parent),
                    "selectedWearSkeletonPath": str(copied_skeletons[0].resolve()),
                }
            )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "workspaceRoot": str(args.workspace.resolve()),
                    "results": selected_items,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    print(json.dumps({"repairedCount": len(repaired), "repaired": repaired}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
