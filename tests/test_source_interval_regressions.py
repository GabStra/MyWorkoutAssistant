import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.cleanup import cleanup_motion_clip
from exercise_motion_pkg.models import MotionClip, MotionFrame


@pytest.mark.parametrize(
    ("exercise_name", "root_delta", "expected_inconsistent"),
    [
        ("Pull-Up", (0.005214, 0.16653), {"rootVerticalPosition"}),
        ("Bench Press", (0.16653, 0.005214), {"rootHorizontalPosition"}),
        ("Barbell Bench Press", (0.0000446, 0.012021), set()),
    ],
)
def test_source_return_endpoint_consistency_checks_both_root_axes(
    exercise_name, root_delta, expected_inconsistent,
):
    endpoint_features = {
        "available": True,
        "exerciseName": exercise_name,
        "start": {
            "bodySpan": 1.0,
            "medianJointPositions": {"pelvis": [0.0, 0.0, 0.0]},
        },
        "end": {
            "bodySpan": 1.0,
            "medianJointPositions": {"pelvis": [root_delta[0], root_delta[1], 0.0]},
        },
    }

    result = bake.source_pose_return_endpoint_consistency(endpoint_features)
    root_comparisons = {
        row["field"]: row
        for row in result["comparisons"]
        if row["field"] in {"rootHorizontalPosition", "rootVerticalPosition"}
    }

    assert root_comparisons["rootHorizontalPosition"]["normalizedDelta"] == pytest.approx(
        abs(root_delta[0]), abs=5e-7
    )
    assert root_comparisons["rootVerticalPosition"]["normalizedDelta"] == pytest.approx(
        abs(root_delta[1])
    )
    assert {
        field for field, comparison in root_comparisons.items() if not comparison["passed"]
    } == expected_inconsistent
    assert result["passed"] is (not expected_inconsistent)


def _generated_pull_endpoint_features_with_vertical_return_mismatch():
    return {
        "available": True,
        "start": {
            "handHeight": "hip",
            "bodySpan": 0.452442,
            "medianJointPositions": {"pelvis": [0.7159953776, 0.4320285956, 0.0]},
        },
        "end": {
            "handHeight": "hip",
            "bodySpan": 0.46996,
            "medianJointPositions": {"pelvis": [0.7135905639, 0.508832, 0.0]},
        },
    }


def test_trusted_return_definition_keeps_root_mismatch_blocking_after_generated_pose_downgrade():
    contract = {
        "exerciseName": "Pull-Up",
        "status": "generated",
        "actionDefinitionAuthority": "structured_definition",
        "completionMode": "return_to_start",
        "primaryMovingRegions": ["arms"],
        "startPoseConstraints": {"handHeight": "above_head"},
    }

    result = bake.validate_source_pose_endpoints_against_contract(
        _generated_pull_endpoint_features_with_vertical_return_mismatch(),
        contract,
    )

    assert result["passed"] is False
    assert any(
        mismatch["field"] == "handHeight"
        and mismatch["endpoint"] == "start"
        for mismatch in result["generatedExpectationMismatches"]
    )
    geometry = next(
        mismatch for mismatch in result["blockingMismatches"]
        if mismatch["field"] == "returnEndpointConsistency"
    )
    assert geometry["requirementOrigin"] == "exercise_definition"
    assert geometry["definitionField"] == "completionMode"
    assert geometry["inconsistentFields"] == ["rootVerticalPosition"]


def test_generated_return_geometry_without_structured_authority_remains_advisory():
    contract = {
        "exerciseName": "Pull-Up",
        "status": "generated",
        "completionMode": "return_to_start",
        "primaryMovingRegions": ["arms"],
        "startPoseConstraints": {"handHeight": "above_head"},
    }

    result = bake.validate_source_pose_endpoints_against_contract(
        _generated_pull_endpoint_features_with_vertical_return_mismatch(),
        contract,
    )

    assert result["passed"] is True
    assert "rootVerticalPosition" in next(
        mismatch for mismatch in result["diagnosticOnlyMismatches"]
        if mismatch["field"] == "returnEndpointConsistency"
    )["inconsistentFields"]


