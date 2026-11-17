import json

from workout_generator_pkg.prescribed_source import (
    _spans, extract_prescribed_facts, load_prescribed_source, map_prescribed_facts,
)


def _library(equipment_type="BARBELL", exercise_name="Bench Press"):
    equipment = {"id": "equip-1", "name": "Barbell" if equipment_type == "BARBELL" else "Dumbbells",
                 "type": equipment_type}
    if equipment_type == "BARBELL":
        equipment.update(barWeight=40.0, availablePlates=[])
    elif equipment_type == "DUMBBELLS":
        equipment.update(dumbbells=[{"weight": 8.0}], extraWeights=[], maxExtraWeightsPerLoadingPoint=0)
    else:
        equipment.update(availableWeights=[{"weight": 4.5}])
    definition = {"id": "def-1", "name": exercise_name, "exerciseType": "WEIGHT",
        "equipmentId": equipment["id"], "bodyWeightPercentage": None,
        "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": [],
        "requiredAccessoryEquipmentIds": [], "exerciseCategory": "MODERATE_COMPOUND"}
    return {"equipments": [equipment], "accessoryEquipments": [], "exerciseDefinitions": [definition]}


def _facts(text, *, name="Bench Press", rounds=None, rest_key=None):
    spans = _spans(text)
    exercise_key = next(key for key, line in spans.items() if name.casefold() in line.casefold())
    rest_key = rest_key or next((key for key, line in spans.items() if line.lower().startswith("rest")), None)
    return {"planName": "Source Plan", "unresolved": [],
        "exercises": [{"sourceKey": exercise_key, "rawName": name, "evidenceKeys": [exercise_key]}],
        "workouts": [{"name": "Day A", "blocks": [{"type": "straight", "exerciseKeys": [exercise_key],
            "restKey": rest_key}]}]}


def test_direct_planindex_json_does_not_call_extractor(tmp_path, monkeypatch):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import build_draft_plan

    equipment, requirements, _, draft = planning_case()
    plan = build_draft_plan(draft, equipment, requirements)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"planIndex": plan}), encoding="utf-8")
    monkeypatch.setattr("workout_generator_pkg.prescribed_source.chat_call",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("JSON source must not call a model")))
    result = load_prescribed_source(path, equipment)
    assert result["planIndex"] == plan
    assert result["unresolved"] == []


def test_text_fact_extraction_is_once_and_numbers_are_parsed_from_cited_spans(tmp_path):
    path = tmp_path / "prescription.txt"
    text = "Bench Press 3 x 8-10 @RPE 7, 40 kg\nREST 2 min"
    path.write_text(text, encoding="utf-8")
    calls = []

    def extract(source, spans):
        calls.append(1)
        return _facts(source)

    extracted = extract_prescribed_facts(path, extract=extract)
    result = map_prescribed_facts(extracted, _library())
    assert calls == [1]
    assert result["unresolved"] == []
    exercise = result["planIndex"]["exercises"][0]
    assert (exercise["numWorkSets"], exercise["minReps"], exercise["maxReps"]) == (3, 8, 10)
    assert exercise["restBetweenSetsSeconds"] == 120
    assert [item["weight"] for item in exercise["targetSetPrescriptions"]] == [40.0] * 3
    assert "RPE 7" in exercise["placementNotes"]


def test_provider_extraction_uses_exactly_one_source_only_call(tmp_path, monkeypatch):
    path = tmp_path / "prescription.txt"
    text = "Bench Press 3 x 8, 40 kg\nREST 60s"
    path.write_text(text, encoding="utf-8")
    spans = _spans(text)
    response = _facts(text)
    calls = []

    def fake_call(client, messages, **kwargs):
        calls.append((messages, kwargs))
        return json.dumps(response), None, None

    monkeypatch.setattr("workout_generator_pkg.prescribed_source.chat_call", fake_call)
    extracted = extract_prescribed_facts(path)
    assert len(calls) == 1 and calls[0][1]["retry"] is False
    assert set(json.loads(calls[0][0][-1]["content"])["sourceSpans"]) == set(spans)
    assert "library" not in calls[0][0][-1]["content"]
    assert extracted["facts"] == response


