import httpx
import pytest
from contextlib import contextmanager

from exercise_motion_pkg.segment_detection import LlamaCppVisionClient
from exercise_motion_pkg.vlm_errors import CriticalVlmInteractionError


def test_vision_sends_source_evidence_schema(monkeypatch):
    from exercise_motion_pkg.bake_and_rank import call_caption_images_json
    client = LlamaCppVisionClient("http://127.0.0.1:8090", "test", max_recovery_retries=0)
    schema = {"type": "object", "additionalProperties": False, "properties": {}}
    requests = []
    def post(**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200, json={"choices": [{"message": {"content": '{}'}}]})
    monkeypatch.setattr(client, '_post_chat_completion', post)
    try:
        assert call_caption_images_json(client.caption_images, frame_paths=[], prompt='Evidence only.',
            response_schema=schema, disable_reasoning=True) == '{}'
        assert requests[0]['response_format'] == {'type': 'json_schema', 'json_schema': {
            'name': 'source_evidence', 'strict': True, 'schema': schema}}
        assert requests[0]['chat_template_kwargs'] == {'enable_thinking': False}
    finally:
        client.close()


@pytest.mark.parametrize("status,body,removed", [
    (400, "unsupported response_format", "response_format"),
    (422, "unknown reasoning_format parameter", "reasoning_format"),
    (400, "Failed to initialize samplers: Unexpected empty grammar stack after accepting piece: <think> (248068)", "response_format"),
    (400, "request exceeds context size", None),
    (500, "server unavailable", None),
    (400, "unsupported chat_template_kwargs", None),
    (400, "invalid response_format schema", None),
])
def test_vision_fallback_preserves_thinking_control(monkeypatch, status, body, removed):
    client = LlamaCppVisionClient("http://127.0.0.1:8090", "test", max_recovery_retries=0)
    requests = []
    def post(**kwargs):
        requests.append(kwargs["json"])
        if len(requests) == 1:
            return httpx.Response(status, text=body)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})
    monkeypatch.setattr(client, "_post_chat_completion", post)
    monkeypatch.setattr(client, "_server_debug_snapshot", lambda: {"test": True})
    try:
        if removed:
            assert client.caption_images(frame_paths=[], prompt="Return JSON.") == '{"ok":true}'
            assert len(requests) == 2
            assert removed not in requests[1]
            assert requests[1] == {key: value for key, value in requests[0].items() if key != removed}
            assert requests[1]["chat_template_kwargs"] == {"enable_thinking": False}
        else:
            with pytest.raises(CriticalVlmInteractionError) as error:
                client.caption_images(frame_paths=[], prompt="Return JSON.")
            assert error.value.details["statusCode"] == status
            assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("spent,expected_calls", [(10.0, 1), (3.0, 2)])
def test_vision_recovery_uses_remaining_request_budget(monkeypatch, spent, expected_calls):
    from exercise_motion_pkg import segment_detection

    clock = [0.0]
    monkeypatch.setattr(segment_detection.time, "monotonic", lambda: clock[0])
    client = LlamaCppVisionClient("http://127.0.0.1:8090", "test")
    timeouts = []
    recoveries = []

    def post(**kwargs):
        timeouts.append(kwargs["timeout"])
        if len(timeouts) == 1:
            clock[0] += spent
            raise httpx.ReadTimeout("slow response")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(client, "_post_chat_completion", post)
    monkeypatch.setattr(client, "_server_debug_snapshot", lambda: {})
    monkeypatch.setattr(client, "_recover_after_vlm_failure",
                        lambda *args, **kwargs: recoveries.append(True) or {})
    try:
        if expected_calls == 1:
            with pytest.raises(CriticalVlmInteractionError) as error:
                client.caption_images(frame_paths=[], prompt="Return JSON.", request_timeout_seconds=10)
            assert error.value.details["requestBudgetExhausted"] is True
            assert recoveries == []
        else:
            assert client.caption_images(frame_paths=[], prompt="Return JSON.", request_timeout_seconds=10) == "{}"
            assert timeouts == [10, 7]
            assert recoveries == [True]
        assert len(timeouts) == expected_calls
    finally:
        client.close()


def test_vision_admission_wait_consumes_request_budget(monkeypatch):
    from exercise_motion_pkg import segment_detection

    clock = [0.0]
    monkeypatch.setattr(segment_detection.time, "monotonic", lambda: clock[0])

    @contextmanager
    def queued_scope(**kwargs):
        assert kwargs["timeout_seconds"] == 10
        clock[0] += 8
        yield

    monkeypatch.setattr(segment_detection, "shared_llama_request_scope", queued_scope)
    client = LlamaCppVisionClient("http://127.0.0.1:8090", "test")
    timeouts = []

    def post(**kwargs):
        timeouts.append(kwargs["timeout"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(client, "_post_chat_completion", post)
    try:
        assert client.caption_images(frame_paths=[], prompt="Return JSON.", request_timeout_seconds=10) == "{}"
        assert timeouts == [2]
    finally:
        client.close()
