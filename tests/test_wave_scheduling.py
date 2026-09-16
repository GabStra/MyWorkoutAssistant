import json
import threading
from types import SimpleNamespace
import pytest

from exercise_motion_pkg import wave_pipeline as wave
from exercise_motion_pkg import bake_and_rank as bake
from test_motion_review_improvements import contract_for, exercise


@pytest.mark.parametrize('statuses,expected_count,result', [
    (['failed'], 1, 'failed'),
    (['rejected_tracking_preflight'], 1, 'failed'),
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
        wham_repo_path=None, body_model_root=None, fallback_candidates=0,
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
        return SimpleNamespace(wham_cache_status='generated', wham_results_pkl=None)
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


def test_cached_source_rejects_invalid_variant_contract(tmp_path):
    contract = contract_for(exercise('Barbell Push Jerk'))
    contract['requiredPhases'] = ['catch the barbell in a split stance']
    path = tmp_path / 'segment_selection.json'
    path.write_text(json.dumps({
        'sourceSelectionPolicyVersion': bake.SOURCE_SELECTION_POLICY_VERSION,
        'preWhamSourceValidationEnabled': True, 'exerciseMotionContractEnabled': True,
        'exerciseMotionContract': contract,
        'exactSourcePhaseValidation': {'passed': True,
            'validationPolicyVersion': bake.EXACT_SOURCE_PHASE_VALIDATION_POLICY_VERSION},
    }))
    assert not bake.cached_source_selection_matches_validation_mode(path,
        pre_wham_source_validation=True, exercise_motion_contract_enabled=True)


@pytest.mark.parametrize('contract', [None, {'status': 'failed'}, {'status': 'generated', 'exerciseName': 'Wrong exercise'}])
def test_source_preparation_blocks_unusable_contract_before_review(tmp_path, monkeypatch, contract):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source')
    monkeypatch.setattr(bake, 'copy_or_download_candidate_source', lambda *a, **k: source)
    candidate = bake.RankedCandidate(exercise_index=0, candidate_rank=0,
        exercise_id='press', exercise_name='Press', exercise_slug='press', candidate={'videoId': 'video'})
    request = bake.BakeAndRankRequest(candidates_json=tmp_path / 'candidates.json',
        workspace=tmp_path, wham_repo_path=None, body_model_root=None,
        pre_wham_source_validation=True, exercise_motion_contract_enabled=True)
    with pytest.raises(bake.ExerciseMotionContractRejected):
        bake.prepare_candidate_input_video(candidate, request=request,
            source_cut_caption_images=lambda **k: pytest.fail('invalid contract reached VLM'),
            exercise_motion_contract_resolver=lambda _: contract)
    assert source.read_bytes() == b'source'


def test_incomplete_tracking_and_invalid_contract_do_not_retry_infrastructure():
    assert wave.wave_retry_disposition({"wham": {"attempts": [
        {"status": "rejected_incomplete_wham_tracking"}]}}) == "next_source"
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
    error = wave.IncompleteWhamTrackingError("lost endpoint", requested_start_seconds=0,
        requested_end_seconds=6.85, retained_start_seconds=0, retained_end_seconds=4)
    status = wave.generation_failure_status(error)
    assert status == "rejected_incomplete_wham_tracking"
    assert wave.wave_retry_disposition({"wham": {"attempts": [{"status": status}]}}) == "next_source"
    assert wave.generation_failure_status(RuntimeError("browser crashed")) == "failed"
