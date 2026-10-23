import copy
import json

import pytest

from workout_generator_pkg import review_assessment as assessment
from workout_generator_pkg.requirement_accounting import alternative_evaluation_contract
from workout_generator_pkg.repair_capabilities import repair_capability_contract


PATH = '/auditTargets/weeklyEffectiveSets/shoulders/maximum'


def records():
    original = {'requirementsId': 'REQ_ORIGINAL', 'restrictionPolicy': {'excludedDefinitionIds': ['excluded']},
        'requirements': {'auditTargets': {'weeklyEffectiveSets': {'shoulders': {'minimum': 15, 'maximum': 18}},
            'maximumSessionSeconds': 5400}, 'sessionsPerWeek': 3,
            'requirementAccounting': [{'priority': 'negotiable', 'enforcement': 'constraint',
                'requirementPaths': [PATH], 'relaxationDirection': 'raise_maximum',
                'sourceReferences': ['SOURCE_7']}]}}
    candidate = copy.deepcopy(original)
    candidate['requirementsId'] = 'REQ_PROPOSED'
    candidate['requirements']['auditTargets']['weeklyEffectiveSets']['shoulders']['maximum'] = 21
    candidate['proposedAlternative'] = {'originalRequirementsId': original['requirementsId'],
        'changes': [{'path': PATH, 'from': 18, 'to': 21}], 'requiresUserApproval': True}
    return original, candidate


def context_and_review():
    original, candidate = records()
    context = {'evaluationContract': alternative_evaluation_contract(original, candidate),
        'requirements': candidate['requirements'], 'repairCapabilityContract': repair_capability_contract(),
        'resolvedDecisions': {'DECISION_0': {'choice': 'Keep shoulders inside 15-18 and retain lateral raises.'}},
        'draft': {'programGuidance': 'Shoulders remain inside 15-18.'},
        'audit': {'weeklyVolume': {'shoulders': 21}}}
    review = {'inputHash': 'CURRENT_CANDIDATE', 'findings': [
        {'severity': 'blocking', 'action': 'clarify', 'message': '21 contradicts guidance and old 18 ceiling.'}]}
    return context, review


def test_contract_scopes_only_authorized_override_without_accepting_or_mutating_requirements():
    original, candidate = records()
    before = copy.deepcopy((original, candidate))
    contract = alternative_evaluation_contract(original, candidate)
    assert contract['approval'] == {'status': 'pending', 'gate': 'after_full_validation', 'owner': 'alternative_acceptance'}
    assert contract['proposedOverrides'] == [{'path': PATH, 'from': 18, 'to': 21}]
    assert contract['originalRequirementsHash'] != contract['evaluationRequirementsHash']
    assert 'any other clause' in contract['decisionScope']
    assert (original, candidate) == before


@pytest.mark.parametrize('change', ['minimum', 'duration', 'frequency', 'equipment', 'from', 'permission', 'unlisted', 'duplicate', 'direction'])
def test_contract_rejects_changes_outside_bound_permission(change):
    original, candidate = records()
    if change == 'minimum':
        candidate['requirements']['auditTargets']['weeklyEffectiveSets']['shoulders']['minimum'] = 12
    elif change == 'duration':
        candidate['requirements']['auditTargets']['maximumSessionSeconds'] = 6000
    elif change == 'frequency':
        candidate['requirements']['sessionsPerWeek'] = 2
    elif change == 'equipment':
        candidate['restrictionPolicy']['excludedDefinitionIds'] = []
    elif change == 'from':
        candidate['proposedAlternative']['changes'][0]['from'] = 17
    elif change == 'permission':
        original['requirements']['requirementAccounting'][0]['priority'] = 'mandatory'
    elif change == 'unlisted':
        candidate['proposedAlternative']['changes'] = []
    elif change == 'duplicate':
        candidate['proposedAlternative']['changes'] *= 2
    else:
        candidate['requirements']['auditTargets']['weeklyEffectiveSets']['shoulders']['maximum'] = 17
        candidate['proposedAlternative']['changes'][0]['to'] = 17
    with pytest.raises(ValueError):
        alternative_evaluation_contract(original, candidate)


