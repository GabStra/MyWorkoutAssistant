import json
import math

import numpy as np
import pytest

from exercise_motion_pkg.cleanup import _rotate_clip_about_axis
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.motion_io import load_motion_json, save_motion_json
from exercise_motion_pkg.pipeline import canonicalize_camera_motion_clip
from exercise_motion_pkg.structural_refinement import _suppress_temporal_spikes


KEY = "left_ankle->left_foot"
PROVENANCE = "gvhmr_ankle_global_smpl_rotation"


def test_motion_io_roundtrips_optional_bone_side_channels(tmp_path):
    clip = MotionClip(
        fps=30.0,
        joint_names=["left_ankle", "left_foot"],
        frames=[MotionFrame(
            time_sec=0.0,
            joints={"left_ankle": (0., 0., 0.), "left_foot": (1., 0., 0.)},
            bone_sides={KEY: (0., 1., 0.)},
            bone_side_provenance={KEY: PROVENANCE},
        )],
    )
    path = tmp_path / "motion.json"
    save_motion_json(path, clip)
    loaded = load_motion_json(path)
    assert loaded.frames[0].bone_sides == {KEY: (0., 1., 0.)}
    assert loaded.frames[0].bone_side_provenance == {KEY: PROVENANCE}

    legacy = MotionClip(fps=30., joint_names=clip.joint_names,
                        frames=[MotionFrame(time_sec=0., joints=clip.frames[0].joints)])
    save_motion_json(path, legacy)
    frame = json.loads(path.read_text(encoding="utf-8"))["frames"][0]
    assert "boneSides" not in frame
    assert "boneSideProvenance" not in frame


def test_rigid_cleanup_and_nonrigid_edit_transport_side_axis(tmp_path):
    frame = MotionFrame(
        time_sec=0.,
        joints={"left_ankle": (0., 0., 0.), "left_foot": (1., 0., 0.)},
        bone_sides={KEY: (0., 1., 0.)},
        bone_side_provenance={KEY: PROVENANCE},
    )
    clip = MotionClip(fps=30., joint_names=list(frame.joints), frames=[frame])

    # Reconstruction camera -> Y-up is a known rigid X rotation.
    canonical = canonicalize_camera_motion_clip(clip)
    np.testing.assert_allclose(canonical.frames[0].bone_sides[KEY], [0., -1., 0.])
    # The cleanup-level rigid Z rotation must carry the vector as well as joints.
    rotated = _rotate_clip_about_axis(
        canonical, pivot=(0., 0., 0.), axis=(0., 0., 1.), angle_radians=math.pi / 2)
    np.testing.assert_allclose(rotated.frames[0].bone_sides[KEY], [1., 0., 0.], atol=1e-12)

    # A non-rigid edit has no known axial roll; carry the existing side by the
    # minimum bone-direction rotation and retain producer provenance.
    edited_joints = {"left_ankle": (0., 0., 0.), "left_foot": (0., 0., 1.)}
    edited = rotated.frames[0].with_joints(edited_joints)
    np.testing.assert_allclose(edited.bone_sides[KEY], [1., 0., 0.], atol=1e-12)
    assert edited.bone_side_provenance == {KEY: PROVENANCE}

    path = tmp_path / "cleaned.json"
    save_motion_json(path, MotionClip(fps=30., joint_names=list(edited.joints), frames=[edited]))
    reloaded = load_motion_json(path).frames[0]
    assert reloaded.bone_sides == edited.bone_sides
    assert reloaded.bone_side_provenance == edited.bone_side_provenance


@pytest.mark.parametrize("frame_fields", [
    {"boneSides": []},
    {"boneSides": {KEY: [1., 2.]}},
    {"boneSides": {KEY: [1., "2", 3.]}},
    {"boneSides": {KEY: [1., float("nan"), 3.]}},
    {"boneSideProvenance": []},
    {"boneSideProvenance": {KEY: 7}},
])
def test_motion_io_rejects_malformed_present_bone_side_fields(tmp_path, frame_fields):
    payload = {
        "fps": 30., "jointNames": ["left_ankle", "left_foot"],
        "frames": [{"timeSec": 0., "joints": {
            "left_ankle": [0., 0., 0.], "left_foot": [1., 0., 0.],
        }, **frame_fields}],
    }
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_motion_json(path)


def test_structural_spike_repair_transports_bone_side_channels():
    frames = []
    for index, foot in enumerate(((0.2, 0., 0.), (0.2, 0.2, 0.), (0.2, 0., 0.))):
        frames.append(MotionFrame(
            time_sec=index / 30.,
            source_time_sec=10. + index / 30.,
            source_frame_index=100 + index,
            inference_frame_index=200 + index,
            joints={"left_ankle": (0., 0., 0.), "left_foot": foot},
            bone_sides={KEY: (0., 1., 0.)},
            bone_side_provenance={KEY: PROVENANCE},
        ))
    clip = MotionClip(fps=30., joint_names=["left_ankle", "left_foot"], frames=frames)

    repaired, report = _suppress_temporal_spikes(clip, active_threshold=0.01)

    assert report["applied"] is True
    middle = repaired.frames[1]
    assert middle.joints["left_foot"] != clip.frames[1].joints["left_foot"]
    assert middle.bone_sides is not None
    side = middle.bone_sides[KEY]
    bone = tuple(middle.joints["left_foot"][axis] - middle.joints["left_ankle"][axis]
                 for axis in range(3))
    assert abs(sum(side[axis] * bone[axis] for axis in range(3))) < 1e-10
    assert middle.bone_side_provenance == {KEY: PROVENANCE}
    assert (middle.source_time_sec, middle.source_frame_index, middle.inference_frame_index) == (
        10. + 1 / 30., 101, 201)
