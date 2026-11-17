from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nonfoot_support_fixture import FPS, build_nonfoot_support_fixture

from exercise_motion_pkg import body_support_observation as bso
from exercise_motion_pkg import foot_contact_observation as fco
from exercise_motion_pkg import source_support_stage
from exercise_motion_pkg import support_geometry
from exercise_motion_pkg.bake_and_rank import body_support_contract_evidence_status
from exercise_motion_pkg.source_support_tracking import FOOT_MATERIAL_POLICY_VERSION
from exercise_motion_pkg.source_frame_clock import (
    build_source_frame_clock, source_frame_clock_path_for_video, write_source_frame_clock,
)


def _observation(digest: str, surface: str):
    return {
        "status": "observed",
        "source": "exact_source_visual_support_observation",
        "sourceVideoSha256": digest,
        "policyVersion": bso.POLICY_VERSION,
        "observation": {
            "pelvis": "unknown", "pelvisContactSurface": "unknown",
            "upperBack": "stationary_support", "upperBackContactSurface": surface,
            "head": "unknown", "headContactSurface": "unknown",
            "leftKnee": "unknown", "leftKneeContactSurface": "unknown",
            "rightKnee": "unknown", "rightKneeContactSurface": "unknown",
        },
        "contactTimeline": {
            "schemaVersion": 1,
            "policyVersion": bso.CONTACT_TIMELINE_POLICY_VERSION,
            "source": "exact_source_visual_contact_timeline",
            "sourceVideoSha256": digest,
            "sourceClock": "video_frame_zero_seconds",
            "status": "observed",
            "samples": [],
        },
    }


