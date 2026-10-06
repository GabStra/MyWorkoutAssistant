import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "migrate_backup_to_exercise_library.py"
SPEC = importlib.util.spec_from_file_location("migrate_backup_to_exercise_library", SCRIPT_PATH)
assert SPEC and SPEC.loader
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def definition(name, definition_id, equipment_id=None, exercise_type="WEIGHT"):
    return {
        "id": definition_id,
        "name": name,
        "exerciseType": exercise_type,
        "equipmentId": equipment_id,
        "muscleGroups": ["BACK_DELTOIDS"],
        "requiredAccessoryEquipmentIds": [],
        "exerciseCategory": "ISOLATION",
    }


def test_bent_over_raises_maps_to_rear_delt_fly():
    old = definition(
        "Bent-Over Raises",
        "legacy",
        MIGRATION.DUMBBELL_PAIR_ID,
    )
    library = [
        definition(
            "Dumbbell Rear Delt Fly",
            "library",
            MIGRATION.DUMBBELL_PAIR_ID,
        )
    ]

    assert MIGRATION.choose_definition(old, library)["id"] == "library"


def test_weight_vest_body_weight_definition_maps_to_generated_equivalent():
    old = definition(
        "Pull-Up",
        "weighted-pull-up",
        MIGRATION.WEIGHT_VEST_ID,
        exercise_type="BODY_WEIGHT",
    )
    library = [definition("Pull-Up", "pull-up", exercise_type="BODY_WEIGHT")]

    assert MIGRATION.choose_definition(old, library)["id"] == "pull-up"


def test_applying_definition_preserves_placement_and_set_ids():
    exercise = {
        "id": "placement-id",
        "type": "Exercise",
        "exerciseDefinitionId": "legacy-definition",
        "name": "Old name",
        "sets": [{"id": "set-id", "reps": 8}],
    }
    target = definition("Dumbbell Rear Delt Fly", "library-definition")

    MIGRATION.apply_definition(exercise, target)

    assert exercise["id"] == "placement-id"
    assert exercise["sets"][0]["id"] == "set-id"
    assert exercise["exerciseDefinitionId"] == "library-definition"
    assert exercise["name"] == "Dumbbell Rear Delt Fly"


def test_spin_bike_warm_up_keeps_contextual_name_override():
    exercise = {
        "id": "placement-id",
        "type": "Exercise",
        "exerciseDefinitionId": "legacy-definition",
        "name": "Warm Up",
        "sets": [],
    }
    target = definition(
        "Spin Bike Seated Cycling",
        "spin-bike-definition",
        exercise_type="COUNTDOWN",
    )

    MIGRATION.apply_definition(exercise, target)

    assert exercise["name"] == "Warm Up"
    assert exercise["nameOverride"] == "Warm Up"
    assert exercise["exerciseDefinitionId"] == "spin-bike-definition"


def test_all_spin_bike_phase_names_are_preserved_as_contextual_overrides():
    target = definition(
        "Spin Bike Seated Cycling",
        "spin-bike-definition",
        exercise_type="COUNTDOWN",
    )

    for phase_name in ("Warm-Up", "Main Set", "Active Rest", "Cool-Down"):
        exercise = {
            "id": f"{phase_name}-placement",
            "type": "Exercise",
            "exerciseDefinitionId": "legacy-definition",
            "name": phase_name,
            "sets": [{"id": f"{phase_name}-set"}],
        }

        MIGRATION.apply_definition(exercise, target)

        assert exercise["name"] == phase_name
        assert exercise["nameOverride"] == phase_name
        assert exercise["sets"][0]["id"] == f"{phase_name}-set"


def test_pruning_removes_only_exercises_outside_generated_library():
    node = [
        {"id": "keep", "type": "Exercise", "exerciseDefinitionId": "generated"},
        {"id": "remove", "type": "Exercise", "exerciseDefinitionId": "legacy"},
    ]
    removed = MIGRATION.Counter()

    MIGRATION.prune_exercises_outside_library(
        node,
        {"generated"},
        {"legacy": "Legacy timer"},
        removed,
    )

    assert [exercise["id"] for exercise in node] == ["keep"]
    assert removed[("legacy", "Legacy timer")] == 1
