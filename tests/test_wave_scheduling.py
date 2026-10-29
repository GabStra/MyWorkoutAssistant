import json
import threading
from types import SimpleNamespace
import pytest

from exercise_motion_pkg import wave_pipeline as wave
from exercise_motion_pkg import bake_and_rank as bake
from test_motion_review_improvements import contract_for, exercise


@pytest.mark.parametrize('statuses,expected_count,result', [
    (['failed'], 1, 'failed'),
    (['failed'], 2, 'pending'),
    (['prepared'], 2, 'pending'),
    (['failed', 'prepared'], 2, 'prepared'),
])
def test_generation_status_counts_finished_failures(statuses, expected_count, result):
    assert wave.generation_status([{'status': status} for status in statuses], expected_count) == result


def test_staged_source_portfolio_allows_two_when_recon_budget_is_two():
    readiness = {'tier': 'high', 'eligible': True, 'portfolioSize': 2}
    single = SimpleNamespace(
        fallback_candidates=0, max_final_output_rejections=0,
        max_reconstruction_candidate_attempts=1,
    )
    dual = SimpleNamespace(
        fallback_candidates=0, max_final_output_rejections=0,
        max_reconstruction_candidate_attempts=2,
    )
    assert wave.staged_source_portfolio_size(single, readiness) == 1
    assert wave.staged_source_portfolio_size(dual, readiness) == 2


@pytest.mark.parametrize(
    "candidate_count,render_prefetch_enabled,expected_prefetch",
    [(1, True, []), (2, True, ["first"]), (1, False, []), (2, False, [])],
)
def test_render_prefetch_setting_controls_overlap_with_unfinished_generation(
    tmp_path, monkeypatch, candidate_count, render_prefetch_enabled, expected_prefetch
):
    from exercise_motion_pkg import resource_budget

    monkeypatch.setenv(
        "EXERCISE_MOTION_RENDER_PREFETCH",
        "on" if render_prefetch_enabled else "off",
    )

    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return '{}'
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **k: None)
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate', lambda *a, **k: {'passed': True})
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
        lambda *a, **k: {'eligible': True, 'portfolioSize': 1})
    monkeypatch.setattr(resource_budget, 'staged_generation_cpu_workers', lambda: 2)
    monkeypatch.setattr(resource_budget, 'render_prefetch_worker_limit', lambda ready_count: 1)
    items = [wave.StagedWaveItem(name, name, bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path / name,
        body_model_root=None, fallback_candidates=0,
        max_final_output_rejections=0)) for name in ['first', 'last'][:candidate_count]]
    candidates = {item.exercise_id: bake.RankedCandidate(
        exercise_index=index, candidate_rank=0, exercise_id=item.exercise_id,
        exercise_name=item.exercise_name, exercise_slug=item.exercise_id,
        candidate={'videoId': item.exercise_id}) for index, item in enumerate(items)}
    monkeypatch.setattr(wave, '_wave_candidates', lambda request: [candidates[request.workspace.name]])
    monkeypatch.setattr(wave, 'prepare_candidate_input_video',
        lambda candidate, **k: tmp_path / f'{candidate.video_id}.mp4')
    prefetch_started = threading.Event()
    prefetched = []
    first_finalized = threading.Event()

    def generate(candidate, **kwargs):
        if candidate.exercise_id == 'last':
            if render_prefetch_enabled:
                assert prefetch_started.wait(3), 'earlier render did not overlap generation'
                assert first_finalized.wait(3), 'completed exercise waited for the slow sibling reconstruction'
            else:
                assert not prefetch_started.wait(0.2), 'disabled render prefetch still started'
        return SimpleNamespace(reconstruction_cache_status='generated', reconstruction_results_pkl=None)

    def prefetch(item, candidate, result, contract):
        prefetched.append(candidate.exercise_id)
        prefetch_started.set()
        return {'status': 'prepared'}

    finalized = []

    def finalize(request, **kwargs):
        finalized.extend(candidate.exercise_id for candidate in kwargs['prepared_candidates'])
        if request.workspace.name == 'first':
            first_finalized.set()
        return {'selected': {'selectedWearSkeletonPath': str(tmp_path / 'wear.json')}}

    monkeypatch.setattr(wave, 'generate_candidate_motion', generate)
    monkeypatch.setattr(wave, 'prepare_cpu_render_cache', prefetch)
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline', finalize)
    report = wave.run_staged_bake_wave(items, workspace=tmp_path / 'wave', wave_id='prefetch')
    assert prefetched == expected_prefetch
    assert sorted(finalized) == sorted(candidates)
    assert report['completedExerciseCount'] == candidate_count
    assert report['metrics']['renderPrefetchEnabled'] is render_prefetch_enabled
    assert report['metrics']['renderPrefetchWorkers'] == (1 if render_prefetch_enabled else 0)


def test_split_gpu_hands_first_approved_source_to_reconstruction_while_reviews_continue(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    monkeypatch.setattr(wave, "exclusive_gpu_device", lambda: "1")

    class Session:
        def __init__(self, request):
            self.request = request
        def caption_images(self, **kwargs): return "{}"
        def run_without_llama_overlap(self, operation): return operation()
        def close(self, **kwargs): pass
        def timing_manifest(self): return {}

    items = [wave.StagedWaveItem(
        name,
        name,
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / f"{name}.json",
            workspace=tmp_path / name,
            body_model_root=None,
            llama_cpp_parallel=2,
            shared_llama_server=True,
        ),
    ) for name in ("first", "second")]
    candidates = {item.exercise_id: bake.RankedCandidate(
        exercise_index=index,
        candidate_rank=0,
        exercise_id=item.exercise_id,
        exercise_name=item.exercise_name,
        exercise_slug=item.exercise_id,
        candidate={"videoId": item.exercise_id},
    ) for index, item in enumerate(items)}

    reconstruction_started = threading.Event()
    second_review_finished = threading.Event()
    generation_calls = {}

    def prepare(candidate, **kwargs):
        return tmp_path / f"{candidate.exercise_id}.mp4"

    def review(candidate, **kwargs):
        if candidate.exercise_id == "second":
            assert reconstruction_started.wait(3), "reconstruction waited for the whole source wave"
            second_review_finished.set()

    def generate(candidate, **kwargs):
        generation_calls[candidate.exercise_id] = generation_calls.get(candidate.exercise_id, 0) + 1
        run_reconstruction = kwargs.get("run_reconstruction_exclusive")
        if run_reconstruction is not None:
            run_reconstruction(lambda: reconstruction_started.set())
        return SimpleNamespace(reconstruction_cache_status="generated", reconstruction_results_pkl=None)

    gate = WaveGpuGate()

    @contextmanager
    def accelerator_phase(wave_id, stage, *, deadline=None, gpu_lane=None):
        with gate.phase(
            wave_id,
            stage,
            lambda: False,
            deadline=deadline,
            gpu_lane=gpu_lane,
        ) as cancelled:
            yield cancelled

    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", Session)
    monkeypatch.setattr(wave, "_wave_candidates", lambda request: [candidates[request.workspace.name]])
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **kwargs: None)
    monkeypatch.setattr(wave, "first_attempt_readiness_assessment", lambda *args, **kwargs: {"eligible": True})
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(wave, "prepare_candidate_input_video", prepare)
    monkeypatch.setattr(wave, "review_prepared_source", review)
    monkeypatch.setattr(wave, "generate_candidate_motion", generate)
    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline", lambda *args, **kwargs: {
        "selected": {"selectedWearSkeletonPath": str(tmp_path / "wear.json")}
    })

    report = wave.run_staged_bake_wave(
        items,
        workspace=tmp_path / "wave",
        wave_id="split-gpu-overlap",
        accelerator_phase=accelerator_phase,
    )

    assert reconstruction_started.is_set()
    assert second_review_finished.is_set()
    assert report["metrics"]["earlyReconstructionOverlap"]
    assert generation_calls == {"first": 1, "second": 1}


