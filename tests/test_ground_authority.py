from dataclasses import replace
from pathlib import Path

import pytest

from exercise_motion_pkg.ground import generate_ground_metadata
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.preview import _clip_has_explicit_render_floor


@pytest.mark.parametrize('contact_joints', [[], ['left_foot'], ['left_knee']])
def test_render_floor_requires_recorded_ground_contacts(tmp_path, contact_joints):
    clip = MotionClip(fps=30., joint_names=['pelvis','left_foot','left_knee'],
        frames=[MotionFrame(0., {'pelvis':(0.,1.,0.),'left_foot':(0.,.2,0.),'left_knee':(0.,.6,0.)})],
        metadata={'cleanup':{'footContacts':[{'contactJoints':contact_joints}]}})
    ground = generate_ground_metadata(video_path=tmp_path/'unused.mp4',cleaned_clip=clip,
        output_path=tmp_path/'ground.json').to_dict()
    assert 'motionGroundPlane' in ground
    assert ('renderGroundPlane' in ground) == bool(contact_joints)
    assert _clip_has_explicit_render_floor(replace(clip,metadata={**clip.metadata,'ground':ground})) == bool(contact_joints)
    if not contact_joints:
        # Retained pre-fix numeric bounds with its old authoritative label
        # must not acquire contact authority at the preview boundary.
        stale = {**ground,'renderSource':'motion_contact_authoritative',
                 'renderGroundPlane':ground['motionGroundPlane']}
        assert not _clip_has_explicit_render_floor(replace(clip,metadata={**clip.metadata,'ground':stale}))


def test_applied_video_floor_survives_without_foot_contacts(tmp_path):
    clip = MotionClip(fps=30.,joint_names=['left_foot'],
        frames=[MotionFrame(0.,{'left_foot':(0.,.2,0.)})],metadata={})
    video = {'applied':True,'framesUsed':2,'cameraGroundPlane':{'normal':[0.,1.,0.],'offset':0.}}
    ground = generate_ground_metadata(video_path=tmp_path/'unused.mp4',cleaned_clip=clip,
        output_path=tmp_path/'ground.json',video_alignment_metadata=video).to_dict()
    assert _clip_has_explicit_render_floor(replace(clip,metadata={'ground':ground}))

def test_html_export_drops_stale_inferred_floor_but_keeps_motion_diagnostic(tmp_path, monkeypatch):
    from exercise_motion_pkg import preview
    ground = {'renderSource':'motion_contact_authoritative',
              'renderGroundPlane':{'normal':[0.,1.,0.],'offset':0.},
              'renderGroundOrigin':{'point':[0.,0.,0.]},
              'motionGroundPlane':{'normal':[0.,1.,0.],'offset':0.}}
    clip = MotionClip(fps=30., joint_names=['pelvis','left_foot'],
        frames=[MotionFrame(0.,{'pelvis':(0.,1.,0.),'left_foot':(0.,.2,0.)})],
        metadata={'ground':ground,'cleanup':{'footContacts':[],
                  'verticalGrounding':{'groundContactMode':'none'}}})
    captured = {}
    def html(payload, **kwargs):
        captured.update(payload)
        return '<html></html>'
    monkeypatch.setattr(preview,'_build_html',html)
    module = tmp_path/'module.js'; module.write_text('// local test module')
    preview.write_preview_html(tmp_path/'preview.html',clip,title='floor authority',three_module_path=module)
    assert 'renderGroundPlane' not in captured['ground']
    assert 'renderGroundOrigin' not in captured['ground']
    assert 'motionGroundPlane' in captured['ground']
    assert 'renderGroundPlane' in clip.metadata['ground']
