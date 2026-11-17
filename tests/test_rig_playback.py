import json
from pathlib import Path
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.rig_playback import decode_rig, sample_rig, validate_rig_playback


def rig_payload(count=30):
    fixture=json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names=list(fixture['joints']);points=np.tile(np.array(list(fixture['joints'].values())),(count,1,1))
    rig=FixedRig(points,names)
    data={'jointNames':names,'parents':rig.parents,'order':rig.order,'offsets':rig.offsets.tolist(),
          'rotationJointNames':[names[j] for j in rig.active],'coordinates':rig.initial.tolist()}
    return data


def export(rig):
    points=decode_rig(rig,rig['coordinates'])
    return {'fps':30.,'jointNames':rig['jointNames'],'fixedRig':rig,'loop':{'enabled':True},
            'frames':[{'timeSec':i/30.,'joints':dict(zip(rig['jointNames'],p.tolist()))} for i,p in enumerate(points)]}


@pytest.mark.parametrize(('end_ratio', 'foot_state', 'anchor_changes', 'ready'), [
    (1., 'stationary_full_sole', False, True),
    (.25, 'stationary_full_sole', False, False),
    (.25, 'moving', False, True),
    (1., 'stationary_full_sole', True, False),
])
def test_playback_requires_coverage_of_the_claimed_stationary_stance(end_ratio, foot_state, anchor_changes, ready):
    payload = export(rig_payload(12))
    from exercise_motion_pkg.body_support_observation import (
        CONTACT_TIMELINE_POLICY_VERSION, POLICY_VERSION,
    )
    digest = 'a' * 64
    stationary_count = (12 if end_ratio == 1. else 4) if foot_state.startswith('stationary') else 0
    payload['sourceFootSupportEvidence'] = {
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
            'observation': {'leftFoot': foot_state, 'leftFootSurface': 'ground',
                            'leftFootContactContinuity': 'continuous'},
            'contactTimeline': {
                'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceClock': 'video_frame_zero_seconds', 'status': 'observed',
                'sourceVideoSha256': digest,
                'samples': [{
                    'sampleId': f'left-{frame}', 'sourceTimeSec': frame / 30.,
                    'sourceFrameIndex': frame, 'sourcePoseFrameIndex': frame, 'sourceFps': 30.,
                    'side': 'left', 'contactState': 'full_sole', 'surface': 'ground',
                    'visible': True, 'sourceTrackStationary': True,
                } for frame in range(stationary_count)],
            },
        },
        'contacts': [{
            'jointName': 'left_foot', 'contactState': 'full_sole',
            'contactMotion': 'stationary', 'source': 'observed_heel_and_forefoot',
            'startRatio': 0., 'endRatio': end_ratio,
        }],
    }
    if anchor_changes:
        contact = payload['sourceFootSupportEvidence']['contacts'][0]
        payload['sourceFootSupportEvidence']['contacts'] = [
            {**contact, 'endRatio': 5 / 11, 'anchorGroupId': 'before'},
            {**contact, 'startRatio': 6 / 11, 'anchorGroupId': 'after'},
        ]
    report = validate_rig_playback(payload)
    readiness = report['supportContactReadiness']
    assert readiness['passed'] is ready
    if foot_state.startswith('stationary'):
        assert readiness['stationaryContactCoverage']['left'] == {
            'coveredFrames': 12 if end_ratio == 1. else 4, 'requiredFrames': 12,
        }
    if not ready:
        assert report['passed'] is False
        assert report['maximumContactErrorMeters'] < .003


def test_final_loop_gate_uses_playback_velocity_even_when_endpoints_coincide():
    from exercise_motion_pkg.bake_and_rank import compute_loop_bridge_quality_metrics_from_payload

    rig = rig_payload(12)
    stable = export(rig)
    assert not compute_loop_bridge_quality_metrics_from_payload(stable)['severeLoopMismatch']
    coordinates = np.asarray(rig['coordinates'])
    coordinates[1, 0] += .02
    rig['coordinates'] = coordinates.tolist()
    hitch = export(rig)
    metrics = compute_loop_bridge_quality_metrics_from_payload(hitch)
    playback = validate_rig_playback(hitch)
    assert metrics['endpointMaxDistance'] == 0.
    assert metrics['severeLoopMismatch']
    assert not playback['seamContinuous']
    for key, value in metrics['playbackSeam'].items():
        assert value == pytest.approx(playback[key])
    # Legacy exports retain their existing diagnostic without claiming rig authority.
    hitch.pop('fixedRig')
    assert compute_loop_bridge_quality_metrics_from_payload(hitch)['playbackSeam'] is None


def test_final_seam_uses_rendered_derivative_when_sample_proxy_flags_a_smooth_wrap():
    rig = rig_payload(4)
    rig['interpolation'] = 'limited_quaternion_hermite_v2'
    values = np.asarray(rig['coordinates'])
    values[:, 0] += [0., .01, .02, .01]
    rig['coordinates'] = values.tolist()
    report = validate_rig_playback(export(rig))
    assert report['seamVelocityMismatchMetersPerSecond'] > report['seamVelocityMismatchLimitMetersPerSecond']
    assert report['seamStepExcessMeters'] < report['seamStepExcessLimitMeters']
    assert report['seamProxyContinuous'] is False
    assert report['seamRenderedVelocityJumpMetersPerSecond'] < report['seamRenderedVelocityJumpLimitMetersPerSecond']
    from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump
    expected = frame_boundary_velocity_jump(
        lambda cursors: sample_rig(rig, cursors, wrap=True), [0], 30.)
    assert report['seamRenderedVelocityJumpMetersPerSecond'] == pytest.approx(expected)
    assert report['seamVerdictSource'] == 'rendered_interpolation'
    assert report['seamContinuous'] and report['passed'], report


def test_rendered_seam_check_keeps_interior_knot_velocity_validation(monkeypatch):
    from exercise_motion_pkg import rig_interpolation

    rig = rig_payload(8)
    rig['interpolation'] = 'limited_quaternion_hermite_v2'
    payload = export(rig)
    payload['fixedRig']['interpolation'] = 'limited_quaternion_hermite_v2'
    monkeypatch.setattr(
        rig_interpolation, 'frame_boundary_velocity_jump',
        lambda _sample, knots, _fps: 0. if len(knots) == 1 else 1.)
    report = validate_rig_playback(payload)
    assert report['seamContinuous']
    assert not report['velocityContinuous']
    assert not report['passed']


def test_default_linear_interpolation_measures_wrap_velocity_and_rejects_a_hitch():
    stable = export(rig_payload(12))
    stable_report = validate_rig_playback(stable)
    assert stable_report['seamRenderedVelocityJumpMetersPerSecond'] < 1e-8
    assert stable_report['seamContinuous']

    rig = rig_payload(12)
    coordinates = np.asarray(rig['coordinates'])
    coordinates[1, 0] += .02
    rig['coordinates'] = coordinates.tolist()
    report = validate_rig_playback(export(rig))
    assert report['seamVerdictSource'] == 'rendered_interpolation'
    assert report['seamRenderedVelocityJumpMetersPerSecond'] > report['seamRenderedVelocityJumpLimitMetersPerSecond']
    assert not report['seamContinuous']


@pytest.mark.parametrize('displacement, acceptable', [(.008, True), (.2, False)])
def test_rendered_seam_uses_actual_motion_quality_for_bridge(displacement, acceptable):
    from copy import deepcopy
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload

    rig = rig_payload(12)
    rig['interpolation'] = 'limited_quaternion_hermite_v2'
    values = np.asarray(rig['coordinates'])
    values[:, 0] += np.linspace(0., displacement, len(values))
    rig['coordinates'] = values.tolist()
    payload = export(rig)
    payload['fixedRig']['interpolation'] = 'limited_quaternion_hermite_v2'
    report = validate_rig_playback(payload)
    assert report['seamRenderedVelocityJumpMetersPerSecond'] < report['seamRenderedVelocityJumpLimitMetersPerSecond']
    assert report['seamStepExcessMeters'] > report['seamStepExcessLimitMeters']
    assert report['seamContinuous'] is acceptable
    assert report['loopMotionDiscontinuity']['rootContinuity']['passed'] is acceptable
    assert report['passed']  # Body playback is valid; the loop policy owns seam rejection.
    for frame in payload['frames']:
        frame['controlledSourceJoints'] = deepcopy(frame['joints'])
        frame['controlledArticulationReferenceJoints'] = deepcopy(frame['joints'])
    final = physical_metrics_from_payload(payload)
    assert ('unsafe_loop_transition' in final['reasons']) is not acceptable
    from exercise_motion_pkg.bake_and_rank import contact_correction_loop_continuity_metrics
    correction = contact_correction_loop_continuity_metrics(
        'Movement', {'requiresReturnToStart': True}, baseline_seam_joint_rms=0.,
        corrected_seam_joint_rms=displacement, corrected_payload=payload)
    assert correction['preservesLoopContinuity'] is acceptable


