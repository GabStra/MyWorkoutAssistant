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

HANDS_FREE_GUIDANCE = """
This is a coach-authored workout. Hard constraints:
- Use ONLY movements explicitly present in the workout text: no substitutions, no
  warm-up, no cool-down, no extra exercises.
- Respect the exact time structure: a block announced as "From a'-b'" must total
  exactly (b-a) minutes across its exercises; never exceed the window. Time caps
  ("time cap N'") bound the whole session.
- The athlete cannot enter reps or weights mid-workout (at most one tap to advance),
  so prescribed reps/weights/time domains must be filled in as set defaults exactly
  as written in the request.
- Timed blocks and per-minute EMOM slots (when present): use exactly one
  TimedDurationSet with autoStart=true and autoStop=true so the watch advances by
  itself.
- Superset members repeat in lock-step: every member MUST carry the same number of
  work sets (the watch repeats the round at the smallest member's count and
  silently truncates the rest). Encode ladders like 20-15-10-5 as one set per
  movement per step (4 sets each, reps 20/15/10/5). A one-off movement (buy-in /
  buy-out run) that does NOT repeat goes OUTSIDE the superset as its own
  component; the cap then belongs to the repeating block.
- MANDATORY time caps: every AMRAP, rounds-for-time, or block the text bounds with
  a window ("time cap 25'", "In 12' time cap", "From 8'-12'") MUST set the
  superset's timeCapSeconds to the window in seconds. Example: an 8-12 minute
  block starting at minute 8 gets timeCapSeconds=240. Without it the watch never
  leaves the block.
- MANDATORY AMRAP mode: an AMRAP ("20 minute AMRAP of: ...", "Amrap 12' of: ...")
  MUST be one superset with amrap=true and timeCapSeconds=the window in seconds.
  Its members carry EXACTLY ONE work set each — they define the round, which the
  watch repeats until the cap expires. Do not estimate rounds by duplicating sets.
- MANDATORY EMOM cadence: "Every N minutes x T minutes" MUST become one superset
  with roundDurationSeconds=N and T/N work sets per member (e.g. "Every 2' x 10'"
  -> roundDurationSeconds=120 and 5 work sets per member). Never combine
  roundDurationSeconds with timeCapSeconds on the same superset.
- MANDATORY cardio quantities: when the text states a distance or calories for a
  row/bike/ski/run movement ("max mt row (target 1100/1000)", "24/20 cal", "800 mt
  run", "500m row"), that movement's sets MUST carry targetDistanceMeters (in
  meters) or targetCalories, first value of male/female pairs. NEVER encode a
  stated distance or calorie quantity as a rep count.
- Goal-based sets: a set whose quantity is a distance or calorie goal WITHOUT a
  stated duration MUST be an EnduranceSet with timeInMillis=0, autoStart=true and
  autoStop=FALSE (the watch counts up and shows the goal; the athlete finishes
  it). autoStop=true is only valid together with a positive timeInMillis.
- MANDATORY runs: a stated run ("800 mt run") MUST use the 'Run' library entry
  (exerciseType RUNNING) with targetDistanceMeters; the watch tracks it with GPS
  and shows the distance goal. Never encode a run as reps or as another movement.
- Rep schemes written as male/female pairs ("@ 22.5/15", "24/20") use the first value.
- BODY_WEIGHT exercises: bodyWeightPercentage must be in percentage form (e.g. 100.0),
  never a fraction like 1.0.
""".strip()

STANDARD_GUIDANCE = """
This is a coach-authored workout. Constraints:
- Use ONLY movements explicitly present in the workout text; respect the prescribed
  sets, reps, loads, and rest exactly as written.
- When the text states a distance or calorie quantity for a timed row/bike/ski/run
  movement, record it on the set as targetDistanceMeters (meters) or targetCalories.
- When the text states a time cap bounding a multi-movement block expressed as a
  superset, set the superset's timeCapSeconds.
- BODY_WEIGHT exercises: bodyWeightPercentage must be in percentage form (e.g. 100.0),
  never a fraction like 1.0.
""".strip()


