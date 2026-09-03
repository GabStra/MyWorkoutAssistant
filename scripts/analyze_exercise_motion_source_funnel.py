from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exercise_motion_pkg.source_outcomes import candidate_result_is_accepted


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def selection_manifest_paths(inputs: Iterable[Path]) -> list[Path]:
    paths: set[Path] = set()
    for input_path in inputs:
        resolved = input_path.expanduser().resolve()
        if resolved.is_dir():
            paths.update(resolved.rglob("selection_manifest.json"))
        elif resolved.name == "selection_manifest.json":
            paths.add(resolved)
        else:
            raise ValueError(f"Expected a selection manifest or directory: {resolved}")
    return sorted(paths)


def manifest_first_candidate(manifest: dict[str, Any]) -> dict[str, Any] | None:
    timings = manifest.get("timings") if isinstance(manifest.get("timings"), dict) else {}
    funnel = timings.get("sourceFunnel") if isinstance(timings.get("sourceFunnel"), dict) else {}
    first = funnel.get("firstCandidate")
    if isinstance(first, dict):
        return first
    candidates = (
        manifest.get("candidateResults")
        if isinstance(manifest.get("candidateResults"), list)
        else []
    )
    first_result = candidates[0] if candidates and isinstance(candidates[0], dict) else None
    if first_result is None:
        return None
    return {
        "videoId": (first_result.get("candidate") or {}).get("videoId"),
        "status": first_result.get("status"),
        "sourcePassed": (
            first_result.get("reconstructionAttempted") is True
            or first_result.get("status") == "ready_for_selection"
            or candidate_result_is_accepted(first_result)
        ),
        "reconstructionAttempted": first_result.get("reconstructionAttempted") is True,
        "accepted": candidate_result_is_accepted(first_result),
        "rejectionTags": [],
    }


def summarize_source_funnel(paths: Iterable[Path], *, label: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    for path in paths:
        manifest = load_manifest(path)
        timings = manifest.get("timings") if isinstance(manifest.get("timings"), dict) else {}
        funnel = timings.get("sourceFunnel") if isinstance(timings.get("sourceFunnel"), dict) else {}
        first = manifest_first_candidate(manifest)
        total_seconds = float(timings.get("totalSeconds") or 0.0)
        selected = isinstance(manifest.get("selected"), dict)
        if first is not None:
            rejection_counts.update(str(tag) for tag in first.get("rejectionTags") or [])
        rows.append(
            {
                "path": str(path),
                "selected": selected,
                "totalSeconds": total_seconds,
                "processedCandidateCount": int(
                    funnel.get("processedCandidateCount")
                    or timings.get("processedCandidateCount")
                    or 0
                ),
                "firstCandidateSourcePassed": bool(first and first.get("sourcePassed")),
                "firstCandidateAccepted": bool(first and first.get("accepted")),
            }
        )

    count = len(rows)
    selected_count = sum(int(row["selected"]) for row in rows)
    total_seconds = sum(float(row["totalSeconds"]) for row in rows)
    processed_count = sum(int(row["processedCandidateCount"]) for row in rows)
    return {
        "schemaVersion": 1,
        "label": label,
        "manifestCount": count,
        "selectedCount": selected_count,
        "selectionRate": round(selected_count / count, 4) if count else 0.0,
        "firstCandidateSourcePassRate": round(
            sum(int(row["firstCandidateSourcePassed"]) for row in rows) / count,
            4,
        ) if count else 0.0,
        "firstCandidateAcceptanceRate": round(
            sum(int(row["firstCandidateAccepted"]) for row in rows) / count,
            4,
        ) if count else 0.0,
        "meanProcessedCandidatesPerSelection": round(processed_count / selected_count, 3)
        if selected_count else None,
        "acceptedOutputsPerWallHour": round(selected_count / (total_seconds / 3600.0), 3)
        if total_seconds > 0.0 else None,
        "totalSeconds": round(total_seconds, 3),
        "firstCandidateRejectionCounts": dict(rejection_counts.most_common()),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate source-funnel metrics from frozen exercise-motion selection manifests."
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--label", default="source-funnel")
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()
    summary = summarize_source_funnel(selection_manifest_paths(args.inputs), label=args.label)
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
