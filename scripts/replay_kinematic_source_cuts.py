"""Replay kinematic source-cut proposals against persisted bake payloads.

Reads ``dominantPoseSamples`` and contracts from exercise-library selection
manifests, proposes cuts with no YOLO/VLM/WHAM, and compares them to the
pre-WHAM VLM window in ``segment_selection.json`` when one exists.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from exercise_motion_pkg.kinematic_cut import propose_source_cut


def first_float(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def iou(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    overlap = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    union = max(left_end, right_end) - min(left_start, right_start)
    return overlap / union if union > 1e-9 else 0.0


def contains(outer_start: float, outer_end: float, inner_start: float, inner_end: float, *, pad: float = 0.5) -> bool:
    return outer_start - pad <= inner_start and inner_end <= outer_end + pad


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def original_window_from_result(result: dict[str, Any]) -> tuple[float, float] | None:
    source_window = result.get("sourceWindow")
    if isinstance(source_window, dict):
        start = first_float(source_window.get("startSeconds"))
        end = first_float(source_window.get("endSeconds"))
        if start is not None and end is not None and end > start:
            return start, end
    candidate = result.get("candidate")
    payload = candidate.get("visionPayload") if isinstance(candidate, dict) else None
    pose = payload.get("posePrefilter") if isinstance(payload, dict) else None
    if isinstance(pose, dict):
        start = first_float(pose.get("bestChunkStartSeconds"), payload.get("bestChunkStartSeconds") if isinstance(payload, dict) else None)
        end = first_float(pose.get("bestChunkEndSeconds"), payload.get("bestChunkEndSeconds") if isinstance(payload, dict) else None)
        if start is not None and end is not None and end > start:
            return start, end
    return None


def contract_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    candidate = result.get("candidate")
    if not isinstance(candidate, dict):
        return None
    for source in (
        candidate.get("exerciseMotionContract"),
        (candidate.get("visionPayload") or {}).get("exerciseMotionContract") if isinstance(candidate.get("visionPayload"), dict) else None,
    ):
        if isinstance(source, dict) and (source.get("completionMode") or source.get("movementType")):
            return source
    return None


def samples_from_result(result: dict[str, Any]) -> list[dict[str, Any]] | None:
    candidate = result.get("candidate")
    payload = candidate.get("visionPayload") if isinstance(candidate, dict) else None
    pose = payload.get("posePrefilter") if isinstance(payload, dict) else None
    samples = pose.get("dominantPoseSamples") if isinstance(pose, dict) else None
    if isinstance(samples, list) and samples:
        return [sample for sample in samples if isinstance(sample, dict)]
    return None


def vlm_window_from_workspace(workspace: Path) -> tuple[float, float, float] | None:
    segment_path = workspace / "segment_detection" / "segment_selection.json"
    payload = load_json(segment_path)
    if payload is None:
        return None
    ranking = payload.get("sourceCutRanking")
    score = first_float(ranking.get("score") if isinstance(ranking, dict) else None) or 0.0
    selected = payload.get("selectedSpanInOriginalSource")
    if isinstance(selected, dict):
        start = first_float(selected.get("startSeconds"))
        end = first_float(selected.get("endSeconds"))
        if start is not None and end is not None and end > start:
            return start, end, score
    if isinstance(ranking, dict) and isinstance(ranking.get("payload"), dict):
        ranking_payload = ranking["payload"]
        start = first_float(
            ranking_payload.get("selected_section_start_seconds"),
            ranking_payload.get("selectedSectionStartSeconds"),
        )
        end = first_float(
            ranking_payload.get("selected_section_end_seconds"),
            ranking_payload.get("selectedSectionEndSeconds"),
        )
        window = payload.get("candidateSourceWindow") if isinstance(payload.get("candidateSourceWindow"), dict) else {}
        offset = first_float(window.get("startSecondsInOriginalSource")) or 0.0
        window_start = first_float(window.get("startSeconds")) or 0.0
        if start is not None and end is not None and end > start:
            # Ranking times may already be original-source seconds.
            if offset and start + 1e-3 < offset:
                start += offset - window_start
                end += offset - window_start
            return start, end, score
    return None


def classify_row(
    *,
    proposal: tuple[float, float] | None,
    vlm: tuple[float, float, float] | None,
) -> str:
    if proposal is None:
        return "fallback_no_proposal" if vlm is None or vlm[2] <= 0.0 else "miss_vlm_approved"
    if vlm is None:
        return "proposed_no_vlm_window"
    vlm_start, vlm_end, vlm_score = vlm
    if vlm_score <= 0.0:
        return "proposed_vlm_failed"
    if contains(*proposal, vlm_start, vlm_end):
        return "covers_vlm"
    if contains(vlm_start, vlm_end, *proposal):
        return "inside_vlm"
    overlap = iou(*proposal, vlm_start, vlm_end)
    if overlap >= 0.5:
        return "overlap_vlm"
    return "disagrees_vlm"


def iter_manifests(library_root: Path) -> list[Path]:
    manifests: list[Path] = []
    seen_exercises: set[str] = set()
    for role in ("bake", "selected", "manual-review"):
        for path in sorted(library_root.glob(f"*/{role}/selection_manifest.json")):
            exercise = path.parent.parent.name
            if role != "bake" and exercise in seen_exercises:
                continue
            seen_exercises.add(exercise)
            manifests.append(path)
    return manifests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("build/exercise_motion/exercise-library"),
    )
    parser.add_argument("--max-proposals", type=int, default=2)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for manifest_path in iter_manifests(args.library_root):
        manifest = load_json(manifest_path)
        if manifest is None:
            continue
        exercise = manifest_path.parent.parent.name
        selection_status = str(manifest.get("selectionStatus") or "")
        for result in manifest.get("candidateResults") or []:
            if not isinstance(result, dict):
                continue
            samples = samples_from_result(result)
            contract = contract_from_result(result)
            parent = original_window_from_result(result)
            if not samples or parent is None:
                continue
            workspace_raw = result.get("candidateWorkspace")
            workspace = Path(str(workspace_raw)) if workspace_raw else None
            vlm = vlm_window_from_workspace(workspace) if workspace and workspace.exists() else None
            proposals = propose_source_cut(
                contract=contract,
                dominant_pose_samples=samples,
                max_proposals=args.max_proposals,
                span_start_seconds=parent[0],
                span_end_seconds=parent[1],
            )
            top = proposals[0] if proposals else None
            proposal_span = (top.start_seconds, top.end_seconds) if top is not None else None
            label = classify_row(proposal=proposal_span, vlm=vlm)
            expands = bool(
                proposal_span
                and (proposal_span[0] < parent[0] - 0.15 or proposal_span[1] > parent[1] + 0.15)
            )
            rows.append(
                {
                    "exercise": exercise,
                    "selectionStatus": selection_status,
                    "candidateStatus": str(result.get("status") or ""),
                    "completionMode": str((contract or {}).get("completionMode") or ""),
                    "movementType": str((contract or {}).get("movementType") or ""),
                    "sampleCount": len(samples),
                    "parent": parent,
                    "proposal": proposal_span,
                    "policy": top.policy if top is not None else None,
                    "confidence": round(top.confidence, 3) if top is not None else None,
                    "vlm": (vlm[0], vlm[1]) if vlm is not None else None,
                    "vlmScore": vlm[2] if vlm is not None else None,
                    "iou": round(iou(*proposal_span, *vlm[:2]), 3) if proposal_span and vlm else None,
                    "expandsParent": expands,
                    "label": label,
                }
            )

    counts = Counter(row["label"] for row in rows)
    proposed = [row for row in rows if row["proposal"] is not None]
    vlm_pass = [row for row in rows if row["vlmScore"] is not None and row["vlmScore"] > 0.0]
    agreement = [row for row in vlm_pass if row["label"] in {"covers_vlm", "inside_vlm", "overlap_vlm"}]
    print(f"candidates_with_pose {len(rows)}")
    print(f"kinematic_proposed {len(proposed)} ({(100.0 * len(proposed) / len(rows)):.0f}%)" if rows else "kinematic_proposed 0")
    print(f"vlm_approved_windows {len(vlm_pass)}")
    if vlm_pass:
        print(f"agreement_with_vlm {len(agreement)}/{len(vlm_pass)} ({(100.0 * len(agreement) / len(vlm_pass)):.0f}%)")
    print("labels:")
    for label, count in counts.most_common():
        print(f"  {label}: {count}")

    ious = [row["iou"] for row in vlm_pass if isinstance(row["iou"], float)]
    if ious:
        print(
            "vlm_iou median={:.2f} mean={:.2f}".format(
                statistics.median(ious),
                statistics.mean(ious),
            )
        )

    print("\nexpands_parent (ab-wheel class):")
    expanded = [row for row in rows if row["expandsParent"]]
    if not expanded:
        print("  none")
    for row in expanded[:20]:
        print(
            "  {exercise} parent={parent[0]:.2f}-{parent[1]:.2f} "
            "kinematic={proposal[0]:.2f}-{proposal[1]:.2f} "
            "vlm={vlm} status={candidateStatus}".format(**row)
        )

    print("\nvlm_approved disagreements:")
    misses = [row for row in rows if row["label"] == "disagrees_vlm"]
    if not misses:
        print("  none")
    for row in misses[:15]:
        print(
            "  {exercise} kinematic={proposal} vlm={vlm} iou={iou} "
            "mode={completionMode}".format(**row)
        )

    print("\nselected exercises:")
    selected_rows = [row for row in rows if row["selectionStatus"] == "selected"]
    selected_counts = Counter(row["label"] for row in selected_rows)
    for label, count in selected_counts.most_common():
        print(f"  {label}: {count}")

    focus = [row for row in rows if "ab-wheel" in row["exercise"]]
    if focus:
        print("\nab-wheel-rollout:")
        for row in focus:
            print(
                "  parent={parent} kinematic={proposal} vlm={vlm} "
                "label={label} expands={expandsParent} policy={policy}".format(**row)
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
