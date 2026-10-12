import pytest

from exercise_motion_pkg import source_review_authority as authority


@pytest.mark.parametrize(
    ("metrics", "visual_integrity_passed", "expected"),
    [
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {
                    "required": True,
                    "passed": True,
                    "reason": "source_pose_full_repetition_phase_return_detected",
                    "phaseSignalEvidence": {"resolved": True},
                },
                "targetMotionObservability": {
                    "required": True,
                    "passed": False,
                    "failureReasons": ["weak_observable_target_motion"],
                },
                "sourcePoseEndpointContractValidation": {"available": True, "passed": True},
            },
            True,
            True,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {
                    "required": True,
                    "passed": False,
                    "reason": "source_pose_dominant_motion_not_resolved_from_clip_noise",
                    "phaseSignalEvidence": {"resolved": False},
                },
            },
            True,
            True,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {
                    "required": False,
                    "passed": True,
                },
                "targetMotionObservability": {"required": True, "available": False},
                "sourcePoseEndpointContractValidation": {"available": True, "passed": True},
            },
            True,
            True,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {"required": False},
                "sourcePoseEndpointContractValidation": {"available": False},
            },
            True,
            True,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {
                    "required": True,
                    "passed": False,
                    "reason": "source_pose_one_way_partial_repetition_phase",
                    "phaseSignalEvidence": {"resolved": True},
                },
                "targetMotionObservability": {"required": True, "passed": True},
                "sourcePoseEndpointContractValidation": {"available": True, "passed": True},
            },
            True,
            False,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {
                    "required": True,
                    "passed": True,
                    "phaseSignalEvidence": {"resolved": True},
                },
                "requiredRegionObservations": {
                    "required": True,
                    "available": True,
                    "passed": False,
                },
            },
            True,
            False,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {"required": False},
                "targetMotionObservability": {"required": True, "passed": False},
                "sourcePoseEndpointContractValidation": {"available": True, "passed": True},
            },
            True,
            False,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {"required": False},
                "sourcePoseEndpointContractValidation": {
                    "available": True,
                    "passed": False,
                    "blockingMismatches": [{"field": "supportMode"}],
                    "rawBlockingMismatches": [{"field": "supportMode"}],
                },
            },
            True,
            False,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {"required": False},
                "sourcePoseEndpointContractValidation": {
                    "available": True,
                    "passed": False,
                    "blockingMismatches": [],
                    "rawBlockingMismatches": [],
                    "diagnosticOnlyMismatches": [{"field": "handHeight"}],
                },
            },
            True,
            True,
        ),
        (
            {
                "candidateFullRepetitionPhaseCompletenessMetrics": {
                    "required": True,
                    "passed": False,
                    "reason": "source_pose_samples_unavailable",
                },
            },
            False,
            False,
        ),
    ],
)
def test_pose_evidence_review_status(metrics, visual_integrity_passed, expected):
    assert authority.source_cut_pose_evidence_needs_review(
        metrics,
        visual_integrity_passed=visual_integrity_passed,
    ) is expected
