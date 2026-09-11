import copy
import json

import pytest

from exercise_library_generator_pkg import generator as g


@pytest.fixture
def equipment():
    return {
        "equipments": [{"id": "bar", "type": "BARBELL", "name": "Barbell"}],
        "accessoryEquipments": [{
            "id": "rack", "type": "ACCESSORY", "name": "Rack",
            "capabilities": ["RACKED_BAR_SUPPORT"],
        }],
    }


@pytest.fixture
def definition():
    return {
        "id": "squat", "name": "Barbell Back Squat", "exerciseType": "WEIGHT",
        "equipmentId": "bar", "requiredAccessoryEquipmentIds": ["rack"],
        "bodyWeightPercentage": None, "muscleGroups": ["FRONT_QUADRICEPS"],
        "secondaryMuscleGroups": [], "exerciseCategory": "HEAVY_COMPOUND",
    }


@pytest.fixture
def generation(monkeypatch, equipment, definition):
    candidate = {key: value for key, value in definition.items() if key not in {
        "id", "muscleGroups", "secondaryMuscleGroups",
    }}
    monkeypatch.setattr(g, "_call_inventory", lambda *a, **k: [candidate])
    monkeypatch.setattr(g, "_emit_definition", lambda *a, **k: copy.deepcopy(definition))
    monkeypatch.setattr(g, "review_library_muscle_semantics", lambda *a, **k: {
        "exerciseDefinitions": [copy.deepcopy(definition)],
    })
    monkeypatch.setattr(g, "review_library_feasibility", lambda *a, **k: {
        "exerciseDefinitions": [copy.deepcopy(definition)], "semanticDiscards": [],
    })

    def run(snapshots):
        def unexpected_call(*args, **kwargs):
            pytest.fail("Unexpected model call")

        return g.generate_exercise_library(
            None, equipment, audit_passes=0, max_workers=1,
            scope_inventory_by_equipment=False,
            semantic_review_call=unexpected_call, chat_call=unexpected_call,
            reasoner_call=unexpected_call, review_checkpoint_callback=snapshots.append,
        )

    return run


def test_normalized_bodyweight_requires_an_explicit_percentage(equipment):
    candidate = {
        "name": "Weighted Squat", "exerciseType": "WEIGHT", "equipmentId": "bar",
        "requiredAccessoryEquipmentIds": [], "bodyWeightPercentage": None,
        "executionMode": "REPETITIONS", "resistanceMode": "BODY_WEIGHT_PLUS_LOAD",
    }
    with pytest.raises(g.InventoryCandidateError, match="movement-specific"):
        g._validate_candidate(candidate, equipment)
    candidate["bodyWeightPercentage"] = 85.0
    normalized = g._validate_candidate(candidate, equipment)
    assert normalized["exerciseType"] == "BODY_WEIGHT"
    assert normalized["bodyWeightPercentage"] == 85.0


@pytest.mark.parametrize("percentage", [None, True, 0, 101, float("nan")])
def test_final_validator_rejects_invalid_bodyweight_percentage(equipment, definition, percentage):
    definition.update(exerciseType="BODY_WEIGHT", bodyWeightPercentage=percentage)
    assert any(error["code"] == "BODY_WEIGHT_PERCENTAGE"
               for error in g._structured_definition_errors(definition, equipment))


def test_feasibility_repairs_claim_that_declared_capability_is_missing(equipment, definition):
    decisions = iter(["DISCARD", "KEEP"])
    calls = []

    def caller(_client, messages, *_args, **_kwargs):
        calls.append(copy.deepcopy(messages))
        decision = next(decisions)
        return json.dumps({"reviews": [{
            "reference": "DEFINITION_1", "decision": decision,
            "missingCapabilities": ["RACKED_BAR_SUPPORT"] if decision == "DISCARD" else [],
            "reason": "Rack assessment",
        }]})

    kept, discards = g._review_feasibility_batch(None, [definition], equipment, caller)
    assert kept == [definition]
    assert not discards
    assert "marked available capabilities as missing" in calls[1][-1]["content"]


@pytest.mark.parametrize("stage", ["review_library_muscle_semantics", "review_library_feasibility"])
def test_review_failure_preserves_generated_source(generation, monkeypatch, stage, definition):
    def fail(*args, **kwargs):
        raise RuntimeError("review unavailable")

    monkeypatch.setattr(g, stage, fail)
    snapshots = []
    with pytest.raises(RuntimeError, match="review unavailable"):
        generation(snapshots)
    assert snapshots[-1]["sourceExerciseDefinitions"] == [definition]
    assert snapshots[-1]["exerciseDefinitions"] == [definition]
    assert snapshots[-1]["reviewStatus"] == "PENDING"


