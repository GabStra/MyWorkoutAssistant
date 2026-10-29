import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import joint_planning, session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError, set_workout_requirements
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _store_tool(messages, name, arguments, result):
    call_id = f'call_{len(messages)}'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
            'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(result)},
    ])


def test_preparation_counts_are_not_carried_as_a_source_cap():
    equipment, _, _, draft = planning_case()
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}])
        sessions.append(session)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}

    first = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    _store_tool(messages, 'prepare_workout_sessions', arguments, first)
    unbounded = {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    assert first['sourceWorkingSetBudget'] == unbounded

    revised = copy.deepcopy(arguments)
    revised['sessions'][0]['exercises'][0]['numWorkSets'] = 6
    from unittest.mock import patch
    from workout_generator_pkg.allocation import allocate_prepared_sets
    with patch('workout_generator_pkg.allocation.allocate_prepared_sets',
               wraps=allocate_prepared_sets) as allocate:
        second = session_drafting.prepare_workout_sessions(revised, messages, equipment)

    assert second['sourceWorkingSetBudget'] == unbounded
    assert allocate.call_args.kwargs['source_working_set_budget'] is None


def test_infeasible_preparation_does_not_freeze_a_source_cap():
    equipment, _, _, draft = planning_case()
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': []}
    authority = session_drafting._preparation_authority(messages, arguments, equipment, None)
    _store_tool(messages, 'prepare_workout_sessions', arguments, {
        'setAllocation': {'feasible': False}, 'sourceBudgetAuthority': authority,
        'sourceWorkingSetBudget': {'source': 'unproved', 'variableWeeklyWorkingSets': 999,
                                   'preparationId': 'NOT_A_PROOF'}})

    assert session_drafting._prior_source_working_set_budget(messages, authority) is None


def test_reviewed_pool_is_complete_and_adds_straight_set_seeds_to_each_session(monkeypatch):
    family = {'exerciseFamilyId': 'family', 'source': 'https://example.org/family', 'basis': 'reviewed'}

    def candidate(reference, *, reviewed=True, demand='absent'):
        value = {'id': reference}
        if reviewed:
            value['reviewedExerciseFamily'] = copy.deepcopy(family)
        value['programmingDemandFacts'] = {'unsupported_trunk': {
            'status': demand,
            'source': 'https://example.org/demand' if demand != 'unknown' else None}}
        return value

    entries = [candidate('LIBRARY_0'), candidate('LIBRARY_1', demand='present'),
        candidate('LIBRARY_2', reviewed=False), candidate('LIBRARY_3', demand='unknown')]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.search_catalog',
        lambda equipment, restrictions: (entries, 'fingerprint'))

    requirements = {'objectiveOrder': ['exercise_distribution', 'demand_distribution']}
    references = session_drafting._reviewed_recipe_candidate_references({}, requirements)
    sessions = [{'exercises': [{'definition_id': 'LIBRARY_9', 'numWorkSets': 2, 'superset': 'PAIR'}]},
        {'exercises': []}]
    pooled = session_drafting._add_reviewed_recipe_candidates(sessions, references)

    assert references == ['LIBRARY_0', 'LIBRARY_1']
    for day in pooled:
        automatic = [item for item in day['exercises'] if item['definition_id'] in references]
        assert [item['definition_id'] for item in automatic] == references
        assert all(item['superset'] is None and item['numWorkSets'] == 1
                   and item['satisfiesCoverage'] == [] for item in automatic)


def test_active_demand_or_family_objective_bounds_preparation_selector_and_repair(monkeypatch):
    allowed = sorted(f'LIBRARY_{index}' for index in range(40))
    receipt = {'requirements': {'objectiveOrder': ['demand_distribution']}}
    monkeypatch.setattr(session_drafting, '_latest_result', lambda *_: (1, receipt))
    monkeypatch.setattr(session_drafting, '_reviewed_recipe_candidate_references',
        lambda *_: allowed)
    assert session_drafting._preparation_choice_domain([], {}) == allowed

    tool = session_drafting.prepare_workout_sessions_tool([], {})
    tool_enum = tool['function']['parameters']['properties']['sessions']['items'][
        'properties']['blocks']['items']['properties']['exercises']['items'][
        'properties']['definition_id']['enum']
    assert tool_enum == allowed

    flat_arguments = {'sessions': [{'exercises': [{'definition_id': 'LIBRARY_40'}]}]}
    flat_schema = session_drafting._preparation_schema(flat_arguments, allowed)
    assert flat_schema['properties']['sessions']['items'][0]['properties']['exercises']['items'][
        'properties']['definition_id']['enum'] == allowed
    block_arguments = {'sessions': [{'blocks': [{'exercises': [{'definition_id': 'LIBRARY_40'}]}]}]}
    block_schema = session_drafting._preparation_schema(block_arguments, allowed)
    assert block_schema['properties']['sessions']['items'][0]['properties']['blocks']['items'][
        'properties']['exercises']['items']['properties']['definition_id']['enum'] == allowed

    model_choices = allowed + [f'LIBRARY_{index}' for index in range(40, 44)]
    prepared = {'requirementsId': 'R1', 'baseDraftId': None, 'name': 'Program', 'sessions': [
        {'name': f'Day {day_index + 1}', 'description': 'Training', 'timesCompletedInAWeek': 1,
         'trainingDays': [day_index * 2], 'exercises': [
             {'definition_id': reference, 'numWorkSets': 2, 'superset': None}
             for reference in model_choices[day_index * 22:(day_index + 1) * 22]]}
        for day_index in range(2)]}
    with pytest.raises(PlanningInputError) as rejected:
        session_drafting._prepare_week(prepared, [], {})
    assert rejected.value.code == 'preparation_selection_outside_reviewed_pool'
    assert [error['path'] for error in rejected.value.errors] == [
        f'/sessions/1/exercises/{index}/definition_id' for index in range(18, 22)]
    assert all(error['admissibleDefinitionIds'] == allowed for error in rejected.value.errors)

    repair_task = {'allowedDefinitionIds': allowed, 'blockRepair': {'groupingOnly': False,
        'sessions': {'SESSION_0': {'occurrences': {'/sessions/0/exercises/0': {}},
            'editableOccurrences': ['/sessions/0/exercises/0'], 'canAdd': False}}},
        'permittedPaths': ['/sessions/0/exercises/0/definition_id']}
    repair_schema = session_drafting.preparation_patch_tool(repair_task)['function']['parameters']
    replacement_schema = repair_schema['properties']['sessionBlocks']['items']['oneOf'][0]
    repair_enum = replacement_schema['properties']['replacements']['items']['properties'][
        'definition_id']['enum']
    assert repair_enum == allowed
    assert not set(model_choices[-4:]).intersection(repair_enum)