def test_gvhmr_stage_split_keeps_only_two_candidates_in_flight(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from exercise_motion_pkg import resource_budget

    monkeypatch.setattr(wave, "exclusive_gpu_device", lambda: "1")

    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return "{}"
        def run_without_llama_overlap(self, operation): return operation()
        def close(self, **kwargs): pass
        def timing_manifest(self): return {}

    items = [wave.StagedWaveItem(
        name,
        name,
        bake.BakeAndRankRequest(
            candidates_json=tmp_path / f"{name}.json",
            workspace=tmp_path / name,
            body_model_root=None,
            llama_cpp_parallel=2,
            shared_llama_server=True,
            use_warm_gvhmr_worker=True,
            gvhmr_stage_split=True,
        ),
    ) for name in ("first", "second", "third", "fourth")]
    candidates = {item.exercise_id: bake.RankedCandidate(
        exercise_index=index,
        candidate_rank=0,
        exercise_id=item.exercise_id,
        exercise_name=item.exercise_name,
        exercise_slug=item.exercise_id,
        candidate={"videoId": item.exercise_id},
    ) for index, item in enumerate(items)}

    two_started = Event()
    release = Event()
    third_reviewed = Event()
    count_lock = Lock()
    started_candidates = []

    def prepare(candidate, **kwargs):
        return tmp_path / f"{candidate.exercise_id}.mp4"

    def review(candidate, **kwargs):
        if candidate.exercise_id == "third":
            third_reviewed.set()

    def generate(candidate, **kwargs):
        assert kwargs.get("run_reconstruction_exclusive") is None
        with count_lock:
            started_candidates.append(candidate.exercise_id)
            if len(started_candidates) == 2:
                two_started.set()
        assert release.wait(5)
        return SimpleNamespace(reconstruction_cache_status="generated", reconstruction_results_pkl=None)

    @contextmanager
    def accelerator_phase(wave_id, stage, *, deadline=None, gpu_lane=None):
        yield lambda: False

    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", Session)
    monkeypatch.setattr(wave, "_wave_candidates", lambda request: [candidates[request.workspace.name]])
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **kwargs: None)
    monkeypatch.setattr(wave, "first_attempt_readiness_assessment", lambda *args, **kwargs: {"eligible": True})
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(wave, "prepare_candidate_input_video", prepare)
    monkeypatch.setattr(wave, "review_prepared_source", review)
    monkeypatch.setattr(wave, "generate_candidate_motion", generate)
    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline", lambda *args, **kwargs: {
        "selected": {"selectedWearSkeletonPath": str(tmp_path / "wear.json")}
    })
    monkeypatch.setattr(resource_budget, "staged_generation_cpu_workers", lambda: 2)

    with ThreadPoolExecutor(max_workers=1) as executor:
        report_future = executor.submit(
            wave.run_staged_bake_wave,
            items,
            workspace=tmp_path / "wave",
            wave_id="gvhmr-stage-split-bounded",
            accelerator_phase=accelerator_phase,
        )
        assert two_started.wait(3)
        assert third_reviewed.wait(3)
        release.set()
        report = report_future.result(timeout=10)

    assert sorted(started_candidates) == ["first", "fourth", "second", "third"]
    assert report["metrics"]["gvhmrStageSplit"]["candidateQueueLimit"] == 2
    assert report["metrics"]["gvhmrStageSplit"]["maximumEarlyCandidatesInFlight"] == 2


def test_gvhmr_stage_split_cli_requires_supervised_worker_and_maps_request(tmp_path):
    from exercise_motion_pkg.cli import build_bake_and_rank_request, build_parser

    parser = build_parser()
    base = ["bake-and-rank", "--candidates-json", str(tmp_path / "candidates.json")]
    with pytest.raises(ValueError, match="GVHMR stage split requires warm workers"):
        build_bake_and_rank_request(parser.parse_args([*base, "--gvhmr-stage-split"]))

    args = parser.parse_args([
        *base,
        "--gvhmr-stage-split",
        "--warm-gvhmr-worker",
        "--shared-llama-server",
    ])
    request = build_bake_and_rank_request(args)
    assert request.gvhmr_stage_split is True
    assert request.use_warm_gvhmr_worker is True
    assert request.shared_llama_server is True


@pytest.mark.parametrize("use_service_phases", [False, True])
def test_persistent_render_prefetch_is_drained_before_wave_returns(tmp_path, monkeypatch, use_service_phases):
    from concurrent.futures import ThreadPoolExecutor
    from exercise_motion_pkg import resource_budget, fit_runtime
    if use_service_phases:
        monkeypatch.setattr(fit_runtime, 'DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS', 0.05)

    monkeypatch.setenv("EXERCISE_MOTION_RENDER_PREFETCH", "on")

    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return '{}'
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **k: None)
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate', lambda *a, **k: {'passed': True})
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
        lambda *a, **k: {'eligible': True, 'portfolioSize': 1})
    monkeypatch.setattr(resource_budget, 'staged_generation_cpu_workers', lambda: 2)
    items = [wave.StagedWaveItem(name, name, bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path / name,
        body_model_root=None, fallback_candidates=0,
        max_final_output_rejections=0)) for name in ['first', 'last']]
    candidates = {item.exercise_id: bake.RankedCandidate(
        exercise_index=index, candidate_rank=0, exercise_id=item.exercise_id,
        exercise_name=item.exercise_name, exercise_slug=item.exercise_id,
        candidate={'videoId': item.exercise_id}) for index, item in enumerate(items)}
    monkeypatch.setattr(wave, '_wave_candidates', lambda request: [candidates[request.workspace.name]])
    monkeypatch.setattr(wave, 'prepare_candidate_input_video',
        lambda candidate, **k: tmp_path / f'{candidate.video_id}.mp4')

    prefetch_started = threading.Event()
    allow_prefetch_to_finish = threading.Event()
    prefetch_finished = threading.Event()
    finalization_finished = threading.Event()

    def generate(candidate, **kwargs):
        if candidate.exercise_id == 'last':
            assert prefetch_started.wait(3), 'earlier render did not overlap generation'
        return SimpleNamespace(reconstruction_cache_status='generated', reconstruction_results_pkl=None)

    def prefetch(item, candidate, result, contract):
        prefetch_started.set()
        assert allow_prefetch_to_finish.wait(3), 'request did not drain speculative render'
        prefetch_finished.set()
        return {'status': 'prepared'}

    def finalize(request, **kwargs):
        if request.workspace.name == 'first':
            assert prefetch_finished.is_set(), 'finalization duplicated an active preparation'
            finalization_finished.set()
        kwargs['shared_vision_session'].caption_images()
        return {'selected': {'selectedWearSkeletonPath': str(tmp_path / 'wear.json')}}

    monkeypatch.setattr(wave, 'generate_candidate_motion', generate)
    monkeypatch.setattr(wave, 'prepare_cpu_render_cache', prefetch)
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline', finalize)

    from contextlib import contextmanager
    phases = []

    @contextmanager
    def accelerator_phase(wave_id, stage):
        phases.append(stage)
        yield lambda: False

    shared_render_executor = ThreadPoolExecutor(max_workers=1)
    wave_executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = wave_executor.submit(
            wave.run_staged_bake_wave,
            items,
            workspace=tmp_path / 'wave',
            wave_id='persistent-prefetch',
            render_executor=shared_render_executor,
            accelerator_phase=accelerator_phase if use_service_phases else None,
        )
        assert prefetch_started.wait(3)
        assert not finalization_finished.wait(0.1), 'finalization duplicated an active preparation'
        assert not future.done(), 'wave returned while its persistent prefetch was still running'

        allow_prefetch_to_finish.set()
        report = future.result(timeout=3)
        assert prefetch_finished.is_set()
        assert all(entry['status'] == 'prepared' for entry in report['metrics']['cpuRenderPrefetch'].values()), \
            'A wall-clock join timer discarded completed, reusable preparation'
        assert report['completedExerciseCount'] == 2
        if use_service_phases:
            assert phases[0] == 'source_and_generation'
            assert phases.count('final_review') == 2
            assert phases[-1] == 'reconstruction'
        from exercise_motion_pkg import fit_runtime
        speculative_workspace = items[0].request.workspace / candidates['first'].workspace_slug
        assert not fit_runtime.active_speculative_workspace(speculative_workspace)
        assert not fit_runtime.speculative_prefetch_abandoned(speculative_workspace)
    finally:
        allow_prefetch_to_finish.set()
        wave_executor.shutdown(wait=True)
        shared_render_executor.shutdown(wait=True)


