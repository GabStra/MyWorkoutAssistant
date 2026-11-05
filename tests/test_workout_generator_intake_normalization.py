import copy
import json

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import plan_review, planning_tools
from workout_generator_pkg.interactive_shell import handle_function_call
from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER
from test_workout_generator_planning_tools import planning_case


def test_setup_intake_does_not_treat_missing_access_evidence_as_confirmation():
    arguments = {'sessionsPerWeek': 3, 'executionRules': [
        {'kind': 'supersetNoReconfiguration', 'coverageKey': None}]}
    result = planning_tools.set_workout_requirements(arguments,
        [{'role': 'user', 'content': 'Three sessions; both superset stations must remain ready.'}],
        planning_case()[0])
    rule = next(rule for rule in result['requirements']['executionRules']
                if rule['kind'] == 'supersetNoReconfiguration')
    assert rule['confirmedIndependentPairs'] == []
    assert {'path': '/executionRules/0/confirmedIndependentPairs', 'value': []} in (
        result['intakeNormalization']['applicationDefaults'])
    assert 'Require confirmed independent access' in result['requirementsPreview']
    assert 'confirmedIndependentPairs' not in arguments['executionRules'][0]


def test_structured_setup_amendment_routes_to_code_owned_intake_before_draft_work():
    from workout_generator_pkg.interactive_shell import _structured_requirements_amendment

    equipment = planning_case()[0]
    messages = [{'role': 'user', 'content': 'Three sessions; keep every numerical limit.'}]
    first = planning_tools.set_workout_requirements({'sessionsPerWeek': 3}, messages, equipment)
    first['sourceReview'] = {'passed': True}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(first)}])
    amended = copy.deepcopy(first['requirements'])
    first['requirements']['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 3, 'maximum': 6}
    messages[-1]['content'] = json.dumps(first)
    amended['executionRules'].append({'kind': 'supersetNoReconfiguration', 'coverageKey': None,
                                     'confirmedIndependentPairs': []})
    messages.append({'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(amended)})
    # A stale review refresh must not consume an unapplied structured instruction.
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'stale-refresh', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'stale-refresh', 'content': json.dumps(first)}])
    arguments = _structured_requirements_amendment(messages)
    assert arguments == {'updates': {}}
    second = planning_tools.set_workout_requirements(arguments, messages, equipment)
    assert second['requirements'] == amended
    second['sourceReview'] = {'passed': True}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'amendment', 'function': {
            'name': 'set_workout_requirements', 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': 'amendment', 'content': json.dumps(second)}])
    assert _structured_requirements_amendment(messages) is None


def test_sparse_intake_is_code_normalized_without_inventing_training_targets():
    equipment = planning_case()[0]
    arguments = {'sessionsPerWeek': 3}
    validate(arguments, planning_tools.workout_requirements_tool(equipment)['function']['parameters'])
    result = planning_tools.set_workout_requirements(arguments,
        [{'role': 'user', 'content': 'A three-day workout, please.'}], equipment)
    assert arguments == {'sessionsPerWeek': 3}
    requirements = result['requirements']
    assert requirements['auditTargets'] == {
        'weeklyEffectiveSets': {}, 'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}
    assert 'workingSetRIR' not in requirements
    assert 'durationBalanceToleranceSeconds' not in requirements
    assert 'objectiveOrder' not in requirements
    assert 'exerciseRestrictions' not in requirements
    assert requirements['relaxationPermissions'] == []
    assert {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2,
            'maximumSets': 20} in requirements['executionRules']
    assert 'Application default' in result['requirementsPreview']
    assert 'Unspecified (no invented target)' in result['requirementsPreview']
    assert result['intakeNormalization']['applicationDefaults']
    assert plan_review._requirements_context(result)['intakeNormalization'] == result['intakeNormalization']


def test_partial_targets_preserve_explicit_values_and_zero_bans():
    arguments = {'sessionsPerWeek': 2, 'auditTargets': {
        'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': 0}},
        'maximumSessionSeconds': 2700}}
    equipment = planning_case()[0]
    validate(arguments, planning_tools.workout_requirements_tool(equipment)['function']['parameters'])
    result = planning_tools.set_workout_requirements(arguments,
        [{'role': 'user', 'content': 'Two 45-minute sessions; no chest work.'}], equipment)
    assert result['requirements']['auditTargets'] == {
        **arguments['auditTargets'], 'perSessionEffectiveSets': {}}
    assert '/auditTargets/weeklyEffectiveSets' not in result['intakeNormalization']['unspecified']
    assert all(item['path'] not in ('/sessionsPerWeek', '/auditTargets/maximumSessionSeconds')
               for item in result['intakeNormalization']['applicationDefaults'])


