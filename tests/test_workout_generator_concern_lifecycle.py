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
        source_schema = options['output_schema']['properties'].get('sourceCoverage', {}).get('properties', {})
        source_key = next(iter(source_schema), None)
        rows = findings(data) if callable(findings) else findings
        payload = {'findings': copy.deepcopy(rows)}
        payload['sourceCoverage'] = {key: True for key in source_schema}
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


def test_python_assigns_each_new_finding_a_distinct_identity(monkeypatch):
    equipment, messages, audited, boundary, context = _case()
    rows = lambda data: [
        {'message': message, 'reason': 'The current sequence is source-relevant.',
         'evidenceRefs': [data['draft']['exercises'][0]['_reviewRef']], 'concernGroup': 'NEW',
         'decisionId': 'none', 'basis': 'established_violation', 'disposition': 'repair',
         'errorKind': 'none', 'repairDimensions': ['ordering'], 'repairObjectiveChoiceIds': []}
        for message in ('The sequence creates a recovery concern.',
            'Reworded: the same sequence may compromise recovery.',
            'A separate setup concern cites this same occurrence.')
    ]
    receipt, _ = _run_discovery(monkeypatch, context, audited, messages, boundary, rows)
    assert len(receipt['findings']) == 3
    assert [finding['concernGroup'] for finding in receipt['findings']] == ['NEW_0', 'NEW_1', 'NEW_2']
    assert len({finding['concernGroupId'] for finding in receipt['findings']}) == 3
    assert [group['findingIndexes'] for group in receipt['assessment']['groups']] == [[0], [1], [2]]


def test_reused_new_marker_cannot_merge_different_dispositions(monkeypatch):
    equipment, messages, audited, boundary, context = _case()
    def rows(data):
        ref = data['draft']['exercises'][0]['_reviewRef']
        return [
            {'message': 'A supported candidate defect.', 'reason': 'A source conflict remains.',
             'evidenceRefs': [ref], 'concernGroup': 'NEW', 'decisionId': 'none',
             'basis': 'established_violation', 'disposition': 'repair', 'errorKind': 'none',
             'repairDimensions': ['ordering'], 'repairObjectiveChoiceIds': []},
            {'message': 'A separate uncertain concern.', 'reason': 'Personal response is unknown.',
             'evidenceRefs': [ref], 'concernGroup': 'NEW', 'decisionId': 'none',
             'basis': 'uncertainty', 'disposition': 'advisory', 'errorKind': 'none'},
        ]
    receipt, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, rows)
    assert all('NEW' in variant['properties']['concernGroup']['enum']
        for variant in captured['schema']['properties']['findings']['items']['anyOf'])
    assert [finding['concernGroup'] for finding in receipt['findings']] == ['NEW_0', 'NEW_1']
    assert [group['disposition'] for group in receipt['assessment']['groups']] == ['repair', 'advisory']


def test_needs_correction_requires_native_source_cited_concern_not_synthetic_duplicate(monkeypatch):
    equipment, messages, audited, boundary, context = _case()
    def supported_finding(data):
        finding = _finding('NEW', data['draft']['exercises'][0]['_reviewRef'], basis='established_violation')
        finding['evidencePaths'].append(data['sourceMessages']['SOURCE_0']['_reviewRef'])
        return [finding]
    receipt, _ = _run_discovery(monkeypatch, context, audited, messages, boundary,
        supported_finding,
        source_status='needs_correction')
    assert len(receipt['findings']) == 1
    assert receipt['requirementAssessments']['SOURCE_0']['findingIndexes'] == [0]
    assert receipt['assessment']['groups'][0]['disposition'] == 'repair'

    empty, _ = _run_discovery(monkeypatch, context, audited, messages, boundary, lambda data: [])
    assert empty['sourceCoverage'] == {'SOURCE_0': True}


