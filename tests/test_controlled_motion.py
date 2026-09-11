import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig, body_relative_points, controlled_target, fit_controlled_motion


def stance(count=45):
    fixture=json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names=list(fixture['joints'])
    points=np.tile(np.array([fixture['joints'][n] for n in names]),(count,1,1))
    return names,points


def payload(names,points,fps=30.):
    return {'fps':fps,'jointNames':names,'frames':[{'timeSec':i/fps,'joints':dict(zip(names,p.tolist()))}
                                                for i,p in enumerate(points)]}


def test_rig_has_constant_bones_and_fixed_sockets_under_arbitrary_rotation():
    names,points=stance()
    rig=FixedRig(points,names)
    values=rig.initial.copy()
    values+=np.random.default_rng(31).normal(0,.1,values.shape)
    result=rig.decode(values)
    for j in rig.order[1:]:
        np.testing.assert_allclose(np.linalg.norm(result[:,j]-result[:,rig.parents[j]],axis=1),
                                   np.linalg.norm(rig.offsets[j]),atol=1e-12)
    for a,b in [('left_hip','right_hip'),('left_collar','right_collar')]:
        distances=np.linalg.norm(result[:,names.index(a)]-result[:,names.index(b)],axis=1)
        assert np.ptp(distances)<1e-12


def test_positive_kernel_does_not_rebound_at_a_stop():
    names,points=stance(120)
    travel=np.minimum(np.arange(120)/60.,1.)*.5
    points[:,:,0]+=travel[:,None]
    target,_,_=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.all(np.diff(target[:,root,0])>=-1e-10)
    assert target[:,root,0].max()<=points[:,root,0].max()+1e-10
    assert target[:,root,0].min()>=points[:,root,0].min()-1e-10


def test_sideways_travel_and_asymmetry_are_preserved_and_rotation_equivariant():
    names,points=stance(90)
    points[:,:,0]+=np.arange(90)[:,None]*.005
    points[:,names.index('left_wrist'),2]+=.1
    target,_,_=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.ptp(target[:,root,0])>.95*np.ptp(points[:,root,0])
    rotation=Rotation.from_euler('xyz',[.2,.6,-.3]).as_matrix()
    rotated,_,_=controlled_target(points@rotation,names,30.)
    np.testing.assert_allclose(rotated,target@rotation,atol=1e-9)
    np.testing.assert_allclose(target[:,names.index('left_wrist')]-target[:,root],
                               points[:,names.index('left_wrist')]-points[:,root],atol=1e-10)


def test_small_subordinate_deviations_reduce_without_a_world_axis_lock():
    names,points=stance(120)
    t=np.arange(120)/30.
    points[:,:,1]+=(.15*np.sin(2*np.pi*.5*t))[:,None]
    points[:,:,0]+=(.008*np.sin(2*np.pi*2.5*t))[:,None]
    target,_,evidence=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.std(target[20:-20,root,0])<np.std(points[20:-20,root,0])*.7
    assert np.ptp(target[:,root,1])>.9*np.ptp(points[:,root,1])
    assert evidence['maximumMinorDeviationCorrectionMeters']>0


def test_fit_preserves_contact_and_rig_and_is_reusable():
    names,points=stance(30)
    rng=np.random.default_rng(13)
    head=names.index('head')
    points[:,head,0]+=rng.normal(0,.002,len(points))
    p=payload(names,points)
    p['sourceFootSupportEvidence']={'contacts':[{'jointName':s+'_foot','contactState':'full_sole',
                                               'contactMotion':'stationary','startRatio':0.,'endRatio':1.}
                                              for s in ('left','right')]}
    result,report=fit_controlled_motion(p,max_evaluations=25,timeout_seconds=60.)
    assert report['applied'],report
    assert report['maximumBoneLengthVariationMeters']<1e-10
    assert report['maximumContactErrorMeters']<.0005
    assert report['jerkAfter']<report['jerkBefore']
    assert report['settlingPreserved']
    assert all(report['checks'].values())
    result['controlledMotionFit']=report
    again,audit=fit_controlled_motion(result)
    assert again is result and audit['reused']


def test_timeout_and_irregular_sampling_return_original():
    names,points=stance(10)
    p=payload(names,points)
    result,report=fit_controlled_motion(p,timeout_seconds=0.)
    assert result is p and report['reason']=='fit_timeout'
    p['frames'][3]['timeSec']+=.01
    result,report=fit_controlled_motion(p)
    assert result is p and report['reason']=='irregular_sampling'


