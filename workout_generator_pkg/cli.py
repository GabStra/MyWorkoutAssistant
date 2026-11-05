import copy
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime

from .domain_ops import _materialize_exercise_definition, build_workout_structure
from .logging_ui import ConversationLogger, PrefixLogger, LoadingIndicator, ParallelLoadingIndicator
from .plan_contract import validate_single_exercise_definition_contract

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)


def _default_script_dir():
    """Return project root path for filesystem outputs."""
    return PROJECT_ROOT
class PlaceholderIdManager:
    """Manages placeholder IDs and their mapping to real UUIDs."""

    # UUID pattern: matches standard UUID format (8-4-4-4-12 hex digits)
    UUID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

    def __init__(self):
        self.placeholder_to_uuid = {}
        self.uuid_to_placeholder = {}
        self._equipment_counter = 0
        self._accessory_counter = 0

    def _is_uuid(self, value):
        """Check if a string value is a valid UUID."""
        if not isinstance(value, str):
            return False
        return bool(self.UUID_PATTERN.match(value))

    def register_placeholder(self, placeholder_id):
        """Register a placeholder ID and generate a UUID for it if not already registered."""
        if placeholder_id not in self.placeholder_to_uuid:
            new_uuid = str(uuid.uuid4())
            self.placeholder_to_uuid[placeholder_id] = new_uuid
            self.uuid_to_placeholder[new_uuid] = placeholder_id
        return self.placeholder_to_uuid[placeholder_id]

    def register_uuid_mapping(self, original_uuid, placeholder_id):
        """
        Register a mapping from an original UUID (from equipment file) to a placeholder ID.
        This preserves the original UUID so it can be restored later.

        Args:
            original_uuid: The original UUID string from the equipment file
            placeholder_id: The placeholder ID (e.g., "EQUIPMENT_0") to map it to
        """
        if not self._is_uuid(original_uuid):
            raise ValueError(f"Invalid UUID format: {original_uuid}")
        if not self._is_placeholder(placeholder_id):
            raise ValueError(f"Invalid placeholder format: {placeholder_id}")

        # Store both directions of the mapping
        self.placeholder_to_uuid[placeholder_id] = original_uuid
        self.uuid_to_placeholder[original_uuid] = placeholder_id

    def convert_uuid_to_placeholder(self, original_uuid, prefix="EQUIPMENT"):
        """
        Convert an original UUID to a placeholder ID and register the mapping.

        Args:
            original_uuid: The original UUID string from the equipment file
            prefix: The prefix for the placeholder (EQUIPMENT or ACCESSORY)

        Returns:
            str: The generated placeholder ID (e.g., "EQUIPMENT_0")
        """
        if not self._is_uuid(original_uuid):
            return original_uuid  # Not a UUID, return as-is

        # Check if we already have a mapping for this UUID
        if original_uuid in self.uuid_to_placeholder:
            return self.uuid_to_placeholder[original_uuid]

        # Generate a new placeholder ID
        if prefix == "EQUIPMENT":
            placeholder_id = f"EQUIPMENT_{self._equipment_counter}"
            self._equipment_counter += 1
        elif prefix == "ACCESSORY":
            placeholder_id = f"ACCESSORY_{self._accessory_counter}"
            self._accessory_counter += 1
        else:
            raise ValueError(f"Invalid prefix: {prefix}. Must be EQUIPMENT or ACCESSORY")

        # Register the mapping
        self.register_uuid_mapping(original_uuid, placeholder_id)
        return placeholder_id

    def get_uuid(self, placeholder_id):
        """
        Get the UUID for a placeholder ID.
        If the placeholder was mapped from an original UUID, returns that original UUID.
        Otherwise, generates a new UUID.
        """
        if placeholder_id in self.placeholder_to_uuid:
            return self.placeholder_to_uuid[placeholder_id]
        return self.register_placeholder(placeholder_id)

    def replace_placeholders(self, obj):
        """Recursively replace placeholder IDs with UUIDs in a JSON structure."""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                # Replace placeholder IDs in 'id' fields and reference fields
                if key in ('id', 'equipmentId', 'previousVersionId', 'nextVersionId', 'globalId'):
                    if isinstance(value, str) and self._is_placeholder(value):
                        result[key] = self.get_uuid(value)
                    else:
                        result[key] = self.replace_placeholders(value)
                elif key == 'requiredAccessoryEquipmentIds':
                    # Handle array of accessory equipment IDs - normalize None to empty array
                    if value is None:
                        result[key] = []
                    elif isinstance(value, list):
                        result[key] = [
                            self.get_uuid(item) if isinstance(item, str) and self._is_placeholder(item) else self.replace_placeholders(item)
                            for item in value
                        ]
                    else:
                        # Fallback: convert to empty array if it's not a list
                        result[key] = []
                elif key == 'restSecondsByExercise':
                    if isinstance(value, dict):
                        converted_map = {}
                        for map_key, map_value in value.items():
                            converted_key = self.get_uuid(map_key) if isinstance(map_key, str) and self._is_placeholder(map_key) else map_key
                            converted_map[converted_key] = self.replace_placeholders(map_value)
                        result[key] = converted_map
                    else:
                        result[key] = {}
                else:
                    result[key] = self.replace_placeholders(value)
            return result
        elif isinstance(obj, list):
            return [self.replace_placeholders(item) for item in obj]
        else:
            return obj

    def _is_placeholder(self, value):
        """Check if a string value is a placeholder ID."""
        if not isinstance(value, str):
            return False
        prefixes = ['EQUIPMENT_', 'ACCESSORY_', 'EXERCISE_', 'COMPONENT_', 'SET_', 'WORKOUT_', 'REST_']
        return any(value.startswith(prefix) for prefix in prefixes)

    def extract_placeholders_from_json(self, obj):
        """Extract all placeholder IDs from a JSON structure and register them."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ('id', 'equipmentId', 'previousVersionId', 'nextVersionId', 'globalId'):
                    if isinstance(value, str) and self._is_placeholder(value):
                        # Only register if not already mapped (don't overwrite provided equipment UUIDs)
                        if value not in self.placeholder_to_uuid:
                            self.register_placeholder(value)
                elif key == 'requiredAccessoryEquipmentIds' and isinstance(value, list):
                    # Extract placeholder IDs from accessory equipment ID array
                    for item in value:
                        if isinstance(item, str) and self._is_placeholder(item):
                            # Only register if not already mapped (don't overwrite provided equipment UUIDs)
                            if item not in self.placeholder_to_uuid:
                                self.register_placeholder(item)
                self.extract_placeholders_from_json(value)
        elif isinstance(obj, list):
            for item in obj:
                self.extract_placeholders_from_json(item)

    def convert_equipment_uuids_to_placeholders(self, equipment_dict, is_accessory=False):
        """
        Convert UUIDs in an equipment dictionary to placeholders, preserving the original UUIDs.
        This modifies the dictionary in-place.

        Args:
            equipment_dict: Dictionary containing equipment data (may have UUID 'id' field)
            is_accessory: If True, use ACCESSORY prefix, otherwise EQUIPMENT prefix

        Returns:
            dict: The modified equipment dictionary with placeholder IDs
        """
        if not isinstance(equipment_dict, dict):
            return equipment_dict

        result = equipment_dict.copy()
        prefix = "ACCESSORY" if is_accessory else "EQUIPMENT"

        # Convert 'id' field if it's a UUID
        if 'id' in result and isinstance(result['id'], str):
            original_id = result['id']
            if self._is_uuid(original_id):
                placeholder_id = self.convert_uuid_to_placeholder(original_id, prefix)
                result['id'] = placeholder_id

        # Convert 'equipmentId' references if they're UUIDs
        if 'equipmentId' in result and isinstance(result['equipmentId'], str):
            original_id = result['equipmentId']
            if self._is_uuid(original_id):
                # Check if it's already mapped (might be an equipment or accessory)
                if original_id in self.uuid_to_placeholder:
                    result['equipmentId'] = self.uuid_to_placeholder[original_id]
                else:
                    # Default to EQUIPMENT prefix if not found
                    result['equipmentId'] = self.convert_uuid_to_placeholder(original_id, "EQUIPMENT")

        # Convert 'requiredAccessoryEquipmentIds' array if present
        if 'requiredAccessoryEquipmentIds' in result and isinstance(result['requiredAccessoryEquipmentIds'], list):
            converted_ids = []
            for item_id in result['requiredAccessoryEquipmentIds']:
                if isinstance(item_id, str):
                    if self._is_uuid(item_id):
                        # Check if already mapped
                        if item_id in self.uuid_to_placeholder:
                            converted_ids.append(self.uuid_to_placeholder[item_id])
                        else:
                            converted_ids.append(self.convert_uuid_to_placeholder(item_id, "ACCESSORY"))
                    elif self._is_placeholder(item_id):
                        # Already a placeholder, just register it
                        if item_id not in self.placeholder_to_uuid:
                            self.register_placeholder(item_id)
                        converted_ids.append(item_id)
                    else:
                        converted_ids.append(item_id)
                else:
                    converted_ids.append(item_id)
            result['requiredAccessoryEquipmentIds'] = converted_ids

        return result

    def get_state(self):
        """Get the current state of the ID manager for serialization."""
        return {
            "placeholder_to_uuid": self.placeholder_to_uuid.copy(),
            "uuid_to_placeholder": self.uuid_to_placeholder.copy()
        }

    def restore_state(self, state):
        """Restore the ID manager state from serialized data."""
        if state:
            self.placeholder_to_uuid = state.get("placeholder_to_uuid", {}).copy()
            self.uuid_to_placeholder = state.get("uuid_to_placeholder", {}).copy()
            # Restore counters by finding the highest index in existing placeholders
            self._equipment_counter = 0
            self._accessory_counter = 0
            for placeholder_id in self.placeholder_to_uuid.keys():
                if placeholder_id.startswith("EQUIPMENT_"):
                    try:
                        index = int(placeholder_id.split("_")[1])
                        self._equipment_counter = max(self._equipment_counter, index + 1)
                    except (ValueError, IndexError):
                        pass
                elif placeholder_id.startswith("ACCESSORY_"):
                    try:
                        index = int(placeholder_id.split("_")[1])
                        self._accessory_counter = max(self._accessory_counter, index + 1)
                    except (ValueError, IndexError):
                        pass


def validate_equipment_immutability(provided_equipment, plan_index_equipment):
    """
    Validate that provided equipment from file has not been modified.
    Plan_index equipment entries are minimal (id, type, name), so we only validate those fields.

    Args:
        provided_equipment: Dict with 'equipments' and 'accessoryEquipments' lists
        plan_index_equipment: Dict with 'equipments' and 'accessoryEquipments' lists from plan_index

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not provided_equipment:
        return True, None

    # Create lookup maps by ID for provided equipment
    provided_equipments_by_id = {eq.get("id"): eq for eq in provided_equipment.get("equipments", [])}
    provided_accessories_by_id = {acc.get("id"): acc for acc in provided_equipment.get("accessoryEquipments", [])}

    # Check all provided equipment items that appear in plan_index
    for eq in plan_index_equipment.get("equipments", []):
        eq_id = eq.get("id")
        if not eq_id:
            continue

        # Check if this ID exists in provided equipment
        if eq_id in provided_equipments_by_id:
            provided_eq = provided_equipments_by_id[eq_id]
            # Validate that id, type, and name match (plan_index has minimal fields)
            if eq.get("id") != provided_eq.get("id"):
                return False, f"Provided equipment {eq_id} ID was modified. Equipment from file is immutable."
            if eq.get("type") != provided_eq.get("type"):
                return False, f"Provided equipment {eq_id} type was modified from '{provided_eq.get('type')}' to '{eq.get('type')}'. Equipment from file is immutable."
            if eq.get("name") != provided_eq.get("name"):
                return False, f"Provided equipment {eq_id} name was modified from '{provided_eq.get('name')}' to '{eq.get('name')}'. Equipment from file is immutable."

    # Check all provided accessory items that appear in plan_index
    for acc in plan_index_equipment.get("accessoryEquipments", []):
        acc_id = acc.get("id")
        if not acc_id:
            continue

        # Check if this ID exists in provided accessories
        if acc_id in provided_accessories_by_id:
            provided_acc = provided_accessories_by_id[acc_id]
            # Validate that id, type, and name match (plan_index has minimal fields)
            if acc.get("id") != provided_acc.get("id"):
                return False, f"Provided accessory equipment {acc_id} ID was modified. Equipment from file is immutable."
            if acc.get("type") != provided_acc.get("type"):
                return False, f"Provided accessory equipment {acc_id} type was modified from '{provided_acc.get('type')}' to '{acc.get('type')}'. Equipment from file is immutable."
            if acc.get("name") != provided_acc.get("name"):
                return False, f"Provided accessory equipment {acc_id} name was modified from '{provided_acc.get('name')}' to '{acc.get('name')}'. Equipment from file is immutable."

    return True, None


