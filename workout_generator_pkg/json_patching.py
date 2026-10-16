"""JSON Patch application and scope guards."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Set, Tuple


def apply_json_patch(json_obj: Dict[str, Any], patch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply RFC 6902 operations atomically; invalid paths never create implicit containers."""
    result = copy.deepcopy(json_obj)

    def tokens(path):
        if not isinstance(path, str) or (path and not path.startswith("/")) or re.search(r"~(?![01])", path):
            raise ValueError(f"Invalid JSON Pointer: {path!r}")
        return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")] if path else []

    def index(part, length, adding=False):
        if adding and part == "-":
            return length
        if not re.fullmatch(r"0|[1-9][0-9]*", part):
            raise ValueError(f"Invalid array index: {part!r}")
        value = int(part)
        if value >= length + int(adding):
            raise ValueError(f"Array index out of range: {part}")
        return value

    def get(parts):
        current = result
        for part in parts:
            if isinstance(current, list):
                current = current[index(part, len(current))]
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise ValueError(f"Patch path does not exist: {parts}")
        return current

    def edit(parts, operation, value=None):
        nonlocal result
        if not parts:
            result = None if operation == "remove" else copy.deepcopy(value)
            return
        parent, key = get(parts[:-1]), parts[-1]
        if isinstance(parent, list):
            position = index(key, len(parent), adding=operation == "add")
            if operation == "add":
                parent.insert(position, copy.deepcopy(value))
            elif operation == "remove":
                parent.pop(position)
            else:
                parent[position] = copy.deepcopy(value)
        elif isinstance(parent, dict):
            if operation != "add" and key not in parent:
                raise ValueError(f"Patch path does not exist: {parts}")
            if operation == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(value)
        else:
            raise ValueError(f"Patch parent is not a container: {parts}")

    def equal(left, right):
        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        if isinstance(left, dict) and isinstance(right, dict):
            return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
        if isinstance(left, list) and isinstance(right, list):
            return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
        return left == right

    if not isinstance(patch, list):
        raise ValueError("Patch must be a list of RFC 6902 operations")
    for operation in patch:
        if not isinstance(operation, dict) or operation.get("op") not in {"add", "remove", "replace", "move", "copy", "test"}:
            raise ValueError(f"Invalid patch operation: {operation!r}")
        op, path = operation["op"], tokens(operation.get("path"))
        if op in {"add", "replace", "test"} and "value" not in operation:
            raise ValueError(f"Patch {op} requires value")
        if op == "test":
            if not equal(get(path), operation["value"]):
                raise ValueError(f"Patch test failed at {operation['path']}")
        elif op in {"move", "copy"}:
            source = tokens(operation.get("from"))
            value = copy.deepcopy(get(source))
            if op == "move":
                if source == path:
                    continue
                if path[:len(source)] == source:
                    raise ValueError("Cannot move a value into its own child")
                edit(source, "remove")
            edit(path, "add", value)
        else:
            if op == "replace":
                get(path)
            edit(path, op, operation.get("value"))
    return result


