import json
from copy import deepcopy
from pathlib import Path
from time import monotonic

import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import FixedRig, support_initialization_articulation_regressions
from exercise_motion_pkg import joint_plant_initialization
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


def test_joint_plant_leaves_unknown_and_unowned_leg_frames_as_source_pose():
    names, source = _stance(3)
    rig = FixedRig(source, names)
    baseline = rig.initial.copy()
    points = rig.decode(baseline)
    pins = np.zeros(points.shape[:2], dtype=bool)
    targets = points.copy()
    left_ankle, left_toe = names.index('left_ankle'), names.index('left_foot')
    pins[:2, [left_ankle, left_toe]] = True
    targets[:2, [left_ankle, left_toe], 0] += .04

    initialized, report = initialize_joint_plant_coordinates(
        rig, baseline, pins, targets, articulation_reference=source,
        fps=30., cyclic=False, deadline=monotonic() + 10.)

    assert initialized is not None, report
    result = rig.decode(initialized)
    # With no owned contacts the initializer may carry the temporally smooth
    # common-root track, but it must retain the source articulation exactly.
    np.testing.assert_allclose(initialized[2, 3:], baseline[2, 3:], atol=1e-8)
    root = result[:, names.index('pelvis')]
    for name in ('right_hip', 'right_knee', 'right_ankle', 'right_foot'):
        index = names.index(name)
        np.testing.assert_allclose(result[:2, index] - root[:2],
                                   points[:2, index] - points[:2, names.index('pelvis')],
                                   atol=1e-8)
    assert np.max(np.linalg.norm((result - targets)[pins], axis=-1)) < 1e-5


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
    np.testing.assert_allclose(spec['targetToe'][2] - spec['targetAnkle'][2],
                               points[2, toe_i] - points[2, ankle_i])