@pytest.mark.parametrize("completion_mode", ["stable_hold", "return_to_start"])
def test_exact_source_phase_rejects_multiple_people_before_pose_extraction(
    tmp_path, monkeypatch, completion_mode,
):
    pose_payload = {
        "blockingIssues": ["multiple_people"],
        "maxSignificantPersonCount": 2,
    }
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda _: SimpleNamespace(duration_seconds=4.))
    monkeypatch.setattr(bake, "target_motion_contract_from_ranking_payload", lambda _: {
        "completionMode": completion_mode,
    })
    monkeypatch.setattr(bake, "run_yolo_pose_prefilter", lambda **_: SimpleNamespace(payload=pose_payload))
    monkeypatch.setattr(
        bake, "source_pose_skeleton_payload_for_window",
        lambda *args, **kwargs: pytest.fail("dominant pose extraction must not run"),
    )

    with pytest.raises(bake.SourceCandidateRejected) as error:
        bake.source_video_phase_completeness_metrics(
            source_video_path=tmp_path / "source.mp4",
            exercise_name="Bench Press",
            ranking_payload={"exerciseMotionContract": {"completionMode": completion_mode}},
        )

    assert "source_multiple_people_detected" in error.value.reason_tags
    assert error.value.evidence["posePrefilter"] is pose_payload


def test_exact_source_phase_keeps_single_person_phase_path(tmp_path, monkeypatch):
    pose_payload = {"blockingIssues": ["weak_body_joint_motion"], "maxSignificantPersonCount": 1}
    source_pose = {"frames": []}
    expected = {"passed": True, "reason": "single_person_phase_checked"}
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda _: SimpleNamespace(duration_seconds=4.))
    monkeypatch.setattr(bake, "target_motion_contract_from_ranking_payload", lambda _: {
        "completionMode": "return_to_start",
    })
    monkeypatch.setattr(bake, "run_yolo_pose_prefilter", lambda **_: SimpleNamespace(payload=pose_payload))
    monkeypatch.setattr(bake, "source_pose_skeleton_payload_for_window", lambda payload, **_: source_pose)
    monkeypatch.setattr(bake, "source_pose_phase_completeness_metrics", lambda **kwargs: expected)

    result = bake.source_video_phase_completeness_metrics(
        source_video_path=tmp_path / "source.mp4",
        exercise_name="Bench Press",
        ranking_payload={"exerciseMotionContract": {"completionMode": "return_to_start"}},
    )

    assert result is expected


def test_source_overview_preserves_dense_integrity_evidence(tmp_path, monkeypatch):
    samples = [tmp_path / f"frame_{index:03d}.jpg" for index in range(24)]
    candidate = bake.SourceCutCandidate(
        candidate_id="A", window=bake.DetectionWindow(index=0, start_seconds=2., end_seconds=7.),
        frame_paths=[tmp_path / f"sheet_{index}.jpg" for index in range(3)],
        sample_frame_paths=samples, visual_integrity={"passed": False},
    )
    captured = {}
    def build_sheet(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]
    monkeypatch.setattr(bake, "build_frame_contact_sheet", build_sheet)
    monkeypatch.setattr(bake, "persistent_border_crop", lambda paths: None)
    overview = bake.source_cut_review_overview(candidate, tmp_path)
    assert len(overview.frame_paths) == 1
    assert len(captured["frame_paths"]) == 8
    assert captured["frame_paths"][0] == samples[0]
    assert captured["frame_paths"][-1] == samples[-1]
    assert captured["timestamps"] == sorted(captured["timestamps"])
    assert overview.sample_frame_paths == samples
    assert overview.visual_integrity == {"passed": False}
    assert len(candidate.frame_paths) == 3


