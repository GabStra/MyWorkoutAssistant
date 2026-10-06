"""Show jointRangeRatios for range+seam failures."""
import json
from pathlib import Path

root = Path("build/exercise_motion/exercise-library")
shown = 0
for skel in root.glob("*/bake/*/wear/skeleton.baked*.json"):
    try:
        data = json.loads(skel.read_text(encoding="utf-8"))
    except Exception:
        continue
    for attempt in (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []:
        report = attempt.get("fitReport") or {}
        checks = report.get("checks") or {}
        failed = {k for k, v in checks.items() if v is False}
        if "jointRange" not in failed or "loopSeam" not in failed:
            continue
        ratios = report.get("jointRangeRatios") or {}
        support_ratios = report.get("supportArticulationRangeRatios") or {}
        weak = sorted(
            ((name, ratio) for name, ratio in ratios.items() if isinstance(ratio, (int, float))),
            key=lambda item: item[1],
        )[:8]
        weak_support = sorted(
            (
                (name, ratio)
                for name, ratio in support_ratios.items()
                if isinstance(ratio, (int, float))
            ),
            key=lambda item: item[1],
        )[:8]
        print(skel)
        print(" failed", sorted(failed))
        print(" weak jointRange", weak)
        print(" weak supportArticulation", weak_support)
        print(
            " seam",
            (report.get("playback") or {}).get("seamStepExcessMeters"),
            (report.get("playback") or {}).get("seamContinuous"),
        )
        shown += 1
        if shown >= 6:
            raise SystemExit