def test_joint_plant_accepts_material_floor_calibration_for_one_side_only():
    from exercise_motion_pkg.joint_plant_initialization import _make_specs

    names, source = _stance(4)
    pins = np.zeros(source.shape[:2], dtype=bool)
    pins[0, names.index('left_ankle')] = True
    axes = np.zeros((len(source), 2, 3), dtype=float)
    axes[..., 2] = 1.

    specs, report = _make_specs(
        names, source, pins, source.copy(), source,
        floor_y=-10., rest_pitch_radians={'left': 0.}, foot_scale=.1,
        side_axis_by_side=axes)

    assert report['feasible'] is True
    assert [spec['side'] for spec in specs] == ['left']
    assert report['feet']['left']['materialFloorCorrection']['frameCount'] == 0


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

    conditioned, counts, _details = source_conditioned_foot_direction_reference(
        source, pins, names, directions,
        {'left': np.ones(len(source), dtype=bool),
         'right': np.ones(len(source), dtype=bool)},
        source_reference=source, frame_times=np.arange(len(source), dtype=float),
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


def test_source_direction_calibration_correction_transports_through_free_frames():
    from exercise_motion_pkg.joint_plant_initialization import (
        source_conditioned_foot_direction_reference,
    )

    names, source = _stance(3)
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')
    for frame, pitch_degrees in enumerate((0., 3., 9.)):
        source[frame, toe_i] = source[frame, ankle_i] + np.array([
            0., np.sin(np.deg2rad(pitch_degrees)), np.cos(np.deg2rad(pitch_degrees))]) * .2
    source_pitch = []
    for frame in range(len(source)):
        bone = source[frame, toe_i] - source[frame, ankle_i]
        source_pitch.append(np.arctan2(bone[1], np.linalg.norm(bone[[0, 2]])))
    directions = np.zeros((len(source), 2, 3), dtype=float)
    directions[:, 0] = np.array([0., 0., 1.])
    directions[:, 1] = source[:, names.index('right_foot')] - source[:, names.index('right_ankle')]
    correction = np.deg2rad(8.)
    for frame in (0, 2):
        pitch = source_pitch[frame] + correction
        directions[frame, 0] = [0., np.sin(pitch), np.cos(pitch)]
    pins = np.zeros(source.shape[:2], dtype=bool)

    conditioned, counts, details = source_conditioned_foot_direction_reference(
        source, pins, names, directions,
        {'left': np.array([True, False, True]), 'right': np.zeros(3, dtype=bool)},
        source_reference=source, frame_times=[0., .02, .1])

    target_pitch = []
    for frame in range(len(source)):
        bone = conditioned[frame, toe_i] - conditioned[frame, ankle_i]
        target_pitch.append(np.arctan2(bone[1], np.linalg.norm(bone[[0, 2]])))
    np.testing.assert_allclose(np.asarray(target_pitch), np.asarray(source_pitch) + correction,
                               atol=1e-10)
    np.testing.assert_allclose(np.diff(target_pitch), np.diff(source_pitch), atol=1e-10)
    assert counts == {'left': 2, 'right': 0}
    assert details['left']['transportedFrameCount'] == 1
    assert details['left']['pitchCorrectionRangeDegrees'] == pytest.approx([8., 8.])


def test_source_direction_transport_needs_clock_only_for_measured_trajectory():
    from exercise_motion_pkg.joint_plant_initialization import (
        source_conditioned_foot_direction_reference,
    )

    names, source = _stance(3)
    directions = np.zeros((len(source), 2, 3), dtype=float)
    pins = np.zeros(source.shape[:2], dtype=bool)
    masks = {'left': np.zeros(len(source), dtype=bool),
             'right': np.zeros(len(source), dtype=bool)}

    unchanged, counts, details = source_conditioned_foot_direction_reference(
        source, pins, names, directions, masks,
        source_reference=source, frame_times=[None] * len(source),
    )

    np.testing.assert_array_equal(unchanged, source)
    assert counts == {'left': 0, 'right': 0}
    assert details == {
        'left': {'trajectoryFrameCount': 0, 'transportedFrameCount': 0},
        'right': {'trajectoryFrameCount': 0, 'transportedFrameCount': 0},
    }
    masks['left'][0] = True
    with pytest.raises(ValueError, match='clock must be finite and strictly increasing'):
        source_conditioned_foot_direction_reference(
            source, pins, names, directions, masks,
            source_reference=source, frame_times=[None] * len(source),
        )


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


@pytest.mark.parametrize('last_state', ['full_sole', 'unknown'])
@pytest.mark.parametrize('origin', [0., 10.])
def test_source_patch_clock_maps_only_inside_verified_last_frame_exposure(last_state, origin):
    from exercise_motion_pkg.contact_constraints import mapped_foot_patch_state_indices

    source_times = [origin + index / 25. for index in range(84)]
    states = ['full_sole'] * 83 + [last_state]
    evidence = {'footPatchEvidence': {
        'available': True,
        'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': origin,
        'sourceFrameCount': 84,
        'sourceFps': 25.,
        'sourceVideoDurationSec': 84 / 25.,
        'sourceTimesSec': source_times,
        'feet': {'left': {'states': states}},
    }}
    fit_times = [origin + 3.32, origin + 3.3333333333333335, origin + 3.36]

    mapped = mapped_foot_patch_state_indices(evidence, fit_times, len(fit_times))

    np.testing.assert_array_equal(mapped, [83, 83, -1])
    # Mapping preserves explicit state identity: the final frame can be mapped
    # without promoting an explicitly unknown observation into contact.
    if last_state == 'unknown':
        assert states[mapped[1]] == 'unknown'


def test_patch_observation_metadata_records_exclusive_video_duration():
    from exercise_motion_pkg.foot_contact_observation import _patch_source_timing_metadata

    timing = _patch_source_timing_metadata(
        [{'timeSeconds': index / 25.} for index in range(84)], 10., 25.)

    assert timing['sourceEndTimeSec'] == pytest.approx(13.32)
    assert timing['sourceVideoDurationSec'] == pytest.approx(3.36)


def test_patch_clock_rejects_disagreeing_media_duration_and_frame_count():
    from exercise_motion_pkg.contact_constraints import mapped_foot_patch_state_indices

    source_times = [index / 25. for index in range(84)]
    evidence = {'footPatchEvidence': {
        'available': True, 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceFrameCount': 84, 'sourceFps': 25.,
        'sourceVideoDurationSec': 3.4, 'sourceTimesSec': source_times,
        'feet': {'left': {'states': ['full_sole'] * 84}},
    }}

    mapped = mapped_foot_patch_state_indices(evidence, [3.32, 3.3333333333], 2)

    np.testing.assert_array_equal(mapped, [-1, -1])


def test_selected_cut_support_maps_parent_clock_once_and_fails_closed_on_hash_mismatch():
    from exercise_motion_pkg.contact_constraints import (
        _fit_local_timed_support_evidence,
        mapped_foot_patch_state_indices,
    )
    from exercise_motion_pkg.controlled_motion import source_foot_patch_clock_failure

    selected_sha, parent_sha = 'a' * 64, 'b' * 64
    selected_lineage = [
        {'selectedFrameIndex': index, 'selectedFrameTimeSec': index / 30.,
         'parentSourceFrameIndex': 60 + index,
         'parentSourceTimeSec': 2. + index / 30.}
        for index in range(4)
    ]
    mapping = {
        'schemaVersion': 1,
        'verified': True,
        'mappingKind': 'selected_segment_to_parent_source',
        'selectedSegmentSha256': selected_sha,
        'parentSourceSha256': parent_sha,
        'selectedStartSeconds': 2.0,
        'selectedFrameClockReceiptSha256': 'd' * 64,
        'parentSourceFps': 30.,
        'selectedFrameLineage': selected_lineage,
    }
    patch_times = [index / 30. for index in range(4)]
    states = ['unknown', 'full_sole', 'full_sole', 'airborne']
    evidence = {
        'sourceVideoSha256': selected_sha,
        'contacts': [{
            'jointName': 'left_foot',
            'supportKind': 'observed_foot_patch',
            'contactState': 'full_sole',
            'startRatio': 1 / 3,
            'endRatio': 2 / 3,
            'anchorGroupId': 'toe-1',
            'ankleAnchorGroupId': 'ankle-1',
        }, {
            'jointName': 'left_ankle',
            'anchorKind': 'ankle',
            'sourceTimeBasis': 'absolute_source_video',
            'sourcePoseStartTimeSec': patch_times[1],
            'sourcePoseEndTimeSec': patch_times[2],
        }],
        'footPatchEvidence': {
            'available': True,
            'sourceVideoSha256': selected_sha,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceFps': 30.,
            'sourceTimesSec': patch_times,
            'feet': {'left': {'states': states}, 'right': {'states': ['unknown'] * 4}},
        },
    }
    fit_times = [2.0 + value for value in patch_times]
    payload = {
        'frames': [{'sourceTimeSec': value} for value in fit_times],
        'sourceFootSupportEvidence': evidence,
        'sourcePoseCameraReference': {'sourceTimelineMapping': mapping},
    }

    mapped = mapped_foot_patch_state_indices(
        evidence, fit_times, len(fit_times), source_timeline_mapping=mapping)
    np.testing.assert_array_equal(mapped, [0, 1, 2, 3])
    timed = _fit_local_timed_support_evidence(payload, evidence)
    assert timed['contacts'][0]['_fitFrameRuns'] == [[1, 2]]
    assert timed['contacts'][1]['_fitFrameRuns'] == [[1, 2]]
    assert source_foot_patch_clock_failure(payload) is None

    parent_clock_evidence = deepcopy(evidence)
    parent_clock_evidence['sourceVideoSha256'] = parent_sha
    parent_patch = parent_clock_evidence['footPatchEvidence']
    parent_patch['sourceVideoSha256'] = parent_sha
    parent_patch['sourceTimesSec'] = [2.0 + value for value in patch_times]
    parent_clock_mapped = mapped_foot_patch_state_indices(
        parent_clock_evidence,
        fit_times,
        len(fit_times),
        source_timeline_mapping=mapping,
    )
    np.testing.assert_array_equal(parent_clock_mapped, [0, 1, 2, 3])

    mismatched = deepcopy(payload)
    mismatched['sourceFootSupportEvidence']['footPatchEvidence'][
        'sourceVideoSha256'] = 'c' * 64
    mismatched['sourceFootSupportEvidence']['sourceVideoSha256'] = 'c' * 64
    mismatch_evidence = mismatched['sourceFootSupportEvidence']
    unresolved = mapped_foot_patch_state_indices(
        mismatch_evidence, fit_times, len(fit_times), source_timeline_mapping=mapping)
    np.testing.assert_array_equal(unresolved, [-1, -1, -1, -1])
    mismatch_timed = _fit_local_timed_support_evidence(mismatched, mismatch_evidence)
    assert mismatch_timed['contacts'][0]['_fitFrameRuns'] == []
    assert mismatch_timed['contacts'][1]['_fitFrameRuns'] == []
    assert source_foot_patch_clock_failure(mismatched)['reason'] == \
        'source_foot_patch_clock_unmapped'

    malformed_mapping = deepcopy(payload)
    malformed_mapping['sourcePoseCameraReference']['sourceTimelineMapping'] = 'verified'
    malformed = _fit_local_timed_support_evidence(
        malformed_mapping, malformed_mapping['sourceFootSupportEvidence'])
    assert malformed['_fitFrameStateIndices'] == [-1, -1, -1, -1]
    assert source_foot_patch_clock_failure(malformed_mapping)['reason'] == \
        'source_foot_patch_clock_unmapped'


def test_fit_clock_rematerializes_exact_contact_and_only_resolves_unknown_patch_state():
    from exercise_motion_pkg.contact_constraints import _fit_local_timed_support_evidence
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    digest = '7' * 64
    timeline = {
        'schemaVersion': 1, 'policyVersion': 1,
        'source': 'exact_source_visual_contact_timeline',
        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
        'status': 'observed', 'requestSha256': 'request', 'responseSha256': 'response',
        'samples': [
            {'sampleId': 'left-first-exposure', 'sourceTimeSec': 0.,
             'sourceFrameIndex': 0, 'sourceFps': 30., 'sourcePoseFrameIndex': 0,
             'side': 'left', 'contactState': 'full_sole', 'surface': 'ground',
             'visible': True, 'sourceTrackStationary': True},
            {'sampleId': 'left-conflicting-exposure', 'sourceTimeSec': 1. / 30.,
             'sourceFrameIndex': 1, 'sourceFps': 30., 'sourcePoseFrameIndex': 1,
             'side': 'left', 'contactState': 'full_sole', 'surface': 'ground',
             'visible': True, 'sourceTrackStationary': True},
        ],
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'sourceVideoSha256': digest, 'contactTimeline': timeline,
        },
        'footPatchEvidence': {
            'available': True, 'sourceVideoSha256': digest,
            'sourceTimeBasis': 'absolute_source_video', 'sourceFps': 30.,
            'sourceTimesSec': [index / 30. for index in range(4)],
            'feet': {
                'left': {'states': ['unknown', 'airborne', 'full_sole', 'full_sole']},
                'right': {'states': ['unknown'] * 4},
            },
        },
        'contacts': [{
            'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
            'contactState': 'full_sole', 'contactMotion': 'stationary',
            'surfaceKind': 'ground', 'verticalOnly': False,
            'startRatio': 2. / 3., 'endRatio': 1.,
            'anchorGroupId': 'left-toe', 'ankleAnchorGroupId': 'left-ankle',
        }],
    }
    names, points = _stance(4)
    payload = {
        'frames': [{'sourceTimeSec': index / 30.} for index in range(4)],
        'jointNames': names,
    }

    timed = _fit_local_timed_support_evidence(payload, evidence)
    exact = [contact for contact in timed['supportContacts']
             if contact.get('supportKind') == 'exact_timed_visual_contact']
    assert [contact['contactTimelineSampleId'] for contact in exact] == [
        'left-first-exposure', 'left-conflicting-exposure']
    assert exact[0]['_fitFrameBounds'] == [0, 0]
    assert exact[1]['_fitFrameBounds'] is None
    assert timed['_fitFrameFootPatchStatesBySide']['left'] == [
        'full_sole', 'unknown', 'full_sole', 'full_sole']
    assert timed['_fitTimedContactStateConflicts'] == [{
        'side': 'left', 'frameIndex': 1, 'nativeState': 'airborne',
        'timelineStates': ['full_sole'],
    }]

    pinned = contact_mask(payload, payload['jointNames'], 4, support_evidence=timed)
    left_ankle = payload['jointNames'].index('left_ankle')
    left_foot = payload['jointNames'].index('left_foot')
    np.testing.assert_array_equal(pinned[:, left_ankle], [True, False, True, True])
    np.testing.assert_array_equal(pinned[:, left_foot], [True, False, True, True])

    from exercise_motion_pkg.joint_plant_initialization import (
        contact_conditioned_articulation_reference,
    )
    conditioned, masks, _observed, report = contact_conditioned_articulation_reference(
        points, pinned, points.copy(), payload['jointNames'], timed,
        [frame['sourceTimeSec'] for frame in payload['frames']],
    )
    assert masks['left'].tolist() == [True, False, True, True]
    assert report['sides']['left']['mappedFullSoleFrameCount'] == 3
    np.testing.assert_array_equal(conditioned[1:], points[1:])

    from exercise_motion_pkg.foot_geometry import calibrated_foot_rest_pitches
    fitted_pitch = calibrated_foot_rest_pitches(
        points, payload['jointNames'], timed,
        frame_times=[frame['sourceTimeSec'] for frame in payload['frames']],
    )
    ankle, toe = names.index('left_ankle'), names.index('left_foot')
    vectors = points[[0, 2, 3], toe] - points[[0, 2, 3], ankle]
    expected_pitch = np.median(np.arcsin(
        np.clip(vectors[:, 1] / np.linalg.norm(vectors, axis=1), -1., 1.)))
    assert fitted_pitch['left'] == pytest.approx(expected_pitch)


