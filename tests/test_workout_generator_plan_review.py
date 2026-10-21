import copy
import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from workout_generator_pkg.planning_tools import audit_workout_plan, confirmed_draft
from test_workout_generator_planning_tools import planning_case, requirement_messages, approved_messages


@pytest.fixture(autouse=True)
def assessment_transport(monkeypatch):
    # These tests isolate individual reviews; the complete assessment has dedicated tests.
    def respond(client, request, **options):
        findings = json.loads(request[-1]['content'])['findings']
        return json.dumps({'groups': [{'findingIndexes': [int(index)],
            'disposition': ('advisory' if finding.get('action') == 'advisory' else
                            'repair' if finding['severity'] == 'blocking' or finding.get('action') == 'repair' else 'advisory'),
            'repairDimensions': ['guidance'] if finding.get('action') == 'repair' or finding['severity'] == 'blocking' else [],
            'reason': 'Existing scope-specific test disposition.'} for index, finding in findings.items()],
            'repairPlan': 'Repair all supported findings together.'}), None, None
    monkeypatch.setattr('workout_generator_pkg.review_assessment._review_call', respond)


def _finding(severity='blocking'):
    return {'severity': severity, 'action': 'repair' if severity == 'blocking' else 'advisory',
            'basis': 'established_violation' if severity == 'blocking' else 'uncertainty', 'muscleTargets': [],
            'path': '/exercises/0/placementNotes',
            'message': 'Execution instructions conflict with approved effort.',
            'evidencePaths': ['/sourceMessages/SOURCE_0/content', '/draft/exercises/0/placementNotes'],
            'repair': 'Match the prescribed effort to the approved requirement and re-audit.'}


def test_review_includes_progression_target_and_invalidates_only_dependent_evidence():
    equipment, _, stored, draft = planning_case()
    target = copy.deepcopy(equipment['exerciseDefinitions'][0])
    target.update(id='variant', name='Harder Push-Up')
    equipment['exerciseDefinitions'].append(target)
    item = draft['workouts'][0]['exercises'][0]
    item['progressionPlan'] = {'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
                               'nextDefinitionName': target['name'], 'atCeilingAction': 're_audit_variant'}
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    context = review._context(result, messages, equipment, None, len(messages) - 1)
    identifier = context['draft']['exercises'][0]['id']
    part = review._evidence_review_context(context, [identifier])
    assert part['draft']['libraryDefinitions']['LIBRARY_1']['name'] == target['name']
    assert 'LIBRARY_1' in part['progressionCapabilities']
    unrelated = copy.deepcopy(context)
    unrelated['draft']['libraryDefinitions']['LIBRARY_99'] = {'name': 'Unrelated'}
    assert review._evidence_review_context(unrelated, [identifier]) == part
    changed = copy.deepcopy(context)
    changed['draft']['libraryDefinitions']['LIBRARY_1']['name'] = 'Changed target'
    assert review._evidence_review_context(changed, [identifier]) != part


def test_saved_recipe_qualification_does_not_claim_or_replace_legacy_portable_notes():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    exercise = result['submittedDraft']['workouts'][0]['exercises'][0]
    exercise['satisfiesCoverage'] = []
    exercise['progressionPlan'] = {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}
    exercise['placementNotes'] = 'Keep each working set at 2-3 RIR.'
    result['recipeQualification'] = {'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': [],
        'progressionPlan': copy.deepcopy(exercise['progressionPlan']), 'portableNotes': 'Obsolete cue from an older receipt.'}]}

    context = review._context(result, messages, equipment, None, len(messages) - 1)

    assert context['qualifiedRecipeContracts']['LIBRARY_0'] == {
        'definition_id': 'LIBRARY_0', 'satisfiesCoverage': [],
        'progressionPlan': exercise['progressionPlan']}
    assert exercise['placementNotes'] == 'Keep each working set at 2-3 RIR.'


def test_oversized_blocker_resolution_is_kept_open_without_discarding_review():
    payload = {'findings': [], 'blockerResolutions': {'BLOCKER_0': {
        'status': 'withdrawn_review_error', 'reason': 'x' * 1201, 'evidencePaths': ['FACT_2']}}}

    normalized = json.loads(review._retain_unverifiable_blocker_resolutions(
        json.dumps(payload), {'BLOCKER_0': _finding()}))

    resolution = normalized['blockerResolutions']['BLOCKER_0']
    assert resolution['status'] == 'open'
    assert resolution['evidencePaths'] == ['FACT_2']
    assert 'exceeded the review limit' in resolution['reason']
    assert normalized['findings'] == []


def test_proposed_alternative_review_separates_pending_approval_from_candidate_merit(monkeypatch):
    equipment, _, stored, draft = planning_case()
    stored['proposedAlternative'] = {
        'originalRequirementsId': stored['requirementsId'],
        'changes': [{'path': '/auditTargets/weeklyEffectiveSets/chest/minimum', 'from': 15, 'to': 10}],
        'requiresUserApproval': True}
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)

    context = review._context(result, messages, equipment, None, len(messages) - 1)

    assert context['proposedAlternative'] == stored['proposedAlternative']
    assert context['alternativeReview'] == {
        'mode': 'hypothetical_candidate_merit',
        'approvalStatus': 'pending',
        'approvalGate': 'after_full_validation',
        'instruction': ('Assess candidate merit using the proposed values for listed changes and all unchanged original requirements. '
            'Pending approval is expected workflow state, not a defect. Python will require explicit selection only after validation.')}
    requests = []
    def respond(client, request, **options):
        requests.append(request)
        return json.dumps({'findings': []}), None, None
    monkeypatch.setattr(review, '_review_call', respond)

    review._review_part(None, 'execution', review._execution_review_context(context),
        context, result, messages, len(messages) - 1, None)

    review_request = json.loads(requests[0][-1]['content'])
    assert review_request['alternativeReview'] == context['alternativeReview']
    assert 'MUST NOT be reported as a finding' in requests[0][0]['content']


def _store(messages, result, call_id='audit'):
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'audit_workout_plan'}}]},
                     {'role': 'tool', 'tool_call_id': call_id, 'content': result['result']}])


def _without_review_refs(value):
    if isinstance(value, dict):
        return {key: _without_review_refs(child) for key, child in value.items() if key != '_reviewRef'}
    if isinstance(value, list):
        return [_without_review_refs(child) for child in value]
    return value


@pytest.mark.parametrize('tamper', ['reps', 'index_type', 'count'])
def test_uniform_review_target_is_lossless_and_does_not_hide_tampering(monkeypatch, tamper):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['workSetTemplate'] = {'reps': 8, 'additionalWeight': 0}
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    before = copy.deepcopy(audited['planIndex'])
    compact = review._compact_review_draft(audited['planIndex'], equipment)
    exercise = compact['exercises'][0]
    assert 'targetSetPrescriptions' not in exercise
    expanded = [{'workSetIndex': i, **exercise['repeatedWorkSetTarget']} for i in range(exercise['numWorkSets'])]
    assert expanded == before['exercises'][0]['targetSetPrescriptions']
    assert audited['planIndex'] == before
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    approved = review.review_draft(None, audited, messages, equipment)
    review.require_current_review(approved, messages, equipment)
    changed = approved['planIndex']['exercises'][0]
    if tamper == 'reps':
        changed['targetSetPrescriptions'][1]['reps'] = 9
    elif tamper == 'index_type':
        changed['targetSetPrescriptions'][1]['workSetIndex'] = True
    else:
        changed['numWorkSets'] = 6
    assert 'targetSetPrescriptions' in review._compact_review_draft(approved['planIndex'], equipment)['exercises'][0]
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(approved, messages, equipment)


def test_review_uses_native_load_calibration_without_inventing_trial_protocol(monkeypatch):
    from workout_generator_pkg.repair_capabilities import WORKING_SET_UNDERPERFORMANCE_GUIDANCE
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft,equipment,messages)
    raw['submittedDraft']['workouts'][0]['exercises'][0]['requiresLoadCalibration'] = True
    raw['planIndex']['exercises'][0]['requiresLoadCalibration'] = True
    before = copy.deepcopy(raw['planIndex'])
    compact = review._compact_review_draft(raw['planIndex'],equipment,raw['submittedDraft'])
    item = compact['exercises'][0]
    assert item['prescriptionStatus'] == 'calibration_required_no_fixed_load'
    assert item['requiresLoadCalibration'] is True
    assert not item.get('repeatedWorkSetTarget') and not item.get('targetSetPrescriptions')
    coaching = item['coachingAuthority']
    assert WORKING_SET_UNDERPERFORMANCE_GUIDANCE in coaching['generatedEffortAcceptance']
    assert 'generatedCalibration' not in coaching
    assert 'calibrationAttempts' not in item
    assert raw['planIndex'] == before and 'prescriptionStatus' not in before['exercises'][0]

    requests = []
    monkeypatch.setattr(review, '_review_call', lambda client, request, **options: (
        requests.append(request) or json.dumps({'findings': []}), None, None))
    context = review._context(raw, messages, equipment, None, len(messages) - 1)
    review._review_part(None, 'evidence', {'reviewedExerciseIds': [item['id']]},
        context, raw, messages, len(messages) - 1, None)
    prompt = requests[0][0]['content']
    assert 'do not require a numeric starting load, generator-authored trial count' in prompt
    assert 'Do not require trial counts, bracketing, logging, stop rules, or added sets/rests' in prompt
    assert 'calibrationTiming' not in requests[0][-1]['content']


