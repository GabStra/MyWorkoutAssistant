import copy
import json
import threading
import time

import pytest

from workout_generator_pkg import exercise_library_tools as library_tools
from workout_generator_pkg.domain_ops import (
    finalize_and_validate_exercise_definition, sync_exercises_from_definitions,
    sync_exercises_from_plan_index, ensure_requiresLoadCalibration,
)
from workout_generator_pkg.plan_contract import (
    ContractValidationError, validate_workout_structures_contract,
    validate_assembled_workout_contract,
)


def test_semantic_search_uses_bounded_batches_and_returns_real_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    definitions = [{"id": f"definition-{i}", "name": f"Exercise {i}"} for i in range(260)]
    definitions[0]["name"] = "Barbell Bench Press"
    batch_sizes = []

    def rank(_client, messages, **kwargs):
        assert kwargs == {"reasoning_effort": "low", "max_tokens": 8192, "timeout": 90}
        request = json.loads(messages[-1]["content"])
        batch_sizes.append(len(request["catalog"]))
        matches = ([{"index": i, "score": 0.99 - i * 0.01} for i in range(10)]
                   if request["catalog"][0][0] == 0 else [])
        return json.dumps({"matches": [matches]}), None, None

    monkeypatch.setattr(library_tools, "chat_call", rank)
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("local model unavailable")))
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["horizontal chest push"]},
        {"exerciseDefinitions": definitions}, client=object(),
    )
    assert sorted(batch_sizes) == [4, 64, 64, 64, 64]
    assert len(result["results"][0]["exercises"]) == 6
    assert result["results"][0]["exercises"][0]["id"] == "LIBRARY_0"
    assert result["results"][0]["exercises"][0]["name"] == "Barbell Bench Press"
    selection = library_tools.execute_library_tool("select_exercises", {"definition_ids": ["LIBRARY_0"]}, {"exerciseDefinitions": list(reversed(definitions))})
    assert selection["selectedExerciseDefinitionIds"] == ["definition-0"]


def test_semantic_search_jobs_bound_queries_catalog_and_parallelism(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    active = 0
    max_active = 0
    lock = threading.Lock()
    job_sizes = []

    def rank(_client, messages, **kwargs):
        nonlocal active, max_active
        request = json.loads(messages[-1]["content"])
        with lock:
            active += 1
            max_active = max(max_active, active)
        job_sizes.append((len(request["queries"]), len(request["catalog"])))
        time.sleep(0.01)
        with lock:
            active -= 1
        return json.dumps({"matches": [[] for _ in request["queries"]]}), None, None

    monkeypatch.setattr(library_tools, "chat_call", rank)
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("local model unavailable")))
    progress = []
    result = library_tools._semantic_matches(
        object(), [f"query {i}" for i in range(7)], [{"name": f"Exercise {i}"} for i in range(130)],
        progress=lambda done, total: progress.append((done, total)),
    )
    assert result == [{} for _ in range(7)]
    assert progress == [(done, 9) for done in range(10)]
    assert len(job_sizes) == 9
    assert all(query_count <= 3 and catalog_count <= 64 for query_count, catalog_count in job_sizes)
    assert max_active <= 3


def test_semantic_search_and_selection_reject_invented_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    gear = {"exerciseDefinitions": [{"id": "definition-0", "name": "Bench Press"}]}
    monkeypatch.setattr(library_tools, "chat_call", lambda *_, **kw: ('{"matches":[[{"index":99,"score":1}]]}', None, None))
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("local model unavailable")))
    failed_search = library_tools.execute_library_tool("search_exercise_library", {"queries": ["press"]}, gear, client=object())
    assert "unknown index" in failed_search["results"][0]["error"]
    assert failed_search["instruction"]
    with pytest.raises(ValueError, match="Unknown library definition IDs"):
        library_tools.execute_library_tool("select_exercises", {"definition_ids": ["invented"]}, gear)


