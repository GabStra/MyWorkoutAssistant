import numpy as np
import pytest
from time import monotonic
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.contact_heel_repair import (
    _aim_rotation,
    _aim_rotation_track,
    _encode_root_adjusted_pose,
    _encode_targets,
    _frame_state,
    _leg_specs,
    _root_track,
    _root_invariant_source_context,
    _coupled_root_fit,
    propose_contact_heel_repair,
)
from exercise_motion_pkg.contact_interpolation import build_contact_foot_tracks


class _SingleLegRig:
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot']
    parents = [-1, 0, 1, 2, 3]
    order = [0, 1, 2, 3, 4]
    root = 0
    active = [0, 2, 3, 4]
    slots = {0: 3, 2: 6, 3: 9, 4: 12}
    width = 15

    def __init__(self):
        self.offsets = np.array([
            [0., 0., 0.], [0., .9, 0.], [0., -.55, 0.],
            [0., -.55, 0.], [0., 0., .2],
        ])

    def decode(self, coordinates):
        coordinates = np.asarray(coordinates, dtype=float)
        rotations = Rotation.from_rotvec(
            coordinates[:, 3:].reshape(-1, 3)).as_matrix().reshape(-1, 4, 3, 3)
        points = np.empty((len(coordinates), len(self.names), 3))
        points[:, self.root] = coordinates[:, :3]
        matrices = {}
        for joint in self.order:
            parent = self.parents[joint]
            local = (rotations[:, (self.slots[joint] - 3) // 3]
                     if joint in self.slots else np.broadcast_to(np.eye(3), (len(coordinates), 3, 3)))
            matrices[joint] = local if parent < 0 else matrices[parent] @ local
            if parent >= 0:
                points[:, joint] = points[:, parent] + np.einsum(
                    'fij,j->fi', matrices[joint], self.offsets[joint])
        return points


def _pose():
    rig = _SingleLegRig()
    coordinates = np.zeros((1, rig.width))
    coordinates[0, rig.slots[2]:rig.slots[2] + 3] = [0., 0., .5]
    coordinates[0, rig.slots[3]:rig.slots[3] + 3] = [0., 0., -.8]
    return rig, coordinates, rig.decode(coordinates)


def test_root_shell_uses_degree_tolerances_as_radians():
    rig, _coordinates, points = _pose()
    directions = ((points[:, 4] - points[:, 3])
                  / np.linalg.norm(points[:, 4] - points[:, 3], axis=1, keepdims=True))
    pinned = np.zeros((1, len(rig.names)), dtype=bool)
    pinned[:, 3:5] = True

    specs = _leg_specs(rig.names, points, points, directions[:, None, :], pinned)
    margins, _ = _frame_state(specs, 0, np.zeros(3))

    np.testing.assert_allclose(np.rad2deg(margins), [9.5, 14.5], atol=1e-8)


def test_unreachable_root_margin_guides_optimizer_to_valid_leg_reach():
    from scipy.optimize import minimize

    rig, _coordinates, points = _pose()
    direction = points[:, 4] - points[:, 3]
    direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, 3:5] = True
    specs = _leg_specs(rig.names, points, points, direction[:, None, :], pinned)
    source_axis = specs[0]['sourceAxis'][0]
    unreachable_seed = -source_axis * .6

    unreachable_margins, unreachable_knees = _frame_state(
        specs, 0, unreachable_seed)
    nearer_margins, _ = _frame_state(specs, 0, -source_axis * .4)

    assert unreachable_knees is None
    assert np.isfinite(unreachable_margins).all()
    assert np.all(unreachable_margins < 0.)
    assert np.min(nearer_margins) > np.min(unreachable_margins)

    result = minimize(
        lambda translation: float(translation @ translation),
        unreachable_seed,
        method='SLSQP',
        bounds=[(-1., 1.)] * 3,
        constraints=[{'type': 'ineq',
                      'fun': lambda translation: _frame_state(
                          specs, 0, translation)[0]}],
        options={'maxiter': 100, 'ftol': 1e-10, 'disp': False},
    )

    feasible_margins, knees = _frame_state(specs, 0, result.x)
    assert result.success, result.message
    assert np.min(feasible_margins) >= -1e-7
    assert knees is not None


