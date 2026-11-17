"""Native shoe-region contact with finite, source-calibrated supporting surfaces."""
from __future__ import annotations

import numpy as np


# Top edges of the heel and midfoot rings in shoe_vertices / wearShoe.
SHOE_DORSUM_VERTICES = (1, 2, 9, 10, 17, 18)
SHOE_DORSUM_TRIANGLES = ((1, 9, 10), (1, 10, 2), (9, 17, 18), (9, 18, 10))


def observed_region_sides(payload):
    """A calibrated pose never supplies its own contact authority."""
    from .body_support_observation import validated_body_support_answer
    source = payload.get('sourceFootSupportEvidence') or {}
    observation = source.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observation) or {}
    retained = payload.get('sourcePoseCameraReference') or {}
    mapping = retained.get('sourceTimelineMapping') or {}
    digest = str(observation.get('sourceVideoSha256') or '').casefold()
    pose_digest = str((retained.get('sourcePose') or {}).get('sourceVideoSha256') or '').casefold()
    assignment = (retained.get('camera') or {}).get('bilateralAssignment')
    if (not digest or digest != pose_digest
            or digest != str(mapping.get('selectedSegmentSha256') or '').casefold()
            or not mapping.get('selectedFrameClockReceiptSha256')
            or not mapping.get('sourcePosePayloadSha256')
            or assignment not in {'identity', 'swapped'}):
        return []
    return [('right' if side == 'left' else 'left') if assignment == 'swapped' else side
            for side in ('left', 'right') if answer.get(side + 'Foot') == 'supported_dorsum'
            and answer.get(side + 'FootSurface') == 'raised_surface'
            and answer.get(side + 'FootSurfaceMotion') == 'stationary'
            and answer.get(side + 'FootSurfaceOrientation') == 'horizontal'
            and answer.get(side + 'FootContactContinuity') == 'continuous']


def calibrated_region_contacts(payload):
    sides = observed_region_sides(payload)
    evidence = payload.get('sourceFootSupportEvidence') or {}
    support = evidence.get('bodySupport') or {}
    digest = str((evidence.get('bodySupportObservation') or {}).get('sourceVideoSha256') or '').casefold()
    camera = (payload.get('sourcePoseCameraReference') or {}).get('camera') or {}
    contacts = [contact for contact in support.get('materialRegionContacts', [])
            if contact.get('side') in sides and contact.get('region') == 'foot_dorsum'
            and str(contact.get('sourceVideoSha256') or '').casefold() == digest
            and contact.get('calibrationSourceTimelineMappingIdentity') ==
            {key: (payload['sourcePoseCameraReference']['sourceTimelineMapping']).get(key)
             for key in ('selectedSegmentSha256', 'selectedFrameClockReceiptSha256',
                         'sourcePosePayloadSha256')}
            and contact.get('calibrationCamera') == {key: camera.get(key) for key in (
                'cameraRotation', 'cameraImageTransform', 'bilateralAssignment')}
            and contact.get('sourceImageRegion') is not None
            and contact.get('sourceImageRegion') == source_surface_image_region(payload, contact['side'])]
    valid = []
    for contact in contacts:
        try:
            bounds = np.asarray(contact.get('boundsXZ'), dtype=float)
            height = float(contact.get('planeOffsetMeters'))
        except (TypeError, ValueError, OverflowError):
            continue
        if (bounds.shape == (4,) and np.isfinite(bounds).all() and np.isfinite(height)
                and bounds[1] > bounds[0] and bounds[3] > bounds[2]):
            valid.append(contact)
    return valid


def dorsal_material_payload(payload, points, resolved, names):
    """Rebase candidate FK context without changing material-roll authority."""
    sides = observed_region_sides(payload)
    if not sides:
        return payload
    frames = []
    for index, (source, row) in enumerate(zip(payload['frames'], points)):
        frame = {**source, 'joints': dict(source['joints']),
                 'boneSides': dict(source.get('boneSides') or {})}
        for side in sides:
            for part in ('ankle', 'foot'):
                frame['joints'][side+'_'+part] = row[names.index(side+'_'+part)].tolist()
            key = side+'_ankle->'+side+'_foot'
            frame['boneSides'][key] = resolved[index][key]
        frames.append(frame)
    return {**payload, 'frames': frames}