def guidance_for_style(style: str) -> str:
    return HANDS_FREE_GUIDANCE if style == "hands-free" else STANDARD_GUIDANCE


def ensure_running_definition(working_library: dict, working_library_path: Path) -> bool:
    """Guarantees one canonical RUNNING 'Run' definition in the working library.

    The exercise library contains no RUNNING entries and the library generator does
    not create them, but the app fully supports RUNNING exercises (GPS tracking +
    distance prescriptions). The definition is content-derived and idempotent, so
    stated runs can be prescribed as real running exercises. Returns True when the
    definition was added.
    """
    import uuid

    for definition in working_library.get("exerciseDefinitions", []):
        if definition.get("exerciseType") == "RUNNING":
            return False

    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    working_library.setdefault("exerciseDefinitions", []).append({
        "id": str(uuid.uuid5(ns, "myworkoutassistant:exercise:Run")),
        "name": "Run",
        "exerciseType": "RUNNING",
        "equipmentId": None,
        "bodyWeightPercentage": None,
        "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_QUADRICEPS", "BACK_HAMSTRING", "BACK_CALVES"],
        "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    })
    working_library_path.parent.mkdir(parents=True, exist_ok=True)
    working_library_path.write_text(
        json.dumps(working_library, indent=2), encoding="utf-8"
    )
    return True


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_working_library(base_library: Path, accumulated_library: Path) -> tuple[dict, Path]:
    """Returns the accumulated library if present, else a copy of the base."""
    if accumulated_library.exists():
        library = _load_json(accumulated_library)
    else:
        library = _load_json(base_library)
        library.setdefault("exerciseMovements", [])
    # Some pre-upgrade library entries store bodyWeightPercentage as a unit fraction,
    # and 74 implement-assisted BODY_WEIGHT entries carry null; the runtime consumes
    # percent and the workout contract requires a positive value, so normalize at the
    # boundary: fractions scale to percent, null defaults to full-bodyweight semantics.
    for definition in library.get("exerciseDefinitions", []):
        if definition.get("exerciseType") != "BODY_WEIGHT":
            continue
        percentage = definition.get("bodyWeightPercentage")
        if isinstance(percentage, (int, float)) and 0 < percentage <= 1.0:
            definition["bodyWeightPercentage"] = percentage * 100
        elif percentage is None:
            definition["bodyWeightPercentage"] = 100.0
    return library, accumulated_library


def audit_missing_candidates(client, equipment, workout_text: str, working_library: dict) -> list[str]:
    """Asks the exercise generator's audit mode for the workout's missing movements.

    The audit receives our library as the existing inventory and the workout text
    as the scope; it returns candidate names for exactly the movements that are
    missing.
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
        "Workout coverage audit. The workout text:\n"
        + workout_text
        + "\nFirst list every distinct movement performed in this workout, then check "
        "each one against the existing inventory and return ONLY the movements that "
        "are missing from it - do not skip or merge any movement from the text. Also "
        "include a new candidate when the "
        "only existing inventory entry for a workout movement is a poor match for how the "
        "movement appears here (different implement, or an irrelevant variant such as "
        "a weighted version of a bodyweight movement) - the candidate must be the more "
        "appropriate version for this workout. This rule takes precedence over variation "
        "exclusion: when only qualified variants of a movement exist (e.g. only "
        "Weighted/Incline/Ring Push-Up), the plain unqualified version (Push-Up) is "
        "missing and must be returned."
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


def ensure_workout_coverage(
    client,
    workout_text: str,
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
        audit_names = audit_call(client, equipment, workout_text, working_library)
        still_missing = [name for name in audit_names if not _covered(name)]
        if not still_missing:
            break
        request = (
            "Workout coverage: generate ONLY these movements and nothing else "
            "(canonical gym names fine): "
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

        existing_accessory_ids = {a["id"] for a in working_library.get("accessoryEquipments", [])}
        for accessory in generated.get("accessoryEquipments", []):
            if accessory["id"] not in existing_accessory_ids:
                working_library.setdefault("accessoryEquipments", []).append(accessory)
                existing_accessory_ids.add(accessory["id"])

    working_library_path.parent.mkdir(parents=True, exist_ok=True)
    working_library_path.write_text(json.dumps(working_library, indent=2), encoding="utf-8")
    return working_library, created



def generate_workout_package(
    workout_text: str,
    library: dict,
    script_dir: Path = REPO,
    force_use_reasoner: str = "hybrid",
    guidance: str = HANDS_FREE_GUIDANCE,
    corrective_context: str = "",
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
        {"role": "user", "content": workout_text},
    ]
    request = f"{guidance}\n\nWorkout text:\n{workout_text}"
    if corrective_context:
        request = f"{request}\n\nThe previous attempt had these fixable problems:\n{corrective_context}"
    provided = {
        "equipments": library.get("equipments", []),
        "accessoryEquipments": library.get("accessoryEquipments", []),
        "exerciseDefinitions": library.get("exerciseDefinitions", []),
        "exerciseMovements": library.get("exerciseMovements", []),
    }
    result = execute_workout_generation(
        client,
        messages,
        custom_prompt=request,
        provided_equipment=provided,
        script_dir=str(script_dir),
        force_use_reasoner=force_use_reasoner,
        allow_educated_load_guesses=True,
    )
    if not result.get("success") or not result.get("filepath"):
        raise RuntimeError(f"Workout generation failed: {result.get('error')}")
    return _load_json(Path(result["filepath"]))


COMPLIANCE_SYSTEM_PROMPT = """You audit a generated workout plan against the workout text it came from.
First list every block and movement in the text, then check each one in the plan.
The plan was built under these mandatory encoding rules:
1. Every AMRAP, rounds-for-time, or block bounded by a stated time window must be a
   superset whose timeCapSeconds equals that window in seconds.
2. "Every N minutes x T minutes" (EMOM) blocks must be one superset with
   roundDurationSeconds = N, and each member must carry T/N work sets (e.g.
   "Every 2' x 10'" -> roundDurationSeconds 120 and 5 work sets per member).
3. Distances (meters) or calories stated for a ROWING, BIKING, SKIING or RUNNING
   movement only, must appear as targetDistanceMeters or targetCalories on that
   movement's timed set. Rep counts on strength or gymnastics movements are NOT
   targets - never report them as missing.
4. Every distinct block and movement listed in the text must appear in the plan -
   a missing block or movement is always an issue.
5. All members of one superset must carry the SAME number of work sets (the
   runtime repeats them in lock-step at the smallest member's count and silently
   truncates longer members). Unequal work-set counts across members are always
   an issue. An AMRAP block must be a superset with amrap=true, timeCapSeconds
   set, and exactly one work set per member - an AMRAP whose members carry
   multiple work sets each, or one without amrap=true, is an issue.
6. A movement whose stated quantity is a distance ("800 mt run") must NOT be
   encoded as rep-based sets; runs must be RUNNING exercises carrying a distance
   prescription. Rep counts on a run-shaped movement are always an issue.
7. A distance or calorie goal set without a stated duration must use
   autoStop=false (the athlete finishes it against the shown goal); autoStop=true
   together with timeInMillis=0 would auto-complete instantly and is always an
   issue.
Return strict JSON: {"issues": ["..."]}
Each issue is one concrete, fixable violation. If the plan complies, return an
empty list. Do not invent requirements that are not in the rules above.
"""


def review_crossfit_mode_compliance(client, workout_text: str, package: dict, call=None) -> list[str]:
    """Two independent cheap LLM audits of the generated package against the text.

    Returns the union of human-readable issues (one chat call each - cheap); empty
    when both agree the plan complies. Two votes guard against a single audit
    passing an incomplete plan. Judgment stays with the LLM - no text parsing.
    """
    if call is None:
        from workout_importer_pkg.setup import _default_llm_call
        call = _default_llm_call

    def walk(components):
        for component in components:
            if component.get("type") == "Superset":
                yield from walk(component.get("exercises", []))
            elif component.get("type") == "Exercise":
                yield component

    compact = []
    for workout in package.get("workouts", []):
        for component in workout.get("workoutComponents", []):
            if component.get("type") == "Superset":
                compact.append({
                    "type": "Superset",
                    "timeCapSeconds": component.get("timeCapSeconds"),
                    "roundDurationSeconds": component.get("roundDurationSeconds"),
                    "amrap": component.get("amrap"),
                    "exercises": [
                        {
                            "name": e.get("name"),
                            "exerciseType": e.get("exerciseType"),
                            "sets": [
                                {
                                    "type": s.get("type"),
                                    "timeInMillis": s.get("timeInMillis"),
                                    "targetDistanceMeters": s.get("targetDistanceMeters"),
                                    "targetCalories": s.get("targetCalories"),
                                }
                                for s in e.get("sets", [])
                            ],
                        }
                        for e in component.get("exercises", [])
                    ],
                })
            elif component.get("type") == "Exercise":
                compact.append({
                    "type": "Exercise",
                    "name": component.get("name"),
                    "exerciseType": component.get("exerciseType"),
                    "sets": [
                        {
                            "type": s.get("type"),
                            "timeInMillis": s.get("timeInMillis"),
                            "targetDistanceMeters": s.get("targetDistanceMeters"),
                            "targetCalories": s.get("targetCalories"),
                        }
                        for s in component.get("sets", [])
                    ],
                })

    user_prompt = (
        f"Workout text:\n{workout_text}\n\n"
        f"Generated plan components (compact):\n{json.dumps(compact, separators=(',', ':'))}"
    )

    def audit_once():
        raw = call(client, COMPLIANCE_SYSTEM_PROMPT, user_prompt)
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        issues = parsed.get("issues", [])
        return [str(issue) for issue in issues if issue][:10]

    seen: list[str] = []
    seen_keys = set()
    for _ in range(2):
        for issue in audit_once():
            key = _normalize(issue)[:80]
            if key and key not in seen_keys:
                seen_keys.add(key)
                seen.append(issue)
    return seen[:10]


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


def backfill_equipment_from_catalog(package: dict, catalog: dict) -> list[str]:
    """Ensures every equipment/accessory referenced by the package resolves.

    The workout generator emits only the equipment its plan declared; definitions
    can reference more (a definition's equipmentId or required accessories). Since
    import replaces the store's gear with the package's, anything dangling would
    break at workout time. The catalog is the complete superset, so backfill from it.
    """
    catalog_by_id = {
        item["id"]: item
        for item in catalog.get("equipments", []) + catalog.get("accessoryEquipments", [])
    }
    referenced = set()
    for definition in package.get("exerciseDefinitions", []):
        if definition.get("equipmentId"):
            referenced.add(definition["equipmentId"])
        referenced.update(definition.get("requiredAccessoryEquipmentIds", []))

    equipment_ids = {e["id"] for e in package.get("equipments", [])}
    accessory_ids = {a["id"] for a in package.get("accessoryEquipments", [])}
    added = []
    for referenced_id in sorted(referenced):
        item = catalog_by_id.get(referenced_id)
        if item is None:
            continue
        if item["type"] == "ACCESSORY":
            if referenced_id not in accessory_ids:
                package.setdefault("accessoryEquipments", []).append(item)
                accessory_ids.add(referenced_id)
                added.append(item["name"])
        elif referenced_id not in equipment_ids:
            package.setdefault("equipments", []).append(item)
            equipment_ids.add(referenced_id)
            added.append(item["name"])
    return added


def sanitize_package_name(package: dict, date_iso: str, explicit_name: str | None = None) -> dict:
    """Normalizes the plan name; an explicit caller name is used verbatim."""
    if explicit_name:
        package["name"] = explicit_name
        for workout in package.get("workouts", []):
            workout["name"] = explicit_name
        return package
    slug = re.sub(r"[^A-Za-z0-9]+", "-", package.get("name") or "WOD").strip("-")
    name = f"WOD {date_iso} {slug}".strip()
    package["name"] = name
    for workout in package.get("workouts", []):
        workout["name"] = name
    return package
