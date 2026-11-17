import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import FixedRig, _sampling_payload
from exercise_motion_pkg.contact_interpolation import ContactFootIKUnreachable
from exercise_motion_pkg.native_contact_reach import NativeContactReachConstraint
from exercise_motion_pkg.rig_playback import sample_rig


def _fixture(mode='stationary', correction=.0007):
    from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame

    rig = FixedRig.__new__(FixedRig)
    rig.names = ['pelvis', 'left_hip', 'right_hip', 'left_knee', 'right_knee',
                 'left_ankle', 'right_ankle', 'left_foot', 'right_foot']
    rig.parents = [-1, 0, 0, 1, 2, 3, 4, 5, 6]
    rig.order = list(range(9))
    rig.active = [0, 3, 4, 5, 6, 7, 8]
    rig.slots = {joint: 3 + 3 * index for index, joint in enumerate(rig.active)}
    rig.root, rig.width = 0, 24
    rig.offsets = np.array([[0., 0., 0.], [-.1, 1., 0.], [.1, 1., 0.],
                           [.01, -.4, 0.], [-.01, -.4, 0.],
                           [-.01, -.4, 0.], [.01, -.4, 0.],
                           [0., 0., .2], [0., 0., .2]])
    rig.initial = np.zeros((5, rig.width))
    rig.material_reference_coordinates = rig.initial.copy()
    geometry = json.loads((Path(__file__).parent / 'fixtures' /
                           'native_foot_geometry_v1.json').read_text())['reference']
    points = rig.decode(rig.initial)
    scale = foot_scale_from_pose(points[0], rig.names)
    rig.native_foot_geometry_for_sampling = geometry
    rig.native_foot_scale_for_sampling = scale
    ankle, foot = points[0, 6], points[0, 8]
    axis = np.array([1., 0., 0.])
    mesh = shoe_vertices(ankle, foot, axis, None, scale,
                         native_geometry=geometry['sides']['right'])
    bary = np.array([.2, .3, .5])
    material = bary @ mesh[shoe_triangles()[11]]
    forward, lateral, up, length = native_foot_bone_frame(ankle, foot, axis)
    reference = geometry['sides']['right']['ankleToFootJointLengthMeters']
    delta = material - ankle
    local = np.array([delta @ forward, delta @ lateral, delta @ up]) * reference / length[0]
    target = material - [0., correction, 0.]
    episode = dict(startFrame=0, endFrame=4, anchorId='right-anchor', regionRole='forefoot',
                   mode=mode, primitiveId='wearShoe:right_ankle->right_foot', triangleIndex=11,
                   barycentric=bary.tolist(), materialOffsetLocalMeters=local.tolist(),
                   referenceLengthMeters=reference, targetWorld=target.tolist(),
                   surfaceNormal=[0., 1., 0.], planeOffsetMeters=float(target[1]))
    if mode == 'verticalOnly':
        episode.pop('targetWorld')
    tracks = {'version': 2, 'right': dict(active=[True] * 5, directions=[[0., 0., 1.]] * 5,
              sideAxes=[axis.tolist()] * 5, anchorIds=['right-anchor'] * 5, episodes=[episode])}
    return rig, tracks


@pytest.mark.parametrize('mode', ['stationary', 'verticalOnly'])
def test_reach_guard_measures_the_actual_unreachable_playback_target(mode):
    rig, tracks = _fixture(mode)
    constraint = NativeContactReachConstraint(rig, tracks, {}, [.5], cyclic=True)
    rows = constraint.residual(rig.initial).reshape(1, 2, 2)
    assert not constraint.unprotected_feasible(rig.initial)
    sampling = {**_sampling_payload(rig, rig.initial), 'contactFootTracks': tracks}
    with pytest.raises(ContactFootIKUnreachable) as error:
        sample_rig(sampling, [.5], wrap=True)
    evidence = error.value.evidence()['samples'][0]
    np.testing.assert_allclose(rows[0, 1, 1],
                               evidence['upperReachExcessMeters'], atol=1e-12)
    # A small radial correction has no problem when the target remains reachable;
    # unilateral mirrored playback still owns the opposite leg as before.
    rig, tracks = _fixture(mode, correction=-.001)
    constraint = NativeContactReachConstraint(rig, tracks, {}, [.5, 4.5], cyclic=True)
    assert constraint.unprotected_feasible(rig.initial)
    sampling = {**_sampling_payload(rig, rig.initial), 'contactFootTracks': tracks,
                '_canonicalExecutionForSampling': {'legs': 'mirrored'}}
    assert np.isfinite(sample_rig(sampling, [.5, 4.5], wrap=True)).all()


