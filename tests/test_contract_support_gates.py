"""Contract support gates reject wrong-surface and unsettled endpoints."""
import math

from exercise_motion_pkg.contract_support_gates import (
    REASON_TERMINAL_SUPPORT_NOT_ELEVATED,
    REASON_TERMINAL_SUPPORT_NOT_SETTLED,
    REASON_TRAVEL_FACING_MISMATCH,
    contract_support_gates,
)

JOINTS = ("pelvis", "left_hip", "right_hip", "left_foot", "right_foot")


def build_export(*, terminal_foot_y=0.0, yaw_degrees=0.0, travel=(0.0, 0.0), frames=24, tail_rotation_frames=0, duration_seconds=1.0):
    frames_payload = []
    total_yaw = math.radians(yaw_degrees)
    for index in range(frames):
        progress = index / (frames - 1)
        t = progress
        if tail_rotation_frames:
            rotation_start = (frames - tail_rotation_frames) / (frames - 1)
            t = max(0.0, (progress - rotation_start) / max(1e-9, 1.0 - rotation_start))
        yaw = total_yaw * t
        pelvis_z = travel[1] * progress
        pelvis_x = travel[0] * progress
        # Hips offset along the rotated hip line; feet under the body.
        hip_half = 0.07
        hip_dx, hip_dz = hip_half * math.cos(yaw), hip_half * math.sin(yaw)
        frames_payload.append({
            "frameIndex": index,
            "timeSec": progress * duration_seconds,
            "sourceTimeSec": 100.0 + progress * duration_seconds,
            "joints": {
                "pelvis": [pelvis_x, 0.9, pelvis_z],
                "left_hip": [pelvis_x + hip_dx, 0.85, pelvis_z + hip_dz],
                "right_hip": [pelvis_x - hip_dx, 0.85, pelvis_z - hip_dz],
                "left_foot": [pelvis_x + hip_dx, terminal_foot_y if index >= frames - 8 else 0.0, pelvis_z + hip_dz],
                "right_foot": [pelvis_x - hip_dx, terminal_foot_y if index >= frames - 8 else 0.0, pelvis_z - hip_dz],
            },
        })
    return {
        "fps": 30.0, "jointNames": list(JOINTS), "renderFloorY": 0.0,
        "frames": frames_payload,
    }


STANDING_CONTRACT = {
    "validEndState": "standing upright with feet shoulder-width apart",
    "endPoseConstraints": {"supportMode": "standing"},
}
ELEVATED_CONTRACT = {
    "validEndState": "standing upright on the surface of the adjustable bench with feet shoulder-width apart",
    "endPoseConstraints": {"supportMode": "standing"},
}


def test_ground_landing_fails_elevated_terminal_contract():
    report = contract_support_gates(build_export(terminal_foot_y=0.02), ELEVATED_CONTRACT)
    assert not report["passed"]
    assert REASON_TERMINAL_SUPPORT_NOT_ELEVATED in report["reasons"]


def test_elevated_landing_passes_elevated_terminal_contract():
    report = contract_support_gates(build_export(terminal_foot_y=0.35), ELEVATED_CONTRACT)
    assert report["passed"]
    assert report["checks"]["terminalElevatedSupport"]["passed"]


def test_rotating_endpoint_fails_standing_settle():
    report = contract_support_gates(
        build_export(yaw_degrees=90.0), STANDING_CONTRACT)
    assert not report["passed"]
    assert REASON_TERMINAL_SUPPORT_NOT_SETTLED in report["reasons"]


def test_stationary_standing_endpoint_passes_settle():
    report = contract_support_gates(build_export(), STANDING_CONTRACT)
    assert report["passed"]


def test_diagonal_rotating_travel_fails_facing_alignment():
    report = contract_support_gates(
        build_export(yaw_degrees=100.0, travel=(1.0, 0.1)), STANDING_CONTRACT)
    assert not report["passed"]
    assert REASON_TRAVEL_FACING_MISMATCH in report["reasons"]


def test_forward_travel_without_rotation_passes_facing_alignment():
    report = contract_support_gates(
        build_export(travel=(0.0, 1.0)), STANDING_CONTRACT)
    assert report["passed"]


def test_unrelated_contract_and_missing_joints_are_unavailable_not_failing():
    export = build_export()
    export["jointNames"] = ["pelvis"]
    report = contract_support_gates(export, STANDING_CONTRACT)
    assert report["available"] is False and report["passed"]
    assert contract_support_gates(build_export(), None)["passed"]


def test_settle_failure_reports_trim_repair_when_earlier_boundary_settles():
    # Rotation confined to the final 10 frames: the endpoint is unsettled but
    # a settled boundary exists inside the trim budget.
    report = contract_support_gates(
        build_export(yaw_degrees=60.0, tail_rotation_frames=12, frames=60, duration_seconds=3.0),
        STANDING_CONTRACT)
    assert not report["passed"]
    repair = report["checks"]["terminalSettle"]["repair"]
    assert repair["feasible"] is True
    assert 0 <= repair["candidateEndFrameIndex"] < 59
    assert repair["trimFrames"] > 0


def test_settle_failure_trim_repair_infeasible_when_rotation_persists():
    # Rotation spread across the whole clip: no settled boundary to trim to.
    report = contract_support_gates(
        build_export(yaw_degrees=100.0, frames=60, duration_seconds=3.0), STANDING_CONTRACT)
    assert not report["passed"]
    assert report["checks"]["terminalSettle"]["repair"]["feasible"] is False


def test_trim_repair_finds_settled_boundary_before_rotation_tail():
    from exercise_motion_pkg.bake_and_rank import (
        RankedCandidate,
        ranked_candidate_with_trimmed_source_window,
    )

    ranked = RankedCandidate(
        exercise_index=0, candidate_rank=0, exercise_id="e", exercise_name="Box Jump",
        exercise_slug="box-jump",
        candidate={"url": "u", "sourceWindowHint": {"startSeconds": 10.0, "endSeconds": 14.0}},
    )
    trimmed = ranked_candidate_with_trimmed_source_window(
        ranked, end_seconds=13.2, reason="materialized_terminal_support_not_settled")
    assert trimmed is not None
    hint = trimmed.source_chunk_hint
    assert hint.start_seconds == 10.0 and hint.end_seconds == 13.2
    assert trimmed.candidate["sourceWindowAttemptMode"] == "terminal_settle_boundary_trim"
    # A trimmed candidate must not be trimmed a second time.
    assert ranked_candidate_with_trimmed_source_window(
        trimmed, end_seconds=12.5, reason="materialized_terminal_support_not_settled") is None
    # Trims that would violate the remaining-duration minimum are refused.
    assert ranked_candidate_with_trimmed_source_window(
        ranked, end_seconds=10.4, reason="materialized_terminal_support_not_settled") is None


def test_elevated_support_contract_prefers_profile_view_band():
    from exercise_motion_pkg.contract_support_gates import (
        contract_preferred_view_band,
        contract_view_band_penalty,
    )
    band = contract_preferred_view_band(ELEVATED_CONTRACT)
    assert band is not None and band["high"] <= 0.30
    # A near-profile source is not penalized; a frontal (jump-toward-camera)
    # source is, and angle-agnostic exercises have no band at all.
    assert contract_view_band_penalty(band, 0.10) == 0.0
    assert contract_view_band_penalty(band, 0.90) > 0.0
    assert contract_preferred_view_band(STANDING_CONTRACT) is None
    assert contract_view_band_penalty(None, 0.90) == 0.0
