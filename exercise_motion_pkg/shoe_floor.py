"""Native shoe clearance in the supported-motion initializer's stored context."""
import numpy as np
from scipy.sparse import csr_matrix, lil_matrix, vstack
from scipy.optimize._numdiff import approx_derivative, group_columns


def native_shoe_material_context(payload, points, names):
    from .foot_geometry import foot_scale_from_pose, transport_sides
    from .temporal_quality import rendered_leg_sides
    sides = [side for side in ('left', 'right') if side+'_foot' in names]
    frames = [{'joints': dict(zip(names, row.tolist())),
               'boneSides': dict(source.get('boneSides') or {})}
              for row, source in zip(points, payload['frames'])]
    for side in sides:
        key = side+'_ankle->'+side+'_foot'
        exported = [index for index, frame in enumerate(frames) if key in frame['boneSides']]
        if exported:
            ankle, toe = [names.index(side+'_'+part) for part in ('ankle', 'foot')]
            source_axes = np.asarray([np.asarray(payload['frames'][index]['joints'][side+'_foot'])-
                                      payload['frames'][index]['joints'][side+'_ankle'] for index in exported])
            source_axes /= np.maximum(np.linalg.norm(source_axes, axis=1, keepdims=True), 1e-12)
            candidate_axes = points[exported, toe]-points[exported, ankle]
            candidate_axes /= np.maximum(np.linalg.norm(candidate_axes, axis=1, keepdims=True), 1e-12)
            axes = np.asarray([frames[index]['boneSides'][key] for index in exported])
            axes -= source_axes*np.sum(axes*source_axes, axis=1, keepdims=True)
            axes /= np.maximum(np.linalg.norm(axes, axis=1, keepdims=True), 1e-12)
            transported = transport_sides(axes, source_axes, candidate_axes, axes)
            for index, axis in zip(exported, transported):
                frames[index]['boneSides'][key] = axis.tolist()
    resolved = rendered_leg_sides(frames)
    scale = foot_scale_from_pose(points[0], names)
    return resolved, scale