def test_truncated_semantic_search_preserves_exact_hits_and_reports_failed_queries(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    gear = {"exerciseDefinitions": [
        {"id": "bench", "name": "Bench Press"},
        {"id": "row", "name": "Cable Row"},
    ]}

    def truncated(*_args, **_kwargs):
        raise ValueError("Response truncated at the 4096-token low-effort budget")

    monkeypatch.setattr(library_tools, "chat_call", truncated)
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("local model unavailable")))
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["bench press", "horizontal pull"]}, gear, client=object(),
    )
    assert result["results"][0]["exercises"][0]["id"] == "LIBRARY_0"
    assert result["results"][1]["error"].startswith("Semantic search failed:")
    assert result["results"][1]["exercises"] == []
    assert result["results"][1]["matchMethod"] == "semantic_partial"
    assert "do not repeat the same failed query unchanged" in result["instruction"]


def test_local_semantic_search_avoids_model_fanout_and_returns_library_placeholders(monkeypatch):
    definitions = [
        {"id": "uuid-a", "name": "Barbell Back Squat"},
        {"id": "uuid-b", "name": "Barbell Curl"},
    ]
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda queries, entries, **kwargs: [{0: 0.72, 1: 0.31}])
    monkeypatch.setattr(library_tools, "chat_call", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("confident local ranking should not call LLM")))
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["quad dominant compound squat"]},
        {"exerciseDefinitions": definitions}, client=object(),
    )
    matches = result["results"][0]["exercises"]
    assert [item["id"] for item in matches] == ["LIBRARY_0", "LIBRARY_1"]
    assert matches[0]["name"] == "Barbell Back Squat"


def test_structured_muscle_filter_excludes_semantically_similar_unrelated_exercises(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    definitions = [
        {"id": "cable-triceps", "name": "Cable Overhead Tricep Extension", "muscleGroups": ['FRONT_TRICEPS'], "secondaryMuscleGroups": []},
        {"id": "quad-extension", "name": "Leg Extension", "muscleGroups": ['FRONT_QUADRICEPS'], "secondaryMuscleGroups": []},
        {"id": "quad-assist", "name": "Front Squat", "exerciseCategory": "HEAVY_COMPOUND",
         "muscleGroups": ['FRONT_QUADRICEPS'], "secondaryMuscleGroups": ['FRONT_TRICEPS']},
    ]
    seen = []
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda _queries, entries, **_kwargs: (seen.extend(e["name"] for e in entries) or [{i: 0.9 for i in range(len(entries))}]))
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["isolation exercise"], "muscleTargets": ["quads"]},
        {"exerciseDefinitions": definitions}, client=object(),
    )
    assert set(seen) == {"Leg Extension", "Front Squat"}
    assert {item["name"] for item in result["results"][0]["exercises"]} == {"Leg Extension", "Front Squat"}


def test_structured_muscle_role_filter_allows_compound_assistance_when_requested(monkeypatch):
    definitions = [{"id": "squat", "name": "Front Squat", "exerciseCategory": "HEAVY_COMPOUND",
                    "muscleGroups": ['FRONT_QUADRICEPS'], "secondaryMuscleGroups": ['BACK_GLUTEAL']}]
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda _q, entries, **_kwargs: [{0: 0.8}] if entries else [])
    equipment = {"exerciseDefinitions": definitions}
    no_assistance = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["glutes"], "muscleTargets": ["glutes"]}, equipment,
    )
    with_assistance = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["glutes"], "muscleTargets": ["glutes"], "muscleRole": "any"}, equipment,
    )
    assert no_assistance["results"][0]["matchMethod"] == "no_suitable_matches"
    assert with_assistance["results"][0]["exercises"][0]["name"] == "Front Squat"


def test_structured_muscle_filter_rejects_unsupported_targets():
    with pytest.raises(ValueError, match="supported muscle targets"):
        library_tools.execute_library_tool(
            "search_exercise_library", {"queries": ["quad isolation"], "muscleTargets": ["vastus lateralis"]},
            {"exerciseDefinitions": [{"id": "leg-extension", "name": "Leg Extension"}]},
        )


