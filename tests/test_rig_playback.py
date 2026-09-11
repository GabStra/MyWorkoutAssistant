import json
from pathlib import Path
import numpy as np
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
         'startRatio': 0., 'endRatio': 1.} for side in ('left', 'right')]}
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
