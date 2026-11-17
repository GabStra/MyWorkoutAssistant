import numpy as np

from exercise_motion_pkg import support_geometry


def _evidence(states, *, timed=True):
    patch = {'available': True, 'feet': {'left': {'states': list(states)}}}
    if timed:
        patch.update(sourceTimeBasis='absolute_source_video', sourceTimeOriginSec=0.,
                     sourceFps=25., sourceTimesSec=[i / 25. for i in range(len(states))])
    return {'footPatchEvidence': patch}


def _run(evidence, *, ankle=False, toe=True):
    names = ['left_ankle', 'left_foot']
    active = np.zeros((4, 2), dtype=bool)
    active[:, 0] = ankle
    active[:, 1] = toe
    ids = np.full((4, 2), None, dtype=object)
    if ankle: ids[:, 0] = 'explicit-ankle'
    if toe: ids[:, 1] = 'observed-foot'
    return support_geometry._stationary_geometry_contact_masks(
        evidence, names, active, ids, [i / 25. for i in range(4)])


def test_timed_full_sole_and_actual_toe_anchor_derive_geometry_only_ankle():
    evidence = _evidence(['full_sole'] * 4)
    active, identities = _run(evidence)
    np.testing.assert_array_equal(active[:, 0], [True] * 4)
    np.testing.assert_array_equal(active[:, 1], [True] * 4)
    np.testing.assert_array_equal(identities[:, 0], ['observed-foot'] * 4)


def test_missing_clock_and_unknown_states_do_not_derive_ankle():
    missing_clock, _ = _run(_evidence(['full_sole'] * 4, timed=False))
    unknown, _ = _run(_evidence(['full_sole', 'unknown', 'full_sole', 'unknown']))
    assert not missing_clock[:, 0].any()
    np.testing.assert_array_equal(unknown[:, 0], [True, False, True, False])


def test_physical_full_sole_without_actual_toe_anchor_does_not_derive_ankle():
    active, _ = _run(_evidence(['full_sole'] * 4), toe=False)
    assert not active[:, 0].any()


def test_explicit_ankle_restraint_remains_authoritative():
    active, identities = _run(_evidence(['unknown'] * 4), ankle=True, toe=False)
    np.testing.assert_array_equal(active[:, 0], [True] * 4)
    np.testing.assert_array_equal(identities[:, 0], ['explicit-ankle'] * 4)