def test_free_foot_keeps_its_world_toe_trajectory_during_root_repair():
    rig, _coordinates, points = _pose()
    direction = (points[:, 4] - points[:, 3])
    direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    pinned = np.zeros((1, len(rig.names)), dtype=bool)
    specs = _leg_specs(rig.names, points, points, direction[:, None, :], pinned)
    shift = np.array([.012, -.004, .007])
    _base_margin, base_knee = _frame_state(specs, 0, np.zeros(3))
    moved_margin, moved_knee = _frame_state(specs, 0, shift)

    np.testing.assert_array_equal(specs[0]['targetToe'][0], points[0, 4])
    assert not specs[0]['toeFollowsRoot'][0]
    assert not specs[0]['ankleFollowsRoot'][0]
    assert np.all(np.isfinite(moved_margin))
    assert not np.allclose(moved_knee[0] - base_knee[0], shift, atol=1e-5)


def test_unknown_gap_carries_smoothed_pitch_without_creating_contact_or_toe_drift():
    rig, _coordinates, point = _pose()
    points = np.repeat(point, 5, axis=0)
    points += np.arange(5)[:, None, None] * np.array([.001, 0., 0.])
    angles = np.linspace(-.20, -.32, len(points))
    directions = np.column_stack([
        np.zeros(len(points)), np.sin(angles), np.cos(angles)])
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[[0, -1], 4] = True

    specs = _leg_specs(rig.names, points, points, directions[:, None, :], pinned)
    expected_ankles = points[:, 4] - np.linalg.norm(
        points[0, 4] - points[0, 3]) * directions
    target_directions = (specs[0]['targetToe'] - specs[0]['targetAnkle'])
    target_directions /= np.linalg.norm(target_directions, axis=1, keepdims=True)
    tracks = build_contact_foot_tracks(type('RigNames', (), {'names': rig.names})(), points, pinned)

    np.testing.assert_array_equal(specs[0]['targetToe'], points[:, 4])
    np.testing.assert_allclose(specs[0]['targetAnkle'], expected_ankles, atol=1e-10)
    np.testing.assert_allclose(target_directions, directions, atol=1e-10)
    assert np.max(np.linalg.norm(np.diff(specs[0]['targetAnkle'], n=2, axis=0), axis=1)) < 1e-3
    assert tracks['left']['active'] == [True, False, False, False, True]


def test_framewise_feasible_offsets_are_only_an_unsmoothed_seed(monkeypatch):
    targets = np.array([0., .01, 0., .01])

    def margins(_specs, frame, translation):
        return np.array([.005 - abs(translation[0] - targets[frame])]), np.zeros((1, 3))

    monkeypatch.setattr('exercise_motion_pkg.contact_heel_repair._frame_state', margins)
    offsets, report = _root_track([{}], len(targets), monotonic() + 2.)

    assert report['feasible']
    np.testing.assert_allclose(offsets[:, 0], [0., .005, 0., .005], atol=1e-6)
    assert report['maxSecondDifferenceMeters'] > 0.


