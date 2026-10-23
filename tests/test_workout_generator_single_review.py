import json

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def setup_case():
    equipment, _, requirements, draft = planning_case()
    messages = requirement_messages(requirements)
    audited = audit_workout_plan(draft, equipment, messages)
    assert audited['passed']
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    context = review._context(audited, messages, equipment, None, boundary)
    return equipment, messages, audited, context


def response_for(data, schema, findings=()):
    wire_findings = []
    for finding in findings:
        wire = dict(finding)
        if wire.get('disposition') == 'repair':
            wire['repairObjectiveChoiceIds'] = wire.pop('repairObjectiveChoiceIds', [])
            wire.pop('repairObjectives', None)
        else:
            wire.pop('repairDimensions', None)
            wire.pop('repairObjectives', None)
            wire.pop('repairObjectiveChoiceIds', None)
        wire_findings.append(wire)
    result = {'findings': wire_findings,
        'sourceCoverage': {key: True for key in schema['properties']['sourceCoverage']['properties']}}
    if 'blockerResolutions' in schema['properties']:
        result['blockerResolutions'] = {key: {'status': 'open', 'reason': 'Still being corrected.', 'evidenceRefs': []}
            for key in schema['properties']['blockerResolutions']['properties']}
    return result


def request_data(request):
    for message in reversed(request):
        if message.get('role') != 'user' or not message.get('content', '').startswith('{'):
            continue
        try:
            value = json.loads(message['content'])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and 'sourceMessages' in value:
            return value
    raise AssertionError('Review request context was not found.')


def finding_variant(schema, disposition):
    item = schema['properties']['findings']['items']
    return next(variant for variant in item['anyOf']
        if variant['properties']['disposition']['enum'] == [disposition])


def assert_provider_supported_schema(node):
    if node.get('type') == 'object':
        properties = node.get('properties')
        assert isinstance(properties, dict) and properties, 'provider object schemas must declare at least one property'
        assert node.get('required') == list(properties)
        for value in properties.values():
            assert_provider_supported_schema(value)
    if isinstance(node.get('items'), dict):
        assert_provider_supported_schema(node['items'])
    for branch in node.get('anyOf', []):
        assert_provider_supported_schema(branch)