def test_grounded_toe_recalibrates_overlapping_ankle_before_fitting():
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    rig = rig_payload(12)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    original = points.copy()
    ankle, foot = (names.index('right_'+part) for part in ('ankle', 'foot'))
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, foot] = True
    pinned[3:8, ankle] = True
    grounded = points[0, foot] + [0., -.08, 0.]
    targets, _ = rig_contact_targets(points, names, pinned, rig['offsets'],
                                     stationary_positions={'right_foot': grounded})
    np.testing.assert_allclose(targets[:, foot], np.tile(grounded, (12, 1)))
    np.testing.assert_allclose(np.linalg.norm(targets[3:8, ankle]-targets[3:8, foot], axis=1),
                               np.linalg.norm(rig['offsets'][foot]))
    np.testing.assert_array_equal(points, original)
    np.testing.assert_array_equal(targets[:3, ankle], points[:3, ankle])
    # Playback reconstructs exactly the same anchors from the exported reference.
    reference = points.copy()
    reference[:, foot] = grounded
    playback, _ = rig_contact_targets(reference, names, pinned, rig['offsets'])
    np.testing.assert_allclose(playback, targets)


def test_materialized_body_support_moves_pinned_ankle_toe_as_pair_to_forefoot_plane():
    from exercise_motion_pkg.rig_playback import rig_contact_targets

    rig = rig_payload(8)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, toe = (names.index(f'right_{part}') for part in ('ankle', 'foot'))
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [ankle, toe]] = True
    plane_y = .13
    evidence = {'bodySupport': {
        'soleContacts': [{'joints': ['right_knee', 'right_ankle', 'right_foot'],
                          'normal': [0., 1., 0.]}],
        'coplanarGroups': [{'joints': ['right_foot'], 'normal': [0., 1., 0.],
                            'planeOffsetMeters': plane_y}],
    }}

    targets, _ = rig_contact_targets(points, names, pinned, np.asarray(rig['offsets']),
                                     evidence=evidence)
    source_vector = points[:, toe] - points[:, ankle]
    target_vector = targets[:, toe] - targets[:, ankle]
    np.testing.assert_allclose(targets[:, toe, 1], plane_y, atol=1e-12)
    np.testing.assert_allclose(target_vector, source_vector, atol=1e-12)


def test_contact_targets_keep_unnamed_continuous_ankle_stationary_across_toe_episodes():
    from exercise_motion_pkg.rig_playback import rig_contact_targets

    rig = rig_payload(12)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, toe = (names.index(f'left_{part}') for part in ('ankle', 'foot'))
    points[0, toe, 0] -= .01
    points[-1, toe, 0] += .01
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, ankle] = True
    pinned[[0, -1], toe] = True

    targets, _ = rig_contact_targets(points, names, pinned, np.asarray(rig['offsets']))
    np.testing.assert_allclose(targets[:, ankle], np.tile(targets[0, ankle], (12, 1)), atol=1e-10)
    np.testing.assert_allclose(
        np.linalg.norm(targets[[0, -1], toe] - targets[[0, -1], ankle], axis=1),
        np.linalg.norm(rig['offsets'][toe]), atol=1e-8)
    np.testing.assert_array_equal(targets[~pinned], points[~pinned])


def test_contact_targets_use_calibrated_material_pitch_only_on_mapped_full_sole_rows():
    from exercise_motion_pkg.contact_constraints import motion_space_support_evidence
    from exercise_motion_pkg.rig_playback import rig_contact_targets

    rig = rig_payload(8)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, toe = (names.index(f'right_{part}') for part in ('ankle', 'foot'))
    # Make the source pair's aggregate pitch differ from the neutral material pitch.
    points[:, toe, 1] += np.linspace(-.025, .015, len(points))
    patch = {
        'available': True, 'sourceTimeBasis': 'absolute_source_video', 'sourceFps': 30.,
        'sourceTimesSec': [90. + index / 30. for index in range(len(points))],
        'feet': {'right': {'states': ['full_sole'] * 4 + ['unknown', 'airborne', 'heel_only', 'toe_only']}},
    }
    payload = {
        'sourceFootSupportEvidence': {'footPatchEvidence': patch},
        'frames': [{'sourceTimeSec': value} for value in patch['sourceTimesSec']],
    }
    evidence = motion_space_support_evidence(payload)
    np.testing.assert_array_equal(evidence['_fitFrameStateIndices'], np.arange(len(points)))
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [ankle, toe]] = True
    floor = float(np.min(points[:, toe, 1]))
    rest_pitch = -.30

    uncalibrated, _ = rig_contact_targets(
        points, names, pinned, np.asarray(rig['offsets']), evidence=evidence, floor=floor)
    calibrated, _ = rig_contact_targets(
        points, names, pinned, np.asarray(rig['offsets']), evidence=evidence,
        floor=floor, rest_pitches={'right': rest_pitch})

    vector = calibrated[:4, toe] - calibrated[:4, ankle]
    pitch = np.arcsin(vector[:, 1] / np.linalg.norm(vector, axis=1))
    np.testing.assert_allclose(pitch, rest_pitch, atol=1e-12)
    np.testing.assert_allclose(
        np.linalg.norm(vector, axis=1), np.linalg.norm(rig['offsets'][toe]), atol=1e-12)
    horizontal_before = uncalibrated[:4, toe][:, (0, 2)] - uncalibrated[:4, ankle][:, (0, 2)]
    horizontal_after = calibrated[:4, toe][:, (0, 2)] - calibrated[:4, ankle][:, (0, 2)]
    horizontal_before /= np.linalg.norm(horizontal_before, axis=1, keepdims=True)
    horizontal_after /= np.linalg.norm(horizontal_after, axis=1, keepdims=True)
    np.testing.assert_allclose(horizontal_after, horizontal_before, atol=1e-12)
    np.testing.assert_allclose(calibrated[:4, toe], uncalibrated[:4, toe], atol=1e-12)
    np.testing.assert_array_equal(calibrated[4:, [ankle, toe]], uncalibrated[4:, [ankle, toe]])


@pytest.mark.parametrize('state_indices', [None, [0, 1]])
def test_contact_targets_do_not_infer_full_sole_rows_without_complete_clock_map(state_indices):
    from exercise_motion_pkg.contact_constraints import motion_space_support_evidence
    from exercise_motion_pkg.rig_playback import rig_contact_targets

    rig = rig_payload(8)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, toe = (names.index(f'right_{part}') for part in ('ankle', 'foot'))
    patch = {
        'available': True, 'sourceTimeBasis': 'absolute_source_video', 'sourceFps': 30.,
        'sourceTimesSec': [90. + index / 30. for index in range(8)],
        'feet': {'right': {'states': ['full_sole'] * 8}},
    }
    payload = {
        'sourceFootSupportEvidence': {'footPatchEvidence': patch},
        'frames': [{'sourceTimeSec': value} for value in patch['sourceTimesSec']],
    }
    evidence = motion_space_support_evidence(payload)
    evidence['_fitFrameStateIndices'] = state_indices
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [ankle, toe]] = True

    expected, _ = rig_contact_targets(
        points, names, pinned, np.asarray(rig['offsets']), evidence=evidence)
    calibrated, _ = rig_contact_targets(
        points, names, pinned, np.asarray(rig['offsets']), evidence=evidence,
        rest_pitches={'right': -.30})

    np.testing.assert_array_equal(calibrated, expected)


