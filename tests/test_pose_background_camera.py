from dataclasses import replace

import numpy as np

from exercise_motion_pkg import pose_prefilter as pose
from exercise_motion_pkg.video_utils import BasicVideoMetadata


def samples(*, moving_camera=False, scene_cut=False):
    metadata = BasicVideoMetadata(8, 4, 320, 240)
    yy, xx = np.indices((240, 320))
    gray = np.where(((xx // 16 + yy // 16) % 2) == 0, 40, 130).astype(np.uint8)
    background = np.repeat(gray[:, :, None], 3, axis=2)
    result = []
    for index in range(4):
        frame = np.roll(background, 12 * index if moving_camera else 0, axis=1).copy()
        if scene_cut and index >= 2:
            frame[:] = 240
        x = 70 if index % 2 == 0 else 150
        box = (x, 45, x + 80, 205)
        frame[45:205, x:x + 80] = 255
        detection = pose.PoseDetection({}, box)
        result.append(pose.PoseSample(index / 8, [detection],
            frame_layout_signature=pose.compute_frame_layout_signature(frame),
            frame_edge_signature=pose.compute_frame_edge_signature(frame),
            frame_background_mask=pose.background_signature_mask([detection], metadata=metadata)))
    return result


def test_subject_motion_does_not_become_camera_motion():
    observed = samples()
    old = pose.frame_visual_jump_metrics([replace(s, frame_background_mask=None) for s in observed])
    assert old["visualContinuityCutCount"] or old["excessiveCameraMotion"]
    current = pose.frame_visual_jump_metrics(observed)
    assert current["backgroundComparedPairs"] == 3
    assert current["visualContinuityCutCount"] == 0
    assert not current["excessiveCameraMotion"]


def test_background_pan_and_scene_cut_remain_rejected():
    for observed in (samples(moving_camera=True), samples(scene_cut=True)):
        result = pose.frame_visual_jump_metrics(observed)
        assert result["backgroundComparedPairs"] == 3
        assert result["visualContinuityCutCount"] or result["excessiveCameraMotion"]


def test_insufficient_background_keeps_whole_image_check():
    observed = [replace(s, frame_background_mask=(False,) * 576) for s in samples()]
    result = pose.frame_visual_jump_metrics(observed)
    assert result["backgroundComparedPairs"] == 0
    assert result["visualContinuityCutCount"] or result["excessiveCameraMotion"]


def test_cached_camera_rejections_reopen_without_invalidating_positive_reviews():
    from exercise_motion_pkg.youtube import YouTubeCandidate, candidate_has_debug_review_payload
    payload = {"passed": False, "blockingIssues": ["camera_or_track_instability"]}
    candidate = YouTubeCandidate("video", "id", "Exercise", None, 20, None, None, None, None,
        status="rejected", vision_payload={"posePrefilter": payload, "sourceRejectionReviewPolicyVersion": 1})
    assert pose.pose_camera_review_is_stale(payload)
    assert not candidate_has_debug_review_payload(candidate)
    assert candidate_has_debug_review_payload(replace(candidate, status="recommended"))
    payload["cameraPolicyVersion"] = pose.POSE_CAMERA_POLICY_VERSION
    assert not pose.pose_camera_review_is_stale(payload)
    assert candidate_has_debug_review_payload(candidate)
    del payload["cameraPolicyVersion"]
    payload["blockingIssues"] = ["cropped_body"]
    assert not pose.pose_camera_review_is_stale(payload)
    assert candidate_has_debug_review_payload(candidate)
