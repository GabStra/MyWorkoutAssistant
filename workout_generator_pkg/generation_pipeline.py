"""Compile the current confirmed, reviewed plan into the native app package."""

from __future__ import annotations

import copy
import json
import os
import time
import uuid
from datetime import datetime

from jsonschema import Draft7Validator

from .constants import JSON_SCHEMA
from .conversation_meta import hash_conversation
from .domain_ops import (
    _materialize_exercise_definition, apply_exercise_library_schema_v2,
    assemble_placeholder_workout_store, build_workout_structure,
    convert_placeholders_to_uuids, create_placeholder_schema,
    ensure_requiresLoadCalibration, finalize_and_validate_exercise_definition,
    reviewable_workout_artifact, EquipmentItem,
)
from .generation_audit import (
    audit_workout_package, plan_audit_package, plan_timing_reps_by_exercise,
    validate_audit_targets, audit_coverage_minimums, family_set_audit_options,
    audit_programming_preferences,
)
from .logging_ui import LoadingIndicator
from .plan_contract import (
    ContractValidationError, hydrate_plan_index_from_exercise_library,
    validate_plan_index_contract, validate_exercise_definitions_contract,
    validate_workout_structures_contract, validate_assembled_workout_contract,
    validate_uuid_conversion_parity,
)
from .plan_review import require_current_review
from .planning_tools import confirmed_draft, draft_coverage_assignments, active_requirement_result
from .planning_decisions import execution_decision_definitions
from .progress import load_generation_progress, save_generation_progress, delete_progress_file
from .training_history import apply_native_load_calibration_policy
from .domain_ops import save_validation_error


