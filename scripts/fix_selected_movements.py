"""Repair already-selected movements in place with the current pipeline fixes.

Runs the skeletal stabilizer (which never ran on fit-produced artifacts before
2026-09-25) over every ``selected/*_wear_skeleton.json``, smooths the embedded
fixedRig coordinate tracks with the same cut-guarded kernel the renderers use,
and regenerates the interactive preview HTML so it embeds the current renderer
(head-pitch correction, shimmer damping). The original skeleton is kept as a
``.pre_fix.bak`` sibling; the fixedRig is only touched when the stabilizer
applied, so accepted and repaired artifacts stay distinguishable.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exercise_motion_pkg.preview import write_baked_preview_html
from exercise_motion_pkg.sequence_stabilization import stabilize_exported_sequence

RIG_SMOOTHING_MAX_STEP = 0.35


def smooth_rig_rows(rows: list[list[float]], wrap: bool) -> list[list[float]] | None:
    count = len(rows)
    if count < 3:
        return None
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        return None

    def neighbour(index: int, step: int) -> list[float]:
        raw = index + step
        bounded = ((raw % count) + count) % count if wrap else max(0, min(count - 1, raw))
        return rows[bounded]

    smoothed = []
    changed = False
    for index, row in enumerate(rows):
        previous = neighbour(index, -1)
        next_row = neighbour(index, +1)
        cut = any(
            abs(previous[c] - row[c]) > RIG_SMOOTHING_MAX_STEP
            or abs(next_row[c] - row[c]) > RIG_SMOOTHING_MAX_STEP
            for c in range(width)
        )
        if cut:
            smoothed.append(list(row))
        else:
            changed = True
            smoothed.append([
                0.25 * previous[c] + 0.5 * row[c] + 0.25 * next_row[c]
                for c in range(width)
            ])
    return smoothed if changed else None


def oscillation_metrics(payload: dict) -> tuple[float, float]:
    frames = payload.get("frames") or []
    skip = {"left_foot", "right_foot", "left_hand", "right_hand"}
    joints = [n for n in (frames[0].get("joints") or {}) if n not in skip]
    flips = total = 0
    accels = []
    for name in joints:
        for axis in range(3):
            deltas = [
                frames[i]["joints"][name][axis] - frames[i - 1]["joints"][name][axis]
                for i in range(1, len(frames))
                if name in frames[i].get("joints", {}) and name in frames[i - 1].get("joints", {})
            ]
            deltas = [d for d in deltas if abs(d) > 1e-5]
            for a, b in zip(deltas, deltas[1:]):
                total += 1
                if (a > 0) != (b > 0):
                    flips += 1
    for i in range(1, len(frames) - 1):
        values = []
        for name in joints:
            j0, j1, j2 = frames[i - 1]["joints"], frames[i]["joints"], frames[i + 1]["joints"]
            if name not in j0 or name not in j1 or name not in j2:
                continue
            ax = j2[name][0] - 2 * j1[name][0] + j0[name][0]
            ay = j2[name][1] - 2 * j1[name][1] + j0[name][1]
            az = j2[name][2] - 2 * j1[name][2] + j0[name][2]
            values.append(math.sqrt(ax * ax + ay * ay + az * az))
        if values:
            accels.append(sorted(values)[len(values) // 2])
    rate = flips / total if total else 0.0
    median_accel = sorted(accels)[len(accels) // 2] if accels else 0.0
    return rate, median_accel * 1000.0


def fix_artifact(path: Path, *, regenerate_html: bool) -> dict:
    with open(path, encoding="utf-8") as handle:
        original = json.load(handle)

    before = oscillation_metrics(original)
    payload, report = stabilize_exported_sequence(
        copy.deepcopy(original), max_evaluations=90, timeout_seconds=90.
    )
    applied = bool(report.get("applied"))
    reused = bool(report.get("reused"))
    result = {
        "path": str(path),
        "stabilized": applied and not reused,
        "alreadyFixed": reused,
        "reason": report.get("reason"),
        "maximumCorrectionMeters": report.get("maximumCorrectionMeters"),
        "flipRateBefore": round(before[0], 4),
        "accelBeforeMm": round(before[1], 2),
    }

    if applied and not reused:
        rig = payload.get("fixedRig")
        loopable = bool((payload.get("loop") or {}).get("enabled"))
        fixed_rig_touched = False
        if isinstance(rig, dict) and isinstance(rig.get("coordinates"), list):
            rows = [list(map(float, row)) for row in rig["coordinates"]]
            smoothed = smooth_rig_rows(rows, wrap=loopable)
            if smoothed is not None:
                rig["coordinates"] = smoothed
                fixed_rig_touched = True
        result["flipRateAfter"] = round(oscillation_metrics(payload)[0], 4)
        result["accelAfterMm"] = round(oscillation_metrics(payload)[1], 2)
        backup = path.with_suffix(".json.pre_fix.bak")
        if not backup.exists():
            backup.write_text(json.dumps(original, indent=2), encoding="utf-8")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result["fixedRigSmoothed"] = fixed_rig_touched

    if regenerate_html:
        html = path.with_name(path.name.replace("_wear_skeleton.json", "_interactive_preview.html"))
        if html.exists():
            try:
                # Refresh with today's renderer (head-pitch correction, shimmer
                # damping) whether or not the data-level stabilization applied.
                write_baked_preview_html(html, payload if applied else original)
                result["htmlRefreshed"] = True
            except Exception as error:  # noqa: BLE001 - report per artifact
                result["htmlRefreshed"] = False
                result["htmlError"] = str(error)[:200]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parents[1] / "build" / "exercise_motion" / "exercise-library"),
    )
    parser.add_argument("--keep-html", action="store_true", help="skip preview HTML regeneration")
    args = parser.parse_args()

    root = Path(args.workspace)
    artifacts = sorted(root.glob("selected" if root.name == "selected" else "*/selected/*_wear_skeleton.json"))
    if not artifacts:
        artifacts = sorted(root.glob("*/selected/*_wear_skeleton.json"))
    print(f"selected skeletons: {len(artifacts)}")
    summary = {"stabilized": 0, "skipped": 0, "html": 0, "errors": 0}
    reports = []
    for path in artifacts:
        try:
            result = fix_artifact(path, regenerate_html=not args.keep_html)
        except Exception as error:  # noqa: BLE001 - one bad artifact must not stop the sweep
            summary["errors"] += 1
            reports.append({"path": str(path), "error": str(error)[:200]})
            print(f"ERROR {path.parent.parent.name}: {error}")
            continue
        reports.append(result)
        if result.get("stabilized"):
            summary["stabilized"] += 1
            summary["html"] += int(bool(result.get("htmlRefreshed")))
            print(
                f"FIXED {path.parent.parent.name}: flips {result['flipRateBefore']:.3f}->"
                f"{result.get('flipRateAfter', result['flipRateBefore']):.3f} "
                f"accel {result['accelBeforeMm']:.1f}->{result.get('accelAfterMm', result['accelBeforeMm']):.1f}mm "
                f"maxCorr {result.get('maximumCorrectionMeters') or 0:.3f}m"
            )
        elif result.get("alreadyFixed"):
            summary["alreadyFixed"] = summary.get("alreadyFixed", 0) + 1
            summary["html"] += int(bool(result.get("htmlRefreshed")))
            print(f"ok    {path.parent.parent.name}: already stabilized in an earlier pass")
        else:
            summary["skipped"] += 1
            print(f"skip  {path.parent.parent.name}: {result.get('reason')}")
    (root / "movement_repair_report.json").write_text(
        json.dumps({"summary": summary, "artifacts": reports}, indent=2), encoding="utf-8"
    )
    print(f"summary: {summary}")


if __name__ == "__main__":
    main()
