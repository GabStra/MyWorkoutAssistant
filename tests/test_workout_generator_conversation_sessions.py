from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from workout_generator_pkg.constants import EXACT_GENERATION_CONFIRMATION
from workout_generator_pkg.conversation_meta import get_active_conversation_id
from workout_generator_pkg.conversation_store import (
    list_conversations,
    load_active_conversation_record,
    load_conversation_record,
    resolve_conversation_id,
    save_conversation,
    set_active_conversation,
)
from workout_generator_pkg import interactive_shell


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    type: str
    function: FakeFunction


class FakeTimeout:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class FakeHttpClient:
    def __init__(self, timeout=None):
        self.timeout = timeout


class FakeHttpxModule:
    Timeout = FakeTimeout
    Client = FakeHttpClient


class FakeOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeLogger:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.lines: list[str] = []
        self.closed = False

    def log(self, line: str) -> None:
        self.lines.append(line)

    def log_print(self, line: str) -> None:
        self.lines.append(line)
        print(line)

    def log_section(self, title: str) -> None:
        self.lines.append(f"--- {title} ---")

    def log_request(self, label: str, content: str) -> None:
        self.lines.append(f"[request] {label}: {content}")

    def log_response(self, label: str, content: str, truncate_at: int = 8000) -> None:
        self.lines.append(f"[response] {label}: {content}")

    def close(self) -> None:
        self.closed = True


def write_progress_file(script_dir: Path, session_id: str, step: int = 3) -> None:
    progress_dir = script_dir / "workouts" / "generation_progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    path = progress_dir / f"progress_2026-05-12_120000_{session_id[:8]}.json"
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "timestamp": "2026-05-12T12:00:00",
                "current_step": step,
                "custom_prompt": "",
                "conversation_hash": "hash",
                "id_manager_state": {},
            }
        ),
        encoding="utf-8",
    )


def make_shell_deps(tmp_path: Path, *, chat_results, generation_results, generation_calls) -> SimpleNamespace:
    chat_iter = iter(chat_results)
    generation_iter = iter(generation_results)

    def chat_call_with_loading(client, api_messages, tools, logger):
        return next(chat_iter)

    def execute_workout_generation(
        client,
        messages,
        custom_prompt="",
        resume_session_id=None,
        provided_equipment=None,
        logger=None,
        script_dir=None,
        deps=None,
        force_use_reasoner=None,
        allow_educated_load_guesses=False,
    ):
        generation_calls.append(
            {
                "custom_prompt": custom_prompt,
                "resume_session_id": resume_session_id,
                "message_count": len(messages),
            }
        )
        return next(generation_iter)

    def handle_function_call(*args, **kwargs):
        kwargs["deps"] = SimpleNamespace(execute_workout_generation=execute_workout_generation)
        return interactive_shell.handle_function_call(*args, **kwargs)

    return SimpleNamespace(
        default_script_dir=lambda: str(tmp_path),
        load_equipment_from_file=lambda path: {},
        load_conversation=interactive_shell.resolve_shell_deps().load_conversation,
        load_active_conversation_record=load_active_conversation_record,
        load_conversation_record=load_conversation_record,
        list_conversations=list_conversations,
        set_active_conversation=set_active_conversation,
        update_conversation_metadata=lambda conversation_id, metadata, script_dir=None: metadata,
        resolve_conversation_id=resolve_conversation_id,
        has_equipment_in_messages=lambda messages: False,
        format_equipment_for_conversation=lambda equipment: "equipment",
        base_system_prompt="base system prompt",
        load_conversation_meta=lambda script_dir=None: {},
        save_conversation_meta=lambda conversation_id, script_dir=None: None,
        get_log_dir=lambda script_dir=None: str(tmp_path / "logs"),
        ConversationLogger=FakeLogger,
        chat_call_with_loading=chat_call_with_loading,
        generate_workout_tool={"name": "generate_workout"},
        handle_function_call=handle_function_call,
        execute_workout_generation=execute_workout_generation,
        save_conversation=save_conversation,
        list_available_progress=interactive_shell.resolve_shell_deps().list_available_progress,
        delete_progress_file=interactive_shell.resolve_shell_deps().delete_progress_file,
        conversation_file=str(tmp_path / "conversation_history.json"),
        OpenAI=FakeOpenAI,
        httpx=FakeHttpxModule,
    )