def test_abandoned_render_prefetch_drain_result_is_recorded(tmp_path, monkeypatch):
    from concurrent.futures import Future

    wave_workspace = tmp_path / "wave"
    worker_workspace = tmp_path / "candidate"
    worker_workspace.mkdir()
    key = "rdl:candidate-1"

    def run_wave(_items, **kwargs):
        future = Future()
        future.set_result({
            "status": "abandoned_for_finalization",
            "startedAt": "2026-10-05T10:00:00+00:00",
            "finishedAt": "2026-10-05T10:00:12+00:00",
            "elapsedSeconds": 12.0,
        })
        kwargs["render_futures"][key] = future
        kwargs["render_workspaces"][key] = worker_workspace
        return {
            "waveId": "prefetch-drain",
            "elapsedSeconds": 20.0,
            "completedExerciseCount": 1,
            "generationEfficiency": {
                "acceptedMovementCount": 1,
                "acceptedPerElapsedMinute": 3.0,
            },
            "metrics": {
                "cpuRenderPrefetch": {
                    key: {
                        "status": "abandoned_for_finalization",
                        "cancelledBeforeStart": False,
                    }
                }
            },
        }

    monkeypatch.setattr(wave, "_run_staged_bake_wave", run_wave)
    report = wave.run_staged_bake_wave(
        [None], workspace=wave_workspace, wave_id="prefetch-drain"
    )

    prefetch = report["metrics"]["cpuRenderPrefetch"][key]
    assert prefetch["workerDrainStatus"] == "completed"
    assert prefetch["workerResultStatus"] == "abandoned_for_finalization"
    assert prefetch["workerElapsedSeconds"] == 12.0
    assert prefetch["workerStartedAt"] == "2026-10-05T10:00:00+00:00"
    assert prefetch["workerFinishedAt"] == "2026-10-05T10:00:12+00:00"
    assert report["metrics"]["renderPrefetchDrainSeconds"] >= 0.0
    assert report["generationEfficiency"]["timingBasis"].endswith(
        "and_prefetch_drain"
    )

    for report_name in ("staged_wave_report.json", "staged_wave_checkpoint.json"):
        persisted = json.loads((wave_workspace / report_name).read_text(encoding="utf-8"))
        assert persisted["metrics"]["cpuRenderPrefetch"][key]["workerElapsedSeconds"] == 12.0


@pytest.mark.parametrize('unavailable_count', [0, 5])
@pytest.mark.parametrize('remaining_source_passes', [True, False])
def test_ready_sources_defer_later_attempts_and_resume_next_candidate(tmp_path, monkeypatch, remaining_source_passes, unavailable_count):
    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return '{}'
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **k: None)
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate', lambda *a, **k: {'passed': True})
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
        lambda *a, **k: {'eligible': True, 'portfolioSize': 1})
    items = [wave.StagedWaveItem(name, name, bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path / name,
        body_model_root=None, fallback_candidates=0,
        max_final_output_rejections=0, llama_cpp_parallel=3))
        for name in ['a', 'b', 'slow', 'queued'] + [f'unavailable_{i}' for i in range(unavailable_count)]]
    candidates = {item.exercise_id: [bake.RankedCandidate(
        exercise_index=0, candidate_rank=index, exercise_id=item.exercise_id,
        exercise_name=item.exercise_name, exercise_slug=item.exercise_id,
        candidate={'videoId': f'{item.exercise_id}-{index}'})
        for index in range(0 if item.exercise_id.startswith('unavailable_') else 2 if item.exercise_id in {'a', 'slow', 'queued'} else 1)] for item in items}
    monkeypatch.setattr(wave, '_wave_candidates', lambda request: candidates[request.workspace.name])
    ready = threading.Event()
    usable = []
    unavailable = []
    unavailable_done = threading.Event()
    if not unavailable_count:
        unavailable_done.set()
    slow_started = threading.Event()
    def progress(message):
        if message.startswith('Source review: unavailable_'):
            unavailable.append(message)
            if len(unavailable) == unavailable_count:
                unavailable_done.set()
        if '1 usable source(s)' in message:
            usable.append(message)
            if len(usable) >= 1: ready.set()
    attempted = []
    def prepare(candidate, **kwargs):
        attempted.append(candidate.video_id)
        if candidate.video_id in {'a-0', 'b-0'}:
            assert slow_started.wait(3)
        if candidate.video_id == 'slow-0':
            slow_started.set()
            assert ready.wait(3)
            raise bake.SourceCandidateRejected('bad window')
        if candidate.video_id == 'slow-1' and not remaining_source_passes:
            raise bake.SourceCandidateRejected('last window rejected')
        return tmp_path / f'{candidate.video_id}.mp4'
    monkeypatch.setattr(wave, 'prepare_candidate_input_video', prepare)
    barrier = threading.Barrier(2)
    def generate(candidate, **kwargs):
        if candidate.exercise_id != 'slow': barrier.wait(3)
        return SimpleNamespace(reconstruction_cache_status='generated', reconstruction_results_pkl=None)
    monkeypatch.setattr(wave, 'generate_candidate_motion', generate)
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline',
        lambda *a, **k: {'selected': {'selectedWearSkeletonPath': str(tmp_path / 'wear.json')}})
    report = wave.run_staged_bake_wave(items, workspace=tmp_path / 'wave1', wave_id='first', progress=progress)
    slow = next(x for x in report['items'] if x['exerciseId'] == 'slow')
    assert slow['source']['failureReason'] == 'source_turn_deferred'
    assert 'slow-1' not in attempted
    resume = json.loads((items[2].request.workspace / 'source_turn_resume.json').read_text())
    assert resume['nextCandidateKey'] == wave._candidate_key(candidates['slow'][1])
    assert wave._candidate_key(candidates['slow'][0]) in resume['attemptedCandidateKeys']
    queued = next(x for x in report['items'] if x['exerciseId'] == 'queued')
    assert queued['source']['failureReason'] == 'source_turn_deferred'
    queued_resume = json.loads((items[3].request.workspace / 'source_turn_resume.json').read_text())
    assert queued_resume['nextCandidateKey'] == wave._candidate_key(candidates['queued'][0])
    assert not any(key.startswith('queued-') for key in attempted)
    assert report['metrics']['generationCpuWorkers'] == 2
    assert sum(x['status'] == 'completed' for x in report['items']) == 2
    ready_source = next(x for x in report['items'] if x['exerciseId'] == 'a')
    assert ready_source['source']['nextCandidateKey'] == wave._candidate_key(candidates['a'][1])
    attempted.clear()
    wave.run_staged_bake_wave([items[2]], workspace=tmp_path / 'wave2', wave_id='second')
    assert attempted == ['slow-1']
    if remaining_source_passes:
        assert not (items[2].request.workspace / 'source_turn_resume.json').exists()
    else:
        final_resume = json.loads((items[2].request.workspace / 'source_turn_resume.json').read_text())
        assert final_resume['attemptedVideoIds'] == ['slow-0', 'slow-1']
        assert final_resume['sourceTurnAttemptsUsed'] == 2
        assert final_resume['nextCandidateKey'] is None
    budget = json.loads((items[2].request.workspace / 'source_turn_budget.json').read_text())
    assert budget['sourceTurnAttemptsUsed'] == 2