def test_unavailable_muscle_targets_do_not_overwrite_findings_or_repairs(monkeypatch):
    from workout_generator_pkg import review_assessment
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    boundary = len(messages) - 1
    context = review._context(audited, messages, equipment, None, boundary)
    unsupported = ['FRONT_QUADRICEPS', 'BACK_HAMSTRING']
    fatigue_repair = 'Redistribute Nordic work and resequence the knee-dominant compound.'
    metadata_repair = 'Correct or explicitly assess unavailable muscle-target metadata.'
    findings = [
        {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': unsupported,
         'path': '/draft/exercises/0/placementNotes',
         'message': 'Eccentric fatigue and exercise order reduce productive squat work.',
         'evidencePaths': ['/draft/exercises/0/placementNotes'], 'repair': fatigue_repair,
         'action': 'repair', 'decisionId': None, 'newConflictEvidencePaths': []},
        {'severity': 'warning', 'basis': 'uncertainty', 'muscleTargets': unsupported,
         'path': '/draft/exercises/0/libraryDefinitionId',
         'message': 'The library cannot represent these finer muscle targets; assess the metadata limitation.',
         'evidencePaths': ['/draft/exercises/0/libraryDefinitionId'], 'repair': metadata_repair,
         'action': 'repair', 'decisionId': None, 'newConflictEvidencePaths': []}]
    monkeypatch.setattr(review, '_review_call', lambda *a, **k: (json.dumps({'findings': findings}), None, None))

    checked = review._review_part(None, 'execution', review._execution_review_context(context),
        context, audited, messages, boundary, None)

    fatigue, metadata = checked['findings']
    assert fatigue['severity'] == 'blocking' and fatigue['basis'] == 'established_violation'
    assert fatigue['repair'] == fatigue_repair
    assert metadata['severity'] == 'warning' and metadata['repair'] == metadata_repair
    assert fatigue['unavailableMuscleTargets'] == metadata['unavailableMuscleTargets'] == sorted(unsupported)

    assessor_calls = []
    assessor_prompts = []
    def assess(client, request, **options):
        assessor_calls.append(json.loads(request[-1]['content']))
        assessor_prompts.append(request[0]['content'])
        return json.dumps({'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['ordering'],
             'reason': 'The fatigue defect is supported.'},
            {'findingIndexes': [1], 'disposition': 'advisory', 'repairDimensions': [],
             'reason': 'Do not infer stimulus from absent finer metadata.'}],
            'repairPlan': 'Repair the supported fatigue/order issue while preserving requirements.'}), None, None
    monkeypatch.setattr(review_assessment, '_review_call', assess)
    assessed = review_assessment.assess_findings(None, context, {'inputHash': 'test', 'findings': checked['findings']})
    assert [group['disposition'] for group in assessed['groups']] == ['repair', 'advisory']
    sent = assessor_calls[0]
    assert 'unavailableMuscleTargets is diagnostic metadata only' in assessor_prompts[0]
    assert sent['findings']['0']['repair'] == fatigue_repair
    assert sent['findings']['0']['severity'] == 'blocking'
    assert sent['findings']['1']['unavailableMuscleTargets'] == sorted(unsupported)
    assert 'libraryDefinitions' in sent['context']['draft']


@pytest.mark.parametrize('stage, code', [
    ('decision', 'decision_review_failed'), ('requirements', 'requirements_review_failed'), ('draft', 'review_execution_failed')])
def test_truncated_reviews_log_diagnostics_and_never_approve_or_retry(monkeypatch, stage, code):
    from workout_generator_pkg.api_client import TruncatedResponseError
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content='rejected partial output', reasoning_content='unfinished reasoning', tool_calls=None))],
        usage=SimpleNamespace(model_dump=lambda: {'completion_tokens': 65536}))
    error = TruncatedResponseError(response, 65536, 'low')
    calls, logged = [], []
    def truncate(*a, **k):
        calls.append(1)
        raise error
    monkeypatch.setattr(review, 'chat_call', truncate)
    logger = SimpleNamespace(log_request=lambda *a: None,
        log_response=lambda label, data, **options: logged.append((label, json.loads(data), options)))
    if stage == 'requirements':
        candidate = copy.deepcopy(stored)
        candidate['sourceMessages'].append({'role': 'user', 'content': 'Keep these targets.', 'messageIndex': len(messages)})
        result = review.review_requirements(None, candidate, messages, logger=logger)
    else:
        name, args = ('audit_workout_plan', draft) if stage == 'draft' else ('record_planning_decisions', {'decisions': [
            {'topic': 'Volume', 'choice': 'Keep the requested volume.', 'sourceReferences': ['SOURCE_0']}]})
        result = json.loads(handle_function_call(None, messages, name, args, equipment, logger=logger)['result'])
    assert not result['passed'] and 'preview' not in result and 'requirementsPreview' not in result
    assert result['errors'][0]['code'] == code and len(calls) == 1
    assert len(logged) == 1 and logged[0][0].startswith('rejected ')
    assert logged[0][1] == error.diagnostics and logged[0][2]['truncate_at'] == 0


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_finding_reference_repair_keeps_valid_blockers_and_is_bounded(monkeypatch, repair_succeeds):
    equipment, _, stored, draft = planning_case()
    valid = _finding()
    malformed = {**_finding('warning'), 'evidencePaths': ['/missing_evidence']}
    calls = []
    def respond(client, request, **options):
        calls.append((request, options))
        if len(calls) == 1:
            return json.dumps({'findings': [valid, malformed]}), None, None
        patch = [{'op': 'replace', 'path': '/evidencePaths',
                  'value': ['/sourceMessages/SOURCE_0/content'] if repair_succeeds else ['/missing_evidence']}]
        return json.dumps({'patches': [patch]}), None, None
    monkeypatch.setattr(review, 'chat_call', respond)
    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and 'preview' not in result
    assert len(calls) == 2 and calls[-1][1]['reasoning_effort'] == 'low'
    assert len(json.loads(calls[-1][0][-1]['content'])['invalidFindings']) == 1
    assert result['review']['findings'][0]['severity'] == 'blocking'
    assert bool(result['review'].get('failure')) is not repair_succeeds


@pytest.mark.parametrize('basis', ['established_violation', 'material_uncertainty'])
def test_malformed_blocker_cannot_be_downgraded_by_reference_repair(monkeypatch, basis):
    equipment, _, stored, draft = planning_case()
    responses = iter([
        {'findings': [{**_finding(), 'basis': basis, 'path': '/invalid'}]},
        {'patches': [[{'op': 'replace', 'path': '/path', 'value': '/draft'},
            {'op': 'replace', 'path': '/basis', 'value': 'uncertainty'}]]},
    ])
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps(next(responses)), None, None))
    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and 'preview' not in result
    assert 'outside allowed error paths' in result['review']['failure']


@pytest.mark.parametrize('basis, expected_severity, passed', [
    ('established_violation', 'blocking', False),
    ('material_uncertainty', 'blocking', False),
    ('uncertainty', 'warning', True),
])
def test_backend_classifies_findings_from_structured_basis(monkeypatch, basis, expected_severity, passed):
    equipment, _, stored, draft = planning_case()
    finding = {**_finding('warning'), 'basis': basis,
               'action': 'advisory' if basis == 'uncertainty' else 'repair'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))

    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])

    assert result['passed'] is passed
    assert result['review']['findings'][0]['severity'] == expected_severity
    assert ('preview' in result) is passed
    if not passed:
        assert result['errors'][-1]['code'] == 'independent_review_finding'


def test_material_fatigue_concern_blocks_export_even_with_warning_label(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    approved = review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    review.require_current_review(approved, messages, equipment)
    approved['review']['findings'].append({**_finding('warning'), 'basis': 'material_uncertainty',
        'message': 'Repeated bracing demands leave the required technical performance unverifiable without mitigation.'})
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(approved, messages, equipment)


@pytest.mark.parametrize('new_instructions', [False, True])
def test_changed_scope_is_reassessed_even_when_cited_occurrence_is_unchanged(monkeypatch, new_instructions):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        payload = {'findings': [_finding()] if len(calls) == 1 else []}
        request = json.loads(args[1][-1]['content'])
        if request.get('previousBlockingFindings'):
            payload['blockerResolutions'] = {key: {'status': 'withdrawn_review_error', 'action': 'none',
                'reason': 'The original controlled-reps note did not contradict effort; the earlier review inferred an unsupported conflict.',
                'evidencePaths': ['/draft/exercises/0/placementNotes']} for key in request['previousBlockingFindings']}
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, 'chat_call', respond)
    first = review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    assert not first['passed']
    _store(messages, {'result': json.dumps(first)}, 'first')
    if new_instructions:
        messages.append({'role': 'user', 'content': 'Reassess execution under my updated instructions.'})
    changed = audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': first['currentDraftId'],
        'patch': [{'op': 'replace', 'path': '/workouts/0/description', 'value': 'Different focus'}]}, equipment, messages)
    fresh = review.review_draft(None, changed, messages, equipment)
    assert len(calls) == 2 and fresh['passed']
    _store(messages, {'result': json.dumps(fresh)}, 'fresh')
    review.require_current_review(fresh, messages, equipment)


@pytest.mark.parametrize('missing_assignment', [False, True])
def test_required_coverage_is_checked_before_review_and_claims_are_verified(monkeypatch, missing_assignment):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{'key': 'requested_pattern', 'description': 'The requested movement pattern', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Include the requested movement pattern in each session.'}], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Missing coverage must defer full review'))
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and result['reviewPending']
    assert result['errors'][0]['code'] == 'required_coverage_missing'
    assert result['errors'][0]['path'] == '/workouts/0/exercises'
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['requested_pattern']
    if missing_assignment:
        draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
        other = copy.deepcopy(draft['workouts'][0]['exercises'][0])
        other.update(numWorkSets=2, satisfiesCoverage=[])
        draft['workouts'][0]['exercises'].append(other)
    def reject_false_assignment(client, request, **options):
        context = json.loads(request[-1]['content'])
        expected = {'EXERCISE_0': ['requested_pattern']}
        if missing_assignment:
            expected['EXERCISE_1'] = []
        assert context['coverageAssignments'] == expected
        assert _without_review_refs(context['requirements']['requiredCoverage']) == requirements['requiredCoverage']
        return json.dumps({'findings': [{**_finding(),
            'path': '/coverageAssignments/EXERCISE_1' if missing_assignment else '/coverageAssignments/EXERCISE_0/0',
            'message': 'Qualifying exercise is missing its movement-pattern assignment.' if missing_assignment
                       else 'Assigned exercise does not satisfy the requested movement pattern.'}]}), None, None
    monkeypatch.setattr(review, 'chat_call', reject_false_assignment)
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and result['errors'][0]['code'] == 'independent_review_finding', result['errors']
    assert result['errors'][0]['draftPath'] == f'/workouts/0/exercises/{1 if missing_assignment else 0}/satisfiesCoverage'