def test_unresolved_required_legacy_region_reviews_and_does_not_short_circuit_sole_followup(
    tmp_path, monkeypatch,
):
    video, pose_reference_path, pose_reference, _payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=4, sides=(),
    )
    write_source_frame_clock(
        build_source_frame_clock(source_video_path=video, output_video_path=video,
                                 crop_start_seconds=0.0, output_fps=FPS),
        output_path=source_frame_clock_path_for_video(video),
    )
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    pose_reference_sha = hashlib.sha256(pose_reference_path.read_bytes()).hexdigest()
    phase_validation_path = video.parent.parent / "segment_detection" / "exact_source_phase_validation.json"
    phase_validation_path.write_text(json.dumps({"metrics": {
        "validationPolicyVersion": 62,
        "sourceVideoSha256": digest,
        "sourcePoseReferencePath": str(pose_reference_path.resolve()),
        "sourcePoseReferenceSha256": pose_reference_sha,
    }}), encoding="utf-8")
    original_observation = _observation(digest, "other")
    evidence = {
        "sourceVideoSha256": digest,
        "bodySupportObservation": original_observation,
        "footPatchEvidence": {
            "available": True, "sourceVideoSha256": digest,
            "policyVersion": fco.POLICY_VERSION,
            "materialStationarityPolicyVersion": FOOT_MATERIAL_POLICY_VERSION,
        },
    }
    contract = {"bodySupportRequirements": {
        "required": [{"region": "upper_back", "side": "center", "surface": "bench"}],
        "prohibited": [],
    }}
    pose = pose_reference.get("pose", pose_reference)
    status_calls = []
    interval_calls = []
    surface_calls = []
    fail_review = True

    monkeypatch.setattr(bso, "source_support_observation_needed", lambda *_a, **_k: False)
    monkeypatch.setattr(bso, "observe_body_support", lambda *_a, **_k: original_observation)
    monkeypatch.setattr(bso, "materialize_knee_support", lambda *_a, **_k: None)
    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr(
        support_geometry, "pre_reconstruction_source_support_readiness",
        lambda *_a, **_k: {"passed": False, "status": "incomplete",
                           "rejectionReasons": ["source_support_incomplete"]},
    )
    monkeypatch.setattr(
        source_support_stage, "refresh_source_foot_contacts_from_dense_sole_review",
        lambda *_a, **_k: None,
    )

    def status_fn(_contract, current, **_kwargs):
        status_calls.append(copy.deepcopy(current.get("bodySurfaceContactEvidence")))
        return {"status": "insufficient_evidence",
                "failures": ["required_upper_back_center_support_unobserved"]}

    def review_samples(record, *_args, **kwargs):
        assert kwargs["source_pose_reference_path"] == pose_reference_path.resolve()
        assert kwargs["source_pose_reference_sha256"] == pose_reference_sha
        surface_calls.append(record["bodyRegion"])
        if fail_review:
            raise RuntimeError("vision callback failed: api_key=secret-value")
        rows = [{**row, "contactState": "no_contact", "visible": True}
                for row in record["sourceEvidence"]["observations"]]
        reviewed = {**record, "sourceEvidence": {**record["sourceEvidence"],
                                                  "observations": rows}}
        return {
            "record": reviewed, "receiptPath": "mock-receipt.json",
            "receiptSha256": "mock-receipt-sha",
            "verifiedEvidence": {
                "coverage": {"allCanonicalPoseFramesObserved": True,
                             "canonicalPoseFrameCount": len(rows)},
                "samples": rows,
            },
        }

    import exercise_motion_pkg.body_surface_evidence as body_surface_evidence
    monkeypatch.setattr(body_surface_evidence, "review_body_surface_contact_samples", review_samples)

    def interval_review(*_args, **_kwargs):
        interval_calls.append(True)
        return {"status": "observed", "feet": {}}

    monkeypatch.setattr(bso, "observe_stationary_sole_intervals", interval_review)

    failed = source_support_stage.observe_source_support_stage(
        video.parent.parent, video, contract=contract, caption_images=lambda **_k: "{}",
        source_pose=pose, source_pose_reference=pose_reference,
        source_foot_support_evidence=evidence, contract_status_fn=status_fn,
        persist_evidence=False, write_repair_marker=False,
    )
    failed_review = failed["evidence"]["bodySurfaceContactEvidence"]["reviews"][0]
    assert failed_review["status"] == "unresolved"
    assert failed_review["reason"] == "visual_review_unavailable"
    assert failed_review["failure"] == {
        "exceptionType": "RuntimeError",
        "exceptionMessage": "vision callback failed: api_key=[redacted]",
    }
    assert all(row["contactState"] == "unknown"
               for row in failed_review["record"]["sourceEvidence"]["observations"])
    assert failed["contractStatus"]["status"] == "insufficient_evidence"

    fail_review = False
    surface_calls.clear()
    interval_calls.clear()
    result = source_support_stage.observe_source_support_stage(
        video.parent.parent, video, contract=contract, caption_images=lambda **_k: "{}",
        source_pose=pose, source_pose_reference=pose_reference,
        source_foot_support_evidence=evidence, contract_status_fn=status_fn,
        persist_evidence=False, write_repair_marker=False,
    )

    regional = result["evidence"]["bodySurfaceContactEvidence"]
    assert regional["sourcePoseReferencePath"] == str(pose_reference_path.resolve())
    assert regional["sourcePoseReferenceSha256"] == pose_reference_sha
    assert surface_calls == [{"name": "upper_back", "side": "center"}]
    assert regional["reviews"][0]["requirement"]["surface"] == "bench"
    assert all(row["contactState"] == "no_contact"
               for row in regional["reviews"][0]["record"]["sourceEvidence"]["observations"])
    assert result["evidence"]["bodySupportObservation"]["observation"][
        "upperBackContactSurface"] == "other"
    assert len(interval_calls) == 1
    assert result["stationarySoleReviewAttempted"] is True
    assert result["contractInsufficient"] is True

    # A now-complete legacy typed/timed result does not schedule the fallback.
    surface_calls.clear()
    interval_calls.clear()
    monkeypatch.setattr(
        support_geometry, "pre_reconstruction_source_support_readiness",
        lambda *_a, **_k: {"passed": True, "status": "ready", "rejectionReasons": []},
    )
    monkeypatch.setattr(bso, "source_sole_review_side_eligibility", lambda *_a, **_k: "eligible")
    complete_observation = _observation(digest, "bench")
    complete_evidence = {"sourceVideoSha256": digest,
                         "bodySupportObservation": complete_observation,
                         "footPatchEvidence": {
                             "available": True, "sourceVideoSha256": digest,
                             "policyVersion": fco.POLICY_VERSION,
                             "materialStationarityPolicyVersion": FOOT_MATERIAL_POLICY_VERSION,
                         }}
    completed = source_support_stage.observe_source_support_stage(
        video.parent.parent, video, contract=contract, caption_images=lambda **_k: "{}",
        source_pose=pose, source_pose_reference=pose_reference,
        source_foot_support_evidence=complete_evidence,
        contract_status_fn=lambda *_a, **_k: {"status": "passed", "failures": []},
        persist_evidence=False, write_repair_marker=False,
    )
    assert surface_calls == []
    assert interval_calls == []
    assert completed["contractStatus"]["status"] == "passed"


