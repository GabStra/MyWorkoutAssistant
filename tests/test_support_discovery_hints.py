"""Discovery hints request source inspection without becoming hard requirements."""
from __future__ import annotations

import hashlib
from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import body_support_observation as bso
from exercise_motion_pkg import source_support_stage
from exercise_motion_pkg import support_geometry


def _hint_contract(*hints: dict) -> dict:
    return {
        "contractScope": "definition_only",
        "bodySupportDiscoveryHints": {"required": list(hints), "prohibited": []},
    }


def _workspace_video(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "candidate"
    video = workspace / "input" / "selected_segment.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"exact selected source cut")
    return workspace, video, hashlib.sha256(video.read_bytes()).hexdigest()


def test_hints_request_knee_observation_and_generic_region_review(tmp_path, monkeypatch):
    workspace, video, digest = _workspace_video(tmp_path)
    contract = _hint_contract(
        {"region": "knee", "side": "both"},
        {"region": "shin", "side": "left", "surface": "any"},
    )
    observed_calls: list[dict] = []
    review_requests: list[dict] = []

    def observe_body_support(*_args, **kwargs):
        observed_calls.append(kwargs)
        return {"status": "unknown", "sourceVideoSha256": digest,
                "policyVersion": bso.POLICY_VERSION, "observation": {}}

    def body_surface_requests(requirements, *_args, **_kwargs):
        review_requests.append(requirements)
        return []

    monkeypatch.setattr(bso, "observe_body_support", observe_body_support)
    monkeypatch.setattr(bso, "_contact_timeline_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(source_support_stage, "_generic_body_surface_review_records",
                        body_surface_requests)
    monkeypatch.setattr(
        support_geometry, "pre_reconstruction_source_support_readiness",
        lambda *_args, **_kwargs: {"passed": True, "status": "ready", "rejectionReasons": []},
    )

    result = source_support_stage.observe_source_support_stage(
        workspace,
        video,
        contract=contract,
        caption_images=None,
        source_pose=None,
        source_pose_reference={"sourceVideoSha256": digest, "pose": {"frames": []}},
        source_foot_support_evidence={"sourceVideoSha256": digest, "contacts": []},
        contract_status_fn=bake.body_support_contract_evidence_status,
        persist_evidence=False,
    )

    assert observed_calls
    requested = set(observed_calls[0]["required_observation_fields"])
    assert {"leftKnee", "rightKnee"} <= requested
    assert observed_calls[0]["request_identity"] == (
        bso.body_support_discovery_request_identity(contract)
    )
    assert review_requests
    discovery = review_requests[0]["discovery"]
    assert {"region": "shin", "side": "left"} in discovery
    # A hint is inspection scope, never a hard requirement of the contract.
    assert result["contractStatus"] == {"status": "not_required", "failures": []}
    assert result["contradiction"] is False
    assert result["contractInsufficient"] is False


def test_negative_hint_observation_does_not_fail_hard_contract(tmp_path):
    _, video, digest = _workspace_video(tmp_path)
    contract = _hint_contract({"region": "knee", "side": "both"})
    evidence = {
        "sourceVideoSha256": digest,
        "bodySupportObservation": {
            "status": "observed",
            "source": "exact_source_visual_support_observation",
            "sourceVideoSha256": digest,
            "policyVersion": bso.POLICY_VERSION,
            "observation": {"leftKnee": "moving", "rightKnee": "moving"},
        },
    }

    status = bake.body_support_contract_evidence_status(
        contract, evidence, selected_video_path=video,
    )

    assert status == {"status": "not_required", "failures": []}


def test_preflight_routes_hint_only_contract_to_shared_source_stage(tmp_path, monkeypatch):
    workspace, video, digest = _workspace_video(tmp_path)
    contract = _hint_contract({"region": "knee", "side": "both"})
    calls: list[tuple] = []

    def source_stage(candidate_workspace, stage_contract, source_video, caption_images):
        calls.append((candidate_workspace, stage_contract, source_video, caption_images))
        return {"sourceVideoSha256": digest}, {"status": "passed", "failures": []}

    monkeypatch.setattr(bake, "_preflight_source_support_stage", source_stage)

    evidence, status = bake.preflight_candidate_body_support(
        workspace, contract, None, selected_source_video_path=video,
    )

    assert len(calls) == 1
    assert calls[0][1] is contract
    assert evidence["sourceVideoSha256"] == digest
    assert status == {"status": "passed", "failures": []}


def test_observation_request_identity_changes_with_hints():
    knee_contract = _hint_contract({"region": "knee", "side": "both"})
    shin_contract = _hint_contract({"region": "shin", "side": "left"})

    assert bso.body_support_discovery_request_identity({}) is None
    assert (bso.body_support_discovery_request_identity(knee_contract)
            == bso.body_support_discovery_request_identity(knee_contract))
    assert (bso.body_support_discovery_request_identity(knee_contract)
            != bso.body_support_discovery_request_identity(shin_contract))
    assert "leftKnee" not in bso.body_support_requirement_observation_fields(knee_contract)
    assert "leftKnee" in bso.body_support_discovery_observation_fields(knee_contract)
    assert bso.source_support_observation_needed(None, {"contacts": []}, knee_contract)


def test_discovery_hints_use_the_same_strict_shape_as_the_producer():
    invalid = _hint_contract({"region": "knee", "side": "typo"})
    assert bso.body_support_discovery_hint_items(invalid) == []
    assert bso.body_support_discovery_hint_items({
        "bodySupportDiscoveryHints": {"contacts": [{"region": "knee", "side": "both"}]},
    }) == []


def test_inferred_surface_does_not_restrict_source_discovery():
    contract = _hint_contract({"region": "knee", "side": "both", "surface": "floor"})
    assert bso.body_support_discovery_hint_items(contract) == [{"region": "knee", "side": "both"}]
    assert {"leftKneeContactSurface", "rightKneeContactSurface"} <= (
        bso.body_support_discovery_observation_fields(contract))
    assert contract["bodySupportDiscoveryHints"]["required"][0]["surface"] == "floor"
