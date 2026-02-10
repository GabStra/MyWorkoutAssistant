"""Typed dependency containers for pipeline and shell orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PipelineDeps:
    test_connection: Any
    hash_conversation: Any
    PlaceholderIdManager: Any
    load_generation_progress: Any
    summarize_conversation: Any
    save_generation_progress: Any
    generate_index: Any
    deduplicate_plan_index_accessories: Any
    validate_equipment_immutability: Any
    emit_equipment_item: Any
    emit_accessory_equipment_item: Any
    emit_exercise_definition: Any
    emit_workout_structure: Any
    parallel_emit_items: Any
    assemble_placeholder_workout_store: Any
    sync_exercises_from_definitions: Any
    apply_accessory_id_rewrite: Any
    validate_and_repair_placeholder_json: Any
    save_validation_error: Any
    convert_placeholders_to_uuids: Any
    ensure_requiresLoadCalibration: Any
    save_workout_to_file: Any
    display_workout_summary: Any
    display_timing_summary: Any
    delete_progress_file: Any
    format_equipment_for_llm: Any
    EquipmentItem: Any
    default_script_dir: Any


@dataclass(frozen=True)
class ShellDeps:
    default_script_dir: Any
    load_equipment_from_file: Any
    load_conversation: Any
    has_equipment_in_messages: Any
    format_equipment_for_conversation: Any
    base_system_prompt: Any
    load_conversation_meta: Any
    save_conversation_meta: Any
    get_log_dir: Any
    ConversationLogger: Any
    chat_call_with_loading: Any
    generate_workout_tool: Any
    handle_function_call: Any
    execute_workout_generation: Any
    save_conversation: Any
    list_available_progress: Any
    delete_progress_file: Any
    conversation_file: Any
    OpenAI: Any
    httpx: Any


def resolve_pipeline_deps() -> PipelineDeps:
    from . import cli as _c

    return PipelineDeps(
        test_connection=_c.test_connection,
        hash_conversation=_c.hash_conversation,
        PlaceholderIdManager=_c.PlaceholderIdManager,
        load_generation_progress=_c.load_generation_progress,
        summarize_conversation=_c.summarize_conversation,
        save_generation_progress=_c.save_generation_progress,
        generate_index=_c.generate_index,
        deduplicate_plan_index_accessories=_c.deduplicate_plan_index_accessories,
        validate_equipment_immutability=_c.validate_equipment_immutability,
        emit_equipment_item=_c.emit_equipment_item,
        emit_accessory_equipment_item=_c.emit_accessory_equipment_item,
        emit_exercise_definition=_c.emit_exercise_definition,
        emit_workout_structure=_c.emit_workout_structure,
        parallel_emit_items=_c.parallel_emit_items,
        assemble_placeholder_workout_store=_c.assemble_placeholder_workout_store,
        sync_exercises_from_definitions=_c.sync_exercises_from_definitions,
        apply_accessory_id_rewrite=_c.apply_accessory_id_rewrite,
        validate_and_repair_placeholder_json=_c.validate_and_repair_placeholder_json,
        save_validation_error=_c.save_validation_error,
        convert_placeholders_to_uuids=_c.convert_placeholders_to_uuids,
        ensure_requiresLoadCalibration=_c.ensure_requiresLoadCalibration,
        save_workout_to_file=_c.save_workout_to_file,
        display_workout_summary=_c.display_workout_summary,
        display_timing_summary=_c.display_timing_summary,
        delete_progress_file=_c.delete_progress_file,
        format_equipment_for_llm=_c.format_equipment_for_llm,
        EquipmentItem=_c.EquipmentItem,
        default_script_dir=_c._default_script_dir,
    )


def resolve_shell_deps() -> ShellDeps:
    from . import cli as _c

    return ShellDeps(
        default_script_dir=_c._default_script_dir,
        load_equipment_from_file=_c.load_equipment_from_file,
        load_conversation=_c.load_conversation,
        has_equipment_in_messages=_c.has_equipment_in_messages,
        format_equipment_for_conversation=_c.format_equipment_for_conversation,
        base_system_prompt=_c.BASE_SYSTEM_PROMPT,
        load_conversation_meta=_c.load_conversation_meta,
        save_conversation_meta=_c.save_conversation_meta,
        get_log_dir=_c.get_log_dir,
        ConversationLogger=_c.ConversationLogger,
        chat_call_with_loading=_c.chat_call_with_loading,
        generate_workout_tool=_c.GENERATE_WORKOUT_TOOL,
        handle_function_call=_c.handle_function_call,
        execute_workout_generation=_c.execute_workout_generation,
        save_conversation=_c.save_conversation,
        list_available_progress=_c.list_available_progress,
        delete_progress_file=_c.delete_progress_file,
        conversation_file=_c.CONVERSATION_FILE,
        OpenAI=_c.OpenAI,
        httpx=_c.httpx,
    )
