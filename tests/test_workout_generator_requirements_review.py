import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planning_tools import (
    SET_WORKOUT_REQUIREMENTS_TOOL, _latest_result, active_requirement_result,
    approved_requirement_base, latest_requirement_candidate, requirement_sources,
    requirements_approved, set_workout_requirements,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_planning_decisions import _without_review_refs


def test_review_uses_executable_balance_default_without_mutating_requirements():
    _, _, candidate, _ = planning_case()
    candidate['requirements']['executionRules'] = [{
        'kind': 'coverageBalance', 'first': 'horizontal_pull',
        'second': 'vertical_pull', 'scope': 'weekly'}]
    original = copy.deepcopy(candidate)
    explicit = copy.deepcopy(candidate)
    explicit['requirements']['executionRules'][0]['relationship'] = 'balanced'

    assert review._requirements_context(candidate) == review._requirements_context(explicit)
    assert candidate == original

    explicit['requirements']['executionRules'][0]['relationship'] = 'first_not_less_than_second'
    assert review._requirements_context(explicit) != review._requirements_context(candidate)


def test_minimum_policy_reaches_extraction_and_independent_review():
    from workout_generator_pkg.interactive_shell import CANONICAL_PLANNING_INSTRUCTION
    from workout_generator_pkg.requirement_accounting import MINIMUM_TARGET_POLICY
    equipment, _, _, _ = planning_case()
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    properties = workout_requirements_tool(equipment)['function']['parameters']['properties']
    assert 'requirementAccounting' not in properties
    assert 'relaxationPermissions' in properties
    assert MINIMUM_TARGET_POLICY in CANONICAL_PLANNING_INSTRUCTION
    assert MINIMUM_TARGET_POLICY in review._REQUIREMENTS_PROMPT
    assert 'Do not require or reconstruct a prose ledger' in review._REQUIREMENTS_PROMPT
    assert 'exercise_distribution means spreading prescribed working-set exposure' in review._REQUIREMENTS_PROMPT
    assert 'Verify requirementAccounting covers EVERY explicit instruction' not in review._REQUIREMENTS_PROMPT


def _record(messages, result):
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(result)}])
    if result.get('requirementsPreview'):
        messages.append({'role': 'assistant', 'content': result['requirementsPreview'],
                         'canonicalRequirementsPreview': result['requirementsId']})


def _append_failed_unrequested_decision(messages, approved, *, updates=None):
    proposed = copy.deepcopy(approved)
    proposed.update({
        'requirementsId': 'REQUIREMENTS_rejected_decision_attempt',
        'baseRequirementsId': approved['requirementsId'],
        'passed': False,
        'sourceReview': {**copy.deepcopy(approved['sourceReview']), 'passed': False},
        'jointDecisionReview': {'passed': False},
        'proposedDecisions': {'DECISION_0': {'choice': 'unapproved'}},
    })
    if updates:
        proposed['requirements'] = copy.deepcopy(approved['requirements'])
        proposed['requirements']['objectiveOrder'] = ['distribution']
    call_id = 'failed-requirements-proposal'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'set_workout_requirements',
            'arguments': json.dumps({'baseRequirementsId': approved['requirementsId'],
                'updates': updates or {}, 'planningDecisions': {'decisions': [{'topic': 'unknown demand',
                    'choice': 'unavailable', 'sourceReferences': ['SOURCE_0']}]}})}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(proposed)},
    ])
    return proposed


