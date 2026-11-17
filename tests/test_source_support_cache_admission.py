from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import body_support_observation as bso
from exercise_motion_pkg import source_support_stage
from exercise_motion_pkg import support_geometry


def _video_and_contract(tmp_path: Path):
    video = tmp_path / "candidate" / "input" / "selected_segment.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"exact selected support-cache source")
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    contract = {
        "groundContactMode": "continuous",
        "bodySupportRequirements": {"required": [], "prohibited": []},
        "bodySupportDiscoveryHints": {
            "required": [{
                "region": "foot", "side": "both", "surface": "ground",
                "contactMode": "stationary",
            }],
            "prohibited": [],
        },
    }
    return video, digest, contract


def _reviewed_coarse(digest: str, contract: dict, *, review_identity: dict):
    return {
        "status": "observed",
        "source": "exact_source_visual_support_observation",
        "sourceVideoSha256": digest,
        "policyVersion": bso.POLICY_VERSION,
        "sourceClock": "video_frame_zero_seconds",
        "reviewIdentity": review_identity,
        "requestIdentity": bso.body_support_discovery_request_identity(contract),
        "observation": {
            "leftFoot": "stationary_full_sole",
            "leftFootSurface": "ground",
            "rightFoot": "stationary_full_sole",
            "rightFootSurface": "ground",
            "leftKnee": "moving",
            "rightKnee": "moving",
        },
    }


def _ready(*_args, **_kwargs):
    return {"status": "ready", "passed": True, "rejectionReasons": []}


def _passed_contract(*_args, **_kwargs):
    return {"status": "passed", "failures": []}


def test_changed_provider_reuses_bound_coarse_and_sends_only_current_timeline(
    tmp_path, monkeypatch,
):
    video, digest, contract = _video_and_contract(tmp_path)
    original_identity = {"structuredResponsePromptPolicyVersion": 1}
    coarse = _reviewed_coarse(digest, contract, review_identity=original_identity)
    evidence = {"sourceVideoSha256": digest, "bodySupportObservation": coarse}
    pose = {"sourceVideoSha256": digest, "frames": []}
    candidates = [
        {"sampleId": f"contact-left-pose-{index}", "side": "left"}
        for index in (0, 3, 5, 6, 9, 17)
    ] + [
        {"sampleId": f"contact-right-pose-{index}", "side": "right"}
        for index in (0, 9, 17)
    ]
    provider_identity = {"model": "current-provider"}
    coarse_callback_calls = []
    timeline_callback_calls = []
    timeline_batches = []

    def current_provider(**kwargs):
        prompt = kwargs.get("prompt", "")
        if "current foot timeline batch:" in prompt:
            timeline_callback_calls.append(kwargs)
        else:
            coarse_callback_calls.append(kwargs)
        return "{}"

    current_provider.settings = provider_identity

    original_observer = bso.observe_foot_contact_timeline

    def timeline_only(video_path, source_pose_reference, support_evidence,
                      caption_images, cache_dir):
        assert caption_images is current_provider
        sample_ids = [row["sampleId"] for row in candidates]
        for offset in range(0, len(sample_ids), 6):
            batch = sample_ids[offset:offset + 6]
            timeline_batches.append(batch)
            caption_images(
                frame_paths=[tmp_path / f"timeline-atlas-{len(timeline_batches)}.png"],
                prompt="current foot timeline batch: " + ",".join(batch),
                max_tokens=600,
            )
        return {
            "schemaVersion": 1,
            "policyVersion": bso.CONTACT_TIMELINE_POLICY_VERSION,
            "source": "exact_source_visual_contact_timeline",
            "sourceVideoSha256": digest,
            "sourceClock": "video_frame_zero_seconds",
            "status": "observed",
            "reviewIdentity": provider_identity,
            "requestSha256": "current-timeline-request",
            "samples": [],
        }

    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_a, **_k: candidates)
    monkeypatch.setattr(bso, "observe_foot_contact_timeline", timeline_only)
    monkeypatch.setattr(source_support_stage, "reclassify_source_foot_contacts_from_timeline",
                        lambda evidence, *_a, **_k: evidence)
    monkeypatch.setattr(support_geometry, "pre_reconstruction_source_support_readiness", _ready)
    monkeypatch.setattr(bso, "materialize_knee_support", lambda *_a, **_k: None)

    result = source_support_stage.observe_source_support_stage(
        video.parent.parent,
        video,
        contract=contract,
        caption_images=current_provider,
        source_pose=pose,
        source_pose_reference=None,
        source_foot_support_evidence=evidence,
        contract_status_fn=_passed_contract,
        persist_evidence=False,
        write_repair_marker=False,
    )

    assert coarse_callback_calls == []
    assert len(timeline_batches) == 2
    assert [len(batch) for batch in timeline_batches] == [6, 3]
    assert len(timeline_callback_calls) == 2
    observed = result["evidence"]["bodySupportObservation"]
    assert observed["reviewIdentity"] == original_identity
    assert observed["contactTimeline"]["reviewIdentity"] == provider_identity
    assert "coarse_support_cache_reused" in result["steps"]
    assert result["timelineStatus"] == "observed"
    assert result["readiness"]["passed"] is True