def test_small_monotonic_motion_is_not_a_hold():
    names,points=stance(90)
    joint=names.index('head')
    points[:,joint,0]+=np.arange(90)*.0001
    _,holds,_=controlled_target(points,names,30.)
    assert np.max(holds[10:-10,joint])<1e-10


def test_hold_coordinates_ignore_rigid_body_turns():
    names,points=stance(45)
    rotations=Rotation.from_euler('y',np.linspace(0.,.6,len(points))[:,None]).as_matrix()
    turned=np.einsum('fij,fkj->fki',rotations,points)
    np.testing.assert_allclose(body_relative_points(turned,names),body_relative_points(points,names),atol=1e-10)


def test_jump_releases_feet_and_preserves_height():
    names,points=stance(48)
    rig=FixedRig(points,names)
    points=rig.decode(rig.initial)
    phase=np.linspace(0.,np.pi,28)
    points[10:38,:,1]+=(.22*np.sin(phase))[:,None]
    p=payload(names,points)
    p['sourceFootSupportEvidence']={'contacts':[
        {'jointName':side+'_foot','contactState':'full_sole','contactMotion':'stationary',
         'startFrame':start,'endFrame':end}
        for side in ('left','right') for start,end in [(0,9),(38,47)]]}
    result,report=fit_controlled_motion(p)
    assert report['applied'],report
    track=np.array([f['joints']['pelvis'] for f in result['frames']])
    assert np.ptp(track[:,1])>.19
    assert report['maximumContactErrorMeters']<.0005


def test_small_slow_articulation_survives_full_fit():
    names,points=stance(60)
    rig=FixedRig(points,names)
    values=rig.initial.copy()
    slot=rig.slots[names.index('head')]
    values[:,slot]+=.07*np.sin(np.linspace(0.,2*np.pi,len(points)))
    points=rig.decode(values)
    result,report=fit_controlled_motion(payload(names,points))
    assert report['applied'],report
    fitted=np.array([[f['joints'][n] for n in names] for f in result['frames']])
    first=body_relative_points(points,names)[:,names.index('head')]
    last=body_relative_points(fitted,names)[:,names.index('head')]
    assert np.linalg.norm(np.ptp(last,axis=0))>.8*np.linalg.norm(np.ptp(first,axis=0))


def test_excursion_constraint_protects_large_range_without_locking_small_motion():
    from exercise_motion_pkg.controlled_motion import excursion_constraints
    names,points=stance(60)
    root=names.index('pelvis');wrist=names.index('left_wrist');head=names.index('head')
    phase=np.arange(60)*2*np.pi/60
    points[:,wrist,0]+=.2*np.sin(phase)
    points[:,head,0]+=.002*np.sin(phase)
    center,direction,minimum,active=excursion_constraints(points,root,1.)
    assert active[:,wrist].any()
    assert not active[:,head].any()
    relative=points-points[:,root:root+1]
    projection=np.sum((relative-center)*direction,axis=-1)
    assert np.all(projection[active]>=minimum[active])
    compressed=center+.5*(relative-center)
    assert np.all(np.sum((compressed-center)*direction,axis=-1)[active]<minimum[active])
    rotation=Rotation.from_euler('xyz',[.2,.5,.8]).as_matrix()
    c,d,m,a=excursion_constraints(points@rotation,root,1.)
    np.testing.assert_allclose(c,center@rotation,atol=1e-12)
    np.testing.assert_allclose(m,minimum,atol=1e-12)
    np.testing.assert_array_equal(a,active)
    np.testing.assert_allclose(d[:,wrist],direction[:,wrist]@rotation,atol=1e-12)


def test_downward_bone_does_not_invent_axial_half_turns():
    from exercise_motion_pkg.controlled_motion import transported_bone_rotations
    phase=np.linspace(0.,2*np.pi,80)
    directions=np.column_stack([.001*np.cos(phase),-np.ones(80),.001*np.sin(phase)])
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    rotations=transported_bone_rotations(directions)
    np.testing.assert_allclose(rotations.apply(np.tile([0.,1.,0.],(80,1))),directions,atol=1e-12)
    changes=(rotations[:-1].inv()*rotations[1:]).magnitude()
    observed=np.arccos(np.clip(np.sum(directions[:-1]*directions[1:],axis=1),-1.,1.))
    np.testing.assert_allclose(changes,observed,atol=1e-10)
    assert np.rad2deg(changes.max())<.01


