import numpy as np
import pytest

from exercise_motion_pkg import contact_heel_pitch
from exercise_motion_pkg.foot_geometry import SHOE_LENGTH_RATIO


def test_native_heel_pitch_inversion_preserves_measured_events_with_fullsole_constraints(monkeypatch):
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
        for frame_index, toe_x in ((1, .02), (2, .04), (3, .02)):
            points[frame_index, toe, 0] += toe_x
            points[frame_index, toe, 2] = np.sqrt(.2 ** 2 - toe_x ** 2)
    contact_targets = points.copy()
    for side in ('left', 'right'):
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        contact_targets[:, toe] = contact_targets[:, ankle] + np.array([.2, 0., 0.])
    monkeypatch.setattr(contact_heel_pitch, 'decode_rig', lambda _rig, _coordinates: points.copy())
    rig = {'jointNames': names, 'coordinates': np.zeros((count, 3))}
    payload = {'footRestPitchRadians': {'left': 0., 'right': 0.}}
    lift = .04
    event = {
        'leftFrame': 1, 'rightFrame': 2, 'alpha': 0., 'sourceTime': 1.,
        'sourceSide': 'right', 'motionSide': 'left',
        'sourceHeelToToeVector': np.array([0., lift]),
        'baselineSourceVector': np.array([0., 0.]),
        'baselineFitVector': np.array([0., 0.]),
        'liftDirection': np.array([0., 1.]),
    }
    source_observations = [
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
        'sourceFootHeelImageObservations': source_observations,
    }
    pinned = np.zeros((count, len(names)), dtype=bool)
    left_ankle, left_toe = names.index('left_ankle'), names.index('left_foot')
    pinned[[0, 4], left_ankle] = True
    pinned[[0, 4], left_toe] = True

    directions, report = contact_heel_pitch.propose_source_heel_pitch(
        rig, np.zeros((count, 3)), payload, constraint, pinned, 30.,
        contact_targets=contact_targets)

    assert report['passed'] is True
    assert report['eventCount'] == 1
    expected = -np.arcsin(lift / (SHOE_LENGTH_RATIO * .2))
    assert report['inversionDetails'][0]['pitchDeltaDegrees'] == pytest.approx(
        np.rad2deg(expected), abs=1e-6)
    assert directions.shape == (count, 2, 3)
    # Full-sole pins are exact zero-delta constraints, and the native toe-only
    # observation retains its measured time and pitch amplitude.
    np.testing.assert_allclose(directions[[0, 4], 0, 1], 0., atol=1e-12)
    np.testing.assert_allclose(directions[[0, 4], 0, 0], 1., atol=1e-12)
    np.testing.assert_allclose(directions[[0, 4], 0, 2], 0., atol=1e-12)
    assert directions[1, 0, 1] < 0.
    # The stance target supplies a constant yaw baseline, but source heading
    # changes remain visible during the toe-only event.
    expected_yaw = np.pi / 2. + np.arctan2(points[2, left_toe, 0]
                                           - points[2, left_ankle, 0],
                                           points[2, left_toe, 2]
                                           - points[2, left_ankle, 2])
    assert np.arctan2(directions[2, 0, 0], directions[2, 0, 2]) == pytest.approx(
        expected_yaw, abs=1e-6)
    assert report['sides']['left']['fullSoleDirichletFrameCount'] == 2

    stale_baseline = {
        **constraint,
        'footGeometryPayload': {'footRestPitchRadians': {'left': .1, 'right': 0.}},
    }
    _, stale_report = contact_heel_pitch.propose_source_heel_pitch(
        rig, np.zeros((count, 3)), payload, stale_baseline, pinned, 30.,
        contact_targets=contact_targets)
    assert stale_report['passed'] is False
    assert stale_report['reason'] == 'material_baseline_rest_pitch_context_mismatch'
    assert stale_report['baselinePitchContextErrorsBySide']['left'][
        'selectedRestPitchRadians'] == pytest.approx(0.)


