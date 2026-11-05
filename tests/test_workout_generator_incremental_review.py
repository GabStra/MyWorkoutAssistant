import copy
import json

import pytest

from workout_generator_pkg import plan_review, interactive_shell, review_assessment
from workout_generator_pkg.planner_context import request_planning_state, planner_response_profile
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def store(messages, result):
    key = f'audit_{len(messages)}'
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
                     {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def test_review_context_pool_identity_is_stable_and_citations_cannot_redirect():
    history = {'LIBRARY_0': {'sessions': [{'performances': [{'equipmentContextRef': 'CONTEXT_0'}]}]}}
    contexts = {'CONTEXT_0': {'name': 'Barbell', 'type': 'BARBELL'}}
    before = copy.deepcopy(history)
    first = plan_review._stable_review_contexts(history, contexts)
    renamed = copy.deepcopy(history)
    renamed['LIBRARY_0']['sessions'][0]['performances'][0]['equipmentContextRef'] = 'CONTEXT_9'
    second = plan_review._stable_review_contexts(renamed, {'CONTEXT_9': contexts['CONTEXT_0']})
    assert first == second and history == before
    altered = plan_review._stable_review_contexts(history, {'CONTEXT_0': {'name': 'Dumbbells'}})
    assert altered != first


def test_followup_uses_low_effort_patch_work_order(monkeypatch):
    from test_workout_generator_single_review import setup_case, request_data, response_for
    equipment, messages, audited, _ = setup_case()
    monkeypatch.setattr(plan_review, '_review_call', lambda client, request, **options: (
        json.dumps(response_for(request_data(request), options['output_schema'])), None, None))
    first = plan_review.review_draft(None, audited, messages, equipment)
    store(messages, first)
    messages.append({'role': 'assistant', 'canonicalDraftPreview': first['draftId'], 'content': first['preview']})
    messages.append({'role': 'user', 'content': 'Change only the session label.'})
    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['editTask']['baseDraftId'] == state['currentDraftId']
    assert 'constructionTask' not in state and 'repairTask' not in state
    assert planner_response_profile(state) == {'reasoning_effort': None, 'activity': 'Editing workout',
                                             'max_tokens': 16384, 'timeout': None}


def test_new_instruction_can_update_requirements_before_construction():
    from workout_generator_pkg.planner_context import construction_tool_failure
    state = {'newInstructionPending': True, 'constructionTask': {'stage': 'choose_movements', 'remainingWeeklySessions': 3}}
    assert construction_tool_failure('set_workout_requirements', {}, state) is None
    assert construction_tool_failure('record_planning_decisions', {}, state) is None
