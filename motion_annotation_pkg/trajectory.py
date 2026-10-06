"""Wrist 3D trajectory reconstruction from rotation-vector + accelerometer streams.

Frame conventions (Android conventions, matching the CSV columns written by the
watch app):
- The CSV stores the TYPE_ROTATION_VECTOR quaternion as columns x, y, z, w with
  w in the 4th column (scalar last). The quaternion rotates vectors from the
  DEVICE frame into the WORLD frame (SensorManager.getRotationMatrixFromVector
  semantics): v_world = R(q) @ v_device.
- World frame is the Android Earth frame: X approximately magnetic east, Y
  magnetic north, Z pointing up away from gravity. Gravity in the world frame
  is [0, 0, -g]; an accelerometer at rest measures specific force
  f_device = R(q)^T @ [0, 0, +g], i.e. it reads +g on the up-pointing axis.
- Units: m/s^2 for acceleration, meters for position, seconds for time.

Drift control: wrist IMU double integration drifts quickly. Quasi-static
windows (low |specific force| variance, typically the pauses between reps) are
detected, the constant acceleration residual measured over those windows is
subtracted (gravity/tilt correction), and velocity is re-anchored to zero
inside each static window (ZUPT). Residual drift is reported honestly in the
returned metrics rather than hidden.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motion_annotation_pkg.signals import sliding_std

_GRAVITY_MPS2 = 9.81
# Static-window gate: |specific force| std below this and mean magnitude near
# its rest level. Tuned for 50 Hz wrist data where rep bursts exceed 1 m/s^2;
# the 0.25 s window fits inside the short pauses between reps so ZUPT gets
# anchors there.
_STATIC_STD_THRESHOLD_MPS2 = 0.3
_STATIC_WINDOW_S = 0.25
_ACCEL_REST_MEAN_MPS2 = _GRAVITY_MPS2
_ACCEL_MEAN_TOLERANCE_MPS2 = 1.5
_LINEAR_REST_MEAN_MPS2 = 0.0
_LINEAR_MEAN_TOLERANCE_MPS2 = 0.5
_MIN_STATIC_SAMPLES = 5


@dataclass(frozen=True)
class TrajectoryResult:
    position: np.ndarray  # (N, 3) world frame, meters
    velocity: np.ndarray  # (N, 3) world frame, m/s
    static_mask: np.ndarray  # (N,) bool, True in quasi-static windows
    drift_metrics: dict[str, float]


def quaternions_to_rotation_matrices(xyzw: np.ndarray) -> np.ndarray:
    """Batch device-to-world rotation matrices from (N, 4) [x, y, z, w] quaternions (normalized)."""
    xyzw = np.asarray(xyzw, dtype=np.float64)
    norms = np.linalg.norm(xyzw, axis=1, keepdims=True)
    safe = np.where(norms > 1e-12, xyzw / np.where(norms > 1e-12, norms, 1.0), np.array([0.0, 0.0, 0.0, 1.0]))
    x, y, z, w = safe[:, 0], safe[:, 1], safe[:, 2], safe[:, 3]
    matrices = np.empty((xyzw.shape[0], 3, 3), dtype=np.float64)
    matrices[:, 0, 0] = 1 - 2 * (y * y + z * z)
    matrices[:, 0, 1] = 2 * (x * y - z * w)
    matrices[:, 0, 2] = 2 * (x * z + y * w)
    matrices[:, 1, 0] = 2 * (x * y + z * w)
    matrices[:, 1, 1] = 1 - 2 * (x * x + z * z)
    matrices[:, 1, 2] = 2 * (y * z - x * w)
    matrices[:, 2, 0] = 2 * (x * z - y * w)
    matrices[:, 2, 1] = 2 * (y * z + x * w)
    matrices[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return matrices


def quaternions_to_euler(xyzw: np.ndarray) -> np.ndarray:
    """(N, 4) scalar-last quaternions to (N, 3) (yaw, pitch, roll) in radians (ZYX intrinsic)."""
    from scipy.spatial.transform import Rotation

    return Rotation.from_quat(np.asarray(xyzw, dtype=np.float64)).as_euler("ZYX")


def reconstruct_trajectory(
    accel_device: np.ndarray,
    quaternions_xyzw: np.ndarray,
    timestamps_nanos: np.ndarray,
    gravity_removed: bool = False,
    static_std_threshold_mps2: float = _STATIC_STD_THRESHOLD_MPS2,
) -> TrajectoryResult:
    """Double-integrate world-frame linear acceleration with ZUPT at quasi-static windows.

    accel_device: (N, 3) device-frame samples, m/s^2. Pass the raw accelerometer
    (specific force) with gravity_removed=False, or LINEAR_ACCELERATION samples
    (gravity already removed by the sensor fusion) with gravity_removed=True.
    quaternions_xyzw: (N, 4) device-to-world rotation-vector quaternions.
    """
    accel_device = np.atleast_2d(np.asarray(accel_device, dtype=np.float64))
    quaternions_xyzw = np.atleast_2d(np.asarray(quaternions_xyzw, dtype=np.float64))
    n = accel_device.shape[0]
    dt_s = _sample_intervals_seconds(np.asarray(timestamps_nanos, dtype=np.int64))
    rotations = quaternions_to_rotation_matrices(quaternions_xyzw)
    linear_world = np.einsum("nij,nj->ni", rotations, accel_device)

    rest_mean, mean_tolerance = (
        (_LINEAR_REST_MEAN_MPS2, _LINEAR_MEAN_TOLERANCE_MPS2)
        if gravity_removed
        else (_ACCEL_REST_MEAN_MPS2, _ACCEL_MEAN_TOLERANCE_MPS2)
    )
    static_mask = _static_mask(linear_world, dt_s, static_std_threshold_mps2, rest_mean, mean_tolerance)
    if not gravity_removed:
        gravity_mps2 = _effective_gravity(linear_world, static_mask)
        linear_world = linear_world - np.array([0.0, 0.0, gravity_mps2])
    if int(static_mask.sum()) >= _MIN_STATIC_SAMPLES:
        # Constant residual over the static windows covers both gravity-scale and
        # quaternion-tilt error; removing it is the main drift correction.
        linear_world = linear_world - linear_world[static_mask].mean(axis=0)

    velocity = _integrate(linear_world, dt_s)
    zupt_residual = float(np.abs(velocity[static_mask]).mean()) if static_mask.any() else 0.0
    velocity = _apply_zupt(velocity, static_mask)
    position = _integrate(velocity, dt_s)

    drift = {
        "static_fraction": float(static_mask.mean()) if n else 0.0,
        "zupt_residual_velocity_mps": zupt_residual,
        "end_to_end_displacement_m": float(np.linalg.norm(position[-1] - position[0])) if n else 0.0,
        "path_length_m": float(np.linalg.norm(np.diff(position, axis=0), axis=1).sum()) if n > 1 else 0.0,
    }
    return TrajectoryResult(position=position, velocity=velocity, static_mask=static_mask, drift_metrics=drift)


def _sample_intervals_seconds(timestamps_nanos: np.ndarray) -> np.ndarray:
    """Per-interval dt in seconds (first interval reused for the leading edge)."""
    if timestamps_nanos.size < 2:
        return np.ones(max(timestamps_nanos.size, 1))
    diffs = np.diff(timestamps_nanos) / 1e9
    return np.concatenate(([diffs[0]], diffs))


def _integrate(values: np.ndarray, dt_s: np.ndarray) -> np.ndarray:
    """Cumulative trapezoidal integration per column with zero initial value."""
    out = np.zeros_like(values, dtype=np.float64)
    if values.shape[0] > 1:
        out[1:] = np.cumsum(0.5 * (values[1:] + values[:-1]) * dt_s[1:, None], axis=0)
    return out


def _static_mask(
    linear_world: np.ndarray,
    dt_s: np.ndarray,
    threshold_mps2: float,
    rest_mean_mps2: float,
    mean_tolerance_mps2: float,
) -> np.ndarray:
    """Quasi-static windows: low |linear acceleration| variance with a rest-like mean magnitude."""
    if linear_world.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    magnitude = np.linalg.norm(linear_world, axis=1)
    window = max(int(round(_STATIC_WINDOW_S / float(np.median(dt_s)))), 3)
    std = sliding_std(magnitude, window)
    mean_ok = np.abs(magnitude - rest_mean_mps2) <= mean_tolerance_mps2
    return (std < threshold_mps2) & mean_ok


def _effective_gravity(force_world: np.ndarray, static_mask: np.ndarray) -> float:
    """Local gravity magnitude from the most static samples, clipped to a sane range."""
    if static_mask.any():
        magnitude = float(np.median(np.linalg.norm(force_world[static_mask], axis=1)))
        if 9.0 <= magnitude <= 10.0:
            return magnitude
    return _GRAVITY_MPS2


def _apply_zupt(velocity: np.ndarray, static_mask: np.ndarray) -> np.ndarray:
    """Zero velocity inside each quasi-static run (device at rest), keeping free-motion integration between runs."""
    corrected = velocity.copy()
    n = static_mask.size
    index = 0
    while index < n:
        if not static_mask[index]:
            index += 1
            continue
        end = index
        while end + 1 < n and static_mask[end + 1]:
            end += 1
        corrected[index : end + 1] = 0.0
        index = end + 1
    return corrected