def test_repeated_source_lines_keep_distinct_code_owned_keys():
    spans = _spans("Bench Press 3 x 8\nBench Press 3 x 8")
    assert len(spans) == 2
    assert len(set(spans)) == 2


def test_per_hand_pair_load_is_doubled_but_single_dumbbell_is_not():
    pair_text = "Bench Press 3 x 8, 8 kg per hand, rest 60s"
    pair = map_prescribed_facts({"facts": _facts(pair_text), "source": {"spans": _spans(pair_text)}},
                                _library("DUMBBELLS"))
    assert pair["unresolved"] == []
    assert pair["planIndex"]["exercises"][0]["targetSetPrescriptions"][0]["weight"] == 16

    single_library = _library("DUMBBELL", "Bench Press")
    single_text = "Bench Press 3 x 8, 4.5 kg, rest 60s"
    single = map_prescribed_facts({"facts": _facts(single_text), "source": {"spans": _spans(single_text)}},
                                  single_library)
    assert single["unresolved"] == []
    assert single["planIndex"]["exercises"][0]["targetSetPrescriptions"][0]["weight"] == 4.5


def test_unsupported_or_missing_source_values_return_local_unresolved():
    text = "Bench Press 8 x 3 @RPE 7\nREST 60"
    result = map_prescribed_facts({"facts": _facts(text), "source": {"spans": _spans(text)}}, _library())
    assert result["planIndex"] is None
    assert any(item["reason"] in {"rest_unit_missing", "prescribed_rest_missing_or_unsupported"}
               for item in result["unresolved"])


def test_source_order_owns_sets_and_reps_and_rejects_fractional_quantities():
    text = "Bench Press 8 x 3, 40 kg\nREST 90s"
    mapped = map_prescribed_facts({"facts": _facts(text), "source": {"spans": _spans(text)}}, _library())
    assert mapped["unresolved"] == []
    exercise = mapped["planIndex"]["exercises"][0]
    assert exercise["numWorkSets"] == 8 and exercise["minReps"] == 3

    bad = "Bench Press 2.5 x 8, 40 kg\nREST 90.5s"
    rejected = map_prescribed_facts({"facts": _facts(bad), "source": {"spans": _spans(bad)}}, _library())
    assert rejected["planIndex"] is None
    assert {x["reason"] for x in rejected["unresolved"]} & {
        "fractional_sets_or_reps_not_supported", "fractional_rest_not_supported"}


def test_range_rest_uses_upper_bound_and_preserves_original_block_wording():
    text = "Bench Press 3 x 8, 40 kg\nREST 60-75s after both exercises"
    result = map_prescribed_facts({"facts": _facts(text), "source": {"spans": _spans(text)}}, _library())
    assert result["unresolved"] == []
    exercise = result["planIndex"]["exercises"][0]
    assert exercise["restBetweenSetsSeconds"] == 75
    assert "REST 60-75s after both exercises" in exercise["placementNotes"]


