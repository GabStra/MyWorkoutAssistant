import copy
import json
import pytest

from workout_generator_pkg import api_metrics, planning_tools, review_assessment
from workout_generator_pkg.requirement_accounting import validate_accounting, relaxation_paths, outcome


def test_accounting_rejects_unknown_sources_and_restriction_relaxation():
    sources = {'SOURCE_0': {'role': 'user', 'content': 'No overhead movements.'}}
    requirements = {'exerciseRestrictions': {}, 'requirementAccounting': [{
        'instruction': 'No overhead movements', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/exerciseRestrictions'], 'priority': 'mandatory',
        'enforcement': 'constraint', 'reason': 'Explicit restriction'}]}
    validate_accounting(requirements, sources)
    changed = copy.deepcopy(requirements)
    changed['requirementAccounting'][0]['priority'] = 'negotiable'
    with pytest.raises(ValueError, match='restrictions'):
        validate_accounting(changed, sources)
    changed['requirementAccounting'][0]['sourceReferences'] = ['SOURCE_99']
    with pytest.raises(ValueError, match='existing user source'):
        validate_accounting(changed, sources)


def test_accounting_must_cover_every_user_source_and_cannot_cite_assistant_text():
    requirements = {'requirementAccounting': [{
        'instruction': 'No overhead movements.', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': [], 'priority': 'mandatory',
        'enforcement': 'semantic_check', 'reason': 'Explicit exercise restriction.'}]}
    sources = {'SOURCE_0': {'role': 'user', 'content': 'No overhead movements.'},
               'SOURCE_1': {'role': 'user', 'content': 'Keep the workouts under an hour.'}}
    with pytest.raises(ValueError, match='SOURCE_1'):
        validate_accounting(requirements, sources)

    requirements['requirementAccounting'][0]['sourceReferences'] = ['SOURCE_0', 'SOURCE_1']
    sources['SOURCE_2'] = {'role': 'assistant', 'content': 'You could also prioritize chest.'}
    requirements['requirementAccounting'][0]['sourceReferences'].append('SOURCE_2')
    with pytest.raises(ValueError, match='only existing user sources'):
        validate_accounting(requirements, sources)


def test_local_cue_budget_excludes_generated_working_set_guidance():
    item = {'placementNotes': 'x' * 500,
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}}
    contract = planning_tools.placement_notes_text_contract(item)
    assert contract['maximumCharacters'] == 500 and contract['charactersToRemove'] == 0
    assert contract['exportMaximumCharacters'] > 500
    assert 'maxLength' not in planning_tools.JSON_SCHEMA['$defs']['Exercise']['properties']['placementNotes']
    assert 'calibration' not in contract['generatedText'].lower()
    assert not {'requiresEffortCalibration', 'calibrationAttempts'} & set(
        planning_tools._DRAFT_SCHEMA['properties'].get('workouts', {}).get(
            'items', {}).get('properties', {}).get('exercises', {}).get('items', {}).get('properties', {}))


@pytest.mark.parametrize('acceptance', [
    {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2},
    {'kind': 'technical_criteria', 'acceptanceCriterion': 'complete each repetition with controlled form',
     'terminationCriterion': 'stop when form cannot remain controlled'},
])
def test_effort_acceptance_does_not_emit_loading_or_progression_advice(acceptance):
    text = planning_tools.effort_acceptance_guidance(acceptance)
    assert 'Working-set acceptance' in text
    assert 're-audit' not in text and 'change load' not in text
    assert 'maximum selectable load' not in text



def test_local_notes_cannot_restate_typed_effort_or_progression():
    draft = {'workouts': [{'exercises': [{'placementNotes': '8-12 reps at 1-2 RIR; next selectable load at ceiling.',
        'progressionPlan': {'kind': 'load'}, 'effortAcceptance': {'kind': 'rir_range',
            'minimumRIR': 1, 'maximumRIR': 2, 'acceptanceCriterion': None, 'terminationCriterion': None}}]}]}
    with pytest.raises(planning_tools.PlanningInputError, match='duplicate typed effort acceptance'):
        planning_tools._bind_effort_acceptance(draft, {'minimum': 1, 'maximum': 2})


def test_latest_assessment_is_bound_to_the_current_draft_and_valid_receipt():
    review = {'inputHash': 'review-input', 'findings': [{'severity': 'warning', 'message': 'Optional.'}]}
    review['assessment'] = {'version': review_assessment.VERSION,
        'inputHash': review_assessment.assessment_hash(review), 'groups': [
            {'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [], 'reason': 'No requirement is violated.'}],
        'repairPlan': ''}
    result = {'requirementsId': 'REQ', 'libraryFingerprint': 'LIB', 'historyFingerprint': None,
        'resolvedDecisions': {}, 'currentDraftId': 'REVISION_2'}
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps({**result, 'review': review})}]
    assert review_assessment.latest_assessment(messages, result) == review['assessment']
    assert review_assessment.latest_assessment(messages, {**result, 'currentDraftId': 'REVISION_3'}) is None
    invalid = copy.deepcopy(review)
    invalid['assessment']['groups'][0].update(disposition='repair', repairDimensions=[])
    messages[1]['content'] = json.dumps({**result, 'review': invalid})
    assert review_assessment.latest_assessment(messages, result) is None