def test_rejected_control_only_decision_proposal_keeps_existing_approved_requirements_active():
    _, arguments, _, _ = planning_case()
    approved = set_workout_requirements(arguments, [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}])
    messages = requirement_messages(approved)
    _, approved = _latest_result(messages, 'set_workout_requirements')
    audit_id = 'existing-audited-source'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': audit_id, 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': audit_id, 'content': json.dumps({
            'requirementsId': approved['requirementsId'], 'passed': False,
            'submittedDraft': {'requirementsId': approved['requirementsId'], 'workouts': [{}]}})},
        {'role': 'user', 'content': '/continue'},
    ])
    failed = _append_failed_unrequested_decision(messages, approved)

    candidate_index, candidate = latest_requirement_candidate(messages)
    active_index, active = active_requirement_result(messages)

    assert candidate_index > active_index
    assert candidate['requirementsId'] == failed['requirementsId']
    assert active['requirementsId'] == approved['requirementsId']
    assert _latest_result(messages, 'set_workout_requirements') == (active_index, active)
    assert requirements_approved(messages)


def test_unreviewed_direct_requirement_result_keeps_original_extraction_behavior():
    result = {'requirementsId': 'REQUIREMENTS_direct', 'requirements': {'objectiveOrder': ['strength']}}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'direct-requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'direct-requirements', 'content': json.dumps(result)},
    ]

    assert active_requirement_result(messages) == (1, result)
    assert _latest_result(messages, 'set_workout_requirements') == (1, result)


@pytest.mark.parametrize('later_user_message', [
    'CONFIRM GENERATE',
    'My answer: accept the disclosed tradeoff',
])
def test_later_gate_answers_do_not_reactivate_rejected_decision_candidate(later_user_message):
    _, arguments, _, _ = planning_case()
    approved = set_workout_requirements(arguments, [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}])
    messages = requirement_messages(approved)
    _, approved = _latest_result(messages, 'set_workout_requirements')
    audit_id = 'existing-audited-source'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': audit_id, 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': audit_id, 'content': json.dumps({
            'requirementsId': approved['requirementsId'], 'passed': False,
            'submittedDraft': {'requirementsId': approved['requirementsId'], 'workouts': [{}]}})},
        {'role': 'user', 'content': '/continue'},
    ])
    failed = _append_failed_unrequested_decision(messages, approved)
    messages.append({'role': 'user', 'content': later_user_message})

    active_index, active = active_requirement_result(messages)

    assert active_index < len(messages) - 2
    assert active['requirementsId'] == approved['requirementsId']
    assert active['requirementsId'] != failed['requirementsId']