def test_source_timed_pitch_does_not_bridge_unmeasured_unknown_gap():
    observations = [
        {'sourceTime': 0., 'leftFrame': 0, 'alpha': 0., 'state': 'full_sole',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
        {'sourceTime': 1., 'leftFrame': 1, 'alpha': 0., 'state': 'toe_only',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
        {'sourceTime': 2., 'leftFrame': 2, 'alpha': 0., 'state': 'unknown',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
        {'sourceTime': 3., 'leftFrame': 3, 'alpha': 0., 'state': 'unknown',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
        {'sourceTime': 4., 'leftFrame': 4, 'alpha': 0., 'state': 'toe_only',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
        {'sourceTime': 5., 'leftFrame': 5, 'alpha': 0., 'state': 'full_sole',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'b'},
        {'sourceTime': 6., 'leftFrame': 6, 'alpha': 0., 'state': 'heel_only',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'b'},
    ]
    event_pitches = [
        ({'sourceSide': 'left', 'motionSide': 'left', 'sourceTime': 1.}, -.2),
        ({'sourceSide': 'left', 'motionSide': 'left', 'sourceTime': 4.}, -.8),
    ]
    result, authority, trajectory, report = contact_heel_pitch._shape_preserving_source_pitch(
        {'sourceFootHeelImageObservations': observations},
        frame_count=7, side='left', fullsole_frame_mask=np.zeros(7, dtype=bool),
        event_pitches=event_pitches, frame_times=np.arange(7, dtype=float), fps=1.)

    assert result[0] == pytest.approx(0.)
    assert result[1] == pytest.approx(-.2)
    assert result[2] == pytest.approx(0.)
    assert result[3] == pytest.approx(0.)
    assert result[4] == pytest.approx(-.8)
    assert authority[[0, 1, 4, 5]].all()
    assert not authority[2] and not authority[3]  # no inferred contact/pitch authority
    assert not authority[6]  # heel-only evidence blocks authority
    assert trajectory[[0, 1, 4, 5]].all()
    assert not trajectory[2] and not trajectory[3]
    assert not trajectory[6]
    assert report['unresolvedObservationCount'] == 3


def test_measured_unknown_heel_geometry_drives_direction_without_contact_labels():
    observations = [
        {'sourceTime': 0., 'leftFrame': 0, 'alpha': 0., 'state': 'full_sole',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
        {'sourceTime': 1., 'leftFrame': 1, 'alpha': 0., 'state': 'unknown',
         'motionSide': 'left', 'sourceSide': 'left'},
        {'sourceTime': 2., 'leftFrame': 2, 'alpha': 0., 'state': 'unknown',
         'motionSide': 'left', 'sourceSide': 'left'},
        {'sourceTime': 3., 'leftFrame': 3, 'alpha': 0., 'state': 'toe_only',
         'motionSide': 'left', 'sourceSide': 'left', 'stationaryAnchorGroupId': 'a'},
    ]
    event_pitches = [
        ({'sourceSide': 'left', 'motionSide': 'left', 'sourceTime': 3.}, -.3),
    ]
    geometry_pitches = [
        ({'sourceSide': 'left', 'motionSide': 'left', 'sourceTime': 1.,
          'stationaryAnchorGroupId': 'a'}, -.025),
        ({'sourceSide': 'left', 'motionSide': 'left', 'sourceTime': 2.,
          'stationaryAnchorGroupId': 'a'}, -.075),
    ]
    result, authority, trajectory, report = contact_heel_pitch._shape_preserving_source_pitch(
        {'sourceFootHeelImageObservations': observations},
        frame_count=4, side='left', fullsole_frame_mask=np.array([True, False, False, False]),
        event_pitches=event_pitches, geometry_pitches=geometry_pitches,
        frame_times=np.arange(4, dtype=float), fps=1.)

    np.testing.assert_allclose(result, [0., -.025, -.075, -.3], atol=1e-12)
    assert authority[[0, 1, 2, 3]].all()  # measured direction only
    assert trajectory.all()
    assert report['unresolvedObservationCount'] == 0


def test_unknown_small_positive_lift_is_not_dead_zoned_to_stance(monkeypatch):
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot',
             'right_hip', 'right_knee', 'right_ankle', 'right_foot']
    points = np.zeros((4, len(names), 3), dtype=float)
    for side in ('left', 'right'):
        points[:, names.index(f'{side}_ankle')] = [0., 0., 0.]
        points[:, names.index(f'{side}_foot')] = [0., 0., .2]
    monkeypatch.setattr(
        'exercise_motion_pkg.foot_geometry.sample_material_foot_points',
        lambda _payload, cursors, *, points=None: {
            'left': {'heel': np.zeros((len(cursors), 3)),
                     'toe': np.zeros((len(cursors), 3))},
            'right': {'heel': np.zeros((len(cursors), 3)),
                      'toe': np.zeros((len(cursors), 3))},
        })
    image_rows = [
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'full_sole',
         'sourceTime': 0., 'leftFrame': 0, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance', 'sourceHeelToToeVector': [0., 0.],
         'confidenceWeight': .95, 'sourceNoiseImageUnits': .002},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'unknown',
         'sourceTime': 1., 'leftFrame': 1, 'alpha': 0.,
         'sourceHeelToToeVector': [0., -.0001], 'confidenceWeight': .95},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'unknown',
         'sourceTime': 2., 'leftFrame': 2, 'alpha': 0.,
         'sourceHeelToToeVector': [0., .0001], 'confidenceWeight': .95},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'unknown',
         'sourceTime': 3., 'leftFrame': 3, 'alpha': 0.,
         'sourceHeelToToeVector': [0., .02], 'confidenceWeight': .95},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'toe_only',
         'sourceTime': 4., 'leftFrame': 3, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance',
         'sourceHeelToToeVector': [0., 0.], 'confidenceWeight': .95},
    ]
    calibration_rows = [
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'full_sole',
         'sourceTime': time, 'leftFrame': 0, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance', 'sourceHeelToToeVector': [0., 0.]}
        for time in (0., .1, .2)
    ]
    pitch_rows, failures, report = contact_heel_pitch._measured_unknown_heel_pitches(
        {'sourceFootHeelImageObservations': image_rows,
         'sourceFootHeelCalibrationObservations': calibration_rows,
         'footGeometryPayload': {'sourcePoseCameraReference': {
             'sourcePose': {'imageHeight': 500}}}},
        points, names, np.array([[1., 0., 0.], [0., 1., 0.]]))

    assert not failures
    assert report['resolvedUnknownGeometryCount'] == 3
    # A small positive lift lies below the 0.002-unit calibration noise, but a
    # valid inversion remains direction evidence and is preserved. Only the
    # invalid tiny-negative no-heel-up root falls back to neutral.
    assert pitch_rows[0][1] == pytest.approx(0.)
    assert pitch_rows[1][1] < 0.
    assert abs(pitch_rows[1][1]) > 0.
    assert pitch_rows[2][1] < pitch_rows[1][1]
    assert abs(pitch_rows[2][1]) > .05  # native fast rise remains in source time


