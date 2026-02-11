"""Generation pipeline orchestration."""

from __future__ import annotations
import json
import os
import re
import time
import traceback
import uuid
from datetime import datetime

from .deps import resolve_pipeline_deps
from .plan_contract import (
    ContractValidationError,
    validate_exercise_definitions_contract,
    validate_plan_index_contract,
    validate_uuid_conversion_parity,
    validate_workout_structures_contract,
)

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
):
    deps = deps or resolve_pipeline_deps()
    test_connection = deps.test_connection
    hash_conversation = deps.hash_conversation
    PlaceholderIdManager = deps.PlaceholderIdManager
    load_generation_progress = deps.load_generation_progress
    summarize_conversation = deps.summarize_conversation
    save_generation_progress = deps.save_generation_progress
    generate_index = deps.generate_index
    deduplicate_plan_index_accessories = deps.deduplicate_plan_index_accessories
    validate_equipment_immutability = deps.validate_equipment_immutability
    emit_equipment_item = deps.emit_equipment_item
    emit_accessory_equipment_item = deps.emit_accessory_equipment_item
    emit_exercise_definition = deps.emit_exercise_definition
    emit_workout_structure = deps.emit_workout_structure
    parallel_emit_items = deps.parallel_emit_items
    assemble_placeholder_workout_store = deps.assemble_placeholder_workout_store
    sync_exercises_from_definitions = deps.sync_exercises_from_definitions
    apply_accessory_id_rewrite = deps.apply_accessory_id_rewrite
    validate_and_repair_placeholder_json = deps.validate_and_repair_placeholder_json
    save_validation_error = deps.save_validation_error
    convert_placeholders_to_uuids = deps.convert_placeholders_to_uuids
    ensure_requiresLoadCalibration = deps.ensure_requiresLoadCalibration
    save_workout_to_file = deps.save_workout_to_file
    display_workout_summary = deps.display_workout_summary
    display_timing_summary = deps.display_timing_summary
    delete_progress_file = deps.delete_progress_file
    format_equipment_for_llm = deps.format_equipment_for_llm
    EquipmentItem = deps.EquipmentItem
    _default_script_dir = deps.default_script_dir
    """
    Execute the complete workout generation process.
    
    Args:
        client: OpenAI client
        messages: Conversation messages
        custom_prompt: Optional additional instructions for workout generation
        resume_session_id: Optional session ID to resume from saved progress
        provided_equipment: Optional dict with 'equipments' and 'accessoryEquipments' keys
        logger: Optional ConversationLogger for debug logging
        script_dir: Optional script directory (for progress/logs)
    
    Returns:
        dict: Result with keys:
            - success: bool
            - filepath: str or None
            - error: str or None
    """
    def _gen_print(msg):
        if logger is not None:
            logger.log_print(msg)
        else:
            print(msg)

    if script_dir is None:
        try:
            script_dir = _default_script_dir()
        except (NameError, AttributeError):
            script_dir = os.getcwd()

    # Test connection before starting generation (skip if resuming)
    if not resume_session_id:
        success, error_msg = test_connection(client, show_message=True, logger=logger)
        if not success:
            err = f"Connection test failed. Cannot proceed with generation. {error_msg}"
            if logger:
                logger.log("Connection test failed: " + str(error_msg))
            return {"success": False, "filepath": None, "error": err}
    
    if not custom_prompt:
        custom_prompt = "Generate workout JSON based on our conversation so far."
    
    # Start total timer
    total_start_time = time.time()
    
    # Generate or use session ID
    if resume_session_id:
        session_id = resume_session_id
        short_sid = session_id[:8] if len(session_id) >= 8 else session_id
        if logger:
            logger.log_section("generation run (resume) session " + short_sid)
        _gen_print(f"Resuming generation from session: {short_sid}...")
    else:
        session_id = str(uuid.uuid4())
        short_sid = session_id[:8] if len(session_id) >= 8 else session_id
        if logger:
            logger.log_section("generation run session " + short_sid)
    
    # Generate conversation hash
    conversation_hash = hash_conversation(messages)
    
    # Initialize placeholder ID manager
    id_manager = PlaceholderIdManager()
    
    # Handle provided equipment if available
    if provided_equipment:
        # Convert UUIDs to placeholders and preserve original UUID mappings
        converted_equipments = []
        for equipment in provided_equipment.get("equipments", []):
            converted_eq = id_manager.convert_equipment_uuids_to_placeholders(equipment, is_accessory=False)
            converted_equipments.append(converted_eq)
            # Also extract any placeholders that might already be in the structure
            id_manager.extract_placeholders_from_json(converted_eq)
        
        converted_accessories = []
        for accessory in provided_equipment.get("accessoryEquipments", []):
            converted_acc = id_manager.convert_equipment_uuids_to_placeholders(accessory, is_accessory=True)
            converted_accessories.append(converted_acc)
            # Also extract any placeholders that might already be in the structure
            id_manager.extract_placeholders_from_json(converted_acc)
        
        # Update provided_equipment with converted versions (now using placeholders)
        provided_equipment = {
            "equipments": converted_equipments,
            "accessoryEquipments": converted_accessories
        }
        
        _gen_print(f"Using provided equipment: {len(provided_equipment.get('equipments', []))} equipment(s), "
              f"{len(provided_equipment.get('accessoryEquipments', []))} accessory(ies)")
        if id_manager._equipment_counter > 0 or id_manager._accessory_counter > 0:
            _gen_print(f"  → Converted {id_manager._equipment_counter} equipment UUID(s) and {id_manager._accessory_counter} accessory UUID(s) to placeholders (original UUIDs preserved)")
    
    # Initialize timing data structure
    timing_data = {
        "total_time_seconds": 0.0,
        "step_times": {},
        "save_times": [],
        "session_start_time": datetime.now().isoformat(),
        "last_step_time": None
    }

    # Collect emitter conversations for persistence in conversation_history.json
    aggregated_emitter_conversations = []

    # Load progress if resuming
    progress_data = None
    previous_session_time = 0.0
    if resume_session_id:
        progress_data = load_generation_progress(resume_session_id, script_dir)
        if not progress_data:
            return {"success": False, "filepath": None, "error": f"Could not load progress for session {resume_session_id[:8]}"}
        
        # Restore ID manager state
        id_manager.restore_state(progress_data.get("id_manager_state", {}))
        
        # Load and restore timing data
        saved_timing = progress_data.get("timing")
        if saved_timing:
            previous_session_time = saved_timing.get("total_time_seconds", 0.0)
            timing_data["total_time_seconds"] = previous_session_time
            # Normalize step_times keys to integers (JSON loads integer keys as strings)
            saved_step_times = saved_timing.get("step_times", {})
            normalized_step_times = {}
            for k, v in saved_step_times.items():
                normalized_key = int(k) if isinstance(k, str) and k.isdigit() else k
                normalized_step_times[normalized_key] = v
            timing_data["step_times"] = normalized_step_times
            timing_data["save_times"] = saved_timing.get("save_times", []).copy()
            timing_data["session_start_time"] = saved_timing.get("session_start_time", datetime.now().isoformat())
            if previous_session_time > 0:
                _gen_print(f"Previous session time: {previous_session_time:.2f}s")
        
        # Warn if conversation changed
        saved_hash = progress_data.get("conversation_hash", "")
        if saved_hash and saved_hash != conversation_hash:
            _gen_print("Warning: Conversation has changed since this generation was started.")
            _gen_print("Resuming anyway, but results may be inconsistent.")
        
        # Use saved custom prompt if available
        if progress_data.get("custom_prompt"):
            custom_prompt = progress_data["custom_prompt"]
        
        # Restore model preference from saved progress (or override via CLI when provided)
        use_reasoner_for_emitting = progress_data.get("use_reasoner_for_emitting", True)
        use_reasoner_for_plan_index = progress_data.get("use_reasoner_for_plan_index", use_reasoner_for_emitting)
        if force_use_reasoner is not None:
            if force_use_reasoner == "hybrid":
                use_reasoner_for_plan_index = True
                use_reasoner_for_emitting = False
                _gen_print("Using CLI model preference override: hybrid-fast (reasoner for plan index, chat for emitting)")
            else:
                override_val = bool(force_use_reasoner)
                use_reasoner_for_plan_index = override_val
                use_reasoner_for_emitting = override_val
                _gen_print(
                    f"Using CLI model preference override: {'reasoner' if override_val else 'chat'} model for plan index and emitting"
                )
        elif "use_reasoner_for_emitting" in progress_data:
            if use_reasoner_for_plan_index == use_reasoner_for_emitting:
                _gen_print(
                    f"Using saved model preference: {'reasoner' if use_reasoner_for_emitting else 'chat'} model for plan index and emitting"
                )
            else:
                _gen_print(
                    "Using saved model preference: hybrid-fast (reasoner for plan index, chat for emitting)"
                )
        
        current_step = progress_data.get("current_step", -1)
        _gen_print(f"Resuming from step {current_step + 1} (last completed: step {current_step})")
    else:
        current_step = -1
        if force_use_reasoner is not None:
            if force_use_reasoner == "hybrid":
                use_reasoner_for_plan_index = True
                use_reasoner_for_emitting = False
                _gen_print("Using CLI model preference: hybrid-fast (reasoner for plan index, chat for emitting)")
            else:
                use_reasoner_for_plan_index = bool(force_use_reasoner)
                use_reasoner_for_emitting = use_reasoner_for_plan_index
                _gen_print(
                    f"Using CLI model preference: {'reasoner' if use_reasoner_for_emitting else 'chat'} model for plan index and emitting"
                )
        else:
            # Prompt user for model preference
            while True:
                user_input = input("Use reasoner model for plan index and emitting? (y/n, default: y): ").strip().lower()
                if not user_input:
                    use_reasoner_for_emitting = True
                    use_reasoner_for_plan_index = True
                    break
                elif user_input in ('y', 'yes'):
                    use_reasoner_for_emitting = True
                    use_reasoner_for_plan_index = True
                    break
                elif user_input in ('n', 'no'):
                    use_reasoner_for_emitting = False
                    use_reasoner_for_plan_index = False
                    break
                else:
                    _gen_print("Please enter 'y' or 'n' (or press Enter for default)")

        if use_reasoner_for_plan_index and use_reasoner_for_emitting:
            _gen_print("Using reasoner model for plan index and emitting (slower but potentially higher quality)")
        elif (not use_reasoner_for_plan_index) and (not use_reasoner_for_emitting):
            _gen_print("Using chat model for plan index and emitting (faster)")
        else:
            _gen_print("Using hybrid-fast model selection (reasoner for plan index, chat for emitting)")
    
    # Track step data for saving progress
    step_data = {}
    
    try:
        # Step 0: Summarize conversation context (once per session)
        if current_step < 0:
            step_start_time = time.time()
            _gen_print("Step 0: Summarizing conversation context...")
            context_summary = summarize_conversation(client, messages, logger)
            if context_summary is None:
                return {"success": False, "filepath": None, "error": "Summarization cancelled"}
            step_time = time.time() - step_start_time
            timing_data["step_times"][0] = step_time
            timing_data["total_time_seconds"] += step_time
            _gen_print(f"✓ Conversation summarized ({step_time:.2f}s)")
            step_data["step_0_context_summary"] = context_summary
            timing_data["last_step_time"] = datetime.now().isoformat()
            _, save_time = save_generation_progress(session_id, 0, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            context_summary = progress_data["step_data"].get("step_0_context_summary")
            if not context_summary:
                return {"success": False, "filepath": None, "error": "Missing context_summary in saved progress"}
            step_data["step_0_context_summary"] = context_summary
            _gen_print("Step 0: Using saved context summary")
        
        # Step 1: Generate PlanIndex (planner stage)
        if current_step < 1:
            step_start_time = time.time()
            _gen_print("Step 1: Generating plan index...")
            plan_index = generate_index(client, context_summary, custom_prompt, use_reasoner_for_plan_index, provided_equipment, logger)
            if plan_index is None:
                return {"success": False, "filepath": None, "error": "Plan index generation cancelled"}
            try:
                validate_plan_index_contract(plan_index)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            # Canonicalize provided equipment fields in plan_index by ID.
            # The model sometimes returns equivalent labels (e.g., "Cable machine")
            # for existing provided IDs, which should not fail immutable checks.
            if provided_equipment:
                provided_eq_by_id = {
                    eq.get("id"): eq
                    for eq in provided_equipment.get("equipments", [])
                    if isinstance(eq, dict) and eq.get("id")
                }
                provided_acc_by_id = {
                    acc.get("id"): acc
                    for acc in provided_equipment.get("accessoryEquipments", [])
                    if isinstance(acc, dict) and acc.get("id")
                }
                for eq in plan_index.get("equipments", []):
                    eq_id = eq.get("id")
                    if eq_id in provided_eq_by_id:
                        provided_eq = provided_eq_by_id[eq_id]
                        eq["type"] = provided_eq.get("type")
                        eq["name"] = provided_eq.get("name")
                for acc in plan_index.get("accessoryEquipments", []):
                    acc_id = acc.get("id")
                    if acc_id in provided_acc_by_id:
                        provided_acc = provided_acc_by_id[acc_id]
                        acc["type"] = provided_acc.get("type")
                        acc["name"] = provided_acc.get("name")
            # Collapse duplicate accessories: if plan_index lists same (type, name) as provided, use provided ID and remove duplicate
            if provided_equipment:
                step_data["step_1_accessory_duplicate_map"] = deduplicate_plan_index_accessories(plan_index, provided_equipment)
            # Validate that provided equipment was not modified
            if provided_equipment:
                is_valid, error_msg = validate_equipment_immutability(
                    provided_equipment,
                    {"equipments": plan_index.get("equipments", []), "accessoryEquipments": plan_index.get("accessoryEquipments", [])}
                )
                if not is_valid:
                    return {"success": False, "filepath": None, "error": f"Equipment validation failed: {error_msg}"}
                
                # Identify new equipment IDs (don't merge minimal plan_index entries yet - they'll be emitted in Step 2)
                provided_eq_ids = {eq.get("id") for eq in provided_equipment.get("equipments", [])}
                provided_acc_ids = {acc.get("id") for acc in provided_equipment.get("accessoryEquipments", [])}
                new_equipment_ids = [eq.get("id") for eq in plan_index.get("equipments", []) if eq.get("id") and eq.get("id") not in provided_eq_ids]
                new_accessory_ids = [acc.get("id") for acc in plan_index.get("accessoryEquipments", []) if acc.get("id") and acc.get("id") not in provided_acc_ids]
                
                if new_equipment_ids or new_accessory_ids:
                    _gen_print(f"  → Detected {len(new_equipment_ids)} new equipment item(s), {len(new_accessory_ids)} new accessory(ies) to be created")
                    # Register new equipment IDs in id_manager
                    for eq_id in new_equipment_ids:
                        id_manager.extract_placeholders_from_json({"id": eq_id})
                    for acc_id in new_accessory_ids:
                        id_manager.extract_placeholders_from_json({"id": acc_id})
            
            step_time = time.time() - step_start_time
            timing_data["step_times"][1] = step_time
            timing_data["total_time_seconds"] += step_time
            _gen_print(f"✓ Generated plan index: {len(plan_index.get('equipments', []))} equipment(s), "
                  f"{len(plan_index.get('accessoryEquipments', []))} accessory(ies), "
                  f"{len(plan_index.get('exercises', []))} exercise(s), "
                  f"{len(plan_index.get('workouts', []))} workout(s) ({step_time:.2f}s)")
            step_data["step_1_plan_index"] = plan_index
            step_data["step_1_provided_equipment"] = provided_equipment  # Save original provided equipment
            timing_data["last_step_time"] = datetime.now().isoformat()
            _, save_time = save_generation_progress(session_id, 1, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            plan_index = progress_data["step_data"].get("step_1_plan_index")
            if not plan_index:
                return {"success": False, "filepath": None, "error": "Missing plan_index in saved progress"}
            try:
                validate_plan_index_contract(plan_index)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            step_data["step_1_plan_index"] = plan_index
            # Restore merged equipment if available
            if "step_1_provided_equipment" in progress_data["step_data"]:
                provided_equipment = progress_data["step_data"]["step_1_provided_equipment"]
            _gen_print("Step 1: Using saved plan index")
        
        # Step 2: Emit equipment items (chunked emitters) - parallelized
        if current_step < 2:
            step_start_time = time.time()
            if provided_equipment:
                # Use provided equipment directly, but also check for new equipment to emit
                _gen_print("Step 2: Loading provided equipment and emitting new equipment...")
                
                # Convert provided equipment to EquipmentItem/AccessoryItem format
                equipment_items = {}
                for eq in provided_equipment.get("equipments", []):
                    eq_id = eq.get("id")
                    if eq_id:
                        equipment_items[eq_id] = EquipmentItem(eq)
                
                accessory_items = {}
                for acc in provided_equipment.get("accessoryEquipments", []):
                    acc_id = acc.get("id")
                    if acc_id:
                        accessory_items[acc_id] = acc  # Accessory items are just dicts
                
                # Identify new equipment in plan_index that needs to be emitted
                provided_eq_ids = {eq.get("id") for eq in provided_equipment.get("equipments", [])}
                provided_acc_ids = {acc.get("id") for acc in provided_equipment.get("accessoryEquipments", [])}
                
                new_equipment_entries = [eq for eq in plan_index.get("equipments", []) if eq.get("id") and eq.get("id") not in provided_eq_ids]
                new_accessory_entries = [acc for acc in plan_index.get("accessoryEquipments", []) if acc.get("id") and acc.get("id") not in provided_acc_ids]
                
                # Emit new equipment if any
                if new_equipment_entries:
                    _gen_print(f"  → Emitting {len(new_equipment_entries)} new equipment item(s)...")
                    new_equipment_items_list = [
                        (eq.get("id"), {"client": client, "context_summary": context_summary, "plan_index": plan_index, "use_reasoner": use_reasoner_for_emitting, "logger": logger})
                        for eq in new_equipment_entries
                    ]
                    new_equipment_results, new_equipment_convs = parallel_emit_items(
                        new_equipment_items_list,
                        emit_equipment_item,
                        "Step 2: Emitting new equipment",
                        logger=logger
                    )
                    aggregated_emitter_conversations.extend(new_equipment_convs)
                    # Add new equipment to equipment_items
                    for eq_id, eq_item in new_equipment_results.items():
                        if eq_item is not None:
                            equipment_items[eq_id] = eq_item
                
                # Emit new accessories if any
                if new_accessory_entries:
                    _gen_print(f"  → Emitting {len(new_accessory_entries)} new accessory(ies)...")
                    new_accessory_items_list = [
                        (acc.get("id"), {"client": client, "context_summary": context_summary, "plan_index": plan_index, "use_reasoner": use_reasoner_for_emitting, "logger": logger})
                        for acc in new_accessory_entries
                    ]
                    new_accessory_results, new_accessory_convs = parallel_emit_items(
                        new_accessory_items_list,
                        emit_accessory_equipment_item,
                        "Step 2: Emitting new accessory equipment",
                        logger=logger
                    )
                    aggregated_emitter_conversations.extend(new_accessory_convs)
                    # Add new accessories to accessory_items
                    for acc_id, acc_item in new_accessory_results.items():
                        if acc_item is not None:
                            accessory_items[acc_id] = acc_item
                
                # Update provided_equipment with newly emitted equipment
                if new_equipment_entries or new_accessory_entries:
                    # Rebuild provided_equipment to include new items
                    updated_equipments = list(provided_equipment.get("equipments", []))
                    updated_accessories = list(provided_equipment.get("accessoryEquipments", []))
                    
                    for eq_id, eq_item in equipment_items.items():
                        if eq_id not in provided_eq_ids and isinstance(eq_item, dict):
                            updated_equipments.append(eq_item)
                    
                    for acc_id, acc_item in accessory_items.items():
                        if acc_id not in provided_acc_ids and isinstance(acc_item, dict):
                            updated_accessories.append(acc_item)
                    
                    provided_equipment = {
                        "equipments": updated_equipments,
                        "accessoryEquipments": updated_accessories
                    }
                
                step_time = time.time() - step_start_time
                timing_data["step_times"][2] = step_time
                timing_data["total_time_seconds"] += step_time
                _gen_print(f"✓ Loaded {len(equipment_items)} equipment item(s), {len(accessory_items)} accessory(ies) ({step_time:.2f}s)")
                step_data["step_2_equipment_items"] = equipment_items
                step_data["step_2_accessory_items"] = accessory_items
                step_data["step_2_provided_equipment"] = provided_equipment  # Save for resume
                timing_data["last_step_time"] = datetime.now().isoformat()
                _, save_time = save_generation_progress(session_id, 2, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
            else:
                # Normal emission path
                _gen_print("Step 2: Emitting equipment items...")
                equipment_entries = [eq for eq in plan_index.get("equipments", []) if eq.get("id")]
                equipment_items_list = [
                    (eq.get("id"), {"client": client, "context_summary": context_summary, "plan_index": plan_index, "use_reasoner": use_reasoner_for_emitting, "logger": logger})
                    for eq in equipment_entries
                ]
                equipment_results, equipment_convs = parallel_emit_items(
                    equipment_items_list,
                    emit_equipment_item,
                    "Step 2: Emitting equipment",
                    logger=logger
                )
                aggregated_emitter_conversations.extend(equipment_convs)
                # Filter out None results (cancelled/failed items)
                equipment_items = {k: v for k, v in equipment_results.items() if v is not None}
                
                # Emit accessory equipment items
                accessory_entries = [acc for acc in plan_index.get("accessoryEquipments", []) if acc.get("id")]
                accessory_items_list = [
                    (acc.get("id"), {"client": client, "context_summary": context_summary, "plan_index": plan_index, "use_reasoner": use_reasoner_for_emitting, "logger": logger})
                    for acc in accessory_entries
                ]
                accessory_results, accessory_convs = parallel_emit_items(
                    accessory_items_list,
                    emit_accessory_equipment_item,
                    "Step 2: Emitting accessory equipment",
                    logger=logger
                )
                aggregated_emitter_conversations.extend(accessory_convs)
                # Filter out None results (cancelled/failed items)
                accessory_items = {k: v for k, v in accessory_results.items() if v is not None}
                
                step_time = time.time() - step_start_time
                timing_data["step_times"][2] = step_time
                timing_data["total_time_seconds"] += step_time
                _gen_print(f"✓ Emitted {len(equipment_items)} equipment item(s), {len(accessory_items)} accessory(ies) ({step_time:.2f}s)")
                step_data["step_2_equipment_items"] = equipment_items
                step_data["step_2_accessory_items"] = accessory_items
                
                # Extract generated equipment and treat it as provided_equipment for consistent formatting/enforcement
                # Convert equipment_items dict (id -> EquipmentItem) to list format
                generated_equipment_list = [eq for eq in equipment_items.values() if isinstance(eq, dict)]
                generated_accessory_list = [acc for acc in accessory_items.values() if isinstance(acc, dict)]
                provided_equipment = {
                    "equipments": generated_equipment_list,
                    "accessoryEquipments": generated_accessory_list
                }
                step_data["step_2_provided_equipment"] = provided_equipment  # Save for resume and subsequent steps
                
                timing_data["last_step_time"] = datetime.now().isoformat()
                _, save_time = save_generation_progress(session_id, 2, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            equipment_items = progress_data["step_data"].get("step_2_equipment_items", {})
            accessory_items = progress_data["step_data"].get("step_2_accessory_items", {})
            # Restore provided_equipment if it was saved (either from file or generated)
            if "step_2_provided_equipment" in progress_data["step_data"]:
                provided_equipment = progress_data["step_data"]["step_2_provided_equipment"]
            elif not provided_equipment and equipment_items:
                # If no provided_equipment was saved but we have equipment_items, extract them
                # This handles cases where old progress files don't have provided_equipment
                generated_equipment_list = [eq for eq in equipment_items.values() if isinstance(eq, dict)]
                generated_accessory_list = [acc for acc in accessory_items.values() if isinstance(acc, dict)]
                provided_equipment = {
                    "equipments": generated_equipment_list,
                    "accessoryEquipments": generated_accessory_list
                }
            if not equipment_items:
                return {"success": False, "filepath": None, "error": "Missing equipment_items in saved progress"}
            step_data["step_2_equipment_items"] = equipment_items
            step_data["step_2_accessory_items"] = accessory_items
            if provided_equipment:
                step_data["step_2_provided_equipment"] = provided_equipment
            _gen_print(f"Step 2: Using saved equipment items ({len(equipment_items)} items, {len(accessory_items)} accessories)")
        
        # Step 3: Emit exercise definitions (chunked emitters) - parallelized
        if current_step < 3:
            step_start_time = time.time()
            _gen_print("Step 3: Emitting exercise definitions...")
            exercise_entries = [ex for ex in plan_index.get("exercises", []) if ex.get("id")]
            # Prepare equipment subsets for each exercise
            exercise_items_list = []
            for ex_entry in exercise_entries:
                ex_id = ex_entry.get("id")
                # Get relevant equipment subset for this exercise
                equipment_id = ex_entry.get("equipmentId")
                equipment_subset = []
                if equipment_id and equipment_id in equipment_items:
                    equipment_subset = [equipment_items[equipment_id]]
                
                # Get relevant accessory equipment for this exercise
                required_accessory_ids = ex_entry.get("requiredAccessoryEquipmentIds", [])
                accessory_subset = []
                if accessory_items:
                    for acc_id in required_accessory_ids:
                        if acc_id in accessory_items:
                            accessory_subset.append(accessory_items[acc_id])
                
                exercise_items_list.append((
                    ex_id,
                    {
                        "client": client,
                        "context_summary": context_summary,
                        "plan_index": plan_index,
                        "equipment_subset": equipment_subset,
                        "accessory_subset": accessory_subset if accessory_subset else None,
                        "use_reasoner": use_reasoner_for_emitting,
                        "provided_equipment": provided_equipment,
                        "logger": logger
                    }
                ))
            try:
                exercise_results, exercise_convs = parallel_emit_items(
                    exercise_items_list,
                    emit_exercise_definition,
                    "Step 3: Emitting exercises",
                    logger=logger,
                    fail_fast=True,
                )
            except Exception as e:
                return {"success": False, "filepath": None, "error": str(e)}
            aggregated_emitter_conversations.extend(exercise_convs)
            # Filter out None results (cancelled/failed items)
            exercise_definitions = {k: v for k, v in exercise_results.items() if v is not None}

            # LLM-only retry pass for failed/missing exercises (no deterministic auto-fix).
            expected_exercise_ids = [ex.get("id") for ex in exercise_entries if ex.get("id")]
            missing_exercise_ids = [ex_id for ex_id in expected_exercise_ids if ex_id not in exercise_definitions]
            if missing_exercise_ids:
                _gen_print(f"  → Retrying {len(missing_exercise_ids)} failed exercise(s) with LLM...")
                exercise_entry_by_id = {ex.get("id"): ex for ex in exercise_entries if ex.get("id")}
                for ex_id in missing_exercise_ids:
                    ex_entry = exercise_entry_by_id.get(ex_id, {})
                    equipment_id = ex_entry.get("equipmentId")
                    equipment_subset = [equipment_items[equipment_id]] if equipment_id and equipment_id in equipment_items else []
                    required_accessory_ids = ex_entry.get("requiredAccessoryEquipmentIds", [])
                    accessory_subset = [accessory_items[acc_id] for acc_id in required_accessory_ids if acc_id in accessory_items]
                    try:
                        retry_result, retry_conv = emit_exercise_definition(
                            ex_id,
                            client=client,
                            context_summary=context_summary,
                            plan_index=plan_index,
                            equipment_subset=equipment_subset,
                            accessory_subset=accessory_subset if accessory_subset else None,
                            use_reasoner=use_reasoner_for_emitting,
                            provided_equipment=provided_equipment,
                            logger=logger,
                        )
                        if retry_conv is not None:
                            aggregated_emitter_conversations.append(retry_conv)
                        if retry_result is not None:
                            exercise_definitions[ex_id] = retry_result
                    except Exception:
                        # Keep missing; contract validation below will report exact failures.
                        pass
            contract_retry_budget = 2
            contract_retry_count = 0
            while True:
                try:
                    validate_exercise_definitions_contract(plan_index, exercise_definitions)
                    break
                except ContractValidationError as e:
                    if contract_retry_count >= contract_retry_budget:
                        return {"success": False, "filepath": None, "error": str(e)}

                    err_text = str(e)
                    retry_ids = set()
                    # Retry missing definitions and mismatch errors that identify an EXERCISE_X id.
                    for match in re.finditer(r"Exercise '([^']+)'", err_text):
                        ex_id = match.group(1)
                        if isinstance(ex_id, str) and ex_id.startswith("EXERCISE_"):
                            retry_ids.add(ex_id)
                    for match in re.finditer(r"for '([^']+)'", err_text):
                        ex_id = match.group(1)
                        if isinstance(ex_id, str) and ex_id.startswith("EXERCISE_"):
                            retry_ids.add(ex_id)

                    if not retry_ids:
                        return {"success": False, "filepath": None, "error": err_text}

                    contract_retry_count += 1
                    _gen_print(
                        f"  → Contract retry {contract_retry_count}/{contract_retry_budget}: "
                        f"re-emitting {len(retry_ids)} exercise(s) due to Step 3 mismatches..."
                    )
                    exercise_entry_by_id = {ex.get("id"): ex for ex in exercise_entries if ex.get("id")}
                    for ex_id in sorted(retry_ids):
                        ex_entry = exercise_entry_by_id.get(ex_id, {})
                        per_ex_error_lines = [
                            line.strip()
                            for line in err_text.splitlines()
                            if ex_id in line
                        ]
                        per_ex_error_context = "\n".join(per_ex_error_lines) if per_ex_error_lines else err_text
                        equipment_id = ex_entry.get("equipmentId")
                        equipment_subset = [equipment_items[equipment_id]] if equipment_id and equipment_id in equipment_items else []
                        required_accessory_ids = ex_entry.get("requiredAccessoryEquipmentIds", [])
                        accessory_subset = [accessory_items[acc_id] for acc_id in required_accessory_ids if acc_id in accessory_items]
                        try:
                            retry_result, retry_conv = emit_exercise_definition(
                                ex_id,
                                client=client,
                                context_summary=context_summary,
                                plan_index=plan_index,
                                equipment_subset=equipment_subset,
                                accessory_subset=accessory_subset if accessory_subset else None,
                                use_reasoner=use_reasoner_for_emitting,
                                provided_equipment=provided_equipment,
                                logger=logger,
                                contract_error_context=per_ex_error_context,
                            )
                            if retry_conv is not None:
                                aggregated_emitter_conversations.append(retry_conv)
                            if retry_result is not None:
                                exercise_definitions[ex_id] = retry_result
                        except Exception:
                            # Keep previous value; next contract validation reports unresolved issues.
                            pass
            step_time = time.time() - step_start_time
            timing_data["step_times"][3] = step_time
            timing_data["total_time_seconds"] += step_time
            _gen_print(f"✓ Emitted {len(exercise_definitions)} exercise definition(s) ({step_time:.2f}s)")
            step_data["step_3_exercise_definitions"] = exercise_definitions
            timing_data["last_step_time"] = datetime.now().isoformat()
            _, save_time = save_generation_progress(session_id, 3, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            exercise_definitions = progress_data["step_data"].get("step_3_exercise_definitions", {})
            accessory_items = progress_data["step_data"].get("step_2_accessory_items", {})
            if not exercise_definitions:
                return {"success": False, "filepath": None, "error": "Missing exercise_definitions in saved progress"}
            try:
                validate_exercise_definitions_contract(plan_index, exercise_definitions)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            step_data["step_3_exercise_definitions"] = exercise_definitions
            _gen_print(f"Step 3: Using saved exercise definitions ({len(exercise_definitions)} exercises)")
        
        # Step 4: Emit workout structures (chunked emitters) - parallelized
        if current_step < 4:
            step_start_time = time.time()
            _gen_print("Step 4: Emitting workout structures...")
            workout_entries = [wo for wo in plan_index.get("workouts", []) if wo.get("id")]
            workout_items_list = [
                (wo.get("id"), {
                    "client": client,
                    "context_summary": context_summary,
                    "plan_index": plan_index,
                    "exercise_index": exercise_definitions,
                    "use_reasoner": use_reasoner_for_emitting,
                    "logger": logger
                })
                for wo in workout_entries
            ]
            workout_results, workout_convs = parallel_emit_items(
                workout_items_list,
                emit_workout_structure,
                "Step 4: Emitting workouts",
                logger=logger
            )
            aggregated_emitter_conversations.extend(workout_convs)
            # Filter out None results (cancelled/failed items)
            workout_structures = {k: v for k, v in workout_results.items() if v is not None}
            try:
                validate_workout_structures_contract(plan_index, workout_structures, exercise_definitions)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            step_time = time.time() - step_start_time
            timing_data["step_times"][4] = step_time
            timing_data["total_time_seconds"] += step_time
            _gen_print(f"✓ Emitted {len(workout_structures)} workout structure(s) ({step_time:.2f}s)")
            step_data["step_4_workout_structures"] = workout_structures
            timing_data["last_step_time"] = datetime.now().isoformat()
            _, save_time = save_generation_progress(session_id, 4, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            workout_structures = progress_data["step_data"].get("step_4_workout_structures", {})
            if not workout_structures:
                return {"success": False, "filepath": None, "error": "Missing workout_structures in saved progress"}
            try:
                validate_workout_structures_contract(plan_index, workout_structures, exercise_definitions)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            step_data["step_4_workout_structures"] = workout_structures
            _gen_print(f"Step 4: Using saved workout structures ({len(workout_structures)} workouts)")
        
        # Step 5: Assemble placeholder-based WorkoutStore
        if current_step < 5:
            step_start_time = time.time()
            _gen_print("Step 5: Assembling placeholder-based WorkoutStore...")
            user_data = {
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "progressionPercentageAmount": 2.5,
                "polarDeviceId": None
            }
            placeholder_workout_store = assemble_placeholder_workout_store(
                equipment_items, accessory_items, exercise_definitions, workout_structures, plan_index, user_data
            )
            placeholder_workout_store = sync_exercises_from_definitions(placeholder_workout_store, exercise_definitions)
            # Rewrite any duplicate accessory IDs to provided IDs in emitted exercises
            apply_accessory_id_rewrite(placeholder_workout_store, step_data.get("step_1_accessory_duplicate_map", {}))
            step_time = time.time() - step_start_time
            timing_data["step_times"][5] = step_time
            timing_data["total_time_seconds"] += step_time
            _gen_print(f"✓ Assembled placeholder WorkoutStore ({step_time:.2f}s)")
            step_data["step_5_placeholder_workout_store"] = placeholder_workout_store
            timing_data["last_step_time"] = datetime.now().isoformat()
            _, save_time = save_generation_progress(session_id, 5, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            placeholder_workout_store = progress_data["step_data"].get("step_5_placeholder_workout_store")
            if not placeholder_workout_store:
                return {"success": False, "filepath": None, "error": "Missing placeholder_workout_store in saved progress"}
            step_data["step_5_placeholder_workout_store"] = placeholder_workout_store
            _gen_print("Step 5: Using saved placeholder WorkoutStore")
        
        # Step 6: Validate and repair placeholder JSON
        if current_step < 6:
            step_start_time = time.time()
            _gen_print("Step 6: Validating and repairing placeholder JSON...")
            try:
                # Check if we're resuming step 6 (current_step == 5 means step 5 completed, step 6 may have partial progress)
                resume_best_json = None
                resume_best_error_count = None
                
                # Check for resume state from previous step 6 attempts
                if current_step == 5:
                    resume_best_json = progress_data["step_data"].get("step_6_best_json")
                    resume_best_error_count = progress_data["step_data"].get("step_6_best_error_count")
                    if resume_best_json is not None:
                        _gen_print(f"  Resuming step 6 with best saved state (error count: {resume_best_error_count if resume_best_error_count is not None else 'N/A'})")
                
                validated_placeholder_store = validate_and_repair_placeholder_json(
                    client, context_summary, placeholder_workout_store, max_attempts=5,
                    session_id=session_id, step_data=step_data, custom_prompt=custom_prompt,
                    conversation_hash=conversation_hash, id_manager=id_manager, script_dir=script_dir,
                    resume_best_json=resume_best_json, resume_best_error_count=resume_best_error_count,
                    timing_data=timing_data, use_reasoner_for_emitting=use_reasoner_for_emitting,
                    logger=logger
                )
                validated_placeholder_store = sync_exercises_from_definitions(validated_placeholder_store, exercise_definitions)
                step_time = time.time() - step_start_time
                timing_data["step_times"][6] = step_time
                timing_data["total_time_seconds"] += step_time
                _gen_print(f"✓ Placeholder validation passed ({step_time:.2f}s)")
                step_data["step_6_validated_placeholder_store"] = validated_placeholder_store
                timing_data["last_step_time"] = datetime.now().isoformat()
                _, save_time = save_generation_progress(session_id, 6, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
            except Exception as validation_err:
                step_time = time.time() - step_start_time
                timing_data["step_times"][6] = step_time
                timing_data["total_time_seconds"] += step_time
                _gen_print(f"Validation/repair failed: {validation_err}")
                # Save error for inspection
                error_filepath = save_validation_error(validation_err, placeholder_workout_store, script_dir)
                if error_filepath:
                    _gen_print(f"Error details saved to: {error_filepath}")
                return {"success": False, "filepath": None, "error": str(validation_err)}
        else:
            validated_placeholder_store = progress_data["step_data"].get("step_6_validated_placeholder_store")
            if not validated_placeholder_store:
                return {"success": False, "filepath": None, "error": "Missing validated_placeholder_store in saved progress"}
            validated_placeholder_store = sync_exercises_from_definitions(validated_placeholder_store, exercise_definitions)
            step_data["step_6_validated_placeholder_store"] = validated_placeholder_store
            _gen_print("Step 6: Using saved validated placeholder store")
        
        # Step 7: Convert placeholders to UUIDs (final step)
        if current_step < 7:
            step_start_time = time.time()
            _gen_print("Step 7: Converting placeholders to UUIDs...")
            data = convert_placeholders_to_uuids(validated_placeholder_store, id_manager, validate_final=True, logger=logger)
            try:
                validate_uuid_conversion_parity(validated_placeholder_store, data)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            step_time = time.time() - step_start_time
            timing_data["step_times"][7] = step_time
            timing_data["total_time_seconds"] += step_time
            _gen_print(f"✓ Converted to UUID-based WorkoutStore ({step_time:.2f}s)")
            step_data["step_7_final_workout_store"] = data
            timing_data["last_step_time"] = datetime.now().isoformat()
            _, save_time = save_generation_progress(session_id, 7, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
        else:
            data = progress_data["step_data"].get("step_7_final_workout_store")
            if not data:
                return {"success": False, "filepath": None, "error": "Missing final_workout_store in saved progress"}
            try:
                validate_uuid_conversion_parity(validated_placeholder_store, data)
            except ContractValidationError as e:
                return {"success": False, "filepath": None, "error": str(e)}
            _gen_print("Step 7: Using saved final workout store")
        
        # Update final total time (including save times)
        save_times_total = sum(timing_data.get("save_times", []))
        step_times_total = sum(timing_data.get("step_times", {}).values())
        # Total time is sum of step times and save times
        timing_data["total_time_seconds"] = step_times_total + save_times_total
        
        # Ensure requiresLoadCalibration is set correctly for all exercises
        ensure_requiresLoadCalibration(data)
        
        # Save workout to file
        filepath = save_workout_to_file(data, script_dir)
        if filepath is None:
            _gen_print("Warning: Failed to save workout to file, but generation was successful.")
            _gen_print("\nGenerated Workout JSON:")
            _gen_print("=" * 70)
            _gen_print(json.dumps(data, indent=2))
            _gen_print("=" * 70)
        else:
            # Display summary instead of full JSON
            display_workout_summary(data, filepath, logger=logger)
        
        # Display timing summary
        display_timing_summary(timing_data, is_resume=(resume_session_id is not None), logger=logger)
        
        # Delete progress file on successful completion
        if delete_progress_file(session_id, script_dir):
            _gen_print("✓ Progress file cleaned up")
        
        return {
            "success": True,
            "filepath": filepath,
            "error": None,
            "emitter_conversations": aggregated_emitter_conversations,
        }
            
    except KeyboardInterrupt:
        return {"success": False, "filepath": None, "error": "Cancelled by user"}
    except ValueError as e:
        return {"success": False, "filepath": None, "error": f"Generation error: {e}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "filepath": None, "error": f"Error: {e}"}

