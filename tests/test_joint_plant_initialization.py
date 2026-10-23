import json
from copy import deepcopy
from pathlib import Path
from time import monotonic

import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import FixedRig, support_initialization_articulation_regressions
from exercise_motion_pkg.joint_plant_initialization import initialize_joint_plant_coordinates


def _stance(count=12):
    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.array([fixture['joints'][name] for name in names]), (count, 1, 1))
    return names, points


@pytest.mark.parametrize(('axis', 'axis_name', 'minimum_root_shift'), [
    (0, 'X', .02), (1, 'Y', .02), (2, 'Z', 0.),
])
def test_joint_plant_moves_root_before_distorting_supported_articulation(
        axis, axis_name, minimum_root_shift):
    names, source = _stance()
    rig = FixedRig(source, names)
    baseline = rig.initial.copy()
    points = rig.decode(baseline)
    pins = np.zeros(points.shape[:2], dtype=bool)
    targets = points.copy()
    for name in ('left_ankle', 'left_foot'):
        pins[:, names.index(name)] = True
        targets[:, names.index(name), axis] += .04

    initialized, report = initialize_joint_plant_coordinates(
        rig, baseline, pins, targets, articulation_reference=source,
        fps=30., cyclic=False, deadline=monotonic() + 10.)

    assert initialized is not None, report
    result = rig.decode(initialized)
    assert np.max(np.linalg.norm((result - targets)[pins], axis=-1)) < 1e-5
    root_offset = initialized[:, :3] - baseline[:, :3]
    assert np.max(root_offset[:, axis]) > minimum_root_shift, axis_name
    assert support_initialization_articulation_regressions(source, result, names) == []
    assert report['root']['maxMagnitudeMeters'] <= .12
    np.testing.assert_allclose(
        report['root']['maxAbsCorrectionXYZMeters'],
        np.max(np.abs(root_offset), axis=0), atol=1e-12)


def test_joint_plant_fails_closed_when_two_contact_targets_force_new_foot_heading():
    from scipy.spatial.transform import Rotation

    names, source = _stance()
    rig = FixedRig(source, names)
    baseline = rig.initial.copy()
    points = rig.decode(baseline)
    pins = np.zeros(points.shape[:2], dtype=bool)
    targets = points.copy()
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    pins[:, [ankle, toe]] = True
    targets[:, toe] = (targets[:, ankle]
                       + Rotation.from_euler('y', 35., degrees=True).apply(
                           points[0, toe] - points[0, ankle]))

    initialized, report = initialize_joint_plant_coordinates(
        rig, baseline, pins, targets, articulation_reference=source,
        fps=30., cyclic=False, deadline=monotonic() + 10.)

    assert initialized is None
    assert report['reason'] == 'left_contact_target_changes_source_foot_pose'
    assert report['preflight']['left']['p95SourceHeadingDeltaDegrees'] > 15.


