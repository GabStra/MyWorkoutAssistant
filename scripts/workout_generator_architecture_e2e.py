#!/usr/bin/env python3
"""Isolated retained-case replay for the coordinated workout architecture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
BASELINE = REPO / "build/deepseek_e2e_20261019T170315"
COORDINATED = REPO / "build/deepseek_coordinated_review_20261019T172651"
BACKUP = REPO / "build/backup_conversion/workout_store_backup_2026-10-15_current_library.json"
CHECKER = COORDINATED / "verify_export.py"
REQUIREMENT_ACCOUNTING_KEY = "requirementAccounting"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def conversation_file(case: Path, conversation_id: str) -> Path:
    path = case / "workouts/conversation_sessions" / conversation_id / "messages.json"
    if not path.is_file():
        raise FileNotFoundError(f"Retained conversation is missing: {path}")
    return path


def case_conversation_id(case: Path) -> str:
    config = read_json(case / "test_config.json") if (case / "test_config.json").is_file() else {}
    if config.get("conversationId"):
        return config["conversationId"]
    metadata = read_json(case / "conversation_meta.json")
    identifier = metadata.get("active_conversation_id")
    if not identifier:
        raise ValueError(f"No retained conversation ID in {case}")
    return identifier


def tool_names(messages: list[dict]) -> dict[str, str]:
    return {call["id"]: call["function"]["name"]
            for message in messages for call in message.get("tool_calls", [])
            if call.get("id") and call.get("function", {}).get("name")}


def tool_results(messages: list[dict], name: str) -> list[dict]:
    names = tool_names(messages)
    results = []
    for message in messages:
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != name:
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            results.append(payload)
    return results


def latest_confirmed_requirements(messages: list[dict]) -> dict | None:
    """Return the newest passing requirements receipt with a later exact confirmation.

    Failed tool calls can follow a confirmed requirements preview during candidate
    repair. They do not revoke that approval; only a newer passing requirements
    receipt would supersede it.
    """
    names = tool_names(messages)
    passing = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != "set_workout_requirements":
            continue
        try:
            result = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if (isinstance(result, dict) and result.get("passed") is True
                and isinstance(result.get("requirements"), dict)
                and result.get("sourceReview", {}).get("passed") is True):
            passing.append((index, result))
    if not passing:
        return None
    result_index, result = passing[-1]
    if not any(message.get("role") == "user"
               and message.get("content", "").strip() == "CONFIRM REQUIREMENTS"
               for message in messages[result_index + 1:]):
        return None
    return result


def approved_requirements(messages: list[dict]) -> dict:
    records = [result for result in tool_results(messages, "set_workout_requirements")
               if result.get("passed") is True and isinstance(result.get("requirements"), dict)]
    if not records:
        raise ValueError("Retained baseline has no passing approved requirements payload")
    return records[-1]


def semantic_projection(requirements: dict) -> dict:
    value = copy.deepcopy(requirements)
    value.pop(REQUIREMENT_ACCOUNTING_KEY, None)
    return value


def process_snapshot(case: Path) -> dict:
    path = case / "process.json"
    if not path.exists():
        return {"processRecord": "missing"}
    state = read_json(path)
    live = []
    for key in ("controllerPID", "childPID"):
        pid = state.get(key)
        if not isinstance(pid, int):
            continue
        try:
            os.kill(pid, 0)
            live.append(pid)
        except (OSError, ProcessLookupError):
            pass
    return {"recordedStatus": state.get("status"), "recordedPIDs": {
        key: state.get(key) for key in ("controllerPID", "childPID")}, "livePIDs": live}


def ensure_case_stopped(case: Path) -> dict:
    state = process_snapshot(case)
    if state.get("recordedStatus") == "running" and state.get("livePIDs"):
        raise RuntimeError(f"Retained case still records a live process: {state}")
    return state


def endpoint_status() -> dict:
    sys.path.insert(0, str(REPO))
    from workout_generator_pkg.llm_config import require_api_key, resolve_llm_endpoint

    config = resolve_llm_endpoint()
    require_api_key(config)
    if not config.is_deepseek:
        raise RuntimeError("This retained E2E is pinned to the configured DeepSeek-compatible endpoint")
    return {"provider": "DeepSeek-compatible", "baseURL": config.base_url, "model": config.model}


def source_fingerprints() -> dict:
    paths = sorted((REPO / "workout_generator_pkg").glob("*.py"))
    return {str(path.relative_to(REPO)): sha256(path) for path in paths}


def make_run(case: Path, baseline_messages: list[dict], source_messages: list[dict]) -> tuple[Path, str]:
    now = datetime.now(timezone.utc)
    run = REPO / "build" / f"workout_generator_architecture_e2e_{now:%Y%m%dT%H%M%S}"
    conversation_id = case_conversation_id(case)
    target_conversation = run / "workouts/conversation_sessions" / conversation_id
    target_conversation.mkdir(parents=True)
    shutil.copy2(conversation_file(case, conversation_id), target_conversation / "messages.json")
    metadata = case / "workouts/conversation_sessions" / conversation_id / "meta.json"
    if metadata.is_file():
        shutil.copy2(metadata, target_conversation / "meta.json")
    shutil.copy2(case / "conversation_meta.json", run / "conversation_meta.json")
    for name in ("input_prompt.txt", "input_events.jsonl"):
        if (case / name).is_file():
            shutil.copy2(case / name, run / name)
    retained = run / "retained_stages"
    retained.mkdir()
    for name in ("owned_candidate_input.json", "retained_complete_candidate.json",
                 "joint_distribution_priority_replay.json", "original_findings_assessment.json",
                 "baseline_result.json", "source_hashes.json"):
        if (case / name).is_file():
            shutil.copy2(case / name, retained / name)
    original_req = approved_requirements(baseline_messages)
    source_req = approved_requirements(source_messages)
    if semantic_projection(original_req["requirements"]) != semantic_projection(source_req["requirements"]):
        raise RuntimeError("The coordinated retained conversation's approved requirements differ from the original baseline")

    (run / "run.py").write_text(
        "from dataclasses import replace\n"
        "from pathlib import Path\n"
        "import sys\n"
        "sys.path.insert(0, str(Path.cwd()))\n"
        "from workout_generator_pkg.deps import resolve_shell_deps\n"
        "from workout_generator_pkg.interactive_shell import main\n"
        "root = Path(__file__).resolve().parent\n"
        "main(replace(resolve_shell_deps(), default_script_dir=lambda: str(root)))\n",
        encoding="utf-8")
    write_json(run / "test_config.json", {"conversationId": conversation_id,
        "sourceCase": str(case), "baselineCase": str(BASELINE), "createdAtUTC": utc_now()})
    write_json(run / "requirement_baseline.json", {
        "originalRequirementsId": original_req.get("requirementsId"),
        "semanticRequirements": semantic_projection(original_req["requirements"]),
        "sourceCaseRequirementsId": source_req.get("requirementsId"),
        "semanticMatch": True})
    write_json(run / "source_fingerprints.json", source_fingerprints())
    return run, conversation_id


def prepare(args) -> tuple[Path, str, dict]:
    case = Path(args.case_root).resolve() if args.case_root else COORDINATED
    if not case.is_dir():
        raise FileNotFoundError(f"Coordinated retained case not found: {case}")
    baseline_messages = read_json(conversation_file(BASELINE, case_conversation_id(BASELINE)))
    source_messages = read_json(conversation_file(case, case_conversation_id(case)))
    state = {"sourceCase": str(case), "baselineCase": str(BASELINE),
             "sourceProcess": ensure_case_stopped(case),
             "baselineProcess": ensure_case_stopped(BASELINE), "endpoint": endpoint_status(),
             "conversationId": case_conversation_id(case),
             "originalApprovedRequirementsId": approved_requirements(baseline_messages).get("requirementsId"),
             "sourceApprovedRequirementsId": approved_requirements(source_messages).get("requirementsId")}
    run, conversation_id = make_run(case, baseline_messages, source_messages)
    state["runDirectory"] = str(run)
    write_json(run / "preflight.json", state)
    return run, conversation_id, state


def fresh_draft_preview(messages: list[dict], start_count: int):
    previews = [(index, message) for index, message in enumerate(messages[start_count:], start_count)
                if message.get("canonicalDraftPreview")]
    return previews[-1][1] if previews else None


def current_candidate_passes(messages: list[dict], requirements_id: str) -> tuple[bool, dict | None]:
    results = tool_results(messages, "audit_workout_plan")
    if not results:
        return False, None
    result = results[-1]
    review = result.get("review") or {}
    assessment = review.get("assessment") or result.get("findingsAssessment") or {}
    groups = assessment.get("groups", []) if isinstance(assessment, dict) else []
    actionable = [group for group in groups if group.get("disposition") == "repair"]
    passed = (result.get("passed") is True and result.get("requirementsId") == requirements_id
              and not result.get("errors") and not (result.get("audit") or {}).get("errors")
              and not result.get("reviewPending") and not result.get("coordinatedJointPending")
              and not review.get("failure") and not actionable)
    return passed, result


def terminal_failed_audit_count(messages: list[dict], requirements_id: str) -> int:
    """Count only completed, actionable audit failures, never review checkpoints/errors."""
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    names = tool_names(messages)
    count = 0
    for message in messages:
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != "audit_workout_plan":
            continue
        try:
            result = json.loads(message.get("content", ""))
        except (TypeError, ValueError):
            continue
        if not isinstance(result, dict) or result.get("passed") is not False:
            continue
        if result.get("requirementsId") != requirements_id:
            continue
        review = result.get("review") or {}
        assessment = review.get("assessment") or result.get("findingsAssessment")
        if (result.get("reviewPending") or result.get("coordinatedJointPending")
                or review.get("failure") or review.get("pending")
                or review.get("complete") is False or not isinstance(assessment, dict)):
            continue
        if (assessment.get("version") != ASSESSMENT_VERSION or assessment.get("pending")
                or assessment.get("complete") is False):
            continue
        groups = assessment.get("groups", [])
        if any(group.get("disposition") in ("pending", "unresolved", "placeholder") for group in groups):
            continue
        count += 1
    return count


def repair_cap_denied_since(messages: list[dict], start_index: int) -> bool:
    """Find the production admission guard's cap result in this attempt only."""
    names = tool_names(messages)
    for message in messages[start_index:]:
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != "audit_workout_plan":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and any(error.get("code") == "repair_round_cap_reached"
               for error in payload.get("errors", []) if isinstance(error, dict)):
            return True
    return False