def test_terminal_soft_tradeoff_needs_same_concern_adjudication_not_generic_or_unrelated_decision():
    concern_id = 'CONCERN_distribution'
    paths = ['/requirements/executionRules/0', '/draft/exercises/0']
    context = {'sourceMessages': {'SOURCE_0': {'role': 'user'}}, 'resolvedDecisions': {}}
    finding = {'basis': 'soft_tradeoff', 'concernGroupId': concern_id, 'decisionId': None}

    assert not review._soft_tradeoff_terminal_evidence(context, finding, paths)

    context['resolvedDecisions']['DECISION_0'] = {
        'choice': 'Accept this concern for this candidate.', 'sourceReferences': ['SOURCE_0'],
        'sourceCountAtResolution': 1, 'acceptedConcernGroupId': concern_id}
    finding['decisionId'] = 'DECISION_0'
    assert review._soft_tradeoff_terminal_evidence(context, finding,
        ['/resolvedDecisions/DECISION_0', '/draft/exercises/0'])
    context['sourceMessages']['SOURCE_1'] = {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'}
    assert review._soft_tradeoff_terminal_evidence(context, finding,
        ['/resolvedDecisions/DECISION_0', '/draft/exercises/0'])
    context['resolvedDecisions']['DECISION_0']['acceptedConcernGroupId'] = 'CONCERN_unrelated'
    assert not review._soft_tradeoff_terminal_evidence(context, finding,
        ['/resolvedDecisions/DECISION_0', '/draft/exercises/0'])

    context['reviewChecklist'] = {'acceptedSoftTradeoffs': {concern_id: {
        'finding': {'concernGroupId': concern_id, 'basis': 'soft_tradeoff'}}}}
    finding['decisionId'] = None
    assert review._soft_tradeoff_terminal_evidence(context, finding, ['/draft/exercises/0'])
    finding['concernGroupId'] = 'CONCERN_other'
    assert not review._soft_tradeoff_terminal_evidence(context, finding, ['/draft/exercises/0'])


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

    def unchanged_echo(data):
        return [{'message': 'Previously accepted soft preference.',
            'reason': 'No new evidence changes the tradeoff.',
            'evidenceRefs': [data['draft']['exercises'][0]['_reviewRef']],
            'concernGroup': 'TRADEOFF_0', 'decisionId': 'none', 'basis': 'soft_tradeoff',
            'disposition': 'advisory', 'errorKind': 'none'}]

    unchanged, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, unchanged_echo)
    assert captured['data']['previousAcceptedSoftTradeoffs']['TRADEOFF_0']['changedEvidenceRefs'] == []
    assert unchanged['findings'] == []

    context['reviewChecklist']['acceptedSoftTradeoffs'][concern_id]['changedDraftPaths'] = ['/workouts/0/name']
    unchanged, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, unchanged_echo)
    assert captured['data']['previousAcceptedSoftTradeoffs']['TRADEOFF_0']['changedEvidenceRefs'] == []
    assert unchanged['findings'] == []

    context['reviewChecklist']['acceptedSoftTradeoffs'][concern_id]['changedDraftPaths'] = ['/workouts/0/exercises/0']
    def stronger(data):
        return [{'message': 'New current evidence establishes a source conflict.',
            'reason': 'The changed exercise now conflicts with the current source.',
            'evidenceRefs': [data['draft']['exercises'][0]['_reviewRef']],
            'concernGroup': 'TRADEOFF_0', 'decisionId': 'none', 'basis': 'established_violation',
            'disposition': 'repair', 'errorKind': 'none', 'repairDimensions': ['ordering'],
            'repairObjectiveChoiceIds': []}]
    reopened, captured = _run_discovery(monkeypatch, context, audited, messages, boundary, stronger)
    assert 'TRADEOFF_0' in captured['data']['previousAcceptedSoftTradeoffs']
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


