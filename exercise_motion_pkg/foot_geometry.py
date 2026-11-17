"""Calibrated ankle-to-forefoot bones and material shoe support points."""
from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np

from .contact_constraints import (
    contact_frame_bounds, motion_support_contacts, observed_ground_contact_mask,
)

SHOE_LENGTH_RATIO = 1.15
_SHOE_ORIENTATION_CONTEXT = ContextVar('shoe_orientation_context', default=None)


def _build_shoe_orientation_context(payload, evidence=None):
    from .contact_constraints import (
        fit_frame_foot_patch_states_by_side, motion_space_support_evidence,
        observed_ground_contact_mask,
    )
    frames, names = payload.get('frames') or [], payload.get('jointNames') or []
    evidence = evidence if isinstance(evidence, dict) else motion_space_support_evidence(payload)
    states = fit_frame_foot_patch_states_by_side(evidence, len(frames))
    ground = observed_ground_contact_mask(evidence, names, len(frames))
    if ground.shape != (len(frames), len(names)):
        ground = np.zeros((len(frames), len(names)), dtype=bool)
    body_support = evidence.get('bodySupport') or payload.get('bodySupport') or {}
    support_geometry = (body_support if body_support.get('status') == 'confirmed'
                        else evidence if evidence.get('status') == 'confirmed' else {})
    mirrored_partial_sides = set()
    if (payload.get('canonicalExecution') or {}).get('legs') == 'mirrored':
        observed_partial_sides = _source_partial_foot_observation_sides(
            payload, evidence, states, len(frames))
        if len(observed_partial_sides) == 1:
            mirrored_partial_sides = observed_partial_sides
    return {'states': states, 'ground': ground,
            'planeGroups': support_geometry.get('coplanarGroups') or [],
            'evidence': evidence,
            'mirroredPartialSides': mirrored_partial_sides}


@contextmanager
def shoe_orientation_context(context):
    token = _SHOE_ORIENTATION_CONTEXT.set(context)
    try:
        yield
    finally:
        _SHOE_ORIENTATION_CONTEXT.reset(token)


def calibrated_foot_rest_pitches(points, names, evidence, frame_times=None, *, canonical_execution=None):
    """Only timed, observed full-sole ground samples define each rig-side neutral."""
    points = np.asarray(points, dtype=float)
    from .contact_constraints import (
        fit_frame_foot_patch_states_by_side,
        contact_frame_bounds, is_observed_ground_contact, is_stationary_contact,
        mapped_foot_patch_state_indices, motion_support_contacts,
    )

    patch = (evidence or {}).get('footPatchEvidence') or {}
    states_by_side = (patch.get('feet') or {}) if patch.get('available') is True else {}
    contacts = motion_support_contacts(evidence)
    result = {}
    for side in ('left', 'right'):
        ankle, toe = f'{side}_ankle', f'{side}_foot'
        if ankle not in names or toe not in names:
            continue
        flat = np.zeros(len(points), dtype=bool)
        for contact in contacts:
            if (contact.get('jointName') != toe
                    or contact.get('contactState') != 'full_sole'
                    or not is_stationary_contact(contact)
                    or not is_observed_ground_contact(contact, evidence)):
                continue
            start, end = contact_frame_bounds(contact, len(points))
            flat[start:end + 1] = True
        # The body-support anchor is an even stronger ground authority than a
        # loose contact interval, so do not drop its pitch samples. When a
        # temporal patch exists, still require every sampled frame to be an
        # explicit full-sole state; unknown, heel/toe-only and airborne samples
        # never enter a neutral-pitch estimate.
        patch_foot = states_by_side.get(side) if isinstance(states_by_side, dict) else None
        patch_states = patch_foot.get('states') if isinstance(patch_foot, dict) else None
        if isinstance(patch_states, list) and patch_states:
            fit_states = fit_frame_foot_patch_states_by_side(evidence, len(points))
            aligned_states = fit_states.get(side)
            if aligned_states is not None:
                explicit_full_sole = np.asarray([
                    state == 'full_sole' for state in aligned_states
                ], dtype=bool)
            else:
                source_times = frame_times if frame_times is not None else [None] * len(points)
                state_indexes = mapped_foot_patch_state_indices(
                    evidence, source_times, frame_count=len(points))
                explicit_full_sole = np.asarray([
                    index >= 0 and index < len(patch_states)
                    and str(patch_states[index]).casefold() == 'full_sole'
                    for index in state_indexes
                ], dtype=bool)
            flat &= explicit_full_sole
        vector = points[:, names.index(toe)] - points[:, names.index(ankle)]
        length = np.linalg.norm(vector, axis=-1)
        flat &= length > 1e-8
        if np.count_nonzero(flat) >= 3:
            result[side] = float(np.median(np.arcsin(np.clip(vector[flat, 1] / length[flat], -1., 1.))))
    if (canonical_execution or {}).get('legs') == 'mirrored' and result:
        # Bind geometry is shared technique intent, not additional contact evidence.
        common_pitch = float(np.mean(list(result.values())))
        result = {'left': common_pitch, 'right': common_pitch}
    return result


def canonical_shoe_calibration_evidence(payload):
    """Require complete shared bind geometry; report motion symmetry separately."""
    if (payload.get('canonicalExecution') or {}).get('legs') != 'mirrored':
        return {'required': False, 'passed': True}
    pitches = payload.get('footRestPitchRadians') or {}
    if not any(side in pitches for side in ('left', 'right')):
        return {'required': False, 'passed': True, 'reason': 'neutral_shoe_bind_calibration_unavailable'}
    values = [pitches.get(side) for side in ('left', 'right')]
    complete = all(isinstance(value, (int, float)) and np.isfinite(value) for value in values)
    passed = bool(complete and values[0] == values[1])
    result = {'required': True, 'passed': passed,
              'reason': None if passed else 'canonical_bilateral_shoe_bind_calibration_incomplete_or_inconsistent',
              'bindPitchRadians': dict(pitches)}
    errors = []
    for frame in payload.get('frames') or []:
        orientations = frame.get('shoeOrientation') or {}
        joints = frame.get('joints') or {}
        if not ({'left', 'right'} <= set(orientations)
                and {'left_hip', 'right_hip'} <= set(joints)):
            continue
        lateral = np.asarray(joints['right_hip']) - joints['left_hip']
        length = np.linalg.norm(lateral)
        if length <= 1e-9:
            continue
        lateral = lateral / length
        left = np.asarray(orientations['left'].get('forward'), dtype=float)
        right = np.asarray(orientations['right'].get('forward'), dtype=float)
        if (left.shape != (3,) or right.shape != (3,) or not np.isfinite(left).all()
                or not np.isfinite(right).all()):
            continue
        mirrored = right - 2 * np.dot(right, lateral) * lateral
        errors.append(float(np.rad2deg(np.arccos(np.clip(np.dot(left, mirrored), -1., 1.)))))
    if errors:
        # Native temporal articulation remains owned by its independent evidence gates.
        result['medianReflectedMaterialForwardErrorDegrees'] = float(np.median(errors))
        result['maximumReflectedMaterialForwardErrorDegrees'] = max(errors)
    return result


