import copy
import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.physical_validation import (
    physical_metrics_from_payload, segment_distance, support_balance, validate_physical_motion,
)
from exercise_motion_pkg.whole_body_repair import contact_pins, repair_whole_body


@pytest.fixture
def poses():
    data = json.loads((Path(__file__).parent / 'fixtures/thruster_contact_frame83.json').read_text())
    names = list(data['source'])
    return names, *(np.repeat(np.array([[pose[n] for n in names]]), 5, axis=0)
                    for pose in (data['source'], data['broken']))


def test_frame83_rejected_even_when_frozen_and_perfectly_smooth(poses):
    names, source, broken = poses
    report = validate_physical_motion(broken, names, reference=source)
    assert not report['passed']
    assert {'ankle_collapse', 'repair_articulation_distortion'} <= set(report['reasons'])
    assert any(e.get('joint') == 'left_hip' for e in report['events'])
    assert any(e.get('joint') == 'right_ankle' for e in report['events'])
    assert validate_physical_motion(source, names, reference=source)['passed']


def test_source_coordinate_rotation_does_not_change_articulation_verdict(poses):
    names, source, _ = poses
    from scipy.spatial.transform import Rotation
    transformed = source @ Rotation.from_euler('y', 127, degrees=True).as_matrix().T + [4., -7., 2.]
    assert validate_physical_motion(transformed, names, reference=source)['passed']


def test_support_screen_excludes_airborne_frames(poses):
    names, source, _ = poses
    shifted = source.copy()
    shifted[:, names.index('neck'), 0] += 3.
    report, outside = support_balance(shifted, names, 30., np.zeros(5, dtype=bool))
    assert not report['available']
    assert not np.any(outside)


def test_segment_collision_handles_crossing_and_parallel_segments():
    assert segment_distance(np.array([-1.,0,0]),np.array([1.,0,0]),
                            np.array([0.,-1,0]),np.array([0.,1,0])) == pytest.approx(0.)
    assert segment_distance(np.array([-1.,0,0]),np.array([1.,0,0]),
                            np.array([-1.,1,0]),np.array([1.,1,0])) == pytest.approx(1.)


def test_contact_release_and_rolling_are_not_pinned(poses):
    names, source, _ = poses
    evidence = {'contacts': [
        {'jointName':'left_foot', 'contactState':'full_sole', 'contactMotion':'stationary', 'startFrame':0, 'endFrame':1},
        {'jointName':'right_foot', 'contactState':'toe_only', 'contactMotion':'rolling', 'startFrame':0, 'endFrame':4},
    ]}
    pinned, _ = contact_pins(source, source.copy(), names, evidence)
    assert pinned[:2, names.index('left_ankle')].all()
    assert not pinned[2:].any()
    assert not pinned[:, names.index('right_foot')].any()


def test_valid_proposal_is_not_needlessly_optimized(poses):
    names, source, _ = poses
    clip = MotionClip(30., names, [MotionFrame(i/30., dict(zip(names,map(tuple,frame)))) for i,frame in enumerate(source)])
    result, report = repair_whole_body(clip, copy.deepcopy(clip), None)
    assert report['applied']
    assert result.frames == clip.frames
    assert 'evaluations' not in report


def test_final_kinematic_gate_blocks_smooth_impossible_pose(poses):
    from exercise_motion_pkg.bake_and_rank import compute_kinematic_plausibility_metrics_from_payload
    names, source, broken = poses
    payload = {'jointNames':names, 'fps':30., 'frames':[
        {'timeSec':i/30.,'joints':dict(zip(names,frame.tolist())),
         'sourceJoints':dict(zip(names,source[i].tolist()))} for i,frame in enumerate(broken)]}
    metrics = compute_kinematic_plausibility_metrics_from_payload(payload)
    assert metrics['severeArtifact']
    assert 'physical_pose_constraint_violation' in metrics['artifactReasons']
    assert metrics['jointAngleStep']['score'] == 1.


def test_failed_repair_is_not_accepted_because_original_pose_is_smooth(poses):
    from exercise_motion_pkg.bake_and_rank import compute_kinematic_plausibility_metrics_from_payload
    names, source, _ = poses
    payload = {'jointNames':names, 'fps':30., 'frames':[
        {'timeSec':i/30.,'joints':dict(zip(names,frame.tolist()))} for i,frame in enumerate(source)],
        'postBakeForefootContactConstraint':{'requiresReconstruction':True}}
    metrics = compute_kinematic_plausibility_metrics_from_payload(payload)
    assert 'physical_contact_repair_rejected' in metrics['artifactReasons']


