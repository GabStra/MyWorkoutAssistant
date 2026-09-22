from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from typing import Any, Iterable


POSE_JOINTS = (
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
LOWER_BODY_JOINTS = frozenset(
    ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
)
ANGLE_CHAINS = {
    "left_elbow": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_elbow": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_shoulder": ("left_elbow", "left_shoulder", "left_hip"),
    "right_shoulder": ("right_elbow", "right_shoulder", "right_hip"),
    "left_hip": ("left_shoulder", "left_hip", "left_knee"),
    "right_hip": ("right_shoulder", "right_hip", "right_knee"),
    "left_knee": ("left_hip", "left_knee", "left_ankle"),
    "right_knee": ("right_hip", "right_knee", "right_ankle"),
}
ALIGNMENT_JOINTS = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
)
PROJECTION_COARSE_ANGLE_STEP_DEGREES = 15.0
PROJECTION_REFINEMENT_STEPS_DEGREES = (3.0, 0.5)


def registered_camera_pose_fidelity_metrics(source_payload, motion_payload, *, camera_reference=None,
                                            camera_orientation=None):
    """Fit one scaled orthographic camera using proximal joints, never each pose.

    Camera elevation and scene rotation are nuisance parameters. Distal joints
    are held out of registration so their errors cannot steer the camera fit.
    """
    import numpy as np
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation

    source = _pose_frames(source_payload, source=True)
    motion = _pose_frames(motion_payload, source=False)
    retained = motion_payload.get('sourcePoseRegistration')
    if camera_reference is None and isinstance(retained, dict):
        evidence = retained.get('sourcePose', {})
        if all(evidence.get(key) == source_payload.get(key)
               for key in ('frames', 'coordinateSpace', 'imageWidth', 'imageHeight', 'sourceTimeOriginSec')):
            camera_reference = retained.get('camera')
    if len(source) < 5 or len(motion) < 5:
        return _unavailable_metrics(source_frame_count=len(source), motion_frame_count=len(motion),
                                    reason="insufficient_pose_frames")
    if camera_reference is not None:
        rotation = np.asarray(camera_reference.get('cameraRotation', []), dtype=float)
        if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
            return _unavailable_metrics(source_frame_count=len(source), motion_frame_count=len(motion),
                                        reason="fixed_camera_registration_unavailable")
        transform = camera_reference.get('cameraImageTransform')
        if not isinstance(transform, (list, tuple)) or len(transform) != 6 or not np.isfinite(transform).all():
            return _unavailable_metrics(source_frame_count=len(source), motion_frame_count=len(motion),
                                        reason="fixed_camera_image_transform_unavailable")
        return _registered_projection_metrics(source, motion, rotation,
                    camera_reference.get('bilateralAssignment') == 'swapped', image_transform=tuple(transform))
    if camera_orientation is not None:
        rotation = np.asarray(camera_orientation, dtype=float)
        if (rotation.shape != (3, 3) or not np.isfinite(rotation).all()
                or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6)
                or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6)):
            return _unavailable_metrics(source_frame_count=len(source), motion_frame_count=len(motion),
                                        reason="invalid_reconstruction_camera_orientation")
        metrics = _registered_projection_metrics(source, motion, rotation, False)
        metrics['cameraOrientationAuthority'] = 'reconstruction_camera_coordinates'
        return metrics
    candidates = []
    for swap in (False, True):
        pairs = []
        for frame in source:
            other = _motion_frame_at_time(motion, frame['time'])
            if other is None:
                continue
            pairs.extend((other['joints'][_bilateral_name(name, swap=swap)], frame['joints'][name])
                         for name in ALIGNMENT_JOINTS if name in frame['joints']
                         and _bilateral_name(name, swap=swap) in other['joints'])
        if len(pairs) < 6:
            continue
        x, y = (np.asarray(values) for values in zip(*pairs))
        center_x, center_y = x.mean(0), y.mean(0)
        x, y = x-center_x, y-center_y
        if np.linalg.matrix_rank(x, tol=1e-8) < 2:
            continue
        affine = np.linalg.lstsq(x, y, rcond=None)[0].T
        u, singular, vt = np.linalg.svd(affine, full_matrices=False)
        rows = u @ vt
        orientation = np.vstack([rows, np.cross(rows[0], rows[1])])
        initial = np.r_[Rotation.from_matrix(orientation).as_rotvec(), np.log(max(float(singular.mean()), 1e-8))]
        def residual(parameters):
            rotation = Rotation.from_rotvec(parameters[:3]).as_matrix()
            return (np.exp(parameters[3]) * (x @ rotation[:2].T)-y).ravel()
        solved = least_squares(residual, initial, max_nfev=80)
        if not solved.success or not np.isfinite(solved.x).all():
            continue
        rotation = Rotation.from_rotvec(solved.x[:3]).as_matrix()
        metrics = _registered_projection_metrics(source, motion, rotation, swap)
        metrics['cameraRegistrationRms'] = float(np.sqrt(np.mean(residual(solved.x)**2)))
        candidates.append(metrics)
    if not candidates:
        return _unavailable_metrics(source_frame_count=len(source), motion_frame_count=len(motion),
                                    reason="camera_registration_unavailable")
    # Registration selection uses only held-in proximal evidence.
    return min(candidates, key=lambda metric: metric['cameraRegistrationRms'])


