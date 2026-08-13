import argparse
import copy
import json
import re
from collections import Counter
from pathlib import Path


BARBELL_ID = "a247d19d-e625-4c84-af6a-f643bb1d076c"
DUMBBELL_PAIR_ID = "fcecd1f6-25e1-4d8b-a3d1-58cdffd6b86c"
SINGLE_DUMBBELL_ID = "f145a180-eaae-4fe1-b7b4-5527ec8adb04"
CABLE_ID = "653678c3-70bf-4425-b6b7-14bf6b752c87"
WEIGHT_VEST_ID = "e95fb928-2fc9-49b3-8dc9-2c60f5f48cd0"
LEGACY_SPIN_BIKE_ACCESSORY_ID = "1bbc8e63-a0d0-4d98-809a-928a337644e1"


NAME_ALIASES = {
    "bench press": "Barbell Bench Press",
    "barbell squat": "Barbell Back Squat",
    "back squat": "Barbell Back Squat",
    "barbell row": "Barbell Bent-Over Row",
    "row": "Barbell Bent-Over Row",
    "barbell calves": "Barbell Calf Raise",
    "db curls": "Single Dumbbell Bicep Curl",
    "db hammer curls": "Single Dumbbell Hammer Curl",
    "cable triceps pull": "Cable Triceps Pushdown",
    "triceps pushdown": "Cable Triceps Pushdown",
    "abs cable crunch": "Cable Crunch",
    "abs crunch": "Cable Crunch",
    "cable abs crunch": "Cable Crunch",
    "db rows 1 arm": "Single-Arm Dumbbell Row",
    "1 arm row": "Single-Arm Dumbbell Row",
    "1 arm db row": "Single-Arm Dumbbell Row",
    "shoulder press": "Barbell Overhead Press",
    "overhead press": "Barbell Overhead Press",
    "seated press": "Barbell Seated Overhead Press",
    "romanian deadlift": "Barbell Romanian Deadlift",
    "zercher squat": "Barbell Zercher Squat",
    "face pull": "Cable Face Pull",
    "ab wheel": "Ab Wheel Kneeling Rollout",
    "shrug": "Dumbbell Shrug",
    "shrugs": "Dumbbell Shrug",
    "lateral raises": "Dumbbell Lateral Raise",
    "bent over raises": "Dumbbell Rear Delt Fly",
    "bent over dumbbell raises": "Single-Arm Dumbbell Rear Delt Fly",
    "pull up": "Pull-Up",
    "pull ups": "Pull-Up",
    "weighted pull ups": "Pull-Up",
    "ring rows": "Ring Row",
    "ring dips": "Ring Dip",
    "dips": "Ring Dip",
    "weighted dips": "Ring Dip",
    "chin ups": "Chin-Up",
    "weighted chin ups": "Chin-Up",
    "nordic curls": "Nordic Curl",
    "hanging knee raises": "Hanging Knee Raise",
    "warm up": "Spin Bike Seated Cycling",
    "main set": "Spin Bike Seated Cycling",
    "active rest": "Spin Bike Seated Cycling",
    "cool down": "Spin Bike Seated Cycling",
}


