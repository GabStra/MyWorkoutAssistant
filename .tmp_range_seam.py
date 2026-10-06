"""Inspect jointRange+loopSeam failures for owning cause."""
import json
from collections import Counter
from pathlib import Path

root = Path("build/exercise_motion/exercise-library")
details = Counter()
examples = []
for skel in root.glob("*/bake/*/wear/skeleton.baked*.json"):
    try:
        data = json.loads(skel.read_text(encoding="utf-8"))
    except Exception:
        continue
    for attempt in (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []:
        report = attempt.get("fitReport") or {}
        checks = report.get("checks") or {}
        failed = {k for k, v in checks.items() if v is False}
        if "jointRange" not in failed:
            continue
        details["jointRange_total"] += 1
        if "loopSeam" in failed:
            details["with_loopSeam"] += 1
        # find jointRange diagnostics
        for key in (
            "jointRange",
            "range",
            "motionRange",
            "supportArticulation",
            "articulationRange",
        ):
            block = report.get(key)
            if isinstance(block, dict):
                details["has_%s" % key] += 1
                if len(examples) < 4 and "loopSeam" in failed:
                    examples.append((str(skel), failed, key, block))
        # scan nested
        for key, value in report.items():
            if not isinstance(value, dict):
                continue
            blob = json.dumps(value)
            if "jointRange" in key or "Range" in key or "retained" in blob[:200]:
                if "range" in key.lower() or "joint" in key.lower():
                    details["key:%s" % key] += 1

print("=== counts ===")
for key, value in details.most_common(40):
    print("%4d | %s" % (value, key))
print("=== examples ===")
for path, failed, key, block in examples:
    print(path)
    print(" failed", sorted(failed))
    print(" ", key, {k: block.get(k) for k in list(block)[:20]})