@pytest.mark.parametrize('new_user_instruction,updates', [
    (True, {}),
    (False, {'objectiveOrder': ['distribution']}),
])
def test_rejected_decision_proposal_does_not_hide_a_new_user_edit_or_changed_requirement_candidate(
        new_user_instruction, updates):
    _, arguments, _, _ = planning_case()
    approved = set_workout_requirements(arguments, [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}])
    messages = requirement_messages(approved)
    _, approved = _latest_result(messages, 'set_workout_requirements')
    audit_id = 'existing-audited-source'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': audit_id, 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': audit_id, 'content': json.dumps({
            'requirementsId': approved['requirementsId'], 'passed': False,
            'submittedDraft': {'requirementsId': approved['requirementsId'], 'workouts': [{}]}})},
    ])
    if new_user_instruction:
        messages.append({'role': 'user', 'content': 'Change the weekly chest target.'})
    messages.append({'role': 'user', 'content': '/continue'})
    failed = _append_failed_unrequested_decision(messages, approved, updates=updates)

    index, active = _latest_result(messages, 'set_workout_requirements')

    assert active['requirementsId'] == failed['requirementsId']
    assert active['requirementsId'] != approved['requirementsId']
    assert index == latest_requirement_candidate(messages)[0]
    assert not requirements_approved(messages)


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
        assert _without_review_refs(context['auditPolicy']) == policy
        return json.dumps({'findings': [{'severity': 'blocking', 'action': 'clarify',
            'path': '/auditPolicy/supportedMuscleTargets',
            'message': 'Separate regional numerical targets are not supported.',
            'evidencePaths': ['/sourceMessages/SOURCE_0/content', '/auditPolicy/supportedMuscleTargets'],
            'repair': 'Explain the limitation and ask whether the user accepts aggregate targets or needs software/library support first.'}]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject)
    payload = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert not payload['passed'] and 'requirementsPreview' not in payload
    assert payload['errors'][0]['action'] == 'clarify'


@pytest.mark.parametrize('muscle,tag', [('abs', 'FRONT_ABS'), ('back', 'BACK_UPPER_BACK'),
                                      ('shoulders', 'FRONT_DELTOIDS'), ('adductors', 'FRONT_ADDUCTORS')])
def test_supported_target_flows_through_without_extra_muscle_choices(monkeypatch, muscle, tag):
    from workout_generator_pkg.generation_audit import audit_policy, available_muscle_targets
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    equipment, arguments, _, _ = planning_case()
    equipment['exerciseDefinitions'][0]['muscleGroups'] = [tag]
    equipment['exerciseDefinitions'][0]['secondaryMuscleGroups'] = []
    arguments['auditTargets']['weeklyEffectiveSets'] = {muscle: {'minimum': 5, 'maximum': 6}}
    arguments['auditTargets']['perSessionEffectiveSets'] = {}
    messages = [{'role': 'user', 'content': f'Plan 5-6 weekly effective sets for {muscle}.'}]
    policy = audit_policy(available_muscle_targets(equipment))
    schema = workout_requirements_tool(equipment)['function']['parameters']['properties']['auditTargets']
    assert set(schema['properties']['weeklyEffectiveSets']['properties']) == set(policy['supportedMuscleTargets'])
    outgoing = _messages_for_api(messages, True, provided_equipment=equipment)
    assert any(json.dumps(policy) in item.get('content', '') for item in outgoing)
    def approve(client, request, **options):
        context = json.loads(request[-1]['content'])
        assert _without_review_refs(context['auditPolicy']) == policy
        assert _without_review_refs(context['requirements']['auditTargets']) == arguments['auditTargets']
        return '{"findings":[]}', None, None
    monkeypatch.setattr(review, 'chat_call', approve)
    payload = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert payload['passed'] and payload['requirementsPreview']
    assert payload['requirements']['auditTargets'] == arguments['auditTargets']
    assert not payload.get('resolvedDecisions')


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


def test_coverage_role_schema_uses_code_owned_keys_and_labels_without_variant_text():
    from jsonschema import ValidationError
    from workout_generator_pkg.planning_tools import validate, workout_requirements_tool

    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': (
        'Include horizontal push work. Low-incline press is only an illustrative example in the accounting notes.') }]
    arguments['requiredCoverage'] = [{'key': 'horizontal_push', 'scope': 'weekly', 'intent': 'inclusion'}]
    schema = workout_requirements_tool(equipment)['function']['parameters']
    role_schema = schema['properties']['requiredCoverage']['items']
    assert 'description' not in role_schema['properties']
    assert 'horizontal_push' in role_schema['properties']['key']['enum']
    validate({'requiredCoverage': arguments['requiredCoverage']}, {
        'type': 'object', 'properties': {'requiredCoverage': schema['properties']['requiredCoverage']},
        'required': ['requiredCoverage'], 'additionalProperties': False})
    with pytest.raises(ValidationError):
        validate({'requiredCoverage': [{'key': 'horizontal_push', 'description': 'Low-incline emphasis', 'scope': 'weekly'}]}, {
            'type': 'object', 'properties': {'requiredCoverage': schema['properties']['requiredCoverage']},
            'required': ['requiredCoverage'], 'additionalProperties': False})
    with pytest.raises(ValidationError):
        validate({'requiredCoverage': [{'key': 'invented_role', 'scope': 'weekly'}]}, {
            'type': 'object', 'properties': {'requiredCoverage': schema['properties']['requiredCoverage']},
            'required': ['requiredCoverage'], 'additionalProperties': False})

    result = set_workout_requirements(arguments, messages, equipment)
    rule = result['requirements']['requiredCoverage'][0]
    assert rule['description'] == 'Horizontal push work'
    assert 'low-incline' not in result['requirementsPreview'].lower()
    assert 'Low-incline press' in result['sourceMessages'][0]['content']


