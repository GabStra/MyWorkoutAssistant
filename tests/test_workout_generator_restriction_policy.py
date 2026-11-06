import copy
import json

import pytest

from workout_generator_pkg import restriction_policy as policy
from workout_generator_pkg import exercise_library_tools as library
from workout_generator_pkg.planning_tools import set_workout_requirements, audit_workout_plan, PlanningInputError
from test_workout_generator_planning_tools import planning_case, requirement_messages, capability_requirement_messages


def restriction_case():
    equipment, requirements, _, draft = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**definition, 'id': key, 'name': name} for key, name in [
        ('a', 'Cable Tricep Pushdown'), ('b', 'Cable Crunch'), ('c', 'Cable Overhead Tricep Extension'),
        ('d', 'Cable Chest Fly'), ('e', 'Barbell Deadlift'), ('f', 'Barbell Romanian Deadlift')]]
    requirements['exerciseRestrictions'] = {'excludeNameTerms': ['Cable', 'Barbell Deadlift'],
                                          'exceptNameTerms': ['Triceps Pushdown', 'Cable Crunch']}
    return equipment, requirements, draft


def test_restrictions_resolve_once_and_all_consumers_enforce_the_same_ids(monkeypatch):
    equipment, requirements, draft = restriction_case()
    monkeypatch.setattr(policy, 'chat_call', lambda *a, **k: pytest.fail('Recognizable terms need no semantic call'))
    before = copy.deepcopy(requirements)
    stored = set_workout_requirements(requirements, [], equipment)
    resolved = stored['restrictionPolicy']
    assert resolved['exceptDefinitionIds'] == ['a', 'b']
    assert resolved['excludedDefinitionIds'] == ['c', 'd', 'e']
    assert requirements == before and 'Cable Tricep Pushdown' in stored['requirementsPreview']
    messages = requirement_messages(stored)
    assert set_workout_requirements(requirements, messages, equipment)['cached']
    assert library.execute_library_tool('search_exercise_library', {'queries': ['Cable Tricep Pushdown']}, equipment,
                                       messages=messages)['results'][0]['exercises'][0]['id'] == 'LIBRARY_0'
    selected = library.execute_library_tool('select_exercises', {'definition_ids': ['LIBRARY_0']}, equipment, messages=messages)
    assert selected['selectedExerciseDefinitionIds'] == ['a']
    with pytest.raises(ValueError, match='restriction policy'):
        library.execute_library_tool('select_exercises', {'definition_ids': ['LIBRARY_2']}, equipment, messages=messages)
    draft['requirementsId'] = stored['requirementsId']
    assert audit_workout_plan(draft, equipment, capability_requirement_messages(stored, equipment))['passed']
    draft['workouts'][0]['exercises'][0]['definition_id'] = 'LIBRARY_2'
    with pytest.raises(ValueError, match='violates approved restrictions'):
        audit_workout_plan(draft, equipment, messages)
    # No second interpretation of wording happens inside the availability gate.
    renamed = {**equipment['exerciseDefinitions'][0], 'name': 'Different display spelling'}
    assert library.definition_available(renamed, equipment, resolved)
    with pytest.raises(ValueError, match='Resolve restriction wording'):
        library.definition_available(renamed, equipment, requirements['exerciseRestrictions'])


def test_unknown_alias_is_semantically_resolved_then_shown_for_approval(monkeypatch):
    equipment, requirements, _ = restriction_case()
    requirements['exerciseRestrictions']['exceptNameTerms'] = ['pulley arm pressdown']
    calls = []
    def resolve(client, messages, **options):
        calls.append(json.loads(messages[-1]['content']))
        assert options['output_schema']['properties']['WORDING_0']['items']['enum'][0] == 'LIBRARY_0'
        return json.dumps({'WORDING_0': ['LIBRARY_0']}), None, None
    monkeypatch.setattr(policy, 'chat_call', resolve)
    stored = set_workout_requirements(requirements, [], equipment, client=object())
    assert len(calls) == 1 and stored['restrictionPolicy']['exceptDefinitionIds'] == ['a']
    assert '### Permitted library exceptions\n\n- Cable Tricep Pushdown' in stored['requirementsPreview']
    assert 'separate approval question' in stored['requirementsPreview']