def _registered_projection_metrics(source, motion, rotation, swap, *, image_transform=None):
    import numpy as np
    transformed = [{**frame, 'joints': {name: tuple((rotation @ np.asarray(point)) * [1., -1., -1.])
                    for name, point in frame['joints'].items()}} for frame in motion]
    if image_transform is None:
        image_transform = _global_similarity_transform(source, transformed, horizontal_vector=(1., 0.),
                                                       mirror=False, swap_bilateral=swap)
    if image_transform is None:
        return _unavailable_metrics(source_frame_count=len(source), motion_frame_count=len(motion),
                                    reason='camera_image_alignment_unavailable')
    image_transform = _recenter_constant_image_offset(
        source, transformed, swap, tuple(image_transform))
    metrics = _projection_metrics(source, transformed, horizontal_vector=(1., 0.), mirror=False,
                                   swap_bilateral=swap, image_transform=image_transform)
    return {**metrics, 'cameraModel': 'fixed_scaled_orthographic', 'cameraRotation': rotation.tolist(),
            'cameraImageTransform': list(image_transform),
            'available': True, 'sourceFrameCount': len(source), 'motionFrameCount': len(motion)}


def _recenter_constant_image_offset(source, transformed, swap, image_transform):
    """Absorb one constant whole-body image offset estimated from proximal joints.

    A retained camera is registered before scene placement and support-driven
    whole-body corrections, so the baked clip can sit at a constant offset in
    the camera frame. That offset is placement, not pose error: pose, angles,
    and the SHAPE of root travel remain fully measured without it. Only the
    translation component is re-fit here (never scale or rotation), and only
    from torso/proximal joints, so time-varying drift stays measurable.
    """
    import numpy as np
    residuals = ([], [])
    for source_frame in source:
        motion_frame = _motion_frame_at_time(transformed, source_frame['time'])
        if motion_frame is None:
            continue
        for name in ALIGNMENT_JOINTS:
            source_point = source_frame['joints'].get(name)
            mapped = _bilateral_name(name, swap=swap)
            motion_point = motion_frame['joints'].get(mapped)
            if source_point is None or motion_point is None:
                continue
            projected = _apply_similarity(
                (motion_point[0], -motion_point[1]), image_transform)
            residuals[0].append(projected[0] - source_point[0])
            residuals[1].append(projected[1] - source_point[1])
    if len(residuals[0]) < 6:
        return image_transform
    offset = (float(np.median(residuals[0])), float(np.median(residuals[1])))
    transform = list(image_transform)
    transform[4] -= offset[0]
    transform[5] -= offset[1]
    return tuple(transform)


def source_pose_reference_for_motion(source_payload: dict[str, Any], motion_payload: dict[str, Any]) -> dict[str, Any]:
    """Select parent-video observations using explicit retained source timestamps."""
    frames = motion_payload.get("frames") or []
    if not frames or any("sourceTimeSec" not in frame for frame in frames):
        return {**source_payload, "frames": []}
    start, end = float(frames[0]["sourceTimeSec"]), float(frames[-1]["sourceTimeSec"])
    return {**source_payload, "sourceTimeOriginSec": start - float(frames[0].get("timeSec", 0.0)),
            "frames": [frame for frame in source_payload.get("frames", [])
                       if start <= float(frame.get("sourceTimeSec", -math.inf)) <= end]}