def test_structured_soft_volume_ranges_survive_intake_and_render_separately_from_limits():
    from workout_generator_pkg.planning_tools import audit_workout_plan, render_draft
    from test_workout_generator_planning_tools import capability_requirement_messages

    equipment, _, _, draft = planning_case()
    supplied = {'sessionsPerWeek': 1, 'objectiveOrder': ['volume_target', 'duration_economy'],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': None,
            'preferredMinimum': 10, 'preferredMaximum': 15}},
            'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 5400}}
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(supplied)}]
    stored = planning_tools.set_workout_requirements({}, messages, equipment)
    assert stored['requirements']['auditTargets'] == supplied['auditTargets']
    assert stored['requirements']['objectiveOrder'] == supplied['objectiveOrder']
    assert 'Preferred weekly range' in stored['requirementsPreview']
    assert '| Chest | — | 10–15 |' in stored['requirementsPreview']
    draft['requirementsId'] = stored['requirementsId']
    result = audit_workout_plan(draft, equipment, capability_requirement_messages(stored, equipment))
    assert result['passed'], result['errors']
    text = render_draft(result['planIndex'], stored['requirements'], result['audit'])
    assert 'No hard volume bound | 10–15 | Below preferred range' in text
    assert result['audit']['volumePreferenceEvidence']['weekly'][0]['shortfall'] == 5


def test_unknown_regional_preference_is_not_rendered_as_zero_achieved_volume():
    from workout_generator_pkg.allocation import _audit_raw
    from workout_generator_pkg.planning_tools import render_draft

    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'pectoralis_clavicular': {'minimum': 0, 'maximum': None,
            'preferredMinimum': 10, 'preferredMaximum': 15}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    plan, report = _audit_raw(draft, equipment, requirements, None, True)
    assert report['volumePreferenceEvidence']['weekly'][0]['status'] == 'unknown'
    text = render_draft(plan, requirements, report)
    assert 'Unknown (known credit: 0)' in text
    assert 'No hard volume bound | 10–15 | Insufficient evidence' in text


def test_missing_schedule_reaches_existing_question_gate_without_approval(monkeypatch):
    monkeypatch.setattr(plan_review, '_review_call',
        lambda *a, **k: (json.dumps({'findings': []}), None, None))
    messages = [{'role': 'user', 'content': 'Help me build a workout.'}]
    response = handle_function_call(None, messages, 'set_workout_requirements', {}, planning_case()[0])
    result = json.loads(response['result'])
    assert response['waiting_for_user'] is True
    assert result['requirements']['sessionsPerWeek'] is None
    assert result['userQuestion']['kind'] == 'clarification'
    assert 'sessions per week' in result['userQuestion']['question']
    assert result['errors'][0]['code'] == 'missing_session_frequency'
    assert 'requirementsPreview' not in result
    assert not planning_tools.requirements_approved(messages, result)


def test_vague_duration_preference_does_not_become_a_numeric_tolerance(monkeypatch):
    monkeypatch.setattr(plan_review, '_review_call',
        lambda *a, **k: (json.dumps({'findings': []}), None, None))
    messages = [{'role': 'user', 'content': 'Three sessions. Keep their durations reasonably similar.'}]
    response = handle_function_call(None, messages, 'set_workout_requirements',
        {'sessionsPerWeek': 3, 'objectiveOrder': ['duration_balance']}, planning_case()[0])
    result = json.loads(response['result'])
    assert result['passed']
    assert 'durationBalanceToleranceSeconds' not in result['requirements']
    assert response['requirements_pending']
    assert not planning_tools.requirements_approved(messages, result)