def review_attempt_summary(messages: list[dict], requirements_id: str | None = None) -> list[dict]:
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    names = tool_names(messages)
    summaries = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != "audit_workout_plan":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if payload.get("passed") is not False:
            continue
        if requirements_id and payload.get("requirementsId") != requirements_id:
            continue
        review = payload.get("review") or {}
        assessment = review.get("assessment") or payload.get("findingsAssessment")
        error_codes = {item.get("code") for item in payload.get("errors", []) if isinstance(item, dict)}
        complete = (not payload.get("reviewPending") and not payload.get("coordinatedJointPending")
                    and not review.get("failure") and not review.get("pending")
                    and isinstance(assessment, dict) and assessment.get("version") == ASSESSMENT_VERSION
                    and not error_codes.intersection({"independent_review_pending", "review_execution_failed"}))
        errors = [{"code": item.get("code"), "path": item.get("path"),
                   "message": item.get("message", "")[:500]} for item in payload.get("errors", [])]
        findings = [{"severity": item.get("severity"), "basis": item.get("basis"),
                     "path": item.get("path"), "message": item.get("message", "")[:1000]}
                    for item in review.get("findings", [])]
        summaries.append({"messageIndex": index, "reviewComplete": complete,
                          "reviewFailure": review.get("failure"), "errors": errors,
                          "provisionalFindings": findings,
                          "assessment": assessment})
    return summaries[-3:]