def source_surface_image_region(payload, side):
    from .body_support_observation import validated_body_support_answer
    source = payload.get('sourceFootSupportEvidence') or {}
    answer = validated_body_support_answer(source.get('bodySupportObservation')) or {}
    if ((payload.get('sourcePoseCameraReference') or {}).get('camera') or {}).get('bilateralAssignment') == 'swapped':
        side = 'right' if side == 'left' else 'left'
    return answer.get(side+'FootSurfaceImageRegion')


def source_surface_projection_errors(contact, region, source_constraint, image_aspect, *, image_height=None):
    """Keep the estimated finite top inside the directly reviewed source area."""
    x0, x1, z0, z1 = contact['boundsXZ']
    points = np.asarray([[x, contact['planeOffsetMeters'], z]
                         for x, z in ((x0, z0), (x1, z0), (x1, z1), (x0, z1))])
    projected = points @ source_constraint['projection'].T + source_constraint['offset']
    polygon = np.asarray(region['polygonNormalizedXY']) * [image_aspect, 1.]
    start, end = polygon, np.roll(polygon, -1, axis=0)
    edges = end-start
    rows = []
    for point in projected:
        relative = point-start
        cross = edges[:, 0]*relative[:, 1]-edges[:, 1]*relative[:, 0]
        if np.all(cross >= 0.) or np.all(cross <= 0.):
            rows.append([0., 0.])
            continue
        alpha = np.clip(np.sum(relative*edges, axis=1)/np.maximum(np.sum(edges*edges, axis=1), 1e-15), 0., 1.)
        nearest = start+alpha[:, None]*edges
        hit = np.argmin(np.linalg.norm(nearest-point, axis=1))
        delta = point-nearest[hit]
        distance = float(np.linalg.norm(delta))
        uncertainty = float(region.get('uncertaintyPixels') or 0.)/image_height if image_height else 0.
        rows.append(delta*max(0., 1.-uncertainty/max(distance, 1e-15)))
    return np.asarray(rows)


def shoe_triangles():
    """The same strip/fan triangulation as wearStrip and wearFan."""
    faces = []
    for lower in (0, 8):
        for corner in range(8):
            following = (corner + 1) % 8
            a, b, c, d = lower + corner, lower + 8 + corner, lower + 8 + following, lower + following
            faces.extend(((a, b, c), (a, c, d)))
    for corner in range(8):
        following = (corner + 1) % 8
        faces.append((24, corner, following))
        faces.append((25, 16 + following, 16 + corner))
    return np.asarray(faces, dtype=int)


SHOE_REGION_FIT_ROW_COUNT = 1 + len(shoe_triangles())


def _clip_triangle_to_patch(triangle, bounds):
    polygon = list(np.asarray(triangle, dtype=float))
    for axis, boundary, sign in ((0, bounds[0], 1), (0, bounds[1], -1),
                                  (2, bounds[2], 1), (2, bounds[3], -1)):
        clipped = []
        if not polygon:
            break
        previous = polygon[-1]
        previous_distance = sign * (previous[axis] - boundary)
        for current in polygon:
            distance = sign * (current[axis] - boundary)
            if (distance >= 0.) != (previous_distance >= 0.):
                alpha = previous_distance / (previous_distance - distance)
                clipped.append(previous + alpha * (current - previous))
            if distance >= 0.:
                clipped.append(current)
            previous, previous_distance = current, distance
        polygon = clipped
    return np.asarray(polygon)


def _point_triangle_distances(points, triangles):
    from .physical_validation import segment_distance
    points, triangles = np.asarray(points), np.asarray(triangles)
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    u, v = b-a, c-a
    normal = np.cross(u, v)
    squared = np.sum(normal*normal, axis=1)
    relative = points[:, None, :]-a[None, :, :]
    signed = np.sum(relative*normal[None, :, :], axis=2)
    projected = relative-normal[None, :, :]*(signed/np.maximum(squared, 1e-15))[:, :, None]
    uu, uv, vv = np.sum(u*u, axis=1), np.sum(u*v, axis=1), np.sum(v*v, axis=1)
    pu, pv = np.sum(projected*u[None, :, :], axis=2), np.sum(projected*v[None, :, :], axis=2)
    determinant = uu*vv-uv*uv
    first = (vv*pu-uv*pv)/np.maximum(determinant, 1e-15)
    second = (uu*pv-uv*pu)/np.maximum(determinant, 1e-15)
    inside = (determinant > 1e-15) & (first >= 0.) & (second >= 0.) & (first+second <= 1.)
    edge = np.minimum.reduce([segment_distance(points[:, None], points[:, None], x[None], y[None])
                              for x, y in ((a, b), (b, c), (c, a))])
    return np.where(inside, np.abs(signed)/np.sqrt(np.maximum(squared, 1e-15)), edge)