def test_explicit_solver_preference_can_be_traced_but_cannot_claim_an_empty_mapping():
    from jsonschema import validate
    from workout_generator_pkg.requirement_accounting import ACCOUNTING_SCHEMA
    entry = {'instruction': 'Prefer exercises with progression headroom.', 'sourceReferences': ['SOURCE_0'],
             'requirementPaths': ['/objectiveOrder'], 'priority': 'preference', 'enforcement': 'semantic_check',
             'reason': 'Supported load-headroom objective; suitability still needs semantic review.'}
    requirements = {'objectiveOrder': ['progression'], 'requirementAccounting': [entry]}
    sources = {'SOURCE_0': {'role': 'user', 'content': entry['instruction']}}
    validate(requirements['requirementAccounting'], ACCOUNTING_SCHEMA)
    validate_accounting(requirements, sources)
    requirements['objectiveOrder'] = None
    with pytest.raises(ValueError, match='nonempty source-backed objectiveOrder'):
        validate_accounting(requirements, sources)


def test_accounting_refresh_copies_frozen_targets_and_requires_new_source_review():
    from jsonschema import ValidationError
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    entry = {'instruction': 'Prefer progression headroom.', 'sourceReferences': ['SOURCE_0'],
             'requirementPaths': ['/objectiveOrder'], 'priority': 'preference', 'enforcement': 'semantic_check',
             'reason': 'Must be independently checked against the original source.'}
    request = {'baseRequirementsId': stored['requirementsId'], 'requirementAccounting': [entry],
               'objectiveOrder': ['progression']}
    refreshed = planning_tools.set_workout_requirements(request, messages, equipment)
    assert refreshed['requirements']['auditTargets'] == stored['requirements']['auditTargets']
    assert refreshed['requirements']['objectiveOrder'] == ['progression']
    assert not planning_tools.requirements_approved(messages, refreshed)
    with pytest.raises(ValidationError):
        planning_tools.set_workout_requirements({**request, 'auditTargets': {}}, messages, equipment)


def test_metadata_only_refresh_inherits_approval_but_priority_and_target_changes_do_not():
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg.generation_audit import ASSUMPTIONS
    from workout_generator_pkg.plan_review import REQUIREMENTS_REVIEW_VERSION, _hash, _requirements_context

    equipment, _, base, _ = planning_case()
    entry = {'instruction': 'Plan 5-6 chest sets.', 'sourceReferences': ['SOURCE_0'],
             'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest/minimum'],
             'priority': 'mandatory', 'enforcement': 'constraint', 'reason': 'Explicit target.'}
    base['requirements']['requirementAccounting'] = [entry]
    base['requirements']['objectiveOrder'] = ['progression']
    base['supportedMuscleTargets'] = planning_tools.available_muscle_targets(equipment)
    base['requirementsId'] = 'REQUIREMENTS_' + planning_tools._fingerprint(
        {'version': base['requirementsVersion'], 'requirements': base['requirements'], 'sources': base['sourceMessages']})[:16]
    messages = requirement_messages(base)

    def refresh(accounting, **changes):
        result = planning_tools.set_workout_requirements({
            'baseRequirementsId': base['requirementsId'], 'requirementAccounting': accounting,
            'objectiveOrder': ['progression'], **changes}, messages, equipment)
        result['sourceReview'] = {'version': REQUIREMENTS_REVIEW_VERSION, 'passed': True, 'findings': [],
            'auditPolicy': copy.deepcopy(ASSUMPTIONS)}
        result['sourceReview']['inputHash'] = _hash(_requirements_context(result))
        result['passed'] = True
        return result

    refreshed = refresh([{**entry, 'sourceReferences': ['SOURCE_0'], 'reason': 'Traceability wording updated.'}])
    assert planning_tools.requirements_approved(messages, refreshed)
    with pytest.raises(planning_tools.PlanningInputError, match='source-authorized relaxationDirection'):
        refresh([{**entry, 'priority': 'negotiable'}])

    changed_objective_order = copy.deepcopy(refreshed)
    changed_objective_order['requirements']['objectiveOrder'] = ['preservation']
    changed_objective_order['sourceReview']['inputHash'] = _hash(_requirements_context(changed_objective_order))
    assert not planning_tools.requirements_approved(messages, changed_objective_order)

    changed_target = copy.deepcopy(refreshed)
    changed_target['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] = 4
    changed_target['sourceReview']['inputHash'] = _hash(_requirements_context(changed_target))
    assert not planning_tools.requirements_approved(messages, changed_target)

    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'refresh', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'refresh', 'content': json.dumps(refreshed)},
    ])
    assert planning_tools.approved_requirement_base(messages)['requirementsId'] == refreshed['requirementsId']


