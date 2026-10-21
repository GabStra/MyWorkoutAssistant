import json

import pytest

from workout_generator_pkg import plan_review, review_assessment as assessment
from workout_generator_pkg.repair_capabilities import repair_capability_contract, repair_field_dimensions


def _review(findings, groups, repair_plan=''):
    review = {'inputHash': 'candidate-review', 'findings': findings}
    review['assessment'] = {
        'version': assessment.VERSION,
        'inputHash': assessment.assessment_hash(review),
        'groups': groups,
        'repairPlan': repair_plan,
    }
    return review


def _finding(action, severity='warning', message='Finding'):
    return {'action': action, 'severity': severity, 'message': message}


def test_plan_review_requires_typed_advisory_action_and_program_guidance_owner():
    schema = plan_review._PLAN_FINDING
    assert schema['properties']['action']['enum'] == ['repair', 'clarify', 'advisory']
    assert 'action' in schema['required']
    contract = repair_capability_contract()
    assert repair_field_dimensions('programGuidance') == {'program_guidance'}
    assert 'program_guidance' in contract['editableDimensions']


def test_program_guidance_is_in_review_facts_and_maps_to_its_typed_repair_path():
    submitted = {'programGuidance': 'Use the rest day after the hardest session.', 'workouts': []}
    compact = plan_review._compact_review_draft({'exercises': [], 'workouts': []},
        {'exerciseDefinitions': []}, submitted)

    assert compact['programGuidance'] == submitted['programGuidance']
    assert plan_review._draft_patch_path('/draft/programGuidance', {'workouts': []}, submitted) == '/programGuidance'


def test_blocking_finding_cannot_be_advisory_even_after_schema_correction(monkeypatch):
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'advisory',
        'path': 'FACT_0', 'message': 'A concrete contradiction.', 'evidencePaths': ['FACT_0'],
        'repair': 'Correct the contradiction.', 'muscleTargets': []}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *_args, **_kwargs: (json.dumps({'patches': [[
        {'op': 'replace', 'path': '/action', 'value': 'repair'}]]}), None, None))

    accepted = plan_review._validated_findings(None, [], json.dumps({'findings': [finding]}),
        lambda item: item, None, 'test', schema=plan_review._PLAN_RESPONSE,
        finding_schema=plan_review._PLAN_FINDING)

    assert accepted[0]['severity'] == 'blocking'
    assert accepted[0]['action'] == 'repair'


def test_advisory_calibration_finding_stays_separate_from_label_repair(monkeypatch):
    findings = [
        _finding('advisory', message='No compatible load history; app-native calibration handles the unknown load.'),
        _finding('repair', message='The session label does not match its focus.'),
    ]
    review = {'inputHash': 'candidate-review', 'findings': findings}
    calls = []

    def respond(_client, request, **_options):
        calls.append(json.loads(request[-1]['content']))
        return json.dumps({'groups': [
            {'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
             'reason': 'Calibration mode handles the missing history; no extra sets are needed.',
             'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []},
            {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['session_labels'],
             'reason': 'Correct only the inaccurate focus label.',
             'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
            'repairPlan': 'Correct the session label only.'}), None, None

    monkeypatch.setattr(assessment, '_review_call', respond)
    result = assessment.assess_findings(None, {'draft': {'programGuidance': ''}}, review)

    assert [group['disposition'] for group in result['groups']] == ['advisory', 'repair']
    assert result['groups'][1]['repairDimensions'] == ['session_labels']
    assert len(calls) == 1


@pytest.mark.parametrize('disposition', ['repair', 'unresolved_capability'])
def test_assessment_cannot_promote_or_mix_advisory_finding(disposition):
    advisory = _finding('advisory')
    with pytest.raises(ValueError, match='cannot be promoted'):
        assessment.validate_assessment(_review([advisory], [{
            'findingIndexes': [0], 'disposition': disposition,
            'repairDimensions': ['guidance'] if disposition == 'repair' else [], 'reason': 'Escalate it.'
        }], 'Repair it.' if disposition == 'repair' else ''))

    mixed = [advisory, _finding('repair', message='A real correction.')]
    with pytest.raises(ValueError, match='Split advisory findings'):
        assessment.validate_assessment(_review(mixed, [{
            'findingIndexes': [0, 1], 'disposition': 'repair',
            'repairDimensions': ['session_labels'], 'reason': 'Group both.'
        }], 'Repair both.'))


def test_carried_advisory_resolution_cannot_become_repair():
    prior = _finding('advisory')
    with pytest.raises(ValueError, match='cannot be promoted'):
        plan_review._validate_carried_resolution({'status': 'open', 'action': 'repair'}, prior)
    plan_review._validate_carried_resolution({'status': 'open', 'action': 'advisory'}, prior)
    plan_review._validate_carried_resolution({'status': 'resolved_by_change', 'action': 'none'}, prior)
    with pytest.raises(ValueError, match='cannot be promoted'):
        plan_review._validate_confirmation_resolution({
            'status': 'open', 'disposition': 'repair', 'repairDimensions': ['guidance'],
            'reason': 'Escalate the carried advisory.', 'evidencePaths': ['/draft']}, prior)
