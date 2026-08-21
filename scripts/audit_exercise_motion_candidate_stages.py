from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from exercise_motion_pkg.bake_and_rank import (
    bake_preview_time_range_with_playwright,
    build_preview_bake_base_options,
    compute_kinematic_plausibility_metrics,
    compute_motion_strength_metrics,
    evaluate_baked_motion_gate,
    evaluate_raw_wham_motion_gate,
    materialized_output_acceptance_metrics,
    ranking_from_manifest,
    review_item_from_manifest,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.pose_fidelity import source_to_motion_pose_fidelity_metrics
from exercise_motion_pkg.preview import ensure_three_module_asset, write_preview_html
from exercise_motion_pkg.structural_refinement import refine_motion_clip_structurally


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def coordinate_range(payload: dict[str, Any], *, field: str, joint: str) -> list[float] | None:
    points: list[list[float]] = []
    for frame in payload.get("frames", []):
        joints = frame.get(field)
        if not isinstance(joints, dict):
            continue
        point = joints.get(joint)
        if isinstance(point, list) and len(point) >= 3:
            points.append([float(point[0]), float(point[1]), float(point[2])])
    if len(points) < 2:
        return None
    return [max(point[axis] for point in points) - min(point[axis] for point in points) for axis in range(3)]


def baked_root_preservation(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    source_range = coordinate_range(payload, field="sourceJoints", joint="pelvis")
    output_range = coordinate_range(payload, field="joints", joint="pelvis")
    settings = payload.get("selectedPreviewSettings") or {}
    return {
        "fixedRoot": settings.get("fixedRoot"),
        "sourcePelvisRange": source_range,
        "outputPelvisRange": output_range,
        "rootMotionCaptureByAxis": [
            (output / source if source > 1e-8 else None)
            for source, output in zip(source_range or [], output_range or [])
        ],
    }


def discover_source_references(candidate_dir: Path) -> list[Path]:
    exact = candidate_dir / "segment_detection" / "exact_source_pose_reference.json"
    candidates = sorted(
        candidate_dir.glob(
            "segment_detection/pre_wham_source_candidates/deterministic_confirmation/"
            "*/exact_source_pose_reference.json"
        )
    )
    return ([exact] if exact.exists() else []) + [path for path in candidates if path != exact]


def structural_transactions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refinement = payload.get("metadata", {}).get("structuralRefinement", {})
    if not isinstance(refinement, dict):
        return []
    transactions: list[dict[str, Any]] = []
    for key, value in refinement.items():
        if not isinstance(value, dict) or not isinstance(value.get("transaction"), dict):
            continue
        transactions.append({"component": key, **value["transaction"]})
    return transactions


def source_fidelity(path: Path, source_reference: Path | None) -> dict[str, Any]:
    if source_reference is None or not path.exists():
        return {"available": False}
    source_document = load_json(source_reference)
    source_payload = source_document.get("pose", source_document)
    return source_to_motion_pose_fidelity_metrics(source_payload, load_json(path))


def first_failure_owner(stages: dict[str, Any]) -> dict[str, Any] | None:
    for stage_name in ("sourceConfirmation", "rawWham", "cleanup", "bake", "finalValidation"):
        stage = stages.get(stage_name, {})
        if stage.get("available") is False:
            return {"stage": stage_name, "reason": "required_artifact_unavailable"}
        if stage.get("passed") is False:
            return {
                "stage": stage_name,
                "reason": "stage_gate_failed",
                "rejectionReasons": stage.get("rejectionReasons", []),
            }
    return None


def ranking_validation_summary(ranking: dict[str, Any] | None) -> dict[str, Any]:
    rows = ranking.get("rankings", []) if isinstance(ranking, dict) else []
    results: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        payload = row.get("ranking", {}).get("payload", {}) if isinstance(row, dict) else {}
        final_validation = payload.get("finalOutputValidation", {})
        results.append(
            {
                "passed": final_validation.get("passed"),
                "rejectionReasons": final_validation.get("rejectionReasons", []),
                "materializedValidationStatus": payload.get("materializedValidationStatus"),
            }
        )
    return {
        "available": any(result.get("passed") is not None for result in results),
        "passed": (
            any(result.get("passed") is True for result in results)
            if any(result.get("passed") is not None for result in results)
            else None
        ),
        "rejectionReasons": sorted(
            {
                str(reason)
                for result in results
                for reason in result.get("rejectionReasons", [])
            }
        ),
        "results": results,
    }


def deterministic_final_validation(
    candidate_dir: Path,
    baked_paths: list[Path],
    source_reference: Path | None,
) -> list[dict[str, Any]]:
    selection_path = candidate_dir.parent / "selection_manifest.json"
    selection = load_json(selection_path) if selection_path.exists() else {}
    candidate_result = next(
        (
            result
            for result in selection.get("candidateResults", [])
            if Path(str(result.get("candidateWorkspace") or ".")).resolve()
            == candidate_dir.resolve()
        ),
        {},
    )
    candidate = candidate_result.get("candidate", {})
    contract = candidate.get("exerciseMotionContract") if isinstance(candidate, dict) else None
    source_document = load_json(source_reference) if source_reference else None
    source_pose = source_document.get("pose", source_document) if source_document else None
    results: list[dict[str, Any]] = []
    for baked_path in baked_paths:
        baked = load_json(baked_path)
        artifact_name = baked_path.name
        artifact_slug = (
            artifact_name[len("skeleton.baked.") : -len(".json")]
            if artifact_name.startswith("skeleton.baked.") and artifact_name.endswith(".json")
            else baked_path.stem
        )
        inferred_review_path = baked_path.parent.parent / "review" / f"{artifact_slug}.webm"
        # Materialized validation owns both the skeleton and its rendered
        # review video. Treat an isolated skeleton-only bake as an unavailable
        # final-validation stage instead of manufacturing an "unreadable"
        # rejection for a file that was never rendered.
        if not inferred_review_path.exists():
            continue
        item = review_item_from_manifest(
            {
                "exerciseIndex": candidate_result.get("exerciseIndex", 0),
                "candidateRank": candidate_result.get("candidateRank", 0),
                "loopIndex": -1,
                "exerciseName": candidate_result.get("exerciseName", candidate_dir.name),
                "candidateTitle": candidate.get("title", "") if isinstance(candidate, dict) else "",
                "candidateWorkspace": str(candidate_dir),
                "previewHtmlPath": str(candidate_dir / "preview" / "motion_preview.html"),
                "skeletonPath": str(baked_path),
                "reviewVideoPath": str(inferred_review_path),
                "durationSec": baked.get("durationSec", 0.0),
                "candidate": candidate,
                "settingsOptions": baked.get("selectedPreviewSettings", {}),
            }
        )
        ranking = ranking_from_manifest(
            {
                "score": 1.0,
                "reasons": ["isolated_deterministic_final_validation"],
                "payload": {"exerciseMotionContract": contract} if isinstance(contract, dict) else {},
            }
        )
        metrics = materialized_output_acceptance_metrics(
            item,
            ranking,
            source_pose_reference=source_pose,
        )
        results.append(
            {
                "path": str(baked_path),
                "passed": metrics.get("passed"),
                "rejectionReasons": metrics.get("rejectionReasons", []),
                "metrics": metrics,
            }
        )
    return results


def audit_candidate(
    candidate_dir: Path,
    *,
    raw_path_override: Path | None = None,
    cleaned_path_override: Path | None = None,
    baked_path_overrides: list[Path] | None = None,
) -> dict[str, Any]:
    raw_path = raw_path_override or candidate_dir / "raw" / "motion.raw.json"
    cleaned_path = cleaned_path_override or candidate_dir / "cleaned" / "motion.cleaned.json"
    source_references = discover_source_references(candidate_dir)
    source_phase_paths = sorted(
        candidate_dir.glob(
            "segment_detection/pre_wham_source_candidates/deterministic_confirmation/"
            "*/exact_source_phase_validation.json"
        )
    )
    baked_paths = baked_path_overrides or sorted(
        (candidate_dir / "wear").glob("skeleton.baked.*.json")
    )

    report: dict[str, Any] = {
        "schemaVersion": 1,
        "candidateDirectory": str(candidate_dir.resolve()),
        "stages": {},
    }
    source_phase = [load_json(path) for path in source_phase_paths]
    source_phase_summaries = []
    for item in source_phase:
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        source_phase_summaries.append(
            {
                "passed": item.get("passed", metrics.get("passed")),
                "reason": item.get("reason", metrics.get("reason")),
                "rejectionReasons": item.get(
                    "rejectionReasons", metrics.get("rejectionReasons", [])
                ),
            }
        )
    report["stages"]["sourceConfirmation"] = {
        "available": bool(source_phase),
        "passed": any(item.get("passed") is True for item in source_phase_summaries),
        "artifacts": [str(path) for path in source_phase_paths],
        "results": source_phase_summaries,
    }

    raw_gate = (
        evaluate_raw_wham_motion_gate(
            raw_path,
            source_pose_reference_path=source_references[0] if source_references else None,
        )
        if raw_path.exists()
        else {"passed": False, "rejectionReasons": ["raw_motion_missing"]}
    )
    report["stages"]["rawWham"] = raw_gate

    cleanup_source_fidelity = source_fidelity(
        cleaned_path,
        source_references[0] if source_references else None,
    )
    cleanup_kinematic = (
        compute_kinematic_plausibility_metrics(cleaned_path)
        if cleaned_path.exists()
        else None
    )
    report["stages"]["cleanup"] = (
        {
            "available": True,
            "passed": bool(
                cleanup_kinematic
                and not cleanup_kinematic.get("severeArtifact")
                and (
                    cleanup_source_fidelity.get("available") is not True
                    or not any(
                        transaction.get("accepted") is False
                        and transaction.get("reason")
                        != "protected_source_fidelity_degraded"
                        for transaction in structural_transactions(load_json(cleaned_path))
                    )
                )
            ),
            "rejectionReasons": (
                ["cleanup_kinematic_artifact"]
                if cleanup_kinematic and cleanup_kinematic.get("severeArtifact")
                else []
            ),
            "kinematic": cleanup_kinematic,
            "motionStrength": compute_motion_strength_metrics(cleaned_path),
            "sourcePoseFidelity": cleanup_source_fidelity,
            "structuralTransactions": structural_transactions(load_json(cleaned_path)),
        }
        if cleaned_path.exists()
        else {"available": False, "rejectionReasons": ["cleaned_motion_missing"]}
    )

    baked_results = []
    for path in baked_paths:
        baked_results.append(
            {
                "path": str(path),
                "motionGate": evaluate_baked_motion_gate(path),
                "rootPreservation": baked_root_preservation(path),
            }
        )
    report["stages"]["bake"] = {
        "available": bool(baked_results),
        "passed": any(result["motionGate"].get("passed") is True for result in baked_results),
        "variants": baked_results,
    }

    deterministic_final_results = deterministic_final_validation(
        candidate_dir,
        baked_paths,
        source_references[0] if source_references else None,
    )
    ranking_path = candidate_dir / "review" / "ranking.json"
    ranking = load_json(ranking_path) if ranking_path.exists() else None
    validation_summary = ranking_validation_summary(ranking)
    if deterministic_final_results:
        validation_summary = {
            "available": True,
            "passed": any(result.get("passed") is True for result in deterministic_final_results),
            "rejectionReasons": sorted(
                {
                    str(reason)
                    for result in deterministic_final_results
                    for reason in result.get("rejectionReasons", [])
                }
            ),
            "results": deterministic_final_results,
        }
    report["stages"]["finalValidation"] = {
        "rankingArtifactAvailable": ranking_path.exists(),
        **validation_summary,
        "artifact": str(ranking_path) if ranking_path.exists() else None,
        "topLevelKeys": sorted(ranking) if isinstance(ranking, dict) else [],
    }
    report["failureOwner"] = first_failure_owner(report["stages"])
    return report


def rerun_structural_refinement(candidate_dir: Path, cleaned_path: Path, output: Path) -> None:
    document = load_json(cleaned_path)
    refinement = document.get("metadata", {}).get("structuralRefinement", {})
    input_frames = refinement.get("inputFrames") if isinstance(refinement, dict) else None
    if not isinstance(input_frames, list) or not input_frames:
        raise ValueError("cleaned artifact has no retained structural-refinement inputFrames")
    references = discover_source_references(candidate_dir)
    source_document = load_json(references[0]) if references else None
    source_pose = source_document.get("pose", source_document) if source_document else None
    metadata = dict(document.get("metadata", {}))
    metadata.pop("structuralRefinement", None)
    clip = MotionClip(
        fps=float(document["fps"]),
        joint_names=[str(name) for name in document["jointNames"]],
        frames=[
            MotionFrame(
                time_sec=float(frame["timeSec"]),
                joints={name: tuple(point) for name, point in frame["joints"].items()},
            )
            for frame in input_frames
        ],
        source=document.get("source", {}),
        metadata=metadata,
    )
    save_motion_json(
        output,
        refine_motion_clip_structurally(clip, source_pose_payload=source_pose),
    )


def rerun_isolated_bake(
    candidate_dir: Path,
    cleaned_path: Path,
    output_dir: Path,
    *,
    auto_world_alignment: bool | None = None,
    lock_planted_feet: bool | None = None,
) -> Path:
    """Bake and render one retained cleaned clip without rerunning upstream stages."""
    clip = load_motion_json(cleaned_path)
    preview_path = output_dir / "preview" / "motion_preview.html"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    write_preview_html(
        preview_path,
        clip,
        title="Isolated retained cleanup bake",
        three_module_path=ensure_three_module_asset(),
    )
    options = build_preview_bake_base_options(motion_tuning_enabled=True)
    if auto_world_alignment is not None:
        options["autoWorldAlignment"] = auto_world_alignment
    source_phase_path = candidate_dir / "segment_detection" / "exact_source_phase_validation.json"
    if not source_phase_path.exists():
        source_phase_path = next(
            iter(
                sorted(
                    candidate_dir.glob(
                        "segment_detection/pre_wham_source_candidates/"
                        "deterministic_confirmation/*/exact_source_phase_validation.json"
                    )
                )
            ),
            source_phase_path,
        )
    if source_phase_path.exists():
        source_phase = load_json(source_phase_path)
        source_metrics = source_phase.get("metrics", source_phase)
        source_support = (
            source_metrics.get("sourceFootSupportEvidence")
            if isinstance(source_metrics, dict)
            else None
        )
        if isinstance(source_support, dict):
            options["sourceFootSupportEvidence"] = source_support
            feet = source_support.get("feet")
            options["lockPlantedFeet"] = bool(
                isinstance(feet, dict)
                and any(
                    isinstance(feet.get(side), dict)
                    and bool(feet[side].get("continuousSupport"))
                    for side in ("left", "right")
                )
            )
    if lock_planted_feet is not None:
        options["lockPlantedFeet"] = lock_planted_feet
    artifact = bake_preview_time_range_with_playwright(
        preview_html_path=preview_path,
        start_seconds=0.0,
        end_seconds=clip.duration_sec,
        options=options,
        candidate_workspace=output_dir,
        review_frames=24,
        artifact_id="isolated-retained-cleanup",
        artifact_label="Isolated retained cleanup",
    )
    return artifact.skeleton_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit retained exercise-motion artifacts stage by stage without rerunning expensive stages."
    )
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-motion", type=Path)
    parser.add_argument("--cleaned-motion", type=Path)
    parser.add_argument("--baked-skeleton", type=Path, action="append", default=[])
    parser.add_argument("--rerun-structural-refinement-out", type=Path)
    parser.add_argument("--rerun-bake-out", type=Path)
    parser.add_argument(
        "--bake-auto-world-alignment",
        choices=("on", "off"),
        help="Override only auto world alignment for an isolated bake.",
    )
    parser.add_argument(
        "--bake-lock-planted-feet",
        choices=("on", "off"),
        help="Override only planted-foot locking for an isolated bake.",
    )
    parser.add_argument(
        "--stage",
        choices=("sourceConfirmation", "rawWham", "cleanup", "bake", "finalValidation"),
        help="Print and save only one stage after computing the complete owner audit.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only stage pass states and the first failure owner.",
    )
    args = parser.parse_args()

    candidate_dir = args.candidate_dir.resolve()
    if args.rerun_structural_refinement_out is not None:
        cleaned_input = args.cleaned_motion or candidate_dir / "cleaned" / "motion.cleaned.json"
        rerun_structural_refinement(
            candidate_dir,
            cleaned_input.resolve(),
            args.rerun_structural_refinement_out.resolve(),
        )
    baked_overrides = [path.resolve() for path in args.baked_skeleton]
    if args.rerun_bake_out is not None:
        cleaned_for_bake = (
            args.rerun_structural_refinement_out.resolve()
            if args.rerun_structural_refinement_out is not None
            else args.cleaned_motion.resolve()
            if args.cleaned_motion
            else candidate_dir / "cleaned" / "motion.cleaned.json"
        )
        baked_overrides.append(
            rerun_isolated_bake(
                candidate_dir,
                cleaned_for_bake,
                args.rerun_bake_out.resolve(),
                auto_world_alignment=(
                    args.bake_auto_world_alignment == "on"
                    if args.bake_auto_world_alignment is not None
                    else None
                ),
                lock_planted_feet=(
                    args.bake_lock_planted_feet == "on"
                    if args.bake_lock_planted_feet is not None
                    else None
                ),
            )
        )
    report = audit_candidate(
        candidate_dir,
        raw_path_override=args.raw_motion.resolve() if args.raw_motion else None,
        cleaned_path_override=(
            args.rerun_structural_refinement_out.resolve()
            if args.rerun_structural_refinement_out is not None
            else args.cleaned_motion.resolve() if args.cleaned_motion else None
        ),
        baked_path_overrides=baked_overrides or None,
    )
    full_report = report
    if args.stage:
        report = {
            "schemaVersion": full_report["schemaVersion"],
            "candidateDirectory": full_report["candidateDirectory"],
            "stages": {args.stage: full_report["stages"][args.stage]},
            "failureOwner": (
                full_report["failureOwner"]
                if isinstance(full_report.get("failureOwner"), dict)
                and full_report["failureOwner"].get("stage") == args.stage
                else None
            ),
        }
    summary = {
        "candidateDirectory": full_report["candidateDirectory"],
        "stageStatus": {
            name: {
                "available": stage.get("available", True),
                "passed": stage.get("passed"),
                "rejectionReasons": stage.get("rejectionReasons", []),
            }
            for name, stage in full_report["stages"].items()
        },
        "failureOwner": full_report["failureOwner"],
    }
    rendered = json.dumps(summary if args.summary_only else report, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
