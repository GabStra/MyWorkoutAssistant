"""Kinematic source-cut proposal from pose keypoint time series.

The exercise motion contract vocabulary is closed by construction (support
modes, hand heights, torso orientations, knee states, stances, completion
modes), so a finite predicate library can score any contract against the
dominant-pose samples the YOLO prefilter already persists per candidate.
A data-driven dominant-motion signal (first principal component of joint
deviations) locates movement cycles without any per-exercise mapping, and
the contract's completion mode picks the cut policy. The VLM scorecard then
verifies one proposed cut instead of searching a grid of arbitrary ones.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

# Joints used for the dominant-motion feature matrix. Eyes and ears are
# excluded because head motion rarely defines a repetition and face crops
# carry no additional cycle information.
FEATURE_JOINTS: tuple[str, ...] = (
    "nose",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

MIN_CORE_JOINTS = 6
MIN_SAMPLE_INTERVAL_SECONDS = 0.05
DEFAULT_MIN_CYCLE_SECONDS = 0.75
DEFAULT_MAX_CYCLE_SECONDS = 20.0
DEFAULT_CYCLE_MARGIN_SECONDS = 0.25
DEFAULT_SPAN_PAD_SECONDS = 4.0
MIN_SIGNAL_QUALITY = 0.12
MIN_AMPLITUDE_TORSO_UNITS = 0.10
HOLD_MAX_MOTION_ENERGY_SCALE = 0.45
SUSTAINED_STATE_SECONDS = 0.5

_CYCLE_POLICIES = {
    "return_to_start",
    "representative_cycle",
    "alternating_pair",
    "active_travel",
}
# Closed cycles snap both ends to the start pose. One-way cuts (distinct_end_state,
# active_travel) may snap the start, but never require the start pose at the end.
_LOOPING_COMPLETION_MODES = {
    "return_to_start",
    "representative_cycle",
    "alternating_pair",
}
POSE_MATCH_THRESHOLD = 0.55
MAX_POSE_SNAP_SECONDS = 2.0
POSE_DWELL_PAD_SECONDS = 1.0
MAX_SIGNAL_SNAP_SECONDS = 2.0
SIGNAL_QUIET_DWELL_SECONDS = 1.0

_MOVEMENT_TYPE_COMPLETION_MODES = {
    "hold": "stable_hold",
    "carry": "active_travel",
    "cyclic": "representative_cycle",
    "transition_sequence": "distinct_end_state",
    "repetition": "return_to_start",
}


@dataclass(frozen=True)
class PoseFrame:
    """One dominant-person pose sample in normalized image coordinates."""

    time_seconds: float
    confidence: float
    keypoints: dict[str, tuple[float, float, float]]


@dataclass(frozen=True)
class SignalResult:
    """Dominant 1-D motion signal plus quality diagnostics."""

    times: tuple[float, ...]
    signal: tuple[float, ...]
    energy: tuple[float, ...]
    explained_variance_ratio: float
    body_scale: float
    mean_confidence: float
    joint_coverage: float

    @property
    def quality(self) -> float:
        return self.explained_variance_ratio * self.joint_coverage * self.mean_confidence


@dataclass(frozen=True)
class CutProposal:
    """A proposed source cut in original-video seconds."""

    start_seconds: float
    end_seconds: float
    policy: str
    confidence: float
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def parse_dominant_pose_samples(payload: Sequence[dict[str, Any]] | None) -> list[PoseFrame]:
    """Parse ``dominantPoseSamples`` payload entries into pose frames."""
    frames: list[PoseFrame] = []
    if not payload:
        return frames
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        try:
            time_seconds = float(entry.get("timeSeconds"))
        except (TypeError, ValueError):
            continue
        keypoints: dict[str, tuple[float, float, float]] = {}
        raw_keypoints = entry.get("keypoints")
        if isinstance(raw_keypoints, dict):
            for name, point in raw_keypoints.items():
                if isinstance(point, Sequence) and len(point) >= 2:
                    try:
                        x, y = float(point[0]), float(point[1])
                        confidence = float(point[2]) if len(point) >= 3 else 1.0
                    except (TypeError, ValueError):
                        continue
                    keypoints[str(name)] = (x, y, confidence)
        if len(keypoints) < MIN_CORE_JOINTS:
            continue
        try:
            confidence = float(entry.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        frames.append(PoseFrame(time_seconds, confidence, keypoints))
    frames.sort(key=lambda frame: frame.time_seconds)
    return frames


def _pair_mid(frame: PoseFrame, base: str) -> tuple[float, float] | None:
    left = frame.keypoints.get(f"left_{base}")
    right = frame.keypoints.get(f"right_{base}")
    if left is None or right is None:
        point = left or right
        if point is None:
            return None
        return (point[0], point[1])
    return ((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0)


def _torso_length(frame: PoseFrame) -> float | None:
    shoulder = _pair_mid(frame, "shoulder")
    hip = _pair_mid(frame, "hip")
    if shoulder is None or hip is None:
        return None
    length = math.hypot(shoulder[0] - hip[0], shoulder[1] - hip[1])
    return length if length > 1e-4 else None


def _joint_angle(first: tuple[float, ...], mid: tuple[float, ...], last: tuple[float, ...]) -> float | None:
    try:
        ax, ay = float(first[0]), float(first[1])
        bx, by = float(mid[0]), float(mid[1])
        cx, cy = float(last[0]), float(last[1])
    except (TypeError, ValueError, IndexError):
        return None
    v1 = (ax - bx, ay - by)
    v2 = (cx - bx, cy - by)
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cosine = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cosine))


def _knee_angle(frame: PoseFrame) -> float | None:
    angles: list[float] = []
    for side in ("left", "right"):
        hip = frame.keypoints.get(f"{side}_hip")
        knee = frame.keypoints.get(f"{side}_knee")
        ankle = frame.keypoints.get(f"{side}_ankle")
        if hip is None or knee is None or ankle is None:
            continue
        angle = _joint_angle(hip, knee, ankle)
        if angle is not None:
            angles.append(angle)
    if not angles:
        return None
    return statistics.mean(angles)


def _torso_tilt_degrees(frame: PoseFrame) -> float | None:
    """Angle of the hip->shoulder axis away from vertical (image up)."""
    shoulder = _pair_mid(frame, "shoulder")
    hip = _pair_mid(frame, "hip")
    if shoulder is None or hip is None:
        return None
    dx = shoulder[0] - hip[0]
    dy = shoulder[1] - hip[1]
    if math.hypot(dx, dy) < 1e-6:
        return None
    return math.degrees(math.atan2(abs(dx), -dy))


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _band_score(value: float | None, low_edge: tuple[float, float], high_edge: tuple[float, float]) -> float:
    """Score how well ``value`` sits inside a band, 1 inside, 0 outside."""
    if value is None:
        return 0.0
    below = 1.0 - _smoothstep(low_edge[0], low_edge[1], value)
    above = _smoothstep(high_edge[0], high_edge[1], value)
    return min(below, above)


def support_mode_scores(frame: PoseFrame) -> dict[str, float]:
    """Per-frame soft scores for the closed supportMode vocabulary."""
    scores = {"standing": 0.0, "seated": 0.0, "lying": 0.0, "kneeling": 0.0, "hanging": 0.0}
    body_scale = _torso_length(frame) or 0.25
    shoulder = _pair_mid(frame, "shoulder")
    hip = _pair_mid(frame, "hip")
    if shoulder is None or hip is None:
        return scores
    tilt = _torso_tilt_degrees(frame)
    knee = _knee_angle(frame)
    left_wrist = frame.keypoints.get("left_wrist")
    right_wrist = frame.keypoints.get("right_wrist")
    wrist_y: list[float] = []
    for point in (left_wrist, right_wrist):
        if point is not None:
            wrist_y.append(point[1])
    ankles = [frame.keypoints.get(f"{side}_ankle") for side in ("left", "right")]
    ankle_points = [point for point in ankles if point is not None]
    knees = [frame.keypoints.get(f"{side}_knee") for side in ("left", "right")]
    knee_points = [point for point in knees if point is not None]
    upright = 1.0 - _smoothstep(35.0, 60.0, 90.0 if tilt is None else tilt)
    horizontal = _smoothstep(50.0, 70.0, 0.0 if tilt is None else tilt)

    standing_knee = _smoothstep(140.0, 160.0, knee or 0.0)
    if ankle_points:
        lowest_body = max(point[1] for point in ankle_points)
        grounded = _smoothstep(hip[1], hip[1] + 0.5 * body_scale, lowest_body)
        scores["standing"] = upright * standing_knee * grounded
    else:
        scores["standing"] = upright * standing_knee * 0.5

    if knee_points and ankle_points:
        knee_y = max(point[1] for point in knee_points)
        ankle_y = max(point[1] for point in ankle_points)
        knees_at_floor = _smoothstep(ankle_y - 0.2 * body_scale, ankle_y + 0.1 * body_scale, knee_y)
        scores["kneeling"] = upright * knees_at_floor * (1.0 - standing_knee)
        seated_hips_low = 1.0 - _smoothstep(0.35, 0.6, (hip[1] - shoulder[1]) / body_scale) if body_scale > 0 else 0.0
        scores["seated"] = upright * (1.0 - standing_knee) * (1.0 - knees_at_floor) * seated_hips_low
    # Lying covers any horizontal torso: supine, prone, and plank shapes
    # keep shoulders and hips at similar heights, so only the tilt matters.
    scores["lying"] = horizontal

    if wrist_y:
        wrists_above_shoulders = 1.0 - _smoothstep(
            shoulder[1] - 0.1 * body_scale, shoulder[1] + 0.1 * body_scale, min(wrist_y)
        )
        body_below_grip = _smoothstep(shoulder[1], shoulder[1] + 0.3 * body_scale, hip[1])
        scores["hanging"] = wrists_above_shoulders * body_below_grip * max(0.2, standing_knee)
    return scores


def hand_height_score(frame: PoseFrame, term: str) -> float:
    """Score handHeight vocabulary terms from wrist height versus torso landmarks."""
    shoulder = _pair_mid(frame, "shoulder")
    hip = _pair_mid(frame, "hip")
    if shoulder is None or hip is None:
        return 0.0
    body_scale = _torso_length(frame) or 0.25
    wrist = _pair_mid(frame, "wrist")
    if wrist is None:
        return 0.0
    # Height above hip along the torso axis, in torso units. Image y grows
    # downward, so a positive value places the hands above the hips.
    height_units = (hip[1] - wrist[1]) / body_scale
    if term == "above_head":
        return _smoothstep(0.9, 1.4, height_units)
    if term == "shoulder_chest":
        return _band_score(height_units, (0.15, 0.05), (0.7, 0.95))
    if term == "hip":
        return _band_score(height_units, (-0.25, -0.15), (0.2, 0.35))
    if term == "below_hips":
        return _smoothstep(-0.15, -0.45, -height_units)
    return 1.0


def torso_orientation_score(frame: PoseFrame, term: str) -> float:
    tilt = _torso_tilt_degrees(frame)
    if tilt is None:
        return 0.0
    if term == "upright":
        return 1.0 - _smoothstep(25.0, 50.0, tilt)
    if term == "hinged":
        return _band_score(tilt, (20.0, 35.0), (65.0, 80.0))
    if term == "horizontal":
        return _smoothstep(55.0, 75.0, tilt)
    return 1.0


def knee_state_score(frame: PoseFrame, term: str) -> float:
    angle = _knee_angle(frame)
    if angle is None:
        return 0.0
    if term == "extended":
        return _smoothstep(140.0, 160.0, angle)
    if term == "flexed":
        return _band_score(angle, (60.0, 80.0), (130.0, 150.0))
    if term == "deep_flexion":
        return 1.0 - _smoothstep(80.0, 100.0, angle)
    return 1.0


def stance_score(frame: PoseFrame, term: str) -> float:
    left_ankle = frame.keypoints.get("left_ankle")
    right_ankle = frame.keypoints.get("right_ankle")
    left_hip = frame.keypoints.get("left_hip")
    right_hip = frame.keypoints.get("right_hip")
    if left_ankle is None or right_ankle is None or left_hip is None or right_hip is None:
        return 1.0 if term in ("any",) else 0.5
    hip_width = abs(left_hip[0] - right_hip[0]) or 0.1
    ankle_width = abs(left_ankle[0] - right_ankle[0])
    ratio = ankle_width / hip_width
    fore_aft = abs(left_ankle[1] - right_ankle[1]) / hip_width
    if term == "narrow":
        return 1.0 - _smoothstep(0.8, 1.1, ratio)
    if term == "shoulder_width":
        return _band_score(ratio, (0.7, 0.9), (1.6, 2.0))
    if term == "wide":
        return _smoothstep(1.7, 2.2, ratio)
    if term == "split":
        return _smoothstep(0.35, 0.7, fore_aft) * (1.0 - _smoothstep(1.4, 1.8, ratio) * 0.5)
    return 1.0


def pose_state_score(frame: PoseFrame, constraints: dict[str, Any] | None) -> float:
    """Mean score of the non-``any`` pose constraints for one frame."""
    if not isinstance(constraints, dict) or not constraints:
        return 1.0
    evaluators = {
        "supportMode": lambda term: support_mode_scores(frame).get(term, 0.0),
        "handHeight": lambda term: hand_height_score(frame, term),
        "torsoOrientation": lambda term: torso_orientation_score(frame, term),
        "kneeState": lambda term: knee_state_score(frame, term),
        "stance": lambda term: stance_score(frame, term),
    }
    scores: list[float] = []
    for key, evaluate in evaluators.items():
        term = str(constraints.get(key) or "any").strip().lower()
        if term in ("", "any", "none"):
            continue
        scores.append(evaluate(term))
    if not scores:
        return 1.0
    return statistics.mean(scores)


def _median_body_scale(frames: Sequence[PoseFrame]) -> float:
    lengths = [length for length in (_torso_length(frame) for frame in frames) if length]
    if lengths:
        return statistics.median(lengths)
    return 0.25


def _build_feature_matrix(frames: Sequence[PoseFrame]) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Build the per-joint deviation matrix in torso-normalized units."""
    body_scale = _median_body_scale(frames)
    feature_count = len(FEATURE_JOINTS) * 2
    raw = np.full((len(frames), feature_count), np.nan, dtype=np.float64)
    for row, frame in enumerate(frames):
        for column, joint in enumerate(FEATURE_JOINTS):
            point = frame.keypoints.get(joint)
            if point is None:
                continue
            raw[row, column * 2] = point[0]
            raw[row, column * 2 + 1] = point[1]
    # Interpolate missing joints over time so short dropouts do not split
    # the signal; fully-missing columns collapse to zero deviation.
    for column in range(feature_count):
        series = raw[:, column]
        valid = np.isfinite(series)
        if valid.sum() >= 2:
            raw[:, column] = np.interp(np.arange(len(series)), np.flatnonzero(valid), series[valid])
        else:
            raw[:, column] = 0.0
    coverage = float(np.mean(np.any(np.isfinite(raw), axis=1)))
    deviations = (raw - np.median(raw, axis=0)) / body_scale
    return deviations, np.array([frame.time_seconds for frame in frames]), body_scale, coverage  # type: ignore[return-value]


