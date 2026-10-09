from dataclasses import fields, replace
from contextvars import ContextVar
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

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
    second = pipeline.run_generation_pipeline(
        replace(request, require_reconstruction_cache=True),
        run_processing_exclusive=exclusive,
        raw_motion_validator=lambda path: calls.append("gate"),
    )
    assert calls == ["gpu", "generate", "gate"]
    assert second.reconstruction_cache_status == "reused_processed"
    assert isinstance(second.cleaned_motion_json_path, Path)
    second.cleaned_motion_json_path.write_text("changed")
    pipeline.run_generation_pipeline(request, run_processing_exclusive=exclusive)
    assert calls[-2:] == ["gpu", "generate"]
    source.write_bytes(b"new video")
    pipeline.run_generation_pipeline(request)
    assert calls[-1] == "generate"


def test_generation_checkpoint_and_reconstruction_cache_track_gvhmr_runtime_code(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    dependency = tmp_path / "gvhmr_inference.py"
    dependency.write_text("bridge version one")
    monkeypatch.setattr(pipeline, "gvhmr_runtime_dependency_paths", lambda: (dependency,))
    monkeypatch.setattr(pipeline, "gvhmr_source_tree_identity", lambda: "source-revision")
    request = pipeline.GenerateRequest(
        "exercise",
        tmp_path / "work",
        video_path=source,
        motion_reconstruction_backend="gvhmr",
    )
    calls = []

    def generate(_request, **_kwargs):
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
    pipeline.run_generation_pipeline(request)
    first_gvhmr_cache_key = pipeline.reconstruction_content_cache_key(request, source)
    dependency.write_text("bridge version two")
    pipeline.run_generation_pipeline(request)

    assert calls == ["generate", "generate"]
    assert pipeline.reconstruction_content_cache_key(request, source) != first_gvhmr_cache_key

    dependency.write_text("bridge version three")
    assert pipeline.reconstruction_content_cache_key(request, source) != first_gvhmr_cache_key


def test_generation_checkpoint_tracks_neutral_body_model_bytes(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    body_model_root = tmp_path / "body-models"
    body_model_root.mkdir()
    neutral_model = body_model_root / "SMPL_NEUTRAL.pkl"
    neutral_model.write_bytes(b"neutral weights A")
    request = pipeline.GenerateRequest(
        "exercise", tmp_path / "work", video_path=source,
        body_model_root=body_model_root,
    )
    calls = []

    def generate(_request, **_kwargs):
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
    pipeline.run_generation_pipeline(request)
    original_stat = neutral_model.stat()
    neutral_model.write_bytes(b"neutral weights B")
    os.utime(neutral_model, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert neutral_model.stat().st_size == original_stat.st_size
    assert neutral_model.stat().st_mtime_ns == original_stat.st_mtime_ns

    pipeline.run_generation_pipeline(request)

    assert calls == ["generate", "generate"]


def test_gvhmr_runtime_dependencies_include_the_container_worker_entrypoint():
    expected = Path(pipeline.__file__).resolve().with_name("gvhmr_warm_worker.py")
    assert expected in pipeline.gvhmr_runtime_dependency_paths()


def test_gvhmr_identity_hashes_dirty_source_bytes_without_lru_staleness(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    pipeline_file = repository / "exercise_motion_pkg" / "pipeline.py"
    pipeline_file.parent.mkdir(parents=True)
    pipeline_file.touch()
    runtime_source = repository / "third_party" / "GVHMR" / "hmr4d" / "configs" / "runtime.py"
    runtime_source.parent.mkdir(parents=True)
    runtime_source.write_text("VERSION = 'one'\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "__file__", str(pipeline_file))

    first_identity = pipeline.gvhmr_source_tree_identity()
    original_stat = runtime_source.stat()
    runtime_source.write_text("VERSION = 'two'\n", encoding="utf-8")
    os.utime(runtime_source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    assert runtime_source.stat().st_size == original_stat.st_size
    assert runtime_source.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert pipeline.gvhmr_source_tree_identity() != first_identity


def test_reconstruction_cache_key_tracks_resolved_docker_image_id_and_fails_closed(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    request = pipeline.GenerateRequest(
        "exercise", tmp_path / "work", video_path=source,
        use_reconstruction_docker=True, reconstruction_docker_image="reconstruction:test",
    )
    monkeypatch.setattr(pipeline, "docker_image_identity", lambda _image: "sha256:" + "a" * 64)
    first_key = pipeline.reconstruction_content_cache_key(request, source)
    monkeypatch.setattr(pipeline, "docker_image_identity", lambda _image: "sha256:" + "b" * 64)
    assert pipeline.reconstruction_content_cache_key(request, source) != first_key

    monkeypatch.setattr(pipeline, "docker_image_identity", lambda _image: None)
    unresolved_identity = pipeline.reconstruction_runtime_identity(request)
    assert unresolved_identity["cacheable"] is False
    old_global_cache = pipeline.global_reconstruction_results_pkl(
        request, source, runtime_identity=unresolved_identity,
    )
    old_global_cache.parent.mkdir(parents=True)
    old_global_cache.write_bytes(b"stale result")
    assert pipeline.reusable_reconstruction_results_pkl(
        replace(request, reuse_reconstruction_cache=True), source,
        runtime_identity=unresolved_identity,
    ) is None


def test_gvhmr_cache_fails_closed_when_source_identity_is_unavailable(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    request = pipeline.GenerateRequest(
        "exercise", tmp_path / "work", video_path=source,
        motion_reconstruction_backend="gvhmr",
    )
    monkeypatch.setattr(pipeline, "gvhmr_source_tree_identity", lambda: "unavailable")

    first_identity = pipeline.reconstruction_runtime_identity(request)
    second_identity = pipeline.reconstruction_runtime_identity(request)

    assert first_identity["cacheable"] is False
    assert second_identity["cacheable"] is False
    assert first_identity["unresolvedIdentityNonce"] != second_identity["unresolvedIdentityNonce"]
    assert pipeline.reconstruction_content_cache_key(
        request, source, runtime_identity=first_identity,
    ) != pipeline.reconstruction_content_cache_key(
        request, source, runtime_identity=second_identity,
    )


@pytest.mark.parametrize("state,expected", [
    ({"status": "completed"}, "export_selected"),
    ({"finalValidation": {"status": "no_selection", "candidateDiagnostics": [{"status": "ready_for_selection"}]}}, "next_source"),
    ({"finalValidation": {"status": "no_selection", "candidateDiagnostics": [{"status": "failed"}]}}, "retry_infrastructure"),
    ({"reconstruction": {"attempts": [{"status": "rejected_raw_reconstruction_validation"}]}}, "next_source"),
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


def test_vlm_model_identity_detects_atomic_same_size_replacement_with_restored_mtime(tmp_path):
    model_path = tmp_path / "vision.gguf"
    replacement_path = tmp_path / "replacement.gguf"
    stable_mtime_ns = 1_700_000_000_000_000_000
    model_path.write_bytes(b"model-version-one")
    os.utime(model_path, ns=(stable_mtime_ns, stable_mtime_ns))
    first = bake.vlm_model_file_identity(model_path)

    replacement_path.write_bytes(b"model-version-two")
    os.utime(replacement_path, ns=(stable_mtime_ns, stable_mtime_ns))
    os.replace(replacement_path, model_path)
    os.utime(model_path, ns=(stable_mtime_ns, stable_mtime_ns))
    second = bake.vlm_model_file_identity(model_path)

    assert first["sizeBytes"] == second["sizeBytes"]
    assert first["mtimeNs"] == second["mtimeNs"]
    assert first["fileId"] != second["fileId"]
    assert first["sha256"] != second["sha256"]
    assert bake.vlm_model_file_identity(model_path) == second


def test_vlm_cache_identities_include_file_backed_server_executable(tmp_path):
    model_path = tmp_path / "vision.gguf"
    mmproj_path = tmp_path / "vision-mmproj.gguf"
    server_path = tmp_path / "llama-server.exe"
    frame_path = tmp_path / "frame.jpg"
    model_path.write_bytes(b"model")
    mmproj_path.write_bytes(b"projector")
    server_path.write_bytes(b"server-one")
    frame_path.write_bytes(b"frame")
    stable_mtime_ns = 1_700_000_000_000_000_000
    os.utime(server_path, ns=(stable_mtime_ns, stable_mtime_ns))
    settings = {
        "llama_cpp_model": str(model_path),
        "llama_cpp_mmproj": str(mmproj_path),
        "llama_cpp_server_command": str(server_path),
        "llama_cpp_base_url": "http://127.0.0.1:8080",
        "llama_cpp_temperature": 0,
    }

    first_identity = bake.vlm_settings_with_file_identities(settings)
    assert first_identity["llama_cpp_server_command"] == bake.vlm_model_file_identity(server_path)
    assert bake.source_review_model_identity(SimpleNamespace(**settings)) == first_identity
    kwargs = {"prompt": "review", "frame_paths": [frame_path], "min_score": .5}
    first_validation_key = bake.final_output_validation_cache_key(**kwargs, model_settings=settings)
    session = object.__new__(bake.LazyLlamaCppVisionSession)
    session.settings = SimpleNamespace(**settings)
    session._condition = threading.Condition()
    session._closed = False
    session._candidate_deadlines = ContextVar("candidate_deadline", default=None)
    session._endpoint_observations = bake.ObservationCache()
    observations = []
    session.caption_images = lambda **_kwargs: observations.append("computed") or json.dumps({
        "supportMode": "standing",
        "kneeState": "extended",
        "torsoOrientation": "upright",
        "handHeight": "hip",
        "stance": "neutral",
    })
    endpoint_kwargs = {"frame_paths": [frame_path], "prompt": "endpoint", "temperature": 0}
    session.caption_endpoint_images(**endpoint_kwargs)
    session.caption_endpoint_images(**endpoint_kwargs)
    assert observations == ["computed"]

    replacement_path = tmp_path / "llama-server-replacement.exe"
    replacement_path.write_bytes(b"server-two")
    os.utime(replacement_path, ns=(stable_mtime_ns, stable_mtime_ns))
    os.replace(replacement_path, server_path)
    os.utime(server_path, ns=(stable_mtime_ns, stable_mtime_ns))
    second_identity = bake.vlm_settings_with_file_identities(settings)
    second_validation_key = bake.final_output_validation_cache_key(**kwargs, model_settings=settings)
    session.caption_endpoint_images(**endpoint_kwargs)

    first_server = first_identity["llama_cpp_server_command"]
    second_server = second_identity["llama_cpp_server_command"]
    assert first_server["sizeBytes"] == second_server["sizeBytes"]
    assert first_server["mtimeNs"] == second_server["mtimeNs"]
    assert first_server["sha256"] != second_server["sha256"]
    assert bake.source_review_model_identity(SimpleNamespace(**settings)) == second_identity
    assert first_validation_key != second_validation_key
    assert observations == ["computed", "computed"]


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
        from exercise_motion_pkg.fit_runtime import current_fit_session
        assert current_fit_session() is not None
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
    restored_payload = json.loads(skeleton.read_text())
    assert restored_payload["frames"] == []
    assert restored_payload["artifactState"]["artifactClass"] == "full_clip_bake"
    assert video.read_bytes() == b"video"
    assert result[0].export_payload["frames"] == []
    assert result[0].export_payload["artifactState"]["artifactClass"] == "full_clip_bake"
    preview.write_text("changed preview")
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 2


def test_bake_path_code_digest_scopes_to_bake_path_source():
    source = Path(bake.__file__).read_text(encoding="utf-8")
    base = bake._bake_path_code_digest_source(source)
    assert base["version"] == 1
    assert base["functionCount"] > 50
    orchestrator_edit = source.replace(
        "def run_bake_and_rank_pipeline(", "def run_bake_and_rank_pipeline(  # digest probe", 1)
    assert orchestrator_edit != source
    assert bake._bake_path_code_digest_source(orchestrator_edit) == base
    bake_path_edit = source.replace(
        '"""Constrain browser IK using each baked frame\'s pre-IK source joints."""',
        '"""Constrain browser IK using each baked frame\'s pre-IK source joints."""  # digest probe',
        1)
    assert bake_path_edit != source
    assert bake._bake_path_code_digest_source(bake_path_edit) != base
    constant_edit = source.replace(
        "FIXED_PREVIEW_CAMERA_YAW_DEGREES = 135.0", "FIXED_PREVIEW_CAMERA_YAW_DEGREES = 136.0", 1)
    assert constant_edit != source
    assert bake._bake_path_code_digest_source(constant_edit) != base


def test_selected_section_code_digest_tracks_external_fit_dependencies():
    base = bake._selected_section_bake_code_digest_source(
        "local-bake-digest",
        {
            "controlled_motion.py": "a" * 64,
            "contact_constraints.py": "b" * 64,
        },
    )
    changed = bake._selected_section_bake_code_digest_source(
        "local-bake-digest",
        {
            "controlled_motion.py": "a" * 64,
            "contact_constraints.py": "c" * 64,
        },
    )

    assert base["dependencyCount"] == 2
    assert changed["sha256"] != base["sha256"]
    from exercise_motion_pkg.fit_runtime import fit_cache_source_paths

    dependency_names = {path.name for path in fit_cache_source_paths()}
    assert "contact_constraints.py" in dependency_names
    assert "temporal_quality.py" in dependency_names


def test_selected_section_cache_digest_changes_when_transitive_fit_dependency_changes(
    tmp_path,
    monkeypatch,
):
    from exercise_motion_pkg import fit_runtime

    dependency = tmp_path / "temporal_quality.py"
    dependency.write_text("quality_policy = 'before'\n", encoding="utf-8")
    monkeypatch.setattr(fit_runtime, "fit_cache_source_paths", lambda: (dependency,))
    bake._SELECTED_SECTION_BAKE_CODE_DIGEST_CACHE.clear()

    before = bake._selected_section_bake_code_digest()
    dependency.write_text("quality_policy = 'after'\n", encoding="utf-8")
    after = bake._selected_section_bake_code_digest()

    assert after["sha256"] != before["sha256"]


def test_bake_checkpoint_key_scopes_code_hash_to_bake_path(tmp_path, monkeypatch):
    preview = tmp_path / "preview.html"
    preview.write_text("preview")
    skeleton = tmp_path / "skeleton.json"
    video = tmp_path / "review.webm"
    captured = {}
    real_cache_key = stage_cache.cache_key

    def capture_cache_key(settings, inputs):
        captured["settings"] = settings
        captured["inputs"] = list(inputs)
        return real_cache_key(settings, inputs)

    monkeypatch.setattr(stage_cache, "cache_key", capture_cache_key)

    def generate(*args, **kwargs):
        skeleton.write_text('{"frames": []}')
        video.write_bytes(b"video")
        return [bake.BakedLoopArtifact(0, skeleton, video, {"frames": []})]

    monkeypatch.setattr(bake, "_bake_preview_loops_with_playwright_uncached", generate)
    bake.bake_preview_loops_with_playwright(
        preview, [bake.EligibleLoop(0, {}, 1, 0, 1)], tmp_path, 6)
    assert Path(bake.__file__) not in captured["inputs"]
    digest = captured["settings"]["bakePathCodeDigest"]
    assert digest["version"] == 1
    assert digest["sha256"]


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