def test_staged_wave_rejects_source_before_motion_generation(tmp_path, monkeypatch):
    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return '{}'
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    candidate = bake.RankedCandidate(
        exercise_index=0,
        candidate_rank=0,
        exercise_id='press',
        exercise_name='Dumbbell Overhead Press',
        exercise_slug='press',
        candidate={'videoId': 'press-source', 'title': 'Press'},
    )
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json',
        workspace=tmp_path / 'press',
        body_model_root=None,
        two_scale_source_validation=True,
        fallback_candidates=0,
        max_final_output_rejections=0,
    )
    item = wave.StagedWaveItem('press', 'Dumbbell Overhead Press', request)
    source_path = tmp_path / 'press' / 'selected.mp4'
    reviewed = []

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, '_wave_candidates', lambda _request: [candidate])
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **_kwargs: None)
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
                        lambda *_args, **_kwargs: {'eligible': True, 'portfolioSize': 1})
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate',
                        lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(wave, 'prepare_candidate_input_video',
                        lambda *_args, **_kwargs: source_path)

    def reject_source(reviewed_candidate, *, selected_video, **_kwargs):
        reviewed.append((reviewed_candidate, selected_video))
        raise bake.SourceCandidateRejected(
            'Source endpoints contradict the movement contract.',
            reason_tags=['two_scale_source_pose_contract_mismatch'],
        )

    monkeypatch.setattr(wave, 'review_prepared_source', reject_source)
    monkeypatch.setattr(wave, 'generate_candidate_motion',
                        lambda *_args, **_kwargs: pytest.fail('rejected source reached reconstruction'))
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline',
                        lambda *_args, **_kwargs: {'selected': None})

    report = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / 'wave', wave_id='source-endpoint-reject',
    )

    assert reviewed == [(candidate, source_path)]
    attempt = report['items'][0]['source']['attempts'][0]
    assert attempt['status'] == 'rejected_source_validation'
    assert attempt['reasonTags'] == ['two_scale_source_pose_contract_mismatch']
    assert report['items'][0]['reconstruction']['status'] != 'prepared'


def test_staged_wave_retains_unresolved_stationary_foot_source_for_review(tmp_path, monkeypatch):
    import hashlib
    from exercise_motion_pkg import body_support_observation as support_observation

    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return '{}'
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    candidate = bake.RankedCandidate(
        exercise_index=0, candidate_rank=0, exercise_id='carry',
        exercise_name='Dumbbell Overhead Carry', exercise_slug='carry',
        candidate={'videoId': 'carry-source', 'title': 'Carry'},
    )
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path / 'carry',
        body_model_root=None, fallback_candidates=0, max_final_output_rejections=0,
    )
    item = wave.StagedWaveItem('carry', 'Dumbbell Overhead Carry', request)
    source_path = tmp_path / 'carry' / 'selected.mp4'
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b'exact selected cut')
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_evidence = {
        'bodySupportObservation': {},
        'footPatchEvidence': {'available': True, 'policyVersion': 16, 'feet': {
            'left': {'states': ['unknown'] * 8}, 'right': {'states': ['unknown'] * 8},
        }},
        'contacts': [],
    }

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, '_wave_candidates_for_item', lambda _item: [candidate])
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **_kwargs: None)
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
                        lambda *_args, **_kwargs: {'eligible': True, 'portfolioSize': 1})
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate',
                        lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(wave, 'prepare_candidate_input_video',
                        lambda *_args, **_kwargs: source_path)
    reviewed = []
    monkeypatch.setattr(wave, 'review_prepared_source',
                        lambda *_args, **_kwargs: reviewed.append('called'))
    monkeypatch.setattr(bake, 'load_pre_reconstruction_exact_source_phase_metrics',
                        lambda _workspace: {'sourceFootSupportEvidence': source_evidence})
    monkeypatch.setattr(bake, 'load_verified_source_pose_reference', lambda *_args: None)
    monkeypatch.setattr(support_observation, 'source_support_observation_needed', lambda *_args: True)
    monkeypatch.setattr(support_observation, 'observe_body_support', lambda *_args: {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'policyVersion': support_observation.POLICY_VERSION,
        'sourceVideoSha256': digest,
        'observation': {
            'leftFoot': 'moving', 'rightFoot': 'stationary_full_sole',
            'rightFootSurface': 'ground',
        },
    })
    monkeypatch.setattr(wave, 'generate_candidate_motion',
                        lambda *_args, **_kwargs: pytest.fail('unresolved support reached reconstruction'))
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline', lambda *_args, **_kwargs: {'selected': None})

    report = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / 'wave', wave_id='source-support-readiness',
    )

    assert report['items'][0]['source']['attempts'], report
    attempt = report['items'][0]['source']['attempts'][0]
    assert attempt['status'] == 'needs_source_review'
    assert attempt['failureOwner'] == 'source_evidence'
    assert attempt['reasonTags'] == ['source_support_contact_evidence_unavailable']
    assert attempt['sourceContactReadiness']['unresolvedSides'] == ['right']
    assert report['items'][0]['source']['failureReason'] == 'source_review_incomplete'
    assert wave.wave_retry_disposition(report['items'][0]) == 'retry_review'
    assert report['items'][0]['reconstruction']['status'] != 'prepared'
    assert reviewed == []


@pytest.mark.parametrize('readiness, expected', [
    ({'passed': False, 'rejectionReasons': ['source_support_contact_evidence_unavailable']}, 'incomplete'),
    ({'passed': False, 'status': 'incomplete', 'rejectionReasons': ['source_support_contact_evidence_incomplete']}, 'incomplete'),
    ({'passed': False, 'status': 'contradictory', 'rejectionReasons': ['source_support_contact_evidence_conflict']}, 'incomplete'),
    ({'passed': False, 'status': 'contradictory', 'rejectionReasons': ['source_support_observation_invalid']}, 'incomplete'),
])
def test_source_support_readiness_keeps_observer_conflicts_in_retained_source_review(readiness, expected):
    route, _reasons = wave.source_support_readiness_route(readiness)
    assert route == expected