def test_vectorized_hinge_frames_match_the_final_branch_validator():
    from exercise_motion_pkg.controlled_motion import hinge_coordinates,transported_hinge_dots
    from exercise_motion_pkg.physical_validation import ARTICULATIONS
    from exercise_motion_pkg.structural_refinement import _local_hinge_bend
    from exercise_motion_pkg.models import MotionFrame
    names,points=stance(3)
    parent,bend,sine=hinge_coordinates(points,names)
    specs=[s for s in ARTICULATIONS if s[0].endswith(('_knee','_elbow'))]
    for index,(_,a,h,b,_) in enumerate(specs):
        expected=_local_hinge_bend(MotionFrame(0.,dict(zip(names,map(tuple,points[0])))),a,h,b)
        if expected is not None:
            np.testing.assert_allclose(parent[0,index],expected[0],atol=1e-12)
            np.testing.assert_allclose(bend[0,index],expected[1],atol=1e-12)
    dots=transported_hinge_dots(parent,bend,parent,-bend)
    np.testing.assert_allclose(dots[sine>1e-8],-1.,atol=1e-12)


def test_fit_budget_scales_with_frames_and_preserves_explicit_limits():
    from exercise_motion_pkg.controlled_motion import fit_time_budget
    assert fit_time_budget({'frames':[None]*60})==150.
    assert fit_time_budget({'frames':[None]*146})==219.
    assert fit_time_budget({'frames':[None]*240})==300.
    assert fit_time_budget({'frames':[None]*2000})==300.
    assert fit_time_budget({'frames':[None]*240},60.)==60.
    assert fit_time_budget({'frames':[None]*240},0.)==0.


def test_solver_can_move_a_tiny_nonzero_rotation():
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    from scipy.sparse import csr_matrix
    names,points=stance(1)
    rig=FixedRig(points,names)
    slot=rig.slots[names.index('left_ankle')]
    base=rig.initial.copy()
    base[:,:3]+=[2.,3.,4.]
    def decode(values):
        coordinates=base.copy()
        coordinates[0,slot]=values[0]
        coordinates[0,2]+=values[1]
        return rig.decode(coordinates).ravel()
    expected=np.array([.02,.11])
    target=decode(expected)
    probes=[]
    def residual(values):
        probes.append(values.copy())
        return decode(values)-target
    initial=np.array([5e-16,.1])
    solved=solve_trajectory(residual,initial,csr_matrix(np.ones((len(target),2))),25)
    np.testing.assert_allclose(solved.x,expected,atol=1e-6)
    first_rotation_probe=next(v for v in probes if v[0]!=initial[0] and v[1]==initial[1])
    derivative=(decode(first_rotation_probe)-decode(initial))/(first_rotation_probe[0]-initial[0])
    assert np.linalg.norm(derivative)>.1


def test_sparse_dependencies_cover_coupled_rotations_and_body_relative_motion():
    from exercise_motion_pkg.controlled_motion import joint_dependencies,rotation_prior_dependencies
    from scipy.optimize._numdiff import approx_derivative
    initial=Rotation.from_euler('xyz',[.3,.4,.5])
    values=np.array([0.,0.,0.,.25,-.37,.22])
    derivative=approx_derivative(lambda v:(initial.inv()*Rotation.from_rotvec(v[3:])).as_rotvec(),values)
    pattern=rotation_prior_dependencies(6).astype(bool)
    assert np.all(abs(derivative[~pattern])<1e-8)
    assert np.any(abs(derivative[:,3:]-np.diag(np.diag(derivative[:,3:])))>1e-3)
    names,points=stance(1)
    rig=FixedRig(points,names)
    values=rig.initial.ravel()+.01
    derivative=approx_derivative(lambda v:body_relative_points(rig.decode(v[None,:]),names).ravel(),values)
    basis=joint_dependencies(rig,('pelvis','left_hip','right_hip','neck'))
    pattern=np.maximum(rig.dependencies,basis[None,:]).astype(bool)
    assert np.all(abs(derivative[~pattern])<1e-7)
    assert not pattern.all()