def canonical_material_shoe_evidence(payload, points=None, cursors=None):
    """Verify the rendered material shoes are reflection-symmetric on mirrored legs."""
    if (payload.get('canonicalExecution') or {}).get('legs') != 'mirrored':
        return {'required': False, 'passed': True}
    from .rig_playback import PLAYBACK_CONTACT_LIMIT_METERS
    frames = payload.get('frames') or []
    names = list(payload.get('jointNames')
                 or (payload.get('fixedRig') or {}).get('jointNames') or [])
    if not frames or not names:
        return {'required': True, 'passed': False,
                'reason': 'canonical_material_shoe_frame_geometry_unavailable'}
    required_joints = ('left_hip', 'right_hip', 'left_ankle', 'left_foot',
                       'right_ankle', 'right_foot')
    missing_joints = [name for name in required_joints if name not in names]
    if missing_joints:
        return {'required': True, 'passed': False,
                'reason': 'canonical_material_shoe_joint_geometry_unavailable',
                'missingJoints': missing_joints}
    try:
        if points is None:
            rig = payload.get('fixedRig')
            if isinstance(rig, dict) and rig.get('coordinates') and rig.get('jointNames'):
                count = len(rig['coordinates'])
                cyclic = bool((payload.get('loop') or {}).get('enabled'))
                cursors = np.arange(count * 4 if cyclic else (count - 1) * 4 + 1) / 4
                from .rig_playback import _native_sampling_rig, sample_rig
                points, side_axes = sample_rig(
                    _native_sampling_rig(payload), cursors, wrap=cyclic,
                    return_side_axes=True)
                sampling = 'fixedRigQuarterFrame'
            else:
                points = np.asarray([
                    [frame['joints'][name] for name in names] for frame in frames
                ], dtype=float)
                cursors = np.arange(len(frames), dtype=float)
                sampling = 'storedFramePoints'
                side_axes = None
        else:
            points = np.asarray(points, dtype=float)
            if cursors is None:
                if points.shape != (len(frames), len(names), 3):
                    return {'required': True, 'passed': False,
                            'reason': 'canonical_material_shoe_cursors_unavailable'}
                cursors = np.arange(len(frames), dtype=float)
            cursors = np.asarray(cursors, dtype=float).reshape(-1)
            sampling = 'explicitPlaybackSamples'
            side_axes = None
            rig = payload.get('fixedRig')
            if isinstance(rig, dict) and rig.get('contactFootTracks', {}).get('version') == 2:
                from .rig_playback import _native_sampling_rig, sample_rig
                _, side_axes = sample_rig(
                    _native_sampling_rig(payload), cursors,
                    wrap=bool((payload.get('loop') or {}).get('enabled')),
                    return_side_axes=True)
        cursors = np.asarray(cursors, dtype=float).reshape(-1)
        if (points.ndim != 3 or points.shape[1:] != (len(names), 3)
                or not len(cursors) or points.shape[0] != len(cursors)
                or not np.isfinite(points).all() or not np.isfinite(cursors).all()):
            raise ValueError('canonical material shoe samples are malformed')
        # Inspect what the renderer receives, not a newly inferred export.
        for side in ('left', 'right'):
            stored = [(frame.get('shoeOrientation') or {}).get(side) for frame in frames]
            if any(value is not None for value in stored):
                if not all(isinstance(value, dict) for value in stored):
                    raise ValueError('incomplete serialized shoe orientation track')
                for key in ('forward', 'side'):
                    values = np.asarray([value[key] for value in stored], dtype=float)
                    if values.shape != (len(frames), 3) or not np.isfinite(values).all():
                        raise ValueError('malformed serialized shoe orientation track')
        geometry = _sample_material_foot_geometry(
            payload, cursors, points, serialized_only=True, side_axes_override=side_axes)
        missing_sides = [side for side in ('left', 'right') if side not in geometry]
        if missing_sides:
            return {'required': True, 'passed': False,
                    'reason': 'canonical_material_shoe_sampled_geometry_unavailable',
                    'missingSides': missing_sides}
        scale = float(foot_scale_from_pose(points[0], names))
        if not np.isfinite(scale) or scale < 0.:
            raise ValueError('canonical material shoe scale is unavailable')
        pitches = payload.get('footRestPitchRadians') or {}
        vertices = {}
        for side in ('left', 'right'):
            pitch = float(pitches[side]) if side in pitches else None
            ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
            vertices[side] = shoe_vertices(
                points[:, ankle], points[:, toe], geometry[side]['lateral'], pitch,
                scale, orientation=geometry[side]['orientation'],
                native_geometry=geometry[side].get('nativeGeometry'))
        if not all(np.isfinite(value).all() for value in vertices.values()):
            raise ValueError('canonical material shoe vertices are not finite')
        midpoint = .5 * (points[:, names.index('left_hip')]
                         + points[:, names.index('right_hip')])
        lateral = points[:, names.index('right_hip')] - points[:, names.index('left_hip')]
        lengths = np.linalg.norm(lateral, axis=1, keepdims=True)
        if not np.isfinite(lengths).all() or not np.all(lengths > 1e-9):
            return {'required': True, 'passed': False,
                    'reason': 'canonical_material_shoe_hip_axis_unavailable'}
        lateral = lateral / lengths
        offset = vertices['right'] - midpoint[:, None, :]
        reflected = vertices['right'] - 2 * np.sum(
            offset * lateral[:, None, :], axis=-1, keepdims=True) * lateral[:, None, :]
        distances = np.linalg.norm(
            vertices['left'][:, :, None, :] - reflected[:, None, :, :], axis=-1)
        error = max(float(np.min(distances, axis=2).max()),
                    float(np.min(distances, axis=1).max()))
    except (KeyError, TypeError, ValueError, IndexError, FloatingPointError, OverflowError):
        return {'required': True, 'passed': False,
                'reason': 'canonical_material_shoe_geometry_unavailable'}
    passed = bool(np.isfinite(error) and error <= PLAYBACK_CONTACT_LIMIT_METERS)
    return {'required': True, 'passed': passed,
            'reason': None if passed else 'canonical_material_shoe_mirror_error_exceeds_tolerance',
            'maximumReflectedVertexErrorMeters': error,
            'toleranceMeters': PLAYBACK_CONTACT_LIMIT_METERS,
            'sampleCount': int(len(cursors)),
            'sampling': sampling,
            'evaluatedSides': ['left', 'right']}


