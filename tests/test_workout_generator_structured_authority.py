import copy
import json
from pathlib import Path

import pytest
from jsonschema import validate

from workout_generator_pkg import plan_review, planning_tools
from workout_generator_pkg.requirement_accounting import (
    STRUCTURED_REQUIREMENTS_MARKER, structured_requirement_source,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages


def intake_case():
    equipment, requirements, _, _ = planning_case()
    requirements['executionRules'] = [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 20}]
    messages = [{'role': 'user', 'content': 'Use these requirements.\n'
        + STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)}]
    return equipment, requirements, messages


def test_intake_seeds_values_and_exposes_only_unspecified_policy_choices():
    equipment, expected, messages = intake_case()
    tool = planning_tools.workout_requirements_tool(equipment, messages)['function']['parameters']
    assert 'auditTargets' not in tool['properties']
    assert 'sessionsPerWeek' not in tool['properties']
    kinds = {rule['properties']['kind']['const']
             for rule in tool['properties']['executionRules']['items']['oneOf']}
    assert 'workSets' not in kinds and 'exerciseExposure' in kinds
    proposed = {'executionRules': [{'kind': 'exerciseExposure',
        'maximumSessionsPerWeek': 1, 'maximumWeeklySets': 6}]}
    validate(proposed, tool)
    result = planning_tools.set_workout_requirements(proposed, messages, equipment)
    assert result['requirements']['auditTargets'] == expected['auditTargets']
    assert result['requirements']['sessionsPerWeek'] == expected['sessionsPerWeek']
    assert expected['executionRules'][0] in result['requirements']['executionRules']
    assert proposed['executionRules'][0] in result['requirements']['executionRules']
    assert not planning_tools.requirements_approved(messages, result)


def test_mismatched_model_copy_does_not_override_user_values():
    equipment, _, messages = intake_case()
    with pytest.raises(planning_tools.PlanningInputError) as error:
        planning_tools.set_workout_requirements({'sessionsPerWeek': 2}, messages, equipment)
    assert error.value.code == 'structured_requirement_mismatch'


def test_existing_balance_default_does_not_look_like_an_unauthorized_change():
    equipment, payload, _ = intake_case()
    payload['requiredCoverage'] = [{'key': key, 'scope': 'weekly'}
                                   for key in ('horizontal_push', 'horizontal_pull')]
    payload['executionRules'].append({'kind': 'coverageBalance', 'first': 'horizontal_push',
        'second': 'horizontal_pull', 'scope': 'weekly'})
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(payload)}]
    candidate = planning_tools.set_workout_requirements({}, messages, equipment)
    context = plan_review._requirements_context(candidate)
    assert '/requirements/executionRules/1' in context['structuredAuthority']['matchedPaths']


@pytest.mark.parametrize('role,prefix,suffix', [
    ('assistant', '', ''), ('user', '```text\n', '\n```'), ('user', '> ', ''),
])
def test_assistant_and_quoted_blocks_are_not_authority(role, prefix, suffix):
    sources = [{'messageIndex': 0, 'role': role,
        'content': prefix + STRUCTURED_REQUIREMENTS_MARKER + '\n{"sessionsPerWeek":3}' + suffix}]
    assert structured_requirement_source(sources, planning_tools._REQUIREMENTS) is None


@pytest.mark.parametrize('payload', [
    '{"sessionsPerWeek":3,"sessionsPerWeek":4}', '{"durationBalanceToleranceSeconds":NaN}',
    '{"unknownField":3}',
])
def test_invalid_marked_input_fails_closed(payload):
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + payload}]
    with pytest.raises(planning_tools.PlanningInputError) as error:
        planning_tools.set_workout_requirements({}, messages, planning_case()[0])
    assert error.value.code == 'invalid_structured_requirements'


def test_new_structured_amendment_is_seeded_without_recopying_old_requirements():
    equipment, _, messages = intake_case()
    base = planning_tools.set_workout_requirements({}, messages, equipment)
    messages = requirement_messages(base)
    messages.append({'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER
                     + '\n{"auditTargets":{"weeklyEffectiveSets":{},"perSessionEffectiveSets":{},"maximumSessionSeconds":4200}}'})
    update = {'baseRequirementsId': base['requirementsId'], 'updates': {}}
    schema = planning_tools.workout_requirements_tool(equipment, messages)['function']['parameters']
    assert 'auditTargets' not in schema['properties']['updates']['properties']
    result = planning_tools.set_workout_requirements(update, messages, equipment)
    assert result['requirements']['auditTargets']['maximumSessionSeconds'] == 4200
    assert result['requirements']['executionRules'] == base['requirements']['executionRules']
    assert not planning_tools.requirements_approved(messages, result)