def test_contact_conditioned_reference_changes_only_mapped_full_sole_foot_vectors(monkeypatch):
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg import contact_constraints
    from exercise_motion_pkg.joint_plant_initialization import (
        contact_conditioned_articulation_reference,
    )

    names, source = _stance(8)
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    knee_i = names.index('left_knee')
    raw_vector = source[:, toe_i] - source[:, ankle_i]
    for frame, angle in enumerate(np.linspace(-25., 30., len(source))):
        source[frame, toe_i] = source[frame, ankle_i] + Rotation.from_euler(
            'x', angle, degrees=True).apply(raw_vector[0])

    pinned = np.zeros(source.shape[:2], dtype=bool)
    pinned[:3, [ankle_i, toe_i]] = True
    targets = source.copy()
    targets[:3, toe_i] = targets[:3, ankle_i] + raw_vector[0]
    evidence = {
        'footPatchEvidence': {
            'available': True,
            'feet': {'left': {'states': ['full_sole', 'full_sole', 'full_sole',
                                         'heel_only', 'airborne', 'unknown', 'unknown']}},
        },
    }
    mapped = np.asarray([0, 1, 2, 3, 4, 5, -1])
    monkeypatch.setattr(
        contact_constraints, 'mapped_foot_patch_state_indices',
        lambda _evidence, _times, count: np.pad(mapped, (0, count-len(mapped)),
                                                  constant_values=-1),
        raising=False,
    )
    conditioned, masks, evidence_masks, report = contact_conditioned_articulation_reference(
        source, pinned, targets, names, evidence, [index / 30. for index in range(8)])

    assert report['available'] is True
    np.testing.assert_array_equal(masks['left'], [True, True, True, False, False, False, False, False])
    np.testing.assert_array_equal(evidence_masks['left'],
                                  [True, True, True, True, True, True, False, False])
    np.testing.assert_allclose(conditioned[:, knee_i], source[:, knee_i], atol=0.)
    np.testing.assert_allclose(conditioned[:, ankle_i], source[:, ankle_i], atol=0.)
    np.testing.assert_allclose(conditioned[:3, toe_i] - conditioned[:3, ankle_i],
                               targets[:3, toe_i] - targets[:3, ankle_i], atol=1e-12)
    np.testing.assert_allclose(conditioned[3:, toe_i], source[3:, toe_i], atol=0.)
    assert support_initialization_articulation_regressions(
        conditioned, conditioned, names, ankle_excursion_masks=masks) == []
    from exercise_motion_pkg.joint_plant_initialization import _make_specs
    _, preflight = _make_specs(names, source, pinned, targets,
                               conditioned)
    assert preflight['feasible'] is True
    assert preflight['feet']['left']['p95SourcePitchDeltaDegrees'] < 1e-6


def test_joint_plant_uses_timed_source_foot_direction_only_on_authorized_owned_rows():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.joint_plant_initialization import _make_specs

    names, source = _stance(4)
    rig = FixedRig(source, names)
    points = rig.decode(rig.initial)
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    raw_vector = points[:, toe_i] - points[:, ankle_i]
    fixed_length = float(np.linalg.norm(raw_vector[0]))
    desired = np.zeros((len(points), 2, 3), dtype=float)
    desired[:, 0] = np.asarray([
        Rotation.from_euler('x', 5., degrees=True).apply(raw_vector[0] / fixed_length)
        for _ in range(len(points))
    ])
    desired[:, 1] = (points[:, names.index('right_foot')]
                     - points[:, names.index('right_ankle')])
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[0, toe_i] = True
    pinned[1, [ankle_i, toe_i]] = True
    pinned[3, ankle_i] = True
    targets = points.copy()
    targets[1, toe_i] = targets[1, ankle_i] + desired[1, 0] * fixed_length
    masks = {'left': np.array([True, True, False, True]),
             'right': np.zeros(len(points), dtype=bool)}

    specs, report = _make_specs(
        names, points, pinned, targets, source,
        desired_world_foot_directions=desired,
        pitch_authority_mask_by_side=masks)

    assert report['feasible'] is True, report
    spec = next(row for row in specs if row['side'] == 'left')
    np.testing.assert_allclose(
        spec['targetAnkle'][0], targets[0, toe_i] - desired[0, 0] * fixed_length)
    np.testing.assert_array_equal(spec['targetAnkle'][1], targets[1, ankle_i])
    np.testing.assert_array_equal(spec['targetToe'][1], targets[1, toe_i])
    np.testing.assert_allclose(
        spec['targetToe'][3], targets[3, ankle_i] + desired[3, 0] * fixed_length)
    np.testing.assert_array_equal(spec['targetAnkle'][2], points[2, ankle_i])
    np.testing.assert_array_equal(spec['targetToe'][2], points[2, toe_i])