def _region_top_distance(frame, bounds, height, clipped_region):
    """Continuous finite-surface distance, including projected edge crossings."""
    from .physical_validation import segment_distance
    for polygon in clipped_region:
        if float(polygon[:, 1].min()) <= height <= float(polygon[:, 1].max()):
            return 0.
    region = frame[list(SHOE_DORSUM_VERTICES)]
    triangles = frame[np.asarray(SHOE_DORSUM_TRIANGLES)]
    x0, x1, z0, z1 = bounds
    top = np.asarray([[x0, height, z0], [x1, height, z0],
                      [x1, height, z1], [x0, height, z1]])
    top_triangles = top[np.asarray([[0, 1, 2], [0, 2, 3]])]
    distances = [_point_triangle_distances(region, top_triangles).min(),
                 _point_triangle_distances(top, triangles).min()]
    starts, ends = triangles[:, [0, 1, 2]].reshape(-1, 3), triangles[:, [1, 2, 0]].reshape(-1, 3)
    distances.append(segment_distance(starts[:, None], ends[:, None],
                                       top[None], np.roll(top, -1, axis=0)[None]).min())
    return float(min(distances))


def triangle_slab_signed_separation(triangles, contact):
    """Triangle/AABB SAT: negative minimum escape translation, zero on touch."""
    triangles = np.asarray(triangles, dtype=float)
    x0, x1, z0, z1 = contact['boundsXZ']
    height, thickness = float(contact['planeOffsetMeters']), float(contact['thicknessMeters'])
    center = np.asarray([(x0+x1)/2., height-thickness/2., (z0+z1)/2.])
    half = np.asarray([(x1-x0)/2., thickness/2., (z1-z0)/2.])
    edges = np.roll(triangles, -1, axis=1)-triangles
    normals = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    cross = np.cross(edges[:, :, None], np.eye(3)[None, None]).reshape(len(triangles), 9, 3)
    axes = np.concatenate([np.broadcast_to(np.eye(3), (len(triangles), 3, 3)),
                           normals[:, None], cross], axis=1)
    lengths = np.linalg.norm(axes, axis=-1)
    axes = axes/np.maximum(lengths[:, :, None], 1e-15)
    projection = np.einsum('tvi,tai->tav', triangles-center, axes)
    radius = np.einsum('tai,i->ta', np.abs(axes), half)
    gap = np.maximum(projection.min(axis=-1)-radius, -radius-projection.max(axis=-1))
    gap[lengths <= 1e-12] = -np.inf
    return gap.max(axis=1)


def finite_slab_triangle_overlap(triangle, contact):
    """Final native overlap metric; independent of the optimizer's escape rows."""
    polygon = _clip_triangle_to_patch(triangle, contact['boundsXZ'])
    if not len(polygon):
        return 0.
    height, thickness = float(contact['planeOffsetMeters']), float(contact['thicknessMeters'])
    low, high = float(polygon[:, 1].min()), float(polygon[:, 1].max())
    return min(thickness, max(0., min(height-low, high-(height-thickness))))


def finite_patch_shoe_fit_rows(vertices, contact):
    """Keep every intersecting native face's escape gradient, without a hull."""
    vertices = np.asarray(vertices)
    bounds, height = np.asarray(contact['boundsXZ']), float(contact['planeOffsetMeters'])
    rows = []
    for frame in vertices.reshape(-1, 26, 3):
        clipped = [_clip_triangle_to_patch(frame[list(face)], bounds) for face in SHOE_DORSUM_TRIANGLES]
        gap = _region_top_distance(frame, bounds, height, [polygon for polygon in clipped if len(polygon)])
        separation = triangle_slab_signed_separation(frame[shoe_triangles()], contact)
        rows.append(np.r_[gap, np.minimum(separation, 0.)])
    return np.asarray(rows).reshape(*vertices.shape[:-2], SHOE_REGION_FIT_ROW_COUNT)