def test_search_schema_and_runtime_use_loaded_library_muscle_capabilities():
    from jsonschema import validate, ValidationError
    equipment = {'exerciseDefinitions': [{'id': 'row', 'name': 'Row', 'exerciseCategory': 'MODERATE_COMPOUND',
                 'muscleGroups': ['BACK_UPPER_BACK'], 'secondaryMuscleGroups': ['FRONT_BICEPS']}]}
    original = copy.deepcopy(library_tools.SEARCH_EXERCISE_LIBRARY_TOOL)
    tool = library_tools.exercise_library_search_tool(equipment)
    schema = tool['function']['parameters']
    assert set(schema['properties']['muscleTargets']['items']['enum']) == {'back', 'biceps'}
    args = {'queries': ['row'], 'muscleTargets': ['lats']}
    with pytest.raises(ValidationError):
        validate(args, schema)
    with pytest.raises(ValueError, match='supported muscle targets'):
        library_tools.execute_library_tool('search_exercise_library', args, equipment)
    assert library_tools.SEARCH_EXERCISE_LIBRARY_TOOL == original


def test_empty_intersection_explains_filter_scope_without_claiming_library_gap():
    equipment = {'exerciseDefinitions': [
        {'id': 'press', 'name': 'Press', "muscleGroups": ['FRONT_CHEST'], "secondaryMuscleGroups": ['FRONT_DELTOIDS']},
        {'id': 'ohp', 'name': 'Overhead press', "muscleGroups": ['FRONT_DELTOIDS'], "secondaryMuscleGroups": []},
    ]}
    result = library_tools.execute_library_tool('search_exercise_library',
        {'queries': ['press'], 'muscleTargets': ['chest', 'shoulders']}, equipment)
    row = result['results'][0]
    assert not row['exercises']
    assert 'All muscleTargets must match' in row['reason']
    assert 'Split alternative muscle groups' in row['reason']


def test_structured_filters_exclude_glute_credit_and_non_isolation_categories(monkeypatch):
    definitions = [
        {"id": "quad-only", "name": "Leg Extension", "exerciseCategory": "ISOLATION",
         "muscleGroups": ['FRONT_QUADRICEPS'], "secondaryMuscleGroups": []},
        {"id": "quad-glute", "name": "Squat", "exerciseCategory": "HEAVY_COMPOUND",
         "muscleGroups": ['FRONT_QUADRICEPS', 'BACK_GLUTEAL'], "secondaryMuscleGroups": []},
        {"id": "quad-curl", "name": "Leg Press", "exerciseCategory": "MODERATE_COMPOUND",
         "muscleGroups": ['FRONT_QUADRICEPS'], "secondaryMuscleGroups": []},
    ]
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda _q, entries, **_kwargs: [{i: 0.8 for i in range(len(entries))}])
    result = library_tools.execute_library_tool(
        "search_exercise_library",
        {"queries": ["quad isolation"], "muscleTargets": ["quads"], "excludedMuscleTargets": ["glutes"],
         "exerciseCategories": ["ISOLATION"]},
        {"exerciseDefinitions": definitions},
    )
    assert [item["name"] for item in result["results"][0]["exercises"]] == ["Leg Extension"]


def test_combined_search_batches_only_calls_with_identical_filters(monkeypatch):
    batches = []

    def execute(_name, arguments, *_args, **_kwargs):
        batches.append(dict(arguments))
        return {"libraryFingerprint": "library", "searchFingerprint": json.dumps(arguments, sort_keys=True), "results": [
            {"query": query, "libraryFingerprint": "library", "searchFingerprint": json.dumps(arguments, sort_keys=True),
             "exercises": [{"name": query}]} for query in arguments["queries"]
        ]}

    monkeypatch.setattr(library_tools, "execute_library_tool", execute)
    calls = [
        ("quad", {"queries": ["isolation"], "muscleTargets": ["quads"], "exerciseCategories": ["ISOLATION"]}),
        ("free", {"queries": ["press"]}),
        ("quad2", {"queries": ["single joint"], "muscleTargets": ["quads"], "exerciseCategories": ["ISOLATION"]}),
    ]
    result = library_tools.execute_library_searches(calls, {}, object(), [])
    assert len(batches) == 2
    assert {key for batch in batches for key in batch if key != "queries"} == {"muscleTargets", "exerciseCategories"}
    assert len(result["quad"]["results"]) == len(result["quad2"]["results"]) == len(result["free"]["results"]) == 1


