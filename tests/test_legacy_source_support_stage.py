"""Legacy bake must use the same exact-cut support authority as the staged wave."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import body_support_observation as support_observation
from exercise_motion_pkg import foot_contact_observation
from exercise_motion_pkg import source_support_stage
from exercise_motion_pkg import wave_pipeline
from exercise_motion_pkg.source_support_tracking import FOOT_MATERIAL_POLICY_VERSION


def _workspace_with_video(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "candidate"
    source = workspace / "input" / "selected_segment.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"exact selected source cut")
    return workspace, source, hashlib.sha256(source.read_bytes()).hexdigest()


def _continuous_ground_contract() -> dict:
    return {
        "groundContactMode": "continuous",
        "bodySupportRequirements": {"required": [], "prohibited": []},
    }


def test_required_ground_observation_cannot_pass_without_source_video(tmp_path):
    _, status = bake.preflight_candidate_body_support(
        tmp_path, _continuous_ground_contract(), None)
    assert status['status'] == 'insufficient_evidence'
    assert status['failures'] == ['source_video_unavailable']


def _moving_observation(digest: str) -> dict:
    return {
        "status": "observed",
        "source": "exact_source_visual_support_observation",
        "sourceClock": "video_frame_zero_seconds",
        "policyVersion": support_observation.POLICY_VERSION,
        "sourceVideoSha256": digest,
        "observation": {
            "leftFoot": "moving",
            "rightFoot": "moving",
            "leftFootSurface": "ground",
            "rightFootSurface": "ground",
            "leftFootContactContinuity": "intermittent",
            "rightFootContactContinuity": "intermittent",
            "leftKnee": "moving",
            "rightKnee": "moving",
        },
    }


def test_legacy_preflight_calls_the_shared_source_support_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source, digest = _workspace_with_video(tmp_path)
    calls: list[tuple[tuple, dict]] = []

    def stage_spy(*args: object, **kwargs: object) -> dict:
        calls.append((args, kwargs))
        return {
            "evidence": {"sourceVideoSha256": digest, "contacts": []},
            "readiness": {"passed": True, "status": "ready", "rejectionReasons": []},
            "contractStatus": {"status": "not_required", "failures": []},
            "refreshed": False,
            "persisted": False,
            "steps": [],
            "contradiction": False,
            "contractInsufficient": False,
            "timelineError": None,
        }

    # The staged wave and legacy preflight share one owner, not a copy.
    assert wave_pipeline.observe_source_support_stage is source_support_stage.observe_source_support_stage
    assert wave_pipeline._persist_exact_source_support_evidence is (
        source_support_stage.persist_exact_source_support_evidence
    )
    monkeypatch.setattr(
        bake, "pre_reconstruction_source_foot_support_evidence",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        bake, "load_verified_source_pose_reference",
        lambda *_args, **_kwargs: {"frames": [], "sourceVideoSha256": digest},
    )
    monkeypatch.setattr(
        source_support_stage, "observe_source_support_stage", stage_spy,
    )

    evidence, status = bake.preflight_candidate_body_support(
        workspace, _continuous_ground_contract(), None,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (workspace, source)
    assert kwargs["force_observation"] is True
    assert kwargs["contract_status_fn"] is bake.body_support_contract_evidence_status
    assert status["status"] == "passed"
    assert evidence["sourceVideoSha256"] == digest


def test_legacy_continuous_ground_observes_before_reconstruction_and_keeps_missing_support_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source, digest = _workspace_with_video(tmp_path)
    observed: dict[str, int] = {"coarse": 0, "sole_review": 0, "timeline": 0}
    evidence = {
        "sourceVideoSha256": digest,
        "contacts": [],
        "footPatchEvidence": {
            "available": True,
            "policyVersion": foot_contact_observation.POLICY_VERSION,
            "materialStationarityPolicyVersion": FOOT_MATERIAL_POLICY_VERSION,
            "sourceVideoSha256": digest,
            "sourceFrameCount": 3,
            "sourceTimesSec": [0.0, 0.1, 0.2],
            "sourceTimeBasis": "video_frame_zero_seconds",
            "feet": {
                "left": {"states": ["unknown", "unknown", "unknown"]},
                "right": {"states": ["unknown", "unknown", "unknown"]},
            },
        },
    }
    pose = {
        "coordinateSpace": "normalized_image_xy",
        "sourceVideoSha256": digest,
        "frames": [
            {"sourceTimeSec": index / 30.0, "joints": {}}
            for index in range(3)
        ],
    }

    def observe_body_support(*_args: object, **_kwargs: object) -> dict:
        observed["coarse"] += 1
        return _moving_observation(digest)

    def observe_sole_review(*_args: object, **_kwargs: object) -> None:
        observed["sole_review"] += 1
        return None

    monkeypatch.setattr(
        bake, "pre_reconstruction_source_foot_support_evidence",
        lambda *_args, **_kwargs: dict(evidence),
    )
    monkeypatch.setattr(
        bake, "load_verified_source_pose_reference",
        lambda *_args, **_kwargs: pose,
    )
    monkeypatch.setattr(
        support_observation, "observe_body_support", observe_body_support,
    )
    monkeypatch.setattr(
        support_observation, "source_support_observation_needed",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        support_observation, "_contact_timeline_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        support_observation, "observe_foot_contact_timeline",
        lambda *_args, **_kwargs: pytest.fail(
            "no timeline candidate should trigger vision for this fixture"
        ),
    )
    monkeypatch.setattr(
        support_observation, "observe_stationary_sole_intervals",
        observe_sole_review,
    )
    monkeypatch.setattr(
        foot_contact_observation, "observe_foot_landmarks",
        lambda *_args, **_kwargs: {"available": False},
    )

    observed_evidence, status = bake.preflight_candidate_body_support(
        workspace, _continuous_ground_contract(), None,
    )

    assert observed["coarse"] == 1
    assert observed["sole_review"] == 1
    assert observed["timeline"] == 0
    assert status["status"] == "insufficient_evidence"
    assert "stationary_contact_evidence_unavailable" in status["failures"]
    assert observed_evidence["bodySupportObservation"]["observation"]["leftFoot"] == "moving"


def test_legacy_contradictory_support_readiness_stays_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source, digest = _workspace_with_video(tmp_path)
    evidence = {"sourceVideoSha256": digest, "contacts": []}
    monkeypatch.setattr(
        bake, "pre_reconstruction_source_foot_support_evidence",
        lambda *_args, **_kwargs: dict(evidence),
    )
    monkeypatch.setattr(
        bake, "load_verified_source_pose_reference", lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        support_observation, "observe_body_support",
        lambda *_args, **_kwargs: _moving_observation(digest),
    )
    monkeypatch.setattr(
        support_observation, "_contact_timeline_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        support_observation, "observe_stationary_sole_intervals",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        source_support_stage, "observe_source_support_stage",
        lambda *_args, **_kwargs: {
            "evidence": dict(evidence),
            "readiness": {
                "passed": False,
                "status": "incomplete",
                "rejectionReasons": ["source_support_contact_evidence_conflict"],
            },
            "contractStatus": {"status": "not_required", "failures": []},
            "refreshed": True,
            "persisted": False,
            "steps": [],
            "contradiction": False,
            "contractInsufficient": False,
            "timelineError": None,
        },
    )

    _, status = bake.preflight_candidate_body_support(
        workspace, _continuous_ground_contract(), None,
    )

    assert status["status"] == "insufficient_evidence"
    assert status["failures"] == ["source_support_contact_evidence_conflict"]


def test_legacy_observer_tool_failure_routes_to_source_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _source, digest = _workspace_with_video(tmp_path)
    monkeypatch.setattr(
        bake, "pre_reconstruction_source_foot_support_evidence",
        lambda *_args, **_kwargs: {"sourceVideoSha256": digest, "contacts": []},
    )
    monkeypatch.setattr(
        bake, "load_verified_source_pose_reference", lambda *_args, **_kwargs: None,
    )

    def failing_stage(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("observer transport failed")

    monkeypatch.setattr(
        source_support_stage, "observe_source_support_stage", failing_stage,
    )

    _, status = bake.preflight_candidate_body_support(
        workspace, _continuous_ground_contract(), None,
    )

    assert status["status"] == "insufficient_evidence"
    assert status["failures"] == ["source_support_observation_error"]
    assert status["observerErrorType"] == "RuntimeError"


def test_unresolved_continuous_ground_rejects_before_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="wood",
        exercise_name="Dumbbell Woodchopper",
        exercise_slug="wood",
        candidate={"videoId": "wood-source", "url": "https://example.invalid/wood"},
    )
    contract = _continuous_ground_contract()
    monkeypatch.setattr(
        bake, "evaluate_source_candidate_gate",
        lambda *_args, **_kwargs: {"passed": True, "reasons": []},
    )
    preflight_calls: list[None] = []

    def unresolved_preflight(*_args: object, **_kwargs: object) -> tuple[dict, dict]:
        preflight_calls.append(None)
        return {"sourceVideoSha256": "digest", "contacts": []}, {
            "status": "insufficient_evidence",
            "failures": ["stationary_contact_evidence_unavailable"],
            "sourceContactReadiness": {
                "passed": False,
                "status": "incomplete",
                "rejectionReasons": ["stationary_contact_evidence_unavailable"],
            },
        }

    def fail_generate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise AssertionError(
            "unresolved continuous-ground support must stop before reconstruction"
        )

    monkeypatch.setattr(
        bake, "preflight_candidate_body_support", unresolved_preflight,
    )
    monkeypatch.setattr(bake, "generate_candidate_motion", fail_generate)

    result = bake.process_ranked_candidate(
        candidate,
        request=bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "build",
            body_model_root=None,
            classify_support_dominance=False,
        ),
        preview_baker=lambda *_args, **_kwargs: [],
        review_items=[],
        review_item_entries=[],
        support_dominance_classifier=None,
        exercise_motion_contract_resolver=lambda _candidate: contract,
    )

    assert preflight_calls == [None]
    assert result["status"] == "rejected_source_support_contract"
    assert result["failureOwner"] == "source_evidence"
    assert result["sourceSupportContractEvidence"]["failures"] == [
        "stationary_contact_evidence_unavailable"
    ]
