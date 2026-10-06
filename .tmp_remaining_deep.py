"""Deeper probes for remaining root-cause owners."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from exercise_motion_pkg.physical_validation import body_scale
from exercise_motion_pkg.sequence_stabilization import contact_mask

ROOT = Path("build/exercise_motion/exercise-library")


def probe_opposite_velocity():
    """Are direction rejects true anti-phase matches or mid-rep false matches?"""
    path = Path(
        "build/exercise_motion/exercise-library/barbell-bench-press/bake/"
        "barbell-bench-press-001-eji1nlsul9k/wear/skeleton.baked.full-input.adaptive-baseline.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    frames, names = data["frames"], data["jointNames"]
    points = np.asarray([[f["joints"][n] for n in names] for f in frames], float)
    fps = float(data.get("fps") or 30)
    scale = body_scale(points, names)
    contacts = contact_mask(data, names, len(frames))
    velocity = np.gradient(gaussian_filter1d(points, max(0.5, fps * 0.04), axis=0), axis=0) * fps
    # Dominant joint travel as crude phase proxy (wrists for bench).
    wrists = points[:, [names.index("left_wrist"), names.index("right_wrist")], 1].mean(axis=1)
    rows = []
    min_frames = max(6, round(fps * 0.5))
    for start in range(len(frames) - min_frames):
        for stop in range(start + min_frames, len(frames)):
            if contacts is not None and not np.array_equal(contacts[start], contacts[stop]):
                continue
            jump = float(np.max(np.linalg.norm(points[start] - points[stop], axis=-1)))
            if jump > max(0.08, 0.12) * scale:
                continue
            left, right = velocity[start].ravel(), velocity[stop].ravel()
            mag = np.linalg.norm(left) * np.linalg.norm(right)
            opposite = mag > (0.05 * scale) ** 2 and np.dot(left, right) < 0
            rows.append(
                {
                    "start": start,
                    "stop": stop,
                    "len": stop - start,
                    "jump": jump,
                    "opposite": opposite,
                    "wrist_y_s": float(wrists[start]),
                    "wrist_y_e": float(wrists[stop]),
                    "wrist_delta": float(wrists[stop] - wrists[start]),
                    "dot": float(np.dot(left, right) / max(mag, 1e-12)) if mag else 0.0,
                }
            )
    print("bench endpoint-feasible", len(rows), "opposite", sum(1 for r in rows if r["opposite"]))
    for r in rows[:12]:
        print(r)


def probe_discontinuity_events():
    path = Path(
        "build/exercise_motion/exercise-library/barbell-reverse-lunge/bake/"
        "barbell-reverse-lunge-002-apumszmlvne-window-01-1733-5467/wear/"
        "skeleton.baked.full-input.adaptive-baseline.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    for i, attempt in enumerate((data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []):
        report = attempt.get("fitReport") or {}
        md = report.get("motionDiscontinuity") or {}
        if not md:
            continue
        events = md.get("events") or []
        print("attempt", i, "failed", [k for k, v in (report.get("checks") or {}).items() if v is False])
        print(" policy", md.get("policy"))
        joint_counts = Counter()
        for ev in events[:20]:
            if isinstance(ev, dict):
                joint_counts[ev.get("joint") or ev.get("track") or ev.get("name") or str(ev)[:60]] += 1
            else:
                joint_counts[str(ev)[:60]] += 1
        print(" event_count", len(events), "top", joint_counts.most_common(8))
        if events:
            print(" sample_event", events[0])


def probe_support_torso_deformation():
    path = Path(
        "build/exercise_motion/exercise-library/single-arm-dumbbell-bench-press/bake/"
        "single-arm-dumbbell-bench-press-001-4q9-9eqql8-window-01-7741-12946/wear/"
        "skeleton.baked.full-input.adaptive-baseline.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    for i, attempt in enumerate((data.get("controlledMotionFit") or {}).get("cycleSelectionAttempts") or []):
        report = attempt.get("fitReport") or {}
        if report.get("reason") != "support_reference_projection_incomplete":
            continue
        align = report.get("supportReferenceAlignment") or {}
        geo = report.get("supportReferenceGeometry") or {}
        print("attempt", i)
        print(" align", {k: align.get(k) for k in list(align)[:15]})
        print(" geo", {k: geo.get(k) for k in (
            "passed", "rejectionReasons", "maximumStationaryJointRangeMeters",
            "maximumSurfaceErrorMeters", "toleranceMeters")})
        print(" calib", {k: (report.get("supportCalibration") or {}).get(k) for k in (
            "passed", "surfaceErrorMeters", "evaluations", "projectionEvaluations",
            "projectionEvaluationBudget", "elapsedSeconds")})
        print(" init_s", report.get("supportInitializationSeconds"))


def probe_phase_vs_contract():
    """Would contract-declared phase find complete cycles where PCA fails?"""
    from exercise_motion_pkg.loop_cycles import rank_loop_cycles

    # Prefer bake_and_rank observable phase if importable.
    try:
        from exercise_motion_pkg.bake_and_rank import (
            observable_motion_spec_for_contract,
            dominant_observable_motion_phase_track,
            body_height_from_payload_frames,
        )
    except Exception as exc:
        print("contract imports unavailable", exc)
        return
    path = Path(
        "build/exercise_motion/exercise-library/barbell-good-morning/bake/"
        "barbell-good-morning-001-c4ghpsq0shg/wear/skeleton.baked.full-input.adaptive-baseline.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    # Try to find a contract nearby
    contract = None
    for rel in (
        "bake/selection_manifest.json",
        "selected/selection_manifest.json",
        "bake/attempt_manifests/best_no_selection_manifest.json",
    ):
        p = path.parents[2] / rel.split("/")[0] if False else path.parents[2]
    # search manifests
    base = path.parents[2]  # exercise slug dir? path = .../barbell-good-morning/bake/<id>/wear/file
    # parents[0]=wear, [1]=candidate, [2]=bake, [3]=exercise
    exercise = path.parents[3]
    for manifest in list(exercise.glob("**/selection_manifest.json"))[:3]:
        try:
            j = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        contract = j.get("exerciseMotionContract") or (j.get("selected") or {}).get(
            "exerciseMotionContract"
        )
        if contract:
            print("found contract in", manifest)
            break
    if not contract:
        # synthesize a simple vertical torso/hip hinge phase from pelvis-neck
        names = data["jointNames"]
        points = np.asarray([[f["joints"][n] for n in names] for f in data["frames"]], float)
        phase = points[:, names.index("neck"), 1] - points[:, names.index("pelvis"), 1]
        print("no contract; using neck-pelvis height phase")
    else:
        spec = observable_motion_spec_for_contract(contract)
        track = dominant_observable_motion_phase_track(
            data["frames"],
            spec=spec,
            body_span=body_height_from_payload_frames(data["frames"]),
        ) if spec is not None else None
        phase = track.get("values") if track else None
        print("contract phase", None if phase is None else len(phase))
    diag = {}
    geo = rank_loop_cycles(data, max_candidates=5, endpoint_correction_ratio=0.06, diagnostics={})
    print("geometric choices", len(geo))
    if phase is not None:
        choices = rank_loop_cycles(
            data,
            max_candidates=5,
            endpoint_correction_ratio=0.06,
            diagnostics=diag,
            phase_values=phase if not isinstance(phase, list) else phase,
        )
        # neck-pelvis path sets phase as ndarray
        if not isinstance(phase, (list, np.ndarray)):
            pass
        print("phase choices", len(choices), "counts", diag.get("counts"))


if __name__ == "__main__":
    print("=== OPPOSITE VELOCITY (bench) ===")
    probe_opposite_velocity()
    print("\n=== DISCONTINUITY EVENTS (reverse lunge) ===")
    probe_discontinuity_events()
    print("\n=== SUPPORT TORSO DEFORMATION ===")
    probe_support_torso_deformation()
    print("\n=== PHASE VS PCA (good morning) ===")
    probe_phase_vs_contract()
