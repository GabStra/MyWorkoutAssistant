import copy
import json

import pytest

from workout_generator_pkg import restriction_policy as policy
from workout_generator_pkg import exercise_library_tools as library
from workout_generator_pkg.planning_tools import set_workout_requirements, audit_workout_plan, PlanningInputError
from test_workout_generator_planning_tools import planning_case, requirement_messages


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
    assert audit_workout_plan(draft, equipment, messages)['passed']
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
        return json.dumps({'matches': [{'kind': 'exception', 'term': 'pulley arm pressdown',
            'references': ['LIBRARY_0'], 'unresolvedReason': None}]}), None, None
    monkeypatch.setattr(policy, 'chat_call', resolve)
    stored = set_workout_requirements(requirements, [], equipment, client=object())
    assert len(calls) == 1 and stored['restrictionPolicy']['exceptDefinitionIds'] == ['a']
    assert '### Permitted library exceptions\n\n- Cable Tricep Pushdown' in stored['requirementsPreview']
    assert 'CONFIRM REQUIREMENTS' in stored['requirementsPreview']


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
    {'matches': [{'kind': 'exception', 'term': 'unknown alias', 'references': ['LIBRARY_999'], 'unresolvedReason': None}]},
    {'matches': []},
    {'matches': [{'kind': 'exception', 'term': 'unknown alias', 'references': [], 'unresolvedReason': 'Ambiguous'}]},
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
    monkeypatch.setattr(policy, 'chat_call', lambda *a, **k: (json.dumps({'matches': [
        {'kind': 'exception', 'term': term, 'references': ['LIBRARY_1', 'LIBRARY_6'], 'unresolvedReason': None}]}), None, None))
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
