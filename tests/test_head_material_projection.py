import json
from pathlib import Path

import numpy as np
from scipy.spatial.distance import cdist

from exercise_motion_pkg.render_geometry import head_material_binding, head_material_vertices
from exercise_motion_pkg.head_material_projection import (
    prepare_head_material_observations, head_material_rows,
    head_material_point_jacobian, head_material_evidence,
)


def _fixture():
    value=json.loads((Path(__file__).parent/'fixtures/native_head_material_regions.json').read_text())
    return value,np.asarray(value['points']),value['jointNames'],np.asarray(value['projection']),np.asarray(value['offset'])


def test_head_material_matches_native_tilted_and_extended_clip_poses():
    fixture,points,names,projection,offset=_fixture()
    actual=head_material_vertices(points,names)
    for native,vertices in zip(fixture['nativeVertices'],actual):
        distance=cdist(native,vertices)
        assert max(distance.min(axis=0).max(),distance.min(axis=1).max())<1e-6


def test_inner_face_is_local_material_evidence_but_unknown_and_ears_only_are_unavailable():
    fixture,points,names,projection,offset=_fixture()
    prepare=lambda frames:prepare_head_material_observations(points,names,np.arange(3.),frames,
        projection,offset,time_tolerance=0.)
    evidence=prepare([fixture['sourceFrame']])
    report=head_material_evidence(points,evidence,projection,offset,maximum_rms_part_ratio=.12)
    assert report['available'] and not report['passed']
    assert report['maximumFrameRmsPartRatio']>.4
    assert report['chinClearanceMeasured'] is False
    unknown={**fixture['sourceFrame'],'jointConfidence':{}}
    ears={**fixture['sourceFrame'],'joints':{k:v for k,v in fixture['sourceFrame']['joints'].items() if 'ear' in k}}
    assert not prepare([unknown])['available']
    assert not prepare([ears])['required']


def test_head_projection_jacobian_includes_first_stored_binding_frame():
    fixture,points,names,projection,offset=_fixture()
    vertices=head_material_vertices(points,names)[2]
    center=(vertices@projection.T+offset).mean(axis=0)
    source={'time':2.,'joints':{'nose':(center+[0.,-.1]).tolist()},'jointConfidence':{'nose':.9}}
    evidence=prepare_head_material_observations(points,names,np.arange(3.),[source],
        projection,offset,time_tolerance=0.)
    analytic=head_material_point_jacobian(points,evidence,projection,offset,weight=2.).toarray()
    base=head_material_rows(points,evidence,projection,offset,weight=2.)
    # The observation is at frame2: changing stored frame0 changes only its
    # shared native head dimensions, independently of the sampled pose.
    column=names.index('head')*3+1
    changed=points.copy();changed[0,names.index('head'),1]+=1e-6
    numerical=(head_material_rows(changed,evidence,projection,offset,weight=2.)-base)/1e-6
    assert np.linalg.norm(analytic[:,column])>0
    np.testing.assert_allclose(analytic[:,column],numerical,rtol=2e-3,atol=2e-3)
    column=(2*len(names)+names.index('neck'))*3+1
    changed=points.copy();changed[2,names.index('neck'),1]+=1e-6
    numerical=(head_material_rows(changed,evidence,projection,offset,weight=2.)-base)/1e-6
    np.testing.assert_allclose(analytic[:,column],numerical,rtol=2e-3,atol=2e-3)

def test_head_binding_transports_rotation_and_keeps_skeleton_immutable():
    _,points,names,_,_=_fixture()
    before=points.copy()
    base=head_material_vertices(points,names)
    angle=.7
    rotation=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
    translation=np.array([.2,-.1,.4])
    moved=head_material_vertices(points@rotation.T+translation,names)
    np.testing.assert_allclose(moved,base@rotation.T+translation,atol=1e-12)
    np.testing.assert_array_equal(points,before)
