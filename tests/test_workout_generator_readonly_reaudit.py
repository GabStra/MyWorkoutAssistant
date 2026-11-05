import copy
import json

import pytest

from workout_generator_pkg import interactive_shell
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, capability_requirement_messages


STATE = {'requirementsApproved': True, 'requirementsId': 'REQUIREMENTS_e0504c52ed5f5505',
         'currentDraftId': 'REVISION_2'}
READ = {'requirementsId': STATE['requirementsId'], 'baseDraftId': STATE['currentDraftId'], 'useSolverMenu': False}


@pytest.mark.parametrize('change', [
    {'useSolverMenu': True}, {'useSolverMenu': 0}, {'edits': {}}, {'patch': []},
    {'workouts': []}, {'name': 'changed'}, {'extra': None},
    {'requirementsId': 'OTHER'}, {'baseDraftId': 'REVISION_1'},
])
def test_only_current_base_only_reads_bypass_edit_admission(change):
    assert interactive_shell._is_saved_draft_revalidation(READ, STATE)
    assert not interactive_shell._is_saved_draft_revalidation({**READ, **change}, STATE)
    assert not interactive_shell._is_saved_draft_revalidation(READ, {**STATE, 'requirementsApproved': False})


def test_base_only_reaudit_reaches_native_audit_and_review_without_repair_or_solver(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = capability_requirement_messages(stored, equipment)
    initial = audit_workout_plan(draft, equipment, messages)
    assert initial['passed'], initial
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'initial', 'function': {
            'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'initial', 'content': json.dumps(initial)},
        {'role': 'user', 'content': 'Re-audit the unchanged saved plan under current code; no new physical confirmation.'},
    ])
    original = copy.deepcopy(messages)
    reviewed = []
    def review(client, result, *args, **kwargs):
        reviewed.append(copy.deepcopy(result))
        return result
    monkeypatch.setattr(interactive_shell, 'review_draft', review)
    monkeypatch.setattr(interactive_shell, 'auto_allocate_workout', lambda *a, **k: pytest.fail(
        'A read-only revalidation must not select a new prescription.'))
    args = {'requirementsId': stored['requirementsId'], 'baseDraftId': initial['currentDraftId'], 'useSolverMenu': False}

    outcome = interactive_shell.handle_function_call(None, messages, 'audit_workout_plan', args,
                                                       provided_equipment=equipment)

    result = json.loads(outcome['result'])
    assert len(reviewed) == 1
    assert result['submittedDraft'] == initial['submittedDraft']
    assert result['currentDraftId'] == initial['currentDraftId']
    assert result['audit']['weeklyWorkingSets'] == initial['audit']['weeklyWorkingSets']
    assert messages == original
    assert args['useSolverMenu'] is False and 'patch' not in args
