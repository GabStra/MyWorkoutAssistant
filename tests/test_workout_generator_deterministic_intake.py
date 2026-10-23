import copy
import json

from workout_generator_pkg import interactive_shell as shell, recipe_contracts
from workout_generator_pkg.planning_tools import set_workout_requirements
from test_workout_generator_planning_tools import planning_case


def test_source_review_concern_waits_for_user_without_losing_findings(monkeypatch):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Keep these targets.'}]
    concern = {'code': 'requirements_source_finding', 'message': 'Two source instructions conflict.',
               'repair': 'Clarify the intended scope.'}
    question = {'kind': 'clarification', 'question': 'Which scope do you intend?', 'options': []}

    def reviewed(_client, candidate, *_args, **_kwargs):
        return {**candidate, 'passed': False, 'errors': [concern],
                'requirementsReviewQuestion': question}

    monkeypatch.setattr(shell, 'review_requirements', reviewed)
    outcome = shell.handle_function_call(None, messages, 'set_workout_requirements', arguments, equipment)
    payload = json.loads(outcome['result'])
    assert outcome['waiting_for_user'] and not outcome['should_exit']
    assert payload['userQuestion'] == question and payload['errors'] == [concern]
    assert outcome['requirements_review_findings'] == [concern]
    assert payload['requirements']['auditTargets'] == arguments['auditTargets']


def test_recipe_qualification_preserves_original_sources_without_accounting():
    equipment, requirements, _, _ = planning_case()
    requirements.pop('requirementAccounting', None)
    sources = {'SOURCE_0': {'role': 'user', 'content': 'Prioritize stable exercises.'},
               'SOURCE_1': {'role': 'user', 'content': 'Keep posterior-chain roles distinct.'}}
    prepared = {'sourceMessages': copy.deepcopy(sources), 'candidates': {'LIBRARY_0': {'name': 'Exercise'}}}
    context = recipe_contracts._recipe_context(prepared, requirements, 'LIBRARY_0',
        equipment['exerciseDefinitions'][0], {}, {})
    assert context['sourceMessages'] == sources and not context['semanticRequirements']
    context['sourceMessages']['SOURCE_0']['content'] = 'Changed projection'
    assert prepared['sourceMessages'] == sources


def test_unapproved_candidate_state_exposes_same_sparse_update_base_as_tool():
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Keep these targets.'}]
    candidate = set_workout_requirements(arguments, messages, equipment)
    candidate.update(passed=False, sourceReview={'passed': False, 'findings': []})
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'type': 'function',
            'function': {'name': 'set_workout_requirements', 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(candidate)},
        {'role': 'user', 'content': 'Change only the session duration.'}])
    outgoing = shell._messages_for_api(messages, True, provided_equipment=equipment)
    content = next(message['content'] for message in outgoing
                   if message.get('content', '').startswith('Current planning state'))
    state = json.loads(content.split('\n', 1)[1])
    assert state['requirementsUpdateBase']['requirementsId'] == candidate['requirementsId']
    assert state['requirementsUpdateBase']['requirements'] == candidate['requirements']
    assert not state['requirementsApproved']
    assert 'accountingRefreshBase' not in state
