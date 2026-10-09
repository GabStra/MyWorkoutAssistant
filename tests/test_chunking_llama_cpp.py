from exercise_motion_pkg import chunking
from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_MODEL


def test_llm_chunk_estimate_uses_llama_cpp_chat_completions(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"rep_duration_min_sec": 4, "rep_duration_max_sec": 8, '
                                '"movement_complexity": "compound", "reason": "Full rep."}'
                            )
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(chunking.httpx, "post", fake_post)

    estimate = chunking.estimate_chunking(
        exercise_name="Barbell Squat",
        use_llm=True,
    )

    assert estimate.source == "llama_cpp"
    assert estimate.movement_complexity == "compound"
    assert calls[0][0] == "http://127.0.0.1:8090/v1/chat/completions"
    assert calls[0][1]["json"]["model"] == DEFAULT_LLAMA_CPP_MODEL
    assert calls[0][1]["json"]["response_format"] == {"type": "json_object"}


def test_contract_chunk_hint_skips_llama_cpp_request(monkeypatch):
    monkeypatch.setattr(
        chunking.httpx,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected model request")),
    )

    estimate = chunking.estimate_chunking(
        exercise_name="Turkish Get-Up",
        use_llm=True,
        exercise_motion_contract={
            "movementType": "transition_sequence",
            "singleExecutionDurationSeconds": {"minSec": 20, "maxSec": 45},
        },
    )

    assert estimate.source == "contract"
    assert estimate.rep_duration_min_sec == 20