def run_shell(monkeypatch: pytest.MonkeyPatch, deps: SimpleNamespace, inputs: list[str]) -> None:
    values = iter(inputs)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(values))
    monkeypatch.setattr("sys.argv", ["workout_generator.py"])
    interactive_shell.main(deps=deps)


def test_legacy_history_migrates_into_archived_session(tmp_path: Path) -> None:
    (tmp_path / "conversation_history.json").write_text(
        json.dumps(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "conversation_meta.json").write_text(
        json.dumps({"conversation_id": "legacy-conversation-id"}),
        encoding="utf-8",
    )

    record = load_active_conversation_record(str(tmp_path))

    assert record is not None
    assert record["conversation_id"] == "legacy-conversation-id"
    assert [message["role"] for message in record["messages"]] == ["system", "user"]
    assert get_active_conversation_id(str(tmp_path)) == "legacy-conversation-id"
    conversations = list_conversations(str(tmp_path))
    assert len(conversations) == 1
    assert conversations[0]["status"] == "active"


def test_save_load_and_list_conversations_by_recency(tmp_path: Path) -> None:
    save_conversation(
        [{"role": "system", "content": "old"}],
        conversation_id="conversation-old",
        script_dir=str(tmp_path),
        metadata={"created_at": "2026-05-10T10:00:00", "updated_at": "2026-05-10T10:00:00"},
    )
    save_conversation(
        [{"role": "system", "content": "new"}],
        conversation_id="conversation-new",
        script_dir=str(tmp_path),
        metadata={
            "created_at": "2026-05-11T10:00:00",
            "updated_at": "2026-05-11T10:00:00",
            "last_generation_result": {"success": True},
        },
    )

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert active_record["conversation_id"] == "conversation-new"
    assert active_record["messages"][0]["content"] == "new"

    conversations = list_conversations(str(tmp_path))
    assert [item["conversation_id"] for item in conversations] == ["conversation-new", "conversation-old"]
    assert conversations[0]["status"] == "active"
    assert conversations[1]["status"] == "open"


def test_reopen_completed_conversation_preserves_turns(tmp_path: Path) -> None:
    completed_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "done"},
        {"role": "emitter", "step": "emit", "item_id": "item-1", "request_messages": [], "response_content": "ok"},
    ]
    save_conversation(
        completed_messages,
        conversation_id="completed-conversation",
        script_dir=str(tmp_path),
        metadata={
            "last_generation_result": {"success": True, "filepath": "workouts/generated.json"},
            "updated_at": "2026-05-11T08:00:00",
        },
    )
    save_conversation(
        [{"role": "system", "content": "active"}],
        conversation_id="active-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-10T08:00:00"},
    )

    assert set_active_conversation("completed-conversation", str(tmp_path)) is True

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert active_record["conversation_id"] == "completed-conversation"
    assert active_record["messages"] == completed_messages


def test_successful_generation_keeps_shell_alive_and_preserves_active_conversation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[
            (
                None,
                [
                    FakeToolCall(
                        id="tool-1",
                        type="function",
                        function=FakeFunction("generate_workout", json.dumps({"custom_prompt": ""})),
                    )
                ],
            ),
            ("You can keep refining this conversation.", None),
        ],
        generation_results=[
            {
                "success": True,
                "filepath": str(tmp_path / "workouts" / "generated.json"),
                "error": None,
                "emitter_conversations": [
                    {
                        "step": "exercise_definitions",
                        "item_id": "exercise-1",
                        "request_messages": [{"role": "user", "content": "emit"}],
                        "response_content": "{\"id\":\"exercise-1\"}",
                    }
                ],
            }
        ],
        generation_calls=generation_calls,
    )

    run_shell(
        monkeypatch,
        deps,
        [EXACT_GENERATION_CONFIRMATION, "another question", "/exit"],
    )

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert any(message.get("content") == "another question" for message in active_record["messages"])
    assert any(message.get("role") == "emitter" for message in active_record["messages"])
    assert generation_calls[0]["resume_session_id"] is None
    captured = capsys.readouterr().out
    assert "Assistant> You can keep refining this conversation." in captured