def materialized_camera_pose_fidelity_metrics(source_payload, motion_payload):
    """Carry the correction camera through unchanged root-relative body shape.

    Registration uses retained pre-fit coordinates, never the fitted output
    under review. Shape changes make registration unavailable. A single constant
    origin preserves time-varying root-motion differences in the comparison.
    """
    import numpy as np

    reference = motion_payload.get('sourcePoseCameraReference')
    if reference is None:
        return registered_camera_pose_fidelity_metrics(source_payload, motion_payload)
    def unavailable(reason):
        return _unavailable_metrics(source_frame_count=len(source_payload.get('frames', [])),
                                    motion_frame_count=len(motion_payload.get('frames', [])), reason=reason)
    if not isinstance(reference, dict):
        return unavailable('invalid_source_camera_reference')
    evidence = reference.get('sourcePose', {})
    for field in ('coordinateSpace', 'imageWidth', 'imageHeight'):
        if evidence.get(field) != source_payload.get(field):
            return unavailable('source_camera_evidence_mismatch')
    observed = {f.get('sourceTimeSec'): f for f in evidence.get('frames', [])}
    if any(observed.get(f.get('sourceTimeSec')) != f for f in source_payload.get('frames', [])):
        return unavailable('source_camera_evidence_mismatch')
    # Retained observations use the parent video clock; a selected cycle's
    # playback starts at zero. Align by explicit provenance, also when the
    # caller supplies the whole parent reference. This is idempotent for an
    # already selected reference and never stretches sparse observations.
    if motion_payload.get('frames') and all('sourceTimeSec' in frame for frame in motion_payload['frames']):
        source_payload = source_pose_reference_for_motion(source_payload, motion_payload)
    coordinate_frames = _pose_frames(reference.get('coordinateReference', {}), source=False)
    original_points, placed_points, original_roots, placed_roots = [], [], [], []
    for frame in motion_payload.get('frames', []):
        if frame.get('syntheticLoopBridge'):
            continue
        before = _motion_frame_at_time(coordinate_frames, float(frame.get('sourceTimeSec', frame.get('timeSec', 0.))))
        placed = frame.get('cameraPlacementReferenceJoints', frame.get('controlledSourceJoints'))
        if before is None or not isinstance(placed, dict):
            return unavailable('source_camera_placement_reference_unavailable')
        root_name = next((n for n in ('pelvis', 'hips') if n in before['joints'] and n in placed), None)
        if root_name is None:
            return unavailable('source_camera_placement_root_unavailable')
        original_root, placed_root = np.asarray(before['joints'][root_name]), np.asarray(placed[root_name])
        original_roots.append(original_root)
        placed_roots.append(placed_root)
        for name in POSE_JOINTS:
            if name in before['joints'] and name in placed:
                original_points.append(np.asarray(before['joints'][name])-original_root)
                placed_points.append(np.asarray(placed[name])-placed_root)
    if len(original_points) < 6:
        return unavailable('source_camera_placement_reference_unavailable')
    x, y = np.asarray(original_points), np.asarray(placed_points)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        return unavailable('invalid_source_camera_placement')
    # Contact registration can translate the whole body differently per frame.
    # Recover orientation from unchanged root-relative shape; use only ONE
    # constant origin so real root-motion differences remain measurable.
    x0, y0 = x, y
    denominator = float(np.sum(x0*x0))
    if denominator <= 1e-12 or np.linalg.matrix_rank(x0, tol=1e-8) < 2:
        return unavailable('source_camera_placement_degenerate')
    u, _, vt = np.linalg.svd(x0.T @ y0)
    orientation = u @ vt
    if np.linalg.det(orientation) < 0:
        u[:, -1] *= -1
        orientation = u @ vt
    scale = float(np.sum((x0 @ orientation)*y0)/denominator)
    error = np.linalg.norm(scale*x0 @ orientation-y, axis=1)
    extent = max(float(np.max(np.linalg.norm(y0, axis=1))), .01)
    if scale <= 1e-12 or float(np.max(error)) > extent * 1e-5:
        return unavailable('source_camera_placement_not_rigid')
    origins = np.asarray(placed_roots)-scale*np.asarray(original_roots) @ orientation
    origin = origins.mean(0)
    restored = {**motion_payload, 'frames': [{**f, 'joints': {
        n: ((np.asarray(p)-origin) @ orientation.T/scale).tolist()
        for n, p in f['joints'].items()
    }} for f in motion_payload.get('frames', [])]}
    camera = reference.get('camera')
    if not isinstance(camera, dict):
        return unavailable('invalid_source_camera_reference')
    metrics = registered_camera_pose_fidelity_metrics(source_payload, restored, camera_reference=camera)
    return {**metrics, 'cameraAuthority': 'retained_source_correction_camera',
            'cameraPlacementMaximumError': float(np.max(error)),
            'cameraPlacementBasis': 'root_relative_shape_and_one_constant_origin',
            'cameraReferenceRootTranslationRange': np.ptp(origins, axis=0).tolist()}


