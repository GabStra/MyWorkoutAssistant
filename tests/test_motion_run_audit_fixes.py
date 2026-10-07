import json
import hashlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import source_review_preflight as preflight
from exercise_motion_pkg import wave_pipeline as wave


def _artifact_test_payload(*, start_frame: int, end_frame: int, frame_count: int, loop_enabled: bool):
    fps = 30.0
    source_indices = [
        round(start_frame + index * (end_frame - start_frame) / (frame_count - 1))
        for index in range(frame_count)
    ]
    frames = [
        {
            "timeSec": index / fps,
            "sourceTimeSec": source_index / fps,
            "sourceFrameIndex": source_index,
            "joints": {"pelvis": [0.0, 0.0, 0.0]},
        }
        for index, source_index in enumerate(source_indices)
    ]
    return {
        "schemaVersion": 1,
        "kind": "wearPreviewSkeleton",
        "source": {"frameCount": max(end_frame + 1, frame_count)},
        "fps": fps,
        "frameCount": frame_count,
        "jointNames": ["pelvis"],
        "rootJoint": "pelvis",
        "selectedPreviewSettings": {},
        "bakedPreviewConfiguration": {},
        "wearDisplay": {},
        "renderFloorY": 0.0,
        "groundContactMode": "observed",
        "elevatedSupportSurfaces": [],
        "bounds": {},
        "loop": {
            "enabled": loop_enabled,
            "sourceStartFrame": start_frame,
            "sourceEndFrame": end_frame,
            "sourceStartTimeSec": start_frame / fps,
            "sourceEndTimeSec": end_frame / fps,
            "durationSec": (end_frame - start_frame) / fps,
        },
        "frames": frames,
    }