def write_event(path: Path, event: str, **details) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"atUTC": utc_now(), "event": event, **details}, ensure_ascii=False) + "\n")


def collect_usage(run: Path, elapsed: float, repair_rounds: int = 0,
                  current_attempt_started_at_utc: str | None = None) -> dict:
    from workout_generator_pkg.usage_reporting import summarize_usage, usage_events

    rows = []
    for path in (run / "logs").glob("*.log"):
        rows.extend(usage_events(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    usage = summarize_usage(rows)
    pending_usage = usage
    if current_attempt_started_at_utc:
        cutoff = datetime.fromisoformat(current_attempt_started_at_utc.replace("Z", "+00:00"))
        current_attempt_rows = []
        for row in rows:
            started_at = row.get("requestStartedAtUTC")
            if not started_at:
                continue
            try:
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if started >= cutoff:
                current_attempt_rows.append(row)
        pending_usage = summarize_usage(current_attempt_rows)
    stage_intervals = {}
    stage_request_seconds = {}
    for row in rows:
        start, end, stage = row.get("requestStartedAtUTC"), row.get("requestFinishedAtUTC"), row.get("stage", "unscoped")
        if not start or not end:
            continue
        try:
            interval = (datetime.fromisoformat(start.replace("Z", "+00:00")),
                        datetime.fromisoformat(end.replace("Z", "+00:00")))
            seconds = max(0.0, (interval[1] - interval[0]).total_seconds())
            stage_request_seconds[stage] = stage_request_seconds.get(stage, 0.0) + seconds
            stage_intervals.setdefault(stage, []).append(interval)
        except (ValueError, TypeError):
            continue
    stage_seconds = {}
    for stage, intervals in stage_intervals.items():
        intervals.sort()
        start, end = intervals[0]
        elapsed = 0.0
        for next_start, next_end in intervals[1:]:
            if next_start > end:
                elapsed += (end - start).total_seconds()
                start, end = next_start, next_end
            elif next_end > end:
                end = next_end
        elapsed += (end - start).total_seconds()
        stage_seconds[stage] = round(elapsed, 2)
    stage_request_seconds = {stage: round(seconds, 2) for stage, seconds in stage_request_seconds.items()}
    return {"elapsedSeconds": round(elapsed, 2), "repairRounds": repair_rounds,
            "apiCalls": usage["requests"], "completedApiCalls": usage["completedRequests"],
            "reportedTokenTotals": usage["reportedTokenTotals"], "totalTokens": usage["totalTokens"],
            "tokenTotalsComplete": usage["tokenTotalsComplete"], "apiStages": usage["stages"],
            "apiStageRequestCounts": usage["stages"], "apiStageSeconds": stage_seconds,
            "apiStageRequestSeconds": stage_request_seconds,
            "pendingApiRequests": pending_usage.get("pendingRequests", 0),
            "pendingApiRequestDetails": pending_usage.get("pendingRequestDetails", []),
            "historicalUnterminatedApiRequests": usage.get("pendingRequests", 0)}


def pending_api_requests(run: Path, since_utc: str | None = None) -> int:
    from workout_generator_pkg.usage_reporting import summarize_usage, usage_events

    rows = []
    for path in (run / "logs").glob("*.log"):
        rows.extend(usage_events(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    if since_utc:
        cutoff = datetime.fromisoformat(since_utc.replace("Z", "+00:00"))
        current_attempt_rows = []
        for row in rows:
            started_at = row.get("requestStartedAtUTC")
            if not started_at:
                continue
            try:
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if started >= cutoff:
                current_attempt_rows.append(row)
        rows = current_attempt_rows
    return summarize_usage(rows).get("pendingRequests", 0)


def cli_waiting_for_input(stdout_path: Path) -> bool:
    """Return true only when the interactive CLI has reached its visible input prompt."""
    try:
        with stdout_path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 4096))
            tail = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    tail = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", tail)
    return tail.rstrip().endswith("You>")


def has_unanswered_user_choice(messages: list[dict], start_index: int) -> bool:
    """Detect a live ask_user interaction; a runner command is not a user answer."""
    calls = {call.get("id"): call.get("function", {}).get("name")
             for message in messages for call in message.get("tool_calls", []) if call.get("id")}
    for index, message in enumerate(messages[start_index:], start_index):
        call_id = message.get("tool_call_id")
        if message.get("role") != "tool" or calls.get(call_id) != "ask_user":
            continue
        try:
            result = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict) or not result.get("userQuestion"):
            continue
        answered = any(
            later.get("role") == "user"
            and later.get("content", "").strip() not in {"", "/continue", "/exit"}
            for later in messages[index + 1:]
        )
        if not answered:
            return True
    return False


def current_planning_state(messages: list[dict]) -> dict:
    """Read production planning state for safe resume and terminal-outcome decisions."""
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload, _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    from workout_generator_pkg.training_history import TrainingHistory

    equipment = _load_exercise_library_payload(str(BACKUP))
    history = TrainingHistory.from_file(str(BACKUP))
    request_messages = _messages_for_api(messages, True, history, equipment)
    return request_planning_state(request_messages)


def candidate_menu_expansion_is_active(messages: list[dict]) -> bool:
    return bool(current_planning_state(messages).get("candidateMenuExpansionTask"))


def refresh_approved_requirement_accounting(run: Path, conversation_id: str) -> tuple[bool, str | None]:
    """Run the narrow, real production accounting refresh before candidate repair."""
    from openai import OpenAI
    from workout_generator_pkg.api_client import chat_call
    from workout_generator_pkg.api_metrics import api_metrics_scope, start_planning_budget
    from workout_generator_pkg.conversation_store import save_conversation
    from workout_generator_pkg.interactive_shell import (
        _load_exercise_library_payload, handle_function_call,
    )
    from workout_generator_pkg.llm_config import require_api_key, resolve_llm_endpoint
    from workout_generator_pkg.logging_ui import ConversationLogger
    from workout_generator_pkg.planning_tools import (
        approved_requirement_base, requirement_sources, source_message_context,
        workout_requirements_tool,
    )

    baseline_messages = read_json(conversation_file(BASELINE, conversation_id))
    base = approved_requirement_base(baseline_messages)
    if not base:
        raise RuntimeError("Original baseline has no current approved requirements to refresh")
    source_messages = requirement_sources(baseline_messages)
    source_context = source_message_context(source_messages)
    endpoint = resolve_llm_endpoint()
    client = OpenAI(api_key=require_api_key(endpoint), base_url=endpoint.base_url)
    equipment = _load_exercise_library_payload(str(BACKUP))
    tool = workout_requirements_tool(equipment, baseline_messages)
    instruction = (
        "Refresh the instruction accounting for this already-approved workout. Return exactly one "
        "set_workout_requirements call using the supplied narrow refresh schema. Do not emit any other "
        "tool. Cite every instruction to the supplied SOURCE_n entry and map only to the frozen "
        "requirement JSON pointers. Include qualitative instructions as semantic checks. Mark a target "
        "negotiable only when the source explicitly allows trade-offs; otherwise use mandatory. Add "
        "objectiveOrder only when the user explicitly ranked objectives. Do not invent priorities, "
        "relaxations, constraints, or exercise minimums."
    )
    model_messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps({
            "baseRequirementsId": base["requirementsId"],
            "approvedRequirements": base["requirements"],
            "originalSources": source_context,
        }, ensure_ascii=False)},
    ]
    logger = ConversationLogger(str(run))
    refresh_state = {"status": "running", "pid": os.getpid(), "startedAtUTC": utc_now(),
                     "conversationId": conversation_id, "stage": "real requirement-accounting extraction and independent review"}
    write_json(run / "requirement_refresh_process.json", refresh_state)
    print(f"Starting DeepSeek requirement refresh; pid={os.getpid()} log={logger.log_filepath}", flush=True)
    start_planning_budget(max_calls=8, max_seconds=300)
    try:
        with api_metrics_scope(logger, "Requirement accounting"):
            content, tool_calls, _reasoning = chat_call(client, model_messages, tools=[tool],
                reasoning_effort="low", max_tokens=16384, timeout=180)
    except Exception as error:
        refresh_state.update(status="failed", endedAtUTC=utc_now(), errorType=type(error).__name__)
        write_json(run / "requirement_refresh_process.json", refresh_state)
        write_json(run / "requirement_refresh_failure.json", {"errorType": type(error).__name__, "message": str(error)})
        return False, None
    if len(tool_calls or []) != 1 or tool_calls[0].function.name != "set_workout_requirements":
        write_json(run / "requirement_refresh_failure.json", {
            "reason": "Model did not return exactly the required extraction tool call",
            "content": content, "toolCallCount": len(tool_calls or []),
        })
        return False, None
    arguments = json.loads(tool_calls[0].function.arguments)

    # The production handler merges the ledger into the frozen approved fields and runs
    # the usual independent source review. The narrow refresh tool cannot edit targets.
    handler_messages = copy.deepcopy(baseline_messages)
    try:
        with api_metrics_scope(logger, "Requirements independent review"):
            outcome = handle_function_call(client, handler_messages, "set_workout_requirements", arguments,
                equipment, logger, str(run), progress=lambda message: write_event(run / "events.jsonl",
                    "requirement_refresh_progress", message=message))
    except Exception as error:
        refresh_state.update(status="failed", endedAtUTC=utc_now(), errorType=type(error).__name__)
        write_json(run / "requirement_refresh_process.json", refresh_state)
        write_json(run / "requirement_refresh_failure.json", {"errorType": type(error).__name__, "message": str(error), "arguments": arguments})
        return False, None
    result = json.loads(outcome["result"])
    request_id = "architecture_requirement_refresh_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    latest_messages = read_json(conversation_file(run, conversation_id))
    latest_messages.extend([
        {"role": "assistant", "content": content, "tool_calls": [{"id": request_id,
         "type": "function", "function": {"name": "set_workout_requirements",
         "arguments": json.dumps(arguments, ensure_ascii=False)}}],
         "harnessStep": "Real model accounting refresh against original approved source; production handler and review."},
        {"role": "tool", "tool_call_id": request_id, "content": json.dumps(result, ensure_ascii=False)},
    ])
    preview = outcome.get("requirements_preview")
    if preview:
        latest_messages.append({"role": "assistant", "content": preview,
                                "canonicalRequirementsPreview": outcome.get("requirements_id")})
    equivalent = (result.get("passed") is True and result.get("sourceReview", {}).get("passed") is True
                  and semantic_projection(result.get("requirements", {}))
                  == semantic_projection(base["requirements"]))
    refresh_record = {"passed": result.get("passed"),
        "sourceReviewPassed": result.get("sourceReview", {}).get("passed"),
        "originalRequirementsId": base["requirementsId"],
        "refreshedRequirementsId": result.get("requirementsId"),
        "equivalentToOriginal": equivalent,
        "accountingCount": len(result.get("requirements", {}).get("requirementAccounting", [])),
        "objectiveOrder": result.get("requirements", {}).get("objectiveOrder"),
        "reviewErrors": result.get("errors", [])}
    write_json(run / "requirement_refresh.json", refresh_record)
    refresh_state.update(status="completed", endedAtUTC=utc_now(), requirementsId=result.get("requirementsId"),
                         passed=result.get("passed"), unchanged=equivalent)
    write_json(run / "requirement_refresh_process.json", refresh_state)
    if result.get("passed") is True and outcome.get("requirements_pending") is True and equivalent and preview:
        latest_messages.append({"role": "user", "content": "CONFIRM REQUIREMENTS",
                                "harnessStep": "User-authorized E2E confirmation because the source-reviewed refresh preserved every approved semantic field."})
        save_conversation(latest_messages, conversation_id=conversation_id,
                          script_dir=str(run), migrate=False)
        write_event(run / "events.jsonl", "requirements_confirmed_unchanged",
                    requirementsId=result.get("requirementsId"))
        return True, result.get("requirementsId")
    save_conversation(latest_messages, conversation_id=conversation_id,
                      script_dir=str(run), migrate=False)
    return False, result.get("requirementsId")