def finite_patch_shoe_errors(vertices, contact):
    """Rolling dorsum touch and mesh penetration INSIDE the finite patch only.

    No material vertex is pinned in XZ. Triangle clipping catches intersections
    even when all three original vertices lie outside the supporting patch.
    """
    vertices = np.asarray(vertices, dtype=float)
    if contact.get('region') != 'foot_dorsum' or vertices.shape[-2:] != (26, 3):
        raise ValueError('Unsupported or invalid native shoe material region')
    bounds = np.asarray(contact['boundsXZ'], dtype=float)
    height = float(contact['planeOffsetMeters'])
    thickness = float(contact.get('thicknessMeters', min(bounds[1]-bounds[0], bounds[3]-bounds[2])*.1))
    if (bounds.shape != (4,) or not np.isfinite(bounds).all() or not np.isfinite(height)
            or bounds[1] <= bounds[0] or bounds[3] <= bounds[2]
            or not np.isfinite(thickness) or thickness <= 0.):
        raise ValueError('A finite calibrated support patch is required')
    rows = []
    for frame in vertices.reshape(-1, 26, 3):
        clipped_region = [_clip_triangle_to_patch(frame[list(face)], bounds)
                          for face in SHOE_DORSUM_TRIANGLES]
        clipped_region = [polygon for polygon in clipped_region if len(polygon)]
        gap = _region_top_distance(frame, bounds, height, clipped_region)
        penetration = 0.
        for triangle in frame[shoe_triangles()]:
            penetration = max(penetration, finite_slab_triangle_overlap(triangle, contact))
        rows.append((gap, -penetration))
    return np.asarray(rows).reshape(*vertices.shape[:-2], 2)


def estimated_patch_from_contact_vertices(vertices, height, *, foot_scale):
    """Estimate a finite scene footprint; this does not claim measured equipment size."""
    region = np.asarray(vertices)[:, list(SHOE_DORSUM_VERTICES)]
    contact = region[np.arange(len(region)), np.argmin(region[:, :, 1], axis=1)]
    low, high = contact[:, [0, 2]].min(axis=0), contact[:, [0, 2]].max(axis=0)
    margin = float(foot_scale) * .15  # Existing native shoe minimum half-width.
    size = float(np.max(high - low) + 2. * margin)
    center = (low + high) * .5
    return {'region': 'foot_dorsum', 'planeOffsetMeters': float(height),
            'boundsXZ': [center[0] - size / 2., center[0] + size / 2.,
                         center[1] - size / 2., center[1] + size / 2.],
            'thicknessMeters': size*.1,
            'geometryAuthority': 'source_camera_fixed_bones_and_observed_contact_calibration',
            'geometryUncertainty': 'monocular_estimate_not_measured_equipment_dimensions',
            'contactMotion': 'rolling_or_unknown', 'estimatedFootprint': True}


def support_surface_for_region(contact):
    """The existing finite preview slab uses exactly the constraint footprint."""
    x0, x1, z0, z1 = map(float, contact['boundsXZ'])
    height = float(contact['planeOffsetMeters'])
    return {'center': [(x0 + x1) / 2., height, (z0 + z1) / 2.],
            'orientationPoint': [(x0 + x1) / 2. + 1., height, (z0 + z1) / 2.],
            'topY': height, 'size': x1 - x0, 'depth': z1 - z0,
            'thickness': float(contact.get('thicknessMeters', min(x1 - x0, z1 - z0) * .1)),
            'source': 'calibrated_material_region',
            'geometryUncertainty': contact.get('geometryUncertainty')}


