import json

from workout_generator_pkg.interactive_shell import (
    _build_initial_messages,
    _load_exercise_definitions,
    _load_exercise_library_payload,
)


def test_load_exercise_definitions_accepts_store_and_backup_wrapper(tmp_path):
    definition = {"id": "definition-1", "name": "Bench", "exerciseType": "WEIGHT"}
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"WorkoutStore": {"schemaVersion": 2, "exerciseDefinitions": [definition]}}))

    assert _load_exercise_definitions(str(path)) == [definition]


def test_load_exercise_library_payload_carries_store_equipment_and_movement_assets(tmp_path):
    definition = {"id": "definition-1", "name": "Bench", "exerciseType": "WEIGHT"}
    equipment = {"id": "equipment-1", "name": "Barbell", "type": "BARBELL"}
    movement = {"movementRef": {"movementId": "bench"}, "json": "{}"}
    path = tmp_path / "library-backup.json"
    path.write_text(json.dumps({
        "WorkoutStore": {
            "schemaVersion": 2,
            "exerciseDefinitions": [definition],
            "equipments": [equipment],
            "accessoryEquipments": [],
        },
        "ExerciseMovements": [movement],
    }))

    payload = _load_exercise_library_payload(str(path))

    assert payload["exerciseDefinitions"] == [definition]
    assert payload["equipments"] == [equipment]
    assert payload["exerciseMovements"] == [movement]


def test_initial_messages_preserve_compact_library_authority_context():
    definitions = [{
        "id": "definition-1",
        "name": "Bench",
        "exerciseType": "WEIGHT",
        "equipmentId": "equipment-1",
        "unused": "not included",
    }]

    messages = _build_initial_messages("base", None, lambda _: "equipment", definitions)

    assert len(messages) == 2
    assert "definition-1" in messages[1]["content"]
    assert "definition-owned and immutable" in messages[1]["content"]
    assert "unused" not in messages[1]["content"]