def test_selected_cut_exposure_lineage_uses_decoded_frame_not_requested_start():
    from exercise_motion_pkg.contact_constraints import mapped_foot_patch_state_indices

    selected_sha, parent_sha = 'e' * 64, 'f' * 64
    fps = 30000. / 1001.
    mapping = {
        'schemaVersion': 1, 'verified': True,
        'mappingKind': 'selected_segment_to_parent_source',
        'selectedSegmentSha256': selected_sha, 'parentSourceSha256': parent_sha,
        'selectedStartSeconds': 7.01,
        'selectedFrameClockReceiptSha256': '1' * 64,
        'parentSourceFps': fps,
        'selectedFrameLineage': [
            {'selectedFrameIndex': index, 'selectedFrameTimeSec': index / fps,
             'parentSourceFrameIndex': 211 + index,
             'parentSourceTimeSec': (211 + index) / fps}
            for index in range(3)
        ],
    }
    evidence = {
        'sourceVideoSha256': selected_sha,
        'footPatchEvidence': {
            'sourceVideoSha256': selected_sha,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceFps': fps,
            'sourceTimesSec': [0., 1. / fps, 2. / fps],
            'feet': {'left': {'states': ['airborne', 'full_sole', 'airborne']}},
        },
    }
    fit_times = [210. / fps, 211. / fps, 212. / fps]
    mapped = mapped_foot_patch_state_indices(
        evidence, fit_times, len(fit_times), source_timeline_mapping=mapping)
    np.testing.assert_array_equal(mapped, [-1, 0, 1])

    # A start-only legacy mapping cannot authorize a selected-cut contact.
    stale_mapping = {key: value for key, value in mapping.items()
                     if key not in {'selectedFrameClockReceiptSha256',
                                    'parentSourceFps', 'selectedFrameLineage'}}
    unresolved = mapped_foot_patch_state_indices(
        evidence, fit_times, len(fit_times), source_timeline_mapping=stale_mapping)
    np.testing.assert_array_equal(unresolved, [-1, -1, -1])