def test_superset_round_rest_does_not_create_an_extra_transition_between_blocks():
    from workout_generator_pkg.domain_ops import build_workout_structure

    text = (
        "Bench Press 2 x 8, 40 kg\n"
        "Bench Press 2 x 8, 40 kg\n"
        "2 rounds\n"
        "REST 2 min after both exercises\n"
        "Bench Press 3 x 8, 40 kg\n"
        "REST 2 min"
    )
    spans = _spans(text)
    exercise_keys = [key for key, line in spans.items() if line.startswith("Bench Press")]
    rounds_key = next(key for key, line in spans.items() if line == "2 rounds")
    ss_rest_key = next(key for key, line in spans.items() if line.startswith("REST 2 min"))
    straight_rest_key = next(key for key, line in spans.items() if line == "REST 2 min")
    facts = {
        "planName": "Recovery transition check",
        "exercises": [
            {"sourceKey": key, "rawName": "Bench Press", "evidenceKeys": [key]}
            for key in exercise_keys
        ],
        "workouts": [{"name": "Day A", "blocks": [
            {"type": "superset", "exerciseKeys": exercise_keys[:2],
             "roundsKey": rounds_key, "restKey": ss_rest_key},
            {"type": "straight", "exerciseKeys": exercise_keys[2:],
             "restKey": straight_rest_key},
        ]}],
    }
    mapped = map_prescribed_facts({"facts": facts, "source": {"spans": spans}}, _library())
    assert mapped["unresolved"] == []
    workout = mapped["planIndex"]["workouts"][0]
    assert workout["supersetGroups"][0]["restSecondsByExercise"][workout["exerciseIds"][1]] == 120
    assert workout["restToNextSeconds"] == [0, 0, 0]
    assert workout["hasRestComponents"] is False
    assert "REST 2 min after both exercises" in mapped["planIndex"]["exercises"][0]["placementNotes"]

    structure = build_workout_structure(workout)["workoutComponents"]
    assert [component["componentType"] for component in structure] == ["Superset", "Exercise"]
    assert structure[0]["restSecondsByExercise"][workout["exerciseIds"][1]] == 120

    # A rest attached to a straight block is between its sets; no standalone
    # transition timer is emitted after the completed block or the session.
    assert [exercise["restBetweenSetsSeconds"] for exercise in mapped["planIndex"]["exercises"]] == [120, 120, 120]
    assert workout["restToNextSeconds"][-1] == 0


def test_straight_block_rest_does_not_become_a_transition_between_blocks():
    from workout_generator_pkg.domain_ops import build_workout_structure

    text = "Bench Press 3 x 8, 40 kg\nREST 2 min\nBench Press 3 x 8, 40 kg\nREST 2 min"
    spans = _spans(text)
    exercise_keys = [key for key, line in spans.items() if line.startswith("Bench Press")]
    rest_keys = [key for key, line in spans.items() if line.startswith("REST")]
    facts = {
        "planName": "Straight-set recovery check",
        "exercises": [{"sourceKey": key, "rawName": "Bench Press", "evidenceKeys": [key]}
                      for key in exercise_keys],
        "workouts": [{"name": "Day A", "blocks": [
            {"type": "straight", "exerciseKeys": [exercise_keys[0]], "restKey": rest_keys[0]},
            {"type": "straight", "exerciseKeys": [exercise_keys[1]], "restKey": rest_keys[1]},
        ]}],
    }
    mapped = map_prescribed_facts({"facts": facts, "source": {"spans": spans}}, _library())
    assert mapped["unresolved"] == []
    workout = mapped["planIndex"]["workouts"][0]
    assert workout["restToNextSeconds"] == [0, 0]
    assert all(exercise["restBetweenSetsSeconds"] == 120 for exercise in mapped["planIndex"]["exercises"])
    structure = build_workout_structure(workout)["workoutComponents"]
    assert [component["componentType"] for component in structure] == ["Exercise", "Exercise"]


def test_source_order_and_superset_grouping_must_be_grounded_in_spans():
    text = "Bench Press 3 x 8, 40 kg\nBench Press 3 x 8, 40 kg\nREST 60s"
    spans = _spans(text)
    keys = [key for key, line in spans.items() if line.startswith("Bench Press")]
    rest_key = next(key for key, line in spans.items() if line.startswith("REST"))
    facts = {
        "planName": "Grounding check",
        "exercises": [{"sourceKey": key, "rawName": "Bench Press", "evidenceKeys": [key]} for key in keys],
        "workouts": [{"name": "Day A", "blocks": [{"type": "straight", "exerciseKeys": keys,
                                                        "restKey": rest_key}]}],
    }
    facts["workouts"][0]["blocks"][0]["exerciseKeys"] = list(reversed(keys))
    reordered = map_prescribed_facts({"facts": facts, "source": {"spans": spans}}, _library())
    assert reordered["planIndex"] is None
    assert any(item["reason"] == "source_occurrence_order_mismatch" for item in reordered["unresolved"])

    # Two selected exercises alone do not establish that the source prescribed
    # a superset; an explicit rounds or grouping cue must be cited.
    facts["workouts"][0]["blocks"][0] = {"type": "superset", "exerciseKeys": keys, "restKey": rest_key}
    invented_group = map_prescribed_facts({"facts": facts, "source": {"spans": spans}}, _library())
    assert invented_group["planIndex"] is None
    assert any(item["reason"] == "superset_grouping_evidence_missing" for item in invented_group["unresolved"])