def test_source_conditioned_reference_carries_geometry_without_adding_pins():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.joint_plant_initialization import (
        source_conditioned_foot_direction_reference,
    )

    names, source = _stance(4)
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    raw_vector = source[:, toe_i] - source[:, ankle_i]
    direction = Rotation.from_euler('x', 6., degrees=True).apply(raw_vector[0])
    directions = np.zeros((len(source), 2, 3), dtype=float)
    directions[:, 0] = direction / np.linalg.norm(direction)
    directions[:, 1] = source[:, names.index('right_foot')] - source[:, names.index('right_ankle')]
    pins = np.zeros(source.shape[:2], dtype=bool)
    pins[0, toe_i] = True
    pins[1, [ankle_i, toe_i]] = True
    pins[3, ankle_i] = True

    conditioned, counts = source_conditioned_foot_direction_reference(
        source, pins, names, directions,
        {'left': np.ones(len(source), dtype=bool),
         'right': np.ones(len(source), dtype=bool)},
    )

    assert counts == {'left': 4, 'right': 4}
    np.testing.assert_array_equal(conditioned[2, names.index('left_knee')],
                                  source[2, names.index('left_knee')])
    np.testing.assert_array_equal(conditioned[2, names.index('left_ankle')],
                                  source[2, names.index('left_ankle')])
    np.testing.assert_array_equal(conditioned[:, ankle_i], source[:, ankle_i])
    np.testing.assert_array_equal(conditioned[:, names.index('left_knee')],
                                  source[:, names.index('left_knee')])
    np.testing.assert_allclose(conditioned[:, toe_i] - conditioned[:, ankle_i],
                               directions[:, 0] * np.linalg.norm(raw_vector[0]),
                               atol=1e-12)


def test_source_patch_clock_does_not_map_crop_end_into_last_video_sample():
    from exercise_motion_pkg.contact_constraints import mapped_foot_patch_state_indices

    source_times = [index / 30. for index in range(96)]
    evidence = {'footPatchEvidence': {
        'available': True,
        'sourceTimeBasis': 'absolute_source_video',
        'sourceFps': 30.,
        'sourceTimesSec': source_times,
        'feet': {'left': {'states': ['full_sole'] * 96}},
    }}
    fit_times = [index / 30. for index in range(96)] + [96 / 30., 95.5 / 30.]

    mapped = mapped_foot_patch_state_indices(evidence, fit_times, len(fit_times))

    np.testing.assert_array_equal(mapped[:96], np.arange(96))
    assert mapped[96] == -1
    assert mapped[97] == -1


