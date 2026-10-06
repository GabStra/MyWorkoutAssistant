"""Contract-aware deterministic gates on the materialized output skeleton.

The final-output VLM validates movement semantics, not skeletal endpoint
facts. These checks compare the delivered wear skeleton against the exercise
contract's support requirements so a clip that lands on the wrong surface, or
ends mid-motion against a standing end state, is rejected deterministically.
"""
from __future__ import annotations

import math
from typing import Any

# Matches the minimum elevation the preview requires before rendering a
# distinct support surface: no real bench/box/step is lower.
ELEVATED_SUPPORT_MIN_HEIGHT = 0.10
# Terminal rotation rate a settled standing end state must fall under
# (deg/frame at 30 Hz). An accepted standing thruster ends at ~0.1 deg/frame;
# a rejected rotating box-jump landing ends at ~3.2 deg/frame.
TERMINAL_YAW_DRIFT_LIMIT_DEGREES = 1.0
TERMINAL_WINDOW_FRAMES = 6
# A rejected unsettled endpoint is first repaired by trimming the boundary
# back to the latest settled frame. Trimming more than this fraction of the
# clip, or leaving less than this duration, discards the movement instead of
# repairing its endpoint, so the source-window retry path is used instead.
TERMINAL_TRIM_MAX_CLIP_FRACTION = 0.3
TERMINAL_TRIM_MIN_REMAINING_SECONDS = 1.0
# Lateral/rotational travel mismatch: net root travel meaningfully off the
# initial facing direction while the body also rotates in place reads as a
# different (rotational/lateral) movement than the contracted straight one.
TRAVEL_MIN_BODY_HEIGHT_RATIO = 0.4
TRAVEL_MAX_FACING_OFFSET_DEGREES = 60.0
ROTATION_MAX_TOTAL_DEGREES = 60.0

REASON_TERMINAL_SUPPORT_NOT_ELEVATED = "materialized_contract_terminal_support_not_elevated"
REASON_TERMINAL_SUPPORT_NOT_SETTLED = "materialized_terminal_support_not_settled"
REASON_TRAVEL_FACING_MISMATCH = "materialized_travel_facing_mismatch"

# Preferred frontalOrBackViewEvidence bands by contract-derived camera need.
# WHAM reconstructs what stays in-image: a jump onto elevated support travels
# toward the equipment, which only a near-profile camera keeps out of depth
# ambiguity, while in-place strength work has no angle requirement at all.
# Bands are deliberately few and derived from contract facts, never names.
PROFILE_VIEW_BAND = {"low": 0.0, "high": 0.30}
CONTRACT_VIEW_BAND_PENALTY = 0.15


def contract_preferred_view_band(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    """Camera-orientation band that keeps the contract's dominant motion in-image.

    Returns None when the exercise has no angle requirement; the generic
    observability ranking already handles that case without an angle term.
    """
    if not isinstance(contract, dict):
        return None
    if contract_requires_elevated_terminal_support(contract):
        return {**PROFILE_VIEW_BAND, "reason": "elevated_terminal_support_travel_prefers_profile_view"}
    spec = contract.get("observableMotionSpec")
    if isinstance(spec, dict) and str(spec.get("motionPattern") or "") == "body_toward_anchor":
        return {**PROFILE_VIEW_BAND, "reason": "anchor_travel_prefers_profile_view"}
    return None


def contract_view_band_penalty(
    band: dict[str, Any] | None,
    frontal_or_back_view_evidence: float | None,
) -> float:
    """Score penalty for a candidate whose view orientation leaves the band."""
    if not isinstance(band, dict) or frontal_or_back_view_evidence is None:
        return 0.0
    evidence = min(1.0, max(0.0, float(frontal_or_back_view_evidence)))
    low = float(band.get("low", 0.0))
    high = float(band.get("high", 1.0))
    distance = max(0.0, low - evidence, evidence - high)
    return CONTRACT_VIEW_BAND_PENALTY * min(1.0, distance / max(1e-9, 1.0 - (high - low)))


def _frames_and_index(export: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]] | None:
    frames = [frame for frame in (export.get("frames") or [])
              if isinstance(frame, dict) and not bool(frame.get("syntheticLoopBridge"))]
    names = [str(name) for name in (export.get("jointNames") or [])]
    index = {name: position for position, name in enumerate(names)}
    if len(frames) < 3 or not all(name in index for name in
                                  ("pelvis", "left_hip", "right_hip", "left_foot", "right_foot")):
        return None
    return frames, index