def test_legacy_refresh_inherits_only_mandatory_accounting():
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg.generation_audit import ASSUMPTIONS
    from workout_generator_pkg.plan_review import REQUIREMENTS_REVIEW_VERSION, _hash, _requirements_context

    equipment, _, base, _ = planning_case()
    base['supportedMuscleTargets'] = planning_tools.available_muscle_targets(equipment)
    messages = requirement_messages(base)
    entry = {'instruction': 'Plan 5-6 chest sets.', 'sourceReferences': ['SOURCE_0'],
             'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest/minimum'],
             'priority': 'mandatory', 'enforcement': 'constraint', 'reason': 'Explicit target.'}

    def reviewed_refresh(accounting):
        result = planning_tools.set_workout_requirements({
            'baseRequirementsId': base['requirementsId'], 'requirementAccounting': accounting}, messages, equipment)
        result['sourceReview'] = {'version': REQUIREMENTS_REVIEW_VERSION, 'passed': True, 'findings': [],
            'auditPolicy': copy.deepcopy(ASSUMPTIONS)}
        result['sourceReview']['inputHash'] = _hash(_requirements_context(result))
        result['passed'] = True
        return result

    metadata_only = reviewed_refresh([{**entry, 'reason': 'Added traceability for the existing target.'}])
    assert planning_tools.requirements_approved(messages, metadata_only)

    newly_negotiable = reviewed_refresh([{**entry, 'priority': 'negotiable',
        'relaxationDirection': 'lower_minimum', 'reason': 'New permission to relax the target.'}])
    assert not planning_tools.requirements_approved(messages, newly_negotiable)


def test_semantic_dismissal_needs_reviewer_resolution_not_just_valid_hashes():
    context = {'requirements': {'instruction': 'Priority lift first'}, 'draft': {'order': ['other', 'priority']}}
    review = {'inputHash': 'snapshot', 'findings': [{'severity': 'blocking', 'message': 'Priority lift is last.'}]}
    group = {'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'reason': 'Unsupported claim',
             'errorKind': 'unsupported_requirement', 'evidencePaths': ['/requirements/instruction', '/draft/order']}
    group['evidenceHash'] = review_assessment._error_evidence(context, group)
    review['assessment'] = {'version': review_assessment.VERSION, 'inputHash': review_assessment.assessment_hash(review),
                            'groups': [group], 'repairPlan': ''}
    with pytest.raises(ValueError, match='responsible independent review'):
        review_assessment.validate_assessment(review, context, require_confirmation=True)
    group['reviewerConfirmation'] = {'inputHash': 'snapshot', 'resolutions': {
        'DISPUTE_0': {'status': 'withdrawn_review_error', 'reason': 'Confirmed source interpretation'}}}
    review_assessment.validate_assessment(review, context, require_confirmation=True)


def test_nested_api_calls_share_call_cap_without_elapsed_deadline():
    token = api_metrics._budget.set(None)
    try:
        api_metrics.start_planning_budget(max_calls=1)
        api_metrics.begin_api_request('test')
        assert api_metrics.remaining_request_timeout(180) == 180
        with pytest.raises(RuntimeError, match='call budget'):
            api_metrics.begin_api_request('test')
    finally:
        api_metrics._budget.reset(token)


def test_numeric_pass_does_not_claim_complete_feasibility():
    assert outcome({'passed': True, 'audit': {'errors': []}})['status'] == 'unresolved'
    assert outcome({'automaticAllocation': {'status': 'unproven'}})['status'] == 'unresolved'
    result = outcome({'automaticAllocation': {'status': 'infeasible'}})
    assert result['status'] == 'unresolved'
    assert 'candidate-menu expansion' in result['reason']


def test_review_continues_retained_analysis_without_accepting_partial_output(monkeypatch):
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.api_client import TruncatedResponseError
    error = TruncatedResponseError.__new__(TruncatedResponseError)
    ValueError.__init__(error, 'truncated final emission')
    error.diagnostics = {'reasoningContent': 'Completed review analysis.',
        'usage': {'completion_tokens_details': {'reasoning_tokens': 950}},
        'toolCalls': [{'function': {'name': 'emit_result', 'arguments': '{"findings":['}}]}
    calls = []
    def reply(client, request, **options):
        calls.append((request, options))
        if len(calls) == 1:
            raise error
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', reply)
    result = plan_review._review_call(None, [{'role': 'user', 'content': 'Original source facts'}],
                                    max_tokens=1000, reasoning_effort='low', output_schema={'type': 'object'})
    assert result[0] == '{"findings":[]}' and len(calls) == 2
    assert calls[1][1]['reasoning_effort'] is None
    assert calls[0][1]['timeout'] is calls[1][1]['timeout'] is None
    assert 'Completed review analysis.' in calls[1][0][-1]['content']
    assert 'Original source facts' in calls[1][0][0]['content']