def test_production_review_is_one_strict_call_over_the_exact_final_artifact(monkeypatch):
    equipment, messages, audited, context = setup_case()
    calls = []

    def respond(client, request, **options):
        data = next(json.loads(message['content']) for message in reversed(request)
            if message.get('role') == 'user' and message.get('content', '').startswith('{')
            and 'sourceMessages' in json.loads(message['content']))
        calls.append((data, options))
        assert data['finalArtifact']
        assert options['reasoning_effort'] is None
        assert options['retry'] is False
        assert options['output_schema']['additionalProperties'] is False
        assert 'blockerResolutions' not in options['output_schema']['properties']
        assert_provider_supported_schema(options['output_schema'])
        return json.dumps(response_for(data, options['output_schema'])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    monkeypatch.setattr(review, 'assess_findings', lambda *a, **k: (_ for _ in ()).throw(AssertionError('second assessment call')))
    monkeypatch.setattr(review, '_confirm_review_corrections', lambda *a, **k: (_ for _ in ()).throw(AssertionError('confirmation call')))

    result = review.review_draft(None, audited, messages, equipment, two_pass=True)

    assert result['passed']
    assert len(calls) == 1
    assert result['review']['reviewedArtifact'] == context['finalArtifact']
    assert result['review']['sourceCoverage'] == {'SOURCE_0': True}
    assert result['review']['requirementAssessments']['SOURCE_0']['status'] == 'supported'
    assert 'reviewerConfirmation' not in json.dumps(result['review']['assessment'])
    review._require_review_receipt(result, messages, equipment)
    result['review'].pop('sourceCoverage')
    with pytest.raises(ValueError, match='every original user source block'):
        review._require_review_receipt(result, messages, equipment)


def test_carried_issue_schema_has_a_populated_resolution_object(monkeypatch):
    equipment, messages, audited, context = setup_case()
    prior_finding = {'message': 'A prior source-backed prescription issue remains open.',
        'repair': 'Correct the prescription while preserving its target.', 'severity': 'blocking',
        'basis': 'established_violation', 'action': 'repair', 'muscleTargets': [], 'decisionId': None,
        'concernGroupId': 'CONCERN_SAVED'}
    context['reviewChecklist'] = {'findings': {'CONCERN_SAVED': {
        'finding': prior_finding, 'changedDraftPaths': [], 'sourceCount': 1}}}
    schemas = []

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        schemas.append(schema)
        assert_provider_supported_schema(schema)
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['components'][0]['_reviewRef']
        if len(schemas) > 1:
            assert set(schema['properties']) == {'findingCorrections', 'blockerResolutions'}
            correction_fields = schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']
            assert set(correction_fields) == {'reason', 'evidenceRefs', 'repairDimensions', 'repairObjectiveChoiceIds'}
            resolution_fields = schema['properties']['blockerResolutions']['properties']['ISSUE_0']['properties']
            assert set(resolution_fields) == {'reason', 'evidenceRefs'}
            return json.dumps({'findingCorrections': {'FINDING_0': {
                'reason': 'Change only the conflicting prescription.', 'evidenceRefs': [source_ref, current_ref],
                'repairDimensions': ['prescription'], 'repairObjectiveChoiceIds': []}},
                'blockerResolutions': {'ISSUE_0': {'reason': 'The cited source conflict is still present.',
                    'evidenceRefs': [source_ref, current_ref]}}}), None, None
        assert set(schema['properties']['blockerResolutions']['properties']) == {'ISSUE_0'}
        finding = {'message': 'The prescription needs correction to preserve the source target.',
            'basis': 'established_violation', 'disposition': 'repair',
            'repairDimensions': ['prescription'],
            'reason': 'Change only the conflicting prescription.', 'errorKind': 'none',
            'evidenceRefs': [source_ref, current_ref], 'concernGroup': 'ISSUE_0', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        payload['blockerResolutions'] = {'ISSUE_0': {'status': 'open',
            'reason': '', 'evidenceRefs': [source_ref, current_ref]}}
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)

    assert len(schemas) == 2
    assert result['scopeResults']['execution']['blockerResolutions']['CONCERN_SAVED']['status'] == 'open'


def test_one_review_derives_source_correction_status_from_its_final_finding(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        data = request_data(request)
        calls.append(data)
        fields = finding_variant(options['output_schema'], 'repair')['properties']
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['components'][0]['_reviewRef']
        finding = {'message': 'The reviewed prescription conflicts with the approved target.',
            'basis': 'established_violation', 'disposition': 'repair',
            'repairDimensions': ['prescription'],
            'reason': 'Change the prescription while preserving the approved source target.',
            'errorKind': 'none', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW_0', 'decisionId': 'none'}
        payload = response_for(data, options['output_schema'], [finding])
        assert set(payload['findings'][0]) == set(fields)
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert len(calls) == 1
    assert not result['passed']
    assert result['review']['requirementAssessments']['SOURCE_0']['status'] == 'needs_correction'
    assert result['review']['assessment']['groups'][0]['disposition'] == 'repair'
    assert result['errors'][0]['code'] == 'independent_review_finding'


def test_withdrawal_requires_source_and_current_proof_without_a_second_confirmation(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        data = request_data(request)
        calls.append(data)
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['components'][0]['_reviewRef']
        finding = {'message': 'The earlier concern was contradicted by the supplied source and final prescription.',
            'basis': 'established_violation', 'disposition': 'withdrawn_review_error',
            'reason': 'The source target and final prescription agree; the earlier interpretation was wrong.',
            'errorKind': 'contradicted_by_current_data', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW_0', 'decisionId': 'none'}
        return json.dumps(response_for(data, options['output_schema'], [finding])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert result['passed']
    assert len(calls) == 1
    group = result['review']['assessment']['groups'][0]
    assert group['disposition'] == 'withdrawn_review_error'
    assert group['evidenceHash']
    assert 'reviewerConfirmation' not in group


def test_invalid_withdrawal_proof_gets_one_correction_and_fails_closed(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        data = next(json.loads(message['content']) for message in reversed(request)
            if message.get('role') == 'user' and message.get('content', '').startswith('{')
            and 'sourceMessages' in json.loads(message['content']))
        calls.append((request, data))
        if len(calls) > 1:
            return json.dumps({'findingCorrections': {'FINDING_0': {
                'reason': 'The original cited source remains the claimed proof.',
                'evidenceRefs': [data['sourceMessages']['SOURCE_0']['_reviewRef']]}}}), None, None
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        finding = {'message': 'The source disproves the alleged violation.',
            'basis': 'established_violation', 'disposition': 'withdrawn_review_error',
            'reason': 'The cited source is the full proof.',
            'errorKind': 'contradicted_by_current_data', 'evidenceRefs': [source_ref],
            'concernGroup': 'NEW_0', 'decisionId': 'none'}
        return json.dumps(response_for(data, options['output_schema'], [finding])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert not result['passed']
    assert len(calls) == 2
    correction = json.loads(calls[1][0][-1]['content'])
    assert 'rejectedResponse' in correction
    assert 'current candidate/data' in correction['validationError']['error']
    assert result['review']['failure']
    assert result['review']['rejectedResponse']

    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'failed-review', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(audited['submittedDraft'])}}]},
        {'role': 'tool', 'tool_call_id': 'failed-review', 'content': json.dumps(result)},
    ])
    repeated = review.review_draft(None, audited, messages, equipment)
    assert repeated['review']['failure'] == result['review']['failure']
    assert len(calls) == 2


def test_semantic_correction_cannot_relabel_unproved_soft_tradeoff(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    responses = []

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['components'][0]['_reviewRef']
        if responses:
            correction_schema = options['output_schema']
            assert set(correction_schema['properties']) == {'findingCorrections'}
            correction_fields = correction_schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']
            assert set(correction_fields) == {'reason', 'evidenceRefs'}
            payload = {'findingCorrections': {'FINDING_0': {
                'reason': 'The tradeoff is optional and the source authority supports that preference.',
                'evidenceRefs': [source_ref, current_ref],
                'basis': 'uncertainty'}}}
            responses.append(payload)
            return json.dumps(payload), None, None
        finding = {'message': 'This optional distribution preference is a tradeoff.',
            'basis': 'soft_tradeoff', 'disposition': 'advisory', 'reason': 'The plan meets the required targets.',
            'errorKind': 'none', 'evidenceRefs': [current_ref],
            'concernGroup': 'NEW_0', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        responses.append(payload)
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert len(responses) == 2
    assert not result['passed']
    assert 'Additional properties are not allowed' in result['review']['failure']
    assert result['review']['rejectedResponse']


def test_semantic_correction_accepts_missing_authority_citation_without_changing_decision(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    responses = []

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['components'][0]['_reviewRef']
        if responses:
            correction_schema = options['output_schema']
            assert set(correction_schema['properties']) == {'findingCorrections'}
            correction_fields = correction_schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']
            assert set(correction_fields) == {'reason', 'evidenceRefs'}
            payload = {'findingCorrections': {'FINDING_0': {
                'reason': 'The plan meets the required targets and the cited user source permits the tradeoff.',
                'evidenceRefs': [source_ref, current_ref]}}}
            responses.append(payload)
            return json.dumps(payload), None, None
        finding = {'message': 'This optional distribution preference is a tradeoff.',
            'basis': 'soft_tradeoff', 'disposition': 'advisory', 'reason': 'The plan meets the required targets.',
            'errorKind': 'none', 'evidenceRefs': [current_ref],
            'concernGroup': 'NEW_0', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        responses.append(payload)
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert len(responses) == 2
    assert result['passed']
    assert result['review']['findings'][0]['basis'] == 'soft_tradeoff'
    assert result['review']['assessment']['groups'][0]['disposition'] == 'advisory'


def test_material_uncertainty_advisory_cannot_be_silently_downgraded(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        data = next(json.loads(message['content']) for message in reversed(request)
            if message.get('role') == 'user' and message.get('content', '').startswith('{')
            and 'sourceMessages' in json.loads(message['content']))
        calls.append(data)
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['components'][0]['_reviewRef']
        finding = {'message': 'An essential execution capability is materially uncertain.',
            'basis': 'material_uncertainty', 'disposition': 'advisory',
            'reason': 'The cited facts do not establish the required capability.',
            'errorKind': 'none', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW_0', 'decisionId': 'none'}
        return json.dumps(response_for(data, options['output_schema'], [finding])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert not result['passed']
    assert len(calls) == 2
    assert result['review']['failure']
    assert 'material_uncertainty' in result['review']['failure']
    assert 'not one of' in result['review']['failure']


def test_disposition_schema_selects_only_supported_owners_and_omits_global_plan(monkeypatch):
    equipment, messages, audited, context = setup_case()

    def respond(client, request, **options):
        schema = options['output_schema']
        assert 'repairPlan' not in schema['properties']
        repair = finding_variant(schema, 'repair')['properties']
        advisory = finding_variant(schema, 'advisory')['properties']
        withdrawn = finding_variant(schema, 'withdrawn_review_error')['properties']
        unresolved = finding_variant(schema, 'unresolved_capability')['properties']
        assert {'repairDimensions', 'repairObjectiveChoiceIds'} <= set(repair)
        for variant in (advisory, withdrawn, unresolved):
            assert 'repairDimensions' not in variant
            assert 'repairObjectiveChoiceIds' not in variant
        assert advisory['basis']['enum'] == ['uncertainty', 'soft_tradeoff']
        assert repair['basis']['enum'] == ['established_violation', 'uncertainty', 'material_uncertainty']
        data = request_data(request)
        return json.dumps(response_for(data, schema)), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review._review_complete_draft(None, context, audited, messages,
        next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user'), None)
    assert not result['findings']


def test_code_owned_redistribution_choice_is_selected_by_opaque_id(monkeypatch):
    equipment, messages, audited, context = setup_case()
    context['draft']['workouts'].append({'id': 'WORKOUT_1', 'name': 'Day B', 'exerciseIds': []})
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}
    context['redistributionObjectiveChoices'] = [objective]
    received = []

    def respond(client, request, **options):
        data = request_data(request)
        received.append(data)
        assert data['repairObjectiveChoices'] == [{'choiceId': 'OBJECTIVE_0', 'objective': objective}]
        schema = options['output_schema']
        ref = data['draft']['exercises'][0]['_reviewRef']
        finding = {'message': 'Spread this exercise across sessions.',
            'basis': 'established_violation', 'disposition': 'repair',
            'repairDimensions': ['exercise_selection'], 'repairObjectiveChoiceIds': ['OBJECTIVE_0'],
            'reason': 'Preserve the exercise while spreading its work across sessions.',
            'errorKind': 'none', 'evidenceRefs': [ref], 'concernGroup': 'NEW_0', 'decisionId': 'none'}
        return json.dumps(response_for(data, schema, [finding])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review._review_complete_draft(None, context, audited, messages,
        next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user'), None)
    assert len(received) == 1
    assert result['assessment']['groups'][0]['repairObjectives'] == [objective]