def material_foot_points(ankle, toe, side, rest_pitch, orientation=None,
                         native_geometry=None):
    """Mirror native shoe origins: calibrated forefoot or uncalibrated ankle."""
    if native_geometry is not None:
        from .native_foot_geometry import native_foot_marker_world

        return native_foot_marker_world(ankle, toe, side, native_geometry)
    vector = np.asarray(toe) - np.asarray(ankle)
    length = np.linalg.norm(vector, axis=-1, keepdims=True)
    forward = vector / np.maximum(length, 1e-12)
    lateral = np.asarray(side) - forward * np.sum(np.asarray(side) * forward, axis=-1, keepdims=True)
    lateral /= np.maximum(np.linalg.norm(lateral, axis=-1, keepdims=True), 1e-12)
    up = np.cross(lateral, forward)
    pitch = 0. if rest_pitch is None else float(rest_pitch)
    sole_forward = forward * np.cos(pitch) - up * np.sin(pitch)
    if orientation is not None:
        sole_forward = np.asarray(orientation['forward'], dtype=float)
        lateral = np.asarray(orientation['side'], dtype=float)
    if rest_pitch is None and orientation is None:
        return np.asarray(ankle) - .08 * length * forward, np.asarray(toe)
    return np.asarray(toe) - SHOE_LENGTH_RATIO * length * sole_forward, np.asarray(toe)


def _native_shoe_vertices(ankle, toe, side, foot_scale, native_geometry):
    """Native-ring shape shared by every Python physical consumer."""
    from .native_foot_geometry import native_foot_bone_frame, native_foot_marker_world

    ankle = np.asarray(ankle, dtype=float)
    forward, lateral, up, length = native_foot_bone_frame(ankle, toe, side)
    heel, toe_marker = native_foot_marker_world(ankle, toe, side, native_geometry)

    def components(point):
        delta = point - ankle
        return (np.sum(delta * forward, axis=-1, keepdims=True),
                np.sum(delta * lateral, axis=-1, keepdims=True),
                np.sum(delta * up, axis=-1, keepdims=True))

    heel_f, heel_l, heel_u = components(heel)
    toe_f, toe_l, toe_u = components(toe_marker)
    width = np.maximum(length * .26, foot_scale * .15)
    height = np.maximum(length * .28, foot_scale * .15)

    def lerp(start, stop, fraction):
        return start + (stop - start) * fraction

    rings = []
    for fraction, center_height, width_scale, height_scale in (
            (0., -.05, .78, .55), (.36, .12, 1., .72), (1., -.25, .76, .35)):
        center = (ankle + forward * lerp(heel_f, toe_f, fraction)
                  + lateral * lerp(heel_l, toe_l, fraction)
                  + up * (lerp(heel_u, toe_u, fraction)
                          + height * (center_height + .60)))
        w, h = lateral * width * width_scale, up * height * height_scale
        top_width = w * .88
        corners = np.stack([center + top_width + h, center - top_width + h,
                            center - w - h, center + w - h], axis=-2)
        ring = np.stack([corners * .7 + np.roll(corners, shift, axis=-2) * .3
                         for shift in (1, -1)], axis=-2).reshape(
                             *corners.shape[:-2], 8, 3)
        rings.append(ring)
    # Caps sit on the physical extrema; no extra legacy forward margin.
    rear_tip = (rings[0][..., 0, :] + rings[0][..., 4, :]) * .5
    toe_tip = (rings[-1][..., 0, :] + rings[-1][..., 4, :]) * .5
    return np.concatenate([*rings, rear_tip[..., None, :], toe_tip[..., None, :]],
                          axis=-2)


def shoe_vertices(ankle, toe, side, rest_pitch, foot_scale, orientation=None,
                  native_geometry=None):
    """The production shoe's three beveled rings and two tips, in vertex order."""
    if native_geometry is not None:
        return _native_shoe_vertices(
            ankle, toe, side, foot_scale, native_geometry)
    heel, toe = material_foot_points(ankle, toe, side, rest_pitch, orientation)
    length = np.linalg.norm(toe - ankle, axis=-1, keepdims=True)
    forward = (np.asarray(orientation['forward'], dtype=float) if orientation is not None
               else ((np.asarray(toe) - np.asarray(ankle)) / np.maximum(length, 1e-12)
                     if rest_pitch is None else
                     (toe - heel) / np.maximum(SHOE_LENGTH_RATIO * length, 1e-12)))
    side_axis = np.asarray(orientation['side'], dtype=float) if orientation is not None else np.asarray(side)
    lateral = side_axis - forward * np.sum(side_axis * forward, axis=-1, keepdims=True)
    lateral /= np.maximum(np.linalg.norm(lateral, axis=-1, keepdims=True), 1e-12)
    up = np.cross(lateral, forward)
    width = np.maximum(length * .26, foot_scale * .15)
    height = np.maximum(length * .28, foot_scale * .15)
    rings = []
    for fraction, center_height, width_scale, height_scale in (
            (0., -.05, .78, .55), (.36, .12, 1., .72), (1., -.25, .76, .35)):
        center = heel + forward * (SHOE_LENGTH_RATIO * length * fraction) + up * height * (center_height + .60)
        w, h = lateral * width * width_scale, up * height * height_scale
        top_width = w * .88
        corners = np.stack([center + top_width + h, center - top_width + h,
                            center - w - h, center + w - h], axis=-2)
        ring = np.stack([corners * .7 + np.roll(corners, shift, axis=-2) * .3
                         for shift in (1, -1)], axis=-2).reshape(*corners.shape[:-2], 8, 3)
        rings.append(ring)
    rear_tip = (rings[0][..., 0, :] + rings[0][..., 4, :]) * .5 - forward * height * .20
    toe_tip = (rings[-1][..., 0, :] + rings[-1][..., 4, :]) * .5 + forward * height * .20
    return np.concatenate([*rings, rear_tip[..., None, :], toe_tip[..., None, :]], axis=-2)


