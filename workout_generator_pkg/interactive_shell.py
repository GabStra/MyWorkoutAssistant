"""Interactive CLI shell handlers."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import uuid
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from .constants import DEEPSEEK_MODEL, EXACT_GENERATION_CONFIRMATION
from .muscle_roles import MUSCLE_ROLE_GUIDANCE
from .planning_tools import (
    SET_WORKOUT_REQUIREMENTS_TOOL, AUDIT_WORKOUT_PLAN_TOOL, REPAIR_WORKOUT_PLAN_TOOL,
    workout_requirements_tool, construction_workout_tool,
    set_workout_requirements, audit_workout_plan, confirmed_draft,
    planning_tool_failure, requirements_approved, require_approved_requirements, PlanningInputError,
    _latest_result,
)
from .conversation_store import normalize_conversation_messages
from .logging_ui import LoadingIndicator, print_markdown
from .training_history import TrainingHistory, GET_TRAINING_EVIDENCE_TOOL, HISTORY_PLANNING_INSTRUCTION
from .plan_review import review_draft, review_followup_instructions, review_requirements, record_planning_decisions
from .planning_decisions import RECORD_PLANNING_DECISIONS_TOOL, render_decisions
from .generation_audit import audit_policy, available_muscle_targets
from .planner_context import focus_planner_context, request_planning_state, pending_reaudit, planner_response_profile
from .deps import resolve_shell_deps
from .exercise_library_tools import (
    SEARCH_EXERCISE_LIBRARY_TOOL, execute_library_tool, execute_library_searches,
)

CANONICAL_PLANNING_INSTRUCTION = (
    "For library-backed workout planning, use search_exercise_library, set_workout_requirements and audit_workout_plan. "
    "The latter replaces the old select_exercises/audit_workout_volume preview workflow. "
    "Record the user's requirements separately, never relax them during automatic repair, and use the current requirementsId. "
    "Clarify material ambiguity before calling set_workout_requirements; otherwise record the original targets before searching. "
    "Stop for CONFIRM REQUIREMENTS; do not resolve tradeoffs without user approval. "
    "Restriction wording is resolved to library IDs by set_workout_requirements. Only for restriction_policy_unresolved (missing or stale policy), "
    "re-record unchanged requirements and display the resolved policy for approval. "
    "Preserve all movement/equipment qualifiers when extracting restrictions. A load limitation on one named exercise does not imply a family-wide ban. "
    "Do not shorten a specific restriction to a broader category; ask for clarification if its scope is ambiguous. "
    "Material ambiguity includes targets, grouped muscle names, balance counting rules and exception scope. Ask and wait unless the user already delegated that choice; then record a supported choice within the delegated scope. "
    "Do not pick an interpretation and label it unchanged. Preserve full exception qualifiers (movement and equipment). "
    "Extract targets, restrictions and explicitly requested exercise coverage; original instructions and clarification answers are retained without rewritten notes. "
    "When the user chooses an interpretation or delegates a choice, use record_planning_decisions to record and disclose it before extracting requirements or auditing a draft. "
    "Reserve that tool for requirement interpretations or explicit user decisions. Ordinary exercise substitutions and prescriptions within approved requirements go directly into the draft patch and audit, without a separate planning-choice review. "
    "Assign each explicit requiredCoverage key to qualifying draft exercises using satisfiesCoverage. Missing assignments fail before execution review; the reviewer verifies the actual movements. "
    "Use the resolvedDecisions already supplied; do not re-ask settled choices without a concrete new contradiction. "
    "Application auditPolicy owns credit and timing estimates. Do not invent user requirements to match it; ask about material conflicts. "
    "For unresolved or ambiguous restriction errors, ask the stated clarification and wait for the user's answer; "
    "do not remove, narrow, broaden or replace the term merely to make resolution pass. "
    "Start discovery with at most six queries across all calls, covering required movement patterns, not a catalog of every possible exercise. "
    "Respect equipment and explicit exclusions in every query. Once candidates are returned, retrieve relevant history and submit a draft. "
    "Search again only for a specific gap found by the audit or a new user request; do not exhaustively explore alternatives. "
    "The user command /continue means resume the saved draft and pending tool feedback without changing approved requirements or restarting discovery. "
    "Do not declare targets infeasible by adding muscle-set credits as if they were separate working sets; compound overlap matters. Attempt an audited draft before proposing a tradeoff. "
    "Follow constructionTask when present: build and audit one workout session at a time. Intermediate numerical failures are expected; Python owns arithmetic. Do not try to solve the entire allocation before calling the audit. For repairs, prefer targeted RFC 6902 patches "
    "through audit_workout_plan with requirementsId, baseDraftId=currentDraftId and patch. Copy the backend revision placeholder; do not invent it. "
    "Patch only changed values, sets, movements or ordering; Python preserves untouched fields and validates the full result. "
    "Use a full replacement only for an initial draft or a necessary whole-structure redesign. "
    "Python runs an independent execution/requirements review after structural, evidence and numerical checks pass. "
    "During intermediate numerical repairs, earlier review findings are guidance pending fresh review; they are not approval. "
    "Its blocking findings must be repaired before a preview is approved. Follow their specific repair instructions; "
    "do not change requirements, relabel exercises, or submit the unchanged draft to get a different review. "
    "Questions and explanations do not change the draft. Do not repeat requirements or audit calls for them; reuse stored IDs and results. "
    "For actual requested edits, submit the patch before claiming that a change was applied. "
    "Submit proposed repairs to the audit before presenting them as workable solutions. Never fabricate rep drop-off or cross-variant starting loads to satisfy a reviewer; "
    "preserve rep ranges and retrieve current evidence for changed variants, using calibration where exact loads are unsupported. "
    "Batch independent exercise queries in one search call, reuse previously returned library references, and search only missing movements. "
    "Use creditsPerWorkingSet from search results to balance every session and weekly totals before submitting the first draft. "
    "On repair, preserve the whole allocation's constraints and all original requirements. Follow the backend repairTask when supplied. Redistribute sets across existing movements before searching; "
    "a muscle at its ceiling does not prove another isolation exercise is required. "
    "Make the smallest coordinated repair and submit it promptly; intermediate drafts may still fail. "
    "Use the audit tools for calculations and feedback instead of solving every constraint in one long internal response. "
    "If a model lookup times out or exhausts its budget, do not repeat the same expensive request automatically; explain the limit and ask the user how to proceed. "
    "Python displays the passing preview automatically; do not author a separate workout preview. "
    "Only generate after a fresh CONFIRM GENERATE; export uses that exact approved draft."
)


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
    exercise_definitions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    messages = [_message("system", content=base_system_prompt)]
    if provided_equipment:
        messages.append(
            _message(
                "system",
                content=format_equipment_for_conversation(provided_equipment),
            )
        )
    if exercise_definitions:
        messages.append(_message(
            "system",
            content=(
                f"A strict exercise library with {len(exercise_definitions)} definitions is loaded. "
                "It is the sole allowed movement source. Clarify material ambiguity with the user before recording requirements. "
                "Otherwise call set_workout_requirements, then wait for CONFIRM REQUIREMENTS. After approval, use search_exercise_library for a small batch of matching entries. "
                "Then call audit_workout_plan with the complete structured draft and current requirementsId. "
                "Repair returned issues with targeted JSON patches against currentDraftId, then call the tool again. Never relax requirements to make a repair pass. "
                "Python displays the passing draft automatically; do not write or reproduce a separate workout preview. "
                "The displayed draft is the one exported after CONFIRM GENERATE; no second planning pass occurs. "
                "Submit a replacement only for actual draft edits; ordinary questions do not require re-auditing. Only change requirements when the user explicitly requests it. "
                "Mobility/ramp-up instructions belong in notes and warm-up flags, not invented standalone exercises. "
                "If a requested exercise is absent, explain the available alternative before confirmation; "
                "never claim an absent movement is library sourced."
                " For volume, use the retrieved library's primary/secondary roles exactly. Effective set targets can be met by direct and indirect work; they do not require direct isolation work for every muscle. "
                + MUSCLE_ROLE_GUIDANCE
            ),
        ))
    return messages


def _load_exercise_library_payload(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as source:
        root = json.load(source)
    payload = root
    if isinstance(root, dict) and isinstance(root.get("WorkoutStore"), dict):
        payload = root["WorkoutStore"]
    definitions = payload.get("exerciseDefinitions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list):
        raise ValueError("expected a schema-v2 store or object containing exerciseDefinitions")
    if any(not isinstance(item, dict) or not item.get("id") for item in definitions):
        raise ValueError("every exercise definition must be an object with an id")
    from .muscle_roles import validate_training_muscles
    for definition in definitions:
        validate_training_muscles(definition)
    movements = []
    if isinstance(root, dict):
        movements = root.get("exerciseMovements") or root.get("ExerciseMovements") or []
    return {
        "exerciseDefinitions": definitions,
        "equipments": payload.get("equipments", []) if isinstance(payload, dict) else [],
        "accessoryEquipments": payload.get("accessoryEquipments", []) if isinstance(payload, dict) else [],
        "exerciseMovements": movements,
    }


def _load_exercise_definitions(filepath: str) -> List[Dict[str, Any]]:
    return _load_exercise_library_payload(filepath)["exerciseDefinitions"]


def _merge_library_items(existing: List[Dict[str, Any]], imported: List[Dict[str, Any]], label: str):
    merged = {item.get("id"): item for item in existing if isinstance(item, dict)}
    for item in imported:
        item_id = item.get("id") if isinstance(item, dict) else None
        if not item_id:
            raise ValueError(f"every {label} item must have an id")
        if item_id in merged and merged[item_id] != item:
            raise ValueError(f"conflicting {label} content for id {item_id}")
        merged[item_id] = item
    return list(merged.values())


def _conversation_log_path(script_dir: str, conversation_id: str) -> str:
    short_cid = conversation_id[:8] if len(conversation_id) >= 8 else conversation_id
    return os.path.join(script_dir, "logs", f"conversation_{short_cid}.log")


def _create_logger(ConversationLogger, script_dir: str, conversation_id: str):
    log_path = _conversation_log_path(script_dir, conversation_id)
    log_dir = os.path.dirname(log_path)
    os.makedirs(log_dir, exist_ok=True)
    recover_transcript = os.path.isfile(log_path) and os.path.getsize(log_path) == 0
    logger = ConversationLogger(log_path)
    logger.log(f"Conversation logging started: {conversation_id}")
    if recover_transcript:
        from .conversation_store import load_conversation_record
        record = load_conversation_record(conversation_id, script_dir) or {}
        logger.log('Recovering empty log from saved conversation; original timestamps are included below.')
        for message in record.get('messages', []):
            if message.get('role') != 'system':
                logger.log(json.dumps(message, ensure_ascii=False))
    return logger, log_path


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
            if role == "assistant" and isinstance(content, str):
                if message.get('unvalidatedProposal'):
                    logger.log_print('[Unvalidated draft discussion; use the passing preview for actual prescriptions.]')
                print_markdown(content, logger)
            else:
                logger.log_print(_format_json(content))
        if role == "assistant" and message.get("tool_calls"):
            logger.log_print("[Tool call triggered]")

        logger.log_print("-" * 70)


def _ensure_tool_responses(messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], bool]:
    repaired = normalize_conversation_messages(messages)
    return repaired, repaired != messages


def _messages_for_api(messages: List[Dict[str, Any]], planning_enabled=False, training_history=None, provided_equipment=None) -> List[Dict[str, Any]]:
    repaired, _ = _ensure_tool_responses(messages)
    result = [{key: value for key, value in message.items() if key not in ("canonicalDraftPreview", "canonicalRequirementsPreview", "unvalidatedProposal")}
              for message in repaired if message.get("role") != "emitter"]
    tool_names = {call["id"]: call["function"]["name"] for message in result
                  for call in message.get("tool_calls", [])}
    seen_entries = set()
    for message in result:
        name = tool_names.get(message.get("tool_call_id"))
        if training_history and name == "get_training_evidence":
            try:
                evidence = json.loads(message.get('content', ''))
                if evidence.get('historyFingerprint') != training_history.fingerprint:
                    message['content'] = json.dumps({'staleHistory': True, 'instruction': 'Retrieve current training evidence again.'})
            except (TypeError, ValueError, AttributeError):
                pass
        if name not in ("audit_workout_plan", "search_exercise_library"):
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        if name == "audit_workout_plan" and "audit" in payload:
            audit = payload["audit"]
            compact = {key: payload[key] for key in ("passed", "requirementsId", "draftId", "currentDraftId", "instruction", "historyFingerprint") if key in payload}
            compact["errors"] = payload.get("errors", [])
            compact['reviewVersion'] = payload.get('review', {}).get('version')
            if payload.get('review', {}).get('followupReview'):
                compact['followupReview'] = payload['review']['followupReview']
            for key in ('reviewPending', 'previousReviewFindings'):
                if key in payload:
                    compact[key] = payload[key]
            compact["audit"] = {key: audit[key] for key in ("targets", "assumptions", "weeklyVolume") if key in audit}
            compact["audit"]["workouts"] = [
                {key: workout[key] for key in ("name", "volume", "contributions", "timing", "estimatedSeconds") if key in workout}
                for workout in audit.get("workouts", [])]
            payload = compact
        elif name == "search_exercise_library" and "results" in payload:
            payload = json.loads(json.dumps(payload))
            for query in payload["results"]:
                for index, exercise in enumerate(query.get("exercises", [])):
                    if training_history and payload.get('historyFingerprint') != training_history.fingerprint:
                        exercise.pop('trainingEvidence', None)
                    identity = (payload.get("libraryFingerprint"), exercise["id"])
                    if identity in seen_entries:
                        query["exercises"][index] = {"id": exercise["id"], "relevanceScore": exercise.get("relevanceScore")}
                    else:
                        seen_entries.add(identity)
        if name == 'audit_workout_plan':
            payload.pop('submittedDraft', None)
        message["content"] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if planning_enabled:
        result = focus_planner_context(result, repaired, provided_equipment)
        result.append({"role": "system", "content": CANONICAL_PLANNING_INSTRUCTION})
        result.append({'role': 'system', 'content': 'Application auditPolicy (estimates and counting conventions, not user requirements): '
            + json.dumps(audit_policy(available_muscle_targets(provided_equipment))) + '. Muscle credits use the selected library roles. Omit unspecified muscle targets; 0-0 is a prohibition. '
            'Apply capabilityLimits when extracting targets or proposing choices. Unsupported granularity is a software/library limitation; do not offer an aggregate field as a way to verify its regions separately. '
            'Explicit timing instructions must be reflected in estimates; ask about a conflict the current estimator cannot represent.'})
        if not requirements_approved(messages):
            result.append({'role': 'system', 'content': 'Current stage: extract requirements only. Reuse resolvedDecisions and record any relevant user-delegated choices with record_planning_decisions. Ask and wait only for remaining material ambiguity outside that authority. Otherwise call set_workout_requirements, display the result and wait for CONFIRM REQUIREMENTS. Do not design a workout or change goals to solve tradeoffs.'})
    if training_history:
        result.append({'role': 'system', 'content': HISTORY_PLANNING_INSTRUCTION + '\nCurrent history snapshot: ' + json.dumps(training_history.context())})
    return result


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
    logger.log_print("  • Type /view to view the latest workout preview in a Markdown pager")
    logger.log_print("  • Type /continue to resume a paused draft using saved lookups and audit feedback")
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
    allow_educated_load_guesses=True,
    training_history=None,
    progress=None,
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
        last_user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), -1)
        for message in messages[last_user_index + 1:]:
            if message.get("role") == "tool":
                try:
                    feedback = json.loads(message.get("content") or "{}")
                except (TypeError, ValueError):
                    continue
                if isinstance(feedback, dict) and feedback.get("requires_plan_revision"):
                    return {"result": "Generation blocked: show the revised preview and wait for a fresh CONFIRM GENERATE.",
                            "should_exit": False, "generation_result": None}
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
        library = (provided_equipment or {}).get("exerciseDefinitions")
        if library:
            try:
                snapshot = confirmed_draft(messages, provided_equipment, allow_educated_load_guesses, require_confirmation=True)
                review_followup_instructions(client, snapshot, messages, provided_equipment, training_history, logger)
                if training_history and (snapshot.get('historyFingerprint') != training_history.fingerprint
                    or training_history.unreviewed(snapshot['planIndex'], messages, provided_equipment)
                    or training_history.load_suitability_errors(snapshot['planIndex'], messages, provided_equipment)):
                    raise ValueError('Review current training evidence and re-audit the draft before confirming generation.')
            except ValueError as error:
                feedback = planning_tool_failure("generate_workout", error)
                feedback["requires_plan_revision"] = True
                return {
                    "result": json.dumps(feedback, ensure_ascii=False), "continue_planning": True,
                    "should_exit": False, "generation_result": None,
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
            if generation_result.get("requires_plan_revision"):
                result_message = json.dumps({
                    "requires_plan_revision": True,
                    "instruction": "Revise the plan using this deterministic audit. Keep the user's agreed goals and equipment restrictions. You may change exercises, pairings and prescriptions as needed. Validate library selection, show the entire revised preview, and obtain a NEW CONFIRM GENERATE before regenerating. If goals cannot be met, explain the conflict and ask the user to resolve it; never silently relax them.",
                    "audit": generation_result["programming_audit"],
                }, ensure_ascii=False)

        return {
            "result": result_message,
            "should_exit": False,
            "generation_result": generation_result,
        }

    if function_name == 'record_planning_decisions':
        result = record_planning_decisions(client, function_args, messages, logger, progress, equipment=provided_equipment)
        return {'result': json.dumps(result, ensure_ascii=False), 'should_exit': False, 'generation_result': None,
                'decision_preview': ('Recorded planning choices:\n' + render_decisions(result['decisions'])) if result['passed'] and not result.get('cached') else None}

    if function_name == "set_workout_requirements":
        result = set_workout_requirements(function_args, messages, provided_equipment or {}, client, progress)
        result = review_requirements(client, result, messages, logger, progress)
        if not result['passed']:
            return {'result': json.dumps(result, ensure_ascii=False), 'should_exit': False, 'generation_result': None}
        pending = not requirements_approved(messages, result)
        return {"result": json.dumps(result, ensure_ascii=False), "requirements_preview": result["requirementsPreview"] if pending else None,
                "requirements_pending": pending, "requirements_id": result['requirementsId'],
                "should_exit": False, "generation_result": None}

    if function_name == "audit_workout_plan":
        result = audit_workout_plan(function_args, provided_equipment or {}, messages, allow_educated_load_guesses, training_history)
        if training_history:
            if result.get('historyFingerprint') != training_history.fingerprint:
                result['cached'] = False
            result['historyFingerprint'] = training_history.fingerprint
            if result.get('preview'):
                result['preview'] = result['preview'].split('\n\nTraining history snapshot:', 1)[0]
                result['preview'] += f"\n\nTraining history snapshot: `{training_history.fingerprint[:12]}`. Comparable records reviewed where available; historical loads are not measured strength limits."
        result = review_draft(client, result, messages, provided_equipment or {}, training_history, logger, progress)
        if not result.get('passed'):
            result.pop('planIndex', None)
        return {"result": json.dumps(result, ensure_ascii=False), "draft_preview": None if result.get("cached") else result.get("preview"),
                "draft_id": result.get("draftId", result["requirementsId"]), "should_exit": False, "generation_result": None}

    if function_name == 'get_training_evidence':
        require_approved_requirements(messages)
        if training_history is None:
            raise ValueError('No history backup loaded; start with --history-backup-file')
        return {'result': json.dumps(training_history.evidence(function_args, provided_equipment or {}, client=client)),
                'should_exit': False, 'generation_result': None}

    if function_name in ("search_exercise_library", "select_exercises"):
        if (provided_equipment or {}).get('exerciseDefinitions'):
            require_approved_requirements(messages)
        return {
            "result": json.dumps(execute_library_tool(function_name, function_args, provided_equipment, client=client, messages=messages, **({'progress': progress} if progress else {})), ensure_ascii=False),
            "should_exit": False, "generation_result": None,
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
    parser.add_argument(
        "--exercise-library-file",
        type=str,
        help="Path to a schema-v2 WorkoutStore or JSON object containing exerciseDefinitions",
    )
    parser.add_argument('--history-backup-file', help='AppBackup containing actual workout history; also supplies the exercise library when no --exercise-library-file is given')
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
    calibration_group = parser.add_mutually_exclusive_group()
    calibration_group.add_argument(
        "--allow-educated-load-guesses",
        dest="allow_educated_load_guesses",
        action="store_true",
        help="Use emitted starting loads when complete (default; retained for command compatibility)",
    )
    calibration_group.add_argument(
        "--require-load-calibration",
        dest="allow_educated_load_guesses",
        action="store_false",
        help="Require calibration for every weight-loaded exercise",
    )
    parser.set_defaults(allow_educated_load_guesses=True)
    args = parser.parse_args()
    training_history = None
    if args.history_backup_file:
        try:
            with LoadingIndicator('Indexing workout history'):
                training_history = TrainingHistory.from_file(args.history_backup_file)
            print(f"Loaded training history: {training_history.context()['definitionsWithEvidence']} exercise definitions with evidence")
            if not args.exercise_library_file:
                args.exercise_library_file = args.history_backup_file
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(f'Cannot load history backup: {error}')
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

    exercise_definitions = None
    if args.exercise_library_file:
        try:
            library_payload = _load_exercise_library_payload(args.exercise_library_file)
            exercise_definitions = library_payload["exerciseDefinitions"]
            print(f"Loaded {len(exercise_definitions)} exercise definition(s) from: {args.exercise_library_file}")
        except Exception as e:
            print(f"Error loading exercise library file: {e}", file=sys.stderr)
            sys.exit(1)
        provided_equipment = dict(provided_equipment or {})
        provided_equipment["equipments"] = _merge_library_items(
            provided_equipment.get("equipments", []), library_payload["equipments"], "equipment"
        )
        provided_equipment["accessoryEquipments"] = _merge_library_items(
            provided_equipment.get("accessoryEquipments", []),
            library_payload["accessoryEquipments"],
            "accessory equipment",
        )
        provided_equipment["exerciseDefinitions"] = exercise_definitions
        provided_equipment["exerciseMovements"] = library_payload["exerciseMovements"]

    api_key = _resolve_api_key()
    timeout = httpx.Timeout(1200.0, connect=60.0)
    http_client = httpx.Client(timeout=timeout)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", http_client=http_client)
    print(f"DeepSeek model: {DEEPSEEK_MODEL}")
    get_log_dir(script_dir)

    conversation_id = str(uuid.uuid4())
    messages = _build_initial_messages(
        BASE_SYSTEM_PROMPT,
        provided_equipment,
        format_equipment_for_conversation,
        exercise_definitions,
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
        # Normalize a saved copy; placeholder responses for pending calls must not enter live state.
        saved_messages, _ = _ensure_tool_responses(state["messages"])
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
            saved_messages,
            conversation_id=state["conversation_id"],
            script_dir=script_dir,
            metadata=merged_metadata,
        )
        if state.get('logger'):
            state['logger'].log(f"Conversation checkpoint saved: {len(saved_messages)} turns.")

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
        next_logger, next_log_path = _create_logger(ConversationLogger, script_dir, next_conversation_id)
        close_logger()
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
        if exercise_definitions and not requirements_approved(state['messages']):
            logger.log_print('Generation blocked: review and CONFIRM REQUIREMENTS before resuming library-backed generation.')
            return False
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
        try:
            user_input = input("You> ").strip()
        except KeyboardInterrupt:
            state["logger"].log_print("\nCancelled. Use /exit to quit.")
            continue
        if not user_input:
            continue
        command = user_input.lower()
        logger = state["logger"]

        if command == "/exit":
            persist_current()
            break

        if command == "/view":
            previews = [message for message in state["messages"] if message.get("canonicalDraftPreview") and message.get("content")]
            replies = previews or [message for message in state["messages"] if message.get("role") == "assistant" and message.get("content")]
            if replies:
                try:
                    print_markdown(replies[-1]["content"], logger, paged=True)
                except KeyboardInterrupt:
                    logger.log_print("\nClosed Markdown viewer.")
            else:
                logger.log_print("No assistant response or workout preview to view yet.")
            continue

        if command == "/clear":
            logger.log("You> /clear")
            next_messages = _build_initial_messages(
                BASE_SYSTEM_PROMPT,
                provided_equipment,
                format_equipment_for_conversation,
                exercise_definitions,
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
                except KeyboardInterrupt:
                    logger.log_print("\nCancelled multi-line input. Returning to prompt...")
                    lines.clear()
                    break
                except EOFError:
                    break
                if line.strip() == "/end":
                    break
                lines.append(line)
            user_input = "\n".join(lines).rstrip("\n")
            if not user_input:
                continue
            command = user_input.lower()

        if exercise_definitions and user_input.startswith('/generate '):
            # Export instructions must enter the conversation before any approval gate.
            user_input = user_input[len('/generate'):].strip()
            command = user_input.lower()

        if user_input.startswith("/generate"):
            logger.log("You> " + user_input)
            custom = user_input[len("/generate"):].strip()
            if exercise_definitions and not requirements_approved(state['messages']):
                logger.log_print('Generation blocked: review and CONFIRM REQUIREMENTS before generating.')
                continue
            if exercise_definitions:
                try:
                    snapshot = confirmed_draft(state["messages"], provided_equipment, args.allow_educated_load_guesses, require_confirmation=True)
                    review_followup_instructions(client, snapshot, state['messages'], provided_equipment, training_history, logger)
                    if training_history and (snapshot.get('historyFingerprint') != training_history.fingerprint
                        or training_history.unreviewed(snapshot['planIndex'], state['messages'], provided_equipment)
                        or training_history.load_suitability_errors(snapshot['planIndex'], state['messages'], provided_equipment)):
                        raise ValueError('Review current training evidence and re-audit the preview first')
                except ValueError as error:
                    logger.log_print(f"Generation blocked: {error}")
                    persist_current()
                    continue
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

            try:
                choice = input(f"\nSelect conversation (1-{len(conversations)}) or 'c' to cancel: ").strip().lower()
            except KeyboardInterrupt:
                logger.log_print("\nCancelled. Returning to prompt...")
                continue
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
            requirements_tool = workout_requirements_tool(provided_equipment)
            tools = [GENERATE_WORKOUT_TOOL]
            if exercise_definitions:
                tools = [requirements_tool, RECORD_PLANNING_DECISIONS_TOOL]
                if requirements_approved(state['messages']):
                    tools.extend([GENERATE_WORKOUT_TOOL, SEARCH_EXERCISE_LIBRARY_TOOL, AUDIT_WORKOUT_PLAN_TOOL])
            if training_history and requirements_approved(state['messages']):
                tools.append(GET_TRAINING_EVIDENCE_TOOL)
            generation_metadata: Optional[Dict[str, Any]] = None
            preview_ready = False
            requires_plan_revision = False
            failed_draft_signatures = set()
            failed_tool_signatures = set()
            planning_pause = None
            tool_round = 0
            while True:
                persist_current()
                api_messages = _messages_for_api(state["messages"], bool(exercise_definitions), training_history, provided_equipment)
                planning_state = request_planning_state(api_messages)
                repair_task = planning_state.get('repairTask')
                construction_task = planning_state.get('constructionTask')
                saved_reaudit = pending_reaudit(planning_state, user_input)
                request_tools = tools
                if planning_state.get('requirementsApproved') and not planning_state.get('planningDecisionNeeded'):
                    request_tools = [tool for tool in request_tools if tool.get('function', {}).get('name') != 'record_planning_decisions']
                request_options = planner_response_profile(planning_state)
                if construction_task:
                    request_tools = [construction_workout_tool(construction_task) if tool.get('function', {}).get('name') == 'audit_workout_plan' else tool
                                     for tool in request_tools]
                    logger.log_print(f"Construction task: {construction_task['action']}; one session, effort=low")
                if repair_task and not saved_reaudit:
                    request_tools = [REPAIR_WORKOUT_PLAN_TOOL if tool.get('function', {}).get('name') == 'audit_workout_plan' else tool
                                     for tool in request_tools]
                    logger.log_print(f"Repair task: {repair_task['baseDraftId']}, finding {repair_task['findingIndex'] + 1} "
                                     f"({repair_task['findingCode']}); targeted patch, effort=low")
                if saved_reaudit:
                    logger.log_print(f"Re-auditing saved draft {saved_reaudit['baseDraftId']} against the current requirements and validators.")
                    content, reasoning_content = None, None
                    tool_calls = [SimpleNamespace(id='reaudit_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='audit_workout_plan', arguments=json.dumps(saved_reaudit)))]
                else:
                    if exercise_definitions:
                        logger.log(f"Planner context: {len(state['messages'])} saved messages -> {len(api_messages)} request messages; "
                                   f"{len(json.dumps(api_messages, ensure_ascii=False))} serialized characters")
                    content, tool_calls, reasoning_content = chat_call_with_loading(client, api_messages, request_tools, logger, **request_options)

                if content is None and tool_calls is None:
                    if tool_round == 0:
                        state["messages"].pop()
                    logger.log_print("Cancelled. Returning to prompt...")
                    break

                has_content = content not in (None, "")
                has_tool_calls = bool(tool_calls)

                if not has_content and not has_tool_calls:
                    if tool_round == 0:
                        state["messages"].pop()
                    logger.log_print(
                        "The model returned an empty response with no tool call. "
                        "Nothing was added to the conversation; please retry."
                    )
                    break

                assistant_message: Dict[str, Any] = _message("assistant")
                if reasoning_content is not None:
                    assistant_message["reasoning_content"] = reasoning_content
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

                pending_audit = _latest_result(state['messages'], 'audit_workout_plan')[1]
                proposing = any(call.function.name in ('audit_workout_plan', 'record_planning_decisions') for call in (tool_calls or []))
                if has_content and (proposing or pending_audit.get('passed') is False):
                    assistant_message['unvalidatedProposal'] = True
                if has_content and not proposing:
                    if assistant_message.get('unvalidatedProposal'):
                        logger.log_print('Draft discussion — prescriptions and repairs below have not passed validation.')
                    print_markdown(content, logger)
                persist_current()

                if has_tool_calls:
                    pending_preview = None
                    batch_blocked = None
                    search_calls = []
                    for call in tool_calls:
                        if call.function.name == "search_exercise_library":
                            try:
                                arguments = json.loads(call.function.arguments)
                                queries = arguments.get("queries")
                                if isinstance(queries, list) and 1 <= len(queries) <= 6 and all(isinstance(q, str) and 0 < len(q.strip()) <= 200 for q in queries):
                                    search_calls.append((call.id, arguments))
                            except (ValueError, AttributeError):
                                pass
                    grouped_searches = {}
                    if len(search_calls) > 1 and all(call.function.name == 'search_exercise_library'
                                                     for call in tool_calls[:len(search_calls)]):
                        started = time.monotonic()
                        logger.log(f"Combined library search started: {len(search_calls)} calls")
                        logger.log_request("combined library queries", json.dumps(search_calls))
                        try:
                            require_approved_requirements(state['messages'])
                            with LoadingIndicator("Searching exercise library (combined queries)") as search_loading:
                                grouped_searches = execute_library_searches(search_calls, provided_equipment, client, state["messages"],
                                    progress=lambda done, total: search_loading.update(f"Exercise search: {done}/{total} batches, up to 3 workers"))
                        except Exception as search_error:
                            grouped_searches = {call_id: (planning_tool_failure('search_exercise_library', search_error) if isinstance(search_error, PlanningInputError) else {
                                'passed': False, 'errors': [{'code': 'library_search_failed', 'message': str(search_error)}],
                                'instruction': 'Report the failed lookup. Do not automatically repeat it, invent matches, or change workout requirements to hide the failure.',
                            }) for call_id, _ in search_calls}
                        finally:
                            logger.log(f"Combined library search finished ({time.monotonic() - started:.2f}s)")
                        logger.log_print(f"Exercise search finished ({len(search_calls)} grouped calls, {time.monotonic() - started:.1f}s).")
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        try:
                            function_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            function_args = {}
                        logger.log_section("tool_call " + function_name)
                        logger.log_request("tool " + function_name, json.dumps(function_args, ensure_ascii=False))

                        if planning_pause or batch_blocked:
                            reason = planning_pause or batch_blocked
                            state['messages'].append(_message('tool', tool_call_id=tool_call.id, content=json.dumps({
                                'passed': False, 'skipped': True, 'tool': function_name,
                                'errors': [{'code': 'tool_batch_blocked', 'message': reason}],
                                'instruction': 'This tool was not executed. Resolve the preceding result before submitting dependent work again.'})))
                            logger.log_print(f'Skipped {function_name}: a preceding step needs attention.')
                            persist_current()
                            continue

                        tool_message = _message(
                            "tool",
                            tool_call_id=tool_call.id,
                            content=(
                                "Tool call started but did not complete. "
                                "Treat this as a failed tool result if execution is interrupted."
                            ),
                        )
                        state["messages"].append(tool_message)

                        loading_label = {
                            'set_workout_requirements': 'Resolving workout requirements',
                            'record_planning_decisions': 'Checking planning choices',
                            "search_exercise_library": "Searching exercise library",
                            "audit_workout_plan": "Auditing workout volume and duration",
                            'get_training_evidence': 'Retrieving training evidence',
                        }.get(function_name)
                        loading = LoadingIndicator(loading_label) if loading_label and tool_call.id not in grouped_searches else None
                        if loading:
                            loading.start()
                        tool_started = time.monotonic()
                        try:
                            if construction_task and function_name == 'audit_workout_plan' and not saved_reaudit:
                                from .planning_tools import validate_construction_submission
                                validate_construction_submission(function_args, construction_task)
                            if (function_name == 'record_planning_decisions' and planning_state.get('requirementsApproved')
                                    and not planning_state.get('planningDecisionNeeded')):
                                raise PlanningInputError('planning_decision_not_needed', 'No pending user authorization or requirement interpretation needs recording.', '/',
                                    'Apply ordinary exercise substitutions and prescriptions through a draft patch and audit. Ask about genuine new ambiguity instead of inventing a requirement decision.')
                            if repair_task and function_name == 'audit_workout_plan' and (
                                    not isinstance(function_args, dict) or 'patch' not in function_args):
                                raise PlanningInputError('repair_patch_required', 'A saved repair task requires a JSON Patch.', '/patch',
                                    'Use repairTask.baseDraftId with requirementsId and patch against currentDraft. Leave untouched fields out; Python audits the complete result.')
                            if tool_call.id in grouped_searches:
                                function_result = {"result": json.dumps(grouped_searches[tool_call.id]), "should_exit": False, "generation_result": None}
                            else:
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
                                    training_history=training_history,
                                    progress=((lambda done, total: loading.update(f"Exercise search: {done}/{total} batches, up to 3 workers"))
                                              if function_name == 'search_exercise_library' else (lambda stage: loading.update(stage))) if loading else None,
                                )
                        except Exception as tool_error:
                            function_result = {
                                "result": json.dumps(planning_tool_failure(function_name, tool_error, function_args), ensure_ascii=False),
                                "should_exit": False,
                                "generation_result": None,
                            }
                        finally:
                            if loading:
                                loading.stop()
                            logger.log(f"Tool {function_name} finished ({time.monotonic() - tool_started:.2f}s)")

                        if training_history and function_name == 'search_exercise_library':
                            payload = json.loads(function_result.get('result', '{}'))
                            if 'results' in payload:
                                function_result['result'] = json.dumps(training_history.annotate_search(payload, provided_equipment))
                        if loading:
                            payload = json.loads(function_result.get('result', '{}'))
                            needs_attention = payload.get('passed') is False or payload.get('errors') or any(item.get('error') for item in payload.get('results', []))
                            stage = {'set_workout_requirements': 'Requirements', 'record_planning_decisions': 'Planning choices', 'search_exercise_library': 'Exercise search', 'get_training_evidence': 'Training history',
                                     'audit_workout_plan': 'Programming audit'}[function_name]
                            logger.log_print(f"{stage}: {'needs attention' if needs_attention else 'complete'} ({time.monotonic() - tool_started:.1f}s).")
                            if function_name == 'audit_workout_plan' and payload.get('reviewPending'):
                                logger.log_print('Full execution review deferred until numerical and evidence checks pass.')
                        logger.log_response("tool result " + function_name, function_result.get("result", ""), truncate_at=8000)
                        tool_result_text = function_result.get("result", "")
                        if tool_result_text and function_name == "generate_workout":
                            if function_result.get("continue_planning"):
                                logger.log_print("The current draft needs validation. Returning to planning before asking for fresh confirmation.")
                            elif (function_result.get("generation_result") or {}).get("requires_plan_revision"):
                                logger.log_print("The programming audit found issues. Returning them to the conversation to revise the plan before asking for confirmation again.")
                            else:
                                logger.log_print(tool_result_text)
                        tool_message["content"] = function_result["result"]
                        tool_message["timestamp"] = _timestamp_now()
                        persist_current()
                        if function_result.get('decision_preview'):
                            print_markdown(function_result['decision_preview'], logger)
                        try:
                            feedback = json.loads(function_result['result'])
                        except (ValueError, TypeError):
                            feedback = {}
                        if isinstance(feedback, dict):
                            if (function_name in ('record_planning_decisions', 'set_workout_requirements', 'audit_workout_plan')
                                    and feedback.get('passed') is False) or function_result.get('requirements_pending'):
                                batch_blocked = f'{function_name} must be resolved before dependent work can run.'
                            failures = feedback.get('errors') or [item['error'] for item in feedback.get('results', []) if item.get('error')]
                            if failures:
                                review_failure = next((error for error in failures if isinstance(error, dict)
                                    and error.get('code') in ('review_execution_failed', 'requirements_review_failed', 'decision_review_failed')), None)
                                if review_failure:
                                    review_stage = {'review_execution_failed': 'Independent review',
                                                    'requirements_review_failed': 'Requirements review',
                                                    'decision_review_failed': 'Planning choice review'}[review_failure['code']]
                                    planning_pause = review_stage + ' failed: ' + review_failure.get('message', review_failure['code'])
                                signature = json.dumps([function_name, function_args, failures], sort_keys=True)
                                discovery_blocked = any(isinstance(error, dict) and error.get('code') == 'discovery_complete' for error in failures)
                                if discovery_blocked:
                                    audit_index, _ = _latest_result(state['messages'], 'audit_workout_plan')
                                    signature = json.dumps([function_name, 'discovery_complete', audit_index])
                                    tools = [tool for tool in tools if tool.get('function', {}).get('name') != 'search_exercise_library']
                                    logger.log('Search unavailable until the draft is revised and audited; rephrasing cannot reopen discovery.')
                                if signature in failed_tool_signatures:
                                    planning_pause = ('Search is still blocked for the same draft; rewording queries made no progress.' if discovery_blocked
                                                      else 'The same tool request failed again without a change.')
                                failed_tool_signatures.add(signature)
                        if function_result.get("continue_planning"):
                            requires_plan_revision = True
                            tools = [SEARCH_EXERCISE_LIBRARY_TOOL, requirements_tool, RECORD_PLANNING_DECISIONS_TOOL, AUDIT_WORKOUT_PLAN_TOOL] if exercise_definitions else []
                            if training_history:
                                tools.append(GET_TRAINING_EVIDENCE_TOOL)

                        if function_result.get("requirements_preview"):
                            state['messages'].append(_message('assistant', content=function_result['requirements_preview'],
                                canonicalRequirementsPreview=function_result['requirements_id']))
                            print_markdown(function_result["requirements_preview"], logger)
                            persist_current()
                        if function_result.get('requirements_pending'):
                            tools = [requirements_tool, RECORD_PLANNING_DECISIONS_TOOL]
                            preview_ready = True
                        if function_name == "audit_workout_plan":
                            pending_preview = function_result if function_result.get("draft_preview") else None
                            feedback = json.loads(function_result['result'])
                            errors = feedback.get('errors', [])
                            lookup_needed = errors and all(error.get('code') == 'training_evidence_required' for error in errors)
                            if feedback.get('passed') is False and not lookup_needed:
                                signature = json.dumps({'draft': feedback.get('draftId', feedback.get('submittedDraft', function_args)), 'errors': errors}, sort_keys=True)
                                if signature in failed_draft_signatures:
                                    planning_pause = 'The same unchanged draft failed again.'
                                failed_draft_signatures.add(signature)
                                if requirements_approved(state['messages']) and SEARCH_EXERCISE_LIBRARY_TOOL not in tools:
                                    tools.append(SEARCH_EXERCISE_LIBRARY_TOOL)

                        generation_result = function_result.get("generation_result")
                        if generation_result is not None:
                            if generation_result.get("requires_plan_revision"):
                                requires_plan_revision = True
                                tools = [SEARCH_EXERCISE_LIBRARY_TOOL, requirements_tool, RECORD_PLANNING_DECISIONS_TOOL, AUDIT_WORKOUT_PLAN_TOOL] if exercise_definitions else []
                                if training_history:
                                    tools.append(GET_TRAINING_EVIDENCE_TOOL)
                            current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
                            generation_metadata = _metadata_for_generation_result(
                                generation_result,
                                state["log_path"],
                                current_record.get("metadata", {}).get("generated_output_paths"),
                            )
                    if pending_preview:
                        preview = pending_preview["draft_preview"]
                        state["messages"].append(_message("assistant", content=preview,
                            canonicalDraftPreview=pending_preview["draft_id"]))
                        print_markdown(preview, logger)
                        persist_current()
                        preview_ready = True
                if planning_pause or preview_ready or not has_tool_calls or (not requires_plan_revision and any(call.function.name == "generate_workout" for call in tool_calls)):
                    break
                tool_round += 1

            if planning_pause:
                logger.log_print(f"Planning paused: {planning_pause} Draft, lookups and audit feedback are saved. Type /continue to resume; you do not need to rewrite your requirements. Generation still requires a passing preview and fresh CONFIRM GENERATE.")

            persist_current(generation_metadata)

        except KeyboardInterrupt:
            logger.log_print("\nCancelled. Returning to prompt...")
            for message in state["messages"]:
                if message.get("role") == "tool" and str(message.get("content", "")).startswith("Tool call started"):
                    message["content"] = "Tool execution cancelled by the user. Do not treat this as a successful result."
            state["messages"] = normalize_conversation_messages(state["messages"])
            persist_current()
            continue
        except Exception as e:
            logger.log_print(f"Error: {e}")
            state["messages"] = normalize_conversation_messages(state["messages"])
            persist_current()