def test_reach_jacobian_includes_refreshed_neighbor_roll_and_cyclic_seam():
    rig, tracks = _fixture(correction=.01)
    constraint = NativeContactReachConstraint(rig, tracks, {}, [.25, 1.5, 4.75], cyclic=True)
    values = rig.initial.copy()
    values[:, rig.slots[8] + 2] = [.01, -.02, .015, -.01, .005]
    jacobian = constraint.jacobian(values)
    # Probe every input independently, including endpoint keys shared across the
    # wrap and terminal-foot roll (which changes axes but not joint positions).
    from scipy.optimize._numdiff import approx_derivative
    expected = approx_derivative(constraint.residual, values.ravel(),
                                 method='3-point', abs_step=1e-6)
    np.testing.assert_allclose(jacobian.toarray(), expected, atol=2e-9, rtol=2e-5)
    assert abs(jacobian[3, rig.slots[8] + 2]) > 1e-6
    assert abs(jacobian[-1, rig.slots[8] + 2]) > 1e-6


def _full_fk_fixture():
    from copy import deepcopy
    from exercise_motion_pkg.native_material_frames import freeze_material_frames
    rig, tracks = _fixture(correction=.01)
    axes = {side: np.tile([1., 0., 0.], (5, 1)) for side in ('left', 'right')}
    rig.material_frames = freeze_material_frames(rig, tracks, axes)
    points = rig.decode(rig.initial)
    payload = {'jointNames': rig.names, 'nativeFootGeometry': rig.native_foot_geometry_for_sampling,
        'renderFloorY': -1., 'loop': {'enabled': True},
        'frames': [{'joints': dict(zip(rig.names, row.tolist()))} for row in points],
        'fixedRig': {k: v.tolist() if isinstance(v,np.ndarray) else deepcopy(v)
                     for k,v in _sampling_payload(rig,rig.initial).items() if not k.startswith('_')}}
    return rig, tracks, payload