def _normalize_accessory_name(name):
    """Normalize accessory name for comparison (strip, lower)."""
    if not isinstance(name, str):
        return ""
    return name.strip().lower()


def deduplicate_plan_index_accessories(plan_index, provided_equipment):
    """
    When plan_index lists an accessory with the same (type, name) as a provided accessory
    but with a different ID, rewrite references to use the provided ID and remove the
    duplicate from plan_index so it is not emitted as "new".
    Modifies plan_index in place.

    Returns:
        dict: Map duplicate_placeholder_id -> provided_placeholder_id for use when
              rewriting emitted exercises. Empty if no duplicates found.
    """
    duplicate_id_to_provided = {}
    if not provided_equipment or not plan_index:
        return duplicate_id_to_provided
    provided_accessories = provided_equipment.get("accessoryEquipments", [])
    if not provided_accessories:
        return duplicate_id_to_provided
    # Map (type, normalized name) -> provided placeholder ID
    provided_by_key = {}
    for acc in provided_accessories:
        acc_id = acc.get("id")
        if not acc_id:
            continue
        key = (str(acc.get("type", "")).strip().upper(), _normalize_accessory_name(acc.get("name")))
        provided_by_key[key] = acc_id
    # Find plan_index accessories that duplicate provided by (type, name)
    plan_accessories = plan_index.get("accessoryEquipments", [])
    for acc in plan_accessories:
        acc_id = acc.get("id")
        if not acc_id:
            continue
        key = (str(acc.get("type", "")).strip().upper(), _normalize_accessory_name(acc.get("name")))
        provided_id = provided_by_key.get(key)
        if provided_id and provided_id != acc_id:
            duplicate_id_to_provided[acc_id] = provided_id
    if not duplicate_id_to_provided:
        return duplicate_id_to_provided
    # Rewrite exercises' requiredAccessoryEquipmentIds to use provided ID
    for ex in plan_index.get("exercises", []):
        ids_list = ex.get("requiredAccessoryEquipmentIds")
        if not isinstance(ids_list, list):
            continue
        rewritten = []
        for aid in ids_list:
            rewritten.append(duplicate_id_to_provided.get(aid, aid))
        ex["requiredAccessoryEquipmentIds"] = rewritten
    # Remove duplicate accessory entries from plan_index so they are not treated as "new"
    plan_index["accessoryEquipments"] = [
        acc for acc in plan_accessories
        if acc.get("id") not in duplicate_id_to_provided
    ]
    return duplicate_id_to_provided