def repair_requirement_accounting(run: Path, conversation_id: str) -> tuple[bool, str | None]:
    """Repair only ledger metadata from the failed independent source review."""
    from openai import OpenAI
    from workout_generator_pkg.api_client import chat_call
    from workout_generator_pkg.api_metrics import api_metrics_scope, start_planning_budget
    from workout_generator_pkg.conversation_store import save_conversation
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload, handle_function_call
    from workout_generator_pkg.llm_config import require_api_key, resolve_llm_endpoint
    from workout_generator_pkg.logging_ui import ConversationLogger
    from workout_generator_pkg.planning_tools import (
        approved_requirement_base, requirement_sources, source_message_context, workout_requirements_tool,
    )

    baseline_messages = read_json(conversation_file(BASELINE, conversation_id))
    base = approved_requirement_base(baseline_messages)
    if not base:
        raise RuntimeError("Original baseline has no current approved requirements")
    current_messages = read_json(conversation_file(run, conversation_id))
    attempted = tool_results(current_messages, "set_workout_requirements")
    if not attempted:
        raise RuntimeError("No saved failed accounting ledger exists to repair")
    prior = attempted[-1]
    ledger = prior.get("requirements", {}).get(REQUIREMENT_ACCOUNTING_KEY)
    if not isinstance(ledger, list) or len(ledger) != 35:
        raise RuntimeError(f"Expected the retained 35-entry ledger, found {len(ledger) if isinstance(ledger, list) else 'no ledger'}")
    review_findings = (read_json(run / "requirement_refresh.json").get("reviewErrors", []))
    sources = source_message_context(requirement_sources(baseline_messages))
    endpoint = resolve_llm_endpoint()
    client = OpenAI(api_key=require_api_key(endpoint), base_url=endpoint.base_url)
    equipment = _load_exercise_library_payload(str(BACKUP))
    tool = workout_requirements_tool(equipment, baseline_messages)
    instruction = (
        "Repair the requirement-accounting metadata using the independent source-review findings. "
        "Return exactly one set_workout_requirements call with the supplied narrow refresh schema. "
        "Preserve every valid existing ledger entry verbatim; edit only entries needed to correct a "
        "finding or source-backed priority classification, and add any missing explicit instruction. "
        "Do not return objectiveOrder: the source word 'preservation' refers to preserving the user's "
        "approved requirements, not preserving the current candidate. Source explicitly permits a "
        "feasible compromise when the 90-minute cap and volume targets conflict: classify those volume "
        "targets as negotiable-for-proposal in the ledger, while keeping the currently approved numeric "
        "targets unchanged until explicit approval. Do not invent any priority or relax any constraint."
    )
    model_messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps({
            "baseRequirementsId": base["requirementsId"],
            "approvedRequirements": base["requirements"],
            "existingRequirementAccounting": ledger,
            "independentReviewFindings": review_findings,
            "originalSources": sources,
        }, ensure_ascii=False)},
    ]
    logger = ConversationLogger(str(run))
    refresh_state = {"status": "running", "pid": os.getpid(), "startedAtUTC": utc_now(),
                     "conversationId": conversation_id, "stage": "narrow metadata repair and independent source review"}
    write_json(run / "requirement_accounting_repair_process.json", refresh_state)
    print(f"Starting narrow DeepSeek ledger repair; pid={os.getpid()} log={logger.log_filepath}", flush=True)
    start_planning_budget(max_calls=6, max_seconds=300)
    try:
        with api_metrics_scope(logger, "Requirement accounting repair"):
            content, tool_calls, _reasoning = chat_call(client, model_messages, tools=[tool],
                reasoning_effort="low", max_tokens=16384, timeout=180)
        if len(tool_calls or []) != 1 or tool_calls[0].function.name != "set_workout_requirements":
            raise ValueError("Model did not return exactly one accounting-repair tool call")
        arguments = json.loads(tool_calls[0].function.arguments)
        handler_messages = copy.deepcopy(baseline_messages)
        with api_metrics_scope(logger, "Repaired requirements independent review"):
            outcome = handle_function_call(client, handler_messages, "set_workout_requirements", arguments,
                equipment, logger, str(run), progress=lambda message: write_event(run / "events.jsonl",
                    "requirement_accounting_repair_progress", message=message))
    except Exception as error:
        refresh_state.update(status="failed", endedAtUTC=utc_now(), errorType=type(error).__name__)
        write_json(run / "requirement_accounting_repair_process.json", refresh_state)
        write_json(run / "requirement_accounting_repair_failure.json", {"errorType": type(error).__name__, "message": str(error)})
        return False, None

    result = json.loads(outcome["result"])
    request_id = "architecture_requirement_accounting_repair_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    current_messages.extend([
        {"role": "assistant", "content": content, "tool_calls": [{"id": request_id,
         "type": "function", "function": {"name": "set_workout_requirements",
         "arguments": json.dumps(arguments, ensure_ascii=False)}}],
         "harnessStep": "Narrow real-model repair of source-review findings; preserved the existing accounting ledger."},
        {"role": "tool", "tool_call_id": request_id, "content": json.dumps(result, ensure_ascii=False)},
    ])
    preview = outcome.get("requirements_preview")
    if preview:
        current_messages.append({"role": "assistant", "content": preview,
                                 "canonicalRequirementsPreview": outcome.get("requirements_id")})
    equivalent = (result.get("passed") is True and result.get("sourceReview", {}).get("passed") is True
                  and semantic_projection(result.get("requirements", {})) == semantic_projection(base["requirements"]))
    record = {"passed": result.get("passed"), "sourceReviewPassed": result.get("sourceReview", {}).get("passed"),
              "originalRequirementsId": base["requirementsId"], "refreshedRequirementsId": result.get("requirementsId"),
              "equivalentToOriginal": equivalent,
              "accountingCount": len(result.get("requirements", {}).get(REQUIREMENT_ACCOUNTING_KEY, [])),
              "objectiveOrder": result.get("requirements", {}).get("objectiveOrder"), "reviewErrors": result.get("errors", [])}
    write_json(run / "requirement_accounting_repair.json", record)
    refresh_state.update(status="completed", endedAtUTC=utc_now(), requirementsId=result.get("requirementsId"),
                         passed=result.get("passed"), unchanged=equivalent)
    write_json(run / "requirement_accounting_repair_process.json", refresh_state)
    if result.get("passed") is True and outcome.get("requirements_pending") is True and equivalent and preview:
        current_messages.append({"role": "user", "content": "CONFIRM REQUIREMENTS",
                                 "harnessStep": "User-authorized E2E confirmation after source review and unchanged-constraints check."})
        save_conversation(current_messages, conversation_id=conversation_id, script_dir=str(run), migrate=False)
        write_event(run / "events.jsonl", "requirements_confirmed_after_ledger_repair", requirementsId=result.get("requirementsId"))
        return True, result.get("requirementsId")
    save_conversation(current_messages, conversation_id=conversation_id, script_dir=str(run), migrate=False)
    return False, result.get("requirementsId")