def test_stale_guidance_and_pending_approval_cannot_be_classified_as_missing_execution(monkeypatch):
    context, review = context_and_review()
    requests = []

    def respond(_client, request, **_options):
        requests.append(request)
        # DeepSeek strict tool parameters reject enum-only property schemas.
        resolution_schema = _options['output_schema']['properties']['groups']['items']['properties']['resolution']
        assert resolution_schema['properties']['kind']['type'] == 'string'
        group = {'findingIndexes': [0], 'repairObjectives': [], 'errorKind': 'none',
            'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': [], 'reason': 'Reconcile the complete proposal.'}
        if len(requests) == 1:
            group.update(disposition='unresolved_capability', repairDimensions=[],
                resolution={'kind': 'approval', 'requirementPaths': [PATH], 'unsupportedBehavior': None})
        else:
            assert 'alternative_acceptance after full validation' in json.loads(request[-1]['content'])['validationError']
            group.update(disposition='repair', repairDimensions=['program_guidance'],
                resolution={'kind': 'candidate_edit', 'requirementPaths': [PATH], 'unsupportedBehavior': None})
        return json.dumps({'groups': [group], 'repairPlan': 'Describe 21 as the proposed ceiling; preserve minimum 15 and await approval.'}), None, None

    monkeypatch.setattr(assessment, '_review_call', respond)
    result = assessment.assess_findings(None, context, review)
    assert len(requests) == 2
    assert result['groups'][0]['disposition'] == 'repair'
    assert result['groups'][0]['repairDimensions'] == ['program_guidance']
    assert review['findings'][0]['severity'] == 'blocking'
    assert context['evaluationContract']['approval']['status'] == 'pending'
    assert context['draft']['programGuidance'] == 'Shoulders remain inside 15-18.'
    supplied = json.loads(requests[0][-1]['content'])['context']
    assert supplied['evaluationContract']['proposedOverrides'][0]['to'] == 21


@pytest.mark.parametrize('behavior', ['alternative_acceptance', 'program_guidance', 'hypothetical_alternative_evaluation', 'automatic_load_reduction'])
def test_unsupported_behavior_is_distinct_from_supported_workflow_and_edits(behavior):
    context, review = context_and_review()
    group = {'findingIndexes': [0], 'disposition': 'unresolved_capability', 'repairDimensions': [],
        'reason': 'The source requires behavior the app cannot execute.',
        'evidencePaths': ['/requirements/sessionsPerWeek', '/draft'],
        'resolution': {'kind': 'unsupported_execution', 'requirementPaths': [], 'unsupportedBehavior': behavior}}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [group], 'repairPlan': ''}
    if behavior == 'automatic_load_reduction':
        assert assessment.validate_assessment(review, context)['groups'][0]['disposition'] == 'unresolved_capability'
    else:
        with pytest.raises(ValueError, match='supported workflow/edit'):
            assessment.validate_assessment(review, context)


def test_numeric_override_alone_is_not_an_unsupported_execution_capability():
    context, review = context_and_review()
    group = {'findingIndexes': [0], 'disposition': 'unresolved_capability', 'repairDimensions': [],
        'reason': 'Needs approval to change the shoulder maximum.',
        'evidencePaths': ['/requirements/auditTargets', '/audit/weeklyVolume'],
        'resolution': {'kind': 'unsupported_execution', 'requirementPaths': [PATH], 'unsupportedBehavior': 'change_target'}}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [group], 'repairPlan': ''}
    with pytest.raises(ValueError, match='evaluation criteria'):
        assessment.validate_assessment(review, context)


