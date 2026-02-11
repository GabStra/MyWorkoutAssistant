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
):
    deps = deps or resolve_shell_deps()
    execute_workout_generation = deps.execute_workout_generation
    """
    Handle function call execution.
    
    Args:
        client: OpenAI client
        messages: Conversation messages
        function_name: Name of the function to call
        function_args: Dictionary of function arguments
        provided_equipment: Optional dict with 'equipments' and 'accessoryEquipments' keys
        logger: Optional ConversationLogger for debug logging
        script_dir: Optional script directory (for progress/logs)
    
    Returns:
        dict: Result with keys:
            - result: The function result (formatted for assistant)
            - should_exit: bool indicating if conversation should end
    """
    if function_name == "generate_workout":
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
        )
        
        if generation_result["success"]:
            for e in generation_result.get("emitter_conversations", []):
                messages.append({
                    "role": "emitter",
                    "step": e["step"],
                    "item_id": e["item_id"],
                    "request_messages": e["request_messages"],
                    "response_content": e["response_content"],
                })
            if generation_result["filepath"]:
                result_message = f"Workout generated successfully and saved to: {generation_result['filepath']}"
            else:
                result_message = "Workout generated successfully (but file save failed - check output above)"
        else:
            result_message = f"Workout generation failed: {generation_result.get('error', 'Unknown error')}"
        
        return {
            "result": result_message,
            "should_exit": True  # Conversation ends after generate_workout
        }
    else:
        return {
            "result": f"Unknown function: {function_name}",
            "should_exit": False
        }


