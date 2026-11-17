"""Stage-level freshness ordering for the persisted source foot patch."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from exercise_motion_pkg import body_support_observation
from exercise_motion_pkg import foot_contact_observation
from exercise_motion_pkg import source_support_stage
from exercise_motion_pkg import support_geometry
from exercise_motion_pkg.source_support_tracking import FOOT_MATERIAL_POLICY_VERSION


def _workspace_with_video(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "candidate"
    source = workspace / "input" / "selected_segment.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"exact selected source cut")
    return workspace, source, hashlib.sha256(source.read_bytes()).hexdigest()


def _patch(digest: str, *, policy_version: int) -> dict:
    return {
        "available": True,
        "source": "mediapipe_full_heel_forefoot",
        "policyVersion": policy_version,
        "materialStationarityPolicyVersion": (
            FOOT_MATERIAL_POLICY_VERSION
            if policy_version == foot_contact_observation.POLICY_VERSION
            else FOOT_MATERIAL_POLICY_VERSION - 1
        ),
        "sourceVideoSha256": digest,
        "feet": {
            "left": {"states": ["full_sole"]},
            "right": {"states": ["moving"]},
        },
    }


def _run_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    patch_policy_version: int,
    include_patch: bool = True,
) -> tuple[dict, dict[str, int]]:
    workspace, source, digest = _workspace_with_video(tmp_path)
    calls = {"landmarks": 0, "reclassified": 0, "readiness": 0}
    evidence = {
        "sourceVideoSha256": digest,
        "contacts": [],
    }
    if include_patch:
        evidence["footPatchEvidence"] = _patch(
            digest, policy_version=patch_policy_version,
        )
    pose = {
        "coordinateSpace": "normalized_image_xy",
        "sourceVideoSha256": digest,
        "frames": [{"sourceTimeSec": 0.0, "joints": {}}],
    }

    def readiness(*_args: object, **_kwargs: object) -> dict:
        # Coarse readiness deliberately passes: the stage must not rely on it
        # to detect stale patch policy/material versions.
        calls["readiness"] += 1
        return {"passed": True, "status": "ready", "rejectionReasons": []}

    def landmarks(*_args: object, **_kwargs: object) -> dict:
        calls["landmarks"] += 1
        return {"available": True}

    def add_contacts(
        current: dict, _landmarks: dict, _pose: dict, *, source_video_path: Path,
    ) -> dict:
        assert source_video_path == source
        calls["reclassified"] += 1
        refreshed = dict(current)
        refreshed["footPatchEvidence"] = _patch(
            digest, policy_version=foot_contact_observation.POLICY_VERSION,
        )
        return refreshed

    monkeypatch.setattr(
        body_support_observation, "source_support_observation_needed",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        body_support_observation, "materialize_knee_support",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        body_support_observation, "_contact_timeline_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        support_geometry, "pre_reconstruction_source_support_readiness", readiness,
    )
    monkeypatch.setattr(
        foot_contact_observation, "observe_foot_landmarks", landmarks,
    )
    monkeypatch.setattr(
        foot_contact_observation, "add_observed_foot_contacts", add_contacts,
    )

    result = source_support_stage.observe_source_support_stage(
        workspace,
        source,
        contract={},
        caption_images=None,
        source_pose=pose,
        source_pose_reference=None,
        source_foot_support_evidence=evidence,
        contract_status_fn=lambda *_args, **_kwargs: {
            "status": "not_required", "failures": [],
        },
        persist_evidence=False,
    )
    expected_readiness_calls = 2 if (
        include_patch
        and patch_policy_version != foot_contact_observation.POLICY_VERSION
    ) else 1
    assert calls["readiness"] == expected_readiness_calls
    return result, calls


def test_stale_foot_patch_is_reclassified_when_coarse_readiness_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run_stage(
        tmp_path, monkeypatch,
        patch_policy_version=foot_contact_observation.POLICY_VERSION - 3,
    )

    assert calls["landmarks"] == 1
    assert calls["reclassified"] == 1
    assert "foot_patch_reclassification" in result["steps"]
    assert result["refreshed"] is True
    patch = result["evidence"]["footPatchEvidence"]
    assert patch["policyVersion"] == foot_contact_observation.POLICY_VERSION
    assert patch["materialStationarityPolicyVersion"] == FOOT_MATERIAL_POLICY_VERSION
    # Source binding remains the selected exact cut.
    assert patch["sourceVideoSha256"] == result["evidence"]["sourceVideoSha256"]


def test_current_foot_patch_avoids_needless_landmark_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run_stage(
        tmp_path, monkeypatch,
        patch_policy_version=foot_contact_observation.POLICY_VERSION,
    )

    assert calls["landmarks"] == 0
    assert calls["reclassified"] == 0
    assert "foot_patch_reclassification" not in result["steps"]
    assert result["refreshed"] is False


def test_ready_without_foot_patch_avoids_landmark_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run_stage(
        tmp_path, monkeypatch,
        patch_policy_version=foot_contact_observation.POLICY_VERSION,
        include_patch=False,
    )

    assert calls["landmarks"] == 0
    assert calls["reclassified"] == 0
    assert "foot_patch_reclassification" not in result["steps"]
    assert result["refreshed"] is False
