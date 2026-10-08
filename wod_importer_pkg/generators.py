"""LLM-generation orchestration for the WOD importer.

Chains the repo's two proven LLM generators (the user's architecture decision —
the importer itself does NOT invent workouts or definitions):

1. ensure_definitions  — exercise_library_generator_pkg scoped to the WOD's missing
   movements (content-derived ids make re-runs idempotent); merged into an
   accumulating library sidecar so prior creations count as covered.
2. generate_workout_package — workout_generator_pkg execute_workout_generation in
   strict exercise-library mode (hard post-validation rejects any movement outside
   the library); the WOD text is the request and the generator's own stage prompts
   decide set types (auto-countdowns for timed blocks, supersets for rounds).

Both passes need DEEPSEEK_API_KEY (env or repo .env). The heuristic path in
build.py remains available offline (--offline) but is no longer the default.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DEFAULT_BASE_LIBRARY = Path("exercise_libraries/exercise_library_2026-08-17_164507_with_movements.json")
DEFAULT_ACCUMULATED_LIBRARY = Path("exercise_libraries/wod_accumulated_library.json")
DEFAULT_EQUIPMENT_FILE = Path(__file__).resolve().parent / "assets" / "gym_equipment.json"

WOD_WORKOUT_GUIDANCE = """
This is a coach-authored CrossFit/Hyrox WOD. Hard constraints:
- Use ONLY movements explicitly present in the WOD text: no substitutions, no
  warm-up, no cool-down, no extra exercises.
- Respect the exact time structure: a block announced as "From a'-b'" must total
  exactly (b-a) minutes across its exercises; never exceed the window. Time caps
  ("time cap N'") bound the whole session.
- The athlete cannot enter reps or weights mid-workout (at most one tap to advance),
  so prescribed reps/weights/time domains must be filled in as set defaults exactly
  as written in the request.
- Timed blocks and per-minute EMOM slots: use exactly one TimedDurationSet with
  autoStart=true and autoStop=true so the watch advances by itself.
- AMRAP and rounds-for-time: express as supersetGroups; no rest between members
  (restToNextSeconds=0) unless the WOD specifies rest.
- Rep schemes written as male/female pairs ("@ 22.5/15", "24/20") use the first value.
- BODY_WEIGHT exercises: bodyWeightPercentage must be in percentage form (e.g. 100.0),
  never a fraction like 1.0.
