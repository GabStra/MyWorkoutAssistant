from __future__ import annotations

import hashlib
import json
import sys
import copy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nonfoot_support_fixture import build_nonfoot_support_fixture, FPS

from exercise_motion_pkg import body_support_observation as bso
from exercise_motion_pkg import source_support_stage
from exercise_motion_pkg import support_geometry
from exercise_motion_pkg.source_frame_clock import (
    build_source_frame_clock, source_frame_clock_path_for_video, write_source_frame_clock,
)


def test_normal_source_stage_records_generic_contact_but_keeps_incomplete_review_unresolved(
    tmp_path, monkeypatch,
):
    video, _reference_path, pose_reference, payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=4, sides=("left",))
    clock = build_source_frame_clock(
        source_video_path=video, output_video_path=video,
        crop_start_seconds=0.0, output_fps=FPS)
    write_source_frame_clock(clock, output_path=source_frame_clock_path_for_video(video))
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    workspace = video.parent.parent
    monkeypatch.setattr(bso, "source_support_observation_needed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(bso, "observe_body_support", lambda *_args, **_kwargs: {
        "status": "unknown", "sourceVideoSha256": digest, "observation": {}})
    monkeypatch.setattr(bso, "validated_body_support_answer", lambda *_args, **_kwargs: {
        "leftKnee": "unknown", "rightKnee": "unknown"})
    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bso, "materialize_knee_support", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bso, "observe_stationary_sole_intervals", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(support_geometry, "pre_reconstruction_source_support_readiness",
                        lambda *_args, **_kwargs: {"passed": False, "status": "incomplete",
                                                   "rejectionReasons": ["source_support_incomplete"]})
    caption_calls = []

    def caption_images(*, frame_paths, prompt, **_kwargs):
        assert len(frame_paths) == 1 and frame_paths[0].suffix == ".png"
        caption_calls.append(prompt)
        aliases = _kwargs["response_schema"]["required"]
        return json.dumps({alias: "unresolved" for alias in aliases})

    result = source_support_stage.observe_source_support_stage(
        workspace, video,
        contract={"bodySupportRequirements": {"required": [
            {"region": "shoulder", "side": "left", "surface": "bench"}], "prohibited": []}},
        caption_images=caption_images, source_pose=None,
        source_pose_reference=pose_reference,
        source_foot_support_evidence={"sourceVideoSha256": digest, "contacts": []},
        contract_status_fn=lambda *_args, **_kwargs: {
            "status": "insufficient_evidence", "failures": ["required_shoulder_left_support_unobserved"]},
        persist_evidence=False,
    )

    regional = result["evidence"]["bodySurfaceContactEvidence"]
    assert caption_calls
    first_call_count = len(caption_calls)
    assert regional["status"] == "insufficient_evidence"
    assert regional["sourceApproval"] is False and regional["geometryApproval"] is False
    review = regional["reviews"][0]
    assert review["requirement"]["region"] == "shoulder"
    assert review["record"]["bodyRegion"] == {"name": "shoulder", "side": "left"}
    assert review["status"] == "unresolved"
    assert review["coverage"]["allCanonicalPoseFramesObserved"] is True
    assert all(row["contactState"] == "unknown" and row["visible"] is False
               for row in review["record"]["sourceEvidence"]["observations"])
    assert result["contractInsufficient"] is True

    stale_cache = copy.deepcopy(result["evidence"])
    stale_cache["bodySurfaceContactEvidence"]["reviews"][0]["requirement"]["surface"] = "floor"
    rerun = source_support_stage.observe_source_support_stage(
        workspace, video,
        contract={"bodySupportRequirements": {"required": [
            {"region": "shoulder", "side": "left", "surface": "bench"}], "prohibited": []}},
        caption_images=caption_images, source_pose=None,
        source_pose_reference=pose_reference,
        source_foot_support_evidence=stale_cache,
        contract_status_fn=lambda *_args, **_kwargs: {
            "status": "insufficient_evidence", "failures": ["required_shoulder_left_support_unobserved"]},
        persist_evidence=False,
    )
    assert len(caption_calls) == first_call_count
    assert rerun["evidence"]["bodySurfaceContactEvidence"]["reviews"][0][
        "requirement"]["surface"] == "bench"


def test_cache_only_unavailable_refresh_preserves_review_and_passes_exact_video(monkeypatch, tmp_path):
    video, _reference_path, pose_reference, payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=4, sides=("left",))
    clock = build_source_frame_clock(
        source_video_path=video, output_video_path=video,
        crop_start_seconds=0.0, output_fps=FPS)
    write_source_frame_clock(clock, output_path=source_frame_clock_path_for_video(video))
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    workspace = video.parent.parent
    retained = {
        "schemaVersion": 1,
        "status": "insufficient_evidence",
        "sourceVideoSha256": digest,
        "sourceApproval": False,
        "geometryApproval": False,
        "visibilityAdjudication": {"receiptPath": "immutable-review.json", "receiptSha256": "a" * 64},
        "reviews": [{"contactId": "retained-contact", "record": {"contactId": "retained-contact"}}],
    }
    monkeypatch.setattr(bso, "source_support_observation_needed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bso, "observe_body_support", lambda *_args, **_kwargs: {
        "status": "observed", "sourceVideoSha256": digest,
        "observation": {"leftKnee": "unknown", "rightKnee": "unknown"},
    })
    monkeypatch.setattr(bso, "validated_body_support_answer", lambda *_args, **_kwargs: {
        "leftKnee": "unknown", "rightKnee": "unknown"})
    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bso, "materialize_knee_support", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(support_geometry, "pre_reconstruction_source_support_readiness",
                        lambda *_args, **_kwargs: {"passed": True, "status": "ready",
                                                   "rejectionReasons": []})
    monkeypatch.setattr(source_support_stage, "_pose_reference_receipt_from_workspace",
                        lambda *_args: (Path("immutable-pose.json"), "b" * 64))
    contract_inputs = []

    def contract_status(_contract, _evidence, *, source_pose=None, selected_video_path=None):
        contract_inputs.append((source_pose, selected_video_path))
        return {"status": "insufficient_evidence",
                "failures": ["required_shoulder_left_support_unobserved"]}

    result = source_support_stage.observe_source_support_stage(
        workspace, video,
        contract={"bodySupportRequirements": {"required": [
            {"region": "shoulder", "side": "left", "surface": "bench"}], "prohibited": []}},
        caption_images=None, source_pose=payload,
        source_pose_reference=pose_reference,
        source_foot_support_evidence={"sourceVideoSha256": digest,
                                      "contacts": [], "bodySurfaceContactEvidence": retained},
        contract_status_fn=contract_status,
        persist_evidence=False,
    )

    assert result["evidence"]["bodySurfaceContactEvidence"] == retained
    assert "generic_body_surface_review_unavailable_preserved_existing" in result["steps"]
    assert contract_inputs
    assert all(source_pose == payload and path == video
               for source_pose, path in contract_inputs)