def test_coupled_root_fit_reduces_root_acceleration_and_keeps_closed_chain():
    rig = _SingleLegRig()
    coordinates = np.zeros((4, rig.width))
    coordinates[:, :3] = np.array([0., .05, 0., .05])[:, None] * [1., 0., 0.]
    coordinates[:, rig.slots[2] + 2] = .5
    coordinates[:, rig.slots[3] + 2] = -.8
    points = rig.decode(coordinates)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    directions = points[:, 4] - points[:, 3]
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    specs = _leg_specs(rig.names, points, points, directions[:, None, :], pinned)
    # This isolates the root trajectory solve: both foot endpoints follow the
    # common translation, so its only remaining hard geometry is the leg chain.
    specs[0]['ankleFollowsRoot'][:] = True
    specs[0]['toeFollowsRoot'][:] = True
    seed, seed_report = _root_track(specs, len(points), monotonic() + 5.)
    assert seed_report['feasible']
    tracks = build_contact_foot_tracks(rig, points, pinned)
    before = np.max(np.linalg.norm(np.diff(points[:, rig.root], n=2, axis=0), axis=1))

    result, report = _coupled_root_fit(
        rig, coordinates, tracks, specs, points, 30., monotonic() + 12.,
        pinned=pinned, seed_offsets=seed, source_constraint={},
        jerk_reference=points, shake_reference=points,
        jerk_limit=1., body_scale=.6)

    assert result is None  # Root continuity remains a hard acceptance gate.
    assert report['reason'] == 'coupled_trajectory_hard_geometry_failed'
    assert report['candidateJerkRms'] < report['jerkReferenceRms']
    assert report['maximumFinalRootSecondDifferenceAt30Hz'] < before
    encoded, targets, _margins = _encode_root_adjusted_pose(
        rig, coordinates, specs, np.asarray(report['rootOffsetByFrame']))
    corrected = rig.decode(encoded)
    after = np.max(np.linalg.norm(np.diff(corrected[:, rig.root], n=2, axis=0), axis=1))
    assert after < before
    np.testing.assert_allclose(corrected[:, 4], targets[:, 4], atol=1e-8)
    np.testing.assert_allclose(
        np.linalg.norm(corrected[:, 2] - corrected[:, 1], axis=1),
        np.linalg.norm(points[:, 2] - points[:, 1], axis=1), atol=1e-8)
    np.testing.assert_allclose(
        np.linalg.norm(corrected[:, 3] - corrected[:, 2], axis=1),
        np.linalg.norm(points[:, 3] - points[:, 2], axis=1), atol=1e-8)
    assert encoded.shape == coordinates.shape

    original = coordinates.copy()
    with pytest.raises(TimeoutError):
        _coupled_root_fit(
            rig, coordinates, tracks, specs, points, 30., monotonic() - 1.,
            pinned=pinned, seed_offsets=seed, source_constraint={},
            jerk_reference=points, shake_reference=points,
            jerk_limit=1., body_scale=.6)
    np.testing.assert_array_equal(coordinates, original)


def test_explicit_airborne_patch_declines_the_local_heel_repair():
    rig, one_frame, _points = _pose()
    coordinates = np.repeat(one_frame, 4, axis=0)
    reference = rig.decode(coordinates)
    payload = {'sourceFootSupportEvidence': {'footPatchEvidence': {
        'available': True, 'feet': {'left': {'states': ['airborne']}}}}}
    source_constraint = {'sourceFootHeelTrajectoryObservations': [{}]}

    proposal = propose_contact_heel_repair(
        rig, coordinates, payload=payload,
        source_projection_constraint=source_constraint,
        anatomical_reference=reference,
        pinned=np.zeros(reference.shape[:2], dtype=bool), fps=30., cyclic=False,
        deadline=monotonic() + 2., jerk_reference=reference,
        shake_reference=reference, jerk_limit=1., body_scale=1.)

    assert proposal is None


