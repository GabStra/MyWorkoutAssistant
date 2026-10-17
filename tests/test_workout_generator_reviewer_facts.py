import json
import pytest

from workout_generator_pkg import plan_review
from workout_generator_pkg.interactive_shell import handle_function_call
from workout_generator_pkg.planning_decisions import resolved_decisions, saved_decisions
from workout_generator_pkg.planning_tools import requirements_approved, requirement_sources, set_workout_requirements
from test_workout_generator_planning_tools import planning_case, requirement_messages


@pytest.mark.parametrize('malformed', ['bad item', None, []])
def test_finding_repair_accepts_non_object_entries_and_keeps_valid_blockers(monkeypatch, malformed):
    blocker = {'severity': 'blocking', 'path': '/draft/exercises/0',
        'message': 'The exercise conflicts with the requested plan.',
        'evidencePaths': ['/sourceMessages/SOURCE_0'], 'repair': 'Replace the exercise.'}
    repaired = {'severity': 'warning', 'path': '/draft/exercises/1',
        'message': 'The exercise could use more detail.',
        'evidencePaths': ['/sourceMessages/SOURCE_0'], 'repair': 'Add the missing detail.'}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [repaired]}), None, None))

    findings = plan_review._validated_findings(None, [], json.dumps({'findings': [blocker, malformed]}),
        lambda finding: finding, None, 'test')

    assert findings == [blocker, repaired]


@pytest.mark.parametrize('field', ['message', 'repair', 'basis'])
def test_reference_repair_cannot_rewrite_other_valid_finding_fields(monkeypatch, field):
    blocker = {'severity': 'blocking', 'path': '/draft', 'basis': 'established_violation',
        'message': 'A confirmed requirement is violated.', 'evidencePaths': ['/source'], 'repair': 'Restore the requirement.'}
    invalid = {**blocker, 'path': '/invalid'}
    corrected = {**invalid, 'path': '/draft', field: 'Different finding.' if field != 'basis' else 'uncertainty'}
    calls = []
    def respond(client, request, **kwargs):
        calls.append(1)
        permissions = json.loads(request[-1]['content'])['invalidFindings'][0]['permittedPaths']
        assert '/path' in permissions['exact'] and '/message' not in permissions['exact']
        return json.dumps({'findings': [corrected]}), None, None
    def normalize(finding):
        if finding['path'] == '/invalid':
            raise ValueError('Invalid reference.')
        return finding
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    with pytest.raises(plan_review.ReviewOutputError) as error:
        plan_review._validated_findings(None, [], json.dumps({'findings': [blocker, invalid]}), normalize, None, 'test')
    assert error.value.findings == [blocker] and calls == [1]


def test_fixing_a_finding_schema_error_does_not_authorize_retargeting_it(monkeypatch):
    original = {'severity': 'blocking', 'path': '/draft/exercises/0', 'message': '',
        'evidencePaths': ['/source'], 'repair': 'Restore the requirement.'}
    repaired = {**original, 'message': 'The requirement is violated.', 'path': '/draft/exercises/1'}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [repaired]}), None, None))
    with pytest.raises(plan_review.ReviewOutputError, match='outside allowed error scope'):
        plan_review._validated_findings(None, [], json.dumps({'findings': [original]}), lambda f: f, None, 'test')


def _without_refs(value):
    if isinstance(value, dict):
        return {key: _without_refs(child) for key, child in value.items() if key != '_reviewRef'}
    if isinstance(value, list):
        return [_without_refs(child) for child in value]
    return value


