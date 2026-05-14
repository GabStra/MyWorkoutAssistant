"""Interactive CLI shell handlers."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import EXACT_GENERATION_CONFIRMATION
from .conversation_store import normalize_conversation_messages
from .deps import resolve_shell_deps


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ."""
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            os.environ.setdefault(key, value)


def _resolve_api_key() -> str:
    """Resolve API key from environment, optionally loading .env from common locations."""
    repo_root = Path(__file__).resolve().parents[1]
    env_candidates = [
        Path.cwd() / ".env",
        repo_root / ".env",
    ]
    seen = set()
    for candidate in env_candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        _load_env_file(candidate)

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key

    raise RuntimeError(
        "Missing API key. Set DEEPSEEK_API_KEY (or OPENAI_API_KEY) in environment "
        "or in a project .env file."
    )


def _timestamp_now() -> str:
    return datetime.now().isoformat()


def _message(role: str, **fields: Any) -> Dict[str, Any]:
    payload = {"role": role, "timestamp": _timestamp_now()}
    payload.update(fields)
    return payload


def _format_timestamp(value: Optional[str]) -> str:
    if not value:
        return "unknown time"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value


def _format_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def _build_initial_messages(
    base_system_prompt: str,
    provided_equipment: Optional[Dict[str, Any]],
    format_equipment_for_conversation,
) -> List[Dict[str, Any]]:
    messages = [_message("system", content=base_system_prompt)]
    if provided_equipment:
        messages.append(
            _message(
                "system",
                content=format_equipment_for_conversation(provided_equipment),
            )
        )
    return messages


def _conversation_log_path(script_dir: str, conversation_id: str) -> str:
    short_cid = conversation_id[:8] if len(conversation_id) >= 8 else conversation_id
    return os.path.join(script_dir, "logs", f"conversation_{short_cid}.log")


def _create_logger(ConversationLogger, script_dir: str, conversation_id: str):
    log_path = _conversation_log_path(script_dir, conversation_id)
    log_dir = os.path.dirname(log_path)
    os.makedirs(log_dir, exist_ok=True)
    return ConversationLogger(log_path), log_path


def _metadata_for_generation_result(
    generation_result: Dict[str, Any],
    log_path: Optional[str],
    previous_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    filepath = generation_result.get("filepath")
    generated_paths = list(previous_paths or [])
    if filepath and filepath not in generated_paths:
        generated_paths.append(filepath)
    return {
        "last_generation_result": {
            "success": bool(generation_result.get("success")),
            "filepath": filepath,
            "error": generation_result.get("error"),
            "recorded_at": _timestamp_now(),
        },
        "generated_output_paths": generated_paths,
        "log_filename": os.path.basename(log_path) if log_path else None,
    }


def _render_turns(messages: List[Dict[str, Any]], logger) -> None:
    logger.log_print("")
    logger.log_print("=" * 70)
    logger.log_print("Conversation Turns")
    logger.log_print("=" * 70)

    visible_roles = {"system", "user", "assistant"}
    visible_messages = [
        message for message in messages
        if message.get("role") in visible_roles
        and (
            message.get("role") != "assistant"
            or message.get("content") not in (None, "")
            or message.get("tool_calls")
        )
    ]

    for index, message in enumerate(visible_messages, start=1):
        role = message.get("role", "unknown")
        timestamp = _format_timestamp(message.get("timestamp"))
        logger.log_print(f"[{index}] {role} | {timestamp}")

        content = message.get("content")
        if content is not None:
            logger.log_print(_format_json(content))
        if role == "assistant" and message.get("tool_calls"):
            logger.log_print("[Tool call triggered]")

        logger.log_print("-" * 70)


def _ensure_tool_responses(messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], bool]:
    repaired = normalize_conversation_messages(messages)
    return repaired, repaired != messages


