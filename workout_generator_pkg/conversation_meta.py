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


def save_conversation_meta(conversation_id: str, script_dir: Optional[str] = None) -> None:
    """Persist conversation metadata."""
    meta_path = conversation_meta_path(script_dir)
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"conversation_id": conversation_id}, f, indent=2)
    except Exception:
        pass


def hash_conversation(messages: List[Dict[str, Any]]) -> str:
    """Compute stable hash of non-system messages."""
    conversation_str = json.dumps(
        [msg for msg in messages if msg.get("role") != "system"],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(conversation_str.encode("utf-8")).hexdigest()