def source_to_motion_pose_fidelity_metrics(
    source_payload: dict[str, Any],
    motion_payload: dict[str, Any],
) -> dict[str, Any]:
    """Compare source 2D pose with raw WHAM without assuming camera scale or yaw.

    A similarity fit uses only the torso and proximal lower body. All limbs are
    then evaluated outside that fit, so a wrong support posture or asymmetric
    arm reconstruction cannot optimize its own error away. Camera-horizontal
    directions spanning the world XZ plane and a mirrored source view are
    evaluated, but one projection is selected for the entire clip. This is
    required for three-quarter sources: treating them as pure X or pure Z
    injects visible sagittal motion into the model's lateral axis.
    """
    source_frames = _pose_frames(source_payload, source=True)
    motion_frames = _pose_frames(motion_payload, source=False)
    if len(source_frames) < 5 or len(motion_frames) < 5:
        return _unavailable_metrics(
            source_frame_count=len(source_frames),
            motion_frame_count=len(motion_frames),
            reason="insufficient_pose_frames",
        )

    mode_metrics: list[dict[str, Any]] = []
    coarse_angles = [
        float(value)
        for value in range(0, 180, round(PROJECTION_COARSE_ANGLE_STEP_DEGREES))
    ]
    for mirror in (False, True):
        for swap_bilateral in (False, True):
            branch_metrics = [
                _projection_metrics_for_angle(
                    source_frames,
                    motion_frames,
                    angle_degrees=angle_degrees,
                    mirror=mirror,
                    swap_bilateral=swap_bilateral,
                )
                for angle_degrees in coarse_angles
            ]
            mode_metrics.extend(branch_metrics)
            usable_branch = [
                metrics
                for metrics in branch_metrics
                if metrics.get("comparableFrameCount", 0) >= 5
            ]
            if not usable_branch:
                continue
            branch_best = min(usable_branch, key=_projection_selection_key)
            best_angle = float(branch_best["projectionHorizontalAngleDegrees"])
            search_radius = PROJECTION_COARSE_ANGLE_STEP_DEGREES
            for refinement_step in PROJECTION_REFINEMENT_STEPS_DEGREES:
                offsets = range(
                    -round(search_radius / refinement_step),
                    round(search_radius / refinement_step) + 1,
                )
                refinements = [
                    _projection_metrics_for_angle(
                        source_frames,
                        motion_frames,
                        angle_degrees=(best_angle + offset * refinement_step) % 180.0,
                        mirror=mirror,
                        swap_bilateral=swap_bilateral,
                    )
                    for offset in offsets
                ]
                mode_metrics.extend(refinements)
                usable_refinements = [
                    metrics
                    for metrics in refinements
                    if metrics.get("comparableFrameCount", 0) >= 5
                ]
                if usable_refinements:
                    branch_best = min(usable_refinements, key=_projection_selection_key)
                    best_angle = float(branch_best["projectionHorizontalAngleDegrees"])
                search_radius = refinement_step
    usable = [metrics for metrics in mode_metrics if metrics.get("comparableFrameCount", 0) >= 5]
    if not usable:
        return _unavailable_metrics(
            source_frame_count=len(source_frames),
            motion_frame_count=len(motion_frames),
            reason="pose_alignment_unavailable",
        )
    selected = min(
        usable,
        key=_projection_selection_key,
    )
    return {
        **selected,
        "available": True,
        "sourceFrameCount": len(source_frames),
        "motionFrameCount": len(motion_frames),
        "evaluatedProjectionCount": len(mode_metrics),
    }


