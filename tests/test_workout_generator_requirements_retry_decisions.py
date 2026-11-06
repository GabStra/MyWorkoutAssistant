import copy
import json
from pathlib import Path

import pytest

from test_workout_generator_context_decisions import context_case
from test_workout_generator_conversation_sessions import make_shell_deps
from test_workout_generator_planning_decisions import store
from workout_generator_pkg import interactive_shell, plan_review, planning_tools
from workout_generator_pkg.conversation_store import load_active_conversation_record, save_conversation
from workout_generator_pkg.planning_decisions import confirmed_setup_access, propose_decisions
from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER


@pytest.mark.parametrize('supported', [True, False])
def test_source_review_retry_preserves_linked_proposal_and_rechecks_physical_claim(monkeypatch, tmp_path, supported):
    equipment, _, messages, decisions = context_case()
    decisions['decisions'] = decisions['decisions'][:1]
    requirements = json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    requirements.update(requiredCoverage=[], familySetBounds=[], objectiveOrder=['duration_balance'],
        exerciseRestrictions={'excludeNameTerms': [], 'exceptNameTerms': []},
        auditTargets={'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': None}},
            'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 5400},
        executionRules=[{'kind': 'supersetNoReconfiguration', 'coverageKey': None,
            'confirmedIndependentPairs': []}])
    requirements.pop('objectiveTiers', None)
    if not supported:
        messages[0]['content'] = 'I own this equipment; choose suitable supersets for me.'
    messages[0]['content'] += '\n' + STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)
    candidate = planning_tools.set_workout_requirements({}, messages, equipment)
    proposal = propose_decisions(decisions, messages, equipment)
    candidate.update(passed=False, proposedDecisions=proposal['decisions'], decisions={}, resolvedDecisions={},
        sourceReview={'passed': False, 'failure': 'Interrupted independent review.'},
        errors=[{'code': 'requirements_review_failed'}])
    original_arguments = {'planningDecisions': copy.deepcopy(decisions)}
    store(messages, 'set_workout_requirements', original_arguments, candidate, 'failed-candidate')
    messages.append({'role': 'user', 'content': '/continue'})
    store(messages, 'set_workout_requirements', {'updates': {}, 'planningDecisions': {'decisions': []}},
        {'passed': False, 'errors': [{'code': 'invalid_arguments'}]}, 'later-rejected-form')

    retry = interactive_shell._requirements_review_retry_arguments(messages, '/continue')
    assert retry == {'updates': {}, 'planningDecisions': original_arguments['planningDecisions']}
    assert 'factualContextLibraryFingerprint' not in json.dumps(retry)
    assert not confirmed_setup_access(messages, equipment, candidate['requirements'])['bindings']
    conversation_id = save_conversation(messages, script_dir=str(tmp_path), migrate=False)
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    calls = []

    def review(_client, request, **_options):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        assert request[0]['content'].startswith('Check the new or revalidated planning choices')
        assert context['newDecisionIds'] == ['DECISION_0']
        assert context['decisions']['DECISION_0']['confirmedSetupAccess'] == {
            'independentDefinitionIds': ['raise'], 'retainedResourceIds': ['bar', 'bench']}
        if supported:
            return '{"findings":[]}', None, None
        return json.dumps({'findings': [{
            'severity': 'blocking', 'basis': 'established_violation',
            'path': context['decisions']['DECISION_0']['_reviewRef'],
            'message': 'Equipment possession does not establish independent floor access.',
            'evidencePaths': [context['sourceMessages']['SOURCE_0']['_reviewRef']],
            'repair': 'Obtain an explicit statement of independent floor access.'}]}), None, None

    monkeypatch.setattr(plan_review, '_review_call', review)
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    planning_calls = []

    def plan_after_confirmation(_client, _request, *_args, **_options):
        saved = load_active_conversation_record(str(tmp_path))['messages']
        assert supported, 'Unsupported physical claims must stop before planning.'
        assert planning_tools.requirements_approved(saved)
        bound = confirmed_setup_access(saved, equipment, candidate['requirements'])
        assert bound['requirements']['executionRules'][0]['confirmedIndependentPairs'] == [['press', 'raise']]
        planning_calls.append(bound)
        return 'Reviewed setup facts are available for exercise selection.', None, None

    deps.chat_call_with_loading = plan_after_confirmation
    inputs = iter(['/resume-conversation ' + conversation_id, '/continue']
        + (['CONFIRM REQUIREMENTS'] if supported else []) + ['/exit'])
    monkeypatch.setattr('builtins.input', lambda _prompt='': next(inputs))
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    interactive_shell.main(deps=deps)

    messages = load_active_conversation_record(str(tmp_path))['messages']
    retry_call = next(call for message in messages for call in message.get('tool_calls', [])
        if call['id'].startswith('requirements_review_'))
    assert json.loads(retry_call['function']['arguments']) == retry
    result = json.loads(next(message['content'] for message in messages
        if message.get('tool_call_id') == retry_call['id']))
    assert len(calls) == 1
    assert len(planning_calls) == int(supported)
    assert result['requirements'] == candidate['requirements']
    assert result['sourceReview']['codeAnsweredChecks'][0]['check'] == 'complete_structured_requirements'
    assert result['passed'] is supported
    assert result['jointDecisionReview']['passed'] is supported
    bound = confirmed_setup_access(messages, equipment, result['requirements'])
    if supported:
        assert len(result['decisions']) == 1
        assert bound['requirements']['executionRules'][0]['confirmedIndependentPairs'] == [['press', 'raise']]
    else:
        assert result['decisions'] == result['resolvedDecisions'] == {}
        assert result['proposedDecisions']
        assert result['requirementsReviewQuestion']
        assert 'requirementsPreview' not in result
        assert not bound['bindings']
        assert not planning_tools.requirements_approved(messages)