def test_combined_search_keeps_same_query_results_isolated_by_muscle_filter(monkeypatch):
    ranked_catalogs = []

    def rank(queries, entries, **_kwargs):
        ranked_catalogs.append((queries, [item["name"] for item in entries]))
        return [{index: 0.9 for index in range(len(entries))}]

    monkeypatch.setattr(library_tools, "_local_semantic_rank", rank)
    equipment = {"exerciseDefinitions": [
        {"id": "quad", "name": "Leg Extension", "muscleGroups": ['FRONT_QUADRICEPS'], "secondaryMuscleGroups": []},
        {"id": "triceps", "name": "Cable Extension", "muscleGroups": ['FRONT_TRICEPS'], "secondaryMuscleGroups": []},
    ]}
    result = library_tools.execute_library_searches([
        ("quad", {"queries": ["extension"], "muscleTargets": ["quads"]}),
        ("triceps", {"queries": ["extension"], "muscleTargets": ["triceps"]}),
    ], equipment, object(), [])
    assert sorted(ranked_catalogs) == sorted([(["extension"], ["Leg Extension"]), (["extension"], ["Cable Extension"])])
    assert result["quad"]["results"][0]["exercises"][0]["name"] == "Leg Extension"
    assert result["triceps"]["results"][0]["exercises"][0]["name"] == "Cable Extension"
    assert result["quad"]["searchFingerprint"] != result["triceps"]["searchFingerprint"]


def test_local_semantic_search_clamps_tiny_cosine_overshoot(monkeypatch):
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: [{0: 1.000000238418579}])
    result = library_tools._semantic_matches(None, ["Bench Press"], [{"name": "Bench Press"}])
    assert result[0][0] == 1.0


@pytest.mark.parametrize("ranking", [
    [{0: 1.01}],
    [{0: float("nan")}],
    [{0: float("inf")}],
    [{1: 0.9}],
    [{True: 0.9}],
    [{0: "0.9"}],
    [],
    [None],
])
def test_malformed_local_semantic_ranking_fails_closed_as_runtime_error(monkeypatch, ranking):
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: ranking)
    with pytest.raises(RuntimeError, match="Local semantic search returned an invalid"):
        library_tools._semantic_matches(None, ["press"], [{"name": "Bench Press"}])


def test_malformed_local_ranking_surfaces_as_tool_execution_failure(monkeypatch):
    from workout_generator_pkg.planning_tools import planning_tool_failure

    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: [{0: 1.01}])
    with pytest.raises(RuntimeError) as caught:
        library_tools.execute_library_tool(
            "search_exercise_library", {"queries": ["press"]},
            {"exerciseDefinitions": [{"id": "definition-0", "name": "Bench Press"}]},
        )
    failure = planning_tool_failure("search_exercise_library", caught.value)
    assert failure["errors"][0]["code"] == "tool_execution_failed"
    assert "Report this execution failure" in failure["errors"][0]["repair"]


def test_failed_search_rerank_can_retry_after_a_new_user_turn(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, 'CACHE_DIRECTORY', tmp_path)
    monkeypatch.setattr(library_tools, '_local_semantic_rank', lambda *_args, **_kwargs: [{0: 0.1}])
    calls = []

    def rerank(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('temporary outage')
        return '{"matches":[[{"index":0,"score":0.9}]]}', None, None

    monkeypatch.setattr(library_tools, 'chat_call', rerank)
    equipment = {'exerciseDefinitions': [{'id': 'press', 'name': 'Bench Press'}]}
    arguments = {'queries': ['pressing movement']}
    messages = [{'role': 'user', 'content': 'Find a pressing movement.'}]
    failed = library_tools.execute_library_tool('search_exercise_library', arguments, equipment, object(), messages)
    assert failed['results'][0]['rerankWarning']
    messages.append({'role': 'tool', 'content': json.dumps(failed)})
    library_tools.execute_library_tool('search_exercise_library', arguments, equipment, object(), messages)
    assert len(calls) == 1
    messages.append({'role': 'user', 'content': 'Retry that lookup.'})
    recovered = library_tools.execute_library_tool('search_exercise_library', arguments, equipment, object(), messages)
    assert len(calls) == 2
    assert 'rerankWarning' not in recovered['results'][0]


def test_failed_weak_match_rerank_is_reported_as_uncertain(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: [{0: 0.1}])
    monkeypatch.setattr(library_tools, "chat_call", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    result = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["unrelated movement"]},
        {"exerciseDefinitions": [{"id": "uuid-a", "name": "Bench Press"}]}, client=object(),
    )
    item = result["results"][0]
    assert item["matchMethod"] == "local_semantic_uncertain"
    assert item["rerankWarning"] == "offline"
    assert "ordering is uncertain" in result["instruction"]