@pytest.mark.parametrize(('unknown_sample', 'coarse_ready', 'expected_observer_calls'), [
    (True, False, 1),
    (True, True, 1),
    (False, True, 0),
])
def test_timed_contact_observation_persists_exact_cut_evidence_before_reconstruction(
        tmp_path, monkeypatch, unknown_sample, coarse_ready, expected_observer_calls):
    import hashlib
    import cv2
    import numpy as np
    from exercise_motion_pkg import body_support_observation as support_observation
    from exercise_motion_pkg import foot_contact_observation
    from exercise_motion_pkg import support_geometry

    class Session:
        def __init__(self, request): pass
        def set_candidate_deadline(self, deadline, *, on_wait=None, wait_remaining=None): pass
        def caption_images(self, **kwargs):
            sample_ids = kwargs['response_schema']['properties']['samples']['items']['properties']['sampleId']['enum']
            samples = [
                {'sampleId': sample_id, 'contactState': 'full_sole',
                 'surface': 'ground', 'visible': True}
                for sample_id in sample_ids
            ]
            return json.dumps({'samples': samples})
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    candidate = bake.RankedCandidate(
        exercise_index=0, candidate_rank=0, exercise_id='carry',
        exercise_name='Dumbbell Overhead Carry', exercise_slug='carry',
        candidate={'videoId': 'carry-timeline', 'title': 'Carry'},
    )
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path / 'carry',
        body_model_root=None, fallback_candidates=0, max_final_output_rejections=0,
    )
    item = wave.StagedWaveItem('carry', 'Dumbbell Overhead Carry', request)
    candidate_workspace = request.workspace / candidate.workspace_slug
    validation_path = candidate_workspace / 'segment_detection' / 'exact_source_phase_validation.json'
    source_path = tmp_path / 'selected.mp4'
    source_path.write_bytes(b'exact selected cut for timeline')
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_pose = {
        'coordinateSpace': 'normalized_image_xy', 'sourceTimeOriginSec': 0.,
        'frames': [
            {'sourceTimeSec': index * .5,
             'joints': {'left_ankle': [.35, .82], 'right_ankle': [.65, .82],
                        'left_hip': [.4, .5], 'right_hip': [.6, .5], 'nose': [.5, .1]},
             'jointConfidence': {'left_ankle': .95, 'right_ankle': .95}}
            for index in range(7)
        ],
    }
    source_pose_reference = {'sourceVideoSha256': digest, 'pose': source_pose}
    evidence = {
        'sourceVideoSha256': digest,
        'footPatchEvidence': {
            'sourceVideoSha256': digest,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceTimeOriginSec': 0.,
            'sourceTimesSec': [index * .5 for index in range(7)],
            'policyVersion': foot_contact_observation.POLICY_VERSION,
            'feet': {'left': {'states': (
                ['unknown'] + ['full_sole'] * 6 if unknown_sample else ['full_sole'] * 7
            )}},
        },
        'feet': {'left': {'contactIntervals': [{
            'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
            'sourceStartTimeSec': 0., 'sourceEndTimeSec': 3.,
        }]}},
        'contacts': [],
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'policyVersion': support_observation.POLICY_VERSION,
            'sourceVideoSha256': digest,
            'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'},
        },
    }
    validation_path.parent.mkdir(parents=True)
    validation_path.write_text(json.dumps({'metrics': {
        'sourceVideoSha256': digest,
        'sourceFootSupportEvidence': evidence,
    }}), encoding='utf-8')

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, '_wave_candidates_for_item', lambda _item: [candidate])
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **_kwargs: None)
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
                        lambda *_args, **_kwargs: {'eligible': True, 'portfolioSize': 1})
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate', lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(wave, 'prepare_candidate_input_video', lambda *_args, **_kwargs: source_path)
    monkeypatch.setattr(wave, 'review_prepared_source', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bake, 'load_verified_source_pose_reference', lambda *_args: source_pose)
    monkeypatch.setattr(support_observation, 'source_support_observation_needed', lambda *_args: False)

    class Capture:
        def __init__(self, _path): self.position = 0
        def get(self, prop):
            return {cv2.CAP_PROP_FPS: 30., cv2.CAP_PROP_FRAME_COUNT: 91}.get(prop, 0.)
        def set(self, prop, value): self.position = int(value); return True
        def read(self): return True, np.zeros((240, 320, 3), dtype=np.uint8)
        def release(self): pass

    monkeypatch.setattr(cv2, 'VideoCapture', Capture)

    readiness_calls = []
    def readiness(current_evidence):
        readiness_calls.append(current_evidence)
        timeline = (current_evidence.get('bodySupportObservation') or {}).get('contactTimeline')
        if coarse_ready or (isinstance(timeline, dict) and timeline.get('status') == 'observed'):
            return {'status': 'ready', 'passed': True, 'rejectionReasons': []}
        return {'status': 'incomplete', 'passed': False, 'unresolvedSides': ['left'],
                'rejectionReasons': ['source_support_contact_evidence_incomplete']}

    monkeypatch.setattr(support_geometry, 'pre_reconstruction_source_support_readiness', readiness)
    observer_calls = []
    original_observer = support_observation.observe_foot_contact_timeline
    def observe_timeline(*args, **kwargs):
        observer_calls.append(args)
        assert args[1] == source_pose_reference
        return original_observer(*args, **kwargs)

    monkeypatch.setattr(support_observation, 'observe_foot_contact_timeline', observe_timeline)
    generate_calls = []
    def generate(*_args, **_kwargs):
        generate_calls.append(True)
        persisted = bake.load_pre_reconstruction_exact_source_phase_metrics(candidate_workspace)
        persisted_evidence = persisted['sourceFootSupportEvidence']
        states = persisted_evidence['footPatchEvidence']['feet']['left']['states']
        assert states == (['unknown'] + ['full_sole'] * 6 if unknown_sample
                          else ['full_sole'] * 7)
        timeline = (persisted_evidence.get('bodySupportObservation') or {}).get('contactTimeline')
        if expected_observer_calls:
            assert timeline['status'] == 'observed'
            assert timeline['sourceVideoSha256'] == digest
            assert timeline['samples']
            assert timeline['samples'][0]['sampleId'] == 'contact-left-pose-0'
        else:
            assert timeline is None
        return SimpleNamespace(reconstruction_cache_status='generated', reconstruction_results_pkl=None)

    monkeypatch.setattr(wave, 'generate_candidate_motion', generate)
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline', lambda *_args, **_kwargs: {'selected': None})

    report = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / 'wave', wave_id='exact-contact-timeline',
    )

    assert len(observer_calls) == expected_observer_calls, report['items'][0]['source']
    assert len(readiness_calls) == (2 if expected_observer_calls else 1)
    assert generate_calls == [True], (report['items'][0]['source'], report['items'][0]['reconstruction'])


def test_contact_timeline_repair_identity_tracks_crop_and_coarse_evidence_not_its_result(monkeypatch):
    from exercise_motion_pkg import body_support_observation

    evidence = {'sourceVideoSha256': 'abc', 'contacts': [{'sourceTimeSec': 1.0}],
                'bodySupportObservation': {
                    'status': 'observed', 'policyVersion': body_support_observation.POLICY_VERSION,
                    'observation': {'leftFoot': 'unknown'},
                    'contactTimeline': {'status': 'unknown'},
                }}
    original = wave._contact_timeline_repair_key('abc', {'frames': [1]}, evidence)
    changed_result = {**evidence, 'bodySupportObservation': {
        **evidence['bodySupportObservation'],
        'contactTimeline': {'status': 'observed', 'samples': []}}}
    assert wave._contact_timeline_repair_key('abc', {'frames': [1]}, changed_result) == original
    changed_input = {**evidence, 'contacts': [{'sourceTimeSec': 2.0}]}
    assert wave._contact_timeline_repair_key('abc', {'frames': [1]}, changed_input) != original
    changed_coarse = {**evidence, 'bodySupportObservation': {
        **evidence['bodySupportObservation'],
        'observation': {'leftFoot': 'stationary_full_sole'},
    }}
    assert wave._contact_timeline_repair_key('abc', {'frames': [1]}, changed_coarse) != original
    monkeypatch.setattr(body_support_observation, 'CONTACT_TIMELINE_CROP_POLICY', 'new-crop-policy')
    assert wave._contact_timeline_repair_key('abc', {'frames': [1]}, evidence) != original