def test_contact_targets_keep_equal_length_clockless_legacy_identity_mapping():
    from exercise_motion_pkg.rig_playback import rig_contact_targets

    rig = rig_payload(8)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, toe = (names.index(f'right_{part}') for part in ('ankle', 'foot'))
    evidence = {'footPatchEvidence': {
        'available': True,
        'feet': {'right': {'states': ['full_sole'] * len(points)}},
    }}
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [ankle, toe]] = True

    calibrated, _ = rig_contact_targets(
        points, names, pinned, np.asarray(rig['offsets']), evidence=evidence,
        rest_pitches={'right': -.30})

    vector = calibrated[:, toe] - calibrated[:, ankle]
    pitch = np.arcsin(vector[:, 1] / np.linalg.norm(vector, axis=1))
    np.testing.assert_allclose(pitch, -.30, atol=1e-12)


@pytest.mark.parametrize('same_stance', [True, False])
def test_observed_stance_identity_prevents_false_ankle_loop_jump(same_stance):
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    rig = rig_payload(12)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, foot = (names.index('right_'+part) for part in ('ankle', 'foot'))
    points[:4, ankle, 2] += .03
    points[8:, ankle, 2] -= .03
    # Independently observed toe episodes need not have identical anchors.
    # Foot-length calibration must still keep the explicitly shared ankle.
    points[:4, foot, 2] += .008
    points[8:, foot, 2] -= .008
    original = points.copy()
    contacts = [{'jointName': 'right_foot', 'contactState': 'full_sole',
                 'contactMotion': 'stationary', 'startFrame': start, 'endFrame': end,
                 'supportKind': 'observed_foot_patch', 'surfaceKind': 'ground',
                 'ankleAnchorGroupId': group}
                for start, end, group in ((0, 3, 'stance-a'), (8, 11, 'stance-a' if same_stance else 'stance-b'))]
    evidence = {'contacts': contacts}
    pinned = contact_mask({'sourceFootSupportEvidence': evidence}, names, len(points))
    floor = float(points[0, foot, 1])
    targets, _ = rig_contact_targets(points, names, pinned, rig['offsets'], evidence=evidence, floor=floor)
    assert (np.linalg.norm(targets[0, ankle]-targets[-1, ankle]) < 1e-10) == same_stance
    np.testing.assert_array_equal(targets[4:8, ankle], points[4:8, ankle])
    np.testing.assert_allclose(np.linalg.norm((targets[:, ankle]-targets[:, foot])[pinned[:, ankle]], axis=1),
                               np.linalg.norm(rig['offsets'][foot]))
    np.testing.assert_array_equal(points, original)
    np.testing.assert_allclose(targets[:4, foot], np.broadcast_to(targets[0, foot], (4, 3)))
    np.testing.assert_allclose(targets[8:, foot], np.broadcast_to(targets[8, foot], (4, 3)))
    assert np.max(np.linalg.norm(targets[:, foot] - points[:, foot], axis=1)) < .01
    np.testing.assert_allclose(targets[pinned[:, foot], foot, 1], floor)


@pytest.mark.parametrize('placed', [False, True])
def test_incompatible_shared_stance_is_an_explicit_contact_rejection(placed):
    from exercise_motion_pkg.contact_constraints import InfeasibleContactCorrection
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    rig = rig_payload(12)
    current = export(rig)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    foot = names.index('right_foot')
    points[8:, foot, 0] += 1.
    current['sourceFootSupportEvidence'] = {'contacts': [
        {'jointName': 'right_foot', 'contactState': 'full_sole',
         'contactMotion': 'stationary', 'ankleAnchorGroupId': 'same-ankle',
         'startFrame': start, 'endFrame': end}
        for start, end in ((0, 3), (8, 11))]}
    for frame, source in zip(current['frames'], points):
        frame['controlledSourceJoints'] = dict(zip(names, source.tolist()))
    if placed:
        current['scenePlacement'] = {'version': 1, 'rotationVector': [0., 0., 0.],
                                     'originAfterRotation': [0., 0., 0.]}
    pinned = contact_mask(current, names, len(points))
    with pytest.raises(InfeasibleContactCorrection):
        rig_contact_targets(points, names, pinned, rig['offsets'],
                            evidence=current['sourceFootSupportEvidence'])
    report = validate_rig_playback(current)
    assert report['passed'] is False
    assert report['reason'] == 'incompatible_stationary_contact_anchors'


def test_playback_uses_temporally_filtered_support_evidence(monkeypatch):
    import exercise_motion_pkg.rig_playback as rig_playback
    from exercise_motion_pkg.contact_constraints import observed_ground_contact_mask

    current = export(rig_payload())
    current['sourceFootSupportEvidence'] = {
        'bodySupport': {
            'required': True,
            'status': 'confirmed',
            'source': 'exact_source_contacts_and_stationary_pose_tracks',
            'stationaryJoints': ['left_ankle', 'left_foot'],
            'coplanarGroups': [],
            'soleContacts': [],
            'nonPenetrationChains': [],
        },
        'temporalResolutionSufficient': True,
        'footPatchEvidence': {
            'available': True,
            'feet': {'left': {'states': ['full_sole', 'toe_only', 'unknown']},
                     'right': {'states': ['unknown']}},
        },
        'contacts': [{
            'jointName': 'left_foot',
            'supportKind': 'observed_foot_patch',
            'contactState': 'full_sole',
            'contactMotion': 'stationary',
            'surfaceKind': 'ground',
            'startFrame': 0,
            'endFrame': 3,
        }],
    }
    original = rig_playback.rig_contact_targets
    captured = {}

    def capture_evidence(*args, **kwargs):
        captured['evidence'] = kwargs['evidence']
        return original(*args, **kwargs)

    monkeypatch.setattr(rig_playback, 'rig_contact_targets', capture_evidence)
    rig_playback.validate_rig_playback(current)

    evidence = captured['evidence']
    assert 'bodySupport' not in evidence
    grounded = observed_ground_contact_mask(evidence, current['jointNames'], len(current['frames']))
    foot = current['jointNames'].index('left_foot')
    assert np.all(grounded[:4, foot])
    assert not np.any(grounded[4:, foot])


def test_joint_anchor_calibration_enforces_displacement_radius_during_solve():
    from exercise_motion_pkg.contact_constraints import calibrate_shared_contact_pair

    # Unequal observed episode lengths favor a diagonal toe correction beyond
    # the radial allowance if the optimizer only receives per-axis bounds.
    points = np.zeros((84, 2, 3))
    points[:, 0] = [0., .05, 0.]
    points[:32, 1] = [.137, 0., -.0555]
    points[32:, 1] = [.1204, 0., -.0237]
    mask = np.ones((84, 2), dtype=bool)
    mask[31] = False
    identities = np.full((84, 2), 'ankle', dtype=object)
    identities[:32, 1], identities[32:, 1] = 'toe-a', 'toe-b'
    ground = mask.copy()
    ground[:, 0] = False
    length = .134
    result = calibrate_shared_contact_pair(points, mask, identities, distance=length,
                                           ground_mask=ground, floor=0.)
    assert np.max(np.linalg.norm(result - points, axis=-1)) <= .1 * length + 1e-7
    np.testing.assert_allclose(result[mask[:, 0], 0],
                               np.broadcast_to(result[0, 0], (83, 3)), atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(result[mask[:, 0], 0] - result[mask[:, 0], 1], axis=1),
                               length, atol=1e-7)
    np.testing.assert_array_equal(result[31], points[31])
    np.testing.assert_allclose(result[mask[:, 1], 1, 1], 0., atol=1e-12)


@pytest.mark.parametrize('surface,shared_plane,calibrated,grounded', [
    ('ground', False, False, True), ('raised_surface', True, False, False),
    ('', True, False, True), ('', False, False, False), ('ground', True, True, False)])