@pytest.mark.parametrize(('fullsole_toe_anchor', 'bridge_expected'), [
    ('toe-A', True), ('toe-B', False),
])
def test_contact_ownership_uses_both_source_endpoints_at_landing_and_release(
        fullsole_toe_anchor, bridge_expected):
    from exercise_motion_pkg.contact_constraints import _fit_local_timed_support_evidence
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    native_times = [index / 10. for index in range(5)]
    states = ['unknown', 'toe_only', 'full_sole', 'toe_only', 'airborne']

    def record(state, index, toe_anchor, ankle_anchor=None):
        return {
            'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
            'contactState': state, 'contactMotion': 'stationary',
            'surfaceKind': 'ground', 'verticalOnly': False,
            'startRatio': index / 4., 'endRatio': index / 4.,
            'anchorGroupId': toe_anchor, 'ankleAnchorGroupId': ankle_anchor,
        }

    evidence = {
        'footPatchEvidence': {
            'available': True, 'sourceTimeBasis': 'absolute_source_video',
            'sourceFps': 10., 'sourceTimesSec': native_times,
            'feet': {
                'left': {'states': states},
                'right': {'states': ['unknown'] * len(states)},
            },
        },
        'contacts': [
            record('toe_only', 1, 'toe-A'),
            record('full_sole', 2, fullsole_toe_anchor, 'ankle-A'),
            record('toe_only', 3, 'toe-A'),
        ],
    }
    fit_times = [index / 20. for index in range(9)]
    payload = {'frames': [{'sourceTimeSec': time} for time in fit_times]}
    timed = _fit_local_timed_support_evidence(payload, evidence)
    names = ['left_ankle', 'left_foot']
    pinned = contact_mask(payload, names, len(fit_times), support_evidence=timed)

    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    np.testing.assert_array_equal(pinned[:, ankle], [False, False, False, False,
                                                      True, False, False, False, False])
    assert pinned[1, toe] == False
    assert pinned[2, toe] == True
    assert pinned[3, toe] == bridge_expected
    assert pinned[4, toe] == True
    assert pinned[5, toe] == bridge_expected
    assert pinned[6, toe] == True
    assert pinned[7, toe] == False
    assert pinned[8, toe] == False

    for basis in ('local_source_video', None):
        unresolved = deepcopy(evidence)
        if basis is None:
            unresolved['footPatchEvidence'].pop('sourceTimeBasis')
        else:
            unresolved['footPatchEvidence']['sourceTimeBasis'] = basis
        unresolved_timed = _fit_local_timed_support_evidence(payload, unresolved)
        unresolved_pins = contact_mask(
            payload, names, len(fit_times), support_evidence=unresolved_timed)
        assert not np.any(unresolved_pins)

    mismatched = deepcopy(evidence)
    mismatched['footPatchEvidence']['feet']['right']['states'].pop()
    mismatched_timed = _fit_local_timed_support_evidence(payload, mismatched)
    mismatched_pins = contact_mask(
        payload, names, len(fit_times), support_evidence=mismatched_timed)
    assert not np.any(mismatched_pins)

    from exercise_motion_pkg.contact_constraints import _without_fit_local_timing_metadata
    support_only = deepcopy(evidence)
    support_only['supportContacts'] = support_only.pop('contacts')
    support_only_timed = _fit_local_timed_support_evidence(payload, support_only)
    assert 'contacts' not in support_only_timed
    assert _without_fit_local_timing_metadata(support_only_timed) == support_only


def test_unmapped_fullsole_mask_keeps_raw_ankle_excursion_guard():
    names, source = _stance(100)
    knee, ankle, toe = (names.index(f'left_{part}') for part in ('knee', 'ankle', 'foot'))
    vector = source[0, toe] - source[0, ankle]
    shank = source[50, knee] - source[50, ankle]
    shank /= np.linalg.norm(shank)
    perpendicular = vector - shank * np.dot(vector, shank)
    perpendicular /= np.linalg.norm(perpendicular)
    length = np.linalg.norm(vector)
    source[50, toe] = source[50, ankle] + length * (
        shank * np.cos(np.deg2rad(140.)) + perpendicular * np.sin(np.deg2rad(140.)))
    candidate = source.copy()
    candidate[50, toe] = candidate[50, ankle] + vector

    regressions = support_initialization_articulation_regressions(
        source, candidate, names,
        ankle_excursion_masks={'left': np.zeros(len(source), dtype=bool)},
    )

    assert any(item['feature'] == 'left_ankle_raw_contact_state_episode_excursion'
               and item['preservedRatio'] < .85 for item in regressions)


def test_mixed_fullsole_and_raw_contact_states_guard_each_episode():
    names, source = _stance(100)
    knee, ankle, toe = (names.index(f'left_{part}') for part in ('knee', 'ankle', 'foot'))
    vector = source[0, toe] - source[0, ankle]
    shank = source[75, knee] - source[75, ankle]
    shank /= np.linalg.norm(shank)
    perpendicular = vector - shank * np.dot(shank, vector)
    perpendicular /= np.linalg.norm(perpendicular)
    length = np.linalg.norm(vector)
    source[75, toe] = source[75, ankle] + length * (
        shank * np.cos(np.deg2rad(140.)) + perpendicular * np.sin(np.deg2rad(140.)))
    candidate = source.copy()
    candidate[75, toe] = candidate[75, ankle] + vector
    full_sole = np.zeros(len(source), dtype=bool)
    full_sole[:50] = True

    regressions = support_initialization_articulation_regressions(
        source, candidate, names,
        ankle_excursion_masks={'left': full_sole},
        ankle_evidence_masks={'left': np.ones(len(source), dtype=bool)},
    )

    assert any(item['feature'] == 'left_ankle_raw_contact_state_episode_excursion'
               and item['startFrame'] == 50 and item['endFrame'] == 99
               for item in regressions)
    from exercise_motion_pkg.controlled_motion import supported_ankle_episode_range_ratios
    ratios, episodes = supported_ankle_episode_range_ratios(
        source, candidate, names, {'left': full_sole},
        {'left': np.ones(len(source), dtype=bool)},
    )
    assert ratios['left_ankle'] < .85
    assert episodes['left_ankle'][0]['authority'] == 'raw_contact_state'