def main(deps=None):
    deps = deps or resolve_shell_deps()
    _default_script_dir = deps.default_script_dir
    load_equipment_from_file = deps.load_equipment_from_file
    load_conversation = deps.load_conversation
    has_equipment_in_messages = deps.has_equipment_in_messages
    format_equipment_for_conversation = deps.format_equipment_for_conversation
    BASE_SYSTEM_PROMPT = deps.base_system_prompt
    load_conversation_meta = deps.load_conversation_meta
    save_conversation_meta = deps.save_conversation_meta
    get_log_dir = deps.get_log_dir
    ConversationLogger = deps.ConversationLogger
    chat_call_with_loading = deps.chat_call_with_loading
    GENERATE_WORKOUT_TOOL = deps.generate_workout_tool
    handle_function_call = deps.handle_function_call
    execute_workout_generation = deps.execute_workout_generation
    save_conversation = deps.save_conversation
    list_available_progress = deps.list_available_progress
    delete_progress_file = deps.delete_progress_file
    CONVERSATION_FILE = deps.conversation_file
    OpenAI = deps.OpenAI
    httpx = deps.httpx
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Workout Assistant & Generator")
    parser.add_argument(
        "--equipment-file",
        type=str,
        help="Path to JSON file containing available equipment (with 'equipments' and optionally 'accessoryEquipments' arrays)"
    )
    reasoner_group = parser.add_mutually_exclusive_group()
    reasoner_group.add_argument(
        "--use-reasoner",
        action="store_true",
        help="Use reasoner model for plan index/emitting without interactive prompt"
    )
    reasoner_group.add_argument(
        "--no-reasoner",
        action="store_true",
        help="Use chat model for plan index/emitting without interactive prompt"
    )
    reasoner_group.add_argument(
        "--hybrid-fast",
        action="store_true",
        help="Use reasoner for plan index and chat model for emitters (faster overall)"
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
    
    # Load equipment from file if provided
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
    # Configure timeout: 20 minutes (1200 seconds) to allow for:
    # - Up to 10 minutes wait before inference starts (DeepSeek API limit)
    # - Time for inference to complete
    # - Buffer for network delays
    timeout = httpx.Timeout(1200.0, connect=60.0)  # 20 min read, 60s connect
    http_client = httpx.Client(timeout=timeout)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", http_client=http_client)                                                                                                                                                                        
    
    # Load previous conversation if it exists
    loaded_messages = load_conversation()
    resumed = False
    if loaded_messages:
        messages = loaded_messages
        # Add equipment context if provided and not already in messages
        if provided_equipment and not has_equipment_in_messages(messages):
            equipment_content = format_equipment_for_conversation(provided_equipment)
            messages.append({"role": "system", "content": equipment_content})
        resumed = True
    else:
        messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
        # Add equipment context if provided
        if provided_equipment:
            equipment_content = format_equipment_for_conversation(provided_equipment)
            messages.append({"role": "system", "content": equipment_content})
    
    # Per-conversation debug log: load or create conversation_id, create logger
    meta = load_conversation_meta()
    if meta and resumed:
        conversation_id = meta["conversation_id"]
    else:
        conversation_id = str(uuid.uuid4())
        save_conversation_meta(conversation_id)
    short_cid = conversation_id[:8] if len(conversation_id) >= 8 else conversation_id
    log_dir = get_log_dir(script_dir)
    log_path = os.path.join(log_dir, f"conversation_{short_cid}.log")
    logger = ConversationLogger(log_path)
    log_ref = [logger]
    
    def save_and_close():
        save_conversation(messages)
        if log_ref[0]:
            log_ref[0].close()
    atexit.register(save_and_close)
    
    # Welcome block (log_print duplicates to log file)
    if resumed:
        logger.log_print("=" * 70)
        logger.log_print("Workout Assistant & Generator")
        logger.log_print("=" * 70)
        logger.log_print("")
        logger.log_print("✓ Resumed previous conversation")
        logger.log_print(f"  Loaded {len(messages) - 1} previous messages")
        logger.log_print("")
        logger.log_print("Commands:")
        logger.log_print("  • Type normal messages to chat with the assistant")
        logger.log_print("  • Type /ml (or /multiline) to enter multi-line mode, finish with a line containing /end")
        logger.log_print("  • Type /generate or /generate <prompt> to generate workout JSON")
        logger.log_print("  • Type /resume to resume a failed or interrupted generation")
        logger.log_print("  • Type /list-progress to list all saved generation progress")
        logger.log_print("  • Type /clear-progress <session_id> to delete a progress file")
        logger.log_print("  • Type /exit to quit")
        logger.log_print("  • Type /clear to start a fresh conversation")
        logger.log_print("  • Press Ctrl+C during generation to cancel")
        logger.log_print("")
        logger.log_print("=" * 70)
        logger.log_print("")
    else:
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
        logger.log_print("Commands:")
        logger.log_print("  • Type normal messages to chat with the assistant")
        logger.log_print("  • Type /ml (or /multiline) to enter multi-line mode, finish with a line containing /end")
        logger.log_print("  • Type /generate or /generate <prompt> to generate workout JSON")
        logger.log_print("  • Type /resume to resume a failed or interrupted generation")
        logger.log_print("  • Type /list-progress to list all saved generation progress")
        logger.log_print("  • Type /clear-progress <session_id> to delete a progress file")
        logger.log_print("  • Type /exit to quit")
        logger.log_print("  • Type /clear to start a fresh conversation")
        logger.log_print("  • Press Ctrl+C during generation to cancel")
        logger.log_print("")
        logger.log_print("=" * 70)
        logger.log_print("")
                                                                                                                                                                                                                                                   
    while True:
        user_input = input("You> ").strip()
        if not user_input:
            continue
        if user_input.lower() == "/exit":
            save_conversation(messages)
            break
        if user_input.lower() == "/clear":
            if log_ref[0]:
                log_ref[0].close()
            conversation_id = str(uuid.uuid4())
            save_conversation_meta(conversation_id)
            short_cid = conversation_id[:8] if len(conversation_id) >= 8 else conversation_id
            log_path = os.path.join(get_log_dir(script_dir), f"conversation_{short_cid}.log")
            log_ref[0] = ConversationLogger(log_path)
            logger = log_ref[0]
            messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
            # Re-add equipment context if provided
            if provided_equipment:
                equipment_content = format_equipment_for_conversation(provided_equipment)
                messages.append({"role": "system", "content": equipment_content})
            if os.path.exists(CONVERSATION_FILE):
                try:
                    os.remove(CONVERSATION_FILE)
                except Exception as e:
                    logger.log_print(f"Warning: Failed to delete conversation file: {e}")
            logger.log_print("Conversation cleared. Starting fresh.")
            logger.log_print("")
            continue

        # Multi-line input mode: /ml or /multiline
        if user_input.lower() in ("/ml", "/multiline"):
            logger.log_print("Entering multi-line mode. Paste your message; type '/end' on a new line to finish.")
            logger.log_print("(Lines are sent as a single message.)")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                # Do not strip spaces inside the content; only remove trailing newline
                if line.strip() == "/end":
                    break
                lines.append(line)
            # Join with newline characters to preserve formatting
            user_input = "\n".join(lines).rstrip("\n")
            if not user_input:
                # Nothing captured, go back to prompt
                continue

        if user_input.startswith("/generate"):
            logger.log("You> " + user_input)
            # Parse command: /generate [prompt]
            custom = user_input[len("/generate"):].strip()
            result = execute_workout_generation(
                client,
                messages,
                custom,
                None,
                provided_equipment,
                logger,
                script_dir,
                force_use_reasoner=force_use_reasoner,
            )
            
            if result["success"]:
                for e in result.get("emitter_conversations", []):
                    messages.append({
                        "role": "emitter",
                        "step": e["step"],
                        "item_id": e["item_id"],
                        "request_messages": e["request_messages"],
                        "response_content": e["response_content"],
                    })
                save_conversation(messages)
            else:
                if result["error"]:
                    logger.log_print(f"Generation error: {result['error']}")
            continue
        
        if user_input.lower() == "/resume":
            logger.log("You> /resume")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            
            # Filter to incomplete only
            incomplete = [p for p in progress_list if p["status"] == "incomplete"]
            if not incomplete:
                logger.log_print("No incomplete generations found. All saved progress is complete.")
                continue
            
            logger.log_print("\nAvailable incomplete generations:")
            logger.log_print("=" * 70)
            for i, prog in enumerate(incomplete, 1):
                timestamp_str = prog.get("timestamp", "Unknown")
                try:
                    dt = datetime.fromisoformat(timestamp_str)
                    timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
                logger.log_print(f"{i}. Session: {prog['short_id']} | Step: {prog['current_step']} | {timestamp_str}")
            logger.log_print("=" * 70)
            
            try:
                choice = input(f"\nSelect generation to resume (1-{len(incomplete)}) or 'c' to cancel: ").strip()
                logger.log("resume choice: " + choice)
                if choice.lower() == 'c':
                    continue
                idx = int(choice) - 1
                if 0 <= idx < len(incomplete):
                    selected = incomplete[idx]
                    logger.log_print(f"\nResuming session {selected['short_id']}...")
                    result = execute_workout_generation(
                        client,
                        messages,
                        "",
                        selected["session_id"],
                        provided_equipment,
                        logger,
                        script_dir,
                        force_use_reasoner=force_use_reasoner,
                    )
                    
                    if result["success"]:
                        for e in result.get("emitter_conversations", []):
                            messages.append({
                                "role": "emitter",
                                "step": e["step"],
                                "item_id": e["item_id"],
                                "request_messages": e["request_messages"],
                                "response_content": e["response_content"],
                            })
                        save_conversation(messages)
                    else:
                        if result["error"]:
                            logger.log_print(f"Resume error: {result['error']}")
                else:
                    logger.log_print("Invalid selection.")
            except (ValueError, KeyboardInterrupt):
                logger.log_print("Cancelled.")
            continue
        
        if user_input.lower() == "/list-progress":
            logger.log("You> /list-progress")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            
            logger.log_print("\nAll saved generation progress:")
            logger.log_print("=" * 70)
            for prog in progress_list:
                timestamp_str = prog.get("timestamp", "Unknown")
                try:
                    dt = datetime.fromisoformat(timestamp_str)
                    timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
                status_icon = "✓" if prog["status"] == "complete" else "○"
                logger.log_print(f"{status_icon} Session: {prog['short_id']} | Step: {prog['current_step']} | {timestamp_str} | {prog['status']}")
            logger.log_print("=" * 70)
            continue
        
        if user_input.lower().startswith("/clear-progress"):
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
        
        if user_input.lower() == "/clear-all-progress":
            logger.log("You> /clear-all-progress")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            
            confirm = input(f"Are you sure you want to delete all {len(progress_list)} progress file(s)? (yes/no): ").strip().lower()
            logger.log("clear-all-progress confirm: " + confirm)
            if confirm == "yes":
                deleted_count = 0
                for prog in progress_list:
                    if delete_progress_file(prog["session_id"], script_dir):
                        deleted_count += 1
                logger.log_print(f"Deleted {deleted_count} progress file(s).")
            else:
                logger.log_print("Cancelled.")
            continue

        logger.log("You> " + user_input)
        messages.append({"role": "user", "content": user_input})
        try:
            tools = [GENERATE_WORKOUT_TOOL]
            api_messages = [m for m in messages if m.get("role") != "emitter"]
            content, tool_calls = chat_call_with_loading(client, api_messages, tools, logger)
            
            if content is None and tool_calls is None:
                # Cancelled - don't add to conversation history
                messages.pop()  # Remove the user message since we cancelled
                logger.log_print("Cancelled. Returning to prompt...")
                continue
            
            # Add assistant message (with content if any, and tool_calls if any)
            assistant_message = {"role": "assistant"}
            if content:
                assistant_message["content"] = content
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in tool_calls
                ]
            messages.append(assistant_message)
            
            # If there's text content, display it
            if content:
                logger.log_print(f"Assistant> {content}")
            
            # Process tool calls if any
            if tool_calls:
                should_exit = False
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}
                    logger.log_section("tool_call " + function_name)
                    logger.log_request("tool " + function_name, json.dumps(function_args, ensure_ascii=False))
                    
                    # Execute function call
                    function_result = handle_function_call(
                        client,
                        messages,
                        function_name,
                        function_args,
                        provided_equipment,
                        logger,
                        script_dir,
                        force_use_reasoner=force_use_reasoner,
                    )
                    
                    logger.log_response("tool result " + function_name, function_result.get("result", ""), truncate_at=8000)
                    # Always surface tool result to the terminal (especially failures),
                    # otherwise generation can appear to stop silently.
                    tool_result_text = function_result.get("result", "")
                    if tool_result_text:
                        logger.log_print(tool_result_text)
                    # Add function result to conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": function_result["result"]
                    })
                    
                    # Check if we should exit
                    if function_result.get("should_exit", False):
                        should_exit = True
                        # Save conversation before exiting
                        save_conversation(messages)
                        break
                
                if should_exit:
                    # Exit the conversation loop
                    break
                
                # If not exiting, get assistant's follow-up response
                api_messages = [m for m in messages if m.get("role") != "emitter"]
                follow_up_content, follow_up_tool_calls = chat_call_with_loading(client, api_messages, tools, logger)
                if follow_up_content:
                    logger.log_print(f"Assistant> {follow_up_content}")
                    messages.append({"role": "assistant", "content": follow_up_content})
                    # Save conversation after assistant response
                    save_conversation(messages)
            else:
                # No tool calls, just save conversation
                save_conversation(messages)
                
        except KeyboardInterrupt:
            logger.log_print("\nCancelled. Returning to prompt...")
            # Remove the user message from history since we cancelled
            messages.pop()
            continue
        except Exception as e:
            logger.log_print(f"Error: {e}")
            # Remove the user message from history on error
            messages.pop()