def test_coverage_claim_changes_invalidate_a_successful_review(monkeypatch):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{'key': 'chest', 'description': 'Chest work', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Include chest work in each session.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['chest']
    messages = requirement_messages(stored)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert result['passed']
    review.require_current_review(result, messages, equipment)
    result['submittedDraft']['workouts'][0]['exercises'][0]['satisfiesCoverage'] = []
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(result, messages, equipment)


@pytest.mark.parametrize('needs_related', ['none', 'concern', 'missing_exact', 'claim'])
def test_review_history_keeps_material_related_records_but_omits_unused_details(needs_related):
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    if needs_related == 'claim':
        draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Compared to Historical movement.'
    result = audit_workout_plan(draft, equipment, messages)
    related = {'reference': 'HISTORY_0', 'definitionId': 'old', 'name': 'Historical movement',
        'sessions': [{'date': '2026-10-01', 'performances': [{'record': {
            'actualReps': 10, 'loadKg': 40, 'loadMeaning': 'pair_total', 'autoRegulationRIR': 2}}]}]}
    item = {'reference': 'LIBRARY_0', 'definitionId': 'press', 'name': 'Push-Up',
        'sessions': [] if needs_related == 'missing_exact' else [{'date': '2026-10-10', 'performances': [{'record': {'actualReps': 8}}]}],
        'loadSuitabilityConcerns': [{'code': 'related_history_only'}] if needs_related == 'concern' else [],
        'relatedMovementHistory': [related]}
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps({
            'historyFingerprint': 'current', 'libraryFingerprint': library_fingerprint(equipment), 'exercises': [item]})}])
    before = copy.deepcopy(messages)
    context = review._context(result, messages, equipment, 'current', len(messages)-1)
    other = context['history']['HISTORY_0']
    if needs_related == 'none':
        assert 'sessions' not in other and other['historyDetailsOmitted']
    else:
        assert other['sessions'][0]['performances'][0]['record']['autoRegulationRIR'] == 2
        assert other['sessions'][0]['performances'][0]['record']['loadMeaning'] == 'pair_total'
    assert messages == before


def test_numerical_repairs_defer_review_but_keep_prior_findings_until_fresh_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls, stages = [], []
    def call(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        assert options['output_schema']['$def']['reference']['enum']
        payload = {'findings': [_finding()]}
        request_data = calls[-1]
        if request_data.get('previousBlockingFindings'):
            payload['blockerResolutions'] = {key: {'status': 'open', 'action': 'repair', 'reason': 'The supplied execution finding remains unresolved.',
                'evidencePaths': ['/draft/exercises/0/placementNotes']} for key in request_data['previousBlockingFindings']}
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, 'chat_call', call)
    prior = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    prior_payload = json.loads(prior['result'])
    prior_finding = prior_payload['review']['findings'][0]
    prior_fingerprint = prior_payload['review']['inputHash']
    obligation_id = review._review_obligation_id(
        prior_finding, prior_payload['submittedDraft'], prior_fingerprint)
    _store(messages, prior, 'prior')
    assert len(calls) == 1
    bad = copy.deepcopy(draft)
    bad['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    bad['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [{'workSetIndex': 0, 'reps': 9, 'additionalWeight': 0}]
    failed = handle_function_call(None, messages, 'audit_workout_plan', bad, equipment)
    combined = json.loads(failed['result'])
    assert not combined['passed'] and failed['draft_preview'] is None
    assert combined['reviewPending'] and 'review' not in combined
    assert {e['code'] for e in combined['errors']} == {'volume_below_target'}
    finding = combined['previousReviewFindings'][0]
    assert finding['draftPath'] == '/workouts/0/exercises/0/placementNotes'
    assert len(calls) == 1
    _store(messages, failed, 'numerical')
    compact = json.loads(next(m['content'].split('\n', 1)[1] for m in _messages_for_api(messages, True, provided_equipment=equipment)
        if m.get('content', '').startswith('Current planning state')))
    pending = compact['repairTask']['pendingReviewObligations']
    pending_by_id = {item['obligationId']: item for item in pending}
    assert obligation_id in pending_by_id
    projected = pending_by_id[obligation_id]
    assert 'finding' not in projected
    assert combined['reviewChecklist']['findings'][obligation_id]['finding']['message'] == finding['message']
    assert projected['sourceDraftId'] == prior_payload['currentDraftId']
    assert projected['sourceFingerprint'] == prior_fingerprint
    assert projected['mappingStatus'] == 'mapped'
    assert projected['subjects'][0]['currentExerciseRef'] == 'EXERCISE_0'
    ledger_summary = compact['repairTask']['reviewLedgerSummary']
    assert ledger_summary['sourceBoundObligationCount'] == 1
    assert ledger_summary['representedByCurrentAssessment'] == 0
    assert ledger_summary['pendingAdjudicationCount'] == 1
    draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Repaired effort instructions.'
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment, progress=stages.append)
    payload = json.loads(result['result'])
    assert not payload['passed'] and result['draft_preview'] is None
    assert payload['errors'][0]['repair'] == _finding()['repair']
    assert stages and len(calls) == 2
    _store(messages, result)
    snapshot = next(m['content'] for m in _messages_for_api(messages, True) if m.get('content', '').startswith('Current planning state'))
    compact = json.loads(snapshot.split('\n', 1)[1])['lastAudit']
    assert compact['errors'][0]['evidencePaths'] == _finding()['evidencePaths']
    assert compact['errors'][0]['repair'] == _finding()['repair']
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert len(calls) == 2  # Failed review is also cached; unchanged retries cannot fish for approval.
    revised = copy.deepcopy(draft)
    revised['workouts'][0]['exercises'][0]['placementNotes'] = 'Revised execution.'
    handle_function_call(None, messages, 'audit_workout_plan', revised, equipment)
    assert len(calls) == 3


def test_successful_review_is_reused_and_confirmation_rejects_stale_or_missing_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"findings":[]}', None, None))
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    payload = json.loads(result['result'])
    assert payload['passed'] and result['draft_preview']
    approved = approved_messages(stored, payload)
    review.require_current_review(payload, approved, equipment)
    _store(messages, result)
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert len(calls) == 1
    changed = copy.deepcopy(payload)
    changed['planIndex']['exercises'][0]['placementNotes'] = 'Changed after review.'
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(changed, approved, equipment)
    missing = audit_workout_plan(draft, equipment, requirement_messages(stored))
    bypass = handle_function_call(None, approved_messages(stored, missing), 'generate_workout', {}, equipment,
                                 deps=SimpleNamespace(execute_workout_generation=lambda *a, **k: pytest.fail('Export bypassed review')))
    assert bypass['continue_planning'] and 'missing or stale' in bypass['result']


@pytest.mark.parametrize('read_only', [True, False])
def test_followup_check_preserves_questions_but_blocks_new_constraints(monkeypatch, read_only):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    payload = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    messages = approved_messages(stored, payload)
    messages.append({'role': 'user', 'content': 'Why this order?' if read_only else 'Remove push-ups; I cannot perform them.'})
    messages.append({'role': 'user', 'content': 'CONFIRM GENERATE'})
    with pytest.raises(ValueError, match='New conversation instructions'):
        review.require_current_review(payload, messages, equipment)
    calls = []
    def classify(client, request, **options):
        calls.append(request)
        assert options['reasoning_effort'] == 'low'
        assert 'workouts' not in json.loads(request[-1]['content'])
        return json.dumps({'readOnly': read_only, 'reason': 'Question only' if read_only else 'New exercise restriction'}), None, None
    monkeypatch.setattr(review, 'chat_call', classify)
    for _ in range(2):
        if read_only:
            review.review_followup_instructions(None, payload, messages, equipment)
            review.require_current_review(payload, messages, equipment)
        else:
            blocked = handle_function_call(None, messages, 'generate_workout', {}, equipment,
                deps=SimpleNamespace(execute_workout_generation=lambda *a, **k: pytest.fail('Exported stale approval')))
            assert blocked['continue_planning'] and 'review_source_changed' in blocked['result']
    assert len(calls) == 1
    saved = review._latest_result(messages, 'audit_workout_plan')[1]
    assert saved['review']['followupReview']['readOnly'] is read_only
    assert saved['draftId'] == payload['draftId']
    if not read_only:
        from workout_generator_pkg.interactive_shell import _messages_for_api
        request = _messages_for_api(messages, True, provided_equipment=equipment)
        state = json.loads(next(m['content'].split('\n', 1)[1] for m in request
                                if (m.get('content') or '').startswith('Current planning state')))
        assert not state['lastAudit']['passed']
        assert state['lastAudit']['errors'][0]['code'] == 'review_source_changed'
    messages.append({'role': 'user', 'content': 'Also avoid jumping.'})
    with pytest.raises(ValueError, match='New conversation instructions'):
        review.require_current_review(saved, messages, equipment)


def test_followup_failure_is_cached_until_explicit_retry(monkeypatch):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    payload = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    messages = approved_messages(stored, payload) + [{'role': 'user', 'content': 'Why these rests?'}]
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or 'invalid json', None, None))
    for _ in range(2):
        with pytest.raises(ValueError, match='Follow-up review failed'):
            review.review_followup_instructions(None, payload, messages, equipment)
    assert len(calls) == 1
    messages.append({'role': 'user', 'content': '/continue'})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or '{"readOnly":true,"reason":"Question only"}', None, None))
    review.review_followup_instructions(None, payload, messages, equipment)
    assert len(calls) == 2
    review.require_current_review(payload, messages, equipment)
    messages.append({'role': 'user', 'content': 'Explain the exercise selection too.'})
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, 'chat_call', cancel)
    with pytest.raises(KeyboardInterrupt):
        review.review_followup_instructions(None, payload, messages, equipment)
    with pytest.raises(ValueError, match='New conversation instructions'):
        review.require_current_review(payload, messages, equipment)


@pytest.mark.parametrize('response', ['not json', '{"findings":[{"severity":"warning"}]}',
    json.dumps(review._RESPONSE), json.dumps(review._RESPONSE) + ',"findings":[]}',
    json.dumps({'findings': [{**_finding(), 'path': '/exercises/999'}]}),
    json.dumps({'findings': [{**_finding(), 'evidencePaths': ['/invented']}]}),])