def escape_json_pointer_token(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def to_json_pointer(path_parts: Iterable[Any]) -> str:
    parts = list(path_parts)
    if not parts:
        return ""
    return "/" + "/".join(escape_json_pointer_token(part) for part in parts)


def normalize_json_pointer(path: Any) -> str:
    if path is None or path == "":
        return ""
    if not isinstance(path, str):
        path = str(path)
    if not path.startswith("/"):
        path = "/" + path
    parts = path.split("/")
    normalized_parts = []
    for part in parts[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        normalized_parts.append(escape_json_pointer_token(part))
    return "/" + "/".join(normalized_parts)


def is_path_allowed(path: Any, allowed_paths: Set[str]) -> bool:
    if "" in allowed_paths:
        return True
    pointer = normalize_json_pointer(path)
    for allowed in allowed_paths:
        allowed_norm = normalize_json_pointer(allowed)
        if pointer == allowed_norm:
            return True
        if allowed_norm and pointer.startswith(allowed_norm + "/"):
            return True
    return False


def is_path_allowed_in_scope(path: Any, allowed_exact_paths: Set[str], allowed_descendant_paths: Set[str]) -> bool:
    pointer = normalize_json_pointer(path)
    if pointer in {normalize_json_pointer(p) for p in allowed_exact_paths}:
        return True
    for allowed in allowed_descendant_paths:
        allowed_norm = normalize_json_pointer(allowed)
        if pointer == allowed_norm:
            return True
        if allowed_norm and pointer.startswith(allowed_norm + "/"):
            return True
    return False


def build_allowed_patch_paths(validation_errors: List[Any]) -> Set[str]:
    allowed: Set[str] = set()
    for error in validation_errors:
        if hasattr(error, "absolute_path"):
            path_parts = list(error.absolute_path)
        else:
            path_parts = []
        base_path = to_json_pointer(path_parts)
        allowed.add(base_path)

        validator = getattr(error, "validator", None)
        message = str(getattr(error, "message", ""))
        if validator == "required":
            m = re.search(r"'([^']+)' is a required property", message)
            if m:
                missing_field = m.group(1)
                required_path_parts = list(path_parts) + [missing_field]
                allowed.add(to_json_pointer(required_path_parts))

    return allowed


def build_allowed_patch_scope(validation_errors: List[Any]) -> Tuple[Set[str], Set[str]]:
    """
    Build strict patch scope from validation errors.

    Returns:
        (allowed_exact_paths, allowed_descendant_paths)
    """
    exact_paths: Set[str] = set()
    descendant_paths: Set[str] = set()

    for error in validation_errors:
        if hasattr(error, "absolute_path"):
            path_parts = list(error.absolute_path)
        else:
            path_parts = []
        base_path = to_json_pointer(path_parts)
        validator = getattr(error, "validator", None)
        message = str(getattr(error, "message", ""))

        if base_path:
            exact_paths.add(base_path)
        else:
            # Avoid allowing root-wide edits by default.
            exact_paths.add("")

        # Leaf-level validators like pattern/const on fields such as /id or /type often
        # need sibling-field repairs on the containing object. Allow descendant edits on
        # the immediate parent object, not just the single failing field.
        if len(path_parts) > 0:
            parent_path = to_json_pointer(path_parts[:-1])
            if parent_path:
                descendant_paths.add(parent_path)

        if validator == "required":
            m = re.search(r"'([^']+)' is a required property", message)
            if m:
                missing_field = m.group(1)
                required_path = to_json_pointer(list(path_parts) + [missing_field])
                exact_paths.add(required_path)
                # Allow filling nested object fields under newly required field.
                descendant_paths.add(required_path)
                if base_path:
                    descendant_paths.add(base_path)

        if validator == "additionalProperties":
            # Example: "Additional properties are not allowed ('foo' was unexpected)"
            found = re.findall(r"'([^']+)'", message)
            for field in found:
                extra_path = to_json_pointer(list(path_parts) + [field])
                exact_paths.add(extra_path)
            if base_path:
                descendant_paths.add(base_path)

        # Container-level validators often require index/key-level fixes.
        if validator in {"minItems", "maxItems", "contains", "uniqueItems", "oneOf", "anyOf", "allOf"}:
            descendant_paths.add(base_path)

    # If root path slipped in from generic errors, do not allow root descendants.
    if "" in descendant_paths:
        descendant_paths.remove("")

    return exact_paths, descendant_paths


def validate_patch_operations_scope(
    patch_array: List[Dict[str, Any]],
    allowed_paths: Set[str],
    allowed_descendant_paths: Set[str] | None = None,
) -> None:
    if not isinstance(patch_array, list):
        raise ValueError("Patch must be a list of RFC 6902 operations")
    descendants = allowed_descendant_paths or set()

    for idx, op in enumerate(patch_array):
        if not isinstance(op, dict):
            raise ValueError(f"Patch operation at index {idx} is not an object")

        op_name = op.get("op")
        op_path = op.get("path")
        if op_path is None:
            raise ValueError(f"Patch operation at index {idx} is missing 'path'")
        if not is_path_allowed_in_scope(op_path, allowed_paths, descendants):
            raise ValueError(
                f"Patch operation {idx} targets path '{op_path}' outside allowed error paths"
            )

        if op_name in ("move", "copy"):
            from_path = op.get("from")
            if from_path is None:
                raise ValueError(f"Patch operation at index {idx} is missing 'from'")
            if not is_path_allowed_in_scope(from_path, allowed_paths, descendants):
                raise ValueError(
                    f"Patch operation {idx} reads from path '{from_path}' outside allowed error paths"
                )


def collect_changed_json_paths(before: Any, after: Any, base_path: str = "") -> Set[str]:
    changed: Set[str] = set()

    if type(before) is not type(after):
        changed.add(normalize_json_pointer(base_path))
        return changed

    if isinstance(before, dict):
        before_keys = set(before.keys())
        after_keys = set(after.keys())
        for key in before_keys | after_keys:
            child_path = f"{base_path}/{escape_json_pointer_token(key)}" if base_path else f"/{escape_json_pointer_token(key)}"
            if key not in before or key not in after:
                changed.add(normalize_json_pointer(child_path))
            else:
                changed.update(collect_changed_json_paths(before[key], after[key], child_path))
        return changed

    if isinstance(before, list):
        max_len = max(len(before), len(after))
        for i in range(max_len):
            child_path = f"{base_path}/{i}" if base_path else f"/{i}"
            if i >= len(before) or i >= len(after):
                changed.add(normalize_json_pointer(child_path))
            else:
                changed.update(collect_changed_json_paths(before[i], after[i], child_path))
        return changed

    if before != after:
        changed.add(normalize_json_pointer(base_path))
    return changed


def validate_changed_paths_scope(
    changed_paths: Set[str],
    allowed_paths: Set[str],
    allowed_descendant_paths: Set[str] | None = None,
) -> None:
    descendants = allowed_descendant_paths or set()
    illegal = [p for p in changed_paths if not is_path_allowed_in_scope(p, allowed_paths, descendants)]
    if illegal:
        sample = ", ".join(illegal[:5])
        raise ValueError(f"Patched JSON modified paths outside allowed error scope: {sample}")
