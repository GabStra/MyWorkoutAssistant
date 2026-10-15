from types import SimpleNamespace
import sys

import pytest

from exercise_library_generator_pkg import generator
from workout_generator_pkg import api_client


def recording_client(requests):
    def create(**kwargs):
        requests.append(kwargs)
        return iter([SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content='{"status":"ok"}'), finish_reason="stop",
        )])])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize("reasoning", [False, True])
def test_library_calls_latest_deepseek_with_correct_thinking_mode(reasoning):
    requests = []
    call = (generator.json_call_reasoner_only_with_loading if reasoning
            else generator.json_call_chat_max_with_loading)
    content = call(recording_client(requests), [{"role": "user", "content": "Return JSON"}], show_loading=False)
    assert content == '{"status":"ok"}'
    assert requests[0]["model"] == "deepseek-flash"
    assert requests[0]["extra_body"] == {"thinking": {"type": "enabled" if reasoning else "disabled"}}
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_library_connection_probe_uses_same_model_without_thinking():
    requests = []
    assert generator.test_connection(
        recording_client(requests), show_message=False, model=generator.DEEPSEEK_MODEL,
    ) == (True, None)
    assert requests[0]["model"] == "deepseek-flash"
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_shared_calls_use_latest_model_with_explicit_thinking_modes():
    requests = []
    client = recording_client(requests)
    api_client.json_call(client, [])
    api_client.json_call_reasoner_only(client, [])
    api_client.json_call_large(client, [])
    assert [request["model"] for request in requests] == ["deepseek-flash"] * 3
    assert [request["extra_body"]["thinking"]["type"] for request in requests] == ["disabled", "enabled", "enabled"]


def test_conversation_tool_call_uses_latest_model_without_reasoning_history_requirement():
    requests = []
    tool_call = SimpleNamespace(id="call-id", type="function", function=SimpleNamespace(name="generate_workout", arguments="{}"))

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Preview", tool_calls=[tool_call]))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert api_client.chat_call(client, [{"role": "user", "content": "Plan a workout"}], tools=[{"type": "function"}]) == ("Preview", [tool_call])
    assert requests[0]["model"] == "deepseek-flash"
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert requests[0]["tools"] == [{"type": "function"}]


@pytest.mark.parametrize("flags, capabilities, expected_stage", [
    ([], [], "capabilities"),
    (["--skip-capabilities"], [], "inventory"),
    ([], ["BENCH_FLAT"], "inventory"),
    (["--capabilities-file", "approved.json"], [], "inventory"),
    (["--generate-capabilities"], ["BENCH_FLAT"], "capabilities"),
    (["--capabilities-output-file", "approved.json"], [], "capabilities"),
])
def test_cli_capability_generation_default(monkeypatch, capsys, flags, capabilities, expected_stage):
    equipment = {"equipments": [{"id": "bench", "capabilities": capabilities}], "accessoryEquipments": []}
    monkeypatch.setattr(sys, "argv", ["generator", "--equipment-file", "equipment.json", *flags])
    monkeypatch.setattr(generator, "load_equipment_from_file", lambda _: equipment)
    monkeypatch.setattr(generator, "_apply_capability_file", lambda value, _: value)
    monkeypatch.setattr(generator, "_resolve_api_key", lambda: "test")
    monkeypatch.setattr(generator, "OpenAI", lambda **kwargs: object())
    monkeypatch.setattr(generator, "test_connection", lambda *args, **kwargs: (True, None))

    def stop_at_stage(stage):
        def stop(*args, **kwargs):
            raise RuntimeError(f"reached-{stage}")
        return stop

    monkeypatch.setattr(generator, "_generate_capability_suggestions", stop_at_stage("capabilities"))
    monkeypatch.setattr(generator, "generate_exercise_library", stop_at_stage("inventory"))
    with pytest.raises(SystemExit) as stopped:
        generator.main()
    assert stopped.value.code == 1
    assert f"reached-{expected_stage}" in capsys.readouterr().err
