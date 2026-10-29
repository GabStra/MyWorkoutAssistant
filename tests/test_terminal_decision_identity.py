import hashlib
import json
from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256


def test_terminal_decision_identity_binds_source_bytes_and_policy_content(tmp_path, monkeypatch):
    package = tmp_path / "package"
    package.mkdir()
    owner = package / "bake_and_rank.py"
    owner.write_text("bake policy v1", encoding="utf-8")
    seam = package / "loop_seam.py"
    seam.write_text("seam policy v1", encoding="utf-8")
    monkeypatch.setattr(bake, "__file__", str(owner))

    workspace = tmp_path / "workspace"
    candidate_workspace = workspace / "bench-press-001-retained-source"
    selected = candidate_workspace / "input" / "selected_segment.mp4"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"selected video bytes v1")
    model = tmp_path / "llama-model.gguf"
    model.write_bytes(b"m" * (1024 * 1024))
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=workspace,
        body_model_root=None,
        llama_cpp_model=str(model),
    )
    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id="bench-press",
        exercise_name="Bench Press",
        exercise_slug="bench-press",
        candidate={"videoId": "retained-source", "sourceWindowAttemptIndex": 0},
    )

    model_cache_hits_before = bake._cached_terminal_media_sha256.cache_info().hits
    initial = bake.candidate_decision_identity(candidate, request, selected)
    assert initial
    assert bake.candidate_decision_identity(candidate, request, selected) == initial
    assert bake._cached_terminal_media_sha256.cache_info().hits > model_cache_hits_before

    # Code content, not mtimes, owns policy freshness.
    seam.write_text("seam policy v2", encoding="utf-8")
    policy_changed = bake.candidate_decision_identity(candidate, request, selected)
    assert policy_changed != initial
    seam.write_text("seam policy v1", encoding="utf-8")

    selected.write_bytes(b"selected video bytes v2")
    source_changed = bake.candidate_decision_identity(candidate, request, selected)
    assert source_changed != initial


def test_terminal_cache_treats_legacy_decision_without_identity_as_miss(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = workspace / "selection_manifest.json"
    manifest.write_text(
        json.dumps({"candidateResults": [{
            "exerciseIndex": 0,
            "candidateRank": 0,
            "candidate": {"videoId": "same-url"},
            "status": "ready_for_selection",
            "finalSelectionStatus": "rejected_after_materialized_review",
        }]}),
        encoding="utf-8",
    )
    assert bake.load_previous_terminal_candidate_results(workspace) == {}


def test_terminal_json_evidence_ignores_run_bookkeeping_but_keeps_source_times(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({
        "waveId": "wave-a",
        "updatedAt": "2026-10-27T08:00:00Z",
        "timings": {"reviewSeconds": 2.1},
        "frames": [{"sourceTimeSec": 1.0, "ankle": [0.1, 0.2]}],
    }), encoding="utf-8")
    initial = bake._terminal_decision_json_identity(evidence)
    evidence.write_text(json.dumps({
        "waveId": "wave-b",
        "updatedAt": "2026-10-27T09:00:00Z",
        "timings": {"reviewSeconds": 3.1},
        "frames": [{"sourceTimeSec": 1.0, "ankle": [0.1, 0.2]}],
    }), encoding="utf-8")
    assert bake._terminal_decision_json_identity(evidence) == initial
    evidence.write_text(json.dumps({
        "waveId": "wave-b",
        "updatedAt": "2026-10-27T09:00:00Z",
        "timings": {"reviewSeconds": 3.1},
        "frames": [{"sourceTimeSec": 1.1, "ankle": [0.1, 0.2]}],
    }), encoding="utf-8")
    assert bake._terminal_decision_json_identity(evidence) != initial


def test_source_pose_cut_clock_mapping_requires_matching_receipts(tmp_path):
    workspace = tmp_path / "candidate"
    selection_dir = workspace / "segment_detection"
    selection_dir.mkdir(parents=True)
    selected_path = workspace / "input" / "selected_segment.mp4"
    selected_path.parent.mkdir(parents=True)
    selected_path.write_bytes(b"selected cut")
    parent_path = tmp_path / "source.mp4"
    parent_path.write_bytes(b"parent source")
    clock_output = workspace / "input" / "reconstruction.mp4"
    clock_receipt_path = bake.source_frame_clock_path_for_video(clock_output)
    clock_receipt_path.write_text("verified parent clock receipt", encoding="utf-8")
    selection = {
        "selectedSegmentPath": str(selected_path.resolve()),
        "selectedSegmentSha256": hashlib.sha256(selected_path.read_bytes()).hexdigest(),
        "sourceVideoPath": str(parent_path.resolve()),
        "selectedSpanInOriginalSource": {"startSeconds": 2.0, "endSeconds": 5.1},
    }
    (selection_dir / "segment_selection.json").write_text(json.dumps(selection), encoding="utf-8")
    source_pose = {
        "sourceTimeOriginSec": 0.0,
        "frames": [
            {"sourceTimeSec": 0.0, "joints": {"ankle": [0.1, 0.2]}},
            {"sourceTimeSec": 1.0, "joints": {"ankle": [0.2, 0.3]}},
        ],
    }
    reference = {
        "sourceVideoSha256": hashlib.sha256(selected_path.read_bytes()).hexdigest(),
        "pose": source_pose,
    }
    (selection_dir / "exact_source_pose_reference.json").write_text(json.dumps(reference), encoding="utf-8")
    receipt = {
        "sourceVideoPath": str(parent_path.resolve()),
        "sourceVideoSha256": hashlib.sha256(parent_path.read_bytes()).hexdigest(),
        "outputVideoPath": str(clock_output.resolve()),
    }

    mapping = bake.verified_source_timeline_mapping(
        workspace=workspace, source_pose=source_pose, clock_receipt=receipt,
    )

    assert mapping is not None
    assert mapping["verified"] is True
    assert mapping["mappingKind"] == "selected_segment_to_parent_source"
    assert mapping["selectedStartSeconds"] == 2.0
    assert mapping["parentSourceSha256"] == receipt["sourceVideoSha256"]
    assert mapping["selectedSegmentSha256"] == selection["selectedSegmentSha256"]
    assert mapping["sourcePosePayloadSha256"] == _canonical_source_pose_sha256(source_pose)

    wrong_receipt = {**receipt, "sourceVideoSha256": "0" * 64}
    assert bake.verified_source_timeline_mapping(
        workspace=workspace, source_pose=source_pose, clock_receipt=wrong_receipt,
    ) is None