def test_full_fk_twist_owner_publication_shoe_marker_and_scene():
    from copy import deepcopy
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.native_material_frames import material_axes, publish_material_frames, place_material_frames
    from exercise_motion_pkg.foot_geometry import _sample_material_foot_geometry, shoe_vertices
    from exercise_motion_pkg.shoe_floor import ShoeFloorConstraint
    from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
    from exercise_motion_pkg.sequence_stabilization import pose_digest
    rig, tracks, payload = _full_fk_fixture()
    q0 = rig.initial.copy();q1 = q0.copy();slot = rig.slots[8]
    axis = rig.offsets[8]/np.linalg.norm(rig.offsets[8])
    q1[2, slot:slot+3] = (Rotation.from_rotvec(q0[2, slot:slot+3])*Rotation.from_rotvec(.1*axis)).as_rotvec()
    np.testing.assert_allclose(rig.decode(q0), rig.decode(q1), atol=1e-14)
    payload['fixedRig']['coordinates'] = q1.tolist()
    publish_material_frames(payload)
    points = rig.decode(q1)
    actual = _sample_material_foot_geometry(payload, np.arange(5), points)['right']['lateral']
    old = _native_side_axes_for_coordinates(rig, q1, {'_nativeFootMaterialTracks': tracks}, publication=False)['right']
    old /= np.linalg.norm(old, axis=1, keepdims=True)
    np.testing.assert_allclose(actual, old, atol=1e-13)
    mesh = shoe_vertices(points[:,6],points[:,8],actual,None,rig.native_foot_scale_for_sampling,
                         native_geometry=rig.native_foot_geometry_for_sampling['sides']['right'])
    original = shoe_vertices(points[:,6],points[:,8],np.tile([1.,0.,0.],(5,1)),None,rig.native_foot_scale_for_sampling,
                         native_geometry=rig.native_foot_geometry_for_sampling['sides']['right'])
    assert np.linalg.norm(mesh-original,axis=-1).max() > .005
    shoe = ShoeFloorConstraint(rig,payload)
    shoe.heights(q1.ravel())
    np.testing.assert_allclose(shoe.material_vertices(shoe.points,shoe.resolved,shoe.scale)['right'],mesh,atol=1e-13)
    from scipy.optimize._numdiff import approx_derivative
    shoe.payload['renderFloorY']=.3
    floor_j=shoe.jacobian(q1.ravel()).toarray()
    expected_floor_j=approx_derivative(shoe.residual,q1.ravel(),method='3-point',abs_step=1e-6)
    np.testing.assert_allclose(floor_j,expected_floor_j,atol=2e-8,rtol=2e-4)
    assert abs(floor_j[5,2*rig.width+slot+2])>1e-4
    static_payload={**payload,'frames':[payload['frames'][2]]}
    static=ShoeFloorConstraint(rig,static_payload,frame_positions=np.array([0]),
                              context=points[2:3],material_frame_positions=np.array([2]))
    np.testing.assert_allclose(static.heights(q1[2]),shoe.heights(q1.ravel())[4:6],atol=1e-13)
    changed=deepcopy(payload);changed['fixedRig']['materialFrames']['referenceBoneSides']['right_ankle->right_foot'][0][1]=.01
    assert pose_digest(changed)!=pose_digest(payload)
    rotation=Rotation.from_rotvec([.1,.2,-.1]);origin=np.array([.2,-.3,.4]);placed=deepcopy(payload['fixedRig'])
    before=material_axes(placed,[1.25,4.75],wrap=True)
    place_material_frames(placed,rotation,origin)
    q=np.asarray(placed['coordinates']);q[:,:3]=rotation.apply(q[:,:3])-origin
    root_slot=rig.slots[0];q[:,root_slot:root_slot+3]=(rotation*Rotation.from_rotvec(q[:,root_slot:root_slot+3])).as_rotvec();placed['coordinates']=q.tolist()
    after=material_axes(placed,[1.25,4.75],wrap=True)
    for side in before:np.testing.assert_allclose(after[side],rotation.apply(before[side]),atol=1e-12)


    from exercise_motion_pkg import controlled_motion as motion
    constraint={'projection':np.array([[1.,0.,0.],[0.,1.,0.]]),
        'nativeMarkerGeometry':json.loads((Path(__file__).parent/'fixtures/native_foot_geometry_v1.json').read_text())['twistedRetargetGeometry'],
        'sourceFootNativeMarkerVectorObservations':[{
            'motionSide':'right','leftFrame':2,'rightFrame':2,'alpha':0.,
            'ankleJointIndex':6,'footJointIndex':8,'sourceHeelToToeVector':np.zeros(2),
            'confidenceWeight':1.,'state':'toe_only'}]}
    marker=lambda q:motion._source_native_marker_vector_fit_rows(rig.decode(q),constraint,
                                motion._source_native_marker_side_axes(rig,q,constraint))
    assert np.linalg.norm(marker(q1)-marker(q0))>1e-4
    jac=motion._source_native_marker_vector_jacobian(constraint,rig=rig,coordinates=q1).toarray()
    for component in range(3):
        plus,minus=q1.copy(),q1.copy();plus[2,slot+component]+=1e-6;minus[2,slot+component]-=1e-6
        np.testing.assert_allclose(jac[:,2*rig.width+slot+component],
                                  (marker(plus)-marker(minus))/2e-6,atol=2e-5,rtol=2e-4)
    captured=[]
    with motion.capture_rejected_fit_candidate(lambda candidate,*args:captured.append(deepcopy(candidate))):
        assert motion.retain_rejected_fit_candidate(payload,{'applied':False},payload)
    assert captured[0]['fixedRig']['materialFrames']==rig.material_frames
    from exercise_motion_pkg.loop_cycles import slice_loop_cycle
    with pytest.raises(ValueError,match='before fitting'):
        slice_loop_cycle({**payload,'frames':payload['frames']*2},{'startFrame':0,'stopFrameExclusive':7})