@pytest.mark.parametrize('sample_interval', [.1, 1.])
def test_complete_source_context_can_recover_outside_partial_discovery_hint(tmp_path, sample_interval):
    contract = {'completionMode': 'return_to_start', 'observableMotionSpec': {
        'primaryMovingRegions': ['hands'], 'referenceRegions': ['hips'],
        'primaryAxis': 'vertical', 'motionPattern': 'joint_flex_extend',
        'requiresReturnToStart': True, 'mustShowFullCycle': True,
        'oneWayPartialIsInvalid': True, 'mustBeVisibleRegions': ['hands', 'hips']}}
    samples = []
    for index in range(round(12/sample_interval)+1):
        time = index*sample_interval
        joints = {}
        for side, x in [('left', .4), ('right', .6)]:
            for name, y in [('shoulder', .3), ('hip', .55), ('knee', .75), ('ankle', .95),
                            ('elbow', .35), ('wrist', .3+.2*math.cos(time*math.pi/4))]:
                joints[f'{side}_{name}'] = [x, y, 1.]
        samples.append({'timeSeconds': time, 'keypoints': joints})
    candidate = bake.RankedCandidate(exercise_index=0, candidate_rank=0, exercise_id='movement',
        exercise_name='Unspecified exercise', exercise_slug='movement', candidate={
            'videoId': 'retained-source', 'durationSeconds': 12,
            'exerciseMotionContract': contract, 'visionPayload': {
                'bestChunkStartSeconds': 9., 'bestChunkEndSeconds': 11.5, 'bestChunkScore': .95,
                'posePrefilter': {'dominantPoseSamples': samples, 'sampleFps': 1/sample_interval}}})
    variants = bake.observed_complete_source_window_variants(candidate)
    if sample_interval > .5:
        assert not variants  # Sparse observations cannot establish a continuous rep.
    else:
        assert variants and variants[0].hint.start_seconds < 1.
        assert variants[0].hint.end_seconds > 7.
        request = bake.BakeAndRankRequest(candidates_json=tmp_path/'candidates.json',
            workspace=tmp_path/'workspace', body_model_root=None,
            segment_max_seconds=0.)
        assert bake.collect_source_window_variants(candidate, request=request)[0].source == 'observed_complete_source_cycle'


@pytest.fixture
def recorded_sources():
    return json.loads((Path(__file__).parent / "fixtures/source_interval_regressions.json").read_text(encoding="utf-8"))


def detect_instance(tmp_path, source):
    directory = tmp_path / "segment_detection"
    directory.mkdir(exist_ok=True)
    (directory / "exact_source_pose_reference.json").write_text(json.dumps({"pose": source["pose"]}), encoding="utf-8")
    return bake.exact_source_pose_first_movement_instance(
        candidate_workspace=tmp_path,
        completion_mode="return_to_start",
        exercise_motion_contract=source["contract"],
    )


@pytest.mark.parametrize("source", ["barbell-thruster", "barbell-bench-press"])
def test_cyclic_source_retains_endpoint_samples_for_3d_loop_selection(tmp_path, recorded_sources, source):
    result = detect_instance(tmp_path, recorded_sources[source])
    assert result["trimmed"] is False
    assert result["reason"] == "cyclic_boundaries_owned_by_observed_3d_cycle_selection"


def test_materialized_source_reference_is_not_cut_twice(recorded_sources):
    pose = recorded_sources["barbell-bench-press"]["pose"]
    ranking = bake.LoopRanking(0, [], payload={"preReconstructionSourceIntervalAuthority": {
        "movementInstance": {"trimmed": True, "endRatio": .52},
    }})
    once = bake.source_pose_reference_for_materialized_review(pose, ranking=ranking)
    twice = bake.source_pose_reference_for_materialized_review(once, ranking=ranking)
    assert len(once["frames"]) < len(pose["frames"])
    assert twice is once