""".strip()


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_working_library(base_library: Path, accumulated_library: Path) -> tuple[dict, Path]:
    """Returns the accumulated library if present, else a copy of the base."""
    if accumulated_library.exists():
        return _load_json(accumulated_library), accumulated_library
    library = _load_json(base_library)
    library.setdefault("exerciseMovements", [])
    return library, accumulated_library


def audit_missing_candidates(client, equipment, wod_text: str, working_library: dict) -> list[str]:
    """Asks the exercise generator's audit mode for the WOD's missing movements.

    The audit receives our library as the existing inventory and the WOD as the
    scope; it returns candidate names for exactly the movements that are missing.
    """
    from exercise_library_generator_pkg.generator import _call_inventory
    from workout_generator_pkg.api_client import json_call_reasoner_only_with_loading

    audit_existing = [
        {
            "name": definition["name"],
            "exerciseType": definition.get("exerciseType"),
            "equipmentId": definition.get("equipmentId"),
        }
        for definition in working_library.get("exerciseDefinitions", [])
    ]
    request = (
        "WOD coverage audit. Today's WOD:\n"
        + wod_text
        + "\nReturn only the distinct movements performed in this WOD that are "
        "missing from the existing inventory."
    )
    candidates = _call_inventory(
        client,
        equipment,
        request,
        audit_existing=audit_existing,
        scope_description=None,
        allowed_equipment_ids=None,
        require_any_accessory=False,
        show_loading=False,
        call_json=json_call_reasoner_only_with_loading,
    )
    return [candidate["name"] for candidate in candidates]


def ensure_wod_coverage(
    client,
    wod_text: str,
    working_library: dict,
    working_library_path: Path,
    equipment_file: Path = DEFAULT_EQUIPMENT_FILE,
    audit_call=None,
    generate_library=None,
) -> tuple[dict, list[str]]:
    """Makes the exercise generator cover every movement in the WOD.

    The generator's audit mode identifies the missing movements (our library is the
    existing inventory, the WOD is the scope); those flow through the generator's
    normal scoped emission + reviews. No heuristic parsing and no separate
    coverage LLM are involved.
    """
    from workout_generator_pkg.cli import load_equipment_from_file

    if audit_call is None:
        audit_call = audit_missing_candidates
    if generate_library is None:
        generate_library = scoped_library_generation

    # The equipment catalog is only consumed by the real audit path; injected
    # test audits don't need the file to exist.
    equipment = load_equipment_from_file(str(equipment_file)) if audit_call is audit_missing_candidates else None

    def _covered(name: str) -> bool:
        key = _normalize(name)
        return any(key in known or known in key for known in known_keys)

    known_keys = {_normalize(d["name"]) for d in working_library.get("exerciseDefinitions", [])}
    created: list[str] = []

    for _attempt in range(2):
        audit_names = audit_call(client, equipment, wod_text, working_library)
        still_missing = [name for name in audit_names if not _covered(name)]
        if not still_missing:
            break
        request = (
            "Gym WOD coverage: generate ONLY these movements and nothing else "
            "(canonical CrossFit names fine): "
            + "; ".join(still_missing)
            + ". Exclude every other exercise."
        )
        cap = max(8, 2 * len(still_missing))
        generated = generate_library(client, equipment_file, request, cap)

        existing_ids = {d["id"] for d in working_library.get("exerciseDefinitions", [])}
        for definition in generated.get("exerciseDefinitions", []):
            normalized = _normalize(definition["name"])
            if definition["id"] in existing_ids or _covered(definition["name"]):
                continue
            working_library.setdefault("exerciseDefinitions", []).append(definition)
            existing_ids.add(definition["id"])
            known_keys.add(normalized)
            created.append(definition["name"])

        existing_equipment_ids = {e["id"] for e in working_library.get("equipments", [])}
        for equipment in generated.get("equipments", []):
            if equipment["id"] not in existing_equipment_ids:
                working_library.setdefault("equipments", []).append(equipment)
                existing_equipment_ids.add(equipment["id"])

    working_library_path.parent.mkdir(parents=True, exist_ok=True)
    working_library_path.write_text(json.dumps(working_library, indent=2), encoding="utf-8")
    return working_library, created



def generate_workout_package(
    wod_text: str,
    library: dict,
    script_dir: Path = REPO,
    force_use_reasoner: str = "hybrid",
) -> dict:
    """Runs the workout generator in strict library mode; returns the package JSON."""
    from workout_generator_pkg.constants import BASE_SYSTEM_PROMPT
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    from workout_generator_pkg.interactive_shell import _resolve_api_key

    import httpx
    from openai import OpenAI

    client = OpenAI(
        api_key=_resolve_api_key(),
        base_url="https://api.deepseek.com",
        http_client=httpx.Client(timeout=httpx.Timeout(1200.0, connect=60.0)),
    )
    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": wod_text},
    ]
    provided = {
        "equipments": library.get("equipments", []),
        "accessoryEquipments": library.get("accessoryEquipments", []),
        "exerciseDefinitions": library.get("exerciseDefinitions", []),
        "exerciseMovements": library.get("exerciseMovements", []),
    }
    result = execute_workout_generation(
        client,
        messages,
        custom_prompt=f"{wod_text}\n\n{WOD_WORKOUT_GUIDANCE}",
        provided_equipment=provided,
        script_dir=str(script_dir),
        force_use_reasoner=force_use_reasoner,
        allow_educated_load_guesses=True,
    )
    if not result.get("success") or not result.get("filepath"):
        raise RuntimeError(f"Workout generation failed: {result.get('error')}")
    return _load_json(Path(result["filepath"]))


def scoped_library_generation(client, equipment_file: Path, request: str, max_definitions: int) -> dict:
    """Scoped exercise-library generation (kept here so tests can monkeypatch it)."""
    from exercise_library_generator_pkg.generator import generate_exercise_library
    from workout_generator_pkg.api_client import (
        json_call_chat_max_with_loading,
        json_call_reasoner_only_with_loading,
    )
    from workout_generator_pkg.cli import load_equipment_from_file

    equipment = load_equipment_from_file(str(equipment_file))
    library = generate_exercise_library(
        client,
        equipment,
        request=request,
        scope_inventory_by_equipment=False,
        audit_passes=0,
        max_workers=2,
        definition_batch_size=max(1, max_definitions),
        max_definitions=max_definitions,
        inventory_call=json_call_reasoner_only_with_loading,
        reasoner_call=json_call_reasoner_only_with_loading,
        chat_call=json_call_chat_max_with_loading,
    )
    failures = library.pop("generationFailures", None)
    discards = library.pop("semanticDiscards", None)
    del failures, discards
    return library


def make_deepseek_client():
    from workout_generator_pkg.interactive_shell import _resolve_api_key

    import httpx
    from openai import OpenAI

    return OpenAI(
        api_key=_resolve_api_key(),
        base_url="https://api.deepseek.com",
        http_client=httpx.Client(timeout=httpx.Timeout(900.0, connect=60.0)),
    )


def sanitize_package_name(package: dict, date_iso: str) -> dict:
    """Normalizes the LLM-chosen plan name to the WOD <date> convention."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", package.get("name") or "WOD").strip("-")
    name = f"WOD {date_iso} {slug}".strip()
    package["name"] = name
    for workout in package.get("workouts", []):
        workout["name"] = name
    return package