def free_foot_floor_translation(ankle, toe, *, floor_y, rest_pitch_radians,
                                foot_scale, side_axis):
    """Return the smallest upward shift that clears the rendered shoe from floor."""
    ankle, toe = np.asarray(ankle, dtype=float), np.asarray(toe, dtype=float)
    side_axis = np.asarray(side_axis, dtype=float)
    values = (ankle, toe, side_axis)
    if any(value.shape != (3,) or not np.isfinite(value).all() for value in values):
        raise ValueError('foot geometry inputs must be finite 3D vectors')
    try:
        floor_y, foot_scale = map(float, (floor_y, foot_scale))
        rest_pitch_radians = (None if rest_pitch_radians is None else float(rest_pitch_radians))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('floor, pitch, and scale must be finite numbers') from error
    foot_forward = toe - ankle
    foot_length_squared = float(np.dot(foot_forward, foot_forward))
    if (not np.isfinite([floor_y, foot_scale]).all()
            or (rest_pitch_radians is not None and not np.isfinite(rest_pitch_radians))
            or foot_scale <= 0. or foot_length_squared <= 1e-16):
        raise ValueError('floor, pitch, scale, and foot axes must be valid')
    side_projection = side_axis - foot_forward * (
        np.dot(side_axis, foot_forward) / foot_length_squared)
    if np.linalg.norm(side_projection) <= 1e-8:
        raise ValueError('floor, pitch, scale, and foot axes must be valid')
    lowest = float(shoe_vertices(
        ankle, toe, side_axis, rest_pitch_radians, foot_scale)[:, 1].min())
    return max(0., floor_y - lowest)


def foot_scale_from_pose(points, names):
    def span(a, b):
        return np.linalg.norm(points[names.index(a)] - points[names.index(b)]) if a in names and b in names else 0.
    return max(span('left_hip', 'right_hip') * .98, span('left_shoulder', 'right_shoulder') * .58)


def material_floor_heights(points, names, rest_pitches, foot_scale, side_axes):
    """Replace ankle floor rows with shoes oriented by rendered bone sides."""
    heights = points[:, :, 1].copy()
    for side in ('left', 'right'):
        if f'{side}_ankle' not in names or f'{side}_foot' not in names:
            continue
        pitch = (float(rest_pitches[side]) if side in rest_pitches else None)
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        value = side_axes[side]
        lateral = np.asarray(value.get('lateral') if isinstance(value, dict) else value,
                             dtype=float)
        orientation = value.get('orientation') if isinstance(value, dict) else None
        vertices = shoe_vertices(points[:, ankle], points[:, toe], lateral, pitch, foot_scale,
                                 orientation=orientation,
                                 native_geometry=(value.get('nativeGeometry')
                                                  if isinstance(value, dict) else None))
        heights[:, ankle] = np.minimum(heights[:, ankle], np.min(vertices[:, :, 1], axis=1))
    return heights