def _messages_for_api(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    repaired, _ = _ensure_tool_responses(messages)
    return [message for message in repaired if message.get("role") != "emitter"]


def _show_commands(logger) -> None:
    logger.log_print("Commands:")
    logger.log_print("  • Type normal messages to chat with the assistant")
    logger.log_print("  • Type /ml (or /multiline) to enter multi-line mode, finish with a line containing /end")
    logger.log_print("  • Type /generate or /generate <prompt> to generate workout JSON")
    logger.log_print("  • Type /resume to reopen a saved conversation and show all stored turns")
    logger.log_print("  • Type /resume-progress to resume an interrupted generation directly")
    logger.log_print("  • Type /list-progress to list all saved generation progress")
    logger.log_print("  • Type /list-conversations to list saved conversations")
    logger.log_print("  • Type /resume-conversation <conversation_id> to reopen a conversation and show all stored turns")
    logger.log_print("  • Type /show-turns [conversation_id] to print exact stored turns")
    logger.log_print("  • Type /clear-progress <session_id> to delete a progress file")
    logger.log_print("  • Type /exit to quit")
    logger.log_print("  • Type /clear to start a fresh conversation")
    logger.log_print("  • Press Ctrl+C during generation to cancel")


def _print_welcome(logger) -> None:
    logger.log_print("=" * 70)
    logger.log_print("Workout Assistant & Generator")
    logger.log_print("=" * 70)
    logger.log_print("")
    logger.log_print("This script is an AI-powered workout assistant that helps you:")
    logger.log_print("  • Chat about workouts, exercises, and fitness goals")
    logger.log_print("  • Generate structured workout JSON files compatible with")
    logger.log_print("    the MyWorkoutAssistant app")
    logger.log_print("")
    logger.log_print("The assistant will ask you about:")
    logger.log_print("  • Your fitness goals and training preferences")
    logger.log_print("  • Available equipment (to suggest compatible exercises)")
    logger.log_print("")
    logger.log_print("The generated JSON includes:")
    logger.log_print("  • Complete workout definitions with exercises, sets, and rest periods")
    logger.log_print("  • Equipment configurations (barbells, dumbbells, machines, etc.)")
    logger.log_print("  • Exercise details (reps, weights, muscle groups, progression settings)")
    logger.log_print("  • Validated against a comprehensive JSON schema")
    logger.log_print("")
    _show_commands(logger)
    logger.log_print("")
    logger.log_print("=" * 70)
    logger.log_print("")


def handle_function_call(
    client,
    messages,
    function_name,
    function_args,
    provided_equipment=None,
    logger=None,
    script_dir=None,
    deps=None,
    force_use_reasoner=None,
    allow_educated_load_guesses=False,
):
    deps = deps or resolve_shell_deps()
    execute_workout_generation = deps.execute_workout_generation
    """
    Handle function call execution.

    Returns:
        dict: Result with keys:
            - result: The function result (formatted for assistant)
            - should_exit: bool indicating if conversation should end
            - generation_result: Optional raw generation result
    """

    def _last_user_message_content():
        for message in reversed(messages):
            if message.get("role") == "user":
                return (message.get("content") or "").strip()
        return ""

    if function_name == "generate_workout":
        last_user_message = _last_user_message_content()
        if last_user_message != EXACT_GENERATION_CONFIRMATION:
            return {
                "result": (
                    "Workout generation blocked. "
                    f"Wait for the user to reply with exactly {EXACT_GENERATION_CONFIRMATION!r} "
                    "before calling generate_workout."
                ),
                "should_exit": False,
                "generation_result": None,
            }
        custom_prompt = function_args.get("custom_prompt", "")
        generation_result = execute_workout_generation(
            client,
            messages,
            custom_prompt,
            None,
            provided_equipment,
            logger,
            script_dir,
            force_use_reasoner=force_use_reasoner,
            allow_educated_load_guesses=allow_educated_load_guesses,
        )

        if generation_result["success"]:
            for emitter_turn in generation_result.get("emitter_conversations", []):
                messages.append(
                    _message(
                        "emitter",
                        step=emitter_turn["step"],
                        item_id=emitter_turn["item_id"],
                        request_messages=emitter_turn["request_messages"],
                        response_content=emitter_turn["response_content"],
                    )
                )
            if generation_result["filepath"]:
                result_message = (
                    f"Workout generated successfully and saved to: {generation_result['filepath']}"
                )
            else:
                result_message = "Workout generated successfully (but file save failed - check output above)"
        else:
            result_message = f"Workout generation failed: {generation_result.get('error', 'Unknown error')}"

        return {
            "result": result_message,
            "should_exit": False,
            "generation_result": generation_result,
        }

    return {
        "result": f"Unknown function: {function_name}",
        "should_exit": False,
        "generation_result": None,
    }


def main(deps=None):
    deps = deps or resolve_shell_deps()
    _default_script_dir = deps.default_script_dir
    load_equipment_from_file = deps.load_equipment_from_file
    load_conversation_record = deps.load_conversation_record
    list_conversations = deps.list_conversations
    set_active_conversation = deps.set_active_conversation
    resolve_conversation_id = deps.resolve_conversation_id
    has_equipment_in_messages = deps.has_equipment_in_messages
    format_equipment_for_conversation = deps.format_equipment_for_conversation
    BASE_SYSTEM_PROMPT = deps.base_system_prompt
    get_log_dir = deps.get_log_dir
    ConversationLogger = deps.ConversationLogger
    chat_call_with_loading = deps.chat_call_with_loading
    GENERATE_WORKOUT_TOOL = deps.generate_workout_tool
    handle_function_call_dep = deps.handle_function_call
    execute_workout_generation = deps.execute_workout_generation
    save_conversation = deps.save_conversation
    list_available_progress = deps.list_available_progress
    delete_progress_file = deps.delete_progress_file
    OpenAI = deps.OpenAI
    httpx = deps.httpx

    parser = argparse.ArgumentParser(description="Workout Assistant & Generator")
    parser.add_argument(
        "--equipment-file",
        type=str,
        help="Path to JSON file containing available equipment (with 'equipments' and optionally 'accessoryEquipments' arrays)",
    )
    reasoner_group = parser.add_mutually_exclusive_group()
    reasoner_group.add_argument(
        "--use-reasoner",
        action="store_true",
        help="Use reasoner model for plan index/emitting without interactive prompt",
    )
    reasoner_group.add_argument(
        "--no-reasoner",
        action="store_true",
        help="Use chat model for plan index/emitting without interactive prompt",
    )
    reasoner_group.add_argument(
        "--hybrid-fast",
        action="store_true",
        help="Use reasoner for plan index and chat model for emitters (faster overall)",
    )
    parser.add_argument(
        "--allow-educated-load-guesses",
        action="store_true",
        help="Allow the generator to keep requiresLoadCalibration=false for load-based exercises when you explicitly want educated starting-load guesses",
    )
    args = parser.parse_args()
    force_use_reasoner = (
        "hybrid"
        if args.hybrid_fast
        else (True if args.use_reasoner else (False if args.no_reasoner else None))
    )

    try:
        script_dir = _default_script_dir()
    except (NameError, AttributeError):
        script_dir = os.getcwd()

    provided_equipment = None
    if args.equipment_file:
        try:
            provided_equipment = load_equipment_from_file(args.equipment_file)
            print(f"Loaded equipment from: {args.equipment_file}")
            print(f"  - {len(provided_equipment.get('equipments', []))} equipment item(s)")
            print(f"  - {len(provided_equipment.get('accessoryEquipments', []))} accessory item(s)")
            print()
        except Exception as e:
            print(f"Error loading equipment file: {e}", file=sys.stderr)
            sys.exit(1)

    api_key = _resolve_api_key()
    timeout = httpx.Timeout(1200.0, connect=60.0)
    http_client = httpx.Client(timeout=timeout)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", http_client=http_client)
    get_log_dir(script_dir)

    conversation_id = str(uuid.uuid4())
    messages = _build_initial_messages(
        BASE_SYSTEM_PROMPT,
        provided_equipment,
        format_equipment_for_conversation,
    )
    metadata = {}

    logger, log_path = _create_logger(ConversationLogger, script_dir, conversation_id)
    metadata.setdefault("log_filename", os.path.basename(log_path))

    state: Dict[str, Any] = {
        "conversation_id": conversation_id,
        "messages": messages,
        "logger": logger,
        "log_path": log_path,
    }

    def persist_current(metadata_update: Optional[Dict[str, Any]] = None) -> None:
        state["messages"], _ = _ensure_tool_responses(state["messages"])
        has_non_system_turns = any(
            message.get("role") != "system" for message in state["messages"]
        )
        if not has_non_system_turns and not metadata_update:
            return
        current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
        existing_metadata = current_record.get("metadata", {})
        merged_metadata = existing_metadata.copy()
        if metadata_update:
            merged_metadata.update(metadata_update)
        merged_metadata["log_filename"] = os.path.basename(state["log_path"])
        save_conversation(
            state["messages"],
            conversation_id=state["conversation_id"],
            script_dir=script_dir,
            metadata=merged_metadata,
        )

    def close_logger() -> None:
        current_logger = state.get("logger")
        if current_logger:
            current_logger.close()
            state["logger"] = None

    def save_and_close() -> None:
        persist_current()
        close_logger()

    atexit.register(save_and_close)

    def switch_conversation(
        next_conversation_id: str,
        next_messages: List[Dict[str, Any]],
        *,
        announce: str,
    ) -> None:
        persist_current()
        close_logger()
        next_logger, next_log_path = _create_logger(ConversationLogger, script_dir, next_conversation_id)
        next_messages, _ = _ensure_tool_responses(next_messages)
        state["conversation_id"] = next_conversation_id
        state["messages"] = next_messages
        state["logger"] = next_logger
        state["log_path"] = next_log_path
        state["logger"].log_print(announce)
        state["logger"].log_print("")

    _print_welcome(state["logger"])

    def resume_generation_picker() -> bool:
        logger = state["logger"]
        logger.log("You> /resume-progress")
        progress_list = list_available_progress(script_dir)
        incomplete = [item for item in progress_list if item["status"] == "incomplete"]
        if not incomplete:
            logger.log_print("No incomplete generations found.")
            return False

        logger.log_print("")
        logger.log_print("Available incomplete generations:")
        logger.log_print("=" * 70)
        for index, progress in enumerate(incomplete, start=1):
            logger.log_print(
                f"{index}. Session: {progress['short_id']} | Step: {progress['current_step']} | "
                f"{_format_timestamp(progress.get('timestamp'))}"
            )
        logger.log_print("=" * 70)

        try:
            choice = input(f"\nSelect generation to resume (1-{len(incomplete)}) or 'c' to cancel: ").strip()
            logger.log("resume-progress choice: " + choice)
            if choice.lower() == "c":
                return False
            idx = int(choice) - 1
        except (ValueError, KeyboardInterrupt):
            logger.log_print("Cancelled.")
            return False

        if not (0 <= idx < len(incomplete)):
            logger.log_print("Invalid selection.")
            return False

        selected = incomplete[idx]
        logger.log_print(f"\nResuming generation session {selected['short_id']}...")
        result = execute_workout_generation(
            client,
            state["messages"],
            "",
            selected["session_id"],
            provided_equipment,
            logger,
            script_dir,
            force_use_reasoner=force_use_reasoner,
            allow_educated_load_guesses=args.allow_educated_load_guesses,
        )
        if result["success"]:
            for emitter_turn in result.get("emitter_conversations", []):
                state["messages"].append(
                    _message(
                        "emitter",
                        step=emitter_turn["step"],
                        item_id=emitter_turn["item_id"],
                        request_messages=emitter_turn["request_messages"],
                        response_content=emitter_turn["response_content"],
                    )
                )
            current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
            persist_current(
                _metadata_for_generation_result(
                    result,
                    state["log_path"],
                    current_record.get("metadata", {}).get("generated_output_paths"),
                )
            )
            return True

        if result.get("error"):
            logger.log_print(f"Resume error: {result['error']}")
            persist_current(
                _metadata_for_generation_result(result, state["log_path"])
            )
        return False

    def resume_conversation_by_id(identifier: str) -> bool:
        logger = state["logger"]
        resolved_id = resolve_conversation_id(identifier, script_dir)
        if not resolved_id:
            logger.log_print(f"Could not resolve conversation id: {identifier}")
            return False
        record = load_conversation_record(resolved_id, script_dir)
        if not record:
            logger.log_print(f"Conversation not found: {identifier}")
            return False
        set_active_conversation(resolved_id, script_dir)
        switch_conversation(
            resolved_id,
            list(record["messages"]),
            announce=f"Resumed conversation {resolved_id[:8]}.",
        )
        _render_turns(state["messages"], state["logger"])
        return True

    while True:
        user_input = input("You> ").strip()
        if not user_input:
            continue
        command = user_input.lower()
        logger = state["logger"]

        if command == "/exit":
            persist_current()
            break

        if command == "/clear":
            logger.log("You> /clear")
            next_messages = _build_initial_messages(
                BASE_SYSTEM_PROMPT,
                provided_equipment,
                format_equipment_for_conversation,
            )
            next_conversation_id = str(uuid.uuid4())
            switch_conversation(
                next_conversation_id,
                next_messages,
                announce="Started a fresh conversation. Archived conversations remain available via /list-conversations.",
            )
            continue

        if command in ("/ml", "/multiline"):
            logger.log_print("Entering multi-line mode. Paste your message; type '/end' on a new line to finish.")
            logger.log_print("(Lines are sent as a single message.)")
            lines = []
            while True:
                try:
                    line = input("ML> ")
                except EOFError:
                    break
                if line.strip() == "/end":
                    break
                lines.append(line)
            user_input = "\n".join(lines).rstrip("\n")
            if not user_input:
                continue
            command = user_input.lower()

        if user_input.startswith("/generate"):
            logger.log("You> " + user_input)
            custom = user_input[len("/generate"):].strip()
            result = execute_workout_generation(
                client,
                state["messages"],
                custom,
                None,
                provided_equipment,
                logger,
                script_dir,
                force_use_reasoner=force_use_reasoner,
                allow_educated_load_guesses=args.allow_educated_load_guesses,
            )
            if result["success"]:
                for emitter_turn in result.get("emitter_conversations", []):
                    state["messages"].append(
                        _message(
                            "emitter",
                            step=emitter_turn["step"],
                            item_id=emitter_turn["item_id"],
                            request_messages=emitter_turn["request_messages"],
                            response_content=emitter_turn["response_content"],
                        )
                    )
                current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
                persist_current(
                    _metadata_for_generation_result(
                        result,
                        state["log_path"],
                        current_record.get("metadata", {}).get("generated_output_paths"),
                    )
                )
            elif result.get("error"):
                logger.log_print(f"Generation error: {result['error']}")
                persist_current(_metadata_for_generation_result(result, state["log_path"]))
            continue

        if command == "/resume-progress":
            resume_generation_picker()
            continue

        if command == "/resume":
            logger.log("You> /resume")
            conversations = list_conversations(script_dir)
            if not conversations:
                logger.log_print("No saved conversations found.")
                continue

            logger.log_print("")
            logger.log_print("Saved conversations:")
            logger.log_print("=" * 70)
            for index, conversation in enumerate(conversations, start=1):
                logger.log_print(
                    f"{index}. {conversation['conversation_id'][:8]} | {conversation['status']} | "
                    f"{_format_timestamp(conversation.get('updated_at'))} | "
                    f"{conversation['message_count']} turn(s)"
                )
            logger.log_print("=" * 70)

            choice = input(f"\nSelect conversation (1-{len(conversations)}) or 'c' to cancel: ").strip().lower()
            logger.log("resume choice: " + choice)
            if choice == "c":
                continue
            try:
                idx = int(choice) - 1
            except ValueError:
                logger.log_print("Invalid selection.")
                continue
            if not (0 <= idx < len(conversations)):
                logger.log_print("Invalid selection.")
                continue
            selected = conversations[idx]
            set_active_conversation(selected["conversation_id"], script_dir)
            switch_conversation(
                selected["conversation_id"],
                list(selected["messages"]),
                announce=f"Resumed conversation {selected['conversation_id'][:8]}.",
            )
            _render_turns(state["messages"], state["logger"])
            continue

        if command == "/list-conversations":
            logger.log("You> /list-conversations")
            conversations = list_conversations(script_dir)
            if not conversations:
                logger.log_print("No saved conversations found.")
                continue
            logger.log_print("")
            logger.log_print("Saved conversations:")
            logger.log_print("=" * 70)
            for conversation in conversations:
                logger.log_print(
                    f"{conversation['conversation_id'][:8]} | {conversation['status']} | "
                    f"{_format_timestamp(conversation.get('updated_at'))} | "
                    f"{conversation['message_count']} turn(s)"
                )
            logger.log_print("=" * 70)
            continue

        if command.startswith("/resume-conversation"):
            logger.log("You> " + user_input)
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                logger.log_print("Usage: /resume-conversation <conversation_id>")
                continue
            resume_conversation_by_id(parts[1].strip())
            continue

        if command.startswith("/show-turns"):
            logger.log("You> " + user_input)
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                _render_turns(state["messages"], logger)
                continue
            resolved_id = resolve_conversation_id(parts[1].strip(), script_dir)
            if not resolved_id:
                logger.log_print(f"Could not resolve conversation id: {parts[1].strip()}")
                continue
            record = load_conversation_record(resolved_id, script_dir)
            if not record:
                logger.log_print(f"Conversation not found: {parts[1].strip()}")
                continue
            _render_turns(record["messages"], logger)
            continue

        if command == "/list-progress":
            logger.log("You> /list-progress")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            logger.log_print("")
            logger.log_print("All saved generation progress:")
            logger.log_print("=" * 70)
            for progress in progress_list:
                status_icon = "✓" if progress["status"] == "complete" else "○"
                logger.log_print(
                    f"{status_icon} Session: {progress['short_id']} | Step: {progress['current_step']} | "
                    f"{_format_timestamp(progress.get('timestamp'))} | {progress['status']}"
                )
            logger.log_print("=" * 70)
            continue

        if command.startswith("/clear-progress"):
            logger.log("You> " + user_input)
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                logger.log_print("Usage: /clear-progress <session_id>")
                logger.log_print("Use /list-progress to see available session IDs")
                continue
            session_id = parts[1].strip()
            if delete_progress_file(session_id, script_dir):
                logger.log_print(f"Progress file for session {session_id[:8]} deleted.")
            else:
                logger.log_print(f"Could not find or delete progress file for session {session_id[:8]}")
            continue

        if command == "/clear-all-progress":
            logger.log("You> /clear-all-progress")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            confirm = input(f"Are you sure you want to delete all {len(progress_list)} progress file(s)? (yes/no): ").strip().lower()
            logger.log("clear-all-progress confirm: " + confirm)
            if confirm == "yes":
                deleted_count = 0
                for progress in progress_list:
                    if delete_progress_file(progress["session_id"], script_dir):
                        deleted_count += 1
                logger.log_print(f"Deleted {deleted_count} progress file(s).")
            else:
                logger.log_print("Cancelled.")
            continue

        logger.log("You> " + user_input)
        state["messages"].append(_message("user", content=user_input))
        try:
            tools = [GENERATE_WORKOUT_TOOL]
            generation_metadata: Optional[Dict[str, Any]] = None
            api_messages = _messages_for_api(state["messages"])
            content, tool_calls = chat_call_with_loading(client, api_messages, tools, logger)

            if content is None and tool_calls is None:
                state["messages"].pop()
                logger.log_print("Cancelled. Returning to prompt...")
                continue

            has_content = content not in (None, "")
            has_tool_calls = bool(tool_calls)

            if not has_content and not has_tool_calls:
                state["messages"].pop()
                logger.log_print(
                    "The model returned an empty response with no tool call. "
                    "Nothing was added to the conversation; please retry."
                )
                continue

            assistant_message: Dict[str, Any] = _message("assistant")
            if has_content:
                assistant_message["content"] = content
            if has_tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in tool_calls
                ]
            state["messages"].append(assistant_message)

            if has_content:
                logger.log_print(f"Assistant> {content}")

            if has_tool_calls:
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}
                    logger.log_section("tool_call " + function_name)
                    logger.log_request("tool " + function_name, json.dumps(function_args, ensure_ascii=False))

                    tool_message = _message(
                        "tool",
                        tool_call_id=tool_call.id,
                        content=(
                            "Tool call started but did not complete. "
                            "Treat this as a failed tool result if execution is interrupted."
                        ),
                    )
                    state["messages"].append(tool_message)

                    try:
                        function_result = handle_function_call_dep(
                            client,
                            state["messages"],
                            function_name,
                            function_args,
                            provided_equipment,
                            logger,
                            script_dir,
                            force_use_reasoner=force_use_reasoner,
                            allow_educated_load_guesses=args.allow_educated_load_guesses,
                        )
                    except Exception as tool_error:
                        function_result = {
                            "result": f"Tool call failed: {tool_error}",
                            "should_exit": False,
                            "generation_result": None,
                        }

                    logger.log_response("tool result " + function_name, function_result.get("result", ""), truncate_at=8000)
                    tool_result_text = function_result.get("result", "")
                    if tool_result_text:
                        logger.log_print(tool_result_text)
                    tool_message["content"] = function_result["result"]
                    tool_message["timestamp"] = _timestamp_now()

                    generation_result = function_result.get("generation_result")
                    if generation_result is not None:
                        current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
                        generation_metadata = _metadata_for_generation_result(
                            generation_result,
                            state["log_path"],
                            current_record.get("metadata", {}).get("generated_output_paths"),
                        )

            persist_current(generation_metadata)

        except KeyboardInterrupt:
            logger.log_print("\nCancelled. Returning to prompt...")
            state["messages"].pop()
            continue
        except Exception as e:
            logger.log_print(f"Error: {e}")
            state["messages"].pop()