def source_to_motion_pose_fidelity_metrics_for_projection(
    source_payload: dict[str, Any],
    motion_payload: dict[str, Any],
    *,
    projection_reference: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate a motion with an already selected camera projection branch.

    Refinement transactions compare two versions of the same reconstructed
    clip.  Re-selecting yaw, mirroring, or bilateral assignment independently
    for each version changes the measuring coordinate system and can reject an
    improvement for an apparent error created only by that branch change.
    """
    source_frames = _pose_frames(source_payload, source=True)
    motion_frames = _pose_frames(motion_payload, source=False)
    horizontal_vector = projection_reference.get("projectionHorizontalVector")
    if (
        len(source_frames) < 5
        or len(motion_frames) < 5
        or not isinstance(horizontal_vector, (list, tuple))
        or len(horizontal_vector) < 2
    ):
        return _unavailable_metrics(
            source_frame_count=len(source_frames),
            motion_frame_count=len(motion_frames),
            reason="fixed_projection_reference_unavailable",
        )
    selected = _projection_metrics(
        source_frames,
        motion_frames,
        horizontal_vector=(float(horizontal_vector[0]), float(horizontal_vector[1])),
        mirror=projection_reference.get("mirrored") is True,
        swap_bilateral=projection_reference.get("bilateralAssignment") == "swapped",
    )
    if selected.get("comparableFrameCount", 0) < 5:
        return _unavailable_metrics(
            source_frame_count=len(source_frames),
            motion_frame_count=len(motion_frames),
            reason="fixed_projection_alignment_unavailable",
        )
    return {
        **selected,
        "available": True,
        "sourceFrameCount": len(source_frames),
        "motionFrameCount": len(motion_frames),
        "evaluatedProjectionCount": 1,
        "projectionSelection": "fixed_reference",
    }


def _projection_metrics_for_angle(
    source_frames: list[dict[str, Any]],
    motion_frames: list[dict[str, Any]],
    *,
    angle_degrees: float,
    mirror: bool,
    swap_bilateral: bool,
) -> dict[str, Any]:
    angle_radians = math.radians(angle_degrees)
    return _projection_metrics(
        source_frames,
        motion_frames,
        horizontal_vector=(math.cos(angle_radians), math.sin(angle_radians)),
        mirror=mirror,
        swap_bilateral=swap_bilateral,
    )


def _projection_selection_key(metrics: dict[str, Any]) -> tuple[float, float]:
    return (
        _number_or_inf(metrics.get("medianJointErrorBodyRatio")),
        _number_or_inf(metrics.get("p90JointErrorBodyRatio")),
    )


def _projection_metrics(
    source_frames: list[dict[str, Any]],
    motion_frames: list[dict[str, Any]],
    *,
    horizontal_vector: tuple[float, float],
    mirror: bool,
    swap_bilateral: bool,
    image_transform: tuple[float, ...] | None = None,
) -> dict[str, Any]:
    joint_errors: dict[str, list[float]] = {name: [] for name in POSE_JOINTS}
    angle_errors: dict[str, list[float]] = {name: [] for name in ANGLE_CHAINS}
    angle_samples: dict[str, list[tuple[float, float]]] = {name: [] for name in ANGLE_CHAINS}
    output_unobservable = {name: 0 for name in ANGLE_CHAINS}
    comparable_frames = 0
    expected_observations = len(source_frames) * len(POSE_JOINTS)
    observed = 0

    transform = image_transform if image_transform is not None else _global_similarity_transform(
        source_frames,
        motion_frames,
        horizontal_vector=horizontal_vector,
        mirror=mirror,
        swap_bilateral=swap_bilateral,
    )
    if transform is None:
        return {
            "projectionHorizontalAxis": _projection_axis_label(horizontal_vector),
            "projectionHorizontalVector": list(horizontal_vector),
            "projectionHorizontalAngleDegrees": math.degrees(
                math.atan2(horizontal_vector[1], horizontal_vector[0])
            ),
            "mirrored": mirror,
            "bilateralAssignment": "swapped" if swap_bilateral else "identity",
            "comparableFrameCount": 0,
            "comparableFrameRatio": 0.0,
            "jointObservationCoverage": 0.0,
            "medianJointErrorBodyRatio": None,
            "p90JointErrorBodyRatio": None,
            "medianLowerJointErrorBodyRatio": None,
            "p90JointAngleErrorDegrees": None,
            "perJointMedianErrorBodyRatio": {},
            "perAngleMedianErrorDegrees": {},
            "angleComparisonSpace": "camera_frame_3d_lifted_source",
        }

    for source_frame in source_frames:
        motion_frame = _motion_frame_at_time(motion_frames, source_frame["time"])
        if motion_frame is None:
            continue
        source_joints = source_frame["joints"]
        motion_joints = motion_frame["joints"]
        fit_names = [
            name
            for name in ALIGNMENT_JOINTS
            if name in source_joints
            and _bilateral_name(name, swap=swap_bilateral) in motion_joints
        ]
        if len(fit_names) < 3:
            continue
        body_span = _body_span(source_joints.values())
        if body_span <= 1e-9:
            continue
        comparable_frames += 1
        projected: dict[str, tuple[float, float]] = {}
        camera_motion: dict[str, tuple[float, float, float]] = {}
        for name, point in motion_joints.items():
            mapped = _bilateral_name(name, swap=swap_bilateral)
            camera_point = _motion_point_in_camera_frame(
                point,
                horizontal_vector=horizontal_vector,
                mirror=mirror,
            )
            if camera_point is None:
                continue
            camera_motion[mapped] = camera_point
            projected[mapped] = _apply_similarity(
                (camera_point[0], -camera_point[1]),
                transform,
            )
        for name in POSE_JOINTS:
            source_point = source_joints.get(name)
            motion_point = projected.get(name)
            if source_point is None or motion_point is None:
                continue
            observed += 1
            joint_errors[name].append(math.dist(source_point, motion_point) / body_span)
        for name, chain in ANGLE_CHAINS.items():
            if any(joint not in source_joints or joint not in camera_motion for joint in chain):
                continue
            confidence = source_frame.get("jointConfidence", {})
            if not all(confidence.get(joint, 1.0) >= 0.35 for joint in chain):
                continue
            if not all(
                math.dist(source_joints[a], source_joints[b]) > body_span * 0.07
                for a, b in zip(chain, chain[1:])
            ):
                continue
            # Same-space angles: lift each 2D source landmark into the registered
            # camera frame using that joint's motion depth, then compare 3D chain
            # angles. Avoids mixing image-plane angles with projected-3D angles.
            lifted: dict[str, tuple[float, float, float]] = {}
            well_conditioned = True
            for joint in chain:
                lifted_point = _lift_source_joint_to_camera_frame(
                    source_joints[joint],
                    camera_motion[joint],
                    transform=transform,
                )
                if lifted_point is None:
                    well_conditioned = False
                    break
                lifted[joint] = lifted_point
            if not well_conditioned:
                output_unobservable[name] += 1
                continue
            body_span_3d = _body_span_3d(camera_motion.values())
            if body_span_3d <= 1e-9:
                output_unobservable[name] += 1
                continue
            if not all(
                math.dist(lifted[a], lifted[b]) > body_span_3d * 0.07
                and math.dist(camera_motion[a], camera_motion[b]) > body_span_3d * 0.07
                for a, b in zip(chain, chain[1:])
            ):
                output_unobservable[name] += 1
                continue
            source_angle = _angle_degrees_3d(*(lifted[joint] for joint in chain))
            motion_angle = _angle_degrees_3d(*(camera_motion[joint] for joint in chain))
            if source_angle is None or motion_angle is None:
                output_unobservable[name] += 1
                continue
            angle_samples[name].append((source_angle, motion_angle))
            angle_errors[name].append(abs(source_angle - motion_angle))

    all_joint_errors = [value for values in joint_errors.values() for value in values]
    lower_errors = [value for name in LOWER_BODY_JOINTS for value in joint_errors[name]]
    all_angle_errors = [value for values in angle_errors.values() for value in values]
    return {
        "projectionHorizontalAxis": _projection_axis_label(horizontal_vector),
        "projectionHorizontalVector": list(horizontal_vector),
        "projectionHorizontalAngleDegrees": math.degrees(
            math.atan2(horizontal_vector[1], horizontal_vector[0])
        ),
        "mirrored": mirror,
        "bilateralAssignment": "swapped" if swap_bilateral else "identity",
        "comparableFrameCount": comparable_frames,
        "comparableFrameRatio": comparable_frames / len(source_frames) if source_frames else 0.0,
        "jointObservationCoverage": observed / expected_observations if expected_observations else 0.0,
        "medianJointErrorBodyRatio": _median(all_joint_errors),
        "p90JointErrorBodyRatio": _percentile(all_joint_errors, 0.90),
        "medianLowerJointErrorBodyRatio": _median(lower_errors),
        "p90JointAngleErrorDegrees": _percentile(all_angle_errors, 0.90),
        "perJointMedianErrorBodyRatio": {
            name: _median(values) for name, values in joint_errors.items()
        },
        "perAngleMedianErrorDegrees": {
            name: _median(values) for name, values in angle_errors.items()
        },
        "perAngleEndpointMetrics": {
            name: {
                **_endpoint_angle_metrics(values),
                "conditionedSampleCount": len(values),
                "outputForeshortenedSampleCount": output_unobservable[name],
                "comparisonUnresolved": len(values) < 6
                and len(values) + output_unobservable[name] >= 6,
            }
            for name, values in angle_samples.items()
        },
        "angleComparisonSpace": "camera_frame_3d_lifted_source",
    }


def _endpoint_angle_metrics(samples: list[tuple[float, float]]) -> dict[str, Any]:
    """Check each visible limb at its own extrema, without a bilateral average."""
    if len(samples) < 6:
        return {"available": False, "mismatch": False}
    angles = [sample[0] for sample in samples]
    extrema = (min(angles), max(angles))
    errors = []
    for extreme in extrema:
        phase = [abs(source - output) for source, output in samples if abs(source - extreme) <= 8]
        if len(phase) >= 3:
            errors.append(statistics.median(phase))
    return {"available": bool(errors), "maxEndpointMedianErrorDegrees": max(errors, default=0),
            "mismatch": any(error > 30 for error in errors)}


def _global_similarity_transform(
    source_frames: list[dict[str, Any]],
    motion_frames: list[dict[str, Any]],
    *,
    horizontal_vector: tuple[float, float],
    mirror: bool,
    swap_bilateral: bool,
) -> tuple[float, float, float, float, float, float] | None:
    """Fit one fixed camera transform for the whole clip.

    A per-frame similarity fit can rotate an incorrect pose into the source
    independently at every timestamp, hiding reversed torso lean, missing root
    travel, and support-posture errors. Camera projection and framing are fixed
    properties of a source interval, so their transform must be fixed too.
    """

    source_fit: list[tuple[float, float]] = []
    motion_fit: list[tuple[float, float]] = []
    for source_frame in source_frames:
        motion_frame = _motion_frame_at_time(motion_frames, source_frame["time"])
        if motion_frame is None:
            continue
        source_joints = source_frame["joints"]
        motion_joints = motion_frame["joints"]
        for name in ALIGNMENT_JOINTS:
            motion_name = _bilateral_name(name, swap=swap_bilateral)
            if name not in source_joints or motion_name not in motion_joints:
                continue
            source_fit.append(source_joints[name])
            motion_fit.append(
                _project_motion_point(
                    motion_joints[motion_name],
                    horizontal_vector=horizontal_vector,
                    mirror=mirror,
                )
            )
    if len(source_fit) < 3:
        return None
    return _similarity_transform(motion_fit, source_fit)


def _bilateral_name(name: str, *, swap: bool) -> str:
    if not swap:
        return name
    if name.startswith("left_"):
        return f"right_{name[5:]}"
    if name.startswith("right_"):
        return f"left_{name[6:]}"
    return name


def _pose_frames(payload: dict[str, Any], *, source: bool) -> list[dict[str, Any]]:
    frames_value = payload.get("frames")
    if not isinstance(frames_value, list):
        return []
    horizontal_scale = 1.0
    if source and payload.get("coordinateSpace") == "normalized_image_xy":
        try:
            width, height = float(payload["imageWidth"]), float(payload["imageHeight"])
        except (KeyError, TypeError, ValueError):
            return []  # A normalized image without dimensions is not metric geometry.
        if not math.isfinite(width + height) or min(width, height) <= 0:
            return []
        horizontal_scale = width / height
    origin = float(payload.get("sourceTimeOriginSec", 0.0)) if source else 0.0
    frames: list[dict[str, Any]] = []
    for index, frame in enumerate(frames_value):
        if not isinstance(frame, dict) or not isinstance(frame.get("joints"), dict):
            continue
        joints = {
            str(name): point
            for name, value in frame["joints"].items()
            if (point := _point(value, dimensions=2 if source else 3)) is not None
        }
        if source:
            joints = {name: (point[0] * horizontal_scale, point[1]) for name, point in joints.items()}
        time_value = frame.get("sourceTimeSec") if source else frame.get("timeSec")
        try:
            time_seconds = float(time_value) if time_value is not None else float(index)
        except (TypeError, ValueError):
            time_seconds = float(index)
        if not math.isfinite(time_seconds):
            continue
        confidence = frame.get("jointConfidence")
        confidence = {str(name): float(value) if isinstance(value, (float, int)) and math.isfinite(value) else 0.
                      for name, value in confidence.items()} if isinstance(confidence, dict) else {}
        if source:
            # Explicitly weak observations must not influence camera fitting or
            # spatial rejection either. Legacy absent confidence stays unknown.
            joints = {name: point for name, point in joints.items() if confidence.get(name, 1.) >= .35}
        frames.append({"time": time_seconds - origin, "joints": joints,
                       "jointConfidence": confidence})
    if not frames:
        return []
    frames.sort(key=lambda frame: frame["time"])
    start = frames[0]["time"]
    duration = frames[-1]["time"] - start
    for index, frame in enumerate(frames):
        frame["normalizedTime"] = (
            (frame["time"] - start) / duration
            if duration > 1e-9
            else index / max(1, len(frames) - 1)
        )
    return frames


def _motion_frame_at_time(frames: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    """Interpolate at the observed time without stretching or extrapolating coverage."""
    if not frames or time_seconds < frames[0]["time"] - 1e-8 or time_seconds > frames[-1]["time"] + 1e-8:
        return None
    index = bisect_left([frame["time"] for frame in frames], time_seconds)
    if index == 0:
        return frames[0]
    if index == len(frames):
        return frames[-1]
    left, right = frames[index - 1], frames[index]
    duration = right["time"] - left["time"]
    if duration <= 1e-9:
        return right
    ratio = (time_seconds - left["time"]) / duration
    return {"time": time_seconds, "joints": {
        name: tuple(a + ratio * (b - a) for a, b in zip(left["joints"][name], right["joints"][name]))
        for name in left["joints"].keys() & right["joints"].keys()
    }}


def _nearest_normalized_frame(
    frames: list[dict[str, Any]],
    normalized_time: float,
) -> dict[str, Any]:
    return min(frames, key=lambda frame: abs(float(frame["normalizedTime"]) - normalized_time))


def _point(value: Any, *, dimensions: int) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) < dimensions:
        return None
    try:
        point = tuple(float(value[index]) for index in range(dimensions))
    except (TypeError, ValueError):
        return None
    return point if all(math.isfinite(component) for component in point) else None


def _project_motion_point(
    point: tuple[float, ...],
    *,
    horizontal_axis: int | None = None,
    horizontal_vector: tuple[float, float] | None = None,
    mirror: bool,
) -> tuple[float, float]:
    camera = _motion_point_in_camera_frame(
        point,
        horizontal_axis=horizontal_axis,
        horizontal_vector=horizontal_vector,
        mirror=mirror,
    )
    if camera is None:
        raise ValueError("motion point must include xyz for camera projection")
    return (camera[0], -camera[1])


def _motion_point_in_camera_frame(
    point: tuple[float, ...],
    *,
    horizontal_axis: int | None = None,
    horizontal_vector: tuple[float, float] | None = None,
    mirror: bool,
) -> tuple[float, float, float] | None:
    if len(point) < 3:
        return None
    if horizontal_vector is None:
        horizontal_vector = (1.0, 0.0) if horizontal_axis == 0 else (0.0, 1.0)
    hx, hz = horizontal_vector
    x_cam = point[0] * hx + point[2] * hz
    z_cam = -point[0] * hz + point[2] * hx
    y_cam = point[1]
    if mirror:
        x_cam = -x_cam
    return (x_cam, y_cam, z_cam)


def _lift_source_joint_to_camera_frame(
    source_xy: tuple[float, float],
    motion_camera_xyz: tuple[float, float, float],
    *,
    transform: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float] | None:
    """Place a 2D source landmark into the motion camera frame with motion depth."""
    projected = _invert_similarity(source_xy, transform)
    if projected is None:
        return None
    return (projected[0], -projected[1], motion_camera_xyz[2])


def _invert_similarity(
    point: tuple[float, float],
    transform: tuple[float, float, float, float, float, float],
) -> tuple[float, float] | None:
    scale_cos, scale_sin, source_x, source_y, target_x, target_y = transform
    x = point[0] - target_x
    y = point[1] - target_y
    denominator = scale_cos * scale_cos + scale_sin * scale_sin
    if denominator <= 1e-20:
        return None
    return (
        (scale_cos * x + scale_sin * y) / denominator + source_x,
        (-scale_sin * x + scale_cos * y) / denominator + source_y,
    )


def _projection_axis_label(horizontal_vector: tuple[float, float]) -> str:
    if abs(horizontal_vector[1]) <= 1e-9:
        return "x"
    if abs(horizontal_vector[0]) <= 1e-9:
        return "z"
    return "xz"


def _similarity_transform(
    source: list[tuple[float, float]],
    target: list[tuple[float, float]],
) -> tuple[float, float, float, float, float, float] | None:
    if len(source) != len(target) or len(source) < 3:
        return None
    source_center = (
        statistics.mean(point[0] for point in source),
        statistics.mean(point[1] for point in source),
    )
    target_center = (
        statistics.mean(point[0] for point in target),
        statistics.mean(point[1] for point in target),
    )
    source_zero = [
        (point[0] - source_center[0], point[1] - source_center[1]) for point in source
    ]
    target_zero = [
        (point[0] - target_center[0], point[1] - target_center[1]) for point in target
    ]
    denominator = sum(x * x + y * y for x, y in source_zero)
    if denominator <= 1e-12:
        return None
    # Projection already searches camera yaw in the world XZ plane and flips
    # world Y into image Y.  Allowing another free image-plane rotation here
    # mixes gravity with the horizontal axis: an incorrect crouch can be
    # rotated toward an upright source, and a correct vertical jump can be
    # scored as horizontal drift.  Fit scale and framing only so world up
    # remains source-image up. Camera-roll normalization, when needed, belongs
    # in source preprocessing where it can be measured from the image.
    scale = sum(
        source_x * target_x + source_y * target_y
        for (source_x, source_y), (target_x, target_y) in zip(source_zero, target_zero)
    ) / denominator
    if not math.isfinite(scale) or scale <= 1e-12:
        return None
    return (
        scale,
        0.0,
        source_center[0],
        source_center[1],
        target_center[0],
        target_center[1],
    )


def _apply_similarity(
    point: tuple[float, float],
    transform: tuple[float, float, float, float, float, float],
) -> tuple[float, float]:
    scale_cos, scale_sin, source_x, source_y, target_x, target_y = transform
    x = point[0] - source_x
    y = point[1] - source_y
    return (
        scale_cos * x - scale_sin * y + target_x,
        scale_sin * x + scale_cos * y + target_y,
    )


def _angle_degrees(
    first: tuple[float, float],
    middle: tuple[float, float],
    last: tuple[float, float],
) -> float | None:
    left = (first[0] - middle[0], first[1] - middle[1])
    right = (last[0] - middle[0], last[1] - middle[1])
    denominator = math.hypot(*left) * math.hypot(*right)
    if denominator <= 1e-12:
        return None
    cosine = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _angle_degrees_3d(
    first: tuple[float, float, float],
    middle: tuple[float, float, float],
    last: tuple[float, float, float],
) -> float | None:
    left = (first[0] - middle[0], first[1] - middle[1], first[2] - middle[2])
    right = (last[0] - middle[0], last[1] - middle[1], last[2] - middle[2])
    left_length = math.sqrt(sum(component * component for component in left))
    right_length = math.sqrt(sum(component * component for component in right))
    if left_length <= 1e-12 or right_length <= 1e-12:
        return None
    cosine = sum(a * b for a, b in zip(left, right)) / (left_length * right_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _body_span(points: Iterable[tuple[float, ...]]) -> float:
    points_list = list(points)
    if len(points_list) < 4:
        return 0.0
    return max(
        max(point[axis] for point in points_list) - min(point[axis] for point in points_list)
        for axis in (0, 1)
    )


def _body_span_3d(points: Iterable[tuple[float, float, float]]) -> float:
    points_list = list(points)
    if len(points_list) < 4:
        return 0.0
    return max(
        max(point[axis] for point in points_list) - min(point[axis] for point in points_list)
        for axis in (0, 1, 2)
    )


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _number_or_inf(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.inf
    return parsed if math.isfinite(parsed) else math.inf


def _unavailable_metrics(
    *,
    source_frame_count: int,
    motion_frame_count: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "sourceFrameCount": source_frame_count,
        "motionFrameCount": motion_frame_count,
        "comparableFrameCount": 0,
        "comparableFrameRatio": 0.0,
    }
