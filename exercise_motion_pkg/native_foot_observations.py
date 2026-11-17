"""Physical source-foot observables for the explicit full-FK material contract.

Raw fitting samples and already corrected playback poses have separate entry
points so a caller cannot silently combine corrected joints with raw axes.
"""
import numpy as np
from scipy.optimize._numdiff import approx_derivative, group_columns
from scipy.sparse import csr_matrix

from .native_foot_geometry import _normalized_side, native_foot_marker_world
from .native_material_frames import material_axes, validate_material_frames
from .rig_playback import decode_rig, sample_rig_coordinates


def foot_markers_from_pose(points, names, side_axes, observations, native_geometry):
    """Use supplied actual pose/axes, one sample per observation, without sampling.

    For playback, supply the points AND axes returned by the same contact sampler.
    The resulting arrays preserve observation order and use world coordinates.
    """
    points = np.asarray(points, dtype=float)
    count = len(observations)
    if points.shape != (count, len(names), 3) or not np.isfinite(points).all():
        raise ValueError('foot observation points must match observations and joint names')
    if not isinstance(side_axes, dict) or not isinstance(native_geometry, dict):
        raise ValueError('physical foot observations require actual axes and native geometry')
    result = {key: np.empty((count, 3)) for key in ('ankle', 'toe', 'heel')}
    for side in ('left', 'right'):
        indices = [i for i, row in enumerate(observations) if row.get('motionSide') == side]
        if not indices:
            continue
        ankle_name, foot_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or foot_name not in names:
            raise ValueError('physical foot observation chain is missing')
        ankle, foot = names.index(ankle_name), names.index(foot_name)
        for i in indices:
            row = observations[i]
            if (row.get('ankleJointIndex', ankle) != ankle
                    or row.get('footJointIndex', foot) != foot):
                raise ValueError('physical foot observation side/joint mapping disagrees')
        axes = np.asarray(side_axes.get(side), dtype=float)
        if axes.shape != (count, 3) or not np.isfinite(axes).all():
            raise ValueError('physical foot observation axes must match the actual pose')
        geometry = _normalized_side((native_geometry.get('sides') or {}).get(side))
        if geometry is None:
            raise ValueError('physical foot observation native side geometry is invalid')
        result['ankle'][indices] = points[indices, ankle]
        heel, toe = native_foot_marker_world(
            points[indices, ankle], points[indices, foot], axes[indices], geometry)
        result['heel'][indices], result['toe'][indices] = heel, toe
    if any(row.get('motionSide') not in ('left', 'right') for row in observations):
        raise ValueError('physical foot observation motionSide is invalid')
    return result


def projected_foot_vectors(markers, projection):
    """Return (N, 2, 2): [toe-minus-ankle, heel-minus-toe] image vectors.

    Camera translation cancels. No weights, target calibration or acceptance
    policy are applied here; the existing fit and gate owners retain them.
    """
    projection = np.asarray(projection, dtype=float)
    if projection.shape != (2, 3) or not np.isfinite(projection).all():
        raise ValueError('foot observation projection must be finite 2 by 3')
    return np.stack(((markers['toe'] - markers['ankle']) @ projection.T,
                     (markers['heel'] - markers['toe']) @ projection.T), axis=1)


def playback_foot_markers(payload, observations, *, wrap=None):
    """Observe the actual contact-corrected playback pose and returned axes."""
    from .rig_playback import _native_sampling_rig, sample_rig
    wrap = bool((payload.get('loop') or {}).get('enabled')) if wrap is None else wrap
    sampler = SourceFootMarkerSampler(payload['fixedRig'], observations,
                                      payload['nativeFootGeometry'], wrap=wrap,
                                      build_pattern=False)
    if not observations:
        return {key: np.empty((0, 3)) for key in ('ankle', 'toe', 'heel')}
    points, axes = sample_rig(_native_sampling_rig(payload), sampler.cursors,
                              wrap=wrap, return_side_axes=True)
    return foot_markers_from_pose(points, payload['jointNames'], axes, observations,
                                  payload['nativeFootGeometry'])