def test_invalid_review_cannot_approve_a_preview(monkeypatch, response):
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (response, None, None))
    messages = requirement_messages(stored)
    failed = review.review_draft(None, result, messages, equipment)
    assert not failed['passed'] and 'preview' not in failed
    assert failed['errors'][0]['code'] == 'review_execution_failed'
    _store(messages, {'result': json.dumps(failed)})
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Unchanged failed reviews must be cached'))
    cached = review.review_draft(None, result, messages, equipment)
    assert cached['errors'] == failed['errors']


def test_explicit_continue_retries_failed_output_but_not_valid_blocking_findings(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    calls = []
    responses = iter([json.dumps(review._RESPONSE), json.dumps({'findings': [_finding()]})])
    def call(client, request, **options):
        calls.append(1)
        assert 'Never return a JSON Schema' in request[0]['content']
        assert json.dumps(review._RESPONSE) not in request[0]['content']
        return next(responses), None, None
    monkeypatch.setattr(review, 'chat_call', call)
    failed = review.review_draft(None, result, messages, equipment)
    _store(messages, {'result': json.dumps(failed)}, 'failed-format')
    assert review.review_draft(None, result, messages, equipment)['review']['failure']
    assert len(calls) == 1
    messages.append({'role': 'user', 'content': '/continue'})
    retried = review.review_draft(None, result, messages, equipment)
    assert len(calls) == 2 and not retried['passed']
    assert retried['errors'][0]['code'] == 'independent_review_finding'
    _store(messages, {'result': json.dumps(retried)}, 'valid-blocker')
    messages.append({'role': 'user', 'content': '/continue'})
    assert not review.review_draft(None, result, messages, equipment)['passed']
    assert len(calls) == 2


@pytest.mark.parametrize('path,evidence', [
    ('/draft/workouts/0', '/draft/workouts/0'), ('/workouts/0', '/workouts/0'),
    ('/draft/workouts/0', '/workouts/0'), ('/workouts/0', '/draft/workouts/0')])
def test_review_normalizes_both_path_roots_without_another_model_call(monkeypatch, path, evidence):
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    finding = {**_finding(), 'path': path, 'evidencePaths': [evidence]}
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or json.dumps({'findings': [finding]}), None, None))
    outcome = review.review_draft(None, result, requirement_messages(stored), equipment)
    assert len(calls) == 1 and outcome['errors'][0]['code'] == 'independent_review_finding'
    assert outcome['errors'][0]['path'] == '/draft/workouts/0'
    assert outcome['errors'][0]['draftPath'] == '/workouts/0'
    assert outcome['errors'][0]['evidencePaths'] == ['/draft/workouts/0']


def test_wrong_wrapper_is_repaired_only_when_the_remaining_path_is_unique():
    context = {'draft': {'workouts': [{}]}, 'audit': {}, 'calibrationPolicy': False}
    assert review._review_pointer(context, '/audit/calibrationPolicy') == '/calibrationPolicy'
    context['draft']['calibrationPolicy'] = True
    with pytest.raises(ValueError, match='reference does not exist'):
        review._review_pointer(context, '/audit/calibrationPolicy')


def test_original_user_constraints_reach_the_reviewer(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = [{'role': 'user', 'content': 'Allow opposing OR non-competing groups; preserve movement qualifiers.'}] + requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    inputs = []
    def call(client, request, **kwargs):
        inputs.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None
    monkeypatch.setattr(review, 'chat_call', call)
    review.review_draft(None, result, messages, equipment)
    assert messages[0]['content'] == inputs[0]['sourceMessages']['SOURCE_0']['content']
    assert 'CONFIRM REQUIREMENTS' not in [m['content'] for m in inputs[0]['sourceMessages'].values()]
    assert 'reviewAuthority' in inputs[0]
    assert _without_review_refs(inputs[0]['audit']['weeklyVolume']) == {
        key: value for key, value in result['audit']['weeklyVolume'].items()
        if key in review.available_muscle_targets(equipment)}
    day = inputs[0]['audit']['workouts'][0]
    assert 'volume' not in day and 'contributions' not in day and 'estimatedSeconds' not in day
    assert day['workingSets'] == result['audit']['workouts'][0]['workingSets']
    assert _without_review_refs(day['setupEstimates']) == result['audit']['workouts'][0]['setupEstimates']
    for definition in inputs[0]['draft']['libraryDefinitions'].values():
        assert 'muscleGroups' in definition and 'secondaryMuscleGroups' in definition
        assert 'trainingMuscles' not in definition
    assert 'coverage-role assignments' in inputs[0]['reviewAuthority']
    assert result['audit']['weeklyVolume']  # Authoritative numerical data remains available to Python.


def test_execution_load_references_preserve_setup_without_strength_transfer():
    context = {'audit': {'workouts': []}, 'history': {'record': 'kept in evidence review'},
        'sourceMessages': {'SOURCE_0': {'content': 'Use my supplied equipment.'}},
        'draft': {'libraryDefinitions': {'LIBRARY_0': {'equipmentId': 'bar'}, 'LIBRARY_1': {'equipmentId': 'pair'}},
            'exercises': [
                {'id': 'EXERCISE_0', 'libraryDefinitionId': 'LIBRARY_0',
                 'repeatedWorkSetTarget': {'reps': 8, 'weight': 80}},
                {'id': 'EXERCISE_1', 'libraryDefinitionId': 'LIBRARY_0',
                 'targetSetPrescriptions': [{'workSetIndex': 0, 'reps': 8, 'weight': 80.0},
                                            {'workSetIndex': 1, 'reps': 7, 'weight': 75}]},
                {'id': 'EXERCISE_2', 'libraryDefinitionId': 'LIBRARY_1',
                 'repeatedWorkSetTarget': {'reps': 12, 'weight': 80}},
                {'id': 'EXERCISE_3', 'libraryDefinitionId': 'LIBRARY_1',
                 'prescriptionStatus': 'calibration_required_no_fixed_load'}]}}
    original = copy.deepcopy(context)
    execution = review._execution_review_context(context)
    exercises = execution['draft']['exercises']
    first = exercises[0]['repeatedWorkSetTarget']['loadConfigurationRef']
    assert exercises[1]['targetSetPrescriptions'][0]['loadConfigurationRef'] == first
    assert exercises[1]['targetSetPrescriptions'][1]['loadConfigurationRef'] != first
    assert exercises[2]['repeatedWorkSetTarget']['loadConfigurationRef'] != first
    assert exercises[1]['targetSetPrescriptions'][1]['reps'] == 7
    assert exercises[3]['prescriptionStatus'] == 'calibration_required_no_fixed_load'
    assert 'weight' not in json.dumps(exercises) and 'history' not in execution
    assert execution['sourceMessages'] == context['sourceMessages'] and context == original
    changed = copy.deepcopy(context)
    changed['draft']['exercises'][0]['repeatedWorkSetTarget']['weight'] = 85
    changed['draft']['exercises'][1]['targetSetPrescriptions'][0]['weight'] = 85
    assert review._execution_review_context(changed) == execution  # Same setup transitions, new load evidence.
    assert review._hash(changed) != review._hash(context)  # Full review/export authority still detects the change.


def test_export_requires_confirmation_after_the_repaired_preview(monkeypatch):
    from dataclasses import replace
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    first = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    _store(messages, first, 'first')
    payload = json.loads(first['result'])
    messages.extend([{'role': 'assistant', 'canonicalDraftPreview': payload['draftId'], 'content': payload['preview']},
                     {'role': 'user', 'content': 'CONFIRM GENERATE'}])
    patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': payload['currentDraftId'], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Revised after confirmation.'}]}
    revised = handle_function_call(None, messages, 'audit_workout_plan', patch, equipment)
    _store(messages, revised, 'revised')
    payload = json.loads(revised['result'])
    messages.append({'role': 'assistant', 'canonicalDraftPreview': payload['draftId'], 'content': payload['preview']})
    calls = []
    deps = SimpleNamespace(execute_workout_generation=lambda *a, **k: calls.append(1) or {
        'success': True, 'filepath': 'mock.json', 'error': None})
    blocked = handle_function_call(None, messages, 'generate_workout', {}, equipment, deps=deps)
    assert not calls and 'fresh CONFIRM GENERATE' in blocked['result']
    pipeline_deps = replace(resolve_pipeline_deps(), test_connection=lambda *a, **k: (True, None))
    exported = execute_workout_generation(None, messages, provided_equipment=equipment, deps=pipeline_deps)
    assert not exported['success'] and 'fresh CONFIRM GENERATE' in exported['error']
    messages.append({'role': 'user', 'content': 'CONFIRM GENERATE'})
    handle_function_call(None, messages, 'generate_workout', {}, equipment, deps=deps)
    assert calls == [1]


@pytest.mark.parametrize('path,expected', [
    ('/draft/planName', '/name'),
    ('/draft/exercises/0/libraryDefinitionId', '/workouts/0/exercises/0/definition_id'),
    ('/draft/workouts/0/restToNextSeconds/0', '/workouts/0/exercises/0/restAfterExerciseSeconds'),
    ('/draft/workouts/0/supersetGroups/0/restSecondsByExercise/EXERCISE_0', '/workouts/0/exercises/0/restAfterSupersetExerciseSeconds'),
    ('/draft/workouts/0/supersetGroups/0', '/workouts/0/exercises'),
    ('/draft/workouts/0/exerciseIds/0', '/workouts/0/exercises/0'),
    ('/draft/workouts/0/id', None),
])
def test_derived_review_paths_resolve_to_editable_source_fields(monkeypatch, path, expected):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['auditTargets']['maximumSessionSeconds'] = 4500
    stored = set_workout_requirements(requirements, [])
    draft['requirementsId'] = stored['requirementsId']
    first = draft['workouts'][0]['exercises'][0]
    first.update(superset='A', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=40)
    second = copy.deepcopy(first)
    second['restAfterSupersetExerciseSeconds'] = 75
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {**_finding(), 'path': path, 'evidencePaths': [path]}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    outcome = review.review_draft(None, result, messages, equipment)
    assert 'failure' not in outcome['review']
    if expected is None:
        assert 'draftPath' not in outcome['errors'][0]
    else:
        assert outcome['errors'][0]['draftPath'] == expected
        review._pointer(draft, expected)