@pytest.mark.parametrize('next_proposal', [False, True])
def test_review_binds_accepted_requirement_results_and_distinguishes_next_pending_proposal(monkeypatch, next_proposal):
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.planning_tools import audit_workout_plan
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, original, draft = planning_case()
    path = '/auditTargets/weeklyEffectiveSets/chest/maximum'
    original['requirements']['requirementAccounting'] = [{'instruction': 'May propose higher ceilings.',
        'priority': 'negotiable', 'enforcement': 'constraint', 'requirementPaths': [path],
        'sourceReferences': ['SOURCE_0'], 'relaxationDirection': 'raise_maximum', 'reason': 'Approved permission.'}]
    accepted = copy.deepcopy(original)
    accepted.update(requirementsId='REQ_ACCEPTED', approvedAlternativeId='ALT_1', passed=True)
    accepted['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] = 8
    accepted['proposedAlternative'] = {'originalRequirementsId': original['requirementsId'],
        'changes': [{'path': path, 'from': 6, 'to': 8}],
        'approvedAlternativeId': 'ALT_1', 'requiresUserApproval': False}

    def recorded(record, name, identifier):
        turns = requirement_messages(record)
        for turn in turns:
            for call in turn.get('tool_calls', []):
                call['id'] = identifier
                call['function']['name'] = name
            if 'tool_call_id' in turn:
                turn['tool_call_id'] = identifier
        return turns

    messages = recorded(original, 'set_workout_requirements', 'original')
    messages += [{'role': 'assistant', 'content': 'Validated alternative: maximum 8; minimum unchanged.',
        'canonicalAlternativePreview': 'ALT_1'}, {'role': 'user', 'content': 'APPROVE ALTERNATIVE ALT_1'}]
    messages += recorded(accepted, 'accept_workout_alternative', 'accept')
    current = accepted
    if next_proposal:
        current = copy.deepcopy(accepted)
        current.update(requirementsId='REQ_NEXT_PROPOSAL')
        current.pop('approvedAlternativeId')
        current['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] = 10
        current['proposedAlternative'] = {'originalRequirementsId': accepted['requirementsId'],
            'changes': [{'path': path, 'from': 8, 'to': 10}], 'requiresUserApproval': True}
        messages += recorded(current, 'set_workout_requirements', 'next')
    draft['requirementsId'] = current['requirementsId']
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    context = plan_review._context(result, messages, equipment, None, len(messages) - 1)
    expected = 'pending' if next_proposal else 'approved'
    assert context['evaluationContract']['approval']['status'] == expected
    assert context['alternativeReview']['approvalStatus'] == expected
    assert context['alternativeReview']['mode'] == (
        'hypothetical_candidate_merit' if next_proposal else 'approved_candidate_merit')
    assert context['evaluationContract']['originalRequirementsId'] == (
        accepted['requirementsId'] if next_proposal else original['requirementsId'])
    calls = []
    def respond(_client, request, **_options):
        calls.append(request)
        return json.dumps({'findings': []}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)
    plan_review._review_part(None, 'execution', plan_review._execution_review_context(context),
        context, result, messages, len(messages) - 1, None)
    prompt = calls[0][0]['content']
    assert ('Pending approval is expected and MUST NOT' in prompt) is next_proposal
    if not next_proposal:
        assert 'do not request a second acceptance' in prompt
        assert 'already been approved' in context['alternativeReview']['instruction']

@pytest.mark.parametrize('legacy_cache', [False, 'missing', 'malformed'])
def test_alternative_confirmation_preserves_new_decision_and_objectives_on_resume(monkeypatch, legacy_cache):
    from workout_generator_pkg import plan_review
    context, review = context_and_review()
    context['draft'].update(exercises=[{'id': 'EXERCISE_0'}], workouts=[{}, {}])
    context['sourceMessages'] = {}
    review['findings'] = [
        {'severity': 'blocking', 'reviewScope': 'execution', 'message': 'Disputed claim.'},
        {'severity': 'blocking', 'reviewScope': 'execution', 'message': 'Another disputed claim.'}]
    group = {'findingIndexes': [0, 1], 'disposition': 'withdrawn_review_error',
        'repairDimensions': [], 'reason': 'Source contradicts old claims.',
        'errorKind': 'contradicted_by_current_data', 'evidencePaths': ['/requirements', '/draft'],
        'resolution': {'kind': 'review_error', 'requirementPaths': [], 'unsupportedBehavior': None}}
    group['evidenceHash'] = assessment._error_evidence(context, group)
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [group], 'repairPlan': ''}
    objectives = [{'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}]
    decisions = {
        'DISPUTE_0': {'status': 'open', 'disposition': 'repair', 'repairDimensions': ['prescription'],
            'repairObjectives': objectives, 'reason': 'Redistribute existing work.', 'evidencePaths': ['/draft'],
            'resolution': {'kind': 'candidate_edit', 'requirementPaths': [], 'unsupportedBehavior': None}},
        'DISPUTE_1': {'status': 'withdrawn_review_error', 'disposition': 'withdrawn_review_error',
            'repairDimensions': [], 'repairObjectives': [], 'reason': 'Source contradicts this claim.',
            'evidencePaths': ['/requirements', '/draft'],
            'resolution': {'kind': 'review_error', 'requirementPaths': [], 'unsupportedBehavior': None}}}
    cached = copy.deepcopy(decisions)
    if legacy_cache == 'missing':
        cached['DISPUTE_0'].pop('resolution')
    elif legacy_cache == 'malformed':
        cached['DISPUTE_0']['resolution']['kind'] = 'unknown'
    review['confirmationProgress'] = {'inputHash': review['inputHash'],
        'assessmentHash': plan_review._hash(review['assessment']), 'outcomes': {'execution': {
            'disputeIds': sorted(decisions), 'resolutions': cached}}}
    calls = []
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda context: {})
    def confirm(*args):
        calls.append(True)
        return {'findings': [], 'blockerResolutions': copy.deepcopy(decisions)}
    monkeypatch.setattr(plan_review, '_review_part', confirm)
    plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)
    checked = assessment.validate_assessment(review, context, require_confirmation=True)
    repaired = next(g for g in checked['groups'] if g['disposition'] == 'repair')
    assert repaired['resolution']['kind'] == 'candidate_edit'
    assert repaired['repairObjectives'] == objectives
    assert len(calls) == int(bool(legacy_cache))
    assert 'confirmationProgress' not in review
    assert len(checked['groups']) == 2

def test_alternative_confirmation_wire_contract_corrects_stale_classification(monkeypatch):
    from workout_generator_pkg import plan_review
    context, _ = context_and_review()
    context['draft'].update(exercises=[{'id': 'EXERCISE_0'}], workouts=[{'id': 'WORKOUT_0', 'name': 'A'}, {'id': 'WORKOUT_1', 'name': 'B'}])
    context['auditPolicy'] = {'supportedMuscleTargets': []}
    context['sourceMessages'] = {}
    part = {'confirmationOnly': True, 'previousBlockingFindings': {
        'DISPUTE_0': {'severity': 'blocking', 'message': 'Disputed claim.'}}}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), {'FACT_0': '/draft'}))
    monkeypatch.setattr(plan_review, '_review_pointer', lambda context, path, root='/draft': path)
    monkeypatch.setattr(plan_review, '_review_views', lambda *args: None)
    calls = []
    def respond(client, request, **options):
        calls.append((request, options))
        return json.dumps({'findings': [], 'blockerResolutions': {'ISSUE_0': {
            'status': 'open', 'disposition': 'repair', 'repairDimensions': ['program_guidance'],
            'repairObjectives': [], 'reason': 'Correct the stale guidance.', 'evidencePaths': ['FACT_0'],
            'resolution': {'kind': 'review_error' if len(calls) == 1 else 'candidate_edit',
                'requirementPaths': [], 'unsupportedBehavior': None}}}}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)
    checked = plan_review._review_part(None, 'execution', part, context, {}, [], 0, None)
    assert len(calls) == 2
    schema = calls[0][1]['output_schema']['properties']['blockerResolutions']['properties']['ISSUE_0']
    assert {'resolution', 'repairObjectives'} <= set(schema['required'])
    assert schema['properties']['resolution']['properties']['kind']['type'] == 'string'
    assert checked['blockerResolutions']['DISPUTE_0']['resolution']['kind'] == 'candidate_edit'
    assert checked['blockerResolutions']['DISPUTE_0']['evidencePaths'] == ['/draft']
    assert 'does not match' in json.loads(calls[1][0][-1]['content'])['validationError']