def test_exercise_distribution_keeps_unclassified_choices_selectable(monkeypatch):
    receipt = {'requirements': {'objectiveOrder': ['exercise_distribution']}}
    monkeypatch.setattr(session_drafting, '_latest_result', lambda *_: (1, receipt))
    monkeypatch.setattr(session_drafting, '_reviewed_recipe_candidate_references', lambda *_: [])
    assert session_drafting._preparation_choice_domain([], {}) is None
    tool = session_drafting.prepare_workout_sessions_tool([], {})
    assert tool is not None
    definition_schema = tool['function']['parameters']['properties']['sessions']['items'][
        'properties']['blocks']['items']['properties']['exercises']['items'][
        'properties']['definition_id']
    assert 'enum' not in definition_schema
    assert session_drafting.prepare_workout_session_tool([], {}) is not None
    errors = session_drafting._preparation_selection_errors(
        {'sessions': [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]}, None)
    assert errors == []
    empty_tool = session_drafting._preparation_schema(
        {'sessions': [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]}, None)
    assert empty_tool['properties']['sessions']['items'][0]['properties']['exercises']['items'][
        'properties']['definition_id'] == {'type': 'string', 'pattern': '^LIBRARY_[0-9]+$'}


def test_exercise_distribution_supplements_only_family_classified_recipes(monkeypatch):
    entries = [
        {'id': 'LIBRARY_FAMILY', 'reviewedExerciseFamily': {
            'exerciseFamilyId': 'family', 'source': 'https://example.org/family', 'basis': 'reviewed'},
         'programmingDemandFacts': {'unsupported_trunk': {'status': 'unknown'}}},
        {'id': 'LIBRARY_UNKNOWN_FAMILY',
         'programmingDemandFacts': {'unsupported_trunk': {'status': 'absent', 'source': 'https://example.org/demand'}}},
    ]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.search_catalog',
        lambda equipment, restrictions: (entries, 'fingerprint'))
    receipt = {'requirements': {'objectiveOrder': ['exercise_distribution']}}

    assert session_drafting._reviewed_recipe_candidate_references({}, receipt) == ['LIBRARY_FAMILY']


def test_omitting_demand_distribution_omits_demand_colocation_goal():
    requirements = {'objectiveOrder': ['duration_balance', 'exercise_distribution']}
    available = {'demand_distribution': True, 'demand_colocation': True,
        'duration_balance': True, 'exercise_distribution': True}

    assert joint_planning._ordered_joint_objective_names(requirements, available) == [
        'duration_balance', 'exercise_distribution']


def test_saved_f2cf_selection_is_rejected_against_the_reviewed_40_choice_domain():
    from workout_generator_pkg import interactive_shell

    root = Path(__file__).resolve().parents[1]
    conversation_path = root / 'build/workout_quality_design_implementation_20261027/fresh_e2e/workouts/conversation_sessions/f2cf6a55-be40-4974-8c82-a9e5855fe875/messages.json'
    library_path = root / 'build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json'
    messages = json.loads(conversation_path.read_text(encoding='utf-8'))
    selection_index = next(index for index, message in enumerate(messages)
        if any(call.get('function', {}).get('name') == 'prepare_workout_sessions'
            for call in message.get('tool_calls', [])))
    arguments = json.loads(next(call['function']['arguments'] for call in messages[selection_index]['tool_calls']
        if call.get('function', {}).get('name') == 'prepare_workout_sessions'))
    context = messages[:selection_index + 1]
    equipment = interactive_shell._load_exercise_library_payload(str(library_path))
    domain = session_drafting._preparation_choice_domain(context, equipment)
    offered = session_drafting.prepare_workout_sessions_tool(context, equipment)
    singular_offered = session_drafting.prepare_workout_session_tool(context, equipment)
    selector_enum = offered['function']['parameters']['properties']['sessions']['items'][
        'properties']['blocks']['items']['properties']['exercises']['items'][
        'properties']['definition_id']['enum']
    singular_enum = singular_offered['function']['parameters']['properties']['definition_ids'][
        'items']['enum']
    proposed = {item['definition_id'] for day in arguments['sessions']
        for block in day['blocks'] for item in block['exercises']}
    outside = sorted(proposed - set(domain))

    assert len(domain) == len(selector_enum) == len(singular_enum) == 40
    assert singular_enum == domain
    assert outside == ['LIBRARY_14', 'LIBRARY_47', 'LIBRARY_53', 'LIBRARY_63']
    assert not set(outside).intersection(selector_enum)
    errors = session_drafting._preparation_selection_errors(
        session_drafting._expand_preparation_blocks(arguments), domain)
    assert len(errors) == 4
    assert {error['path'] for error in errors} == {
        f'/sessions/1/exercises/{index}/definition_id' for index in (0, 4, 5, 12)}
    with pytest.raises(PlanningInputError) as rejected:
        session_drafting._prepare_week(arguments, context, equipment)
    assert rejected.value.code == 'preparation_selection_outside_reviewed_pool'
    assert len(rejected.value.errors) == 4