def _sample_material_foot_geometry(payload, cursors, points, *, resolved_sides=None,
                                   keyframe_points=None, serialized_only=False,
                                   side_axes_override=None):
    """Resolve rendered shoe heel/toe points and side axes at rig samples."""
    if 'materialFrames' in (payload.get('fixedRig') or {}):
        from .native_material_frames import material_axes
        from .native_foot_geometry import validated_native_foot_geometry
        rig = payload['fixedRig']
        axes = material_axes(rig, cursors, wrap=bool((payload.get('loop') or {}).get('enabled')))
        native = validated_native_foot_geometry(payload.get('nativeFootGeometry'))
        if native is None:
            raise ValueError('materialFrames requires native foot geometry')
        names = payload['jointNames']
        points = np.asarray(points, dtype=float)
        result = {}
        for side, axis in axes.items():
            ankle, foot = [names.index(f'{side}_{part}') for part in ('ankle', 'foot')]
            override = (side_axes_override or {}).get(side)
            if override is not None:
                axis = np.asarray(override, dtype=float).copy()
            forward = points[:, foot] - points[:, ankle]
            forward /= np.maximum(np.linalg.norm(forward, axis=1, keepdims=True), 1e-12)
            axis = axis - forward*np.sum(axis*forward, axis=1, keepdims=True)
            length = np.linalg.norm(axis, axis=1, keepdims=True)
            if np.any(length < 1e-8) or not np.isfinite(axis).all():
                raise ValueError('materialFrames returned side is degenerate')
            axis /= length
            heel, toe = material_foot_points(points[:, ankle], points[:, foot], axis, None,
                                             native_geometry=native['sides'][side])
            result[side] = {'heel': heel, 'toe': toe, 'lateral': axis,
                            'forward': forward, 'orientation': {'forward': forward, 'side': axis},
                            'nativeGeometry': native['sides'][side]}
        return result
    from .temporal_quality import rendered_leg_sides

    frames, names = payload['frames'], payload['jointNames']
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    points = np.asarray(points, dtype=float)
    if points.shape != (len(cursors), len(names), 3):
        raise ValueError('sampled points must have shape (len(cursors), joint_count, 3)')
    if keyframe_points is None:
        keyframe_points = np.asarray([
            [frame['joints'][name] for name in names] for frame in frames
        ], dtype=float)
    else:
        keyframe_points = np.asarray(keyframe_points, dtype=float)
    if keyframe_points.shape != (len(frames), len(names), 3):
        raise ValueError('keyframe points must match frame and joint counts')
    resolved = (rendered_leg_sides(frames) if resolved_sides is None
                else resolved_sides)
    from .native_foot_geometry import validated_native_foot_geometry
    native = validated_native_foot_geometry(payload.get('nativeFootGeometry'))
    if side_axes_override is not None and not isinstance(side_axes_override, dict):
        raise ValueError('sampled native side axes must be a side-keyed mapping')
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % len(frames)
    alpha = cursors - first
    pitches = payload.get('footRestPitchRadians') or {}
    orientation_tracks = ({} if serialized_only else shoe_orientation_tracks(
        payload, keyframe_points, resolved_sides=resolved))
    stored_keyframe_points = np.asarray([
        [frame['joints'][name] for name in names] for frame in frames
    ], dtype=float)
    if (np.allclose(keyframe_points, stored_keyframe_points, rtol=0., atol=1e-9)
            and frames and all(isinstance(frame.get('shoeOrientation'), dict)
                               for frame in frames)):
        for side in ('left', 'right'):
            if all(isinstance(frame['shoeOrientation'].get(side), dict)
                   and {'forward', 'side'} <= set(frame['shoeOrientation'][side])
                   for frame in frames):
                orientation_tracks[side] = {
                    'forward': _unit_rows(np.asarray([
                        frame['shoeOrientation'][side]['forward'] for frame in frames
                    ], dtype=float)),
                    'side': _unit_rows(np.asarray([
                        frame['shoeOrientation'][side]['side'] for frame in frames
                    ], dtype=float)),
                }
    result = {}
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        key = f'{ankle_name}->{toe_name}'
        resolved_lateral = np.asarray([
            resolved[index].get(key, frame.get('boneSides', {}).get(key, [0., 0., 1.]))
            for index, frame in enumerate(frames)
        ], dtype=float)
        lateral = (resolved_lateral[first] * (1. - alpha[:, None])
                   + resolved_lateral[last] * alpha[:, None])
        exported = np.asarray([
            key in frames[a].get('boneSides', {}) and key in frames[b].get('boneSides', {})
            for a, b in zip(first, last)
        ], dtype=bool)
        exported_rows = np.flatnonzero(exported)
        if exported_rows.size:
            a, b = first[exported_rows], last[exported_rows]
            sample_vector = points[exported_rows, toe] - points[exported_rows, ankle]
            sample_axis = sample_vector / np.maximum(
                np.linalg.norm(sample_vector, axis=1, keepdims=True), 1e-12)

            def endpoint_side(endpoint):
                source_axis = np.asarray([
                    np.asarray(frames[index]['joints'][toe_name], dtype=float)
                    - np.asarray(frames[index]['joints'][ankle_name], dtype=float)
                    for index in endpoint
                ])
                source_axis /= np.maximum(
                    np.linalg.norm(source_axis, axis=1, keepdims=True), 1e-12)
                candidate_axis = keyframe_points[endpoint, toe] - keyframe_points[endpoint, ankle]
                candidate_axis /= np.maximum(
                    np.linalg.norm(candidate_axis, axis=1, keepdims=True), 1e-12)
                source_side = np.asarray([
                    frames[index]['boneSides'][key] for index in endpoint
                ], dtype=float)
                source_side -= source_axis * np.sum(
                    source_side * source_axis, axis=1, keepdims=True)
                source_side /= np.maximum(
                    np.linalg.norm(source_side, axis=1, keepdims=True), 1e-12)
                candidate_side = transport_sides(
                    source_side, source_axis, candidate_axis, source_side)
                return transport_sides(
                    candidate_side, candidate_axis, sample_axis,
                    lateral[exported_rows].copy())

            start_side, end_side = endpoint_side(a), endpoint_side(b)
            angle = np.arctan2(
                np.sum(sample_axis * np.cross(start_side, end_side), axis=1),
                np.sum(start_side * end_side, axis=1),
            ) * alpha[exported_rows]
            lateral[exported_rows] = (
                start_side * np.cos(angle)[:, None]
                + np.cross(sample_axis, start_side) * np.sin(angle)[:, None]
            )
        override = (side_axes_override or {}).get(side)
        if override is not None:
            override = np.asarray(override, dtype=float)
            if override.shape != lateral.shape:
                raise ValueError(f'{side} sampled side axes must match sampled cursors')
            valid_override = np.isfinite(override).all(axis=1)
            # Serialized frame axes own exact keys. Playback-only inferred axes
            # are used between keys where native contact sampling changed the chain.
            valid_override &= np.abs(cursors - np.round(cursors)) > 1e-12
            if np.any(valid_override):
                sample_axis = points[:, toe] - points[:, ankle]
                sample_axis /= np.maximum(np.linalg.norm(sample_axis, axis=1, keepdims=True), 1e-12)
                transported = override.copy()
                transported -= sample_axis * np.sum(
                    transported * sample_axis, axis=1, keepdims=True)
                transported /= np.maximum(np.linalg.norm(transported, axis=1, keepdims=True), 1e-12)
                lateral[valid_override] = transported[valid_override]
        orientation = _sample_orientation_track(orientation_tracks.get(side), first, last, alpha)
        material_side = orientation['side'].copy() if orientation is not None else lateral
        if override is not None and np.any(valid_override):
            material_side[valid_override] = lateral[valid_override]
            if orientation is not None:
                orientation['side'][valid_override] = lateral[valid_override]
        native_side = native['sides'][side] if native is not None else None
        heel, forefoot = material_foot_points(
            points[:, ankle], points[:, toe], material_side, (float(pitches[side]) if side in pitches else None),
            orientation=orientation, native_geometry=native_side)
        result[side] = {'heel': heel, 'toe': forefoot, 'lateral': material_side,
                        'forward': (orientation['forward'] if orientation else None),
                        'orientation': orientation, 'nativeGeometry': native_side}
    return result


def _unit_rows(values, fallback=None):
    values = np.asarray(values, dtype=float)
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    if fallback is None:
        fallback = np.zeros_like(values)
        fallback[..., 0] = 1.
    fallback = np.asarray(fallback, dtype=float)
    return np.where(lengths > 1e-10, values / np.maximum(lengths, 1e-10), fallback)


def _sample_orientation_track(track, first, last, alpha):
    if track is None:
        return None
    forward = track['forward'][first] * (1. - alpha[:, None]) + track['forward'][last] * alpha[:, None]
    side = track['side'][first] * (1. - alpha[:, None]) + track['side'][last] * alpha[:, None]
    forward = _unit_rows(forward)
    side -= forward * np.sum(side * forward, axis=1, keepdims=True)
    side = _unit_rows(side)
    # Keep an orthonormal right-handed frame after cursor interpolation.
    side = _unit_rows(np.cross(forward, np.cross(side, forward)))
    return {'forward': forward, 'side': side}