def test_uncertain_local_ranking_reranks_only_shortlist_and_caches_valid_result(monkeypatch, tmp_path):
    entries = [{"name": f"Exercise {index}"} for index in range(80)]
    local = {index: 0.30 - index / 1000 for index in range(80)}
    calls = []
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: [dict(local)])

    def rerank(_client, messages, **_kwargs):
        request = json.loads(messages[-1]["content"])
        calls.append(request)
        return json.dumps({"matches": [[{"index": 0, "score": 0.97}, {"index": 1, "score": 0.9}]]}), None, None

    monkeypatch.setattr(library_tools, "chat_call", rerank)
    result = library_tools._semantic_matches(object(), ["ambiguous query"], entries)
    repeated = library_tools._semantic_matches(object(), ["ambiguous query"], entries)
    assert len(calls) == 1
    assert len(calls[0]["catalog"]) <= 24
    assert list(result[0]) == [0, 1]
    assert result[0][0] == 0.97
    assert repeated == result


def test_legacy_fallback_reuses_completed_catalog_batches_after_partial_failure(monkeypatch, tmp_path):
    definitions = [{"id": f"id-{index}", "name": f"Exercise {index}"} for index in range(130)]
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    monkeypatch.setattr(library_tools, "_local_semantic_rank", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("local model unavailable")))
    calls = []
    fail_once = {64}

    def rank(_client, messages, **_kwargs):
        request = json.loads(messages[-1]["content"])
        first_index = request["catalog"][0][0]
        calls.append(first_index)
        if first_index in fail_once:
            fail_once.remove(first_index)
            raise RuntimeError("temporary batch failure")
        return json.dumps({"matches": [[{"index": first_index, "score": 0.8}]]}), None, None

    monkeypatch.setattr(library_tools, "chat_call", rank)
    equipment = {"exerciseDefinitions": definitions}
    partial = library_tools.execute_library_tool("search_exercise_library", {"queries": ["compound exercise"]}, equipment, client=object())
    assert partial["results"][0]["error"].startswith("Semantic search failed:")
    assert partial["results"][0]["complete"] is False
    # The library is sorted by ID before LIBRARY_n assignment, so LIBRARY_128 maps to Exercise 98.
    assert {item["name"] for item in partial["results"][0]["exercises"]} == {"Exercise 0", "Exercise 98"}
    completed_after_first_run = calls.count(0) + calls.count(128)
    assert completed_after_first_run == 2

    complete = library_tools.execute_library_tool("search_exercise_library", {"queries": ["compound exercise"]}, equipment, client=object())
    assert "error" not in complete["results"][0]
    assert sorted(calls[:3]) == [0, 64, 128]
    assert calls[3:] == [64]


def test_get_exercise_candidates_returns_only_valid_current_library_refs():
    equipment = {"exerciseDefinitions": [
        {"id": "uuid-a", "name": "Allowed"},
        {"id": "uuid-b", "name": "Excluded"},
    ]}
    result = library_tools.get_exercise_candidates({"definition_ids": ["LIBRARY_0"]}, equipment)
    assert result["exercises"][0]["id"] == "LIBRARY_0"
    assert result["exercises"][0]["name"] == "Allowed"
    with pytest.raises(ValueError, match="Unknown library definition IDs"):
        library_tools.get_exercise_candidates({"definition_ids": ["LIBRARY_2"]}, equipment)


