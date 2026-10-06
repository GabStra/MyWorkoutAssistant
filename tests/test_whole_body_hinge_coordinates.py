import numpy as np

from exercise_motion_pkg.whole_body_repair import HingeCoordinates


def test_hinge_cannot_switch_branch_when_endpoint_crosses_old_bend_direction():
    names=['right_hip','right_knee','right_ankle']
    source=np.tile([[0.,0.,0.],[0.,-.3,.4],[0.,-.6,0.]],(3,1,1))
    hinges=HingeCoordinates(source,names,np.zeros((3,3),dtype=bool))
    proposed=source.copy()
    angle=np.deg2rad([89.,90.,91.])
    proposed[:,2]=np.column_stack([np.zeros(3),-.6*np.cos(angle),.6*np.sin(angle)])
    result=hinges.apply(proposed)
    np.testing.assert_allclose(np.linalg.norm(result[:,1]-result[:,0],axis=1),.5,atol=1e-10)
    np.testing.assert_allclose(np.linalg.norm(result[:,2]-result[:,1],axis=1),.5,atol=1e-10)
    assert np.max(np.linalg.norm(np.diff(result[:,1],axis=0),axis=1))<.02


def test_near_straight_source_noise_does_not_flip_the_hinge():
    names=['right_hip','right_knee','right_ankle']
    source=np.tile([[0.,1.,0.],[0.,.5,0.],[0.,0.,0.]],(5,1,1))
    source[:,1,2]=[1e-5,-1e-5,1e-5,-1e-5,1e-5]
    hinges=HingeCoordinates(source,names,np.zeros((5,3),dtype=bool))
    proposed=source.copy()
    proposed[:,2,1]=.05
    result=hinges.apply(proposed)
    assert np.max(np.linalg.norm(np.diff(result[:,1],axis=0),axis=1))<1e-8


def test_ankle_contacts_remain_fixed_while_hinge_is_reconstructed():
    names=['right_hip','right_knee','right_ankle']
    source=np.tile([[0.,0.,0.],[0.,-.3,.4],[0.,-.6,0.]],(3,1,1))
    pinned=np.zeros((3,3),dtype=bool)
    pinned[:,2]=True
    hinges=HingeCoordinates(source,names,pinned)
    result=hinges.apply(source.copy(),np.full((3,1),np.deg2rad(50.)))
    np.testing.assert_array_equal(result[:,2],source[:,2])
    assert np.all(result[:,1,2]>0.)


def test_matching_angles_do_not_allow_opposite_knee_branch():
    from exercise_motion_pkg.physical_validation import validate_physical_motion
    joints={'pelvis':(0.,1.,0.),'neck':(0.,2.,0.),
            'left_shoulder':(-.3,1.8,0.),'right_shoulder':(.3,1.8,0.),
            'left_hip':(-.3,1.,0.),'right_hip':(0.,1.,0.),
            'right_knee':(.3,.5,0.),'right_ankle':(0.,0.,0.),'right_foot':(0.,0.,.2)}
    names=list(joints)
    source=np.tile(list(joints.values()),(5,1,1))
    proposed=source.copy()
    proposed[:,names.index('right_knee'),0]=-.3
    report=validate_physical_motion(proposed,names,reference=source)
    assert 'repair_hinge_branch_flip' in report['reasons']
    assert 'repair_articulation_distortion' not in report['reasons']


def test_near_straight_contact_fit_converges_inside_anatomical_limits():
    import json
    from pathlib import Path
    from exercise_motion_pkg.models import MotionClip,MotionFrame
    from exercise_motion_pkg.whole_body_repair import repair_whole_body
    fixture=json.loads((Path(__file__).parent/'fixtures/whole_body_standing_contacts.json').read_text())
    # Isolate the near-extension numerical case from motion-window boundaries.
    # Dynamic branch continuity is covered separately, and by the full-clip canary.
    def clip(key):
        return MotionClip(fixture['fps'],fixture['jointNames'],
                          [MotionFrame(i/fixture['fps'],fixture[key][1]) for i in range(3)],
                          metadata={'contactSourceHingeBounds':{k:[v[1]]*3 for k,v in fixture['bounds'].items()}})
    result,report=repair_whole_body(clip('reference'),clip('proposal'),{'contacts':fixture['contacts']})
    assert report['applied'],report
    assert report['maximumBoneLengthErrorMeters']<=.002
    assert report['maximumContactErrorMeters']==0.
    assert report['validation']['passed']


def test_final_spike_check_includes_hinges_not_only_wrist_and_ankle_endpoints():
    from exercise_motion_pkg.temporal_quality import introduced_joint_spikes
    frames=[]
    for i in range(3):
        source={'pelvis':[0.,1.,0.],'right_knee':[0.,.5,0.],
                'right_ankle':[0.,0.,0.],'neck':[0.,1.8,0.]}
        joints={k:list(v) for k,v in source.items()}
        if i==1:
            joints['right_knee'][0]=.15
        frames.append({'timeSec':i/30.,'sourceJoints':source,'joints':joints})
    report=introduced_joint_spikes({'frames':frames})
    assert report['severe']
    assert report['events'][0]['joint']=='right_knee'
