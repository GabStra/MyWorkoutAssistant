"""Refresh retained artifacts without rerunning discovery or GPU inference.

Work in a separate output directory. Old approvals are not new visual verdicts;
the audit records deterministic failures and the need for visual review.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import time
import hashlib

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.acceptance import decide_acceptance, invalidate_retained_acceptance
from exercise_motion_pkg.foot_contact_observation import add_observed_foot_contacts, observe_foot_landmarks
from exercise_motion_pkg.preview import write_baked_preview_html
from exercise_motion_pkg.stage_cache import render_with_cpu_slot


def refresh_artifact(selected: Path, output: Path, *, render: bool) -> dict:
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite an earlier refresh: {output}")
    shutil.copytree(selected, output)
    invalidate_retained_acceptance(output, "artifact_refresh_requires_revalidation")
    skeleton = next(output.glob("*_wear_skeleton.json"))
    payload = json.loads(skeleton.read_text())
    original = copy.deepcopy(payload)
    evidence = payload.get("sourceFootSupportEvidence")
    reference_path = output / "segment_detection/exact_source_pose_reference.json"
    source_video = next(output.glob("*_selected_input.mp4"), None)
    source_pose = bake.load_verified_source_pose_reference(reference_path, source_video)
    reference_rebuilt = False
    if source_pose is None and source_video is not None:
        manifest = json.loads((output / "selection_manifest.json").read_text())
        selected_ranking = (manifest.get("selected") or {}).get("ranking") or {}
        observed = bake.source_video_phase_completeness_metrics(
            source_video_path=source_video, exercise_name=str(payload.get("title") or selected.parent.name),
            ranking_payload=selected_ranking.get("payload") or {}, include_pose_reference=True,
        )
        source_pose = (observed or {}).get("_sourcePoseReference")
        if source_pose is not None:
            reference_path.parent.mkdir(parents=True, exist_ok=True)
            reference_path.write_text(json.dumps({"schemaVersion": 1,
                "sourceVideoSha256": hashlib.sha256(source_video.read_bytes()).hexdigest(), "pose": source_pose}))
            reference_rebuilt = True
    if isinstance(evidence, dict) and source_pose and source_video:
        evidence = add_observed_foot_contacts(evidence, observe_foot_landmarks(source_video), source_pose)
        payload["sourceFootSupportEvidence"] = evidence
        previous = payload.get("sourceContactSequenceCorrection", {})
        translations = previous.get("translationTrack", [])
        if previous.get("reason") == "source_contact_rigid_sequence_correction" and len(translations) == len(payload["frames"]):
            # Undo this specific rigid pass before recomputing its anchors.
            # Do not subtract unknown IK corrections or change joint angles.
            for frame, translation in zip(payload["frames"], translations):
                for name, point in frame["joints"].items():
                    frame["joints"][name] = [point[i] - translation[i] for i in range(3)]
                if isinstance(frame.get("rootTranslationApplied"), list):
                    frame["rootTranslationApplied"] = [frame["rootTranslationApplied"][i] - translation[i] for i in range(3)]
            payload, _ = bake.apply_source_contact_sequence_correction(payload, evidence)
    kinematics = bake.compute_kinematic_plausibility_metrics_from_payload(payload)
    support = bake.source_confirmed_support_stationarity_metrics(payload, evidence)
    fidelity = bake.materialized_source_pose_fidelity_metrics(
        source_pose_payload=source_pose, output_motion_payload=payload)
    reasons = list(kinematics["artifactReasons"]) + support.get("rejectionReasons", []) + fidelity.get("rejectionReasons", [])
    decision = decide_acceptance(
        {"kinematics": kinematics, "support": support, "fidelity": fidelity}, {},
        deterministic_rejections=reasons, review_rejections=[],
    )
    skeleton.write_text(json.dumps(payload, indent=2))
    prefix = skeleton.name.removesuffix("_wear_skeleton.json")
    preview = output / f"{prefix}_interactive_preview.html"
    write_baked_preview_html(preview, payload, three_module_path=output / "three.module.0.169.0.js")
    render_seconds = 0.0
    if render:
        render_started = time.perf_counter()
        with bake.browser_session(bake.launch_chromium_browser) as browser:
            page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
            page.goto(preview.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_function("() => window.exerciseMotionAutomation != null")
            indices = bake.dense_loop_review_video_frame_indices(payload)
            urls = bake.render_baked_wear_frames_with_playwright(
                page, export_payload=payload, frame_indices=indices, options={})
            _, quality = bake.write_validated_review_video_from_data_urls(
                urls, output / f"{prefix}_selected_preview.webm",
                fps=bake.parse_review_video_fps(payload, frame_count=len(urls)))
            if not quality["passed"]:
                raise RuntimeError(f"Refreshed video is unreadable: {quality}")
            page.close()
        render_seconds = time.perf_counter() - render_started
    result = {"source": str(selected.resolve()), "output": str(output.resolve()),
              "status": "rejected" if reasons else "needs_visual_review", "reasons": reasons,
              "acceptanceDecision": decision.to_dict(),
              "kinematics": kinematics, "support": support, "sourcePoseFidelity": fidelity,
              "sourcePoseReferenceAvailable": source_pose is not None,
              "sourcePoseReferenceRebuilt": reference_rebuilt,
              "jointPositionsChanged": original["frames"] != payload["frames"],
              "videoRegenerated": render, "renderSeconds": render_seconds,
              "totalSeconds": time.perf_counter() - started}
    (output / "renderer_refresh_audit.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercises", nargs="*", help="Workspace slugs; otherwise audit checkpoint successes")
    parser.add_argument("--render", action="store_true", help="Regenerate videos with the production renderer")
    args = parser.parse_args()
    if args.output.resolve() == args.workspace.resolve() or args.workspace.resolve() in args.output.resolve().parents:
        parser.error("Use an output directory outside the active workspace")
    if args.exercises:
        slugs = args.exercises
    else:
        checkpoint = json.loads((args.workspace / "workout_motion_generation_checkpoint.json").read_text(encoding="utf-8-sig"))
        slugs = [bake.slugify(item["exerciseName"]) for item in checkpoint["exercises"] if item["status"] == "completed"]
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for slug in slugs:
        try:
            result = render_with_cpu_slot(lambda: refresh_artifact(
                args.workspace / slug / "selected", args.output / slug, render=args.render))
        except Exception as exc:
            result = {"exercise": slug, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        (args.output / "audit.json").write_text(json.dumps(results, indent=2))
        print(f"{slug}: {result['status']}", flush=True)


if __name__ == "__main__":
    main()
