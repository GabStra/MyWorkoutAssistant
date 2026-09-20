import httpx
import pytest

from exercise_motion_pkg.segment_detection import LlamaCppVisionClient
from exercise_motion_pkg.vlm_errors import CriticalVlmInteractionError


@pytest.mark.parametrize("status,body,removed", [
    (400, "unsupported response_format", "response_format"),
    (422, "unknown reasoning_format parameter", "reasoning_format"),
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