def dominant_motion_signal(frames: Sequence[PoseFrame]) -> SignalResult | None:
    """First principal component of joint deviations: the rep axis, learned from data."""
    if len(frames) < 8:
        return None
    deviations, times, body_scale, coverage = _build_feature_matrix(frames)
    covariance = deviations.T @ deviations
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    top = order[0]
    total_variance = float(np.sum(eigenvalues))
    if total_variance <= 1e-12:
        return None
    explained_variance_ratio = float(eigenvalues[top] / total_variance)
    direction = eigenvectors[:, top]
    signal = deviations @ direction
    # Canonical sign: the strongest excursion is positive.
    if float(np.max(signal)) < -float(np.min(signal)):
        signal = -signal
        direction = -direction
    smoothed = _centered_median_filter(signal, width=5)
    speed = np.gradient(smoothed, times) if len(times) >= 3 else np.zeros_like(smoothed)
    joint_presence = [
        len([joint for joint in FEATURE_JOINTS if joint in frame.keypoints]) / len(FEATURE_JOINTS)
        for frame in frames
    ]
    return SignalResult(
        times=tuple(float(value) for value in times),
        signal=tuple(float(value) for value in smoothed),
        energy=tuple(float(value) for value in speed),
        explained_variance_ratio=explained_variance_ratio,
        body_scale=body_scale,
        mean_confidence=float(statistics.mean(frame.confidence for frame in frames)),
        joint_coverage=float(statistics.mean(joint_presence)) * coverage,
    )


