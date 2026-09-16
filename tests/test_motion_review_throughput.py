import json
import threading
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import browser_workers
from exercise_motion_pkg import review_questions
from exercise_motion_pkg import wave_pipeline as wave


def test_questions_run_concurrently_with_candidate_deadline():
    class Session:
        _max_active_calls = 6
        _candidate_deadlines = threading.local()
        def caption_images(self): pass
    session = Session()
    session._candidate_deadlines.value = 12345
    barrier = threading.Barrier(6, timeout=5)
    def question(index):
        assert session._candidate_deadlines.value == 12345
        barrier.wait()
        return index
    result = review_questions.run_questions({str(i): lambda i=i: question(i) for i in range(6)}, session.caption_images)
    assert result == {str(i): i for i in range(6)}
    assert session._candidate_deadlines.value == 12345


def test_question_pool_grows_to_vlm_parallel_slots():
    class Session:
        _max_active_calls = 8
        _candidate_deadlines = threading.local()
        def caption_images(self): pass
    session = Session()
    session._candidate_deadlines.value = 99
    barrier = threading.Barrier(8, timeout=5)
    def question(index):
        barrier.wait()
        return index
    result = review_questions.run_questions(
        {str(i): lambda i=i: question(i) for i in range(8)},
        session.caption_images,
    )
    assert result == {str(i): i for i in range(8)}
    assert review_questions.question_cache_metrics()["executorWorkers"] >= 8


def test_question_retry_reuses_conclusive_negative_but_not_missing_answer(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"image")
    calls = []
    answers = {"identity": {"verdict": "mismatch"}, "observation": None}
    def run(name):
        def ask():
            calls.append(name)
            return json.dumps(answers[name]), answers[name]
        return review_questions.answer_question(directory=tmp_path, name=name, prompt=name,
            frames=[frame], max_tokens=256, operation=ask, reusable=lambda value: isinstance(value, dict))
    run("identity"); run("observation")
    answers["observation"] = {"complete": True}
    assert run("identity")[1]["verdict"] == "mismatch"
    run("observation")
    assert calls == ["identity", "observation", "observation"]
    frame.write_bytes(b"changed evidence")
    run("identity")
    assert calls[-1] == "identity"


def test_source_gate_parallelizes_independent_questions_and_retries_only_missing_evidence(tmp_path, monkeypatch):
    from collections import Counter
    from test_two_scale_source_validation import make_review_item, topology_response
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"image")
    monkeypatch.setattr(bake, "final_output_motion_contact_sheets", lambda *args, **kwargs: [sheet])
    barrier = threading.Barrier(6, timeout=5)
    calls = []
    first_attempt = [True]
    lock = threading.Lock()
    class Session:
        settings = SimpleNamespace(llama_cpp_model="model")
        _max_active_calls = 6
        _candidate_deadlines = threading.local()
        def caption_images(self, **kwargs):
            prompt = kwargs["prompt"]
            if "Audit only the consistency" in prompt:
                with lock:
                    assert len(calls) >= 6
                    calls.append("consistency")
                return json.dumps({"corroboratedConflict": False, "targetIdentitySupported": "true",
                    "requiredEquipmentSupported": "true", "completeExecutionSupported": "true",
                    "corroboratedContradictions": []})
            if "verify only exercise identity" in prompt:
                name, answer = "identity", {"verdict": "match", "visibleEquipment": ["dumbbell"]}
            elif "one uniformly sampled" in prompt:
                name, answer = "uniform", {"unrelatedActionVisible": False, "unrelatedTileNumbers": []}
            elif "one motion-focused chronological" in prompt:
                name, answer = "motion", {"targetExerciseActionVisible": True, "namedEquipmentEngagedStatus": "engaged"}
            elif "Verify an exact exercise-specific movement topology" in prompt:
                name, answer = "topology", topology_response()
            else:
                name = "observation" if "These sheets emphasize" in prompt else "completeness"
                answer = {"visibleEquipment": ["dumbbell"], "orderedPhases": ["raise", "lower"],
                    "startStateVisible": True, "actionPhaseVisible": True, "turningPointVisible": True,
                    "returnOrFinishVisible": True, "complete": True}
                if name == "observation" and first_attempt[0]:
                    answer.pop("complete")
            with lock:
                calls.append(name)
            if first_attempt[0]:
                barrier.wait()
            return json.dumps(answer)
    session = Session()
    def run():
        return bake.validate_two_scale_source_with_caption_images(make_review_item(tmp_path),
            uniform_sheet_paths=[sheet], output_dir=tmp_path / "review", caption_images=session.caption_images)
    assert run()["reviewStatus"] == "incomplete"
    first_attempt[0] = False
    assert run()["passed"] is True
    assert Counter(calls) == {"identity": 1, "uniform": 1, "motion": 1, "topology": 1,
                             "completeness": 1, "observation": 2, "consistency": 2}