def test_alias_resolution_receives_original_clarification_without_duplicate_structured_targets(monkeypatch):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, requirements, _ = restriction_case()
    requirements['exerciseRestrictions']['excludeNameTerms'].append('pushdown machine')
    clarification = ('Previously approved alias: pushdown machine means the current-library Cable Tricep Pushdown, '
        'which remains explicitly allowed by its existing exception. No broader cable permission is implied.')
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)}]
    original_messages, original_requirements = copy.deepcopy(messages), copy.deepcopy(requirements)
    payloads = []

    def resolve(client, request, **options):
        payload = json.loads(request[-1]['content'])
        payloads.append(payload)
        clarified = any(source['role'] == 'user' and clarification in source['content']
                        for source in payload['sourceMessages'].values())
        assert payload['wordings'] == {'WORDING_0': 'pushdown machine'}
        return json.dumps({'WORDING_0': ['LIBRARY_0'] if clarified else []}), None, None

    monkeypatch.setattr(policy, 'chat_call', resolve)
    with pytest.raises(PlanningInputError, match='Cannot resolve restriction'):
        set_workout_requirements(requirements, messages, equipment, client=object())
    clarified_messages = messages + [{'role': 'user', 'content': clarification}]
    original_clarified = copy.deepcopy(clarified_messages)
    result = set_workout_requirements(requirements, clarified_messages, equipment, client=object())

    assert result['restrictionPolicy']['exceptDefinitionIds'] == ['a', 'b']
    assert result['restrictionPolicy']['excludedDefinitionIds'] == ['c', 'd', 'e']
    assert {'kind': 'exclude', 'term': 'pushdown machine', 'definitionIds': ['a']} in result['restrictionPolicy']['matches']
    assert payloads[0]['wordings'] == payloads[1]['wordings']
    assert payloads[1]['sourceMessages']['SOURCE_1']['content'] == clarification
    assert 'auditTargets' not in payloads[1]['sourceMessages']['SOURCE_0']['content']
    assert 'pushdown machine' in payloads[1]['sourceMessages']['SOURCE_0']['content']
    assert 'Working sets at' in payloads[1]['sourceMessages']['SOURCE_0']['content']
    assert messages == original_messages and clarified_messages == original_clarified
    assert requirements == original_requirements


def test_unresolved_or_stale_policy_cannot_silently_allow_or_substitute_exercises():
    equipment, requirements, _ = restriction_case()
    unresolved = copy.deepcopy(requirements)
    unresolved['exerciseRestrictions']['exceptNameTerms'] = ['ambiguous movement']
    with pytest.raises(PlanningInputError, match='Cannot resolve restriction'):
        set_workout_requirements(unresolved, [], equipment)
    stored = set_workout_requirements(requirements, [], equipment)
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'].append({**changed['exerciseDefinitions'][0], 'id': 'new', 'name': 'Cable New Movement'})
    with pytest.raises(PlanningInputError, match='current library'):
        policy.effective_restrictions(stored, changed)
    legacy = {key: value for key, value in stored.items() if key != 'restrictionPolicy'}
    with pytest.raises(PlanningInputError, match='current library'):
        policy.effective_restrictions(legacy, equipment)
    renewed = set_workout_requirements(requirements, requirement_messages(legacy), equipment)
    assert renewed['restrictionPolicy'] and not renewed.get('cached')


@pytest.mark.parametrize('response', [
    {'WORDING_0': ['LIBRARY_999']},
    {},
    {'WORDING_0': []},
    {'WORDING_0': ['LIBRARY_0'], 'extra': []},
    {'matches': [{'kind': 'exclude', 'term': 'pushdown machine', 'references': [],
        'unresolvedReason': 'Maps to Cable Tricep Pushdown (LIBRARY_6), which is explicitly excepted; no exclusion reference applied.'}]},
])
def test_bad_semantic_resolution_never_produces_an_approved_policy(monkeypatch, response):
    equipment, requirements, _ = restriction_case()
    requirements['exerciseRestrictions']['exceptNameTerms'] = ['unknown alias']
    monkeypatch.setattr(policy, 'chat_call', lambda *a, **k: (json.dumps(response), None, None))
    with pytest.raises((PlanningInputError, RuntimeError)):
        set_workout_requirements(requirements, [], equipment, client=object())