def _source_partial_foot_observation_sides(payload, evidence, states, frame_count):
    """Return sides with a current, pose-bound source foot-patch observation."""
    patch = (evidence or {}).get('footPatchEvidence') or {}
    source_sha = str((evidence or {}).get('sourceVideoSha256') or '').casefold()
    if (patch.get('available') is not True
            or patch.get('source') != 'mediapipe_full_heel_forefoot'
            or not source_sha
            or str(patch.get('sourceVideoSha256') or '').casefold() != source_sha
            or patch.get('sourceTimeBasis') != 'absolute_source_video'):
        return set()
    source_pose = (payload.get('sourcePoseCameraReference') or {}).get('sourcePose')
    if not isinstance(source_pose, dict):
        return set()
    from .foot_contact_observation import foot_patch_pose_binding_failure
    if foot_patch_pose_binding_failure(patch, source_pose):
        return set()
    patch_feet = patch.get('feet') or {}
    result = set()
    for side in ('left', 'right'):
        missing = 'right' if side == 'left' else 'left'
        patch_states = (patch_feet.get(side) or {}).get('states') or []
        aligned_states = states.get(side) or ()
        missing_patch_states = (patch_feet.get(missing) or {}).get('states') or []
        missing_aligned_states = states.get(missing) or ()
        if (len(patch_states) != patch.get('sourceFrameCount')
                or len(aligned_states) != frame_count
                or len(missing_patch_states) != patch.get('sourceFrameCount')
                or len(missing_aligned_states) != frame_count):
            continue
        source_states = [str(state).casefold() for state in patch_states]
        fit_states = [str(state).casefold() for state in aligned_states]
        absent_source_states = [str(state).casefold() for state in missing_patch_states]
        absent_fit_states = [str(state).casefold() for state in missing_aligned_states]
        source_partial_count = sum(
            state in {'toe_only', 'heel_only'} for state in source_states)
        aligned_partial_count = sum(
            state in {'toe_only', 'heel_only'} for state in fit_states)
        if (source_partial_count >= 3 and aligned_partial_count >= 3
                and 'full_sole' not in source_states and 'full_sole' not in fit_states
                and all(state in {'', 'unknown'} for state in absent_source_states)
                and all(state in {'', 'unknown'} for state in absent_fit_states)):
            result.add(side)
    return result