def test_timed_review_finding_maps_to_seconds_in_the_editable_draft(monkeypatch):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'][0].update(exerciseType='COUNTUP', bodyWeightPercentage=None, name='Hold')
    requirements['auditTargets']['weeklyEffectiveSets'] = {}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use a 45-second hold.'}])
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0].update(minReps=None, maxReps=None, durationSeconds=45)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {**_finding(), 'path': '/draft/exercises/0/timeInMillis'}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    outcome = review.review_draft(None, result, messages, equipment)
    error = outcome['errors'][0]
    assert error['path'] == '/draft/exercises/0/timeInMillis'
    assert error['draftPath'] == '/workouts/0/exercises/0/durationSeconds'
    assert review._pointer(draft, error['draftPath']) == 45
    assert 'source-schema units' in outcome['instruction']


def test_review_preserves_questions_and_answers_in_order_without_requiring_copied_notes(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    clarification = [
        {'role': 'assistant', 'content': 'Exclude just conventional deadlift or every hinge?'},
        {'role': 'user', 'content': 'Only conventional.'},
        {'role': 'assistant', 'content': 'Which balance convention should I use?'},
        {'role': 'user', 'content': 'Use your judgment within my other constraints.'}]
    messages.extend(clarification)
    requests = []
    def check(client, request, **kwargs):
        context = json.loads(request[-1]['content'])
        requests.append(context)
        assert _without_review_refs(list(context['sourceMessages'].values())[-4:]) == clarification
        assert 'notes' not in context['requirements']
        assert _without_review_refs(context['restrictionPolicy']) == {'excludedExerciseNames': [], 'exceptExerciseNames': []}
        assert 'Do not request notes or a rewritten recap' in request[0]['content']
        assert 'When the user explicitly delegates a decision' in request[0]['content']
        finding = {**_finding(), 'path': '/audit/restrictionPolicy/excludedExerciseNames',
                   'evidencePaths': ['/sourceMessages/SOURCE_2/content']}
        return json.dumps({'findings': [finding]}), None, None
    monkeypatch.setattr(review, 'chat_call', check)
    result = audit_workout_plan(draft, equipment, messages)
    outcome = review.review_draft(None, result, messages, equipment)
    assert not outcome['passed'] and 'failure' not in outcome['review']
    assert outcome['errors'][0]['path'] == '/restrictionPolicy/excludedExerciseNames'
    assert len(requests) == 1


def test_raw_review_is_logged_even_when_references_are_invalid(monkeypatch):
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    raw = json.dumps({'findings': [{**_finding(), 'path': '/invented'}]})
    logged = []
    logger = SimpleNamespace(log_request=lambda *a: None, log_response=lambda label, content, **k: logged.append(content))
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (raw, None, None))
    outcome = review.review_draft(None, result, requirement_messages(stored), equipment, logger=logger)
    assert logged == [raw, raw] and outcome['review']['failure']  # Original and one bounded finding repair.


def test_warnings_are_displayed_without_mutating_draft_and_changed_context_invalidates_cache(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    calls = []
    def call(*args, **kwargs):
        calls.append(1)
        return json.dumps({'findings': [_finding('warning')]}), None, None
    monkeypatch.setattr(review, 'chat_call', call)
    before = copy.deepcopy(draft)
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert draft == before and 'Independent review notes:' in result['draft_preview']
    _store(messages, result)
    messages.append({'role': 'user', 'content': 'Keep all movements as straight sets.'})
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert len(calls) == 2


def test_review_cancellation_propagates(monkeypatch):
    equipment, _, stored, draft = planning_case()
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, 'chat_call', cancel)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    with pytest.raises(KeyboardInterrupt):
        review.review_draft(None, result, requirement_messages(stored), equipment)


@pytest.mark.parametrize('resume_id', [None, 'saved-generation'])
def test_pipeline_and_resume_cannot_bypass_missing_review(tmp_path, resume_id):
    from dataclasses import replace
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    deps = replace(resolve_pipeline_deps(), test_connection=lambda *a, **k: pytest.fail('Review validation must not make a connection-test request.'))
    exported = execute_workout_generation(None, approved_messages(stored, result), provided_equipment=equipment,
                                         script_dir=str(tmp_path), resume_session_id=resume_id, deps=deps)
    assert not exported['success'] and 'missing or stale' in exported['error']


@pytest.mark.parametrize('resume_id', [None, 'saved-generation'])
def test_pipeline_preserves_live_history_for_review_validation(tmp_path, monkeypatch, resume_id):
    from dataclasses import replace
    from workout_generator_pkg import generation_pipeline
    from workout_generator_pkg.deps import resolve_pipeline_deps
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    history = SimpleNamespace(fingerprint='current-history')
    received = []
    def check(snapshot, transcript, library, supplied_history):
        received.append(supplied_history)
        raise ValueError('Stopped after live-history handoff')
    monkeypatch.setattr(generation_pipeline, 'require_current_review', check)
    deps = replace(resolve_pipeline_deps(), test_connection=lambda *a, **k: (True, None))
    outcome = generation_pipeline.execute_workout_generation(None, approved_messages(stored, result),
        provided_equipment=equipment, script_dir=str(tmp_path), resume_session_id=resume_id, deps=deps,
        training_history=history)
    assert received == [history]
    assert not outcome['success'] and outcome['error'] == 'Stopped after live-history handoff'


def test_review_history_snapshot_and_json_request_use_the_configured_thinking_budget(monkeypatch):
    from workout_generator_pkg import api_client
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='{"findings":[]}', reasoning_content='checked'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kwargs: client
    api_client.chat_call(client, [], response_format={'type': 'json_object'})
    assert len(requests) == 1 and requests[0]['response_format'] == {'type': 'json_object'}
    assert requests[0]['extra_body']['thinking']['type'] == 'enabled'
    assert requests[0]['reasoning_effort'] == 'high' and requests[0]['max_tokens'] == 65536
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    history = SimpleNamespace(fingerprint='current-history')
    result = review.review_draft(None, result, requirement_messages(stored), equipment, history)
    review.require_current_review(result, requirement_messages(stored), equipment, history)
    review.require_current_review(result, requirement_messages(stored), equipment, 'current-history')
    with pytest.raises(ValueError, match='missing or stale'):
        review.require_current_review(result, requirement_messages(stored), equipment, SimpleNamespace(fingerprint='new-history'))


def test_numerical_failure_never_calls_expensive_review_or_exports(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [{'workSetIndex': 0, 'reps': 9, 'additionalWeight': 0}]
    calls = []
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (calls.append(1) or 'invalid JSON', None, None))
    messages = requirement_messages(stored)
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    payload = json.loads(result['result'])
    assert {e['code'] for e in payload['errors']} == {'volume_below_target'}
    assert not payload['passed'] and result['draft_preview'] is None and 'planIndex' not in payload
    assert payload['reviewPending'] and 'review' not in payload
    _store(messages, result)
    handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    assert not calls


def test_previous_review_warning_remains_guidance_during_numerical_failure(monkeypatch):
    equipment, _, stored, draft = planning_case()
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [_finding('warning')]}), None, None))
    messages = requirement_messages(stored)
    previous = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    _store(messages, previous)
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [{'workSetIndex': 0, 'reps': 9, 'additionalWeight': 0}]
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Numerical repairs must defer the reviewer'))
    result = handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    payload = json.loads(result['result'])
    assert not payload['passed'] and payload['previousReviewFindings'][0]['severity'] == 'warning'
    assert 'preview' not in payload and 'planIndex' not in payload


def _review_receipt(call_id, authority, draft, version, findings, dispositions, boundary, resolutions=None):
    assessment = {'groups': [{'findingIndexes': [index], 'disposition': disposition}
                             for index, disposition in dispositions.items()]}
    scope_results = ({'execution': {'inputHash': f'scope-{version}', 'findings': [],
                                    'blockerResolutions': copy.deepcopy(resolutions)}} if resolutions else {})
    return [
        {'role': 'assistant', 'tool_calls': [{'id': call_id,
            'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps({
            **authority, 'submittedDraft': copy.deepcopy(draft), 'currentDraftId': f'DRAFT_V{version}',
            'review': {'version': version, 'inputHash': f'old-{version}', 'instructionBoundary': boundary,
                       'findings': copy.deepcopy(findings), 'assessment': assessment,
                       'scopeResults': scope_results}})}]


def test_unresolved_review_findings_survive_review_version_change_until_reassessed():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    old = _finding()
    old['draftPath'] = '/workouts/0/sessionName'
    related = copy.deepcopy(old)
    related['message'] = 'The same session label also misstates its emphasis.'
    # The source is the prior plan and its review policy version; v69 omitted this target.
    messages.extend(_review_receipt('old-audit', authority, result['submittedDraft'], 68,
        [old, related], {0: 'repair', 1: 'repair'}, len(messages) - 1))
    messages.extend(_review_receipt('new-audit', authority, result['submittedDraft'], 69,
        [], {}, len(messages) - 1))

    checklist = review._review_checklist(result, messages)

    assert len(checklist['findings']) == 2
    assert {item['finding']['message'] for item in checklist['findings'].values()} == {
        old['message'], related['message']}
    assert all(item['finding']['draftPath'] == '/workouts/0/sessionName'
               for item in checklist['findings'].values())
    assert all(item['sourceDraftId'] == 'DRAFT_V68' for item in checklist['findings'].values())
    assert all(item['sourceFingerprint'] == 'old-68' for item in checklist['findings'].values())


def test_newer_explicit_blocker_resolution_can_withdraw_carried_finding():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    finding = _finding()
    finding['draftPath'] = '/workouts/0/sessionName'
    obligation_id = review._review_obligation_id(finding, result['submittedDraft'], 'old-68')
    messages.extend(_review_receipt('old-audit', authority, result['submittedDraft'], 68,
        [finding], {0: 'repair'}, len(messages) - 1))
    messages.extend(_review_receipt('new-audit', authority, result['submittedDraft'], 69,
        [], {}, len(messages) - 1,
        {'BLOCKER_V68_0': {'status': 'withdrawn_review_error', 'reason': 'Current evidence disproved it.'}}))
    current_receipt = json.loads(messages[-1]['content'])
    current_receipt['review']['scopeResults']['execution']['blockerResolutions'] = {
        obligation_id: {'status': 'withdrawn_review_error', 'reason': 'Current evidence disproved it.'}}
    current_receipt['reviewChecklist'] = {'findings': {'BLOCKER_V68_0': {
        'finding': copy.deepcopy(finding), 'references': ['LIBRARY_0']}}, 'changedDraftPaths': [], 'sourceCount': 1}
    messages[-1]['content'] = json.dumps(current_receipt)
    # The no-change cache path must not return a checklist retired by this receipt.
    assert review._review_checklist(result, messages) is None


