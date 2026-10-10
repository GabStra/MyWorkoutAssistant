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
        max_final_output_rejections=0)) for name in ['a', 'b', 'slow'] + [f'unavailable_{i}' for i in range(unavailable_count)]]
    candidates = {item.exercise_id: [bake.RankedCandidate(
        exercise_index=0, candidate_rank=index, exercise_id=item.exercise_id,
        exercise_name=item.exercise_name, exercise_slug=item.exercise_id,
        candidate={'videoId': f'{item.exercise_id}-{index}'})
        for index in range(0 if item.exercise_id.startswith('unavailable_') else 2 if item.exercise_id == 'slow' else 1)] for item in items}
    monkeypatch.setattr(wave, '_wave_candidates', lambda request: candidates[request.workspace.name])
    ready = threading.Event()
    usable = []
    unavailable = []
    unavailable_done = threading.Event()
    if not unavailable_count:
        unavailable_done.set()
    def progress(message):
        if message.startswith('Source review: unavailable_'):
            unavailable.append(message)
            if len(unavailable) == unavailable_count:
                unavailable_done.set()
        if '1 usable source(s)' in message:
            usable.append(message)
            if len(usable) == 2: ready.set()
    attempted = []
    def prepare(candidate, **kwargs):
        attempted.append(candidate.video_id)
        if candidate.video_id == 'slow-0':
            assert ready.wait(3)
            assert unavailable_done.wait(3)
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
    assert report['metrics']['generationCpuWorkers'] == 2
    assert sum(x['status'] == 'completed' for x in report['items']) == 2
    attempted.clear()
    wave.run_staged_bake_wave([items[2]], workspace=tmp_path / 'wave2', wave_id='second')
    assert attempted == ['slow-1']
    assert not (items[2].request.workspace / 'source_turn_resume.json').exists()


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