@pytest.mark.parametrize('cyclic', [False, True])
def test_joint_plant_smooths_root_across_contact_release(cyclic):
    names, source = _stance()
    rig = FixedRig(source, names)
    baseline = rig.initial.copy()
    points = rig.decode(baseline)
    pins = np.zeros(points.shape[:2], dtype=bool)
    targets = points.copy()
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    pins[3:9, [ankle, toe]] = True
    targets[3:9, [ankle, toe], 0] += .04

    initialized, report = initialize_joint_plant_coordinates(
        rig, baseline, pins, targets, articulation_reference=source,
        fps=30., cyclic=cyclic, deadline=monotonic() + 10.)

    assert initialized is not None, report
    result = rig.decode(initialized)
    assert np.max(np.linalg.norm((result - targets)[pins], axis=-1)) < 1e-5
    assert report['root']['cyclic'] is cyclic
    assert report['root']['maxStepMeters'] < .01
    assert report['root']['maxSecondDifferenceMeters'] < .003


def test_joint_plant_preserves_registered_vertical_excursion_during_contact_release():
    names, source = _stance()
    lift = np.array([0., 0., 0., .04, .08, .10, .08, .04, 0., 0., 0., 0.])
    source[:, :, 1] += lift[:, None]
    rig = FixedRig(source, names)
    baseline = rig.initial.copy()
    points = rig.decode(baseline)
    pins = np.zeros(points.shape[:2], dtype=bool)
    targets = points.copy()
    contact_frames = np.r_[0:3, 8:12]
    pins[np.ix_(contact_frames, [names.index('left_ankle'), names.index('left_foot')])] = True
    targets[contact_frames[:, None], [names.index('left_ankle'), names.index('left_foot')], 0] += .04

    initialized, report = initialize_joint_plant_coordinates(
        rig, baseline, pins, targets, articulation_reference=source,
        fps=30., cyclic=False, deadline=monotonic() + 10.)

    assert initialized is not None, report
    result = rig.decode(initialized)
    root = names.index('pelvis')
    assert np.ptp(source[:, root, 1]) >= .099
    assert np.ptp(result[:, root, 1]) >= .095
    np.testing.assert_allclose(result[:, root, 1], source[:, root, 1], atol=.005)
    assert np.max(np.linalg.norm((result - targets)[pins], axis=-1)) < 1e-5


def test_joint_plant_deadline_leaves_input_and_rig_unchanged():
    names, source = _stance()
    rig = FixedRig(source, names)
    baseline = rig.initial.copy()
    original_rig = rig.initial.copy()
    points = rig.decode(baseline)
    pins = np.zeros(points.shape[:2], dtype=bool)
    pins[:, [names.index('left_ankle'), names.index('left_foot')]] = True

    with pytest.raises(TimeoutError):
        initialize_joint_plant_coordinates(
            rig, baseline, pins, points, articulation_reference=source,
            fps=30., cyclic=False, deadline=monotonic() - 1.)

    np.testing.assert_array_equal(baseline, original_rig)
    np.testing.assert_array_equal(rig.initial, original_rig)