def _legacy_bounded_selection_evidence(interval: dict[str, object]) -> dict[str, object]:
    """Model a persisted schema-v1 selection written before parent binding."""
    interval_keys = (
        "type",
        "startFrame",
        "endFrame",
        "startTimeSec",
        "endTimeSec",
        "durationSec",
    )
    normalized_interval = {key: interval[key] for key in interval_keys if key in interval}
    selection_id = hashlib.sha256(
        json.dumps(
            {"interval": normalized_interval},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {"selectionId": selection_id, "interval": normalized_interval}


def test_manual_review_fallback_is_exportable_from_a_staged_wave():
    assert wave.wave_manifest_is_exportable({"selected": {"selectedWearSkeletonPath": "x"}})
    fallback_manifest = {
        "selected": None,
        "selectionStatus": "needs_manual_review",
        "manualReviewFallback": {"selectedWearSkeletonPath": "x"},
    }
    assert wave.wave_manifest_is_exportable(fallback_manifest)
    assert wave.artifact_disposition(fallback_manifest) == "manual_review"
    assert wave.final_validation_outcome_status(fallback_manifest) == "needs_manual_review"
    assert not wave.wave_manifest_is_exportable({
        "selected": None,
        "selectionStatus": "needs_manual_review",
    })
    assert not wave.wave_manifest_is_exportable({
        "selected": None,
        "selectionStatus": "failed",
        "manualReviewFallback": {"selectedWearSkeletonPath": "x"},
    })
    assert wave.artifact_disposition({
        "selected": None,
        "candidateResults": [{"status": "needs_source_review"}],
    }) == "retryable"
    assert wave.wave_retry_disposition({"status": "completed"}) == "export_selected"
    assert wave.wave_retry_disposition({
        "status": "completed",
        "artifactLifecycle": {"state": "manual_review"},
    }) == "export_manual_review"


def test_artifact_lifecycle_records_only_valid_terminal_transitions():
    lifecycle = wave.initial_artifact_lifecycle()
    lifecycle = wave.transition_artifact_lifecycle(lifecycle, "manual_review")
    assert lifecycle["state"] == "manual_review"
    assert lifecycle["terminal"] is True
    assert [entry["state"] for entry in lifecycle["history"]] == [
        "awaiting_final_validation", "manual_review",
    ]
    with pytest.raises(ValueError, match="Invalid artifact lifecycle transition"):
        wave.transition_artifact_lifecycle(lifecycle, "accepted")

    retry = wave.transition_artifact_lifecycle(
        wave.initial_artifact_lifecycle(), "retryable",
    )
    accepted_after_retry = wave.transition_artifact_lifecycle(retry, "accepted")
    assert accepted_after_retry["terminal"] is True
    assert [entry["state"] for entry in accepted_after_retry["history"]] == [
        "awaiting_final_validation", "retryable", "accepted",
    ]


def test_cyclic_contract_rejects_full_clip_before_final_render_validation(monkeypatch, tmp_path):
    contract = {
        "movementType": "repetition",
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
    }
    item = bake.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name="Curl",
        candidate_title="source",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "full-clip.json",
        review_video_path=tmp_path / "full-clip.webm",
        duration_sec=4.0,
        loop_start_seconds=0.0,
        loop_end_seconds=4.0,
        candidate={"exerciseMotionContract": contract},
        artifact_class=bake.FULL_CLIP_BAKE,
        export_payload={"loop": {"enabled": False}},
    )
    ranking = bake.LoopRanking(score=1.0, reasons=[], payload={"exerciseMotionContract": contract})
    monkeypatch.setattr(
        bake,
        "materialized_metrics_with_gpu_handoff",
        lambda *args, **kwargs: pytest.fail("Artifact-class mismatch must short-circuit expensive validation"),
    )
    class_gate_calls = []
    original_class_gate = bake.movement_artifact_class_gate

    def capture_class_gate(*args, **kwargs):
        class_gate_calls.append(kwargs)
        return original_class_gate(*args, **kwargs)

    monkeypatch.setattr(bake, "movement_artifact_class_gate", capture_class_gate)

    rejected_item, rejected_ranking = bake.apply_materialized_output_acceptance_gate(
        (item, ranking),
        request=None,
    )

    assert rejected_item is item
    assert "required_artifact_class_cyclic_rebake" in rejected_ranking.payload[
        "materializedHardRejectionReasons"
    ]
    assert rejected_ranking.payload["materializedOutputAcceptanceGate"]["skippedReasons"] == [
        "final_validation_skipped_for_artifact_class_mismatch"
    ]
    assert rejected_ranking.payload["artifactClassGate"]["acceptedArtifactClasses"] == [
        bake.CYCLIC_REBAKE
    ]
    assert rejected_ranking.payload["acceptanceDecision"]["status"] == "invalid"
    assert class_gate_calls[0]["require_terminal"] is True


def test_artifact_state_records_full_clip_cycle_selection_and_rebake():
    from exercise_motion_pkg.artifact_state import cycle_selection_evidence

    payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    payload["sourceCyclePreflight"] = {"passed": True}
    payload["observedCycleProposals"] = [{"startFrame": 5, "stopFrameExclusive": 46}]
    full_clip_payload = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    full_clip_payload["source"]["frameCount"] = 60
    lineage = cycle_selection_evidence(
        full_clip_payload,
        {
            "type": "detected_cycle",
            "startFrame": 5,
            "endFrame": 45,
            "startTimeSec": 5 / 30,
            "endTimeSec": 45 / 30,
            "durationSec": 40 / 30,
        },
    )
    contract = {"completionMode": "return_to_start", "requiresReturnToStart": True}

    state = bake.artifact_state_for_baked_payload(
        payload,
        contract=contract,
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=lineage,
    )

    assert state["artifactClass"] == bake.CYCLIC_REBAKE
    assert state["terminal"] is True
    assert state["history"] == [
        bake.FULL_CLIP_BAKE,
        bake.CYCLE_SELECTION,
        bake.CYCLIC_REBAKE,
    ]
    assert state["lineageComplete"] is True
    assert state["selectionEvidence"]["cyclicRebake"]["contentSha256"]

    corrupted_state = json.loads(json.dumps(state))
    corrupted_state["selectionEvidence"]["cycleSelection"]["selectionId"] = "a" * 64
    with pytest.raises(ValueError, match="lineage flag does not match"):
        bake.validate_artifact_state(corrupted_state)
    changed_payload = json.loads(json.dumps(payload))
    changed_payload["frames"][0]["joints"]["pelvis"][0] = 0.25
    with pytest.raises(ValueError, match="does not match its movement payload"):
        bake.validate_artifact_state(state, movement_payload=changed_payload)
    changed_renderer = json.loads(json.dumps(payload))
    changed_renderer["selectedPreviewSettings"]["cameraYawDegrees"] = 35.0
    with pytest.raises(ValueError, match="does not match its movement payload"):
        bake.validate_artifact_state(state, movement_payload=changed_renderer)
    changed_endpoint = json.loads(json.dumps(payload))
    changed_endpoint["frames"][0]["sourceFrameIndex"] = 6
    changed_endpoint_state = json.loads(json.dumps(state))
    from exercise_motion_pkg.artifact_state import baked_payload_identity
    changed_endpoint_state["selectionEvidence"]["cyclicRebake"] = baked_payload_identity(
        changed_endpoint
    )
    with pytest.raises(ValueError, match="interval does not match its selected-cycle evidence"):
        bake.validate_artifact_state(
            changed_endpoint_state,
            movement_payload=changed_endpoint,
        )

    from exercise_motion_pkg.artifact_state import validate_artifact_history

    with pytest.raises(ValueError, match="Invalid movement artifact transition"):
        validate_artifact_history([bake.FULL_CLIP_BAKE, bake.CYCLIC_REBAKE])


def test_retained_cycle_fit_lineage_uses_materialized_frames_not_preflight_bounds(
    monkeypatch,
):
    from exercise_motion_pkg.artifact_state import cycle_selection_evidence
    from exercise_motion_pkg.controlled_motion import (
        CONTROLLED_MOTION_STRATEGY,
        controlled_motion_fit_source_evidence_digest,
    )
    from exercise_motion_pkg.sequence_stabilization import pose_digest

    contract = {
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "exerciseName": "Barbell Step-Up",
    }
    full_clip = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    parent_state = bake.artifact_state_for_baked_payload(
        full_clip,
        contract=contract,
        selection_class=bake.FULL_CLIP_BAKE,
    )

    retained = json.loads(json.dumps(full_clip))
    retained["loop"]["enabled"] = True
    retained["loop"]["transition"] = "requires_cycle_repair"
    retained["sourceCyclePreflight"] = [{
        "passed": True,
        "selection": {"startFrame": 17, "stopFrameExclusive": 50},
    }]
    retained["artifactState"] = parent_state
    fit_source_digest = controlled_motion_fit_source_evidence_digest(retained)
    retained["controlledMotionFit"] = {
        "applied": True,
        "strategy": CONTROLLED_MOTION_STRATEGY,
        "fitSourceEvidenceDigest": fit_source_digest,
        "outputPoseDigest": pose_digest(retained),
    }

    selection = bake.selection_evidence_for_materialized_interval(
        parent_selection_evidence=parent_state["selectionEvidence"],
        movement_payload=retained,
        selection_class=bake.FULL_CLIP_BAKE,
        source_parent_payload=full_clip,
    )
    assert selection["cycleSelection"]["interval"]["startFrame"] == 0
    assert selection["cycleSelection"]["interval"]["endFrame"] == 59
    assert bake.attach_materialized_source_interval(
        retained,
        selection,
        selection_class=bake.CYCLE_SELECTION,
    )
    retained["artifactState"] = bake.artifact_state_for_baked_payload(
        retained,
        contract=contract,
        selection_class=bake.FULL_CLIP_BAKE,
        selection_evidence=selection,
    )

    assert retained["artifactState"]["artifactClass"] == bake.CYCLIC_REBAKE
    assert retained["artifactState"]["lineageComplete"] is True
    assert retained["artifactState"]["selectionEvidence"]["cycleSelection"][
        "interval"
    ]["startFrame"] == 0
    assert retained["artifactState"]["selectionEvidence"]["cycleSelection"][
        "interval"
    ]["endFrame"] == 59
    assert retained["artifactState"]["selectionEvidence"]["sourceCyclePreflight"][0][
        "selection"
    ] == {"startFrame": 17, "stopFrameExclusive": 50}
    assert retained["controlledMotionFit"]["fitSourceEvidenceDigest"] == (
        controlled_motion_fit_source_evidence_digest(retained)
    )

    monkeypatch.setattr(bake, "compute_kinematic_plausibility_metrics_from_payload", lambda _: {
        "artifactReasons": [], "processingIncompleteReasons": [],
    })
    monkeypatch.setattr(bake, "materialized_source_pose_fidelity_metrics", lambda **_: {
        "rejectionReasons": [],
    })
    monkeypatch.setattr(bake, "exercise_requires_loop_continuity", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bake, "compute_loop_bridge_quality_metrics_from_payload", lambda _: {
        "severeLoopMismatch": True,
    })
    from exercise_motion_pkg import support_geometry
    monkeypatch.setattr(support_geometry, "declare_support_requirements", lambda *_args: None)
    monkeypatch.setattr(support_geometry, "validate_support_geometry", lambda *_args: {
        "passed": True, "rejectionReasons": [],
    })
    gate = bake.pre_render_deterministic_gate(
        retained,
        None,
        exercise_motion_contract=contract,
    )
    assert gate["passed"] is False
    assert "materialized_loop_bridge_pose_mismatch" in gate["rejectionReasons"]


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_source_frame_index",
        "out_of_interval_source_frame_index",
        "reordered_source_frame_index",
        "missing_source_time",
        "invalid_source_time",
        "out_of_interval_source_time",
        "reordered_source_time",
    ],
)
def test_cycle_lineage_rejects_invalid_interior_source_provenance(corruption):
    from exercise_motion_pkg.artifact_state import (
        baked_payload_identity,
        cycle_selection_evidence,
    )

    interval = {
        "type": "detected_cycle",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    full_clip = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    contract = {"completionMode": "return_to_start", "requiresReturnToStart": True}
    selection_evidence = cycle_selection_evidence(full_clip, interval)
    payload["artifactState"] = bake.artifact_state_for_baked_payload(
        payload,
        contract=contract,
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=selection_evidence,
    )
    assert payload["artifactState"]["terminal"] is True

    corrupted_payload = json.loads(json.dumps(payload))
    middle_index = len(corrupted_payload["frames"]) // 2
    frame = corrupted_payload["frames"][middle_index]
    previous_frame = corrupted_payload["frames"][middle_index - 1]
    if corruption == "missing_source_frame_index":
        frame.pop("sourceFrameIndex")
    elif corruption == "out_of_interval_source_frame_index":
        frame["sourceFrameIndex"] = interval["endFrame"] + 1
    elif corruption == "reordered_source_frame_index":
        frame["sourceFrameIndex"] = previous_frame["sourceFrameIndex"] - 1
    elif corruption == "missing_source_time":
        frame.pop("sourceTimeSec")
    elif corruption == "invalid_source_time":
        frame["sourceTimeSec"] = "not-a-time"
    elif corruption == "out_of_interval_source_time":
        frame["sourceTimeSec"] = interval["endTimeSec"] + 1 / 30
    elif corruption == "reordered_source_time":
        frame["sourceTimeSec"] = previous_frame["sourceTimeSec"] - 1 / 30
    else:
        raise AssertionError(f"Unhandled corruption: {corruption}")

    corrupted_state = corrupted_payload["artifactState"]
    corrupted_state["selectionEvidence"]["cyclicRebake"] = baked_payload_identity(
        corrupted_payload
    )
    # Keep the identity current so the failure proves the interval lineage
    # check inspects interior provenance, rather than only its content hash.
    assert corrupted_state["selectionEvidence"]["cyclicRebake"]["contentSha256"] == (
        baked_payload_identity(corrupted_payload)["contentSha256"]
    )
    assert corrupted_payload["frames"][0]["sourceFrameIndex"] == interval["startFrame"]
    assert corrupted_payload["frames"][-1]["sourceFrameIndex"] == interval["endFrame"]
    with pytest.raises(ValueError, match="interval does not match its selected-cycle evidence"):
        bake.validate_artifact_state(corrupted_state, movement_payload=corrupted_payload)


def test_cycle_lineage_excludes_synthetic_bridge_from_source_interval_but_counts_it():
    from exercise_motion_pkg.artifact_state import cycle_selection_evidence

    interval = {
        "type": "detected_cycle",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    payload["frames"].append(
        {"syntheticLoopBridge": True, "timeSec": len(payload["frames"]) / 30}
    )
    payload["frameCount"] = len(payload["frames"])
    full_clip = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    state = bake.artifact_state_for_baked_payload(
        payload,
        contract={"completionMode": "return_to_start", "requiresReturnToStart": True},
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=cycle_selection_evidence(full_clip, interval),
    )

    assert state["terminal"] is True
    assert state["selectionEvidence"]["cyclicRebake"]["frameCount"] == len(
        payload["frames"]
    )
    bake.validate_artifact_state(state, movement_payload=payload)


@pytest.mark.parametrize(
    ("cycle_fit_applied", "expected_rendered_classes"),
    [
        (True, [bake.CYCLIC_REBAKE]),
        (False, [bake.FULL_CLIP_BAKE]),
    ],
)
def test_valid_required_cycle_rebake_skips_full_clip_review_render_but_keeps_fallback(
    tmp_path,
    monkeypatch,
    cycle_fit_applied,
    expected_rendered_classes,
):
    from exercise_motion_pkg.artifact_state import cycle_selection_evidence

    contract = {
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
    }
    interval = {
        "type": "detected_cycle",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    full_clip = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    full_clip["artifactState"] = bake.artifact_state_for_baked_payload(
        full_clip,
        contract=contract,
        selection_class=bake.FULL_CLIP_BAKE,
    )
    cycle = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    cycle["source"]["frameCount"] = 60
    cycle["artifactState"] = bake.artifact_state_for_baked_payload(
        cycle,
        contract=contract,
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=cycle_selection_evidence(full_clip, interval),
    )
    cycle["controlledMotionFit"] = {"applied": cycle_fit_applied}

    rendered_classes = []

    def deterministic_gate(payload, *_args, **_kwargs):
        passed = not (
            payload["artifactState"]["artifactClass"] == bake.CYCLIC_REBAKE
            and not cycle_fit_applied
        )
        return {"passed": passed, "rejectionReasons": [] if passed else ["fit_not_applied"]}

    monkeypatch.setattr(bake, "pre_render_deterministic_gate", deterministic_gate)
    monkeypatch.setattr(
        bake,
        "render_baked_wear_frames_with_playwright",
        lambda _page, *, export_payload, frame_indices, options: (
            rendered_classes.append(export_payload["artifactState"]["artifactClass"])
            or ["data:image/jpeg;base64,AA=="] * len(frame_indices)
        ),
    )
    monkeypatch.setattr(
        bake,
        "write_validated_review_video_from_data_urls",
        lambda *_args, **_kwargs: (None, {"passed": True}),
    )

    artifacts = []
    for index, (payload, artifact_class) in enumerate(
        [(full_clip, bake.FULL_CLIP_BAKE), (cycle, bake.CYCLIC_REBAKE)]
    ):
        artifact_dir = tmp_path / str(index)
        artifact_dir.mkdir()
        artifacts.append(
            bake.BakedLoopArtifact(
                loop_index=index,
                skeleton_path=artifact_dir / "skeleton.json",
                review_video_path=artifact_dir / "review.webm",
                export_payload=payload,
                artifact_class=artifact_class,
            )
        )

    bake.render_prechecked_baked_artifacts(
        page=None,
        artifacts=artifacts,
        workspace=tmp_path,
        exercise_motion_contract=contract,
    )

    assert rendered_classes == expected_rendered_classes
    if cycle_fit_applied:
        parent_gate = full_clip["preRenderDeterministicGate"]
        assert parent_gate["passed"] is False
        assert "required_cycle_rebake_available" in parent_gate["rejectionReasons"]
        assert parent_gate["supersededByRequiredArtifact"]["artifactClass"] == bake.CYCLIC_REBAKE
    else:
        assert full_clip["preRenderDeterministicGate"]["passed"] is True


@pytest.mark.parametrize("cache_hit", [False, True], ids=["fresh-bake", "cache-hit"])
@pytest.mark.parametrize(
    "selection_class",
    [bake.CYCLE_SELECTION, bake.BOUNDED_MOVEMENT_SELECTION],
    ids=["cyclic", "bounded"],
)
def test_rematerialized_selection_preserves_lineage_through_package_audit(
    tmp_path,
    monkeypatch,
    cache_hit,
    selection_class,
):
    from exercise_motion_pkg.artifact_state import (
        build_packaged_artifact_state,
        bounded_movement_selection_evidence,
        cycle_selection_evidence,
    )

    interval = {
        "type": "source_selection",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    child_interval = {
        "type": "source_selection",
        "startFrame": 10,
        "endFrame": 30,
        "startTimeSec": 10 / 30,
        "endTimeSec": 30 / 30,
        "durationSec": 20 / 30,
    }
    if selection_class == bake.CYCLE_SELECTION:
        contract = {
            "completionMode": "return_to_start",
            "requiresReturnToStart": True,
        }
        full_clip = _artifact_test_payload(
            start_frame=0,
            end_frame=59,
            frame_count=60,
            loop_enabled=False,
        )
        parent_payload = _artifact_test_payload(
            start_frame=5,
            end_frame=45,
            frame_count=41,
            loop_enabled=True,
        )
        parent_evidence = cycle_selection_evidence(full_clip, interval)
    else:
        contract = {"completionMode": "distinct_end_state"}
        parent_payload = _artifact_test_payload(
            start_frame=5,
            end_frame=45,
            frame_count=41,
            loop_enabled=False,
        )
        source_parent_payload = _artifact_test_payload(
            start_frame=0,
            end_frame=59,
            frame_count=60,
            loop_enabled=False,
        )
        parent_evidence = {
            "boundedMovementSelection": bounded_movement_selection_evidence(
                interval,
                source_parent_payload=source_parent_payload,
            )
        }
    parent_state = bake.artifact_state_for_baked_payload(
        parent_payload,
        contract=contract,
        selection_class=selection_class,
        selection_evidence=parent_evidence,
    )
    parent_payload["artifactState"] = parent_state
    child_payload = _artifact_test_payload(
        start_frame=10,
        end_frame=30,
        frame_count=21,
        loop_enabled=selection_class == bake.CYCLE_SELECTION,
    )
    workspace = tmp_path / f"{selection_class}-{cache_hit}"
    preview_path = workspace / "preview.html"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text("<html></html>", encoding="utf-8")
    artifact_id = "lineage-rematerialization"
    start_seconds = 1.0
    end_seconds = 2.0
    source_pose_reference = {"coordinateSpace": "normalized_image_xy", "frames": []}
    source_camera_reference = {
        "camera": {"cameraRotation": "registered"},
        "sourcePose": source_pose_reference,
    }
    fit_inputs = []
    artifact_slug = f"{artifact_id}-{int(start_seconds * 1000):06d}-{int(end_seconds * 1000):06d}"
    skeleton_path = workspace / "wear" / f"skeleton.baked.{artifact_slug}.json"
    review_video_path = workspace / "review" / f"{artifact_slug}.webm"

    monkeypatch.setattr(bake, "preview_html_source_signature", lambda _path: {"sha256": "preview"})
    monkeypatch.setattr(bake, "_bake_path_code_digest", lambda: {"sha256": "bake-code"})
    monkeypatch.setattr(
        bake,
        "selected_section_wear_skeleton_cache_is_current",
        lambda *_args, **_kwargs: cache_hit,
    )
    monkeypatch.setattr(
        bake,
        "selected_section_review_video_cache_is_current",
        lambda *_args, **_kwargs: cache_hit,
    )
    if cache_hit:
        skeleton_path.parent.mkdir(parents=True)
        review_video_path.parent.mkdir(parents=True)
        skeleton_path.write_text(json.dumps(child_payload), encoding="utf-8")
        review_video_path.write_bytes(b"cached review")
    else:
        monkeypatch.setattr(
            bake,
            "load_baked_source_camera_reference",
            lambda _workspace, _source_pose: source_camera_reference,
        )

        class FakePage:
            def goto(self, *_args, **_kwargs):
                return None

            def wait_for_function(self, *_args, **_kwargs):
                return None

            def evaluate(self, *_args, **_kwargs):
                return json.loads(json.dumps(child_payload))

        class FakeBrowser:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def new_page(self, **_kwargs):
                return FakePage()

        playwright_module = types.ModuleType("playwright")
        playwright_sync_api = types.ModuleType("playwright.sync_api")
        playwright_sync_api.sync_playwright = lambda: None
        playwright_module.sync_api = playwright_sync_api
        monkeypatch.setitem(sys.modules, "playwright", playwright_module)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", playwright_sync_api)
        monkeypatch.setattr(bake, "browser_session", lambda _launch: FakeBrowser())
        monkeypatch.setattr(
            bake,
            "select_readable_preview_camera_options",
            lambda payload, *, options: (options, {}, False),
        )
        monkeypatch.setattr(
            bake,
            "deterministic_post_bake_scene_orientation_correction",
            lambda payload, *, options: (options, {}, False),
        )

        def capture_fit_input(payload, **_kwargs):
            fit_inputs.append(json.loads(json.dumps(payload)))
            return payload, {}

        monkeypatch.setattr(
            bake,
            "constrain_baked_payload_to_source_articulation",
            capture_fit_input,
        )
        monkeypatch.setattr(bake, "dense_loop_review_video_frame_indices", lambda _payload: [0, 10, 20])
        monkeypatch.setattr(
            bake,
            "render_baked_wear_frames_with_playwright",
            lambda *_args, **_kwargs: ["frame-0", "frame-1", "frame-2"],
        )
        monkeypatch.setattr(bake, "repeated_review_frame_data_urls", lambda frames, **_kwargs: frames)
        monkeypatch.setattr(bake, "write_review_video_from_data_urls", lambda _frames, path, **_kwargs: Path(path).write_bytes(b"review"))
        monkeypatch.setattr(bake, "review_video_render_quality_metrics", lambda _path: {"passed": True})
        monkeypatch.setattr(bake, "review_video_encode_fidelity_metrics", lambda *_args: {"passed": True})

    artifact = bake.bake_preview_time_range_with_playwright.__wrapped__(
        preview_html_path=preview_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        options={},
        candidate_workspace=workspace,
        review_frames=5,
        artifact_id=artifact_id,
        selection_class=selection_class,
        exercise_motion_contract=contract,
        source_pose_reference=source_pose_reference,
        lineage_parent_state=parent_state,
        lineage_parent_payload=parent_payload,
    )

    if not cache_hit:
        assert len(fit_inputs) == 1
        fit_input = fit_inputs[0]
        assert fit_input["sourcePoseCameraReference"] == source_camera_reference
        from exercise_motion_pkg import controlled_motion

        fit_selection = controlled_motion._fit_source_interval_selection(fit_input)
        assert fit_selection["available"] is True
        assert fit_selection["kind"] == (
            "cycle" if selection_class == bake.CYCLE_SELECTION else "bounded_movement"
        )

    movement_state = artifact.export_payload["artifactState"]
    assert movement_state["terminal"] is True
    assert movement_state["lineageComplete"] is True
    selected_interval = movement_state["selectionEvidence"][
        "cycleSelection" if selection_class == bake.CYCLE_SELECTION else "boundedMovementSelection"
    ]["interval"]
    assert selected_interval["type"] == child_interval["type"]
    assert selected_interval["startFrame"] == child_interval["startFrame"]
    assert selected_interval["endFrame"] == child_interval["endFrame"]
    assert selected_interval["startTimeSec"] == pytest.approx(child_interval["startTimeSec"])
    assert selected_interval["endTimeSec"] == pytest.approx(child_interval["endTimeSec"])
    assert selected_interval["durationSec"] == pytest.approx(child_interval["durationSec"])
    bake.validate_artifact_state(movement_state, movement_payload=artifact.export_payload)

    identity = bake.selected_skeleton_file_identity(artifact.skeleton_path)
    package_state = build_packaged_artifact_state(
        movement_state,
        package_class=bake.PACKAGED_MOVEMENT,
    )
    review_window, _ = bake.build_final_output_review_window_evidence(
        artifact.export_payload,
        requested_frame_count=7,
    )
    entry = {
        "artifactClass": movement_state["artifactClass"],
        "artifactState": movement_state,
        "packagedArtifactClass": bake.PACKAGED_MOVEMENT,
        "packagedArtifactState": package_state,
        "packagedWearSkeletonPath": str(artifact.skeleton_path),
        "selectedWearSkeletonPath": str(artifact.skeleton_path),
        "packagedSkeletonReviewParity": {
            "verified": True,
            "artifactClass": movement_state["artifactClass"],
            "artifactHistory": movement_state["history"],
            **identity,
        },
        "ranking": {
            "payload": {
                "finalOutputValidation": {
                    "artifactClassGate": {
                        "passed": True,
                        "artifactClass": movement_state["artifactClass"],
                    },
                    "renderEvidence": {
                        "skeletonIdentity": identity,
                        "reviewWindow": review_window,
                    },
                }
            }
        },
    }
    assert bake.audit_artifact_package_state(
        entry,
        skeleton_path=artifact.skeleton_path,
    )["passed"] is True

    tampered_payload = json.loads(json.dumps(artifact.export_payload))
    tampered_state = tampered_payload["artifactState"]
    selection_key = (
        "cycleSelection" if selection_class == bake.CYCLE_SELECTION else "boundedMovementSelection"
    )
    tampered_selection = tampered_state["selectionEvidence"][selection_key]
    tampered_selection["interval"]["startFrame"] = 9
    tampered_selection["interval"]["startTimeSec"] = 9 / 30
    tampered_selection["interval"]["durationSec"] = 21 / 30
    if selection_class == bake.CYCLE_SELECTION:
        selection_payload = {
            "fullClipContentSha256": tampered_state["selectionEvidence"]["fullClipBake"]["contentSha256"],
            "interval": tampered_selection["interval"],
        }
        tampered_selection["selectionId"] = hashlib.sha256(
            json.dumps(selection_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    else:
        tampered_selection["selectionId"] = hashlib.sha256(
            json.dumps(
                {
                    "sourceParentContentSha256": tampered_selection["sourceParent"][
                        "contentSha256"
                    ],
                    "interval": tampered_selection["interval"],
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    artifact.skeleton_path.write_text(json.dumps(tampered_payload), encoding="utf-8")
    tampered_identity = bake.selected_skeleton_file_identity(artifact.skeleton_path)
    entry["artifactState"] = tampered_state
    entry["packagedArtifactState"] = build_packaged_artifact_state(
        tampered_state,
        package_class=bake.PACKAGED_MOVEMENT,
    )
    entry["packagedSkeletonReviewParity"].update(tampered_identity)
    entry["ranking"]["payload"]["finalOutputValidation"]["renderEvidence"][
        "skeletonIdentity"
    ] = tampered_identity
    rejected = bake.audit_artifact_package_state(entry, skeleton_path=artifact.skeleton_path)
    assert rejected["passed"] is False
    assert "selected_artifact_state_invalid" in rejected["rejectionReasons"]


def test_cycle_without_full_clip_parent_cannot_become_terminal():
    from exercise_motion_pkg.artifact_state import build_artifact_state

    state = build_artifact_state(
        artifact_class=bake.CYCLIC_REBAKE,
        selection_class=bake.CYCLE_SELECTION,
        required_class=None,
    )

    assert state["history"] == [bake.CYCLE_SELECTION, bake.CYCLIC_REBAKE]
    assert state["lineageComplete"] is False
    assert state["terminal"] is False
    gate = bake.movement_artifact_class_gate(
        state,
        accepted_classes=bake.TERMINAL_ARTIFACT_CLASSES,
        gate_name="focused_regression",
        require_terminal=True,
    )
    assert gate["passed"] is False
    assert gate["rejectionReasons"] == [
        "artifact_lineage_incomplete",
        "artifact_state_not_terminal",
    ]

    with pytest.raises(ValueError, match="unaccepted movement"):
        from exercise_motion_pkg.artifact_state import build_packaged_artifact_state
        build_packaged_artifact_state(state, package_class=bake.PACKAGED_MOVEMENT)


def test_full_clip_lineage_tracks_the_final_fitted_payload_identity():
    from exercise_motion_pkg.artifact_state import build_artifact_state

    payload = _artifact_test_payload(
        start_frame=0,
        end_frame=19,
        frame_count=20,
        loop_enabled=False,
    )
    state = bake.artifact_state_for_baked_payload(
        payload,
        contract=None,
        selection_class=bake.FULL_CLIP_BAKE,
    )
    assert state["lineageComplete"] is True
    assert state["terminal"] is True
    assert state["selectionEvidence"]["fullClipBake"]["identityVersion"] == 2

    changed_payload = json.loads(json.dumps(payload))
    changed_payload["frames"][-1]["joints"]["pelvis"][1] = 0.1
    with pytest.raises(ValueError, match="Full-clip bake identity does not match"):
        bake.validate_artifact_state(state, movement_payload=changed_payload)

    incomplete = build_artifact_state(
        artifact_class=bake.FULL_CLIP_BAKE,
        selection_class=bake.FULL_CLIP_BAKE,
        required_class=None,
    )
    assert incomplete["lineageComplete"] is False
    assert incomplete["terminal"] is False


def test_bounded_rebake_requires_matching_selection_and_output_identity():
    from exercise_motion_pkg.artifact_state import (
        PACKAGED_MOVEMENT,
        bounded_movement_selection_evidence,
        build_packaged_artifact_state,
        build_artifact_state,
        validate_artifact_state,
    )

    interval = {
        "type": "exact_source_movement_instance",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    incomplete = build_artifact_state(
        artifact_class=bake.BOUNDED_MOVEMENT_REBAKE,
        selection_class=bake.BOUNDED_MOVEMENT_SELECTION,
        required_class=bake.BOUNDED_MOVEMENT_REBAKE,
        selection_evidence={
            "boundedMovementSelection": _legacy_bounded_selection_evidence(interval),
        },
    )
    assert incomplete["lineageComplete"] is False
    assert incomplete["terminal"] is False
    assert bake.movement_artifact_class_gate(
        incomplete,
        accepted_classes={bake.BOUNDED_MOVEMENT_REBAKE},
        gate_name="bounded_lineage_regression",
    )["passed"] is False

    payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=False,
    )
    payload["artifactState"] = bake.artifact_state_for_baked_payload(
        payload,
        contract={"completionMode": "distinct_end_state"},
        selection_class=bake.BOUNDED_MOVEMENT_SELECTION,
        # Persisted schema-v1 state before source-parent binding.
        selection_evidence={
            "boundedMovementSelection": _legacy_bounded_selection_evidence(interval),
        },
    )
    assert payload["artifactState"]["lineageComplete"] is True
    assert payload["artifactState"]["terminal"] is True
    validate_artifact_state(payload["artifactState"], movement_payload=payload)

    payload["loop"]["sourceEndFrame"] = 44
    with pytest.raises(ValueError, match="does not match its movement payload"):
        validate_artifact_state(payload["artifactState"], movement_payload=payload)

    looping_payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    looping_payload["artifactState"] = bake.artifact_state_for_baked_payload(
        looping_payload,
        contract={"completionMode": "distinct_end_state"},
        selection_class=bake.BOUNDED_MOVEMENT_SELECTION,
        selection_evidence={
            "boundedMovementSelection": _legacy_bounded_selection_evidence(interval),
        },
    )
    assert looping_payload["artifactState"]["lineageComplete"] is False
    assert looping_payload["artifactState"]["terminal"] is False
    gate = bake.movement_artifact_class_gate(
        looping_payload["artifactState"],
        accepted_classes={bake.BOUNDED_MOVEMENT_REBAKE},
        gate_name="bounded_loop_regression",
    )
    assert gate["passed"] is False
    with pytest.raises(ValueError, match="unaccepted movement"):
        build_packaged_artifact_state(
            looping_payload["artifactState"],
            package_class=PACKAGED_MOVEMENT,
        )
    forged_state = dict(looping_payload["artifactState"])
    forged_state["lineageComplete"] = True
    forged_state["terminal"] = True
    with pytest.raises(ValueError, match="lineage flag"):
        validate_artifact_state(forged_state, movement_payload=looping_payload)


def test_bounded_selection_identity_binds_source_parent_payload():
    from exercise_motion_pkg.artifact_state import (
        bounded_movement_selection_evidence,
        validate_artifact_state,
    )

    interval = {
        "type": "exact_source_movement_instance",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    parent_a = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    parent_b = json.loads(json.dumps(parent_a))
    parent_b["frames"][0]["joints"]["pelvis"][0] = 0.25

    evidence_a = bounded_movement_selection_evidence(
        interval,
        source_parent_payload=parent_a,
    )
    evidence_b = bounded_movement_selection_evidence(
        interval,
        source_parent_payload=parent_b,
    )
    assert evidence_a["selectionId"] != evidence_b["selectionId"]

    fitted_payload = _artifact_test_payload(
        start_frame=10,
        end_frame=30,
        frame_count=21,
        loop_enabled=False,
    )
    fitted_evidence = bake.selection_evidence_for_materialized_interval(
        parent_selection_evidence={"boundedMovementSelection": evidence_a},
        movement_payload=fitted_payload,
        selection_class=bake.BOUNDED_MOVEMENT_SELECTION,
        parent_interval=interval,
        source_parent_payload=parent_a,
    )
    fitted_selection = fitted_evidence["boundedMovementSelection"]
    assert fitted_selection["sourceParent"] == evidence_a["sourceParent"]
    assert fitted_selection["interval"]["startFrame"] == 10
    assert fitted_selection["interval"]["endFrame"] == 30

    state = bake.artifact_state_for_baked_payload(
        fitted_payload,
        contract={"completionMode": "distinct_end_state"},
        selection_class=bake.BOUNDED_MOVEMENT_SELECTION,
        selection_evidence=fitted_evidence,
        source_parent_payload=parent_a,
    )
    validate_artifact_state(
        state,
        movement_payload=fitted_payload,
        source_parent_payload=parent_a,
    )
    with pytest.raises(ValueError, match="source-parent identity does not match"):
        validate_artifact_state(
            state,
            movement_payload=fitted_payload,
            source_parent_payload=parent_b,
        )

def test_final_review_window_must_match_selected_cycle_interval():
    from exercise_motion_pkg.artifact_state import cycle_selection_evidence

    interval = {
        "type": "detected_cycle",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    full_clip = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    payload["artifactState"] = bake.artifact_state_for_baked_payload(
        payload,
        contract={"completionMode": "return_to_start", "requiresReturnToStart": True},
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=cycle_selection_evidence(full_clip, interval),
    )
    review_window, state = bake.build_final_output_review_window_evidence(
        payload,
        requested_frame_count=8,
    )
    bake.validate_final_output_review_window(
        review_window,
        artifact_state=state,
        movement_payload=payload,
    )

    corrupted = json.loads(json.dumps(review_window))
    corrupted["selection"]["interval"]["endFrame"] = 44
    with pytest.raises(ValueError, match="interval differs from the selected artifact lineage"):
        bake.validate_final_output_review_window(
            corrupted,
            artifact_state=state,
            movement_payload=payload,
        )


def test_review_sampler_uses_materialized_frames_when_legacy_payload_omits_frame_count():
    payload = _artifact_test_payload(
        start_frame=0,
        end_frame=19,
        frame_count=20,
        loop_enabled=False,
    )
    del payload["frameCount"]
    payload["artifactState"] = bake.artifact_state_for_baked_payload(
        payload,
        contract=None,
        selection_class=bake.FULL_CLIP_BAKE,
    )

    review_window, _ = bake.build_final_output_review_window_evidence(
        payload,
        requested_frame_count=8,
    )

    assert review_window["frameCount"] == 20
    assert len(review_window["frameIndices"]) == 8
    assert review_window["frameIndices"][0] == 0
    assert review_window["frameIndices"][-1] == 19


def test_authoritative_distinct_end_source_interval_has_bounded_artifact_class():
    clip = SimpleNamespace(frame_count=91, fps=30.0)

    eligible = bake.build_candidate_review_eligible_loops(
        clip,
        source_interval_authority={
            "authoritative": True,
            "movementInstance": {
                "completionMode": "distinct_end_state",
                "trimmed": False,
            },
        },
    )

    assert len(eligible) == 1
    assert eligible[0].loop["type"] == "exact_source_movement_instance"
    assert eligible[0].artifact_class == bake.BOUNDED_MOVEMENT_SELECTION
    assert eligible[0].end_seconds == pytest.approx(90 / 30.0)


def test_review_item_load_rejects_malformed_persisted_artifact_history(tmp_path):
    item = bake.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=0,
        exercise_name="Curl",
        candidate_title="source",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "preview.webm",
        duration_sec=2.0,
        loop_start_seconds=0.0,
        loop_end_seconds=2.0,
        candidate={},
        artifact_class=bake.CYCLIC_REBAKE,
        export_payload={
            "artifactState": {
                "schemaVersion": 1,
                "artifactClass": bake.CYCLIC_REBAKE,
                "requiredClass": bake.CYCLIC_REBAKE,
                "terminal": True,
                "history": [bake.FULL_CLIP_BAKE, bake.CYCLIC_REBAKE],
                "selectionEvidence": {},
            }
        },
    )

    with pytest.raises(ValueError, match="Invalid movement artifact transition"):
        bake.review_item_artifact_class(item)


def test_selected_output_audit_rejects_broken_artifact_provenance(tmp_path, monkeypatch):
    from exercise_motion_pkg.artifact_state import (
        cycle_selection_evidence,
        build_packaged_artifact_state,
        validate_packaged_artifact_state,
    )

    skeleton_path = tmp_path / "exercise_wear_skeleton.json"
    payload = _artifact_test_payload(
        start_frame=5,
        end_frame=45,
        frame_count=41,
        loop_enabled=True,
    )
    full_clip_payload = _artifact_test_payload(
        start_frame=0,
        end_frame=59,
        frame_count=60,
        loop_enabled=False,
    )
    interval = {
        "type": "detected_cycle",
        "startFrame": 5,
        "endFrame": 45,
        "startTimeSec": 5 / 30,
        "endTimeSec": 45 / 30,
        "durationSec": 40 / 30,
    }
    payload["artifactState"] = bake.artifact_state_for_baked_payload(
        payload,
        contract={"completionMode": "return_to_start", "requiresReturnToStart": True},
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=cycle_selection_evidence(full_clip_payload, interval),
    )
    skeleton_path.write_text(json.dumps(payload), encoding="utf-8")
    skeleton_identity = bake.selected_skeleton_file_identity(skeleton_path)
    movement_state = payload["artifactState"]
    package_state = build_packaged_artifact_state(
        movement_state,
        package_class="packaged_movement",
    )
    review_window, _ = bake.build_final_output_review_window_evidence(
        payload,
        requested_frame_count=bake.FINAL_OUTPUT_VALIDATION_FRAME_COUNT,
    )
    entry = {
        "artifactClass": bake.CYCLIC_REBAKE,
        "artifactState": movement_state,
        "packagedArtifactClass": "packaged_movement",
        "packagedArtifactState": package_state,
        "packagedWearSkeletonPath": str(skeleton_path),
        "packagedSkeletonReviewParity": {
            "verified": True,
            "artifactClass": bake.CYCLIC_REBAKE,
            "artifactHistory": movement_state["history"],
            **skeleton_identity,
        },
        "selectedWearSkeletonPath": str(skeleton_path),
        "selectedInputVideoPath": str(tmp_path / "input.mp4"),
        "selectedReviewVideoPath": str(tmp_path / "preview.webm"),
        "selectedPreviewHtmlPath": str(tmp_path / "preview.html"),
        "ranking": {
            "payload": {
                "finalOutputValidation": {
                    "artifactClassGate": {
                        "passed": True,
                        "artifactClass": bake.CYCLIC_REBAKE,
                    },
                    "renderEvidence": {
                        "available": True,
                        "skeletonIdentity": skeleton_identity,
                        "reviewWindow": review_window,
                    },
                }
            }
        },
    }
    (tmp_path / "input.mp4").write_bytes(b"input")
    (tmp_path / "preview.webm").write_bytes(b"preview")
    (tmp_path / "preview.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(
        bake,
        "video_visual_jump_metrics",
        lambda _path: {"passed": True, "visualJumpCount": 0},
    )
    monkeypatch.setattr(
        bake,
        "review_video_render_quality_metrics",
        lambda _path: {"passed": True},
    )
    monkeypatch.setattr(
        bake,
        "selected_skeleton_audit_metrics",
        lambda *_args, **_kwargs: {"passed": True, "severeLoopMismatch": False},
    )
    monkeypatch.setattr(
        bake,
        "selected_preview_html_link_metrics",
        lambda _path: {"passed": True},
    )
    manifest_path = tmp_path / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps({"selectedResults": [entry], "selectionStatus": "selected"}),
        encoding="utf-8",
    )

    valid_report = bake.audit_selected_output_manifest(manifest_path)
    assert valid_report["passed"] is True

    # Keep the review and package hashes consistent with the source skeleton,
    # but alter only its embedded artifact state. The manifest state must not
    # authorize a different skeleton lineage.
    payload["artifactState"] = {**movement_state, "requiredClass": None}
    bake.validate_artifact_state(payload["artifactState"], movement_payload=payload)
    skeleton_path.write_text(json.dumps(payload), encoding="utf-8")
    drifted_identity = bake.selected_skeleton_file_identity(skeleton_path)
    entry["packagedSkeletonReviewParity"].update(drifted_identity)
    entry["ranking"]["payload"]["finalOutputValidation"]["renderEvidence"][
        "skeletonIdentity"
    ] = drifted_identity
    manifest_path.write_text(
        json.dumps({"selectedResults": [entry], "selectionStatus": "selected"}),
        encoding="utf-8",
    )
    embedded_state_drift = bake.audit_selected_output_manifest(manifest_path)
    assert embedded_state_drift["passed"] is False
    assert "selected_artifact_state_invalid" in embedded_state_drift["options"][0][
        "rejectionReasons"
    ]

    payload["artifactState"] = movement_state
    skeleton_path.write_text(json.dumps(payload), encoding="utf-8")
    entry["packagedSkeletonReviewParity"].update(skeleton_identity)
    entry["ranking"]["payload"]["finalOutputValidation"]["renderEvidence"][
        "skeletonIdentity"
    ] = skeleton_identity

    entry["artifactState"] = {
        **movement_state,
        "history": [bake.FULL_CLIP_BAKE, bake.CYCLIC_REBAKE],
    }
    manifest_path.write_text(
        json.dumps({"selectedResults": [entry], "selectionStatus": "selected"}),
        encoding="utf-8",
    )
    report = bake.audit_selected_output_manifest(manifest_path)

    assert report["passed"] is False
    assert "selected_artifact_state_invalid" in report["options"][0]["rejectionReasons"]
    assert report["options"][0]["artifactPackageState"]["approvedMovement"] is True

    invalid_package_state = {
        **package_state,
        "history": [
            bake.FULL_CLIP_BAKE,
            bake.CYCLIC_REBAKE,
            "packaged_movement",
        ],
    }
    with pytest.raises(ValueError, match="Invalid movement artifact transition"):
        validate_packaged_artifact_state(
            invalid_package_state,
            movement_state=movement_state,
        )


def test_manual_review_package_remains_unapproved_and_can_have_nonterminal_parent(tmp_path):
    from exercise_motion_pkg.artifact_state import (
        MANUAL_REVIEW_PACKAGE,
        PACKAGED_MOVEMENT,
        build_artifact_state,
        build_packaged_artifact_state,
        validate_packaged_artifact_state,
    )

    skeleton_path = tmp_path / "manual_review_wear_skeleton.json"
    movement_state = build_artifact_state(
        artifact_class=bake.FULL_CLIP_BAKE,
        selection_class=bake.FULL_CLIP_BAKE,
        required_class=bake.CYCLIC_REBAKE,
    )
    skeleton_path.write_text(
        json.dumps({"frames": [{}, {}], "artifactState": movement_state}),
        encoding="utf-8",
    )
    manual_package = build_packaged_artifact_state(
        movement_state,
        package_class=MANUAL_REVIEW_PACKAGE,
    )
    entry = {
        "artifactClass": bake.FULL_CLIP_BAKE,
        "artifactState": movement_state,
        "selectionStatus": "needs_manual_review",
        "packagedArtifactClass": MANUAL_REVIEW_PACKAGE,
        "packagedArtifactState": manual_package,
        "packagedWearSkeletonPath": str(skeleton_path),
        "selectedWearSkeletonPath": str(skeleton_path),
        "packagedSkeletonReviewParity": {
            "verified": False,
            "reason": "review_identity_unavailable",
            "artifactClass": bake.FULL_CLIP_BAKE,
            "artifactHistory": movement_state["history"],
        },
    }

    audit = bake.audit_artifact_package_state(
        entry,
        skeleton_path=skeleton_path,
        manual_review=True,
    )

    assert audit["passed"] is True
    assert audit["approvedMovement"] is False
    assert manual_package["parentTerminal"] is False

    manual_review_dir = tmp_path / "manual-review"
    manual_review_dir.mkdir()
    manifest_path = manual_review_dir / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps({"selectionStatus": "needs_manual_review", "manualReviewFallback": entry}),
        encoding="utf-8",
    )
    manifest_report = bake.audit_selected_output_manifest(manifest_path)
    assert manifest_report["passed"] is False
    assert manifest_report["manualReviewPackage"]["passed"] is True
    assert manifest_report["manualReviewPackage"]["approvedMovement"] is False

    entry["artifactState"] = {
        **movement_state,
        "history": [bake.FULL_CLIP_BAKE, bake.CYCLIC_REBAKE],
    }
    manifest_path.write_text(
        json.dumps({"selectionStatus": "needs_manual_review", "manualReviewFallback": entry}),
        encoding="utf-8",
    )
    invalid_manifest_report = bake.audit_selected_output_manifest(manifest_path)
    assert invalid_manifest_report["passed"] is False
    assert invalid_manifest_report["manualReviewPackage"]["passed"] is False
    assert "manual_review_artifact_state_invalid" in invalid_manifest_report["rejectionReasons"]

    legacy_manual_package = {
        key: manual_package[key]
        for key in (
            "schemaVersion",
            "artifactClass",
            "terminal",
            "approvedMovement",
            "parentArtifactClass",
            "history",
        )
    }
    assert validate_packaged_artifact_state(
        legacy_manual_package,
        movement_state=movement_state,
    ) == legacy_manual_package
    with pytest.raises(ValueError, match="cannot be packaged as approved"):
        build_packaged_artifact_state(
            movement_state,
            package_class=PACKAGED_MOVEMENT,
        )


def test_candidate_bake_manifest_commits_processing_and_terminal_lifecycle_atomically(tmp_path):
    workspace = tmp_path / "candidate"
    processing = {
        "status": "processing",
        "activeStage": "browser_bake",
        "artifactLifecycle": {
            "schemaVersion": 1,
            "state": "processing",
            "stage": "browser_bake",
            "terminal": False,
            "history": [{"state": "processing", "stage": "browser_bake"}],
        },
    }
    bake.write_candidate_bake_manifest(workspace, processing)
    path = workspace / "review" / "bake_manifest.json"
    assert json.loads(path.read_text())["artifactLifecycle"]["stage"] == "browser_bake"

    incomplete = {**processing, "status": "needs_motion_processing"}
    bake.write_candidate_bake_manifest(workspace, incomplete)
    incomplete_manifest = json.loads(path.read_text())
    assert incomplete_manifest["artifactLifecycle"]["state"] == "needs_motion_processing"
    assert incomplete_manifest["artifactLifecycle"]["terminal"] is False
    assert not bake.candidate_result_has_terminal_quality_decision(incomplete_manifest)

    terminal = {**processing, "status": "ready_for_selection"}
    bake.write_candidate_bake_manifest(workspace, terminal)
    lifecycle = json.loads(path.read_text())["artifactLifecycle"]
    assert lifecycle["state"] == "ready_for_selection"
    assert lifecycle["terminal"] is True
    assert terminal["artifactLifecycle"] == lifecycle
    assert [entry["state"] for entry in lifecycle["history"]] == [
        "processing", "ready_for_selection",
    ]
    assert not list(path.parent.glob("*.tmp"))


def test_atomic_json_writer_replaces_existing_manifest(tmp_path):
    path = tmp_path / "selection_manifest.json"
    path.write_text('{"state":"old"}')
    bake.write_json_atomic(path, {"state": "new"})
    assert json.loads(path.read_text()) == {"state": "new"}
    assert list(tmp_path.iterdir()) == [path]


def test_workspace_lease_excludes_a_second_owner_and_releases_cleanly(tmp_path):
    from exercise_motion_pkg.process_lock import WorkspaceLease

    with WorkspaceLease(tmp_path, stage="first_run"):
        owner = json.loads((tmp_path / ".motion_workspace.owner.json").read_text())
        assert owner["stage"] == "first_run"
        with pytest.raises(TimeoutError, match="already owned"):
            with WorkspaceLease(tmp_path, stage="second_run"):
                pytest.fail("A second process must not own the same workspace")
    assert not (tmp_path / ".motion_workspace.owner.json").exists()
    with WorkspaceLease(tmp_path, stage="resumed_run"):
        assert json.loads((tmp_path / ".motion_workspace.owner.json").read_text())["stage"] == "resumed_run"


def test_staged_wave_entrypoint_leases_its_checkpoint_workspace(tmp_path):
    from exercise_motion_pkg.process_lock import WorkspaceLease

    with WorkspaceLease(tmp_path, stage="existing_wave_owner"):
        with pytest.raises(TimeoutError, match="already owned"):
            wave.run_staged_bake_wave(
                [], workspace=tmp_path, wave_id="duplicate-wave",
            )


def test_workspace_lease_blocks_powershell_file_share_none_owner(tmp_path):
    import os
    import shutil
    import subprocess

    from exercise_motion_pkg.process_lock import WorkspaceLease

    powershell = shutil.which("pwsh")
    if os.name != "nt" or powershell is None:
        pytest.skip("PowerShell/.NET file-sharing interoperability is Windows-specific")
    environment = dict(os.environ)
    environment["MOTION_WORKSPACE_LEASE_TEST_DIR"] = str(tmp_path)
    command = (
        "$path = Join-Path $env:MOTION_WORKSPACE_LEASE_TEST_DIR '.motion_workspace.lock'; "
        "try { $stream = [System.IO.FileStream]::new($path, "
        "[System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, "
        "[System.IO.FileShare]::None); $stream.Dispose(); exit 2 } "
        "catch [System.IO.IOException] { exit 23 }"
    )
    with WorkspaceLease(tmp_path, stage="python_owner"):
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
    assert result.returncode == 23, result.stdout + result.stderr


def test_final_fit_source_projection_constraint_uses_retained_camera_and_timestamps():
    from exercise_motion_pkg.controlled_motion import (
        _prepare_source_projection_fit_constraints,
        _source_projection_fit_rows,
    )

    names = (
        "left_shoulder", "right_shoulder", "left_hip", "right_hip",
        "left_knee", "right_knee",
    )
    frame_count = 7
    times = np.arange(frame_count, dtype=float) / 10.
    source_origin = 17.0
    points = np.zeros((frame_count, len(names), 3), dtype=float)
    bases = np.asarray([
        [-.2, 1.4, 0.], [.2, 1.4, 0.], [-.15, 1., 0.], [.15, 1., 0.],
        [-.15, .5, 0.], [.15, .5, 0.],
    ])
    source_frames = []
    fit_frames = []
    for frame_index, timestamp in enumerate(times):
        points[frame_index] = bases + np.asarray([timestamp * .08, timestamp * .02, 0.])
        observed = {
            name: [float(points[frame_index, joint, 0] + .5),
                   float(points[frame_index, joint, 1] + .5)]
            for joint, name in enumerate(names)
        }
        source_frames.append({
            "sourceTimeSec": float(source_origin + timestamp),
            "joints": observed,
            "jointConfidence": {name: 1. for name in names},
        })
        fit_frames.append({
            "timeSec": float(timestamp),
            "sourceTimeSec": float(source_origin + timestamp),
        })
    payload = {
        "fps": 10.,
        "frames": fit_frames,
        "sourcePoseCameraReference": {
            "sourcePose": {
                "coordinateSpace": "normalized_image_xy",
                "imageWidth": 1000,
                "imageHeight": 1000,
                "sourceTimeOriginSec": source_origin,
                "frames": source_frames,
            },
            "camera": {
                "cameraRotation": np.eye(3).tolist(),
                "cameraImageTransform": [1., 0., 0., 0., .5, .5],
                "bilateralAssignment": "identity",
            },
        },
    }
    constraint = _prepare_source_projection_fit_constraints(
        payload, fit_frames, names, points, np.zeros((frame_count, len(names)), dtype=bool), 1.7,
    )
    assert constraint["available"] is True
    assert constraint["observationCount"] == frame_count * len(names)
    assert np.max(np.abs(_source_projection_fit_rows(points, constraint))) < 1e-8

    moved = points.copy()
    moved[3, names.index("left_shoulder"), 0] += .1
    assert np.linalg.norm(_source_projection_fit_rows(moved, constraint)) > .01


@pytest.mark.parametrize("reason,expected", [
    ("no_approved_discovery_candidates", "next_source"),
    ("no_reconstruction_ready_source", "next_source"),
    ("source_processing_failed", "retry_infrastructure"),
    ("source_review_incomplete", "retry_review"),
])
def test_source_exhaustion_does_not_trigger_individual_infrastructure_retry(reason, expected):
    state = {"status": "retry_required", "source": {
        "status": "failed", "failureReason": reason, "attempts": [],
    }}
    assert wave.wave_retry_disposition(state) == expected


@pytest.mark.parametrize("rotation,camera,passed", [
    (180, -45, True), (179.62562857778346, -45.37437142221654, True),
    (179.94259943482632, -45.05740056517368, True),
    (0, 135, True), (180, 135, False), (0, -45, False),
])
def test_export_camera_compensation(rotation, camera, passed):
    payload = {"wearDisplay": {"viewYawDegrees": camera},
        "bakedPreviewConfiguration": {"bakedSagittalPlaneAlignment": {
            "applied": True, "yawDegrees": rotation}}}
    assert bake.materialized_camera_is_canonical(payload) is passed


@pytest.mark.parametrize("reference,events", [(None, ["handoff", "compute"]),
                                            ({"frames": []}, ["compute"])])
def test_materialized_metrics_only_handoff_for_missing_pose(monkeypatch, reference, events):
    calls = []
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "materialized_output_acceptance_metrics",
        lambda *args, **kwargs: calls.append("compute") or {"passed": True})
    monkeypatch.setattr(bake, "run_with_caption_gpu_exclusive",
        lambda caption, operation: calls.append("handoff") or operation())
    bake.materialized_metrics_with_gpu_handoff(SimpleNamespace(loop_index=-1), None,
        caption_images=None, source_pose_reference=reference)
    assert calls == events


@pytest.mark.parametrize("status,attempts", [("needs_source_review", 2), ("ready_for_selection", 1), ("failed", 1)])
def test_review_retry_is_bounded_and_owner_specific(status, attempts):
    calls = []
    def run():
        calls.append(1)
        return {"selected": None, "selectionStatus": "needs_manual_review",
            "candidateResults": [{"status": status}]}
    result = wave.finalize_with_bounded_review_retry(run)
    assert len(calls) == result["reviewAttemptCount"] == attempts
    disposition = wave.wave_retry_disposition({"finalValidation": {
        "status": "no_selection", **wave.final_processing_diagnostics(result)}})
    assert disposition == {"needs_source_review": "retry_review", "ready_for_selection": "next_source",
                           "failed": "retry_infrastructure"}[status]


def test_review_retry_stops_when_second_review_succeeds():
    manifests = iter([
        {"selected": None, "candidateResults": [{"status": "needs_source_review"}]},
        {"selected": {"artifact": "approved"}, "candidateResults": []},
    ])
    result = wave.finalize_with_bounded_review_retry(lambda: next(manifests))
    assert result["selected"] == {"artifact": "approved"}
    assert result["reviewAttemptCount"] == 2


@pytest.mark.parametrize("entry_key", ["rejectedBest", "manualReviewFallback"])
def test_outer_retry_does_not_multiply_completed_candidate_review_budget(entry_key):
    calls = []
    def run():
        calls.append(1)
        return {"selected": None, "candidateResults": [{"status": "needs_manual_review"}],
                entry_key: {"ranking": {"payload": {"finalOutputValidation": {
                    "passed": False, "failureOwner": "review", "underlyingMotionRejected": False,
                    "boundedReview": {"additionalReviewCount": 1},
                    "rejectionReasons": ["visual_review_unresolved"]}}}}}
    result = wave.finalize_with_bounded_review_retry(run)
    assert len(calls) == 1
    assert result["selected"] is None
    assert result["reviewRetrySkippedReason"] == "candidate_review_budget_exhausted"


def test_incomplete_source_review_does_not_penalize_source(tmp_path, monkeypatch):
    request = SimpleNamespace(source_outcome_index=tmp_path / "outcomes.json")
    item = wave.StagedWaveItem("curl", "Curl", request)
    monkeypatch.setattr(wave, "_wave_candidates_for_item", lambda item: [])
    monkeypatch.setattr(wave, "update_source_outcome_index",
        lambda *args: pytest.fail("Incomplete evidence must not become a quality outcome"))
    state = {"source": {"failureReason": "source_review_incomplete",
        "attempts": [{"status": "needs_source_review", "videoId": "id"}]}}
    assert wave.wave_retry_disposition(state) == "retry_review"
    assert wave._record_wave_source_rejections([item], {"curl": state}) == []


def test_complete_source_review_cache_tracks_video_contract_model_and_frames(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"first")
    sheet = tmp_path / "frame.jpg"
    sheet.write_bytes(b"frame")
    item = SimpleNamespace(exercise_name="Curl", candidate_workspace=tmp_path, candidate={})
    model = SimpleNamespace(llama_cpp_model="model-one")
    class Session:
        settings = model
        def caption_images(self): pass
    monkeypatch.setattr(bake, "final_output_source_video_window",
        lambda item: (video, bake.DetectionWindow(0, 0, 5)))
    calls = []
    passed = [True]
    def validate(*args, **kwargs):
        calls.append(1)
        return {"passed": passed[0], "reviewStatus": "passed" if passed[0] else "incomplete",
                "uniformContactSheetPaths": [str(path) for path in kwargs['uniform_sheet_paths']],
                "motionContactSheetPaths": []}
    monkeypatch.setattr(bake, "_validate_two_scale_source_uncached", validate)
    def run(contract=None, sheets=None):
        return bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=sheets or [sheet],
            output_dir=tmp_path / "review", caption_images=Session().caption_images,
            exercise_motion_contract=contract)
    run(); run()
    assert len(calls) == 1
    video.write_bytes(b"changed"); run()
    run({"policy": 2}); model.llama_cpp_model = "model-two"; run({"policy": 2})
    sheet.write_bytes(b"changed frame"); run({"policy": 2})
    assert len(calls) == 5
    passed[0] = False
    run({"policy": 3}); run({"policy": 3})
    assert len(calls) == 7  # Incomplete reviews remain retryable.
    passed[0] = True
    run(); run()
    assert len(calls) == 8
    item.candidate['exerciseMotionContract'] = {'advisoryText': 'Updated explicit loading requirement'}
    run(); run()
    assert len(calls) == 9  # The implicit candidate contract is the reviewed contract too.
    alternative = tmp_path / 'other-frame.jpg'
    alternative.write_bytes(b'other sampling of the same video')
    run(sheets=[alternative]); run(sheets=[alternative])
    assert len(calls) == 10  # Existing old sheets have not changed; the supplied evidence has.
    detail = tmp_path / 'original.jpg'
    detail.write_bytes(b'full-resolution implement')
    (tmp_path / 'contact_sheet_crop.json').write_text(json.dumps({'framePaths': [str(detail)]}))
    run(sheets=[alternative]); run(sheets=[alternative])
    assert len(calls) == 11
    detail.write_bytes(b'changed original implement')
    run(sheets=[alternative])
    assert len(calls) == 12


@pytest.mark.parametrize("passed,review_status,expected_calls", [(True, "passed", 1), (False, "incomplete", 2), (False, "rejected", 1)])
def test_preflight_review_defers_uncertain_evidence_before_reconstruction(tmp_path, monkeypatch, passed, review_status, expected_calls):
    candidate = bake.RankedCandidate(0, 1, "curl", "Curl", "curl", {"videoId": "id", "title": "Curl"})
    request = SimpleNamespace(two_scale_source_validation=True, workspace=tmp_path)
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda path: SimpleNamespace(duration_seconds=5))
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **k: [])
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "validate_source_pose_endpoints_against_contract", lambda *a, **k: {})
    for name in ("small_motion", "completeness", "identity", "topology"):
        monkeypatch.setattr(bake, f"two_scale_{name}_failure_is_independent_outlier", lambda **k: False)
    monkeypatch.setattr(bake, "two_scale_source_validation_needs_repair", lambda validation: False)
    calls = []
    def validate(*args, **kwargs):
        calls.append(1)
        return {"passed": passed, "reviewStatus": review_status, "rejectionReasons": ["unresolved"]}
    monkeypatch.setattr(bake, "validate_two_scale_source_with_caption_images", validate)
    def run():
        preflight.review_prepared_source(candidate, request=request, selected_video=tmp_path / "source.mp4",
            contract=None, caption_images=lambda: "")
    if passed:
        run()
    else:
        error = preflight.SourceReviewIncomplete if review_status == "incomplete" else bake.SourceCandidateRejected
        with pytest.raises(error): run()
    assert len(calls) == expected_calls


def test_preflight_rejects_window_after_repair_refutes_required_claim(tmp_path, monkeypatch):
    candidate = bake.RankedCandidate(0, 1, "calf-raise", "Barbell Calf Raise", "calf-raise",
        {"videoId": "id", "title": "Barbell Calf Raise"})
    request = SimpleNamespace(two_scale_source_validation=True, workspace=tmp_path)
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda path: SimpleNamespace(duration_seconds=5))
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **k: [])
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "validate_source_pose_endpoints_against_contract", lambda *a, **k: {})
    for name in ("small_motion", "completeness", "identity", "topology"):
        monkeypatch.setattr(bake, f"two_scale_{name}_failure_is_independent_outlier", lambda **k: False)
    monkeypatch.setattr(bake, "two_scale_source_validation_needs_repair", lambda validation: True)
    validation_calls = []
    monkeypatch.setattr(bake, "validate_two_scale_source_with_caption_images", lambda *a, **k: (
        validation_calls.append(1) or {
            "passed": False,
            "reviewStatus": "incomplete",
            "rejectionReasons": ["two_scale_source_identity_failed", "two_scale_source_motion_not_verified"],
        }
    ))
    monkeypatch.setattr(bake, "repair_two_scale_source_disagreement", lambda *a, **k: {
        "valid": True,
        "resolved": False,
        "evidenceClaims": [{"id": "target_identity", "result": "refuted", "valid": True}],
        "evidenceOriginGroups": {"target_identity": ["two_scale_source_identity_failed"]},
    })

    with pytest.raises(bake.SourceCandidateRejected) as raised:
        preflight.review_prepared_source(candidate, request=request, selected_video=tmp_path / "source.mp4",
            contract=None, caption_images=lambda: "")

    assert raised.value.reason_tags == ["two_scale_source_identity_failed"]
    assert len(validation_calls) == 1