def test_clear_starts_new_conversation_without_deleting_archived_ones(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_conversation(
        [{"role": "system", "content": "original"}],
        conversation_id="existing-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-10T09:00:00"},
    )
    original_active_id = get_active_conversation_id(str(tmp_path))
    assert original_active_id == "existing-conversation"

    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=generation_calls,
    )

    run_shell(monkeypatch, deps, ["/clear", "/exit"])

    conversations = list_conversations(str(tmp_path))
    assert len(conversations) == 1
    assert any(item["conversation_id"] == "existing-conversation" for item in conversations)


def test_resume_can_reopen_completed_conversation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_conversation(
        [{"role": "system", "content": "completed"}],
        conversation_id="completed-conversation",
        script_dir=str(tmp_path),
        metadata={
            "updated_at": "2026-05-12T10:00:00",
            "last_generation_result": {"success": True},
        },
    )
    save_conversation(
        [{"role": "system", "content": "active"}],
        conversation_id="active-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-10T10:00:00"},
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/resume", "1", "/exit"])

    assert get_active_conversation_id(str(tmp_path)) == "completed-conversation"
    output = capsys.readouterr().out
    assert "Resumed conversation complete" in output
    assert "Conversation Turns" in output
    assert "completed" in output


def test_resume_progress_targets_generation_progress_not_archived_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_conversation(
        [{"role": "system", "content": "active"}],
        conversation_id="active-conversation",
        script_dir=str(tmp_path),
    )
    save_conversation(
        [{"role": "system", "content": "completed"}],
        conversation_id="completed-conversation",
        script_dir=str(tmp_path),
        metadata={"last_generation_result": {"success": True}},
    )
    write_progress_file(tmp_path, "progress-session-1234", step=4)

    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[
            {
                "success": True,
                "filepath": str(tmp_path / "workouts" / "resumed.json"),
                "error": None,
                "emitter_conversations": [],
            }
        ],
        generation_calls=generation_calls,
    )

    run_shell(monkeypatch, deps, ["/resume-progress", "1", "/exit"])

    assert generation_calls == [
        {
            "custom_prompt": "",
            "resume_session_id": "progress-session-1234",
            "message_count": 1,
        }
    ]


def test_show_turns_hides_tool_and_emitter_payloads_but_keeps_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_conversation(
        [
            {"role": "system", "content": "system", "timestamp": "2026-05-12T09:00:00"},
            {"role": "user", "content": "user", "timestamp": "2026-05-12T09:01:00"},
            {
                "role": "assistant",
                "content": "assistant",
                "timestamp": "2026-05-12T09:02:00",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tool-1",
                "content": "tool result",
                "timestamp": "2026-05-12T09:03:00",
            },
            {
                "role": "emitter",
                "step": "exercise_definitions",
                "item_id": "exercise-1",
                "request_messages": [{"role": "user", "content": "emit this"}],
                "response_content": "{\"ok\":true}",
                "timestamp": "2026-05-12T09:04:00",
            },
        ],
        conversation_id="turns-conversation",
        script_dir=str(tmp_path),
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/show-turns turns-conversation", "/exit"])

    output = capsys.readouterr().out
    assert "[1] system | 2026-05-12 09:00:00" in output
    assert "[2] user | 2026-05-12 09:01:00" in output
    assert "[3] assistant | 2026-05-12 09:02:00" in output
    assert "[Tool call triggered]" in output
    assert "tool_name: generate_workout" not in output
    assert "request_messages:" not in output
    assert "tool result" not in output
    assert "[5] tool | 2026-05-12 09:03:00" not in output
    assert "[5] emitter | 2026-05-12 09:04:00" not in output


def test_resume_repairs_orphaned_tool_call_before_next_api_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_conversation(
        [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "The generation hit a validation snag — let me try again!"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-orphan",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
        ],
        conversation_id="orphaned-tool-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-12T17:25:30"},
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[("Recovered after resume.", None)],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/resume", "1", "continue", "/exit"])

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert any(
        message.get("role") == "tool" and message.get("tool_call_id") == "tool-orphan"
        for message in active_record["messages"]
    )


def test_messages_for_api_repairs_multiple_orphaned_tool_calls_and_drops_stray_tools() -> None:
    repaired = interactive_shell._messages_for_api(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": EXACT_GENERATION_CONFIRMATION},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {"role": "user", "content": EXACT_GENERATION_CONFIRMATION},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-2",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tool-stray", "content": "orphan"},
            {"role": "user", "content": "continue"},
        ]
    )

    assert [(message["role"], message.get("tool_call_id")) for message in repaired] == [
        ("system", None),
        ("user", None),
        ("assistant", None),
        ("tool", "tool-1"),
        ("user", None),
        ("assistant", None),
        ("tool", "tool-2"),
        ("user", None),
    ]