def test_nested_pose_receipt_binding_reaches_contract_consumer(tmp_path, monkeypatch):
    video, pose_reference_path, pose_reference, _payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=4, sides=(),
    )
    write_source_frame_clock(
        build_source_frame_clock(source_video_path=video, output_video_path=video,
                                 crop_start_seconds=0.0, output_fps=FPS),
        output_path=source_frame_clock_path_for_video(video),
    )
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    pose_sha = hashlib.sha256(pose_reference_path.read_bytes()).hexdigest()
    phase_path = video.parent.parent / "segment_detection" / "exact_source_phase_validation.json"
    phase_path.write_text(json.dumps({"metrics": {
        "validationPolicyVersion": 62,
        "sourceVideoSha256": digest,
        "sourcePoseReferencePath": str(pose_reference_path.resolve()),
        "sourcePoseReferenceSha256": pose_sha,
    }}), encoding="utf-8")

    observation = _observation(digest, "unknown")
    evidence = {
        "sourceVideoSha256": digest,
        "bodySupportObservation": observation,
        "footPatchEvidence": {
            "available": True, "sourceVideoSha256": digest,
            "policyVersion": fco.POLICY_VERSION,
            "materialStationarityPolicyVersion": FOOT_MATERIAL_POLICY_VERSION,
        },
    }
    contract = {"bodySupportRequirements": {
        "required": [{"region": "upper_back", "side": "center", "surface": "bench"}],
        "prohibited": [],
    }}
    pose = pose_reference.get("pose", pose_reference)
    expected_states = ["direct_contact", "direct_contact", "no_contact", "direct_contact"]
    verifier_calls = []

    monkeypatch.setattr(bso, "source_support_observation_needed", lambda *_a, **_k: False)
    monkeypatch.setattr(bso, "observe_body_support", lambda *_a, **_k: observation)
    monkeypatch.setattr(bso, "materialize_knee_support", lambda *_a, **_k: None)
    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr(
        support_geometry, "pre_reconstruction_source_support_readiness",
        lambda *_a, **_k: {"passed": True, "status": "ready", "rejectionReasons": []},
    )
    monkeypatch.setattr(
        source_support_stage, "refresh_source_foot_contacts_from_dense_sole_review",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(bso, "source_sole_review_side_eligibility", lambda *_a, **_k: "ineligible")

    def review_samples(record, *_args, **_kwargs):
        rows = [
            {**row, "contactState": state, "visible": True}
            for row, state in zip(record["sourceEvidence"]["observations"], expected_states)
        ]
        reviewed_record = {**record, "sourceEvidence": {
            **record["sourceEvidence"], "observations": rows,
        }}
        return {
            "record": reviewed_record,
            "receiptPath": str(tmp_path / "cached-review.json"),
            "receiptSha256": "cached-review-sha",
            "verifiedEvidence": {
                "coverage": {"allCanonicalPoseFramesObserved": True,
                             "canonicalPoseFrameCount": len(rows)},
                "samples": rows,
            },
        }

    import exercise_motion_pkg.body_surface_evidence as body_surface_evidence
    monkeypatch.setattr(body_surface_evidence, "review_body_surface_contact_samples", review_samples)

    def verify_cached(record, _video, _source_pose, **kwargs):
        verifier_calls.append(kwargs)
        return {
            "coverage": {"allCanonicalPoseFramesObserved": True,
                         "canonicalPoseFrameCount": len(expected_states)},
            "samples": [{"contactState": state} for state in expected_states],
        }

    monkeypatch.setattr(body_surface_evidence, "verify_body_surface_contact_evidence", verify_cached)

    def current_status(current_contract, current_evidence, *, source_pose=None):
        return body_support_contract_evidence_status(
            current_contract, current_evidence, source_pose=source_pose,
            selected_video_path=video,
        )

    result = source_support_stage.observe_source_support_stage(
        video.parent.parent, video, contract=contract, caption_images=lambda **_k: "{}",
        source_pose=pose, source_pose_reference=pose_reference,
        source_foot_support_evidence=evidence, contract_status_fn=current_status,
        persist_evidence=False, write_repair_marker=False,
    )

    regional = result["evidence"]["bodySurfaceContactEvidence"]
    assert regional["sourcePoseReferencePath"] == str(pose_reference_path.resolve())
    assert regional["sourcePoseReferenceSha256"] == pose_sha
    assert len(verifier_calls) == 1
    assert Path(verifier_calls[0]["source_pose_reference_path"]).resolve() == pose_reference_path.resolve()
    assert verifier_calls[0]["source_pose_reference_sha256"] == pose_sha
    assert [row["contactState"] for row in regional["reviews"][0]["record"][
        "sourceEvidence"]["observations"]] == expected_states
    assert result["contractStatus"] == {
        "status": "contradicted",
        "failures": ["required_upper_back_center_support_missing"],
    }
