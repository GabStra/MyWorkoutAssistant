"""Tests for the no-parser WOD importer: setup-plan parsing, catalog extension,
and the definition merge. LLM calls are injected fakes — no network.
"""

import json

from wod_importer_pkg.generators import ensure_definitions
from wod_importer_pkg.setup import extend_equipment_catalog, plan_missing

FAKE_SETUP_JSON = json.dumps({
    "exercisesToCreate": ["Wall Ball", "Burpee Box Jump Over"],
    "missingEquipment": [{"name": "Medicine Ball", "type": "GENERIC"}],
})


class FakeCompletion:
    class Choice:
        class Message:
            content = FAKE_SETUP_JSON

        message = Message()

    choices = [Choice()]


class FakeClient:
    def chat(self):
        raise NotImplementedError

    class completions:
        @staticmethod
        def create(**kwargs):
            completion = FakeCompletion()
            return completion


def _def(id_, name):
    return {"id": id_, "name": name, "exerciseType": "BODY_WEIGHT", "equipmentId": None,
            "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
            "muscleGroups": [], "secondaryMuscleGroups": [], "exerciseCategory": None}


def _eq(id_, name):
    return {"id": id_, "type": "GENERIC", "name": name}


def test_plan_missing_parses_llm_json_and_filters_invalid_types():
    calls = []

    def fake_call(client, system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return json.dumps({
            "exercisesToCreate": ["Wall Ball", "  "],
            "missingEquipment": [
                {"name": "Sled", "type": "GENERIC"},
                {"name": "Magic Wand", "type": "NOT_A_TYPE"},  # must be filtered
            ],
        })

    catalog = {"equipments": [_eq("e1", "Barbell")], "accessoryEquipments": []}
    plan = plan_missing(FakeClient(), "some WOD text", catalog, ["Deadlift"], call=fake_call)

    assert plan["exercisesToCreate"] == ["Wall Ball"]
    assert plan["missingEquipment"] == [{"name": "Sled", "type": "GENERIC"}]
    # the prompt carried the whole WOD, the equipment catalog and the exercise names
    system_prompt, user_prompt = calls[0]
    assert "Available equipment" in user_prompt and "Barbell" in user_prompt
    assert "Existing exercises" in user_prompt and "Deadlift" in user_prompt
    assert "Today's WOD" in user_prompt and "some WOD text" in user_prompt


def test_extend_equipment_catalog_adds_missing_and_skips_known():
    catalog = {"equipments": [_eq("e1", "Barbell")], "accessoryEquipments": []}

    catalog, added = extend_equipment_catalog(
        catalog,
        [{"name": "Sled", "type": "GENERIC"}, {"name": "barbell", "type": "BARBELL"}],
    )

    names = [e["name"] for e in catalog["equipments"]]
    assert names == ["Barbell", "Sled"]  # "barbell" normalized-duplicate skipped
    assert added == [{"id": catalog["equipments"][1]["id"], "type": "GENERIC", "name": "Sled", "capabilities": []}]

    # deterministic ids: same request re-run adds nothing new
    _, added_again = extend_equipment_catalog(catalog, [{"name": "Sled", "type": "GENERIC"}])
    assert added_again == []


def test_ensure_definitions_merges_generated_and_skips_duplicates(tmp_path):
    working = {
        "exerciseDefinitions": [_def("d-existing", "Deadlift")],
        "equipments": [_eq("e1", "Barbell")],
        "exerciseMovements": [{"movementRef": {"movementId": "m1"}}],
    }
    library_path = tmp_path / "accumulated.json"
    calls = []

    def fake_generation(client, equipment_file, request, max_definitions):
        calls.append(request)
        return {
            "exerciseDefinitions": [
                _def("d-new", "Wall Ball"),
                _def("d-existing", "Deadlift"),  # duplicate: must be skipped
            ],
            "equipments": [_eq("e1", "Barbell"), _eq("e2", "Medicine Ball")],
        }

    library, created, _ = ensure_definitions(
        movement_names=["Wall Ball"],
        working_library=working,
        working_library_path=library_path,
        equipment_file=tmp_path / "equipment.json",
        make_client=lambda: object(),
        generate_library=fake_generation,
    )

    assert [d["name"] for d in library["exerciseDefinitions"]] == ["Deadlift", "Wall Ball"]
    assert created == ["Wall Ball"]
    assert len(calls) == 1
    assert library["exerciseMovements"] == working["exerciseMovements"]  # sidecar preserved
    assert library_path.exists()  # accumulated sidecar written


def test_ensure_definitions_retries_when_generation_missed_names(tmp_path):
    working = {"exerciseDefinitions": [], "equipments": [], "exerciseMovements": []}
    library_path = tmp_path / "accumulated.json"
    requests = []

    def fake_generation(client, equipment_file, request, max_definitions):
        requests.append(request)
        if len(requests) == 1:
            # first pass over-returns variants and misses the second requested movement
            return {"exerciseDefinitions": [_def("d1", "Bike Erg Standing")], "equipments": []}
        return {"exerciseDefinitions": [_def("d2", "Shuttle Run")], "equipments": []}

    library, created, _ = ensure_definitions(
        movement_names=["Bike Erg Standing", "Shuttle Run"],
        working_library=working,
        working_library_path=library_path,
        equipment_file=tmp_path / "equipment.json",
        make_client=lambda: object(),
        generate_library=fake_generation,
    )

    assert len(requests) == 2
    assert "Bike Erg Standing" in requests[0]
    assert "Shuttle Run" in requests[1]
    assert sorted(created) == ["Bike Erg Standing", "Shuttle Run"]
    assert {d["name"] for d in library["exerciseDefinitions"]} == {"Bike Erg Standing", "Shuttle Run"}