def test_contact_surface_owns_height_without_pinning_release(surface, shared_plane, calibrated, grounded):
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    rig = rig_payload(12)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    points[:, :, 1] += .4
    contact = {'jointName': 'right_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
               'supportKind': 'observed_foot_patch', 'surfaceKind': surface, 'startFrame': 0, 'endFrame': 3}
    evidence = {'contacts': [contact]}
    if shared_plane:
        evidence['sharedSupportPlaneY'] = .8
    if calibrated:
        evidence['bodySupport'] = {'required': True, 'status': 'confirmed',
                                   'stationaryJoints': ['right_foot', 'right_ankle']}
    pinned = contact_mask({'sourceFootSupportEvidence': evidence}, names, len(points))
    targets, _ = rig_contact_targets(points, names, pinned, rig['offsets'], evidence=evidence, floor=0.)
    foot, ankle = names.index('right_foot'), names.index('right_ankle')
    np.testing.assert_allclose(targets[:4, foot, 1], 0. if grounded else points[0, foot, 1])
    np.testing.assert_array_equal(targets[4:], points[4:])
    np.testing.assert_allclose(targets[:4, ankle]-targets[:4, foot], points[:4, ankle]-points[:4, foot], atol=1e-12)


def test_playback_validates_height_only_contact_separately_from_tangent_motion():
    rig = rig_payload(12)
    payload = export(rig)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    foot = names.index('left_foot')
    payload['sourceFootSupportEvidence'] = {
        'sharedSupportPlaneY': float(np.median(points[:, foot, 1]) + .01),
        'contacts': [{
            'jointName': 'left_foot',
            'supportKind': 'observed_foot_patch',
            'surfaceKind': 'ground',
            'contactState': 'toe_only',
            'contactMotion': 'stationary',
            'verticalOnly': True,
            'startFrame': 1,
            'endFrame': 10,
        }],
    }

    report = validate_rig_playback(payload)

    assert report['maximumStoredFrameHeightOnlyContactErrorMeters'] == pytest.approx(.01)
    assert report['maximumHeightOnlyContactErrorMeters'] == pytest.approx(.01)
    assert report['maximumContactErrorMeters'] == 0.
    assert not report['passed']


@pytest.mark.parametrize('anchored', [False, True])
def test_floor_clearance_translates_free_rig_without_changing_motion(anchored):
    from exercise_motion_pkg.rig_playback import unanchored_floor_clearance_lift
    rig = rig_payload()
    before = sample_rig(rig, np.arange(120) / 4, wrap=True)
    floor = float(before[:, :, 1].min()) + .01
    pinned = np.zeros(before[::4].shape[:2], dtype=bool)
    pinned[:, 0] = anchored
    lift = unanchored_floor_clearance_lift(rig, floor, pinned, cyclic=True)
    if anchored:
        assert lift == 0.0
        return
    coordinates = np.asarray(rig['coordinates'])
    coordinates[:, 1] += lift
    rig['coordinates'] = coordinates.tolist()
    after = sample_rig(rig, np.arange(120) / 4, wrap=True)
    assert float(after[:, :, 1].min()) == pytest.approx(floor)
    np.testing.assert_allclose(after - before, np.broadcast_to([0., lift, 0.], before.shape), atol=1e-12)


def test_free_joint_floor_lift_ignores_planted_contacts():
    from exercise_motion_pkg.rig_playback import free_joint_floor_clearance_lift
    rig = rig_payload(8)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    floor = float(points[:, :, 1].min())
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, names.index('left_foot')] = True
    dipped = np.asarray(rig['coordinates'], dtype=float)
    dipped[:, 1] -= 0.003
    rig['coordinates'] = dipped.tolist()
    lift = free_joint_floor_clearance_lift(rig, floor, pinned, cyclic=False)
    assert lift == pytest.approx(0.003, abs=1e-4)


def test_free_material_floor_lift_checks_shoe_shell_and_exempts_only_full_sole_plants():
    from exercise_motion_pkg.rig_playback import free_material_floor_clearance_lift

    rig = rig_payload(3)
    coordinates = np.asarray(rig['coordinates'], dtype=float)
    coordinates[:, 1] += 2.
    rig['coordinates'] = coordinates.tolist()
    payload = export(rig)
    payload['loop'] = {'enabled': False}
    # Missing calibration must still measure the renderer's default zero-pitch shoe.
    payload['footRestPitchRadians'] = {}
    points = decode_rig(rig, rig['coordinates'])
    floor = float(points[:, :, 1].min()) - .0001
    payload['renderFloorY'] = floor
    assert points[:, :, 1].min() > floor

    names = payload['jointNames']
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, names.index('left_ankle')] = True
    lift = free_material_floor_clearance_lift(payload, pinned, cyclic=False)
    assert lift > .001

    payload['sourceFootSupportEvidence'] = {'contacts': [{
        'jointName': 'left_foot', 'contactState': 'full_sole',
        'contactMotion': 'stationary', 'supportKind': 'observed_foot_patch',
        'surfaceKind': 'ground', 'startFrame': 0, 'endFrame': len(points) - 1,
    }]}
    pinned[:, names.index('left_foot')] = True
    assert free_material_floor_clearance_lift(payload, pinned, cyclic=False) < .0002


def test_empty_point_pins_still_respect_native_toe_contact_ownership():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, _sampling_payload, apply_supported_floor_clearance)
    from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame
    from exercise_motion_pkg.rig_playback import native_active_contact_ownership

    native = json.loads((Path(__file__).parent / 'fixtures'
                         / 'native_foot_geometry_v1.json').read_text())['reference']
    rig = rig_payload(3)
    coordinates = np.asarray(rig['coordinates'], dtype=float)
    coordinates[:, 1] += 2.
    rig['coordinates'] = coordinates.tolist()
    payload = export(rig)
    payload['loop'] = {'enabled': False}
    payload['footRestPitchRadians'] = {}
    payload['nativeFootGeometry'] = native
    points = decode_rig(rig, rig['coordinates'])
    floor = float(points[:, :, 1].min()) - .0001
    payload['renderFloorY'] = floor

    names = payload['jointNames']
    count = len(points)
    pinned = np.zeros(points.shape[:2], dtype=bool)  # suppressed native pins
    rig_frame = FixedRig(points, names)
    rig_frame.native_foot_geometry_for_sampling = native
    rig_frame.native_foot_scale_for_sampling = float(foot_scale_from_pose(points[0], names))
    reference = {
        **payload,
        'frames': [{'joints': dict(zip(names, row.tolist()))} for row in points],
        'fixedRig': _sampling_payload(rig_frame, rig_frame.initial),
    }

    def side_track(side, active):
        ankle_i, foot_i = names.index(side + '_ankle'), names.index(side + '_foot')
        direction = points[:, foot_i] - points[:, ankle_i]
        direction /= np.linalg.norm(direction, axis=1)[:, None]
        axes = np.cross(direction, np.asarray([0., 0., 1.]))
        axes /= np.linalg.norm(axes, axis=1)[:, None]
        if not active:
            return {'active': [False] * count, 'directions': direction.tolist(),
                    'sideAxes': axes.tolist(), 'anchorIds': [None] * count,
                    'episodes': []}
        foot_scale = .2
        triangle_index, bary = 22, np.asarray([0., 0., 1.])
        mesh = shoe_vertices(points[0, ankle_i], points[0, foot_i], axes[0], None,
                             foot_scale, native_geometry=native['sides'][side])
        material_point = bary @ mesh[shoe_triangles()[triangle_index]]
        forward, lateral, up, length = native_foot_bone_frame(
            points[0, ankle_i], points[0, foot_i], axes[0])
        delta = material_point - points[0, ankle_i]
        ref_length = native['sides'][side]['ankleToFootJointLengthMeters']
        local = np.asarray([delta @ forward, delta @ lateral, delta @ up])
        local *= ref_length / float(length[0])
        return {
            'active': [True] * count, 'directions': direction.tolist(),
            'sideAxes': axes.tolist(), 'anchorIds': ['native-toe'] * count,
            'episodes': [{
                'startFrame': 0, 'endFrame': count - 1, 'anchorId': 'native-toe',
                'regionRole': 'forefoot', 'mode': 'stationary',
                'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
                'triangleIndex': triangle_index, 'barycentric': bary.tolist(),
                'materialOffsetLocalMeters': local.tolist(),
                'referenceLengthMeters': ref_length,
                'targetWorld': material_point.tolist(),
                'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': float(material_point[1]),
            }],
        }

    stationary_toe = {'version': 2, 'left': side_track('left', False),
                      'right': side_track('right', True)}
    free_flight = {'version': 2, 'left': side_track('left', False),
                   'right': side_track('right', False)}
    ownership = native_active_contact_ownership(
        stationary_toe, count=count, cyclic=False)
    assert np.all(ownership['right'])
    assert 'left' not in ownership

    ownership_report = {}
    corrected, lift = apply_supported_floor_clearance(
        rig_frame.initial, rig_frame, pinned, points, floor, cyclic=False,
        material_reference=reference, contact_foot_tracks=stationary_toe,
        ownership_report=ownership_report)
    assert lift == 0.0
    np.testing.assert_array_equal(corrected, rig_frame.initial)
    assert ownership_report['suppressed'] is True
    assert ownership_report['reason'] == 'nativeMaterialContactOwnsFloor'
    assert ownership_report['ownedSides'] == ['right']

    free_corrected, free_lift = apply_supported_floor_clearance(
        rig_frame.initial, rig_frame, pinned, points, floor, cyclic=False,
        material_reference=reference, contact_foot_tracks=free_flight,
        ownership_report={})
    assert free_lift > 0.
    assert np.all(free_corrected[:, 1] > rig_frame.initial[:, 1])


