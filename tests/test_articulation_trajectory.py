import copy
import json
import math

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from scipy.sparse import diags, csr_matrix, kron, vstack
from scipy.optimize._numdiff import group_columns

from exercise_motion_pkg.articulation_trajectory import (
    _natural_jacobian_column_groups, fit_chain_rotations,
    fit_pose_and_temporal_trajectories, temporal_quality_comparison,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg import structural_refinement as refinement


def arm_clip(angles):
    frames = []
    for index, angle in enumerate(angles):
        rotation = Rotation.from_euler('z', angle, degrees=True)
        shoulder = np.array([0., 1., 0.])
        elbow = shoulder + rotation.apply([.3, -.3, 0.])
        wrist = elbow + rotation.apply([.3, -.1, 0.])
        hand = wrist + rotation.apply([.1, 0., 0.])
        joints = {'pelvis': (0., .5, 0.), 'head': (0., 1.5, 0.)}
        joints.update({name: tuple(float(v) for v in point) for name, point in zip(
            ['left_shoulder', 'left_elbow', 'left_wrist', 'left_hand'], [shoulder, elbow, wrist, hand])})
        frames.append(MotionFrame(index / 30., joints))
    return MotionClip(30., list(frames[0].joints), frames)


CHAIN = ('left_shoulder', 'left_elbow', 'left_wrist', 'left_hand')


def test_natural_sparse_jacobian_coloring_reduces_banded_frame_colors():
    frame_count = 12
    frame_dependencies = csr_matrix(np.array([
        [1, 0, 1, 0, 0, 0, 0, 0],
        [1, 1, 1, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 1, 0, 0, 0],
        [0, 0, 0, 1, 1, 1, 0, 0],
        [0, 0, 0, 0, 0, 1, 1, 0],
        [0, 0, 0, 0, 0, 1, 1, 1],
    ], dtype=float))
    patterns = []
    for temporal_order in range(4):
        temporal = diags(
            [np.ones(frame_count - temporal_order)] * (temporal_order + 1),
            range(temporal_order + 1),
            shape=(frame_count - temporal_order, frame_count),
        )
        patterns.append(kron(temporal, frame_dependencies))
    pattern = vstack(patterns, format='csr')

    groups = _natural_jacobian_column_groups(pattern)
    default_group_count = int(group_columns(pattern, order=0).max() + 1)

    assert int(groups.max() + 1) == 12
    assert int(groups.max() + 1) < default_group_count
    for row_index in range(pattern.shape[0]):
        columns = pattern.getrow(row_index).indices
        assert len(set(groups[columns])) == len(columns)


def test_rotational_smoothing_preserves_each_bone_length_and_root():
    source = arm_clip([0., 0., 0., 45., 0., 0., 0.])
    result = fit_chain_rotations(source, CHAIN)
    for before, after in zip(source.frames, result.frames):
        assert before.joints[CHAIN[0]] == after.joints[CHAIN[0]]
        for parent, child in zip(CHAIN, CHAIN[1:]):
            assert math.dist(after.joints[parent], after.joints[child]) == pytest.approx(
                math.dist(before.joints[parent], before.joints[child]), abs=1e-12)
    # Pipeline metadata and coordinates must remain serializable without a
    # custom encoder for numpy scalars.
    json.dumps([frame.joints for frame in result.frames])


def test_trajectory_fit_capture_records_replayable_exact_solver_inputs(monkeypatch, tmp_path):
    source = arm_clip([0., 10., 20., 30., 20., 10.])
    proposal = arm_clip([0., 12., 23., 32., 22., 11.])
    destination = tmp_path / 'trajectory-fit.json'
    monkeypatch.setenv('EXERCISE_MOTION_TRAJECTORY_FIT_CAPTURE', str(destination))

    refinement._capture_trajectory_fit_replay(
        source,
        proposal,
        (CHAIN,),
        observation_weights=np.ones((source.frame_count, len(CHAIN) - 1)),
        projected_observations=True,
        rigid_pair=('left_wrist', 'left_hand'),
        timeout_seconds=120.,
        max_evaluations=400,
    )

    payload = json.loads(destination.read_text(encoding='utf-8'))
    assert payload['schema'] == 'trajectory_fit_replay_v1'
    assert payload['source']['frames'][0]['joints'] == json.loads(
        json.dumps(source.frames[0].joints)
    )
    assert payload['proposal']['frames'][-1]['joints'] == json.loads(
        json.dumps(proposal.frames[-1].joints)
    )
    assert payload['chains'] == [list(CHAIN)]
    assert payload['solver_options']['observation_weights'] == np.ones(
        (source.frame_count, len(CHAIN) - 1)
    ).tolist()
    assert payload['solver_options']['rigid_pair'] == ['left_wrist', 'left_hand']


def test_fitting_constant_correction_preserves_real_source_motion():
    source = arm_clip(np.linspace(-15., 15., 19))
    proposal = arm_clip(np.linspace(-5., 25., 19))
    result = fit_chain_rotations(source, CHAIN, proposal=proposal)
    for actual, expected in zip(result.frames, proposal.frames):
        for name in CHAIN:
            np.testing.assert_allclose(actual.joints[name], expected.joints[name], atol=1e-10)


def test_rotation_wrap_does_not_turn_a_small_motion_into_a_limb_spin():
    source = arm_clip(np.linspace(170., 190., 21))
    result = fit_chain_rotations(source, CHAIN)
    for parent, child in zip(CHAIN, CHAIN[1:]):
        vectors = np.array([np.subtract(frame.joints[child], frame.joints[parent])
                            for frame in result.frames])
        directions = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        steps = np.degrees(np.arccos(np.clip(np.sum(directions[1:] * directions[:-1], axis=1), -1., 1.)))
        assert np.max(steps) <= 1.01


@pytest.mark.parametrize('has_source', [False, True])
def test_pose_improvement_cannot_authorize_a_new_local_spike(monkeypatch, has_source):
    before = arm_clip([0.] * 21)
    proposed = arm_clip([0.] * 10 + [60.] + [0.] * 10)
    monkeypatch.setattr(refinement, 'registered_camera_pose_fidelity_metrics', lambda *a, **k: {
        'available': True, 'p90JointErrorBodyRatio': .1 if k.get('camera_reference') else .2})
    result, report = refinement._accept_source_preserving_refinement_step(
        before, proposed, source_pose_payload={} if has_source else None,
        source_guided_articulation=True, step_name='test')
    assert not report['accepted']
    assert report['reason'] == 'temporal_quality_degraded'
    assert result.frames == before.frames


def test_unchanged_correction_does_not_create_motion():
    source = arm_clip([10.] * 11)
    result = fit_chain_rotations(source, CHAIN, proposal=copy.deepcopy(source))
    assert temporal_quality_comparison(source, result)['passed']
    for before, after in zip(source.frames, result.frames):
        for name in CHAIN:
            np.testing.assert_allclose(after.joints[name], before.joints[name], atol=1e-12)


def test_joint_pose_temporal_fit_improves_target_without_accepting_a_snap():
    source = arm_clip([0.] * 41)
    target = arm_clip([0.] * 10 + [45.] * 21 + [0.] * 10)
    assert not temporal_quality_comparison(source, target)['passed']
    result, report = fit_pose_and_temporal_trajectories(source, target, (CHAIN,))
    assert report['applied']
    assert report['objectiveProgress']
    assert report['objectiveProgress'][0]['bestObjective'] <= report['initialObjective']
    assert report['objectiveProgress'][-1]['bestObjective'] == pytest.approx(report['finalObjective'])
    assert 0 < report['residualEvaluationSeconds'] <= report['elapsedSeconds']
    assert 0 < report['residualEvaluationShare'] <= 1
    assert report['poseTargetRmsAfter'] < report['poseTargetRmsBefore'] * .65
    assert temporal_quality_comparison(source, result)['passed']
    for before, after in zip(source.frames, result.frames):
        assert before.joints['pelvis'] == after.joints['pelvis']
        assert before.joints['head'] == after.joints['head']
        assert before.joints[CHAIN[0]] == after.joints[CHAIN[0]]
        for parent, child in zip(CHAIN, CHAIN[1:]):
            assert math.dist(after.joints[parent], after.joints[child]) == pytest.approx(
                math.dist(before.joints[parent], before.joints[child]), abs=1e-10)


def test_missing_observations_do_not_force_return_to_uncorrected_pose():
    source = arm_clip([0.] * 25)
    target = arm_clip([30.] * 20 + [0.] * 5)
    weights = np.ones((25, 3))
    weights[20:] = 0
    result, report = fit_pose_and_temporal_trajectories(source, target, (CHAIN,), observation_weights=weights)
    assert report['applied']
    expected = arm_clip([30.] * 25)
    assert math.dist(result.frames[-1].joints['left_wrist'], expected.frames[-1].joints['left_wrist']) < .03
    assert temporal_quality_comparison(source, result)['passed']


def test_absent_evidence_leaves_the_original_clip_unchanged():
    source = arm_clip([0.] * 9)
    result, report = fit_pose_and_temporal_trajectories(source, arm_clip([50.] * 9), (CHAIN,),
                                                       observation_weights=np.zeros((9, 3)))
    assert result is source
    assert not report['applied']
    assert report['reason'] == 'no_observed_targets'


def test_exhausted_budget_keeps_original_geometry():
    source = arm_clip([0.] * 9)
    result, report = fit_pose_and_temporal_trajectories(source, arm_clip([50.] * 9), (CHAIN,), timeout_seconds=0)
    assert result is source
    assert not report['applied']
    assert report['reason'] == 'fit_budget_exhausted'


def test_post_ik_spike_repair_does_not_shorten_the_limb():
    source = arm_clip([0.] * 5 + [60.] + [0.] * 5)
    repaired, report = refinement.suppress_post_ik_anatomical_spikes(source)
    assert report['applied']
    for before, after in zip(source.frames, repaired.frames):
        for parent, child in zip(CHAIN, CHAIN[1:]):
            assert math.dist(after.joints[parent], after.joints[child]) == pytest.approx(
                math.dist(before.joints[parent], before.joints[child]), abs=1e-10)


def test_old_spike_elsewhere_cannot_hide_a_new_smaller_spike():
    angles = [0.] * 31
    angles[6] = 75.
    before = arm_clip(angles)
    angles[24] = 35.
    proposed = arm_clip(angles)
    comparison = temporal_quality_comparison(before, proposed)
    assert not comparison['passed']
    assert 'introducedJointSpikes' in comparison['degradedCategories']
    assert any(abs(event['frameIndex'] - 24) <= 1
               for event in comparison['proposed']['introducedJointSpikes']['events'])