def test_selected_clock_duplicate_parent_exposures_keep_only_consistent_contacts():
    from exercise_motion_pkg.contact_constraints import _fit_local_timed_support_evidence

    selected_sha, parent_sha = '2' * 64, '3' * 64
    output_fps, parent_fps = 30., 24.
    parent_indexes = [0, 1, 2, 2, 3, 4]
    mapping = {
        'schemaVersion': 1, 'verified': True,
        'mappingKind': 'selected_segment_to_parent_source',
        'selectedSegmentSha256': selected_sha, 'parentSourceSha256': parent_sha,
        'selectedStartSeconds': 0., 'selectedFrameClockReceiptSha256': '4' * 64,
        'parentSourceFps': parent_fps,
        'selectedFrameLineage': [
            {'selectedFrameIndex': index, 'selectedFrameTimeSec': index / output_fps,
             'parentSourceFrameIndex': parent_index,
             'parentSourceTimeSec': parent_index / parent_fps}
            for index, parent_index in enumerate(parent_indexes)
        ],
    }

    def mapped_support(duplicate_states):
        evidence = {
            'sourceVideoSha256': selected_sha,
            'footPatchEvidence': {
                'available': True, 'sourceVideoSha256': selected_sha,
                'sourceTimeBasis': 'absolute_source_video',
                'sourceTimeOriginSec': 0., 'sourceFrameCount': 6,
                'sourceVideoDurationSec': 6. / output_fps,
                'sourceFps': output_fps,
                'sourceTimesSec': [index / output_fps for index in range(6)],
                'feet': {'left': {'states': ['unknown', 'full_sole', *duplicate_states,
                                              'airborne', 'airborne']},
                         'right': {'states': ['unknown'] * 6}},
            },
            'contacts': [{
                'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
                'contactState': 'full_sole', 'startRatio': .2, 'endRatio': .6,
                'anchorGroupId': 'toe-A', 'ankleAnchorGroupId': 'ankle-A',
            }],
        }
        fit_times = [index / parent_fps for index in range(5)]
        payload = {
            'frames': [{'sourceTimeSec': time} for time in fit_times],
            'sourceFootSupportEvidence': evidence,
            'sourcePoseCameraReference': {'sourceTimelineMapping': mapping},
        }
        return _fit_local_timed_support_evidence(payload, evidence)

    consistent = mapped_support(['full_sole', 'full_sole'])
    assert consistent['_fitFrameStateIndices'] == [0, 1, 2, 4, 5]
    assert consistent['contacts'][0]['_fitFrameRuns'] == [[1, 2]]

    conflicting = mapped_support(['full_sole', 'airborne'])
    assert conflicting['_fitFrameStateIndices'] == [0, 1, -1, 4, 5]
    assert conflicting['contacts'][0]['_fitFrameRuns'] == [[1, 1]]