def native_region_geometry(payload, points=None, cursors=None):
    """Evaluate stored or dense playback with the renderer's complete keyframe context."""
    from .foot_geometry import _sample_material_foot_geometry, foot_scale_from_pose, shoe_vertices
    from .shoe_floor import native_shoe_material_context
    contacts = calibrated_region_contacts(payload)
    required = observed_region_sides(payload)
    if not required:
        return {'required': False, 'passed': True, 'maximumSurfaceErrorMeters': 0.,
                'rejectionReasons': []}
    if set(required) != {row['side'] for row in contacts}:
        return {'required': True, 'passed': False,
                'rejectionReasons': ['material_region_calibration_unresolved']}
    names = payload['jointNames']
    keyframes = np.asarray([[frame['joints'][name] for name in names]
                            for frame in payload['frames']], dtype=float)
    positions = np.arange(len(keyframes)) if cursors is None else np.asarray(cursors)
    points = keyframes if points is None else np.asarray(points)
    if payload.get('_materialRegionKeyframePoints') is not None:
        keyframes = np.asarray(payload['_materialRegionKeyframePoints'])
    elif len(points) == len(keyframes) and np.array_equal(positions, np.arange(len(keyframes))):
        keyframes = points
    resolved, scale = native_shoe_material_context(payload, keyframes, names)
    # Validation always uses actual serialized keyframes, never a per-frame
    # frozen side axis or a material frame built from dense samples as keyframes.
    material_payload = dorsal_material_payload(payload, keyframes, resolved, names)
    geometry = _sample_material_foot_geometry(
        material_payload, positions, points, resolved_sides=resolved,
        keyframe_points=keyframes)
    errors = []
    for contact in contacts:
        side = contact['side']
        ankle, toe = [names.index(side + '_' + name) for name in ('ankle', 'foot')]
        vertices = shoe_vertices(points[:, ankle], points[:, toe], geometry[side]['lateral'],
                                 (payload.get('footRestPitchRadians') or {}).get(side), scale,
                                 orientation=geometry[side]['orientation'],
                                 native_geometry=geometry[side].get('nativeGeometry'))
        errors.append(finite_patch_shoe_errors(vertices, contact))
    rows = np.concatenate(errors)
    maximum = float(np.max(np.abs(rows[:, 0]), initial=0.))
    penetration = float(np.max(-rows[:, 1], initial=0.))
    from .support_geometry import TOLERANCE_METERS
    from .rig_playback import PLAYBACK_FLOOR_LIMIT_METERS
    passed = maximum <= TOLERANCE_METERS and penetration <= PLAYBACK_FLOOR_LIMIT_METERS
    reasons = [] if passed else ['material_region_surface_geometry_mismatch']
    projected_error = None
    if any(contact.get('sourceImageRegion') for contact in contacts):
        from .controlled_motion import _prepare_source_projection_fit_constraints
        constraint = _prepare_source_projection_fit_constraints(
            payload, payload['frames'], names, keyframes, np.zeros(keyframes.shape[:2], dtype=bool), 1.)
        if not constraint.get('available'):
            reasons.append('material_region_source_surface_camera_unavailable')
        else:
            source = payload['sourcePoseCameraReference']['sourcePose']
            projected_error = max(float(np.max(np.abs(source_surface_projection_errors(
                contact, contact['sourceImageRegion'], constraint,
                float(source['imageWidth'])/float(source['imageHeight']),
                image_height=source['imageHeight'])))) for contact in contacts)
            if projected_error > 1e-9:
                reasons.append('material_region_source_surface_image_mismatch')
    return {'required': True,
            'maximumSurfaceErrorMeters': maximum, 'toleranceMeters': TOLERANCE_METERS,
            'maximumMaterialPenetrationMeters': penetration,
            'penetrationToleranceMeters': PLAYBACK_FLOOR_LIMIT_METERS,
            'maximumSourceSurfaceRegionProjectionError': projected_error,
            'passed': not reasons, 'rejectionReasons': reasons}