@pytest.mark.parametrize('scenario', ['unavailable', 'invalid', 'expired', 'contradictory'])
def test_source_support_failure_routes_without_weakening_or_restarting_turn(tmp_path, monkeypatch, scenario):
    import hashlib
    from exercise_motion_pkg import body_support_observation as support_observation
    from exercise_motion_pkg import foot_contact_observation
    from exercise_motion_pkg import support_geometry

    class Session:
        def __init__(self, request): pass
        def set_candidate_deadline(self, deadline, *, on_wait=None, wait_remaining=None): pass
        def caption_images(self, **kwargs): return '{}'
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    candidates = [
        bake.RankedCandidate(
            exercise_index=0, candidate_rank=rank, exercise_id='carry',
            exercise_name='Dumbbell Overhead Carry', exercise_slug='carry',
            candidate={'videoId': f'carry-source-{suffix}', 'title': f'Carry {suffix}'},
        )
        for rank, suffix in enumerate(('a', 'b'))
    ]
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path / 'carry',
        body_model_root=None, fallback_candidates=0, max_final_output_rejections=0,
        source_review_timeout_seconds=1e-9 if scenario == 'expired' else 180.0,
    )
    item = wave.StagedWaveItem('carry', 'Dumbbell Overhead Carry', request)
    source_paths = {}
    source_evidence_by_slug = {}
    for candidate in candidates:
        path = tmp_path / f'{candidate.video_id}.mp4'
        path.write_bytes(candidate.video_id.encode('utf-8'))
        source_paths[candidate.video_id] = path
        source_evidence_by_slug[candidate.workspace_slug] = {
            'candidateVideoId': candidate.video_id,
            'footPatchEvidence': {
                'available': True,
                'policyVersion': foot_contact_observation.POLICY_VERSION,
            },
            'contacts': ([{
                'jointName': 'right_foot', 'contactState': 'full_sole',
                'contactMotion': 'stationary', 'source': 'observed_foot_patch',
            }] if candidate is candidates[1] else []),
        }

    monkeypatch.setattr(wave, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(wave, '_wave_candidates_for_item', lambda _item: candidates)
    monkeypatch.setattr(wave, 'build_exercise_motion_contract_resolver', lambda **_kwargs: None)
    monkeypatch.setattr(wave, 'first_attempt_readiness_assessment',
                        lambda *_args, **_kwargs: {'eligible': True, 'portfolioSize': 1})
    monkeypatch.setattr(wave, 'evaluate_source_candidate_gate',
                        lambda *_args, **_kwargs: {'passed': True})
    monkeypatch.setattr(wave, 'prepare_candidate_input_video',
                        lambda candidate, **_kwargs: source_paths[candidate.video_id])
    monkeypatch.setattr(wave, 'review_prepared_source', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bake, 'load_pre_reconstruction_exact_source_phase_metrics',
                        lambda workspace: {'sourceFootSupportEvidence': source_evidence_by_slug[workspace.name]})
    monkeypatch.setattr(bake, 'load_verified_source_pose_reference', lambda *_args: None)
    monkeypatch.setattr(support_observation, 'source_support_observation_needed', lambda *_args: True)

    if scenario == 'contradictory':
        def conflicting_observers(_evidence):
            return {
                'required': True, 'available': False, 'evaluated': True, 'passed': False,
                'status': 'incomplete', 'unresolvedSides': ['right'],
                'rejectionReasons': ['source_support_contact_evidence_conflict'],
            }
        monkeypatch.setattr(support_geometry, 'pre_reconstruction_source_support_readiness',
                            conflicting_observers)

    def observe_body_support(video_path, *_args, **_kwargs):
        if scenario == 'invalid':
            right_foot = 'ambiguous'
        else:
            right_foot = 'stationary_full_sole'
        return {
            'status': 'observed',
            'source': 'exact_source_visual_support_observation',
            'policyVersion': support_observation.POLICY_VERSION,
            'sourceVideoSha256': hashlib.sha256(video_path.read_bytes()).hexdigest(),
            'observation': {'rightFoot': right_foot, 'rightFootSurface': 'ground'},
        }

    monkeypatch.setattr(support_observation, 'observe_body_support', observe_body_support)
    monkeypatch.setattr(wave, 'generate_candidate_motion', lambda *_args, **_kwargs: SimpleNamespace(
        reconstruction_cache_status='generated', reconstruction_results_pkl=None,
    ))
    monkeypatch.setattr(wave, 'run_bake_and_rank_pipeline', lambda *_args, **_kwargs: {'selected': None})

    report = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / f'wave-{scenario}', wave_id=f'support-route-{scenario}',
    )
    source = report['items'][0]['source']
    attempts = source['attempts']

    if scenario == 'contradictory':
        assert [attempt['status'] for attempt in attempts] == ['needs_source_review']
        assert attempts[0]['failureOwner'] == 'source_evidence'
        assert attempts[0]['reasonTags'] == ['source_support_contact_evidence_conflict']
        assert source['failureReason'] == 'source_review_incomplete'
    elif scenario in {'unavailable', 'invalid'}:
        assert len(attempts) == 1
        assert attempts[0]['status'] == 'needs_source_review'
        expected_reason = (
            'source_support_contact_evidence_incomplete'
            if scenario == 'unavailable' else 'source_support_observation_invalid'
        )
        assert attempts[0]['reasonTags'] == [expected_reason]
        assert source['failureReason'] == 'source_review_incomplete'
    else:
        assert attempts == []
        assert source['failureReason'] == 'source_review_incomplete'
    assert all(attempt['videoId'] != candidates[1].video_id for attempt in attempts)


def test_cached_source_rejects_invalid_variant_contract(tmp_path):
    contract = contract_for(exercise('Barbell Push Jerk'))
    contract['requiredPhases'] = ['catch the barbell in a split stance']
    path = tmp_path / 'segment_selection.json'
    path.write_text(json.dumps({
        'sourceSelectionPolicyVersion': bake.SOURCE_SELECTION_POLICY_VERSION,
        'preReconstructionSourceValidationEnabled': True, 'exerciseMotionContractEnabled': True,
        'exerciseMotionContract': contract,
        'exactSourcePhaseValidation': {'passed': True,
            'validationPolicyVersion': bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION},
    }))
    assert not bake.cached_source_selection_matches_validation_mode(path,
        pre_reconstruction_source_validation=True, exercise_motion_contract_enabled=True)


@pytest.mark.parametrize('contract', [None, {'status': 'failed'}, {'status': 'generated', 'exerciseName': 'Wrong exercise'}])
def test_source_preparation_blocks_unusable_contract_before_review(tmp_path, monkeypatch, contract):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source')
    monkeypatch.setattr(bake, 'copy_or_download_candidate_source', lambda *a, **k: source)
    candidate = bake.RankedCandidate(exercise_index=0, candidate_rank=0,
        exercise_id='press', exercise_name='Press', exercise_slug='press', candidate={'videoId': 'video'})
    request = bake.BakeAndRankRequest(candidates_json=tmp_path / 'candidates.json',
        workspace=tmp_path, body_model_root=None,
        pre_reconstruction_source_validation=True, exercise_motion_contract_enabled=True)
    with pytest.raises(bake.ExerciseMotionContractRejected):
        bake.prepare_candidate_input_video(candidate, request=request,
            source_cut_caption_images=lambda **k: pytest.fail('invalid contract reached VLM'),
            exercise_motion_contract_resolver=lambda _: contract)
    assert source.read_bytes() == b'source'


def test_incomplete_tracking_and_invalid_contract_do_not_retry_infrastructure():
    assert wave.wave_retry_disposition({"reconstruction": {"attempts": [
        {"status": "rejected_incomplete_reconstruction_tracking"}]}}) == "next_source"
    assert wave.wave_retry_disposition({"source": {"failureReason": "exercise_contract_invalid"}}) == "repair_contract"
    assert wave.wave_retry_disposition({"source": {"failureReason": "needs_definition_review"}}) == "needs_definition_review"


def test_wave_routes_failures_to_the_stage_that_owns_them():
    deferred = {"source": {"failureReason": "source_turn_deferred"}}
    assert wave.wave_retry_disposition(deferred) == "continue_source"

    support_repair = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "reasons": ["source_confirmed_support_unrepaired", "source_confirmed_baseline_support_drift"],
        }],
    }}
    assert wave.wave_retry_disposition(support_repair) == "retry_processing"

    missing_contact_evidence = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "reasons": ["source_support_contact_evidence_unavailable"],
        }],
    }}
    assert wave.wave_retry_disposition(missing_contact_evidence) == "retry_review"
    incomplete_contact_evidence = {"finalValidation": {
        "status": "incomplete_processing",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "reasons": ["source_support_contact_evidence_incomplete"],
        }],
    }}
    assert wave.wave_retry_disposition(incomplete_contact_evidence) == "retry_review"
    contradictory_contact_evidence = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "reasons": ["source_support_contact_evidence_conflict"],
        }],
    }}
    assert wave.wave_retry_disposition(contradictory_contact_evidence) == "retry_review"
    invalid_support_observation = {"finalValidation": {
        "status": "incomplete_processing",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "reasons": ["source_support_observation_invalid"],
        }],
    }}
    assert wave.wave_retry_disposition(invalid_support_observation) == "retry_review"

    raw_reconstruction_failure = {"reconstruction": {"attempts": [
        {"status": "rejected_raw_reconstruction_validation"},
    ]}}
    assert wave.wave_retry_disposition(raw_reconstruction_failure) == "retry_processing"

    bad_source_tracking = {"reconstruction": {"attempts": [
        {"status": "rejected_incomplete_reconstruction_tracking"},
    ]}}
    assert wave.wave_retry_disposition(bad_source_tracking) == "next_source"