def apply_accessory_id_rewrite(workout_store, duplicate_id_to_provided):
    """
    Rewrite requiredAccessoryEquipmentIds in all exercises in workout_store so that
    any duplicate placeholder ID is replaced with the provided ID. Modifies in place.
    """
    if not duplicate_id_to_provided:
        return
    for workout in workout_store.get("workouts", []):
        for comp in workout.get("workoutComponents", []):
            if comp.get("type") != "Exercise":
                continue
            ids_list = comp.get("requiredAccessoryEquipmentIds")
            if not isinstance(ids_list, list):
                continue
            comp["requiredAccessoryEquipmentIds"] = [
                duplicate_id_to_provided.get(aid, aid) for aid in ids_list
            ]
            # Superset: rewrite in nested exercises
            for ex in comp.get("exercises", []):
                nested_ids = ex.get("requiredAccessoryEquipmentIds")
                if isinstance(nested_ids, list):
                    ex["requiredAccessoryEquipmentIds"] = [
                        duplicate_id_to_provided.get(aid, aid) for aid in nested_ids
                    ]


# Progress management functions for resume capability
PROGRESS_DIR = "workouts/generation_progress"


LOGS_DIR = "logs"


CONVERSATION_META_FILE = "conversation_meta.json"


def load_equipment_from_file(filepath):
    """
    Load equipment JSON from a file and validate its structure.

    Args:
        filepath: Path to the equipment JSON file

    Returns:
        dict: Dictionary with keys:
            - equipments: list of equipment dictionaries (required)
            - accessoryEquipments: list of accessory equipment dictionaries (optional)

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If JSON is invalid or structure is incorrect
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Equipment file not found: {filepath}")

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in equipment file: {e}")
    except Exception as e:
        raise ValueError(f"Failed to read equipment file: {e}")

    # Validate structure
    if not isinstance(data, dict):
        raise ValueError("Equipment file must contain a JSON object")

    if "equipments" not in data:
        raise ValueError("Equipment file must contain 'equipments' array")

    if not isinstance(data["equipments"], list):
        raise ValueError("'equipments' must be an array")

    if "accessoryEquipments" in data and not isinstance(data["accessoryEquipments"], list):
        raise ValueError("'accessoryEquipments' must be an array if present")

    # Normalize: ensure accessoryEquipments exists (empty list if not provided)
    if "accessoryEquipments" not in data:
        data["accessoryEquipments"] = []

    # Extract and validate placeholder IDs from equipment
    # (IDs will be registered with id_manager later in execute_workout_generation)

    return {
        "equipments": data["equipments"],
        "accessoryEquipments": data["accessoryEquipments"]
    }

# Token limits for DeepSeek models


# Simplified equipment schema for incremental generation


def emit_exercise_definition(
    exercise_id,
    client,
    context_summary,
    plan_index,
    equipment_subset,
    accessory_subset=None,
    use_reasoner=True,
    provided_equipment=None,
    logger=None,
    contract_error_context=None,
    allow_educated_load_guesses=True,
    max_attempts=4,
    deterministic=False,
):
    """Compatibility entry point for deterministic materialization of a planned exercise."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    exercise_entry = next((entry for entry in plan_index.get("exercises", [])
                           if entry.get("id") == exercise_id), None)
    if exercise_entry is None:
        raise ValueError(f"Exercise ID {exercise_id} not found in PlanIndex")
    item = finalize_and_validate_exercise_definition(
        _materialize_exercise_definition(exercise_entry), plan_entry=exercise_entry,
        equipment_subset=equipment_subset, accessory_subset=accessory_subset,
        all_equipment_candidates=(provided_equipment or {}).get("equipments", []),
        allow_educated_load_guesses=allow_educated_load_guesses)
    validate_single_exercise_definition_contract(exercise_entry, item)
    return ExerciseDefinition(item), None


