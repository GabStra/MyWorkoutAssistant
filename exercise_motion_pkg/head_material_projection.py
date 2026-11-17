"""Observed facial points constrain the rendered head region, never a guessed nose joint."""
from __future__ import annotations

import numpy as np
from scipy.spatial import ConvexHull, QhullError
from scipy.sparse import coo_matrix

from .render_geometry import head_material_binding, head_material_vertices

INNER_FACE = ('nose', 'left_eye', 'right_eye')
EARS = ('left_ear', 'right_ear')


def _outside_distances(vertices, observations, projection, offset):
    projected = vertices @ projection.T + offset
    hull = ConvexHull(projected)
    points = np.asarray([row['point'] for row in observations])
    return np.maximum(np.max(points @ hull.equations[:, :2].T
                             + hull.equations[:, 2], axis=1), 0.)


def head_material_reference_span(coordinate_reference, names, camera):
    """Immutable local material scale in the original retained camera frame."""
    frames = (coordinate_reference or {}).get('frames') or []
    points = np.asarray([[frame['joints'][name] for name in names] for frame in frames])
    if not len(points):
        raise ValueError('Retained head material reference is unavailable')
    rotation = np.asarray(camera['cameraRotation'], dtype=float)
    a, b, *_ = camera['cameraImageTransform']
    projection = np.asarray([a*rotation[0]-b*rotation[1],
                             b*rotation[0]+a*rotation[1]])
    vertices = head_material_vertices(points, names)
    spans = np.linalg.norm(np.ptp(vertices @ projection.T, axis=1), axis=1)
    if not np.isfinite(spans).all() or np.any(spans <= 1e-9):
        raise ValueError('Retained projected head material scale is unavailable')
    return float(np.median(spans))


def prepare_head_material_observations(points, names, times, source_frames,
                                       projection, offset, *, time_tolerance, reference_part_span=None):
    """Bind observations to the same verified clock and fixed camera as body rows."""
    groups = []
    eligible = 0
    try:
        binding = head_material_binding(points, names)
    except ValueError as exc:
        return {'available': False, 'required': False, 'reason': str(exc),
                'groups': [], 'jointNames': list(names)}
    times = np.asarray(times)
    for frame in source_frames:
        time = float(frame['time'])
        if time < times[0]-time_tolerance or time > times[-1]+time_tolerance:
            continue
        confidence = frame.get('jointConfidence') or {}
        observed = {}
        for name in (*INNER_FACE, *EARS):
            point = frame['joints'].get(name)
            trust = confidence.get(name)
            # Same known-source point eligibility used for independent source
            # observations; absent/occluded facial points stay unavailable.
            if (point is not None and isinstance(trust, (int, float))
                    and np.isfinite(trust) and trust >= .35):
                observed[name] = {'name': name, 'point': np.asarray(point[:2]),
                                  'confidenceWeight': float(np.sqrt(np.clip(trust, 0., 1.)))}
        inner = [observed[name] for name in INNER_FACE if name in observed]
        ears = [observed[name] for name in EARS if name in observed]
        if not inner:
            continue  # An earless avatar cannot establish face completion from ears alone.
        eligible += len(inner)
        right = int(np.searchsorted(times, time, side='left'))
        if right <= 0:
            left = right = 0
            alpha = 0.
        elif right >= len(times):
            left = right = len(times)-1
            alpha = 0.
        else:
            left = right-1
            span = float(times[right]-times[left])
            alpha = 0. if span <= 1e-12 else float((time-times[left])/span)
        sample = points[left]*(1-alpha)+points[right]*alpha
        try:
            vertices = head_material_vertices(sample[None], names, binding=binding)[0]
            projected = vertices @ projection.T + offset
            part_span = (float(np.linalg.norm(np.ptp(projected, axis=0)))
                         if reference_part_span is None else float(reference_part_span))
            if not np.isfinite(part_span) or part_span <= 1e-9:
                continue
        except (ValueError, QhullError):
            continue
        groups.append({'leftFrame': left, 'rightFrame': right, 'alpha': alpha,
                       'sourceTime': time, 'innerFace': inner, 'ears': ears,
                       'referencePartSpan': part_span})
    return {'available': bool(groups), 'required': eligible > 0,
            'groups': groups, 'jointNames': list(names),
            'reason': None if groups else 'eligible_inner_face_observations_unavailable'}


def _group_rows(sample, group, binding, names, projection, offset, weight):
    vertices = head_material_vertices(sample[None], names, binding=binding)[0]
    distances = _outside_distances(vertices, group['innerFace'], projection, offset)
    confidence = np.asarray([row['confidenceWeight'] for row in group['innerFace']])
    return weight * confidence * distances / group['referencePartSpan']