def stop_child(process: subprocess.Popen, command: str = "/exit\n") -> None:
    if process.poll() is not None:
        return
    try:
        process.stdin.write(command.encode("utf-8"))
        process.stdin.flush()
        process.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_case(args, run: Path, conversation_id: str, state: dict) -> int:
    from workout_generator_pkg.interactive_shell import _completed_changed_repair_rounds

    messages_path = conversation_file(run, conversation_id)
    messages = read_json(messages_path)
    starting_count = len(messages)
    requirements_id = state.get("refreshedRequirementsId")
    process_path = run / "process.json"
    event_path = run / "events.jsonl"
    out_path, err_path = run / "stdout.log", run / "stderr.log"
    command = [sys.executable, "-X", "faulthandler", "-u", str(run / "run.py"),
               "--history-backup-file", str(BACKUP), "--hybrid-fast",
               "--max-repair-rounds", str(args.max_repair_rounds),
               "--repair-attempt-start-index", str(starting_count)]
    started = time.monotonic()
    attempt_started_at_utc = utc_now()
    write_event(event_path, "run_started", argv=command, initialMessageCount=starting_count,
                startedAtUTC=attempt_started_at_utc, maxRepairRounds=args.max_repair_rounds,
                repairAttemptStartIndex=starting_count)
    status = {"status": "running", "startedAtUTC": utc_now(), "sourceCase": str(state["sourceCase"]),
              "childPID": None, "conversationId": conversation_id}
    with out_path.open("wb") as stdout, err_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=REPO, stdin=subprocess.PIPE,
                                   stdout=stdout, stderr=stderr, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        status["childPID"] = process.pid
        write_json(process_path, status)
        requirements_confirmed = True
        draft_confirmed = False
        requirements_id = state.get("refreshedRequirementsId")
        repair_rounds = _completed_changed_repair_rounds(messages, starting_count)
        last_failed_audit_count = terminal_failed_audit_count(messages, requirements_id)
        last_message_count = starting_count
        stable_since = time.monotonic()
        stop_after_review = False
        deadline = started + args.timeout_seconds
        process.stdin.write(f"/resume-conversation {conversation_id}\n/continue\n".encode("utf-8"))
        process.stdin.flush()
        write_event(event_path, "resume_requested", conversationId=conversation_id)
        outcome = "unresolved"
        reason = "Timed out before producing a verified export"

        while process.poll() is None and time.monotonic() < deadline:
            try:
                messages = read_json(messages_path)
            except (OSError, ValueError):
                time.sleep(0.5)
                continue
            if len(messages) != last_message_count:
                last_message_count = len(messages)
                stable_since = time.monotonic()

            if cli_waiting_for_input(out_path) and time.monotonic() - stable_since > 3:
                planning_state = current_planning_state(messages)
                expansion_failure = planning_state.get("menuExpansionUnresolved")
                if isinstance(expansion_failure, dict):
                    outcome, reason = "unresolved", expansion_failure.get(
                        "reason", "The bounded candidate-menu expansion did not establish a validated candidate")
                    write_event(event_path, "candidate_menu_expansion_unresolved",
                                sourceProblemFingerprint=expansion_failure.get("sourceProblemFingerprint"),
                                blockers=expansion_failure.get("blockers", []))
                    break
                if (has_unanswered_user_choice(messages, starting_count)
                        and not planning_state.get("candidateMenuExpansionTask")):
                    outcome, reason = "unresolved", "A user choice is required before changing a negotiable requirement; no choice was inferred"
                    write_event(event_path, "stopped_for_unanswered_user_choice", repairRound=repair_rounds)
                    break

            completed_repair_rounds = _completed_changed_repair_rounds(messages, starting_count)
            if completed_repair_rounds > repair_rounds:
                for round_number in range(repair_rounds + 1, completed_repair_rounds + 1):
                    write_event(event_path, "candidate_changing_repair_admitted",
                                repairRound=round_number, maxRepairRounds=args.max_repair_rounds,
                                repairAttemptStartIndex=starting_count)
                repair_rounds = completed_repair_rounds

            if requirements_confirmed and not draft_confirmed:
                preview = fresh_draft_preview(messages, starting_count)
                if preview:
                    passed, result = current_candidate_passes(messages, requirements_id)
                    if passed and cli_waiting_for_input(out_path):
                        process.stdin.write(b"CONFIRM GENERATE\n")
                        process.stdin.flush()
                        draft_confirmed = True
                        write_event(event_path, "passing_preview_confirmed", draftId=result.get("draftId"))
                    elif not passed and cli_waiting_for_input(out_path) and time.monotonic() - stable_since > 5:
                        outcome, reason = "unresolved", "A preview appeared without a passing current full review; export approval was withheld"
                        break

            if requirements_confirmed and not draft_confirmed:
                failed_count = terminal_failed_audit_count(messages, requirements_id)
                if (failed_count > last_failed_audit_count and cli_waiting_for_input(out_path)
                        and time.monotonic() - stable_since > 3):
                    last_failed_audit_count = failed_count
                    if repair_rounds >= args.max_repair_rounds:
                        outcome, reason = "unresolved", f"Repair limit reached ({repair_rounds}); saved candidate and feedback were preserved"
                        stop_after_review = True
                        write_event(event_path, "repair_limit_reached_waiting_for_review_completion",
                                    repairRound=repair_rounds,
                                    pendingApiRequests=pending_api_requests(run, attempt_started_at_utc))
                    else:
                        process.stdin.write(b"/continue\n")
                        process.stdin.flush()
                        write_event(event_path, "repair_resumed", repairRound=repair_rounds)
                        stable_since = time.monotonic()

                cap_denied = repair_cap_denied_since(messages, starting_count)
                if (cap_denied and cli_waiting_for_input(out_path)
                        and time.monotonic() - stable_since > 3):
                    outcome, reason = "unresolved", f"Repair limit reached ({repair_rounds}); saved candidate and feedback were preserved"
                    stop_after_review = True
                    write_event(event_path, "repair_limit_reached_waiting_for_review_completion",
                                repairRound=repair_rounds,
                                pendingApiRequests=pending_api_requests(run, attempt_started_at_utc))

            if (stop_after_review and cli_waiting_for_input(out_path)
                    and time.monotonic() - stable_since > 5):
                pending = pending_api_requests(run, attempt_started_at_utc)
                if pending == 0:
                    write_event(event_path, "review_completion_drained", repairRound=repair_rounds)
                    break

            generated = [entry for entry in (run / "workouts").glob("workout_plan_*.json") if entry.is_file()]
            if draft_confirmed and generated:
                outcome, reason = "generated", "Confirmed export produced; exact checker pending"
                break
            time.sleep(0.5)

        if outcome == "unresolved" and time.monotonic() >= deadline:
            reason = "Run exceeded the configured wall-clock limit; no infeasibility claim is made"
        stop_child(process)
        status.update(status="exited", exitCode=process.returncode, endedAtUTC=utc_now())
        write_json(process_path, status)

    cli_elapsed = time.monotonic() - started
    run_created = datetime.fromisoformat(state.get("createdAtUTC", utc_now()).replace("Z", "+00:00"))
    elapsed = (datetime.now(timezone.utc) - run_created).total_seconds()
    messages = read_json(messages_path)
    exports = sorted((run / "workouts").glob("workout_plan_*.json"), key=lambda p: p.stat().st_mtime)
    verification = None
    if outcome == "generated" and exports:
        export = exports[-1]
        checker = make_dynamic_checker(run)
        verified = subprocess.run([sys.executable, str(checker), conversation_id, str(export), str(messages_path)],
                                  cwd=REPO, capture_output=True, text=True, timeout=300)
        (run / "export_verification.log").write_text(verified.stdout + verified.stderr, encoding="utf-8")
        if verified.returncode == 0:
            outcome, reason = "completed_verified", "Export passed the exact current review, schema and numerical checker"
            verification_path = run / "final_verification.json"
            verification = read_json(verification_path) if verification_path.exists() else {"checkerExitCode": 0}
        else:
            outcome, reason = "generated_unverified", "The export exists but failed the exact checker"

    metrics = collect_usage(run, elapsed, repair_rounds)
    metrics["cliElapsedSeconds"] = round(cli_elapsed, 2)
    review_attempts = review_attempt_summary(messages, requirements_id)
    result = {"outcome": outcome, "reason": reason, "conversationId": conversation_id,
              "runDirectory": str(run), "requirementsConfirmedUnchanged": requirements_confirmed,
              "draftConfirmed": draft_confirmed, "originalRequirementsId": state["originalApprovedRequirementsId"],
              "refreshedRequirementsId": requirements_id, "metrics": metrics,
              "reviewComplete": bool(review_attempts) and review_attempts[-1]["reviewComplete"],
              "reviewAttempts": review_attempts, "verification": verification,
              "priorResumeAttemptArtifact": str(REPO / "build/workout_generator_architecture_e2e_20261019T172459/e2e_result.json"),
              "createdAtUTC": state["createdAtUTC"], "completedAtUTC": utc_now()}
    write_json(run / "e2e_result.json", result)
    write_event(event_path, "run_finished", outcome=outcome, elapsedSeconds=round(elapsed, 2),
                repairRounds=repair_rounds, apiCalls=metrics["apiCalls"], totalTokens=metrics["totalTokens"])
    return 0 if outcome == "completed_verified" else 1