def test_selected_video_uses_review_interval_not_cached_ratio(tmp_path):
    directory = tmp_path / "segment_detection"
    directory.mkdir()
    (directory / "exact_source_pose_reference.json").write_text(json.dumps({
        "pose": {"authoritativeMovementInstance": {"trimmed": True, "endRatio": .2}},
    }), encoding="utf-8")
    item = SimpleNamespace(candidate={}, candidate_workspace=tmp_path, loop_index=0,
                           loop_start_seconds=0., loop_end_seconds=1.6, duration_sec=1.6,
                           source_review_video_path=None, source_review_start_seconds=None,
                           source_review_end_seconds=None)
    window = bake.selected_source_section_window_for_review_item(item, source_duration_seconds=3.12)
    assert window.start_seconds == 0.
    assert window.end_seconds == 1.6


def test_validated_pre_reconstruction_interval_exports_full_source_while_unvalidated_item_keeps_crop(
    tmp_path, monkeypatch,
):
    workspace = tmp_path / "candidate"
    selected_segment = workspace / "input" / "selected_segment.mp4"
    selected_segment.parent.mkdir(parents=True)
    selected_segment.write_bytes(b"validated source bytes")
    trim_calls = []
    monkeypatch.setattr(bake, "source_video_duration_seconds", lambda _path: 2.9)

    def trim_video(**kwargs):
        trim_calls.append(kwargs)
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"cropped source bytes")
        return output_path

    monkeypatch.setattr(bake, "trim_video", trim_video)

    def item(authoritative):
        return bake.ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=0,
            exercise_name="Example",
            candidate_title="Example source",
            candidate_workspace=workspace,
            preview_html_path=workspace / "preview.html",
            skeleton_path=workspace / "skeleton.json",
            review_video_path=workspace / "preview.webm",
            duration_sec=2.733,
            loop_start_seconds=0.0,
            loop_end_seconds=2.733,
            candidate={
                "preReconstructionSourceIntervalAuthority": {"authoritative": authoritative},
            },
        )

    validated_payload = {
        "exerciseIndex": 0,
        "candidateRank": 0,
        "loopIndex": 0,
        "exerciseName": "Example",
        "candidateTitle": "Example source",
        "candidateWorkspace": str(workspace),
        "previewHtmlPath": str(workspace / "preview.html"),
        "skeletonPath": str(workspace / "skeleton.json"),
        "reviewVideoPath": str(workspace / "preview.webm"),
        "durationSec": 2.733,
        "loopStartSeconds": 0.0,
        "loopEndSeconds": 2.733,
        "candidate": {},
        "ranking": {
            "score": 1.0,
            "reasons": [],
            "payload": {
                "sectionSelectionPolicy": "validated_pre_reconstruction_source_interval",
                "preReconstructionSourceIntervalAuthority": {"authoritative": True},
            },
        },
    }
    validated_item = bake.review_item_from_manifest(validated_payload)
    assert bake.source_selection_clearance_for_review_item(
        validated_item, required=True,
    )["status"] == "needs_source_review"
    validated_manifest = bake.review_item_to_manifest(validated_item)
    assert Path(validated_manifest["selectedInputVideoPath"]) == selected_segment
    assert validated_manifest["selectedInputSourceWindow"]["endSeconds"] == pytest.approx(2.9)
    assert not trim_calls
    selection = bake.movement_instance_selection_payload(
        validated_item,
        bake.ranking_from_manifest(validated_payload["ranking"]),
    )
    assert selection["endSeconds"] == pytest.approx(2.9)

    unvalidated_manifest = bake.review_item_to_manifest(item(False))
    assert Path(unvalidated_manifest["selectedInputVideoPath"]).name == (
        "selected_source_section_000000_002733.mp4"
    )
    assert unvalidated_manifest["selectedInputSourceWindow"]["endSeconds"] == pytest.approx(2.733)
    assert len(trim_calls) == 1