def test_whole_body_solver_repairs_bad_knees_without_moving_contact_targets(poses,monkeypatch):
    from exercise_motion_pkg import physical_validation
    monkeypatch.setattr(physical_validation,'support_balance',
                        lambda points,*args,**kwargs: ({'available':True},np.ones(len(points))))
    names, source, broken = poses
    source=source[:3]
    proposed=source.copy()
    for name in ('left_knee','right_knee'):
        proposed[:,names.index(name)]=broken[:3,names.index(name)]
    def clip(points):
        return MotionClip(30.,names,[MotionFrame(i/30.,dict(zip(names,map(tuple,frame)))) for i,frame in enumerate(points)])
    evidence={'contacts':[{'jointName':s+'_foot','contactState':'toe_only','contactMotion':'stationary',
                           'startRatio':0.,'endRatio':1.} for s in ('left','right')]}
    result,report=repair_whole_body(clip(source),clip(proposed),evidence,max_evaluations=8)
    assert report['applied'],report
    assert report['maximumContactErrorMeters']==0.
    assert report['maximumBoneLengthErrorMeters']<.002
    assert report['validation']['passed']
    assert report['validation']['balance']['advisoryWarning']


def test_constant_bone_stretch_is_rejected_even_without_temporal_variation(poses):
    names, source, _ = poses
    stretched=source*1.2
    report=validate_physical_motion(stretched,names,reference=source)
    assert 'repair_bone_length_distortion' in report['reasons']


def test_balance_is_advisory_and_cannot_override_anatomical_failure():
    from exercise_motion_pkg.acceptance import decide_acceptance
    options={'metrics':{'physical':{'available':True}},'review':{'passed':True},'review_rejections':[]}
    decision=decide_acceptance(**options,deterministic_rejections=['physical_balance_requires_review'])
    assert decision.status=='valid'
    decision=decide_acceptance(**options,deterministic_rejections=[
        'physical_balance_requires_review','physical_pose_constraint_violation'])
    assert decision.status=='invalid'


def test_balance_warning_does_not_trigger_repair_or_final_rejection(poses,monkeypatch):
    from exercise_motion_pkg import physical_validation
    from exercise_motion_pkg.bake_and_rank import compute_kinematic_plausibility_metrics_from_payload
    names,source,_=poses
    monkeypatch.setattr(physical_validation,'support_balance',
                        lambda points,*args,**kwargs: ({'available':True},np.ones(len(points))))
    clip=MotionClip(30.,names,[MotionFrame(i/30.,dict(zip(names,map(tuple,frame)))) for i,frame in enumerate(source)])
    result,report=repair_whole_body(clip,copy.deepcopy(clip),None)
    assert report['applied']
    assert 'evaluations' not in report
    assert report['validation']['balance']['advisoryWarning']
    assert result.frames==clip.frames
    payload={'jointNames':names,'fps':30.,'frames':[
        {'timeSec':i/30.,'joints':dict(zip(names,frame.tolist()))} for i,frame in enumerate(source)]}
    metrics=compute_kinematic_plausibility_metrics_from_payload(payload)
    assert metrics['physicalConstraints']['balance']['advisoryWarning']
    assert not metrics['severeArtifact']
    payload['postBakeForefootContactConstraint']={'requiresReconstruction':True,
        'wholeBodyRepair':{'reason':'whole_body_balance_requires_review'}}
    assert not compute_kinematic_plausibility_metrics_from_payload(payload)['severeArtifact']


def test_solver_timeout_retains_original_and_requests_reconstruction(poses):
    names,source,broken=poses
    def clip(points):
        return MotionClip(30.,names,[MotionFrame(i/30.,dict(zip(names,map(tuple,frame)))) for i,frame in enumerate(points)])
    original=clip(source)
    evidence={'contacts':[{'jointName':'left_foot','contactState':'full_sole','contactMotion':'stationary',
                           'startRatio':0.,'endRatio':1.}]}
    result,report=repair_whole_body(original,clip(broken),evidence,timeout_seconds=0.)
    assert result is original
    assert report['requiresReconstruction']
    assert report['reason']=='whole_body_repair_timeout'