def head_material_rows(candidate, evidence, projection, offset, *, weight):
    if not evidence.get('available'):
        return np.empty(0)
    names = evidence['jointNames']
    binding = head_material_binding(candidate, names)
    rows = []
    for group in evidence['groups']:
        sample = (candidate[group['leftFrame']]*(1-group['alpha'])
                  + candidate[group['rightFrame']]*group['alpha'])
        rows.extend(_group_rows(sample, group, binding, names, projection, offset, weight))
    return np.asarray(rows)


def head_material_point_jacobian(candidate, evidence, projection, offset, *, weight):
    """Local pose derivatives plus exact first-stored-frame dimension ownership."""
    names = evidence['jointNames']
    groups = evidence.get('groups') or []
    binding = head_material_binding(candidate, names)
    index = names.index
    needed = [index(name) for name in ('pelvis', 'left_hip', 'right_hip', 'neck', 'head',
                                      'left_shoulder', 'right_shoulder', 'spine3') if name in names]
    if 'spine3' not in names and 'spine2' in names:
        needed.append(index('spine2'))
    step = 1e-6
    rows, columns, values = [], [], []
    row_offset = 0
    bind_index = binding['frameIndex']
    bind_points = candidate[bind_index]
    dimension_gradients = {}
    for key, start, end in (('headLength', 'neck', 'head'),
                            ('shoulderWidth', 'left_shoulder', 'right_shoulder')):
        vector = bind_points[index(end)]-bind_points[index(start)]
        unit = vector / np.linalg.norm(vector)
        dimension_gradients[key] = ((index(start), -unit), (index(end), unit))
    for group in groups:
        sample = (candidate[group['leftFrame']]*(1-group['alpha'])
                  + candidate[group['rightFrame']]*group['alpha'])
        base = _group_rows(sample, group, binding, names, projection, offset, weight)
        def append(derivative, frame, joint, component, gain=1.):
            active = np.flatnonzero(derivative)
            rows.extend((active+row_offset).tolist())
            columns.extend([(frame*len(names)+joint)*3+component]*len(active))
            values.extend((derivative[active]*gain).tolist())
        for joint in needed:
            for component in range(3):
                perturbed = sample.copy()
                perturbed[joint, component] += step
                derivative = (_group_rows(perturbed, group, binding, names,
                                          projection, offset, weight)-base)/step
                append(derivative, group['leftFrame'], joint, component, 1-group['alpha'])
                append(derivative, group['rightFrame'], joint, component, group['alpha'])
        for key, gradients in dimension_gradients.items():
            changed = {**binding, key: binding[key]+step}
            derivative = (_group_rows(sample, group, changed, names,
                                      projection, offset, weight)-base)/step
            for joint, gradient in gradients:
                for component in range(3):
                    append(derivative, bind_index, joint, component, gradient[component])
        row_offset += len(base)
    return coo_matrix((values, (rows, columns)),
                      shape=(row_offset, candidate.size)).tocsr()


def head_material_evidence(candidate, evidence, projection, offset, *, maximum_rms_part_ratio,
                           sample_points=None):
    """Fresh local-part evidence; ears remain diagnostic for earless avatars."""
    if not evidence.get('available'):
        return {'available': False, 'required': evidence.get('required', False),
                'passed': None, 'reason': evidence.get('reason')}
    names = evidence['jointNames']
    binding = head_material_binding(candidate, names)
    frame_rms, distances, ears = [], [], []
    for i, group in enumerate(evidence['groups']):
        sample = (candidate[group['leftFrame']]*(1-group['alpha'])
                  + candidate[group['rightFrame']]*group['alpha']) if sample_points is None else sample_points[i]
        vertices = head_material_vertices(sample[None], names, binding=binding)[0]
        outside = _outside_distances(vertices, group['innerFace'], projection, offset)
        ratios = outside/group['referencePartSpan']
        confidence = np.asarray([row['confidenceWeight'] for row in group['innerFace']])
        frame_rms.append(float(np.sqrt(np.mean((ratios*confidence)**2))))
        distances.extend(ratios.tolist())
        if group['ears']:
            ears.extend((_outside_distances(vertices, group['ears'], projection, offset)
                         /group['referencePartSpan']).tolist())
    maximum = max(frame_rms)
    return {'available': True, 'required': True,
            'passed': maximum <= maximum_rms_part_ratio,
            'observationCount': len(distances), 'sourceSampleCount': len(frame_rms),
            'maximumFrameRmsPartRatio': maximum,
            'maximumOutsidePartRatio': max(distances),
            'maximumRmsPartRatio': maximum_rms_part_ratio,
            'earMaximumOutsidePartRatioDiagnostic': max(ears, default=None),
            'reference': 'native_head_material_region_with_immutable_local_normalization',
            'calibrationScope': 'new local-part application of existing source-projection RMS policy',
            'chinClearanceMeasured': False}
