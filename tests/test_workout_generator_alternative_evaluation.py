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
    if not next_proposal:
        assert 'already been approved' in context['alternativeReview']['instruction']