def _centered_median_filter(values: np.ndarray, *, width: int) -> np.ndarray:
    if width < 3 or len(values) < width:
        return values.copy()
    half = width // 2
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, width)
    return np.median(windows, axis=1)


def _robust_sigma(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    return 1.4826 * mad


@dataclass(frozen=True)
class Cycle:
    start_seconds: float
    end_seconds: float
    amplitude: float
    duration_seconds: float
    peak_seconds: float = 0.0

    def overlaps(self, start: float, end: float) -> bool:
        return self.start_seconds < end and start < self.end_seconds

    def contains(self, start: float, end: float, *, pad: float = 0.0) -> bool:
        return self.start_seconds - pad <= start and end <= self.end_seconds + pad


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if bool(value):
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def detect_cycles(
    signal: SignalResult,
    *,
    min_cycle_seconds: float = DEFAULT_MIN_CYCLE_SECONDS,
    max_cycle_seconds: float = DEFAULT_MAX_CYCLE_SECONDS,
    margin_seconds: float = DEFAULT_CYCLE_MARGIN_SECONDS,
) -> list[Cycle]:
    """Signed baseline excursions: leave the baseline band on one side,
    travel, and return. Both the leave and the return must cross the
    baseline, so half-cycles that hover above the median do not count."""
    times = np.asarray(signal.times)
    values = np.asarray(signal.signal)
    if len(values) < 8:
        return []
    baseline = float(np.median(values))
    sigma = max(_robust_sigma(values.tolist()), 1e-3)
    deviation = np.abs(values - baseline)
    # Noise-relative thresholds must stay below the observed peak deviation,
    # otherwise continuously-moving signals (MAD comparable to amplitude)
    # never cross the enter threshold. Anchor both bands to the 95th
    # percentile deviation and apply the visible-displacement floor.
    peak_deviation = max(float(np.percentile(deviation, 95)), 1e-3)
    if peak_deviation < MIN_AMPLITUDE_TORSO_UNITS:
        # Nothing moves a visible amount: only keypoint jitter.
        return []
    enter = min(max(1.5 * sigma, MIN_AMPLITUDE_TORSO_UNITS), 0.6 * peak_deviation)
    exit_band = 0.5 * enter

    median_step = float(np.median(np.diff(times))) if len(times) > 1 else 0.125
    margin = max(1, round(margin_seconds / median_step)) if median_step > 0 else 1

    def index_before(run_start: int) -> int:
        return max(0, run_start - 1)

    def index_after(run_end: int) -> int:
        return min(len(values) - 1, run_end + 1)

    cycles: list[Cycle] = []
    positive = (values - baseline) > exit_band
    negative = (baseline - values) > exit_band
    for mask, signed_values in ((positive, values - baseline), (negative, baseline - values)):
        for run_start, run_end in _true_runs(mask):
            segment = signed_values[run_start : run_end + 1]
            if len(segment) == 0:
                continue
            peak = float(np.max(segment))
            if peak < enter:
                continue
            start_index = index_before(run_start)
            end_index = index_after(run_end)
            start_time = float(times[max(0, start_index - margin)])
            end_time = float(times[min(len(times) - 1, end_index + margin)])
            duration = end_time - start_time
            if duration < min_cycle_seconds or duration > max_cycle_seconds:
                continue
            peak_offset = int(run_start) + int(np.argmax(segment))
            cycles.append(
                Cycle(
                    start_seconds=start_time,
                    end_seconds=end_time,
                    amplitude=peak,
                    duration_seconds=duration,
                    peak_seconds=float(times[peak_offset]),
                )
            )
    cycles.sort(key=lambda cycle: cycle.start_seconds)
    return cycles


def _state_series(
    frames: Sequence[PoseFrame],
    constraints: dict[str, Any] | None,
) -> list[float]:
    return [pose_state_score(frame, constraints) for frame in frames]


def _sustained_runs(scores: Sequence[float], times: Sequence[float], threshold: float) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, score in enumerate(scores):
        if score >= threshold:
            if start is None:
                start = index
        elif start is not None:
            if (times[index - 1] - times[start]) >= SUSTAINED_STATE_SECONDS:
                runs.append((start, index - 1))
            start = None
    if start is not None and (times[-1] - times[start]) >= SUSTAINED_STATE_SECONDS:
        runs.append((start, len(scores) - 1))
    return runs


def _cycle_proposals(
    frames: Sequence[PoseFrame],
    signal: SignalResult,
    contract: dict[str, Any],
    *,
    max_proposals: int,
) -> list[CutProposal]:
    cycles = detect_cycles(signal)
    if not cycles:
        return []
    start_constraints = contract.get("startPoseConstraints")
    end_constraints = contract.get("endPoseConstraints")
    looping = contract_completion_mode(contract) in _LOOPING_COMPLETION_MODES
    durations = [cycle.duration_seconds for cycle in cycles]
    median_duration = statistics.median(durations)
    scored: list[tuple[float, int, Cycle]] = []
    for index, cycle in enumerate(cycles):
        regularity = 1.0
        if len(cycles) > 1:
            spread = abs(cycle.duration_seconds - median_duration) / median_duration
            regularity = max(0.2, 1.0 - spread)
        # A return-to-start cycle starts and ends near the contract's start
        # pose while its extreme travels away from it; excursions that peak
        # in the start pose (e.g. standing around) rank lower.
        boundary_score = _boundary_state_score(frames, signal, cycle, start_constraints)
        away_score = 1.0 - _peak_state_score(frames, signal, cycle, start_constraints)
        score = min(cycle.amplitude, 1.0) * regularity * (0.5 + 0.5 * boundary_score) * (0.6 + 0.4 * away_score)
        scored.append((score, index, cycle))
    scored.sort(key=lambda item: (-item[0], item[1]))
    proposals: list[CutProposal] = []
    for score, _, cycle in scored[:max_proposals]:
        start_seconds, end_seconds = cycle.start_seconds, cycle.end_seconds
        if looping:
            start_seconds, end_seconds = _refine_cycle_bounds_to_signal(
                signal=signal,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                peak_seconds=cycle.peak_seconds,
            )
        if _has_usable_pose_constraints(start_constraints) or _has_usable_pose_constraints(end_constraints):
            start_seconds, end_seconds = _refine_cycle_bounds_to_poses(
                frames=frames,
                signal=signal,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                start_constraints=start_constraints if isinstance(start_constraints, dict) else None,
                end_constraints=end_constraints if isinstance(end_constraints, dict) else None,
                looping=looping,
            )
        proposals.append(
            CutProposal(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                policy="cycle_return_to_start",
                confidence=max(0.0, min(1.0, score * signal.quality)),
                stats={
                    "amplitudeTorsoUnits": cycle.amplitude,
                    "durationSeconds": end_seconds - start_seconds,
                    "cycleCount": float(len(cycles)),
                    "explainedVarianceRatio": signal.explained_variance_ratio,
                },
            )
        )
    return proposals


def _has_usable_pose_constraints(constraints: dict[str, Any] | None) -> bool:
    if not isinstance(constraints, dict):
        return False
    for key in ("supportMode", "handHeight", "torsoOrientation", "kneeState", "stance"):
        term = str(constraints.get(key) or "any").strip().lower()
        if term not in {"", "any", "none"}:
            return True
    return False


def _nearest_time_index(times: Sequence[float], target_seconds: float) -> int:
    return min(range(len(times)), key=lambda index: abs(times[index] - target_seconds))


def _signal_turning_indices(values: np.ndarray) -> tuple[list[int], list[int]]:
    """Local maxima and minima of the smoothed 1-D motion signal."""
    maxima: list[int] = []
    minima: list[int] = []
    if len(values) < 3:
        return maxima, minima
    deriv = np.diff(values)
    for index in range(1, len(values) - 1):
        left = float(deriv[index - 1])
        right = float(deriv[index])
        if left > 0 and right <= 0:
            maxima.append(index)
        elif left < 0 and right >= 0:
            minima.append(index)
    if float(values[0]) <= float(values[1]):
        minima.insert(0, 0)
    else:
        maxima.insert(0, 0)
    last = len(values) - 1
    if float(values[last]) <= float(values[last - 1]):
        minima.append(last)
    else:
        maxima.append(last)
    return maxima, minima


def _first_index_in_direction(
    candidates: Sequence[int],
    *,
    origin_index: int,
    direction: int,
    stop_index: int,
    times: Sequence[float],
    max_extra_seconds: float,
) -> int | None:
    origin_time = times[origin_index]
    chosen: int | None = None
    chosen_delta = float("inf")
    for index in candidates:
        if direction > 0:
            if index <= origin_index or index > stop_index:
                continue
        elif index >= origin_index or index < stop_index:
            continue
        delta = abs(times[index] - origin_time)
        if delta > max_extra_seconds + 1e-9 or delta >= chosen_delta:
            continue
        chosen = index
        chosen_delta = delta
    return chosen


def _walk_while_quiet(
    energy: Sequence[float],
    times: Sequence[float],
    *,
    origin_index: int,
    direction: int,
    stop_index: int,
    quiet_cap: float,
    max_extra_seconds: float,
) -> int:
    origin_time = times[origin_index]
    index = origin_index
    last_index = len(times) - 1
    while True:
        nxt = index + direction
        if nxt < 0 or nxt > last_index:
            break
        if direction > 0 and nxt > stop_index:
            break
        if direction < 0 and nxt < stop_index:
            break
        if abs(times[nxt] - origin_time) > max_extra_seconds + 1e-9:
            break
        if abs(float(energy[nxt])) > quiet_cap:
            break
        index = nxt
    return index


def _refine_cycle_bounds_to_signal(
    *,
    signal: SignalResult,
    start_seconds: float,
    end_seconds: float,
    peak_seconds: float,
) -> tuple[float, float]:
    """Close a looping cycle to the rest-side turning points of the 1-D signal.

    PCA re-entry is a return to the median, not to the visible start pose.
    For a periodic excursion the start pose is the opposite turning point from
    the peak, so both bounds walk to the nearest rest-side extremum. If none
    exists inside the cap, a short low-energy dwell is kept so a slow finish
    is not cut off.
    """
    times = list(signal.times)
    values = np.asarray(signal.signal, dtype=np.float64)
    energy = np.asarray(signal.energy, dtype=np.float64)
    if len(times) < 3 or end_seconds <= start_seconds:
        return start_seconds, end_seconds
    start_index = _nearest_time_index(times, start_seconds)
    end_index = _nearest_time_index(times, end_seconds)
    peak_index = _nearest_time_index(times, peak_seconds)
    if end_index <= start_index:
        return start_seconds, end_seconds
    last_index = len(times) - 1
    peak_index = min(max(start_index, peak_index), end_index)
    median_value = float(np.median(values))
    peak_is_maximum = float(values[peak_index]) >= median_value
    maxima, minima = _signal_turning_indices(values)
    rest_indices = minima if peak_is_maximum else maxima
    cycle_energy = np.abs(energy[start_index : end_index + 1])
    peak_energy = float(np.max(cycle_energy)) if len(cycle_energy) else 0.0
    quiet_cap = max(0.2 * peak_energy, 1e-4)
    new_start_index = _first_index_in_direction(
        rest_indices,
        origin_index=start_index,
        direction=-1,
        stop_index=0,
        times=times,
        max_extra_seconds=MAX_SIGNAL_SNAP_SECONDS,
    )
    if new_start_index is None:
        new_start_index = _walk_while_quiet(
            energy,
            times,
            origin_index=start_index,
            direction=-1,
            stop_index=0,
            quiet_cap=quiet_cap,
            max_extra_seconds=SIGNAL_QUIET_DWELL_SECONDS,
        )
    new_end_index = _first_index_in_direction(
        rest_indices,
        origin_index=end_index,
        direction=1,
        stop_index=last_index,
        times=times,
        max_extra_seconds=MAX_SIGNAL_SNAP_SECONDS,
    )
    if new_end_index is None:
        new_end_index = _walk_while_quiet(
            energy,
            times,
            origin_index=end_index,
            direction=1,
            stop_index=last_index,
            quiet_cap=quiet_cap,
            max_extra_seconds=SIGNAL_QUIET_DWELL_SECONDS,
        )
    new_start_index = min(new_start_index, peak_index)
    new_end_index = max(new_end_index, peak_index)
    if new_end_index <= new_start_index:
        return start_seconds, end_seconds
    refined_start = times[new_start_index]
    refined_end = times[new_end_index]
    if refined_end - refined_start < DEFAULT_MIN_CYCLE_SECONDS:
        return start_seconds, end_seconds
    if refined_end - refined_start > DEFAULT_MAX_CYCLE_SECONDS:
        return start_seconds, end_seconds
    return refined_start, refined_end


def _snap_index_to_pose(
    *,
    scores: Sequence[float],
    times: Sequence[float],
    origin_index: int,
    direction: int,
    stop_index: int,
    threshold: float = POSE_MATCH_THRESHOLD,
    max_extra_seconds: float = MAX_POSE_SNAP_SECONDS,
    dwell_pad_seconds: float = POSE_DWELL_PAD_SECONDS,
) -> int:
    """Move a bound toward a matching pose, then keep a short readable dwell.

    Looping cuts search for the start pose after PCA re-entry. One-way cuts
    search for the start pose behind the transition and the end pose after it.
    A missing match leaves the original bound in place.
    """
    if direction not in (-1, 1) or not scores or not times:
        return origin_index
    last_index = len(scores) - 1
    origin_index = min(max(0, origin_index), last_index)
    origin_time = times[origin_index]

    def allowed(index: int) -> bool:
        if index < 0 or index > last_index:
            return False
        if direction < 0 and index < stop_index:
            return False
        if direction > 0 and index > stop_index:
            return False
        return abs(times[index] - origin_time) <= max_extra_seconds + 1e-9

    match_index: int | None = origin_index if scores[origin_index] >= threshold else None
    if match_index is None:
        cursor = origin_index
        while True:
            nxt = cursor + direction
            if not allowed(nxt):
                break
            cursor = nxt
            if scores[cursor] >= threshold:
                match_index = cursor
                break
    if match_index is None:
        return origin_index
    index = match_index
    dwell_origin = times[match_index]
    while True:
        nxt = index + direction
        if not allowed(nxt) or scores[nxt] < threshold:
            break
        if abs(times[nxt] - dwell_origin) > dwell_pad_seconds + 1e-9:
            break
        index = nxt
    return index


def _refine_cycle_bounds_to_poses(
    *,
    frames: Sequence[PoseFrame],
    signal: SignalResult,
    start_seconds: float,
    end_seconds: float,
    start_constraints: dict[str, Any] | None,
    end_constraints: dict[str, Any] | None,
    looping: bool,
    start_stop_index: int | None = None,
    end_stop_index: int | None = None,
) -> tuple[float, float]:
    times = list(signal.times)
    if len(times) < 2 or end_seconds <= start_seconds:
        return start_seconds, end_seconds
    start_index = _nearest_time_index(times, start_seconds)
    end_index = _nearest_time_index(times, end_seconds)
    if end_index <= start_index:
        return start_seconds, end_seconds
    peak_index = _nearest_time_index(times, 0.5 * (start_seconds + end_seconds))
    last_index = len(times) - 1
    start_limit = 0 if start_stop_index is None else min(max(0, start_stop_index), last_index)
    end_limit = last_index if end_stop_index is None else min(max(0, end_stop_index), last_index)
    new_start_index = start_index
    new_end_index = end_index
    if _has_usable_pose_constraints(start_constraints):
        start_scores = _state_series(frames, start_constraints)
        new_start_index = _snap_index_to_pose(
            scores=start_scores,
            times=times,
            origin_index=start_index,
            direction=-1,
            stop_index=start_limit,
        )
        if looping:
            new_end_index = _snap_index_to_pose(
                scores=start_scores,
                times=times,
                origin_index=end_index,
                direction=1,
                stop_index=end_limit,
            )
    if not looping and _has_usable_pose_constraints(end_constraints):
        end_scores = _state_series(frames, end_constraints)
        new_end_index = _snap_index_to_pose(
            scores=end_scores,
            times=times,
            origin_index=end_index,
            direction=1,
            stop_index=end_limit,
        )
    new_start_index = min(new_start_index, peak_index)
    new_end_index = max(new_end_index, peak_index)
    if new_end_index <= new_start_index:
        return start_seconds, end_seconds
    refined_start = times[new_start_index]
    refined_end = times[new_end_index]
    if refined_end - refined_start < DEFAULT_MIN_CYCLE_SECONDS:
        return start_seconds, end_seconds
    if refined_end - refined_start > DEFAULT_MAX_CYCLE_SECONDS:
        return start_seconds, end_seconds
    return refined_start, refined_end


def _state_score_at(frames: Sequence[PoseFrame], signal: SignalResult, target_seconds: float, constraints: dict[str, Any] | None) -> float:
    times = signal.times
    index = min(range(len(times)), key=lambda i: abs(times[i] - target_seconds))
    values = [pose_state_score(frames[i], constraints) for i in range(max(0, index - 1), min(len(frames), index + 2))]
    return statistics.mean(values) if values else 1.0


def _boundary_state_score(
    frames: Sequence[PoseFrame],
    signal: SignalResult,
    cycle: Cycle,
    constraints: dict[str, Any] | None,
) -> float:
    scores = [
        _state_score_at(frames, signal, cycle.start_seconds, constraints),
        _state_score_at(frames, signal, cycle.end_seconds, constraints),
    ]
    return statistics.mean(scores)


def _peak_state_score(
    frames: Sequence[PoseFrame],
    signal: SignalResult,
    cycle: Cycle,
    constraints: dict[str, Any] | None,
) -> float:
    return _state_score_at(frames, signal, cycle.peak_seconds, constraints)


def _distinct_end_state_proposals(
    frames: Sequence[PoseFrame],
    signal: SignalResult,
    contract: dict[str, Any],
    *,
    max_proposals: int,
) -> list[CutProposal]:
    times = list(signal.times)
    start_scores = _state_series(frames, contract.get("startPoseConstraints"))
    end_scores = _state_series(frames, contract.get("endPoseConstraints"))
    start_runs = _sustained_runs(start_scores, times, threshold=POSE_MATCH_THRESHOLD)
    end_runs = _sustained_runs(end_scores, times, threshold=POSE_MATCH_THRESHOLD)
    proposals: list[CutProposal] = []
    for end_start, end_stop in end_runs[:max_proposals]:
        prior_starts = [run for run in start_runs if run[1] < end_start]
        if not prior_starts:
            continue
        start_run = prior_starts[-1]
        start_seconds = times[start_run[1]]
        end_seconds = times[end_start]
        start_seconds, end_seconds = _refine_cycle_bounds_to_poses(
            frames=frames,
            signal=signal,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            start_constraints=contract.get("startPoseConstraints")
            if isinstance(contract.get("startPoseConstraints"), dict)
            else None,
            end_constraints=contract.get("endPoseConstraints")
            if isinstance(contract.get("endPoseConstraints"), dict)
            else None,
            looping=False,
            start_stop_index=start_run[0],
            end_stop_index=end_stop,
        )
        if end_seconds - start_seconds < DEFAULT_MIN_CYCLE_SECONDS:
            continue
        proposals.append(
            CutProposal(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                policy="distinct_end_state",
                confidence=0.6 * signal.quality,
                stats={},
            )
        )
    return proposals


def _stable_hold_proposals(
    frames: Sequence[PoseFrame],
    signal: SignalResult,
    contract: dict[str, Any],
    *,
    max_proposals: int,
) -> list[CutProposal]:
    times = list(signal.times)
    state_scores = _state_series(frames, contract.get("startPoseConstraints") or contract.get("endPoseConstraints"))
    energy = np.abs(np.asarray(signal.energy))
    # Calm must compare against an absolute displacement rate (torso units
    # per second); a purely relative threshold flags half of uniform jitter
    # as motion. A visible repetition moves >0.1 torso units in ~1s.
    calm_cap = max(HOLD_MAX_MOTION_ENERGY_SCALE, 0.25 * float(np.percentile(energy, 90)))
    calm = (energy <= calm_cap).tolist()
    scores = [0.5 * state + 0.5 * float(calm_value) for state, calm_value in zip(state_scores, calm)]
    runs = _sustained_runs(scores, times, threshold=0.6)
    runs = [run for run in runs if calm[run[0]] and calm[run[1]]]
    if not runs:
        return []
    runs.sort(key=lambda run: times[run[1]] - times[run[0]], reverse=True)
    proposals: list[CutProposal] = []
    for start_index, end_index in runs[:max_proposals]:
        start_seconds = times[start_index]
        end_seconds = times[end_index]
        if end_seconds - start_seconds < DEFAULT_MIN_CYCLE_SECONDS:
            continue
        proposals.append(
            CutProposal(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                policy="stable_hold",
                confidence=0.7 * signal.quality,
                stats={"holdSeconds": end_seconds - start_seconds},
            )
        )
    return proposals


def contract_completion_mode(contract: dict[str, Any] | None) -> str:
    """Resolve completionMode without importing bake_and_rank."""
    if not isinstance(contract, dict):
        return ""
    raw = str(contract.get("completionMode") or "").strip().lower()
    if raw:
        return raw
    topology = contract.get("movementTopology")
    if isinstance(topology, dict):
        raw = str(topology.get("completionMode") or "").strip().lower()
        if raw:
            return raw
    movement_type = str(contract.get("movementType") or "").strip().lower()
    return _MOVEMENT_TYPE_COMPLETION_MODES.get(movement_type, "")


def filter_pose_samples_to_span(
    samples: Sequence[dict[str, Any]] | None,
    *,
    start_seconds: float,
    end_seconds: float,
    pad_seconds: float = DEFAULT_SPAN_PAD_SECONDS,
) -> list[dict[str, Any]]:
    """Keep pose samples inside ``[start - pad, end + pad]`` in original-source time."""
    if not samples:
        return []
    lo = start_seconds - max(0.0, pad_seconds)
    hi = end_seconds + max(0.0, pad_seconds)
    kept: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        try:
            time_seconds = float(sample.get("timeSeconds"))
        except (TypeError, ValueError):
            continue
        if lo <= time_seconds <= hi:
            kept.append(sample)
    return kept


def proposals_overlapping_span(
    proposals: Iterable[CutProposal],
    *,
    start_seconds: float,
    end_seconds: float,
    pad_seconds: float = DEFAULT_SPAN_PAD_SECONDS,
) -> list[CutProposal]:
    """Keep proposals that overlap ``[start, end]`` and stay within the pad.

    Highest confidence wins; distance from the span midpoint is the tie-break,
    so a cycle that covers the selected window is preferred over a neighbor.
    A neighboring cycle that only grazes the span is dropped even when pose
    samples were padded, so parent expansion cannot pull in the previous rep.
    """
    span_start = float(start_seconds)
    span_end = float(end_seconds)
    if span_end <= span_start:
        return []
    pad = max(0.0, float(pad_seconds))
    midpoint = 0.5 * (span_start + span_end)
    kept: list[CutProposal] = []
    for proposal in proposals:
        if proposal.end_seconds <= span_start or proposal.start_seconds >= span_end:
            continue
        if proposal.start_seconds < span_start - pad or proposal.end_seconds > span_end + pad:
            continue
        overlap = min(proposal.end_seconds, span_end) - max(proposal.start_seconds, span_start)
        proposal_mid = 0.5 * (proposal.start_seconds + proposal.end_seconds)
        belongs_to_span = span_start <= proposal_mid <= span_end
        mostly_inside = overlap >= 0.5 * max(proposal.duration_seconds, 1e-6)
        if not belongs_to_span and not mostly_inside:
            continue
        kept.append(proposal)
    kept.sort(
        key=lambda proposal: (
            -proposal.confidence,
            abs(0.5 * (proposal.start_seconds + proposal.end_seconds) - midpoint),
        )
    )
    return kept


def propose_source_cut(
    *,
    contract: dict[str, Any] | None,
    dominant_pose_samples: Sequence[dict[str, Any]] | None,
    max_proposals: int = 2,
    span_start_seconds: float | None = None,
    span_end_seconds: float | None = None,
    span_pad_seconds: float = DEFAULT_SPAN_PAD_SECONDS,
) -> list[CutProposal]:
    """Propose source cuts from pose samples, using the contract cut policy."""
    samples = dominant_pose_samples
    if span_start_seconds is not None and span_end_seconds is not None:
        samples = filter_pose_samples_to_span(
            samples,
            start_seconds=span_start_seconds,
            end_seconds=span_end_seconds,
            pad_seconds=span_pad_seconds,
        )
    frames = parse_dominant_pose_samples(samples)
    if len(frames) < 8:
        return []
    signal = dominant_motion_signal(frames)
    if signal is None or signal.quality < MIN_SIGNAL_QUALITY:
        return []
    safe_contract = contract if isinstance(contract, dict) else {}
    completion_mode = contract_completion_mode(safe_contract)
    request_count = max_proposals
    if span_start_seconds is not None and span_end_seconds is not None:
        request_count = max(max_proposals, 8)
    if completion_mode in _CYCLE_POLICIES:
        proposals = _cycle_proposals(frames, signal, safe_contract, max_proposals=request_count)
    elif completion_mode == "distinct_end_state":
        proposals = _distinct_end_state_proposals(frames, signal, safe_contract, max_proposals=request_count)
        if not proposals:
            proposals = _cycle_proposals(frames, signal, safe_contract, max_proposals=request_count)
    elif completion_mode == "stable_hold":
        proposals = _stable_hold_proposals(frames, signal, safe_contract, max_proposals=request_count)
    else:
        # Unknown or missing contract: cycles are the dominant library shape and
        # a safe default; callers keep the existing grid search as fallback.
        proposals = _cycle_proposals(frames, signal, safe_contract, max_proposals=request_count)
    if span_start_seconds is not None and span_end_seconds is not None:
        return proposals_overlapping_span(
            proposals,
            start_seconds=span_start_seconds,
            end_seconds=span_end_seconds,
            pad_seconds=span_pad_seconds,
        )[:max_proposals]
    return proposals[:max_proposals]


def cycles_intersecting(
    proposals: Iterable[CutProposal],
    *,
    start_seconds: float,
    end_seconds: float,
    containment_pad_seconds: float = 0.5,
) -> list[CutProposal]:
    """Proposals whose interval contains the query interval (for replay checks)."""
    return [
        proposal
        for proposal in proposals
        if proposal.start_seconds - containment_pad_seconds <= start_seconds
        and end_seconds <= proposal.end_seconds + containment_pad_seconds
    ]