def _stationary_unknown_heel_case(
    monkeypatch, *, toe_offset=0., ray_time_shift=0., baseline=True, native_pitch=0.,
):
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot',
             'right_hip', 'right_knee', 'right_ankle', 'right_foot']
    points = np.zeros((4, len(names), 3), dtype=float)
    for side in ('left', 'right'):
        points[:, names.index(f'{side}_ankle')] = [0., 0., 0.]
        points[:, names.index(f'{side}_foot')] = [
            0., .2 * np.sin(native_pitch), .2 * np.cos(native_pitch)]
    monkeypatch.setattr(
        'exercise_motion_pkg.foot_geometry.sample_material_foot_points',
        lambda _payload, cursors, *, points=None: {
            'left': {'heel': np.zeros((len(cursors), 3)),
                     'toe': np.zeros((len(cursors), 3))},
            'right': {'heel': np.zeros((len(cursors), 3)),
                      'toe': np.zeros((len(cursors), 3))},
        })
    image_rows = [
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'full_sole',
         'sourceTime': 0., 'leftFrame': 0, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance', 'sourceHeelToToeVector': [0., 0.],
         'confidenceWeight': .95, 'sourceNoiseImageUnits': .005},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'unknown',
         'sourceTime': .2, 'leftFrame': 1, 'alpha': 0.,
         'sourceHeelToToeVector': [0., .001],
         'confidenceWeight': .95, 'sourceNoiseImageUnits': .005},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'toe_only',
         'sourceTime': .25, 'leftFrame': 2, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance', 'sourceHeelToToeVector': [0., .02],
         'confidenceWeight': .95, 'sourceNoiseImageUnits': .005},
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'full_sole',
         'sourceTime': .3, 'leftFrame': 3, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance', 'sourceHeelToToeVector': [0., 0.],
         'confidenceWeight': .95, 'sourceNoiseImageUnits': .005},
    ]
    calibration_rows = ([
        {'sourceSide': 'left', 'motionSide': 'left', 'state': 'full_sole',
         'sourceTime': time, 'leftFrame': 0, 'alpha': 0.,
         'stationaryAnchorGroupId': 'stance', 'sourceHeelToToeVector': [0., 0.]}
        for time in (0., .01, .02)
    ] if baseline else [])
    ray_rows = []
    ray_rows.append({
        'sourceSide': 'left', 'motionSide': 'left', 'state': 'unknown',
        'sourceTime': .2, 'toeImagePoint': [.50015 + toe_offset, .6],
        'confidenceWeight': .95,
    })
    for time, x in ((.1, .5), (.15, .5001), (.25, .5002), (.3, .5003)):
        ray_rows.append({
            'sourceSide': 'left', 'motionSide': 'left', 'state': 'toe_only',
            'sourceTime': time + ray_time_shift, 'toeImagePoint': [x, .6],
            'confidenceWeight': .95, 'stationaryAnchorGroupId': 'stance',
        })
    constraint = {
        'sourceFootHeelImageObservations': image_rows,
        'sourceFootHeelCalibrationObservations': calibration_rows,
        'sourceFootRayObservations': ray_rows,
        'footGeometryPayload': {'sourcePoseCameraReference': {
            'sourcePose': {'imageWidth': 854, 'imageHeight': 480}}},
    }
    result = contact_heel_pitch._measured_unknown_heel_pitches(
        constraint, points, names, np.array([[1., 0., 0.], [0., 1., 0.]]))
    return result