def test_invalid_coarse_receipt_still_uses_current_provider(tmp_path, monkeypatch):
    video, digest, contract = _video_and_contract(tmp_path)
    invalid = _reviewed_coarse(
        "different-source-sha", contract,
        review_identity={"structuredResponsePromptPolicyVersion": 1},
    )
    evidence = {"sourceVideoSha256": digest, "bodySupportObservation": invalid}
    coarse_calls = []
    provider_calls = []

    def current_provider(**kwargs):
        provider_calls.append(kwargs)
        return "coarse response"

    current_provider.settings = {"model": "current-provider"}

    def observer(video_path, caption_images, cache_dir, **kwargs):
        coarse_calls.append(caption_images)
        if caption_images is None:
            return {"status": "unknown", "reason": "support_observer_unavailable"}
        caption_images(frame_paths=[], prompt="fresh coarse support", max_tokens=1000)
        return _reviewed_coarse(
            digest, contract, review_identity={"model": "current-provider"},
        )

    monkeypatch.setattr(bso, "observe_body_support", observer)
    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr(support_geometry, "pre_reconstruction_source_support_readiness", _ready)
    monkeypatch.setattr(bso, "materialize_knee_support", lambda *_a, **_k: None)

    result = source_support_stage.observe_source_support_stage(
        video.parent.parent,
        video,
        contract=contract,
        caption_images=current_provider,
        source_pose=None,
        source_pose_reference=None,
        source_foot_support_evidence=evidence,
        contract_status_fn=_passed_contract,
        persist_evidence=False,
        write_repair_marker=False,
    )

    assert coarse_calls == [None, current_provider]
    assert len(provider_calls) == 1
    assert result["evidence"]["bodySupportObservation"]["sourceVideoSha256"] == digest


def test_native_reviewer_identity_uses_distinct_cache_namespace():
    class NativeReviewer:
        source_review_identity = {
            "provider": "native_codex_agent",
            "requestedModel": "gpt-6-luna",
            "requestedEffort": "low",
            "actualModelTelemetry": "unavailable",
            "reviewProtocolVersion": 1,
        }

    def llama_reviewer():
        pass

    llama_reviewer.settings = SimpleNamespace(llama_cpp_base_url="http://127.0.0.1:8090")
    native = bso._review_model_identity(NativeReviewer())
    llama = bso._review_model_identity(llama_reviewer)

    assert native == {"sourceReviewer": NativeReviewer.source_review_identity}
    assert native != llama


def test_malformed_native_reviewer_identity_fails_closed():
    class NativeReviewer:
        source_review_identity = {
            "provider": "native_codex_agent",
            "reviewProtocolVersion": True,
        }

    with pytest.raises(ValueError, match="positive reviewProtocolVersion"):
        bso._review_model_identity(NativeReviewer())