def test_coupled_heel_repair_decline_preserves_solver_failure_details(monkeypatch):
    import exercise_motion_pkg.contact_heel_repair as repair
    import exercise_motion_pkg.contact_heel_pitch as pitch

    rig, one_frame, _points = _pose()
    coordinates = np.repeat(one_frame, 4, axis=0)
    reference = rig.decode(coordinates)
    pinned = np.zeros(reference.shape[:2], dtype=bool)
    directions = np.tile([0., 0., 1.], (len(coordinates), 2, 1))
    root_report = {'feasible': True, 'maxMagnitudeMeters': .026}
    coupled_report = {
        'attempted': True,
        'applied': False,
        'reason': 'coupled_trajectory_hard_geometry_failed',
        'optimizerSuccess': False,
        'optimizerMessage': 'maximum function evaluations exceeded',
        'evaluations': 10,
        'maximumFinalHardExcessDegrees': .2399,
        'maximumFinalKeyHardExcessDegrees': 0.,
    }
    monkeypatch.setattr(
        pitch, 'propose_source_heel_pitch',
        lambda *_args, **_kwargs: (directions, {'passed': True}),
    )
    monkeypatch.setattr(
        repair, '_leg_specs',
        lambda *_args, **_kwargs: [{'side': 'left', 'indices': (1, 2, 3, 4)}],
    )
    monkeypatch.setattr(
        repair, '_root_track',
        lambda _specs, count, _deadline: (np.zeros((count, 3)), root_report),
    )
    monkeypatch.setattr(
        repair, '_encode_root_adjusted_pose',
        lambda _rig, pose, _specs, _offsets: (pose.copy(), _rig.decode(pose), np.zeros((len(pose), 2))),
    )
    monkeypatch.setattr(
        repair, 'build_contact_foot_tracks',
        lambda *_args, **_kwargs: {'version': 1, 'left': {}, 'right': {}},
    )
    monkeypatch.setattr(
        repair, '_coupled_root_fit',
        lambda *_args, **_kwargs: (None, coupled_report),
    )
    payload = {'sourceFootSupportEvidence': {'footPatchEvidence': {
        'available': True, 'feet': {'left': {'states': ['full_sole']}}}}}
    constraint = {
        'sourceFootHeelTrajectoryObservations': [{}],
        'sourceFootHeelImageObservations': [{'state': 'full_sole'}],
    }
    failure = {}

    proposal = propose_contact_heel_repair(
        rig, coordinates, payload=payload, source_projection_constraint=constraint,
        anatomical_reference=reference, pinned=pinned, fps=30., cyclic=False,
        deadline=monotonic() + 2., jerk_reference=reference,
        shake_reference=reference, jerk_limit=1., body_scale=1.,
        failure_report=failure,
    )

    assert proposal is None
    assert failure == {
        'reason': 'coupled_trajectory_hard_geometry_failed',
        'rootFeasibility': root_report,
        'coupledRootTrajectoryFit': coupled_report,
    }


def test_reencoding_keeps_the_exact_toe_pivot_and_two_bone_chain():
    rig, coordinates, points = _pose()
    direction = (points[:, 4] - points[:, 3])
    direction = Rotation.from_rotvec([.08, 0., 0.]).apply(direction)
    direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    pinned = np.zeros((1, len(rig.names)), dtype=bool)
    pinned[:, 4] = True
    specs = _leg_specs(rig.names, points, points, direction[:, None, :], pinned)
    _margins, knees = _frame_state(specs, 0, np.zeros(3))
    targets = points.copy()
    targets[:, 2] = knees
    targets[:, 3] = specs[0]['targetAnkle']
    moving = [2, 3, 4]

    encoded = _encode_targets(rig, coordinates, targets, moving)

    assert encoded is not None
    np.testing.assert_allclose(rig.decode(encoded)[:, moving], targets[:, moving], atol=1e-8)
    np.testing.assert_array_equal(encoded[:, 3:6], coordinates[:, 3:6])
    np.testing.assert_allclose(targets[:, 4], points[:, 4], atol=0.)
    np.testing.assert_allclose(
        np.linalg.norm(targets[:, 2] - targets[:, 1], axis=1),
        np.linalg.norm(points[:, 2] - points[:, 1], axis=1), atol=1e-10)
    np.testing.assert_allclose(
        np.linalg.norm(targets[:, 3] - targets[:, 2], axis=1),
        np.linalg.norm(points[:, 3] - points[:, 2], axis=1), atol=1e-10)


