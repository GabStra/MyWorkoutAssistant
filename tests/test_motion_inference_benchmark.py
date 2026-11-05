import json
from types import SimpleNamespace

import httpx
import pytest

from exercise_motion_pkg.segment_detection import LlamaCppVisionClient
from scripts import benchmark_motion_inference_settings as bench


def test_replay_uses_production_request_policy_and_records_both_gpus(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"retained-image")
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"requests": [{"id": "endpoint", "prompt": "Observe posture",
        "images": [image.name], "kwargs": {"max_tokens": 200, "disable_reasoning": True,
            "clef_visual_decision_backend": "qwen-chat"}}]}))
    requests = bench.fixed_requests(manifest)
    assert requests[0]["images"] == [str(image)]
    assert requests[0]["imageHashes"]
    sent, settings_used, closed = [], [], []

    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"supportMode":"standing"}'},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 100}, "timings": {"prompt_ms": 5}})

    class Ranker:
        def __init__(self, settings):
            settings_used.append(settings)
            self.process = SimpleNamespace(args=["owned-production-launch"])
            self.server_log_path = None
            self.client = LlamaCppVisionClient(settings.llama_cpp_base_url, settings.llama_cpp_model,
                temperature=settings.llama_cpp_temperature, top_p=settings.llama_cpp_top_p,
                top_k=settings.llama_cpp_top_k, disable_reasoning=settings.llama_cpp_disable_reasoning)
            self.client.client.close()
            self.client.client = httpx.Client(transport=httpx.MockTransport(respond))

        def close(self, *, force_stop_server):
            closed.append(force_stop_server)
            self.client.close()

        def _server_props_payload(self):
            return {"total_slots": 3}

    monkeypatch.setattr(bench, "LlamaCppVisionRanker", Ranker)
    monkeypatch.setattr(bench.subprocess, "check_output", lambda *a, **k: "0, 95, 11000, 180\n1, 0, 450, [N/A]\n")
    result = bench.benchmark("3:1024:512", requests, tmp_path / "run", 0,
        context_per_slot=16384, workers=4, repeats=1, kv_type="q8_0", kv_unified=False)
    assert "error" not in result
    assert settings_used[0].llama_cpp_ctx_size == settings_used[0].llama_cpp_fit_ctx == 49152
    assert settings_used[0].llama_cpp_reasoning_budget == 64
    assert sent[0]["max_tokens"] == 200
    assert sent[0]["reasoning_format"] == "deepseek"
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert "cache_prompt" not in sent[0]
    row = result["waves"][0]["rows"][0]
    assert row["decision"] == {"supportMode": "standing"}
    assert row["responses"][0]["timings"] == {"prompt_ms": 5}
    assert closed == [True]
    gpus = bench.parse_gpu_samples("0, 95, 11000, 180\n1, 0, 450, [N/A]\n")
    assert [gpu["index"] for gpu in gpus] == [0, 1]
    assert gpus[1]["powerWatts"] is None
    assert not result["gpuSamplingErrors"]


def test_replay_rejects_duplicate_ids_and_missing_images(tmp_path):
    manifest = tmp_path / "cases.json"
    row = {"id": "same", "prompt": "Observe", "images": ["missing.jpg"]}
    manifest.write_text(json.dumps({"requests": [row, row]}))
    with pytest.raises(ValueError, match="unique"):
        bench.fixed_requests(manifest)
    manifest.write_text(json.dumps({"requests": [row]}))
    with pytest.raises(FileNotFoundError):
        bench.fixed_requests(manifest)
    source = {"sourceCandidate": {"id": "A", "start": 0, "end": 1,
                                 "requiredEquipment": "none"}, "images": []}
    raw = '{"candidates":[{"id":"A","approved":true,"confidence":95}]}'
    with pytest.raises(ValueError, match="production parser"):
        bench.review_decision(source, json.loads(raw), raw)