def test_browser_bake_candidate_exception_routes_by_determinism_and_owner(monkeypatch):
    deterministic = bake._candidate_processing_exception_metadata(
        ValueError("cyclic interval mismatch"), "browser_bake")
    browser_bake_failure = {
        "selected": None,
        "candidateResults": [{
            "status": "failed",
            "failureStage": "browser_bake",
            "failureOwner": deterministic["failureOwner"],
            "failureExceptionType": deterministic["exceptionType"],
            "processingRetryPolicy": deterministic["processingRetryPolicy"],
            "failures": [{
                "reason": "candidate_failed",
                "failureStage": "browser_bake",
                **deterministic,
                "message": "ValueError: cyclic interval mismatch",
            }],
        }],
        "timings": {},
    }
    recovered = {"selected": {"candidate": {"videoId": "approved-A"}},
                 "candidateResults": [], "timings": {}}
    attempts = iter((browser_bake_failure,))
    calls = []
    monkeypatch.setattr(
        "exercise_motion_pkg.stage_cache.advance_processing_attempt",
        lambda: None,
    )

    def operation():
        result = next(attempts)
        calls.append(result)
        return result

    final = wave.finalize_with_bounded_processing_retry(operation)

    assert len(calls) == 1
    assert final["candidateResults"][0]["status"] == "needs_motion_processing"
    assert final["processingRetrySkippedReason"] == "deterministic_browser_bake_failure"
    assert final["processingAttempts"][0]["retryDisposition"] == "retry_processing"

    # Recognized transient browser infrastructure still receives its one
    # bounded retry on the exact retained candidate.
    transient = bake._candidate_processing_exception_metadata(
        TimeoutError("browser worker timed out"), "browser_bake")
    transient_failure = {
        **browser_bake_failure,
        "candidateResults": [{
            **browser_bake_failure["candidateResults"][0],
            "failureOwner": transient["failureOwner"],
            "failureExceptionType": transient["exceptionType"],
            "processingRetryPolicy": transient["processingRetryPolicy"],
            "failures": [{"reason": "candidate_failed", **transient}],
        }],
    }
    transient_calls = iter((transient_failure, recovered))
    transient_run_count = []
    transient_final = wave.finalize_with_bounded_processing_retry(
        lambda: (transient_run_count.append(True), next(transient_calls))[1]
    )
    assert len(transient_run_count) == 2
    assert transient_final["selected"]["candidate"]["videoId"] == "approved-A"

    # Explicit source/review ownership is preserved; an unclassified browser
    # exception stays on the infrastructure route instead of local replay.
    for owner, expected in (("source", "next_source"), ("review", "retry_review"),
                            (None, "retry_infrastructure")):
        exception_meta = bake._candidate_processing_exception_metadata(
            RuntimeError("unexpected browser failure"), "browser_bake")
        diagnostic = {
            "status": "failed",
            "stage": "browser_bake",
            "failureOwner": owner,
            "exceptionType": exception_meta["exceptionType"],
            "reasons": ["candidate_failed"],
            "failureOwnersByReason": {
                "candidate_failed": [owner] if owner else [],
            },
        }
        state = {"finalValidation": {
            "status": "no_selection",
            "candidateDiagnostics": [diagnostic],
        }}
        assert wave.wave_retry_disposition(state) == expected


def test_wave_progress_admission_stops_same_terminal_and_bounds_transient_retries():
    progress = {"elapsedSeconds": 20.0, "work": {
        "stable-input": {"attempts": 1, "terminal": True},
        "transient-input": {"attempts": 1, "terminal": False},
    }}
    assert wave.wave_progress_admission(
        progress, "stable-input", exercise_timeout_seconds=1200,
    ) == (False, "same_input_terminal_decision")
    assert wave.wave_progress_admission(
        progress, "transient-input", exercise_timeout_seconds=1200,
    ) == (True, None)
    assert wave.wave_progress_admission(
        {"elapsedSeconds": 1200.0, "work": {}},
        "new-input", exercise_timeout_seconds=1200,
    ) == (False, "exercise_turn_budget_exhausted")
    assert wave.wave_progress_admission(
        {"elapsedSeconds": 20.0, "work": {
            "transient-input": {"attempts": 2, "terminal": False},
        }},
        "transient-input", exercise_timeout_seconds=1200,
    ) == (False, "same_input_transient_retry_budget_exhausted")


def test_wave_progress_time_uses_interval_union_and_excludes_bounded_wait():
    assert wave._interval_union_seconds([(0.0, 10.0), (5.0, 15.0)]) == 15.0
    wall_overlap = wave._interval_overlap_seconds((0.0, 10.0), [(5.0, 15.0)])
    charged_overlap = min(max(0.0, wall_overlap - 2.0), 10.0)
    assert charged_overlap == 3.0
    active_delta, wait_delta = wave._source_turn_wave_deltas(
        active_seconds=500.0,
        prior_active_seconds=400.0,
        excluded_wait_seconds=500.0,
        prior_excluded_wait_seconds=450.0,
    )
    # Prior-turn wait must not be subtracted again from this wave's overlap.
    assert (active_delta, wait_delta) == (100.0, 50.0)
    current_overlap = min(max(0.0, 80.0 - wait_delta), active_delta)
    assert current_overlap == 30.0
    progress = {
        "sourceSeconds": 10.0,
        "waves": {"wave-1": {"processingSeconds": 5.0}},
    }
    assert wave._refresh_wave_progress_elapsed(progress) == 15.0


def test_remaining_exercise_budget_uses_original_limit_across_stages(tmp_path):
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path / "press",
        body_model_root=None,
        exercise_timeout_seconds=1200.0,
    )
    item = wave.StagedWaveItem("press", "Press", request)
    configured_limit = 1200.0

    source_item = wave._request_with_remaining_exercise_budget(
        item,
        {"elapsedSeconds": 450.0},
        configured_limit_seconds=configured_limit,
    )
    assert source_item.request.exercise_timeout_seconds == 750.0

    final_item = wave._request_with_remaining_exercise_budget(
        source_item,
        {"elapsedSeconds": 550.0},  # 450 s prior work + 100 s this wave
        configured_limit_seconds=configured_limit,
    )
    assert final_item.request.exercise_timeout_seconds == 650.0


def test_source_turn_budget_uses_original_exercise_cap_before_global_deadline(tmp_path):
    import time
    from exercise_motion_pkg.source_turn_budget import (
        SOURCE_TURN_BUDGET_POLICY_VERSION,
        _SourceTurnBudget,
    )

    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=tmp_path / "press",
        body_model_root=None,
        source_review_timeout_seconds=180.0,
        exercise_timeout_seconds=1200.0,
    )
    started_at = time.perf_counter()
    budget = _SourceTurnBudget(
        request,
        {
            "sourceTurnBudgetPolicyVersion": SOURCE_TURN_BUDGET_POLICY_VERSION,
            "sourceTurnElapsedSeconds": 100.0,
        },
        started_at=started_at,
    )
    wave._cap_source_turn_budget_to_exercise(
        budget,
        started_at=started_at,
        configured_exercise_limit_seconds=1200.0,
        exercise_elapsed_seconds=1100.0,
    )

    assert budget.deadline is not None
    assert 79.9 <= budget.deadline - started_at <= 80.1


