"""Checks on the final exported tracks, independent of camera and root travel."""
from __future__ import annotations

import math
import statistics
from typing import Any

import numpy as np


def track_discontinuity_metrics(joint_tracks, *, root_joint, fps=30., body_height=None):
    """Distinguish a local motion discontinuity from a smooth speed maximum.

    Evaluate at a common time interval. Large displacement alone is not a
    tracking jump; it must also depart abruptly from neighbouring velocities.
    """
    if root_joint not in joint_tracks or len(joint_tracks[root_joint]) < 5 or fps <= 0:
        return {'available': False, 'severe': False, 'events': []}
    names = [name for name, values in joint_tracks.items() if len(values) == len(joint_tracks[root_joint])]
    points = np.asarray([joint_tracks[name] for name in names]).transpose(1, 0, 2)
    if not np.isfinite(points).all():
        return {'available': False, 'severe': True, 'events': [], 'reason': 'nonfinite_motion'}
    scale = float(np.median(np.max(np.linalg.norm(points[:, :, None]-points[:, None, :], axis=-1), axis=(1, 2))))
    if body_height is not None and np.isfinite(body_height) and body_height > 0:
        scale = body_height
    old_times = np.arange(len(points))/fps
    times = np.arange(int(np.floor(old_times[-1]*30+1e-8))+1)/30.
    from scipy.interpolate import PchipInterpolator
    # Preserve monotonic travel without introducing the alternating zero/change
    # acceleration produced by linear upsampling of lower-rate observations.
    sampled = PchipInterpolator(old_times, points, axis=0)(times)
    relative = sampled-sampled[:, names.index(root_joint):names.index(root_joint)+1]
    velocity = np.diff(relative, axis=0)
    residual = velocity[1:-1]-.5*(velocity[:-2]+velocity[2:])
    events = []
    for j, name in enumerate(names):
        if not name.endswith(('elbow', 'wrist', 'hand', 'ankle', 'foot')):
            continue
        steps = np.linalg.norm(velocity[1:-1, j], axis=-1)/max(scale, 1e-8)
        changes = np.linalg.norm(residual[:, j], axis=-1)/max(scale, 1e-8)
        coordinated = np.zeros(len(steps), dtype=bool)
        counterparts = [name.replace('left_', 'right_', 1) if name.startswith('left_') else name.replace('right_', 'left_', 1)]
        if name.endswith('foot'):
            counterparts.append(name[:-4]+'ankle')
        if name.endswith('hand'):
            counterparts.append(name[:-4]+'wrist')
        if name.endswith('ankle'):
            counterparts.append(name[:-5]+'foot')
        if name.endswith('wrist'):
            counterparts.append(name[:-5]+'hand')
        a = velocity[1:-1, j]
        for other in counterparts:
            if other == name or other not in names:
                continue
            b = velocity[1:-1, names.index(other)]
            lengths = np.linalg.norm(a, axis=-1)*np.linalg.norm(b, axis=-1)
            coordinated |= ((np.sum(a*b, axis=-1)/np.maximum(lengths, 1e-12) > .8)
                            & (np.linalg.norm(b, axis=-1) > .5*np.linalg.norm(a, axis=-1)))
        limits = np.where(coordinated, .12, .03)
        for index in np.flatnonzero((steps > limits) & (changes > .01)):
            events.append({'joint': name, 'timeSec': float(times[index+2]),
                           'stepBodyRatioAt30Hz': float(steps[index]),
                           'velocityResidualBodyRatioAt30Hz': float(changes[index])})
    return {'available': True, 'severe': bool(events), 'events': events,
            'policy': 'time_normalized_local_velocity_discontinuity_v1', 'referenceFps': 30.}


def body_orientation_axes(points, names):
    """Dimensionless axes expose rotation noise even on a narrow skeleton."""
    required = ('left_hip', 'right_hip', 'pelvis', 'neck')
    if not all(name in names for name in required):
        return np.empty((len(points), 0, 3))
    left, right, pelvis, neck = [points[:, names.index(name)] for name in required]
    lateral = right - left
    lateral /= np.maximum(np.linalg.norm(lateral, axis=1, keepdims=True), 1e-12)
    up = neck - pelvis
    up -= lateral * np.sum(up * lateral, axis=1, keepdims=True)
    up /= np.maximum(np.linalg.norm(up, axis=1, keepdims=True), 1e-12)
    return np.stack([lateral, up], axis=1)