def test_source_reviewed_cleanup_preserves_stationary_endpoint_frames(recorded_sources):
    pose = recorded_sources["barbell-bench-press"]["pose"]
    joints = pose["frames"][0]["joints"]
    frames = [MotionFrame(index / 30, {name: tuple(point) for name, point in joints.items()}) for index in range(30)]
    for index in range(10, 20):
        frames[index].joints.update({name: (point[0] + 0.1, point[1], point[2]) for name, point in frames[index].joints.items()})
    clip = MotionClip(30, list(joints), frames)
    cleaned, stats = cleanup_motion_clip(clip, preserve_temporal_extent=True, support_mode_hint="lying")
    assert len(cleaned.frames) == len(frames)
    assert [frame.time_sec for frame in cleaned.frames] == [frame.time_sec for frame in frames]
    assert stats.trimmed_start_frames == stats.trimmed_end_frames == 0


@pytest.mark.parametrize('duration', [7.66, 9.01, 30.])
def test_source_overview_sampling_meets_timing_gate_without_inventing_dense_samples(tmp_path, duration):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from exercise_motion_pkg.source_evidence import MAX_TIMING_EVIDENCE_SAMPLE_GAP_SECONDS, temporal_observation_bins
    samples = []
    for index in range(24):
        path = tmp_path / f'frame_{index:02d}.jpg'
        assert cv2.imwrite(str(path), np.full((80, 120, 3), index * 8, dtype=np.uint8))
        samples.append(path)
    candidate = bake.SourceCutCandidate('A', bake.DetectionWindow(0, 0., duration),
        [tmp_path / 'old1.jpg', tmp_path / 'old2.jpg', tmp_path / 'old3.jpg'],
        sample_frame_paths=samples)
    reviewed = bake.source_cut_review_overview(candidate, tmp_path)
    inventory = bake.source_cut_candidate_evidence_inventory(reviewed)
    original_times = bake.source_cut_sample_timestamps(candidate_window=candidate.window, sample_count=24)
    assert all(frame['timestampSeconds'] in original_times for frame in inventory)
    assert len({frame['id'] for frame in inventory}) == len(inventory)
    assert len({frame['timestampSeconds'] for frame in inventory}) == len(inventory)
    assert reviewed.sample_frame_paths == samples
    assert len(inventory) > 8
    prompt = bake.source_cut_candidate_timing_prompt(reviewed)
    for frame in inventory:
        assert json.dumps({'id': frame['id'], 'tileNumber': frame['tileNumber'],
            'sheet': frame['image'], 'timestampSeconds': frame['timestampSeconds']}, separators=(',', ':')) in prompt
    assert max(sum(frame['image'] == image for frame in inventory) for image in {frame['image'] for frame in inventory}) <= 8
    observations = [{'phaseId': 'lower', 'visible': True, 'evidenceFrameIds': [frame['id'] for frame in inventory[:2]]},
                    {'phaseId': 'return', 'visible': True, 'evidenceFrameIds': [frame['id'] for frame in inventory[-2:]]}]
    timing = temporal_observation_bins(observations, ['lower', 'return'], inventory,
        id_field='phaseId', require_visible=True)
    assert (timing['status'] == 'sampled') is (duration <= 9.01)
    if duration > 9.01:
        assert timing['reason'] == 'sample_gap_too_large_for_timing'
    else:
        assert timing['maximumAdjacentSampleGapSeconds'] <= MAX_TIMING_EVIDENCE_SAMPLE_GAP_SECONDS
        # Dense evidence cannot turn a missing return observation into a complete action.
        partial = temporal_observation_bins(observations[:1], ['lower', 'return'], inventory,
            id_field='phaseId', require_visible=True)
        assert partial['status'] == 'unresolved'


