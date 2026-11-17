from copy import deepcopy

import numpy as np
import pytest

from exercise_motion_pkg.sequence_stabilization import (
    canonical_stance_compatibility,
    contact_mask,
    fit_contact_mask,
)
from exercise_motion_pkg.youtube import normalize_bilateral_execution


NAMES = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']


def payload(*, stance=None, ground_mode='continuous', states=None, mapping=None):
    value = {'groundContactMode': ground_mode, 'jointNames': NAMES,
             'frames': [{'joints': {}} for _ in range(len(mapping or [0, 0, 0]))]}
    if stance is not None:
        value['bilateralExecution'] = {'stance': stance}
    return value


def evidence(*, states=None, mapping=None):
    result = {'footPatchEvidence': {'available': True, 'feet': {}}}
    if states is not None:
        result['footPatchEvidence']['feet'] = {
            side: {'states': list(states)} for side in ('left', 'right')}
    if mapping is not None:
        result['_fitFrameStateIndices'] = list(mapping)
    return result


def test_missing_intent_leaves_observed_mask_unchanged():
    item = payload()
    support = evidence(states=['full_sole'] * 3, mapping=[0, 1, 2])
    observed = contact_mask(item, NAMES, 3, support_evidence=support)
    np.testing.assert_array_equal(
        fit_contact_mask(item, NAMES, 3, support_evidence=support), observed)
    compatibility = canonical_stance_compatibility(item, NAMES, 3, support)
    assert compatibility['required'] is False
    assert compatibility['passed'] is True


def test_active_continuous_stance_pins_forefeet_not_ankles():
    item = payload(stance='stationary_bilateral')
    support = evidence(states=['full_sole'] * 3, mapping=[0, 1, 2])
    compatibility = canonical_stance_compatibility(item, NAMES, 3, support)
    assert compatibility['required'] is True
    assert compatibility['passed'] is True
    mask = fit_contact_mask(item, NAMES, 3, support_evidence=support)
    assert mask[:, NAMES.index('left_foot')].all()
    assert mask[:, NAMES.index('right_foot')].all()
    assert not mask[:, NAMES.index('left_ankle')].any()
    assert not mask[:, NAMES.index('right_ankle')].any()


def test_fit_contact_mask_does_not_mutate_source_evidence_or_contacts():
    item = payload(stance='stationary_bilateral')
    item['sourceFootSupportEvidence'] = {
        'contacts': [{'jointName': 'left_foot', 'contactState': 'toe_only',
                      'contactMotion': 'stationary', 'verticalOnly': False}],
        'supportContacts': [],
    }
    support = evidence(states=['full_sole'] * 3, mapping=[0, 1, 2])
    before_payload = deepcopy(item)
    before_support = deepcopy(support)
    fit_contact_mask(item, NAMES, 3, support_evidence=support)
    assert item == before_payload
    assert support == before_support


def test_known_airborne_in_fit_scope_gets_no_model_pins():
    item = payload(stance='stationary_bilateral')
    support = evidence(states=['airborne', 'full_sole', 'full_sole'], mapping=[0, 1, 2])
    compatibility = canonical_stance_compatibility(item, NAMES, 3, support)
    assert compatibility['passed'] is False
    assert 'airborne' in compatibility['reason']
    assert not fit_contact_mask(item, NAMES, 3, support_evidence=support).any()
    inactive = payload(stance='stationary_bilateral', ground_mode='intermittent')
    compatibility = canonical_stance_compatibility(inactive, NAMES, 3, support)
    assert compatibility['required'] is True
    assert compatibility['passed'] is False
    assert not fit_contact_mask(
        inactive, NAMES, 3, support_evidence=support).any()


def test_airborne_states_outside_fit_state_mapping_do_not_veto():
    item = payload(stance='stationary_bilateral')
    support = evidence(
        states=['airborne', 'airborne', 'full_sole', 'full_sole', 'full_sole', 'airborne'],
        mapping=[2, 3, 4],
    )
    compatibility = canonical_stance_compatibility(item, NAMES, 3, support)
    assert compatibility['passed'] is True
    mask = fit_contact_mask(item, NAMES, 3, support_evidence=support)
    assert mask[:, NAMES.index('left_foot')].all()
    assert mask[:, NAMES.index('right_foot')].all()


def test_normalize_accepts_explicit_stance_and_rejects_unknown_mode():
    assert normalize_bilateral_execution(
        {'stance': 'stationary_bilateral', 'arms': 'mirrored'}) == {
            'stance': 'stationary_bilateral', 'arms': 'mirrored'}
    assert normalize_bilateral_execution(
        {'stance': 'unconstrained', 'legs': 'mirrored'})['stance'] == 'unconstrained'
    with pytest.raises(ValueError):
        normalize_bilateral_execution({'stance': 'both_planted'})
    with pytest.raises(ValueError):
        normalize_bilateral_execution({'torso': 'mirrored'})