def test_repaired_source_verdict_is_reused_with_provenance(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"image")
    item = SimpleNamespace(exercise_name="Curl", candidate_workspace=tmp_path)
    class Session:
        settings = SimpleNamespace(llama_cpp_model="model")
        def caption_images(self): pass
    monkeypatch.setattr(bake, "final_output_source_video_window", lambda item: (video, bake.DetectionWindow(0, 0, 5)))
    calls = []
    def review(*args, **kwargs):
        calls.append(1)
        return {"passed": False, "reviewStatus": "incomplete", "rejectionReasons": ["missing"],
            "uniformContactSheetPaths": [str(sheet)], "motionContactSheetPaths": []}
    monkeypatch.setattr(bake, "_validate_two_scale_source_uncached", review)
    def run():
        return bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[sheet],
            output_dir=tmp_path / "review", caption_images=Session().caption_images)
    validation = run()
    bake.cache_repaired_source_review(validation, {"valid": True, "resolved": False})
    assert validation["passed"] is False
    repair = {"valid": True, "resolved": True, "claims": {"source": {"verdict": "supported"}}}
    bake.cache_repaired_source_review(validation, repair)
    cached = run()
    assert len(calls) == 1
    assert cached["passed"] is True and cached["reviewStatus"] == "passed"
    assert cached["originalRejectionReasons"] == ["missing"]
    assert cached["disagreementRepair"] == repair


def test_cpu_render_prefetch_uses_production_baker_without_caption_model(tmp_path, monkeypatch):
    candidate = bake.RankedCandidate(0, 1, "curl", "Curl", "curl", {"videoId": "id"})
    request = bake.BakeAndRankRequest(candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        wham_repo_path=None, body_model_root=None, adaptive_preview_settings=True)
    item = wave.StagedWaveItem("curl", "Curl", request)
    preview = tmp_path / "preview.html"; preview.write_text("html")
    cleaned = tmp_path / "cleaned.json"; cleaned.write_text("{}")
    monkeypatch.setattr(bake, "pre_wham_source_interval_authority", lambda **kwargs: "authority")
    monkeypatch.setattr(bake, "load_motion_json", lambda path: "clip")
    monkeypatch.setattr(bake, "build_candidate_review_eligible_loops", lambda clip, **kwargs: ["loop"])
    monkeypatch.setattr(bake, "pre_wham_source_foot_support_evidence", lambda workspace: {"foot": "supported"})
    calls = []
    def render(*args, **kwargs):
        calls.append((args, kwargs))
        return ["artifact"]
    monkeypatch.setattr(bake, "bake_preview_loops_with_playwright", render)
    result = wave.prepare_cpu_render_cache(item, candidate,
        SimpleNamespace(preview_html_path=preview, cleaned_motion_json_path=cleaned), {"contract": "current"})
    assert result["status"] == "prepared"
    assert calls[0][1]["caption_images"] is None
    assert calls[0][1]["adaptive_preview_settings"] is True
    assert calls[0][1]["exercise_motion_contract"] == {"contract": "current"}


