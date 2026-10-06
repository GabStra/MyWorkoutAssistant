import json
import threading
import sys
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import segment_detection as segment
from exercise_motion_pkg import youtube
from exercise_motion_pkg.revalidation_contracts import RevalidationContractCache, with_revalidation_contract
from exercise_motion_pkg.vlm_errors import CriticalVlmInteractionError
from test_motion_review_improvements import contract_for, exercise


def test_revalidation_wait_is_bounded_and_interruptible(monkeypatch):
    future = object()
    calls = []
    def fake_wait(pending, *, timeout, return_when):
        calls.append(timeout)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return set(), pending
    monkeypatch.setattr(bake, 'wait', fake_wait)
    with pytest.raises(KeyboardInterrupt):
        list(bake.interruptible_completed([future]))
    assert calls == [0.2, 0.2]


def test_closed_vlm_client_cannot_send_or_recover(monkeypatch):
    client = segment.LlamaCppVisionClient(base_url='http://unused', model='test')
    client.close()
    monkeypatch.setattr(client, '_recover_after_vlm_failure_when_idle',
        lambda *a, **k: pytest.fail('closed client attempted recovery'))
    with pytest.raises(RuntimeError, match='closed'):
        client._post_chat_completion()
    assert client._recover_after_vlm_failure(
        CriticalVlmInteractionError('timeout', interaction='test'),
        failed_client_generation=0)['cancelled']


def test_pose_release_drops_worker_models_before_emptying_allocator(monkeypatch):
    from exercise_motion_pkg import pose_prefilter as pose
    events = []
    cache = {'model': object()}
    monkeypatch.setattr(pose._YOLO_MODEL_THREAD_LOCAL, 'models', cache, raising=False)
    def collect():
        assert not cache
        events.append('collect')
    monkeypatch.setattr(pose.gc, 'collect', collect)
    cuda = SimpleNamespace(is_available=lambda: True,
        synchronize=lambda: events.append('synchronize'),
        empty_cache=lambda: events.append('empty'),
        ipc_collect=lambda: events.append('ipc'))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=cuda))
    pose.release_yolo_pose_cuda_memory()
    assert events == ['collect', 'synchronize', 'empty', 'ipc']


@pytest.mark.parametrize('fails', [False, True])
def test_exclusive_worker_releases_models_before_unlocking(tmp_path, monkeypatch, fails):
    session = bake.LazyLlamaCppVisionSession(bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json', workspace=tmp_path,
        wham_repo_path=None, body_model_root=None))
    monkeypatch.setattr(session, '_close_ranker_locked', lambda **kwargs: None)
    events = []
    def release():
        assert session._wham_active
        events.append('release')
    monkeypatch.setattr(session, '_release_cached_exclusive_models', release)
    def operation():
        events.append('operation')
        if fails:
            raise ValueError('operation failed')
        return 42
    if fails:
        with pytest.raises(ValueError, match='operation failed'):
            session.run_without_llama_overlap(operation)
    else:
        assert session.run_without_llama_overlap(operation) == 42
    assert events == ['operation', 'release']
    assert not session._wham_active


def test_revalidation_reuses_current_cache_with_matching_context(tmp_path):
    entry = exercise('Standing Cable Press')
    contract = contract_for(entry)
    contract['motionContext'] = {'equipment': 'cable'}
    (tmp_path / 'contract.json').write_text(json.dumps({
        'schemaVersion': youtube.EXERCISE_MOTION_CONTRACT_CACHE_VERSION, 'contract': contract}))
    (tmp_path / 'broken.json').write_text('{')
    cache = RevalidationContractCache(tmp_path)
    resolved = cache.resolve(entry.name, {'equipment': 'cable'})
    assert resolved is not None
    assert cache.resolve(entry.name, {'equipment': 'barbell'}) is None
    assert cache.resolve('Different Exercise', {'equipment': 'cable'}) is None
    old = {'candidate': {'exerciseMotionContract': {'contractPolicyVersion': 23}},
           'ranking': {'score': .9, 'payload': {'exerciseMotionContract': {'contractPolicyVersion': 23}}}}
    updated = with_revalidation_contract(old, resolved)
    assert updated['candidate']['exerciseMotionContract'] == resolved
    assert updated['ranking']['payload']['exerciseMotionContract'] == resolved
    assert old['candidate']['exerciseMotionContract']['contractPolicyVersion'] == 23


def test_recovery_does_not_probe_busy_inference_or_restart_healthy_server():
    ranker = youtube.LlamaCppVisionRanker.__new__(youtube.LlamaCppVisionRanker)
    ranker._server_recovery_lock = threading.Lock()
    ranker._server_models_payload = lambda: {'data': [{'id': 'model'}]}
    ranker._chat_completions_ready = lambda: pytest.fail('inference health probe would queue')
    ranker._stop_owned_llama_cpp_server = lambda: pytest.fail('healthy server restarted')
    ranker._recover_llama_cpp_server_after_vlm_failure()


def test_recovery_defers_while_peer_http_request_is_active(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    client = segment.LlamaCppVisionClient(base_url='http://unused', model='test')
    original = client.client
    def post(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return 'ok'
    monkeypatch.setattr(original, 'post', post)
    monkeypatch.setattr(client, '_recover_after_vlm_failure_when_idle', lambda *a, **k: pytest.fail('recovery interrupted peer'))
    worker = threading.Thread(target=client._post_chat_completion)
    worker.start()
    try:
        assert entered.wait(5)
        result = client._recover_after_vlm_failure(CriticalVlmInteractionError('timeout', interaction='test'), failed_client_generation=0)
        assert result['deferredForActiveRequests'] == 1
    finally:
        release.set()
        worker.join(5)
        client.close()
    assert not worker.is_alive()


def test_frame_capture_preserves_exception_and_does_not_return_empty(tmp_path, monkeypatch):
    html = tmp_path / 'interactive.html'
    skeleton = tmp_path / 'skeleton.json'
    html.write_text('fixture')
    skeleton.write_text('{}')
    item = bake.ReviewItem(exercise_index=0, candidate_rank=0, loop_index=0, exercise_name='Demo',
        candidate_title='Demo', candidate_workspace=tmp_path, preview_html_path=html,
        skeleton_path=skeleton, review_video_path=None, duration_sec=2, loop_start_seconds=0,
        loop_end_seconds=2, candidate={})
    def fail(**kwargs):
        raise RuntimeError('automation API missing')
    monkeypatch.setattr(bake, 'render_review_window_contact_sheet', fail)
    with pytest.raises(bake.ReviewFrameCaptureError, match='automation API missing') as error:
        bake.final_output_vlm_preview_contact_sheets(item, output_dir=tmp_path / 'review')
    assert isinstance(error.value.__cause__, RuntimeError)