def make_dynamic_checker(run: Path) -> Path:
    source = CHECKER.read_text(encoding="utf-8")
    source = source.replace("conversation, export = sys.argv[1:]", "conversation, export, messages_file = sys.argv[1:]")
    old = "messages = read(next(Path('build/deepseek_e2e_20261019T170315/workouts/conversation_sessions').glob(conversation + '*/messages.json')))"
    if old not in source:
        raise RuntimeError("Retained exact checker changed shape; update the runner's path adaptation before relying on it")
    source = source.replace(old, "messages = read(Path(messages_file))")
    old_block = "assert not any(finding['severity'] == 'blocking' for finding in approved['review']['findings'])"
    new_block = (
        "assessment = approved['review'].get('assessment') or approved.get('findingsAssessment') or {}\n"
        "assert not any(group.get('disposition') == 'repair' for group in assessment.get('groups', [])), assessment"
    )
    if old_block in source:
        source = source.replace(old_block, new_block)
    source = source.replace("(Path(__file__).resolve().parent / 'final_verification.json')",
                            "(Path(__file__).resolve().parent / 'final_verification.json')")
    path = run / "verify_export.py"
    path.write_text(source, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-root", help="Retained coordinated-case directory (defaults to the October 19 case)")
    parser.add_argument("--run", action="store_true", help="Start the real DeepSeek replay; default only prepares and preflights")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare an isolated case without calling the model")
    parser.add_argument("--repair-accounting", help="Repair the failed source-reviewed ledger in an existing isolated run")
    parser.add_argument("--continue-after-accounting", help="Continue candidate replay after a saved passing accounting approval")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Whole-run wall-clock limit")
    parser.add_argument("--max-repair-rounds", type=int, default=3,
                        help="Maximum candidate-changing repair submissions in this replay (default: 3)")
    args = parser.parse_args()
    if args.timeout_seconds < 60 or args.max_repair_rounds < 0:
        parser.error("timeout must be at least 60 seconds and repair rounds cannot be negative")
    if args.continue_after_accounting:
        run = Path(args.continue_after_accounting).resolve()
        preflight = read_json(run / "preflight.json")
        conversation_id = case_conversation_id(run)
        messages = read_json(conversation_file(run, conversation_id))
        latest = latest_confirmed_requirements(messages)
        if latest is None:
            raise RuntimeError("Saved conversation lacks a passing, user-confirmed requirements refresh")
        state = {**preflight, "createdAtUTC": read_json(run / "test_config.json").get("createdAtUTC", utc_now()),
                 "requirementsConfirmedUnchanged": True,
                 "refreshedRequirementsId": latest.get("requirementsId")}
        return run_case(args, run, conversation_id, state)
    if args.repair_accounting:
        run = Path(args.repair_accounting).resolve()
        preflight = read_json(run / "preflight.json")
        conversation_id = case_conversation_id(run)
        started = time.monotonic()
        repaired, requirements_id = repair_requirement_accounting(run, conversation_id)
        elapsed = time.monotonic() - started
        if not repaired:
            repair_record = read_json(run / "requirement_accounting_repair.json") if (run / "requirement_accounting_repair.json").exists() else {}
            result = {"outcome": "review_required" if repair_record.get("reviewErrors") else "unresolved",
                "reason": "The repaired requirement ledger did not pass independent review with unchanged approved semantics; candidate repair was not started.",
                "runDirectory": str(run), "requirementsConfirmedUnchanged": False,
                "originalRequirementsId": preflight["originalApprovedRequirementsId"],
                "refreshedRequirementsId": requirements_id, "missedRequirements": repair_record.get("reviewErrors", []),
                "repairRounds": 0, "metrics": collect_usage(run, elapsed),
                "priorResumeAttemptArtifact": str(REPO / "build/workout_generator_architecture_e2e_20261019T172459/e2e_result.json"),
                "completedAtUTC": utc_now()}
            write_json(run / "e2e_result.json", result)
            print(json.dumps(result, indent=2))
            return 1
        state = {**preflight, "createdAtUTC": read_json(run / "test_config.json").get("createdAtUTC", utc_now()),
                 "requirementsConfirmedUnchanged": True, "refreshedRequirementsId": requirements_id}
        return run_case(args, run, conversation_id, state)
    run, conversation_id, state = prepare(args)
    state["createdAtUTC"] = utc_now()
    print(json.dumps({"preflight": state, "runDirectory": str(run),
                      "modelWillRun": bool(args.run and not args.prepare_only)}, indent=2))
    if args.run and not args.prepare_only:
        refresh_started = time.monotonic()
        refreshed, refreshed_id = refresh_approved_requirement_accounting(run, conversation_id)
        refresh_elapsed = time.monotonic() - refresh_started
        state["requirementsConfirmedUnchanged"] = refreshed
        state["refreshedRequirementsId"] = refreshed_id
        if not refreshed:
            refresh_record = read_json(run / "requirement_refresh.json") if (run / "requirement_refresh.json").exists() else {}
            findings = refresh_record.get("reviewErrors", [])
            write_json(run / "e2e_result.json", {"outcome": "review_required" if findings else "unresolved",
                "reason": "Requirement accounting did not pass independent review with unchanged approved semantics; candidate repair was not started.",
                "runDirectory": str(run), "requirementsConfirmedUnchanged": False,
                "originalRequirementsId": state["originalApprovedRequirementsId"],
                "refreshedRequirementsId": refreshed_id, "missedRequirements": findings,
                "repairRounds": 0, "metrics": collect_usage(run, refresh_elapsed),
                "priorResumeAttemptArtifact": str(REPO / "build/workout_generator_architecture_e2e_20261019T172459/e2e_result.json"),
                "completedAtUTC": utc_now()})
            return 1
        return run_case(args, run, conversation_id, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