def body_orientation_noise(points, names, reference, fps):
    """Detect added rotation roughness, not whether the source motion is correct.

    Unit-axis second differences avoid Euler wrap and world-frame dependence.
    Values are degree equivalents normalized to a 30 Hz sampling interval.
    """
    if len(points) < 5 or not np.isfinite(fps) or fps <= 0:
        return {'available': False, 'severe': False}
    axes = body_orientation_axes(points, names)
    source_axes = body_orientation_axes(reference, names)
    if not axes.shape[1] or axes.shape != source_axes.shape:
        return {'available': False, 'severe': False}
    def roughness(track):
        differences = np.diff(track, n=2, axis=0)
        return float(np.rad2deg(np.sqrt(np.mean(np.sum(differences**2, axis=-1)))) * (fps / 30.)**2)
    before, after = roughness(source_axes), roughness(axes)
    threshold = max(.5, before * 2.5)
    return {'available': True, 'severe': after > threshold,
            'sourceRmsDegreesAt30Hz': before, 'outputRmsDegreesAt30Hz': after,
            'limitDegreesAt30Hz': threshold, 'policy': 'introduced_body_rotation_noise_v1'}


def body_local_head_direction(points, names):
    """Head articulation relative to the moving torso, independent of world pose."""
    if 'head' not in names or 'neck' not in names:
        return None
    axes = body_orientation_axes(points, names)
    if not axes.shape[1]:
        return None
    direction = points[:, names.index('head')] - points[:, names.index('neck')]
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-12)
    lateral, up = axes[:, 0], axes[:, 1]
    return np.stack([np.sum(direction * axis, axis=1)
                     for axis in (lateral, up, np.cross(lateral, up))], axis=1)


def body_orientation_noise_from_payload(payload):
    names = ['left_hip', 'right_hip', 'pelvis', 'neck']
    frames = payload.get('frames') or []
    if not frames or any(any(n not in (f.get(key) or {}) for n in names)
                         for f in frames for key in ('joints', 'sourceJoints')):
        return {'available': False, 'severe': False}
    points, reference = [np.asarray([[f[key][n] for n in names] for f in frames], dtype=float)
                         for key in ('joints', 'sourceJoints')]
    return body_orientation_noise(points, names, reference, float(payload.get('fps') or 30.))


def refresh_motion_bounds(payload: dict[str, Any]) -> None:
    """Bounds describe final joints; the floor is a separate, persistent plane."""
    points = [point for frame in payload.get("frames", [])
              for point in frame.get("joints", {}).values()
              if isinstance(point, (list, tuple)) and len(point) == 3
              and all(math.isfinite(float(value)) for value in point)]
    if not points:
        return
    values = np.asarray(points, dtype=float)
    low, high = values.min(axis=0), values.max(axis=0)
    payload["bounds"] = {
        **{f"min{axis}": float(low[i]) for i, axis in enumerate("XYZ")},
        **{f"max{axis}": float(high[i]) for i, axis in enumerate("XYZ")},
        "center": ((low + high) / 2).tolist(), "size": (high - low).tolist(),
    }


def _unit(value: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(value))
    return value / length if math.isfinite(length) and length > 1e-8 else None


def transport_side(side: np.ndarray, old_axis: np.ndarray, new_axis: np.ndarray) -> np.ndarray | None:
    """Minimal rotation of a bone frame, without attributing bone swing to roll."""
    cosine = float(np.clip(np.dot(old_axis, new_axis), -1, 1))
    if cosine < -0.999999:
        return None  # Antiparallel swing has no unique minimal transport axis.
    cross = np.cross(old_axis, new_axis)
    transported = side + np.cross(cross, side) + np.cross(cross, np.cross(cross, side)) / (1 + cosine)
    return _unit(transported - new_axis * np.dot(transported, new_axis))