def test_unknown_heel_direction_uses_stationary_same_anchor_toe_without_contact(monkeypatch):
    pitch_rows, failures, report = _stationary_unknown_heel_case(monkeypatch)

    assert not failures
    assert len(pitch_rows) == 1
    row, target = pitch_rows[0]
    assert target == pytest.approx(0.)
    assert row['state'] == 'unknown'
    assert row['directionOnlyNeutralWithinNoise'] is True
    evidence = row['toeStationarityEvidence']
    assert evidence['contactResolved'] is False
    assert evidence['toeDisplacementPixels'] < evidence['calibratedSameAnchorJitterP95Pixels']
    assert report['resolvedUnknownDirectionOnlyCount'] == 1


@pytest.mark.parametrize('case', [
    'moved_toe', 'outside_cadence', 'missing_baseline',
])
def test_unknown_heel_direction_stays_unresolved_without_its_evidence(monkeypatch, case):
    kwargs = {
        'toe_offset': .02 if case == 'moved_toe' else 0.,
        'ray_time_shift': 1. if case == 'outside_cadence' else 0.,
        'baseline': case != 'missing_baseline',
        'native_pitch': 0.,
    }
    pitch_rows, _failures, report = _stationary_unknown_heel_case(monkeypatch, **kwargs)

    assert pitch_rows == []
    assert report['resolvedUnknownDirectionOnlyCount'] == 0


def test_inconsistent_native_pitch_uses_measured_neutral_baseline_not_raw_orientation(monkeypatch):
    pitch_rows, failures, report = _stationary_unknown_heel_case(
        monkeypatch, native_pitch=-.4)

    assert not failures
    assert len(pitch_rows) == 1
    row, target = pitch_rows[0]
    assert target == pytest.approx(0.)
    assert row['directionOnlyNeutralWithinNoise'] is True
    assert row['nativePitchMatchesSourceImage'] is False
    assert row['toeStationarityEvidence']['contactResolved'] is False
    assert report['resolvedUnknownDirectionOnlyCount'] == 1


def test_source_pitch_authority_never_exceeds_mapped_trajectory():
    # The observation's source clock is closer to fit frame 0, while its
    # retained cursor points at frame 1. The singleton cannot be mapped within
    # the frame's half-step clock tolerance, so it must not authorize contact.
    observation = {
        'sourceTime': .4, 'leftFrame': 1, 'alpha': 0., 'state': 'toe_only',
        'motionSide': 'right', 'sourceSide': 'right',
        'stationaryAnchorGroupId': 'stance',
    }
    event = ({'sourceSide': 'right', 'motionSide': 'right', 'sourceTime': .4}, -.2)
    _, authority, trajectory, _ = contact_heel_pitch._shape_preserving_source_pitch(
        {'sourceFootHeelImageObservations': [observation]},
        frame_count=3, side='right', fullsole_frame_mask=np.zeros(3, dtype=bool),
        event_pitches=[event], frame_times=np.arange(3, dtype=float), fps=1.)

    assert not trajectory.any()
    assert not authority.any()
    assert np.all(~authority | trajectory)
