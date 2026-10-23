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
         'sharedSupportPlaneY': .8}
    placed = normalize_scene_placement(original)
    assert placed['scenePlacement']['orientationReason'] == 'consistent_extended_supported_stance'
    assert placed['scenePlacement']['rotationDegrees'] > 1.
    joints = placed['frames'][0]['joints']
    up = np.array(joints['neck']) - (np.array(joints['left_ankle']) + joints['right_ankle'])/2
    np.testing.assert_allclose(up[[0, 2]], 0., atol=1e-12)
    assert validate_rig_playback(placed)['passed']


def test_fractional_rotation_preserves_lengths_and_detects_hidden_contact_slip():
    rig=rig_payload(2);values=np.array(rig['coordinates']);points=decode_rig(rig,values)
    root=rig['jointNames'].index('pelvis');foot=rig['jointNames'].index('left_foot');anchor=points[0,foot]
    rotation=Rotation.from_euler('y',np.pi/2)
    values[1,:3]=rotation.apply(values[0,:3]-anchor)+anchor
    slot=3+3*rig['rotationJointNames'].index('pelvis')
    values[1,slot:slot+3]=(rotation*Rotation.from_rotvec(values[0,slot:slot+3])).as_rotvec()
    rig['coordinates']=values.tolist();p=export(rig)
    np.testing.assert_allclose(p['frames'][0]['joints']['left_foot'],p['frames'][1]['joints']['left_foot'],atol=1e-12)
    p['sourceFootSupportEvidence']={'contacts':[{'jointName':'left_foot','contactState':'toe_only','contactMotion':'stationary','startRatio':0.,'endRatio':1.}]}
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
        'contactState':'toe_only','contactMotion':'stationary','startRatio':0.,'endRatio':1.}]}
    report=validate_rig_playback(payload)
    assert not report['passed']
    assert abs(report['maximumContactErrorMeters']-.01)<1e-10


def test_supported_playback_uses_the_validated_support_anatomy_reference(monkeypatch):
    from types import SimpleNamespace

    from exercise_motion_pkg import body_support_observation, equipment_constraints
    from exercise_motion_pkg import foot_geometry, heel_contacts, loop_seam
    from exercise_motion_pkg import rig_playback, support_alignment, support_geometry
    from exercise_motion_pkg.physical_validation import validate_physical_motion
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    names = payload['jointNames']
    supported = decode_rig(payload['fixedRig'], payload['fixedRig']['coordinates'])
    raw = supported.copy()
    raw[:, names.index('neck'), 0] += .04
    for frame, controlled in zip(payload['frames'], raw):
        frame['controlledSourceJoints'] = dict(zip(names, controlled.tolist()))
        frame['controlledArticulationReferenceJoints'] = dict(zip(names, controlled.tolist()))

    keyframe_gate = validate_physical_motion(
        supported, names, reference=supported, anatomy_reference=supported, fps=30.)
    assert keyframe_gate['passed'], keyframe_gate

    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support',
                        lambda _: {'bodySupport': {'required': True}})
    monkeypatch.setattr(support_geometry, 'validated_support_reference',
                        lambda _: (supported, None))
    monkeypatch.setattr(rig_playback, 'contact_mask',
                        lambda *_args, **_kwargs: np.zeros((len(payload['frames']), len(names)), dtype=bool))
    monkeypatch.setattr(heel_contacts, 'heel_contact_tracks', lambda *_args, **_kwargs:
                        SimpleNamespace(pairs=[], residual=lambda *_a: np.empty((0, 3))))
    monkeypatch.setattr(loop_seam, 'seam_quality_metrics',
                        lambda *_args, **_kwargs: {'seamContinuous': True})
    monkeypatch.setattr(equipment_constraints, 'validate_grip', lambda *_: {'passed': True})
    monkeypatch.setattr(support_geometry, 'validate_support_geometry', lambda *_: {'passed': True})
    monkeypatch.setattr(support_geometry, 'validate_supported_shoe_orientation', lambda *_: {'passed': True})
    monkeypatch.setattr(foot_geometry, 'validate_material_shoes', lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(support_alignment, 'validate_payload_alignment', lambda *_: {'passed': True})

    observed = {}

    def validate_with_capture(points, joint_names, *, reference=None, anatomy_reference=None,
                              fps=30., support_mask=None):
        observed['reference'] = reference
        observed['anatomy_reference'] = anatomy_reference
        return validate_physical_motion(
            points, joint_names, reference=reference, anatomy_reference=anatomy_reference,
            fps=fps, support_mask=support_mask)

    monkeypatch.setattr(rig_playback, 'validate_physical_motion', validate_with_capture)
    report = rig_playback.validate_rig_playback(payload)

    assert report['passed'], report
    np.testing.assert_allclose(observed['reference'][::4], supported)
    np.testing.assert_allclose(observed['anatomy_reference'][::4], supported)
    assert not np.allclose(observed['reference'][::4], raw)


@pytest.mark.parametrize(('reference', 'reference_error', 'expected_reason'), [
    (None, 'support_corrected_reference_unavailable', 'support_corrected_reference_unavailable'),
    (np.zeros((1, 1)), None, 'support_corrected_reference_invalid'),
])
def test_supported_playback_fails_closed_when_validated_reference_is_unavailable(
        monkeypatch, reference, reference_error, expected_reason):
    from exercise_motion_pkg import body_support_observation, support_geometry

    payload = export(rig_payload(8))
    monkeypatch.setattr(body_support_observation, 'materialize_stationary_sole_support',
                        lambda _: {'bodySupport': {'required': True}})
    monkeypatch.setattr(support_geometry, 'validated_support_reference',
                        lambda _: (reference, reference_error))

    report = validate_rig_playback(payload)

    assert not report['passed']
    assert report['reason'] == expected_reason
    assert report['physicalReasons'] == [expected_reason]