def test_source_only_requirements_refresh_carries_obligation_only_with_reused_same_candidate_proof():
    _, messages, audited, _, _ = _case()
    old_requirements_call, old_requirements = review._latest_result(messages, 'set_workout_requirements')
    prior = copy.deepcopy(audited)
    prior['requirementsId'] = old_requirements['requirementsId']
    prior['submittedDraft']['requirementsId'] = old_requirements['requirementsId']
    prior['resolvedDecisions'] = {}
    prior['coordinatedJointPlanning'] = {
        'problemFingerprint': 'same-objective-domain',
        'solvedPrescriptionHash': 'same-solved-prescription',
    }
    prior_finding = {'message': 'The prior setup assertion needs fresh adjudication.',
        'reason': 'Earlier review treated unknown station spacing as a defect.',
        'severity': 'blocking', 'basis': 'material_uncertainty', 'action': 'repair',
        'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
        'concernGroupId': 'CONCERN_setup', 'reviewScope': 'semantic'}
    prior['review'] = {'version': review.REVIEW_VERSION, 'instructionBoundary': len(messages) - 1,
        'inputHash': 'prior-review', 'findings': [prior_finding],
        'assessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair'}]},
        'scopeResults': {}}
    audit_call = {'id': 'prior-audit', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}
    history = [*messages, {'role': 'assistant', 'tool_calls': [audit_call]},
        {'role': 'tool', 'tool_call_id': 'prior-audit', 'content': json.dumps(prior)},
        {'role': 'user', 'content': 'Clarification: station positions are unknown; accept this setup uncertainty for this candidate.'}]
    refresh_call = {'id': 'refresh-requirements', 'type': 'function',
        'function': {'name': 'set_workout_requirements', 'arguments': '{}'}}
    refreshed_requirements = copy.deepcopy(old_requirements)
    refreshed_requirements['requirementsId'] = 'REQUIREMENTS_source_refresh'
    history.extend([{'role': 'assistant', 'tool_calls': [refresh_call]},
        {'role': 'tool', 'tool_call_id': 'refresh-requirements',
            'content': json.dumps(refreshed_requirements)}])

    current = copy.deepcopy(audited)
    current['requirementsId'] = 'REQUIREMENTS_source_refresh'
    current['submittedDraft']['requirementsId'] = 'REQUIREMENTS_source_refresh'
    current['resolvedDecisions'] = {'DECISION_new': {'choice': 'Accept disclosed setup uncertainty.'}}
    current['coordinatedJointPlanning'] = {
        'problemFingerprint': 'same-objective-domain',
        'solvedPrescriptionHash': 'same-solved-prescription',
        'reusedForValidatedCandidate': True,
    }
    carried = review._review_checklist(current, history)
    assert carried is not None
    assert len(carried['findings']) == 1
    assert next(iter(carried['findings'].values()))['finding']['concernGroupId'] == 'CONCERN_setup'

    changed_proof = copy.deepcopy(current)
    changed_proof['coordinatedJointPlanning']['problemFingerprint'] = 'different-objective-domain'
    assert review._review_checklist(changed_proof, history) is None


def test_saved_native_source_refresh_retains_prior_setup_obligation():
    path = Path('build/workout_concentration_20261026/review_source_correction_resume_v3/workouts/conversation_sessions/71cc1068-f6a3-4056-945b-99fec5c88a4d/messages.json')
    messages = json.loads(path.read_text(encoding='utf-8'))
    current = next(json.loads(message['content']) for message in reversed(messages)
        if message.get('role') == 'tool' and isinstance(message.get('content'), str)
        and message['content'].startswith('{')
        and (lambda receipt: isinstance(receipt.get('submittedDraft'), dict)
             and receipt.get('coordinatedJointPlanning', {}).get('reusedForValidatedCandidate'))(
                 json.loads(message['content'])))

    ledger = review._review_checklist(current, messages)
    assert ledger is not None
    setup_keys = [key for key, entry in ledger['findings'].items()
        if 'Session A equipment sequencing' in entry['finding'].get('message', '')]
    assert len(setup_keys) == 1
    assert ledger['findings'][setup_keys[0]]['finding']['action'] == 'repair'
    issue_aliases = {f'ISSUE_{index}': key for index, key in enumerate(sorted(ledger['findings']))}
    assert any(key == setup_keys[0] and alias.startswith('ISSUE_')
        for alias, key in issue_aliases.items())