def test_materialized_support_uses_final_rig_and_still_rejects_penetration(tmp_path):
    from exercise_motion_pkg.bake_and_rank import materialized_cleanup_support_metrics
    rig = rig_payload()
    payload = export(rig)
    floor = float(decode_rig(rig, rig['coordinates'])[:, :, 1].min())
    payload['renderFloorY'] = floor
    (tmp_path / 'cleaned').mkdir()
    (tmp_path / 'cleaned/motion.cleaned.json').write_text(json.dumps({
        'metadata': {'cleanup': {'supportSurfaceConstraint': {'maximumSuppressedNonPenetrationLift': .6}}}}))
    skeleton = tmp_path / 'final.json'
    skeleton.write_text(json.dumps(payload))
    assert not materialized_cleanup_support_metrics(tmp_path, skeleton_path=skeleton)['supportContactContradiction']
    values = np.asarray(rig['coordinates'])
    values[:, 1] -= .01
    rig['coordinates'] = values.tolist()
    payload = export(rig)
    payload['renderFloorY'] = floor
    skeleton.write_text(json.dumps(payload))
    assert materialized_cleanup_support_metrics(tmp_path, skeleton_path=skeleton)['supportContactContradiction']


def test_materialized_support_missing_output_uses_cleanup_fallback(tmp_path):
    from exercise_motion_pkg.bake_and_rank import materialized_cleanup_support_metrics
    metrics = materialized_cleanup_support_metrics(
        tmp_path,
        skeleton_path=tmp_path / 'not-yet-written-skeleton.json',
    )
    assert metrics['supportContactContradiction'] is False
    assert metrics['reason'] == 'cleaned_motion_missing'


def test_scene_placement_preserves_fractional_articulation_travel_and_reuse():
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    rig = rig_payload()
    values = np.array(rig['coordinates'])
    values[:, 0] += np.linspace(2., 3., len(values))
    rig['coordinates'] = values.tolist()
    original = export(rig)
    original['loop']['enabled'] = False
    placed = normalize_scene_placement(original)
    assert placed is not original
    assert placed['scenePlacement']['rotationDegrees'] == 0
    assert normalize_scene_placement(placed) is placed
    np.testing.assert_allclose(np.array(placed['bounds']['center'])[[0, 2]], 0., atol=1e-12)
    before = sample_rig(rig, [.5, 15.25, 28.75])
    after = sample_rig(placed['fixedRig'], [.5, 15.25, 28.75])
    np.testing.assert_allclose(after-after[:, :1], before-before[:, :1], atol=1e-12)
    np.testing.assert_allclose(after[-1]-after[0], before[-1]-before[0], atol=1e-12)
    assert validate_rig_playback(placed)['passed']


def test_scene_placement_transforms_contact_foot_tracks_with_the_rig():
    from exercise_motion_pkg.contact_interpolation import build_contact_foot_tracks
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    rig = rig_payload()
    points = decode_rig(rig, np.asarray(rig['coordinates']))
    pinned = np.ones(points.shape[:2], dtype=bool)
    rig['contactFootTracks'] = build_contact_foot_tracks(rig, points, pinned)
    original = export(rig)
    original['renderFloorY'] = -10.
    placed = normalize_scene_placement(original)
    assert placed is not original
    origin = np.asarray(placed['scenePlacement']['originAfterRotation'])
    for side in ('left', 'right'):
        before = rig['contactFootTracks'][side]
        after = placed['fixedRig']['contactFootTracks'][side]
        np.testing.assert_allclose(after['toes'], np.asarray(before['toes']) - origin)
        np.testing.assert_allclose(after['directions'], before['directions'])
    queries = np.array([.5, 15.25, 28.75])
    np.testing.assert_allclose(
        sample_rig(placed['fixedRig'], queries), sample_rig(rig, queries) - origin,
        atol=1e-10)


def test_scene_placement_transforms_native_material_point_and_support_plane(monkeypatch):
    import json
    from pathlib import Path
    from exercise_motion_pkg.contact_interpolation import validate_native_contact_track_geometry
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame
    from exercise_motion_pkg.scene_placement import normalize_scene_placement

    monkeypatch.setattr('exercise_motion_pkg.rig_playback.validate_rig_playback',
                        lambda _payload: {'passed': True})
    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    native = fixture['reference']
    foot_scale = .2
    rig = rig_payload()
    values = np.asarray(rig['coordinates'])
    tilt = Rotation.from_euler('z', 5., degrees=True)
    values[:, :3] = tilt.apply(values[:, :3])
    slot = 3 + 3 * rig['rotationJointNames'].index('pelvis')
    values[:, slot:slot+3] = (
        (tilt * Rotation.from_rotvec(values[:, slot:slot+3])).as_rotvec())
    rig['coordinates'] = values.tolist()
    original = export(rig)
    original['groundContactMode'] = 'continuous'
    original['nativeFootGeometry'] = native
    original['sourceFootSupportEvidence'] = {'contacts': [
        {'jointName': side + '_foot', 'contactState': 'full_sole',
         'contactMotion': 'stationary', 'startRatio': 0., 'endRatio': 1.}
        for side in ('left', 'right')]}

    names = original['jointNames']
    points = np.asarray([[frame['joints'][name] for name in names]
                         for frame in original['frames']])
    side = 'left'
    ankle_i, foot_i = names.index(side + '_ankle'), names.index(side + '_foot')
    direction = points[:, foot_i] - points[:, ankle_i]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    axes = np.cross(direction, np.asarray([0., 0., 1.]))
    axes /= np.linalg.norm(axes, axis=1)[:, None]
    triangle_index, barycentric = 22, np.asarray([0., 0., 1.])
    mesh = shoe_vertices(points[0, ankle_i], points[0, foot_i], axes[0], None,
                         foot_scale, native_geometry=native['sides'][side])
    triangle = shoe_triangles()[triangle_index]
    material_point = barycentric @ mesh[triangle]
    forward, lateral, up, length = native_foot_bone_frame(
        points[0, ankle_i], points[0, foot_i], axes[0])
    delta = material_point - points[0, ankle_i]
    reference_length = native['sides'][side]['ankleToFootJointLengthMeters']
    local = np.asarray([np.dot(delta, forward), np.dot(delta, lateral), np.dot(delta, up)])
    local *= reference_length / float(length[0])
    track = {
        'active': [True] * len(points), 'directions': direction.tolist(),
        'sideAxes': axes.tolist(), 'anchorIds': ['native-anchor'] * len(points),
        'episodes': [{
            'startFrame': 0, 'endFrame': len(points)-1, 'anchorId': 'native-anchor',
            'regionRole': 'forefoot', 'mode': 'stationary',
            'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
            'triangleIndex': triangle_index, 'barycentric': barycentric.tolist(),
            'materialOffsetLocalMeters': local.tolist(),
            'referenceLengthMeters': reference_length,
            'targetWorld': material_point.tolist(),
            'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': float(material_point[1]),
        }],
    }
    rig['contactFootTracks'] = {'version': 2, side: track}
    placed = normalize_scene_placement(original)
    assert placed is not original
    rotation = Rotation.from_rotvec(placed['scenePlacement']['rotationVector'])
    origin = np.asarray(placed['scenePlacement']['originAfterRotation'])
    assert rotation.magnitude() > 1e-3
    after_track = placed['fixedRig']['contactFootTracks'][side]
    after_episode = after_track['episodes'][0]
    np.testing.assert_allclose(after_track['directions'], rotation.apply(direction), atol=1e-12)
    np.testing.assert_allclose(after_track['sideAxes'], rotation.apply(axes), atol=1e-12)
    np.testing.assert_array_equal(after_episode['materialOffsetLocalMeters'], local.tolist())
    expected_point = rotation.apply(material_point) - origin
    np.testing.assert_allclose(after_episode['targetWorld'], expected_point, atol=1e-12)
    expected_normal = rotation.apply([0., 1., 0.])
    np.testing.assert_allclose(after_episode['surfaceNormal'], expected_normal, atol=1e-12)
    assert after_episode['planeOffsetMeters'] == pytest.approx(
        float(material_point[1] - np.dot(expected_normal, origin)), abs=1e-12)

    placed_points = np.asarray([[frame['joints'][name] for name in names]
                               for frame in placed['frames']])
    placed_mesh = shoe_vertices(
        placed_points[0, ankle_i], placed_points[0, foot_i],
        np.asarray(after_track['sideAxes'][0]), None, foot_scale,
        native_geometry=native['sides'][side])
    placed_point = barycentric @ placed_mesh[triangle]
    np.testing.assert_allclose(placed_point, expected_point, atol=1e-12)
    assert float(np.dot(placed_point, expected_normal)) == pytest.approx(
        after_episode['planeOffsetMeters'], abs=1e-12)
    assert after_episode['regionRole'] == 'forefoot'
    assert after_episode['anchorId'] == 'native-anchor'
    assert validate_native_contact_track_geometry(
        placed_points, names,
        {side: np.asarray(after_track['sideAxes'])},
        placed['fixedRig']['contactFootTracks'], native, foot_scale)