class SourceFootMarkerSampler:
    """Raw-q physical markers and their actual fractional/seam dependencies."""
    def __init__(self, rig, observations, native_geometry, *, wrap=False, build_pattern=True):
        if validate_material_frames(rig) is None:
            raise ValueError('physical foot sampling requires materialFrames; legacy belongs to caller')
        self.rig, self.observations = dict(rig), tuple(dict(row) for row in observations)
        self.geometry, self.wrap = native_geometry, bool(wrap)
        self.shape = np.asarray(rig['coordinates']).shape
        count, width = self.shape
        cursors = []
        for row in self.observations:
            left, right, alpha = row.get('leftFrame'), row.get('rightFrame'), row.get('alpha')
            if (type(left) is not int or type(right) is not int
                    or not 0 <= left < count or not 0 <= right < count
                    or not isinstance(alpha, (int, float)) or not np.isfinite(alpha)
                    or not 0 <= alpha <= 1):
                raise ValueError('physical foot observation clock is invalid')
            following = (left + 1) % count if wrap else min(left + 1, count - 1)
            if right not in (left, following) or (right == left and alpha != 0):
                raise ValueError('physical foot observation clock is not adjacent')
            cursors.append(left + alpha)
        self.cursors = np.asarray(cursors)
        self.pattern = self.groups = None
        if not build_pattern:
            return
        names = rig['jointNames']
        rotation_slots = {names.index(name): 3 + 3*i
                          for i, name in enumerate(rig['rotationJointNames'])}
        rows, columns = [], []
        for index, (row, cursor) in enumerate(zip(self.observations, self.cursors)):
            side = row.get('motionSide')
            if side not in ('left', 'right') or f'{side}_foot' not in names:
                raise ValueError('physical foot observation side is invalid')
            slots = {0, 1, 2}
            joint = names.index(f'{side}_foot')
            while joint >= 0:
                if joint in rotation_slots:
                    slots.update(range(rotation_slots[joint], rotation_slots[joint]+3))
                joint = rig['parents'][joint]
            stencil = int(np.floor(cursor)) + np.arange(-1, 3)
            stencil = stencil % count if wrap else np.clip(stencil, 0, count-1)
            for frame in np.unique(stencil):
                for slot in slots:
                    for component in range(4):
                        rows.append(index*4 + component)
                        columns.append(int(frame)*width + slot)
        self.pattern = csr_matrix((np.ones(len(rows)), (rows, columns)),
                                  shape=(len(self.observations)*4, count*width))
        self.groups = group_columns(self.pattern)

    def sample(self, coordinates):
        """Sample RAW FK only; never run contact correction or infer material axes."""
        values = np.asarray(coordinates, dtype=float).reshape(self.shape)
        if not np.isfinite(values).all():
            raise ValueError('physical foot sample coordinates must be finite')
        if not self.observations:
            return {key: np.empty((0, 3)) for key in ('ankle', 'toe', 'heel')}
        rig = {**self.rig, 'coordinates': values}
        sampled = sample_rig_coordinates(rig, self.cursors, wrap=self.wrap)
        points = decode_rig(rig, sampled)
        axes = material_axes(rig, self.cursors, wrap=self.wrap, coordinates=sampled)
        return foot_markers_from_pose(points, rig['jointNames'], axes,
                                      self.observations, self.geometry)

    def vectors(self, coordinates, projection):
        return projected_foot_vectors(self.sample(coordinates), projection)

    def jacobian(self, coordinates, projection):
        """Coordinate Jacobian of flattened (N,2,2) vectors, before fit weights."""
        values = np.asarray(coordinates, dtype=float).reshape(self.shape)
        if not self.observations:
            return csr_matrix((0, values.size))
        if self.pattern is None:
            prepared = SourceFootMarkerSampler(self.rig, self.observations,
                                                self.geometry, wrap=self.wrap)
            self.pattern, self.groups = prepared.pattern, prepared.groups
        return csr_matrix(approx_derivative(
            lambda q: self.vectors(q, projection).ravel(), values.ravel(),
            method='3-point', abs_step=1e-6, sparsity=(self.pattern, self.groups)))