def test_selected_cut_mapping_does_not_allow_clockless_equal_length_fallback():
    from exercise_motion_pkg.contact_constraints import mapped_foot_patch_state_indices

    evidence = {'sourceVideoSha256': 'c' * 64, 'footPatchEvidence': {
        'available': True,
        'feet': {'left': {'states': ['full_sole'] * 3}},
    }}
    mapping = {
        'schemaVersion': 1, 'verified': True,
        'mappingKind': 'selected_segment_to_parent_source',
        'selectedSegmentSha256': 'a' * 64,
        'parentSourceSha256': 'b' * 64,
        'selectedStartSeconds': 2.0,
    }
    mapped = mapped_foot_patch_state_indices(
        evidence, [None] * 3, 3, source_timeline_mapping=mapping)
    np.testing.assert_array_equal(mapped, [-1, -1, -1])


@pytest.mark.parametrize('invalid_count', [84.5, True])
def test_patch_clock_rejects_nonintegral_or_boolean_frame_count(invalid_count):
    from exercise_motion_pkg.contact_constraints import mapped_foot_patch_state_indices

    source_times = [index / 25. for index in range(84)]
    evidence = {'footPatchEvidence': {
        'available': True, 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceFrameCount': invalid_count, 'sourceFps': 25.,
        'sourceVideoDurationSec': 84 / 25., 'sourceTimesSec': source_times,
        'feet': {'left': {'states': ['full_sole'] * 84}},
    }}

    mapped = mapped_foot_patch_state_indices(evidence, [3.32, 3.3333333333], 2)

    np.testing.assert_array_equal(mapped, [-1, -1])


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


