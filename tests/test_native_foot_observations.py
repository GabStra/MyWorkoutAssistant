import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.native_foot_observations import (
    SourceFootMarkerSampler, foot_markers_from_pose, projected_foot_vectors,
)
from exercise_motion_pkg.native_material_frames import material_axes
from exercise_motion_pkg.rig_playback import decode_rig, sample_rig_coordinates


def fixture():
    names = ['pelvis', 'left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    q = np.zeros((5, 18))
    q[:, 3:6] = np.array([0., .03, -.02])
    rig = dict(jointNames=names, parents=[-1, 0, 1, 0, 3], order=list(range(5)),
               rotationJointNames=names, coordinates=q,
               offsets=[[0., 0., 0.], [-.1, -.8, 0.], [0., 0., .134],
                        [.1, -.8, 0.], [0., 0., .134]],
               interpolation='limited_quaternion_hermite_v2')
    rig['materialFrames'] = dict(version=1, referenceCoordinates=q.copy(),
        referenceBoneSides={f'{side}_ankle->{side}_foot': [[1., 0., 0.]]*5
                            for side in ('left', 'right')})
    geometry = json.loads((Path(__file__).parent/'fixtures/native_foot_geometry_v1.json')
                          .read_text())['reference']
    # The generic fixture's markers are exactly on the bone axis, so twist
    # cannot move them. Use explicitly nonaxial calibrated marker offsets.
    for side in ('left', 'right'):
        geometry['sides'][side]['toeFromAnkleLocalMeters'][1:] = [.009, .012]
        geometry['sides'][side]['heelFromAnkleLocalMeters'][1:] = [-.006, .015]
    observations = [dict(leftFrame=1, rightFrame=2, alpha=.37, motionSide='right'),
                    dict(leftFrame=4, rightFrame=0, alpha=.61, motionSide='left')]
    return rig, geometry, observations


def test_pure_terminal_twist_changes_physical_observables_not_joint_points():
    rig, geometry, observations = fixture()
    observation = {**observations[0], 'leftFrame': 2, 'rightFrame': 2, 'alpha': 0.}
    sampler = SourceFootMarkerSampler(rig, [observation], geometry)
    q = rig['coordinates'].copy()
    slot = 3 + 3*rig['rotationJointNames'].index('right_foot')
    local_axis = np.asarray(rig['offsets'][4])/np.linalg.norm(rig['offsets'][4])
    q[2, slot:slot+3] = (Rotation.from_rotvec(q[2, slot:slot+3])
                         * Rotation.from_rotvec(.1*local_axis)).as_rotvec()
    np.testing.assert_allclose(decode_rig(rig, q), decode_rig(rig, rig['coordinates']), atol=1e-14)
    before, after = sampler.sample(rig['coordinates']), sampler.sample(q)
    assert np.linalg.norm(after['toe']-before['toe']) > 1e-5
    assert np.linalg.norm(after['heel']-before['heel']) > 1e-5
    projection = np.array([[1., .2, 0.], [0., 1., .3]])
    assert np.linalg.norm(sampler.vectors(q, projection)-sampler.vectors(rig['coordinates'], projection)) > 1e-5
    # Fit and gate can consume exactly these same projected physical vectors.
    np.testing.assert_array_equal(sampler.vectors(q, projection), projected_foot_vectors(after, projection))


def test_fractional_seam_jacobian_and_actual_pose_marker_authority():
    rig, geometry, observations = fixture()
    rig['materialFrames']['stationaryLocalBindings'] = {
        'right_ankle->right_foot': [dict(startFrame=0, endFrame=4, anchorId='sole',
            activeFrames=list(range(5)), localSideAxis=[.9, .3, 0.])]}
    q = rig['coordinates'].copy()
    q[:, 6:] = np.random.default_rng(7).normal(0., .035, q[:, 6:].shape)
    sampler = SourceFootMarkerSampler(rig, observations, geometry, wrap=True)
    projection = np.array([[.6, .1, -.2], [0., -.7, .05]])
    actual = sampler.jacobian(q, projection).toarray()
    independent = approx_derivative(lambda x: sampler.vectors(x, projection).ravel(),
                                    q.ravel(), method='3-point', abs_step=2e-6)
    np.testing.assert_allclose(actual, independent, atol=2e-9, rtol=2e-5)
    current = {**rig, 'coordinates': q}
    sampled = sample_rig_coordinates(current, sampler.cursors, wrap=True)
    points = decode_rig(current, sampled)
    axes = material_axes(current, sampler.cursors, wrap=True, coordinates=sampled)
    raw = foot_markers_from_pose(points, rig['jointNames'], axes, observations, geometry)
    for key in raw:
        np.testing.assert_allclose(raw[key], sampler.sample(q)[key], atol=1e-14)
    # An actual corrected pose must carry its corrected axes, not re-read raw q.
    rotation = Rotation.from_rotvec([.08, -.11, .03])
    translation = np.array([.1, .2, -.3])
    moved = rotation.apply(points.reshape(-1, 3)).reshape(points.shape)+translation
    corrected = foot_markers_from_pose(moved, rig['jointNames'],
        {side: rotation.apply(axis) for side, axis in axes.items()}, observations, geometry)
    for key in raw:
        np.testing.assert_allclose(corrected[key], rotation.apply(raw[key])+translation, atol=1e-14)


def test_new_mode_and_clock_fail_closed():
    rig, geometry, observations = fixture()
    legacy = {key: value for key, value in rig.items() if key != 'materialFrames'}
    with pytest.raises(ValueError, match='legacy belongs to caller'):
        SourceFootMarkerSampler(legacy, observations, geometry)
    malformed = deepcopy(rig)
    malformed['materialFrames']['version'] = 2
    with pytest.raises(ValueError, match='version'):
        SourceFootMarkerSampler(malformed, observations, geometry)
    with pytest.raises(ValueError, match='not adjacent'):
        SourceFootMarkerSampler(rig, [{**observations[0], 'rightFrame': 4}], geometry)
    with pytest.raises(ValueError, match='not adjacent'):
        SourceFootMarkerSampler(rig, [observations[1]], geometry, wrap=False)


def test_assembled_projection_rows_jacobian_and_report_share_physical_observables():
    from exercise_motion_pkg import controlled_motion as cm
    rig_data, geometry, observations = fixture()
    q = rig_data['coordinates'].copy()
    q[:, 6:] = np.random.default_rng(11).normal(0., .025, q[:, 6:].shape)
    rig = cm.FixedRig.__new__(cm.FixedRig)
    rig.names = rig_data['jointNames']; rig.parents = rig_data['parents']; rig.order = rig_data['order']
    rig.offsets = np.asarray(rig_data['offsets']); rig.active = list(range(len(rig.names)))
    rig.slots = {j:3+3*j for j in rig.active}; rig.width=q.shape[1]; rig.root=0; rig.initial=q.copy()
    rig.material_frames=rig_data['materialFrames']
    rig.native_foot_geometry_for_sampling=geometry; rig.native_foot_scale_for_sampling=.2
    projection=np.array([[.6,.1,-.2],[0.,-.7,.05]])
    ray=[]
    for i,row in enumerate(observations):
        side=row['motionSide']
        ray.append({**row,'sourceSide':side,'sourceTime':float(i),
                    'ankleJointIndex':rig.names.index(side+'_ankle'),
                    'footJointIndex':rig.names.index(side+'_foot'),
                    'targetRay':np.array([.8,.6]),'sourceRay':np.array([.8,.6]),
                    'headingOffsetRadians':0.,'confidenceWeight':.9,
                    'heelPhasePreservation':dict(stanceTargetAngleRadians=0.,nativePhaseRadians=.4,noiseThresholdRadians=.01)})
    heel=[{**row,'sourceHeelToToeVector':np.array([.04,-.02]),'imageOffset':np.array([99.,99.]),
           'sourceNoiseImageUnits':0.,'stationaryAnchorGroupId':'a'} for row in ray]
    calibration=[{**heel[0],'leftFrame':i,'rightFrame':i,'alpha':0.,'sourceTime':float(i+10)} for i in (0,2,3)]
    event=dict(sourceSide='right',stationaryAnchorGroupId='a',observationTimes=[0.],
               sourceExcursionImageUnits=.2,sourceNoiseImageUnits=0.,fitMinimumRatio=.92)
    trajectory=[{**heel[0],'baselineFitVector':np.array([99.,99.]),'liftDirection':np.array([0.,1.])}]
    constraint=dict(available=True,projection=projection,offset=np.array([.1,.2]),normalization=1.,weight=2.,
        observations=[dict(leftFrame=1,rightFrame=2,alpha=.37,jointIndex=0,sourcePoint=np.zeros(2),confidenceWeight=.7)],
        sourceFootRayObservations=ray,sourceFootHeelImageObservations=heel,
        sourceFootNativeMarkerVectorObservations=heel,sourceFootHeelCalibrationObservations=calibration,
        sourceFootHeelTrajectoryObservations=trajectory,sourceFootHeelTrajectoryEvents=[event],
        nativeMarkerGeometry=geometry,_nativeFootObservationWrap=True)
    def rows(values):
        values=np.asarray(values).reshape(q.shape)
        return cm._source_projection_fit_rows(rig.decode(values),constraint,
            native_sampling_rig={**cm._sampling_payload(rig,values),'_observationWrap':True})
    assembled=cm._source_projection_fit_jacobian(constraint,frame_count=len(q),joint_count=len(rig.names),
        rig=rig,coordinates=q).toarray()
    independent=approx_derivative(rows,q.ravel(),method='3-point',abs_step=2e-6)
    assert assembled.shape==(13,q.size)  # 2 joint +2 ray +4 heel +1 event +4 native marker.
    np.testing.assert_allclose(assembled,independent,atol=2e-6,rtol=2e-4)
    points=rig.decode(q)
    payload=dict(jointNames=rig.names,frames=[{'joints':dict(zip(rig.names,p.tolist()))} for p in points],
                 fixedRig=cm._sampling_payload(rig,q),nativeFootGeometry=geometry,loop={'enabled':True})
    raw=cm._source_foot_pose_constraint(constraint,sampling_rig={**cm._sampling_payload(rig,q),'_observationWrap':True})
    playback=cm._source_foot_pose_constraint(constraint,playback_payload=payload)
    np.testing.assert_allclose(cm._source_physical_foot_vectors(raw,ray),cm._source_physical_foot_vectors(playback,ray),atol=1e-14)
    assert cm._source_foot_ray_fit_evidence(points,raw)==cm._source_foot_ray_fit_evidence(points,playback)
    assert cm._source_foot_phase_fit_evidence(points,raw)==cm._source_foot_phase_fit_evidence(points,playback)
    # Absolute image rows must not carry the old source-3D-derived offset.
    honest={**constraint,'sourceFootHeelImageObservations':[{**r,'imageOffset':np.zeros(2)} for r in heel]}
    np.testing.assert_array_equal(rows(q),cm._source_projection_fit_rows(points,honest,native_sampling_rig={**cm._sampling_payload(rig,q),'_observationWrap':True}))
    legacy=deepcopy(rig_data);legacy.pop('materialFrames')
    legacy_rows=cm._source_projection_fit_rows(points,{**constraint,'sourceFootNativeMarkerVectorObservations':[],
        'sourceFootHeelImageObservations':[],'sourceFootHeelTrajectoryEvents':[]})
    assert legacy_rows.size==4
    malformed=deepcopy(payload);malformed['fixedRig']['materialFrames']['version']=2
    with pytest.raises(ValueError,match='version'):
        cm._source_foot_ray_fit_evidence(points,cm._source_foot_pose_constraint(constraint,playback_payload=malformed))


def test_output_phase_uses_physical_toe_and_preserves_legacy_joint_mode():
    from exercise_motion_pkg.bake_and_rank import output_foot_orientation_phase_tracks
    rig,geometry,_=fixture()
    q=rig['coordinates'].copy()
    q[:,15:18]=np.arange(5)[:,None]*np.array([0.,0.,.07])
    rig={**rig,'coordinates':q}
    points=decode_rig(rig,q)
    payload=dict(jointNames=rig['jointNames'],fixedRig=rig,nativeFootGeometry=geometry,
        frames=[{'joints':dict(zip(rig['jointNames'],row.tolist()))} for row in points],
        loop={'enabled':False})
    physical=output_foot_orientation_phase_tracks(payload)
    assert physical['right']['geometrySource']=='output_ankle_to_native_material_toe'
    assert physical['right']['range']>1e-4
    legacy=deepcopy(payload);legacy['fixedRig'].pop('materialFrames')
    old=output_foot_orientation_phase_tracks(legacy)
    assert old['right']['geometrySource']=='output_ankle_to_foot_joints'
    assert old['right']['range']<1e-12


def test_newmode_yaw_initializer_rotates_material_axis_with_derived_pose():
    from exercise_motion_pkg import controlled_motion as cm
    _,geometry,_=fixture()
    names=['right_knee','right_ankle','right_foot']
    points=np.array([[[0.,0.,0.],[0.,1.,0.],[0.,1.,.12]]])
    anchor=np.array([0.,1.,.06]);normal=np.array([0.,1.,0.]);side=np.array([[1.,0.,0.]])
    tracks={'version':2,'right':dict(active=[True],anchorIds=['sole'],episodes=[
        dict(startFrame=0,endFrame=0,anchorId='sole',mode='stationary',regionRole='full_sole',
             targetWorld=anchor,surfaceNormal=normal)])}
    row=dict(sourceSide='right',motionSide='right',leftFrame=0,rightFrame=0,alpha=0.,
        ankleJointIndex=1,footJointIndex=2,sourceRay=np.array([1.,0.]),
        targetRay=np.array([0.,1.]),headingOffsetRadians=np.pi/2)
    constraint=dict(available=True,projection=np.array([[1.,0.,0.],[0.,0.,1.]]),
        sourceFootRaySideMapping={'right':'right'},sourceFootRayObservations=[row])
    yaw,report=cm._native_fullsole_camera_yaw_by_side(points,names,tracks,constraint,
        material_side_axes={'right':side},native_geometry=geometry)
    rotation=Rotation.from_rotvec(normal*yaw['right'])
    moved=rotation.apply((points-anchor).reshape(-1,3)).reshape(points.shape)+anchor
    markers=foot_markers_from_pose(moved,names,{'right':rotation.apply(side)},[row],geometry)
    ray=projected_foot_vectors(markers,constraint['projection'])[0,0]
    assert abs(np.arctan2(ray[1],ray[0]))<1e-7
    assert abs(yaw['right']-np.pi/2)>np.deg2rad(1.)
    assert report['bySide']['right']['endpointKind']=='native_material_toe'
