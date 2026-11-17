"""Exact native knee-material constraints and their structured trajectory derivative."""
import numpy as np
from scipy.sparse import csr_matrix, eye

from .render_geometry import (knee_support_region, material_body_axes, material_leg_sides,
                              leg_roll_closure_angle)
from .temporal_quality import coordinate_knee_side
from .rig_playback import sample_rig_coordinates


def _unit(value):
    return value / np.maximum(np.linalg.norm(value, axis=-1, keepdims=True), 1e-12)


def _unit_jacobian(value):
    length = np.linalg.norm(value)
    normal = value / length
    return (np.eye(3) - np.outer(normal, normal)) / length


def _cross_matrix(value):
    x, y, z = value
    return np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])


def propagate_material_frame_jacobian(history, local_jacobians):
    """Chain a native three-vector frame recurrence through sparse rig inputs.

    Local blocks already include each frame's point/FK derivative. A reset or
    exported frame has a zero history block, retaining its exact native scope.
    """
    from scipy.sparse import vstack
    history = np.asarray(history, dtype=float)
    local = [csr_matrix(block) for block in local_jacobians]
    if history.shape != (len(local), 3, 3) or not local:
        raise ValueError('Material frame history must match its three-row local blocks')
    width = local[0].shape[1]
    if any(block.shape != (3, width) for block in local):
        raise ValueError('Material frame local Jacobians must share their rig input layout')
    previous = csr_matrix((3, width))
    result = []
    for transition, block in zip(history, local):
        previous = csr_matrix(transition) @ previous + block
        result.append(previous)
    return vstack(result, format='csr')