def test_root_track_keeps_feasible_seed_when_smoothing_projection_fails(monkeypatch):
    count = 5
    required_x = np.array([0., .06, 0., 0., 0.])
    spec = {
        'rootSeed': np.zeros((count, 3)),
        'kneeTolerance': .1,
        'ankleTolerance': .1,
        'targetAnkle': np.zeros((count, 3)),
        'targetToe': np.zeros((count, 3)),
        'ankle': np.zeros((count, 3)),
        'toe': np.zeros((count, 3)),
    }

    def frame_state(_specs, frame, translation):
        return np.array([translation[0] - required_x[frame], 1.]), None

    calls = 0

    def fail_smoothing_projection(_fun, x0, **_kwargs):
        nonlocal calls
        calls += 1
        # The first call is the per-frame feasibility solve. Later calls are
        # the smoothing projection and deliberately return its infeasible seed.
        result = np.asarray([.061, 0., 0.]) if calls == 1 else np.asarray(x0)
        return type('Result', (), {'x': result, 'success': calls == 1})()

    monkeypatch.setattr(joint_plant_initialization, '_frame_state', frame_state)
    monkeypatch.setattr(joint_plant_initialization, 'minimize', fail_smoothing_projection)

    translations, report = joint_plant_initialization._root_track(
        [spec], count, monotonic() + 5., cyclic=False, fps=30.)

    assert translations is not None, report
    margins = np.asarray([
        frame_state([spec], frame, translations[frame])[0]
        for frame in range(count)
    ])
    assert np.min(margins) >= 0.
    assert translations[1, 0] >= required_x[1]
    assert report['rejectedSmoothingProjectionCount'] > 0
    assert report['minimumRejectedSmoothingProjectionMarginDegrees'] < 0.
    assert report['perFrameFeasibleSeedMinimumMarginDegrees'] >= 0.


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