def test_scene_placement_respects_explicit_floor_and_digest():
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    from exercise_motion_pkg.sequence_stabilization import pose_digest
    original = export(rig_payload())
    original['renderFloorY'] = -10.
    placed = normalize_scene_placement(original)
    assert placed['renderFloorY'] == 0.
    assert placed['scenePlacement']['rotationDegrees'] == 0.
    digest = pose_digest(placed)
    placed['scenePlacement']['rotationVector'][0] += .01
    assert pose_digest(placed) != digest


def test_scene_placement_transforms_support_plane_offset_with_floor():
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    from exercise_motion_pkg.support_geometry import geometry_errors
    original = export(rig_payload())
    original['renderFloorY'] = -10.
    names = original['jointNames']
    points = np.array([[f['joints'][n] for n in names] for f in original['frames']])
    group = {'joints': ['left_foot', 'right_foot'], 'normal': [0, 2, 0],
             'planeOffsetMeters': float(points[0, names.index('left_foot'), 1])}
    original['sourceFootSupportEvidence'] = {'bodySupport': {'coplanarGroups': [group]}}
    placed = normalize_scene_placement(original)
    after = np.array([[f['joints'][n] for n in names] for f in placed['frames']])
    np.testing.assert_allclose(
        geometry_errors(after, names, placed['sourceFootSupportEvidence']['bodySupport']),
        geometry_errors(points, names, original['sourceFootSupportEvidence']['bodySupport']), atol=1e-12)