def test_saved_f2cf_preparation_cannot_bypass_domain_check_through_cache_or_direct_draft(monkeypatch):
    from workout_generator_pkg import interactive_shell, planning_tools

    root = Path(__file__).resolve().parents[1]
    conversation_path = root / 'build/workout_quality_design_implementation_20261027/fresh_e2e/workouts/conversation_sessions/f2cf6a55-be40-4974-8c82-a9e5855fe875/messages.json'
    library_path = root / 'build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json'
    messages = json.loads(conversation_path.read_text(encoding='utf-8'))
    preparation_call = next(call for message in messages for call in message.get('tool_calls', [])
        if call.get('function', {}).get('name') == 'prepare_workout_sessions'
        and 'basePreparationId' in json.loads(call['function']['arguments']))
    preparation_result_index = next(index for index, message in enumerate(messages)
        if message.get('role') == 'tool' and message.get('tool_call_id') == preparation_call['id'])
    prepared = json.loads(messages[preparation_result_index]['content'])
    equipment = interactive_shell._load_exercise_library_payload(str(library_path))
    draft_message_index = next(index for index, message in enumerate(messages)
        if any(call.get('function', {}).get('name') == 'draft_workout_sessions'
            for call in message.get('tool_calls', [])))
    current_messages = messages[:draft_message_index]
    cache_arguments = {key: copy.deepcopy(prepared[key]) for key in
        ('requirementsId', 'baseDraftId', 'name', 'sessions')}

    assert session_drafting._cached_preparation(current_messages, cache_arguments, equipment,
        prepared['historyFingerprint']) is None

    draft_call = next(call for message in messages for call in message.get('tool_calls', [])
        if call.get('function', {}).get('name') == 'draft_workout_sessions')
    draft_arguments = json.loads(draft_call['function']['arguments'])
    monkeypatch.setattr(session_drafting, 'chat_call',
        lambda *_args, **_kwargs: pytest.fail('stale preparation reached a prescription worker'))
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *_args, **_kwargs: pytest.fail('stale preparation reached recipe qualification'))

    from types import SimpleNamespace
    result = session_drafting.draft_workout_sessions(None, draft_arguments, current_messages,
        equipment, {'historyFingerprint': prepared['historyFingerprint']},
        training_history=SimpleNamespace(fingerprint=prepared['historyFingerprint']))

    assert result['passed'] is False
    assert len(result['preparationErrors']) == 4
    assert all(error['code'] == 'preparation_selection_outside_reviewed_pool'
        for error in result['preparationErrors'])

    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.get_exercise_candidates',
        lambda *_args, **_kwargs: pytest.fail('out-of-domain singular selection reached metadata retrieval'))
    with pytest.raises(PlanningInputError) as rejected:
        planning_tools.prepare_workout_session({
            'requirementsId': prepared['requirementsId'], 'baseDraftId': None,
            'definition_ids': ['LIBRARY_14', 'LIBRARY_47', 'LIBRARY_53', 'LIBRARY_63']},
            current_messages, equipment)
    assert rejected.value.code == 'preparation_selection_outside_reviewed_pool'
    assert len(rejected.value.errors) == 4


