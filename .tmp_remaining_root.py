"""Investigate remaining prod failure root causes from retained artifacts."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from exercise_motion_pkg.loop_cycles import rank_loop_cycles
from exercise_motion_pkg.physical_validation import body_scale
from exercise_motion_pkg.repetition_phase import complete_repetition, major_phase_sequence
from exercise_motion_pkg.sequence_stabilization import contact_mask

ROOT = Path("build/exercise_motion/exercise-library")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def still_empty_preflight(limit=25):
    rows = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load(skel)
        cm = data.get("controlledMotionFit") or {}
        if cm.get("reason") != "source_cycle_preflight_rejected":
            continue
        diagnostics = {}
        choices = rank_loop_cycles(
            data, max_candidates=3, endpoint_correction_ratio=0.06, diagnostics=diagnostics
        )
        if choices:
            continue
        counts = diagnostics.get("counts") or {}
        frames = data.get("frames") or []
        names = data.get("jointNames") or []
        if not frames or not names:
            continue
        points = np.asarray([[f["joints"][n] for n in names] for f in frames], float)
        fps = float(data.get("fps") or 30)
        contacts = contact_mask(data, names, len(frames))
        scale = body_scale(points, names)
        root = names.index("pelvis")
        features = np.concatenate(
            [points[:, root : root + 1], points - points[:, root : root + 1]], axis=1
        )
        velocity = (
            np.gradient(gaussian_filter1d(points, max(0.5, fps * 0.04), axis=0), axis=0) * fps
        )
        flat = features.reshape(len(frames), -1)
        centered = flat - flat.mean(axis=0)
        phase = gaussian_filter1d(
            centered @ np.linalg.svd(centered, full_matrices=False)[2][0],
            max(0.5, fps * 0.04),
        )
        # Why directionCompatible is low: sample endpoint-feasible rejects.
        dir_reject = Counter()
        phase_seqs = Counter()
        min_frames = max(6, round(fps * 0.5))
        endpoint_ok = 0
        for start in range(0, len(frames) - min_frames, 3):
            for stop in range(start + min_frames, len(frames), 3):
                if contacts is not None and not np.array_equal(contacts[start], contacts[stop]):
                    continue
                jump = float(np.max(np.linalg.norm(points[start] - points[stop], axis=-1)))
                if jump > max(0.08, 0.12) * scale:
                    continue
                endpoint_ok += 1
                left, right = velocity[start].ravel(), velocity[stop].ravel()
                mag = np.linalg.norm(left) * np.linalg.norm(right)
                if mag > (0.05 * scale) ** 2 and np.dot(left, right) < 0:
                    dir_reject["opposite_velocity"] += 1
                    continue
                dir_reject["direction_ok"] += 1
                if stop < len(frames):
                    closed = np.concatenate([phase[start:stop], phase[stop : stop + 1]])
                else:
                    closed = np.concatenate([phase[start:stop], phase[start : start + 1]])
                ok, seq = complete_repetition(closed.tolist())
                phase_seqs[tuple(seq)] += 1
                if ok:
                    dir_reject["complete_ok"] += 1
        # Prior preflight diagnostics if present
        prior = []
        for item in cm.get("sourceCyclePreflight") or []:
            if isinstance(item, dict):
                prior.append(
                    {
                        "reason": item.get("reason"),
                        "counts": ((item.get("proposalDiagnostics") or {}).get("counts")),
                        "source_passed": (item.get("sourcePhase") or {}).get("passed"),
                        "output_passed": (item.get("outputPhase") or {}).get("passed"),
                    }
                )
        rows.append(
            {
                "path": str(skel),
                "frames": len(frames),
                "counts": counts,
                "endpoint_ok_sampled": endpoint_ok,
                "dir_reject": dict(dir_reject),
                "phase_seqs": phase_seqs.most_common(5),
                "prior": prior[:2],
                "bucket": (
                    "no_endpoint"
                    if counts.get("endpointFeasible", 0) == 0
                    else "no_direction"
                    if counts.get("directionCompatible", 0) == 0
                    else "no_complete"
                    if counts.get("completePhase", 0) == 0
                    else "no_range"
                    if counts.get("rangePreserved", 0) == 0
                    else "other"
                ),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def fit_validation_owners(limit_per=8):
    combos = Counter()
    playback_fail_reason = Counter()
    seam_mag = []
    shake_examples = []
    discontinuity_examples = []
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load(skel)
        for attempt in (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []:
            report = attempt.get("fitReport") or {}
            if report.get("applied"):
                continue
            checks = report.get("checks") or {}
            if not checks:
                continue
            failed = tuple(sorted(k for k, v in checks.items() if v is False))
            if not failed:
                continue
            # skip pure seam-only (already understood)
            if set(failed) <= {"loopSeam", "playback"}:
                continue
            combos[failed] += 1
            pb = report.get("playback") or {}
            if checks.get("playback") is False:
                # infer owning playback subgate
                if (pb.get("bodySupport") or {}).get("passed") is False:
                    playback_fail_reason["bodySupport"] += 1
                elif float(pb.get("maximumContactErrorMeters") or 0) > 0.0005:
                    playback_fail_reason["subframe_contacts"] += 1
                elif (pb.get("equipment") or {}).get("passed") is False:
                    playback_fail_reason["equipment"] += 1
                elif pb.get("velocityContinuous") is False:
                    playback_fail_reason["velocityContinuous"] += 1
                elif (pb.get("physicalReasons") or []):
                    playback_fail_reason[
                        "physical:" + ",".join((pb.get("physicalReasons") or [])[:2])
                    ] += 1
                else:
                    playback_fail_reason["other_playback"] += 1
            if checks.get("loopSeam") is False:
                excess = pb.get("seamStepExcessMeters")
                limit = pb.get("seamStepExcessLimitMeters")
                if excess is not None:
                    ratio = float(excess) / float(limit) if limit else None
                    seam_mag.append(ratio if ratio is not None else float(excess))
            if "jointShake" in failed or "relativeJointShake" in failed or "jerk" in failed:
                if len(shake_examples) < limit_per:
                    shake_examples.append(
                        {
                            "path": str(skel),
                            "failed": failed,
                            "stop": (report.get("boundedRefinement") or {}).get("stopReason"),
                            "jerkAfter": report.get("jerkAfter"),
                            "jerkBefore": report.get("jerkBefore"),
                            "settlingAfter": report.get("settlingSpeedAfter"),
                            "settlingLimit": report.get("settlingLimit"),
                        }
                    )
            if "motionDiscontinuity" in failed:
                md = report.get("motionDiscontinuity") or {}
                if len(discontinuity_examples) < limit_per:
                    discontinuity_examples.append(
                        {
                            "path": str(skel),
                            "failed": failed,
                            "severe": md.get("severe"),
                            "available": md.get("available"),
                            "keys": sorted(md.keys())[:12],
                            "summary": {
                                k: md.get(k)
                                for k in (
                                    "maxJumpMeters",
                                    "maxJumpRatio",
                                    "worstJoint",
                                    "reason",
                                    "eventCount",
                                )
                                if k in md
                            },
                        }
                    )
    return combos, playback_fail_reason, seam_mag, shake_examples, discontinuity_examples


def support_geometry_fails(limit=12):
    rows = []
    reasons = Counter()
    for skel in ROOT.glob("*/bake/*/wear/skeleton.baked*.json"):
        data = load(skel)
        for attempt in (data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []:
            report = attempt.get("fitReport") or {}
            if report.get("reason") != "support_reference_projection_incomplete":
                continue
            geo = report.get("supportReferenceGeometry") or {}
            align = report.get("supportReferenceAlignment") or {}
            if geo.get("passed") is not False and align.get("passed") is not False:
                continue
            for r in geo.get("rejectionReasons") or []:
                reasons[str(r)] += 1
            if align.get("passed") is False:
                reasons["alignment:" + str(align.get("reason"))] += 1
            rows.append(
                {
                    "path": str(skel),
                    "geo_passed": geo.get("passed"),
                    "geo_reasons": geo.get("rejectionReasons"),
                    "stationary_range": geo.get("maximumStationaryJointRangeMeters"),
                    "surface_err": geo.get("maximumSurfaceErrorMeters"),
                    "tol": geo.get("toleranceMeters"),
                    "align_passed": align.get("passed"),
                    "align_reason": align.get("reason"),
                    "contacts": (report.get("supportReferenceContacts") or {}).get(
                        "maximumErrorMeters"
                    ),
                    "projection_evals": (report.get("supportCalibration") or {}).get(
                        "projectionEvaluations"
                    )
                    or (report.get("supportCalibration") or {}).get("projectionEvaluationBudget"),
                    "init_s": report.get("supportInitializationSeconds"),
                }
            )
            if len(rows) >= limit:
                return reasons, rows
    return reasons, rows


if __name__ == "__main__":
    print("=== STILL-EMPTY PREFLIGHT ===")
    rows = still_empty_preflight(20)
    buckets = Counter(r["bucket"] for r in rows)
    print("buckets", dict(buckets))
    for r in rows[:8]:
        print(r["path"])
        print(" ", r["bucket"], "frames", r["frames"], "counts", r["counts"])
        print(" ", "dir", r["dir_reject"], "phase", r["phase_seqs"][:3])
        if r["prior"]:
            print(" ", "prior", r["prior"])

    print("\n=== FIT VALIDATION (non seam-only) ===")
    combos, pb, seam_mag, shake, disc = fit_validation_owners()
    print("top combos:")
    for k, v in combos.most_common(12):
        print(f"  {v:3d} | {k}")
    print("playback sub-reasons:", dict(pb.most_common(10)))
    if seam_mag:
        arr = np.asarray([x for x in seam_mag if x is not None], float)
        print(
            "seam excess ratio among these: n",
            len(arr),
            "median",
            float(np.median(arr)),
            "p90",
            float(np.percentile(arr, 90)),
            "max",
            float(np.max(arr)),
        )
    print("shake examples:")
    for e in shake[:4]:
        print(" ", e)
    print("discontinuity examples:")
    for e in disc[:4]:
        print(" ", e)

    print("\n=== SUPPORT GEOMETRY/ALIGNMENT HARD FAILS ===")
    reasons, rows = support_geometry_fails()
    print("reasons", dict(reasons.most_common(12)))
    for r in rows[:6]:
        print(r)