def test_independent_review_maps_fact_refs_to_exact_draft_paths(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)

    def respond(client, request, **options):
        context = json.loads(request[-1]['content'])
        assert context['draft']['exercises'][0]['_reviewRef'].startswith('FACT_')
        assert '_reviewRef' not in draft['workouts'][0]['exercises'][0]
        finding = {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': [],
            'path': context['draft']['exercises'][0]['_reviewRef'],
            'message': 'The exercise conflicts with a stated execution requirement.',
            'evidencePaths': [context['sourceMessages']['SOURCE_0']['_reviewRef']],
            'repair': 'Use an exercise that satisfies the stated execution requirement.'}
        return json.dumps({'findings': [finding]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert result['errors'][0].get('draftPath') == '/workouts/0/exercises/0', result['errors']
    assert result['review']['findings'][0]['path'] == '/draft/exercises/0'
    assert result['review']['findings'][0]['evidencePaths'] == ['/sourceMessages/SOURCE_0']


def test_joint_requirements_and_decision_review_approves_and_saves_once(monkeypatch):
    equipment, requirements, stored, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Set up the requested workout targets.'},
        {'role': 'user', 'content': 'For balance accounting, count each working set once.'}]
    candidate = set_workout_requirements(requirements, messages, equipment)
    decision_proposal = {'decisions': [{'topic': 'Balance accounting',
        'choice': 'Count each working set once for movement balance.', 'sourceReferences': ['SOURCE_1']}]}
    calls = []

    def approve(client, request, **options):
        calls.append(request)
        context = json.loads(request[-1]['content'])
        assert _without_refs(context['requirements']) == plan_review._extracted_context(candidate)
        assert context['newDecisionIds'] == ['DECISION_0']
        assert context['decisions']['DECISION_0']['choice'] == decision_proposal['decisions'][0]['choice']
        assert context['sourceMessages']['SOURCE_1']['_reviewRef'].startswith('FACT_')
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, 'chat_call', approve)
    result = plan_review.review_requirements(None, candidate, messages, planning_decisions=decision_proposal)
    assert result['passed'] and result['jointDecisionReview']['passed'], result.get('errors') or result.get('sourceReview')
    assert result['sourceReview']['inputHash'] == plan_review._hash(plan_review._requirements_context(result))
    assert 'User-authorized planning choices:' in result['requirementsPreview']
    assert len(calls) == 1

    call_id = 'requirements-joint'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(result)},
        {'role': 'assistant', 'content': result['requirementsPreview'],
         'canonicalRequirementsPreview': result['requirementsId']},
        {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'},
    ])
    assert saved_decisions(messages) == result['decisions']
    assert requirements_approved(messages, result)
    repeated_candidate = set_workout_requirements(requirements, messages, equipment)
    repeated = plan_review.review_requirements(None, repeated_candidate, messages, planning_decisions=decision_proposal)
    assert repeated['passed'] and repeated['sourceReview']['inputHash'] == result['sourceReview']['inputHash']
    assert len(calls) == 1


def test_joint_review_does_not_save_decisions_when_any_finding_blocks(monkeypatch):
    equipment, requirements, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Set up the requested workout targets.'},
        {'role': 'user', 'content': 'I delegate the balance convention to the planner.'}]
    candidate = set_workout_requirements(requirements, messages, equipment)
    proposal = {'decisions': [{'topic': 'Balance accounting',
        'choice': 'Count each working set once for movement balance.', 'sourceReferences': ['SOURCE_1']}]}

    def reject(client, request, **options):
        context = json.loads(request[-1]['content'])
        return json.dumps({'findings': [{'severity': 'blocking',
            'path': context['decisions']['DECISION_0']['_reviewRef'],
            'message': 'The decision overstates what the audit can verify.',
            'evidencePaths': [context['sourceMessages']['SOURCE_1']['_reviewRef']],
            'repair': 'Clarify the supported counting convention.'}]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', reject)
    result = plan_review.review_requirements(None, candidate, messages, planning_decisions=proposal)
    assert not result['passed'] and not result['jointDecisionReview']['passed']
    assert result['resolvedDecisions'] == {}
    assert saved_decisions(messages) == {}


def test_joint_choice_replacement_keeps_only_the_new_choice_active(monkeypatch):
    equipment, requirements, stored, _ = planning_case()
    messages = requirement_messages(stored) + [{'role': 'user', 'content': 'Count overlapping credits separately.'}]
    first = {'decisions': [{'topic': 'Balance accounting', 'choice': 'Count each set once.',
        'sourceReferences': ['SOURCE_1']}]}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    first_result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', first, equipment)['result'])
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'choice0', 'function': {'name': 'record_planning_decisions'}}]},
        {'role': 'tool', 'tool_call_id': 'choice0', 'content': json.dumps(first_result)},
        {'role': 'user', 'content': 'Change that choice: count each overlapping muscle credit separately.'},
    ])
    candidate = dict(stored, sourceMessages=requirement_sources(messages),
        resolvedDecisions=resolved_decisions(messages))
    replacement = {'decisions': [{'topic': 'Balance accounting', 'choice': 'Count each overlapping muscle credit separately.',
        'sourceReferences': ['SOURCE_2'], 'supersedes': 'DECISION_0', 'reason': 'The user explicitly changed the choice.'}]}
    result = plan_review.review_requirements(None, candidate, messages, planning_decisions=replacement)
    assert result['passed'] and result['decisions']['DECISION_0']['supersededBy'] == 'DECISION_1'
    assert list(result['resolvedDecisions']) == ['DECISION_1']
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements-joint', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements-joint', 'content': json.dumps(result)},
    ])
    assert list(resolved_decisions(messages)) == ['DECISION_1']
