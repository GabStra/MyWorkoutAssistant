"""The equipment setup step: one LLM call that decides what equipment the workout needs.

Input: the whole workout text (WOD, strength session, any workout) and the gym
equipment catalog. Output: equipment the workout requires that the catalog lacks
(the exercise generator handles exercise coverage itself via its audit mode —
see generators.ensure_workout_coverage).
"""

from __future__ import annotations

import json
import re

EQUIPMENT_SYSTEM_PROMPT = """You are the equipment planner for a gym workout tracker.
You receive a workout text (a WOD, a strength session, or any other workout) and the
gym's available equipment (name + type).
Return strict JSON:
{"missingEquipment": [{"name": "...", "type": "..."}]}
Each entry is equipment the workout requires that is NOT in the available equipment list.
type must be one of: GENERIC, BARBELL, DUMBBELLS, DUMBBELL, PLATELOADEDCABLE,
WEIGHTVEST, MACHINE, CARDIO_MACHINE, ACCESSORY.
Rules: only equipment actually required by movements in the workout; never invent
equipment types outside the enum; return an empty list when the catalog suffices.
"""

VALID_EQUIPMENT_TYPES = {
    "GENERIC", "BARBELL", "DUMBBELLS", "DUMBBELL", "PLATELOADEDCABLE",
    "WEIGHTVEST", "MACHINE", "CARDIO_MACHINE", "ACCESSORY",
}


def plan_missing_equipment(client, workout_text: str, equipment_catalog: dict, call=None) -> list[dict]:
    """Returns [{"name", "type"}] for equipment the workout needs but the catalog lacks."""
    if call is None:
        call = _default_llm_call
    equipment_lines = "\n".join(
        f"- {item['name']} ({item['type']})"
        for item in equipment_catalog.get("equipments", []) + equipment_catalog.get("accessoryEquipments", [])
    )
    user_prompt = f"Available equipment:\n{equipment_lines}\n\nWorkout:\n{workout_text}"
    raw = call(client, EQUIPMENT_SYSTEM_PROMPT, user_prompt)
    parsed = json.loads(raw)
    return [
        {"name": item["name"], "type": item["type"]}
        for item in parsed.get("missingEquipment", [])
        if item.get("name") and item.get("type") in VALID_EQUIPMENT_TYPES
    ]


def _default_llm_call(client, system_prompt: str, user_prompt: str) -> str:
    """DeepSeek chat call with JSON response format and one retry."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        except Exception as error:  # noqa: BLE001 - surfaced to the caller
            last_error = error
    raise RuntimeError(f"Setup LLM call failed: {last_error}")


def extend_equipment_catalog(catalog: dict, missing_equipment: list[dict]) -> tuple[dict, list[dict]]:
    """Adds missing equipment to the catalog with deterministic ids.

    Returns (updated_catalog, added_items). Items already present (by normalized
    name) are skipped; new items get uuid5 ids so re-runs converge.
    """
    import uuid

    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    def normalize(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.lower())

    known = {
        normalize(item["name"]): item
        for item in catalog.get("equipments", []) + catalog.get("accessoryEquipments", [])
    }
    added = []
    for item in missing_equipment:
        key = normalize(item["name"])
        if key in known:
            continue
        entry = {
            "id": str(uuid.uuid5(ns, f"myworkoutassistant:gym-equipment:{item['name']}")),
            "type": item["type"],
            "name": item["name"],
            "capabilities": [],
        }
        target = "accessoryEquipments" if item["type"] == "ACCESSORY" else "equipments"
        catalog.setdefault(target, []).append(entry)
        known[key] = entry
        added.append(entry)
    return catalog, added
