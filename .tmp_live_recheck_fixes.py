"""Live-replay retained prod fails for the four fix owners."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from time import monotonic

import numpy as np

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.equipment_constraints import calibrated_grip_constraint
from exercise_motion_pkg.loop_cycles import rank_loop_cycles
from exercise_motion_pkg.rig_playback import rig_contact_targets
from exercise_motion_pkg.support_alignment import validate_alignment
from exercise_motion_pkg.support_geometry import (
    calibrate_support_pose,
    initialize_supported_motion,
    support_evidence,
    validate_support_geometry,
)

ROOT = Path("build/exercise_motion/exercise-library")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect_support_torso_or_plant(limit=6):
    rows = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load(skel)
        for attempt_i, attempt in enumerate(
            (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []
        ):
            report = attempt.get("fitReport") or {}
            if report.get("reason") != "support_reference_projection_incomplete":
                continue
            geo = report.get("supportReferenceGeometry") or {}
            align = report.get("supportReferenceAlignment") or {}
            reasons = set(geo.get("rejectionReasons") or [])
            torso = align.get("reason") == "support_correction_introduced_torso_deformation"
            plant = "supported_body_moves" in reasons
            if not (torso or plant):
                continue
            sel = attempt.get("selection") or {}
            if "startFrame" not in sel or "stopFrameExclusive" not in sel:
                continue
            rows.append(
                {
                    "skel": skel,
                    "attempt": attempt_i,
                    "start": int(sel["startFrame"]),
                    "stop": int(sel["stopFrameExclusive"]),
                    "then_ptp": geo.get("maximumStationaryJointRangeMeters"),
                    "then_spine": align.get("maximumIntroducedSpineLateralOffsetMeters"),
                    "then_geo_reasons": sorted(reasons),
                    "then_align_reason": align.get("reason"),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def replay_support(row, *, max_evaluations=80, budget_s=180.):
    data = load(row["skel"])
    frames = data["frames"][row["start"]:row["stop"]]
    payload = {**{k: v for k, v in data.items() if k != "frames"}, "frames": frames}
    payload.pop("controlledMotionFit", None)
    bs = support_evidence(payload)
    if not bs.get("required"):
        return {"skipped": "support_not_required"}
    names = payload["jointNames"]
    pts = np.asarray([[f["joints"][n] for n in names] for f in frames], float)
    if len(pts) < 5:
        return {"skipped": "too_short"}
    rig = FixedRig(pts, names)
    fps = float(payload.get("fps") or 30)
    equip = calibrated_grip_constraint(payload, pts, names)
    t0 = monotonic()
    pose, calib = calibrate_support_pose(rig, pts, bs, alignment_reference=pts)
    if pose is None or not calib.get("passed"):
        return {
            "passed": False,
            "stage": "calibrate",
            "calib": {k: calib.get(k) for k in ("passed", "surfaceErrorMeters", "evaluations")},
            "seconds": round(monotonic() - t0, 2),
        }
    pinned = np.zeros((len(pts), len(names)), dtype=bool)
    for name in bs.get("stationaryJoints") or []:
        pinned[:, names.index(name)] = True
    targets, _ = rig_contact_targets(
        pts,
        names,
        pinned,
        rig.offsets,
        stationary_positions={n: pose[names.index(n)] for n in bs.get("stationaryJoints") or []},
        evidence=payload.get("sourceFootSupportEvidence"),
        floor=payload.get("renderFloorY"),
    )
    try:
        init = initialize_supported_motion(
            rig,
            pts,
            bs,
            pose,
            calib,
            monotonic() + budget_s,
            fps=fps,
            alignment_reference=pts,
            pinned=pinned,
            contact_targets=targets,
            equipment=equip,
            max_evaluations=max_evaluations,
        )
    except TimeoutError:
        return {"passed": False, "stage": "init_timeout", "seconds": round(monotonic() - t0, 2)}
    geo = validate_support_geometry(payload, init, names)
    align = validate_alignment(init, pts, names, bs)
    return {
        "passed": bool(geo.get("passed") and align.get("passed")),
        "geo_passed": geo.get("passed"),
        "align_passed": align.get("passed"),
        "ptp": geo.get("maximumStationaryJointRangeMeters"),
        "spine": align.get("maximumIntroducedSpineLateralOffsetMeters"),
        "geo_reasons": geo.get("rejectionReasons"),
        "align_reason": align.get("reason"),
        "then_ptp": row["then_ptp"],
        "then_spine": row["then_spine"],
        "path": str(row["skel"]),
        "attempt": row["attempt"],
        "seconds": round(monotonic() - t0, 2),
    }


def collect_discontinuity(limit=8):
    rows = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load(skel)
        for attempt_i, attempt in enumerate(
            (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []
        ):
            report = attempt.get("fitReport") or {}
            checks = report.get("checks") or {}
            if checks.get("motionDiscontinuity") is not False:
                continue
            sel = attempt.get("selection") or {}
            if "startFrame" not in sel:
                continue
            md = report.get("motionDiscontinuity") or {}
            rows.append(
                {
                    "skel": skel,
                    "attempt": attempt_i,
                    "start": int(sel["startFrame"]),
                    "stop": int(sel["stopFrameExclusive"]),
                    "failed": sorted(k for k, v in checks.items() if v is False),
                    "events": len(md.get("events") or []),
                    "jerk_before": report.get("jerkBefore"),
                    "jerk_after": report.get("jerkAfter"),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def replay_fit_slice(row, *, timeout_seconds=180.):
    from exercise_motion_pkg.controlled_motion import fit_controlled_motion

    data = load(row["skel"])
    frames = data["frames"][row["start"]:row["stop"]]
    payload = {**{k: v for k, v in data.items() if k not in ("frames", "controlledMotionFit")},
               "frames": frames}
    # Match cyclic cycle fits when the attempt had loop seam in the fail set.
    if "loopSeam" in row["failed"]:
        payload["loop"] = {"enabled": True}
    t0 = monotonic()
    _, report = fit_controlled_motion(payload, timeout_seconds=timeout_seconds)
    checks = report.get("checks") or {}
    failed = sorted(k for k, v in checks.items() if v is False)
    return {
        "applied": report.get("applied"),
        "reason": report.get("reason"),
        "failed": failed,
        "motionDiscontinuity": checks.get("motionDiscontinuity"),
        "jerk_before": report.get("jerkBefore"),
        "jerk_after": report.get("jerkAfter"),
        "then_failed": row["failed"],
        "path": str(row["skel"]),
        "attempt": row["attempt"],
        "seconds": round(monotonic() - t0, 2),
        "stop": (report.get("boundedRefinement") or {}).get("stopReason"),
        "polish_methods": [
            b.get("method")
            for b in ((report.get("boundedRefinement") or {}).get("blocks") or [])
            if b.get("method")
        ],
    }


def check_preflight(limit=30):
    outcomes = Counter()
    recovered = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load(skel)
        if (data.get("controlledMotionFit") or {}).get("reason") != "source_cycle_preflight_rejected":
            continue
        if sum(outcomes.values()) >= limit:
            break
        diagnostics = {}
        choices = rank_loop_cycles(
            data, max_candidates=5, endpoint_correction_ratio=0.06, diagnostics=diagnostics
        )
        if choices:
            outcomes["recovered"] += 1
            recovered.append((str(skel), diagnostics.get("counts")))
        else:
            outcomes["still_empty"] += 1
    return outcomes, recovered[:5]


if __name__ == "__main__":
    print("=== PREFLIGHT (ranking only; Fix1 was cut recovery upstream) ===")
    out, recovered = check_preflight(30)
    print(dict(out))
    for row in recovered:
        print(" recovered", row[0].split("exercise-library/")[-1][:80], row[1])

    print("\n=== SUPPORT plant/torso LIVE REPLAY ===")
    support_rows = collect_support_torso_or_plant(5)
    print("candidates", len(support_rows))
    support_out = Counter()
    for row in support_rows:
        result = replay_support(row)
        if result.get("skipped"):
            support_out[f"skipped_{result['skipped']}"] += 1
            print(" skip", result)
            continue
        key = "passed" if result.get("passed") else "failed"
        support_out[key] += 1
        print(
            f" {key}",
            Path(result.get("path", "")).parts[-4] if result.get("path") else "?",
            f"attempt={result.get('attempt')}",
            f"ptp {result.get('then_ptp')}->{result.get('ptp')}",
            f"spine {result.get('then_spine')}->{result.get('spine')}",
            f"geo={result.get('geo_passed')} align={result.get('align_passed')}",
            f"s={result.get('seconds')}",
            result.get("geo_reasons") or result.get("align_reason") or "",
        )
    print("support summary", dict(support_out))

    print("\n=== DISCONTINUITY LIVE FIT REPLAY (expensive; 2 samples) ===")
    disc_rows = collect_discontinuity(2)
    print("candidates", len(disc_rows))
    disc_out = Counter()
    for row in disc_rows:
        print(" replaying", Path(str(row["skel"])).parts[-4], "attempt", row["attempt"],
              "then", row["failed"])
        result = replay_fit_slice(row, timeout_seconds=200.)
        if result.get("applied"):
            disc_out["applied"] += 1
        elif result.get("motionDiscontinuity") is True:
            disc_out["disc_cleared_other_fails"] += 1
        elif result.get("motionDiscontinuity") is False:
            disc_out["disc_still_fails"] += 1
        else:
            disc_out["no_checks"] += 1
        print(
            " ",
            "applied" if result.get("applied") else "failed",
            result.get("reason"),
            "failed_now",
            result.get("failed"),
            "disc",
            result.get("motionDiscontinuity"),
            "jerk",
            result.get("jerk_before"),
            "->",
            result.get("jerk_after"),
            "stop",
            result.get("stop"),
            "methods",
            result.get("polish_methods"),
            "s",
            result.get("seconds"),
        )
    print("disc summary", dict(disc_out))