def test_full_fk_stationary_reference_fractional_clock_and_guard_fd():
    from exercise_motion_pkg.native_material_frames import freeze_material_frames, material_axes
    from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates
    from exercise_motion_pkg.rig_playback import sample_rig_coordinates
    from scipy.optimize._numdiff import approx_derivative
    rig,tracks,payload=_full_fk_fixture()
    del rig.material_frames
    tracks['right']['episodes'][0]['regionRole']='full_sole'
    tracks['right']['sideAxes']=[[float(np.cos(a)),float(np.sin(a)),0.] for a in [.01,.02,-.01,.03,0.]]
    rig.material_frames=freeze_material_frames(rig,tracks,{side:np.tile([1.,0.,0.],(5,1)) for side in ('left','right')})
    assert len(rig.material_frames['stationaryLocalBindings']['right_ankle->right_foot'])==1
    q=rig.initial.copy();q[:,rig.slots[8]+2]=[.02,-.01,.03,-.02,.01]
    cursors=np.array([0.,1.25,3.75,4.75])
    sampled=sample_rig_coordinates(_sampling_payload(rig,q),cursors,wrap=True)
    old=_native_side_axes_for_coordinates(rig,sampled,{'_nativeFootMaterialTracks':tracks},
                                         frame_positions=cursors,wrap=True,publication=False)['right']
    old/=np.linalg.norm(old,axis=1,keepdims=True)
    np.testing.assert_allclose(material_axes(_sampling_payload(rig,q),cursors,wrap=True)['right'],old,atol=1e-12)
    # Reference is fixed: only actual neighboring current-key rotations differentiate.
    guard=NativeContactReachConstraint(rig,tracks,{},[.25,4.75],cyclic=True)
    from exercise_motion_pkg.controlled_motion import _refresh_native_foot_contact_tracks
    production={**_sampling_payload(rig,q),'contactFootTracks':_refresh_native_foot_contact_tracks(rig,q,tracks,{})}
    guarded=guard.residual(q).reshape(-1,2,2)
    with pytest.raises(ContactFootIKUnreachable) as error:
        sample_rig(production,[.25,4.75],wrap=True)
    for row in error.value.evidence()['samples']:
        assert guarded[row['sampleIndex'],1,1]==pytest.approx(row['upperReachExcessMeters'],abs=1e-12)
    actual=guard.jacobian(q).toarray()
    expected=approx_derivative(guard.residual,q.ravel(),method='3-point',abs_step=1e-6)
    np.testing.assert_allclose(actual,expected,atol=3e-9,rtol=2e-5)


@pytest.mark.parametrize('change',[lambda b:b.update(version=2),lambda b:b.update(version=True),
    lambda b:b.update(referenceCoordinates=b['referenceCoordinates'][:-1]),
    lambda b:b['referenceBoneSides'].update({'right_ankle->right_foot':[[0.,0.,1.]]*5}),
    lambda b:b.update(stationaryLocalBindings={'right_ankle->right_foot':[{
        'startFrame':0,'endFrame':4,'activeFrames':[2,1],'localSideAxis':[1.,0.,0.],'anchorId':'a'}]})])
def test_full_fk_malformed_present_binding_fails(change):
    from exercise_motion_pkg.native_material_frames import material_axes
    rig,tracks,payload=_full_fk_fixture();change(payload['fixedRig']['materialFrames'])
    with pytest.raises(ValueError):material_axes(payload['fixedRig'],[.5])


def test_full_fk_native_floor_heel_section_local_axis_jacobian():
    from scipy.optimize._numdiff import approx_derivative
    from exercise_motion_pkg.controlled_motion import _native_material_subframe_axis_jacobian
    from exercise_motion_pkg.support_geometry import _native_side_axes_for_coordinates, _native_foot_material_contact_residuals
    from exercise_motion_pkg.foot_geometry import material_floor_heights
    from exercise_motion_pkg.heel_contacts import HeelContacts
    from exercise_motion_pkg.contact_interpolation import native_material_playback_residuals
    rig,tracks,payload=_full_fk_fixture()
    cursors=np.array([1.25,4.75]);q=rig.initial[:2].copy()
    q[:,rig.slots[8]:rig.slots[8]+3]=[[.02,.03,.1],[-.01,.02,-.04]]
    evidence={'_nativeFootMaterialTracks':tracks,'nativeFootGeometry':rig.native_foot_geometry_for_sampling,
              '_nativeFootScale':rig.native_foot_scale_for_sampling}
    def axes(values):
        return _native_side_axes_for_coordinates(rig,values,evidence,frame_positions=cursors,wrap=True)
    def rows(points,side_axes):
        material={side:{'lateral':axis,'nativeGeometry':rig.native_foot_geometry_for_sampling['sides'][side]}
                  for side,axis in side_axes.items()}
        floor=np.minimum(material_floor_heights(points,rig.names,{},rig.native_foot_scale_for_sampling,material)-.3,0.)
        heel=HeelContacts([(6,8)],np.ones((2,1),bool),np.zeros((2,1,3)),[None],
             [rig.native_foot_geometry_for_sampling['sides']['right']],[]).residual(points,side_axes=[side_axes['right']]).reshape(2,-1)
        native,errors=_native_foot_material_contact_residuals(points,rig.names,evidence,
                        frame_positions=cursors,side_axes_override=side_axes)
        assert not errors
        playback=native_material_playback_residuals(points,rig.names,rig.offsets,tracks,cursors,
                            wrap=True,fractional_side_axes=side_axes)
        return np.concatenate([floor,heel,native,playback],axis=1)
    points=rig.decode(q);fixed_axes=axes(q);width=rows(points,fixed_axes).shape[1]
    axis_j=_native_material_subframe_axis_jacobian(lambda a:rows(points,a),axes,q,
        list(rig.slots.values()),row_start=0,row_stride=width,axis_scale=1.,fd_step=1e-6).toarray()
    point_j=approx_derivative(lambda x:rows(rig.decode(x.reshape(q.shape)),fixed_axes).ravel(),
                             q.ravel(),method='3-point',abs_step=1e-6)
    expected=approx_derivative(lambda x:rows(rig.decode(x.reshape(q.shape)),axes(x.reshape(q.shape))).ravel(),
                              q.ravel(),method='3-point',abs_step=1e-6)
    np.testing.assert_allclose(axis_j+point_j,expected,atol=2e-8,rtol=2e-4)
    assert np.max(np.abs(axis_j[:,rig.slots[8]+2]))>1e-4