def shoe_orientation_tracks(payload, points, *, resolved_sides=None):
    """Build material shoe axes from verified full-sole states and preserve free pitch.

    Only timed full-sole observations with a verified ground plane constrain the
    sole normal. Between those anchors, the original/calibrated foot pitch is
    retained and the material side is minimally transported with the foot axis.
    """
    points = np.asarray(points, dtype=float)
    frames, names = payload.get('frames') or [], payload.get('jointNames') or []
    if points.shape != (len(frames), len(names), 3):
        raise ValueError('shoe orientation points must match payload frame/joint shape')
    context = _SHOE_ORIENTATION_CONTEXT.get()
    if context is None or context['ground'].shape != (len(frames), len(names)):
        context = _build_shoe_orientation_context(payload)
    states, ground = context['states'], context['ground']
    mode = str(payload.get('groundContactMode') or '').casefold()
    plane_groups = context['planeGroups']
    mirrored_partial_sides = set(context.get('mirroredPartialSides') or ())
    from .temporal_quality import rendered_leg_sides
    resolved = rendered_leg_sides(frames) if resolved_sides is None else resolved_sides
    pitches = payload.get('footRestPitchRadians') or {}
    result = {}
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        bone_forward = _unit_rows(points[:, toe] - points[:, ankle])
        key = f'{ankle_name}->{toe_name}'
        fallback_side = np.asarray([
            resolved[i].get(key, frame.get('boneSides', {}).get(key, [0., 0., 1.]))
            for i, frame in enumerate(frames)
        ], dtype=float)
        fallback_side -= bone_forward * np.sum(fallback_side * bone_forward, axis=1, keepdims=True)
        fallback_side = _unit_rows(fallback_side)
        up = _unit_rows(np.cross(fallback_side, bone_forward))
        pitch = float(pitches.get(side, 0.))
        free_forward = _unit_rows(bone_forward * np.cos(pitch) - up * np.sin(pitch))
        side_axis = fallback_side.copy()
        forward = free_forward.copy()
        side_states = states.get(side, ())
        full = np.asarray([str(state).casefold() == 'full_sole' for state in side_states], dtype=bool)
        if full.shape != (len(frames),):
            full = np.zeros(len(frames), dtype=bool)
        normal = None
        side_names = {ankle_name, toe_name}
        for group in plane_groups:
            if (set(group.get('joints') or ()) & side_names
                    and 'normal' in group and 'planeOffsetMeters' in group):
                candidate_normal = np.asarray(group.get('normal'), dtype=float)
                if (candidate_normal.shape == (3,) and np.isfinite(candidate_normal).all()
                        and np.linalg.norm(candidate_normal) > 1e-8):
                    normal = candidate_normal / np.linalg.norm(candidate_normal)
                    break
        # Only an observed continuous/intermittent ground mask owns the
        # horizontal sole plane; the render-floor height is not an orientation
        # input, so its absence must not disable the observed-ground producer.
        if normal is None and mode in {'continuous', 'intermittent'}:
            grounded = (ground[:, toe] if ground.shape == (len(frames), len(names))
                        else np.zeros(len(frames), dtype=bool))
            if not np.any(grounded):
                if side in mirrored_partial_sides:
                    result[side] = {'forward': free_forward.copy(), 'side': fallback_side.copy(),
                                    'contactMask': np.zeros(len(frames), dtype=bool)}
                continue
            normal = np.array([0., 1., 0.])
        elif normal is not None:
            grounded = np.ones(len(frames), dtype=bool)
        else:
            if side in mirrored_partial_sides:
                result[side] = {'forward': free_forward.copy(), 'side': fallback_side.copy(),
                                'contactMask': np.zeros(len(frames), dtype=bool)}
            continue
        contact = full & grounded
        anchors = np.flatnonzero(contact)
        if not anchors.size:
            if side in mirrored_partial_sides:
                result[side] = {'forward': free_forward.copy(), 'side': fallback_side.copy(),
                                'contactMask': np.zeros(len(frames), dtype=bool)}
            continue
        for index in anchors:
            projected = bone_forward[index] - normal * np.dot(bone_forward[index], normal)
            if np.linalg.norm(projected) <= 1e-8:
                continue
            forward[index] = projected / np.linalg.norm(projected)
            side_axis[index] = np.cross(forward[index], normal)
            side_axis[index] /= max(np.linalg.norm(side_axis[index]), 1e-12)
        valid_anchors = np.flatnonzero(contact & np.isfinite(forward).all(axis=1))
        for index in np.flatnonzero(~contact):
            before = valid_anchors[valid_anchors < index]
            after = valid_anchors[valid_anchors > index]
            left = int(before[-1]) if before.size else None
            right = int(after[0]) if after.size else None
            if left is not None and right is not None:
                start = transport_sides(
                    side_axis[left:left + 1], forward[left:left + 1],
                    free_forward[index:index + 1], fallback_side[index:index + 1])[0]
                end = transport_sides(
                    side_axis[right:right + 1], forward[right:right + 1],
                    free_forward[index:index + 1], fallback_side[index:index + 1])[0]
                amount = (index - left) / max(right - left, 1)
                angle = np.arctan2(
                    np.dot(free_forward[index], np.cross(start, end)),
                    np.dot(start, end))
                side_axis[index] = start * np.cos(amount * angle) + np.cross(
                    free_forward[index], start) * np.sin(amount * angle)
            else:
                anchor = left if left is not None else right
                side_axis[index] = transport_sides(
                    side_axis[anchor:anchor + 1], forward[anchor:anchor + 1],
                    free_forward[index:index + 1], fallback_side[index:index + 1])[0]
        # Contact rows are exact plane frames; free rows preserve the measured
        # pitch and event timing, while transporting only the material side.
        forward[~contact] = free_forward[~contact]
        side_axis -= forward * np.sum(side_axis * forward, axis=1, keepdims=True)
        side_axis = _unit_rows(side_axis)
        result[side] = {'forward': forward, 'side': side_axis,
                        'contactMask': contact}
    if ((payload.get('canonicalExecution') or {}).get('legs') == 'mirrored'
            and len(result) == 1):
        # A single observed shoe is shared technique intent only when the
        # absent side has no contrary native state. This models the missing
        # material basis without inventing a contact or copying observed facts.
        source = next(iter(result))
        missing = 'right' if source == 'left' else 'left'
        allowed_states = {'', 'unknown', 'full_sole'}
        if (all(str(state).casefold() in allowed_states
                for state in states.get(missing, ()))
                and 'left_hip' in names and 'right_hip' in names):
            lateral = (points[:, names.index('right_hip')]
                       - points[:, names.index('left_hip')])
            lengths = np.linalg.norm(lateral, axis=1, keepdims=True)
            if np.isfinite(lateral).all() and np.all(lengths > 1e-9):
                lateral = lateral / lengths
                observed = result[source]
                # Forward is polar and reflects directly. The material side is
                # axial, so negate its reflected vector to keep
                # up = cross(side, forward) reflection-correct.
                forward = observed['forward'] - 2 * np.sum(
                    observed['forward'] * lateral, axis=1, keepdims=True) * lateral
                side_axis = -(observed['side'] - 2 * np.sum(
                    observed['side'] * lateral, axis=1, keepdims=True) * lateral)
                forward, side_axis = _unit_rows(forward), _unit_rows(side_axis)
                if np.isfinite(forward).all() and np.isfinite(side_axis).all():
                    result[missing] = {
                        'forward': forward,
                        'side': side_axis,
                        'contactMask': np.zeros(len(frames), dtype=bool),
                        'modelMirroredFrom': source,
                    }
    if ((payload.get('canonicalExecution') or {}).get('legs') == 'mirrored'
            and len(result) == 2 and {'left_hip', 'right_hip'} <= set(names)):
        # Heel-unobserved sides have no measured pitch authority. Where the
        # opposite side has genuine calibrated full-sole anchors, its reflected
        # orientation is the only canonical basis for the unobservable shoe.
        # Replace only uncertain, non-owned rows; keep the target's own anchors,
        # contact mask and any contrary observed state untouched.
        evidence = context.get('evidence') or {}
        patch = evidence.get('footPatchEvidence') or {}
        feet = (patch.get('feet') or {}) if patch.get('available') is True else {}
        pitch_sources = {
            side: str((feet.get(side) or {}).get('pitchReferenceSource') or 'unknown')
            for side in ('left', 'right')
        }
        unobserved = [side for side in result
                      if pitch_sources.get(side, '').casefold() == 'heel_unobserved']
        if len(unobserved) == 1:
            target = unobserved[0]
            source = 'right' if target == 'left' else 'left'
            source_states = [str(state).casefold() for state in states.get(source, ())]
            target_states = [str(state).casefold() for state in states.get(target, ())]
            source_heel_rows = (
                (feet.get(source) or {}).get('heelImageObservations') or [])
            source_calibrated = sum(
                str(row.get('state') or '').casefold() == 'full_sole'
                and row.get('stationaryAnchorGroupId') is not None
                for row in source_heel_rows
            )
            if (source in result
                    and len(source_states) == len(frames)
                    and len(target_states) == len(frames)
                    and source_states.count('full_sole') >= 3
                    and source_calibrated >= 3
                    and pitch_sources.get(source, '').casefold() in {'relative_stance', 'observed_ground_plane'}):
                lateral = (points[:, names.index('right_hip')]
                           - points[:, names.index('left_hip')])
                lengths = np.linalg.norm(lateral, axis=1, keepdims=True)
                if np.isfinite(lateral).all() and np.all(lengths > 1e-9):
                    lateral = lateral / lengths
                    observed = result[source]
                    forward = observed['forward'] - 2 * np.sum(
                        observed['forward'] * lateral, axis=1, keepdims=True) * lateral
                    side_axis = -(observed['side'] - 2 * np.sum(
                        observed['side'] * lateral, axis=1, keepdims=True) * lateral)
                    forward, side_axis = _unit_rows(forward), _unit_rows(side_axis)
                    target_track = result[target]
                    uncertain = np.asarray([
                        state in {'', 'unknown', 'toe_only'} for state in target_states
                    ], dtype=bool)
                    replace = uncertain & ~target_track['contactMask']
                    if np.any(replace) and np.isfinite(forward).all() and np.isfinite(side_axis).all():
                        target_track['forward'] = np.where(
                            replace[:, None], forward, target_track['forward'])
                        target_track['side'] = np.where(
                            replace[:, None], side_axis, target_track['side'])
                        target_track['modelMirroredFrom'] = source
                        target_track['modelAuthority'] = True
    return result