def test_canonical_stance_requires_geometry_and_keeps_estimated_anchors_separate():
    from exercise_motion_pkg.controlled_motion import apply_canonical_stance_targets
    item = payload()
    item['canonicalExecution'] = {'stance': 'stationary_bilateral'}
    item['renderFloorY'] = 0.0
    assert canonical_stance_compatibility(item, NAMES[:-1], 3)['passed'] is False
    support = evidence(states=['unknown'] * 3, mapping=[0, 1, 2])
    assert canonical_stance_compatibility(item, NAMES, 3, support)['passed'] is True
    pinned = fit_contact_mask(item, NAMES, 3, support_evidence=support)
    targets = np.zeros((3, len(NAMES), 3))
    targets[:, NAMES.index('right_foot'), 0] = [0., .01, .02]
    targets[:, NAMES.index('right_foot'), 1] = .01
    targets[:, NAMES.index('right_ankle'), 1] = [.1, .2, .1]
    before = targets.copy()
    result = apply_canonical_stance_targets(item, targets, NAMES, pinned)
    np.testing.assert_array_equal(targets, before)
    np.testing.assert_allclose(result[:, NAMES.index('right_foot')], [[.01, 0., 0.]] * 3)
    np.testing.assert_array_equal(result[:, NAMES.index('right_ankle')],
                                  before[:, NAMES.index('right_ankle')])
    item.pop('renderFloorY')
    shift = np.array([1., -1.7, 2.])
    estimated = apply_canonical_stance_targets(item, before, NAMES, pinned)
    translated = apply_canonical_stance_targets(item, before + shift, NAMES, pinned)
    np.testing.assert_allclose(translated, estimated + shift, atol=1e-12)


def test_stationary_mirrored_heading_target_preserves_articulation_and_heel_motion():
    import json
    from pathlib import Path
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.controlled_motion import canonical_stance_heading_target

    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    base = np.array([fixture['joints'][name] for name in names])
    points = np.repeat(base[None], 8, axis=0)
    points[:, names.index('right_ankle'), 1] += .02 * np.sin(np.linspace(0., np.pi, 8))
    points[:, names.index('left_hand'), 1] += .1 * np.sin(np.linspace(0., np.pi, 8))
    rotations = Rotation.from_euler('y', np.linspace(-.04, .04, 8)[:, None]).as_matrix()
    points = np.einsum('fij,fnj->fni', rotations, points)
    points += np.linspace([0., 0., 0.], [.1, .05, -.1], 8)[:, None, :]
    before = points.copy()
    anchors = np.zeros_like(points)
    anchors[:, names.index('right_foot'), 0] = .3
    execution = {'stance': 'stationary_bilateral', 'legs': 'mirrored', 'torso': 'sagittal'}
    result, report = canonical_stance_heading_target(points, names, execution, anchors)
    assert report['applied'] is True
    np.testing.assert_array_equal(points, before)
    np.testing.assert_allclose(result[:, names.index('pelvis'), 1:], before[:, names.index('pelvis'), 1:], atol=1e-12)
    np.testing.assert_allclose(result[:, :, 1], before[:, :, 1], atol=1e-12)
    np.testing.assert_allclose(
        np.linalg.norm(result[:, :, None] - result[:, None, :], axis=-1),
        np.linalg.norm(before[:, :, None] - before[:, None, :], axis=-1), atol=1e-12)
    hip_axis = result[:, names.index('right_hip')] - result[:, names.index('left_hip')]
    np.testing.assert_allclose(hip_axis[:, 2], 0., atol=1e-12)
    hip_midpoint = (result[:, names.index('right_hip')] + result[:, names.index('left_hip')]) / 2.
    np.testing.assert_allclose(hip_midpoint[:, 0], .15, atol=1e-12)
    _, invalid = canonical_stance_heading_target(points, names, execution, np.zeros_like(points))
    assert invalid['required'] and not invalid['applied']


@pytest.mark.parametrize('execution', [
    {}, {'stance': 'unconstrained', 'legs': 'mirrored', 'torso': 'sagittal'},
    {'stance': 'stationary_bilateral', 'legs': 'unconstrained', 'torso': 'sagittal'},
    {'stance': 'stationary_bilateral', 'legs': 'mirrored', 'torso': 'unconstrained'},
])
def test_heading_target_keeps_unconstrained_or_unilateral_motion(execution):
    from exercise_motion_pkg.controlled_motion import canonical_stance_heading_target
    points = np.zeros((3, 1, 3))
    result, report = canonical_stance_heading_target(points, ['pelvis'], execution, None)
    assert result is points
    assert report == {'required': False, 'applied': False}