def test_new_movement_role_can_be_searched_after_prior_results_without_audit(monkeypatch, tmp_path):
    from workout_generator_pkg import planning_tools

    definitions = [{"id": "uuid-a", "name": "Barbell Back Squat"}]
    gear = {"exerciseDefinitions": definitions}
    fingerprint = __import__("hashlib").sha256(json.dumps(
        {"equipment": gear, "entries": [library_tools._selection_entry(definitions[0], {}, "LIBRARY_0")]},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    prior = {"libraryFingerprint": fingerprint,
             "results": [{"query": "quad dominant", "matchMethod": "semantic", "exercises": [{"id": "LIBRARY_0"}]}]}
    messages = [{"role": "user", "content": "Set requirements"},
                {"role": "tool", "content": json.dumps(prior)}]
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    monkeypatch.setattr(planning_tools, "_latest_result", lambda *_args: (-1, {"requirements": {"exerciseRestrictions": {}}}))
    monkeypatch.setattr(planning_tools, "require_approved_requirements", lambda _messages: None)
    monkeypatch.setattr(library_tools, "_semantic_matches", lambda _client, queries, _entries, **_kwargs: [{0: 0.9} for _ in queries])

    result = library_tools.execute_library_tool("search_exercise_library", {"queries": ["posterior chain isolation"]}, gear,
                                                client=object(), messages=messages)
    assert result["results"][0]["exercises"][0]["name"] == "Barbell Back Squat"


def test_combined_search_calls_chunk_more_than_six_queries(monkeypatch, tmp_path):
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    monkeypatch.setattr(library_tools, "_semantic_matches", lambda _client, queries, _entries, **_kwargs: [{0: 0.9} for _ in queries])
    calls = [(f"call-{batch}", {"queries": [f"movement role {batch}-{item}" for item in range(6)]}) for batch in range(2)]
    result = library_tools.execute_library_searches(
        calls, {"exerciseDefinitions": [{"id": "uuid-a", "name": "Candidate"}]}, object(), [],
    )
    assert len(result["call-0"]["results"]) == 6
    assert len(result["call-1"]["results"]) == 6
    assert not result["call-0"].get("errors")
    assert not result["call-1"].get("errors")


def test_unchanged_failed_search_is_not_retried_but_new_query_is_allowed(monkeypatch, tmp_path):
    definitions = [{"id": "uuid-a", "name": "Candidate"}]
    gear = {"exerciseDefinitions": definitions}
    entries = [library_tools._selection_entry(definitions[0], {}, "LIBRARY_0")]
    fingerprint = __import__("hashlib").sha256(json.dumps(
        {"equipment": gear, "entries": entries}, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    prior = {"libraryFingerprint": fingerprint,
             "results": [{"query": "unsupported movement", "error": "temporary failure", "exercises": [], "complete": False}]}
    messages = [{"role": "user", "content": "Find an unsupported movement"},
                {"role": "tool", "content": json.dumps(prior)}]
    calls = []
    monkeypatch.setattr(library_tools, "CACHE_DIRECTORY", tmp_path)
    monkeypatch.setattr(library_tools, "_semantic_matches", lambda _client, queries, _entries, **_kwargs: (calls.append(list(queries)) or [{0: 0.8}]))
    blocked = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["unsupported movement", "new movement role"]}, gear,
        client=object(), messages=messages,
    )
    assert calls == [["new movement role"]]
    assert blocked["results"][0]["error"].startswith("This exact search query already failed")
    assert blocked["results"][1]["exercises"][0]["name"] == "Candidate"

    messages.append({"role": "tool", "content": json.dumps(blocked)})
    same_turn = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["unsupported movement"]}, gear,
        client=object(), messages=messages,
    )
    assert calls == [["new movement role"]]
    assert same_turn["results"][0]["error"].startswith("This exact search query already failed")

    messages.append({"role": "user", "content": "Retry the unsupported movement search"})
    retried = library_tools.execute_library_tool(
        "search_exercise_library", {"queries": ["unsupported movement"]}, gear,
        client=object(), messages=messages,
    )
    assert calls == [["new movement role"], ["unsupported movement"]]
    assert retried["results"][0]["exercises"][0]["name"] == "Candidate"


def test_combined_search_reports_each_call_when_its_queries_are_available(monkeypatch):
    batches = []
    reports = []

    def execute(_name, arguments, *_args, **_kwargs):
        batches.append(arguments["queries"])
        return {"libraryFingerprint": "fingerprint", "results": [
            {"query": query, "exercises": [{"name": query}]} for query in arguments["queries"]
        ]}

    monkeypatch.setattr(library_tools, "execute_library_tool", execute)
    calls = [("early", {"queries": ["query 0"]}),
             ("late", {"queries": [f"query {index}" for index in range(6, 12)]})]
    results = library_tools.execute_library_searches(
        calls, {}, object(), [], on_result=lambda call_id, result: reports.append((call_id, result, len(batches))),
    )

    assert {call_id for call_id, _, _ in reports} == {'early', 'late'}
    assert all(results[call_id] == payload for call_id, payload, _ in reports)


