import copy
import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.api_client import StructuredResponseError
from test_workout_generator_single_review import request_data, response_for, setup_case


@pytest.mark.parametrize('field,malformed', [
    ('reason', 'setup_changeover_time_uncertain'),
    ('message', 'equipment_setups'),
    ('subjectRefs', ['EXERCISE_0', 'UNKNOWN_SUBJECT']),
    ('evidenceRefs', ['UNKNOWN_REFERENCE']),
    ('decisionId', 'UNKNOWN_DECISION'),
])
def test_form_correction_reuses_valid_review_and_carried_concern(monkeypatch, field, malformed):
    _, messages, audited, context = setup_case()
    context['reviewChecklist'] = {'findings': {'CONCERN_TIMING': {
        'finding': {'message': 'Prior setup objection.',
            'reviewJudgment': 'recovery_uncertainty', 'basis': 'material_uncertainty',
            'action': 'clarify', 'severity': 'blocking', 'concernGroupId': 'CONCERN_TIMING'},
        'changedDraftPaths': [], 'sourceCount': 1}}}
    snapshots = copy.deepcopy(context)
    calls = []
    invalid = False
    original = None

    def respond(_client, request, **options):
        nonlocal original
        assert options['retry'] is False
        calls.append(request)
        schema = options['output_schema']
        if 'findingCorrections' in schema['properties']:
            payload = json.loads(request[-1]['content'])
            if field == 'evidenceRefs':
                assert request[:len(calls[-2])] == calls[-2]
                assert request_data(request)['sourceMessages']
            else:
                assert len(request) == 2
                assert set(payload['rejectedFindings']) == {'FINDING_0'}
                assert payload['rejectedResolutions'] == {}
                assert all(key not in payload for key in (
                    'finalArtifact', 'draft', 'history', 'sourceMessages', 'requirements', 'rejectedResponse'))
                assert len(json.dumps(request)) < len(json.dumps(calls[-2]))
            entries = schema['properties']['findingCorrections']['properties']
            assert set(schema['properties']) == {'findingCorrections'}
            assert set(entries) == {'FINDING_0'}
            assert set(entries['FINDING_0']['properties']) == {field}
            replacement = original['findings'][0][field]
            return json.dumps({'findingCorrections': {'FINDING_0': {field: replacement}}}), None, None
        data = request_data(request)
        plan_ref = data['finalArtifact']['_reviewRef']
        findings = [{'message': 'equipment_setup', 'reason': 'setup_changeover_time_uncertainty',
            'qualitativeRationale': 'Actual transition time is unmeasured.',
            'subjectRefs': ['EXERCISE_0'], 'evidenceRefs': [plan_ref],
            'basis': 'uncertainty', 'disposition': 'advisory', 'concernGroup': 'NEW', 'decisionId': 'none'},
            {'message': 'fatigue_recovery', 'reason': 'recovery_uncertainty',
            'qualitativeRationale': 'Personal recovery is unmeasured.',
            'subjectRefs': ['EXERCISE_0'], 'evidenceRefs': [plan_ref],
            'basis': 'uncertainty', 'disposition': 'advisory', 'concernGroup': 'ISSUE_0', 'decisionId': 'none'}]
        original = response_for(data, schema, findings)
        original['blockerResolutions']['ISSUE_0'] = {
            'reason': 'recovery_uncertainty', 'evidenceRefs': [plan_ref]}
        payload = copy.deepcopy(original)
        if invalid:
            payload['findings'][0][field] = (
                [*payload['findings'][0][field], *malformed] if field == 'evidenceRefs' else malformed)
            raise StructuredResponseError(json.dumps(payload), ValidationError('Malformed selector'))
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, 'chat_call', respond)
    boundary = len(messages) - 1
    baseline = review._review_complete_draft(None, context, audited, messages, boundary, None)
    assert len(calls) == 1
    invalid = True
    corrected = review._review_complete_draft(None, context, audited, messages, boundary, None)
    assert len(calls) == 3
    assert corrected == baseline
    assert context == snapshots
    assert corrected['reviewedArtifact'] == context['finalArtifact']
    resolution = corrected['scopeResults']['execution']['blockerResolutions']['CONCERN_TIMING']
    assert resolution['status'] == 'withdrawn_review_error'