def test_same_version_reorder_and_omission_keep_stable_obligations_until_resolution():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    first = _finding()
    first.update(draftPath='/workouts/0/sessionName', message='The session label omits a planned hinge.',
                 repair='Rename the session.')
    second = _finding()
    second.update(draftPath='/workouts/0/sessionName', message='The session label claims chest work that is absent.',
                  repair='Correct the description.')
    first_id = review._review_obligation_id(first, result['submittedDraft'], 'old-69')
    second_id = review._review_obligation_id(second, result['submittedDraft'], 'old-69')
    messages.extend(_review_receipt('audit-a', authority, result['submittedDraft'], 69,
        [first, second], {0: 'repair', 1: 'repair'}, len(messages) - 1))
    messages.extend(_review_receipt('audit-b', authority, result['submittedDraft'], 69,
        [second, first], {0: 'repair', 1: 'repair'}, len(messages) - 1))

    reordered = review._review_checklist(result, messages)
    assert set(reordered['findings']) == {first_id, second_id}

    messages.extend(_review_receipt('audit-b2', authority, result['submittedDraft'], 69,
        [second], {0: 'repair'}, len(messages) - 1))
    omitted = review._review_checklist(result, messages)
    assert set(omitted['findings']) == {first_id, second_id}

    messages.extend(_review_receipt('audit-c', authority, result['submittedDraft'], 69,
        [second], {0: 'repair'}, len(messages) - 1,
        {first_id: {'status': 'resolved_by_change', 'reason': 'The title was corrected.'}}))
    resolved = review._review_checklist(result, messages)
    assert set(resolved['findings']) == {second_id}

    messages.extend(_review_receipt('audit-d', authority, result['submittedDraft'], 69,
        [], {}, len(messages) - 1))
    assert set(review._review_checklist(result, messages)['findings']) == {second_id}
    # A later same-version audit may omit the resolution record; retirement
    # remains in force without resurrecting the first finding.
    messages.extend(_review_receipt('audit-e', authority, result['submittedDraft'], 69,
        [], {}, len(messages) - 1))
    assert first_id not in review._review_checklist(result, messages)['findings']


def test_each_carried_obligation_uses_its_own_source_draft_for_changed_paths():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}

    old_source = copy.deepcopy(result['submittedDraft'])
    exercises = old_source['workouts'][0]['exercises']
    while len(exercises) <= 22:
        exercises.append(copy.deepcopy(exercises[-1]))
    finding = _finding()
    finding.update(path='/draft/exercises/22/coachingAuthority',
        evidencePaths=['/draft/exercises/22/coachingAuthority'],
        draftPath='/workouts/0/exercises/22/coachingAuthority',
        message='The old occurrence lacks an authoritative coaching note.')
    messages.extend(_review_receipt('old-long-plan', authority, old_source, 69,
        [finding], {0: 'repair'}, len(messages) - 1))
    messages.extend(_review_receipt('current-short-plan', authority, result['submittedDraft'], 70,
        [], {}, len(messages) - 1))

    checklist = review._review_checklist(result, messages)
    obligation = next(iter(checklist['findings'].values()))

    assert checklist['changedDraftPaths'] == []
    assert obligation['changedDraftPaths']
    assert any(path.startswith('/workouts/0/exercises') for path in obligation['changedDraftPaths'])


def test_unmodified_carried_blocker_does_not_resolve_or_dereference_stale_path(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = review._context(result, messages, equipment, None, len(messages) - 1)
    obligation_id = 'OBLIGATION_STALE_PATH'
    previous = {**_finding(), 'message': 'The prior coaching note was unsupported.',
        'path': '/draft/exercises/22/coachingAuthority',
        'evidencePaths': ['/draft/exercises/22/coachingAuthority'],
        'draftPath': '/workouts/0/exercises/22/coachingAuthority', 'reviewScope': 'execution'}
    current_path = '/draft/exercises/0/placementNotes'
    context['reviewChecklist'] = {'findings': {obligation_id: {
        'finding': previous, 'references': [], 'sourceFingerprint': 'prior-source',
        'sourceDraftId': 'OLD_DRAFT', 'changedDraftPaths': [], 'sourceCount': 1}},
        'changedDraftPaths': [], 'sourceCount': 1}
    seen = {}
    def respond(client, request, **kwargs):
        seen['request'] = request
        seen['schema'] = kwargs['output_schema']
        return json.dumps({'findings': [], 'blockerResolutions': {'ISSUE_0': {
                'status': 'resolved_by_change', 'action': 'none', 'reason': 'That old note was corrected.',
            'evidencePaths': [current_path]}}}), None, None
    monkeypatch.setattr(review, '_review_call', respond)

    part = review._with_blocker_checklist('execution', review._execution_review_context(context), context)
    checked = review._review_part(None, 'execution', part,
        context, result, messages, len(messages) - 1, None)

    resolution = checked['blockerResolutions'][obligation_id]
    assert resolution['status'] == 'open'
    assert resolution['evidencePaths'] == [current_path]
    assert checked['findings'][0]['path'] == current_path
    assert checked['findings'][0]['draftPath'] == '/workouts/0/exercises/0/placementNotes'
    request_context = json.loads(seen['request'][-1]['content'])
    assert set(request_context['previousBlockingFindings']) == {'ISSUE_0'}
    assert obligation_id not in seen['request'][-1]['content']
    assert set(seen['schema']['properties']['blockerResolutions']['required']) == {'ISSUE_0'}


def test_long_stable_blocker_ids_use_exact_request_local_aliases_and_reject_unknown_aliases(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = review._context(result, messages, equipment, None, len(messages) - 1)
    first = 'OBLIGATION_10c242587b09a0ad496d'
    near_lookalike = 'OBLIGATION_10c242587a0b0d86965b6f'
    part = {'previousBlockingFindings': {
        first: {'message': 'The first prior blocker.'},
        near_lookalike: {'message': 'The second prior blocker.'}}}
    monkeypatch.setattr(review, '_with_review_refs', lambda value: (copy.deepcopy(value), {'FACT_0': '/draft'}))
    monkeypatch.setattr(review, '_review_pointer', lambda context, path, root='/draft': path)
    calls = []
    def respond(client, request, **kwargs):
        request_context = json.loads(request[-1]['content'])
        calls.append((request_context, kwargs['output_schema']))
        resolutions = {
            local_id: {'status': 'withdrawn_review_error', 'action': 'none', 'reason': 'Retained from current evidence.',
                       'evidencePaths': ['FACT_0']}
            for local_id in request_context['previousBlockingFindings']}
        if len(calls) == 1:
            # This reproduces the live failure: a long stable ID is transcribed as a similar-looking one.
            resolutions['ISSUE_2'] = resolutions.pop('ISSUE_1')
        return json.dumps({'findings': [], 'blockerResolutions': resolutions}), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    execution_part = review._execution_review_context(context)
    execution_part['previousBlockingFindings'] = part['previousBlockingFindings']

    with pytest.raises(ValidationError):
        review._review_part(None, 'execution', execution_part,
            context, result, messages, len(messages) - 1, None)
    request_context, schema = calls[0]
    assert set(request_context['previousBlockingFindings']) == {'ISSUE_0', 'ISSUE_1'}
    serialized = json.dumps(request_context)
    assert first not in serialized and near_lookalike not in serialized
    assert set(schema['properties']['blockerResolutions']['required']) == {'ISSUE_0', 'ISSUE_1'}
    wire_resolution = schema['properties']['blockerResolutions']['properties']['ISSUE_0']
    wire_action = wire_resolution['properties']['action']
    assert wire_action['type'] == 'string'
    assert wire_action['enum'] == ['repair', 'clarify', 'advisory', 'none']
    assert None not in wire_action['enum']
    assert not {'allOf', 'if', 'then', 'const'}.intersection(wire_resolution)

    checked = review._review_part(None, 'execution', execution_part,
        context, result, messages, len(messages) - 1, None)
    assert set(checked['blockerResolutions']) == {first, near_lookalike}
    assert checked['blockerResolutions'][first]['status'] == 'withdrawn_review_error'


def test_open_resolution_keeps_stable_id_when_current_occurrence_path_moves():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    prior = _finding()
    prior.update(path='/draft/exercises/0/placementNotes', evidencePaths=['/draft/exercises/0/placementNotes'],
        draftPath='/workouts/0/exercises/0/placementNotes', message='The current cue still lacks a concrete setup.')
    obligation_id = review._review_obligation_id(prior, result['submittedDraft'], 'old-69')
    messages.extend(_review_receipt('prior-blocker', authority, result['submittedDraft'], 69,
        [prior], {0: 'repair'}, len(messages) - 1))

    current_draft = copy.deepcopy(result['submittedDraft'])
    current_draft['workouts'][0]['exercises'].append(
        copy.deepcopy(current_draft['workouts'][0]['exercises'][0]))
    current = copy.deepcopy(prior)
    current.update(path='/draft/exercises/1/placementNotes',
        evidencePaths=['/draft/exercises/1/placementNotes'],
        draftPath='/workouts/0/exercises/1/placementNotes')
    current_receipt = _review_receipt('moved-blocker', authority, current_draft, 70,
        [current], {0: 'repair'}, len(messages) - 1,
        {obligation_id: {'status': 'open', 'reason': current['message'],
            'evidencePaths': ['/draft/exercises/1/placementNotes']}})
    messages.extend(current_receipt)
    current_result = copy.deepcopy(result)
    current_result['submittedDraft'] = current_draft

    checklist = review._review_checklist(current_result, messages)

    assert set(checklist['findings']) == {obligation_id}
    entry = checklist['findings'][obligation_id]
    assert entry['finding']['draftPath'] == '/workouts/0/exercises/1/placementNotes'
    assert entry['finding']['message'] == current['message']


def test_review_obligations_do_not_cross_evidence_authority_changes():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    finding = _finding()
    messages.extend(_review_receipt('old-audit', authority, result['submittedDraft'], 68,
        [finding], {0: 'repair'}, len(messages) - 1))
    changed = copy.deepcopy(result)
    changed['historyFingerprint'] = 'new-history-authority'

    assert review._review_checklist(changed, messages) is None


def _hypothetical_review_ledger(changes, *, same_requirements=True, origin=True, current_decisions=None):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    source = audit_workout_plan(draft, equipment, messages)
    source.update(allowEducatedLoadGuesses=True)
    if current_decisions is not None:
        source['resolvedDecisions'] = copy.deepcopy(current_decisions)
    authority = {key: source.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    finding = _finding()
    messages.extend(_review_receipt('source-review', authority, source['submittedDraft'], 69,
        [finding], {0: 'repair'}, len(messages) - 1))

    proposed_id = 'PROPOSAL_REQUIREMENTS_TEST'
    proposed_requirements = copy.deepcopy(stored['requirements'])
    if not same_requirements:
        proposed_requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] += 1
    candidate_record = copy.deepcopy(stored)
    candidate_record.update(requirementsId=proposed_id, requirements=proposed_requirements,
        proposedAlternative={'originalRequirementsId': stored['requirementsId'] if origin else 'OTHER_REQUIREMENTS',
            'changes': copy.deepcopy(changes), 'requiresUserApproval': True})
    if current_decisions is not None:
        candidate_record['resolvedDecisions'] = copy.deepcopy(current_decisions)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'hypothetical-requirements',
            'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'hypothetical-requirements', 'content': json.dumps(candidate_record)},
    ])
    candidate = copy.deepcopy(source)
    candidate['requirementsId'] = proposed_id
    candidate['submittedDraft']['requirementsId'] = proposed_id
    return review._review_checklist(candidate, messages), candidate, messages, equipment


