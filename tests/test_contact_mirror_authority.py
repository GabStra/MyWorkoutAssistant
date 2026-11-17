import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.controlled_motion import canonical_bilateral_reference
from exercise_motion_pkg.motion_placement import contact_consistent_target
from exercise_motion_pkg.support_alignment import (
    authoritative_mirror_sides, contact_consistent_policy_target, policy_alignment_errors,
)


def _fixture():
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json')
                        .read_text(encoding='utf-8'))
    names = list(fixture['joints'])
    points = np.repeat(np.asarray([fixture['joints'][name] for name in names])[None], 3, axis=0)
    return names, points


def test_contact_placement_reseats_only_the_unobserved_mirrored_chain():
    names, points = _fixture()
    execution = {'legs': 'mirrored'}
    points = canonical_bilateral_reference(points, names, execution)
    original = points.copy()
    pinned = np.zeros(points.shape[:2], dtype=bool)
    right = [names.index('right_ankle'), names.index('right_foot')]
    pinned[:, right] = True
    anchors = points.copy()
    anchors[:, right, 2] += .02
    kwargs = {'root_index': names.index('pelvis'), 'root_reference': points[:, names.index('pelvis')]}
    stale, _, _ = contact_consistent_target(points, pinned, anchors, **kwargs)
    assert np.max(np.abs(policy_alignment_errors(stale, names, execution))) > .001

    result, _ = contact_consistent_policy_target(points, names, execution, pinned, anchors, **kwargs)

    assert authoritative_mirror_sides(pinned, names, execution) == {'legs': 'right'}
    np.testing.assert_allclose(result[:, right], anchors[:, right], atol=1e-12)
    np.testing.assert_allclose(policy_alignment_errors(result, names, execution, pinned), 0., atol=1e-12)
    np.testing.assert_array_equal(points, original)
    repeated, _ = contact_consistent_policy_target(result, names, execution, pinned, anchors, **kwargs)
    np.testing.assert_allclose(repeated, result, atol=1e-12)


def test_contacts_on_both_sides_never_choose_one_by_sample_count():
    names, points = _fixture()
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, names.index('right_foot')] = True
    pinned[0, names.index('left_foot')] = True
    assert authoritative_mirror_sides(pinned, names, {'legs': 'mirrored'}) == {}
    anchors = points.copy()
    anchors[:, names.index('right_foot'), 2] += .02
    kwargs = {'root_index': names.index('pelvis'), 'root_reference': points[:, names.index('pelvis')]}
    expected, _, _ = contact_consistent_target(points, pinned, anchors, **kwargs)
    result, _ = contact_consistent_policy_target(
        points, names, {'legs': 'mirrored'}, pinned, anchors, **kwargs)
    np.testing.assert_array_equal(result, expected)
    pinned[:, names.index('left_foot')] = False
    assert authoritative_mirror_sides(pinned, names, {'legs': 'unconstrained'}) == {}


def test_native_pin_suppression_does_not_erase_source_mirror_authority():
    names, points = _fixture()
    execution = {'legs': 'mirrored'}
    source_pinned = np.zeros(points.shape[:2], dtype=bool)
    source_pinned[:, names.index('right_foot')] = True
    solver_pinned = source_pinned.copy()
    solver_pinned[:, names.index('right_foot')] = False

    source_authority = authoritative_mirror_sides(source_pinned, names, execution)
    assert source_authority == {'legs': 'right'}
    assert authoritative_mirror_sides(solver_pinned, names, execution) == {}

    preserved = canonical_bilateral_reference(
        points, names, execution, authoritative_sides=source_authority)
    averaged = canonical_bilateral_reference(
        points, names, execution,
        authoritative_sides=authoritative_mirror_sides(solver_pinned, names, execution))
    np.testing.assert_array_equal(
        preserved[:, names.index('right_foot')], points[:, names.index('right_foot')])
    assert np.max(np.abs(averaged[:, names.index('right_foot')]
                         - points[:, names.index('right_foot')])) > .001