def test_coverage_sparse_update_schema_cannot_add_freeform_role_description():
    from jsonschema import ValidationError
    from workout_generator_pkg.planning_tools import validate, _requirement_update_tool

    equipment, _, _, _ = planning_case()
    candidate = {'requirementsId': 'REQUIREMENTS_test'}
    schema = _requirement_update_tool(equipment, candidate)['function']['parameters']
    coverage_schema = schema['properties']['updates']['properties']['requiredCoverage']
    assert 'description' not in coverage_schema['items']['properties']
    with pytest.raises(ValidationError):
        validate({'baseRequirementsId': candidate['requirementsId'], 'updates': {'requiredCoverage': [
            {'key': 'horizontal_push', 'description': 'Low-incline emphasis', 'scope': 'weekly'}]}}, schema)


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
    assert payload['requirementsReviewQuestion']['kind'] == 'clarification'
    assert 'current requirements remain unchanged' in payload['requirementsReviewQuestion']['question']
    assert calls[0]['sourceMessages']['SOURCE_0']['content'] == messages[0]['content']
    _record(messages, payload)
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    assert not requirements_approved(messages)


def test_initial_established_requirement_violation_allows_one_sparse_correction_round(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets and do not reconfigure shared equipment during supersets.'}]
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
        'path': '/requirements/executionRules', 'decisionId': None,
        'message': 'The explicit superset equipment rule is missing from executionRules.',
        'evidencePaths': ['/sourceMessages/SOURCE_0/content', '/requirements/executionRules'],
        'repair': 'Add the typed supersetNoReconfiguration execution rule.'}
    responses = [json.dumps({'findings': [finding]}), '{"findings":[]}']
    calls = []
    def review_source(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        return responses.pop(0), None, None
    monkeypatch.setattr(review, 'chat_call', review_source)

    first_tool = handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)
    first = json.loads(first_tool['result'])
    assert first['passed'] is False
    assert 'requirementsReviewQuestion' not in first and not first_tool.get('waiting_for_user')
    assert 'baseRequirementsId=' + first['requirementsId'] in first['instruction']
    assert 'requirements_preview' not in first_tool
    _record(messages, first)

    repaired_rules = first['requirements']['executionRules'] + [{'kind': 'supersetNoReconfiguration', 'coverageKey': None}]
    update = {'baseRequirementsId': first['requirementsId'], 'updates': {'executionRules': repaired_rules}}
    second_tool = handle_function_call(None, messages, 'set_workout_requirements', update, equipment)
    second = json.loads(second_tool['result'])
    assert second['passed'] is True
    assert second_tool['requirements_pending'] is True
    assert len(calls) == 2 and calls[1]['reviewScope']['baseSourceReviewPassed'] is False
    assert not requirements_approved(messages, second)  # The correction still needs a fresh confirmation.


def test_automatic_requirement_correction_is_not_repeated_or_used_for_relaxation(monkeypatch):
    equipment, arguments, approved_candidate, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
        'path': '/requirements/executionRules', 'decisionId': None,
        'message': 'A source-backed execution rule is missing.',
        'evidencePaths': ['/sourceMessages/SOURCE_0/content'], 'repair': 'Add the source-backed rule.'}
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or json.dumps({'findings': [finding]}), None, None))
    first = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert 'requirementsReviewQuestion' not in first
    _record(messages, first)
    repeated = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert repeated['requirementsReviewQuestion']['kind'] == 'clarification'
    assert len(calls) == 1  # Same failed review is reused; no repair call is made by Python.

    approved_messages = requirement_messages(approved_candidate)
    assert not review._eligible_initial_requirement_correction(
        [finding], candidate=approved_candidate, messages=approved_messages, boundary=0, gaps=[], failure=None)
    relaxation = {**finding, 'path': '/requirements/relaxationPermissions'}
    assert not review._eligible_initial_requirement_correction(
        [relaxation], candidate=approved_candidate, messages=[], boundary=0, gaps=[], failure=None)


