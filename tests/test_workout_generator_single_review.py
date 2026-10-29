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


def test_incomplete_balance_disclosure_matches_preview_review_and_export_receipt(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    evidence = {'approvedPriorities': [
        {'priority': 'distribution', 'owner': 'joint_solver', 'status': 'feasible',
         'solverStage': {'goal': 'distribution', 'status': 'feasible', 'value': 12}}]}
    audited['automaticAllocation'] = {'priorityExecution': evidence}

    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        assert data['programmingSummary']['priorityExecution']['approvedPriorities'][0]['status'] == 'feasible'
        assert 'the approved balance hierarchy is not proven optimal' in data['finalArtifact']['programGuidance']
        return json.dumps(response_for(data, options['output_schema'])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert result['passed']
    assert 'approved balance hierarchy is not proven optimal' in result['preview']
    assert result['audit']['priorityExecution'] == evidence
    assert 'the approved balance hierarchy is not proven optimal' in result['review']['reviewedArtifact']['programGuidance']
    review._require_review_receipt(result, messages, equipment)


def response_for(data, schema, findings=()):
    wire_findings = []
    for finding in findings:
        wire = dict(finding)
        properties = finding_variant(schema, wire['disposition'])['properties']
        if 'subjectRefs' in properties:
            subjects = properties['subjectRefs']['items']['enum']
            wire.setdefault('subjectRefs', [ref for ref in wire.get('evidenceRefs', []) if ref in subjects]
                or [next(iter(data['reviewSubjects']))])
            if wire.get('message') not in properties['message']['enum']:
                wire['message'] = 'source_compliance'
            if wire.get('reason') not in properties['reason']['enum']:
                wire['reason'] = ('unsupported_requirement' if wire.get('errorKind') == 'unsupported_requirement'
                    else 'contradicted_by_current_data' if wire.get('disposition') == 'withdrawn_review_error'
                    else 'capacity_uncertainty' if wire.get('basis') in ('uncertainty', 'material_uncertainty')
                    else 'emphasis_tradeoff' if wire.get('basis') == 'soft_tradeoff' else 'source_conflict')
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
        result['blockerResolutions'] = {key: {'reason': 'source_conflict', 'evidenceRefs': []}
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
        assert 'Sequencing compliance is code-owned' in data['reviewAuthority']
        assert any('shared deterministic audit owns block and superset-member category order' in guideline
            for guideline in data['programmingGuidelines']['review'])
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
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        if len(schemas) > 1:
            assert set(schema['properties']) == {'findingCorrections', 'blockerResolutions'}
            correction_fields = schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']
            assert set(correction_fields) == {'evidenceRefs', 'repairDimensions', 'repairObjectiveChoiceIds'}
            resolution_fields = schema['properties']['blockerResolutions']['properties']['ISSUE_0']['properties']
            assert set(resolution_fields) == {'reason', 'evidenceRefs'}
            return json.dumps({'findingCorrections': {'FINDING_0': {
                'evidenceRefs': [source_ref, current_ref],
                'repairDimensions': ['prescription'], 'repairObjectiveChoiceIds': []}},
                'blockerResolutions': {'ISSUE_0': {'reason': 'source_conflict',
                    'evidenceRefs': [source_ref, current_ref]}}}), None, None
        assert set(schema['properties']['blockerResolutions']['properties']) == {'ISSUE_0'}
        assert set(schema['properties']['blockerResolutions']['properties']['ISSUE_0']['properties']) == {
            'reason', 'evidenceRefs'}
        finding = {'message': 'The prescription needs correction to preserve the source target.',
            'basis': 'established_violation', 'disposition': 'repair',
            'repairDimensions': ['prescription'],
            'reason': 'source_conflict', 'errorKind': 'none',
            'evidenceRefs': [source_ref, current_ref], 'concernGroup': 'ISSUE_0', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        payload['blockerResolutions'] = {'ISSUE_0': {
            'reason': 'source_conflict', 'evidenceRefs': []}}
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)

    assert len(schemas) == 2
    assert result['scopeResults']['execution']['blockerResolutions']['CONCERN_SAVED']['status'] == 'open'


@pytest.mark.parametrize(('accepted_concern_id', 'incoming_disposition', 'incoming_decision_id', 'expected_resolution', 'expected_disposition'), [
    ('CONCERN_NORDIC', 'unresolved_capability', 'DECISION_0', 'resolved_by_change', 'advisory'),
    ('CONCERN_NORDIC', 'repair', 'none', 'resolved_by_change', 'advisory'),
    ('CONCERN_NORDIC', 'repair', 'DECISION_0', 'resolved_by_change', 'advisory'),
    (None, 'unresolved_capability', 'DECISION_0', 'open', 'unresolved_capability'),
    ('CONCERN_OTHER', 'unresolved_capability', 'DECISION_0', 'open', 'unresolved_capability'),
])
def test_final_review_requires_exact_user_acceptance_intent_for_material_uncertainty(
        monkeypatch, accepted_concern_id, incoming_disposition, incoming_decision_id,
        expected_resolution, expected_disposition):
    equipment, messages, audited, context = setup_case()
    audited['historyFingerprint'] = None
    context['candidateAcceptanceScope'] = review.candidate_acceptance_scope(audited)
    messages.append({'role': 'user', 'content': 'Accept this disclosed uncertainty for generation only; do not infer capability.'})
    source_id = 'SOURCE_1'
    context['sourceMessages'][source_id] = {'role': 'user',
        'content': 'Accept this disclosed uncertainty for generation only; do not infer capability.'}
    decision = {'topic': 'Personal recovery tolerance',
        'choice': 'Accept the disclosed uncertainty for this candidate only.',
        'sourceReferences': [source_id], 'sourceCountAtResolution': 2}
    if accepted_concern_id is not None:
        decision['acceptedConcernGroupId'] = accepted_concern_id
        decision['acceptedCandidateScope'] = review.candidate_acceptance_scope(audited)
    context['resolvedDecisions'] = {'DECISION_0': decision}
    superseded_model_decision = incoming_disposition == 'repair' and incoming_decision_id == 'DECISION_0'
    if superseded_model_decision:
        decision['supersededBy'] = 'DECISION_1'
        active_decision = dict(decision)
        active_decision.pop('supersededBy')
        context['resolvedDecisions']['DECISION_1'] = active_decision
    prior_finding = {'message': 'Personal recovery tolerance for this repeated eccentric work is unknown.',
        'repair': 'Treat this as a material uncertainty.', 'severity': 'blocking',
        'basis': 'material_uncertainty', 'action': 'clarify', 'muscleTargets': [], 'decisionId': None,
        'concernGroupId': 'CONCERN_NORDIC'}
    context['reviewChecklist'] = {'findings': {'CONCERN_NORDIC': {
        'finding': prior_finding, 'changedDraftPaths': [], 'sourceCount': 1}}}

    def respond(client, request, **options):
        data = request_data(request)
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        finding = {'message': 'Personal tolerance remains unknown and is accepted only for generation.',
            'basis': 'material_uncertainty', 'disposition': incoming_disposition,
            'reason': 'Personal capability remains unverified.',
            # Deliberately omit the decision and user-source references. Code
            # must bind their exact owners from the typed decision record.
            'errorKind': 'none', 'evidenceRefs': [current_ref],
            'concernGroup': 'ISSUE_0', 'decisionId': incoming_decision_id}
        if incoming_disposition == 'repair':
            finding['repairDimensions'] = [next(iter(review.REPAIR_DIMENSIONS))]
            finding['repairObjectiveChoiceIds'] = []
        payload = response_for(data, options['output_schema'], [finding])
        payload['blockerResolutions'] = {'ISSUE_0': {
            'reason': 'capacity_uncertainty',
            'evidenceRefs': [current_ref]}}
        assert 'status' not in options['output_schema']['properties']['blockerResolutions']['properties']['ISSUE_0']['properties']
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = len(messages) - 1
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)

    resolution = result['scopeResults']['execution']['blockerResolutions']['CONCERN_NORDIC']
    assert resolution['status'] == expected_resolution
    assert result['assessment']['groups'][0]['disposition'] == expected_disposition
    assert result['findings'][0]['severity'] == ('warning' if expected_disposition == 'advisory' else 'blocking')
    if accepted_concern_id == 'CONCERN_NORDIC':
        expected_decision_id = 'DECISION_1' if superseded_model_decision else 'DECISION_0'
        assert result['findings'][0]['decisionId'] == expected_decision_id
    assert result['findings'][0]['basis'] == 'material_uncertainty'
    if expected_disposition == 'advisory':
        assert result['findings'][0]['severity'] == 'warning'
    if accepted_concern_id == 'CONCERN_NORDIC':
        expected_refs = {f'/resolvedDecisions/{expected_decision_id}', f'/sourceMessages/{source_id}'}
        assert expected_refs <= set(result['findings'][0]['evidencePaths'])
        assert expected_refs <= set(resolution['evidencePaths'])
        assert result['assessment']['groups'][0]['repairDimensions'] == []
        assert result['assessment']['groups'][0]['repairObjectives'] == []


@pytest.mark.parametrize('scope_field', ['workoutsFingerprint', 'libraryFingerprint', 'historyFingerprint'])
def test_scoped_acceptance_does_not_cross_candidate_or_evidence_scope(scope_field):
    _, messages, audited, context = setup_case()
    audited['historyFingerprint'] = None
    context['candidateAcceptanceScope'] = review.candidate_acceptance_scope(audited)
    source_id = 'SOURCE_0'
    scope = review.candidate_acceptance_scope(audited)
    scope[scope_field] = 'changed-scope'
    context['resolvedDecisions'] = {'DECISION_0': {
        'acceptedConcernGroupId': 'CONCERN_NORDIC', 'acceptedCandidateScope': scope,
        'sourceReferences': [source_id], 'sourceCountAtResolution': len(context['sourceMessages'])}}
    finding = {'basis': 'material_uncertainty', 'action': 'clarify', 'repair': 'Keep this blocker.',
        'concernGroupId': 'CONCERN_NORDIC', 'decisionId': 'DECISION_0', 'newConflictEvidencePaths': []}

    assert not review._check_decision_finding(finding, context)
    assert finding['action'] == 'clarify'


def test_scoped_acceptance_preserves_new_conflicts_and_established_violations():
    _, messages, audited, context = setup_case()
    audited['historyFingerprint'] = None
    context['candidateAcceptanceScope'] = review.candidate_acceptance_scope(audited)
    source_id = 'SOURCE_0'
    context['resolvedDecisions'] = {'DECISION_0': {
        'acceptedConcernGroupId': 'CONCERN_NORDIC',
        'acceptedCandidateScope': review.candidate_acceptance_scope(audited),
        'sourceReferences': [source_id], 'sourceCountAtResolution': len(context['sourceMessages'])}}

    context['sourceMessages']['SOURCE_1'] = {'role': 'user', 'content': 'A new relevant user constraint.'}
    new_conflict = {'basis': 'material_uncertainty', 'action': 'clarify', 'repair': 'Keep this blocker.',
        'concernGroupId': 'CONCERN_NORDIC', 'decisionId': 'DECISION_0',
        'newConflictEvidencePaths': ['/sourceMessages/SOURCE_1']}
    assert not review._check_decision_finding(new_conflict, context)
    assert new_conflict['action'] == 'clarify'

    violation = {'basis': 'established_violation', 'action': 'repair', 'repair': 'Keep this repair.',
        'concernGroupId': 'CONCERN_NORDIC', 'decisionId': 'DECISION_0', 'newConflictEvidencePaths': []}
    assert not review._check_decision_finding(violation, context)
    assert violation['action'] == 'repair'


def test_unchanged_accepted_tradeoff_echo_does_not_reopen_the_ledger(monkeypatch):
    equipment, messages, audited, context = setup_case()
    prior_finding = {'message': 'A balance residual is an accepted soft preference.',
        'repair': 'No defect; the preference remains an advisory.', 'severity': 'advisory',
        'basis': 'soft_tradeoff', 'action': 'advisory', 'muscleTargets': [], 'decisionId': None,
        'concernGroupId': 'CONCERN_BALANCE'}
    context['reviewChecklist'] = {'findings': {}, 'acceptedSoftTradeoffs': {'CONCERN_BALANCE': {
        'finding': prior_finding, 'changedDraftPaths': [], 'sourceCount': 1}}}

    def respond(client, request, **options):
        data = request_data(request)
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        echo = {'message': prior_finding['message'], 'basis': 'soft_tradeoff', 'disposition': 'advisory',
            'reason': prior_finding['repair'], 'errorKind': 'none', 'evidenceRefs': [current_ref],
            'concernGroup': 'TRADEOFF_0', 'decisionId': 'none'}
        return json.dumps(response_for(data, options['output_schema'], [echo])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review._review_complete_draft(None, context, audited, messages, len(messages) - 1, None)

    assert result['findings'] == []


def test_one_review_derives_source_correction_status_from_its_final_finding(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        data = request_data(request)
        calls.append(data)
        fields = finding_variant(options['output_schema'], 'repair')['properties']
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        finding = {'message': 'The reviewed prescription conflicts with the approved target.',
            'basis': 'established_violation', 'disposition': 'repair',
            'repairDimensions': ['prescription'],
            'reason': 'Change the prescription while preserving the approved source target.',
            'errorKind': 'none', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW', 'decisionId': 'none'}
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
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        finding = {'message': 'The earlier concern was contradicted by the supplied source and final prescription.',
            'basis': 'established_violation', 'disposition': 'withdrawn_review_error',
            'reason': 'The source target and final prescription agree; the earlier interpretation was wrong.',
            'errorKind': 'contradicted_by_current_data', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW', 'decisionId': 'none'}
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
            'concernGroup': 'NEW', 'decisionId': 'none'}
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
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        if responses:
            correction_schema = options['output_schema']
            assert set(correction_schema['properties']) == {'findingCorrections'}
            correction_fields = correction_schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']
            assert set(correction_fields) == {'authorityRef'}
            payload = {'findingCorrections': {'FINDING_0': {
                'authorityRef': source_ref,
                'basis': 'uncertainty'}}}
            responses.append(payload)
            return json.dumps(payload), None, None
        finding = {'message': 'This optional distribution preference is a tradeoff.',
            'basis': 'soft_tradeoff', 'disposition': 'advisory', 'reason': 'The plan meets the required targets.',
            'errorKind': 'none', 'evidenceRefs': [current_ref],
            'concernGroup': 'NEW', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        responses.append(payload)
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert len(responses) == 1
    assert result['passed']
    finding = result['review']['findings'][0]
    assert finding['basis'] == 'soft_tradeoff'
    assert finding['evidencePaths'] == ['/finalArtifact/workouts/0', '/requirements']


@pytest.mark.parametrize('extra,accepted', [
    ({'reason': 'Unrequested replacement', 'evidenceRefs': ['unrequested reference'],
      'repairDimensions': [], 'repairObjectiveChoiceIds': []}, True),
    ({'repairDimensions': ['exercise_selection']}, False),
    ({'unrecognizedField': 'anything'}, False),
])
def test_reference_only_correction_preserves_original_support_and_rejects_new_owners(extra, accepted):
    original = {'findings': [{'message': 'Original judgment', 'basis': 'soft_tradeoff',
        'reason': 'Original support', 'evidenceRefs': ['CURRENT'], 'disposition': 'advisory'}]}
    schema = {'type': 'object', 'properties': {'findingCorrections': {
        'type': 'object', 'properties': {'FINDING_0': {
            'type': 'object', 'properties': {'authorityRef': {'type': 'string', 'enum': ['SOURCE']}},
            'required': ['authorityRef'], 'additionalProperties': False}},
        'required': ['FINDING_0'], 'additionalProperties': False}},
        'required': ['findingCorrections'], 'additionalProperties': False}
    correction = {'findingCorrections': {'FINDING_0': {'authorityRef': 'SOURCE', **extra}}}
    if not accepted:
        with pytest.raises(review.ValidationError, match='Additional properties'):
            review._merge_review_correction(original, correction, schema)
        return
    merged = review._merge_review_correction(original, correction, schema)
    assert merged['findings'][0] == {**original['findings'][0], 'evidenceRefs': ['CURRENT', 'SOURCE']}
    assert original['findings'][0]['evidenceRefs'] == ['CURRENT']
    assert correction['findingCorrections']['FINDING_0']['reason'] == 'Unrequested replacement'


def test_correction_objectives_reuse_catalog_ids_while_final_evidence_scopes_them():
    choices = [{'kind': 'redistribute_work', 'exerciseRefs': [f'EXERCISE_{i}'], 'minimumSessions': 2}
               for i in range(2)]
    context = {'draft': {'exercises': [
        {'id': f'EXERCISE_{i}', 'libraryDefinitionId': f'LIBRARY_{i}'} for i in range(2)],
        'libraryDefinitions': {'LIBRARY_0': {}, 'LIBRARY_1': {}}},
        'redistributionObjectiveChoices': choices}
    fields = {'reason': {'type': 'string'},
              'evidenceRefs': {'type': 'array', 'items': {'type': 'string'}},
              'repairDimensions': {'type': 'array', 'items': {'type': 'string'}},
              'repairObjectiveChoiceIds': review.provider_repair_objective_selection_schema(choices)}
    output_schema = {'properties': {'findings': {'items': {'properties': {
        'disposition': {'enum': ['repair']}, **fields}}}}}
    original = {'findings': [{'disposition': 'repair', 'basis': 'uncertainty', 'evidenceRefs': ['CITED']}]}
    schema = review._review_correction_schema(original, output_schema, context,
        {'CITED': '/requirements'}, choices)
    selector = schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']['repairObjectiveChoiceIds']
    assert selector['items']['enum'] == ['OBJECTIVE_0', 'OBJECTIVE_1']
    review.validate(['OBJECTIVE_0'], selector)
    assert review.finding_redistribution_objective_choices(
        {'evidencePaths': ['/draft/exercises/0']}, context) == [choices[0]]
    assert review.finding_redistribution_objective_choices(
        {'evidencePaths': ['/requirements']}, context) == []


def test_review_with_no_correctable_support_stops_locally_instead_of_building_empty_schema():
    original = {'findings': [
        {'disposition': 'unresolved_capability', 'basis': 'material_uncertainty', 'evidenceRefs': ['FACT_0']},
        {'disposition': 'withdrawn_review_error', 'basis': 'established_violation', 'evidenceRefs': ['FACT_1']},
    ], 'blockerResolutions': {}}
    output_schema = {'properties': {'findings': {'items': {'anyOf': [
        {'properties': {'disposition': {'enum': ['repair']}}},
        {'properties': {'disposition': {'enum': ['unresolved_capability']}}},
        {'properties': {'disposition': {'enum': ['withdrawn_review_error']}}},
    ]}}}}
    with pytest.raises(ValueError, match='no correctable support fields; stop locally'):
        review._review_correction_schema(original, output_schema, {}, {}, [])


def test_legacy_full_review_correction_is_narrowed_and_only_valid_selected_refs_are_derived():
    source_ref = 'FACT_SOURCE'
    current_refs = {
        'FACT_650': '/programmingSummary/coverageRequirements/9',
        'FACT_682': '/programmingSummary/coverageBalanceEvidence/0',
        'FACT_683': '/programmingSummary/coverageBalanceEvidence/1',
        'FACT_658': '/programmingSummary/coverageRequirements/11',
        'FACT_806': '/audit/workouts/0/setupEstimates/6',
        'FACT_304': '/finalArtifact/workouts/0/components/3',
        'FACT_351': '/finalArtifact/workouts/1/components/0',
    }
    facts = {source_ref: '/sourceMessages/SOURCE_0', 'FACT_0': '/requirements',
        'FACT_PLAN': '/finalArtifact', **current_refs}
    context = {'sourceMessages': {'SOURCE_0': {'role': 'user'}}}
    output_schema = {'properties': {'findings': {'items': {'anyOf': [{
        'properties': {'disposition': {'enum': ['advisory']},
            'basis': {'enum': ['uncertainty', 'soft_tradeoff']},
            'reason': {'type': 'string'}, 'evidenceRefs': {'type': 'array', 'items': {'type': 'string'}}}}]}}}}

    findings = []
    for index in range(9):
        refs = ['FACT_650'] if index == 2 else ['FACT_806'] if index == 5 else ['FACT_304']
        if index == 2:
            refs = ['FACT_682', 'FACT_683', 'FACT_658', 'FACT_650']
        elif index == 5:
            refs = ['FACT_806', 'FACT_304', 'FACT_351']
        findings.append({'disposition': 'advisory',
            'basis': 'soft_tradeoff' if index in (2, 5) else 'uncertainty',
            'reason': f'Original reviewed judgment {index}.', 'evidenceRefs': refs})
    original = {'findings': findings, 'blockerResolutions': {}}
    schema = review._review_correction_schema(original, output_schema, context, facts, [])
    entries = schema['properties']['findingCorrections']['properties']
    assert set(entries) == {'FINDING_2', 'FINDING_5'}
    for entry in entries.values():
        assert set(entry['properties']) == {'authorityRef'}
        assert entry['properties']['authorityRef']['enum'] == ['APPROVED_REQUIREMENTS']

    # The retained live response echoed all nine reasons/citations. FACT_650 is a current-plan
    # coverage summary, and the other refs are plan/audit data, so none can prove source authority.
    legacy = {'findingCorrections': {f'FINDING_{index}': {
        'reason': f'Rewritten support {index}.',
        'evidenceRefs': findings[index]['evidenceRefs']} for index in range(9)}}
    with pytest.raises(review.ValidationError, match='authorityRef'):
        review._merge_review_correction(original, legacy, schema)
    assert original['findings'][2]['reason'] == 'Original reviewed judgment 2.'
    assert original['findings'][5]['reason'] == 'Original reviewed judgment 5.'

    # The exact latest live reply chose a plan fact as authority. Semantic owner choices
    # reject it before code binds any evidence reference.
    live_reply = {'findingCorrections': {'FINDING_2': {'authorityRef': 'FACT_682'}}}
    with pytest.raises(review.ValidationError, match='authorityRef'):
        review._merge_review_correction(original, live_reply, schema)

    legacy['findingCorrections']['FINDING_2']['authorityRef'] = 'APPROVED_REQUIREMENTS'
    legacy['findingCorrections']['FINDING_5']['authorityRef'] = 'APPROVED_REQUIREMENTS'
    merged = review._merge_review_correction(original, legacy, schema, facts)
    assert len(merged['findings']) == 9
    assert merged['findings'][2]['reason'] == original['findings'][2]['reason']
    assert merged['findings'][5]['reason'] == original['findings'][5]['reason']
    assert facts and facts['FACT_0'] == '/requirements'
    assert 'FACT_0' in merged['findings'][2]['evidenceRefs']
    assert 'FACT_0' in merged['findings'][5]['evidenceRefs']
    for index in set(range(9)) - {2, 5}:
        assert merged['findings'][index] == original['findings'][index]


def test_live_wrong_fact_class_correction_uses_semantic_owner_choice():
    findings = [{'disposition': 'advisory', 'basis': 'uncertainty',
        'reason': f'Original judgment {index}.', 'evidenceRefs': ['FACT_682']}
        for index in range(4)]
    findings[3]['basis'] = 'soft_tradeoff'
    original = {'findings': findings, 'blockerResolutions': {}}
    context = {'sourceMessages': {'SOURCE_0': {'role': 'user'}}}
    facts = {'FACT_0': '/requirements', 'FACT_682': '/programmingSummary/coverageBalanceEvidence/0'}
    output_schema = {'properties': {'findings': {'items': {'anyOf': [{
        'properties': {'disposition': {'enum': ['advisory']},
            'basis': {'enum': ['uncertainty', 'soft_tradeoff']}, 'reason': {'type': 'string'},
            'evidenceRefs': {'type': 'array', 'items': {'type': 'string'}}}}]}}}}
    schema = review._review_correction_schema(original, output_schema, context, facts, [])
    entries = schema['properties']['findingCorrections']['properties']
    assert set(entries) == {'FINDING_3'}
    assert entries['FINDING_3']['properties']['authorityRef']['enum'] == [
        'APPROVED_REQUIREMENTS']

    # This is the exact failed live correction: the value is a plan fact, not its owner.
    actual_reply = {'findingCorrections': {'FINDING_3': {'authorityRef': 'FACT_682'}}}
    with pytest.raises(review.ValidationError, match='authorityRef'):
        review._merge_review_correction(original, actual_reply, schema, facts)
    corrected = {'findingCorrections': {'FINDING_3': {'authorityRef': 'APPROVED_REQUIREMENTS'}}}
    assert review._deterministic_review_reference_correction(schema) == corrected
    merged = review._merge_review_correction(original, corrected, schema, facts)
    assert 'FACT_0' in merged['findings'][3]['evidenceRefs']
    assert merged['findings'][3]['reason'] == findings[3]['reason']
    assert [item['reason'] for item in merged['findings']] == [item['reason'] for item in findings]


def test_review_binds_missing_tradeoff_owner_without_reasking_valid_repair_fields(monkeypatch):
    equipment, messages, audited, context = setup_case()
    calls = []

    def respond(client, request, **options):
        data = request_data(request)
        calls.append(options['stage'] if 'stage' in options else 'review')
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        repair = {'message': 'The reviewed prescription conflicts with its approved target.',
            'reason': 'source_conflict', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW', 'decisionId': 'none', 'basis': 'established_violation',
            'disposition': 'repair', 'errorKind': 'none', 'repairDimensions': ['prescription'],
            'repairObjectiveChoiceIds': []}
        tradeoff = {'message': 'The balance preference has an unresolved residual.',
            'reason': 'Unequal role counts remain a disclosed soft tradeoff.', 'evidenceRefs': [current_ref],
            'concernGroup': 'NEW', 'decisionId': 'none', 'basis': 'soft_tradeoff',
            'disposition': 'advisory', 'errorKind': 'none'}
        return json.dumps(response_for(data, options['output_schema'], [repair, tradeoff])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)

    assert len(calls) == 1
    assert [finding['concernGroup'] for finding in result['findings']] == ['NEW_0', 'NEW_1']
    assert 'prescription' in result['assessment']['groups'][0]['repairDimensions']
    assert result['findings'][0]['reviewJudgment'] == 'source_conflict'
    assert 'Code-owned exposure:' in result['findings'][0]['repair']
    assert '/requirements' in result['findings'][1]['evidencePaths']


def test_live_advisory_material_uncertainty_is_canonicalized_before_narrow_correction(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    raw_reviews = []
    correction_responses = []
    expected_messages = [
        'Session B deadlifts/Barbell Bench Press volume distribution: 9 bench-press working sets in one session and 3 RDL sets are within numeric bounds, but the ordering RDL supersetted with dumbbell incline press then 8 sets split squat before bench press concentrates pressing fatigue and axial/hinge work without any demand annotation to verify. Insufficient evidence to call a violation; attention only.',
        'Vertical push exposure is minimal: only 2 Barbell Overhead Press working sets weekly versus 5 vertical-pull sets, and the vertical push appears in Session A alone. Balance relationships are qualitative with no numeric quota, and pressing volume overall is ample, but overhead pressing development is lightly dosed.',
        'Missing personal capacity, recovery, and exercise-capability evidence: Ring Pull-Up, Pull-Up, and the Nordic variants have no comparable records and no established assisted method. Session A pairs Ring Pull-Up with Overhead Press and puts 5 sets of Nordic curls first, which is unverified for this user\'s ability to complete. This is uncertainty, not an approved sufficiency.',
    ]

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        if raw_reviews:
            entries = schema['properties']['findingCorrections']['properties']
            assert set(entries) == {'FINDING_1'}
            fields = entries['FINDING_1']['properties']
            assert set(fields) == {'authorityRef'}
            assert fields['authorityRef']['enum'] == ['APPROVED_REQUIREMENTS']
            payload = {'findingCorrections': {'FINDING_1': {
                'authorityRef': 'APPROVED_REQUIREMENTS'}}}
            correction_responses.append(payload)
            return review._canonical_review_content(json.dumps(payload), schema), None, None

        plan_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        findings = [
            {'message': expected_messages[0], 'reason': 'Attention only.', 'evidenceRefs': [plan_ref],
             'concernGroup': 'NEW', 'decisionId': 'none', 'basis': 'uncertainty',
             'disposition': 'advisory', 'errorKind': 'none'},
            {'message': expected_messages[1], 'reason': 'This is a soft tradeoff.', 'evidenceRefs': [plan_ref],
             'concernGroup': 'NEW', 'decisionId': 'none', 'basis': 'soft_tradeoff',
             'disposition': 'advisory', 'errorKind': 'none'},
            {'message': expected_messages[2], 'reason': 'The personal capability is unverified.',
             'evidenceRefs': [plan_ref], 'concernGroup': 'NEW', 'decisionId': 'none',
             'basis': 'material_uncertainty', 'disposition': 'advisory', 'errorKind': 'none'},
        ]
        payload = response_for(data, schema, findings)
        raw_reviews.append(payload)
        canonical = review._canonical_review_content(json.dumps(payload), schema)
        canonical_payload = json.loads(canonical)
        assert canonical_payload['findings'][2]['basis'] == 'uncertainty'
        assert [finding['disposition'] for finding in canonical_payload['findings']] == [
            finding['disposition'] for finding in payload['findings']]
        assert canonical_payload['sourceCoverage'] == payload['sourceCoverage']
        return canonical, None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert len(raw_reviews) == 1
    assert correction_responses == []  # indexed owners are bound by Python, without another model call
    assert result['passed']
    assert [finding['reviewConcern'] for finding in result['review']['findings']] == ['source_compliance'] * 3
    assert all(finding['subjectFacts'] for finding in result['review']['findings'])
    assert [finding['basis'] for finding in result['review']['findings']] == [
        'uncertainty', 'soft_tradeoff', 'uncertainty']
    assert [group['disposition'] for group in result['review']['assessment']['groups']] == [
        'advisory', 'advisory', 'advisory']
    assert result['review']['sourceCoverage'] == raw_reviews[0]['sourceCoverage']


@pytest.mark.parametrize('missing_category', ['authorityRef', 'currentPlanRef'])
def test_semantic_correction_selects_only_missing_evidence_without_changing_decision(
        monkeypatch, missing_category):
    equipment, messages, audited, _ = setup_case()
    responses = []

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        assert not responses
        finding = {'message': 'This optional distribution preference is a tradeoff.',
            'basis': 'soft_tradeoff', 'disposition': 'advisory', 'reason': 'The plan meets the required targets.',
            'errorKind': 'none',
            'evidenceRefs': [current_ref if missing_category == 'authorityRef' else source_ref],
            'concernGroup': 'NEW', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        responses.append(payload)
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment)

    assert len(responses) == 1
    assert result['passed']
    assert result['review']['findings'][0]['basis'] == 'soft_tradeoff'
    assert result['review']['findings'][0]['reviewJudgment'] == responses[0]['findings'][0]['reason']
    assert 'Code-owned exposure:' in result['review']['findings'][0]['repair']
    assert result['review']['assessment']['groups'][0]['disposition'] == 'advisory'
    expected_paths = ({'/requirements', '/finalArtifact/workouts/0'}
        if missing_category == 'authorityRef' else {'/sourceMessages/SOURCE_0', '/finalArtifact'})
    assert set(result['review']['findings'][0]['evidencePaths']) == expected_paths


def test_material_uncertainty_advisory_cannot_be_silently_downgraded(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        data = next(json.loads(message['content']) for message in reversed(request)
            if message.get('role') == 'user' and message.get('content', '').startswith('{')
            and 'sourceMessages' in json.loads(message['content']))
        calls.append(data)
        source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        finding = {'message': 'An essential execution capability is materially uncertain.',
            'basis': 'material_uncertainty', 'disposition': 'advisory',
            'reason': 'The cited facts do not establish the required capability.',
            'errorKind': 'none', 'evidenceRefs': [source_ref, current_ref],
            'concernGroup': 'NEW', 'decisionId': 'none'}
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
            'errorKind': 'none', 'evidenceRefs': [ref], 'concernGroup': 'NEW', 'decisionId': 'none'}
        return json.dumps(response_for(data, schema, [finding])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    result = review._review_complete_draft(None, context, audited, messages,
        next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user'), None)
    assert len(received) == 1
    assert result['assessment']['groups'][0]['repairObjectives'] == [objective]


def test_review_correction_can_repair_citations_before_selecting_same_catalog_objective(monkeypatch):
    equipment, messages, audited, context = setup_case()
    context['draft']['workouts'].append({'id': 'WORKOUT_1', 'name': 'Day B', 'exerciseIds': []})
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}
    context['redistributionObjectiveChoices'] = [objective]
    responses = []

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        if not responses:
            source_ref = data['sourceMessages']['SOURCE_0']['_reviewRef']
            plan_ref = data['draft']['workouts'][0]['_reviewRef']
            finding = {'message': 'Preserve this exercise while redistributing its work.',
                'reason': '',
                'evidenceRefs': [source_ref, 'UNKNOWN_CITATION'], 'concernGroup': 'NEW', 'decisionId': 'none',
                'basis': 'established_violation', 'disposition': 'repair', 'errorKind': 'none',
                'repairDimensions': ['exercise_selection'], 'repairObjectiveChoiceIds': ['OBJECTIVE_0']}
            responses.append(('initial', plan_ref, source_ref))
            return json.dumps(response_for(data, schema, [finding])), None, None

        selector = schema['properties']['findingCorrections']['properties']['FINDING_0']['properties'][
            'repairObjectiveChoiceIds']
        assert selector['items']['enum'] == ['OBJECTIVE_0']
        _, plan_ref, source_ref = responses[0]
        correction = {'findingCorrections': {'FINDING_0': {
            'evidenceRefs': [source_ref, plan_ref],
            'repairDimensions': ['exercise_selection'],
            'repairObjectiveChoiceIds': ['OBJECTIVE_0']}}}
        responses.append(('correction', correction))
        return json.dumps(correction), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)

    assert [response[0] for response in responses] == ['initial', 'correction']
    assert result['assessment']['groups'][0]['repairObjectives'] == [objective]


def test_carried_advisory_bad_citation_uses_one_support_only_correction(monkeypatch):
    equipment, messages, audited, context = setup_case()
    context['reviewChecklist'] = {'findings': {'CONCERN_LABEL': {
        'finding': {'message': 'The prior focus label contradicted the exercise list.',
            'repair': 'Use labels that reflect the emitted exercises.', 'severity': 'blocking',
            'basis': 'established_violation', 'action': 'repair', 'muscleTargets': [],
            'concernGroupId': 'CONCERN_LABEL'},
        'changedDraftPaths': ['/finalArtifact/workouts/0/description'], 'sourceCount': 1}}}
    calls = []

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        current_ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        calls.append(schema)
        if len(calls) == 1:
            finding = {'message': 'Current exercise exposure may warrant a fatigue review.',
                'reason': 'Personal tolerance is unknown, so this remains an advisory.',
                'evidenceRefs': ['ISSUE_0', current_ref], 'concernGroup': 'ISSUE_0',
                'decisionId': 'none', 'basis': 'uncertainty', 'disposition': 'advisory',
                'errorKind': 'none'}
            payload = response_for(data, schema, [finding])
            payload['blockerResolutions']['ISSUE_0'] = {
                'reason': 'contradicted_by_current_data',
                'evidenceRefs': [current_ref]}
            return json.dumps(payload), None, None

        assert set(schema['properties']) == {'findingCorrections', 'blockerResolutions'}
        finding_fields = schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']
        assert set(finding_fields) == {'evidenceRefs'}
        correction = {'findingCorrections': {'FINDING_0': {'evidenceRefs': [current_ref]}},
            'blockerResolutions': {'ISSUE_0': {
                'reason': 'contradicted_by_current_data',
                'evidenceRefs': [current_ref]}}}
        return json.dumps(correction), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)

    assert len(calls) == 2
    assert result['findings'][0]['concernGroup'] == 'ISSUE_0'
    assert result['findings'][0]['basis'] == 'uncertainty'
    assert result['findings'][0]['evidencePaths'] == ['/finalArtifact/workouts/0']
    assert result['scopeResults']['execution']['blockerResolutions']['CONCERN_LABEL']['status'] == 'resolved_by_change'


@pytest.mark.parametrize('changed', [True, False])
def test_carried_review_error_correction_can_select_resolution_only_with_a_real_change(monkeypatch, changed):
    equipment, messages, audited, context = setup_case()
    context['reviewChecklist'] = {'findings': {'CONCERN_ORDER': {
        'finding': {'message': 'The opening exercise is out of order.', 'repair': 'Reorder it.',
            'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
            'muscleTargets': [], 'decisionId': None, 'concernGroupId': 'CONCERN_ORDER'},
        'changedDraftPaths': ['/finalArtifact/workouts/0/components/0'] if changed else [], 'sourceCount': 1}}}
    responses = []

    def respond(client, request, **options):
        data = request_data(request)
        ref = data['finalArtifact']['workouts'][0]['_reviewRef']
        schema = options['output_schema']
        if not responses:
            finding = {'message': 'The previous order concern is now resolved.',
                'reason': 'The current artifact has changed.', 'evidenceRefs': [ref],
                'concernGroup': 'ISSUE_0', 'decisionId': 'none', 'basis': 'established_violation',
                'disposition': 'withdrawn_review_error', 'errorKind': 'contradicted_by_current_data'}
            payload = response_for(data, schema, [finding])
            payload['blockerResolutions']['ISSUE_0'] = {'reason': 'contradicted_by_current_data', 'evidenceRefs': [ref]}
        else:
            assert len(responses) == 1
            assert schema['properties']['findingCorrections']['properties']['FINDING_0']['properties']['status'][
                'enum'] == ['withdrawn_review_error', 'resolved_by_change']
            payload = {'findingCorrections': {'FINDING_0': {'status': 'resolved_by_change',
                'evidenceRefs': [ref]}},
                'blockerResolutions': {'ISSUE_0': {'reason': 'contradicted_by_current_data', 'evidenceRefs': [ref]}}}
        responses.append(payload)
        return json.dumps(payload), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    if not changed:
        with pytest.raises(ValueError, match='relevant current change'):
            review._review_complete_draft(None, context, audited, messages, boundary, None)
    else:
        result = review._review_complete_draft(None, context, audited, messages, boundary, None)
        assert result['findings'] == []
        assert result['scopeResults']['execution']['blockerResolutions']['CONCERN_ORDER']['status'] == 'resolved_by_change'
    assert len(responses) == 2


def test_unsupported_optional_objective_does_not_discard_or_waive_review_finding(monkeypatch):
    equipment, messages, audited, context = setup_case()
    base_exercise = context['draft']['exercises'][0]
    for index in (1, 2):
        exercise = dict(base_exercise, id=f'EXERCISE_{index}', libraryDefinitionId=f'LIBRARY_{index}')
        context['draft']['exercises'].append(exercise)
        context['draft']['libraryDefinitions'][f'LIBRARY_{index}'] = dict(
            context['draft']['libraryDefinitions']['LIBRARY_0'])
        context['draft']['workouts'].append({'id': f'WORKOUT_{index}', 'name': f'Day {index}',
            'exerciseIds': [f'EXERCISE_{index}']})

    supported = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}
    unrelated = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_2'], 'minimumSessions': 2}
    context['redistributionObjectiveChoices'] = [supported, unrelated]
    calls, metrics = [], []

    class CaptureLogger:
        def log(self, message):
            metrics.append(message)

        def log_request(self, *args, **kwargs):
            pass

        def log_response(self, *args, **kwargs):
            pass

    def respond(client, request, **options):
        data = request_data(request)
        schema = options['output_schema']
        references = [item['_reviewRef'] for item in data['draft']['exercises'][:2]]
        second_session_ref = data['draft']['workouts'][1]['_reviewRef']
        findings = [
            {'message': 'Correct the cited exercise distribution.', 'reason': 'Keep this correction active.',
             'evidenceRefs': [references[0]], 'concernGroup': 'NEW', 'decisionId': 'none',
             'basis': 'uncertainty', 'disposition': 'repair', 'errorKind': 'none',
             'repairDimensions': ['prescription'], 'repairObjectiveChoiceIds': ['OBJECTIVE_0', 'OBJECTIVE_1']},
            {'message': 'Develop the other cited role.', 'reason': 'Keep this concern active too.',
             'evidenceRefs': [second_session_ref], 'concernGroup': 'NEW', 'decisionId': 'none',
             'basis': 'uncertainty', 'disposition': 'repair', 'errorKind': 'none',
             'repairDimensions': ['coverage'], 'repairObjectiveChoiceIds': ['OBJECTIVE_1']},
        ]
        calls.append(findings)
        return json.dumps(response_for(data, schema, findings)), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    result = review._review_complete_draft(None, context, audited, messages, boundary, CaptureLogger())

    assert len(calls) == 1
    assert [finding['action'] for finding in result['findings']] == ['repair', 'clarify']
    assert [group['disposition'] for group in result['assessment']['groups']] == ['repair', 'unresolved_capability']
    assert 'prescription' in result['assessment']['groups'][0]['repairDimensions']
    assert result['assessment']['groups'][0]['repairObjectives'] == [supported]
    assert result['assessment']['groups'][1]['repairDimensions'] == []
    assert result['assessment']['groups'][1]['repairObjectives'] == []

    from workout_generator_pkg.repair_contract import build_repair_contract
    unsupported_group_contract = build_repair_contract(
        result['assessment']['groups'][1]['repairObjectives'], audited['submittedDraft'],
        context['requirements'], [], requirements_id=audited['requirementsId'])
    assert unsupported_group_contract['redistributions'] == []
    diagnostic = next(metric for metric in metrics
        if 'independent_plan_review_unsupported_repair_objective' in metric)
    assert 'OBJECTIVE_1' in diagnostic
    assert 'findingRemainsActive' in diagnostic
