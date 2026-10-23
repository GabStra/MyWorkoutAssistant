import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _case():
    equipment, _, requirements, draft = planning_case()
    messages = requirement_messages(requirements)
    audited = audit_workout_plan(draft, equipment, messages)
    assert audited['passed']
    boundary = len(messages) - 1
    context = review._context(audited, messages, equipment, None, boundary)
    return equipment, messages, audited, boundary, context


def _finding(group, ref, *, basis='uncertainty', action='repair', message='A source-grounded concern.'):
    return {'concernGroup': group, 'basis': basis,
        'severity': 'blocking' if basis in ('established_violation', 'material_uncertainty') else 'warning',
        'action': action, 'decisionId': None, 'message': message, 'evidencePaths': [ref]}


def _run_discovery(monkeypatch, context, audited, messages, boundary, findings,
                   *, source_status='supported', resolutions=None, trace=None):
    captured = trace if trace is not None else {}

    def discover(client, request, **options):
        data = json.loads(request[-1]['content'])
        captured['data'] = data
        captured['schema'] = options['output_schema']
        source_schema = options['output_schema']['properties'].get('requirementAssessments', {}).get('properties', {})
        source_key = next(iter(source_schema), None)
        rows = findings(data) if callable(findings) else findings
        payload = {'findings': copy.deepcopy(rows)}
        if source_key:
            source_ref = data['sourceMessages'][source_key]['_reviewRef']
            payload['requirementAssessments'] = {key: {
                'status': source_status,
                'reason': 'The source is represented by the cited plan concern.' if source_status == 'needs_correction'
                    else 'The controlled candidate is consistent with this source.',
                'evidencePaths': [source_ref] if source_status == 'needs_correction'
                    else [data['audit']['_reviewRef']],
            } for key in source_schema}
        if resolutions is not None:
            payload['blockerResolutions'] = copy.deepcopy(resolutions(data) if callable(resolutions) else resolutions)
        from jsonschema import validate
        validate(payload, options['output_schema'])
        return json.dumps(payload), None, None

    def adjudicate(client, context_arg, receipt, logger=None, *, single_attempt=False, evidence_context=None):
        captured['adjudicated'] = True
        groups = []
        for index, item in enumerate(receipt['findings']):
            disposition = 'advisory' if item['action'] == 'advisory' else 'repair'
            groups.append({'findingIndexes': [index], 'disposition': disposition,
                'repairDimensions': ['ordering'] if disposition == 'repair' else [],
                'repairObjectives': [], 'reason': 'The cited concern is supported by this candidate.',
                'errorKind': 'none', 'authorityEvidenceRefs': [],
                'evidencePaths': list(dict.fromkeys([item['path'], *item['evidencePaths']]))})
        result = {'version': review.ASSESSMENT_VERSION,
            'inputHash': review.assessment_hash(receipt), 'groups': groups,
            'repairPlan': 'Correct the cited ordering issue.' if any(g['disposition'] == 'repair' for g in groups) else ''}
        return result

    monkeypatch.setattr(review, '_review_call', discover)
    monkeypatch.setattr(review, 'assess_findings', adjudicate)
    reviewed = review._review_complete_draft(None, context, audited, messages, boundary, None)
    return reviewed, captured


def test_same_group_rewordings_merge_and_distinct_same_path_concerns_do_not(monkeypatch):
    equipment, messages, audited, boundary, context = _case()
    rows = lambda data: [
        _finding('NEW_0', data['draft']['exercises'][0]['_reviewRef'], basis='established_violation', message='The sequence creates a recovery concern.'),
        _finding('NEW_0', data['draft']['exercises'][0]['_reviewRef'], basis='established_violation', message='Reworded: the same sequence may compromise recovery.'),
        _finding('NEW_1', data['draft']['exercises'][0]['_reviewRef'], basis='established_violation', message='A separate setup concern cites this same occurrence.'),
    ]
    receipt, _ = _run_discovery(monkeypatch, context, audited, messages, boundary, rows)
    assert len(receipt['findings']) == 2
    assert receipt['findings'][0]['concernGroupId'] != receipt['findings'][1]['concernGroupId']
    assert 'Reworded:' in receipt['findings'][0]['message']
    assert receipt['assessment']['groups'][0]['findingIndexes'] == [0]
    assert receipt['assessment']['groups'][1]['findingIndexes'] == [1]