def test_promoted_shared_source_receipt_is_consumable_and_hash_bound(tmp_path, recorded_sources):
    import hashlib
    import cv2
    import numpy as np

    from exercise_motion_pkg import wave_pipeline as wave

    def write_video(path, color):
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 64),
        )
        assert writer.isOpened()
        for _ in range(96):
            writer.write(np.full((64, 64, 3), color, dtype=np.uint8))
        writer.release()

    shared_root = tmp_path / "shared-source-cache"
    candidate_workspace = tmp_path / "candidate"
    selected_video = candidate_workspace / "input" / "selected_segment.mp4"
    selected_video.parent.mkdir(parents=True)
    write_video(selected_video, 70)
    source_sha256 = hashlib.sha256(selected_video.read_bytes()).hexdigest()

    shared_entry = shared_root / "placeholder"
    shared_entry.mkdir(parents=True)
    shared_reference = shared_entry / "exact_source_pose_reference.json"
    shared_reference.write_text(json.dumps({
        "sourceVideoSha256": source_sha256,
        "pose": recorded_sources["barbell-bench-press"]["pose"],
    }), encoding="utf-8")

    exercise_name = "Barbell Bench Press"
    contract = None
    cache_payload, cache_key = bake.exact_source_phase_validation_cache_key(
        source_video_path=selected_video,
        exercise_name=exercise_name,
        exercise_motion_contract=contract,
    )
    cache_entry = shared_root / cache_key
    cache_entry.mkdir()
    shared_cache_receipt = cache_entry / "exact_source_phase_validation.json"
    validation = {
        "required": True,
        "passed": True,
        "reason": "validated",
        "requiredRegionObservations": {"passed": True},
        "sourceVideoPath": str(selected_video.resolve()),
        "sourceVideoSha256": source_sha256,
        "sourcePoseReferencePath": str(shared_reference.resolve()),
    }
    bake.write_exact_source_phase_validation_cache(
        cache_path=shared_cache_receipt,
        cache_key=cache_key,
        metrics=validation,
    )
    shared_receipt_before = shared_cache_receipt.read_bytes()
    shared_reference_before = shared_reference.read_bytes()
    loaded_validation = bake.load_cached_exact_source_phase_validation(
        cache_path=shared_cache_receipt,
        cache_key=cache_key,
        source_video_path=selected_video,
    )
    assert loaded_validation is not None

    promoted = bake.promote_and_require_exact_source_phase_validation(
        candidate_workspace=candidate_workspace,
        exercise_name=exercise_name,
        validation=loaded_validation,
        exercise_motion_contract=contract,
        rejection_context="test source receipt promotion",
    )
    canonical_receipt = (
        candidate_workspace / "segment_detection" / "exact_source_phase_validation.json"
    )
    support_evidence = {"sourceVideoSha256": source_sha256, "review": "retained"}
    assert promoted["sourceVideoSha256"] == source_sha256
    assert canonical_receipt.is_file()
    assert wave._persist_exact_source_support_evidence(
        candidate_workspace, source_sha256, support_evidence,
    )

    canonical_metrics = json.loads(canonical_receipt.read_text(encoding="utf-8"))["metrics"]
    inline_metrics = json.loads(
        (candidate_workspace / "segment_detection" / "segment_selection.json").read_text(
            encoding="utf-8"
        )
    )["exactSourcePhaseValidation"]
    assert canonical_metrics["sourceFootSupportEvidence"] == support_evidence
    assert inline_metrics["sourceFootSupportEvidence"] == support_evidence
    assert shared_cache_receipt.read_bytes() == shared_receipt_before
    assert shared_reference.read_bytes() == shared_reference_before

    mismatched_workspace = tmp_path / "mismatched-candidate"
    mismatched_video = mismatched_workspace / "input" / "selected_segment.mp4"
    mismatched_video.parent.mkdir(parents=True)
    write_video(mismatched_video, 150)
    bake.promote_and_require_exact_source_phase_validation(
        candidate_workspace=mismatched_workspace,
        exercise_name=exercise_name,
        validation=loaded_validation,
        exercise_motion_contract=contract,
        rejection_context="test mismatched source receipt promotion",
    )
    assert not (
        mismatched_workspace / "segment_detection" / "exact_source_phase_validation.json"
    ).exists()
    mismatched_sha256 = hashlib.sha256(mismatched_video.read_bytes()).hexdigest()
    assert not wave._persist_exact_source_support_evidence(
        mismatched_workspace,
        mismatched_sha256,
        {"sourceVideoSha256": mismatched_sha256},
    )
    assert shared_cache_receipt.read_bytes() == shared_receipt_before
    assert shared_reference.read_bytes() == shared_reference_before
