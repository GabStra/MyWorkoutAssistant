import copy
import json

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planning_tools import (
    SET_WORKOUT_REQUIREMENTS_TOOL, requirement_sources, requirements_approved, set_workout_requirements,
)
from test_workout_generator_planning_tools import planning_case


def _record(messages, result):
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(result)}])
    if result.get('requirementsPreview'):
        messages.append({'role': 'assistant', 'content': result['requirementsPreview'],
                         'canonicalRequirementsPreview': result['requirementsId']})


def test_planner_and_requirements_reviewer_share_actual_numerical_capabilities(monkeypatch):
    from workout_generator_pkg.generation_audit import MUSCLES, audit_policy, available_muscle_targets
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Audit lats and upper back separately at 15-18 sets each.'}]
    policy = audit_policy()
    assert policy['supportedMuscleTargets'] == {muscle: sorted(tags) for muscle, tags in MUSCLES.items()}
    policy = audit_policy(available_muscle_targets(equipment))
    schema = workout_requirements_tool(equipment)['function']['parameters']['properties']['auditTargets']
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        assert set(schema['properties'][field]['properties']) == set(policy['supportedMuscleTargets'])
    outgoing = _messages_for_api(messages, True, provided_equipment=equipment)
    assert any(json.dumps(policy) in m.get('content', '') for m in outgoing)
    def reject(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        assert context['auditPolicy'] == policy
        return json.dumps({'findings': [{'severity': 'blocking', 'action': 'clarify',
            'path': '/auditPolicy/supportedMuscleTargets',
            'message': 'Separate regional numerical targets are not supported.',
            'evidencePaths': ['/sourceMessages/SOURCE_0/content', '/auditPolicy/supportedMuscleTargets'],
            'repair': 'Explain the limitation and ask whether the user accepts aggregate targets or needs software/library support first.'}]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject)
    payload = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert not payload['passed'] and 'requirementsPreview' not in payload
    assert payload['errors'][0]['action'] == 'clarify'


def test_extraction_preserves_originals_and_never_promotes_model_notes():
    equipment, arguments, _, _ = planning_case()
    messages = [
        {'role': 'user', 'content': 'Keep my full original requirements; calves have no target.'},
        {'role': 'assistant', 'content': 'Separate targets (a) or combined (b)?'},
        {'role': 'user', 'content': '1-b. Allow only the conventional deadlift exclusion.'}]
    arguments['notes'] = 'Invented warm-up and prohibition. ' * 200
    before = copy.deepcopy(messages)
    result = set_workout_requirements(arguments, messages, equipment)
    assert result['requirements']['notes'] == ''
    assert result['sourceMessages'] == requirement_sources(messages)
    assert messages == before
    assert 'notes' not in SET_WORKOUT_REQUIREMENTS_TOOL['function']['parameters']['properties']
    assert 'Invented' not in result['requirementsPreview']
    assert not requirements_approved(messages, result)
    outgoing = _messages_for_api(messages, True)
    assert any('generalWarmupSeconds' in m.get('content', '') and 'Application auditPolicy' in m['content'] for m in outgoing)


@pytest.mark.parametrize('path,message,repair', [
    ('/requirements/auditTargets/weeklyEffectiveSets/calves', 'Unspecified calves became a zero target.', 'Remove the unsupported calf target.'),
    ('/sourceMessages/SOURCE_0/content', 'Posterior balance counting is unresolved.', 'Ask how overlapping posterior sets should count and wait.'),
    ('/sourceMessages/SOURCE_0/content', 'Warm-up duration differs from the estimator.', 'Ask which duration applies before recording requirements.'),
])
def test_source_findings_block_requirement_approval(monkeypatch, path, message, repair):
    equipment, arguments, _, _ = planning_case()
    arguments['auditTargets']['weeklyEffectiveSets']['calves'] = {'minimum': 0, 'maximum': 0}
    messages = [{'role': 'user', 'content': 'Calves have no target; balance quads with posterior work; warm up for eight minutes.'}]
    finding = {'severity': 'blocking', 'path': path, 'message': message,
               'evidencePaths': ['/sourceMessages/SOURCE_0/content'], 'repair': repair}
    calls = []
    def check(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    result = handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)
    payload = json.loads(result['result'])
    assert payload['passed'] is False and 'requirements_preview' not in result
    assert payload['errors'][0]['repair'] == repair
    assert calls[0]['sourceMessages']['SOURCE_0']['content'] == messages[0]['content']
    _record(messages, payload)
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    assert not requirements_approved(messages)


def test_successful_source_review_is_cached_and_new_source_needs_confirmation(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"findings":[]}', None, None))
    first = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    _record(messages, first)
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    assert requirements_approved(messages)
    repeated = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert repeated['requirementsId'] == first['requirementsId'] and len(calls) == 1
    messages.append({'role': 'user', 'content': 'Keep stationary carries if space allows.'})
    revised = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert revised['requirementsId'] != first['requirementsId'] and len(calls) == 2
    assert not requirements_approved(messages, revised)


def test_invalid_source_references_fail_closed_and_execution_failure_waits_for_explicit_retry(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    calls = []
    finding = {'severity': 'blocking', 'path': '/sourceMessages/999', 'message': 'Unsupported.',
               'evidencePaths': ['/sourceMessages/999'], 'repair': 'Ask.'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or json.dumps({'findings': [finding]}), None, None))
    def submit():
        return json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    failed = submit()
    assert failed['errors'][0]['code'] == 'requirements_review_failed'
    _record(messages, failed)
    assert not submit()['passed'] and len(calls) == 2  # Original and one finding repair, then cached.
    messages.append({'role': 'user', 'content': '/continue'})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"findings":[]}', None, None))
    repaired = submit()
    assert repaired['passed'] and len(calls) == 3
    assert 'errors' not in repaired and 'instruction' not in repaired


def test_cancelled_source_review_propagates(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    def cancel(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, 'chat_call', cancel)
    with pytest.raises(KeyboardInterrupt):
        handle_function_call(None, [{'role': 'user', 'content': 'Plan chest work.'}],
                             'set_workout_requirements', arguments, equipment)


def test_source_review_is_bound_to_the_actual_extracted_fields(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    _record(messages, result)
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    assert requirements_approved(messages)
    changed = copy.deepcopy(result)
    changed['requirements']['auditTargets']['weeklyEffectiveSets']['calves'] = {'minimum': 0, 'maximum': 0}
    assert not requirements_approved(messages, changed)


def test_missing_original_source_is_rejected_before_a_model_call(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('No source to review'))
    with pytest.raises(ValueError, match='No original user instructions'):
        handle_function_call(None, [], 'set_workout_requirements', arguments, equipment)


def test_source_placeholders_do_not_expose_or_confuse_original_transcript_positions():
    equipment, arguments, _, _ = planning_case()
    candidate = set_workout_requirements(arguments, [], equipment)
    candidate['sourceMessages'] = [
        {'messageIndex': 3, 'role': 'user', 'content': 'Original requirements'},
        {'messageIndex': 5, 'role': 'assistant', 'content': 'Choose a or b?'},
        {'messageIndex': 9, 'role': 'user', 'content': 'a'}]
    original_id = '11111111-1111-4111-8111-111111111111'
    candidate['restrictionPolicy'] = {'excludedDefinitionIds': [original_id],
        'excludedExerciseNames': ['Barbell Deadlift'], 'exceptExerciseNames': []}
    context = review._requirements_context(candidate)
    assert list(context['sourceMessages']) == ['SOURCE_0', 'SOURCE_1', 'SOURCE_2']
    assert review._pointer(context, '/sourceMessages/SOURCE_2/content') == 'a'
    assert 'messageIndex' not in json.dumps(context) and original_id not in json.dumps(context)
    with pytest.raises(ValueError, match='Reviewer reference does not exist'):
        review._requirements_pointer(context, '/sourceMessages/9')
    assert candidate['sourceMessages'][2]['messageIndex'] == 9


def test_miswrapped_restriction_findings_reach_the_planner_without_another_review(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Exclude conventional barbell deadlift; other hinges are allowed.'}]
    finding = {'severity': 'blocking', 'path': '/requirements/restrictionPolicy',
               'message': 'The deadlift restriction is missing.',
               'evidencePaths': ['/requirements/restrictionPolicy/excludedExerciseNames', '/sourceMessages/SOURCE_0/content'],
               'repair': 'Restore only the conventional barbell deadlift exclusion.'}
    calls = []
    def check(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        assert 'notes' not in calls[-1]['requirements']
        assert 'Do not request notes or a rewritten recap' in request[0]['content']
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    result = handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)
    payload = json.loads(result['result'])
    assert not payload['passed'] and 'requirements_preview' not in result
    error = payload['errors'][0]
    assert error['code'] == 'requirements_source_finding'
    assert error['path'] == '/restrictionPolicy'
    assert error['evidencePaths'] == ['/restrictionPolicy/excludedExerciseNames', '/sourceMessages/SOURCE_0/content']
    assert error['repair'] == finding['repair']
    _record(messages, payload)
    cached = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert cached['errors'] == payload['errors'] and len(calls) == 1


def test_requirement_wrapper_repair_rejects_ambiguous_and_missing_paths():
    context = {'requirements': {}, 'restrictionPolicy': {}, 'auditPolicy': {}}
    assert review._requirements_pointer(context, '/requirements/restrictionPolicy') == '/restrictionPolicy'
    context['auditPolicy']['restrictionPolicy'] = {}
    with pytest.raises(ValueError, match='reference does not exist'):
        review._requirements_pointer(context, '/requirements/restrictionPolicy')
    with pytest.raises(ValueError, match='reference does not exist'):
        review._requirements_pointer(context, '/requirements/invented')


def test_missing_optional_restrictions_have_a_valid_review_target_without_mutating_extraction(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Exclude conventional deadlift.'}]
    before = copy.deepcopy(arguments)
    def check(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        assert context['requirements']['exerciseRestrictions'] == {'excludeNameTerms': [], 'exceptNameTerms': []}
        assert 'For a missing field, cite its existing containing object' in request[0]['content']
        assert 'When the user explicitly delegates a decision' in request[0]['content']
        finding = {'severity': 'blocking', 'path': '/requirements/exerciseRestrictions/excludeNameTerms',
                   'message': 'The conventional deadlift exclusion is missing.',
                   'evidencePaths': ['/sourceMessages/SOURCE_0/content'], 'repair': 'Restore the exclusion.'}
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    payload = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert payload['errors'][0]['code'] == 'requirements_source_finding'
    assert 'restrictionPolicy is derived by Python, not editable' in payload['instruction']
    assert 'exerciseRestrictions' not in payload['requirements'] and arguments == before