def test_scene_placement_levels_consistent_supported_stance_once():
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    rig = rig_payload()
    values = np.array(rig['coordinates'])
    tilt = Rotation.from_euler('z', 5., degrees=True)
    values[:, :3] = tilt.apply(values[:, :3])
    slot = 3 + 3 * rig['rotationJointNames'].index('pelvis')
    values[:, slot:slot+3] = (tilt * Rotation.from_rotvec(values[:, slot:slot+3])).as_rotvec()
    rig['coordinates'] = values.tolist()
    original = export(rig)
    original['groundContactMode'] = 'continuous'
    original['sourceFootSupportEvidence'] = {'contacts': [
        {'jointName': side+'_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'supportKind': 'observed_foot_patch', 'startRatio': 0., 'endRatio': 1.} for side in ('left', 'right')],
         'bodySupport': {'status': 'confirmed',
                         'stationaryJoints': ['left_ankle', 'left_foot', 'right_ankle', 'right_foot'],
                         'soleContacts': [], 'coplanarGroups': []}}
    # This fixture declares a verified full-sole plane, so give its rendered
    # shoes the corresponding material basis. The foot/knee skeleton remains
    # tilted; only the shoe shell is oriented to the observed support plane.
    plane_normal = tilt.apply(np.array([0., 1., 0.]))
    plane_offset = None
    for side in ('left', 'right'):
        ankle = np.asarray(original['frames'][0]['joints'][f'{side}_ankle'])
        foot = np.asarray(original['frames'][0]['joints'][f'{side}_foot'])
        plane_offset = float(np.dot(plane_normal, foot)) if plane_offset is None else plane_offset
        original['sourceFootSupportEvidence']['bodySupport']['soleContacts'].append({
            'joints': [f'{side}_knee', f'{side}_ankle', f'{side}_foot'],
            'normal': plane_normal.tolist(),
            'planeOffsetMeters': plane_offset,
        })
        original['sourceFootSupportEvidence']['bodySupport']['coplanarGroups'].append({
            'joints': [f'{side}_ankle', f'{side}_foot'],
            'normal': plane_normal.tolist(),
            'planeOffsetMeters': plane_offset,
        })
    for frame in original['frames']:
        frame['shoeOrientation'] = {}
        for side in ('left', 'right'):
            ankle = np.asarray(frame['joints'][f'{side}_ankle'])
            foot = np.asarray(frame['joints'][f'{side}_foot'])
            forward = foot - ankle
            forward -= plane_normal * np.dot(forward, plane_normal)
            forward /= np.linalg.norm(forward)
            material_side = np.cross(forward, plane_normal)
            material_side /= np.linalg.norm(material_side)
            frame['shoeOrientation'][side] = {
                'forward': forward.tolist(),
                'side': material_side.tolist(),
            }
    original['footRestPitchRadians'] = {'left': 0., 'right': 0.}
    placed = normalize_scene_placement(original)
    assert placed['scenePlacement']['orientationReason'] == 'consistent_extended_supported_stance'
    assert placed['scenePlacement']['rotationDegrees'] > 1.
    joints = placed['frames'][0]['joints']
    up = np.array(joints['neck']) - (np.array(joints['left_ankle']) + joints['right_ankle'])/2
    np.testing.assert_allclose(up[[0, 2]], 0., atol=1e-12)
    assert validate_rig_playback(placed)['passed']


def test_unreachable_contact_ik_is_structured_as_failed_unverified_playback(monkeypatch):
    from exercise_motion_pkg.contact_interpolation import _solve_knee
    from exercise_motion_pkg.controlled_motion import playback_validation_checks
    import exercise_motion_pkg.rig_playback as rig_playback_module

    payload = export(rig_payload(8))

    def sample_with_unreachable_contact(*_args, **_kwargs):
        hip = np.zeros((1, 3))
        knee = np.array([[0., -0.4, 0.]])
        ankle = np.array([[0., -0.8, 0.]])
        target = np.array([[0.9, 0., 0.]])
        return _solve_knee(hip, knee, ankle, target, .4, .4, 'right')

    monkeypatch.setattr(rig_playback_module, 'sample_rig', sample_with_unreachable_contact)
    playback = validate_rig_playback(payload)

    assert playback['passed'] is False
    assert playback['reason'] == 'contact_foot_ik_unreachable'
    assert playback['contactFootIKUnreachable']['side'] == 'right'
    assert playback['contactFootIKUnreachable']['samples'][0] == {
        'sampleIndex': 0,
        'hipTargetMeters': [0., 0., 0.],
        'ankleTargetMeters': [.9, 0., 0.],
        'hipToAnkleTargetDistanceMeters': pytest.approx(.9),
        'minimumReachMeters': pytest.approx(0.),
        'maximumReachMeters': pytest.approx(.8),
        'lowerReachDeficitMeters': 0.,
        'upperReachExcessMeters': pytest.approx(.1),
    }
    assert set(playback['validationStatusByCheck'].values()) == {'failed', 'unverified'}
    assert playback_validation_checks(playback, cyclic=True) == {
        'playback': False, 'loopSeam': False,
    }


def test_scene_placement_rotates_shoe_material_basis_without_translation(monkeypatch):
    from exercise_motion_pkg.scene_placement import normalize_scene_placement
    # Isolate the axis transform from the separate material-sole acceptance
    # gate; other coverage owns that validator's thresholds and evidence.
    monkeypatch.setattr('exercise_motion_pkg.rig_playback.validate_rig_playback',
                        lambda _payload: {'passed': True})
    rig = rig_payload()
    values = np.array(rig['coordinates'])
    tilt = Rotation.from_euler('z', 5., degrees=True)
    values[:, :3] = tilt.apply(values[:, :3])
    slot = 3 + 3 * rig['rotationJointNames'].index('pelvis')
    values[:, slot:slot+3] = (tilt * Rotation.from_rotvec(values[:, slot:slot+3])).as_rotvec()
    rig['coordinates'] = values.tolist()
    original = export(rig)
    original['groundContactMode'] = 'continuous'
    original['sourceFootSupportEvidence'] = {'contacts': [
        {'jointName': side+'_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'supportKind': 'observed_foot_patch', 'startRatio': 0., 'endRatio': 1.} for side in ('left', 'right')],
         'sharedSupportPlaneY': .8}
    for frame in original['frames']:
        frame['shoeOrientation'] = {
            side: {'forward': [0., 0., 1.], 'side': [1., 0., 0.]}
            for side in ('left', 'right')
        }
    placed = normalize_scene_placement(original)
    assert placed['scenePlacement']['rotationDegrees'] > 1.
    rotation = Rotation.from_rotvec(placed['scenePlacement']['rotationVector'])
    for before, after in zip(original['frames'], placed['frames'], strict=True):
        for side in ('left', 'right'):
            before_axes = before['shoeOrientation'][side]
            after_axes = after['shoeOrientation'][side]
            np.testing.assert_allclose(after_axes['forward'], rotation.apply(before_axes['forward']), atol=1e-12)
            np.testing.assert_allclose(after_axes['side'], rotation.apply(before_axes['side']), atol=1e-12)
            assert abs(np.dot(after_axes['forward'], after_axes['side'])) < 1e-12


def test_fractional_rotation_preserves_lengths_and_detects_hidden_contact_slip():
    rig=rig_payload(2);values=np.array(rig['coordinates']);points=decode_rig(rig,values)
    root=rig['jointNames'].index('pelvis');foot=rig['jointNames'].index('left_foot');anchor=points[0,foot]
    rotation=Rotation.from_euler('y',np.pi/2)
    values[1,:3]=rotation.apply(values[0,:3]-anchor)+anchor
    slot=3+3*rig['rotationJointNames'].index('pelvis')
    values[1,slot:slot+3]=(rotation*Rotation.from_rotvec(values[0,slot:slot+3])).as_rotvec()
    rig['coordinates']=values.tolist();p=export(rig)
    np.testing.assert_allclose(p['frames'][0]['joints']['left_foot'],p['frames'][1]['joints']['left_foot'],atol=1e-12)
    p['sourceFootSupportEvidence']={'contacts':[{'jointName':'left_foot','contactState':'toe_only','verticalOnly':False,'contactMotion':'stationary','startRatio':0.,'endRatio':1.}]}
    report=validate_rig_playback(p)
    assert not report['passed']
    assert report['maximumContactErrorMeters']>.01
    assert report['maximumBoneLengthVariationMeters']<1e-12


def test_travel_is_kept_and_loop_requires_cycle_repair():
    rig=rig_payload();values=np.array(rig['coordinates']);values[:,0]+=np.linspace(0.,1.,len(values));rig['coordinates']=values.tolist()
    report=validate_rig_playback(export(rig))
    assert report['passed'],report
    assert not report['seamContinuous'] and report['loopTransition']=='requires_cycle_repair'
    assert report['seamPositionJumpMeters']>.99
    positions=sample_rig(rig,[.5,10.5,20.5])
    for joint,parent in enumerate(rig['parents']):
        if parent>=0:assert np.ptp(np.linalg.norm(positions[:,joint]-positions[:,parent],axis=-1))<1e-12


def test_closed_stationary_loop_checks_the_entire_seam_without_fading():
    payload=export(rig_payload(8))
    report=validate_rig_playback(payload)
    assert report['passed'] and report['seamContinuous'], report
    assert report['sampleCount']==32
    assert report['loopTransition']=='continuous'
    assert report['seamVelocityMismatchMetersPerSecond']<1e-10


def test_final_physical_gate_rejects_unsafe_loop_without_fade_exception():
    from copy import deepcopy
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload
    rig=rig_payload()
    values=np.array(rig['coordinates'])
    values[:,0]+=np.linspace(0.,1.,len(values))
    rig['coordinates']=values.tolist()
    payload=export(rig)
    payload['loop']['restartFadeMillis']=150
    for frame in payload['frames']:
        frame['controlledSourceJoints']=deepcopy(frame['joints'])
    report=physical_metrics_from_payload(payload)
    assert not report['passed']
    assert 'unsafe_loop_transition' in report['reasons']


def test_subframe_knee_reference_is_time_interpolated_independently_of_anatomy_authority():
    from exercise_motion_pkg.physical_validation import validate_physical_motion
    from exercise_motion_pkg.rig_playback import playback_reference_samples

    rig = rig_payload(2)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    index = {name: i for i, name in enumerate(names)}
    reference = points.copy()

    hip, knee, ankle, foot = (index[f'left_{joint}']
                              for joint in ('hip', 'knee', 'ankle', 'foot'))
    parent_axis = points[1, hip] - points[1, knee]
    parent_axis /= np.linalg.norm(parent_axis)
    ankle_direction = points[1, ankle] - points[1, knee]
    ankle_length = np.linalg.norm(ankle_direction)
    bend_axis = ankle_direction - np.dot(ankle_direction, parent_axis) * parent_axis
    bend_axis /= np.linalg.norm(bend_axis)
    knee_angle = np.deg2rad(40.)
    new_direction = (np.cos(knee_angle) * parent_axis
                     + np.sin(knee_angle) * bend_axis)
    displaced_ankle = points[1, knee] + ankle_length * new_direction
    ankle_delta = displaced_ankle - points[1, ankle]
    reference[1, ankle] = displaced_ankle
    reference[1, foot] += ankle_delta

    interpolated, anatomy = playback_reference_samples(
        reference, np.array([0]), np.array([1]), np.array([.5]), names)
    np.testing.assert_allclose(interpolated[0], .5 * (reference[0] + reference[1]))
    np.testing.assert_array_equal(anatomy[0], reference[0])

    actual = points[0:1]
    playback_check = validate_physical_motion(
        actual, names, reference=interpolated, anatomy_reference=anatomy)
    endpoint_check = validate_physical_motion(
        actual, names, reference=reference[0:1], anatomy_reference=anatomy)
    assert any(event.get('reason') == 'repair_articulation_distortion'
               and event.get('joint') == 'left_knee'
               for event in playback_check['events'])
    assert not any(event.get('reason') == 'repair_articulation_distortion'
                   and event.get('joint') == 'left_knee'
                   for event in endpoint_check['events'])


def test_final_physical_gate_allows_intentional_open_loop_seam():
    from copy import deepcopy
    from exercise_motion_pkg.controlled_motion import CONTROLLED_MOTION_STRATEGY, REQUIRED_FIT_CHECKS
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload
    from exercise_motion_pkg.sequence_stabilization import pose_digest
    rig = rig_payload()
    values = np.array(rig['coordinates'])
    values[:, 0] += np.linspace(0., 0.05, len(values))
    rig['coordinates'] = values.tolist()
    payload = export(rig)
    payload['loop'] = {
        **payload['loop'],
        'enabled': True,
        'transition': 'requires_cycle_repair',
        'restartFadeMillis': 0,
    }
    for frame in payload['frames']:
        frame['controlledSourceJoints'] = deepcopy(frame['joints'])
    payload['controlledMotionFit'] = {
        'applied': True,
        'reason': 'validated_controlled_motion_open_seam',
        'loopSeamOpen': True,
        'strategy': CONTROLLED_MOTION_STRATEGY,
        'checks': {**dict.fromkeys(REQUIRED_FIT_CHECKS, True), 'loopSeam': False},
    }
    payload['controlledMotionFit']['outputPoseDigest'] = pose_digest(payload)
    report = physical_metrics_from_payload(payload)
    assert 'unsafe_loop_transition' not in report.get('reasons', [])
    # Open-seam labeling alone must not invent a wrap rejection; body playback
    # may still fail for independent reasons on a traveling clip.
    assert report.get('rigPlayback', {}).get('openLoopSeam') is True


def test_pose_digest_covers_rig_coordinates_and_loop_policy():
    from exercise_motion_pkg.sequence_stabilization import pose_digest
    payload=export(rig_payload())
    original=pose_digest(payload)
    payload['fixedRig']['coordinates'][0][0]+=.01
    assert pose_digest(payload)!=original
    changed=pose_digest(payload)
    payload['loop']['enabled']=False
    assert pose_digest(payload)!=changed


def test_smooth_fast_cycle_is_not_rejected_for_normal_last_to_first_displacement():
    rig=rig_payload(120)
    values=np.array(rig['coordinates'])
    phase=np.arange(120)*2*np.pi/120
    values[:,0]+=.8*np.sin(phase)
    values[:,2]+=.8*np.cos(phase)
    rig['coordinates']=values.tolist()
    report=validate_rig_playback(export(rig))
    assert report['seamPositionJumpMeters']>.04
    assert report['passed'] and report['seamContinuous'],report
    assert report['seamStepExcessMeters']<1e-10


def test_contact_validation_cannot_move_the_source_anchor_with_the_repaired_pose():
    from copy import deepcopy
    rig=rig_payload(8)
    payload=export(rig)
    source=[deepcopy(f['joints']) for f in payload['frames']]
    values=np.array(rig['coordinates']);values[:,0]+=.01;rig['coordinates']=values.tolist()
    payload=export(rig)
    for frame,original in zip(payload['frames'],source):
        frame['controlledSourceJoints']=original
    payload['sourceFootSupportEvidence']={'contacts':[{'jointName':'left_foot',
        'contactState':'toe_only','verticalOnly':False,'contactMotion':'stationary','startRatio':0.,'endRatio':1.}]}
    report=validate_rig_playback(payload)
    assert not report['passed']
    assert abs(report['maximumContactErrorMeters']-.01)<1e-10


def test_supported_anatomy_source_need_not_lie_on_spatial_support_plane(monkeypatch):
    from copy import deepcopy
    from exercise_motion_pkg import physical_validation, rig_playback
    from exercise_motion_pkg.support_geometry import validate_support_geometry
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    names = payload['jointNames']
    points = decode_rig(payload['fixedRig'], payload['fixedRig']['coordinates'])
    source = points+np.array([0., .35, 0.])
    for frame, raw, spatial in zip(payload['frames'], source, points):
        frame['controlledArticulationReferenceJoints'] = dict(zip(names, raw.tolist()))
        frame['supportCorrectedReferenceJoints'] = dict(zip(names, spatial.tolist()))
        frame['supportContactReferenceJoints'] = dict(zip(names, spatial.tolist()))
    payload['sourceFootSupportEvidence'] = {'bodySupport': {
        'required': True, 'status': 'confirmed', 'stationaryJoints': ['pelvis'],
        'coplanarGroups': [{'joints': ['pelvis'], 'normal': [0., 1., 0.],
                            'planeOffsetMeters': float(points[0, names.index('pelvis'), 1])}]}}
    assert validate_support_geometry(payload, points, names)['passed']
    assert not validate_support_geometry(payload, source, names)['passed']
    original = rig_playback.validate_physical_motion
    observed = []
    def capture(points, names, **kwargs):
        observed.append(kwargs['anatomy_reference'].copy())
        return original(points, names, **kwargs)
    monkeypatch.setattr(rig_playback, 'validate_physical_motion', capture)
    result = rig_playback.validate_rig_playback(payload)
    assert result['passed'], result
    np.testing.assert_allclose(observed[-1][::4], source, atol=1e-12)
    assert physical_validation.physical_metrics_from_payload(payload)['passed']
    # Missing material-frame authority is still rejected by actual geometry,
    # independently of the perfectly usable source anatomy reference.
    unknown = deepcopy(payload)
    unknown['sourceFootSupportEvidence']['bodySupport']['status'] = 'unresolved'
    rejected = rig_playback.validate_rig_playback(unknown)
    assert not rejected['passed'] and not rejected['bodySupport']['passed']


def test_contact_interpolation_does_not_join_different_observed_anchors():
    from exercise_motion_pkg.contact_constraints import interpolated_contact_mask

    pinned = np.ones((4, 1), dtype=bool)
    identities = np.array([['stance-a'], ['stance-a'], ['stance-b'], ['stance-b']], dtype=object)
    mask = interpolated_contact_mask(pinned, np.array([0, 1, 2, 3]),
                                     np.array([1, 2, 3, 0]), identities)
    assert mask[:, 0].tolist() == [True, False, True, False]
    # Observed knots stay constrained even when the next interval has another anchor.
    assert interpolated_contact_mask(pinned, np.arange(4), np.arange(4), identities).all()
def test_calibrated_ankle_point_outlasts_sole_patch_without_extending_contact():
    from exercise_motion_pkg.rig_playback import rig_contact_targets
    from exercise_motion_pkg.sequence_stabilization import contact_mask
    rig = rig_payload(8)
    names = rig['jointNames']
    points = decode_rig(rig, rig['coordinates'])
    ankle, foot = [names.index('right_' + part) for part in ('ankle', 'foot')]
    points[:, ankle, 1] += .04
    points[5:, [ankle, foot], 0] += .2
    evidence = {'contacts': [
        {'jointName': 'right_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'surfaceKind': 'ground', 'startFrame': 0, 'endFrame': 2, 'ankleAnchorGroupId': 'stance-a'},
        {'jointName': 'right_ankle', 'contactMotion': 'stationary', 'startFrame': 1, 'endFrame': 3},
        {'jointName': 'right_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'surfaceKind': 'ground', 'startFrame': 5, 'endFrame': 7, 'ankleAnchorGroupId': 'stance-b'}],
        'footPatchEvidence': {'available': True, 'feet': {'right': {
            'states': ['full_sole'] * 3 + ['unknown', 'airborne'] + ['full_sole'] * 3}}},
        '_fitFrameStateIndices': list(range(8))}
    pinned = contact_mask({'sourceFootSupportEvidence': evidence}, names, 8)
    original_mask = pinned.copy()
    floor = float(points[0, foot, 1])
    targets, _ = rig_contact_targets(points, names, pinned, rig['offsets'], evidence=evidence,
                                     floor=floor, rest_pitches={'right': -.2})
    np.testing.assert_allclose(targets[:4, ankle], np.broadcast_to(targets[0, ankle], (4, 3)), atol=1e-12)
    assert not pinned[3, foot] and pinned[3, ankle]
    assert not pinned[4, ankle] and targets[5, ankle, 0] != targets[0, ankle, 0]
    rebuilt, _ = rig_contact_targets(targets, names, pinned, rig['offsets'], evidence=evidence,
                                     floor=floor, rest_pitches={'right': -.2})
    np.testing.assert_allclose(rebuilt[pinned], targets[pinned], atol=1e-12)
    np.testing.assert_array_equal(pinned, original_mask)