def test_later_valid_current_payload_supersedes_an_invalid_earlier_payload():
    sources = [
        {'messageIndex': 0, 'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n{"bad":true}'},
        {'messageIndex': 2, 'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n{"sessionsPerWeek":3}'},
    ]
    result = structured_requirement_source(sources, planning_tools._REQUIREMENTS)
    assert result['sourceMessageIndex'] == 2
    assert result['requirements'] == {'sessionsPerWeek': 3}


def retained_case():
    root = Path(__file__).parents[1] / 'build/workout_initial_requirements_e2e_20261028/fresh_e2e'
    meta = json.loads((root / 'conversation_meta.json').read_text())
    messages = json.loads((root / 'workouts/conversation_sessions' / meta['active_conversation_id']
                          / 'messages.json').read_text(encoding='utf-8'))
    candidate = json.loads(messages[5]['content'])
    candidate['resolvedDecisions'] = copy.deepcopy(candidate.get('proposedDecisions', {}))
    findings = copy.deepcopy(candidate['sourceReview']['findings'])
    for key in ('sourceReview', 'errors', 'passed', 'requirementsReviewQuestion', 'userQuestion'):
        candidate.pop(key, None)
    return candidate, messages[:5], findings


def reviewed(monkeypatch, candidate, messages, findings):
    calls = []
    def reply(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({'findings': findings}), None, None
    monkeypatch.setattr(plan_review, '_review_call', reply)
    result = plan_review.review_requirements(None, candidate, messages)
    assert len(calls) == 1
    return result, calls[0]


def test_saved_false_authorization_and_code_verification_findings_are_answered_by_code(monkeypatch):
    candidate, messages, saved = retained_case()
    false_findings = [saved[0], saved[2], saved[3], saved[4]]
    for finding in false_findings[:2]:
        finding.update(check='authorization', implementationCheck=None)
    false_findings[2].update(check='implementation', implementationCheck='regional_reporting')
    false_findings[3].update(check='implementation', implementationCheck='direct_coverage')
    before = copy.deepcopy(candidate['requirements'])
    result, call = reviewed(monkeypatch, candidate, messages, false_findings)
    assert result['passed'], result.get('errors')
    assert result['requirements'] == before
    assert len(result['sourceReview']['codeAnsweredChecks']) == 4
    assert 'requirementsReviewQuestion' not in result
    assert not planning_tools.requirements_approved(messages, result)
    context = json.loads(call[0][1][-1]['content'])
    assert 'Structured values loaded by Python' in context['sourceMessages']['SOURCE_0']['content']
    assert 'Prefer 3 direct calf sets' in context['sourceMessages']['SOURCE_0']['content']
    assert result['structuredAuthority']['sha256']
    assert 'plan audit still pending' in result['requirementsPreview']


def test_real_exclusion_scope_question_remains_a_gate(monkeypatch):
    candidate, messages, saved = retained_case()
    finding = saved[1]
    finding.update(check='scope_ambiguity', implementationCheck=None)
    result, _ = reviewed(monkeypatch, candidate, messages, [finding])
    assert not result['passed']
    assert result['requirementsReviewQuestion']['kind'] == 'clarification'


def test_mixed_saved_findings_answer_only_the_code_owned_questions(monkeypatch):
    candidate, messages, saved = retained_case()
    for index in (0, 2):
        saved[index].update(check='authorization', implementationCheck=None)
    saved[1].update(check='scope_ambiguity', implementationCheck=None)
    saved[3].update(check='implementation', implementationCheck='regional_reporting')
    saved[4].update(check='implementation', implementationCheck='direct_coverage')
    result, _ = reviewed(monkeypatch, candidate, messages, saved)
    assert not result['passed']
    assert len(result['sourceReview']['codeAnsweredChecks']) == 4
    assert len(result['sourceReview']['findings']) == 1
    assert result['sourceReview']['findings'][0]['path'] == '/requirements/exerciseRestrictions'
    assert result['requirementsReviewQuestion']['kind'] == 'clarification'


def test_active_prose_conflict_is_not_silenced_by_an_exact_structured_match(monkeypatch):
    candidate, messages, saved = retained_case()
    messages.append({'role': 'user', 'content': 'Change the weekly schedule to four sessions.'})
    candidate['sourceMessages'] = planning_tools.requirement_sources(messages)
    source_id = len(candidate['sourceMessages']) - 1
    finding = {**saved[0], 'check': 'source_conflict', 'implementationCheck': None,
        'path': f'/sourceMessages/SOURCE_{source_id}',
        'evidencePaths': [f'/sourceMessages/SOURCE_{source_id}', '/requirements'],
        'basis': 'uncertainty', 'action': 'clarify'}
    result, _ = reviewed(monkeypatch, candidate, messages, [finding])
    assert not result['passed']
    assert result['requirementsReviewQuestion']['kind'] == 'clarification'


def test_direct_review_cannot_bless_a_forged_structured_value(monkeypatch):
    candidate, messages, _ = retained_case()
    candidate['requirements']['sessionsPerWeek'] = 4
    monkeypatch.setattr(plan_review, '_review_call', lambda *args, **kwargs: pytest.fail('No model call is needed'))
    with pytest.raises(planning_tools.PlanningInputError) as error:
        plan_review.review_requirements(None, candidate, messages)
    assert error.value.code == 'structured_requirement_mismatch'


def test_structured_receipt_cannot_relabel_assistant_content_as_user_authority(monkeypatch):
    candidate, messages, _ = retained_case()
    original = candidate['sourceMessages'][0]
    messages[original['messageIndex']]['role'] = 'assistant'
    monkeypatch.setattr(plan_review, '_review_call', lambda *args, **kwargs: pytest.fail('No model call is needed'))
    with pytest.raises(planning_tools.PlanningInputError) as error:
        plan_review.review_requirements(None, candidate, messages)
    assert error.value.code == 'structured_requirement_source_changed'


def test_structured_intake_and_review_schemas_support_strict_delivery():
    from workout_generator_pkg.api_client import _strict_parameters_compatible, _strict_wire_schema
    equipment, _, messages = intake_case()
    tool = planning_tools.workout_requirements_tool(equipment, messages)['function']['parameters']
    assert _strict_parameters_compatible(_strict_wire_schema(tool))
    schema = plan_review._strict_review_schema({'FACT_0': '/requirements'},
        plan_review._STRUCTURED_SOURCE_RESPONSE)
    assert _strict_parameters_compatible(schema)


def test_unchanged_source_checked_fields_do_not_reopen_during_an_amendment():
    context = {'structuredAuthority': {'matchedPaths': []}, 'reviewScope': {
        'baseSourceReviewPassed': True, 'changedPaths': ['/auditTargets/maximumSessionSeconds']}}
    answer = plan_review._code_answered_requirement_finding({
        'check': 'authorization', 'path': '/requirements/workingSetRIR'}, context)
    assert answer['check'] == 'unchanged_source_checked_field'
    assert plan_review._code_answered_requirement_finding({
        'check': 'authorization', 'path': '/requirements/auditTargets'}, context) is None


def test_additional_prose_requirement_can_still_request_a_scoped_correction(monkeypatch):
    candidate, messages, saved = retained_case()
    messages.append({'role': 'user', 'content': 'Choose and propose explicit exercise-frequency and weekly-set caps.'})
    candidate['sourceMessages'] = planning_tools.requirement_sources(messages)
    source_id = len(candidate['sourceMessages']) - 1
    finding = {**saved[0], 'check': 'source_omission', 'implementationCheck': None,
        'path': '/requirements/executionRules',
        'evidencePaths': [f'/sourceMessages/SOURCE_{source_id}', '/requirements/executionRules'],
        'message': 'The additional source request delegates an exposure-cap choice that has not been proposed.',
        'repair': 'Propose the delegated exerciseExposure rule while preserving the supplied rules.'}
    result, _ = reviewed(monkeypatch, candidate, messages, [finding])
    assert not result['passed']
    assert result['sourceReview']['findings']
    assert 'One scoped correction attempt' in result['instruction']