def test_independent_search_filters_run_concurrently_and_publish_on_caller_thread(monkeypatch):
    import threading
    barrier = threading.Barrier(2, timeout=3)
    caller = threading.get_ident()
    published = []

    def execute(_name, arguments, *_args, **_kwargs):
        barrier.wait()
        return {'libraryFingerprint': 'library', 'results': [
            {'query': query, 'exercises': []} for query in arguments['queries']]}

    monkeypatch.setattr(library_tools, 'execute_library_tool', execute)
    results = library_tools.execute_library_searches([
        ('quad', {'queries': ['squat'], 'muscleTargets': ['quads']}),
        ('chest', {'queries': ['press'], 'muscleTargets': ['chest']})], {}, object(), [],
        on_result=lambda key, payload: published.append((key, threading.get_ident())))
    assert list(results) == ['quad', 'chest']
    assert set(published) == {('quad', caller), ('chest', caller)}


def test_selection_must_precede_confirmation_and_survives_saved_messages():
    messages = [
        {"role": "user", "content": "Make a plan"},
        {"role": "assistant", "tool_calls": [{"id": "selection", "function": {"name": "select_exercises"}}]},
        {"role": "tool", "tool_call_id": "selection", "content": '{"selectedExerciseDefinitionIds":["definition-0"]}'},
        {"role": "assistant", "content": "Preview"},
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]
    assert library_tools.selected_library_ids_from_messages(json.loads(json.dumps(messages))) == ["definition-0"]
    late_selection = [messages[0], messages[-1], *messages[1:4]]
    assert library_tools.selected_library_ids_from_messages(late_selection) == []


def _selection_turn(ids, preview):
    return [
        {"role": "assistant", "tool_calls": [{"id": "selection", "function": {"name": "select_exercises"}}]},
        {"role": "tool", "tool_call_id": "selection", "content": json.dumps({"selectedExerciseDefinitionIds": ids})},
        {"role": "assistant", "content": preview},
    ]


def test_revision_invalidates_stale_selection_before_generation():
    messages = [
        {"role": "user", "content": "Create a plan"},
        *_selection_turn(["deadlift"], "| Exercise | Sets |\n|---|---|\n| Barbell Deadlift | 3 |"),
        {"role": "user", "content": "Remove the deadlift; RDL only"},
        {"role": "assistant", "content": "| Exercise | Sets |\n|---|---|\n| Romanian Deadlift | 3 |"},
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]
    assert library_tools.selected_library_ids_from_messages(messages) == []
    messages[-2:-1] = _selection_turn(["rdl"], messages[-2]["content"])
    assert library_tools.selected_library_ids_from_messages(messages, [{"id": "rdl", "name": "Romanian Deadlift"}]) == ["rdl"]


def test_unused_selected_alternative_cannot_be_restored_by_repair():
    definitions = [{"id": "rdl", "name": "Romanian Deadlift"}, {"id": "deadlift", "name": "Barbell Deadlift"}]
    messages = [
        {"role": "user", "content": "RDL only"},
        *_selection_turn(["rdl", "deadlift"],
                        "| Order | Exercise | Sets |\n|---|---|---|\n| 1 | **Romanian Deadlift** | 3 |\n\nBarbell Deadlift is removed."),
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]
    with pytest.raises(ValueError, match="Selected but not in exercise rows.*barbell deadlift"):
        library_tools.selected_library_ids_from_messages(messages, definitions)
    messages[2]["content"] = '{"selectedExerciseDefinitionIds":["rdl"]}'
    assert library_tools.selected_library_ids_from_messages(messages, definitions) == ["rdl"]


def _rest_plan():
    return {
        "exercises": [{"id": f"EXERCISE_{i}"} for i in range(4)],
        "workouts": [{
            "id": "WORKOUT_0", "name": "Day C", "exerciseIds": [f"EXERCISE_{i}" for i in range(4)],
            "restToNextSeconds": [150, 120, 0, 0],
            "supersetGroups": [{
                "exerciseIds": ["EXERCISE_2", "EXERCISE_3"],
                "restSecondsByExercise": {"EXERCISE_2": 40, "EXERCISE_3": 90},
            }],
        }],
    }