def execute_workout_generation(
    client, messages, custom_prompt="", resume_session_id=None,
    provided_equipment=None, logger=None, script_dir=None,
    force_use_reasoner=None, allow_educated_load_guesses=True, training_history=None,
):
    """Compile without provider calls; confirmation and review remain authoritative."""
    # These CLI-owned utilities remain public compatibility entry points.
    from .cli import (PlaceholderIdManager, _default_script_dir, save_workout_to_file,
                      display_workout_summary, display_timing_summary)

    def _gen_print(message):
        logger.log_print(message) if logger is not None else print(message)

    def _log_step_error(step, error, prefix="Error reason"):
        _gen_print(f"{prefix} ({step}): {error}")

    script_dir = script_dir or _default_script_dir()
    review_equipment = copy.deepcopy(provided_equipment or {})
    try:
        canonical_snapshot = confirmed_draft(messages, review_equipment,
            allow_educated_load_guesses, require_confirmation=True)
        history_fingerprint = (training_history if training_history is not None
                               else canonical_snapshot.get('historyFingerprint'))
        require_current_review(canonical_snapshot, messages, review_equipment, history_fingerprint)
        _, approved_requirements = active_requirement_result(messages)
        audit_requirements = approved_requirements.get('requirements', {})
        coverage_rules = audit_requirements.get('requiredCoverage', [])
    except ValueError as error:
        return {"success": False, "filepath": None, "error": str(error)}

    session_id = resume_session_id or str(uuid.uuid4())
    conversation_hash = hash_conversation(messages)
    id_manager = PlaceholderIdManager()
    timing_data = {"total_time_seconds": 0.0, "step_times": {}, "save_times": [],
                   "session_start_time": datetime.now().isoformat(), "last_step_time": None}
    if resume_session_id:
        progress = load_generation_progress(resume_session_id, script_dir)
        if not progress:
            return {"success": False, "filepath": None,
                    "error": f"Could not load progress for session {resume_session_id[:8]}"}
        id_manager.restore_state(progress.get('id_manager_state', {}))
        _gen_print("Resuming by recompiling the current confirmed plan; saved emission artifacts are not authoritative.")

    step_data = {}
    step_started = time.time()

    def checkpoint(step, **artifacts):
        nonlocal step_started
        now = time.time()
        step_data.update(artifacts)
        timing_data['step_times'][step] = now - step_started
        timing_data['last_step_time'] = datetime.now().isoformat()
        save_generation_progress(session_id, step, step_data, custom_prompt,
            conversation_hash, id_manager, script_dir, timing_data)
        step_started = time.time()

    try:
        plan_index = copy.deepcopy(canonical_snapshot['planIndex'])
        execution_definitions = execution_decision_definitions(messages, review_equipment)
        supplied_exercise_definitions = [copy.deepcopy(execution_definitions.get(definition['id'], definition))
            for definition in review_equipment.get('exerciseDefinitions', [])]
        supplied_exercise_movements = copy.deepcopy(review_equipment.get('exerciseMovements', []))
        selected_ids = {item['libraryDefinitionId'] for item in plan_index['exercises']}
        if selected_ids - {item['id'] for item in supplied_exercise_definitions}:
            raise ContractValidationError("Selected exercises are absent from the currently loaded library. Select available entries and confirm the preview again.")
        provided_equipment = copy.deepcopy(review_equipment)
        for key, accessory in (('equipments', False), ('accessoryEquipments', True)):
            provided_equipment[key] = [id_manager.convert_equipment_uuids_to_placeholders(item, is_accessory=accessory)
                                      for item in review_equipment.get(key, [])]
        provided_equipment['exerciseDefinitions'] = copy.deepcopy([
            item for item in supplied_exercise_definitions if item['id'] in selected_ids])
        for item in provided_equipment['exerciseDefinitions']:
            item['equipmentId'] = id_manager.uuid_to_placeholder.get(item.get('equipmentId'), item.get('equipmentId'))
            item['requiredAccessoryEquipmentIds'] = [id_manager.uuid_to_placeholder.get(i, i)
                for i in item.get('requiredAccessoryEquipmentIds') or []]
        plan_index['equipments'] = copy.deepcopy(provided_equipment['equipments'])
        plan_index['accessoryEquipments'] = copy.deepcopy(provided_equipment['accessoryEquipments'])
        hydrate_plan_index_from_exercise_library(plan_index, provided_equipment['exerciseDefinitions'])
        validate_plan_index_contract(plan_index, provided_equipment)
        validate_audit_targets(plan_index.get('auditTargets'))
        expected_plan = copy.deepcopy(plan_index)
        apply_native_load_calibration_policy(expected_plan, messages, review_equipment,
            getattr(training_history, 'fingerprint', None) or canonical_snapshot.get('historyFingerprint'),
            allow_educated_load_guesses=allow_educated_load_guesses)
        if ([item.get('requiresLoadCalibration') for item in plan_index['exercises']]
                != [item.get('requiresLoadCalibration') for item in expected_plan['exercises']]):
            raise ContractValidationError("The approved draft's load-calibration flags do not match its current comparable history. Re-audit the draft before generation.")
        plan_index = expected_plan
        plan_audit = audit_workout_package(plan_audit_package(plan_index, allow_educated_load_guesses),
            plan_index.get('auditTargets') or {},
            coverage_by_exercise=draft_coverage_assignments(plan_index, canonical_snapshot.get('submittedDraft')),
            **family_set_audit_options(audit_requirements or plan_index, review_equipment))
        audit_coverage_minimums(plan_audit, coverage_rules)
        audit_programming_preferences(plan_audit, plan_index, audit_requirements)
        if plan_audit['issues']:
            return {"success": False, "filepath": None, "error": "Programming audit requires a revised plan.",
                    "requires_plan_revision": True, "programming_audit": plan_audit}
        checkpoint(1, step_1_plan_index=plan_index, step_1_programming_audit=plan_audit)

        equipment_items = {item['id']: EquipmentItem(item) for item in provided_equipment['equipments']}
        accessory_items = {item['id']: item for item in provided_equipment['accessoryEquipments']}
        exercise_definitions = {}
        for entry in plan_index['exercises']:
            exercise = _materialize_exercise_definition(entry)
            exercise_definitions[entry['id']] = finalize_and_validate_exercise_definition(
                exercise, plan_entry=entry,
                equipment_subset=[equipment_items[entry['equipmentId']]] if entry.get('equipmentId') in equipment_items else [],
                accessory_subset=[accessory_items[i] for i in entry.get('requiredAccessoryEquipmentIds') or []],
                all_equipment_candidates=list(equipment_items.values()),
                allow_educated_load_guesses=allow_educated_load_guesses)
        validate_exercise_definitions_contract(plan_index, exercise_definitions)
        checkpoint(3, step_2_equipment_items=equipment_items, step_2_accessory_items=accessory_items,
                   step_3_exercise_definitions=exercise_definitions)
        workout_structures = {day['id']: build_workout_structure(day) for day in plan_index['workouts']}
        validate_workout_structures_contract(plan_index, workout_structures, exercise_definitions)
        placeholder_store = assemble_placeholder_workout_store(equipment_items, accessory_items,
            exercise_definitions, workout_structures, plan_index)
        validate_assembled_workout_contract(plan_index, placeholder_store)
        Draft7Validator(create_placeholder_schema()).validate(placeholder_store)
        checkpoint(6, step_4_workout_structures=workout_structures,
                   step_5_placeholder_workout_store=placeholder_store,
                   step_6_validated_placeholder_store=placeholder_store)
        data = convert_placeholders_to_uuids(placeholder_store, id_manager, validate_final=False, logger=logger)
        validate_uuid_conversion_parity(placeholder_store, data)
        Draft7Validator(JSON_SCHEMA).validate(data)
        data = apply_exercise_library_schema_v2(data, supplied_exercise_definitions, supplied_exercise_movements)
        checkpoint(7, step_7_final_workout_store=data)
        _gen_print("Step 8: Auditing actual generated volume and duration...")
        audit_start = time.time()
        with LoadingIndicator("Auditing generated volume and duration"):
            setup_seconds = {id_manager.placeholder_to_uuid.get(e['id'], e['id']): e['setupSeconds']
                             for e in plan_index['exercises'] if 'setupSeconds' in e}
            coverage = {id_manager.placeholder_to_uuid.get(identifier, identifier): keys for identifier, keys in
                        draft_coverage_assignments(plan_index, canonical_snapshot.get('submittedDraft')).items()}
            timing_reps = {id_manager.placeholder_to_uuid.get(identifier, identifier): reps
                           for identifier, reps in plan_timing_reps_by_exercise(
                               plan_index, allow_educated_load_guesses).items()}
            final_audit = audit_workout_package(data, plan_index.get("auditTargets") or {},
                setup_seconds_by_exercise=setup_seconds,
                coverage_by_exercise=coverage, rep_duration_seconds_by_exercise={
                    id_manager.placeholder_to_uuid.get(e['id'], e['id']): e['repDurationSeconds']
                    for e in plan_index['exercises'] if 'repDurationSeconds' in e},
                timing_reps_by_exercise=timing_reps,
                **family_set_audit_options(audit_requirements or plan_index, review_equipment),
                )
            audit_coverage_minimums(final_audit, coverage_rules)
            audit_programming_preferences(final_audit, canonical_snapshot['planIndex'], audit_requirements)
            emitted_audit = audit_workout_package(data, plan_index.get("auditTargets") or {},
                setup_seconds_by_exercise=setup_seconds,
                rep_duration_seconds_by_exercise={
                    id_manager.placeholder_to_uuid.get(e['id'], e['id']): e['repDurationSeconds']
                    for e in plan_index['exercises'] if 'repDurationSeconds' in e},
                **family_set_audit_options(audit_requirements or plan_index, review_equipment),
                )
            for conservative, emitted in zip(final_audit['workouts'], emitted_audit['workouts'], strict=True):
                conservative['emittedPrescriptionEstimatedSeconds'] = emitted['estimatedSeconds']
                conservative['emittedPrescriptionTiming'] = copy.deepcopy(emitted['timing'])
        final_audit["prescriptionChanges"] = step_data.get("step_1_programming_audit", {}).get("prescriptionChanges", [])
        priority_receipt = canonical_snapshot.get('coordinatedJointPlanning') or canonical_snapshot.get('automaticAllocation') or {}
        for field in ('priorityExecution', 'priorityTradeoffs'):
            if field in priority_receipt:
                final_audit[field] = copy.deepcopy(priority_receipt[field])
        step_data["step_8_programming_audit"] = final_audit
        timing_data["step_times"][8] = time.time() - audit_start
        for workout_audit in final_audit["workouts"]:
            _gen_print(f"  {workout_audit['name']}: {workout_audit['workingSets']} working sets, estimated {workout_audit['estimatedSeconds']/60:.1f} min")
        for muscle, volume in final_audit["weeklyVolume"].items():
            _gen_print(f"  Weekly {muscle}: {volume['direct']:g} direct + {volume['indirect']:g} indirect = {volume['effective']:g} effective sets")
        if final_audit["issues"]:
            _gen_print("Final programming audit failed: " + " | ".join(final_audit["issues"]))
            save_validation_error(ValueError(" | ".join(final_audit["issues"])), data, script_dir)
            return {"success": False, "filepath": None, "error": "Final programming audit failed: " + " | ".join(final_audit["issues"]),
                    "requires_plan_revision": True, "programming_audit": final_audit}
        _gen_print("✓ Actual volume and duration audit passed (duration is an estimate under stated assumptions)")
        _, save_time = save_generation_progress(session_id, 8, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data)

        # Update final total time (including save times)
        save_times_total = sum(timing_data.get("save_times", []))
        step_times_total = sum(timing_data.get("step_times", {}).values())
        # Total time is sum of step times and save times
        timing_data["total_time_seconds"] = step_times_total + save_times_total
        
        # Final calibration policy is controlled by the user-selected mode.
        ensure_requiresLoadCalibration(
            data,
            allow_educated_load_guesses=allow_educated_load_guesses,
        )

        from .plan_review import _context
        reviewed_context = _context(canonical_snapshot, messages, review_equipment,
            training_history if training_history is not None else canonical_snapshot.get('historyFingerprint'),
            canonical_snapshot['review']['instructionBoundary'])
        program_guidance = reviewed_context['finalArtifact']['programGuidance']
        actual = reviewable_workout_artifact(canonical_snapshot['planIndex'], program_guidance,
            data, id_manager.placeholder_to_uuid)
        if actual != reviewed_context['finalArtifact']:
            raise ContractValidationError('The final export differs from the independently reviewed artifact. Re-audit and review before export.')
        

        # Save workout to file
        filepath = save_workout_to_file(data, script_dir)
        guidance_filepath = None
        if isinstance(program_guidance, str) and program_guidance.strip():
            if not filepath:
                return {"success": False, "filepath": None, "error": "Could not save the workout required for its program guidance sidecar."}
            guidance_filepath = os.path.splitext(filepath)[0] + ".guidance.md"
            with open(guidance_filepath, "w", encoding="utf-8") as guidance_file:
                guidance_file.write("# Program guidance\n\nManual reference for the generated program; this file is not included in the phone or watch workout data.\n\n")
                guidance_file.write(program_guidance.strip())
                guidance_file.write("\n")
            _gen_print(f"Program guidance and audit disclosures saved to: {guidance_filepath}")
        if filepath:
            audit_filepath = os.path.splitext(filepath)[0] + ".audit.json"
            with open(audit_filepath, "w", encoding="utf-8") as audit_file:
                json.dump(final_audit, audit_file, indent=2, ensure_ascii=False)
            _gen_print(f"Programming audit saved to: {audit_filepath}")
        if filepath is None:
            return {"success": False, "filepath": None, "error": "Could not save the compiled workout package."}
        display_workout_summary(data, filepath, logger=logger)

        # Display timing summary
        display_timing_summary(timing_data, is_resume=(resume_session_id is not None), logger=logger)
        
        # Delete progress file on successful completion
        if delete_progress_file(session_id, script_dir):
            _gen_print("✓ Progress file cleaned up")
        
        return {
            "success": True,
            "filepath": filepath,
            "guidance_filepath": guidance_filepath,
            "error": None,
            "emitter_conversations": [],
        }
            
    except KeyboardInterrupt:
        return {"success": False, "filepath": None, "error": "Cancelled by user"}
    except ValueError as e:
        _log_step_error("Pipeline", e)
        return {"success": False, "filepath": None, "error": f"Generation error: {e}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        _log_step_error("Pipeline", e)
        return {"success": False, "filepath": None, "error": f"Error: {e}"}