def test_save_conversation_repairs_orphaned_tool_calls_at_persistence_boundary(tmp_path: Path) -> None:
    save_conversation(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": EXACT_GENERATION_CONFIRMATION},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "stray-tool", "content": "orphan"},
            {"role": "assistant", "content": "next"},
        ],
        conversation_id="persisted-conversation",
        script_dir=str(tmp_path),
    )

    record = load_conversation_record("persisted-conversation", str(tmp_path))
    assert record is not None
    assert [(message["role"], message.get("tool_call_id")) for message in record["messages"]] == [
        ("system", None),
        ("user", None),
        ("assistant", None),
        ("tool", "tool-1"),
        ("assistant", None),
    ]


def test_interrupted_tool_call_still_persists_matching_tool_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deps = make_shell_deps(
        tmp_path,
        chat_results=[
            (
                None,
                [
                    FakeToolCall(
                        id="tool-1",
                        type="function",
                        function=FakeFunction("generate_workout", json.dumps({"custom_prompt": ""})),
                    )
                ],
            ),
        ],
        generation_results=[],
        generation_calls=[],
    )

    def interrupted_handle_function_call(*args, **kwargs):
        raise KeyboardInterrupt()

    deps.handle_function_call = interrupted_handle_function_call

    run_shell(monkeypatch, deps, [EXACT_GENERATION_CONFIRMATION, "/exit"])

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert any(
        message.get("role") == "tool" and message.get("tool_call_id") == "tool-1"
        for message in active_record["messages"]
    )


def test_failed_generation_still_records_tool_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[
            (
                None,
                [
                    FakeToolCall(
                        id="tool-1",
                        type="function",
                        function=FakeFunction("generate_workout", json.dumps({"custom_prompt": ""})),
                    )
                ],
            ),
        ],
        generation_results=[
            {
                "success": False,
                "filepath": None,
                "error": "first failure",
                "emitter_conversations": [],
            },
        ],
        generation_calls=generation_calls,
    )

    run_shell(monkeypatch, deps, [EXACT_GENERATION_CONFIRMATION, "/exit"])

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    tool_messages = [message for message in active_record["messages"] if message.get("role") == "tool"]
    assert [message.get("tool_call_id") for message in tool_messages] == ["tool-1"]
    assert len(generation_calls) == 1
    output = capsys.readouterr().out
    assert "Workout generation failed: first failure" in output


def test_shell_does_not_resume_previous_conversation_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_conversation(
        [
            {"role": "system", "content": "previous system"},
            {"role": "user", "content": "previous user"},
        ],
        conversation_id="previous-conversation",
        script_dir=str(tmp_path),
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/show-turns", "/exit"])

    output = capsys.readouterr().out
    assert "✓ Resumed active conversation" not in output
    assert "previous user" not in output
    assert "base system prompt" in output