def test_saved_scoped_warmup_repair_routes_to_typed_update_but_mixed_clarification_stops(monkeypatch):
    session = (Path(__file__).parents[1] / 'build' / 'workout_single_review_20261023' / 'warmup_owner_continuation3'
        / 'workouts' / 'conversation_sessions' / '20deca57-14c9-4f60-b74b-f9b669028801' / 'messages.json')
    messages = json.loads(session.read_text(encoding='utf-8'))
    result_index = next(index for index in range(len(messages) - 1, -1, -1)
        if messages[index].get('role') == 'tool'
        and json.loads(messages[index].get('content', '{}')).get('reviewScope', {}).get('newSourceMessageIds') == ['SOURCE_4'])
    saved = json.loads(messages[result_index]['content'])
    source4 = next(message['content'] for message in messages[:result_index]
        if message.get('role') == 'user' and 'APPROVE SCOPED: Resolve the native warm-up capability conflict' in message.get('content', ''))
    assert 'hip_dominant' in source4 and len(saved['sourceReview']['findings']) == 1
    assert saved['sourceReview']['findings'][0]['basis'] == 'established_violation'
    assert saved['sourceReview']['findings'][0]['action'] == 'repair'

    candidate = copy.deepcopy(saved)
    for key in ('sourceReview', 'passed', 'errors', 'instruction', 'requirementsReviewQuestion', 'userQuestion'):
        candidate.pop(key, None)
    source_messages = copy.deepcopy(messages[:result_index])

    def review_with(findings):
        monkeypatch.setattr(review, '_review_call', lambda *args, **kwargs:
            (json.dumps({'findings': copy.deepcopy(findings)}), None, None))
        return review.review_requirements(None, copy.deepcopy(candidate), copy.deepcopy(source_messages))

    repaired = review_with(saved['sourceReview']['findings'])
    assert repaired['passed'] is False
    assert 'requirementsReviewQuestion' not in repaired
    assert 'One scoped correction attempt' in repaired['instruction']
    assert 'fresh user confirmation' in repaired['instruction']
    assert 'requirementsPreview' not in repaired

    clarification = copy.deepcopy(saved['sourceReview']['findings'][0])
    clarification.update(basis='uncertainty', action='clarify', message='Confirm whether this warm-up rule should also cover other exercise roles.')
    mixed = review_with([saved['sourceReview']['findings'][0], clarification])
    assert mixed['passed'] is False
    assert mixed['requirementsReviewQuestion']['kind'] == 'clarification'
    assert mixed['requirements']['executionRules'] == candidate['requirements']['executionRules']

    from workout_generator_pkg.planner_context import focus_planner_context
    equipment, _, _, _ = planning_case()

    def continued_state(transcript):
        continued = copy.deepcopy(transcript)
        continued.append({'role': 'user', 'content': '/continue'})
        outgoing = focus_planner_context(continued, continued, equipment)
        state_message = next(message['content'] for message in outgoing
            if message.get('role') == 'system' and message.get('content', '').startswith('Current planning state'))
        return json.loads(state_message.split('\n', 1)[1])

    saved_repair_state = continued_state(messages)
    instruction = saved_repair_state['requirementsFeedback']['instruction']
    assert 'one typed set_workout_requirements update' in instruction
    assert 'Do not ask the user to repeat the scoped authorization' in instruction
    assert saved_repair_state['requirementsApproved'] is False

    mixed_saved_messages = copy.deepcopy(messages)
    mixed_saved = copy.deepcopy(saved)
    mixed_saved['sourceReview']['findings'].append(clarification)
    mixed_saved['requirementsReviewQuestion'] = {'kind': 'clarification', 'question': clarification['message']}
    mixed_saved_messages[result_index]['content'] = json.dumps(mixed_saved)
    mixed_state = continued_state(mixed_saved_messages)
    mixed_instruction = mixed_state['requirementsFeedback']['instruction']
    assert 'one typed set_workout_requirements update' not in mixed_instruction
    assert 'Do not ask the user to repeat the scoped authorization' not in mixed_instruction
    assert mixed_state['requirementsApproved'] is False