def _sample_jacobian(rig, coordinates, cursors, cyclic, step):
    """Color the existing interpolator's four-frame, joint-decoupled stencil."""
    from .controlled_motion import _sampling_payload
    count, width = coordinates.shape
    first = np.floor(cursors).astype(int)
    neighbors = first[:, None] + np.arange(-1, 3)
    neighbors = neighbors % count if cyclic else np.clip(neighbors, 0, count - 1)
    conflicts = [set() for _ in range(count)]
    for stencil in neighbors:
        for frame in stencil:
            conflicts[frame].update(stencil)
    colors = np.full(count, -1, dtype=int)
    for frame in range(count):
        used = {colors[other] for other in conflicts[frame] if colors[other] >= 0}
        color = 0
        while color in used:
            color += 1
        colors[frame] = color
    rows, columns, entries = [], [], []
    for color in range(int(colors.max()) + 1):
        frames = np.flatnonzero(colors == color)
        for rotations in (False, True):
            for component in range(3):
                slots = (3 + component + 3 * np.arange((width - 3) // 3)
                         if rotations else np.array([component]))
                plus, minus = coordinates.copy(), coordinates.copy()
                plus[frames[:, None], slots] += step
                minus[frames[:, None], slots] -= step
                difference = (sample_rig_coordinates(_sampling_payload(rig, plus), cursors, wrap=cyclic)
                              - sample_rig_coordinates(_sampling_payload(rig, minus), cursors, wrap=cyclic)) / (2 * step)
                sample, output = np.nonzero(difference)
                keep = (output >= 3) if rotations else (output < 3)
                sample, output = sample[keep], output[keep]
                matching = colors[neighbors[sample]] == color
                hit = neighbors[sample, matching.argmax(axis=1)]
                source = 3 + 3 * ((output - 3) // 3) + component if rotations else component
                rows.extend((sample * width + output).tolist())
                columns.extend((hit * width + source).tolist())
                entries.extend(difference[sample, output].tolist())
    return csr_matrix((entries, (rows, columns)), shape=(len(cursors) * width, count * width))


class MaterialFloorConstraint:
    """Keep observed contacts separate from candidate-dependent native material frames."""
    def __init__(self, rig, evidence, *, cursors=None, frame_positions=None, check_budget=None):
        from .support_geometry import support_contact_masks
        self.rig, self.evidence, self.names = rig, evidence, rig.names
        self.contacts = list(evidence.get('_floorMaterialContacts', []))
        self.context = np.asarray(evidence.get('_materialReferencePoints', rig.decode(rig.initial))).copy()
        self.positions = (np.arange(len(rig.initial)) if frame_positions is None
                          else np.asarray(frame_positions, dtype=float))
        if not np.array_equal(self.positions, self.positions.astype(int)):
            raise ValueError('Material keyframe positions must retain exact stored-frame identity')
        self.positions = self.positions.astype(int)
        self.complete = np.array_equal(self.positions, np.arange(len(self.context)))
        self.cursors = np.asarray(self.positions if cursors is None else cursors, dtype=float)
        if not self.complete and not np.array_equal(self.cursors, self.cursors.astype(int)):
            raise ValueError('A local material projection can query only its actual stored-frame context')
        self.cyclic = bool(evidence.get('_materialLoopable'))
        self.first = np.floor(self.cursors).astype(int)
        self.last = ((self.first + 1) % len(self.context) if self.cyclic else
                     np.minimum(self.first + 1, len(self.context) - 1))
        self.alpha = self.cursors - self.first
        active, _ = support_contact_masks(evidence, self.names, len(self.cursors),
                                         frame_positions=self.cursors)
        self.active = active[:, [self.names.index(joint) for joint in self.contacts]]
        self.shape = (len(self.cursors) * len(self.contacts), len(self.positions) * rig.width)
        self.check_budget = check_budget
        self._values = None
        self._jacobians = {}

    def _check(self):
        if self.check_budget is not None:
            self.check_budget()

    def _prepare(self, values, *, check=True):
        values = np.asarray(values, dtype=float).reshape(len(self.positions), self.rig.width)
        if self._values is not None and np.array_equal(values, self._values):
            return
        if check:
            self._check()
        from .controlled_motion import _sampling_payload
        self.points = self.context.copy()
        self.points[self.positions] = self.rig.decode(values)
        frames = [{'joints': dict(zip(self.names, row.tolist()))} for row in self.points]
        tracks = material_leg_sides(frames, loopable=self.cyclic)
        self.body = material_body_axes(self.points, self.names)
        self.sides = {joint: np.asarray([row[joint.split('_')[0] + '_knee->'
                                             + joint.split('_')[0] + '_ankle'] for row in tracks])
                      for joint in self.contacts}
        self.sample_coordinates = (sample_rig_coordinates(_sampling_payload(self.rig, values), self.cursors,
                                                          wrap=self.cyclic) if self.complete else values)
        self.sample_points = (self.rig.decode(self.sample_coordinates) if self.complete
                              else self.points[self.first])
        raw = []
        for joint in self.contacts:
            side = joint.split('_')[0]
            axes = self.sides[joint][self.first] * (1 - self.alpha[:, None]) + self.sides[joint][self.last] * self.alpha[:, None]
            region = knee_support_region(self.sample_points, self.names, joint,
                lengths=self.evidence['_materialSegmentLengths'][side], side_axes=axes, body_axes=self.body[self.first])
            raw.append(region[:, :, 1].min(axis=1) - self.evidence['_renderFloorY'])
        self.raw_values = np.stack(raw, axis=1) if raw else np.empty((len(self.cursors), 0))
        self._values = values.copy()
        self._jacobians = {}

    def residual(self, values, *, bounded=True, check=True):
        from .support_geometry import TOLERANCE_METERS
        self._prepare(values, check=check)
        raw = self.raw_values
        fitted = np.minimum(raw, 0.) + np.maximum(raw - TOLERANCE_METERS, 0.) if bounded else raw
        return np.where(self.active, fitted, np.minimum(raw, 0.)).ravel()

    def jacobian(self, values, *, bounded=True):
        from .support_geometry import TOLERANCE_METERS
        self._check()
        self._prepare(values)
        if bounded in self._jacobians:
            return self._jacobians[bounded]
        selected = ((self.raw_values < 0.) | (self.active & (self.raw_values > TOLERANCE_METERS))
                    if bounded else (self.active | (self.raw_values < 0.)))
        active_rows = np.argwhere(selected)
        if not len(active_rows):
            result = csr_matrix(self.shape)
            self._jacobians[bounded] = result
            return result
        step, points, count = 1e-6, self.points, len(self.points)
        fk = self.rig.fk_jacobian(self._values)
        sample_fk = self.rig.fk_jacobian(self.sample_coordinates)
        interpolation = (_sample_jacobian(self.rig, self._values, self.cursors, self.cyclic, step)
                         if self.complete else eye(self.shape[1], format='csr'))
        tapes = {}
        free = set(self.positions)
        for joint in self.contacts:
            side = joint.split('_')[0]
            ids = [self.names.index(side + '_' + part) for part in ('hip', 'knee', 'ankle', 'foot')]
            axes = _unit(points[:, ids[2]] - points[:, ids[1]])
            raw, history, local = [], [], {}
            def value(frame, previous):
                thigh, shin, foot = (_unit(frame[b] - frame[a]) for a, b in zip(ids, ids[1:]))
                return coordinate_knee_side(thigh, shin, foot, previous)
            for frame in range(count):
                self._check()
                previous = None if not frame else raw[-1]
                thigh, shin, foot = (_unit(points[frame, b] - points[frame, a]) for a, b in zip(ids, ids[1:]))
                side_value, derivative = coordinate_knee_side(thigh, shin, foot, previous, previous_jacobian=True)
                raw.append(side_value)
                history.append(derivative)
                if frame in free:
                    block = np.zeros((3, 4, 3))
                    for k, index in enumerate(ids):
                        for component in range(3):
                            plus, minus = points[frame].copy(), points[frame].copy()
                            plus[index, component] += step
                            minus[index, component] -= step
                            block[:, k, component] = (value(plus, previous) - value(minus, previous)) / (2 * step)
                    local[frame] = block
            raw = np.asarray(raw)
            angle = leg_roll_closure_angle(raw[-1], raw[0], axes[-1], axes[0]) if self.cyclic else 0.
            closure_gradient = np.zeros(12)
            if self.cyclic:
                endpoints = np.r_[raw[-1], raw[0], axes[-1], axes[0]]
                for index in range(12):
                    plus, minus = endpoints.copy(), endpoints.copy()
                    plus[index] += step
                    minus[index] -= step
                    delta = (leg_roll_closure_angle(*plus.reshape(4, 3))
                             - leg_roll_closure_angle(*minus.reshape(4, 3)))
                    closure_gradient[index] = np.arctan2(np.sin(delta), np.cos(delta)) / (2 * step)
            tapes[joint] = ids, axes, raw, history, local, angle, closure_gradient
        body_gradients = {}
        def body_back(frame, gradient):
            if frame not in body_gradients:
                lo, hi = max(0, frame - 3), min(count, frame + 4)
                window = points[lo:hi]
                ids = [self.names.index(name) for name in ('left_hip', 'right_hip', 'neck', 'pelvis')]
                block = np.zeros((3, 3, hi - lo, 4, 3))
                for index in range(hi - lo):
                    if lo + index not in free:
                        continue
                    for k, joint in enumerate(ids):
                        for component in range(3):
                            plus, minus = window.copy(), window.copy()
                            plus[index, joint, component] += step
                            minus[index, joint, component] -= step
                            block[:, :, index, k, component] = (
                                material_body_axes(plus, self.names)[frame - lo]
                                - material_body_axes(minus, self.names)[frame - lo]) / (2 * step)
                body_gradients[frame] = lo, hi, ids, block
            lo, hi, ids, block = body_gradients[frame]
            result = np.zeros_like(points)
            part = np.einsum('ab,abfkd->fkd', gradient, block)
            for k, joint in enumerate(ids):
                result[lo:hi, joint] += part[:, k]
            return result
        rows, columns, entries = [], [], []
        for sample, contact in active_rows:
            self._check()
            joint = self.contacts[contact]
            ids, axes, raw, history, local, angle, closure_gradient = tapes[joint]
            first, last, alpha = self.first[sample], self.last[sample], self.alpha[sample]
            closed = self.sides[joint]
            side = closed[first] * (1 - alpha) + closed[last] * alpha
            point, body = self.sample_points[sample:sample + 1], self.body[first:first + 1]
            def height(p, z, matrix):
                return knee_support_region(p, self.names, joint,
                    lengths=self.evidence['_materialSegmentLengths'][joint.split('_')[0]],
                    side_axes=z[None], body_axes=matrix)[:, :, 1].min()
            point_gradient, side_gradient, body_gradient = np.zeros((len(self.names), 3)), np.empty(3), np.empty((3, 3))
            for index in ids[:3]:
                for component in range(3):
                    plus, minus = point.copy(), point.copy()
                    plus[0, index, component] += step
                    minus[0, index, component] -= step
                    point_gradient[index, component] = (height(plus, side, body) - height(minus, side, body)) / (2 * step)
            for component in range(3):
                plus, minus = side.copy(), side.copy()
                plus[component] += step
                minus[component] -= step
                side_gradient[component] = (height(point, plus, body) - height(point, minus, body)) / (2 * step)
            for row in range(3):
                for column in range(3):
                    plus, minus = body.copy(), body.copy()
                    plus[0, row, column] += step
                    minus[0, row, column] -= step
                    body_gradient[row, column] = (height(point, side, plus) - height(point, side, minus)) / (2 * step)
            closed_gradient = np.zeros((count, 3))
            closed_gradient[first] += (1 - alpha) * side_gradient
            closed_gradient[last] += alpha * side_gradient
            state_gradient, axis_gradient, angle_gradient = np.zeros((count, 3)), np.zeros((count, 3)), 0.
            for frame in np.flatnonzero(np.any(closed_gradient != 0., axis=1)):
                theta = angle * frame / count
                cosine, sine, axis, vector = np.cos(theta), np.sin(theta), axes[frame], raw[frame]
                dv = cosine * np.eye(3) + sine * _cross_matrix(axis) + (1 - cosine) * np.outer(axis, axis)
                da = -sine * _cross_matrix(vector) + (1 - cosine) * (np.dot(axis, vector) * np.eye(3) + np.outer(axis, vector))
                dt = -vector * sine + np.cross(axis, vector) * cosine + axis * np.dot(axis, vector) * sine
                state_gradient[frame] += dv.T @ closed_gradient[frame]
                axis_gradient[frame] += da.T @ closed_gradient[frame]
                angle_gradient += frame / count * np.dot(dt, closed_gradient[frame])
            state_gradient[-1] += angle_gradient * closure_gradient[:3]
            state_gradient[0] += angle_gradient * closure_gradient[3:6]
            axis_gradient[-1] += angle_gradient * closure_gradient[6:9]
            axis_gradient[0] += angle_gradient * closure_gradient[9:]
            gradient = body_back(first, body_gradient)
            for frame in range(count - 1, -1, -1):
                if frame in free:
                    part = np.einsum('a,akd->kd', state_gradient[frame], local[frame])
                    for k, index in enumerate(ids):
                        gradient[frame, index] += part[k]
                    delta = _unit_jacobian(points[frame, ids[2]] - points[frame, ids[1]]).T @ axis_gradient[frame]
                    gradient[frame, ids[2]] += delta
                    gradient[frame, ids[1]] -= delta
                if frame:
                    state_gradient[frame - 1] += history[frame].T @ state_gradient[frame]
            stored = csr_matrix(gradient[self.positions].ravel()[None]) @ fk
            if self.complete:
                sample_block = sample_fk[sample * len(self.names) * 3:(sample + 1) * len(self.names) * 3,
                                        sample * self.rig.width:(sample + 1) * self.rig.width]
                sampled = csr_matrix(point_gradient.ravel()[None]) @ sample_block @ interpolation[
                    sample * self.rig.width:(sample + 1) * self.rig.width]
            else:
                free_frame = np.flatnonzero(self.positions == first)
                sampled = csr_matrix((1, self.shape[1]))
                if len(free_frame):
                    index = int(free_frame[0])
                    sample_block = sample_fk[index * len(self.names) * 3:(index + 1) * len(self.names) * 3]
                    sampled = csr_matrix(point_gradient.ravel()[None]) @ sample_block
            combined = (stored + sampled).tocoo()
            rows.extend([int(sample * len(self.contacts) + contact)] * combined.nnz)
            columns.extend(combined.col.tolist())
            entries.extend(combined.data.tolist())
        result = csr_matrix((entries, (rows, columns)), shape=self.shape)
        self._jacobians[bounded] = result
        return result