def test_wave_overlaps_cpu_render_with_extraction_but_waits_to_start_final_vlm(tmp_path, monkeypatch):
    rendered = threading.Event()
    second_extracted = threading.Event()
    gpu_released = threading.Event()
    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): pytest.fail("Test must not call a model")
        def run_without_llama_overlap(self, operation): return operation()
        def close(self, **kwargs): pass
    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", Session)
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **kwargs: None)
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(wave, "first_attempt_readiness_assessment", lambda *args, **kwargs: {"eligible": True})
    items = [wave.StagedWaveItem(name, name, bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json", workspace=tmp_path / name,
        wham_repo_path=None, body_model_root=None, fallback_candidates=0, max_final_output_rejections=0))
        for name in ("first", "second")]
    monkeypatch.setattr(wave, "_wave_candidates_for_item", lambda item: [bake.RankedCandidate(
        0, 1, item.exercise_id, item.exercise_name, item.exercise_id, {"videoId": item.exercise_id})])
    monkeypatch.setattr(wave, "prepare_candidate_input_video", lambda candidate, **kwargs: tmp_path / "video.mp4")
    def generate(candidate, **kwargs):
        if candidate.exercise_id == "second":
            assert rendered.wait(5), "Rendering did not start while another extraction was active"
            second_extracted.set()
        return SimpleNamespace(wham_cache_status="reused", wham_results_pkl=None)
    monkeypatch.setattr(wave, "generate_candidate_motion", generate)
    def render(item, candidate, result, contract):
        if candidate.exercise_id == "first":
            assert not gpu_released.is_set()
            rendered.set()
            assert second_extracted.wait(5)
        return {"status": "prepared"}
    monkeypatch.setattr(wave, "prepare_cpu_render_cache", render)
    monkeypatch.setattr(wave, "_stop_warm_wham_worker_before_vlm",
        lambda items: gpu_released.set() or {"stopped": True})
    def finalize(request, **kwargs):
        assert gpu_released.is_set()
        return {"selected": {"candidate": {"videoId": request.workspace.name}}, "candidateResults": []}
    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline", finalize)
    result = wave.run_staged_bake_wave(items, workspace=tmp_path / "wave", wave_id="test")
    assert result["completedExerciseCount"] == 2
    assert len(result["metrics"]["cpuRenderPrefetch"]) == 2
    for state in result["items"]:
        final = state["finalValidation"]
        timing = final["schedulingTimings"]
        assert set(timing) == {"executorQueueWaitSeconds", "renderPrefetchWaitSeconds",
                               "pipelineProcessingSeconds"}
        assert all(value >= 0 for value in timing.values())
        assert final["elapsedSeconds"] == pytest.approx(sum(timing.values()), abs=.002)


def test_finalization_abandons_unfinished_speculative_prefetch(tmp_path, monkeypatch):
    import time as time_module
    finalize_started = threading.Event()
    release_render = threading.Event()
    render_started = threading.Event()

    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): pytest.fail("Test must not call a model")
        def run_without_llama_overlap(self, operation): return operation()
        def close(self, **kwargs): pass

    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", Session)
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **kwargs: None)
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(wave, "first_attempt_readiness_assessment", lambda *args, **kwargs: {"eligible": True})
    item = wave.StagedWaveItem(
        "slow", "Slow",
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / "candidates.json",
            workspace=tmp_path / "slow",
            wham_repo_path=None,
            body_model_root=None,
            fallback_candidates=0,
            max_final_output_rejections=0,
            llama_cpp_parallel=1,
        ),
    )
    monkeypatch.setattr(wave, "_wave_candidates_for_item", lambda _item: [bake.RankedCandidate(
        0, 1, "slow", "Slow", "slow", {"videoId": "slow"})])
    monkeypatch.setattr(wave, "prepare_candidate_input_video", lambda candidate, **kwargs: tmp_path / "video.mp4")
    monkeypatch.setattr(
        wave,
        "generate_candidate_motion",
        lambda candidate, **kwargs: SimpleNamespace(wham_cache_status="reused", wham_results_pkl=None),
    )

    def render(_item, candidate, result, contract):
        render_started.set()
        # Stay unfinished until finalization has already started process().
        assert finalize_started.wait(5)
        release_render.wait(5)
        return {"status": "prepared", "artifactCount": 0}

    monkeypatch.setattr(wave, "prepare_cpu_render_cache", render)
    monkeypatch.setattr(wave, "_stop_warm_wham_worker_before_vlm", lambda items: {"stopped": True})

    def finalize(request, **kwargs):
        finalize_started.set()
        # Give the abandon path a moment; must not block on the stuck prefetch.
        time_module.sleep(0.05)
        release_render.set()
        return {"selected": {"candidate": {"videoId": "slow"}}, "candidateResults": []}

    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline", finalize)
    started = time_module.perf_counter()
    result = wave.run_staged_bake_wave([item], workspace=tmp_path / "wave", wave_id="abandon")
    elapsed = time_module.perf_counter() - started
    assert elapsed < 2.0
    assert result["completedExerciseCount"] == 1
    prefetch = result["metrics"]["cpuRenderPrefetch"]
    assert len(prefetch) == 1
    status = next(iter(prefetch.values()))["status"]
    assert status in {"abandoned_for_finalization", "prepared"}
    if status == "abandoned_for_finalization":
        assert render_started.is_set()
    timing = result["items"][0]["finalValidation"]["schedulingTimings"]
    assert timing["renderPrefetchWaitSeconds"] < 0.5