@pytest.mark.parametrize('receipt_ids', [[], ['DISPUTE_0'], ['DISPUTE_0', 'DISPUTE_2']])
def test_partial_group_confirmation_cannot_skip_independent_adjudication(monkeypatch, receipt_ids):
    from workout_generator_pkg import plan_review
    context, review = context_and_review()
    context['draft'].update(exercises=[], workouts=[])
    context['sourceMessages'] = {}
    review['findings'] = [{'severity': 'blocking', 'reviewScope': 'execution'} for _ in range(2)]
    group = {'findingIndexes': [0, 1], 'disposition': 'withdrawn_review_error', 'repairDimensions': [],
        'reason': 'Old claim contradicted.', 'errorKind': 'contradicted_by_current_data',
        'evidencePaths': ['/requirements', '/draft'],
        'resolution': {'kind': 'review_error', 'requirementPaths': [], 'unsupportedBehavior': None},
        'reviewerConfirmation': {'inputHash': review['inputHash'],
            'resolutions': {key: {'status': 'withdrawn_review_error'} for key in receipt_ids}}}
    group['evidenceHash'] = assessment._error_evidence(context, group)
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [group], 'repairPlan': ''}
    with pytest.raises(ValueError, match='responsible independent'):
        assessment.validate_assessment(review, context, require_confirmation=True)
    calls = []
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda context: {})
    def confirm(client, scope, part, *args):
        calls.append(sorted(part['previousBlockingFindings']))
        return {'findings': [], 'blockerResolutions': {key: {
            'status': 'withdrawn_review_error', 'disposition': 'withdrawn_review_error',
            'repairDimensions': [], 'repairObjectives': [], 'reason': 'Current source disproves the claim.',
            'evidencePaths': ['/requirements', '/draft'],
            'resolution': {'kind': 'review_error', 'requirementPaths': [], 'unsupportedBehavior': None}}
            for key in part['previousBlockingFindings']}}
    monkeypatch.setattr(plan_review, '_review_part', confirm)
    plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)
    assert calls == [['DISPUTE_0', 'DISPUTE_1']]
    assessment.validate_assessment(review, context, require_confirmation=True)