@pytest.mark.parametrize('missing', ['qualitativeRationale', 'evidenceRefs'])
def test_missing_semantic_support_keeps_reviewer_context(monkeypatch, missing):
    _, messages, audited, context = setup_case()
    calls = []

    def respond(_client, request, **options):
        calls.append(request)
        if len(calls) == 2:
            assert request[:len(calls[0])] == calls[0]
            assert request_data(request)['sourceMessages']
            value = ('Actual transition time is unmeasured.' if missing == 'qualitativeRationale'
                else [request_data(request)['finalArtifact']['_reviewRef']])
            return json.dumps({'findingCorrections': {'FINDING_0': {missing: value}}}), None, None
        data = request_data(request)
        payload = response_for(data, options['output_schema'], [{
            'message': 'equipment_setup', 'reason': 'setup_changeover_time_uncertainty',
            'qualitativeRationale': 'Actual transition time is unmeasured.', 'subjectRefs': ['EXERCISE_0'],
            'evidenceRefs': [data['finalArtifact']['_reviewRef']], 'basis': 'uncertainty',
            'disposition': 'advisory', 'concernGroup': 'NEW', 'decisionId': 'none'}])
        payload['findings'][0][missing] = '' if missing == 'qualitativeRationale' else ['UNKNOWN_REFERENCE']
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, 'chat_call', respond)
    result = review._review_complete_draft(None, context, audited, messages, len(messages) - 1, None)
    assert len(calls) == 2
    assert result['findings'][0]['qualitativeRationale'] == 'Actual transition time is unmeasured.'


@pytest.mark.parametrize('supported', [True, False])
def test_reference_correction_requires_actual_withdrawal_authority(monkeypatch, supported):
    _, messages, audited, context = setup_case()
    calls = []

    def respond(_client, request, **options):
        calls.append(request)
        if len(calls) == 2:
            assert request[:len(calls[0])] == calls[0]
            data = request_data(request)
            references = ['FINAL_ARTIFACT']
            if supported:
                references.append(data['sourceMessages']['SOURCE_0']['_reviewRef'])
            fields = options['output_schema']['properties']['findingCorrections']['properties'][
                'FINDING_0']['properties']
            assert set(fields) == {'evidenceRefs'}
            return json.dumps({'findingCorrections': {'FINDING_0': {
                'evidenceRefs': references}}}), None, None
        data = request_data(request)
        payload = response_for(data, options['output_schema'], [{
            'message': 'review_error', 'errorKind': 'unsupported_requirement',
            'qualitativeRationale': 'The prior objection was unsupported.', 'subjectRefs': ['EXERCISE_0'],
            'evidenceRefs': [data['finalArtifact']['_reviewRef'], 'UNKNOWN_AUTHORITY'],
            'basis': 'uncertainty', 'disposition': 'withdrawn_review_error',
            'concernGroup': 'NEW', 'decisionId': 'none'}])
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, 'chat_call', respond)
    if supported:
        result = review._review_complete_draft(None, context, audited, messages, len(messages) - 1, None)
        assert result['assessment']['groups'][0]['disposition'] == 'withdrawn_review_error'
    else:
        with pytest.raises(ValueError, match='authoritative policy/source'):
            review._review_complete_draft(None, context, audited, messages, len(messages) - 1, None)
    assert len(calls) == 2


def test_resolution_choice_correction_keeps_valid_carried_evidence():
    original = {'findings': [], 'blockerResolutions': {'ISSUE_0': {
        'reason': 'source_conflicts', 'evidenceRefs': ['SOURCE_0', 'FINAL_ARTIFACT']}}}
    output_schema = {'properties': {'blockerResolutions': {'properties': {'ISSUE_0': {
        'properties': {'reason': {'type': 'string', 'enum': ['source_conflict']},
            'evidenceRefs': {'type': 'array', 'items': {'type': 'string',
                'enum': ['SOURCE_0', 'FINAL_ARTIFACT']}}}}}}}}
    schema = review._review_correction_schema(original, output_schema, {}, {}, [], choice_only=True)
    fields = schema['properties']['blockerResolutions']['properties']['ISSUE_0']['properties']
    assert set(fields) == {'reason'}
    merged = review._merge_review_correction(original, {
        'blockerResolutions': {'ISSUE_0': {'reason': 'source_conflict'}}}, schema)
    assert merged == {'findings': [], 'blockerResolutions': {'ISSUE_0': {
        'reason': 'source_conflict', 'evidenceRefs': ['SOURCE_0', 'FINAL_ARTIFACT']}}}
    assert original['blockerResolutions']['ISSUE_0']['reason'] == 'source_conflicts'