def test_batched_aim_matches_scalar_parallel_antiparallel_and_twisted_cases():
    current = Rotation.from_rotvec(np.array([
        [0., 0., .42],
        [.2, -.1, .63],
        [-.3, .15, -.27],
        [.01, -.02, .51],
    ])).as_matrix()
    offset = np.array([0., 0., 1.])
    source = np.einsum('fij,j->fi', current, offset)
    target = source.copy()
    target[1] = -source[1]
    target[2] = -source[2] + np.array([1e-12, 0., 0.])
    target[3] = Rotation.from_rotvec([.3, -.4, .2]).apply(source[3])

    batched = _aim_rotation_track(current, offset, target)
    scalar = np.asarray([
        _aim_rotation(matrix, offset, direction)
        for matrix, direction in zip(current, target)
    ])

    np.testing.assert_allclose(batched, scalar, atol=1e-12, rtol=1e-12)


def test_root_solver_excludes_only_rows_invariant_under_fixed_foot_targets():
    constraint = {
        'observations': [{'jointIndex': 1}, {'jointIndex': 2}],
        'sourceFootPointObservations': [{'jointIndex': 3}, {'jointIndex': 4}],
        'sourceFootRayObservations': [
            {'ankleJointIndex': 3, 'footJointIndex': 4},
            {'ankleJointIndex': 6, 'footJointIndex': 7},
        ],
        'sourceFootHeelImageObservations': [
            {'motionSide': 'left'}, {'motionSide': 'right'},
        ],
        'sourceFootHeelTrajectoryEvents': [
            {'motionSide': 'left'}, {'motionSide': 'right'},
        ],
    }
    specs = [{
        'side': 'left', 'indices': (0, 1, 3, 4),
        'ankleFollowsRoot': np.zeros(6, dtype=bool),
        'toeFollowsRoot': np.zeros(6, dtype=bool),
    }]

    filtered, excluded = _root_invariant_source_context(constraint, specs)

    assert filtered['observations'] == [{'jointIndex': 1}, {'jointIndex': 2}]
    assert filtered['sourceFootPointObservations'] == []
    assert filtered['sourceFootRayObservations'] == [
        {'ankleJointIndex': 6, 'footJointIndex': 7}]
    assert filtered['sourceFootHeelImageObservations'] == [{'motionSide': 'right'}]
    assert filtered['sourceFootHeelTrajectoryEvents'] == [{'motionSide': 'right'}]
    assert excluded == {
        'pointObservations': 2, 'rayObservations': 1,
        'materialHeelObservations': 1, 'materialHeelEvents': 1,
    }

    # If either endpoint follows root, none of that foot's image constraints
    # are constant and they must remain in the optimization objective.
    specs[0]['toeFollowsRoot'][2] = True
    unfiltered, excluded = _root_invariant_source_context(constraint, specs)
    assert unfiltered == constraint
    assert not any(excluded.values())


def test_root_offsets_do_not_change_fixed_foot_endpoints_or_contact_tracks():
    rig, one_frame, one_point = _pose()
    coordinates = np.repeat(one_frame, 4, axis=0)
    points = np.repeat(one_point, 4, axis=0)
    direction = points[:, 4] - points[:, 3]
    direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, 4] = True
    specs = _leg_specs(rig.names, points, points, direction[:, None, :], pinned)
    seed = np.zeros((len(points), 3))
    shifted = np.tile([.01, -.004, .006], (len(points), 1))
    first, _targets, _margins = _encode_root_adjusted_pose(
        rig, coordinates, specs, seed)
    second, _targets, _margins = _encode_root_adjusted_pose(
        rig, coordinates, specs, shifted)

    first_points, second_points = rig.decode(first), rig.decode(second)
    np.testing.assert_allclose(first_points[:, 3:5], second_points[:, 3:5], atol=1e-8)
    first_tracks = build_contact_foot_tracks(rig, first_points, pinned)
    second_tracks = build_contact_foot_tracks(rig, second_points, pinned)
    for field in ('active', 'toes', 'directions'):
        np.testing.assert_allclose(first_tracks['left'][field],
                                   second_tracks['left'][field], atol=1e-8)