def test_generation_rejects_empty_review_and_preserves_diagnostics(generation, monkeypatch, definition):
    monkeypatch.setattr(g, "review_library_feasibility", lambda *a, **k: {
        "exerciseDefinitions": [], "semanticDiscards": ["Squat rejected"],
    })
    snapshots = []
    with pytest.raises(ValueError, match="safety limit"):
        generation(snapshots)
    assert snapshots[-1]["reviewStatus"] == "FAILED"
    assert snapshots[-1]["exerciseDefinitions"] == [definition]
    assert snapshots[-1]["semanticDiscards"] == ["Squat rejected"]


def test_generation_preserves_feasibility_reasons(generation, monkeypatch):
    original = g.review_library_feasibility

    def reviewed(*args, **kwargs):
        return {**original(*args, **kwargs), "semanticDiscards": ["Other exercise rejected"]}

    monkeypatch.setattr(g, "review_library_feasibility", reviewed)
    snapshots = []
    result = generation(snapshots)
    assert result["semanticDiscards"] == ["Other exercise rejected"]
    assert snapshots[-1]["sourceExerciseDefinitions"]
    assert snapshots[-1]["reviewStatus"] == "COMPLETE"


def test_standalone_feasibility_rejects_mass_discard(monkeypatch, equipment, definition):
    monkeypatch.setattr(g, "_review_feasibility_resilient", lambda *a, **k: ([], ["Rejected"]))
    snapshots = []
    with pytest.raises(ValueError, match="safety limit"):
        g.review_library_feasibility(
            None, {**equipment, "exerciseDefinitions": [definition]},
            progress_callback=snapshots.append,
        )
    assert snapshots[-1]["exerciseDefinitions"] == [definition]
    assert snapshots[-1]["semanticDiscards"] == ["Rejected"]


def test_deterministic_review_cannot_publish_an_empty_library(equipment, definition):
    definition["equipmentId"] = "unknown"
    snapshots = []
    with pytest.raises(ValueError, match="safety limit"):
        g.review_library_deterministic_validation(
            None, {**equipment, "exerciseDefinitions": [definition]},
            progress_callback=snapshots.append,
        )
    assert snapshots[-1]["reviewStatus"] == "FAILED"
    assert snapshots[-1]["exerciseDefinitions"] == [definition]


def test_generation_runs_real_review_pipeline_with_fake_model_responses(equipment, definition):
    candidate = {key: value for key, value in definition.items() if key not in {
        "id", "muscleGroups", "secondaryMuscleGroups",
    }}
    snapshots = []
    stages = []

    def inventory(*args, **kwargs):
        return json.dumps({"exercises": [candidate]})

    def emitter(_client, messages, *args, **kwargs):
        emitted_candidate = json.loads(messages[-1]["content"].split("Candidate:\n")[1])
        return json.dumps({**emitted_candidate, "muscleGroups": ["FRONT_QUADRICEPS"],
                           "secondaryMuscleGroups": []})

    def reviewer(_client, messages, *args, **kwargs):
        if "anatomical map regions" in messages[0]["content"]:
            stages.append("muscles")
            review = {"reference": "DEFINITION_1", "muscleGroups": ["FRONT_QUADRICEPS"],
                      "secondaryMuscleGroups": []}
        else:
            stages.append("feasibility")
            review = {"reference": "DEFINITION_1", "decision": "KEEP",
                      "missingCapabilities": [], "reason": "Rack support is present"}
        return json.dumps({"reviews": [review]})

    result = g.generate_exercise_library(
        None, equipment, audit_passes=0, max_workers=1, scope_inventory_by_equipment=False,
        inventory_call=inventory, chat_call=emitter, reasoner_call=reviewer,
        semantic_review_call=reviewer, review_checkpoint_callback=snapshots.append,
    )
    assert stages == ["muscles", "feasibility", "feasibility"]
    assert len(result["exerciseDefinitions"]) == 1
    assert result["exerciseDefinitions"][0]["requiredAccessoryEquipmentIds"] == ["rack"]
    assert snapshots[0]["reviewStatus"] == "PENDING"
    assert snapshots[-1]["reviewStatus"] == "COMPLETE"
    assert all(snapshot["sourceExerciseDefinitions"] for snapshot in snapshots)