def test_preparation_sends_reviewed_alternatives_through_existing_recipe_pool(monkeypatch):
    equipment, _, _, draft = planning_case()
    original = copy.deepcopy(equipment['exerciseDefinitions'][0])
    for exercise_id in ('reviewed-option-a', 'reviewed-option-b'):
        variant = copy.deepcopy(original)
        variant['id'] = exercise_id
        variant['name'] = exercise_id
        equipment['exerciseDefinitions'].append(variant)
    definitions = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])
    original_reference = next(f'LIBRARY_{index}' for index, definition in enumerate(definitions)
                              if definition['id'] == original['id'])
    references = [f'LIBRARY_{index}' for index, definition in enumerate(definitions)
                  if definition['id'] != original['id']]
    family = {'exerciseFamilyId': 'family', 'source': 'https://example.org/family', 'basis': 'reviewed'}
    entries = [{'id': reference, 'reviewedExerciseFamily': family,
        'programmingDemandFacts': {'unsupported_trunk': {'status': 'absent',
            'source': 'https://example.org/demand'}}} for reference in references]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.search_catalog',
        lambda equipment, restrictions: (entries, 'fingerprint'))

    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': original_reference, 'numWorkSets': 5, 'superset': None}])
        sessions.append(session)

    prepared = session_drafting.prepare_workout_sessions({
        'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}, messages, equipment)

    assert set(references).issubset(prepared['definition_ids'])
    assert all(set(references).issubset({item['definition_id'] for item in day['exercises']})
               for day in prepared['recipeSessions'])
    for day in prepared['recipeSessions']:
        automatic = [item for item in day['exercises'] if item['definition_id'] in references]
        assert all(item['superset'] is None and item['satisfiesCoverage'] == [] for item in automatic)


def test_development_menu_uses_no_numeric_cap_for_unbounded_joint_receipt(monkeypatch):
    from workout_generator_pkg import generation_audit

    equipment, _, _, draft = planning_case()
    session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
    session.update(trainingDays=[0], timesCompletedInAWeek=1, exercises=[{
        'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'allocationBounds': {'minimum': 2, 'maximum': 10},
        'superset': None, 'satisfiesCoverage': ['vertical_pull']}])
    requirements = {'requirements': {'requiredCoverage': [{'key': 'vertical_pull', 'intent': 'development'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 1, 'maximum': 10}}}}}
    received = {}
    monkeypatch.setattr(session_drafting, '_prior_source_working_set_budget',
        lambda messages, authority: {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None})
    def limits(*args, **kwargs):
        received.update(kwargs)
        return {'volumeCreditCoupling': {}, 'developmentRoleRelief': {}}
    monkeypatch.setattr(generation_audit, 'development_menu_limits', limits)

    session_drafting._development_menu_review({'sourceBudgetAuthority': {}}, [session], requirements,
        equipment, [], None)

    assert received['source_set_cap'] is None


def test_two_reviewed_alternatives_are_available_to_one_joint_solve(monkeypatch):
    from workout_generator_pkg.joint_planning import solve_prescribed_week

    equipment, _, _, draft = planning_case()
    original = copy.deepcopy(equipment['exerciseDefinitions'][0])
    alternatives = []
    for exercise_id, muscle in (('reviewed-back-option', 'BACK_UPPER_BACK'),
                                ('reviewed-shoulder-option', 'FRONT_DELTOIDS')):
        variant = copy.deepcopy(original)
        variant.update(id=exercise_id, name=exercise_id, muscleGroups=[muscle], secondaryMuscleGroups=[])
        equipment['exerciseDefinitions'].append(variant)
        alternatives.append(exercise_id)
    definitions = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])
    references_by_id = {definition['id']: f'LIBRARY_{index}' for index, definition in enumerate(definitions)}
    original_reference = references_by_id[original['id']]
    references = [references_by_id[exercise_id] for exercise_id in alternatives]
    family = {'exerciseFamilyId': 'family', 'source': 'https://example.org/family', 'basis': 'reviewed'}
    entries = [{'id': reference, 'reviewedExerciseFamily': family,
        'programmingDemandFacts': {'unsupported_trunk': {'status': 'absent',
            'source': 'https://example.org/demand'}}} for reference in references]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.search_catalog',
        lambda equipment, restrictions: (entries, 'fingerprint'))

    requirements = {'sessionsPerWeek': 2, 'auditTargets': {
        'weeklyEffectiveSets': {muscle: {'minimum': 2, 'maximum': 2}
                                for muscle in ('chest', 'back', 'shoulders')},
        'perSessionEffectiveSets': {},
        'maximumSessionSeconds': 1000}}
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Plan two sessions covering chest, back, and shoulders.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': original_reference, 'numWorkSets': 2, 'superset': None}])
        sessions.append(session)
    prepared = session_drafting.prepare_workout_sessions({
        'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}, messages, equipment)

    assert set(references).issubset(prepared['definition_ids'])
    assert all(set(references).issubset({item['definition_id'] for item in day['exercises']})
               for day in prepared['recipeSessions'])
    recipes = []
    for index, selection in enumerate(prepared['recipeSessions']):
        exercises = []
        for candidate in selection['exercises']:
            exercise = copy.deepcopy(draft['workouts'][0]['exercises'][0])
            exercise['definition_id'] = candidate['definition_id']
            exercise['numWorkSets'] = 2
            exercise['superset'] = None
            exercise.pop('placementNotes', None)
            exercises.append(exercise)
        recipes.append({**{key: selection[key] for key in
            ('name', 'description', 'timesCompletedInAWeek', 'trainingDays')}, 'exercises': exercises})
    joint = solve_prescribed_week(recipes, stored['requirements'], equipment,
        stored.get('restrictionPolicy'), source_working_set_budget=prepared['sourceWorkingSetBudget'])

    assert joint['feasible'], joint
    selected = {item['definition_id'] for day in joint['sessions'] for item in day['exercises']}
    assert set(references).issubset(selected)


def test_feasible_joint_receipt_reuses_its_explicit_source_budget():
    equipment, _, _, draft = planning_case()
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}])
        sessions.append(session)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}

    first = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    _store_tool(messages, 'prepare_workout_sessions', arguments, first)
    verified_cap = {'source': 'user_approved_source_set_limit',
        'variableWeeklyWorkingSets': 20,
        'preparationId': first['preparationId']}
    _store_tool(messages, 'draft_workout_sessions', {'preparationId': first['preparationId']}, {
        'preparationId': first['preparationId'], 'requirementsId': first['requirementsId'],
        'baseDraftId': first['baseDraftId'], 'libraryFingerprint': first['libraryFingerprint'],
        'historyFingerprint': first['historyFingerprint'],
        'recipeQualification': {'contracts': [{'definition_id': 'LIBRARY_0'}]},
        'proposedSubmission': {'workouts': copy.deepcopy(first['sessions'])},
        'jointPlanning': {'feasible': True,
            'sourceWorkingSetBudget': copy.deepcopy(verified_cap)}})
    first_budget = copy.deepcopy(verified_cap)

    revised = copy.deepcopy(arguments)
    revised['sessions'][0]['exercises'][0]['numWorkSets'] = 6
    second = session_drafting.prepare_workout_sessions(revised, messages, equipment)

    assert second['sourceWorkingSetBudget'] == first_budget
    assert second['sourceWorkingSetBudget']['preparationId'] == first['preparationId']