def test_exception_only_lifts_matching_exclusions():
    equipment, requirements, _ = restriction_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0], 'id': 'g', 'name': 'Weighted Dumbbell Crunch'})
    requirements['exerciseRestrictions']['exceptNameTerms'] = ['crunch']
    result = set_workout_requirements(requirements, [], equipment)
    assert result['restrictionPolicy']['exceptDefinitionIds'] == ['b']
    assert result['restrictionPolicy']['exceptExerciseNames'] == ['Cable Crunch']


@pytest.mark.parametrize('semantic', [False, True])
def test_multiple_exception_candidates_require_user_clarification(monkeypatch, semantic):
    equipment, requirements, _ = restriction_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0], 'id': 'g', 'name': 'Cable Reverse Crunch'})
    term = 'ab movement' if semantic else 'crunch'
    requirements['exerciseRestrictions']['exceptNameTerms'] = [term]
    monkeypatch.setattr(policy, 'chat_call', lambda *a, **k: (json.dumps({
        'WORDING_0': ['LIBRARY_1', 'LIBRARY_6']}), None, None))
    with pytest.raises(PlanningInputError, match='Cable Crunch, Cable Reverse Crunch') as error:
        set_workout_requirements(requirements, [], equipment, client=object())
    assert error.value.code == 'ambiguous_restriction_exception'


def test_legacy_cached_policy_is_resolved_again_and_requires_new_approval():
    equipment, requirements, _ = restriction_case()
    stored = set_workout_requirements(requirements, [], equipment)
    stored['restrictionPolicy'].pop('resolutionVersion')
    renewed = set_workout_requirements(requirements, requirement_messages(stored), equipment)
    assert not renewed.get('cached')
    assert renewed['restrictionPolicy']['resolutionVersion'] == policy.RESTRICTION_POLICY_VERSION


@pytest.mark.parametrize('changed_library,changed_alias', [(False, False), (True, False), (False, True)])
def test_scoped_new_exclusion_reuses_only_unchanged_approved_alias(monkeypatch, changed_library, changed_alias):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, requirements, _ = restriction_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0],
        'id': 'g', 'name': 'Weighted Dumbbell Crunch'})
    requirements['exerciseRestrictions']['excludeNameTerms'].append('pushdown machine')
    monkeypatch.setattr(policy, 'chat_call', lambda *a, **k:
        (json.dumps({'WORDING_0': ['LIBRARY_0']}), None, None))
    stored = set_workout_requirements(requirements, [], equipment, client=object())
    messages = requirement_messages(stored)
    updated = copy.deepcopy(requirements)
    updated['exerciseRestrictions']['excludeNameTerms'].append('Weighted Dumbbell Crunch')
    if changed_alias:
        updated['exerciseRestrictions']['excludeNameTerms'][-2] = 'new pushdown alias'
    if changed_library:
        equipment['exerciseDefinitions'][0]['name'] = 'Renamed Cable Tricep Pushdown'
    messages.append({'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(updated)})
    monkeypatch.setattr(policy, 'chat_call', lambda *a, **k: pytest.fail('No alias call for unchanged approved meaning'))
    arguments = {'baseRequirementsId': stored['requirementsId'], 'updates': {}}
    if changed_library or changed_alias:
        with pytest.raises(PlanningInputError, match='Cannot resolve restriction'):
            set_workout_requirements(arguments, messages, equipment)
    else:
        result = set_workout_requirements(arguments, messages, equipment, client=object())
        assert result['restrictionPolicy']['exceptDefinitionIds'] == ['a', 'b']
        assert result['restrictionPolicy']['excludedDefinitionIds'] == ['c', 'd', 'e', 'g']
        assert result['requirements']['auditTargets'] == requirements['auditTargets']
        assert result['requirements']['exerciseRestrictions'] == updated['exerciseRestrictions']
