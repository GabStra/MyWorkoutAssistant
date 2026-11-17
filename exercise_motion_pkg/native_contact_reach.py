"""Fit the reach domain of production's unprotected native contact projection."""
import numpy as np
from scipy.optimize._numdiff import approx_derivative, group_columns
from scipy.sparse import csr_matrix


class NativeContactReachConstraint:
    """Refresh candidate key tracks before measuring actual playback ankle targets.

    Protected-knee material chains are deliberately not covered by this guard;
    the production sampler still validates those through their existing path.
    """
    def __init__(self, rig, tracks, evidence, cursors, *, cyclic, check_budget=None):
        from .support_joint_tracks import build_support_joint_tracks, validate_support_joint_tracks

        self.rig, self.tracks, self.evidence = rig, tracks, evidence
        self.cursors = np.asarray(cursors, dtype=float)
        self.cyclic, self.check_budget = cyclic, check_budget
        self.support_tracks = build_support_joint_tracks(evidence, rig.names, len(rig.initial))
        if self.support_tracks is not None:
            self.support_tracks = validate_support_joint_tracks(
                self.support_tracks, rig.names, len(rig.initial))
        count, width = rig.initial.shape
        self.shape = (len(self.cursors) * 4, count * width)
        neighbors = np.floor(self.cursors).astype(int)[:, None] + np.arange(-1, 3)
        neighbors = neighbors % count if cyclic else np.clip(neighbors, 0, count - 1)
        rows, columns = [], []
        for side_index, side in enumerate(('left', 'right')):
            if side not in tracks:
                continue
            # Both FK points and refreshed side axes read the complete foot chain.
            slots = {0, 1, 2}
            joint = rig.names.index(f'{side}_foot')
            while joint >= 0:
                if joint in rig.slots:
                    slots.update(range(rig.slots[joint], rig.slots[joint] + 3))
                joint = rig.parents[joint]
            for sample, stencil in enumerate(neighbors):
                for frame in np.unique(stencil):
                    for slot in slots:
                        for bound in range(2):
                            rows.append(sample * 4 + side_index * 2 + bound)
                            columns.append(frame * width + slot)
        self.pattern = csr_matrix((np.ones(len(rows)), (rows, columns)), shape=self.shape)
        self.groups = group_columns(self.pattern)
        self._values = None

    def residual(self, values):
        from .controlled_motion import _refresh_native_foot_contact_tracks, _sampling_payload
        from .rig_playback import sample_rig_coordinates
        from .contact_interpolation import _sample_native_material_contact_tracks

        values = np.asarray(values, dtype=float).reshape(self.rig.initial.shape)
        if self._values is not None and np.array_equal(values, self._values):
            return self._rows.copy()
        if self.check_budget is not None:
            self.check_budget()
        sampling = _sampling_payload(self.rig, values)
        sampling['contactFootTracks'] = _refresh_native_foot_contact_tracks(
            self.rig, values, self.tracks, self.evidence)
        if self.support_tracks is not None:
            sampling['supportJointTracks'] = self.support_tracks
            sampling['_supportJointTracksForSampling'] = self.support_tracks
        coordinates = sample_rig_coordinates(sampling, self.cursors, wrap=self.cyclic)
        rows, self.covered_samples = _sample_native_material_contact_tracks(
            sampling, self.cursors, self.rig.decode(coordinates), wrap=self.cyclic,
            preserve_keys=True,
            native_foot_geometry=sampling.get('_nativeFootGeometryForSampling'),
            foot_scale=sampling.get('_nativeFootScaleForSampling'),
            measure_unprotected_reach=True)
        self._values, self._rows = values.copy(), rows.ravel()
        return self._rows.copy()

    def unprotected_feasible(self, values):
        """Whether the covered branch lies inside the true two-bone reach domain."""
        return not np.any(self.residual(values) > 0.)

    def jacobian(self, values):
        # Re-evaluate the refreshed key frame on every probe; a fractional-axis
        # derivative alone misses the neighboring keys used by Hermite playback.
        return csr_matrix(approx_derivative(
            self.residual, np.asarray(values, dtype=float).ravel(), method='3-point',
            abs_step=1e-6, sparsity=(self.pattern, self.groups)))