def calibration_source_slice(source_constraint):
    """Retain genuine exposure rows while rebinding their FK sample indices."""
    fields = ('observations', 'sourceFootPointObservations', 'sourceFootRayObservations',
              'sourceFootHeelImageObservations', 'sourceFootHeelTrajectoryObservations',
              'sourceFootHeelCalibrationObservations')
    body_times = sorted({row['sourceTime'] for row in source_constraint['observations']})
    selected = [body_times[index] for index in np.linspace(0, len(body_times)-1, 5).astype(int)]
    foot_rows = [row for field in fields[1:] for row in source_constraint.get(field, [])]
    # Keep at least one genuine foot exposure if uniform body sampling misses
    # every available material observation. No interpolated image fact is made.
    if foot_rows and not any(abs(row['sourceTime']-time) <= 1e-9
                             for row in foot_rows for time in selected):
        foot_times = sorted({row['sourceTime'] for row in foot_rows})
        selected.append(foot_times[len(foot_times)//2])
    selected = sorted(set(selected))
    rows = [row for field in fields for row in source_constraint.get(field, [])]
    joins = []
    for time in selected:
        source = next(row for row in rows if abs(row['sourceTime']-time) <= 1e-9)
        joins.append((source['leftFrame'], source['rightFrame'], source['alpha']))
    sliced = dict(source_constraint)
    for field in fields:
        sliced[field] = [
            {**row, 'leftFrame': phase, 'rightFrame': phase, 'alpha': 0.}
            for phase, time in enumerate(selected)
            for row in source_constraint.get(field, [])
            if abs(row['sourceTime']-time) <= 1e-9]
    return selected, joins, sliced


def calibrate_material_regions(rig, payload, coordinates, pinned, targets,
                               source_constraint, *, deadline, max_evaluations, fps):
    """Estimate support geometry from observed contact, camera and fixed-bone FK.

    The plane and footprint are inferred, not contact evidence. Five actual
    exposure phases calibrate the scene; the normal full initializer and final
    gates retain authority over the complete trajectory.
    """
    from time import monotonic
    from scipy.optimize import least_squares
    from copy import deepcopy, copy
    from . import controlled_motion as c
    from .shoe_floor import ShoeFloorConstraint
    sides = observed_region_sides(payload)
    if not sides:
        return coordinates, {'required': False, 'passed': True}
    if not source_constraint.get('available'):
        return None, {'required': True, 'passed': False, 'reason': 'source_camera_unavailable'}
    image_regions = [source_surface_image_region(payload, side) for side in sides]
    if not all(image_regions):
        return None, {'required': True, 'passed': False, 'reason': 'source_surface_image_region_unresolved'}
    full_coordinates = np.asarray(coordinates).copy()
    full_payload = payload
    selected_times, joins, sampled_source_constraint = calibration_source_slice(source_constraint)
    original = np.stack([full_coordinates[left]*(1-alpha)+full_coordinates[right]*alpha
                         for left, right, alpha in joins])
    pinned = np.stack([pinned[left] & pinned[right] for left, right, _ in joins])
    targets = np.stack([targets[left]*(1-alpha)+targets[right]*alpha for left, right, alpha in joins])
    rig = copy(rig)
    rig.initial = original.copy()
    payload = deepcopy(payload)
    payload['frames'] = [deepcopy(full_payload['frames'][right]) for _, right, _ in joins]
    source_constraint = sampled_source_constraint
    for frame, time in zip(payload['frames'], selected_times):
        frame['sourceTimeSec'] = source_constraint['sourceTimeOriginSec'] + time
    reference = rig.decode(original)
    from .physical_validation import source_hinge_direction_authority
    direction_authority = source_hinge_direction_authority(payload, rig.names)
    for frame, row in zip(payload['frames'], reference):
        frame['joints'] = dict(zip(rig.names, row.tolist()))
    evidence = payload.setdefault('sourceFootSupportEvidence', {})
    support = evidence.setdefault('bodySupport', {})
    retained = payload['sourcePoseCameraReference']
    mapping = retained['sourceTimelineMapping']
    identity = {key: mapping.get(key) for key in (
        'selectedSegmentSha256', 'selectedFrameClockReceiptSha256', 'sourcePosePayloadSha256')}
    digest = retained['sourcePose']['sourceVideoSha256']
    image_aspect = float(retained['sourcePose']['imageWidth'])/float(retained['sourcePose']['imageHeight'])
    contacts = []
    # Establish only the numerical layout here; no source or geometry acceptance.
    for side in sides:
        contacts.append({'side': side, 'region': 'foot_dorsum', 'boundsXZ': [-1., 1., -1., 1.],
                         'planeOffsetMeters': 0., 'sourceVideoSha256': digest,
                         'calibrationCamera': {key: retained['camera'].get(key) for key in (
                             'cameraRotation', 'cameraImageTransform', 'bilateralAssignment')},
                         'calibrationSourceTimelineMappingIdentity': identity})
        contacts[-1]['sourceImageRegion'] = image_regions[len(contacts)-1]
    previous = support.get('materialRegionContacts')
    support['materialRegionContacts'] = contacts
    shoes = ShoeFloorConstraint(rig, payload, context=reference)
    shoes.heights(original.ravel())
    vertices = shoes.material_vertices(shoes.points, shoes.resolved, shoes.scale)
    heights = [float(np.median(vertices[side][:, SHOE_DORSUM_VERTICES, 1].min(axis=1)))
               for side in sides]
    surface_parameters = []
    dimensions = []
    from .support_geometry import TOLERANCE_METERS
    from .rig_playback import PLAYBACK_FLOOR_LIMIT_METERS
    for index, side in enumerate(sides):
        estimate = estimated_patch_from_contact_vertices(vertices[side], heights[index], foot_scale=shoes.scale)
        contacts[index].update(estimate)
        x0, x1, z0, z1 = estimate['boundsXZ']
        half = np.asarray([(x1-x0)/2., (z1-z0)/2.])
        center = np.asarray([(x0+x1)/2., (z0+z1)/2.])
        dimensions.append(half)
        # Edge contact is legitimate. A symmetric footprint center is not a
        # source fact; seed the same finite patch at its contact-footprint edges.
        candidates = []
        for dx in (-1., 0., 1.):
            for dz in (-1., 0., 1.):
                candidate = center + half * [dx, dz]
                contact = {**estimate, 'boundsXZ': [candidate[0]-half[0], candidate[0]+half[0],
                                                    candidate[1]-half[1], candidate[1]+half[1]]}
                rows = finite_patch_shoe_errors(vertices[side], contact)
                score = np.sum((rows[:, 0]/TOLERANCE_METERS)**2
                               + (rows[:, 1]/PLAYBACK_FLOOR_LIMIT_METERS)**2)
                candidates.append((float(score), candidate))
        center = min(candidates, key=lambda item: item[0])[1]
        surface_parameters.extend([heights[index], *center])
    count, width = original.shape
    columns = list(range(3))
    for name in ('pelvis', 'left_knee', 'left_ankle', 'left_foot',
                 'right_knee', 'right_ankle', 'right_foot'):
        slot = rig.slots[rig.names.index(name)]
        columns.extend(range(slot, slot+3))
    columns = np.asarray(columns)
    coordinate_count = count * len(columns)

    def unpack(values):
        q = original.copy()
        q[:, columns] = values[:coordinate_count].reshape(count, len(columns))
        return q
    features = [side + suffix for side in ('left', 'right') for suffix in (
        '_knee', '_ankle', '_knee_excursion', '_ankle_excursion',
        '_knee_bend_direction', '_foot_heading', '_heel_pitch')]
    keys = [(feature, frame) for feature in features for frame in (-1, *range(count))]
    best = {'cost': float('inf')}

    def residual(values):
        if monotonic() >= deadline:
            raise TimeoutError('Material support calibration deadline')
        q = unpack(values)
        points = rig.decode(q)
        shoes.heights(q.ravel())
        material = shoes.material_vertices(shoes.points, shoes.resolved, shoes.scale)
        region_rows, image_rows = [], []
        for index, side in enumerate(sides):
            height, center_x, center_z = values[coordinate_count+3*index:coordinate_count+3*index+3]
            half = dimensions[index]
            contacts[index].update(planeOffsetMeters=float(height), boundsXZ=[
                center_x-half[0], center_x+half[0], center_z-half[1], center_z+half[1]])
            region_rows.append(finite_patch_shoe_fit_rows(material[side], contacts[index]).ravel())
            # This is a physical support-area obligation, not a noisy skeletal
            # point. Convert image distance to minimum world displacement and
            # use the same existing material-support weight as the mesh rows.
            image_rows.append(2000./max(float(np.linalg.norm(source_constraint['projection'], ord=2)), 1e-15) *
                              source_surface_projection_errors(contacts[index], image_regions[index],
                                                               source_constraint, image_aspect,
                                                               image_height=retained['sourcePose']['imageHeight']).ravel())
        guards = dict.fromkeys(keys, 0.)
        for event in c.support_initialization_articulation_regressions(
                reference, points, rig.names, fps=fps,
                direction_authority=direction_authority):
            delta = (event['minimumPreservedRatio'] - event['preservedRatio']
                     if 'preservedRatio' in event else np.deg2rad(
                         event.get('p95ChangeDegrees', event.get('changeDegrees', 0.))
                         - event.get('toleranceDegrees', 0.)))
            guards[(event['feature'], event.get('frameIndex', -1))] = max(0., delta)
        rows = np.r_[c._source_projection_fit_rows(points, source_constraint),
                     c.CONTACT_FIT_WEIGHT * (points - targets)[pinned].ravel(),
                     c.SUPPORT_ARTICULATION_FIT_WEIGHT * np.asarray([guards[key] for key in keys]),
                     c.ANATOMY_FIT_WEIGHT * c.fit_anatomy_structure_residuals(
                         points, rig.names, reference).ravel(),
                     2000. * np.concatenate(region_rows),
                     np.concatenate(image_rows),
                     .0001 * (q - original).ravel()]
        cost = float(rows @ rows)
        if cost < best['cost']:
            best.update(cost=cost, values=values.copy())
        return rows

    try:
        fit = least_squares(residual, np.r_[original[:, columns].ravel(), surface_parameters],
                            max_nfev=max_evaluations, ftol=1e-8, xtol=1e-8, gtol=1e-8)
        values = fit.x
        status = {'status': int(fit.status), 'evaluations': int(fit.nfev), 'message': fit.message}
    except TimeoutError:
        values = best.get('values')
        status = {'status': 'deadline'}
    if values is None:
        if previous is None:
            support.pop('materialRegionContacts', None)
        else:
            support['materialRegionContacts'] = previous
        return None, {'required': True, 'passed': False, **status}
    # Rebind geometry to the retained best values, not the last FD perturbation.
    saved_deadline = deadline
    deadline = float('inf')
    residual(values)
    deadline = saved_deadline
    q = unpack(values)
    points = rig.decode(q)
    guards = c.support_initialization_articulation_regressions(
        reference, points, rig.names, fps=fps, direction_authority=direction_authority)
    material_rows = np.concatenate([finite_patch_shoe_errors(
        shoes.material_vertices(shoes.points, shoes.resolved, shoes.scale)[side], contact)
        for side, contact in zip(sides, contacts)])
    error = float(np.max(np.abs(material_rows[:, 0]), initial=0.))
    penetration = float(np.max(-material_rows[:, 1], initial=0.))
    projected_error = max(float(np.max(np.abs(source_surface_projection_errors(
        contact, region, source_constraint, image_aspect,
        image_height=retained['sourcePose']['imageHeight']))))
                          for contact, region in zip(contacts, image_regions))
    from .support_geometry import TOLERANCE_METERS
    from .rig_playback import PLAYBACK_FLOOR_LIMIT_METERS
    passed = (error <= TOLERANCE_METERS and penetration <= PLAYBACK_FLOOR_LIMIT_METERS
              and projected_error <= 1e-9 and not guards
              and np.max(c.fit_anatomy_structure_residuals(points, rig.names, reference), initial=0.) < 1e-6)
    report = {'required': True, 'passed': bool(passed), **status,
              'maximumSurfaceErrorMeters': error, 'articulationRegressions': guards,
              'maximumMaterialPenetrationMeters': penetration,
              'maximumSourceSurfaceRegionProjectionError': projected_error,
              'sourcePhaseJoins': joins, 'sourcePhaseTimesSec': selected_times,
              'diagnosticCandidateCoordinates': q.tolist(),
              'diagnosticSurfaceEstimates': contacts,
              'geometryAuthority': 'source_camera_fixed_bones_and_observed_contact_calibration'}
    for frame, row in zip(payload['frames'], points):
        frame['joints'] = dict(zip(rig.names, row.tolist()))
    from .bake_and_rank import materialized_source_pose_fidelity_metrics
    report['sourcePoseFidelity'] = materialized_source_pose_fidelity_metrics(
        source_pose_payload=retained['sourcePose'], output_motion_payload=payload, required=True)
    passed = passed and report['sourcePoseFidelity']['passed']
    report['passed'] = bool(passed)
    if not passed:
        support.pop('materialRegionContacts', None)
        return None, report
    full_payload.setdefault('sourceFootSupportEvidence', {}).setdefault('bodySupport', {})[
        'materialRegionContacts'] = contacts
    full_payload['elevatedSupportSurfaces'] = [support_surface_for_region(contact) for contact in contacts]
    # Five-phase geometry calibration is not a replacement trajectory.
    return full_coordinates, report