def test_preflight_keeps_bounded_retry_when_repair_remains_uncertain(tmp_path, monkeypatch):
    candidate = bake.RankedCandidate(0, 1, "curl", "Curl", "curl", {"videoId": "id", "title": "Curl"})
    request = SimpleNamespace(two_scale_source_validation=True, workspace=tmp_path)
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda path: SimpleNamespace(duration_seconds=5))
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **k: [])
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "validate_source_pose_endpoints_against_contract", lambda *a, **k: {})
    for name in ("small_motion", "completeness", "identity", "topology"):
        monkeypatch.setattr(bake, f"two_scale_{name}_failure_is_independent_outlier", lambda **k: False)
    monkeypatch.setattr(bake, "two_scale_source_validation_needs_repair", lambda validation: True)
    validation_calls = []
    monkeypatch.setattr(bake, "validate_two_scale_source_with_caption_images", lambda *a, **k: (
        validation_calls.append(1) or {
            "passed": False,
            "reviewStatus": "incomplete",
            "rejectionReasons": ["two_scale_source_target_blind_motion_observation_inconsistent"],
        }
    ))
    monkeypatch.setattr(bake, "repair_two_scale_source_disagreement", lambda *a, **k: {
        "valid": True,
        "resolved": False,
        "evidenceClaims": [{"id": "complete_action", "result": "uncertain", "valid": True}],
        "evidenceOriginGroups": {"complete_action": [
            "two_scale_source_target_blind_motion_observation_inconsistent"]},
    })

    with pytest.raises(preflight.SourceReviewIncomplete):
        preflight.review_prepared_source(candidate, request=request, selected_video=tmp_path / "source.mp4",
            contract=None, caption_images=lambda: "")

    assert len(validation_calls) == 2


