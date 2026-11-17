"""Focused ownership regressions for observed full-sole Lunge contacts.

The physical sole state is owned by the observed foot patch. Exact XYZ point
ownership is separate: a full-sole foot contact pins the foot, while an
explicit ankle contact (or ankle restraint) owns the ankle.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg import contact_heel_pitch
from exercise_motion_pkg.controlled_motion import apply_canonical_stance_targets
from exercise_motion_pkg.joint_plant_initialization import (
    contact_conditioned_articulation_reference,
)
from exercise_motion_pkg.rig_playback import rig_contact_targets
from exercise_motion_pkg.sequence_stabilization import contact_mask


NAMES = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']


def _stance(count=6):
    points = np.zeros((count, len(NAMES), 3), dtype=float)
    for side, x in (('left', -.2), ('right', .2)):
        ankle, toe = NAMES.index(f'{side}_ankle'), NAMES.index(f'{side}_foot')
        points[:, ankle] = [x, 0., 0.]
        points[:, toe] = [x, 0., .2]
    return points


def test_retained_lunge_fixture_keeps_foot_and_ankle_pin_ownership_separate():
    fixture = json.loads(
        (Path(__file__).parent / 'fixtures'
         / 'fixture_lunge_contact_ownership.json').read_text(encoding='utf-8'))
    names = list(fixture['jointNames'])
    count = int(fixture['frameCount'])
    payload = {'jointNames': names, 'frames': [{} for _ in range(count)]}
    pins = contact_mask(payload, names, count,
                        support_evidence=fixture['supportEvidence'])
    actual = {joint: [frame for frame in range(count) if pins[frame, names.index(joint)]]
              for joint in names if pins[:, names.index(joint)].any()}
    expected = {joint: list(frames)
                for joint, frames in fixture['expectedV3Pins'].items() if frames}
    assert actual == expected
    for joint, frames in fixture['unknownContactFrames'].items():
        assert not set(actual.get(joint, [])) & set(frames)


def test_full_sole_foot_pins_foot_but_explicit_ankle_restraint_pins_ankle():
    payload = {'sourceFootSupportEvidence': {'contacts': [
        {'jointName': 'left_foot', 'contactState': 'full_sole',
         'contactMotion': 'stationary', 'startFrame': 2, 'endFrame': 5},
        {'jointName': 'right_ankle',
         'supportKind': 'observed_stationary_ankle_restraint',
         'contactMotion': 'stationary', 'verticalOnly': False,
         'surfaceKind': 'fixed_bar', 'startFrame': 0, 'endFrame': 4,
         '_fitFrameBounds': [0, 4], '_fitFrameCount': 8},
    ]}}
    mask = contact_mask(payload, NAMES, 8,
                        support_evidence=payload['sourceFootSupportEvidence'])
    assert mask[2:6, NAMES.index('left_foot')].all()
    assert not mask[:, NAMES.index('left_ankle')].any()
    assert mask[:5, NAMES.index('right_ankle')].all()
    assert not mask[:, NAMES.index('right_foot')].any()


def test_articulation_reference_consumes_full_sole_foot_ownership():
    source = _stance(6)
    names = NAMES
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    pinned = np.zeros(source.shape[:2], dtype=bool)
    pinned[:, toe_i] = True
    targets = source.copy()
    targets[:, toe_i] += np.array([0., .03, 0.])
    evidence = {
        'footPatchEvidence': {
            'available': True,
            'feet': {'left': {'states': ['full_sole'] * len(source)}},
        },
        '_fitFrameFootPatchStatesBySide': {
            'left': ['full_sole'] * len(source),
            'right': ['unknown'] * len(source),
        },
    }
    conditioned, masks, _observed, report = contact_conditioned_articulation_reference(
        source, pinned, targets, names, evidence,
        [index / 30. for index in range(len(source))],
    )
    np.testing.assert_array_equal(masks['left'],
                                  np.ones(len(source), dtype=bool))
    np.testing.assert_allclose(conditioned[:, ankle_i], source[:, ankle_i], atol=0.)
    np.testing.assert_allclose(
        conditioned[:, toe_i] - conditioned[:, ankle_i],
        targets[:, toe_i] - targets[:, ankle_i], atol=1e-12)
    assert report['sides']['left']['mappedFullSoleFrameCount'] == len(source)


def test_source_heel_pitch_uses_observed_full_sole_state_not_ankle_pin(monkeypatch):
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot',
             'right_hip', 'right_knee', 'right_ankle', 'right_foot']
    count = 5
    points = np.zeros((count, len(names), 3), dtype=float)
    for side, x in (('left', -.2), ('right', .2)):
        hip, knee, ankle, toe = [names.index(f'{side}_{part}')
                                 for part in ('hip', 'knee', 'ankle', 'foot')]
        points[:, hip] = [x, 1.2, 0.]
        points[:, knee] = [x + .3, .6, 0.]
        points[:, ankle] = [x, 0., 0.]
        points[:, toe] = [x, 0., .2]
    contact_targets = points.copy()
    for side in ('left', 'right'):
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        contact_targets[:, toe] = contact_targets[:, ankle] + np.array([.2, 0., 0.])
    monkeypatch.setattr(contact_heel_pitch, 'decode_rig',
                        lambda _rig, _coordinates: points.copy())
    rig = {'jointNames': names, 'coordinates': np.zeros((count, 3))}
    payload = {'footRestPitchRadians': {'left': 0., 'right': 0.}}
    event = {
        'leftFrame': 1, 'rightFrame': 2, 'alpha': 0., 'sourceTime': 1.,
        'sourceSide': 'right', 'motionSide': 'left',
        'sourceHeelToToeVector': np.array([0., .04]),
        'baselineSourceVector': np.array([0., 0.]),
        'baselineFitVector': np.array([0., 0.]),
        'liftDirection': np.array([0., 1.]),
    }
    observations = [
        {'leftFrame': 0, 'rightFrame': 0, 'alpha': 0., 'sourceTime': 0.,
         'sourceSide': 'right', 'motionSide': 'left', 'state': 'full_sole',
         'confidenceWeight': 1., 'stationaryAnchorGroupId': 'stance'},
        {'leftFrame': 1, 'rightFrame': 2, 'alpha': 0., 'sourceTime': 1.,
         'sourceSide': 'right', 'motionSide': 'left', 'state': 'toe_only',
         'confidenceWeight': 1., 'stationaryAnchorGroupId': 'stance'},
        {'leftFrame': 4, 'rightFrame': 4, 'alpha': 0., 'sourceTime': 4.,
         'sourceSide': 'right', 'motionSide': 'left', 'state': 'full_sole',
         'confidenceWeight': 1., 'stationaryAnchorGroupId': 'stance'},
    ]
    constraint = {
        'projection': np.array([[1., 0., 0.], [0., 1., 0.]]),
        'sourceFootHeelTrajectoryObservations': [event],
        'sourceFootHeelImageObservations': observations,
    }
    pinned = np.zeros((count, len(names)), dtype=bool)
    left_toe = names.index('left_foot')
    pinned[[0, 4], left_toe] = True
    directions, report = contact_heel_pitch.propose_source_heel_pitch(
        rig, np.zeros((count, 3)), payload, constraint, pinned, 30.,
        contact_targets=contact_targets)
    assert report['sides']['left']['fullSoleDirichletFrameCount'] == 2
    np.testing.assert_allclose(directions[[0, 4], 0, 1], 0., atol=1e-12)
    np.testing.assert_allclose(directions[[0, 4], 0, 0], 1., atol=1e-12)
    np.testing.assert_allclose(directions[[0, 4], 0, 2], 0., atol=1e-12)


def test_anatomical_inverse_suppresses_only_unowned_full_sole_ankle_anchor(monkeypatch):
    captured = []

    def geometry(ankle, toe, direction, marker, rest, scale, floor, **kwargs):
        captured.append(kwargs)
        return {'vector': np.zeros(3), 'virtualClearance': np.zeros(3),
                'vertices': np.zeros((4, 3)), 'ankle': ankle, 'toe': toe}

    monkeypatch.setattr(contact_heel_pitch, 'anatomical_marker_foot_geometry', geometry)
    points = np.asarray([[
        [0., 0., 0.], [0., 0., .2], [.2, 0., 0.], [.2, 0., .2],
    ]])
    names = NAMES
    rows = [{
        'leftFrame': 0, 'rightFrame': 0, 'alpha': 0., 'sourceTime': 0.,
        'motionSide': 'left', 'state': 'full_sole',
        'anatomicalMarkerLocalVector': [0., 0., -.05],
        'sourceHeelToToeVector': [0., 0.], 'sourceNoiseImageUnits': .001,
    }]
    constraint = {'projection': [[1., 0., 0.], [0., 1., 0.]],
                  'sourceTimeOriginSec': 0.,
                  'sourceFootHeelImageObservations': rows}
    widened_pins = np.ones(points.shape[:2], dtype=bool)

    def payload(contacts):
        return {
            'footRestPitchRadians': {'left': 0., 'right': 0.},
            'sourcePoseCameraReference': {'sourcePose': {'imageHeight': 360.}},
            'frames': [{'sourceTimeSec': 0.}],
            'renderFloorY': None,
            'sourceFootSupportEvidence': {'contacts': contacts},
        }

    full_sole_foot = [{
        'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
        'contactState': 'full_sole', 'contactMotion': 'stationary',
        'startFrame': 0, 'endFrame': 0,
    }]
    contact_heel_pitch._propose_anatomical_heel_pitch(
        points, names, payload(full_sole_foot), constraint, 30., None,
        pinned=widened_pins)
    assert captured and all(call['ankle_anchor'] is None for call in captured)

    captured.clear()
    explicit_ankle = full_sole_foot + [{
        'jointName': 'left_ankle',
        'supportKind': 'observed_stationary_ankle_restraint',
        'contactMotion': 'stationary', 'verticalOnly': False,
        'startFrame': 0, 'endFrame': 0,
        '_fitFrameBounds': [0, 0], '_fitFrameCount': 1,
    }]
    contact_heel_pitch._propose_anatomical_heel_pitch(
        points, names, payload(explicit_ankle), constraint, 30., None,
        pinned=widened_pins)
    assert captured and all(call['ankle_anchor'] is not None for call in captured)


def test_contact_targets_derive_ankle_from_full_sole_foot_ownership():
    count = 8
    names = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    points = np.zeros((count, len(names), 3), dtype=float)
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    points[:, ankle] = [0., 0., 0.]
    points[:, toe] = [0., 0., .2]
    points[:, toe, 1] = np.linspace(-.025, .015, count)
    offsets = np.zeros((len(names), 3), dtype=float)
    offsets[toe] = points[0, toe] - points[0, ankle]
    offsets[names.index('right_foot')] = np.array([0., 0., .2])
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, toe] = True
    evidence = {
        'footPatchEvidence': {
            'available': True,
            'feet': {'left': {'states': ['full_sole'] * count}},
        },
        '_fitFrameStateIndices': list(range(count)),
    }
    rest_pitch = -.30
    targets, _ = rig_contact_targets(
        points, names, pinned, offsets, evidence=evidence,
        rest_pitches={'left': rest_pitch})
    vector = targets[:, toe] - targets[:, ankle]
    pitch = np.arcsin(vector[:, 1] / np.linalg.norm(vector, axis=1))
    np.testing.assert_allclose(pitch, rest_pitch, atol=1e-12)
    np.testing.assert_allclose(
        np.linalg.norm(vector, axis=1), np.linalg.norm(offsets[toe]),
        atol=1e-12)


def test_canonical_stance_targets_shift_ankle_with_full_sole_foot_ownership():
    source = _stance(4)
    targets = source.copy()
    targets[:, NAMES.index('left_foot'), 1] = .04
    pinned = np.zeros(source.shape[:2], dtype=bool)
    pinned[:, NAMES.index('left_foot')] = True
    payload = {
        'canonicalExecution': {'stance': 'stationary_bilateral'},
        'renderFloorY': 0.,
        'frames': [{'sourceTimeSec': index / 30.} for index in range(len(source))],
        'sourceFootSupportEvidence': {
            'footPatchEvidence': {
                'available': True,
                    'sourceTimeBasis': 'absolute_source_video',
                    'sourceFps': 30.,
                    'sourceTimesSec': [index / 30. for index in range(len(source))],
                'feet': {'left': {'states': ['full_sole'] * len(source)}},
            },
            'contacts': [{
                'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
                'contactState': 'full_sole', 'contactMotion': 'stationary',
                'startFrame': 0, 'endFrame': len(source) - 1,
            }],
        },
    }
    result = apply_canonical_stance_targets(payload, targets, NAMES, pinned)
    ankle, toe = NAMES.index('left_ankle'), NAMES.index('left_foot')
    toe_shift = result[:, toe] - targets[:, toe]
    np.testing.assert_allclose(result[:, ankle] - targets[:, ankle], toe_shift,
                               atol=1e-12)
