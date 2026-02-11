import json
import os
import sys
import threading
import time
import atexit
import uuid
import copy
import hashlib
import glob
import random
import traceback
import argparse
import re
from types import SimpleNamespace
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import httpx
from workout_generator_pkg.constants import (
    JSON_SCHEMA,
    EXAMPLE_JSON,
    PARALLEL_LOG_REQUEST_TRUNCATE,
    DEEPSEEK_CHAT_DEFAULT_TOKENS,
    DEEPSEEK_CHAT_MAX_TOKENS,
    DEEPSEEK_REASONER_DEFAULT_TOKENS,
    DEEPSEEK_REASONER_MAX_TOKENS,
    BASE_SYSTEM_PROMPT,
    SUMMARIZATION_SYSTEM_PROMPT,
    JSON_SYSTEM_PROMPT,
    SELF_HEAL_SYSTEM_PROMPT,
    EQUIPMENT_SCHEMA,
    EQUIPMENT_EXAMPLE,
    EQUIPMENT_SYSTEM_PROMPT,
    EXERCISE_SCHEMA,
    EXERCISE_EXAMPLE,
    EXERCISE_SYSTEM_PROMPT,
    WORKOUT_STRUCTURE_EXAMPLE,
    WORKOUT_STRUCTURE_SYSTEM_PROMPT,
    PLAN_INDEX_EXAMPLE,
    PLAN_INDEX_SYSTEM_PROMPT,
    JSON_PATCH_REPAIR_SYSTEM_PROMPT,
    GENERATE_WORKOUT_TOOL,
    MUSCLE_GROUP_FIXES,
)

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)


def _default_script_dir():
    """Return project root path for filesystem outputs."""
    return PROJECT_ROOT
try:
    from openai import APIConnectionError
except ImportError:
    APIConnectionError = None
try:
    from httpx import RemoteProtocolError
except ImportError:
    try:
        from httpcore import RemoteProtocolError
    except ImportError:
        RemoteProtocolError = None
                                                                                                                                                                                                                                                   
# Optional validation (pip install jsonschema)                                                                                                                                                                                                   
try:                                                                                                                                                                                                                                             
    from jsonschema import validate                                                                                                                                                                                                              
except Exception:                                                                                                                                                                                                                                
    validate = None                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                   
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

def generate_uuid():
    """Generate a new UUID string."""
    return str(uuid.uuid4())

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


def merge_equipment(provided_equipment, plan_index_equipment, id_manager):
    """
    Merge provided equipment with newly created equipment from plan_index.
    Provided equipment remains unchanged, new equipment is added.
    
    Args:
        provided_equipment: Dict with 'equipments' and 'accessoryEquipments' lists (from file)
        plan_index_equipment: Dict with 'equipments' and 'accessoryEquipments' lists (from plan_index)
        id_manager: PlaceholderIdManager instance
    
    Returns:
        dict: Merged equipment with 'equipments' and 'accessoryEquipments' lists
    """
    # Start with provided equipment (unchanged)
    merged_equipments = list(provided_equipment.get("equipments", [])) if provided_equipment else []
    merged_accessories = list(provided_equipment.get("accessoryEquipments", [])) if provided_equipment else []
    
    # Create sets of existing IDs to avoid duplicates
    existing_equipment_ids = {eq.get("id") for eq in merged_equipments if eq.get("id")}
    existing_accessory_ids = {acc.get("id") for acc in merged_accessories if acc.get("id")}
    
    # Add new equipment from plan_index that doesn't exist in provided equipment
    for eq in plan_index_equipment.get("equipments", []):
        eq_id = eq.get("id")
        if eq_id and eq_id not in existing_equipment_ids:
            # This is new equipment - register its ID and add it
            id_manager.extract_placeholders_from_json(eq)
            merged_equipments.append(eq)
            existing_equipment_ids.add(eq_id)
    
    # Add new accessories from plan_index that don't exist in provided equipment
    for acc in plan_index_equipment.get("accessoryEquipments", []):
        acc_id = acc.get("id")
        if acc_id and acc_id not in existing_accessory_ids:
            # This is new accessory - register its ID and add it
            id_manager.extract_placeholders_from_json(acc)
            merged_accessories.append(acc)
            existing_accessory_ids.add(acc_id)
    
    return {
        "equipments": merged_equipments,
        "accessoryEquipments": merged_accessories
    }

# Progress management functions for resume capability
PROGRESS_DIR = "workouts/generation_progress"


LOGS_DIR = "logs"


CONVERSATION_META_FILE = "conversation_meta.json"




class ConversationLogger:
    """
    Per-conversation debug logger. Writes timestamped lines to a log file.
    Use log_print for lines that should also go to stdout.
    """

    def __init__(self, log_path):
        self._path = log_path
        self._file = open(log_path, 'a', encoding='utf-8')
        self._lock = threading.Lock()

    def _timestamp(self):
        return datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")

    def _write(self, msg):
        with self._lock:
            try:
                self._file.write(self._timestamp() + msg + "\n")
                self._file.flush()
            except Exception as e:
                print(f"Warning: Failed to write to debug log: {e}", file=sys.stderr)

    def log(self, msg):
        """Write timestamped line to log file only."""
        self._write(msg)

    def log_print(self, msg):
        """Write to log and print to stdout."""
        self._write(msg)
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"))

    def log_section(self, title):
        """Write a section header to the log."""
        self._write("--- " + title + " ---")

    def log_request(self, label, summary):
        """Log an API request (label + summary)."""
        self._write("[request] " + label + ": " + str(summary))

    def log_response(self, label, content, truncate_at=8000):
        """Log an API response; truncate large content."""
        s = str(content) if content is not None else ""
        if truncate_at and len(s) > truncate_at:
            s = s[:truncate_at] + f"... [truncated, total {len(s)} chars]"
        self._write("[response] " + label + ": " + s)

    def flush(self):
        with self._lock:
            try:
                if self._file:
                    self._file.flush()
            except Exception as e:
                print(f"Warning: Failed to flush debug log: {e}", file=sys.stderr)

    def close(self):
        with self._lock:
            try:
                if self._file:
                    self._file.flush()
                    self._file.close()
                    self._file = None
            except Exception as e:
                print(f"Warning: Failed to close debug log: {e}", file=sys.stderr)


# When using PrefixLogger (parallel item emission), log more of the request in the log file


class PrefixLogger:
    """
    Wrapper that prepends a prefix (e.g. [EQUIPMENT_0]) to every log line.
    Used so parallel item logs can be filtered by item_id.
    """

    def __init__(self, logger, prefix):
        self._logger = logger
        self._prefix = prefix
        self.is_parallel = True  # Emitters use this to apply higher request truncation

    def log(self, msg):
        self._logger.log(self._prefix + msg)

    def log_print(self, msg):
        self._logger.log_print(self._prefix + msg)

    def log_section(self, title):
        self._logger.log_section(self._prefix + title)

    def log_request(self, label, summary):
        self._logger.log_request(self._prefix + label, summary)

    def log_response(self, label, content, truncate_at=8000):
        self._logger.log_response(self._prefix + label, content, truncate_at=truncate_at)

    def flush(self):
        self._logger.flush()

    def close(self):
        self._logger.close()







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



# Simplified exercise schema for incremental generation



# Workout structure schema


# PlanIndex structure for planner/emitter architecture


# JSON Patch repair system prompt

# Function tool schema for OpenAI function calling
                                                                                                                                                                                                                                                   
class LoadingIndicator:
    def __init__(self, message="Thinking"):
        self.message = message
        self.stop_event = threading.Event()
        self.thread = None
        self.start_time = None
        
    def _animate(self):
        """Internal method to run the animation in a separate thread."""
        dots = ["", ".", "..", "..."]
        dot_index = 0
        
        while not self.stop_event.is_set():
            elapsed = int(time.time() - self.start_time)
            text = f"{self.message}{dots[dot_index]:<3} ({elapsed}s)\r"
            sys.stdout.write(text)
            sys.stdout.flush()
            dot_index = (dot_index + 1) % len(dots)
            time.sleep(0.5)
    
    def start(self):
        """Start the loading indicator."""
        self.start_time = time.time()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the loading indicator and clear the line."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.1)
        # Clear the line
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

