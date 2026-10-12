from types import SimpleNamespace

import httpx

from exercise_motion_pkg import fit_runtime, youtube
from exercise_motion_pkg.segment_detection import LlamaCppVisionClient
from exercise_motion_pkg.vlm_errors import CriticalVlmInteractionError


def test_repeated_bake_shares_fit_budget_until_retained_input_changes(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(fit_runtime, 'monotonic', lambda: clock[0])
    motion = tmp_path / 'motion.cleaned.json'
    motion.write_text('original')
    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=10) as session:
        assert session.remaining() == 10
        clock[0] = 8
    clock[0] = 50  # Time between attempts is not solver work.
    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=10) as session:
        assert session.remaining() == 2
        clock[0] = 52
    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=10) as session:
        assert session.remaining() == 0
    motion.write_text('new observed motion')
    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=10) as session:
        assert session.remaining() == 10


def test_loading_server_does_not_satisfy_attach_readiness(monkeypatch):
    ranker = object.__new__(youtube.LlamaCppVisionRanker)
    ranker.settings = SimpleNamespace(llama_cpp_base_url='http://127.0.0.1:8090')
    paths = []
    def get(url, **kwargs):
        paths.append(url)
        return httpx.Response(503 if url.endswith('/health') else 200, json={'data': []})
    monkeypatch.setattr(youtube.httpx, 'get', get)
    assert ranker._server_models_payload() is None
    assert paths == ['http://127.0.0.1:8090/health']


def test_recovery_waits_until_health_finishes_loading(monkeypatch):
    client = LlamaCppVisionClient('http://127.0.0.1:8090', 'test')
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(503 if len(calls) == 1 else 200)
    monkeypatch.setattr(client.client, 'get', get)
    monkeypatch.setattr('exercise_motion_pkg.segment_detection.time.sleep', lambda seconds: None)
    try:
        client._wait_for_chat_ready_after_recovery(CriticalVlmInteractionError('loading', interaction='test'))
        assert calls == ['http://127.0.0.1:8090/health'] * 2
    finally:
        client.close()


def test_loading_response_retries_same_request_without_server_recovery(monkeypatch):
    client = LlamaCppVisionClient('http://127.0.0.1:8090', 'test')
    posted = []
    def post(**kwargs):
        posted.append(kwargs['json'])
        return (httpx.Response(503, text='{"error":{"message":"Loading model"}}')
                if len(posted) == 1 else
                httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}]}))
    monkeypatch.setattr(client, '_post_chat_completion', post)
    monkeypatch.setattr(client, '_server_debug_snapshot', lambda: {})
    monkeypatch.setattr(client.client, 'get', lambda *args, **kwargs: httpx.Response(200))
    monkeypatch.setattr(client, '_recover_after_vlm_failure', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Loading must not restart the server')))
    try:
        assert client.caption_images(frame_paths=[], prompt='Return JSON.') == '{}'
        assert len(posted) == 2 and posted[0] == posted[1]
    finally:
        client.close()
