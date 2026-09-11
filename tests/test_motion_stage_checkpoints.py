from dataclasses import fields, replace
import json
from pathlib import Path

import pytest

from exercise_motion_pkg import pipeline
from exercise_motion_pkg import stage_cache
from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave
from exercise_motion_pkg.cleanup import CleanupStats


def test_stage_rejects_modified_or_missing_outputs(tmp_path):
    output = tmp_path / "result.json"
    output.write_text("first")
    checkpoint = tmp_path / "checkpoint.json"
    stage_cache.save_stage(checkpoint, "key", {"value": 1}, [output])
    assert stage_cache.load_stage(checkpoint, "key") == {"value": 1}
    assert stage_cache.load_stage(checkpoint, "other") is None
    output.write_text("other")
    assert stage_cache.load_stage(checkpoint, "key") is None
    output.unlink()
    assert stage_cache.load_stage(checkpoint, "key") is None


def test_processed_motion_reuse_skips_gpu_but_rechecks_current_raw_gate(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    request = pipeline.GenerateRequest("exercise", tmp_path, video_path=source)
    calls = []
    def generate(request, **kwargs):
        calls.append("generate")
        values = {}
        for field in fields(pipeline.GenerateResult):
            if "Path" in str(field.type):
                path = tmp_path / (field.name + ".json")
                path.write_text("{}")
                values[field.name] = path
        values.update(cleanup_stats=CleanupStats(10, 10, 0, 0, 1, 1), motion_tuning_enabled=True)
        return pipeline.GenerateResult(**values)
    monkeypatch.setattr(pipeline, "_run_generation_pipeline_uncached", generate)
    def exclusive(operation):
        calls.append("gpu")
        return operation()
    pipeline.run_generation_pipeline(request, run_processing_exclusive=exclusive)
    second = pipeline.run_generation_pipeline(replace(request, require_wham_cache=True, wham_tracking_preflight=True),
        run_processing_exclusive=exclusive, raw_motion_validator=lambda path: calls.append("gate"))
    assert calls == ["gpu", "generate", "gate"]
    assert second.wham_cache_status == "reused_processed"
    assert isinstance(second.cleaned_motion_json_path, Path)
    second.cleaned_motion_json_path.write_text("changed")
    pipeline.run_generation_pipeline(request, run_processing_exclusive=exclusive)
    assert calls[-2:] == ["gpu", "generate"]
    source.write_bytes(b"new video")
    pipeline.run_generation_pipeline(request)
    assert calls[-1] == "generate"


@pytest.mark.parametrize("state,expected", [
    ({"status": "completed"}, "export_selected"),
    ({"finalValidation": {"status": "no_selection", "candidateDiagnostics": [{"status": "ready_for_selection"}]}}, "next_source"),
    ({"finalValidation": {"status": "no_selection", "candidateDiagnostics": [{"status": "failed"}]}}, "retry_infrastructure"),
    ({"wham": {"attempts": [{"status": "rejected_raw_wham_validation"}]}}, "next_source"),
    ({"source": {"failureReason": "source_turn_deferred"}}, "next_source"),
    ({"finalValidation": {"status": "failed"}}, "retry_infrastructure"),
])
def test_retry_disposition_preserves_failure_owner(state, expected):
    assert wave.wave_retry_disposition(state) == expected


def test_rigid_metadata_repair_preserves_actual_renderer_options(tmp_path):
    skeleton = tmp_path / "skeleton.json"
    skeleton.write_text(json.dumps({
        "sourceContactSequenceCorrection": {"posePreservation": "per_frame_rigid_translation"},
        "selectedPreviewSettings": {"lockPlantedFeet": False, "lockPlantedHands": False},
        "bakedPreviewConfiguration": {"lockPlantedFeet": False, "lockPlantedHands": False}}))
    item = bake.review_item_from_manifest({"selectedWearSkeletonPath": str(skeleton),
        "settingsVariantId": "adaptive-contact-sequence-correction",
        "settingsOptions": {"lockPlantedFeet": True, "contactSequenceCorrection": True}})
    assert item.settings_options["lockPlantedFeet"] is False
    assert item.settings_options["contactSequenceCorrection"] is True
    assert json.loads(skeleton.read_text())["selectedPreviewSettings"]["lockPlantedFeet"] is False


def test_review_cache_changes_with_model(tmp_path):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")
    kwargs = {"prompt": "review", "frame_paths": [image], "min_score": .5}
    assert bake.final_output_validation_cache_key(**kwargs, model_settings={"model": "A"}) != bake.final_output_validation_cache_key(**kwargs, model_settings={"model": "B"})


def test_early_raw_gate_stops_before_preview_and_cleanup(tmp_path, monkeypatch):
    from test_exercise_motion_pkg import build_fixture_clip
    from exercise_motion_pkg.motion_io import save_motion_json
    motion = tmp_path / "source.json"
    video = tmp_path / "source.mp4"
    save_motion_json(motion, build_fixture_clip())
    video.write_bytes(b"video")
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected raw motion must not enter preview or cleanup")
    monkeypatch.setattr(pipeline, "write_preview_html", forbidden)
    monkeypatch.setattr(pipeline, "cleanup_motion_clip", forbidden)
    def reject(path):
        assert path.exists()
        raise bake.RawMotionRejected({"passed": False, "rejectionReasons": ["test_irreparable"]})
    with pytest.raises(bake.RawMotionRejected):
        pipeline.run_generation_pipeline(pipeline.GenerateRequest("exercise", tmp_path / "work",
            video_path=video, normalized_motion_json=motion, spinepose_enabled=False), raw_motion_validator=reject)


def test_bake_checkpoint_restores_payload_and_video_without_browser(tmp_path, monkeypatch):
    preview = tmp_path / "preview.html"
    preview.write_text("preview")
    skeleton = tmp_path / "skeleton.json"
    video = tmp_path / "review.webm"
    calls = []
    def generate(*args, **kwargs):
        calls.append("browser")
        skeleton.write_text('{"frames": []}')
        video.write_bytes(b"video")
        return [bake.BakedLoopArtifact(0, skeleton, video, {"frames": []})]
    monkeypatch.setattr(bake, "_bake_preview_loops_with_playwright_uncached", generate)
    args = (preview, [bake.EligibleLoop(0, {}, 1, 0, 1)], tmp_path, 6)
    bake.bake_preview_loops_with_playwright(*args)
    skeleton.write_text("downstream gate annotations")
    video.unlink()
    result = bake.bake_preview_loops_with_playwright(*args)
    assert calls == ["browser"]
    assert json.loads(skeleton.read_text()) == {"frames": []}
    assert video.read_bytes() == b"video"
    assert result[0].export_payload == {"frames": []}
    preview.write_text("changed preview")
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 2


def test_cached_review_frames_regenerate_when_image_missing(tmp_path):
    image = tmp_path / "image.jpg"
    calls = []
    def render():
        calls.append(1)
        image.write_bytes(b"image")
        return [image]
    checkpoint = tmp_path / "checkpoint.json"
    stage_cache.cached_paths(checkpoint, "key", render)
    stage_cache.cached_paths(checkpoint, "key", render)
    assert len(calls) == 1
    image.unlink()
    stage_cache.cached_paths(checkpoint, "key", render)
    assert len(calls) == 2


def test_failed_artifact_retention_keeps_checkpoint_inputs(tmp_path):
    raw = tmp_path / "candidate" / "raw" / "motion.raw.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}")
    disposable = tmp_path / "other" / "raw" / "unused.json"
    disposable.parent.mkdir(parents=True)
    disposable.write_text("{}")
    stage_cache.save_stage(tmp_path / "candidate" / "generation_checkpoint.json", "key", {}, [raw])
    bake.apply_artifact_retention_policy(tmp_path, {"selected": None, "candidateResults": []})
    assert raw.exists()
    assert not disposable.exists()


@pytest.mark.parametrize("contents", ["[]", "not json", '{"key": "key", "outputs": [1], "payload": {}}'])
def test_malformed_checkpoint_is_a_cache_miss(tmp_path, contents):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(contents)
    assert stage_cache.load_stage(checkpoint, "key") is None
