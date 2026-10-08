"""Helpers for loading exercise contracts in retained replay tools."""

from __future__ import annotations

from typing import Any


def unwrap_exercise_motion_contract(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("exerciseMotionContract", "contract"):
        contract = payload.get(key)
        if isinstance(contract, dict):
            return contract
    return payload
