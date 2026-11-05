import copy
import json

from workout_generator_pkg import alternative_repair, conflict_resolution, interactive_shell


def test_refresh_native_reviews_latest_exact_artifact_without_version_or_receipt_lineage(monkeypatch):
    original = {'repairCandidateId': 'CANDIDATE', 'requirementsId': 'REQ_ALT',
        'originalRequirementsId': 'REQ', 'workouts': [{'name': 'Original'}]}
    revised = {**original, 'workouts': [{'name': 'Latest saved artifact'}]}
    diagnosis = {'diagnosisVersion': -1, 'alternativeRepairCandidates': [original]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'old',
            'function': {'name': 'propose_workout_alternatives'}}]},
        {'role': 'tool', 'tool_call_id': 'old', 'content': json.dumps(diagnosis)},
        {'role': 'assistant', 'tool_calls': [{'id': 'latest',
            'function': {'name': 'repair_workout_alternative'}}]},
        {'role': 'tool', 'tool_call_id': 'latest', 'content': json.dumps({'candidateSnapshot': revised})},
    ]
    before = copy.deepcopy(messages)
    calls = []
    monkeypatch.setattr(conflict_resolution, 'latest_candidate_diagnosis', lambda *_: (1, diagnosis))
    def native_refresh(candidate, *_args):
        calls.append(copy.deepcopy(candidate))
        return {'status': 'refreshed', 'candidate': candidate}
    monkeypatch.setattr(alternative_repair, 'refresh_candidate_assessment', native_refresh)

    response = interactive_shell.handle_function_call(None, messages, 'propose_workout_alternatives', {
        'requirementsId': 'REQ', 'baseDraftId': 'DRAFT', 'repairCandidateId': 'CANDIDATE',
        'staleAlternativeAssessment': True}, provided_equipment={})

    result = json.loads(response['result'])
    assert calls == [revised]
    assert messages == before
    assert result['alternativeRepairCandidates'][0]['workouts'] == revised['workouts']
    assert result['passed'] is False