def test_schedule_answer_updates_only_frequency_and_preserves_default_disclosure(monkeypatch):
    monkeypatch.setattr(plan_review, '_review_call',
        lambda *a, **k: (json.dumps({'findings': []}), None, None))
    equipment = planning_case()[0]
    messages = [{'role': 'user', 'content': 'Help me build a workout.'}]
    response = handle_function_call(None, messages, 'set_workout_requirements', {}, equipment)
    first = json.loads(response['result'])
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'intake', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'intake', 'content': response['result']},
        {'role': 'user', 'content': 'Three sessions per week.'}])
    response = handle_function_call(None, messages, 'set_workout_requirements',
        {'baseRequirementsId': first['requirementsId'], 'updates': {'sessionsPerWeek': 3}}, equipment)
    second = json.loads(response['result'])
    assert second['passed'] and response['requirements_pending']
    assert second['requirements'] == {**first['requirements'], 'sessionsPerWeek': 3}
    defaults = second['intakeNormalization']['applicationDefaults']
    assert defaults and all(item['path'] != '/sessionsPerWeek' for item in defaults)
    assert 'Application default' in second['requirementsPreview']
    assert not planning_tools.requirements_approved(messages, second)


def test_explicit_structured_instructions_win_over_application_defaults():
    supplied = {'sessionsPerWeek': 4, 'auditTargets': {'maximumSessionSeconds': 3600},
        'executionRules': [{'kind': 'workSets', 'coverageKey': None,
                           'minimumSets': 2, 'maximumSets': 3}]}
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(supplied)}]
    result = planning_tools.set_workout_requirements({}, messages, planning_case()[0])
    assert result['requirements']['sessionsPerWeek'] == 4
    assert result['requirements']['auditTargets']['maximumSessionSeconds'] == 3600
    assert result['requirements']['executionRules'][0] == supplied['executionRules'][0]
    assert all(item['path'] != '/executionRules/0'
               for item in result['intakeNormalization']['applicationDefaults'])
    from workout_generator_pkg.requirement_accounting import structured_requirement_mismatches
    authority = planning_tools._structured_requirement_source(result['sourceMessages'])
    assert structured_requirement_mismatches(result['requirements'], authority) == []
    changed = copy.deepcopy(result['requirements'])
    changed['auditTargets']['maximumSessionSeconds'] = 5400
    assert structured_requirement_mismatches(changed, authority) == ['/requirements/auditTargets/maximumSessionSeconds']
    schema = planning_tools.workout_requirements_tool(planning_case()[0], messages)['function']['parameters']
    assert 'maximumSessionSeconds' not in schema['properties']['auditTargets']['properties']
    assert 'weeklyEffectiveSets' in schema['properties']['auditTargets']['properties']


def test_supplied_rule_list_cannot_gain_model_authored_constraints(monkeypatch):
    supplied = {'sessionsPerWeek': 3, 'executionRules': [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3}]}
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(supplied)}]
    equipment = planning_case()[0]
    schema = planning_tools.workout_requirements_tool(equipment, messages)['function']['parameters']
    assert 'executionRules' not in schema['properties']
    extra = {'kind': 'order', 'before': 'hip_dominant', 'after': 'horizontal_push'}
    with pytest.raises(planning_tools.PlanningInputError) as error:
        planning_tools.set_workout_requirements({'executionRules': [extra]}, messages, equipment)
    assert error.value.code == 'structured_requirement_mismatch'
    candidate = planning_tools.set_workout_requirements({}, messages, equipment)
    assert candidate['requirements']['executionRules'][0] == supplied['executionRules'][0]
    # Even a cached or externally constructed candidate cannot bypass the boundary.
    candidate['requirements']['executionRules'].append(extra)
    monkeypatch.setattr(plan_review, '_review_call', lambda *a, **k: pytest.fail('Do not pay to review drift.'))
    with pytest.raises(planning_tools.PlanningInputError) as error:
        plan_review.review_requirements(None, candidate, messages)
    assert error.value.code == 'structured_requirement_mismatch'
    assert error.value.path == '/requirements/executionRules'


def test_unsupported_target_is_reported_not_dropped_or_merged():
    arguments = {'sessionsPerWeek': 3, 'auditTargets': {
        'weeklyEffectiveSets': {'latissimus_dorsi': {'minimum': 10, 'maximum': 15}}}}
    with pytest.raises(planning_tools.PlanningInputError) as error:
        planning_tools.set_workout_requirements(arguments,
            [{'role': 'user', 'content': 'Ten to fifteen weekly lat sets.'}], planning_case()[0])
    assert error.value.code == 'unsupported_muscle_targets'
    assert arguments['auditTargets']['weeklyEffectiveSets']['latissimus_dorsi']['minimum'] == 10