def test_id_only_hypothetical_review_keeps_source_bound_obligations():
    checklist, candidate, messages, equipment = _hypothetical_review_ledger([])

    assert checklist and len(checklist['findings']) == 1
    entry = next(iter(checklist['findings'].values()))
    assert entry['sourceDraftId'] == 'DRAFT_V69'
    assert entry['sourceFingerprint'] == 'old-69'
    assert entry['finding']['message'] == _finding()['message']
    candidate['reviewChecklist'] = checklist
    context = review._context(candidate, messages, equipment, None, len(messages) - 1)
    projected = next(iter(context['reviewChecklist']['findings'].values()))
    assert projected['finding']['message'] == _finding()['message']
    assert projected['sourceFingerprint'] == 'old-69'


def test_hypothetical_bridge_uses_reviewed_decisions_not_stale_requirement_receipt_decisions():
    decisions = {'DECISION_0': {'choice': 'Use the approved distribution.'}}
    checklist, _, _, _ = _hypothetical_review_ledger([], current_decisions=decisions)

    assert checklist and len(checklist['findings']) == 1
    assert next(iter(checklist['findings'].values()))['sourceDraftId'] == 'DRAFT_V69'


@pytest.mark.parametrize('kwargs', [
    {'same_requirements': False},
    {'origin': False},
    {'changes': [{'path': '/auditTargets/weeklyEffectiveSets/chest/minimum', 'from': 5, 'to': 5}]},
])
def test_hypothetical_ledger_bridge_rejects_changed_or_unbound_requirements(kwargs):
    checklist, _, _, _ = (_hypothetical_review_ledger([], **kwargs) if 'changes' not in kwargs
                          else _hypothetical_review_ledger(kwargs['changes']))

    assert checklist is None


def test_review_input_identity_ignores_own_ledger_output_but_keeps_carried_obligations():
    base = {'requirements': {'goal': 'same'}, 'draft': {'workouts': []}}
    own = {'OBLIGATION_OWN': {'finding': {'message': 'Current review finding.'},
        'references': [], 'sourceFingerprint': 'own-hash', 'sourceDraftId': 'REVISION_CURRENT'}}
    carried = {'OBLIGATION_OLD': {'finding': {'message': 'Prior unresolved finding.'},
        'references': ['LIBRARY_4'], 'sourceFingerprint': 'prior-hash', 'sourceDraftId': 'REVISION_OLD'}}

    baseline_hash = review._review_input_hash(base, 'REVISION_CURRENT')
    with_own_output = copy.deepcopy(base)
    with_own_output['reviewChecklist'] = {'findings': own}
    assert review._review_input_hash(with_own_output, 'REVISION_CURRENT') == baseline_hash

    with_carried = copy.deepcopy(base)
    with_carried['reviewChecklist'] = {'findings': carried}
    assert review._review_input_hash(with_carried, 'REVISION_CURRENT') != baseline_hash
    with_both = copy.deepcopy(base)
    with_both['reviewChecklist'] = {'findings': {**carried, **own}}
    assert review._review_input_hash(with_both, 'REVISION_CURRENT') == review._review_input_hash(
        with_carried, 'REVISION_CURRENT')


def test_review_cache_accepts_terminal_resolution_but_rejects_new_carried_obligation():
    base = {'requirements': {'goal': 'same'}, 'draft': {'workouts': []}}
    carried = {'OBLIGATION_OLD': {'finding': {'message': 'Prior unresolved finding.'},
        'references': ['LIBRARY_4'], 'sourceFingerprint': 'prior-hash', 'sourceDraftId': 'REVISION_OLD'}}
    reviewed_input = copy.deepcopy(base)
    reviewed_input['reviewChecklist'] = {'findings': carried}
    resolved_output = copy.deepcopy(base)
    cached = {'reviewBaseHash': review._review_base_hash(reviewed_input),
        'reviewLedgerOutputFingerprint': review._review_ledger_fingerprint(resolved_output)}

    assert review._review_cache_matches(cached, resolved_output)
    new_obligation = {'OBLIGATION_NEW': {'finding': {'message': 'New external finding.'},
        'references': ['LIBRARY_5'], 'sourceFingerprint': 'new-hash', 'sourceDraftId': 'REVISION_OLDER'}}
    changed_output = copy.deepcopy(resolved_output)
    changed_output['reviewChecklist'] = {'findings': new_obligation}
    assert not review._review_cache_matches(cached, changed_output)


def test_terminally_resolved_review_is_cached_and_remains_exportable(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Use a band for every rep.'
    messages = requirement_messages(stored)
    calls = []

    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        calls.append(payload)
        previous = payload.get('previousBlockingFindings')
        if previous:
            return json.dumps({'findings': [], 'blockerResolutions': {
                key: {'status': 'resolved_by_change', 'action': 'none', 'reason': 'The unsupported band instruction was removed.',
                      'evidencePaths': ['/draft/exercises/0/placementNotes']}
                for key in previous}}), None, None
        finding = {**_finding(), 'message': 'The required band is unavailable.',
                   'evidencePaths': ['/draft/exercises/0/placementNotes', '/equipment']}
        return json.dumps({'findings': [finding]}), None, None

    monkeypatch.setattr(review, 'chat_call', respond)
    first = review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    assert not first['passed']
    _store(messages, {'result': json.dumps(first)}, 'terminal-source')

    patch = [{'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Bodyweight only; no band.'}]
    repaired = audit_workout_plan({'requirementsId': stored['requirementsId'],
        'baseDraftId': first['currentDraftId'], 'patch': patch}, equipment, messages)
    result = review.review_draft(None, repaired, messages, equipment)
    assert result['passed'], result.get('errors')
    _store(messages, {'result': json.dumps(result)}, 'terminal-resolution')
    assert len(calls) == 2

    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Unchanged terminal resolution should reuse its review receipt'))
    unchanged = audit_workout_plan({'requirementsId': stored['requirementsId'],
        'baseDraftId': result['currentDraftId'], 'patch': []}, equipment, messages)
    cached = review.review_draft(None, unchanged, messages, equipment)
    assert cached.get('cached') or cached['review'] == result['review']
    review.require_current_review(cached, messages, equipment)
    _store(messages, {'result': json.dumps(cached)}, 'cached-terminal-review')
    messages.extend([{'role': 'assistant', 'content': cached['preview'],
                      'canonicalDraftPreview': cached['draftId']},
                     {'role': 'user', 'content': 'CONFIRM GENERATE'}])
    confirmed_draft(messages, equipment, require_confirmation=True)
    assert len(calls) == 2


def test_session_findings_in_distinct_workouts_keep_separate_origin_ids():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    result.update(allowEducatedLoadGuesses=False)
    authority = {key: result.get(key) for key in (
        'requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions', 'allowEducatedLoadGuesses')}
    source = copy.deepcopy(result['submittedDraft'])
    source['workouts'].append(copy.deepcopy(source['workouts'][0]))
    first = _finding()
    first.update(draftPath='/workouts/0/sessionName', message='The session label omits upper back work.')
    second = copy.deepcopy(first)
    second['draftPath'] = '/workouts/1/sessionName'
    first_id = review._review_obligation_id(first, source, 'old-69')
    second_id = review._review_obligation_id(second, source, 'old-69')
    assert first_id != second_id

    messages.extend(_review_receipt('sessions-a', authority, source, 69,
        [first, second], {0: 'repair', 1: 'repair'}, len(messages) - 1))
    checklist = review._review_checklist(result, messages)
    assert set(checklist['findings']) == {first_id, second_id}
    assert {entry['sourceDraftId'] for entry in checklist['findings'].values()} == {'DRAFT_V69'}
    assert all(entry['sourceFingerprint'] == 'old-69' for entry in checklist['findings'].values())


def test_invalid_rep_targets_stop_before_expensive_execution_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [
        {'workSetIndex': i, 'reps': 1, 'additionalWeight': 0} for i in range(5)]
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('Invalid contract must not invoke a reviewer'))
    with pytest.raises(ValueError, match='outside minReps'):
        handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)