def _rest_structure():
    return {"workoutMetadata": {"name": "Day C"}, "workoutComponents": [
        {"componentType": "Exercise", "exerciseId": "EXERCISE_0"},
        {"componentType": "Rest", "timeInSeconds": 150},
        {"componentType": "Exercise", "exerciseId": "EXERCISE_1"},
        {"componentType": "Rest", "timeInSeconds": 120},
        {"componentType": "Superset", "exerciseIds": ["EXERCISE_2", "EXERCISE_3"],
         "restSecondsByExercise": {"EXERCISE_2": 40, "EXERCISE_3": 90}},
    ]}


@pytest.mark.parametrize("defect", ["missing_round_rest", "misplaced_transition"])
def test_rest_contract_separates_round_recovery_and_rejects_misplaced_transitions(defect):
    plan = _rest_plan()
    structure = _rest_structure()
    definitions = {exercise["id"]: exercise for exercise in plan["exercises"]}
    validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)
    if defect == "missing_round_rest":
        structure["workoutComponents"][-1]["restSecondsByExercise"]["EXERCISE_3"] = 0
    else:
        structure["workoutComponents"].insert(0, structure["workoutComponents"].pop(1))
    with pytest.raises(ContractValidationError, match="rest"):
        validate_workout_structures_contract(plan, {"WORKOUT_0": structure}, definitions)


def test_final_contract_rejects_repair_that_changes_work_set_count():
    plan = {"exercises": [{"id": "EXERCISE_0", "numWorkSets": 3}], "workouts": [
        {"id": "WORKOUT_0", "name": "Day", "exerciseIds": ["EXERCISE_0"], "restToNextSeconds": [0]},
    ]}
    package = {"workouts": [{"id": "WORKOUT_0", "name": "Day", "workoutComponents": [{
        "id": "EXERCISE_0", "type": "Exercise", "sets": [{"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 20}],
    }]}]}
    with pytest.raises(ContractValidationError, match="work set count"):
        validate_assembled_workout_contract(plan, package)


def test_plan_guidance_survives_repair_and_loaded_guesses_require_calibration():
    exercise = {
        "id": "EXERCISE_0", "type": "Exercise", "enabled": True, "name": "Bench Press",
        "notes": "", "placementNotes": "", "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0",
        "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [], "muscleGroups": ['FRONT_CHEST'],
        "minReps": 6, "maxReps": 8, "generateWarmUpSets": False, "progressionMode": "OFF",
        "showCountDownTimer": False, "keepScreenOn": False, "requiresLoadCalibration": False,
        "sets": [{"id": "SET_0", "type": "WeightSet", "reps": 8, "weight": 60.0, "subCategory": "WorkSet"}],
    }
    plan_entry = {
        "id": "EXERCISE_0", "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0",
        "placementNotes": "Keep 1–2 RIR. Add load after reaching 8 reps on every set.",
        "generateWarmUpSets": True, "progressionMode": "AUTO_REGULATION",
    }
    equipment = [{"id": "EQUIPMENT_0", "type": "BARBELL", "name": "Barbell", "barWeight": 20,
                  "sleeveLength": 300, "availablePlates": [{"weight": 20, "thickness": 20}]}]
    normalized = finalize_and_validate_exercise_definition(exercise, plan_entry, equipment_subset=equipment)
    assert normalized["requiresLoadCalibration"] is True
    assert normalized["placementNotes"] == plan_entry["placementNotes"]
    explicit_plan = {**plan_entry, "targetSetPrescriptions": [{"workSetIndex": 0, "reps": 8, "weight": 60.0}]}
    explicit = finalize_and_validate_exercise_definition(exercise, explicit_plan, equipment_subset=equipment)
    assert explicit["requiresLoadCalibration"] is False
    package = {"workouts": [{"workoutComponents": [copy.deepcopy(normalized)]}]}
    package["workouts"][0]["workoutComponents"][0]["placementNotes"] = ""
    sync_exercises_from_definitions(package, {"EXERCISE_0": normalized})
    sync_exercises_from_plan_index(package, {"exercises": [plan_entry]})
    ensure_requiresLoadCalibration(package)
    restored = package["workouts"][0]["workoutComponents"][0]
    assert restored["placementNotes"] == plan_entry["placementNotes"]
    assert restored["requiresLoadCalibration"] is True
