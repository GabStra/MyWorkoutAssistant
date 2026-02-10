"""JSON Patch application and scope guards."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Set, Tuple


def apply_json_patch(json_obj: Dict[str, Any], patch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply a JSON Patch (RFC 6902) to a JSON object."""
    result = copy.deepcopy(json_obj)

    def get_path(obj: Any, path_str: str) -> Any:
        if path_str == "":
            return obj
        parts = path_str.lstrip("/").split("/")
        current = obj
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx] if 0 <= idx < len(current) else None
                except ValueError:
                    return None
            else:
                return None
            if current is None:
                return None
        return current

    def set_path(obj: Any, path_str: str, value: Any) -> Any:
        if path_str == "":
            return value
        parts = path_str.lstrip("/").split("/")
        current = obj
        for i, part in enumerate(parts[:-1]):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                if part not in current:
                    next_part = parts[i + 1].replace("~1", "/").replace("~0", "~")
                    try:
                        int(next_part)
                        current[part] = []
                    except ValueError:
                        current[part] = {}
                current = current[part]
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    if idx >= len(current):
                        current.extend([None] * (idx - len(current) + 1))
                    current = current[idx]
                except ValueError:
                    return obj
            else:
                return obj

        final_part = parts[-1].replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current[final_part] = value
        elif isinstance(current, list):
            try:
                idx = int(final_part)
                if idx >= len(current):
                    current.extend([None] * (idx - len(current) + 1))
                current[idx] = value
            except ValueError:
                return obj
        return obj

    for operation in patch:
        op = operation.get("op")
        path = operation.get("path", "")

        if op == "add":
            value = operation.get("value")
            if path.endswith("/-") or (
                isinstance(get_path(result, path.rsplit("/", 1)[0]), list) if "/" in path else isinstance(result, list)
            ):
                parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
                parent = get_path(result, parent_path) if parent_path else result
                if isinstance(parent, list):
                    parent.append(value)
                else:
                    set_path(result, path, value)
            else:
                set_path(result, path, value)

        elif op == "remove":
            if "/" in path:
                parent_path = "/".join(path.split("/")[:-1])
                key = path.split("/")[-1].replace("~1", "/").replace("~0", "~")
                parent = get_path(result, parent_path)
                if isinstance(parent, dict):
                    parent.pop(key, None)
                elif isinstance(parent, list):
                    try:
                        idx = int(key)
                        if 0 <= idx < len(parent):
                            parent.pop(idx)
                    except ValueError:
                        pass
            else:
                result.pop(path, None)

        elif op == "replace":
            value = operation.get("value")
            set_path(result, path, value)

        elif op == "move":
            from_path = operation.get("from", "")
            value = get_path(result, from_path)
            if value is not None:
                if "/" in from_path:
                    parent_path = "/".join(from_path.split("/")[:-1])
                    key = from_path.split("/")[-1].replace("~1", "/").replace("~0", "~")
                    parent = get_path(result, parent_path)
                    if isinstance(parent, dict):
                        parent.pop(key, None)
                    elif isinstance(parent, list):
                        try:
                            idx = int(key)
                            if 0 <= idx < len(parent):
                                parent.pop(idx)
                        except ValueError:
                            pass
                else:
                    result.pop(from_path, None)
                set_path(result, path, value)

        elif op == "copy":
            from_path = operation.get("from", "")
            value = get_path(result, from_path)
            if value is not None:
                set_path(result, path, copy.deepcopy(value))

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

        if validator == "required":
            m = re.search(r"'([^']+)' is a required property", message)
            if m:
                missing_field = m.group(1)
                required_path = to_json_pointer(list(path_parts) + [missing_field])
                exact_paths.add(required_path)
                # Allow filling nested object fields under newly required field.
                descendant_paths.add(required_path)

        if validator == "additionalProperties":
            # Example: "Additional properties are not allowed ('foo' was unexpected)"
            found = re.findall(r"'([^']+)'", message)
            for field in found:
                extra_path = to_json_pointer(list(path_parts) + [field])
                exact_paths.add(extra_path)

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