class ShoeFloorConstraint:
    def __init__(self, rig, payload, *, frame_positions=None, context=None, check_budget=None, material_frame_positions=None):
        from .foot_geometry import shoe_orientation_tracks
        from .temporal_quality import rendered_leg_sides
        self.rig, self.payload, self.check_budget = rig, payload, check_budget
        artifact_rig = payload.get('fixedRig') or {}
        if 'materialFrames' in artifact_rig:
            from copy import deepcopy
            from .native_material_frames import validate_material_frames
            binding = validate_material_frames(artifact_rig)
            existing = getattr(rig, 'material_frames', None)
            if existing is not None and existing != binding:
                raise ValueError('shoe material calibration differs from current rig context')
            rig.material_frames = deepcopy(binding)
        self.context = np.asarray(context if context is not None else [
            [frame['joints'][name] for name in rig.names] for frame in payload['frames']], dtype=float).copy()
        positions = np.arange(len(rig.initial)) if frame_positions is None else np.asarray(frame_positions)
        if not np.array_equal(positions, positions.astype(int)):
            raise ValueError('Shoe floor projection requires exact stored-frame positions')
        self.positions = positions.astype(int)
        self.material_positions = (self.positions if material_frame_positions is None else
                                   np.asarray(material_frame_positions, dtype=int))
        self.full_fk_material = getattr(rig, 'material_frames', None) is not None
        self.sides = [side for side in ('left', 'right')
                      if {side+'_ankle', side+'_foot'}.issubset(rig.names)]
        from .material_region_support import calibrated_region_contacts, SHOE_REGION_FIT_ROW_COUNT
        self.region_contacts = calibrated_region_contacts(payload)
        self.floor_row_count = len(self.context)*len(self.sides)
        self.region_row_count = SHOE_REGION_FIT_ROW_COUNT
        self.shape = (self.floor_row_count + len(self.context)*self.region_row_count*len(self.region_contacts),
                      len(self.positions)*rig.width)
        self.packed_width = 9*len(self.sides)
        pattern = lil_matrix((self.shape[0], len(self.context)*self.packed_width+1), dtype=int)
        orientations = ({} if self.full_fk_material else shoe_orientation_tracks(
            payload, self.context, resolved_sides=rendered_leg_sides(payload['frames'])))
        for side_index, side in enumerate(self.sides):
            anchors = np.flatnonzero(orientations.get(side, {}).get('contactMask', []))
            for frame in range(len(self.context)):
                neighbors = {frame}
                if len(anchors) and frame not in anchors:
                    before, after = anchors[anchors < frame], anchors[anchors > frame]
                    if len(before): neighbors.add(int(before[-1]))
                    if len(after): neighbors.add(int(after[0]))
                for neighbor in neighbors:
                    pattern[frame*len(self.sides)+side_index,
                            neighbor*self.packed_width+side_index*9+np.arange(9)] = 1
        pattern[:, -1] = 1
        for contact_index, contact in enumerate(self.region_contacts):
            side_index = self.sides.index(contact['side'])
            for frame in range(len(self.context)):
                for component in range(self.region_row_count):
                    pattern[self.floor_row_count + (contact_index*len(self.context)+frame)*self.region_row_count+component] = (
                        pattern[frame*len(self.sides)+side_index])
        self.pattern = pattern.tocsr()
        self.groups = group_columns(self.pattern)

    def heights(self, values, *, check=True):
        from .foot_geometry import foot_scale_from_pose, transport_sides
        from .temporal_quality import rendered_leg_sides
        if check and self.check_budget is not None:
            self.check_budget()
        points = self.context.copy()
        points[self.positions] = self.rig.decode(np.asarray(values).reshape(len(self.positions), self.rig.width))
        resolved, scale = ((None, foot_scale_from_pose(points[0], self.rig.names))
                           if self.full_fk_material else
                           native_shoe_material_context(self.payload, points, self.rig.names))
        if self.full_fk_material:
            from .controlled_motion import _sampling_payload
            from .native_material_frames import material_axes
            current = np.asarray(values).reshape(len(self.positions), self.rig.width)
            if len(points) == len(self.rig.initial):
                full = self.rig.initial.copy()
                full[self.positions] = current
                axes = material_axes(_sampling_payload(self.rig, full), np.arange(len(points)))
            elif len(points) == len(current):
                axes = material_axes(_sampling_payload(self.rig, self.rig.initial),
                                     self.material_positions, coordinates=current)
            else:
                raise ValueError('native shoe material frame needs explicit complete current context')
            resolved = [{f'{side}_ankle->{side}_foot': axis[index]
                         for side, axis in axes.items()} for index in range(len(points))]
        self.points, self.resolved, self.scale = points, resolved, scale
        return self._heights(points, resolved, scale)

    def _heights(self, points, resolved, scale):
        vertices = self.material_vertices(points, resolved, scale)
        return np.stack([vertices[side][:, :, 1].min(axis=1)-float(self.payload['renderFloorY'])
                         for side in self.sides], axis=1).ravel() if self.sides else np.empty(0)

    def material_vertices(self, points, resolved, scale):
        from .foot_geometry import _sample_material_foot_geometry, shoe_vertices
        from .material_region_support import dorsal_material_payload
        if getattr(self, 'full_fk_material', False):
            from .native_foot_geometry import validated_native_foot_geometry
            native = validated_native_foot_geometry(self.payload.get('nativeFootGeometry'))
            if native is None:
                raise ValueError('native material shoe requires calibrated geometry')
            return {side: shoe_vertices(
                points[:, self.rig.names.index(side+'_ankle')],
                points[:, self.rig.names.index(side+'_foot')],
                np.asarray([row[f'{side}_ankle->{side}_foot'] for row in resolved]),
                None, scale, native_geometry=native['sides'][side]) for side in self.sides}
        material_payload = dorsal_material_payload(self.payload, points, resolved, self.rig.names)
        geometry = _sample_material_foot_geometry(material_payload, np.arange(len(points), dtype=float), points,
                                                 resolved_sides=resolved, keyframe_points=points)
        result = {}
        for side in self.sides:
            ankle, toe = [self.rig.names.index(side+'_'+part) for part in ('ankle', 'foot')]
            pitch = (self.payload.get('footRestPitchRadians') or {}).get(side)
            vertices = shoe_vertices(points[:, ankle], points[:, toe], geometry[side]['lateral'],
                                     pitch, scale, orientation=geometry[side]['orientation'],
                                     native_geometry=geometry[side].get('nativeGeometry'))
            result[side] = vertices
        return result

    def _residual_rows(self, points, resolved, scale):
        rows = [np.minimum(self._heights(points, resolved, scale), 0.)]
        if self.region_contacts:
            from .material_region_support import finite_patch_shoe_fit_rows
            vertices = self.material_vertices(points, resolved, scale)
            rows.extend(finite_patch_shoe_fit_rows(vertices[contact['side']], contact).ravel()
                        for contact in self.region_contacts)
        return np.concatenate(rows)

    def residual(self, values, *, check=True):
        self.heights(values, check=check)
        return self._residual_rows(self.points, self.resolved, self.scale)

    def jacobian(self, values):
        from .foot_geometry import foot_scale_from_pose
        from .material_floor import propagate_material_frame_jacobian
        if self.full_fk_material:
            # Per-key full FK plus the frame-zero foot scale. No nonlocal
            # point-only orientation anchors or history occur in this mode.
            count = len(self.context)
            width = self.rig.width
            pattern = lil_matrix(self.shape, dtype=int)
            for local, frame in enumerate(self.positions):
                columns = local*width + np.arange(width)
                rows = list(frame*len(self.sides) + np.arange(len(self.sides)))
                for contact in range(len(self.region_contacts)):
                    rows.extend(self.floor_row_count + (contact*count+frame)*self.region_row_count
                                + np.arange(self.region_row_count))
                for row in rows:
                    pattern[row, columns] = 1
                if frame == 0:
                    pattern[:, columns] = 1
            pattern = pattern.tocsr()
            return csr_matrix(approx_derivative(self.residual, np.asarray(values).ravel(),
                method='3-point', abs_step=1e-6, sparsity=(pattern, group_columns(pattern))))
        self.heights(values)
        points, resolved, scale = self.points.copy(), self.resolved, self.scale
        count, width, step = len(points), self.rig.width, 1e-6
        packed = np.empty((count, self.packed_width))
        fk = self.rig.fk_jacobian(np.asarray(values).reshape(len(self.positions), width))
        free = {int(frame): local for local, frame in enumerate(self.positions)}
        zero = csr_matrix((3, self.shape[1]))
        def joint_fk(frame, joint):
            return (fk[(free[frame]*len(self.rig.names)+joint)*3:
                       (free[frame]*len(self.rig.names)+joint+1)*3]
                    if frame in free else zero)
        chains = {}
        for side_index, side in enumerate(self.sides):
            ids = [self.rig.names.index(side+'_'+part) for part in ('knee', 'ankle', 'foot')]
            key = side+'_ankle->'+side+'_foot'
            history, local_blocks = [], []
            source = self.payload['frames']
            for frame in range(count):
                if self.check_budget is not None: self.check_budget()
                previous = None if frame == 0 else np.asarray(resolved[frame-1][key])
                exported = source[frame].get('boneSides', {}).get(key)
                foot_axis = points[frame, ids[2]]-points[frame, ids[1]]
                foot_axis /= max(np.linalg.norm(foot_axis), 1e-12)
                initial_cross = np.cross(foot_axis, points[frame, ids[0]]-points[frame, ids[1]])
                if exported is None and previous is None and np.linalg.norm(initial_cross) <= 1e-8:
                    # Native degenerate initialization can fall back to the knee
                    # frame's separate history. Keep that rare path exact too.
                    return csr_matrix(approx_derivative(self.residual, values, method='2-point'))
                def side_value(row, old):
                    from .temporal_quality import _unit, _cross3, transport_side, coordinate_knee_side
                    knee, ankle, toe = row[ids]
                    foot, shin = _unit(toe-ankle), _unit(ankle-knee)
                    if exported is not None:
                        old_axis = _unit(np.asarray(source[frame]['joints'][side+'_foot'])-
                                         source[frame]['joints'][side+'_ankle'])
                        axis = _unit(np.asarray(exported)-old_axis*np.dot(exported, old_axis))
                        result = transport_side(axis, old_axis, foot)
                        if result is not None: return result
                    result = _unit(old-foot*np.dot(old, foot)) if old is not None else None
                    if result is None: result = _unit(_cross3(foot, -shin))
                    if result is None:
                        hip = row[self.rig.names.index(side+'_hip')]
                        result = coordinate_knee_side(_unit(knee-hip), shin, foot, None)
                    return result
                local = np.zeros((3, 9))
                for k, joint in enumerate(ids):
                    for component in range(3):
                        plus, minus = points[frame].copy(), points[frame].copy()
                        plus[joint, component] += step; minus[joint, component] -= step
                        local[:, k*3+component] = (side_value(plus, previous)-side_value(minus, previous))/(2*step)
                h = np.zeros((3, 3))
                if previous is not None:
                    for component in range(3):
                        plus, minus = previous.copy(), previous.copy()
                        plus[component] += step; minus[component] -= step
                        h[:, component] = (side_value(points[frame], plus)-side_value(points[frame], minus))/(2*step)
                history.append(h)
                local_blocks.append(csr_matrix(local) @ vstack([joint_fk(frame, joint) for joint in ids]))
                offset = side_index*9
                packed[frame, offset:offset+9] = np.r_[points[frame, ids[1]], points[frame, ids[2]], resolved[frame][key]]
            chains[side] = propagate_material_frame_jacobian(np.asarray(history), local_blocks)
        mapping = []
        for frame in range(count):
            for side in self.sides:
                mapping.extend([joint_fk(frame, self.rig.names.index(side+'_ankle')),
                                joint_fk(frame, self.rig.names.index(side+'_foot')),
                                chains[side][frame*3:(frame+1)*3]])
        scale_gradient = csr_matrix((1, self.shape[1]))
        for name in ('left_hip', 'right_hip', 'left_shoulder', 'right_shoulder'):
            if name not in self.rig.names: continue
            joint = self.rig.names.index(name)
            gradient = np.empty((1, 3))
            for component in range(3):
                plus, minus = points[0].copy(), points[0].copy()
                plus[joint, component] += step; minus[joint, component] -= step
                gradient[0, component] = (foot_scale_from_pose(plus,self.rig.names)-foot_scale_from_pose(minus,self.rig.names))/(2*step)
            scale_gradient += csr_matrix(gradient) @ joint_fk(0, joint)
        mapping = vstack([*mapping, scale_gradient], format='csr')
        def reduced(vector):
            if self.check_budget is not None: self.check_budget()
            tracks = vector[:-1].reshape(count, self.packed_width)
            candidate, axes = points.copy(), [{} for _ in range(count)]
            for index, side in enumerate(self.sides):
                offset = index*9
                candidate[:, self.rig.names.index(side+'_ankle')] = tracks[:, offset:offset+3]
                candidate[:, self.rig.names.index(side+'_foot')] = tracks[:, offset+3:offset+6]
                key = side+'_ankle->'+side+'_foot'
                for frame in range(count): axes[frame][key] = tracks[frame, offset+6:offset+9]
            return self._residual_rows(candidate, axes, vector[-1])
        reduced_jacobian = approx_derivative(reduced, np.r_[packed.ravel(), scale], method='2-point',
                                             sparsity=(self.pattern, self.groups))
        return csr_matrix(reduced_jacobian @ mapping)