def test_feasible_joint_unbounded_receipt_keeps_fresh_preparations_unbounded():
    equipment, _, _, draft = planning_case()
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}])
        sessions.append(session)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}

    first = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    unbounded = copy.deepcopy(first['sourceWorkingSetBudget'])
    _store_tool(messages, 'prepare_workout_sessions', arguments, first)
    verified_cap = copy.deepcopy(unbounded)
    _store_tool(messages, 'draft_workout_sessions', {'preparationId': first['preparationId']}, {
        'preparationId': first['preparationId'], 'requirementsId': first['requirementsId'],
        'baseDraftId': first['baseDraftId'], 'libraryFingerprint': first['libraryFingerprint'],
        'historyFingerprint': first['historyFingerprint'],
        'proposedSubmission': {'workouts': copy.deepcopy(first['sessions'])},
        'jointPlanning': {'feasible': True, 'sourceWorkingSetBudget': verified_cap}})

    revised = copy.deepcopy(arguments)
    revised['sessions'][0]['exercises'][0]['numWorkSets'] = 6
    from unittest.mock import patch
    from workout_generator_pkg.allocation import allocate_prepared_sets
    with patch('workout_generator_pkg.allocation.allocate_prepared_sets',
               wraps=allocate_prepared_sets) as allocate:
        second = session_drafting.prepare_workout_sessions(revised, messages, equipment)

    assert unbounded == {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    assert second['sourceWorkingSetBudget'] == verified_cap
    assert allocate.call_args.kwargs['source_working_set_budget'] == verified_cap


def test_repair_reuses_cap_only_from_exact_worker_source_audit_after_new_revision():
    from pathlib import Path
    from workout_generator_pkg import interactive_shell, repair_execution
    from workout_generator_pkg.planning_tools import active_requirement_result
    from workout_generator_pkg.training_history import TrainingHistory

    run = Path('build/workout_quality_policy_20261027/fresh_e2e')
    transcript = run / 'workouts/conversation_sessions/aca503d2-2204-4091-959a-64cc950960f4/messages.json'
    backup = Path('build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json')
    if not transcript.is_file() or not backup.is_file():
        pytest.skip('Retained v7 transcript and library backup are local acceptance artifacts.')
    messages = json.loads(transcript.read_text(encoding='utf-8'))[:224]
    equipment = interactive_shell._load_exercise_library_payload(backup)
    history = TrainingHistory.from_file(backup)
    _, receipt = active_requirement_result(messages)
    _, worker = session_drafting._retained_tool_results(messages, 'draft_workout_sessions')[-1]
    _, latest_audit = session_drafting._retained_tool_results(messages, 'audit_workout_plan')[-1]
    assert latest_audit['currentDraftId'] == 'REVISION_1'
    assert worker['baseDraftId'] is None
    assert latest_audit['submittedDraft'] != worker['proposedSubmission']
    assert worker['jointPlanning']['sourceWorkingSetBudget']['variableWeeklyWorkingSets'] == 78

    if worker.get('libraryFingerprint') != session_drafting.library_fingerprint(equipment):
        current_authority = session_drafting._preparation_authority(messages,
            {'baseDraftId': worker.get('baseDraftId')}, equipment, history.fingerprint)
        assert session_drafting.source_working_set_budget_for_worker(
            messages, worker, equipment, history.fingerprint) is None
        assert session_drafting._prior_source_working_set_budget(messages, current_authority) is None
        return

    worker_budget = session_drafting.source_working_set_budget_for_worker(
        messages, worker, equipment, history.fingerprint)
    assert worker_budget == worker['jointPlanning']['sourceWorkingSetBudget']
    budget = repair_execution._repair_source_working_set_budget(
        latest_audit['submittedDraft']['workouts'], receipt['requirements'], equipment,
        receipt.get('restrictionPolicy'), requirements_id=receipt['requirementsId'],
        allow_educated_load_guesses=False, training_history=history,
        messages=messages, redistribution_constraints=[])
    assert budget == worker_budget

    # A previous feasible audit is not enough when it no longer matches the
    # worker's exact source artifact.
    stale_messages = copy.deepcopy(messages)
    worker_index, stale_worker = session_drafting._retained_tool_results(
        stale_messages, 'draft_workout_sessions')[-1]
    stale_worker['proposedSubmission']['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    stale_messages[worker_index]['content'] = json.dumps(stale_worker)
    rejected = repair_execution._repair_source_working_set_budget(
        latest_audit['submittedDraft']['workouts'], receipt['requirements'], equipment,
        receipt.get('restrictionPolicy'), requirements_id=receipt['requirementsId'],
        allow_educated_load_guesses=False, training_history=history,
        messages=stale_messages, redistribution_constraints=[])
    assert rejected is None
    assert session_drafting.source_working_set_budget_for_worker(
        stale_messages, stale_worker, equipment, history.fingerprint) is None


def test_worker_source_cap_requires_current_preparation_and_authority():
    equipment, _, _, draft = planning_case()
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}])
        sessions.append(session)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    _store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    worker = {'preparationId': prepared['preparationId'], 'requirementsId': prepared['requirementsId'],
        'baseDraftId': prepared['baseDraftId'], 'libraryFingerprint': prepared['libraryFingerprint'],
        'historyFingerprint': None,
        'proposedSubmission': {'workouts': copy.deepcopy(prepared['sessions'])},
        'jointPlanning': {'feasible': True, 'sourceWorkingSetBudget': {
            'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}}}
    _store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, worker)

    worker_budget = worker['jointPlanning']['sourceWorkingSetBudget']
    assert session_drafting.source_working_set_budget_for_worker(messages, worker, equipment) == worker_budget

    # A reviewed planning choice does not turn the unbounded receipt into a cap.
    messages.extend([
        {'role': 'user', 'content': 'Keep the disclosed menu tradeoff for this candidate.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'decision', 'function': {
            'name': 'record_planning_decisions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'decision', 'content': json.dumps({
            'passed': True, 'decisionReview': {'passed': True, 'instructionBoundary': len(messages) - 2}})},
    ])
    assert session_drafting.source_working_set_budget_for_worker(
        messages, worker, equipment) == worker_budget

    stale = copy.deepcopy(worker)
    stale['jointPlanning']['sourceWorkingSetBudget'] = {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': 0}
    assert session_drafting.source_working_set_budget_for_worker(messages, stale, equipment) is None


def test_accepted_menu_worker_budget_and_joint_proof_survive_later_model_preparation_churn():
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch

    from workout_generator_pkg import allocation, interactive_shell, repair_execution
    from workout_generator_pkg.planning_tools import _latest_result
    from workout_generator_pkg.restriction_policy import effective_restrictions
    from workout_generator_pkg.training_history import TrainingHistory

    transcript_path = Path('build/workout_quality_completion_20261026/fresh_e2e/workouts/'
        'conversation_sessions/8422535f-9662-40b0-92b6-21c8e0e788ee/messages.json')
    backup_path = Path('build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json')
    if not transcript_path.is_file() or not backup_path.is_file():
        import pytest
        pytest.skip('Retained E2E transcript and library backup are local acceptance artifacts.')
    # Replay the saved 90-message run prefix in memory. The retained file is never rewritten.
    retained = json.loads(transcript_path.read_text(encoding='utf-8'))[:90]
    # /continue replayed the accepted worker result, then the next assistant
    # action submitted its exact candidate for a fresh production audit.
    messages = retained[:88]
    history = TrainingHistory.from_file(backup_path)
    equipment = interactive_shell._load_exercise_library_payload(backup_path)
    _, worker = _latest_result(messages, 'draft_workout_sessions')
    _, latest_preparation = _latest_result(messages, 'prepare_workout_sessions')
    if latest_preparation['libraryFingerprint'] != session_drafting.library_fingerprint(equipment):
        current_authority = session_drafting._preparation_authority(messages,
            {'baseDraftId': latest_preparation.get('baseDraftId')}, equipment, history.fingerprint)
        assert session_drafting.source_working_set_budget_for_worker(
            messages, worker, equipment, history.fingerprint) is None
        assert session_drafting._prior_source_working_set_budget(messages, current_authority) is None
        return
    assert worker['preparationId'] == '451ab46665367fa9507b2270e27439680045e4840a6e782deebfc95886871318'
    assert latest_preparation['preparationId'] != worker['preparationId']
    assert latest_preparation['sourceWorkingSetBudget']['variableWeeklyWorkingSets'] == 84
    assert worker['jointPlanning']['sourceWorkingSetBudget']['variableWeeklyWorkingSets'] == 75

    source_budget = session_drafting.source_working_set_budget_for_worker(
        messages, worker, equipment, history.fingerprint)
    assert source_budget == worker['jointPlanning']['sourceWorkingSetBudget']

    _, requirement_receipt = _latest_result(messages, 'set_workout_requirements')
    source_workouts = worker['proposedSubmission']['workouts']
    proof_owner = {**worker, 'coordinatedJointPlanning': worker['jointPlanning']}
    reused = allocation.reusable_joint_receipt(proof_owner, worker['requirementsId'],
        source_workouts, requirement_receipt['requirements'], equipment,
        messages, history, effective_restrictions(requirement_receipt, equipment),
        False, preserve_source_selection=False,
        source_working_set_budget=source_budget)
    assert reused is not None
    assert reused['sourceWorkingSetBudget'] == source_budget
    assert reused['solvedPrescriptionHash'] == worker['jointPlanning']['solvedPrescriptionHash']

    # Repair and interactive audit paths resolve the same accepted-preparation
    # source cap despite later, unapproved model churn.
    assert repair_execution._repair_source_working_set_budget(
        source_workouts, requirement_receipt['requirements'], equipment,
        effective_restrictions(requirement_receipt, equipment),
        requirements_id=worker['requirementsId'], allow_educated_load_guesses=False,
        training_history=history, messages=messages, redistribution_constraints=[]) == source_budget

    audit_call = retained[88]['tool_calls'][0]
    arguments = json.loads(audit_call['function']['arguments'])
    # Replay through the actual interactive audit handler after /continue. The
    # reviewer is stubbed to avoid provider calls; a solver call fails the test.
    with patch('workout_generator_pkg.interactive_shell.review_draft',
               side_effect=lambda client, result, *args, **kwargs: result), \
         patch('workout_generator_pkg.joint_planning.solve_prescribed_week',
               side_effect=AssertionError('validated worker receipt should be reused')):
        response = interactive_shell.handle_function_call(None, messages,
            'audit_workout_plan', arguments, provided_equipment=equipment,
            deps=SimpleNamespace(execute_workout_generation=lambda *args, **kwargs: None),
            allow_educated_load_guesses=False, training_history=history)
    continued = json.loads(response['result'])
    assert continued['passed'] is True
    assert (continued.get('coordinatedJointPlanning') or {}).get('reusedForValidatedCandidate') is True
    assert continued.get('jointPromotionGate') is None
    assert not any(error.get('code') == 'joint_candidate_comparison_unresolved'
                   for error in continued.get('errors', []))

    # Once materialized as REVISION_0, the exact worker artifact remains a
    # valid proof owner; a different current artifact invalidates that handoff.
    exact_current = messages + [retained[88], {'role': 'tool',
        'tool_call_id': audit_call['id'], 'content': json.dumps(continued)}]
    assert session_drafting.source_working_set_budget_for_worker(
        exact_current, worker, equipment, history.fingerprint) == source_budget
    changed_current = copy.deepcopy(exact_current)
    changed_result = json.loads(changed_current[-1]['content'])
    changed_result['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    changed_current[-1]['content'] = json.dumps(changed_result)
    assert session_drafting.source_working_set_budget_for_worker(
        changed_current, worker, equipment, history.fingerprint) is None


def test_retained_continue_dispatches_worker_reaudit_without_planner_call(monkeypatch, tmp_path):
    from dataclasses import replace
    from pathlib import Path
    from types import SimpleNamespace

    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.deps import resolve_shell_deps
    from workout_generator_pkg.planner_context import pending_reaudit, request_planning_state
    from workout_generator_pkg.training_history import TrainingHistory

    transcript_path = Path('build/workout_quality_completion_20261026/fresh_e2e/workouts/'
        'conversation_sessions/8422535f-9662-40b0-92b6-21c8e0e788ee/messages.json')
    backup_path = Path('build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json')
    if not transcript_path.is_file() or not backup_path.is_file():
        pytest.skip('Retained E2E transcript and library backup are local acceptance artifacts.')
    retained = json.loads(transcript_path.read_text(encoding='utf-8'))[:94]
    assert len(retained) == 94 and retained[-1].get('role') == 'assistant'
    history = TrainingHistory.from_file(backup_path)
    equipment = interactive_shell._load_exercise_library_payload(str(backup_path))
    state = request_planning_state(interactive_shell._messages_for_api(
        retained, True, history, equipment))
    reaudit = pending_reaudit(state, '/continue')
    if state.get('requirementsId') != 'REQUIREMENTS_d5c59e7fb135dc20':
        # The retained receipt belongs to an older requirement authority. It
        # cannot authorize resuming its worker proof under today's policy.
        assert state['requirementsApproved'] is False
        assert reaudit is None
        return
    assert state['requirementsId'] == 'REQUIREMENTS_d5c59e7fb135dc20'
    assert state['requirementsApproved'] is True
    assert reaudit['_internalAuditAction'] == 'validated_worker_receipt_recovery'
    assert reaudit['baseDraftId'] == 'REVISION_0'

    conversation_id = '8422535f-9662-40b0-92b6-21c8e0e788ee'
    saved_record = {'messages': copy.deepcopy(retained), 'metadata': {}}
    calls = []
    events = []

    class Logger:
        def __init__(self, *_args): pass
        def log(self, *args): events.append(args)
        def log_print(self, *args): events.append(args)
        def log_response(self, *_args, **_kwargs): pass
        def __getattr__(self, _name): return lambda *_args, **_kwargs: None
        def close(self): pass

    def never_call_planner(*_args, **_kwargs):
        pytest.fail('A validated worker proof should dispatch the audit before planner chat.')

    def handle_audit(_client, _messages, name, arguments, *_args, **_kwargs):
        calls.append((name, arguments))
        return {'result': json.dumps({'passed': True, 'userQuestion': 'stop after dispatch'}),
                'waiting_for_user': True, 'should_exit': False, 'generation_result': None}

    deps = replace(resolve_shell_deps(),
        default_script_dir=lambda: str(tmp_path),
        load_conversation_record=lambda _cid, _directory: copy.deepcopy(saved_record),
        resolve_conversation_id=lambda _identifier, _directory: conversation_id,
        set_active_conversation=lambda *_args: None,
        save_conversation=lambda *_args, **_kwargs: None,
        get_log_dir=lambda *_args: None,
        ConversationLogger=Logger,
        chat_call_with_loading=never_call_planner,
        handle_function_call=handle_audit,
        OpenAI=lambda **_kwargs: object(),
        httpx=SimpleNamespace(Timeout=lambda *_args, **_kwargs: None,
                              Client=lambda **_kwargs: object()),
        list_available_progress=lambda *_args: [],
        delete_progress_file=lambda *_args: None)
    monkeypatch.setattr(interactive_shell, 'resolve_llm_endpoint',
        lambda: SimpleNamespace(model='offline-test', base_url='https://unused.invalid'))
    monkeypatch.setattr(interactive_shell, 'require_api_key', lambda _endpoint: 'offline-test')
    monkeypatch.setattr(interactive_shell, '_render_turns', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(interactive_shell, 'report_usage', lambda *_args, **_kwargs: None)
    inputs = iter([f'/resume-conversation {conversation_id}', '/continue', '/exit'])
    input_calls = []
    def fake_input(*_args):
        value = next(inputs)
        input_calls.append(value)
        return value
    monkeypatch.setattr('builtins.input', fake_input)
    monkeypatch.setattr('sys.argv', ['workout-generator', '--history-backup-file', str(backup_path)])

    interactive_shell.main(deps)

    assert len(calls) == 1, (input_calls, [event for event in events if any(
        token in str(event) for token in ('continue', 'paused', 'Error:', 'Planning'))])
    name, arguments = calls[0]
    assert name == 'audit_workout_plan'
    assert arguments == {'requirementsId': 'REQUIREMENTS_d5c59e7fb135dc20',
                         'baseDraftId': 'REVISION_0', 'patch': []}


def test_menu_reconsideration_unions_prior_recipe_only_when_code_requests_it():
    equipment, _, _, draft = planning_case()
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition.update(id='push-up-variation', name='Push-Up Variation')
    equipment['exerciseDefinitions'].append(second_definition)
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = []
    for index in range(2):
        session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
        session.update(name=f'Day {index + 1}', trainingDays=[index * 2],
            exercises=[{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}])
        sessions.append(session)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': sessions}
    first = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    _store_tool(messages, 'prepare_workout_sessions', arguments, first)

    revised = copy.deepcopy(arguments)
    for day in revised['sessions']:
        day['exercises'][0]['definition_id'] = 'LIBRARY_1'
    selected_only = session_drafting.prepare_workout_sessions(revised, messages, equipment)
    reconsidered = session_drafting.prepare_workout_sessions(
        revised, messages, equipment, preserve_prior_menu=True)

    assert {item['definition_id'] for item in selected_only['recipeSessions'][0]['exercises']} == {'LIBRARY_1'}
    assert {item['definition_id'] for item in reconsidered['recipeSessions'][0]['exercises']} == {'LIBRARY_0', 'LIBRARY_1'}
    assert reconsidered['sourceWorkingSetBudget'] == {
        'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}


def test_menu_union_keeps_nonshared_member_of_prior_superset_as_standalone_option():
    current = [{'trainingDays': [0], 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}]}]
    prior = {'preparationId': 'PREP_OLD', 'recipeSessions': [{
        'trainingDays': [0], 'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_0', 'numWorkSets': 4, 'superset': 'PAIR'},
            {'definition_id': 'LIBRARY_1', 'numWorkSets': 3, 'superset': 'PAIR'},
        ]}]}

    union = session_drafting._union_prior_recipe_menu(current, prior)

    assert [(item['definition_id'], item['numWorkSets'], item['superset'])
            for item in union[0]['exercises']] == [
        ('LIBRARY_0', 5, None), ('LIBRARY_1', 3, None)]


