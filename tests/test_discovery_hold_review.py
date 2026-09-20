from dataclasses import replace

from exercise_motion_pkg.youtube import (
    YouTubeCandidate,
    build_candidate_vision_prompt,
    candidate_has_debug_review_payload,
)


def candidate():
    return YouTubeCandidate(
        url="https://www.youtube.com/watch?v=hold", video_id="hold",
        title="Hold demonstration", channel="Coach", duration_seconds=20,
        view_count=100, upload_date=None, description_snippet="", thumbnail=None,
    )


def test_static_hold_review_preserves_identity_without_requiring_joint_travel():
    item = candidate()
    prompt = build_candidate_vision_prompt("Supported Hold", item, {
        "completionMode": "stable_hold",
        "advisoryText": "Maintain the prescribed posture and support.",
    })
    assert "joint travel is not required" in prompt
    assert "A single still image is insufficient" in prompt
    assert "required posture and support" in prompt
    assert "wrong_variant" in prompt
    assert "not just the athlete holding the start/end position" not in prompt
    assert "normal-speed, continuous, not paused" not in prompt
    dynamic = build_candidate_vision_prompt("Dynamic movement", item)
    assert "not just the athlete holding the start/end position" in dynamic
    assert "joint travel is not required" not in dynamic


def test_only_stale_negative_hold_review_is_reopened():
    item = candidate()
    item = replace(item, vision_payload={
        "exerciseMotionContract": {"completionMode": "stable_hold"},
        "semanticGate": {"passed": True},
        "sourceRejectionReviewPolicyVersion": 1,
    }, status="rejected")
    assert not candidate_has_debug_review_payload(item)
    item = replace(item, status="recommended")
    assert candidate_has_debug_review_payload(item)
    item = replace(item, status="rejected")
    item.vision_payload["staticHoldReviewPolicyVersion"] = 1
    assert candidate_has_debug_review_payload(item)
    del item.vision_payload["staticHoldReviewPolicyVersion"]
    item.vision_payload["exerciseMotionContract"]["completionMode"] = "return_to_start"
    assert candidate_has_debug_review_payload(item)
