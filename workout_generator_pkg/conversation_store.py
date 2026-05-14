"""Archived conversation session persistence helpers."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .conversation_meta import get_active_conversation_id, save_conversation_meta
from .paths import (
    get_conversations_dir,
    legacy_conversation_history_path,
)


def _timestamp_now() -> str:
    return datetime.now().isoformat()


def _conversation_dir(conversation_id: str, script_dir: Optional[str] = None) -> str:
    return os.path.join(get_conversations_dir(script_dir), conversation_id)


def _messages_path(conversation_id: str, script_dir: Optional[str] = None) -> str:
    return os.path.join(_conversation_dir(conversation_id, script_dir), "messages.json")


def _metadata_path(conversation_id: str, script_dir: Optional[str] = None) -> str:
    return os.path.join(_conversation_dir(conversation_id, script_dir), "meta.json")


def _ensure_conversation_dir(conversation_id: str, script_dir: Optional[str] = None) -> None:
    os.makedirs(_conversation_dir(conversation_id, script_dir), exist_ok=True)


def _is_valid_message(msg: Dict[str, Any]) -> bool:
    if not isinstance(msg, dict):
        return False
    role = msg.get("role")
    return role in {"system", "user", "assistant", "tool", "emitter"}


def normalize_conversation_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid_messages: List[Dict[str, Any]] = []
    for message in messages:
        if not _is_valid_message(message):
            continue
        valid_messages.append(message)

    normalized: List[Dict[str, Any]] = []
    pending_tool_call_ids: List[str] = []
    responded_ids: set[str] = set()

    def placeholder_tool_message(tool_call_id: str) -> Dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": (
                "Tool call was not completed in the previous session. "
                "Treat this as a failed tool result and continue."
            ),
            "timestamp": _timestamp_now(),
        }

    def flush_pending_tool_calls() -> None:
        for tool_call_id in pending_tool_call_ids:
            if tool_call_id in responded_ids:
                continue
            normalized.append(placeholder_tool_message(tool_call_id))
        pending_tool_call_ids.clear()
        responded_ids.clear()

    for message in valid_messages:
        if (
            message.get("role") == "assistant"
            and message.get("content") in (None, "")
            and not message.get("tool_calls")
        ):
            continue

        if message.get("role") == "tool":
            tool_call_id = message.get("tool_call_id")
            if not pending_tool_call_ids or not tool_call_id or tool_call_id not in pending_tool_call_ids:
                continue
            normalized.append(message)
            responded_ids.add(tool_call_id)
            continue

        flush_pending_tool_calls()
        normalized.append(message)

        tool_calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if tool_calls:
            pending_tool_call_ids = [
                tool_call.get("id")
                for tool_call in tool_calls
                if tool_call.get("id")
            ]

    flush_pending_tool_calls()
    return normalized


def _normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return normalize_conversation_messages(messages)


def _default_metadata(conversation_id: str, now: Optional[str] = None) -> Dict[str, Any]:
    timestamp = now or _timestamp_now()
    return {
        "conversation_id": conversation_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_generation_result": None,
        "generated_output_paths": [],
        "log_filename": None,
    }


def _read_json_dict(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _load_metadata(conversation_id: str, script_dir: Optional[str] = None) -> Dict[str, Any]:
    metadata = _read_json_dict(_metadata_path(conversation_id, script_dir))
    defaults = _default_metadata(conversation_id)
    defaults.update(metadata)
    defaults["conversation_id"] = conversation_id
    return defaults


def _save_metadata(
    conversation_id: str,
    metadata: Dict[str, Any],
    script_dir: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _load_metadata(conversation_id, script_dir)
    merged = existing.copy()
    merged.update(metadata)
    merged["conversation_id"] = conversation_id
    if not merged.get("created_at"):
        merged["created_at"] = _timestamp_now()
    if not merged.get("updated_at"):
        merged["updated_at"] = _timestamp_now()
    _ensure_conversation_dir(conversation_id, script_dir)
    with open(_metadata_path(conversation_id, script_dir), "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    return merged


def _ensure_migrated(script_dir: Optional[str] = None) -> None:
    legacy_path = legacy_conversation_history_path(script_dir)
    if not os.path.exists(legacy_path):
        return

    try:
        with open(legacy_path, "r", encoding="utf-8") as f:
            legacy_data = json.load(f)
    except Exception:
        return

    if not isinstance(legacy_data, list):
        return

    active_conversation_id = get_active_conversation_id(script_dir)
    if not active_conversation_id:
        active_conversation_id = str(uuid.uuid4())

    existing_messages = load_conversation(conversation_id=active_conversation_id, script_dir=script_dir, migrate=False)
    if existing_messages:
        save_conversation_meta(active_conversation_id, script_dir)
        return

    normalized = _normalize_messages(legacy_data)
    if not normalized:
        return

    now = _timestamp_now()
    save_conversation(
        normalized,
        conversation_id=active_conversation_id,
        script_dir=script_dir,
        metadata={
            "created_at": now,
            "updated_at": now,
        },
        set_active=True,
        migrate=False,
    )


def save_conversation(
    messages: List[Dict[str, Any]],
    conversation_id: Optional[str] = None,
    script_dir: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    set_active: bool = True,
    migrate: bool = True,
) -> str:
    if migrate:
        _ensure_migrated(script_dir)

    conversation_id = conversation_id or get_active_conversation_id(script_dir) or str(uuid.uuid4())
    normalized = _normalize_messages(messages)
    now = _timestamp_now()
    _ensure_conversation_dir(conversation_id, script_dir)
    with open(_messages_path(conversation_id, script_dir), "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    saved_metadata = _load_metadata(conversation_id, script_dir)
    if not saved_metadata.get("created_at"):
        saved_metadata["created_at"] = now
    saved_metadata["updated_at"] = now
    if metadata:
        saved_metadata.update(metadata)
        saved_metadata["updated_at"] = metadata.get("updated_at", now)
    _save_metadata(conversation_id, saved_metadata, script_dir)

    if set_active:
        save_conversation_meta(conversation_id, script_dir)

    return conversation_id


def load_conversation(
    conversation_id: Optional[str] = None,
    script_dir: Optional[str] = None,
    *,
    migrate: bool = True,
) -> List[Dict[str, Any]]:
    if migrate:
        _ensure_migrated(script_dir)

    conversation_id = conversation_id or get_active_conversation_id(script_dir)
    if not conversation_id:
        return []

    try:
        with open(_messages_path(conversation_id, script_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return _normalize_messages(data)
    except Exception:
        pass
    return []


def load_conversation_record(
    conversation_id: str,
    script_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    _ensure_migrated(script_dir)
    messages = load_conversation(conversation_id=conversation_id, script_dir=script_dir, migrate=False)
    if not messages:
        metadata = _load_metadata(conversation_id, script_dir)
        if not os.path.exists(_metadata_path(conversation_id, script_dir)):
            return None
    else:
        metadata = _load_metadata(conversation_id, script_dir)

    return {
        "conversation_id": conversation_id,
        "messages": messages,
        "metadata": metadata,
        "message_count": len(messages),
    }


def load_active_conversation_record(script_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conversation_id = get_active_conversation_id(script_dir)
    if not conversation_id:
        _ensure_migrated(script_dir)
        conversation_id = get_active_conversation_id(script_dir)
        if not conversation_id:
            return None
    return load_conversation_record(conversation_id, script_dir)


def list_conversations(script_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_migrated(script_dir)
    conversations_dir = get_conversations_dir(script_dir)
    active_conversation_id = get_active_conversation_id(script_dir)
    conversations: List[Dict[str, Any]] = []

    try:
        entries = os.listdir(conversations_dir)
    except FileNotFoundError:
        entries = []

    for entry in entries:
        conversation_dir = os.path.join(conversations_dir, entry)
        if not os.path.isdir(conversation_dir):
            continue
        record = load_conversation_record(entry, script_dir)
        if not record:
            continue
        metadata = record["metadata"]
        last_generation_result = metadata.get("last_generation_result")
        if entry == active_conversation_id:
            status = "active"
        elif isinstance(last_generation_result, dict) and last_generation_result.get("success"):
            status = "completed"
        else:
            status = "open"
        conversations.append(
            {
                **record,
                "status": status,
                "updated_at": metadata.get("updated_at"),
                "created_at": metadata.get("created_at"),
            }
        )

    conversations.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return conversations


def set_active_conversation(conversation_id: str, script_dir: Optional[str] = None) -> bool:
    record = load_conversation_record(conversation_id, script_dir)
    if not record:
        return False
    save_conversation_meta(conversation_id, script_dir)
    return True


def update_conversation_metadata(
    conversation_id: str,
    metadata: Dict[str, Any],
    script_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    record = load_conversation_record(conversation_id, script_dir)
    if not record:
        return None
    updated = record["metadata"].copy()
    updated.update(metadata)
    updated["updated_at"] = _timestamp_now()
    return _save_metadata(conversation_id, updated, script_dir)


def resolve_conversation_id(identifier: str, script_dir: Optional[str] = None) -> Optional[str]:
    _ensure_migrated(script_dir)
    normalized = identifier.strip()
    if not normalized:
        return None

    direct_record = load_conversation_record(normalized, script_dir)
    if direct_record:
        return normalized

    matches = [
        item["conversation_id"]
        for item in list_conversations(script_dir)
        if item["conversation_id"].startswith(normalized)
    ]
    if len(matches) == 1:
        return matches[0]
    return None
