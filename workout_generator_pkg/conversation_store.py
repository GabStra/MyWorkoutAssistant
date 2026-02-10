"""Conversation history persistence helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def save_conversation(messages: List[Dict[str, Any]]) -> None:
    with open("conversation_history.json", "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)


def _is_valid_message(msg: Dict[str, Any]) -> bool:
    if not isinstance(msg, dict):
        return False
    role = msg.get("role")
    return role in {"system", "user", "assistant", "tool", "emitter"}


def load_conversation() -> List[Dict[str, Any]]:
    try:
        with open("conversation_history.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [m for m in data if _is_valid_message(m)]
    except Exception:
        pass
    return []
