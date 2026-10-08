"""Regression gate for generated WOD packages.

Validates every workouts/wod_<date>.json against the app model:
- referential integrity (definitions, equipment, accessories)
- set-level structure per exercise type
- BODY_WEIGHT percentage semantics (percent form, positive)
- day-specific structure assertions (e.g. today's Hyrox block timing)

Packages are local artifacts (workouts/ is gitignored); the suite skips when
none exist so CI stays green, and validates everything present otherwise.
"""

import glob
import json
from pathlib import Path

import pytest

from wod_importer_pkg.generators import _normalize  # reuse the project's normalizer

REPO = Path(__file__).resolve().parents[1]


def _packages() -> list[str]:
    return sorted(glob.glob(str(REPO / "workouts" / "wod_2*.json")))


def _walk_exercises(components):
    for component in components:
        if component.get("type") == "Superset":
            yield from _walk_exercises(component.get("exercises", []))
        elif component.get("type") == "Exercise":
            yield component


def _validate_package(package: dict) -> None:
    name = package.get("name", "<unnamed>")
    assert package.get("schemaVersion") == 2, f"{name}: schemaVersion must be 2"
    assert package.get("name"), f"{name}: missing plan name"
    assert package.get("workouts"), f"{name}: no workouts"

    definitions = {d["id"]: d for d in package.get("exerciseDefinitions", [])}
    equipment = {e["id"]: e for e in package.get("equipments", [])}
    accessories = {a["id"]: a for a in package.get("accessoryEquipments", [])}
    referenced_definition_ids = set()
    referenced_equipment_ids = set()
    referenced_accessory_ids = set()

    for workout in package["workouts"]:
        components = workout.get("workoutComponents", [])
        assert components, f"{name}: workout has no components"
        for component in _walk_exercises(components):
            label = f"{name}: exercise '{component.get('name')}'"
            definition = definitions.get(component.get("exerciseDefinitionId"))
            assert definition is not None, f"{label}: unresolvable exerciseDefinitionId"
            referenced_definition_ids.add(definition["id"])

            assert component["exerciseType"] == definition["exerciseType"], (
                f"{label}: exerciseType mismatch with definition"
            )
            if component.get("equipmentId"):
                referenced_equipment_ids.add(component["equipmentId"])
                assert component["equipmentId"] in equipment, (
                    f"{label}: equipmentId not in package equipments"
                )
            for accessory_id in definition.get("requiredAccessoryEquipmentIds", []):
                referenced_accessory_ids.add(accessory_id)
                assert accessory_id in accessories, (
                    f"{name}: definition '{definition['name']}' references accessory "
                    f"{accessory_id} that is not in package accessoryEquipments"
                )

            if definition["exerciseType"] == "BODY_WEIGHT":
                percentage = definition.get("bodyWeightPercentage")
                assert isinstance(percentage, (int, float)) and percentage > 1.0, (
                    f"{name}: '{definition['name']}' bodyWeightPercentage must be "
                    f"percentage-form and positive, got {percentage!r}"
                )

            sets = component.get("sets", [])
            assert sets, f"{label}: no sets"
            for set_data in sets:
                set_type = set_data.get("type")
                if set_type in ("TimedDurationSet", "EnduranceSet"):
                    assert set_data.get("timeInMillis", 0) > 0, f"{label}: timed set with no duration"
                elif set_type == "WeightSet":
                    assert set_data.get("reps", 0) > 0, f"{label}: weight set with no reps"
                    assert set_data.get("weight", -1) >= 0, f"{label}: negative weight"
                elif set_type == "BodyWeightSet":
                    assert set_data.get("reps", 0) > 0, f"{label}: bodyweight set with no reps"
                elif set_type == "RestSet":
                    # zero-duration rest is the structural "no rest" marker inside
                    # supersets (restSecondsByExercise = 0)
                    assert set_data.get("timeInSeconds", -1) >= 0, f"{label}: negative rest"
                else:
                    raise AssertionError(f"{label}: unknown set type {set_type}")

    # definitions embedded in the package must be exactly the referenced ones
    assert referenced_definition_ids == set(definitions), (
        f"{name}: package definitions and referenced exercises diverge "
        f"(unreferenced: {[d['name'] for i, d in definitions.items() if i not in referenced_definition_ids]})"
    )
    del referenced_equipment_ids, referenced_accessory_ids


