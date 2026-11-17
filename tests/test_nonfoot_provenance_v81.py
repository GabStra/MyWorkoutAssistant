from copy import deepcopy
import json
from exercise_motion_pkg.bake_and_rank import load_verified_source_pose_reference
from exercise_motion_pkg.body_support_observation import materialize_ankle_support
from exercise_motion_pkg.contact_constraints import _fit_local_timed_support_evidence, is_observed_support_contact, observed_support_contact_mask
from nonfoot_support_fixture import FPS, build_nonfoot_support_fixture

def fixture(tmp_path, sample_frames=(0, 6)):
    return build_nonfoot_support_fixture(tmp_path, sample_frames=sample_frames)

def test_producer_emits_exact_singleton_rows_not_a_bridged_span(tmp_path):
    video,_,reference,p=fixture(tmp_path); e=p['sourceFootSupportEvidence']; materialize_ankle_support(p,reference,source_video_path=video)
    cs=e['supportContacts']; assert len(cs)==2 and [c['nonFootSupportReceipt']['rowId'] for c in cs]==['left-ankle-0','left-ankle-6']
    assert all(c['sourcePoseStartTimeSec']==c['sourcePoseEndTimeSec'] and is_observed_support_contact(c,e) for c in cs)
    mapped=_fit_local_timed_support_evidence(p,deepcopy(e)); mask=observed_support_contact_mask(mapped,['left_ankle'],12)
    assert mask[:,0].nonzero()[0].tolist()==[0,6]

def test_bad_trackhash_stale_pose_and_missing_reference_fail_closed(tmp_path):
    video,ref,reference,p=fixture(tmp_path); e=p['sourceFootSupportEvidence']; materialize_ankle_support(p,reference,source_video_path=video); c=deepcopy(e['supportContacts'][0])
    c['nonFootSupportReceipt']['sourcePoseTrackProof']['sourcePoseTrackSha256']='0'*64; assert not is_observed_support_contact(c,e)
    edited=json.loads(ref.read_text());
    for i,f in enumerate(edited['pose']['frames']): f['joints']['left_ankle']=[.1+.8*i/11,.8]
    ref.write_text(json.dumps(edited)); assert not is_observed_support_contact(e['supportContacts'][0],e)
    moving=load_verified_source_pose_reference(ref,video); p2=deepcopy(p); materialize_ankle_support(p2,moving,source_video_path=video); assert p2['sourceFootSupportEvidence']['supportContacts']==[]
    ref.unlink(); p3=deepcopy(p); materialize_ankle_support(p3,reference,source_video_path=video); assert p3['sourceFootSupportEvidence']['supportContacts']==[]

def test_wrong_top_digest_without_lineage_rejected(tmp_path):
    video,_,reference,p=fixture(tmp_path); e=p['sourceFootSupportEvidence']; materialize_ankle_support(p,reference,source_video_path=video); c=e['supportContacts'][0]
    e['sourceVideoSha256']='b'*64; assert not is_observed_support_contact(c,e)

def test_bad_interval_and_camera_gate_are_rejected(tmp_path):
    from exercise_motion_pkg.controlled_motion import source_support_authority
    video,_,reference,p=fixture(tmp_path); e=p['sourceFootSupportEvidence']; materialize_ankle_support(p,reference,source_video_path=video)
    bad=deepcopy(e['supportContacts'][0]); bad['sourcePoseEndTimeSec'] += .2
    assert not is_observed_support_contact(bad,e)
    result=source_support_authority({'groundContactMode':'unknown'},e,{})
    assert result['status']=='unresolved' and 'retained_source_camera_authority_unavailable' in result['unresolvedReasons']


def test_legacy_torso_exception_is_preserved(tmp_path):
    from exercise_motion_pkg.controlled_motion import source_support_authority
    _video,_ref,reference,p=fixture(tmp_path); e=p['sourceFootSupportEvidence']
    torso=deepcopy(e); torso['supportContacts']=[]
    torso['bodySupport']={'required':True,'status':'confirmed','stationaryJoints':['pelvis']}
    torso['bodySupportObservation']['observation']={'pelvis':'stationary_support','pelvisContactSurface':'bench'}
    torso['bodySupportObservation']['contactTimeline']['samples']=[]
    result=source_support_authority({'groundContactMode':'unknown'},torso,{})
    assert result['bodySupportConfirmed'] is True


def test_selected_parent_clock_maps_only_observed_singletons(tmp_path):
    video,_ref,reference,p=fixture(tmp_path); e=p['sourceFootSupportEvidence']; materialize_ankle_support(p,reference,source_video_path=video)
    digest=e['sourceVideoSha256']; parent='c'*64
    mapping={'schemaVersion':1,'verified':True,'mappingKind':'selected_segment_to_parent_source',
      'selectedSegmentSha256':digest,'parentSourceSha256':parent,
      'selectedFrameClockReceiptSha256':'d'*64,'sourcePosePayloadSha256':'e'*64,
      'selectedStartSeconds':10.,'selectedFrameCount':12,'parentSourceFps':FPS,
      'selectedFrameLineage':[{'selectedFrameIndex':i,'selectedFrameTimeSec':i/FPS,
       'parentSourceFrameIndex':300+i,'parentSourceTimeSec':10.+i/FPS} for i in range(12)]}
    p['sourcePoseCameraReference']={'sourceTimelineMapping':mapping}
    for i,f in enumerate(p['frames']): f['sourceTimeSec']=10.+i/FPS
    mapped=_fit_local_timed_support_evidence(p,deepcopy(e))
    mask=observed_support_contact_mask(mapped,['left_ankle'],12)
    assert mask[:,0].nonzero()[0].tolist()==[0,6]

def test_missing_source_video_path_does_not_create_a_receipt(tmp_path):
    _video,_ref,reference,p=fixture(tmp_path)
    materialize_ankle_support(p,reference)
    assert p['sourceFootSupportEvidence']['supportContacts']==[]
