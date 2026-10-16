import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from workout_generator_pkg import api_client, cli, exercise_library_tools as library, interactive_shell
from workout_generator_pkg.cancellation import run_cancellable
from workout_generator_pkg.generation_audit import muscle_credits_per_set


def equipment():
    return {"exerciseDefinitions": [{"id": "definition", "name": "Bench Press", "exerciseCategory": "HEAVY_COMPOUND",
        "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": ["FRONT_DELTOIDS", "FRONT_TRICEPS", "BACK_TRICEPS"]}],
        "equipments": [], "accessoryEquipments": []}


def test_exact_lookup_and_saved_cache_avoid_model_calls_and_invalidate_on_change(monkeypatch):
    gear = equipment()
    calls = []
    def semantic(client, queries, entries):
        calls.append(queries)
        return [{0: 0.9} for _ in queries]
    monkeypatch.setattr(library, "_semantic_matches", semantic)
    exact = library.execute_library_tool("search_exercise_library", {"queries": ["BENCH PRESS"]}, gear)
    assert calls == []
    entry = exact["results"][0]["exercises"][0]
    assert entry["creditsPerWorkingSet"] == muscle_credits_per_set(gear["exerciseDefinitions"][0])
    assert entry["creditsPerWorkingSet"]["triceps"] == {"direct": 0, "indirect": 0.5}
    args = {"queries": ["horizontal push", "horizontal push"]}
    result = library.execute_library_tool("search_exercise_library", args, gear, client=object())
    history = [{"role": "tool", "content": json.dumps(result)}]
    assert library.execute_library_tool("search_exercise_library", args, gear, messages=history) == result
    assert calls == [["horizontal push"]]
    gear["equipments"].append({"id": "new", "name": "New gear"})
    library.execute_library_tool("search_exercise_library", args, gear, client=object(), messages=history)
    assert len(calls) == 2


def test_independent_tool_searches_are_combined_without_duplicate_queries(monkeypatch):
    calls = []
    def semantic(client, queries, entries):
        calls.append(queries)
        return [{0: 0.9} for _ in queries]
    monkeypatch.setattr(library, "_semantic_matches", semantic)
    results = library.execute_library_searches([
        ("one", {"queries": ["push", "chest"]}), ("two", {"queries": ["chest", "push"]}),
    ], equipment(), object(), [])
    assert calls == [["push", "chest"]]
    assert [r["query"] for r in results["two"]["results"]] == ["chest", "push"]


def test_model_feedback_is_compact_without_mutating_authoritative_draft():
    from test_workout_generator_planning_tools import planning_case, approved_messages, requirement_messages
    from workout_generator_pkg.planning_tools import audit_workout_plan
    gear, requirements, stored, draft = planning_case()
    result = audit_workout_plan(draft, gear, requirement_messages(stored))
    messages = approved_messages(stored, result)
    before = copy.deepcopy(messages)
    outgoing = interactive_shell._messages_for_api(messages)
    audit = next(json.loads(m["content"]) for m in outgoing if m.get("role") == "tool" and '"audit"' in m.get("content", ""))
    assert "planIndex" not in audit and "preview" not in audit
    assert audit["audit"]["workouts"][0]["contributions"]
    assert messages == before


def test_reasoning_budgets_reject_truncation_without_retry():
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    options = []
    client.with_options = lambda **kwargs: options.append(kwargs) or client
    with pytest.raises(ValueError, match="truncated"):
        api_client.chat_call(client, [])
    assert len(requests) == 1
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["max_tokens"] == 65536
    assert requests[0]["timeout"] is None
    assert options == [{"max_retries": 0}]


def test_truncated_planning_output_is_logged_but_never_accepted_or_retried(monkeypatch):
    requests, logged = [], []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(
            content='incomplete output', reasoning_content='unfinished reasoning', tool_calls=None))],
            usage=SimpleNamespace(model_dump=lambda: {'completion_tokens': 65536, 'prompt_tokens': 12000}))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kwargs: client
    logger = SimpleNamespace(log=lambda *a: None, log_print=lambda *a: None,
        log_response=lambda label, content, **options: logged.append((label, json.loads(content), options)))
    monkeypatch.setattr(api_client.LoadingIndicator, 'start', lambda self: None)
    monkeypatch.setattr(api_client.LoadingIndicator, 'stop', lambda self: None)
    with pytest.raises(api_client.TruncatedResponseError):
        api_client.chat_call_with_loading(client, [], logger=logger)
    assert len(requests) == 1 and len(logged) == 1
    assert logged[0][1]['usage']['completion_tokens'] == 65536
    assert logged[0][1]['reasoningContent'] == 'unfinished reasoning'
    assert logged[0][1]['content'] == 'incomplete output' and logged[0][2]['truncate_at'] == 0


def test_truncation_diagnostics_distinguish_reasoning_exhaustion_from_output_size():
    for has_output in (False, True):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='partial JSON' if has_output else None, reasoning_content='retained rejected reasoning', tool_calls=None))],
            usage=SimpleNamespace(model_dump=lambda: {'completion_tokens': 65536, 'prompt_tokens': 53282,
                'completion_tokens_details': {'reasoning_tokens': 64000 if has_output else 65536}}))
        error = api_client.TruncatedResponseError(response, 65536, 'high')
        assert error.diagnostics['cause'] == ('completion_length_limit' if has_output else 'reasoning_budget_exhausted')
        assert ('exhausted the budget in reasoning' in str(error)) is (not has_output)


def test_repair_profile_keeps_thinking_enabled_and_logs_actual_effort(monkeypatch):
    requests, logged = [], []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='Repair ready.', reasoning_content='', tool_calls=None))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kwargs: client
    monkeypatch.setattr(api_client.LoadingIndicator, 'start', lambda self: None)
    monkeypatch.setattr(api_client.LoadingIndicator, 'stop', lambda self: None)
    logger = SimpleNamespace(log=logged.append, log_print=logged.append)
    api_client.chat_call_with_loading(client, [], logger=logger, reasoning_effort='low', activity='Repairing draft')
    assert requests[0]['reasoning_effort'] == 'low'
    assert requests[0]['extra_body']['thinking']['type'] == 'enabled'
    assert requests[0]['timeout'] is None
    assert any('Repairing draft (effort=low' in line for line in logged)
    assert any('Repair response ready' in line for line in logged)


def test_request_deadline_returns_without_waiting_for_network():
    release = threading.Event()
    try:
        with pytest.raises(TimeoutError, match="No automatic retry"):
            run_cancellable(lambda: release.wait(5), deadline_seconds=0.01)
    finally:
        release.set()


def test_conversation_log_is_written_before_close_and_write_failure_is_visible(tmp_path, monkeypatch):
    logger, path = interactive_shell._create_logger(cli.ConversationLogger, str(tmp_path), "durable-log")
    try:
        logger.log("Tool search finished (1.23s)")
        assert "Conversation logging started" in Path(path).read_text(encoding="utf-8")
        assert "Tool search finished (1.23s)" in Path(path).read_text(encoding="utf-8")
        def fail_open(*args, **kwargs):
            raise OSError('write failed')
        with monkeypatch.context() as patcher:
            patcher.setattr('builtins.open', fail_open)
            with pytest.raises(RuntimeError, match="Cannot write conversation log"):
                logger.log("must not disappear silently")
    finally:
        logger.close()
