import copy
import json
from types import SimpleNamespace

import pytest

from workout_generator_pkg import conflict_resolution, interactive_shell, plan_review, planning_tools
from test_workout_generator_planning_tools import planning_case


@pytest.mark.parametrize('disposition', ['repair', 'unresolved_capability'])
def test_diagnosis_continues_only_supported_alternative_repairs(monkeypatch, disposition):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(planning_tools, 'require_approved_requirements', lambda *_: None)
    monkeypatch.setattr(interactive_shell, 'require_approved_requirements', lambda *_: None)
    monkeypatch.setattr(interactive_shell, '_latest_result', lambda *_: (0, stored))
    monkeypatch.setattr(planning_tools, 'latest_draft_submission', lambda *_: (copy.deepcopy(draft), 'SOURCE'))
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *_: 'Unapproved alternative')
    review = {'version': plan_review.REVIEW_VERSION,
        'findings': [{'severity': 'warning', 'message': 'Repair the setup cue.'}],
        'assessment': {'groups': [{'findingIndexes': [0], 'disposition': disposition,
            'repairDimensions': ['guidance'] if disposition == 'repair' else []}]}}
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda *_: {
        'passed': False, 'review': review, 'errors': [{'code': 'independent_review_finding'}]})

    def diagnose(**kwargs):
        kwargs['review_candidate'](copy.deepcopy(draft['workouts']), stored['requirements'],
            {'audit': {'errors': []}})
        return {'outcome': 'unresolved', 'reason': 'No reviewed proposal yet.',
            'diagnosisDeadlineUTC': '2099-01-01T00:00:00Z'}

    monkeypatch.setattr(conflict_resolution, 'diagnose_conflict_and_propose', diagnose)
    response = interactive_shell.handle_function_call(None, [], 'propose_workout_alternatives',
        {'requirementsId': stored['requirementsId'], 'baseDraftId': 'SOURCE'},
        provided_equipment=equipment, deps=SimpleNamespace(execute_workout_generation=None))
    result = json.loads(response['result'])
    assert result['passed'] is False
    assert len(result['alternativeRepairCandidates']) == 1
    assert result['jointPlanningStopped'] is (disposition != 'repair')
    if disposition == 'repair':
        assert 'coordinated repair' in result['instruction']
        assert result['errors'] == [{'code': 'independent_review_finding'}]
    assert not result.get('proposals')
