"""Conversation metadata and hashing helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .paths import conversation_meta_path


def load_conversation_meta(script_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load conversation metadata."""
    meta_path = conversation_meta_path(script_dir)
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_conversation_meta(active_conversation_id: str, script_dir: Optional[str] = None) -> None:
    """Persist active conversation metadata."""
    meta_path = conversation_meta_path(script_dir)
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"active_conversation_id": active_conversation_id}, f, indent=2)
    except Exception:
        pass


def get_active_conversation_id(script_dir: Optional[str] = None) -> Optional[str]:
    """Return the active conversation id from either the new or legacy meta shape."""
    meta = load_conversation_meta(script_dir)
    active_conversation_id = meta.get("active_conversation_id")
    if isinstance(active_conversation_id, str) and active_conversation_id.strip():
        return active_conversation_id.strip()

    legacy_conversation_id = meta.get("conversation_id")
    if isinstance(legacy_conversation_id, str) and legacy_conversation_id.strip():
        return legacy_conversation_id.strip()

    return None


def hash_conversation(messages: List[Dict[str, Any]]) -> str:
    """Compute stable hash of non-system messages."""
    conversation_str = json.dumps(
        [msg for msg in messages if msg.get("role") != "system"],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(conversation_str.encode("utf-8")).hexdigest()
