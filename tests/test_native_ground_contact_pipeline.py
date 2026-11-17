import hashlib
import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.ground import (
    clip_has_render_floor_authority,
    estimate_native_ground_plane_from_source_support,
)
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.foot_geometry import foot_scale_from_pose, shoe_vertices
from exercise_motion_pkg.native_foot_geometry import native_foot_geometry_from_prior


FIXTURE = Path(__file__).parent / "fixtures" / "native_foot_geometry_v1.json"


def _case(tmp_path, monkeypatch):
    prior = json.loads(FIXTURE.read_text(encoding="utf-8"))["sourcePrior"]
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"selected source bytes")
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    clock = tmp_path / "selected.clock.json"
    clock.write_text("{}", encoding="utf-8")
    clock_sha = hashlib.sha256(clock.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "exercise_motion_pkg.source_frame_clock.load_verified_source_frame_clock",
        lambda path, *, expected_video_path=None: {
            "verified": True, "outputVideoSha256": video_sha, "outputFrameCount": 1,
            "outputFps": 30., "frames": [{"outputFrameIndex": 0,
                                             "sourceFrameIndex": 0,
                                             "sourceTimeSec": 0.}],
        })
    names = ["pelvis", "left_hip", "right_hip", "left_shoulder", "right_shoulder",
             "left_ankle", "left_foot", "right_ankle", "right_foot"]
    joints = {
        "pelvis": (0., 1., 0.), "left_hip": (-.1, .9, 0.), "right_hip": (.1, .9, 0.),
        "left_shoulder": (-.2, 1.4, 0.), "right_shoulder": (.2, 1.4, 0.),
        "left_ankle": (-.1, .2, 0.), "left_foot": (-.1, .2, .134302),
        "right_ankle": (.1, .2, 0.), "right_foot": (.1, .2, .134302),
    }
    sides = {"left_ankle->left_foot": (1., 0., 0.),
             "right_ankle->right_foot": (1., 0., 0.)}
    frame = MotionFrame(0., joints, source_time_sec=0., source_frame_index=0,
                        bone_sides=sides)
    mapping = {
        "verified": True,
        "mappingKind": "selected_segment_to_parent_source",
        "selectedSegmentSha256": video_sha,
        "selectedFrameClockReceiptPath": str(clock),
        "selectedFrameClockReceiptSha256": clock_sha,
        "selectedFrameLineage": [{"selectedFrameIndex": 0, "selectedFrameTimeSec": 0.,
                                   "parentSourceFrameIndex": 0,
                                   "parentSourceTimeSec": 0.}],
    }
    clip = MotionClip(
        fps=30., joint_names=names, frames=[frame],
        metadata={"reconstruction": {"footMarkerPrior": prior},
                  "sourceTimelineMapping": mapping})
    def row(sample_id, side, surface, state="full_sole"):
        return {"sampleId": sample_id, "side": side, "landmark": "foot",
                "contactState": state, "surface": surface, "visible": True,
                "sourceTimeSec": 0., "sourceFps": 30., "sourceFrameIndex": 0,
                "sourcePoseFrameIndex": 0, "sourceTrackStationary": False,
                "reviewOnly": True}
    observation = {
        "schemaVersion": 1, "policyVersion": 8,
        "source": "exact_source_visual_support_observation",
        "sourceVideoSha256": video_sha, "status": "observed",
        "contactTimeline": {
            "schemaVersion": 1, "policyVersion": 8,
            "source": "exact_source_visual_contact_timeline",
            "sourceClock": "video_frame_zero_seconds", "status": "observed",
            "sourceVideoSha256": video_sha,
            "samples": [row("left-slide", "left", "ground"),
                        row("right-bench", "right", "raised_surface")],
        },
    }
    evidence = {"sourceVideoSha256": video_sha, "bodySupportObservation": observation}
    return clip, evidence, video


def test_native_ground_plane_uses_source_ground_rows_native_mesh_and_single_shift(tmp_path, monkeypatch):
    clip, evidence, video = _case(tmp_path, monkeypatch)
    plane = estimate_native_ground_plane_from_source_support(
        clip, evidence, selected_video_path=video)
    assert plane is not None
    assert plane["sampleCount"] == 1
    assert plane["samples"][0]["side"] == "left"
    assert plane["samples"][0]["patchRole"] == "full_sole"
    assert plane["samples"][0]["sampleId"] == "left-slide"

    before = clip.frames[0]
    scale = foot_scale_from_pose(np.asarray([before.joints[name] for name in clip.joint_names]),
                                 clip.joint_names)
    mesh_before = shoe_vertices(
        np.asarray(before.joints["left_ankle"]), np.asarray(before.joints["left_foot"]),
        np.asarray(before.bone_sides["left_ankle->left_foot"]), None, scale,
        native_geometry=native_foot_geometry_from_prior(
            clip.metadata["reconstruction"]["footMarkerPrior"])["sides"]["left"])
    from exercise_motion_pkg.cleanup import ground_to_floor
    grounded = ground_to_floor(clip, floor_height=plane["planeOffsetMeters"])
    for name in clip.joint_names:
        assert grounded.frames[0].joints[name][1] == (
            before.joints[name][1] - plane["planeOffsetMeters"])
    assert float(mesh_before[:, 1].min()) == plane["planeOffsetMeters"]


def test_invalid_selected_video_binding_fails_closed_and_never_uses_joint_contacts(
        tmp_path, monkeypatch):
    clip, evidence, video = _case(tmp_path, monkeypatch)
    evidence["sourceVideoSha256"] = "0" * 64
    assert estimate_native_ground_plane_from_source_support(
        clip, evidence, selected_video_path=video) is None
    clip.metadata["cleanup"] = {
        "footContacts": [{"contactJoints": ["left_foot"]}],
        "nativeFootGeometryAvailable": True,
    }
    assert clip_has_render_floor_authority(clip) is False
