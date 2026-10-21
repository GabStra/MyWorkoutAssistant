#!/usr/bin/env python3
"""Isolated, explicitly synthetic E2E cases for the workout architecture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

import workout_generator_architecture_e2e as retained

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "build/synthetic_workout_generator_architecture_cases.json"


def _workout_audit_within_reviewed_envelope(actual: list[dict], reviewed: list[dict]) -> bool:
    """Accept realized timing below the conservative rep-range estimate, never above it."""
    if len(actual) != len(reviewed):
        return False

    def without_ids_and_timing(value):
        if isinstance(value, dict):
            return {key: without_ids_and_timing(item) for key, item in value.items()
                    if key not in ("exerciseId", "timing", "estimatedSeconds")}
        if isinstance(value, list):
            return [without_ids_and_timing(item) for item in value]
        return value

    for realized, estimate in zip(actual, reviewed, strict=True):
        realized_timing, estimated_timing = realized.get("timing", {}), estimate.get("timing", {})
        if set(realized_timing) != set(estimated_timing):
            return False
        if any(realized_timing[key] > estimated_timing[key] for key in realized_timing):
            return False
        if realized.get("estimatedSeconds", 0) > estimate.get("estimatedSeconds", 0):
            return False
        if without_ids_and_timing(realized) != without_ids_and_timing(estimate):
            return False
    return True


def process_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def ensure_saved_process_stopped(process_state: dict, run: Path) -> None:
    if process_state.get("status") == "running" and process_is_alive(process_state.get("childPID")):
        raise RuntimeError(
            f"Cannot resume {run}: saved CLI process {process_state.get('childPID')} is still running. "
            "Wait for it to stop or recover that same process before starting another CLI."
        )


def cached_review_failure_without_route(audit: dict | None, planner_state: dict,
                                        current_audit_version: int,
                                        current_review_version: int) -> str | None:
    """Explain why a current-version cached review failure cannot be resumed productively."""
    if not isinstance(audit, dict):
        return None
    review = audit.get("review") or {}
    errors = [item for item in audit.get("errors", []) if isinstance(item, dict)]
    failure = next((item for item in errors if item.get("code") == "review_execution_failed"), None)
    if (not failure or audit.get("auditVersion") != current_audit_version
            or review.get("version") != current_review_version
            or review.get("pending") or review.get("inProgress")):
        return None
    if any(planner_state.get(key) for key in ("repairTask", "conflictDiagnosisTask", "candidateMenuExpansionTask")):
        return None
    detail = str(failure.get("message") or "")
    return ("The latest independent review failed validation and is cached under the current review versions; "
            "the planner has no actionable repair task. Fix the review/code inputs or advance the review contract "
            "before resuming." + (f" Detail: {detail[:350]}" if detail else ""))


def current_planner_state(messages: list[dict], backup: Path) -> dict:
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload, _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    from workout_generator_pkg.training_history import TrainingHistory

    equipment = _load_exercise_library_payload(str(backup))
    history = TrainingHistory.from_file(str(backup))
    return request_planning_state(_messages_for_api(messages, True, history, equipment))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_case(case: dict, backup: Path, backup_hash: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    run = REPO / "build" / f"synthetic_workout_architecture_{case['id']}_{stamp}"
    conversation_id = str(uuid.uuid4())
    source_messages = retained.read_json(
        retained.conversation_file(retained.BASELINE, retained.case_conversation_id(retained.BASELINE)))
    system = [copy.deepcopy(message) for message in source_messages if message.get("role") == "system"][:3]
    if len(system) != 3:
        raise ValueError("The immutable backup's retained system context is incomplete")
    exercise_count = len(retained.read_json(backup)["WorkoutStore"]["exerciseDefinitions"])
    if f"{exercise_count} definitions" not in system[-1].get("content", ""):
        raise ValueError("Retained system context does not match the immutable exercise-library backup")
    now = datetime.now(timezone.utc).isoformat()
    synthetic_request = "\n\n".join(case["sourceMessages"])
    messages = system + [{"role": "user", "timestamp": now, "content": synthetic_request,
                          "imageAttachments": [], "syntheticFixtureId": case["id"]}]
    session = run / "workouts" / "conversation_sessions" / conversation_id
    session.mkdir(parents=True)
    retained.write_json(session / "messages.json", messages)
    retained.write_json(session / "meta.json", {"conversation_id": conversation_id, "created_at": now,
        "updated_at": now, "last_generation_result": None, "generated_output_paths": [],
        "log_filename": f"conversation_{conversation_id[:8]}.log"})
    retained.write_json(run / "conversation_meta.json", {"active_conversation_id": conversation_id})
    retained.write_json(run / "test_config.json", {"fixtureSetId": "synthetic_workout_architecture_varied_cases_v1",
        "fixtureId": case["id"], "syntheticOnly": True, "realUserApprovalClaimed": False,
        "conversationId": conversation_id, "immutableBackup": str(backup),
        "immutableBackupSHA256": backup_hash, "createdAtUTC": now,
        "testOnlyApprovals": "Exact production confirmation phrases may be injected only after their reviewed canonical previews."})
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
    (run / "input_prompt.txt").write_text(synthetic_request, encoding="utf-8")
    retained.write_json(run / "preflight.json", {"modelWillRun": False, "fixtureId": case["id"],
        "classification": "SYNTHETIC ONLY; NOT A REAL-USER APPROVAL OR RETAINED BENCHMARK",
        "backupSHA256Before": backup_hash, "messagesSeeded": len(messages), "createdAtUTC": now})
    return run


def _tool_result_after(messages: list[dict], tool_name: str, start: int) -> dict | None:
    names = retained.tool_names(messages)
    latest = None
    for message in messages[start:]:
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != tool_name:
            continue
        try:
            value = json.loads(message.get("content", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            latest = value
    return latest


def _preview_for(messages: list[dict], marker: str, identifier: str, expected: str | None = None) -> bool:
    return any(message.get("role") == "assistant" and message.get(marker) == identifier
               and isinstance(message.get("content"), str)
               and (expected is None or message["content"] == expected)
               for message in messages)


def _volume_reduction(proposal: dict) -> float:
    reduction = 0.0
    for change in proposal.get("changes", []):
        path = change.get("path", "")
        if "/auditTargets/weeklyEffectiveSets/" in path and path.endswith("/minimum"):
            if isinstance(change.get("from"), (int, float)) and isinstance(change.get("to"), (int, float)):
                reduction += max(0, change["from"] - change["to"])
    return reduction


def approval_action(messages: list[dict], start: int) -> tuple[str, str] | None:
    """Return an exact test-only approval only when a fresh production preview is valid."""
    requirements = _tool_result_after(messages, "set_workout_requirements", start)
    previews = [m for m in messages[start:] if m.get("role") == "assistant"]
    if requirements and requirements.get("passed") is True and requirements.get("sourceReview", {}).get("passed") is True:
        identifier = requirements.get("requirementsId")
        if identifier and _preview_for(messages[start:], "canonicalRequirementsPreview", identifier,
                                       requirements.get("requirementsPreview")):
            # Alternative acceptance itself approves the new requirement revision.
            latest_alternative_approval = any(m.get("role") == "user" and
                str(m.get("content", "")).strip().startswith("APPROVE ALTERNATIVE ")
                for m in messages[start:])
            if not latest_alternative_approval and not any(m.get("role") == "user" and
                    m.get("content", "").strip() == "CONFIRM REQUIREMENTS" for m in messages[start:]):
                return "CONFIRM REQUIREMENTS", "passing source review and exact canonical requirements preview"

    proposals = _tool_result_after(messages, "propose_workout_alternatives", start)
    if proposals and proposals.get("outcome") == "alternatives_ready":
        from workout_generator_pkg.conflict_resolution import render_alternative_preview
        eligible = [p for p in proposals.get("proposals", [])
                    if p.get("independentReview", {}).get("passed") is True
                    and _preview_for(messages[start:], "canonicalAlternativePreview", p.get("proposalId"),
                                     render_alternative_preview(p))]
    else:
        eligible = []

    repair_result = _tool_result_after(messages, "repair_workout_alternative", start)
    if repair_result and repair_result.get("passed") is True:
        from workout_generator_pkg.user_interaction import pending_question
        question = pending_question(messages)
        repaired_proposal = repair_result.get("proposal")
        if (question and question.get("kind") == "alternative"
                and question.get("messageIndex", -1) >= start
                and repaired_proposal
                and question.get("reference") == repaired_proposal.get("proposalId")
                and repair_result.get("outcome") == "alternatives_ready"
                and repair_result.get("repairStatus") == "repaired_and_reviewed"
                and repaired_proposal.get("independentReview", {}).get("passed") is True
                and all(p.get("proposalId") != repaired_proposal.get("proposalId") for p in eligible)):
            eligible.append(repaired_proposal)

    approved = [m.get("content", "").strip().removeprefix("APPROVE ALTERNATIVE ")
                for m in messages[start:] if m.get("role") == "user"
                and m.get("content", "").strip().startswith("APPROVE ALTERNATIVE ")]
    if not approved and eligible:
        smallest = min(_volume_reduction(p) for p in eligible)
        best = [p for p in eligible if _volume_reduction(p) == smallest]
        if len(best) == 1:
            return f"APPROVE ALTERNATIVE {best[0]['proposalId']}", \
                "unique minimum-volume relaxation with exact passing full-review preview"

    candidate_id = next((m.get("canonicalDraftPreview") for m in reversed(previews)
                         if m.get("canonicalDraftPreview")), None)
    requirement_ids = [r.get("requirementsId") for r in retained.tool_results(messages, "set_workout_requirements")
                       if r.get("passed") is True]
    current_requirements_id = requirement_ids[-1] if requirement_ids else None
    if candidate_id and current_requirements_id:
        passed, audit = retained.current_candidate_passes(messages, current_requirements_id)
        if passed and audit and audit.get("draftId") == candidate_id and not any(
                m.get("role") == "user" and m.get("content", "").strip() == "CONFIRM GENERATE"
                for m in messages[start:]):
            return "CONFIRM GENERATE", "passing current audit and independent review with canonical candidate preview"
    return None


def _latest_materialized_audit(messages: list[dict], requirements_id: str | None) -> dict | None:
    if not requirements_id:
        return None
    audits = retained.tool_results(messages, "audit_workout_plan")
    return next((result for result in reversed(audits)
                 if result.get("requirementsId") == requirements_id
                 and result.get("currentDraftId")
                 and (result.get("audit") or result.get("submittedDraft"))), None)


def current_candidate_validation_pending(messages: list[dict], requirements_id: str | None) -> bool:
    """Detect an explicitly saved in-progress independent review for the current candidate."""
    current = _latest_materialized_audit(messages, requirements_id)
    if not current:
        return False
    errors = {error.get("code") for error in current.get("errors", []) if isinstance(error, dict)}
    review = current.get("review") or {}
    return (current.get("reviewPending") is True
            or "independent_review_pending" in errors
            or review.get("inProgress") is True
            or review.get("pending") is True)


def current_candidate_validation_complete(messages: list[dict], requirements_id: str | None) -> bool:
    """Return true when the latest materialized candidate is no longer awaiting review work."""
    current = _latest_materialized_audit(messages, requirements_id)
    if not current:
        return False
    errors = {error.get("code") for error in current.get("errors", []) if isinstance(error, dict)}
    review = current.get("review") or {}
    return (not current.get("reviewPending")
            and "independent_review_pending" not in errors
            and "coordinated_joint_pending" not in errors
            and not review.get("inProgress")
            and not review.get("pending"))


def candidate_validation_failure_summary(messages: list[dict], requirements_id: str | None) -> str | None:
    audit = _latest_materialized_audit(messages, requirements_id)
    if not audit:
        return None
    errors = [item for item in audit.get("errors", []) if isinstance(item, dict)]
    if errors:
        error = errors[0]
        detail = str(error.get("message") or "").strip()
        return f"{error.get('code', 'audit_failure')}: {detail[:500]}".strip()
    review = audit.get("review") or {}
    failure = str(review.get("failure") or "").strip()
    if failure:
        return f"independent_review_failure: {failure[:500]}"
    return None


def _self_check() -> None:
    assert approval_action([], 0) is None
    fake_requirements = {"requirementsId": "R1", "passed": True,
                         "sourceReview": {"passed": True}, "requirementsPreview": "full preview"}
    messages = [{"role": "assistant", "tool_calls": [{"id": "r", "function": {"name": "set_workout_requirements"}}]},
                {"role": "tool", "tool_call_id": "r", "content": json.dumps(fake_requirements)},
                {"role": "assistant", "canonicalRequirementsPreview": "R1", "content": "full preview"}]
    assert approval_action(messages[:1], 0) is None
    assert approval_action(messages, 0) == ("CONFIRM REQUIREMENTS", "passing source review and exact canonical requirements preview")
    messages[1]["content"] = json.dumps({**fake_requirements, "sourceReview": {"passed": False}})
    assert approval_action(messages, 0) is None
    from workout_generator_pkg.conflict_resolution import render_alternative_preview
    proposal = {"proposalId": "ALT_test", "changes": [{"path": "/auditTargets/weeklyEffectiveSets/chest/minimum",
        "from": 15, "to": 14}], "independentReview": {"passed": True, "preview": "Full reviewed candidate"},
        "claim": "Validated for this supplied menu; no global optimum is claimed."}
    preview = render_alternative_preview(proposal)
    proposal_result = {"outcome": "alternatives_ready", "proposals": [proposal]}
    alt_messages = [
        {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "propose_workout_alternatives"}}]},
        {"role": "tool", "tool_call_id": "a", "content": json.dumps(proposal_result)},
        {"role": "assistant", "canonicalAlternativePreview": "ALT_test", "content": "truncated preview"},
    ]
    assert approval_action(alt_messages, 0) is None
    alt_messages[-1]["content"] = preview
    assert approval_action(alt_messages, 0) == ("APPROVE ALTERNATIVE ALT_test",
        "unique minimum-volume relaxation with exact passing full-review preview")


def verify_export(messages: list[dict], export: Path, backup: Path) -> dict:
    """Verify the exported package against the latest approved plan and live validators."""
    import copy
    from jsonschema import Draft7Validator
    from workout_generator_pkg.constants import JSON_SCHEMA
    from workout_generator_pkg.domain_ops import get_selectable_weights_for_exercise
    from workout_generator_pkg.generation_audit import audit_workout_package
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload
    from workout_generator_pkg.plan_contract import LIBRARY_DEFINITION_OWNED_FIELDS
    from workout_generator_pkg.plan_review import require_current_review
    from workout_generator_pkg.planning_tools import (ASSUMPTIONS, AUDIT_VERSION, confirmed_draft,
        library_fingerprint, requirements_approved, workout_schedule_suffix)
    from workout_generator_pkg.training_history import TrainingHistory

    package_bytes = export.read_bytes()
    package = json.loads(package_bytes)
    sidecar = retained.read_json(export.with_suffix(".audit.json"))
    requirements_results = retained.tool_results(messages, "set_workout_requirements")
    requirements_result = next((item for item in reversed(requirements_results)
        if item.get("passed") is True and item.get("requirements")), None)
    if not requirements_result or not requirements_approved(messages, requirements_result):
        raise ValueError("No current source-reviewed and explicitly test-approved requirements receipt")
    equipment = _load_exercise_library_payload(str(backup))
    history = TrainingHistory.from_file(str(backup))
    approved = confirmed_draft(messages, equipment, require_confirmation=True)
    if approved.get("requirementsId") != requirements_result["requirementsId"]:
        raise ValueError("Exported plan does not reference the current approved requirements")
    require_current_review(approved, messages, equipment, history)
    if approved.get("historyFingerprint") != history.fingerprint:
        raise ValueError("Training history changed since candidate review")
    if approved.get("libraryFingerprint") != library_fingerprint(equipment):
        raise ValueError("Exercise library or equipment changed since candidate review")
    if approved.get("auditVersion") != AUDIT_VERSION or approved.get("audit", {}).get("assumptions") != ASSUMPTIONS:
        raise ValueError("Candidate was reviewed under stale audit rules")
    requirements = requirements_result["requirements"]
    if sidecar.get("targets") != requirements.get("auditTargets"):
        raise ValueError("Export sidecar targets differ from current approved requirements")
    store = retained.read_json(backup)
    store = store.get("WorkoutStore", store)
    source_definitions = {entry["id"]: entry for entry in store["exerciseDefinitions"]}
    definitions = {entry["id"]: entry for entry in package.get("exerciseDefinitions", [])}
    if package.get("schemaVersion") != 2:
        raise ValueError("Export is not exercise-library schema version 2")
    policy = requirements_result.get("restrictionPolicy", {})
    excluded = set(policy.get("excludedDefinitionIds", []))
    if excluded & set(definitions):
        raise ValueError("Export contains an exercise excluded by the approved restriction policy")
    for identifier, definition in definitions.items():
        if identifier not in source_definitions:
            raise ValueError(f"Export contains an exercise outside the immutable library: {identifier}")
        for field in LIBRARY_DEFINITION_OWNED_FIELDS:
            if definition.get(field) != source_definitions[identifier].get(field):
                raise ValueError(f"Library-owned field changed for {identifier}: {field}")
    for field in ("equipments", "accessoryEquipments"):
        if package.get(field) != store.get(field):
            raise ValueError(f"Export equipment changed from the immutable backup: {field}")

    submitted = approved["submittedDraft"]["workouts"]
    plan_days = approved["planIndex"]["workouts"]
    workouts = package["workouts"]
    expected_days = requirements.get("sessionsPerWeek")
    if expected_days is not None and len(workouts) != expected_days:
        raise ValueError("Exported session count differs from the current approved schedule")
    if not (len(workouts) == len(submitted) == len(plan_days)):
        raise ValueError("Exported workouts do not match the reviewed plan length")
    days = sorted(day for workout in submitted for day in workout["trainingDays"])
    if len(days) != len(set(days)):
        raise ValueError("Two exported sessions occupy the same training day")
    min_rest = requirements.get("minimumRestDaysBetweenSessions", 0)
    if len(days) > 1 and any((days[(i + 1) % len(days)] - day - 1) % 7 < min_rest
                              for i, day in enumerate(days)):
        raise ValueError("Exported schedule violates the approved recovery-day spacing")

    def exercises(workout):
        for component in workout["workoutComponents"]:
            if component["type"] == "Exercise":
                yield component
            elif component["type"] == "Superset":
                yield from component["exercises"]

    setup, rep_times, coverage = {}, {}, {}
    unique_ids = []
    equipment_by_id = {entry["id"]: entry for entry in package["equipments"]}
    working_sets = 0
    for workout, source_day, plan_day in zip(workouts, submitted, plan_days, strict=True):
        if workout["name"] != source_day["name"] or workout.get("timesCompletedInAWeek") != 1:
            raise ValueError("Exported workout identity or weekly schedule differs from the reviewed draft")
        if workout.get("description", "").endswith(workout_schedule_suffix(source_day["trainingDays"])) is False:
            raise ValueError("Exported schedule text differs from the reviewed training days")
        unique_ids.extend([workout["id"], workout["globalId"]])
        actual_exercises = list(exercises(workout))
        if len(actual_exercises) != len(source_day["exercises"]):
            raise ValueError("Exported exercise count differs from the reviewed draft")
        for exercise, source, planned_id in zip(actual_exercises, source_day["exercises"], plan_day["exerciseIds"], strict=True):
            planned = next(entry for entry in approved["planIndex"]["exercises"] if entry["id"] == planned_id)
            if exercise.get("exerciseDefinitionId") != planned["libraryDefinitionId"]:
                raise ValueError("Exported exercise order/identity differs from the joint-solved plan")
            for field in LIBRARY_DEFINITION_OWNED_FIELDS:
                if exercise.get(field) != definitions[planned["libraryDefinitionId"]].get(field):
                    raise ValueError(f"Exported exercise does not match its source definition: {field}")
            if bool(exercise.get("requiresLoadCalibration")) != bool(planned.get("requiresLoadCalibration")):
                raise ValueError("Exported native calibration mode differs from the reviewed plan")
            if "repDurationSeconds" in planned:
                rep_times[exercise["id"]] = planned["repDurationSeconds"]
            coverage[exercise["id"]] = list(source.get("satisfiesCoverage", []))
            work = [item for item in exercise["sets"] if item["type"] != "RestSet"
                    and item.get("subCategory", "WorkSet") not in ("WarmupSet", "WarmUpSet", "CalibrationSet")]
            if len(work) != source["numWorkSets"]:
                raise ValueError("Exported working-set count differs from the reviewed plan")
            if planned.get("targetSetPrescriptions"):
                load_field = "additionalWeight" if exercise["exerciseType"] == "BODY_WEIGHT" else "weight"
                actual = [(item["reps"], item.get(load_field, 0)) for item in work]
                expected = [(item["reps"], item[load_field]) for item in sorted(
                    planned["targetSetPrescriptions"], key=lambda item: item["workSetIndex"])]
                if actual != expected:
                    raise ValueError("Exported reps or loads differ from approved target prescriptions")
            working_sets += len(work)
            if any(field in exercise for field in (
                    "requiresEffortCalibration", "calibrationAttempts", "calibrationRecoverySeconds")):
                raise ValueError("Export contains a generator-authored calibration protocol")
            if "setupSeconds" in planned:
                setup[exercise["id"]] = planned["setupSeconds"]
            for item in work:
                if item["type"] in ("WeightSet", "BodyWeightSet"):
                    if not source["minReps"] <= item["reps"] <= source["maxReps"]:
                        raise ValueError("Exported reps are outside the approved prescription range")
                    load = item.get("weight", item.get("additionalWeight", 0))
                    if not exercise.get("requiresLoadCalibration") and exercise.get("equipmentId"):
                        selectable = get_selectable_weights_for_exercise(exercise["exerciseType"],
                            equipment_by_id[exercise["equipmentId"]])
                        if not any(abs(load - value) < 1e-6 for value in selectable):
                            raise ValueError("Exported load is not selectable on the approved equipment")
                unique_ids.append(item["id"])
            unique_ids.extend([exercise["id"]])
        unique_ids.extend(component["id"] for component in workout["workoutComponents"]
                          if component["type"] != "Exercise")
    if len(unique_ids) != len(set(unique_ids)):
        raise ValueError("Export contains duplicate occurrence, set, or component IDs")

    projection = copy.deepcopy(package)
    for key in ("schemaVersion", "exerciseDefinitions", "exerciseMovements"):
        projection.pop(key, None)
    for workout in projection["workouts"]:
        for exercise in exercises(workout):
            exercise.pop("exerciseDefinitionId", None)
    schema_errors = list(Draft7Validator(JSON_SCHEMA).iter_errors(projection))
    if schema_errors:
        raise ValueError("Export failed schema validation: " + "; ".join(error.message for error in schema_errors[:5]))
    if sidecar.get("coverageByExercise", {}) != coverage:
        raise ValueError("Export coverage sidecar differs from the reviewed plan")
    if sidecar.get("repDurationSecondsByExercise", {}) != rep_times:
        raise ValueError("Export rep-time sidecar differs from the reviewed plan")
    actual = audit_workout_package(package, requirements["auditTargets"], setup_seconds_by_exercise=setup,
        coverage_by_exercise=coverage, rep_duration_seconds_by_exercise=rep_times)
    if actual["errors"]:
        raise ValueError("Reproduced export audit failed: " + json.dumps(actual["errors"], ensure_ascii=False))
    for key in ("weeklyVolume", "weeklyWorkingSets", "weeklyCoverageSets", "workouts"):
        approved_value = approved["audit"].get(key)
        if key == "workouts":
            matches_review = _workout_audit_within_reviewed_envelope(actual[key], approved_value)
        else:
            matches_review = actual[key] == approved_value
        if actual[key] != sidecar.get(key) or not matches_review:
            raise ValueError(f"Reproduced export audit differs from the approved review: {key}")
    duration_limit = requirements["auditTargets"].get("maximumSessionSeconds")
    if duration_limit and any(day["estimatedSeconds"] > duration_limit for day in actual["workouts"]):
        raise ValueError("An exported session exceeds the approved duration cap")
    if export.read_bytes() != package_bytes:
        raise ValueError("Export changed while verification was running")
    return {"verified": True, "file": str(export.resolve()), "sha256": hashlib.sha256(package_bytes).hexdigest(),
        "requirementsId": requirements_result["requirementsId"], "draftId": approved["draftId"],
        "auditVersion": approved["auditVersion"], "reviewVersion": approved["review"]["version"],
        "sessionCount": len(workouts), "exerciseDefinitions": len(definitions), "workingSets": working_sets,
        "weeklyCoverageSets": actual["weeklyCoverageSets"],
        "actualMinutes": [round(day["estimatedSeconds"] / 60, 2) for day in actual["workouts"]]}


def provider_failure_reason(output_tail):
    match = re.search(r'Error code:\s*(\d{3})', output_tail)
    if not match:
        return None
    status = int(match.group(1))
    if status == 402 and 'insufficient balance' in output_tail.casefold():
        return 'Model provider returned HTTP 402 for insufficient balance; saved planning state is resumable.'
    return f'Model provider returned HTTP {status}; saved planning state is resumable.'


def run_case(case: dict, run: Path, timeout_seconds: int, *, resume: bool = False) -> int:
    from workout_generator_pkg.constants import EXACT_GENERATION_CONFIRMATION
    from workout_generator_pkg.interactive_shell import _completed_changed_repair_rounds
    from workout_generator_pkg.planning_tools import REQUIREMENTS_CONFIRMATION

    conversation_id = retained.case_conversation_id(run)
    messages_path = retained.conversation_file(run, conversation_id)
    initial_messages = retained.read_json(messages_path)
    first_turn = len(initial_messages)
    repair_attempt_start_index = first_turn
    previous_report = None
    attempt_number = 1
    orphaned_attempt = None
    orphaned_repair_start = first_turn
    if resume:
        previous_path = run / "synthetic_case_result.json"
        previous_report = retained.read_json(previous_path)
        if previous_report.get("fixtureId") != case["id"] or previous_report.get("syntheticOnly") is not True:
            raise RuntimeError("Cannot resume a different or non-synthetic case")
        if previous_report.get("outcome") != "unresolved" or previous_report.get("backupUnchanged") is not True:
            raise RuntimeError("Resume requires an unresolved prior attempt with an unchanged backup")
        process_state = retained.read_json(run / "process.json")
        ensure_saved_process_stopped(process_state, run)
        if process_state.get('status') == 'running':
            orphaned_attempt = process_state
            attempt_number = max(int(previous_report.get("attemptNumber", 1)) + 1,
                                 int(process_state.get('attemptNumber', 0)) + 1)
            for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('attemptNumber') == process_state.get('attemptNumber') and event.get('event') in (
                        'synthetic_run_started', 'synthetic_run_resumed'):
                    orphaned_repair_start = int(event.get('repairAttemptStartIndex', first_turn))
                    break
        else:
            attempt_number = int(previous_report.get("attemptNumber", 1)) + 1
        config = retained.read_json(run / "test_config.json")
        backup = Path(config["immutableBackup"])
        backup_hash = config["immutableBackupSHA256"]
        if file_hash(backup) != backup_hash:
            raise RuntimeError("Synthetic fixture backup changed before resume")
        # Preserve the old budget only to drain an admitted candidate's still-pending
        # review under the same audit/review contract. A later explicit resume after a
        # completed review or a changed review version gets a fresh bounded budget.
        current_requirements_id = next((item.get("requirementsId") for item in reversed(
            retained.tool_results(initial_messages, "set_workout_requirements")) if item.get("passed") is True), None)
        pending_audit = _latest_materialized_audit(initial_messages, current_requirements_id)
        pending_review = current_candidate_validation_pending(initial_messages, current_requirements_id)
        if not pending_review and pending_audit:
            from workout_generator_pkg.planning_tools import AUDIT_VERSION
            from workout_generator_pkg.plan_review import REVIEW_VERSION
            planner_state = current_planner_state(initial_messages, backup)
            terminal_failure = cached_review_failure_without_route(
                pending_audit, planner_state, AUDIT_VERSION, REVIEW_VERSION)
            if terminal_failure:
                raise RuntimeError(f"Cannot resume {run}: {terminal_failure}")
        if pending_review and pending_audit:
            from workout_generator_pkg.planning_tools import AUDIT_VERSION
            from workout_generator_pkg.plan_review import REVIEW_VERSION
            saved_review_version = (pending_audit.get("review") or {}).get("version")
            if pending_audit.get("auditVersion") == AUDIT_VERSION and saved_review_version == REVIEW_VERSION:
                for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("attemptNumber") == previous_report.get("attemptNumber") and event.get("event") in (
                            "synthetic_run_started", "synthetic_run_resumed"):
                        repair_attempt_start_index = int(event.get("repairAttemptStartIndex", first_turn))
                        break
        archived_attempt_number = (int(orphaned_attempt.get('attemptNumber')) if orphaned_attempt
                                   else attempt_number - 1)
        archive = run / f"attempt_{archived_attempt_number:02d}"
        if archive.exists():
            archived = retained.read_json(archive / "synthetic_case_result.json")
            if archived.get("attemptNumber") != archived_attempt_number:
                raise RuntimeError(f"Attempt archive already exists with unexpected contents: {archive}")
        else:
            archive.mkdir(parents=True)
            for name in ("synthetic_case_result.json", "stdout.log", "stderr.log", "events.jsonl", "process.json",
                         "final_verification.json"):
                source = run / name
                if source.is_file():
                    shutil.copy2(source, archive / name)
            log_dir = run / "logs"
            if log_dir.is_dir():
                shutil.copytree(log_dir, archive / "logs")
        if orphaned_attempt:
            timestamps = [path.stat().st_mtime for path in (run / 'stdout.log', run / 'stderr.log') if path.is_file()]
            ended = max(timestamps, default=time.time())
            started_at = datetime.fromisoformat(orphaned_attempt['startedAtUTC'].replace('Z', '+00:00')).timestamp()
            elapsed = max(0.0, ended - started_at)
            cumulative = elapsed + previous_report.get('cumulativeElapsedSeconds', previous_report.get('elapsedSeconds', 0))
            requirements_id = next((item.get('requirementsId') for item in reversed(
                retained.tool_results(initial_messages, 'set_workout_requirements')) if item.get('passed') is True), None)
            candidate_passed, audit = retained.current_candidate_passes(initial_messages, requirements_id) if requirements_id else (False, None)
            try:
                output_tail = (run / 'stdout.log').read_text(encoding='utf-8', errors='replace')[-6000:]
            except OSError:
                output_tail = ''
            paused = re.search(r'Planning paused:([^\r\n]+)', output_tail)
            prior_history = previous_report.get('attemptHistory', []) + [{
                'attemptNumber': int(previous_report.get('attemptNumber', 1)),
                'outcome': previous_report.get('outcome'), 'elapsedSeconds': previous_report.get('elapsedSeconds'),
                'apiMetrics': previous_report.get('apiMetrics'),
                'archivedResult': str((run / f"attempt_{archived_attempt_number - 1:02d}" / 'synthetic_case_result.json').resolve())}]
            recovered = {**previous_report, 'attemptNumber': archived_attempt_number,
                'outcome': 'unresolved', 'reason': 'Interrupted harness recovered saved CLI state: ' +
                    (paused.group(1).strip() if paused else 'the CLI process exited before the runner wrote its result.'),
                'candidateReviewPassed': candidate_passed, 'candidateDraftId': audit.get('currentDraftId') if audit else None,
                'testOnlyApprovalActions': [], 'elapsedSeconds': round(elapsed, 2),
                'cumulativeElapsedSeconds': round(cumulative, 2),
                'apiMetrics': retained.collect_usage(run, cumulative,
                    previous_report.get('apiMetrics', {}).get('repairRounds', 0)
                    + _completed_changed_repair_rounds(initial_messages, orphaned_repair_start),
                    orphaned_attempt.get('startedAtUTC')),
                'attemptHistory': prior_history, 'export': None, 'verification': None,
                'timingEvidenceComplete': False,
                'completedAtUTC': datetime.fromtimestamp(ended, timezone.utc).isoformat()}
            retained.write_json(archive / 'synthetic_case_result.json', recovered)
            previous_report = recovered
        retained.write_json(run / "resume_manifest.json", {"fixtureId": case["id"], "attemptNumber": attempt_number,
            "previousResult": str((archive / "synthetic_case_result.json").resolve()),
            "previousOutcome": previous_report.get("outcome"), "startedAtUTC": datetime.now(timezone.utc).isoformat(),
            "sameConversationId": conversation_id, "requirementsAndSearchResultsReused": True,
            "realUserApprovalClaimed": False})
    config = retained.read_json(run / "test_config.json")
    backup = Path(config["immutableBackup"])
    backup_hash = config["immutableBackupSHA256"]
    if file_hash(backup) != backup_hash:
        raise RuntimeError("Synthetic fixture backup changed before start")
    out_path, err_path = run / "stdout.log", run / "stderr.log"
    command = [sys.executable, "-X", "faulthandler", "-u", str(run / "run.py"),
               "--history-backup-file", str(backup), "--hybrid-fast",
               "--max-repair-rounds", "3",
               "--repair-attempt-start-index", str(repair_attempt_start_index)]
    started = time.monotonic()
    run_started = datetime.now(timezone.utc).isoformat()
    with (run / "events.jsonl").open("a" if resume else "w", encoding="utf-8") as events:
        events.write(json.dumps({"event": "synthetic_run_resumed" if resume else "synthetic_run_started",
            "attemptNumber": attempt_number, "atUTC": run_started, "argv": command,
            "maxRepairRounds": 3, "repairAttemptStartIndex": repair_attempt_start_index,
            "testOnly": True, "realUserApprovalClaimed": False}) + "\n")
    status = {"status": "running", "startedAtUTC": run_started, "fixtureId": case["id"],
              "attemptNumber": attempt_number, "childPID": None}
    retained.write_json(run / "process.json", status)
    sent: set[str] = set()
    review_continuations = 0
    repair_count = _completed_changed_repair_rounds(initial_messages, repair_attempt_start_index)
    idle_since = None
    reason = "Timed out before a reviewed export was produced"
    with out_path.open("wb") as stdout, err_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=REPO, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        status["childPID"] = process.pid
        retained.write_json(run / "process.json", status)
        process.stdin.write(f"/resume-conversation {conversation_id}\n/continue\n".encode("utf-8"))
        process.stdin.flush()
        deadline = started + timeout_seconds
        while process.poll() is None and time.monotonic() < deadline:
            try:
                messages = retained.read_json(messages_path)
            except (OSError, ValueError):
                time.sleep(0.5)
                continue
            completed_repairs = _completed_changed_repair_rounds(messages, repair_attempt_start_index)
            if completed_repairs > repair_count:
                for round_number in range(repair_count + 1, completed_repairs + 1):
                    with (run / "events.jsonl").open("a", encoding="utf-8") as events:
                        events.write(json.dumps({"event": "candidate_changing_repair_admitted",
                            "attemptNumber": attempt_number, "repairRound": round_number,
                            "maxRepairRounds": 3, "repairAttemptStartIndex": first_turn,
                            "atUTC": datetime.now(timezone.utc).isoformat()}) + "\n")
                repair_count = completed_repairs
            current_requirements_id = next((item.get("requirementsId") for item in reversed(
                retained.tool_results(messages, "set_workout_requirements")) if item.get("passed") is True), None)
            if completed_repairs > 3:
                reason = "Production repair admission exceeded the three candidate-changing round cap"
                break
            if completed_repairs >= 3 and current_candidate_validation_complete(messages, current_requirements_id):
                # Allow the third admitted revision to finish its numerical and independent
                # review. If it passes, the normal exact-preview approval gate still applies.
                if approval_action(messages, first_turn) is None and not sent:
                    reason = ("Three candidate-changing repair rounds were admitted; the final "
                              "candidate validation completed without a passing approval preview")
                    failure_detail = candidate_validation_failure_summary(messages, current_requirements_id)
                    if failure_detail:
                        reason += f". Latest validation failure: {failure_detail}"
                    break
            action = approval_action(messages, first_turn)
            if action and action[0] not in sent and retained.cli_waiting_for_input(out_path):
                text, evidence = action
                if text == "CONFIRM REQUIREMENTS":
                    allowed = REQUIREMENTS_CONFIRMATION
                elif text == "CONFIRM GENERATE":
                    allowed = EXACT_GENERATION_CONFIRMATION
                else:
                    allowed = text
                process.stdin.write((allowed + "\n").encode("utf-8"))
                process.stdin.flush()
                sent.add(text)
                with (run / "events.jsonl").open("a", encoding="utf-8") as events:
                    events.write(json.dumps({"event": "test_only_exact_approval_injected", "atUTC": datetime.now(timezone.utc).isoformat(),
                        "phrase": allowed, "evidence": evidence, "realUserApprovalClaimed": False}) + "\n")
                idle_since = None
            elif retained.cli_waiting_for_input(out_path):
                if (completed_repairs >= 3 and review_continuations < 2
                        and current_candidate_validation_pending(messages, current_requirements_id)):
                    process.stdin.write("/continue\n".encode("utf-8"))
                    process.stdin.flush()
                    review_continuations += 1
                    with (run / "events.jsonl").open("a", encoding="utf-8") as events:
                        events.write(json.dumps({"event": "test_only_pending_review_resume",
                            "attemptNumber": attempt_number, "atUTC": datetime.now(timezone.utc).isoformat(),
                            "continuation": review_continuations, "repairRoundsAdmitted": completed_repairs,
                            "repairAttemptStartIndex": repair_attempt_start_index,
                            "realUserApprovalClaimed": False}) + "\n")
                    idle_since = None
                    time.sleep(0.5)
                    continue
                if idle_since is None:
                    try:
                        output_tail = out_path.read_text(encoding="utf-8", errors="replace")[-6000:]
                    except OSError:
                        output_tail = ""
                    provider_failure = provider_failure_reason(output_tail)
                    if provider_failure:
                        reason = provider_failure
                        break
                    paused = re.search(r"Planning paused:([^\r\n]+)", output_tail)
                    if paused:
                        reason = "Planning paused: " + paused.group(1).strip()
                        break
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= 45:
                    reason = "CLI requested user input that the synthetic approval gates could not safely provide"
                    break
            else:
                idle_since = None
            time.sleep(0.5)
        if process.poll() is None:
            retained.stop_child(process)
        messages = retained.read_json(messages_path)
    elapsed = time.monotonic() - started
    meta_path = run / "workouts" / "conversation_sessions" / conversation_id / "meta.json"
    metadata = retained.read_json(meta_path)
    generation = metadata.get("last_generation_result") or {}
    output = Path(generation["filepath"]) if generation.get("filepath") else None
    exported = generation.get("success") is True and output is not None and output.is_file()
    latest_req = retained.tool_results(messages, "set_workout_requirements")
    requirements_id = next((item.get("requirementsId") for item in reversed(latest_req)
                            if item.get("passed") is True), None)
    candidate_passed, audit = retained.current_candidate_passes(messages, requirements_id) if requirements_id else (False, None)
    verification = None
    if exported and candidate_passed:
        try:
            verification = verify_export(messages, output, backup)
            retained.write_json(run / "final_verification.json", verification)
            outcome = "synthetic_export_verified"
        except Exception as error:
            reason = f"Export was produced but the generic production-path verifier rejected it: {type(error).__name__}: {error}"
            outcome = "synthetic_export_unverified"
    else:
        outcome = "unresolved"
    backup_after = file_hash(backup)
    cumulative_elapsed = elapsed + (previous_report.get("cumulativeElapsedSeconds", previous_report.get("elapsedSeconds", 0))
        if previous_report else 0)
    previous_repairs = previous_report.get("apiMetrics", {}).get("repairRounds", 0) if previous_report else 0
    report = {"fixtureId": case["id"], "syntheticOnly": True, "realUserApprovalClaimed": False,
        "attemptNumber": attempt_number, "resumedSameConversation": resume,
        "outcome": outcome, "reason": None if outcome == "synthetic_export_verified" else reason,
        "requirementsId": requirements_id, "candidateReviewPassed": candidate_passed,
        "candidateDraftId": audit.get("currentDraftId") if audit else None,
        "candidateValidationFailure": candidate_validation_failure_summary(messages, requirements_id),
        "testOnlyApprovalActions": sorted(sent), "elapsedSeconds": round(elapsed, 2),
        "cumulativeElapsedSeconds": round(cumulative_elapsed, 2),
        "apiMetrics": retained.collect_usage(run, cumulative_elapsed, previous_repairs + repair_count,
            run_started),
        "attemptHistory": ((previous_report.get("attemptHistory", []) + [{"attemptNumber": int(previous_report.get("attemptNumber", 1)),
            "outcome": previous_report.get("outcome"), "elapsedSeconds": previous_report.get("elapsedSeconds"),
            "apiMetrics": previous_report.get("apiMetrics"), "archivedResult": str(
                (run / f"attempt_{attempt_number - 1:02d}" / "synthetic_case_result.json").resolve())}])
            if previous_report else []),
        "export": ({"path": str(output), "sha256": file_hash(output), "verified": verification is not None}
                   if exported else None), "verification": verification,
        "immutableBackupSHA256Before": backup_hash, "immutableBackupSHA256After": backup_after,
        "backupUnchanged": backup_after == backup_hash, "completedAtUTC": datetime.now(timezone.utc).isoformat()}
    retained.write_json(run / "synthetic_case_result.json", report)
    status.update(status="exited", endedAtUTC=report["completedAtUTC"], exitCode=process.returncode)
    retained.write_json(run / "process.json", status)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if outcome == "synthetic_export_verified" and report["backupUnchanged"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=("all", "synthetic_ordinary_4day_60min",
        "synthetic_tight_time_negotiable_volume"), default="all")
    parser.add_argument("--run", action="store_true", help="Start real model calls through the production CLI; omitted means prepare only")
    parser.add_argument("--resume-directory", help="Resume an unresolved synthetic case in its existing conversation directory")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.timeout_seconds < 60:
        parser.error("timeout must be at least 60 seconds")
    if args.self_check:
        _self_check()
        print("Synthetic runner approval-gate self-check passed")
        return 0
    fixture = retained.read_json(FIXTURE)
    if fixture.get("syntheticOnly") is not True or fixture.get("realUserApprovalClaimed") is not False:
        raise ValueError("Fixture manifest is not explicitly synthetic")
    backup_info = fixture["immutableFixtureInput"]
    backup = Path(backup_info["path"])
    expected_hash = backup_info["sha256"]
    if file_hash(backup) != expected_hash:
        raise ValueError("Immutable workout backup hash does not match the synthetic fixture manifest")
    if args.resume_directory:
        run = Path(args.resume_directory).resolve()
        config = retained.read_json(run / "test_config.json")
        if config.get("syntheticOnly") is not True or config.get("immutableBackupSHA256") != expected_hash:
            raise ValueError("Resume directory is not the matching isolated synthetic fixture")
        case = next((item for item in fixture["cases"] if item["id"] == config.get("fixtureId")), None)
        if case is None or args.case_id not in ("all", case["id"]):
            raise ValueError("Resume directory does not match the selected fixture")
        return run_case(case, run, args.timeout_seconds, resume=True)
    selected = [case for case in fixture["cases"] if args.case_id == "all" or case["id"] == args.case_id]
    if len(selected) != (2 if args.case_id == "all" else 1):
        raise ValueError("Requested synthetic fixture is missing or duplicated")
    prepared = []
    for case in selected:
        run = prepare_case(case, backup, expected_hash)
        prepared.append({"fixtureId": case["id"], "runDirectory": str(run), "modelWillRun": args.run,
                         "testOnly": True, "realUserApprovalClaimed": False})
        if args.run:
            return_code = run_case(case, run, args.timeout_seconds)
            if return_code:
                print(json.dumps(prepared, indent=2))
                return return_code
    print(json.dumps(prepared, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
