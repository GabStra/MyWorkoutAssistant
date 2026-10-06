from types import SimpleNamespace

import pytest

from exercise_motion_pkg.youtube import (
    source_review_pose_motion_evidence,
    source_review_temporal_change_metrics,
)


def test_distal_motion_profile_retains_person_region():
    candidate = SimpleNamespace(vision_payload={"posePrefilter": {
        "passed": True,
        "validChunks": [{
            "startSeconds": 0, "endSeconds": 2,
            "targetMotionObservability": {
                "passed": True, "distalVerticalRangeRatio": 0.06,
                "minDistalVerticalRangeRatio": 0.035,
            },
            "sourceWindowIntegrity": {"passed": True},
        }],
        "dominantPoseSamples": [
            {"timeSeconds": t, "bbox": [0.4, 0.1, 0.55, 0.9]}
            for t in (0, 1, 2)
        ],
    }})
    evidence = source_review_pose_motion_evidence(candidate, start_seconds=0, end_seconds=2)
    assert evidence is not None
    assert evidence["normalizedPersonRoi"] is not None
    assert evidence["strongMotion"] is False


def test_small_moving_subject_without_pose_is_not_declared_static(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    paths = []
    for index in range(8):
        frame = np.full((360, 640), 96, dtype=np.uint8)
        x = 270 + index * 2
        frame[145:185, x:x + 14] = 220
        path = tmp_path / f"frame_{index}.png"
        assert cv2.imwrite(str(path), frame)
        paths.append(path)
    metrics = source_review_temporal_change_metrics(paths)
    assert metrics["globalNearIdenticalFrames"] is True
    assert metrics["nearIdenticalFrames"] is False
    assert metrics["reason"] == "insufficient_person_motion_evidence"


def test_legacy_boundary_override_cannot_supply_identity_review():
    from exercise_motion_pkg.bake_and_rank import candidate_completed_identity_review
    from exercise_motion_pkg.youtube import candidate_has_debug_review_payload

    payload = {"target_identity_match": True, "source_score": 0.9,
               "sourceObservedBoundaryAuthoritative": True}
    candidate = SimpleNamespace(candidate={"visionPayload": payload, "visionScore": 0.9})
    assert candidate_completed_identity_review(candidate) is False
    discovery_candidate = SimpleNamespace(vision_payload=payload, vision_score=0.9)
    assert candidate_has_debug_review_payload(discovery_candidate) is False
    payload.pop("sourceObservedBoundaryAuthoritative")
    assert candidate_completed_identity_review(candidate) is True
    assert candidate_has_debug_review_payload(discovery_candidate) is True