def test_crossfit_mode_fields_pass_generator_schema():
    """The CrossFit mode fields (superset cap/cadence, timed-set targets) are
    teachable to the LLM generator: they validate against JSON_SCHEMA, including
    explicit nulls, and bad values are rejected."""
    import uuid

    from jsonschema import validate
    from jsonschema.exceptions import ValidationError

    from workout_generator_pkg.constants import JSON_SCHEMA

    def validate_against_def(instance, def_name):
        # $defs at the root so nested "#/$defs/..." refs resolve; $ref selects the def.
        validate(instance, {"$defs": JSON_SCHEMA["$defs"], "$ref": f"#/$defs/{def_name}"})

    superset = {
        "id": str(uuid.uuid4()), "type": "Superset", "enabled": True,
        "exercises": [], "restSecondsByExercise": {},
        "timeCapSeconds": 240, "roundDurationSeconds": None,
    }
    validate_against_def(superset, "Superset")

    timed = {
        "id": str(uuid.uuid4()), "type": "TimedDurationSet",
        "timeInMillis": 240000, "autoStart": True, "autoStop": True,
        "targetDistanceMeters": 1100.0, "targetCalories": None,
    }
    validate_against_def(timed, "TimedDurationSet")

    endurance = {
        "id": str(uuid.uuid4()), "type": "EnduranceSet",
        "timeInMillis": 0, "autoStart": True, "autoStop": True,
        "targetCalories": 24.0,
    }
    validate_against_def(endurance, "EnduranceSet")

    with pytest.raises(ValidationError):
        validate_against_def({**superset, "timeCapSeconds": 0}, "Superset")
    with pytest.raises(ValidationError):
        validate_against_def({**timed, "targetCalories": "many"}, "TimedDurationSet")


def test_all_generated_packages_are_valid():
    packages = _packages()
    if not packages:
        pytest.skip("no generated WOD packages present in workouts/")
    for path in packages:
        with open(path, encoding="utf-8") as handle:
            package = json.load(handle)
        _validate_package(package)


def test_today_hyrox_package_structure():
    path = REPO / "workouts" / "wod_2026-10-06.json"
    if not path.exists():
        pytest.skip("wod_2026-10-06.json not present")
    package = json.loads(path.read_text(encoding="utf-8"))
    _validate_package(package)

    workout = package["workouts"][0]
    components = workout["workoutComponents"]
    timed_seconds = 0
    for component in _walk_exercises(components):
        for set_data in component["sets"]:
            if set_data["type"] == "TimedDurationSet":
                assert set_data["autoStart"] and set_data["autoStop"], (
                    "timed sets must advance hands-free (autoStart + autoStop)"
                )
                timed_seconds += set_data["timeInMillis"] / 1000
            elif set_data["type"] == "EnduranceSet":
                assert set_data["autoStart"] and set_data["autoStop"], (
                    "timed sets must advance hands-free (autoStart + autoStop)"
                )
                timed_seconds += set_data["timeInMillis"] / 1000
    # Row 4' + bike 4x1' = the 0-8' windows; the 8-12' AMRAP must stay inside 4'
    assert timed_seconds == 480, f"timed blocks must total 8 minutes, got {timed_seconds / 60}"
    supersets = [c for c in components if c["type"] == "Superset"]
    amrap = [
        c for c in supersets
        if any("shuttle" in _normalize(e["name"]) for e in c["exercises"])
    ]
    assert len(amrap) == 1, "expected exactly one AMRAP superset (G2OH + shuttle)"
    superset_names = {_normalize(e["name"]) for e in amrap[0]["exercises"]}
    assert any("gtoh" in n or "groundtooverhead" in n for n in superset_names)
    rounds = {len(e["sets"]) for e in amrap[0]["exercises"]}
    assert len(rounds) == 1  # superset members advance in lock-step