def transport_sides(sides, old_axes, new_axes, fallback):
    """Vectorized minimal bone-frame transport for sampled shoe axes."""
    sides = np.asarray(sides, dtype=float)
    old_axes = np.asarray(old_axes, dtype=float)
    new_axes = np.asarray(new_axes, dtype=float)
    fallback = np.asarray(fallback, dtype=float).copy()
    cosine = np.clip(np.sum(old_axes * new_axes, axis=1), -1., 1.)
    cross = np.cross(old_axes, new_axes)
    cross_side = np.cross(cross, sides)
    denominator = np.maximum(1. + cosine, 1e-12)
    transported = sides + cross_side + np.cross(cross, cross_side) / denominator[:, None]
    transported -= new_axes * np.sum(transported * new_axes, axis=1, keepdims=True)
    length = np.linalg.norm(transported, axis=1, keepdims=True)
    fallback -= new_axes * np.sum(fallback * new_axes, axis=1, keepdims=True)
    fallback_length = np.linalg.norm(fallback, axis=1, keepdims=True)
    use_fallback = (cosine < -0.999999) | (length[:, 0] <= 1e-8) | ~np.isfinite(length[:, 0])
    transported = np.where(use_fallback[:, None], fallback, transported)
    length = np.where(use_fallback[:, None], fallback_length, length)
    return transported / np.maximum(length, 1e-12)


def sample_material_foot_points(payload, cursors, *, points=None):
    """Return production-rendered material heel and toe positions at cursors.

    ``points`` is an optional candidate keyframe track with shape
    ``(frame_count, joint_count, 3)``. Candidate positions are linearly
    interpolated at each cursor; without it, the serialized fixed rig is
    sampled with the same interpolation as playback.
    """
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    wrap = bool((payload.get('loop') or {}).get('enabled'))
    if points is None:
        from .rig_playback import _native_sampling_rig, sample_rig
        points, side_axes = sample_rig(
            _native_sampling_rig(payload), cursors, wrap=wrap,
            return_side_axes=True)
    else:
        side_axes = None
        points = np.asarray(points, dtype=float)
        frame_count = len(payload['frames'])
        if points.shape != (frame_count, len(payload['jointNames']), 3):
            raise ValueError('candidate points must have shape (frame_count, joint_count, 3)')
        if frame_count:
            cursors = np.mod(cursors, frame_count) if wrap else np.clip(cursors, 0., frame_count - 1.)
            first = np.floor(cursors).astype(int)
            last = (first + 1) % frame_count if wrap else np.minimum(first + 1, frame_count - 1)
            amount = cursors - first
            points = points[first] * (1. - amount[:, None, None]) + points[last] * amount[:, None, None]
        rig = payload.get('fixedRig')
        if isinstance(rig, dict) and rig.get('contactFootTracks', {}).get('version') == 2:
            from .rig_playback import _native_sampling_rig, sample_rig
            _, side_axes = sample_rig(
                _native_sampling_rig(payload), cursors, wrap=wrap,
                return_side_axes=True)
    geometry = _sample_material_foot_geometry(
        payload, cursors, points, side_axes_override=side_axes)
    return {side: {'heel': values['heel'], 'toe': values['toe'],
                   'sideAxis': values['lateral'], 'forwardAxis': values['forward']}
            for side, values in geometry.items()}


def validate_material_shoes(payload, points, cursors, *, floor_limit, contact_limit):
    """Check material soles at the same interpolated poses as rig playback."""
    pitches = payload.get('footRestPitchRadians') or {}
    floor = payload.get('renderFloorY')
    if floor is None:
        return {'required': False, 'passed': True}
    from .contact_constraints import motion_space_support_evidence
    frames, names = payload['frames'], payload['jointNames']
    from .rig_playback import _native_sampling_rig, sample_rig
    rig = payload.get('fixedRig')
    side_axes = None
    if isinstance(rig, dict) and rig.get('contactFootTracks', {}).get('version') == 2:
        _, side_axes = sample_rig(
            _native_sampling_rig(payload), cursors,
            wrap=bool((payload.get('loop') or {}).get('enabled')),
            return_side_axes=True)
    geometry = _sample_material_foot_geometry(
        payload, cursors, points, side_axes_override=side_axes)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % len(frames)
    evidence = motion_space_support_evidence(payload)
    ground = observed_ground_contact_mask(evidence, names, len(frames))
    full = np.zeros_like(ground)
    for contact in motion_support_contacts(evidence):
        if contact.get('contactState') == 'full_sole' and contact.get('jointName') in names:
            start, end = contact_frame_bounds(contact, len(frames))
            full[start:end + 1, names.index(contact['jointName'])] = True
    scale = foot_scale_from_pose(np.asarray([frames[0]['joints'][n] for n in names]), names)
    penetration, contact_error = 0., 0.
    evaluated_sides = []
    for side in ('left', 'right'):
        if side not in geometry:
            continue
        evaluated_sides.append(side)
        pitch = (float(pitches[side]) if side in pitches else None)
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        axes = geometry[side]['lateral']
        vertices = shoe_vertices(points[:, ankle], points[:, toe], axes, pitch, scale,
                                 orientation=geometry[side]['orientation'],
                                 native_geometry=geometry[side].get('nativeGeometry'))
        penetration = max(penetration, float(floor) - float(vertices[:, :, 1].min()))
        active = (full[first, toe] & full[last, toe] & ground[first, toe] & ground[last, toe])
        if np.any(active):
            heel, forefoot = geometry[side]['heel'], geometry[side]['toe']
            contact_error = max(contact_error, float(np.max(np.abs(
                np.stack([heel[active, 1], forefoot[active, 1]]) - float(floor)))))
    return {'required': True, 'passed': bool(evaluated_sides) and penetration <= floor_limit and contact_error <= contact_limit,
            'evaluatedSides': evaluated_sides,
            'maximumSurfacePenetrationMeters': max(0., penetration),
            'maximumFullSoleContactErrorMeters': contact_error}
