import hashlib
import json
from pathlib import Path

from exercise_motion_pkg.bake_and_rank import (
    exact_source_validation_effectively_passed,
    load_cached_exact_source_phase_validation,
    source_cut_confirmation_failure_class,
    source_pose_audit_uncertainty_is_verified_and_masked,
)


def _masked_arm_validation(tmp_path):
    video_sha = "a5e454e081dd9c227da016c2f328409ab9ed885cd93730937fbf4e509956cbde"
    event_frames = (13, 14, 15, 16)
    frame_times = [index * (4.0 / 29.97) for index in range(56)] + [7.374040707374041]
    audit = {
        "policyVersion": 1,
        "unresolved": True,
        "events": [
            {
                "frameIndex": index,
                "sourceTimeSec": frame_times[index],
                "joints": ["right_shoulder", "right_elbow", "right_wrist"],
                "originalJoints": {
                    "right_shoulder": [0.4, 0.4, 0.0],
                    "right_elbow": [0.5, 0.5, 0.0],
                    "right_wrist": [0.6, 0.5, 0.0],
                },
                "originalConfidence": {
                    "right_shoulder": 0.99,
                    "right_elbow": 0.99,
                    "right_wrist": 0.99,
                },
                "reason": "unilateral_limb_association_collapse",
                "status": "unknown",
                "independentAnchorsAgree": False,
            }
            for index in event_frames
        ],
        "independentSource": "mediapipe_full_heel_forefoot",
        "independentAvailable": True,
    }
    frames = []
    for index, timestamp in enumerate(frame_times):
        joints = {
            "hips": [0.5, 0.4 if 18 <= index <= 35 else 0.5, 0.0],
            "pelvis": [0.5, 0.4 if 18 <= index <= 35 else 0.5, 0.0],
            "left_ankle": [0.3, 0.8, 0.0],
            "right_ankle": [0.7, 0.8, 0.0],
            "left_shoulder": [0.45, 0.3, 0.0],
            "shoulders": [0.5, 0.3, 0.0],
            "right_shoulder": [0.55, 0.3, 0.0],
            "right_elbow": [0.6, 0.4, 0.0],
            "right_wrist": [0.65, 0.5, 0.0],
        }
        if index in event_frames:
            for name in ("right_shoulder", "right_elbow", "right_wrist"):
                joints.pop(name)
        frames.append({"sourceTimeSec": timestamp, "joints": joints})
    reference_path = tmp_path / "exact_source_pose_reference.json"
    reference_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "validationPolicyVersion": 62,
                "sourceVideoSha256": video_sha,
                "pose": {
                    "sourceTimeOriginSec": 0.0,
                    "frames": frames,
                    "sourcePoseEvidenceAudit": audit,
                },
            }
        ),
        encoding="utf-8",
    )
    validation = {
        "required": True,
        "passed": True,
        "reason": "source_pose_full_repetition_phase_return_detected",
        "frameCount": 3,
        "sampleCount": 57,
        "hasReturnPhase": True,
        "hasCompleteMajorCycle": True,
        "hasSingleMajorCycle": True,
        "dominantMotionRangeRatio": 0.6079471844796998,
        "endpointPhaseDeltaRatio": 0.16179681154105646,
        "sourceVideoSha256": video_sha,
        "sourcePoseReferencePath": str(reference_path),
        "sourcePoseReferenceSha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "sourcePoseEvidenceAudit": audit,
        "sourcePoseEndpointContractValidation": {"available": True, "passed": True},
        "requiredRegionObservations": {
            "required": True,
            "available": True,
            "passed": True,
            "observedFrameCounts": {"hips": 57, "feet": 57, "torso": 57},
        },
        "targetMotionObservabilityMetrics": {"required": True, "passed": True},
    }
    return validation


def test_masked_noncritical_arm_audit_does_not_veto_complete_phase(tmp_path):
    validation = _masked_arm_validation(tmp_path)

    assert source_pose_audit_uncertainty_is_verified_and_masked(validation)
    assert exact_source_validation_effectively_passed(validation)
    assert source_cut_confirmation_failure_class(validation) != "pose_evidence_unresolved"


def test_unknown_joint_still_present_in_bound_pose_fails_closed(tmp_path):
    validation = _masked_arm_validation(tmp_path)
    reference_path = validation["sourcePoseReferencePath"]
    reference = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    reference["pose"]["frames"][13]["joints"]["right_wrist"] = [0.6, 0.5, 0.0]
    Path(reference_path).write_text(json.dumps(reference), encoding="utf-8")
    validation["sourcePoseReferenceSha256"] = hashlib.sha256(
        Path(reference_path).read_bytes()
    ).hexdigest()

    assert not source_pose_audit_uncertainty_is_verified_and_masked(validation)
    assert not exact_source_validation_effectively_passed(validation)


def test_legacy_unresolved_audit_without_reference_digest_fails_closed(tmp_path):
    validation = _masked_arm_validation(tmp_path)
    validation.pop("sourcePoseReferenceSha256")

    assert not source_pose_audit_uncertainty_is_verified_and_masked(validation)
    assert not exact_source_validation_effectively_passed(validation)
    assert source_cut_confirmation_failure_class(validation) == "pose_evidence_unresolved"


def test_legacy_unresolved_phase_cache_is_recomputed_instead_of_reused(tmp_path):
    validation = _masked_arm_validation(tmp_path)
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"retained exact source bytes")
    video_sha = hashlib.sha256(video_path.read_bytes()).hexdigest()
    reference_path = Path(validation["sourcePoseReferencePath"])
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["sourceVideoSha256"] = video_sha
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    validation["sourceVideoSha256"] = video_sha
    validation["sourcePoseReferenceSha256"] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    validation.pop("sourcePoseReferenceSha256")
    cache_path = tmp_path / "phase.json"
    cache_path.write_text(
        json.dumps({"schemaVersion": 6, "cacheKey": "current-key", "metrics": validation}),
        encoding="utf-8",
    )

    assert load_cached_exact_source_phase_validation(
        cache_path=cache_path,
        cache_key="current-key",
        source_video_path=video_path,
    ) is None


def test_masked_audit_does_not_override_missing_required_regions(tmp_path):
    validation = _masked_arm_validation(tmp_path)
    validation["requiredRegionObservations"]["passed"] = False

    assert source_pose_audit_uncertainty_is_verified_and_masked(validation)
    assert not exact_source_validation_effectively_passed(validation)


def test_masked_audit_does_not_override_one_way_partial_phase(tmp_path):
    validation = _masked_arm_validation(tmp_path)
    validation.update(
        passed=False,
        reason="source_pose_one_way_partial_repetition_phase",
        hasReturnPhase=False,
        hasCompleteMajorCycle=False,
        hasSingleMajorCycle=False,
        endpointPhaseDeltaRatio=0.627059,
        maxEndpointPhaseDeltaRatio=0.55,
    )

    assert not exact_source_validation_effectively_passed(validation)
    assert source_cut_confirmation_failure_class(validation) == "pose_confirmed_incomplete"