def test_rounds_count_conflicting_with_member_sets_is_rejected():
    text = "Bench Press 3 x 8, 40 kg\n2 rounds\nREST 60s"
    spans = _spans(text)
    exercise_key = next(key for key, line in spans.items() if line.startswith("Bench Press"))
    rounds_key = next(key for key, line in spans.items() if line == "2 rounds")
    rest_key = next(key for key, line in spans.items() if line.startswith("REST"))
    facts = {
        "planName": "Rounds mismatch",
        "exercises": [{"sourceKey": exercise_key, "rawName": "Bench Press", "evidenceKeys": [exercise_key]}],
        "workouts": [{"name": "Day A", "blocks": [{"type": "straight", "exerciseKeys": [exercise_key],
            "roundsKey": rounds_key, "restKey": rest_key}]}],
    }
    result = map_prescribed_facts({"facts": facts, "source": {"spans": spans}}, _library())
    assert result["planIndex"] is None
    assert any(item["reason"] == "rounds_count_conflicts_with_sets" for item in result["unresolved"])


def test_missing_cited_prescription_line_is_not_guessed():
    text = "Bench Press 3 x 8, 40 kg\nREST 60s"
    facts = _facts(text)
    facts["workouts"][0]["blocks"][0]["exerciseKeys"] = []
    result = map_prescribed_facts({"facts": facts, "source": {"spans": _spans(text)}}, _library())
    assert result["planIndex"] is None
    assert any(item["reason"] == "unassigned_or_unknown_exercise_fact" for item in result["unresolved"])


def test_unassigned_tempo_or_warmup_instruction_blocks_partial_plan():
    text = "Bench Press 3 x 8, 40 kg\nTempo 3-1-2\nREST 60s"
    facts = _facts(text)
    result = map_prescribed_facts({"facts": facts, "source": {"spans": _spans(text)}}, _library())
    assert result["planIndex"] is None
    assert any(item["reason"] == "source_instruction_not_assigned_or_unsupported" for item in result["unresolved"])


def test_model_cannot_assign_an_unrelated_library_name_to_a_cited_line():
    text = "Bench Press 3 x 8, 40 kg\nREST 60s"
    facts = _facts(text, name="Bench Press")
    facts["exercises"][0]["rawName"] = "Back Squat"
    result = map_prescribed_facts({"facts": facts, "source": {"spans": _spans(text)}},
                                  _library("BARBELL", "Back Squat"))
    assert result["planIndex"] is None
    assert any(item["reason"] == "exercise_name_not_present_in_source_line" for item in result["unresolved"])