def test_preflight_does_not_accept_generic_repair_without_dumbbell_pair_count(tmp_path, monkeypatch):
    contract = {
        "exerciseName": "Dumbbell Overhead Press",
        "motionContext": {
            "primaryEquipment": {"type": "DUMBBELLS", "name": "Dumbbell Pair"},
        },
    }
    candidate = bake.RankedCandidate(
        0, 1, "dumbbell-overhead-press", "Dumbbell Overhead Press", "dumbbell-overhead-press",
        {"videoId": "id", "title": "Dumbbell Overhead Press", "exerciseMotionContract": contract},
    )
    request = SimpleNamespace(two_scale_source_validation=True, workspace=tmp_path)
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda path: SimpleNamespace(duration_seconds=5))
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **k: [])
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "validate_source_pose_endpoints_against_contract", lambda *a, **k: {})
    for name in ("small_motion", "completeness", "identity", "topology"):
        monkeypatch.setattr(bake, f"two_scale_{name}_failure_is_independent_outlier", lambda **k: False)
    monkeypatch.setattr(bake, "two_scale_source_validation_needs_repair", lambda validation: True)
    validation_calls = []
    validation = {
        "passed": False,
        "reviewStatus": "incomplete",
        "rejectionReasons": [
            "two_scale_source_required_equipment_not_observed",
            "two_scale_source_required_equipment_count_unverified",
            "two_scale_source_evidence_consistency_incomplete",
        ],
        "missingEvidenceReasons": ["two_scale_source_required_equipment_count_unverified"],
        "exerciseMotionContract": contract,
        "gates": {"targetBlindEquipmentDetail": {"requiredEquipmentQuantityObserved": False}},
    }
    monkeypatch.setattr(bake, "validate_two_scale_source_with_caption_images", lambda *a, **k: (
        validation_calls.append(1) or json.loads(json.dumps(validation))
    ))
    repair_calls = []
    monkeypatch.setattr(bake, "repair_two_scale_source_disagreement", lambda *a, **k: (
        repair_calls.append(1) or {"valid": True, "resolved": True, "claims": ["required_equipment"]}
    ))
    cache_calls = []
    cache_repair = bake.cache_repaired_source_review

    def cache_repair_with_trace(current_validation, repair):
        cache_calls.append(current_validation)
        return cache_repair(current_validation, repair)

    monkeypatch.setattr(bake, "cache_repaired_source_review", cache_repair_with_trace)

    with pytest.raises(preflight.SourceReviewIncomplete):
        preflight.review_prepared_source(
            candidate, request=request, selected_video=tmp_path / "source.mp4",
            contract=contract, caption_images=lambda: "",
        )

    assert len(validation_calls) == len(repair_calls) == len(cache_calls) == 2
    assert all(result["passed"] is False for result in cache_calls)


@pytest.mark.parametrize("cache_only", [False, True])
def test_cli_cache_only_request_reaches_bake_and_staged_generation(tmp_path, cache_only):
    from exercise_motion_pkg.cli import build_parser, build_bake_and_rank_request

    args = build_parser().parse_args([
        "bake-and-rank", "--candidates-json", str(tmp_path / "candidates.json"),
        "--workspace", str(tmp_path), "--wham-repo-path", str(tmp_path / "wham"),
        "--body-model-root", str(tmp_path / "models"),
        *(["--require-wham-cache"] if cache_only else []),
    ])
    request = build_bake_and_rank_request(args)
    assert request.require_wham_cache is cache_only
    assert request.reuse_wham_cache is True