@pytest.mark.parametrize("max_workers", [1, 3])
@pytest.mark.parametrize("failed_phase", ["inventory", "audit"])
def test_failed_equipment_batch_stops_before_emission(
    monkeypatch, equipment, definition, max_workers, failed_phase,
):
    equipment["equipments"].append({"id": "db", "type": "DUMBBELL", "name": "Dumbbell"})

    def inventory(*args, **kwargs):
        is_audit = "audit_existing" in kwargs
        if kwargs["allowed_equipment_ids"] == {"bar"} and is_audit == (failed_phase == "audit"):
            raise RuntimeError("Barbell request timed out")
        if kwargs["allowed_equipment_ids"] == {"db"}:
            return [{**definition, "name": "Dumbbell Curl", "equipmentId": "db"}]
        return []

    def unexpected_emitter(*args, **kwargs):
        pytest.fail("Incomplete inventory reached definition emission")

    monkeypatch.setattr(g, "_call_inventory", inventory)
    monkeypatch.setattr(g, "_emit_definition", unexpected_emitter)
    with pytest.raises(ValueError, match="Inventory incomplete.*Barbell request timed out"):
        g.generate_exercise_library(None, equipment, audit_passes=1, max_workers=max_workers)


@pytest.mark.parametrize("primary_id", [None, "vest"])
def test_accessory_variants_survive_parser_audits_and_final_output(monkeypatch, primary_id):
    equipment = {
        "equipments": [{"id": "vest", "type": "WEIGHTVEST", "name": "Weight Vest"}],
        "accessoryEquipments": [
            {"id": "rings", "type": "ACCESSORY", "name": "Gymnastic Rings"},
            {"id": "bar", "type": "ACCESSORY", "name": "Pull-Up Bar"},
        ],
    }
    base = {
        "name": "Pull-Up", "exerciseType": "BODY_WEIGHT", "equipmentId": primary_id,
        "bodyWeightPercentage": 100.0,
    }
    candidates = [{**base, "requiredAccessoryEquipmentIds": [item]} for item in ("rings", "bar")]
    parsed = g._parse_inventory(json.dumps({"exercises": candidates + candidates}), equipment)
    assert len(parsed) == 2

    def inventory(*args, **kwargs):
        if kwargs["allowed_equipment_ids"] == ({primary_id} if primary_id else set()):
            # The audit repeats both variants; neither should be lost or duplicated.
            return copy.deepcopy(parsed)
        return []

    def emitter(_client, candidate, **kwargs):
        return g._validate_definition(
            {**candidate, "muscleGroups": ["BACK_UPPER_BACK"], "secondaryMuscleGroups": []},
            candidate, equipment,
        )

    monkeypatch.setattr(g, "_call_inventory", inventory)
    monkeypatch.setattr(g, "_emit_definition", emitter)
    monkeypatch.setattr(g, "review_library_muscle_semantics", lambda _client, payload, **k: payload)
    monkeypatch.setattr(g, "review_library_feasibility", lambda _client, payload, **k: payload)
    result = g.generate_exercise_library(None, equipment, audit_passes=1, max_workers=2)
    definitions = result["exerciseDefinitions"]
    assert len(definitions) == 2
    assert len({definition["id"] for definition in definitions}) == 2
    prefix = "Weight Vest, " if primary_id else ""
    assert {definition["name"] for definition in definitions} == {
        f"Pull-Up ({prefix}Gymnastic Rings)", f"Pull-Up ({prefix}Pull-Up Bar)",
    }
    assert {tuple(definition["requiredAccessoryEquipmentIds"]) for definition in definitions} == {
        ("rings",), ("bar",),
    }


def test_accessory_order_does_not_create_duplicate_candidates():
    equipment = {
        "equipments": [],
        "accessoryEquipments": [
            {"id": "bar", "type": "ACCESSORY", "name": "Pull-Up Bar"},
            {"id": "belt", "type": "ACCESSORY", "name": "Belt"},
        ],
    }
    base = {"name": "Pull-Up", "exerciseType": "BODY_WEIGHT", "equipmentId": None,
            "bodyWeightPercentage": 100.0}
    parsed = g._parse_inventory(json.dumps({"exercises": [
        {**base, "requiredAccessoryEquipmentIds": ["bar", "belt"]},
        {**base, "requiredAccessoryEquipmentIds": ["belt", "bar"]},
    ]}), equipment)
    assert len(parsed) == 1