class ParallelLoadingIndicator:
    """Loading indicator for parallel execution showing aggregate progress."""
    def __init__(self, base_message="Generating", total_items=0):
        self.base_message = base_message
        self.total_items = total_items
        self.completed_items = 0
        self.stop_event = threading.Event()
        self.thread = None
        self.start_time = None
        self.lock = threading.Lock()
        
    def _animate(self):
        """Internal method to run the animation in a separate thread."""
        dots = ["", ".", "..", "..."]
        dot_index = 0
        
        while not self.stop_event.is_set():
            with self.lock:
                completed = self.completed_items
                total = self.total_items
            elapsed = int(time.time() - self.start_time)
            if total > 0:
                text = f"{self.base_message} ({completed}/{total}){dots[dot_index]:<3} ({elapsed}s)\r"
            else:
                text = f"{self.base_message}{dots[dot_index]:<3} ({elapsed}s)\r"
            sys.stdout.write(text)
            sys.stdout.flush()
            dot_index = (dot_index + 1) % len(dots)
            time.sleep(0.5)
    
    def start(self):
        """Start the loading indicator."""
        self.start_time = time.time()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()
    
    def increment(self):
        """Increment the completed items count."""
        with self.lock:
            self.completed_items += 1
    
    def stop(self):
        """Stop the loading indicator and clear the line."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.1)
        # Clear the line
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()



















def generate_equipment(client, messages, id_manager):
    """Generate equipment list with placeholder IDs."""
    equipment_messages = messages + [
        {"role": "system", "content": EQUIPMENT_SYSTEM_PROMPT},
        {"role": "user", "content": "Generate all equipment needed for the workout based on our conversation."}
    ]
    
    content = json_call_with_loading(client, equipment_messages)
    if content is None:
        return None
    
    if not content:
        raise ValueError("Model returned empty equipment JSON content.")
    
    try:
        data = json.loads(content)
        if "equipments" not in data or not isinstance(data["equipments"], list):
            raise ValueError("Invalid equipment JSON format: missing 'equipments' array")
        
        # Extract and register all placeholder IDs
        for equipment in data["equipments"]:
            id_manager.extract_placeholders_from_json(equipment)
        
        # Normalize equipment immediately after generation
        normalized_equipments = fix_equipment_errors(data["equipments"])
        
        return normalized_equipments
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse equipment JSON: {e}")

def generate_exercises(client, messages, equipment_list, id_manager, provided_equipment=None):
    """Generate exercise list with placeholder IDs, referencing equipment placeholders."""
    if provided_equipment:
        # Use formatted equipment text showing total weight combinations
        formatted_equipment = format_equipment_for_llm(
            provided_equipment.get("equipments", []),
            provided_equipment.get("accessoryEquipments", [])
        )
        equipment_json = json.dumps(provided_equipment, indent=2)
        equipment_content = (
            f"{formatted_equipment}\n\n"
            f"Use only equipment from the list above. "
            f"All WeightSet weights and BodyWeightSet additionalWeight values must match valid combinations shown.\n\n"
            f"Equipment JSON (for reference):\n{equipment_json}"
        )
    else:
        # Fallback to original format (for Step 1 before equipment is generated)
        equipment_json = json.dumps({"equipments": equipment_list}, indent=2)
        equipment_content = f"Available equipment:\n{equipment_json}"
    
    exercise_messages = messages + [
        {"role": "system", "content": EXERCISE_SYSTEM_PROMPT},
        {"role": "user", "content": f"{equipment_content}\n\nGenerate all exercises needed for the workout based on our conversation. Reference equipment using their placeholder IDs (EQUIPMENT_0, EQUIPMENT_1, etc.)."}
    ]
    
    content = json_call_with_loading(client, exercise_messages)
    if content is None:
        return None
    
    if not content:
        raise ValueError("Model returned empty exercise JSON content.")
    
    try:
        data = json.loads(content)
        if "exercises" not in data or not isinstance(data["exercises"], list):
            raise ValueError("Invalid exercise JSON format: missing 'exercises' array")
        
        # Extract and register all placeholder IDs (exercises and sets)
        for exercise in data["exercises"]:
            id_manager.extract_placeholders_from_json(exercise)
        
        # Normalize exercises immediately after generation
        normalized_exercises = fix_exercise_errors(data["exercises"])
        
        return normalized_exercises
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse exercise JSON: {e}")

def generate_workout_structure(client, messages, exercise_list, id_manager):
    """Generate workout structure with placeholder IDs, referencing exercise placeholders."""
    exercise_json = json.dumps({"exercises": exercise_list}, indent=2)
    
    workout_messages = messages + [
        {"role": "system", "content": WORKOUT_STRUCTURE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Available exercises:\n{exercise_json}\n\nGenerate the workout structure based on our conversation. Reference exercises using their placeholder IDs (EXERCISE_0, EXERCISE_1, etc.).\n\nIMPORTANT: Generate a specific description for workoutMetadata.description based on the actual exercises provided above. Make it specific to the exercises in this workout (e.g., muscle groups, primary exercises, or training focus), not a generic description. Keep it under 50 characters."}
    ]
    
    content = json_call_with_loading(client, workout_messages)
    if content is None:
        return None
    
    if not content:
        raise ValueError("Model returned empty workout structure JSON content.")
    
    try:
        data = json.loads(content)
        if "workoutMetadata" not in data or "workoutComponents" not in data:
            raise ValueError("Invalid workout structure JSON format: missing 'workoutMetadata' or 'workoutComponents'")
        
        # Extract and register all placeholder IDs
        id_manager.extract_placeholders_from_json(data)
        
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse workout structure JSON: {e}")

# Chunked emitters for planner/emitter architecture
def emit_equipment_item(equipment_id, client, context_summary, plan_index, use_reasoner=True, logger=None):
    """
    Emit a single equipment item using either deepseek-reasoner @ 64K or deepseek-chat @ 8K.
    
    Args:
        client: OpenAI client
        equipment_id: Placeholder ID (e.g., "EQUIPMENT_0")
        context_summary: Summarized conversation context
        plan_index: PlanIndex dict containing equipment entry for this ID
        use_reasoner: If True, use reasoner model (slower, potentially higher quality).
                     If False, use chat model (faster, 8K max tokens).
        logger: Optional ConversationLogger for debug logging
    
    Returns:
        dict: Single EquipmentItem with placeholder ID, or None if cancelled
    """
    # Find the equipment entry in plan_index
    equipment_entry = None
    for eq in plan_index.get("equipments", []):
        if eq.get("id") == equipment_id:
            equipment_entry = eq
            break
    
    if not equipment_entry:
        raise ValueError(f"Equipment ID {equipment_id} not found in PlanIndex")
    
    equipment_entry_json = json.dumps(equipment_entry, indent=2)
    
    user_content = (
        "Use equipment names consistent with the plan entry.\n\n"
        f"Plan entry for {equipment_id}:\n{equipment_entry_json}\n\n"
        f"Generate ONLY this one equipment object using placeholder IDs. "
        f"Output format should match one of the Equipment types from the schema. "
        f"Use placeholder ID: {equipment_id}\n\n"
        f"Output only the equipment object JSON, not a wrapper."
    )
    
    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "system", "content": EQUIPMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    
    if logger:
        request_truncate = PARALLEL_LOG_REQUEST_TRUNCATE if getattr(logger, "is_parallel", False) else 2000
        trunc = user_content[:request_truncate] + (f"... [truncated, total {len(user_content)} chars]" if request_truncate and len(user_content) > request_truncate else "")
        logger.log_request("emit_equipment " + equipment_id, trunc)
    if use_reasoner:
        content = json_call_reasoner_only_with_loading(client, messages, "", show_loading=False, logger=logger)
    else:
        content = json_call_chat_max_with_loading(client, messages, "", show_loading=False, logger=logger)
    if content is None:
        return (None, None)
    
    if not content:
        raise ValueError(f"Model returned empty equipment JSON content for {equipment_id}")
    
    if logger:
        logger.log_response("emit_equipment " + equipment_id, content, truncate_at=8000)
    log_entry = None
    if logger:
        log_entry = {
            "step": "equipment",
            "item_id": equipment_id,
            "request_messages": messages,
            "response_content": content,
        }
    try:
        data = json.loads(content)
        # If it's wrapped in an "equipments" array, extract the first item
        if "equipments" in data and isinstance(data["equipments"], list) and len(data["equipments"]) > 0:
            equipment_item = data["equipments"][0]
        elif "id" in data or "type" in data:
            # It's already a single equipment object
            equipment_item = data
        else:
            raise ValueError(f"Invalid equipment JSON format for {equipment_id}: expected equipment object or equipments array")
        
        # Ensure the ID matches
        if equipment_item.get("id") != equipment_id:
            equipment_item["id"] = equipment_id
        
        # Normalize equipment before wrapping
        normalized_list = fix_equipment_errors([equipment_item])
        normalized_item = normalized_list[0] if normalized_list else equipment_item
        
        return (EquipmentItem(normalized_item), log_entry)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse equipment JSON for {equipment_id}: {e}")

def emit_accessory_equipment_item(accessory_id, client, context_summary, plan_index, use_reasoner=True, logger=None):
    """
    Emit a single accessory equipment item using either deepseek-reasoner @ 64K or deepseek-chat @ 8K.
    
    Args:
        client: OpenAI client
        accessory_id: Placeholder ID (e.g., "ACCESSORY_0")
        context_summary: Summarized conversation context
        plan_index: PlanIndex dict containing accessory equipment entry for this ID
        use_reasoner: If True, use reasoner model (slower, potentially higher quality).
                     If False, use chat model (faster, 8K max tokens).
        logger: Optional ConversationLogger for debug logging
    
    Returns:
        dict: Single AccessoryEquipment item with placeholder ID, or None if cancelled
    """
    # Find the accessory equipment entry in plan_index
    accessory_entry = None
    for acc in plan_index.get("accessoryEquipments", []):
        if acc.get("id") == accessory_id:
            accessory_entry = acc
            break
    
    if not accessory_entry:
        raise ValueError(f"Accessory Equipment ID {accessory_id} not found in PlanIndex")
    
    accessory_entry_json = json.dumps(accessory_entry, indent=2)
    
    user_content = (
        "Use accessory names consistent with the plan entry.\n\n"
        f"Plan entry for {accessory_id}:\n{accessory_entry_json}\n\n"
        f"Generate ONLY this one accessory equipment object using placeholder IDs. "
        f"Output format should match $defs.EquipmentAccessory from the schema. "
        f"Use placeholder ID: {accessory_id}\n\n"
        f"Accessory equipment only requires: id, type (must be 'ACCESSORY'), and name.\n\n"
        f"Output only the accessory equipment object JSON, not a wrapper."
    )
    
    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "system", "content": EQUIPMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    
    if logger:
        request_truncate = PARALLEL_LOG_REQUEST_TRUNCATE if getattr(logger, "is_parallel", False) else 2000
        trunc = user_content[:request_truncate] + (f"... [truncated, total {len(user_content)} chars]" if request_truncate and len(user_content) > request_truncate else "")
        logger.log_request("emit_accessory " + accessory_id, trunc)
    if use_reasoner:
        content = json_call_reasoner_only_with_loading(client, messages, "", show_loading=False, logger=logger)
    else:
        content = json_call_chat_max_with_loading(client, messages, "", show_loading=False, logger=logger)
    if content is None:
        return (None, None)
    
    if not content:
        raise ValueError(f"Model returned empty accessory equipment JSON content for {accessory_id}")
    
    if logger:
        logger.log_response("emit_accessory " + accessory_id, content, truncate_at=8000)
    log_entry = None
    if logger:
        log_entry = {
            "step": "accessory",
            "item_id": accessory_id,
            "request_messages": messages,
            "response_content": content,
        }
    try:
        data = json.loads(content)
        # If it's wrapped in an array or object, extract the item
        if "accessoryEquipments" in data and isinstance(data["accessoryEquipments"], list) and len(data["accessoryEquipments"]) > 0:
            accessory_item = data["accessoryEquipments"][0]
        elif "equipments" in data and isinstance(data["equipments"], list) and len(data["equipments"]) > 0:
            accessory_item = data["equipments"][0]
        elif "id" in data and data.get("type") == "ACCESSORY":
            accessory_item = data
        else:
            raise ValueError(f"Invalid accessory equipment JSON format for {accessory_id}: expected accessory equipment object")
        
        # Ensure the ID matches
        if accessory_item.get("id") != accessory_id:
            accessory_item["id"] = accessory_id
        
        # Ensure type is ACCESSORY
        accessory_item["type"] = "ACCESSORY"
        
        # Normalize accessory equipment before wrapping
        normalized_list = fix_equipment_errors([accessory_item])
        normalized_item = normalized_list[0] if normalized_list else accessory_item
        
        return (EquipmentItem(normalized_item), log_entry)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse accessory equipment JSON for {accessory_id}: {e}")

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
):
    """
    Emit a single exercise definition using either deepseek-reasoner @ 64K or deepseek-chat @ 8K.
    
    Args:
        client: OpenAI client
        exercise_id: Placeholder ID (e.g., "EXERCISE_0")
        context_summary: Summarized conversation context
        plan_index: PlanIndex dict containing exercise entry for this ID
        equipment_subset: List of weight-loaded equipment items relevant to this exercise (only those referenced)
        accessory_subset: List of accessory equipment items relevant to this exercise (optional)
        use_reasoner: If True, use reasoner model (slower, potentially higher quality).
                     If False, use chat model (faster, 8K max tokens).
        provided_equipment: Optional dict with 'equipments' and 'accessoryEquipments' keys
        logger: Optional ConversationLogger for debug logging
    
    Returns:
        dict: Single ExerciseDefinition with placeholder IDs, or None if cancelled
    """
    # Find the exercise entry in plan_index
    exercise_entry = None
    for ex in plan_index.get("exercises", []):
        if ex.get("id") == exercise_id:
            exercise_entry = ex
            break
    
    if not exercise_entry:
        raise ValueError(f"Exercise ID {exercise_id} not found in PlanIndex")
    
    exercise_entry_json = json.dumps(exercise_entry, indent=2)
    # Short list: id, type, name only for relevant equipment (subset used by this exercise)
    equipment_list_short = format_equipment_list_for_plan(equipment_subset, accessory_subset)
    
    # Include accessory equipment if available (id/type/name already in equipment_list_short)
    accessory_json_text = ""
    if accessory_subset:
        accessory_json = json.dumps({"accessoryEquipments": accessory_subset}, indent=2)
        accessory_json_text = f"\nRelevant accessory equipment:\n{accessory_json}\n"
    
    # Weight combinations only for equipment used by this exercise (subset), not entire gym
    equipment_combinations_info = []
    for eq in equipment_subset:
        eq_id = eq.get("id", "Unknown")
        eq_name = eq.get("name", "Unknown")
        eq_type = eq.get("type", "").upper()
        valid_combinations = calculate_equipment_weight_combinations(eq)
        if valid_combinations:
            sorted_combos = sorted(valid_combinations)
            combo_str = ", ".join(f"{w}kg" for w in sorted_combos)
            total_count = len(sorted_combos)
            equipment_combinations_info.append(f"  - {eq_id} ({eq_name}, {eq_type}): {combo_str} (total {total_count} combinations)")
        else:
            equipment_combinations_info.append(f"  - {eq_id} ({eq_name}, {eq_type}): (none calculated)")
    combinations_text = ""
    if equipment_combinations_info:
        combinations_text = (
            "\n\nValid weight combinations for equipment used by this exercise:\n"
            + "\n".join(equipment_combinations_info)
            + "\n\nUse only equipment from the list above. "
            "For WEIGHT exercises, all WeightSet weights must be from the valid combinations shown. "
            "For BODY_WEIGHT exercises, all BodyWeightSet additionalWeight values must be from the valid combinations shown.\n"
        )
    
    # Check if plan entry specifies requiredAccessoryEquipmentIds
    plan_accessory_ids = exercise_entry.get("requiredAccessoryEquipmentIds", [])
    accessory_hint = ""
    if plan_accessory_ids:
        accessory_hint = f"\nIMPORTANT: The plan entry specifies requiredAccessoryEquipmentIds: {plan_accessory_ids}. Copy this list exactly in the exercise definition (same IDs, no extras, no omissions).\n"
    elif accessory_subset:
        accessory_hint = "\nIMPORTANT: The plan entry requiredAccessoryEquipmentIds is empty. Use an empty array [] for requiredAccessoryEquipmentIds.\n"
    
    # Build explicit instructions from plan entry (numWorkSets, restBetweenSetsSeconds, minReps, maxReps)
    plan_spec_lines = []
    num_work_sets = exercise_entry.get("numWorkSets")
    if num_work_sets is not None and exercise_entry.get("exerciseType") not in ("COUNTDOWN", "COUNTUP"):
        plan_spec_lines.append(f"This exercise has exactly {num_work_sets} work sets. Emit exactly {num_work_sets} work sets (with RestSets between them).")
    rest_between = exercise_entry.get("restBetweenSetsSeconds")
    if rest_between is not None:
        plan_spec_lines.append(f"Rest between sets: {rest_between} seconds.")
    min_reps = exercise_entry.get("minReps")
    max_reps = exercise_entry.get("maxReps")
    if min_reps is not None and max_reps is not None and exercise_entry.get("exerciseType") not in ("COUNTDOWN", "COUNTUP"):
        plan_spec_lines.append(f"Rep range: minReps={min_reps}, maxReps={max_reps}. Set minReps and maxReps accordingly and use a representative rep value within that range for each work set.")
    plan_spec_instructions = "\n".join(plan_spec_lines)
    if plan_spec_instructions:
        plan_spec_instructions = "CRITICAL - Follow these exact specifications from the plan:\n" + plan_spec_instructions + "\n\n"

    valid_muscle_groups = (
        JSON_SCHEMA.get("$defs", {})
        .get("MuscleGroup", {})
        .get("enum", [])
    )
    muscle_group_enum_text = ", ".join(valid_muscle_groups)
    
    user_content = (
        "CRITICAL: Use a movement-only exercise name. Remove equipment/accessory words and remove set/time details from the name.\n"
        "Examples: 'Barbell Back Squat' -> 'Back Squat', 'DB Bulgarian Split Squat' -> 'Bulgarian Split Squat', "
        "'Cable Triceps Pushdown' -> 'Triceps Pushdown', 'Warm up (spin bike)' -> 'Warm Up'.\n\n"
        f"{plan_spec_instructions}"
        f"Plan entry for {exercise_id}:\n{exercise_entry_json}\n\n"
        f"Relevant equipment (id, type, name):\n{equipment_list_short}\n"
        f"{accessory_json_text}"
        f"{combinations_text}\n"
        f"Generate ONLY this one exercise definition using placeholder IDs. "
        f"Output format should match $defs.Exercise from the schema. "
        f"Use placeholder ID: {exercise_id} for the exercise, SET_X for sets, "
        f"and reference equipment using EQUIPMENT_X placeholders.\n"
        f"CRITICAL: muscleGroups must be a non-empty array using ONLY these valid enum values:\n"
        f"{muscle_group_enum_text}\n"
        f"Set requiredAccessoryEquipmentIds to EXACTLY match plan entry requiredAccessoryEquipmentIds.\n"
        f"{accessory_hint}"
        f"IMPORTANT: Set requiresLoadCalibration to true ONLY if the user explicitly requested calibration sets for this exercise. "
        f"Otherwise, default to false. Calibration sets are only applicable to WEIGHT exercises or BODY_WEIGHT exercises with equipment.\n"
        f"Output only the exercise object JSON, not a wrapper."
    )
    
    max_attempts = 4
    attempt = 1
    last_error = None
    last_content = None

    def _emit_log(msg):
        if logger:
            logger.log_print(msg)
        else:
            print(msg)

    def _path_to_parts(path):
        if not isinstance(path, str) or not path.startswith("/"):
            return []
        parts = []
        for token in path.strip("/").split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if token.isdigit():
                parts.append(int(token))
            else:
                parts.append(token)
        return parts

    def _scoped_errors_from_validation_message(error_text):
        if not error_text:
            return []
        segments = [seg.strip() for seg in str(error_text).split(" | ") if seg.strip()]
        scoped = []

        def add(path, message, validator="type"):
            scoped.append(
                SimpleNamespace(
                    message=message,
                    absolute_path=_path_to_parts(path),
                    validator=validator,
                )
            )

        for seg in segments:
            lower = seg.lower()
            if "empty musclegroups array" in lower or "invalid muscle group values" in lower:
                add("/muscleGroups", seg, "minItems")
            elif "invalid secondarymusclegroups values" in lower:
                add("/secondaryMuscleGroups", seg, "minItems")
            elif "contains set type" in lower or "set type" in lower or "weightset weights" in lower:
                add("/sets", seg, "oneOf")
            elif "minreps" in lower or "maxreps" in lower:
                add("/minReps", seg, "minimum")
                add("/maxReps", seg, "minimum")
            elif "equipmentid" in lower and "references" in lower:
                add("/equipmentId", seg, "enum")
            elif "requiredaccessoryequipmentids" in lower:
                add("/requiredAccessoryEquipmentIds", seg, "enum")
            elif "minloadpercent" in lower or "maxloadpercent" in lower or "load percentages" in lower:
                add("/minLoadPercent", seg, "minimum")
                add("/maxLoadPercent", seg, "maximum")

        return scoped

    def _repair_exercise_with_json_patch(exercise_obj, validation_error_text):
        scoped_errors = _scoped_errors_from_validation_message(validation_error_text)
        if not scoped_errors:
            raise ValueError("Cannot derive scoped error paths for exercise patch repair")

        allowed_paths, allowed_descendant_paths = build_allowed_patch_scope(scoped_errors)
        allowed_paths_list = sorted(normalize_json_pointer(p) for p in allowed_paths if p is not None)
        allowed_descendant_paths_list = sorted(
            normalize_json_pointer(p) for p in allowed_descendant_paths if p is not None
        )
        exercise_schema_json = json.dumps(EXERCISE_SCHEMA, indent=2)
        muscle_group_enum_text = ", ".join(valid_muscle_groups)
        exercise_type_enum = JSON_SCHEMA.get("$defs", {}).get("ExerciseType", {}).get("enum", [])
        exercise_category_enum = JSON_SCHEMA.get("$defs", {}).get("ExerciseCategory", {}).get("enum", [])
        exercise_type_enum_text = ", ".join(exercise_type_enum)
        exercise_category_enum_text = ", ".join(exercise_category_enum)
        equipment_ids_text = ", ".join(
            sorted(eq.get("id") for eq in (equipment_subset or []) if isinstance(eq, dict) and eq.get("id"))
        ) or "(none)"
        accessory_ids_text = ", ".join(
            sorted(acc.get("id") for acc in (accessory_subset or []) if isinstance(acc, dict) and acc.get("id"))
        ) or "(none)"
        plan_entry_text = json.dumps(exercise_entry, indent=2)

        errors_text = "\n".join(f"- {err.message}" for err in scoped_errors)
        exercise_json_str = json.dumps(exercise_obj, indent=2)
        patch_user_content = (
            f"Context summary:\n{context_summary}\n\n"
            f"Plan entry for this exercise:\n{plan_entry_text}\n\n"
            f"Validation errors for this exercise:\n{errors_text}\n\n"
            f"Exercise JSON (with errors):\n{exercise_json_str}\n\n"
            f"Exercise schema ($defs.Exercise):\n{exercise_schema_json}\n\n"
            f"Valid ExerciseType values: {exercise_type_enum_text}\n"
            f"Valid ExerciseCategory values: {exercise_category_enum_text}\n"
            f"Valid MuscleGroup enum values: {muscle_group_enum_text}\n"
            f"Available equipment IDs for this exercise: {equipment_ids_text}\n"
            f"Available accessory IDs for this exercise: {accessory_ids_text}\n\n"
            "Generate a JSON Patch (RFC 6902) array for this exercise object only. "
            "CRITICAL: JSON Pointer paths are relative to this exercise object root. "
            "Do NOT use paths starting with /workouts, /exercises, /equipments, or any outer wrapper.\n"
            f"Allowed exact patch paths: {allowed_paths_list}\n"
            f"Allowed descendant patch roots: {allowed_descendant_paths_list}\n"
            "Fix ONLY the highlighted validation issues. "
            "Do NOT modify fields outside the failing paths. "
            "Any value written to muscleGroups/secondaryMuscleGroups MUST use only valid MuscleGroup enum values above.\n"
            "Output only the JSON Patch array."
        )
        patch_messages = [
            {"role": "system", "content": BASE_SYSTEM_PROMPT},
            {"role": "system", "content": JSON_PATCH_REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": patch_user_content},
        ]

        if logger:
            trunc = patch_user_content[:2000] + (f"... [truncated, total {len(patch_user_content)} chars]" if len(patch_user_content) > 2000 else "")
            logger.log_request("repair_exercise_with_json_patch " + exercise_id, trunc)
        patch_content = json_call_reasoner_only_with_loading(
            client,
            patch_messages,
            "",
            show_loading=False,
            logger=logger,
        )
        if patch_content is None:
            return None
        if not patch_content:
            raise ValueError("Model returned empty JSON Patch content for exercise repair")
        if logger:
            logger.log_response("repair_exercise_with_json_patch " + exercise_id, patch_content, truncate_at=8000)

        patch = json.loads(patch_content)
        if isinstance(patch, list):
            patch_array = patch
        elif isinstance(patch, dict) and isinstance(patch.get("patch"), list):
            patch_array = patch["patch"]
        else:
            raise ValueError("Invalid JSON Patch format: expected array of patch operations")

        validate_patch_operations_scope(patch_array, allowed_paths, allowed_descendant_paths)
        repaired = apply_json_patch(exercise_obj, patch_array)
        changed_paths = collect_changed_json_paths(exercise_obj, repaired)
        validate_changed_paths_scope(changed_paths, allowed_paths, allowed_descendant_paths)
        return repaired

    while attempt <= max_attempts:
        retry_context = ""
        if attempt == 1 and contract_error_context:
            retry_context = (
                "\n\nCONTRACT RETRY CONTEXT:\n"
                f"The previous emitted exercise failed Step 3 contract validation with:\n{contract_error_context}\n\n"
                "Regenerate this exercise so it matches the plan entry exactly, while still satisfying schema constraints.\n"
                "Output only valid exercise JSON.\n"
            )
        elif last_error:
            previous_output = (last_content or "")[:3500]
            retry_context = (
                "\n\nAUTO-HEAL RETRY CONTEXT:\n"
                f"Previous attempt failed validation/parsing with error:\n{last_error}\n\n"
                "Regenerate the FULL exercise object and fix all issues.\n"
                "CRITICAL: muscleGroups must be a non-empty array of valid enum values.\n"
                "Do not return explanations. Return only valid exercise JSON.\n"
                f"Previous invalid JSON snippet:\n{previous_output}\n"
            )

        retry_user_content = user_content + retry_context
        messages = [
            {"role": "system", "content": BASE_SYSTEM_PROMPT},
            {"role": "system", "content": EXERCISE_SYSTEM_PROMPT},
            {"role": "user", "content": retry_user_content}
        ]

        if logger:
            request_truncate = PARALLEL_LOG_REQUEST_TRUNCATE if getattr(logger, "is_parallel", False) else 2000
            trunc = retry_user_content[:request_truncate] + (f"... [truncated, total {len(retry_user_content)} chars]" if request_truncate and len(retry_user_content) > request_truncate else "")
            logger.log_request("emit_exercise " + exercise_id, trunc)
        # Always use reasoner during auto-heal retries for higher repair quality.
        use_reasoner_for_this_attempt = use_reasoner or bool(last_error) or bool(contract_error_context)
        if use_reasoner_for_this_attempt:
            content = json_call_reasoner_only_with_loading(client, messages, "", show_loading=False, logger=logger)
        else:
            content = json_call_chat_max_with_loading(client, messages, "", show_loading=False, logger=logger)
        if content is None:
            return (None, None)
        if not content:
            last_error = f"Model returned empty exercise JSON content for {exercise_id}"
            last_content = content
            if attempt >= max_attempts:
                raise ValueError(
                    f"Exercise '{exercise_id}' failed after {max_attempts} auto-heal attempts. "
                    f"Last error: {last_error}"
                )
            attempt += 1
            _emit_log(f"  Retrying {exercise_id} with auto-heal (attempt {attempt})...")
            continue

        if logger:
            logger.log_response("emit_exercise " + exercise_id, content, truncate_at=8000)
        log_entry = None
        if logger:
            log_entry = {
                "step": "exercise",
                "item_id": exercise_id,
                "request_messages": messages,
                "response_content": content,
            }

        try:
            data = json.loads(content)
            # If it's wrapped in an "exercises" array, extract the first item
            if "exercises" in data and isinstance(data["exercises"], list) and len(data["exercises"]) > 0:
                exercise_item = data["exercises"][0]
            elif "id" in data and data.get("type") == "Exercise":
                # It's already a single exercise object
                exercise_item = data
            else:
                raise ValueError(f"Invalid exercise JSON format for {exercise_id}: expected exercise object or exercises array")

            # Ensure the ID matches
            if exercise_item.get("id") != exercise_id:
                exercise_item["id"] = exercise_id

            # Normalize requiredAccessoryEquipmentIds to empty array if None
            if exercise_item.get("requiredAccessoryEquipmentIds") is None:
                exercise_item["requiredAccessoryEquipmentIds"] = []

            # Normalize requiresLoadCalibration: True for WEIGHT exercises and BODY_WEIGHT with equipment
            if exercise_item.get("requiresLoadCalibration") is None:
                exercise_type = exercise_item.get("exerciseType")
                equipment_id = exercise_item.get("equipmentId")
                if exercise_type == "WEIGHT" or (exercise_type == "BODY_WEIGHT" and equipment_id is not None):
                    exercise_item["requiresLoadCalibration"] = True
                else:
                    exercise_item["requiresLoadCalibration"] = False

            # Finalize and validate this exercise before adding it to exercise_definitions.
            normalized_item = finalize_and_validate_exercise_definition(
                exercise_item,
                equipment_subset=equipment_subset,
                accessory_subset=accessory_subset,
                all_equipment_candidates=(provided_equipment or {}).get("equipments", []) if isinstance(provided_equipment, dict) else None,
            )

            return (ExerciseDefinition(normalized_item), log_entry)
        except Exception as e:
            last_error = str(e)
            last_content = content

            # If exercise JSON parsed successfully, try scoped JSON Patch repair first.
            try:
                parsed = json.loads(content)
                if "exercises" in parsed and isinstance(parsed["exercises"], list) and len(parsed["exercises"]) > 0:
                    exercise_item = parsed["exercises"][0]
                elif "id" in parsed and parsed.get("type") == "Exercise":
                    exercise_item = parsed
                else:
                    exercise_item = None
            except Exception:
                exercise_item = None

            if isinstance(exercise_item, dict):
                try:
                    if exercise_item.get("id") != exercise_id:
                        exercise_item["id"] = exercise_id
                    patched_item = _repair_exercise_with_json_patch(exercise_item, last_error)
                    if patched_item is not None:
                        normalized_item = finalize_and_validate_exercise_definition(
                            patched_item,
                            equipment_subset=equipment_subset,
                            accessory_subset=accessory_subset,
                            all_equipment_candidates=(provided_equipment or {}).get("equipments", []) if isinstance(provided_equipment, dict) else None,
                        )
                        _emit_log(f"  Patched {exercise_id} with scoped JSON Patch auto-heal.")
                        return (ExerciseDefinition(normalized_item), log_entry)
                except Exception as patch_error:
                    last_error = f"{last_error} | JSON Patch repair failed: {patch_error}"

            if attempt >= max_attempts:
                raise ValueError(
                    f"Exercise '{exercise_id}' failed after {max_attempts} auto-heal attempts. "
                    f"Last error: {last_error}"
                )
            attempt += 1
            _emit_log(f"  Retrying {exercise_id} with auto-heal (attempt {attempt})...")
            continue

    raise ValueError(
        f"Exercise '{exercise_id}' failed after {max_attempts} auto-heal attempts. "
        f"Last error: {last_error or 'unknown error'}"
    )

def emit_workout_structure(workout_id, client, context_summary, plan_index, exercise_index, use_reasoner=True, logger=None):
    """
    Emit a single workout structure using either deepseek-reasoner @ 64K or deepseek-chat @ 8K.
    
    Args:
        client: OpenAI client
        workout_id: Placeholder ID (e.g., "WORKOUT_0")
        context_summary: Summarized conversation context
        plan_index: PlanIndex dict containing workout entry for this ID
        exercise_index: Dict mapping exercise_id -> ExerciseDefinition for exercises referenced in this workout
        use_reasoner: If True, use reasoner model (slower, potentially higher quality).
                     If False, use chat model (faster, 8K max tokens).
        logger: Optional ConversationLogger for debug logging
    
    Returns:
        dict: Single WorkoutStructure with placeholder IDs, or None if cancelled
    """
    # Find the workout entry in plan_index
    workout_entry = None
    for wo in plan_index.get("workouts", []):
        if wo.get("id") == workout_id:
            workout_entry = wo
            break
    
    if not workout_entry:
        raise ValueError(f"Workout ID {workout_id} not found in PlanIndex")
    
    workout_entry_json = json.dumps(workout_entry, indent=2)
    
    # Build minimal exercise reference list (just IDs and names for context)
    exercise_refs = []
    for ex_id in workout_entry.get("exerciseIds", []):
        if ex_id in exercise_index:
            ex = exercise_index[ex_id]
            exercise_refs.append({
                "id": ex_id,
                "name": ex.get("name", "Unknown"),
                "exerciseType": ex.get("exerciseType", "WEIGHT")
            })
    
    exercise_refs_json = json.dumps({"exercises": exercise_refs}, indent=2)
    
    # When plan entry provides restToNextSeconds (same order as exerciseIds), instruct to use those values exactly
    rest_to_next_instruction = ""
    rest_to_next_seconds = workout_entry.get("restToNextSeconds")
    exercise_ids_ordered = workout_entry.get("exerciseIds", [])
    if rest_to_next_seconds is not None and isinstance(rest_to_next_seconds, list) and len(rest_to_next_seconds) == len(exercise_ids_ordered):
        pairs = [f"after {ex_id}: {sec}s" for ex_id, sec in zip(exercise_ids_ordered, rest_to_next_seconds)]
        rest_to_next_instruction = (
            "CRITICAL - Rest between exercises: Use these EXACT rest durations (in seconds) after each exercise, in order: "
            + ", ".join(pairs) + ". "
            "Do NOT use 180 or 120 unless listed. After the last exercise the value is 0: do NOT add a Rest component after the last exercise.\n\n"
        )
    
    user_content = (
        "Base the workout on the plan entry; preserve user-specified day names and exercise order.\n\n"
        f"{rest_to_next_instruction}"
        f"Plan entry for {workout_id}:\n{workout_entry_json}\n\n"
        f"Available exercises (references):\n{exercise_refs_json}\n\n"
        f"Generate ONLY this one workout structure using placeholder IDs. "
        f"Output format should match WORKOUT_STRUCTURE_EXAMPLE. "
        f"Use placeholder ID: {workout_id} for the workout, "
        f"reference exercises using EXERCISE_X placeholders, "
        f"and use COMPONENT_X for Rest components and Supersets.\n\n"
        f"IMPORTANT: Generate a specific description for workoutMetadata.description based on the actual exercises provided above. "
        f"Make it specific to the exercises in this workout (e.g., muscle groups, primary exercises, or training focus), "
        f"not a generic description. Keep it under 50 characters.\n\n"
        f"Output only the workout structure JSON (workoutMetadata + workoutComponents), not a wrapper."
    )
    
    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "system", "content": WORKOUT_STRUCTURE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    
    if logger:
        request_truncate = PARALLEL_LOG_REQUEST_TRUNCATE if getattr(logger, "is_parallel", False) else 2000
        trunc = user_content[:request_truncate] + (f"... [truncated, total {len(user_content)} chars]" if request_truncate and len(user_content) > request_truncate else "")
        logger.log_request("emit_workout_structure " + workout_id, trunc)
    if use_reasoner:
        content = json_call_reasoner_only_with_loading(client, messages, "", show_loading=False, logger=logger)
    else:
        content = json_call_chat_max_with_loading(client, messages, "", show_loading=False, logger=logger)
    if content is None:
        return (None, None)
    
    if not content:
        raise ValueError(f"Model returned empty workout structure JSON content for {workout_id}")
    
    if logger:
        logger.log_response("emit_workout_structure " + workout_id, content, truncate_at=8000)
    log_entry = None
    if logger:
        log_entry = {
            "step": "workout_structure",
            "item_id": workout_id,
            "request_messages": messages,
            "response_content": content,
        }
    try:
        data = json.loads(content)
        # If it's wrapped, try to extract workoutMetadata and workoutComponents
        if "workoutMetadata" in data and "workoutComponents" in data:
            workout_structure = data
        elif "workouts" in data and isinstance(data["workouts"], list) and len(data["workouts"]) > 0:
            # Try to extract from a workouts array (unlikely but handle it)
            wo = data["workouts"][0]
            workout_structure = {
                "workoutMetadata": {
                    "name": wo.get("name", ""),
                    "description": wo.get("description", ""),
                    "order": wo.get("order", 0),
                    "enabled": wo.get("enabled", True),
                    "usePolarDevice": wo.get("usePolarDevice", False),
                    "creationDate": wo.get("creationDate", date.today().isoformat()),
                    "isActive": wo.get("isActive", True),
                    "timesCompletedInAWeek": wo.get("timesCompletedInAWeek"),
                    "type": wo.get("type", 0)
                },
                "workoutComponents": wo.get("workoutComponents", [])
            }
        else:
            raise ValueError(f"Invalid workout structure JSON format for {workout_id}: expected workoutMetadata and workoutComponents")
        
        # Enforce plan contract for workout identity fields regardless of LLM drift.
        metadata = workout_structure.setdefault("workoutMetadata", {})
        metadata["id"] = workout_id
        if workout_entry.get("name"):
            metadata["name"] = workout_entry.get("name")
        
        return (WorkoutStructure(workout_structure), log_entry)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse workout structure JSON for {workout_id}: {e}")

def parallel_emit_items(items, emitter_func, loading_message, max_workers=None, logger=None, fail_fast=False):
    """
    Execute emitter function for multiple items in parallel using ThreadPoolExecutor.

    Args:
        items: List of tuples (item_id, emitter_args_dict) where emitter_args_dict contains
               the arguments needed to call the emitter function (excluding item_id).
        emitter_func: Function to call for each item. Should take item_id as first arg,
                      followed by unpacked **emitter_args_dict. Returns (result, log_entry)
                      where log_entry may be None.
        loading_message: Base message for progress indicator (e.g., "Generating equipment")
        max_workers: Maximum number of worker threads (default: min(32, len(items) + 4))
        logger: Optional ConversationLogger for debug logging (loading start/stop)
        fail_fast: If True, stop/cancel remaining work when any item fails and raise.

    Returns:
        tuple: (results_dict, emitter_conversations_list) where results_dict maps item_id
               to result (or None if cancelled/failed), and emitter_conversations_list
               contains log_entry dicts from emitters for persistence in conversation_history.
    """
    if not items:
        return ({}, [])

    def _out(msg):
        if logger:
            logger.log_print(msg)
        else:
            print(msg)

    results = {}
    errors = []
    emitter_conversations = []
    emitter_conversations_lock = threading.Lock()
    cancelled = threading.Event()
    loading = ParallelLoadingIndicator(loading_message, len(items))
    if logger:
        logger.log("Loading started: " + loading_message)
        logger.log_section(f"Parallel: {loading_message} ({len(items)} items)")

    def emit_wrapper(item_data):
        """Wrapper to handle individual item emission with error handling."""
        if cancelled.is_set():
            return (None, None)

        if isinstance(item_data, tuple) and len(item_data) == 2:
            item_id, emitter_args = item_data
        else:
            item_id = item_data.get("id") if isinstance(item_data, dict) else item_data
            emitter_args = {}

        # Pass a prefixed logger so each item's log lines are identifiable
        args_copy = dict(emitter_args)
        if logger:
            args_copy["logger"] = PrefixLogger(logger, f"[{item_id}] ")

        try:
            result = emitter_func(item_id, **args_copy)
            loading.increment()
            # Emitters return (parsed_result, log_entry)
            if isinstance(result, tuple) and len(result) == 2:
                parsed_result, log_entry = result
                if log_entry is not None:
                    with emitter_conversations_lock:
                        emitter_conversations.append(log_entry)
                return (item_id, parsed_result)
            return (item_id, result)
        except KeyboardInterrupt:
            cancelled.set()
            return (item_id, None)
        except Exception as e:
            loading.increment()
            errors.append((item_id, str(e)))
            if fail_fast:
                cancelled.set()
            return (item_id, None)

    loading.start()

    try:
        if max_workers is None:
            max_workers = min(32, len(items) + 4)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {executor.submit(emit_wrapper, item): item for item in items}

            for future in as_completed(future_to_item):
                if cancelled.is_set():
                    for f in future_to_item:
                        f.cancel()
                    break

                try:
                    item_id, result = future.result()
                    if item_id:
                        results[item_id] = result
                except Exception as e:
                    item_data = future_to_item[future]
                    if isinstance(item_data, tuple):
                        item_id = item_data[0]
                    else:
                        item_id = item_data.get("id") if isinstance(item_data, dict) else str(item_data)
                    errors.append((item_id, str(e)))
                    results[item_id] = None

    except KeyboardInterrupt:
        cancelled.set()
        _out("\nCancelled. Stopping parallel execution...")
    finally:
        loading.stop()
        if logger:
            logger.log_section(f"End parallel: {loading_message}")
            logger.log("Loading finished: " + loading_message)

    if errors:
        _out(f"  Warning: {len(errors)} item(s) failed:")
        for item_id, error_msg in errors[:5]:
            _out(f"    - {item_id}: {error_msg}")
        if len(errors) > 5:
            _out(f"    ... and {len(errors) - 5} more error(s)")
        if fail_fast:
            first_item, first_error = errors[0]
            raise RuntimeError(
                f"{loading_message} failed (fail-fast) on '{first_item}': {first_error}"
            )

    return (results, emitter_conversations)























def validate_and_repair_placeholder_json(client, context_summary, placeholder_json, max_attempts=5,
                                         session_id=None, step_data=None, custom_prompt="",
                                         conversation_hash="", id_manager=None, script_dir=None,
                                         resume_best_json=None, resume_best_error_count=None,
                                         timing_data=None, use_reasoner_for_emitting=None, logger=None):
    """
    Validate placeholder-based WorkoutStore and repair errors using JSON Patch in a loop.
    
    Args:
        client: OpenAI client
        context_summary: Summarized conversation context
        placeholder_json: Placeholder-based WorkoutStore to validate and repair
        max_attempts: Maximum number of repair attempts
        session_id: Optional session ID for progress saving
        step_data: Optional dict to update with progress data
        custom_prompt: Optional custom prompt for progress saving
        conversation_hash: Optional conversation hash for progress saving
        id_manager: Optional PlaceholderIdManager for progress saving
        script_dir: Optional script directory for progress saving
        resume_best_json: Optional best JSON state from previous run (for resume)
        resume_best_error_count: Optional best error count from previous run (for resume)
        timing_data: Optional dict to track timing information
        logger: Optional ConversationLogger for debug logging
    
    Returns:
        dict: Validated and repaired placeholder WorkoutStore, or raises exception if repair fails
    """
    def _out(msg):
        if logger:
            logger.log_print(msg)
        else:
            print(msg)
    if validate is None:
        # No validation available, return as-is
        return placeholder_json
    
    placeholder_schema = create_placeholder_schema()
    
    # Initialize state: use resume data if provided, otherwise start fresh
    if resume_best_json is not None:
        current_json = resume_best_json
        best_error_count = resume_best_error_count if resume_best_error_count is not None else float('inf')
        _out(f"  Resuming with best state (previous best error count: {resume_best_error_count if resume_best_error_count is not None else 'N/A'})")
    else:
        current_json = placeholder_json
        best_error_count = float('inf')
    
    best_json = current_json
    attempt = 0
    
    # Track if we should save progress (only if session_id and related params are provided)
    should_save_progress = (session_id is not None and step_data is not None and 
                           id_manager is not None and script_dir is not None)
    
    while attempt < max_attempts:
        attempt += 1
        
        # Pre-validation normalization: Fix equipment structure issues before schema validation
        if "equipments" in current_json:
            equipments_before = len(current_json["equipments"])
            current_json["equipments"] = fix_equipment_errors(current_json["equipments"])
            equipments_after = len(current_json["equipments"])
            if equipments_before != equipments_after:
                _out(f"  Auto-fixed equipment structure issues (removed {equipments_before - equipments_after} invalid equipment item(s))")
        
        # Custom validation: Check and fix equipment weight combinations before schema validation
        equipment_by_id = {eq.get("id"): eq for eq in current_json.get("equipments", [])}
        weight_fixes_applied = []
        
        # Check all exercises in workouts
        for workout in current_json.get("workouts", []):
            for component in workout.get("workoutComponents", []):
                if component.get("type") == "Exercise":
                    fixes = fix_equipment_weights(component, equipment_by_id)
                    weight_fixes_applied.extend(fixes)
                elif component.get("type") == "Superset":
                    for ex in component.get("exercises", []):
                        fixes = fix_equipment_weights(ex, equipment_by_id)
                        weight_fixes_applied.extend(fixes)
        
        if weight_fixes_applied:
            _out(f"  Auto-fixed {len(weight_fixes_applied)} equipment weight combination issue(s)")
        
        # Pre-validation normalization: Fix TimedDurationSet/EnduranceSet to use timeInMillis instead of timeInSeconds
        for workout in current_json.get("workouts", []):
            for component in workout.get("workoutComponents", []):
                if component.get("type") == "Exercise":
                    if "sets" in component:
                        component["sets"] = fix_set_errors(component["sets"])
                elif component.get("type") == "Superset":
                    for ex in component.get("exercises", []):
                        if "sets" in ex:
                            ex["sets"] = fix_set_errors(ex["sets"])
        
        try:
            validate(instance=current_json, schema=placeholder_schema)
            # Validation passed!
            if attempt > 1:
                _out(f"✓ Validation passed after {attempt} repair attempt(s)")
            
            # Save final success state if progress saving is enabled
            if should_save_progress:
                step_data["step_6_validated_placeholder_store"] = current_json
                step_data["step_6_best_json"] = current_json
                step_data["step_6_best_error_count"] = 0
                step_data["step_6_current_attempt"] = attempt
                _, _ = save_generation_progress(session_id, 6, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
            
            return current_json
        except Exception as validation_err:
            # Count validation errors
            error_count = 0
            if hasattr(validation_err, 'context') and validation_err.context:
                error_count = len(validation_err.context)
            else:
                error_count = 1
            
            # Update best state if this is better
            if error_count < best_error_count:
                best_error_count = error_count
                best_json = copy.deepcopy(current_json)
                
                # Save progress if error count improved
                if should_save_progress:
                    step_data["step_6_best_json"] = best_json
                    step_data["step_6_best_error_count"] = best_error_count
                    step_data["step_6_current_attempt"] = attempt
                    _, _ = save_generation_progress(session_id, 5, step_data, custom_prompt, conversation_hash, id_manager, script_dir, timing_data, use_reasoner_for_emitting)
            
            if attempt >= max_attempts:
                # Max attempts reached
                raise Exception(f"Validation failed after {max_attempts} repair attempts. Last error count: {error_count}. Best error count achieved: {int(best_error_count) if best_error_count != float('inf') else 'N/A'}. Last error: {str(validation_err)}")
            
            # Collect all errors
            errors_to_fix = []
            if hasattr(validation_err, 'context') and validation_err.context:
                errors_to_fix = list(validation_err.context)
            else:
                errors_to_fix = [validation_err]
            
            # Analyze and log errors
            error_analysis, log_filepath = analyze_and_log_validation_errors(errors_to_fix, attempt, script_dir)
            
            # Display error counter with enhanced breakdown
            error_summary = error_analysis.get("error_summary", {})
            by_item_type = error_summary.get("by_item_type", {})
            by_error_type = error_summary.get("by_error_type", {})
            common_patterns = error_analysis.get("common_patterns", [])
            
            # Build item type breakdown string
            item_type_parts = []
            for item_type, count in sorted(by_item_type.items(), key=lambda x: x[1], reverse=True):
                # Handle None item_type defensively
                item_type_display = (item_type or "unknown").capitalize()
                item_type_parts.append(f"{item_type_display}({count})")
            item_type_str = ", ".join(item_type_parts) if item_type_parts else "Unknown"
            
            # Build error type breakdown string
            error_type_parts = []
            for err_type, count in sorted(by_error_type.items(), key=lambda x: x[1], reverse=True):
                error_type_parts.append(f"{err_type}({count})")
            error_type_str = ", ".join(error_type_parts) if error_type_parts else "Unknown"
            
            # Display enhanced error information
            if error_count < best_error_count:
                if best_error_count == float('inf'):
                    _out(f"  Validation error detected (attempt {attempt}/{max_attempts}), attempting repair... Errors: {error_count}")
                else:
                    _out(f"  Validation error detected (attempt {attempt}/{max_attempts}), attempting repair... Errors: {error_count} (improved from {int(best_error_count)})")
            else:
                _out(f"  Validation error detected (attempt {attempt}/{max_attempts}), attempting repair... Errors: {error_count}")
            
            # Show categorized breakdown
            if by_item_type:
                _out(f"    Errors by item type: {item_type_str}")
            if by_error_type:
                _out(f"    Errors by category: {error_type_str}")
            
            # Show top error patterns
            if common_patterns:
                top_patterns = common_patterns[:3]
                _out(f"    Top issues: {', '.join(top_patterns)}")
            
            # Show log file path
            if log_filepath:
                _out(f"    Detailed errors saved to: {log_filepath}")
            
            # Try to repair
            try:
                repaired_json = repair_with_json_patch(client, context_summary, current_json, errors_to_fix, logger=logger)
                if repaired_json is None:
                    raise Exception("Repair was cancelled")
                # Remove any None values that might have been introduced by JSON patch operations
                current_json = remove_none_from_workout_components(repaired_json, logger=logger)
            except Exception as repair_err:
                _out(f"  Warning: Repair failed: {repair_err}")
                # Continue to next attempt with original error
                continue
    
    # Should not reach here, but return current_json if we do
    return current_json

def repair_with_json_patch(client, context_summary, placeholder_json, validation_errors, logger=None):
    """
    Repair validation errors using JSON Patch (RFC 6902) via deepseek-reasoner @ 64K max.

    Args:
        client: OpenAI client
        context_summary: Summarized conversation context
        placeholder_json: Placeholder-based WorkoutStore with validation errors
        validation_errors: List of validation error messages or single error
        logger: Optional ConversationLogger for debug logging (request/response)

    Returns:
        dict: Repaired placeholder JSON, or None if cancelled
    """
    # Format errors for the prompt
    if not isinstance(validation_errors, list):
        validation_errors = [validation_errors]

    error_messages = []
    for error in validation_errors:
        if hasattr(error, 'message'):
            error_messages.append(str(error.message))
        elif hasattr(error, '__str__'):
            error_messages.append(str(error))
        else:
            error_messages.append(repr(error))

    errors_text = "\n".join(f"- {msg}" for msg in error_messages)
    placeholder_json_str = json.dumps(placeholder_json, indent=2)

    user_content = (
        f"Context summary:\n{context_summary}\n\n"
        f"Validation errors:\n{errors_text}\n\n"
        f"Placeholder JSON (with errors):\n{placeholder_json_str}\n\n"
        f"Generate a JSON Patch (RFC 6902) array that fixes ONLY these validation errors. "
        f"Do NOT introduce new UUIDs - the document uses placeholder IDs (EQUIPMENT_X, EXERCISE_X, etc.). "
        f"Output only the JSON Patch array, not a wrapper."
    )

    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "system", "content": JSON_PATCH_REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]

    if logger:
        trunc = user_content[:2000] + (f"... [truncated, total {len(user_content)} chars]" if len(user_content) > 2000 else "")
        logger.log_request("repair_with_json_patch", trunc)
    content = json_call_reasoner_only_with_loading(client, messages, "Repairing validation errors", show_loading=True, logger=logger)
    if content is None:
        return None

    if logger:
        logger.log_response("repair", content, truncate_at=8000)
    if not content:
        raise ValueError("Model returned empty JSON Patch content")

    try:
        allowed_paths, allowed_descendant_paths = build_allowed_patch_scope(validation_errors)
        patch = json.loads(content)
        # If it's wrapped, try to extract the patch array
        if isinstance(patch, list):
            patch_array = patch
        elif "patch" in patch and isinstance(patch["patch"], list):
            patch_array = patch["patch"]
        else:
            raise ValueError("Invalid JSON Patch format: expected array of patch operations")

        validate_patch_operations_scope(patch_array, allowed_paths, allowed_descendant_paths)

        # Apply the patch
        repaired_json = apply_json_patch(placeholder_json, patch_array)
        changed_paths = collect_changed_json_paths(placeholder_json, repaired_json)
        validate_changed_paths_scope(changed_paths, allowed_paths, allowed_descendant_paths)
        return repaired_json
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON Patch: {e}")
    except Exception as e:
        raise ValueError(f"Failed to apply JSON Patch: {e}")












# Muscle group name mappings for common errors
















def summarize_conversation(client, messages, logger=None):
    """
    Condense conversation history to extract only relevant information for workout generation.
    
    Args:
        client: OpenAI client
        messages: Full conversation message history
        logger: Optional ConversationLogger for debug logging
        
    Returns:
        str: Condensed extraction of essential workout generation information, or None if cancelled
    """
    # Filter out system messages and keep only user/assistant conversation
    conversation_messages = [msg for msg in messages if msg.get("role") in ["user", "assistant"]]
    
    # If conversation is very short, return a simple summary
    if len(conversation_messages) <= 2:
        # Just extract user messages
        user_messages = [msg.get("content", "") for msg in conversation_messages if msg.get("role") == "user"]
        return "\n".join(user_messages) if user_messages else "No specific requirements mentioned."
    
    # Use LLM to summarize the conversation
    user_content = (
        "Extract and condense the following conversation to only the information relevant for workout generation:\n\n"
        + "\n".join([f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')}"
                     for msg in conversation_messages])
    )
    summarization_messages = [
        {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    if logger:
        trunc = user_content[:2000] + (f"... [truncated, total {len(user_content)} chars]" if len(user_content) > 2000 else "")
        logger.log_request("summarize_conversation", f"model=deepseek-reasoner messages={len(summarization_messages)}\n{trunc}")
    content, _ = chat_call_with_loading(client, summarization_messages, logger=logger)
    if content is None:
        return None
    if logger:
        logger.log_response("summarize_conversation", content, truncate_at=8000)
    return content

def generate_index(client, context_summary, custom_request="", use_reasoner=True, provided_equipment=None, logger=None):
    """
    Generate a PlanIndex - a compact plan defining what objects will exist, their placeholder IDs, and relationships.
    This is the planner stage of the planner/emitter architecture.
    
    Args:
        client: OpenAI client
        context_summary: Summarized conversation context
        custom_request: Additional user request (e.g., from /generate command)
        use_reasoner: If True, use reasoner model (slower, potentially higher quality).
                     If False, use chat model (faster, 8000 max tokens).
        provided_equipment: Optional dict with 'equipments' and 'accessoryEquipments' keys
        logger: Optional ConversationLogger for debug logging
        
    Returns:
        dict: PlanIndex with equipments, exercises, and workouts entries, all using placeholder IDs, or None if cancelled
    """
    user_content = f"Context summary:\n{context_summary}\n\n"
    if custom_request:
        user_content += f"Additional request: {custom_request}\n\n"
    
    # Include provided equipment if available (id/type/name only for plan index)
    if provided_equipment:
        formatted_equipment = format_equipment_list_for_plan(
            provided_equipment.get("equipments", []),
            provided_equipment.get("accessoryEquipments", [])
        )
        user_content += (
            f"{formatted_equipment}\n\n"
            f"CRITICAL: Equipment from the provided file is IMMUTABLE - you CANNOT edit, modify, or change any equipment or accessories from the list above.\n"
            f"Use equipment and accessories from the list above when available (use their exact placeholder IDs).\n"
            f"When an exercise requires an accessory that is already in the list above (same name), you MUST use that existing ID. Do NOT create a new accessory with a new ID for the same item.\n"
            f"If necessary equipment or accessories are missing from the list above, you MAY create new equipment or accessory entries with new placeholder IDs.\n"
            f"When creating new equipment or accessories, use new placeholder IDs (EQUIPMENT_X, ACCESSORY_X) that don't conflict with the IDs shown above.\n"
            f"Ensure all equipmentId and requiredAccessoryEquipmentIds values match equipment/accessories from either the provided list OR newly created entries.\n\n"
        )
    
    user_content += (
        "If workout/day names appear in both Context summary and Additional request with different formatting, "
        "prefer the exact names from Context summary.\n\n"
        "Generate the PlanIndex based on this context. Output only the PlanIndex JSON."
    )
    
    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "system", "content": PLAN_INDEX_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    
    if logger:
        trunc = user_content[:2000] + (f"... [truncated, total {len(user_content)} chars]" if len(user_content) > 2000 else "")
        logger.log_request("generate_index", f"model={'reasoner' if use_reasoner else 'chat'} messages={len(messages)}\n{trunc}")
    if use_reasoner:
        content = json_call_reasoner_only_with_loading(client, messages, "Generating plan index", show_loading=True, logger=logger)
    else:
        content = json_call_chat_max_with_loading(client, messages, "Generating plan index", show_loading=True, logger=logger)
    if content is None:
        return None
    if logger:
        logger.log_response("generate_index", content, truncate_at=8000)
    
    if not content:
        raise ValueError("Model returned empty PlanIndex JSON content.")
    
    try:
        plan_index = json.loads(content)
        # Validate basic structure
        if not isinstance(plan_index, dict):
            raise ValueError("Invalid PlanIndex format: must be an object")
        if "equipments" not in plan_index or not isinstance(plan_index["equipments"], list):
            raise ValueError("Invalid PlanIndex format: missing 'equipments' array")
        if "accessoryEquipments" not in plan_index or not isinstance(plan_index["accessoryEquipments"], list):
            raise ValueError("Invalid PlanIndex format: missing 'accessoryEquipments' array")
        if "exercises" not in plan_index or not isinstance(plan_index["exercises"], list):
            raise ValueError("Invalid PlanIndex format: missing 'exercises' array")
        if "workouts" not in plan_index or not isinstance(plan_index["workouts"], list):
            raise ValueError("Invalid PlanIndex format: missing 'workouts' array")
        
        return plan_index
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse PlanIndex JSON: {e}")

# Normalized data structures for planner/emitter architecture
# These are type hints/documentation - actual data is dict-based for JSON compatibility




def self_heal_validation_error(client, workout_json, validation_error, context_summary, max_attempts=3, attempt=1):
    """
    Attempt to self-heal a validation error by sending it to the LLM for fixing.
    Uses targeted healing to fix only the specific failing item, not the entire JSON.
    
    Args:
        client: OpenAI client
        workout_json: The invalid JSON that failed validation
        validation_error: The validation error exception
        context_summary: Summary of generation context
        max_attempts: Maximum number of retry attempts
        attempt: Current attempt number (for recursion)
        
    Returns:
        dict: Fixed JSON that should pass validation
        
    Raises:
        Exception: If healing fails after max attempts
    """
    if attempt > max_attempts:
        raise Exception(f"Self-healing failed after {max_attempts} attempts. Last error: {str(validation_error)}")
    
    # Extract error details
    error_details = extract_validation_error_details(validation_error)
    path_info = error_details.get("path_info", {})
    
    print(f"  Attempt {attempt}/{max_attempts}: Analyzing error...")
    if error_details.get("path"):
        print(f"    Error path: {error_details['path']}")
    if error_details.get("expected"):
        print(f"    Expected: {error_details['expected']}")
    
    # Try to extract the specific failing item
    extracted_data = extract_item_by_path(workout_json, path_info)
    
    if extracted_data is None:
        # Cannot extract specific item (path not parseable), fall back to full JSON healing
        print(f"    Warning: Cannot extract specific item, using full JSON healing (may hit token limits)")
        return self_heal_validation_error_full_json(client, workout_json, validation_error, context_summary, max_attempts, attempt)
    
    item = extracted_data.get("item")
    item_context = extracted_data.get("context", {})
    item_type = extracted_data.get("item_type", "unknown")
    
    print(f"    Extracted {item_type} item for targeted healing")
    
    # Build minimal JSON structure with just the item and context
    minimal_json = {
        "item": item,
        "itemType": item_type,
        "context": item_context
    }
    
    # Build prompt for LLM
    error_message = error_details.get("message", str(validation_error))
    invalid_json_str = json.dumps(minimal_json, indent=2)
    
    heal_messages = [
        {"role": "system", "content": SELF_HEAL_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Fix the following JSON schema validation error:\n\n"
            f"ERROR MESSAGE:\n{error_message}\n\n"
            f"ERROR DETAILS:\n"
            f"- Path: {error_details.get('path', 'Unknown')}\n"
            f"- Expected: {error_details.get('expected', 'Unknown')}\n"
            f"- Actual value: {error_details.get('actual', 'Unknown')}\n"
            f"- Item Type: {item_type}\n\n"
            f"CONTEXT:\n{context_summary}\n\n"
            f"INVALID ITEM (extracted from full structure):\n{invalid_json_str}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Fix ONLY the field(s) causing the validation error in the 'item' field\n"
            f"2. Preserve all other data in the item exactly as-is\n"
            f"3. Return ONLY the fixed item (the value of 'item' after fixing), not the wrapper structure\n"
            f"4. Ensure the fix satisfies the schema requirement: {error_details.get('expected', 'schema constraint')}\n"
            f"5. Use the context provided (equipments, etc.) to make contextually appropriate fixes\n"
        )}
    ]
    
    # Call LLM to get fixed item
    try:
        print(f"    Calling LLM for targeted fix...")
        fixed_json_str = json_call_reasoner_only_with_loading(client, heal_messages, "Fixing validation error")
        
        if fixed_json_str is None:
            raise Exception("LLM call was cancelled")
        
        # Parse the fixed JSON
        try:
            fixed_item_data = json.loads(fixed_json_str)
            # The LLM should return just the fixed item, but might return a wrapper
            if isinstance(fixed_item_data, dict) and "item" in fixed_item_data:
                fixed_item = fixed_item_data["item"]
            else:
                fixed_item = fixed_item_data
        except json.JSONDecodeError as e:
            raise Exception(f"LLM returned invalid JSON: {e}")
        
        # Reassemble the fixed item back into the full structure
        fixed_json = reassemble_item(workout_json, path_info, fixed_item)
        
        # Validate the reassembled JSON
        if validate is not None:
            try:
                validate(instance=fixed_json, schema=JSON_SCHEMA)
                print(f"  ✓ Self-healing successful on attempt {attempt}!")
                return fixed_json
            except Exception as new_error:
                # Still invalid, try again if we have attempts left
                if attempt < max_attempts:
                    print(f"    Validation still failing, retrying...")
                    return self_heal_validation_error(
                        client, 
                        fixed_json, 
                        new_error, 
                        context_summary, 
                        max_attempts, 
                        attempt + 1
                    )
                else:
                    raise Exception(f"Fixed JSON still invalid after {max_attempts} attempts. Last error: {str(new_error)}")
        else:
            # No validation available, return the fixed JSON
            print(f"  ✓ Self-healing completed (validation disabled)")
            return fixed_json
            
    except Exception as e:
        if attempt < max_attempts:
            print(f"    Error during healing, retrying... ({str(e)})")
            return self_heal_validation_error(
                client, 
                workout_json, 
                validation_error, 
                context_summary, 
                max_attempts, 
                attempt + 1
            )
        else:
            raise Exception(f"Self-healing failed: {str(e)}")

def self_heal_validation_error_full_json(client, workout_json, validation_error, context_summary, max_attempts=3, attempt=1):
    """
    Fallback self-healing method that sends the entire JSON (used when path cannot be parsed).
    This is the original implementation kept as a fallback.
    """
    if attempt > max_attempts:
        raise Exception(f"Self-healing failed after {max_attempts} attempts. Last error: {str(validation_error)}")
    
    # Extract error details
    error_details = extract_validation_error_details(validation_error)
    
    print(f"  Attempt {attempt}/{max_attempts}: Analyzing error (full JSON mode)...")
    if error_details.get("path"):
        print(f"    Error path: {error_details['path']}")
    if error_details.get("expected"):
        print(f"    Expected: {error_details['expected']}")
    
    # Build prompt for LLM
    error_message = error_details.get("message", str(validation_error))
    invalid_json_str = json.dumps(workout_json, indent=2)
    
    heal_messages = [
        {"role": "system", "content": SELF_HEAL_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Fix the following JSON schema validation error:\n\n"
            f"ERROR MESSAGE:\n{error_message}\n\n"
            f"ERROR DETAILS:\n"
            f"- Path: {error_details.get('path', 'Unknown')}\n"
            f"- Expected: {error_details.get('expected', 'Unknown')}\n"
            f"- Actual value: {error_details.get('actual', 'Unknown')}\n\n"
            f"CONTEXT:\n{context_summary}\n\n"
            f"INVALID JSON:\n{invalid_json_str}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Fix ONLY the field(s) causing the validation error\n"
            f"2. Preserve all other data exactly as-is\n"
            f"3. Return the complete corrected JSON structure\n"
            f"4. Ensure the fix satisfies the schema requirement: {error_details.get('expected', 'schema constraint')}\n"
        )}
    ]
    
    # Call LLM to get fixed JSON
    try:
        print(f"    Calling LLM for fix...")
        fixed_json_str = json_call_reasoner_only_with_loading(client, heal_messages, "Fixing validation error (full JSON)")
        
        if fixed_json_str is None:
            raise Exception("LLM call was cancelled")
        
        # Parse the fixed JSON
        try:
            fixed_json = json.loads(fixed_json_str)
        except json.JSONDecodeError as e:
            raise Exception(f"LLM returned invalid JSON: {e}")
        
        # Validate the fixed JSON
        if validate is not None:
            try:
                validate(instance=fixed_json, schema=JSON_SCHEMA)
                print(f"  ✓ Self-healing successful on attempt {attempt}!")
                return fixed_json
            except Exception as new_error:
                # Still invalid, try again if we have attempts left
                if attempt < max_attempts:
                    print(f"    Validation still failing, retrying...")
                    return self_heal_validation_error_full_json(
                        client, 
                        fixed_json, 
                        new_error, 
                        context_summary, 
                        max_attempts, 
                        attempt + 1
                    )
                else:
                    raise Exception(f"Fixed JSON still invalid after {max_attempts} attempts. Last error: {str(new_error)}")
        else:
            # No validation available, return the fixed JSON
            print(f"  ✓ Self-healing completed (validation disabled)")
            return fixed_json
            
    except Exception as e:
        if attempt < max_attempts:
            print(f"    Error during healing, retrying... ({str(e)})")
            return self_heal_validation_error_full_json(
                client, 
                workout_json, 
                validation_error, 
                context_summary, 
                max_attempts, 
                attempt + 1
            )
        else:
            raise Exception(f"Self-healing failed: {str(e)}")

def save_workout_to_file(workout_json, script_dir=None):
    """
    Save workout JSON to a timestamped file in the workouts/ directory.
    
    Args:
        workout_json: The complete workout JSON dictionary
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
        filename = f"workout_{timestamp}.json"
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
    Display a summary of the generated workout.
    
    Args:
        workout_json: The complete workout JSON dictionary
        filepath: Path to the saved file
        logger: Optional ConversationLogger for debug logging
    """
    _out = (lambda m: logger.log_print(m)) if logger else (lambda m: print(m))
    workouts = workout_json.get("workouts", [])
    equipments = workout_json.get("equipments", [])
    
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
    _out("Workout Generated Successfully!")
    _out("=" * 70)
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
            1: "Generate plan index",
            2: "Emit equipment items",
            3: "Emit exercise definitions",
            4: "Emit workout structures",
            5: "Assemble placeholder WorkoutStore",
            6: "Validate and repair JSON",
            7: "Convert placeholders to UUIDs"
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
    validate_load_percent_range as _mod_validate_load_percent_range,
    finalize_and_validate_exercise_definition as _mod_finalize_and_validate_exercise_definition,
    generate_recursive_valid_subsets as _mod_generate_recursive_valid_subsets,
    calculate_equipment_weight_combinations as _mod_calculate_equipment_weight_combinations,
    format_equipment_list_for_plan as _mod_format_equipment_list_for_plan,
    format_equipment_for_llm as _mod_format_equipment_for_llm,
    format_equipment_for_conversation as _mod_format_equipment_for_conversation,
    has_equipment_in_messages as _mod_has_equipment_in_messages,
    fix_timed_sets as _mod_fix_timed_sets,
    create_placeholder_schema as _mod_create_placeholder_schema,
    ensure_unique_ids as _mod_ensure_unique_ids,
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
validate_load_percent_range = _mod_validate_load_percent_range
finalize_and_validate_exercise_definition = _mod_finalize_and_validate_exercise_definition
generate_recursive_valid_subsets = _mod_generate_recursive_valid_subsets
calculate_equipment_weight_combinations = _mod_calculate_equipment_weight_combinations
format_equipment_list_for_plan = _mod_format_equipment_list_for_plan
format_equipment_for_llm = _mod_format_equipment_for_llm
format_equipment_for_conversation = _mod_format_equipment_for_conversation
has_equipment_in_messages = _mod_has_equipment_in_messages
fix_timed_sets = _mod_fix_timed_sets
create_placeholder_schema = _mod_create_placeholder_schema
ensure_unique_ids = _mod_ensure_unique_ids
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