def test_review_equipment_uses_app_load_limits_instead_of_ambiguous_inventory_counts():
    equipment = {'equipments': [{'id': 'bar', 'name': 'Barbell', 'type': 'BARBELL',
        'barWeight': 10, 'sleeveLength': 270, 'availablePlates': [
            {'weight': weight, 'thickness': 10} for weight in [20, 10, 5, 5, 5, 2.5, 1.25, 1, .5, .25]]}],
        'accessoryEquipments': [{'id': 'rack', 'name': 'Rack'}]}
    before = copy.deepcopy(equipment)
    result = review._review_equipment(equipment)
    bar = result['equipments'][0]
    assert bar['selectableLoadSummary']['maximumKg'] == 111
    assert bar['selectableLoadSummary']['loadConvention'] == 'total_including_bar'
    assert 'availablePlates' not in bar
    assert bar['barWeight'] == 10 and result['accessoryEquipments'] == equipment['accessoryEquipments']
    assert equipment == before


def test_review_shares_definitions_losslessly_and_still_detects_changed_occurrence_fields(monkeypatch):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    second = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    second['placementNotes'] = 'Different setup and effort instructions.'
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = review._context(result, messages, equipment, None, len(messages)-1)
    compact = context['draft']
    assert list(compact['libraryDefinitions']) == ['LIBRARY_0']
    for index, (original, occurrence) in enumerate(zip(result['planIndex']['exercises'], compact['exercises'])):
        restored = {**compact['libraryDefinitions'][occurrence['libraryDefinitionId']], **occurrence}
        restored['libraryDefinitionId'] = equipment['exerciseDefinitions'][0]['id']
        assert restored.pop('coachingAuthority')['localNotes'] == draft['workouts'][0]['exercises'][index]['placementNotes']
        rendered = restored.pop('renderedGuidance')
        assert rendered == original['placementNotes']
        restored['placementNotes'] = rendered
        assert restored == original
        assert 'muscleGroups' not in occurrence and 'exerciseType' not in occurrence
    assert review._review_pointer(context, '/draft/libraryDefinitions/LIBRARY_0/exerciseType')
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    approved = review.review_draft(None, result, messages, equipment)
    review.require_current_review(approved, messages, equipment)
    for key, value in [('bodyWeightPercentage', 66), ('movementRef', None)]:
        changed = copy.deepcopy(approved)
        changed['planIndex']['exercises'][1][key] = value
        with pytest.raises(ValueError, match='missing or stale'):
            review.require_current_review(changed, messages, equipment)


def test_related_summary_cannot_hide_material_records_from_another_selected_movement():
    related = {'reference': 'HISTORY_0', 'name': 'Historical movement', 'sessions': [
        {'performances': [{'record': {'actualReps': 8, 'loadKg': 40, 'autoRegulationRIR': 2}}]}]}
    summary = {key: value for key, value in related.items() if key != 'sessions'} | {'historyDetailsOmitted': True}
    compact = review._compact_review_history([
        {'reference': 'LIBRARY_0', 'relatedMovementHistory': [summary]},
        {'reference': 'LIBRARY_1', 'relatedMovementHistory': [related]},
    ])
    assert not compact['HISTORY_0'].get('historyDetailsOmitted')
    assert compact['HISTORY_0']['sessions'][0]['performances'][0]['record']['autoRegulationRIR'] == 2


def test_review_history_compacts_only_reconstructible_repetition_and_keeps_effort_and_load_units():
    caution = review.RELATED_LOAD_TRANSFER_CAUTION
    record = {'actualReps': 8, 'loadKg': 40, 'loadMeaning': 'app_total_external_load', 'autoRegulationRIR': 2}
    historical = {'reference': 'LIBRARY_1', 'definitionId': 'historical-uuid', 'name': 'Single-arm row',
        'sessions': [{'date': '2026-10-01', 'performances': [{'order': 0, 'intraSetRestInSeconds': 20, 'record': record}]}]}
    roots = [{'reference': 'LIBRARY_0', 'name': 'Pair row', 'relatedMovementHistory': [
        {**historical, 'differences': {'name': {'candidate': 'Pair row', 'historical': 'Single-arm row'},
             'equipmentId': {'candidate': 'pair', 'historical': 'single'}}, 'loadTransfer': caution}]},
        {'reference': 'LIBRARY_2', 'name': 'Other row', 'relatedMovementHistory': [
             {**historical, 'loadTransfer': 'The historical load excludes the implement.'}]}]
    before = copy.deepcopy(roots)
    compact = review._compact_review_history(roots)
    link = compact['LIBRARY_0']['relatedMovementHistory'][0]
    assert 'loadTransfer' not in link and 'name' not in link['differences']
    assert link['differences']['equipmentId'] == {'candidate': 'pair', 'historical': 'single'}
    assert compact['LIBRARY_2']['relatedMovementHistory'][0]['loadTransfer'] == 'The historical load excludes the implement.'
    performance = compact['LIBRARY_1']['sessions'][0]['performances'][0]
    assert performance['record'] == record and performance['intraSetRestInSeconds'] == 20
    assert roots == before


@pytest.mark.parametrize('path', ['/draft/exercises/0/name', '/exercises/0/muscleGroups/0'])
def test_reviewer_occurrence_field_citations_resolve_to_shared_data_without_losing_patch_location(monkeypatch, path):
    equipment, _, stored, draft = planning_case()
    finding = {**_finding(), 'path': path, 'evidencePaths': [path]}
    monkeypatch.setattr(review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    result = json.loads(handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert not result['passed'] and not result['review'].get('failure')
    error = result['errors'][0]
    assert error['path'].startswith('/draft/libraryDefinitions/LIBRARY_0/')
    assert error['draftPath'] == '/workouts/0/exercises/0'


@pytest.mark.parametrize('resolution_kind,passing', [
    ('missing', False), ('open', False), ('unrelated_change', False), ('fixed', True), ('long_resolution', True), ('withdrawal', True)])
def test_known_blocker_requires_explicit_supported_resolution(monkeypatch, resolution_kind, passing):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['placementNotes'] = (
        'No added gear; bodyweight only.' if resolution_kind == 'withdrawal' else 'Use a band for every rep.')
    messages = requirement_messages(stored)
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        previous = payload.get('previousBlockingFindings')
        if not previous:
            finding = {**_finding(), 'message': 'The prescribed band is unavailable in confirmed equipment.',
                       'evidencePaths': ['/draft/exercises/0/placementNotes', '/equipment']}
            return json.dumps({'findings': [finding]}), None, None
        assert all('_reviewRef' not in item for item in previous.values())
        reply = {'findings': []}  # Forgetting a known blocker must never approve the draft.
        if resolution_kind != 'missing':
            status = ('open' if resolution_kind == 'open' else 'withdrawn_review_error'
                      if resolution_kind == 'withdrawal' else 'resolved_by_change')
            reply['blockerResolutions'] = {key: {'status': status, 'action': 'repair' if status == 'open' else 'none',
                'reason': 'The existing note explicitly needs no band; prior review was wrong.' if status == 'withdrawn_review_error'
                          else ('The actual band instruction was removed. ' * 24) if resolution_kind == 'long_resolution'
                          else 'The actual band instruction was removed.' if resolution_kind == 'fixed'
                          else 'The setup problem still needs correction.',
                'evidencePaths': ['/draft/exercises/0/placementNotes']} for key in previous}
        return json.dumps(reply), None, None
    monkeypatch.setattr(review, 'chat_call', respond)
    first = review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    assert not first['passed']
    _store(messages, {'result': json.dumps(first)}, 'known-blocker')
    patch = [{'op': 'replace', 'path': '/workouts/0/description', 'value': 'Different focus'}]
    if resolution_kind in ('fixed', 'long_resolution'):
        patch.append({'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Bodyweight only; no band.'})
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': first['currentDraftId'], 'patch': patch}, equipment, messages)
    result = review.review_draft(None, raw, messages, equipment)
    assert result['passed'] is passing, result.get('errors')
    if passing:
        _store(messages, {'result': json.dumps(result)}, 'resolved-blocker')
        review.require_current_review(result, messages, equipment)
        proof = next(iter(result['review']['scopeResults']['execution']['blockerResolutions'].values()))
        assert proof['reason'] and proof['evidencePaths'] == ['/draft/exercises/0/placementNotes']
        if resolution_kind == 'long_resolution':
            assert proof['reason'] == 'The actual band instruction was removed. ' * 24
        tampered = copy.deepcopy(result)
        tampered['review']['reviewLedgerOutputFingerprint'] = 'tampered-ledger-output'
        with pytest.raises(ValueError, match='missing or stale'):
            review.require_current_review(tampered, messages, equipment)
    else:
        assert 'preview' not in result and 'planIndex' not in result
        if resolution_kind == 'unrelated_change':
            resolution = next(iter(result['review']['scopeResults']['execution']['blockerResolutions'].values()))
            assert resolution['status'] == 'open'
            assert 'did not cite a verified change' in resolution['reason']
        if resolution_kind == 'open':
            assert result['errors'][0]['message'] == 'The setup problem still needs correction.'
            _store(messages, {'result': json.dumps(result)}, 'still-open')
            monkeypatch.setattr(review, 'chat_call', lambda *a, **k: pytest.fail('An unchanged reconciled blocker is cached'))
            unchanged = audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': result['currentDraftId'], 'patch': []}, equipment, messages)
            assert not review.review_draft(None, unchanged, messages, equipment)['passed']


@pytest.mark.parametrize('role,expected', [('user', True), ('assistant', False)])
def test_blocker_resolution_requires_actual_new_user_authority(role, expected):
    assert review._blocker_change_cited('/sourceMessages/SOURCE_1', {'previousSourceCount': 1},
        {'sourceMessages': {'SOURCE_1': {'role': role}}}, {}) is expected


def test_unchanged_blocker_cannot_be_closed_by_an_unrelated_repair():
    resolution = {'status': 'resolved_by_change', 'reason': 'An unrelated field changed.',
        'evidencePaths': ['/draft/exercises/1/placementNotes']}
    prior = {'path': '/draft/exercises/1/placementNotes', 'message': 'The unsupported setup cue remains.'}
    review._retain_unmodified_blocker(resolution, prior, ['/draft/exercises/1/placementNotes'])
    assert resolution == {'status': 'open', 'action': 'repair',
        'reason': 'The proposed resolution did not cite a verified change for this finding; keep it open for reassessment. Prior finding: The unsupported setup cue remains.',
        'evidencePaths': ['/draft/exercises/1/placementNotes']}