def test_scoped_source_review_receives_code_computed_field_and_source_diff():
    equipment, arguments, stored, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    base = set_workout_requirements(arguments, messages, equipment)
    prior_finding = {'severity': 'blocking', 'basis': 'uncertainty', 'path': '/sourceMessages/SOURCE_0/content',
        'message': 'Clarify recovery expectations.', 'repair': 'Ask the user about recovery.'}
    base['sourceReview'] = {'passed': False, 'findings': [prior_finding]}
    _record(messages, base)
    updated = copy.deepcopy(base)
    updated['baseRequirementsId'] = base['requirementsId']
    updated['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] = 7
    updated['sourceMessages'].append({'messageIndex': 1, 'role': 'user',
        'content': 'Raise the chest ceiling to seven sets.'})
    scope = review._requirements_review_scope(updated, messages)
    expected_prior = {key: prior_finding[key] for key in ('severity', 'basis', 'message', 'repair')}
    assert scope == {'baseRequirementsId': base['requirementsId'],
        'baseSourceReviewPassed': False, 'changedPaths': ['/auditTargets/weeklyEffectiveSets/chest/maximum'],
        'newSourceMessageIds': ['SOURCE_1'], 'previousSourceFindings': [expected_prior]}


def test_source_review_preserves_the_code_rendered_scoped_change_preview(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    candidate = set_workout_requirements(arguments, messages, equipment)
    candidate['requirementsPreview'] += '\n\nUpdated fields:\n- Chest maximum: 7 sets'
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = review.review_requirements(None, candidate, messages)
    assert result['passed']
    assert 'Updated fields:\n- Chest maximum: 7 sets' in result['requirementsPreview']


def test_requirements_source_review_uses_one_low_effort_attempt(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    options_seen = []

    def respond(_client, _request, **options):
        options_seen.append(options)
        return '{"findings":[]}', None, None

    monkeypatch.setattr(review, 'chat_call', respond)
    result = review.review_requirements(None,
        set_workout_requirements(arguments, messages, equipment), messages)

    assert result['passed'] is True
    assert len(options_seen) == 1
    assert options_seen[0]['reasoning_effort'] == 'low'
    assert options_seen[0]['max_tokens'] == 8192
    assert options_seen[0]['retry'] is False


def test_requirements_source_review_configures_bounded_wrapper_recovery(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    options_seen = []

    def review_call(_client, _request, **options):
        options_seen.append(options)
        return '{"findings":[]}', None, None

    monkeypatch.setattr(review, '_review_call', review_call)
    result = review.review_requirements(None,
        set_workout_requirements(arguments, messages, equipment), messages)

    assert result['passed'] is True
    assert len(options_seen) == 1
    assert options_seen[0]['reasoning_effort'] == 'low'
    assert options_seen[0]['max_tokens'] == 8192
    assert options_seen[0]['retry'] is True


@pytest.mark.parametrize('source_is_supported', [True, False])
def test_source_citation_recovery_selects_only_user_source_and_classifies_by_owned_path(monkeypatch, source_is_supported):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    candidate = set_workout_requirements(arguments, messages, equipment)
    proposal = {'decisions': {'DECISION_0': {'topic': 'Volume preference',
        'choice': 'Preserve the user requested volume.', 'sourceReferences': ['SOURCE_0'],
        'sourceCountAtResolution': 1}}, 'newDecisionIds': ['DECISION_0']}
    monkeypatch.setattr(review, 'propose_decisions', lambda *_args, **_kwargs: copy.deepcopy(proposal))
    calls = []

    def respond(_client, request, **options):
        calls.append((request, options))
        if len(calls) == 1:
            context = json.loads(request[-1]['content'])
            return json.dumps({'findings': [{
                'severity': 'blocking', 'basis': 'uncertainty', 'action': 'clarify',
                'path': context['requirements']['_reviewRef'], 'decisionId': 'DECISION_0',
                'message': 'A source-backed requirement needs clarification.',
                'evidencePaths': [context['requirements']['executionRules'][0]['_reviewRef']],
                'repair': 'Ask a focused clarification question.'}]}), None, None
        selection_request = json.loads(request[-1]['content'])
        selection_schema = options['output_schema']
        choices = selection_schema['properties']['findingSourceReferences']['properties']['FINDING_A']['enum']
        source_ref = next(ref for ref in choices if ref != 'NONE') if source_is_supported else 'NONE'
        if source_is_supported:
            assert source_ref in selection_request['sources']
        return json.dumps({'findingSourceReferences': {'FINDING_A': source_ref}}), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_requirements(None, candidate, messages, planning_decisions=proposal)

    assert len(calls) == 2
    assert calls[1][1]['output_schema']['properties']['findingSourceReferences']['properties']['FINDING_A']['enum']
    assert not result['passed']
    assert bool(result['sourceReview'].get('failure')) is (not source_is_supported)
    finding = result['sourceReview']['findings'][0]
    assert finding['path'] == '/requirements'
    assert finding['decisionId'] == 'DECISION_0'
    assert finding['action'] == 'clarify'
    assert finding['severity'] == 'blocking'
    assert ('/sourceMessages/SOURCE_0' in finding['evidencePaths']) is source_is_supported
    assert result['decisions'] == {}


def test_informational_source_finding_does_not_block_or_request_reconstruction(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    finding = {'severity': 'warning', 'basis': 'uncertainty',
        'path': '/sourceMessages/SOURCE_0/content', 'message': 'Recovery capacity is not known.',
        'evidencePaths': ['/sourceMessages/SOURCE_0/content'],
        'repair': 'Personal recovery data was not supplied.'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    result = handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)
    payload = json.loads(result['result'])
    assert payload['passed'] is True
    assert 'requirementsReviewQuestion' not in payload
    assert 'Recovery capacity is not known.' in payload['requirementsPreview']


def test_clarification_request_cannot_be_downgraded_to_a_warning(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    finding = {'severity': 'warning', 'basis': 'uncertainty', 'action': 'clarify',
        'path': '/sourceMessages/SOURCE_0/content', 'message': 'Recovery capacity needs clarification.',
        'evidencePaths': ['/sourceMessages/SOURCE_0/content'],
        'repair': 'Ask the user about recovery capacity.'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    result = handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)
    payload = json.loads(result['result'])
    assert payload['passed'] is False
    assert payload['sourceReview']['findings'][0]['severity'] == 'blocking'
    assert payload['requirementsReviewQuestion']['kind'] == 'clarification'


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
    def malformed_once(*a, **kwargs):
        assert kwargs['retry'] is False
        calls.append(1)
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', malformed_once)
    def submit():
        return json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    failed = submit()
    assert failed['errors'][0]['code'] == 'requirements_review_failed'
    assert failed['requirementsReviewQuestion']['kind'] == 'clarification'
    _record(messages, failed)
    assert not submit()['passed'] and len(calls) == 1  # Malformed review is cached; no model form-repair call.
    messages.append({'role': 'user', 'content': '/continue'})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"findings":[]}', None, None))
    repaired = submit()
    assert repaired['passed'] and len(calls) == 2
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
    from workout_generator_pkg import generation_audit
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    _record(messages, result)
    messages.append({'role': 'user', 'content': 'CONFIRM REQUIREMENTS'})
    assert requirements_approved(messages)
    monkeypatch.setattr(generation_audit, 'CALIBRATION_TIMING', 'Updated workout execution timing explanation.')
    assert generation_audit.audit_workout_package({'workouts': []}, {})['calibrationTiming'] == generation_audit.CALIBRATION_TIMING
    assert requirements_approved(messages)  # Execution-report metadata does not change approved requirements.
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
    schema = SET_WORKOUT_REQUIREMENTS_TOOL['function']['parameters']['properties']['executionRules']
    assert json.dumps(schema, separators=(',', ':')) in review._REQUIREMENTS_PROMPT
    assert 'executionRulesSchema' not in review._with_review_refs(context)[0]
    assert 'Conditional advice' in review._REQUIREMENTS_PROMPT
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
        assert _without_review_refs(context['requirements']['exerciseRestrictions']) == {'excludeNameTerms': [], 'exceptNameTerms': []}
        assert 'A missing field is cited by its containing object FACT_n' in request[0]['content']
        assert 'When the user explicitly delegates a decision' in request[0]['content']
        finding = {'severity': 'blocking', 'path': '/requirements/exerciseRestrictions/excludeNameTerms',
                   'message': 'The conventional deadlift exclusion is missing.',
                   'evidencePaths': ['/sourceMessages/SOURCE_0/content'], 'repair': 'Restore the exclusion.'}
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    payload = json.loads(handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)['result'])
    assert payload['errors'][0]['code'] == 'requirements_source_finding'
    assert payload['errors'][0]['repair'] == 'Restore the exclusion.'
    assert 'exerciseRestrictions' not in payload['requirements'] and arguments == before


def test_intake_reference_error_exposes_choices_and_allows_correction():
    from workout_generator_pkg.planning_tools import PlanningInputError, workout_requirements_tool
    from jsonschema import ValidationError, validate
    equipment, arguments, _, _ = planning_case()
    arguments['requiredCoverage'] = [
        {'key': 'elbow_flexion', 'scope': 'weekly'},
        {'key': 'elbow_extension', 'scope': 'weekly'}]
    arguments['executionRules'] = [{'kind': 'coverageBalance', 'first': 'biceps',
        'second': 'triceps', 'scope': 'weekly'}]
    original = copy.deepcopy(arguments)
    with pytest.raises(PlanningInputError) as caught:
        set_workout_requirements(copy.deepcopy(arguments), [], equipment)
    error = caught.value.errors[0]
    assert error['allowedCoverageKeys'] == ['elbow_extension', 'elbow_flexion']
    assert error['invalidReferences'] == {'first': 'biceps', 'second': 'triceps'}
    assert 'not declared in requiredCoverage' in error['message']
    assert 'declare a supported role' in error['repair']
    assert arguments == original
    arguments['executionRules'][0].update(first='elbow_flexion', second='elbow_extension')
    result = set_workout_requirements(arguments, [], equipment)
    assert result['requirements']['executionRules'][0]['first'] == 'elbow_flexion'
    assert not any(e.get('code') == 'invalid_execution_rule' for e in result.get('errors', []))
    update_schema = workout_requirements_tool(equipment, requirement_messages(result))['function']['parameters']
    update_rules = update_schema['properties']['updates']['properties']['executionRules']
    first_schema = next(r for r in update_rules['items']['oneOf']
        if r['properties']['kind']['const'] == 'coverageBalance')['properties']['first']
    assert 'elbow_flexion' in first_schema['enum']
    assert 'invented_role' not in first_schema['enum']
    schema = workout_requirements_tool(equipment)['function']['parameters']
    bad = copy.deepcopy(original)
    bad.pop('requirementAccounting', None)
    bad['executionRules'][0]['first'] = 'invented_role'
    with pytest.raises(ValidationError):
        validate(bad, schema)
