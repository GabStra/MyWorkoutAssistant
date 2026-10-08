"""Tests for the no-parser WOD importer: equipment planning, catalog extension,
the generator-native coverage pass, and the definition merge. All LLM calls are
injected fakes — no network.
"""

import json

from wod_importer_pkg.generators import ensure_wod_coverage
from wod_importer_pkg.setup import extend_equipment_catalog, plan_missing_equipment


class _FakeMessage:
    content = json.dumps({"missingEquipment": [{"name": "Sled", "type": "GENERIC"}]})


class _FakeCompletions:
    @staticmethod
    def create(**kwargs):
        return type("R", (), {"choices": [type("C", (), {"message": _FakeMessage()})]})()


class FakeClient:
    completions = _FakeCompletions()


def _def(id_, name):
    return {"id": id_, "name": name, "exerciseType": "BODY_WEIGHT", "equipmentId": None,
            "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
            "muscleGroups": [], "secondaryMuscleGroups": [], "exerciseCategory": None}


def _eq(id_, name):
    return {"id": id_, "type": "GENERIC", "name": name}


def test_plan_missing_equipment_parses_and_filters_invalid_types():
    calls = []

    def fake_call(client, system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return json.dumps({
            "missingEquipment": [
                {"name": "Sled", "type": "GENERIC"},
                {"name": "Magic Wand", "type": "NOT_A_TYPE"},  # filtered out
            ],
        })

    catalog = {"equipments": [_eq("e1", "Barbell")], "accessoryEquipments": []}
    missing = plan_missing_equipment(FakeClient(), "WOD with sled pushes", catalog, call=fake_call)

    assert missing == [{"name": "Sled", "type": "GENERIC"}]
    system_prompt, user_prompt = calls[0]
    assert "Barbell" in user_prompt and "WOD with sled pushes" in user_prompt


def test_plan_missing_equipment_empty_when_catalog_suffices():
    def fake_call(client, system_prompt, user_prompt):
        return json.dumps({"missingEquipment": []})

    catalog = {"equipments": [_eq("e1", "Rower")], "accessoryEquipments": []}
    assert plan_missing_equipment(FakeClient(), "4 min row", catalog, call=fake_call) == []


def test_extend_equipment_catalog_adds_missing_and_skips_known():
    catalog = {"equipments": [_eq("e1", "Barbell")], "accessoryEquipments": []}

    catalog, added = extend_equipment_catalog(
        catalog,
        [{"name": "Sled", "type": "GENERIC"}, {"name": "barbell", "type": "BARBELL"}],
    )

    assert [e["name"] for e in catalog["equipments"]] == ["Barbell", "Sled"]
    assert len(added) == 1

    # deterministic ids: same request re-run adds nothing new
    _, added_again = extend_equipment_catalog(catalog, [{"name": "Sled", "type": "GENERIC"}])
    assert added_again == []


def test_coverage_pass_generates_only_missing_and_persists(tmp_path):
    """The generator's audit decides coverage; generation emits only the missing."""
    working = {
        "exerciseDefinitions": [_def("d-existing", "Deadlift")],
        "equipments": [_eq("e1", "Barbell")],
        "exerciseMovements": [{"movementRef": {"movementId": "m1"}}],
    }
    library_path = tmp_path / "accumulated.json"
    audits = []
    generations = []

    def fake_audit(client, equipment, wod_text, library):
        audits.append(wod_text)
        # the generator's audit sees Deadlift as covered, Wall Ball as missing
        return ["Deadlift", "Wall Ball"]

    def fake_generation(client, equipment_file, request, max_definitions):
        generations.append(request)
        assert "Wall Ball" in request and "Deadlift" not in request
        return {
            "exerciseDefinitions": [_def("d-new", "Wall Ball")],
            "equipments": [_eq("e2", "Medicine Ball")],
        }

    library, created = ensure_wod_coverage(
        client=FakeClient(),
        wod_text="WOD with wall balls",
        working_library=working,
        working_library_path=library_path,
        equipment_file=tmp_path / "equipment.json",
        audit_call=fake_audit,
        generate_library=fake_generation,
    )

    names = [d["name"] for d in library["exerciseDefinitions"]]
    assert names == ["Deadlift", "Wall Ball"]
    assert created == ["Wall Ball"]
    # audit -> generate -> re-audit: the loop verifies coverage after generating
    assert len(audits) == 2 and len(generations) == 1
    assert library["exerciseMovements"] == working["exerciseMovements"]
    assert library_path.exists()


def test_coverage_pass_skips_generation_when_all_covered(tmp_path):
    working = {"exerciseDefinitions": [_def("d1", "Row")], "equipments": [], "exerciseMovements": []}
    generations = []

    def fake_audit(client, equipment, wod_text, library):
        return ["Row"]  # audit says everything is covered

    def fake_generation(client, equipment_file, request, max_definitions):
        generations.append(request)
        return {"exerciseDefinitions": [], "equipments": []}

    library, created = ensure_wod_coverage(
        client=FakeClient(),
        wod_text="4 min row",
        working_library=working,
        working_library_path=tmp_path / "accumulated.json",
        equipment_file=tmp_path / "equipment.json",
        audit_call=fake_audit,
        generate_library=fake_generation,
    )

    assert created == [] and generations == []
    assert [d["name"] for d in library["exerciseDefinitions"]] == ["Row"]