def test_needs_correction_requires_native_source_cited_concern_not_synthetic_duplicate(monkeypatch):
    equipment, messages, audited, boundary, context = _case()
    def supported_finding(data):
        finding = _finding('NEW_0', data['draft']['exercises'][0]['_reviewRef'], basis='established_violation')
        finding['evidencePaths'].append(data['sourceMessages']['SOURCE_0']['_reviewRef'])
        return [finding]
    receipt, _ = _run_discovery(monkeypatch, context, audited, messages, boundary,
        supported_finding,
        source_status='needs_correction')
    assert len(receipt['findings']) == 1
    assert receipt['requirementAssessments']['SOURCE_0']['findingIndexes'] == [0]
    assert receipt['assessment']['groups'][0]['disposition'] == 'repair'

    with pytest.raises(ValueError, match='must be represented by a cited review concern'):
        _run_discovery(monkeypatch, context, audited, messages, boundary, lambda data: [], source_status='needs_correction')


@pytest.mark.parametrize('authority_kind', ['source', 'requirement', 'decision'])
def test_soft_tradeoff_is_terminal_only_with_same_group_authority_and_current_evidence(monkeypatch, authority_kind):
    equipment, messages, audited, boundary, context = _case()
    prior_id = 'CONCERN_previous'
    if authority_kind == 'decision':
        context['resolvedDecisions']['DECISION_0'] = {
            'choice': 'Keep the approved exercise choice.', 'sourceReferences': ['SOURCE_0'],
            'sourceCountAtResolution': len(context['sourceMessages'])}
    context['reviewChecklist'] = {'findings': {'OBLIGATION_previous': {
        'finding': {'concernGroupId': prior_id, 'severity': 'warning', 'basis': 'uncertainty',
            'action': 'repair', 'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
            'message': 'The optional distribution concern.', 'repair': '', 'muscleTargets': []},
        'changedDraftPaths': [], 'sourceCount': len(context['sourceMessages']),
    }}}
    def authority_ref(data):
        if authority_kind == 'source':
            return data['sourceMessages']['SOURCE_0']['_reviewRef']
        if authority_kind == 'requirement':
            return data['requirements']['executionRules'][0]['_reviewRef']
        return data['resolvedDecisions']['DECISION_0']['_reviewRef']
    def rows(data):
        source_ref = authority_ref(data)
        current_ref = data['draft']['exercises'][0]['_reviewRef']
        finding = _finding('ISSUE_0', source_ref, basis='soft_tradeoff', action='advisory',
            message='This optional distribution preference is a disclosed tradeoff.')
        finding['evidencePaths'].append(current_ref)
        if authority_kind == 'decision':
            finding['decisionId'] = 'DECISION_0'
        return [finding]
    def resolutions(data):
        source_ref = authority_ref(data)
        current_ref = data['draft']['exercises'][0]['_reviewRef']
        return {'ISSUE_0': {'status': 'accepted_soft_tradeoff', 'reason': 'The optional preference is explicitly disclosed.',
                    'evidencePaths': [source_ref, current_ref]}}
    receipt, _ = _run_discovery(monkeypatch, context, audited, messages, boundary, rows,
        resolutions=resolutions)
    assert receipt['scopeResults']['execution']['blockerResolutions']['OBLIGATION_previous']['status'] == 'accepted_soft_tradeoff'
    assert receipt['findings'][0]['concernGroupId'] == prior_id
    assert receipt['assessment']['groups'][0]['disposition'] == 'advisory'

    projected = copy.deepcopy(audited)
    projected['review'] = receipt
    audit_call = {'role': 'assistant', 'tool_calls': [{'id': 'reviewed', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]}
    history = [*messages, audit_call, {'role': 'tool', 'tool_call_id': 'reviewed',
        'content': json.dumps(projected)}]
    ledger = review._review_checklist(projected, history)
    assert list(ledger['acceptedSoftTradeoffs']) == [prior_id]
    accepted = ledger['acceptedSoftTradeoffs'][prior_id]
    assert accepted['finding']['basis'] == 'soft_tradeoff'
    assert accepted['assessment']['reason'] == 'The cited concern is supported by this candidate.'
    assert accepted['assessment']['evidencePaths']

    projected['reviewChecklist'] = copy.deepcopy(ledger)
    context2 = review._context(projected, history, equipment, None, boundary)
    context2['reviewChecklist']['acceptedSoftTradeoffs'][prior_id]['changedDraftPaths'] = [
        '/workouts/0/exercises/0']
    def strengthened(data):
        finding = _finding('TRADEOFF_0', data['draft']['exercises'][0]['_reviewRef'],
            basis='established_violation', message='The updated evidence now establishes a source conflict.')
        finding['evidencePaths'].append(data['sourceMessages']['SOURCE_0']['_reviewRef'])
        return [finding]
    stronger_review, _ = _run_discovery(monkeypatch, context2, projected, history, boundary, strengthened)
    assert stronger_review['findings'][0]['concernGroupId'] == prior_id
    stronger_result = copy.deepcopy(projected)
    stronger_result['review'] = stronger_review
    next_call = {'role': 'assistant', 'tool_calls': [{'id': 'reviewed-again', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]}
    stronger_history = [*history, next_call, {'role': 'tool', 'tool_call_id': 'reviewed-again',
        'content': json.dumps(stronger_result)}]
    reopened_ledger = review._review_checklist(stronger_result, stronger_history)
    assert not reopened_ledger['acceptedSoftTradeoffs']
    assert len(reopened_ledger['findings']) == 1
    assert next(iter(reopened_ledger['findings'].values()))['finding']['basis'] == 'established_violation'


@pytest.mark.parametrize('evidence_case', ['missing_authority', 'missing_current', 'invalid_decision_provenance'])
def test_soft_tradeoff_proof_is_checked_after_adjudication_before_terminal_acceptance(
        monkeypatch, evidence_case):
    equipment, messages, audited, boundary, context = _case()
    context['reviewChecklist'] = {'findings': {'OBLIGATION_previous': {
        'finding': {'concernGroupId': 'CONCERN_previous', 'severity': 'warning', 'basis': 'uncertainty',
            'action': 'repair', 'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
            'message': 'An unresolved optional distribution concern.', 'repair': '', 'muscleTargets': []},
        'changedDraftPaths': [], 'sourceCount': len(context['sourceMessages']),
    }}}
    if evidence_case == 'invalid_decision_provenance':
        context['resolvedDecisions']['DECISION_0'] = {
            'choice': 'Keep the approved exercise choice.', 'sourceReferences': ['SOURCE_MISSING'],
            'sourceCountAtResolution': len(context['sourceMessages'])}
    trace = {}

    def rows(data):
        if evidence_case == 'missing_authority':
            refs = [data['draft']['exercises'][0]['_reviewRef']]
        else:
            authority = (data['resolvedDecisions']['DECISION_0']['_reviewRef']
                         if evidence_case == 'invalid_decision_provenance'
                         else data['requirements']['executionRules'][0]['_reviewRef'])
            refs = [authority]
            if evidence_case != 'missing_current':
                refs.append(data['draft']['exercises'][0]['_reviewRef'])
        finding = _finding('ISSUE_0', refs[0], basis='soft_tradeoff', action='advisory')
        finding['evidencePaths'] = refs
        if evidence_case == 'invalid_decision_provenance':
            finding['decisionId'] = 'DECISION_0'
        return [finding]

    def resolutions(data):
        return {'ISSUE_0': {'status': 'accepted_soft_tradeoff',
            'reason': 'Accept the optional tradeoff.', 'evidencePaths': rows(data)[0]['evidencePaths']}}

    with pytest.raises(ValueError, match='soft tradeoff'):
        _run_discovery(monkeypatch, context, audited, messages, boundary, rows,
            resolutions=resolutions, trace=trace)
    assert trace['adjudicated'] is True


def test_withdrawn_resolution_removes_prior_accepted_soft_tradeoff():
    equipment, messages, audited, boundary, _ = _case()
    concern_id = 'CONCERN_withdrawn'
    draft = copy.deepcopy(audited['submittedDraft'])
    finding = {'concernGroupId': concern_id, 'severity': 'warning', 'basis': 'soft_tradeoff',
        'action': 'advisory', 'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
        'message': 'A disclosed optional tradeoff.'}
    first = copy.deepcopy(audited)
    first['reviewChecklist'] = {'findings': {'OBLIGATION_previous': {
        'finding': {**finding, 'basis': 'uncertainty', 'action': 'repair'},
        'changedDraftPaths': [], 'sourceCount': len(messages)}}, 'acceptedSoftTradeoffs': {}}
    first['submittedDraft'] = draft
    first['review'] = {'version': review.REVIEW_VERSION, 'instructionBoundary': boundary,
        'findings': [finding], 'inputHash': 'first',
        'assessment': {'groups': [{'findingIndexes': [0], 'disposition': 'advisory',
            'reason': 'Accepted with disclosure.', 'evidencePaths': ['/draft/exercises/0']}]},
        'scopeResults': {'execution': {'blockerResolutions': {'OBLIGATION_previous': {
            'status': 'accepted_soft_tradeoff', 'reason': 'Accepted with disclosure.',
            'evidencePaths': ['/draft/exercises/0']}}}}}
    first_call = {'id': 'first-audit', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}
    first_history = [*messages, {'role': 'assistant', 'tool_calls': [first_call]},
        {'role': 'tool', 'tool_call_id': 'first-audit', 'content': json.dumps(first)}]

    latest = copy.deepcopy(first)
    latest['review'] = {'version': review.REVIEW_VERSION, 'instructionBoundary': boundary,
        'findings': [], 'inputHash': 'withdrawn', 'scopeResults': {'execution': {
            'blockerResolutions': {'OBLIGATION_previous': {
                'status': 'withdrawn_review_error', 'reason': 'The earlier finding was a review error.',
                'evidencePaths': ['/draft/exercises/0']}}}}}
    latest_call = {'id': 'latest-audit', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}
    history = [*first_history, {'role': 'assistant', 'tool_calls': [latest_call]},
        {'role': 'tool', 'tool_call_id': 'latest-audit', 'content': json.dumps(latest)}]

    ledger = review._review_checklist(latest, history)
    assert ledger is None


def test_hard_carried_finding_cannot_use_soft_tradeoff_terminal_status():
    context = {'reviewChecklist': {}}
    finding = {'basis': 'established_violation', 'severity': 'blocking', 'action': 'repair'}
    with pytest.raises(ValueError, match='nonblocking'):
        review._validate_carried_resolution({'status': 'accepted_soft_tradeoff', 'action': 'none'}, finding)


def test_accepted_tradeoff_stays_closed_until_its_evidence_changes_then_can_be_reopened(monkeypatch):
    equipment, messages, audited, boundary, context = _case()
    concern_id = 'CONCERN_tradeoff'
    context['reviewChecklist'] = {'findings': {}, 'acceptedSoftTradeoffs': {concern_id: {
        'finding': {'concernGroupId': concern_id, 'severity': 'warning', 'basis': 'soft_tradeoff',
            'action': 'advisory', 'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
            'message': 'Previously accepted soft preference.'},
        'assessment': {'reason': 'Accepted with disclosed tradeoff.', 'evidencePaths': ['/draft/exercises/0']},
        'changedDraftPaths': [], 'sourceCount': len(context['sourceMessages']),
    }}}
    unchanged, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, lambda data: [])
    assert not any(value.startswith('TRADEOFF_') for value in
        captured['schema']['properties']['findings']['items']['properties']['concernGroup']['enum'])

    context['reviewChecklist']['acceptedSoftTradeoffs'][concern_id]['changedDraftPaths'] = ['/workouts/0/name']
    unchanged, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, lambda data: [])
    assert not any(value.startswith('TRADEOFF_') for value in
        captured['schema']['properties']['findings']['items']['properties']['concernGroup']['enum'])

    context['reviewChecklist']['acceptedSoftTradeoffs'][concern_id]['changedDraftPaths'] = ['/workouts/0/exercises/0']
    def stronger(data):
        return [_finding('TRADEOFF_0', data['draft']['exercises'][0]['_reviewRef'],
            basis='established_violation', message='New current evidence establishes a source conflict.')]
    reopened, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, stronger)
    assert 'TRADEOFF_0' in captured['schema']['properties']['findings']['items']['properties']['concernGroup']['enum']
    assert reopened['findings'][0]['concernGroupId'] == concern_id
    assert reopened['assessment']['groups'][0]['disposition'] == 'repair'