def emit_workout_structure(
    workout_id,
    client,
    context_summary,
    plan_index,
    exercise_index,
    use_reasoner=True,
    logger=None,
    contract_error_context=None,
):
    """Construct the already planned structure without another model call."""
    workout_entry = next((workout for workout in plan_index.get("workouts", []) if workout.get("id") == workout_id), None)
    if workout_entry is None:
        raise ValueError(f"Unknown planned workout {workout_id}")
    return build_workout_structure(workout_entry), None


# Muscle group name mappings for common errors


# Normalized data structures for planner/emitter architecture
# These are type hints/documentation - actual data is dict-based for JSON compatibility


def save_workout_to_file(workout_json, script_dir=None):
    """
    Save workout plan package JSON to a timestamped file in the workouts/ directory.

    Args:
        workout_json: The complete workout plan package JSON dictionary
        script_dir: Directory where the script is located (defaults to current directory)

    Returns:
        str: Path to the saved file, or None if saving failed
    """
    try:
        # Determine the base directory (where the script is located)
        if script_dir is None:
            try:
                # Get the directory where this script is located
                script_dir = _default_script_dir()
            except (NameError, AttributeError):
                # Fallback to current working directory if __file__ is not available
                script_dir = os.getcwd()

        # Create workouts directory if it doesn't exist
        workouts_dir = os.path.join(script_dir, "workouts")
        os.makedirs(workouts_dir, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"workout_plan_{timestamp}.json"
        filepath = os.path.join(workouts_dir, filename)

        # Write JSON to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(workout_json, f, indent=2, ensure_ascii=False)

        return filepath
    except Exception as e:
        print(f"Error saving workout to file: {e}", file=sys.stderr)
        return None

def display_workout_summary(workout_json, filepath, logger=None):
    """
    Display a summary of the generated workout plan package.

    Args:
        workout_json: The complete workout plan package JSON dictionary
        filepath: Path to the saved file
        logger: Optional ConversationLogger for debug logging
    """
    _out = (lambda m: logger.log_print(m)) if logger else (lambda m: print(m))
    workouts = workout_json.get("workouts", [])
    equipments = workout_json.get("equipments", [])
    plan_name = workout_json.get("name", "Generated Workout Plan")

    if not workouts:
        _out("Warning: No workouts found in generated JSON")
        return

    # Sort workouts by order value (default to 999 if missing)
    sorted_workouts = sorted(workouts, key=lambda w: w.get("order", 999))

    # Collect all workout names in sorted order
    workout_names = []
    total_exercise_count = 0

    for workout in sorted_workouts:
        workout_name = workout.get("name", "Unnamed Workout")
        workout_names.append(workout_name)

        # Count exercises in workout components
        exercise_count = 0
        for component in workout.get("workoutComponents", []):
            if component.get("type") == "Exercise":
                exercise_count += 1
            elif component.get("type") == "Superset":
                exercise_count += len(component.get("exercises", []))
        total_exercise_count += exercise_count

    # Get file size
    file_size = 0
    if filepath and os.path.exists(filepath):
        file_size = os.path.getsize(filepath)

    # Display summary
    _out("\n" + "=" * 70)
    _out("Workout Plan Generated Successfully!")
    _out("=" * 70)
    _out(f"Plan Name: {plan_name}")
    if len(workout_names) == 1:
        _out(f"Workout Name: {workout_names[0]}")
    else:
        _out(f"Workouts ({len(workout_names)}):")
        for name in workout_names:
            _out(f"  - {name}")
    _out(f"Exercises: {total_exercise_count}")
    _out(f"Equipment Items: {len(equipments)}")
    if filepath:
        _out(f"Saved to: {filepath}")
        if file_size > 0:
            _out(f"File Size: {file_size:,} bytes")
    _out("=" * 70)

def display_timing_summary(timing_data, is_resume=False, logger=None):
    """
    Display timing summary for workout generation.

    Args:
        timing_data: Dict with timing information
        is_resume: Whether this was a resumed session
        logger: Optional ConversationLogger for debug logging
    """
    if not timing_data:
        return
    _out = (lambda m: logger.log_print(m)) if logger else (lambda m: print(m))

    total_time = timing_data.get("total_time_seconds", 0.0)
    step_times = timing_data.get("step_times", {})
    save_times = timing_data.get("save_times", [])

    _out("\n" + "=" * 70)
    _out("Generation Timing Summary")
    _out("=" * 70)

    if is_resume:
        _out(f"Total Generation Time: {total_time:.2f}s (includes previous session)")
    else:
        _out(f"Total Generation Time: {total_time:.2f}s")

    if step_times:
        _out("\nStep Times:")
        step_names = {
            0: "Summarize conversation",
            1: "Load confirmed plan",
            2: "Load equipment",
            3: "Compile exercise prescriptions",
            4: "Build workout structures",
            5: "Assemble placeholder workout plan package",
            6: "Validate package schema",
            7: "Convert placeholders to UUIDs",
            8: "Audit actual volume and duration",
        }
        # Sort keys (should be integers after normalization, but handle both for safety)
        sorted_keys = sorted(step_times.keys(), key=lambda k: int(k) if isinstance(k, str) and k.isdigit() else (k if isinstance(k, int) else 0))
        for step_num in sorted_keys:
            step_time = step_times[step_num]
            # Normalize step_num to int for lookup (should already be int after load normalization)
            step_num_int = int(step_num) if isinstance(step_num, str) and step_num.isdigit() else step_num
            step_name = step_names.get(step_num_int, f"Step {step_num_int}")
            _out(f"  {step_name}: {step_time:.2f}s")

    _out("=" * 70)


CONVERSATION_FILE = "conversation_history.json"


# Extracted module bindings (compatibility-safe rebinds)
from workout_generator_pkg.paths import (
    get_progress_dir as _mod_get_progress_dir,
    get_log_dir as _mod_get_log_dir,
    conversation_meta_path as _mod_conversation_meta_path,
)
from workout_generator_pkg.conversation_meta import (
    load_conversation_meta as _mod_load_conversation_meta,
    save_conversation_meta as _mod_save_conversation_meta,
    hash_conversation as _mod_hash_conversation,
)
from workout_generator_pkg.progress import (
    save_generation_progress as _mod_save_generation_progress,
    load_generation_progress as _mod_load_generation_progress,
    list_available_progress as _mod_list_available_progress,
    delete_progress_file as _mod_delete_progress_file,
)
from workout_generator_pkg.conversation_store import (
    save_conversation as _mod_save_conversation,
    _is_valid_message as _mod_is_valid_message,
    load_conversation as _mod_load_conversation,
    load_active_conversation_record as _mod_load_active_conversation_record,
    load_conversation_record as _mod_load_conversation_record,
    list_conversations as _mod_list_conversations,
    set_active_conversation as _mod_set_active_conversation,
    update_conversation_metadata as _mod_update_conversation_metadata,
    resolve_conversation_id as _mod_resolve_conversation_id,
)
from workout_generator_pkg.api_client import (
    chat_call as _mod_chat_call,
    _log_connection_error as _mod__log_connection_error,
    test_connection as _mod_test_connection,
    _retry_on_connection_error as _mod__retry_on_connection_error,
    _collect_streaming_response as _mod__collect_streaming_response,
    json_call as _mod_json_call,
    chat_call_with_loading as _mod_chat_call_with_loading,
    json_call_with_retry as _mod_json_call_with_retry,
    json_call_with_loading as _mod_json_call_with_loading,
    json_call_chat_max_with_loading as _mod_json_call_chat_max_with_loading,
    is_json_complete as _mod_is_json_complete,
    json_call_large as _mod_json_call_large,
    json_call_reasoner_only as _mod_json_call_reasoner_only,
    json_call_large_with_retry as _mod_json_call_large_with_retry,
    json_call_large_with_loading as _mod_json_call_large_with_loading,
    json_call_reasoner_only_with_loading as _mod_json_call_reasoner_only_with_loading,
    estimate_output_size as _mod_estimate_output_size,
)
from workout_generator_pkg.json_patching import (
    apply_json_patch as _mod_apply_json_patch,
    escape_json_pointer_token as _mod_escape_json_pointer_token,
    to_json_pointer as _mod_to_json_pointer,
    normalize_json_pointer as _mod_normalize_json_pointer,
    is_path_allowed as _mod_is_path_allowed,
    build_allowed_patch_paths as _mod_build_allowed_patch_paths,
    build_allowed_patch_scope as _mod_build_allowed_patch_scope,
    validate_patch_operations_scope as _mod_validate_patch_operations_scope,
    collect_changed_json_paths as _mod_collect_changed_json_paths,
    validate_changed_paths_scope as _mod_validate_changed_paths_scope,
)
from workout_generator_pkg.domain_ops import (
    validate_exercise_type_consistency as _mod_validate_exercise_type_consistency,
    validate_reps_for_exercise_type as _mod_validate_reps_for_exercise_type,
    validate_muscle_groups as _mod_validate_muscle_groups,
    validate_equipment_references as _mod_validate_equipment_references,
    validate_equipment_weight_combinations as _mod_validate_equipment_weight_combinations,
    fix_equipment_weights as _mod_fix_equipment_weights,
    finalize_and_validate_exercise_definition as _mod_finalize_and_validate_exercise_definition,
    generate_recursive_valid_subsets as _mod_generate_recursive_valid_subsets,
    calculate_equipment_weight_combinations as _mod_calculate_equipment_weight_combinations,
    get_selectable_weights_for_exercise as _mod_get_selectable_weights_for_exercise,
    format_equipment_list_for_plan as _mod_format_equipment_list_for_plan,
    format_planner_equipment_context as _mod_format_planner_equipment_context,
    format_equipment_for_llm as _mod_format_equipment_for_llm,
    format_equipment_for_conversation as _mod_format_equipment_for_conversation,
    has_equipment_in_messages as _mod_has_equipment_in_messages,
    fix_timed_sets as _mod_fix_timed_sets,
    create_placeholder_schema as _mod_create_placeholder_schema,
    ensure_unique_ids as _mod_ensure_unique_ids,
    apply_exercise_library_schema_v2 as _mod_apply_exercise_library_schema_v2,
    _dedupe_sets_in_exercise as _mod__dedupe_sets_in_exercise,
    convert_placeholders_to_uuids as _mod_convert_placeholders_to_uuids,
    remove_none_from_workout_components as _mod_remove_none_from_workout_components,
    ensure_requiresLoadCalibration as _mod_ensure_requiresLoadCalibration,
    assemble_placeholder_workout_store as _mod_assemble_placeholder_workout_store,
    fix_muscle_groups as _mod_fix_muscle_groups,
    infer_exercise_category as _mod_infer_exercise_category,
    fix_muscle_groups_in_exercise as _mod_fix_muscle_groups_in_exercise,
    fix_set_errors as _mod_fix_set_errors,
    fix_exercise_errors as _mod_fix_exercise_errors,
    sync_exercises_from_definitions as _mod_sync_exercises_from_definitions,
    sync_exercises_from_plan_index as _mod_sync_exercises_from_plan_index,
    fix_equipment_errors as _mod_fix_equipment_errors,
    save_validation_error as _mod_save_validation_error,
    get_item_type_label as _mod_get_item_type_label,
    parse_error_path as _mod_parse_error_path,
    extract_validation_error_details as _mod_extract_validation_error_details,
    analyze_and_log_validation_errors as _mod_analyze_and_log_validation_errors,
    extract_item_by_path as _mod_extract_item_by_path,
    reassemble_item as _mod_reassemble_item,
    build_context_summary as _mod_build_context_summary,
    EquipmentItem as _mod_EquipmentItem,
    ExerciseDefinition as _mod_ExerciseDefinition,
    WorkoutStructure as _mod_WorkoutStructure,
)
from workout_generator_pkg.generation_pipeline import (
    execute_workout_generation as _mod_execute_workout_generation,
)
from workout_generator_pkg.interactive_shell import (
    handle_function_call as _mod_handle_function_call,
    main as _mod_main,
)

get_progress_dir = _mod_get_progress_dir
get_log_dir = _mod_get_log_dir
_conversation_meta_path = _mod_conversation_meta_path
load_conversation_meta = _mod_load_conversation_meta
save_conversation_meta = _mod_save_conversation_meta
hash_conversation = _mod_hash_conversation
save_generation_progress = _mod_save_generation_progress
load_generation_progress = _mod_load_generation_progress
list_available_progress = _mod_list_available_progress
delete_progress_file = _mod_delete_progress_file
save_conversation = _mod_save_conversation
_is_valid_message = _mod_is_valid_message
load_conversation = _mod_load_conversation
load_active_conversation_record = _mod_load_active_conversation_record
load_conversation_record = _mod_load_conversation_record
list_conversations = _mod_list_conversations
set_active_conversation = _mod_set_active_conversation
update_conversation_metadata = _mod_update_conversation_metadata
resolve_conversation_id = _mod_resolve_conversation_id
chat_call = _mod_chat_call
_log_connection_error = _mod__log_connection_error
test_connection = _mod_test_connection
_retry_on_connection_error = _mod__retry_on_connection_error
_collect_streaming_response = _mod__collect_streaming_response
json_call = _mod_json_call
chat_call_with_loading = _mod_chat_call_with_loading
json_call_with_retry = _mod_json_call_with_retry
json_call_with_loading = _mod_json_call_with_loading
json_call_chat_max_with_loading = _mod_json_call_chat_max_with_loading
is_json_complete = _mod_is_json_complete
json_call_large = _mod_json_call_large
json_call_reasoner_only = _mod_json_call_reasoner_only
json_call_large_with_retry = _mod_json_call_large_with_retry
json_call_large_with_loading = _mod_json_call_large_with_loading
json_call_reasoner_only_with_loading = _mod_json_call_reasoner_only_with_loading
estimate_output_size = _mod_estimate_output_size
apply_json_patch = _mod_apply_json_patch
escape_json_pointer_token = _mod_escape_json_pointer_token
to_json_pointer = _mod_to_json_pointer
normalize_json_pointer = _mod_normalize_json_pointer
is_path_allowed = _mod_is_path_allowed
build_allowed_patch_paths = _mod_build_allowed_patch_paths
build_allowed_patch_scope = _mod_build_allowed_patch_scope
validate_patch_operations_scope = _mod_validate_patch_operations_scope
collect_changed_json_paths = _mod_collect_changed_json_paths
validate_changed_paths_scope = _mod_validate_changed_paths_scope
validate_exercise_type_consistency = _mod_validate_exercise_type_consistency
validate_reps_for_exercise_type = _mod_validate_reps_for_exercise_type
validate_muscle_groups = _mod_validate_muscle_groups
validate_equipment_references = _mod_validate_equipment_references
validate_equipment_weight_combinations = _mod_validate_equipment_weight_combinations
fix_equipment_weights = _mod_fix_equipment_weights
finalize_and_validate_exercise_definition = _mod_finalize_and_validate_exercise_definition
generate_recursive_valid_subsets = _mod_generate_recursive_valid_subsets
calculate_equipment_weight_combinations = _mod_calculate_equipment_weight_combinations
get_selectable_weights_for_exercise = _mod_get_selectable_weights_for_exercise
format_equipment_list_for_plan = _mod_format_equipment_list_for_plan
format_planner_equipment_context = _mod_format_planner_equipment_context
format_equipment_for_llm = _mod_format_equipment_for_llm
format_equipment_for_conversation = _mod_format_equipment_for_conversation
has_equipment_in_messages = _mod_has_equipment_in_messages
fix_timed_sets = _mod_fix_timed_sets
create_placeholder_schema = _mod_create_placeholder_schema
ensure_unique_ids = _mod_ensure_unique_ids
apply_exercise_library_schema_v2 = _mod_apply_exercise_library_schema_v2
_dedupe_sets_in_exercise = _mod__dedupe_sets_in_exercise
convert_placeholders_to_uuids = _mod_convert_placeholders_to_uuids
remove_none_from_workout_components = _mod_remove_none_from_workout_components
ensure_requiresLoadCalibration = _mod_ensure_requiresLoadCalibration
assemble_placeholder_workout_store = _mod_assemble_placeholder_workout_store
fix_muscle_groups = _mod_fix_muscle_groups
infer_exercise_category = _mod_infer_exercise_category
fix_muscle_groups_in_exercise = _mod_fix_muscle_groups_in_exercise
fix_set_errors = _mod_fix_set_errors
fix_exercise_errors = _mod_fix_exercise_errors
sync_exercises_from_definitions = _mod_sync_exercises_from_definitions
sync_exercises_from_plan_index = _mod_sync_exercises_from_plan_index
fix_equipment_errors = _mod_fix_equipment_errors
save_validation_error = _mod_save_validation_error
get_item_type_label = _mod_get_item_type_label
parse_error_path = _mod_parse_error_path
extract_validation_error_details = _mod_extract_validation_error_details
analyze_and_log_validation_errors = _mod_analyze_and_log_validation_errors
extract_item_by_path = _mod_extract_item_by_path
reassemble_item = _mod_reassemble_item
build_context_summary = _mod_build_context_summary
EquipmentItem = _mod_EquipmentItem
ExerciseDefinition = _mod_ExerciseDefinition
WorkoutStructure = _mod_WorkoutStructure
execute_workout_generation = _mod_execute_workout_generation
handle_function_call = _mod_handle_function_call
main = _mod_main

if __name__ == "__main__":
    main()