def normalize_name(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"\bdb\b", "dumbbell", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def merge_items_by_id(existing: list[dict], authoritative: list[dict]) -> list[dict]:
    authoritative_by_id = {item["id"]: copy.deepcopy(item) for item in authoritative}
    merged = [
        authoritative_by_id.get(item["id"], copy.deepcopy(item))
        for item in existing
        if item["id"] != LEGACY_SPIN_BIKE_ACCESSORY_ID
    ]
    existing_ids = {item["id"] for item in merged}
    merged.extend(
        copy.deepcopy(item) for item in authoritative if item["id"] not in existing_ids
    )
    return merged


def choose_definition(old: dict, library_definitions: list[dict]) -> dict | None:
    old_name = normalize_name(old["name"])
    normalized_aliases = {normalize_name(name): target for name, target in NAME_ALIASES.items()}
    target_name = normalized_aliases.get(old_name, old["name"])

    if old_name == normalize_name("Bench Press"):
        target_name = {
            BARBELL_ID: "Barbell Bench Press",
            DUMBBELL_PAIR_ID: "Dumbbell Bench Press",
            SINGLE_DUMBBELL_ID: "Single Dumbbell Bench Press",
        }.get(old.get("equipmentId"), target_name)
    elif old_name == normalize_name("Bulgarian Split Squat"):
        target_name = {
            DUMBBELL_PAIR_ID: "Dumbbell Bulgarian Split Squat",
            SINGLE_DUMBBELL_ID: "Single Dumbbell Bulgarian Split Squat",
        }.get(old.get("equipmentId"), target_name)
    elif old_name in {normalize_name("DB Lateral Raises"), normalize_name("Lateral Raises")}:
        target_name = {
            DUMBBELL_PAIR_ID: "Dumbbell Lateral Raise",
            SINGLE_DUMBBELL_ID: "Single-Arm Dumbbell Lateral Raise",
        }.get(old.get("equipmentId"), target_name)
    elif old_name in {normalize_name("Shrug"), normalize_name("Shrugs")}:
        target_name = {
            DUMBBELL_PAIR_ID: "Dumbbell Shrug",
            SINGLE_DUMBBELL_ID: "Single Dumbbell Shrug",
            BARBELL_ID: "Barbell Shrug",
        }.get(old.get("equipmentId"), target_name)

    if LEGACY_SPIN_BIKE_ACCESSORY_ID in old.get("requiredAccessoryEquipmentIds", []):
        target_name = "Spin Bike Seated Cycling"

    candidates = [
        definition
        for definition in library_definitions
        if definition["exerciseType"] == old["exerciseType"]
        and normalize_name(definition["name"]) == normalize_name(target_name)
    ]
    if not candidates:
        return None

    same_equipment = [
        definition for definition in candidates
        if definition.get("equipmentId") == old.get("equipmentId")
    ]
    if len(same_equipment) == 1:
        return same_equipment[0]

    if old.get("equipmentId") is None and len(candidates) == 1:
        return candidates[0]

    if LEGACY_SPIN_BIKE_ACCESSORY_ID in old.get("requiredAccessoryEquipmentIds", []) and len(candidates) == 1:
        return candidates[0]

    if (
        old.get("equipmentId") == WEIGHT_VEST_ID
        and old["exerciseType"] == "BODY_WEIGHT"
        and len(candidates) == 1
    ):
        return candidates[0]

    return None


DEFINITION_OWNED_FIELDS = (
    "exerciseType",
    "equipmentId",
    "bodyWeightPercentage",
    "muscleGroups",
    "secondaryMuscleGroups",
    "requiredAccessoryEquipmentIds",
    "exerciseCategory",
    "movementRef",
)


def apply_definition(exercise: dict, definition: dict) -> None:
    legacy_name = exercise.get("name", "")
    name_override = exercise.get("nameOverride")
    if not name_override and (
        normalize_name(legacy_name)
        in {
            normalize_name("Warm Up"),
            normalize_name("Main Set"),
            normalize_name("Active Rest"),
            normalize_name("Cool Down"),
        }
        and normalize_name(definition["name"])
        == normalize_name("Spin Bike Seated Cycling")
    ):
        name_override = legacy_name
    elif not name_override and normalize_name(legacy_name).startswith("weighted "):
        name_override = legacy_name

    exercise["exerciseDefinitionId"] = definition["id"]
    exercise["nameOverride"] = name_override
    exercise["name"] = name_override or definition["name"]
    for field in DEFINITION_OWNED_FIELDS:
        if field in definition:
            exercise[field] = copy.deepcopy(definition[field])
        else:
            exercise.pop(field, None)


def migrate_exercises(node, mappings: dict[str, dict], counts: Counter) -> None:
    if isinstance(node, list):
        for item in node:
            migrate_exercises(item, mappings, counts)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "Exercise":
        old_definition_id = node.get("exerciseDefinitionId")
        definition = mappings.get(old_definition_id)
        if definition is not None:
            apply_definition(node, definition)
            counts[old_definition_id] += 1
    for value in node.values():
        migrate_exercises(value, mappings, counts)


def collect_definition_references(node, references: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            collect_definition_references(item, references)
    elif isinstance(node, dict):
        definition_id = node.get("exerciseDefinitionId")
        if definition_id:
            references.add(definition_id)
        for value in node.values():
            collect_definition_references(value, references)


def prune_exercises_outside_library(
    node,
    library_definition_ids: set[str],
    legacy_names_by_id: dict[str, str],
    removed: Counter,
) -> bool:
    if isinstance(node, list):
        retained = []
        for item in node:
            if prune_exercises_outside_library(
                item,
                library_definition_ids,
                legacy_names_by_id,
                removed,
            ):
                retained.append(item)
        node[:] = retained
        return True
    if not isinstance(node, dict):
        return True
    if node.get("type") == "Exercise":
        definition_id = node.get("exerciseDefinitionId")
        if definition_id not in library_definition_ids:
            removed[(definition_id, legacy_names_by_id.get(definition_id, node.get("name", "Unknown")))] += 1
            return False
    for value in node.values():
        prune_exercises_outside_library(
            value,
            library_definition_ids,
            legacy_names_by_id,
            removed,
        )
    if node.get("type") == "Superset" and not node.get("exercises"):
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--exercise-library", required=True)
    parser.add_argument("--equipment", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    backup = json.loads(Path(args.backup).read_text(encoding="utf-8"))
    library = json.loads(Path(args.exercise_library).read_text(encoding="utf-8"))
    equipment = json.loads(Path(args.equipment).read_text(encoding="utf-8"))
    store = backup["WorkoutStore"]

    old_definitions = store.get("exerciseDefinitions", [])
    library_definitions = library["exerciseDefinitions"]
    mappings = {
        old["id"]: target
        for old in old_definitions
        if (target := choose_definition(old, library_definitions)) is not None
        and target["id"] != old["id"]
    }

    migrated_counts = Counter()
    migrate_exercises(backup, mappings, migrated_counts)

    library_ids = {definition["id"] for definition in library_definitions}
    removed_exercises = Counter()
    prune_exercises_outside_library(
        backup,
        library_ids,
        {definition["id"]: definition["name"] for definition in old_definitions},
        removed_exercises,
    )
    referenced_ids: set[str] = set()
    collect_definition_references(backup, referenced_ids)
    store["exerciseDefinitions"] = copy.deepcopy(library_definitions)
    store["equipments"] = merge_items_by_id(
        store.get("equipments", []),
        equipment.get("equipments", []),
    )
    store["accessoryEquipments"] = merge_items_by_id(
        store.get("accessoryEquipments", []),
        equipment.get("accessoryEquipments", []),
    )

    final_definition_ids = {definition["id"] for definition in store["exerciseDefinitions"]}
    missing_definition_ids = sorted(referenced_ids - final_definition_ids)
    if missing_definition_ids:
        raise ValueError(f"Missing referenced definitions after migration: {missing_definition_ids}")

    report = {
        "sourceBackup": str(Path(args.backup).resolve()),
        "sourceExerciseLibrary": str(Path(args.exercise_library).resolve()),
        "sourceEquipment": str(Path(args.equipment).resolve()),
        "mappedLegacyDefinitions": len(mappings),
        "migratedExerciseOccurrences": sum(migrated_counts.values()),
        "removedLegacyDefinitions": len(old_definitions) - len(
            {definition["id"] for definition in old_definitions} & library_ids
        ),
        "removedExerciseOccurrencesWithoutLibraryEquivalent": sum(removed_exercises.values()),
        "removedExercisesWithoutLibraryEquivalent": [
            {"id": definition_id, "name": name, "occurrences": occurrences}
            for (definition_id, name), occurrences in removed_exercises.items()
        ],
        "mappings": [
            {
                "oldId": old["id"],
                "oldName": old["name"],
                "newId": mappings[old["id"]]["id"],
                "newName": mappings[old["id"]]["name"],
                "occurrences": migrated_counts[old["id"]],
            }
            for old in old_definitions if old["id"] in mappings
        ],
        "finalDefinitionCount": len(store["exerciseDefinitions"]),
        "libraryDefinitionCount": len(library_definitions),
    }

    Path(args.output).write_text(json.dumps(backup, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