def test_saved_msg58_60_duplicate_cluster_uses_explicit_identity_not_message_text():
    path = Path('build/workout_joint_priority_solver_20261023/fresh_e2e_role_keys_continuation3/workouts/conversation_sessions/3ba7d8ff-f809-4b0d-9b2d-ee88bdbcc72f/messages.json')
    messages = json.loads(path.read_text(encoding='utf-8'))
    first = json.loads(messages[58]['content'])['review']['findings']
    second = json.loads(messages[60]['content'])['review']['findings']
    assert len(first) == 7 and len(second) == 10

    # The retained reviewer output restates the same B-session concentration
    # with changed wording; the local explicit group is supplied by the new
    # review response, while independent rest concerns retain separate IDs.
    original = {**first[0], 'concernGroupId': 'CONCERN_B_cluster'}
    reworded = {**second[8], 'concernGroupId': 'CONCERN_B_cluster'}
    rest = {**second[1], 'concernGroupId': 'CONCERN_B_transition'}
    assert original['message'] != reworded['message']
    draft = {'workouts': []}
    assert review._review_obligation_signature(original, draft) == review._review_obligation_signature(reworded, draft)
    assert review._review_obligation_signature(original, draft) != review._review_obligation_signature(rest, draft)

    def receipt(finding):
        return {'requirementsId': 'requirements', 'libraryFingerprint': 'library',
            'historyFingerprint': 'history', 'resolvedDecisions': {}, 'currentDraftId': 'candidate',
            'submittedDraft': draft, 'reviewChecklist': {'findings': {}},
            'review': {'version': review.REVIEW_VERSION, 'instructionBoundary': 0,
                'findings': [finding], 'assessment': {'groups': [
                    {'findingIndexes': [0], 'disposition': 'repair'}]}, 'scopeResults': {'execution': {}}}}
    first_result = receipt(original)
    second_result = receipt(reworded)
    first_call = {'id': 'audit-58', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}
    second_call = {'id': 'audit-60', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}
    history = [
        {'role': 'user', 'content': 'Original training request.'},
        {'role': 'assistant', 'tool_calls': [first_call]},
        {'role': 'tool', 'tool_call_id': 'audit-58', 'content': json.dumps(first_result)},
        {'role': 'assistant', 'tool_calls': [second_call]},
        {'role': 'tool', 'tool_call_id': 'audit-60', 'content': json.dumps(second_result)},
    ]
    ledger = review._review_checklist(second_result, history)
    assert ledger is not None and len(ledger['findings']) == 1
    assert next(iter(ledger['findings'].values()))['finding']['concernGroupId'] == 'CONCERN_B_cluster'