def transport_corrected_bone_sides(previous_frames: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    """Keep axial orientation attached to a bone when an IK pass moves its joints."""
    for before, after in zip(previous_frames, payload.get("frames", [])):
        for key, value in list(after.get("boneSides", {}).items()):
            if "->" not in key:
                continue
            start, end = key.split("->", 1)
            if not all(start in frame.get("joints", {}) and end in frame.get("joints", {})
                       for frame in (before, after)):
                continue
            axes = [_unit(np.asarray(frame["joints"][end]) - frame["joints"][start])
                    for frame in (before, after)]
            if any(axis is None for axis in axes):
                continue
            side = _unit(np.asarray(value) - axes[0] * np.dot(value, axes[0]))
            if side is not None:
                transported = transport_side(side, axes[0], axes[1])
                if transported is not None:
                    after["boneSides"][key] = transported.tolist()
    # A confirmed sole contact owns shoe roll. Transporting the old roll after
    # correcting pitch would preserve the very tilt the support repair removed.
    from .support_geometry import support_evidence, evidence_is_complete
    evidence = support_evidence(payload)
    if evidence.get('status') == 'confirmed' and evidence_is_complete(evidence, payload.get('jointNames', [])):
        for contact in evidence.get('soleContacts', []):
            _, ankle, toe = contact['joints']
            normal = np.asarray(contact['normal'], dtype=float)
            for frame in payload.get('frames', []):
                forward = np.asarray(frame['joints'][toe])-frame['joints'][ankle]
                side = _unit(np.cross(forward, normal))
                if side is not None:
                    frame.setdefault('boneSides', {})[f'{ankle}->{toe}'] = side.tolist()


def bone_roll_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """Locate abrupt axial changes separately from anatomical joint angles.

    Smooth pronation, including angles crossing +/-180, is permitted. Missing
    samples split the track; they must never be joined into a fictitious step.
    """
    frames = payload.get("frames", [])
    keys = sorted({key for frame in frames for key in frame.get("boneSides", {})})
    events = []
    maximum = 0.0
    fps = max(1.0, float(payload.get("fps") or 30))
    for key in keys:
        if "->" not in key:
            continue
        start, end = key.split("->", 1)
        previous = None
        steps: dict[int, float] = {}
        for index, frame in enumerate(frames):
            joints = frame.get("joints", {})
            side_value = frame.get("boneSides", {}).get(key)
            if side_value is None or start not in joints or end not in joints:
                previous = None
                continue
            axis = _unit(np.asarray(joints[end], dtype=float) - joints[start])
            side = np.asarray(side_value, dtype=float)
            side = _unit(side - axis * np.dot(side, axis)) if axis is not None else None
            if side is None:
                previous = None
                events.append({"bone": key, "frameIndex": index, "reason": "invalid_bone_orientation"})
                continue
            if previous is not None:
                transported = transport_side(previous[1], previous[0], axis)
                if transported is not None:
                    angle = math.degrees(math.atan2(float(np.dot(axis, np.cross(transported, side))),
                                                   float(np.dot(transported, side))))
                    steps[index] = angle
                    maximum = max(maximum, abs(angle))
            previous = axis, side
        for index, angle in steps.items():
            neighbours = [steps[j] for j in range(index - 3, index + 4) if j != index and j in steps]
            if len(neighbours) < 3:
                continue
            expected = statistics.median(neighbours)
            # Time-scaled limits plus an absolute orientation jump floor.
            threshold = max(15.0, 600.0 / fps)
            reversal = any(angle * steps.get(j, 0) < 0 and abs(steps.get(j, 0)) > 12
                           for j in (index - 1, index + 1, index + 2))
            if reversal:
                threshold = max(12.0, 360.0 / fps)
            if abs(angle - expected) > threshold and (abs(angle) > 25 or reversal):
                events.append({"bone": key, "frameIndex": index, "stepDegrees": angle,
                               "localExpectedStepDegrees": expected, "reason": "axial_twist_discontinuity"})
    return {"available": bool(keys), "severe": bool(events), "maxStepDegrees": maximum, "events": events}


def rendered_leg_sides(frames: list[dict[str, Any]]) -> list[dict[str, list[float]]]:
    """Replay the renderer's knee frames, including axes absent from boneSides.

    Keep this kernel in parity with wearCoordinateLegSides and Kotlin's
    coordinateLegSides. Production-JavaScript regression tests verify parity.
    Missing joints break a track instead of carrying an old orientation over it.
    """
    previous: dict[str, np.ndarray] = {}
    result = []
    for frame in frames:
        current: dict[str, np.ndarray] = {}
        joints = frame.get("joints", {})
        for leg in ("left", "right"):
            names = [f"{leg}_{joint}" for joint in ("hip", "knee", "ankle", "foot")]
            if not all(name in joints for name in names):
                continue
            hip, knee, ankle, toe = (np.asarray(joints[name], dtype=float) for name in names)
            thigh, shin, foot = (_unit(vector) for vector in (knee - hip, ankle - knee, toe - ankle))
            if thigh is None or shin is None or foot is None:
                continue
            shin_key = f"{leg}_knee->{leg}_ankle"
            old = previous.get(shin_key)
            reference = _unit(old - shin * np.dot(old, shin)) if old is not None else None
            if reference is None:
                reference = _unit(np.cross(foot, -shin))
            knee_side = np.cross(thigh, shin)
            bend = float(np.linalg.norm(knee_side))
            side = knee_side / bend if bend > .342 else reference
            if side is None:
                continue
            if reference is not None and np.dot(side, reference) < 0:
                side = -side
            if reference is not None and old is not None:
                weight = .2 * float(np.clip((bend - .342) / .3, 0, 1))
                side = _unit(reference * (1 - weight) + side * weight)
            current[f"{leg}_hip->{leg}_knee"] = side
            current[shin_key] = side
            foot_side = _unit(side - foot * np.dot(side, foot))
            current[f"{leg}_ankle->{leg}_foot"] = (
                foot_side if foot_side is not None else reference if reference is not None else side
            )
        result.append({key: value.tolist() for key, value in current.items()})
        previous = current
    return result


def rendered_bone_roll_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    frames = payload.get("frames", [])
    resolved = rendered_leg_sides(frames)
    metrics = bone_roll_metrics({**payload, "frames": [
        {**frame, "boneSides": {**frame.get("boneSides", {}), **sides}}
        for frame, sides in zip(frames, resolved)
    ]})
    metrics["orientationSource"] = "exported_forearms_and_rendered_leg_frames"
    metrics["renderedLegFrameCount"] = sum(bool(sides) for sides in resolved)
    return metrics


SPIKE_JOINT_NAMES = ("left_wrist", "right_wrist", "left_ankle", "right_ankle",
                     "left_knee", "right_knee", "left_elbow", "right_elbow")


def introduced_joint_spike_limit(before, scale):
    """Largest local residual allowed by the source-amplification spike gate."""
    return np.maximum(np.maximum(scale * .012, before * 2.5), before + scale * .008)


def introduced_joint_spikes(payload: dict[str, Any]) -> dict[str, Any]:
    """Detect local jitter amplified by postprocessing, allowing rigid motion.

    sourceJoints only establish what processing changed; they are not evidence
    that an upstream pose is correct. Root-relative residual lengths are also
    invariant to a fixed camera/world rotation.
    """
    frames = payload.get("frames", [])
    events = []
    spans = []
    for frame in frames:
        points = list(frame.get("joints", {}).values())
        if points:
            spans.append(float(np.linalg.norm(np.ptp(np.asarray(points), axis=0))))
    scale = statistics.median(spans) if spans else 0
    if scale <= 1e-8:
        return {"severe": False, "events": []}
    for i in range(1, len(frames) - 1):
        group = frames[i-1:i+2]
        for name in SPIKE_JOINT_NAMES:
            residuals = []
            for field in ("sourceJoints", "joints"):
                if not all(name in f.get(field, {}) and "pelvis" in f.get(field, {}) for f in group):
                    break
                points = [np.asarray(f[field][name]) - f[field]["pelvis"] for f in group]
                times = [f.get("timeSec") for f in group]
                alpha = ((times[1] - times[0]) / (times[2] - times[0])
                         if all(isinstance(t, (float, int)) for t in times) and times[2] > times[0]
                         else .5)
                residuals.append(float(np.linalg.norm(points[1] - (points[0] * (1-alpha) + points[2] * alpha))))
            if len(residuals) == 2 and residuals[1] > introduced_joint_spike_limit(residuals[0], scale):
                events.append({"joint": name, "frameIndex": i, "before": residuals[0], "after": residuals[1]})
    return {"severe": bool(events), "events": events}