def test_source_name_modifiers_cannot_be_dropped_and_other_rows_cannot_donate_quantities():
    text = "Incline Dumbbell Bench Press 3 x 8, 12 kg\nREST 60s"
    spans = _spans(text)
    key = next(key for key, line in spans.items() if line.startswith("Incline"))
    rest_key = next(key for key, line in spans.items() if line.startswith("REST"))
    facts = _facts(text, name="Dumbbell Bench Press")
    facts["workouts"][0]["blocks"][0]["restKey"] = rest_key
    dropped_modifier = map_prescribed_facts(
        {"facts": facts, "source": {"spans": spans}}, _library("DUMBBELL", "Dumbbell Bench Press"))
    assert dropped_modifier["planIndex"] is None
    assert any(item["reason"] == "exercise_name_not_present_in_source_line"
               for item in dropped_modifier["unresolved"])

    borrowed_text = "Bench Press 3 x 8\nIncline Bench Press 4 x 10, 40 kg\nREST 60s"
    borrowed_spans = _spans(borrowed_text)
    primary = next(key for key, line in borrowed_spans.items() if line.startswith("Bench Press"))
    other = next(key for key, line in borrowed_spans.items() if line.startswith("Incline"))
    borrowed_rest = next(key for key, line in borrowed_spans.items() if line.startswith("REST"))
    borrowed_facts = _facts(borrowed_text, name="Bench Press")
    borrowed_facts["exercises"][0]["sourceKey"] = primary
    borrowed_facts["exercises"][0]["evidenceKeys"] = [primary, other]
    borrowed_facts["workouts"][0]["blocks"][0]["exerciseKeys"] = [primary]
    borrowed_facts["workouts"][0]["blocks"][0]["restKey"] = borrowed_rest
    borrowed = map_prescribed_facts(
        {"facts": borrowed_facts, "source": {"spans": borrowed_spans}}, _library())
    assert borrowed["planIndex"] is None
    assert any(item["reason"] == "other_prescription_row_used_as_evidence"
               for item in borrowed["unresolved"])


def test_operator_cached_definition_mapping_repairs_a_grounded_source_alias():
    text = "Back Squat 3 x 8, 40 kg\nREST 60s"
    facts = _facts(text, name="Back Squat")
    extracted = {"facts": facts, "source": {"spans": _spans(text)}}
    library = _library("BARBELL", "Barbell Back Squat")
    initial = map_prescribed_facts(extracted, library)
    assert initial["planIndex"] is None
    diagnostic = initial["unresolved"][0]
    assert diagnostic["reason"] == "library_definition_missing"
    assert diagnostic["candidates"][0] == {"id": "def-1", "name": "Barbell Back Squat"}

    key = facts["exercises"][0]["sourceKey"]
    # Operator edits the cached extraction wrapper, outside model-returned facts.
    extracted["definitionMappings"] = {key: "def-1"}
    mapped = map_prescribed_facts(extracted, library)
    assert mapped["unresolved"] == []
    exercise = mapped["planIndex"]["exercises"][0]
    assert exercise["libraryDefinitionId"] == "def-1"
    assert exercise["nameOverride"] == "Back Squat"
    assert "source name 'Back Squat' mapped to 'Barbell Back Squat'" in exercise["placementNotes"]


def test_invalid_operator_definition_mapping_is_rejected():
    text = "Back Squat 3 x 8, 40 kg\nREST 60s"
    facts = _facts(text, name="Back Squat")
    key = facts["exercises"][0]["sourceKey"]
    result = map_prescribed_facts({"facts": facts, "source": {"spans": _spans(text)},
                                   "definitionMappings": {key: "unknown-definition"}},
                                  _library("BARBELL", "Barbell Back Squat"))
    assert result["planIndex"] is None
    assert any(item["reason"] == "operator_mapping_definition_unknown" for item in result["unresolved"])


def test_model_facts_cannot_supply_operator_library_id_overrides():
    text = "Back Squat 3 x 8, 40 kg\nREST 60s"
    facts = _facts(text, name="Back Squat")
    key = facts["exercises"][0]["sourceKey"]
    facts["definitionMappings"] = {key: "def-1"}
    result = map_prescribed_facts({"facts": facts, "source": {"spans": _spans(text)}},
                                  _library("BARBELL", "Barbell Back Squat"))
    assert result["planIndex"] is None
    assert any(item["reason"] == "library_definition_missing" for item in result["unresolved"])


def test_unsupported_comma_decimal_and_scientific_loads_are_not_partially_parsed():
    for load in ("1,5 kg", "1e309 kg"):
        text = f"Bench Press 3 x 8, {load}\nREST 60s"
        result = map_prescribed_facts({"facts": _facts(text), "source": {"spans": _spans(text)}}, _library())
        assert result["planIndex"] is None
        assert any(item["reason"] == "exact_load_missing_from_source" for item in result["unresolved"])
