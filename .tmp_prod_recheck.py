"""Re-evaluate retained prod rejects with current code (scoped gates)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from time import monotonic

import numpy as np

from exercise_motion_pkg.anatomical_repair import repair_residuals, repair_rig_anatomy
from exercise_motion_pkg.controlled_motion import FixedRig, project_contact_plant_coordinates
from exercise_motion_pkg.loop_cycles import rank_loop_cycles

ROOT = Path("build/exercise_motion/exercise-library")


def load_skel(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_preflight(limit=40):
    outcomes = Counter()
    recovered = []
    still = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load_skel(skel)
        cm = data.get("controlledMotionFit") or {}
        if cm.get("reason") != "source_cycle_preflight_rejected":
            continue
        if len(recovered) + len(still) >= limit:
            break
        diagnostics = {}
        try:
            choices = rank_loop_cycles(
                data, max_candidates=5, endpoint_correction_ratio=0.06, diagnostics=diagnostics
            )
        except Exception as exc:
            outcomes["error"] += 1
            still.append((str(skel), str(exc)))
            continue
        counts = diagnostics.get("counts") or {}
        if choices:
            outcomes["recovered"] += 1
            recovered.append((str(skel), len(choices), counts))
        else:
            outcomes["still_empty"] += 1
            still.append((str(skel), counts))
    return outcomes, recovered[:5], still[:5]


def check_anatomy(limit=8):
    outcomes = Counter()
    samples = []
    seen = 0
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load_skel(skel)
        cm = data.get("controlledMotionFit") or {}
        reason = cm.get("reason")
        attempt_hit = any(
            (a.get("fitReport") or {}).get("reason") == "anatomical_source_projection_incomplete"
            for a in cm.get("cycleSelectionAttempts") or []
        )
        if reason != "anatomical_source_projection_incomplete" and not attempt_hit:
            continue
        # Prefer cleaned motion if present.
        cleaned = skel.parents[1] / "cleaned" / "motion.cleaned.json"
        payload = load_skel(cleaned) if cleaned.is_file() else data
        names = payload.get("jointNames") or data.get("jointNames")
        frames = payload.get("frames") or []
        if not names or len(frames) < 7:
            continue
        points = np.asarray([[f["joints"][n] for n in names] for f in frames], dtype=float)
        before, _ = repair_residuals(points, names)
        bad = int(np.any(before > 1e-6, axis=1).sum())
        rig = FixedRig(points, names)
        t0 = monotonic()
        _, report = repair_rig_anatomy(rig, points, deadline=monotonic() + 120.0)
        dt = monotonic() - t0
        key = "passed" if report.get("passed") else "failed"
        outcomes[key] += 1
        samples.append(
            {
                "path": str(skel),
                "bad": bad,
                "passed": report.get("passed"),
                "evals": report.get("evaluations"),
                "budget": report.get("evaluationBudget"),
                "unrepaired": report.get("unrepairedFrameCount"),
                "seconds": round(dt, 2),
            }
        )
        seen += 1
        if seen >= limit:
            break
    return outcomes, samples


def check_support_contact_polish(limit=8):
    """Replay contact plant polish on attempts that failed contacts near-miss."""
    outcomes = Counter()
    samples = []
    seen = 0
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load_skel(skel)
        cm = data.get("controlledMotionFit") or {}
        for attempt in cm.get("cycleSelectionAttempts") or []:
            report = attempt.get("fitReport") or {}
            if report.get("reason") != "support_reference_projection_incomplete":
                continue
            contacts = report.get("supportReferenceContacts") or {}
            geometry = report.get("supportReferenceGeometry") or {}
            alignment = report.get("supportReferenceAlignment") or {}
            equipment = report.get("supportReferenceEquipment") or {}
            if not (
                geometry.get("passed")
                and alignment.get("passed") is not False
                and equipment.get("passed") is not False
                and contacts.get("passed") is False
            ):
                continue
            before = contacts.get("maximumErrorMeters")
            if before is None or before >= 0.02:
                # large misses need full support re-init; skip for this cheap check
                outcomes["skipped_large"] += 1
                continue
            outcomes["near_miss_contacts"] += 1
            samples.append(
                {
                    "path": str(skel),
                    "before_m": before,
                    "anatomy_passed": (report.get("supportReferenceAnatomy") or {}).get("passed"),
                    "note": "would_enter_contact_polish_path",
                }
            )
            seen += 1
            if seen >= limit:
                return outcomes, samples
    return outcomes, samples


def check_seam_only(limit=20):
    outcomes = Counter()
    samples = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load_skel(skel)
        for attempt in (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []:
            report = attempt.get("fitReport") or {}
            checks = report.get("checks") or {}
            if not checks:
                continue
            failed = {k for k, v in checks.items() if v is False}
            if not failed or not failed <= {"loopSeam", "playback"}:
                continue
            if checks.get("loopSeam") is not False:
                continue
            playback = report.get("playback") or {}
            would_open = playback.get("seamContinuous") is False or (
                playback.get("seamContinuous") is None
            )
            outcomes["seam_only"] += 1
            if would_open:
                outcomes["would_open_seam_now"] += 1
            samples.append(
                {
                    "path": str(skel),
                    "failed": sorted(failed),
                    "playback_passed": checks.get("playback"),
                    "seamContinuous": playback.get("seamContinuous"),
                    "reason_then": report.get("reason"),
                    "would_open_seam_now": would_open,
                }
            )
            if len(samples) >= limit:
                return outcomes, samples
    return outcomes, samples


if __name__ == "__main__":
    print("=== PREFLIGHT (source_cycle_preflight_rejected) ===")
    out, recovered, still = check_preflight(40)
    print(dict(out))
    print("recovered examples:")
    for row in recovered:
        print(" ", row)
    print("still empty examples:")
    for row in still:
        print(" ", row)

    print("\n=== ANATOMY (anatomical_source_projection_incomplete) ===")
    out, samples = check_anatomy(6)
    print(dict(out))
    for row in samples:
        print(" ", row)

    print("\n=== SUPPORT CONTACT NEAR-MISS (eligible for new polish) ===")
    out, samples = check_support_contact_polish(10)
    print(dict(out))
    for row in samples:
        print(" ", row)

    print("\n=== SEAM-ONLY (open-seam eligible) ===")
    out, samples = check_seam_only(15)
    print(dict(out))
    for row in samples[:8]:
        print(" ", row)
