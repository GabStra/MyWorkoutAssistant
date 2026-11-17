import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse import eye as sparse_eye

from exercise_motion_pkg.motion_placement import root_motion_quality
from exercise_motion_pkg.trajectory_restoration import (
    _project_coordinate_rows_to_key_pin_tangent,
    dense_cyclic_root_continuity_rows,
    dense_root_sampling_jacobian,
)
from exercise_motion_pkg.rig_interpolation import INTERPOLATION, hermite_samples
from exercise_motion_pkg.controlled_motion import (
    _dense_root_continuity_protection_enabled,
    dense_root_continuity_only_seam_failure,
)


def test_dense_cyclic_root_rows_match_validator_and_include_seam():
    # Uneven cyclic samples make the duplicated-traversal seam row active.
    root = np.array([
        [0.00, 0., 0.], [0.03, 0., 0.], [0.07, 0., 0.],
        [0.13, 0., 0.], [0.21, 0., 0.], [0.31, 0., 0.],
    ])
    fps, scale = 30. * 4., .8
    labels, violations, jacobian, report = dense_cyclic_root_continuity_rows(
        root, fps=fps, scale=scale, cyclic=True)
    expected = root_motion_quality(np.concatenate([root, root]), fps, scale)
    assert jacobian is None
    assert len(labels) == len(root) * 2 - 2
    assert report['maximumSecondDifferenceMetersAt30Hz'] == expected['maximumSecondDifferenceMetersAt30Hz']
    assert report['limitMetersAt30Hz'] == expected['limitMetersAt30Hz']
    assert report['frames'] == expected['frames']
    assert np.allclose(violations, np.diff(np.concatenate([root, root]), n=2, axis=0)[:, 0]
                       .__abs__() * (fps / 30.)**2 / (.05 * scale) - 1.)


def test_dense_root_jacobian_chains_through_projection_and_playback_sampler():
    phase = 2. * np.pi * np.arange(8) / 8.
    root = np.column_stack((.10*np.sin(phase), .06*np.cos(phase), .04*np.sin(phase+.4)))
    n = len(root)
    cursors = np.arange(n * 4, dtype=float) / 4.
    first = np.floor(cursors).astype(int)
    last = (first + 1) % n
    alpha = cursors - first
    # A small coordinate projection mixes adjacent roots before the exact
    # Hermite playback sampler, exercising both links in the Jacobian chain.
    projection = np.eye(root.size)
    for frame in range(n):
        projection[3*frame:3*frame+3, 3*((frame-1) % n):3*((frame-1) % n)+3] += .08*np.eye(3)
    source = root.ravel().copy()
    projected = (projection @ source).reshape(root.shape)
    sampled = hermite_samples(projected, first, last, alpha, wrap=True, smooth_limiter=True)
    interpolation_jacobian = dense_root_sampling_jacobian(
        projected, cursors, interpolation=INTERPOLATION, wrap=True)
    chain = interpolation_jacobian @ csr_matrix(projection)
    labels, _, jacobian, _ = dense_cyclic_root_continuity_rows(
        sampled, fps=120., scale=.9, cyclic=True, sampled_root_jacobian=chain)
    assert jacobian.shape == (len(labels), root.size)
    epsilon = 1e-6

    def evaluate(q):
        projected_q = (projection @ q).reshape(root.shape)
        samples_q = hermite_samples(projected_q, first, last, alpha,
                                    wrap=True, smooth_limiter=True)
        return dense_cyclic_root_continuity_rows(
            samples_q, fps=120., scale=.9, cyclic=True)[1]

    for column in (0, 1, 6, 9, 12):
        delta = np.eye(root.size)[column] * epsilon
        finite = (evaluate(source + delta) - evaluate(source - delta)) / (2 * epsilon)
        assert np.allclose(finite, jacobian[:, column].toarray().ravel(), rtol=2e-6, atol=2e-7)


def test_dense_root_seam_eligibility_is_root_only_and_keeps_playback_pass():
    report = {
        'checks': {'contacts': True, 'playback': True, 'loopSeam': False,
                   'jerk': False, 'jointShake': False, 'relativeJointShake': False},
        'playback': {
            'passed': True, 'velocityContinuous': True, 'seamContinuous': False,
            'seamRenderedVelocityJumpMetersPerSecond': .001,
            'seamRenderedVelocityJumpLimitMetersPerSecond': .01,
            # Stored proxy may fail while rendered interpolation passes.
            'seamProxyContinuous': False,
            'loopMotionDiscontinuity': {
                'available': True, 'severe': False,
                'rootContinuity': {
                    'available': True, 'passed': False,
                    'maximumSecondDifferenceMetersAt30Hz': .12,
                    'limitMetersAt30Hz': .04,
                },
            },
            'physicalReasons': [], 'physicalEvents': [],
        },
    }
    assert dense_root_continuity_only_seam_failure(report)
    assert not dense_root_continuity_only_seam_failure({
        **report,
        'checks': {**report['checks'], 'anatomy': False},
    })
    assert not dense_root_continuity_only_seam_failure({
        **report,
        'playback': {**report['playback'], 'velocityContinuous': False},
    })
    assert not dense_root_continuity_only_seam_failure({
        **report,
        'playback': {**report['playback'], 'loopMotionDiscontinuity': {
            **report['playback']['loopMotionDiscontinuity'], 'severe': True}},
    })


def test_passing_playback_root_guard_is_protected_during_other_cyclic_repairs():
    # Dense-only eligibility remains distinct from retaining a passing root
    # invariant while repairing jerk or other temporal checks.
    assert _dense_root_continuity_protection_enabled(
        dense_root_only=False, cyclic=True, baseline_passed=True)
    assert not _dense_root_continuity_protection_enabled(
        dense_root_only=False, cyclic=True, baseline_passed=False)
    assert not _dense_root_continuity_protection_enabled(
        dense_root_only=False, cyclic=False, baseline_passed=True)
    assert _dense_root_continuity_protection_enabled(
        dense_root_only=True, cyclic=True, baseline_passed=False)


def test_material_attachment_rows_are_preserved_in_key_pin_tangent():
    class RootOnlyRig:
        names = ['pelvis']
        width = 3

        def decode(self, coordinates):
            return np.asarray(coordinates).reshape(-1, 1, 3)

        def fk_jacobian(self, coordinates):
            return sparse_eye(np.asarray(coordinates).size, format='csr')

    coordinates = np.zeros((2, 3))
    pinned = np.zeros((2, 1), dtype=bool)
    rows = csr_matrix([[1., 1., 0., 0., 1., 0.]])
    material = csr_matrix([[1., 0., 0., 1., 0., 0.]])
    projected, _ = _project_coordinate_rows_to_key_pin_tangent(
        coordinates, RootOnlyRig(), pinned, rows, protected_jacobian=material)
    assert np.allclose(material @ projected.T, 0., atol=1e-12)
    assert np.allclose(projected, [[0., 1., 0., 0., 1., 0.]])