def _points(frames: list[dict[str, Any]], index: dict[str, int], *names: str) -> list[list[float]]:
    return [[frame["joints"][name] for name in names] for frame in frames]


def _hip_yaw_track(frames: list[dict[str, Any]], index: dict[str, int]) -> list[float]:
    hips = _points(frames, index, "left_hip", "right_hip")
    return [math.atan2(left[0]-right[0], left[2]-right[2]) for left, right in hips]


def _unwrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def contract_requires_elevated_terminal_support(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    end_state = " ".join(str(part) for part in (
        contract.get("validEndState"), contract.get("endState"),
    ) if part)
    return "on the surface of" in end_state.casefold()


def contract_requires_standing_terminal_state(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    constraints = contract.get("endPoseConstraints")
    if isinstance(constraints, dict):
        support = str(constraints.get("supportMode") or "").casefold()
        if support and support != "standing":
            return False
        return bool(support)
    end_state = str(contract.get("validEndState") or "").casefold()
    return "standing" in end_state


def contract_support_gates(export: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    resolved = _frames_and_index(export)
    if resolved is None or not isinstance(contract, dict):
        return {"available": False, "passed": True, "reasons": [], "checks": {}}
    frames, index = resolved
    body_height = max(
        1e-6,
        max(
            (max(point[1] for point in frame["joints"].values()) for frame in frames),
            default=1.0,
        )
        - min(min(point[1] for point in frame["joints"].values()) for frame in frames),
    )
    checks: dict[str, Any] = {}
    reasons: list[str] = []

    floor = export.get("renderFloorY")
    floor = float(floor) if isinstance(floor, (int, float)) and math.isfinite(float(floor)) else None

    if contract_requires_elevated_terminal_support(contract):
        feet = _points(frames, index, "left_foot", "right_foot")
        terminal_feet = [min(left[1], right[1]) for left, right in feet[-TERMINAL_WINDOW_FRAMES:]]
        terminal_height = sum(terminal_feet) / len(terminal_feet)
        base = floor if floor is not None else min(
            min(left[1], right[1]) for left, right in feet[:TERMINAL_WINDOW_FRAMES])
        elevation = terminal_height - base
        passed = elevation >= ELEVATED_SUPPORT_MIN_HEIGHT
        checks["terminalElevatedSupport"] = {
            "required": True, "elevationMeters": elevation, "limitMeters": ELEVATED_SUPPORT_MIN_HEIGHT,
            "passed": passed,
        }
        if not passed:
            reasons.append(REASON_TERMINAL_SUPPORT_NOT_ELEVATED)

    if contract_requires_standing_terminal_state(contract):
        yaw = _hip_yaw_track(frames, index)
        window = yaw[-(TERMINAL_WINDOW_FRAMES + 1):] or yaw
        drift = [abs(_unwrap_degrees(math.degrees(b - a))) for a, b in zip(window, window[1:])]
        mean_drift = sum(drift) / max(len(drift), 1) * (float(export.get("fps") or 30.) / 30.)
        passed = mean_drift <= TERMINAL_YAW_DRIFT_LIMIT_DEGREES
        settle = {
            "required": True, "meanYawDriftDegreesPerFrame": mean_drift,
            "limitDegreesPerFrame": TERMINAL_YAW_DRIFT_LIMIT_DEGREES, "passed": passed,
        }
        if not passed:
            settle["repair"] = _terminal_settle_trim_repair(
                export, frames, index, yaw,
                requires_elevation=contract_requires_elevated_terminal_support(contract),
                floor=floor,
            )
        checks["terminalSettle"] = settle
        if not passed:
            reasons.append(REASON_TERMINAL_SUPPORT_NOT_SETTLED)

        pelvis = [points[0] for points in _points(frames, index, "pelvis")]
        net = (pelvis[-1][0] - pelvis[0][0], pelvis[-1][2] - pelvis[0][2])
        travel = math.hypot(*net)
        hips0 = frames[0]["joints"]
        hip_x = hips0["left_hip"][0] - hips0["right_hip"][0]
        hip_z = hips0["left_hip"][2] - hips0["right_hip"][2]
        hip_norm = math.hypot(hip_x, hip_z)
        total_rotation = abs(_unwrap_degrees(math.degrees(yaw[-1] - yaw[0]))) if len(yaw) > 1 else 0.
        if travel > TRAVEL_MIN_BODY_HEIGHT_RATIO * body_height and hip_norm > 1e-9:
            # Facing is the hip-line perpendicular; sign ambiguity is resolved
            # by the shoulders, when present, else skipped as unavailable.
            forward = (-hip_z / hip_norm, hip_x / hip_norm)
            offset = abs(_unwrap_degrees(math.degrees(
                math.atan2(net[0] * forward[1] - net[1] * forward[0],
                           net[0] * forward[0] + net[1] * forward[1]))))
            facing_offset = min(offset, 180.0 - offset)
            passed = not (facing_offset > TRAVEL_MAX_FACING_OFFSET_DEGREES
                          and total_rotation > ROTATION_MAX_TOTAL_DEGREES)
            checks["travelFacingAlignment"] = {
                "required": True, "travelMeters": travel,
                "facingOffsetDegrees": facing_offset, "totalRotationDegrees": total_rotation,
                "passed": passed,
            }
            if not passed:
                reasons.append(REASON_TRAVEL_FACING_MISMATCH)

    return {"available": True, "passed": not reasons, "reasons": reasons, "checks": checks}


def _terminal_settle_trim_repair(
    export: dict[str, Any],
    frames: list[dict[str, Any]],
    index: dict[str, int],
    yaw: list[float],
    *,
    requires_elevation: bool,
    floor: float | None,
) -> dict[str, Any]:
    """Latest earlier boundary whose trailing window already settles.

    The movement-cut retry can shorten the window to this frame instead of
    discarding the candidate. Feasibility bounds keep the trim a boundary
    repair, never a content rewrite.
    """
    fps = float(export.get("fps") or 30.)
    max_trim = int(len(frames) * TERMINAL_TRIM_MAX_CLIP_FRACTION)
    for end in range(len(frames) - 2, max(2, len(frames) - 1 - max_trim), -1):
        window = yaw[max(0, end - TERMINAL_WINDOW_FRAMES):end + 1]
        drift = [abs(_unwrap_degrees(math.degrees(b - a))) for a, b in zip(window, window[1:])]
        if not drift or sum(drift) / len(drift) * (fps / 30.) > TERMINAL_YAW_DRIFT_LIMIT_DEGREES:
            continue
        if requires_elevation:
            frame = frames[end]["joints"]
            feet = min(frame["left_foot"][1], frame["right_foot"][1])
            base = floor if floor is not None else min(
                min(f["joints"]["left_foot"][1], f["joints"]["right_foot"][1])
                for f in frames[:TERMINAL_WINDOW_FRAMES])
            if feet - base < ELEVATED_SUPPORT_MIN_HEIGHT:
                continue
        remaining = float(frames[end].get("timeSec", end / fps))
        if remaining < TERMINAL_TRIM_MIN_REMAINING_SECONDS:
            return {"feasible": False, "reason": "remaining_duration_below_minimum"}
        return {
            "feasible": True,
            "candidateEndFrameIndex": end,
            "sourceTimeSec": frames[end].get("sourceTimeSec", frames[end].get("timeSec")),
            "trimFrames": len(frames) - 1 - end,
            "remainingDurationSec": remaining,
            "trimLimitClipFraction": TERMINAL_TRIM_MAX_CLIP_FRACTION,
        }
    return {"feasible": False, "reason": "no_settled_boundary_within_trim_budget"}
