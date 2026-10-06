"""The setup step: one LLM call that decides what the WOD needs.

Input: the whole WOD text, the gym equipment catalog, and the names of every
exercise already in the library. Output (structured JSON): which equipment is
missing from the catalog and which movements need new definitions. There is no
heuristic parsing anywhere — the LLM reads the WOD directly.
"""

from __future__ import annotations

import json
import re

SETUP_SYSTEM_PROMPT = """You are the exercise-coverage planner for a gym workout tracker.
You receive today's WOD text, the gym's available equipment (name + type), and the
names of every exercise already defined in the tracker's library.
Return strict JSON:
{
  "exercisesToCreate": ["<movement>", ...],       // movements performed in the WOD that
                                                  // do NOT exist in the library (canonical
                                                  // CrossFit names, e.g. "Wall Ball")
  "missingEquipment": [{"name": "...", "type": "..."}]  // equipment the WOD requires that
                                                        // is NOT in the available equipment;
                                                        // type must be one of:
                                                        // GENERIC, BARBELL, DUMBBELLS,
                                                        // DUMBBELL, PLATELOADEDCABLE,
                                                        // WEIGHTVEST, MACHINE,
                                                        // CARDIO_MACHINE, ACCESSORY
}
Rules:
- Only movements actually performed in the WOD; ignore warm-up chatter and section titles.
- A movement is covered when an existing exercise is the same movement, even if the
  library name carries equipment/equipment-position qualifiers (e.g. "Barbell Deadlift"
  covers "Deadlift"); prefer the library over creating duplicates.
- Sub-variations that are genuinely different movements (e.g. "Burpee Box Jump Over"
  vs "Burpee") count as missing.
- Machine cardio (row, bike erg, assault bike, ski erg) is a timed movement on that machine.
- Never invent equipment types outside the enum; never return equipment the WOD does not use.
"""

VALID_EQUIPMENT_TYPES = {
    "GENERIC", "BARBELL", "DUMBBELLS", "DUMBBELL", "PLATELOADEDCABLE",
    "WEIGHTVEST", "MACHINE", "CARDIO_MACHINE", "ACCESSORY",
}


def plan_missing(
    client,
    wod_text: str,
    equipment_catalog: dict,
    exercise_names: list[str],
    call=None,
) -> dict:
    """Returns {"exercisesToCreate": [names], "missingEquipment": [{name, type}]}."""
    if call is None:
        call = _default_llm_call
    equipment_lines = "\n".join(
        f"- {item['name']} ({item['type']})"
        for item in equipment_catalog.get("equipments", []) + equipment_catalog.get("accessoryEquipments", [])
    )
    exercise_lines = "\n".join(f"- {name}" for name in exercise_names)
    user_prompt = (
        f"Available equipment:\n{equipment_lines}\n\n"
        f"Existing exercises:\n{exercise_lines}\n\n"
        f"Today's WOD:\n{wod_text}"
    )
    raw = call(client, SETUP_SYSTEM_PROMPT, user_prompt)
    parsed = json.loads(raw)
    equipment = [
        {"name": item["name"], "type": item["type"]}
        for item in parsed.get("missingEquipment", [])
        if item.get("name") and item.get("type") in VALID_EQUIPMENT_TYPES
    ]
    exercises = [
        name.strip() for name in parsed.get("exercisesToCreate", []) if name.strip()
    ]
    return {"exercisesToCreate": exercises, "missingEquipment": equipment}


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