def test_source_cursor_after_final_candidate_failure_dispatches_alternate_candidate(tmp_path, monkeypatch):
    class Session:
        def __init__(self, request): pass
        def caption_images(self, **kwargs): return "{}"
        def close(self, **kwargs): pass
        def run_without_llama_overlap(self, operation): return operation()

    monkeypatch.setattr(wave, "LazyLlamaCppVisionSession", Session)
    monkeypatch.setattr(wave, "build_exercise_motion_contract_resolver", lambda **_kwargs: None)
    monkeypatch.setattr(wave, "evaluate_source_candidate_gate", lambda *_args, **_kwargs: {"passed": True})
    monkeypatch.setattr(wave, "first_attempt_readiness_assessment",
                        lambda *_args, **_kwargs: {"eligible": True, "portfolioSize": 1})
    workspace = tmp_path / "exercise"
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / "candidates.json",
        workspace=workspace,
        body_model_root=None,
        fallback_candidates=0,
        max_final_output_rejections=0,
        authoritative_exercise_motion_context={"motionContractVersion": 1},
    )
    item = wave.StagedWaveItem("press", "Press", request, "run-1", "turn-1")
    candidates = [
        bake.RankedCandidate(
            exercise_index=0,
            candidate_rank=index,
            exercise_id="press",
            exercise_name="Press",
            exercise_slug="press",
            candidate={"videoId": video_id},
        )
        for index, video_id in enumerate(("video-A", "video-B"))
    ]
    monkeypatch.setattr(wave, "_wave_candidates", lambda _request: candidates)
    prepared_ids = []
    generated_ids = []

    def prepare(candidate, **_kwargs):
        prepared_ids.append(candidate.video_id)
        output = workspace / candidate.workspace_slug / "input" / "selected_segment.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(candidate.video_id.encode())
        return output

    monkeypatch.setattr(wave, "prepare_candidate_input_video", prepare)
    def generate(candidate, *_args, **_kwargs):
        generated_ids.append(candidate.video_id)
        return SimpleNamespace(
            reconstruction_cache_status="generated",
            reconstruction_results_pkl=None,
        )

    monkeypatch.setattr(wave, "generate_candidate_motion", generate)

    def final_result(*_args, prepared_candidates, **_kwargs):
        candidate = prepared_candidates[0]
        if candidate.video_id == "video-A":
            return {
                "selected": None,
                "candidateResults": [{
                    "candidate": {"videoId": "video-A"},
                    "candidateWorkspace": str(workspace / candidate.workspace_slug),
                    "status": "rejected_baked_motion_validation",
                    "failureOwner": "motion_output",
                    "failures": [{
                        "reason": "supported_material_sole_pitch_unavailable",
                        "failureOwner": "motion_output",
                    }],
                }],
                "timings": {},
            }
        return {
            "selected": {
                "candidate": {"videoId": "video-B"},
                "selectedWearSkeletonPath": str(tmp_path / "selected.json"),
            },
            "candidateResults": [],
            "timings": {},
        }

    monkeypatch.setattr(wave, "run_bake_and_rank_pipeline", final_result)
    first = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / "wave-1", wave_id="wave-1",
    )
    first_item = first["items"][0]
    assert first_item["retryDisposition"] == "repair_evidence"
    assert first_item["source"]["nextCandidateKey"] == wave._candidate_key(candidates[1])
    progress_receipt = json.loads((workspace / "wave_progress.json").read_text(encoding="utf-8"))
    assert len(progress_receipt["work"]) == 1
    assert next(iter(progress_receipt["work"].values()))["terminal"] is True
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"exercises": [{
        "id": "press",
        "name": "Press",
        "motionContext": request.authoritative_exercise_motion_context,
    }]}), encoding="utf-8")
    from exercise_motion_pkg.source_turn_budget import write_source_turn_cursor_from_wave_state
    write_source_turn_cursor_from_wave_state(
        workspace / "source_turn_resume.json",
        wave_state=first_item,
        exercise_plan_path=plan_path,
        source_review_turn_id="turn-1",
        transition="next_source_candidate",
    )

    second = wave.run_staged_bake_wave(
        [item], workspace=tmp_path / "wave-2", wave_id="wave-2",
    )
    assert prepared_ids == ["video-A", "video-B"]
    assert second["items"][0]["status"] == "completed"
    assert second["items"][0]["finalValidation"]["candidateKey"] == wave._candidate_key(candidates[1])

    # A third distinct wave must stop before source review/reconstruction when
    # the exact terminal candidate bytes and evidence are unchanged.
    prepared_before_replay = list(prepared_ids)
    generated_before_replay = list(generated_ids)
    wave.run_staged_bake_wave(
        [item], workspace=tmp_path / "wave-3", wave_id="wave-3",
    )
    assert prepared_ids == prepared_before_replay
    assert generated_ids == generated_before_replay

    # Changing the retained cut changes the content-bound decision identity,
    # so the candidate is eligible for a fresh bounded attempt.
    (workspace / candidates[1].workspace_slug / "input" / "selected_segment.mp4").write_bytes(
        b"video-B-changed-cut"
    )
    wave.run_staged_bake_wave(
        [item], workspace=tmp_path / "wave-4", wave_id="wave-4",
    )
    assert prepared_ids == ["video-A", "video-B", "video-B"]


@pytest.mark.parametrize("reason", [
    "materialized_source_pose_fidelity_unavailable",
    "supported_material_sole_pitch_unavailable",
])
def test_missing_material_output_evidence_retries_local_processing_only_when_motion_owned(reason):
    owned = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "failureOwner": "motion_output",
            "reasons": [reason],
            "failureOwnersByReason": {reason: ["motion_output"]},
        }],
    }}
    assert wave.wave_retry_disposition(owned) == "repair_evidence"

    source_owned = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "failureOwner": "source",
            "reasons": [reason],
            "failureOwnersByReason": {reason: ["source"]},
        }],
    }}
    assert wave.wave_retry_disposition(source_owned) == "next_source"

    unowned = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "reasons": [reason],
            "failureOwnersByReason": {},
        }],
    }}
    assert wave.wave_retry_disposition(unowned) == "next_source"

    conflicting = {"finalValidation": {
        "status": "no_selection",
        "candidateDiagnostics": [{
            "status": "rejected_baked_motion_validation",
            "failureOwner": "motion_output",
            "reasons": [reason],
            "failureOwnersByReason": {reason: ["source"]},
        }],
    }}
    assert wave.wave_retry_disposition(conflicting) == "next_source"


def test_contract_generation_repairs_invalid_variant_before_accepting(monkeypatch):
    entry = exercise("Barbell Push Jerk")
    valid = contract_for(entry)
    bad = {**valid, "advisoryText": "bad variant"}
    drafts = iter([bad, valid])
    prompts = []
    monkeypatch.setattr(bake, "normalize_exercise_motion_contract_response", lambda *a, **k: next(drafts))
    monkeypatch.setattr(bake, "exercise_motion_contract_is_usable", lambda c, **k: c is valid)
    monkeypatch.setattr(bake, "exercise_motion_contract_has_specific_topology", lambda c: True)
    monkeypatch.setattr(bake, "exercise_motion_contract_unusable_reason", lambda c, **k: "split catch contradicts non-split variant")
    def caption(**kwargs):
        prompts.append(kwargs["prompt"])
        return "{}"
    result, _, error = bake.generate_specific_exercise_motion_contract(
        exercise=entry, caption_images=caption, source="test", request_timeout_seconds=10)
    assert result is valid and error is None
    assert len(prompts) == 2
    assert "split catch contradicts non-split variant" in prompts[1]


def test_incomplete_tracking_is_classified_before_retry_selection():
    error = wave.IncompleteReconstructionTrackingError("lost endpoint", requested_start_seconds=0,
        requested_end_seconds=6.85, retained_start_seconds=0, retained_end_seconds=4)
    status = wave.generation_failure_status(error)
    assert status == "rejected_incomplete_reconstruction_tracking"
    assert wave.wave_retry_disposition({"reconstruction": {"attempts": [{"status": status}]}}) == "next_source"
    assert wave.generation_failure_status(RuntimeError("browser crashed")) == "failed"