@pytest.mark.parametrize('arguments', [
    {'auditTargets': None}, {'sessionsPerWeek': 0},
    {'auditTargets': {'maximumSessionSeconds': 'short'}},
])
def test_normalization_does_not_replace_invalid_explicit_input(arguments):
    original = copy.deepcopy(arguments)
    with pytest.raises(ValidationError):
        planning_tools.set_workout_requirements(arguments,
            [{'role': 'user', 'content': 'Make a workout.'}], planning_case()[0])
    assert arguments == original


def test_conflicting_explicit_execution_bounds_are_not_repaired_with_defaults():
    with pytest.raises(planning_tools.PlanningInputError) as error:
        planning_tools.set_workout_requirements({'sessionsPerWeek': 3, 'executionRules': [
            {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 4, 'maximumSets': 3}]},
            [{'role': 'user', 'content': 'At least four sets but no more than three.'}], planning_case()[0])
    assert error.value.code == 'invalid_execution_rule'


def test_missing_isolation_rest_is_disclosed_once_and_not_retrofitted_during_updates():
    from workout_generator_pkg.programming_guidelines import DEFAULT_ISOLATION_REST_RULE
    from workout_generator_pkg.requirement_accounting import structured_requirement_mismatches

    supplied = {'sessionsPerWeek': 3, 'executionRules': [{'kind': 'rest', 'coverageKey': None,
        'exerciseCategory': 'HEAVY_COMPOUND', 'context': 'straightSets',
        'minimumSeconds': 120, 'maximumSeconds': 180}]}
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(supplied)}]
    result = planning_tools.set_workout_requirements({}, messages, planning_case()[0])
    requirements = result['requirements']
    index = requirements['executionRules'].index(DEFAULT_ISOLATION_REST_RULE)
    assert {'path': f'/executionRules/{index}', 'value': DEFAULT_ISOLATION_REST_RULE} in (
        result['intakeNormalization']['applicationDefaults'])
    assert 'Application default' in result['requirementsPreview']
    assert not structured_requirement_mismatches(requirements,
        planning_tools._structured_requirement_source(result['sourceMessages']))
    before = copy.deepcopy(requirements)
    planning_tools._ensure_application_execution_rules(requirements)
    assert requirements == before
    requirements['executionRules'].remove(DEFAULT_ISOLATION_REST_RULE)
    planning_tools._ensure_application_execution_rules(requirements, include_rest_defaults=False)
    assert DEFAULT_ISOLATION_REST_RULE not in requirements['executionRules']


@pytest.mark.parametrize('selector', [
    {'coverageKey': None}, {'coverageKey': None, 'exerciseCategory': 'ISOLATION'},
    {'coverageKey': 'calves'},
])
def test_explicit_zero_rest_policy_is_not_overridden_by_an_isolation_default(selector):
    from workout_generator_pkg.programming_guidelines import DEFAULT_ISOLATION_REST_RULE

    zero = {'kind': 'rest', **selector, 'context': 'straightSets',
        'minimumSeconds': 0, 'maximumSeconds': 0}
    requirements = {'executionRules': [copy.deepcopy(zero)]}
    planning_tools._ensure_application_execution_rules(requirements)
    assert requirements['executionRules'][0] == zero
    assert DEFAULT_ISOLATION_REST_RULE not in requirements['executionRules']


def test_isolation_rest_policy_rejects_zero_and_supplies_a_positive_solver_option():
    from workout_generator_pkg.allocation import _audit_raw
    from workout_generator_pkg.joint_planning import _rest_options
    from workout_generator_pkg.programming_guidelines import DEFAULT_ISOLATION_REST_RULE, audit_execution_rules

    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'][0]['exerciseCategory'] = 'ISOLATION'
    requirements['executionRules'] = [copy.deepcopy(DEFAULT_ISOLATION_REST_RULE)]
    item = draft['workouts'][0]['exercises'][0]
    item['restBetweenSetsSeconds'] = 0
    plan, report = _audit_raw(draft, equipment, requirements, None, True)
    audit_execution_rules(draft, requirements, report, plan)
    assert any(error['code'] == 'execution_rest' for error in report['errors'])
    variants = list(_rest_options([item], requirements, {'LIBRARY_0': equipment['exerciseDefinitions'][0]}, 5))
    assert item['restBetweenSetsSeconds'] == 0
    assert variants[-1][0]['restBetweenSetsSeconds'] == 60
    draft['workouts'][0]['exercises'] = variants[-1]
    plan, report = _audit_raw(draft, equipment, requirements, None, True)
    audit_execution_rules(draft, requirements, report, plan)
    assert not report['errors'], report['errors']