def test_abandoned_speculative_prefetch_releases_bake_checkpoint_lock(tmp_path, monkeypatch):
    import time as time_module
    from exercise_motion_pkg import fit_runtime

    preview = tmp_path / "preview.html"
    preview.write_text("preview")
    speculative_started = threading.Event()
    release_speculative = threading.Event()
    bake_calls = {"count": 0}
    args = (preview, [bake.EligibleLoop(0, {}, 1, 0, 1)], tmp_path, 6)

    def uncached(*_args, **_kwargs):
        bake_calls["count"] += 1
        if bake_calls["count"] == 1:
            speculative_started.set()
            while not release_speculative.wait(0.05):
                if fit_runtime.speculative_prefetch_abandoned(tmp_path):
                    raise fit_runtime.SpeculativePrefetchAbandoned()
            raise fit_runtime.SpeculativePrefetchAbandoned()
        skeleton = tmp_path / "skeleton.json"
        video = tmp_path / "review.webm"
        skeleton.write_text('{"frames": []}')
        video.write_bytes(b"video")
        return [bake.BakedLoopArtifact(0, skeleton, video, {"frames": []})]

    monkeypatch.setattr(bake, "_bake_preview_loops_with_playwright_uncached", uncached)

    def speculative():
        with fit_runtime.speculative_workspace(tmp_path), fit_runtime.speculative_fit_context():
            try:
                bake.bake_preview_loops_with_playwright(*args, speculative_prefetch=True)
            except fit_runtime.SpeculativePrefetchAbandoned:
                pass

    thread = threading.Thread(target=speculative)
    thread.start()
    assert speculative_started.wait(5)
    fit_runtime.abandon_speculative_workspace(tmp_path)
    started = time_module.perf_counter()
    bake.bake_preview_loops_with_playwright(*args)
    assert time_module.perf_counter() - started < 2.0
    release_speculative.set()
    thread.join(5)


def test_browser_reuse_context_isolation_and_failed_job_recovery():
    pytest.importorskip("playwright.sync_api")
    workers = browser_workers.BrowserWorkers(workers=1)
    launches = []
    def launch(runtime):
        launches.append(threading.get_ident())
        return bake.launch_chromium_browser(runtime)
    def render(fail=False):
        with workers.session(launch) as browser:
            assert len(browser.contexts) == 0
            page = browser.new_page()
            page.set_content('<canvas id="c" width="32" height="32"></canvas>')
            page.evaluate("c.getContext('2d').fillRect(0,0,32,32)")
            if fail:
                raise ValueError("broken job")
            return page.locator("canvas").screenshot()
    try:
        first = workers.run(render)
        assert first == workers.run(render)
        assert len(launches) == 1
        with pytest.raises(ValueError, match="broken job"):
            workers.run(lambda: render(fail=True))
        assert first == workers.run(render)
        assert len(launches) == 2
        assert len(set(launches)) == 1
    finally:
        workers.close()
    assert all(not thread.is_alive() for thread in workers._threads)