def test_joint_solver_can_omit_an_option_from_the_union_menu():
    from workout_generator_pkg import joint_planning

    equipment, requirements, _, draft = planning_case()
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition['id'] = 'push-up-option'
    equipment['exerciseDefinitions'].append(second_definition)
    session = copy.deepcopy(draft['workouts'][0])
    for item in session['exercises']:
        item.pop('placementNotes', None)
    second = copy.deepcopy(session['exercises'][0])
    second['definition_id'] = 'LIBRARY_1'
    second['setupSeconds'] = 1500
    session['exercises'].append(second)

    result = joint_planning.solve_prescribed_week([session], requirements, equipment,
        preserve_source_selection=False)

    assert result['feasible'], result
    selected = result['sessions'][0]['exercises']
    assert len(selected) == 1
    assert result['audit']['weeklyVolume']['chest']['effective'] == 5


def test_internal_menu_control_is_not_accepted_as_model_argument():
    equipment, _, _, draft = planning_case()
    stored = set_workout_requirements({
        'sessionsPerWeek': 2,
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 10, 'maximum': 12}},
                         'perSessionEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}},
                         'maximumSessionSeconds': 1000},
    }, [{'role': 'user', 'content': 'Plan two sessions with 10-12 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    session = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
    session.update(name='Day 1', trainingDays=[0],
        exercises=[{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}])
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
        'name': 'Program', 'sessions': [session, {**session, 'name': 'Day 2', 'trainingDays': [2]}],
        '_internalPreservePriorMenu': True}

    with pytest.raises(PlanningInputError) as error:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)

    assert error.value.code == 'invalid_preparation_arguments'