def test_full_fk_protected_key_material_uses_actual_returned_axis():
    from exercise_motion_pkg.rig_playback import _native_sampling_rig
    from exercise_motion_pkg.native_material_frames import material_axes
    from exercise_motion_pkg.foot_geometry import sample_material_foot_points
    from exercise_motion_pkg.native_foot_geometry import native_foot_marker_world
    rig,tracks,payload=_full_fk_fixture()
    q=rig.initial.copy();q[2,rig.slots[8]+2]=.1
    payload['fixedRig']['coordinates']=q.tolist()
    episode=tracks['right']['episodes'][0]
    episode['mode']='verticalOnly';episode.pop('targetWorld')
    episode['planeOffsetMeters']+=.011
    payload['fixedRig']['contactFootTracks']=tracks
    payload['fixedRig']['supportJointTracks']={'version':1,'source':'validated_stationary_body_support',
        'joints':{'right_knee':{'episodeIds':['support']*5}}}
    sampled,axes=sample_rig(_native_sampling_rig(payload),[2.],return_side_axes=True)
    np.testing.assert_allclose(sampled[0,4],rig.decode(q)[2,4],atol=1e-12)
    baseline=material_axes(payload['fixedRig'],[2.])['right']
    assert np.linalg.norm(axes['right']-baseline)>1e-3
    material=sample_material_foot_points(payload,[2.])['right']
    expected=native_foot_marker_world(sampled[:,6],sampled[:,8],axes['right'],
                                     rig.native_foot_geometry_for_sampling['sides']['right'])
    np.testing.assert_allclose(material['sideAxis'],axes['right'],atol=1e-12)
    np.testing.assert_allclose(material['heel'],expected[0],atol=1e-12)
    np.testing.assert_allclose(material['toe'],expected[1],atol=1e-12)


@pytest.mark.parametrize('empty_tracks', [True, False])
def test_free_foot_binding_producer_boundary_preserves_unconstrained_twist(empty_tracks):
    from exercise_motion_pkg.native_material_frames import freeze_material_frames, validate_material_frames
    rig, _ = _fixture()
    axes = {side: np.tile([1., 0., 0.], (len(rig.initial), 1)) for side in ('left', 'right')}
    tracks = {'version': 2}
    if not empty_tracks:
        for side in axes:
            tracks[side] = {'active': [False]*len(rig.initial),
                'directions': [[0., 0., 1.]]*len(rig.initial),
                'sideAxes': axes[side].tolist(), 'anchorIds': [None]*len(rig.initial),
                'episodes': []}
    # Same factory/call boundary as the producer's absent-track fallback. The
    # nested fitter condition itself belongs to the next normal-owner capture.
    rig.material_frames = freeze_material_frames(rig, tracks, axes)
    assert rig.material_frames['stationaryLocalBindings'] == {}
    baseline = _sampling_payload(rig, rig.initial)
    assert 'contactFootTracks' not in baseline
    validate_material_frames(baseline)
    q = rig.initial.copy()
    q[2, rig.slots[8]+2] = .1  # Local foot offset is +Z in this qualified fixture.
    produced = _sampling_payload(rig, q)
    np.testing.assert_array_equal(produced['materialFrames']['referenceCoordinates'],
                                  rig.material_reference_coordinates)
    before, before_axes = sample_rig(baseline, [2.], return_side_axes=True)
    after, after_axes = sample_rig(produced, [2.], return_side_axes=True)
    np.testing.assert_allclose(after, before, atol=1e-14)
    np.testing.assert_allclose(after_axes['right'][0], [np.cos(.1), np.sin(.1), 0.], atol=1e-13)
    assert np.linalg.norm(after_axes['right']-before_axes['right']) > .09
