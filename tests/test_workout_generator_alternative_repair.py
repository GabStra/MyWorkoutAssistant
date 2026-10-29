import copy
import json

import pytest

from workout_generator_pkg.conflict_resolution import render_alternative_preview
from workout_generator_pkg.user_interaction import pending_question
from workout_generator_pkg.alternative_repair import execute_repair
from workout_generator_pkg.plan_review import _actionable_review_errors


def test_alternative_repair_keeps_shared_candidate_contract():
    from workout_generator_pkg.planning_tools import coordinated_repair_tool
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool

    task = {'repairCandidateId': 'ALT_1', 'originalRequirementsId': 'REQ_1',
        'currentDraft': {'workouts': [{'exercises': [{}]}, {'exercises': [{'definition_id': 'LIBRARY_7'}, {}]}]},
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair'}]}}
    shared = coordinated_repair_tool(task)['function']['description']
    alternative = repair_workout_alternative_tool(task)['function']
    assert shared in alternative['description']
    assert 'WORKOUT_1: EXERCISE_1, EXERCISE_2' in alternative['description']
    assert 'EXERCISE_1=LIBRARY_7' in alternative['description']
    assert '500 characters of local technique/setup cues' in alternative['description']
    assert 'exerciseMoves only to move an existing movement to a different workout' in alternative['description']
    assert alternative['parameters']['properties']['repairCandidateId']['enum'] == ['ALT_1']
    assert 'baseDraftId' not in alternative['parameters']['properties']


def test_alternative_repair_tool_offers_replacement_only_for_a_saved_proposal():
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool

    candidate, _ = _repair_scope_case()
    assert 'replaceRejectedRepair' not in repair_workout_alternative_tool(candidate)['function']['parameters']['properties']
    candidate['submissionCorrectionEdits'] = {'exerciseRemovals': ['EXERCISE_0']}
    tool = repair_workout_alternative_tool(candidate)['function']
    assert 'replaceRejectedRepair' in tool['parameters']['properties']
    assert 'amended by default' in tool['description']


def test_alternative_note_rejection_explains_local_limit_and_current_repair_tool():
    from jsonschema import validate, ValidationError
    from workout_generator_pkg.planning_tools import planning_tool_failure

    with pytest.raises(ValidationError) as caught:
        validate({'edits': {'placementNotes': 'x' * 501}}, {'properties': {'edits': {
            'properties': {'placementNotes': {'type': 'string', 'maxLength': 500}}}}})
    feedback = planning_tool_failure('repair_workout_alternative', caught.value)
    error = feedback['errors'][0]
    assert 'repair_workout_alternative' in error['repair']
    assert 'audit_workout_plan' not in error['repair']
    contract = error['textFieldContract']
    assert contract['currentCharacters'] == 501 and contract['maximumCharacters'] == 500
    assert contract['charactersToRemove'] == 1
    assert 'rendered separately' in contract['purpose']
    assert 'local technique/setup cues only' in error['repair']


def test_repaired_alternative_preview_is_bound_to_latest_success_and_original_requirements():
    proposal = {
        'proposalId': 'ALT_REPAIRED_1',
        'originalRequirementsId': 'REQ_ORIGINAL',
        'baseDraftId': 'DRAFT_CURRENT',
        'changes': [{'path': '/auditTargets/maxSessionSeconds', 'from': 600, 'to': 720}],
        'workouts': [{'exercises': []}],
        'independentReview': {'passed': True, 'preview': 'Reviewed alternative preview'},
    }
    repair_result = {'passed': True, 'outcome': 'alternatives_ready',
        'repairStatus': 'repaired_and_reviewed', 'proposal': proposal}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'req', 'function': {'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'req', 'content': json.dumps({'requirementsId': 'REQ_ORIGINAL', 'requirements': {'auditTargets': {}}})},
        {'role': 'assistant', 'tool_calls': [{'id': 'repair', 'function': {'name': 'repair_workout_alternative', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'repair', 'content': json.dumps(repair_result)},
        {'role': 'assistant', 'content': render_alternative_preview(proposal),
         'canonicalAlternativePreview': proposal['proposalId']},
    ]

    question = pending_question(messages)
    assert question['kind'] == 'alternative'
    assert question['reference'] == proposal['proposalId']

    changed_preview = copy.deepcopy(messages)
    changed_preview[-1]['content'] += '\nUnreviewed change'
    assert pending_question(changed_preview) is None

    stale = copy.deepcopy(messages)
    stale.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'diagnosis', 'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'diagnosis', 'content': json.dumps({'outcome': 'unresolved', 'proposals': []})},
    ])
    assert pending_question(stale) is None


def test_actionable_review_errors_keep_indexes_from_complete_finding_ledger():
    review = {
        'findings': [
        {'severity': 'warning', 'message': 'Advisory row'},
        {'severity': 'blocking', 'message': 'Actionable row'},
        ],
        'assessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'advisory'},
        {'findingIndexes': [1], 'disposition': 'repair'},
        ]},
    }
    actionable = _actionable_review_errors(review)
    assert [error['findingIndex'] for error in actionable] == [1]
    assert actionable[0]['message'] == 'Actionable row'


def _repair_scope_case(training_days=(0, 5)):
    candidate = {
        'repairCandidateId': 'REVISION_1', 'baseDraftId': 'REVISION_1',
        'originalRequirementsId': 'REQ_ORIGINAL', 'requirementsId': 'REQ_ALT',
        'requirements': {}, 'changes': [], 'candidateMenuFingerprint': 'menu',
        'libraryFingerprint': 'library', 'trainingHistoryFingerprint': 'history',
        'currentDraft': {'name': 'Four day plan'},
        'workouts': [
            {'trainingDays': [training_days[0]], 'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 1}]},
            {'trainingDays': [training_days[1]], 'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 1}]},
        ],
        'findingsAssessment': {'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['ordering']},
        ]},
        'reviewFindings': [{'draftPath': '/workouts/0', 'path': '/workouts/0'}],
    }
    arguments = {
        'repairCandidateId': 'REVISION_1', 'originalRequirementsId': 'REQ_ORIGINAL',
        'addressedFindingIndexes': [0],
        'edits': {'workoutUpdates': [
            {'workoutRef': 'WORKOUT_1', 'setFields': {'trainingDays': [6]}},
        ]},
    }
    return candidate, arguments


def _stub_repair_preconditions(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    import workout_generator_pkg.planning_tools as planning_tools
    import workout_generator_pkg.planning_decisions as planning_decisions

    monkeypatch.setattr(alternative_repair, '_fresh_binding', lambda *args: True)
    monkeypatch.setattr(alternative_repair, '_latest_result', lambda *args: (0, {'requirements': {}}))
    monkeypatch.setattr(alternative_repair, '_validate_draft_schema', lambda *args: None)
    monkeypatch.setattr(alternative_repair, 'normalize_work_set_bounds', lambda draft, *args: draft)
    monkeypatch.setattr(alternative_repair, 'build_draft_plan', lambda *args: {})
    monkeypatch.setattr(planning_tools, 'require_approved_requirements', lambda messages: None)
    monkeypatch.setattr(planning_decisions, 'resolved_decisions', lambda messages: {})


def test_alternative_repair_passes_compiled_refs_for_cross_workout_schedule_change(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool
    from jsonschema import validate

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    candidate['workouts'][0]['exercises'].append({'definition_id': 'LIBRARY_2', 'numWorkSets': 1})
    candidate['workouts'][1]['exercises'][0]['definition_id'] = 'LIBRARY_3'
    candidate['workouts'][1]['exercises'].append({'definition_id': 'LIBRARY_4', 'numWorkSets': 1})
    arguments = {'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': candidate['originalRequirementsId'], 'addressedFindingIndexes': [0],
        'sessionBlocks': [
            {'sessionReference': 'WORKOUT_0', 'blocks': [
                {'exercises': ['EXERCISE_0']}, {'exercises': ['EXERCISE_2']}]},
            {'sessionReference': 'WORKOUT_1', 'blocks': [
                {'exercises': ['EXERCISE_1']}, {'exercises': ['EXERCISE_3']}]}]}
    tool = repair_workout_alternative_tool({**candidate,
        'currentDraft': {'workouts': copy.deepcopy(candidate['workouts'])}})['function']
    assert 'sessionBlocks' in tool['parameters']['required']
    assert 'edits' not in tool['parameters']['properties']
    assert 'typed edits transaction' not in tool['description']
    validate(arguments, tool['parameters'])

    def solve(sessions, requirements, equipment, restriction_policy, **kwargs):
        assert [[item['definition_id'] for item in day['exercises']] for day in sessions] == [
            ['LIBRARY_1', 'LIBRARY_3'], ['LIBRARY_2', 'LIBRARY_4']]
        assert requirements == candidate['requirements']
        assert kwargs['preserve_source_selection'] is True
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
            'occurrenceLineage': [[[0, 0], [0, 1]], [[1, 0], [1, 1]]]}

    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', solve)

    class ReachedAudit(Exception):
        pass

    def audit_candidate(candidate, workouts, *args):
        assert [[item['definition_id'] for item in day['exercises']] for day in workouts] == [
            ['LIBRARY_1', 'LIBRARY_3'], ['LIBRARY_2', 'LIBRARY_4']]
        raise ReachedAudit

    monkeypatch.setattr(alternative_repair, '_audit_candidate', audit_candidate)
    with pytest.raises(ReachedAudit):
        alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)


def test_alternative_repair_preserves_prior_proposal_across_invalid_and_partial_corrections(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    previous = {'workoutUpdates': [
        {'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Keep original focus'}},
        {'workoutRef': 'WORKOUT_1', 'setFields': {'trainingDays': [6]}},
    ]}
    candidate['submissionCorrectionEdits'] = previous
    malformed_attempt = {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'unsupportedTypedField': 'malformed'}}]}
    arguments['edits'] = copy.deepcopy(malformed_attempt)

    invalid_result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)
    assert invalid_result['failureStage'] == 'repair_admission'
    assert invalid_result['submittedEdits'] == previous
    assert invalid_result['rejectedAttemptEdits'] == malformed_attempt
    assert invalid_result['findingsAssessment'] == candidate['findingsAssessment']

    resumed_candidate = copy.deepcopy(candidate)
    resumed_candidate['submissionCorrectionEdits'] = invalid_result['submittedEdits']
    corrected = {'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': candidate['originalRequirementsId'], 'addressedFindingIndexes': [0],
        'edits': {'workoutUpdates': [{'workoutRef': 'WORKOUT_1',
            'setFields': {'trainingDays': [6]}}]}}
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: {'feasible': False, 'status': 'unproven'})

    from types import SimpleNamespace
    from workout_generator_pkg import interactive_shell as shell
    from workout_generator_pkg.planner_context import _sanitize_stale_history_receipts
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool
    from test_workout_generator_planner_context import _history_bound_run, _state

    resumed_candidate['trainingHistoryFingerprint'] = 'history'
    assert 'replaceRejectedRepair' in repair_workout_alternative_tool(resumed_candidate)['function']['parameters']['properties']
    _, _, _, messages = _history_bound_run('history')
    handled = shell.handle_function_call(None, messages, 'repair_workout_alternative', corrected, {},
        deps=SimpleNamespace(execute_workout_generation=None), alternative_repair_task=resumed_candidate)
    corrected_result = json.loads(handled['result'])
    assert corrected_result['attemptStatus'] == 'joint_repair_unresolved'
    assert corrected_result['submittedEdits']['workoutUpdates'] == previous['workoutUpdates']
    assert corrected_result['rejectedAttemptEdits'] == corrected['edits']
    assert corrected_result['trainingHistoryFingerprint'] == 'history'
    assert corrected_result['findingsAssessment'] == candidate['findingsAssessment']
    assert corrected_result['candidateSnapshot']['workouts'] == candidate['workouts']

    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'resumed_repair', 'type': 'function',
            'function': {'name': 'repair_workout_alternative', 'arguments': json.dumps(corrected)}}]},
        {'role': 'tool', 'tool_call_id': 'resumed_repair', 'content': json.dumps(corrected_result)},
    ])
    sanitized = _sanitize_stale_history_receipts(messages, 'history', True)
    saved = next(message for message in sanitized if message.get('tool_call_id') == 'resumed_repair')
    assert json.loads(saved['content']) == corrected_result
    state = _state(shell._messages_for_api(messages, True,
        SimpleNamespace(fingerprint='history', context=lambda: {'historyFingerprint': 'history'}), {}))
    assert not state.get('staleHistoryBoundReceipts')
    assert state['otherToolResults']['repair_workout_alternative']['attemptStatus'] == 'joint_repair_unresolved'


def test_explicit_alternative_replacement_still_requires_the_complete_assessment(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, _ = _repair_scope_case()
    candidate['findingsAssessment'] = {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['ordering']},
        {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['prescription']},
    ]}
    candidate['reviewFindings'] = [
        {'draftPath': '/workouts/0', 'path': '/workouts/0'},
        {'draftPath': '/workouts/0/exercises/0/numWorkSets', 'path': '/workouts/0/exercises/0/numWorkSets'},
    ]
    candidate['submissionCorrectionEdits'] = {'exerciseRemovals': ['EXERCISE_0']}
    replacement = {'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': candidate['originalRequirementsId'],
        'addressedFindingIndexes': [0, 1], 'replaceRejectedRepair': True,
        'edits': {'workoutUpdates': [{'workoutRef': 'WORKOUT_1',
            'setFields': {'trainingDays': [6]}}]}}
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('An incomplete assessed replacement must be rejected before solving.'))

    result = alternative_repair.execute_repair(replacement, candidate, [], {}, None, True, None)
    assert result['attemptStatus'] == 'repair_failed'
    assert result['failureStage'] == 'repair_admission'
    assert result['replacedSubmittedEdits'] == candidate['submissionCorrectionEdits']
    assert result['submittedEdits'] == replacement['edits']
    assert result['findingsAssessment'] == candidate['findingsAssessment']


def test_final_scope_rejection_preserves_solver_receipt_and_candidate(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    from workout_generator_pkg.planning_tools import PlanningInputError

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    validations = []

    def validate_scope(*args):
        validations.append(1)
        if len(validations) == 2:
            raise PlanningInputError('assessed_repair_not_addressed', 'Final coverage failed.', '/patch', 'Repair all findings.')

    monkeypatch.setattr(alternative_repair, 'validate_repair_scope', validate_scope)
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda sessions, *args, **kwargs: {'feasible': True, 'status': 'optimal',
            'sessions': copy.deepcopy(sessions), 'occurrenceLineage': [[[0, 0]], [[1, 0]]]})
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda *args: pytest.fail('Final repair-scope rejection must stop before audit.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['attemptStatus'] == 'repair_failed'
    assert result['failureStage'] == 'final_repair_scope'
    assert result['jointSolve']['status'] == 'optimal'
    assert result['workouts'][1]['trainingDays'] == [6]
    assert result['solvedMenuFingerprint']
    assert result['errors'][0]['code'] == 'assessed_repair_not_addressed'


def test_missing_solver_lineage_preserves_solved_candidate_without_model_retry(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    solved = copy.deepcopy(candidate['workouts'])
    solved[1]['trainingDays'] = [6]
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: {'feasible': True, 'status': 'optimal', 'sessions': solved})
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda *args: pytest.fail('Missing internal lineage must stop before audit.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['outcome'] == 'unresolved'
    assert result['attemptStatus'] == 'joint_repair_unresolved'
    assert result['failureStage'] == 'solver_lineage'
    assert result['jointSolve']['status'] == 'optimal'
    assert 'sessions' not in result['jointSolve']
    assert result['workouts'] == solved
    assert result['solvedMenuFingerprint']
    assert result['errors'][0]['code'] == 'missing_occurrence_lineage'
    assert 'cannot be corrected by changing the repair edits' in result['reason']


def test_alternative_repair_preflights_invalid_guidance_before_joint_solver(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    from workout_generator_pkg.planning_tools import PlanningInputError

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    monkeypatch.setattr(alternative_repair, '_validate_draft_schema', lambda *args: (_ for _ in ()).throw(
        PlanningInputError('progression_in_local_notes', 'Local notes duplicate typed progression.',
            '/workouts/0/exercises/0/placementNotes', 'Keep notes local.')))
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('Invalid typed source must be rejected before the solver.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['attemptStatus'] == 'repair_failed'
    assert result['errors'][0]['code'] == 'progression_in_local_notes'
    assert 'no feasibility or requirement conflict was established' in result['reason']


@pytest.mark.parametrize(('solver_receipt', 'attempt_status'), [
    ({'feasible': False, 'status': 'infeasible'}, 'repair_menu_infeasible'),
    ({'feasible': False, 'status': 'unproven'}, 'joint_repair_unresolved'),
    ({'feasible': False, 'status': 'infeasible', 'rejectedOptions': [
        {'code': 'invalid_recipe', 'message': 'The supplied recipe is invalid.'}]}, 'joint_repair_unresolved'),
])
def test_alternative_repair_preserves_joint_solver_status_without_global_conflict_claim(monkeypatch, solver_receipt, attempt_status):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    status = solver_receipt['status']
    solver_receipt.setdefault('instruction', 'No combination in the supplied prescription menu satisfies the joint model.')
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: solver_receipt)
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda *args: pytest.fail('An infeasible or unresolved menu must not reach audit or review.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['outcome'] == 'unresolved'
    assert result['attemptStatus'] == attempt_status
    assert result['jointSolve']['status'] == status
    assert 'sessions' not in result['jointSolve']
    if status == 'infeasible' and solver_receipt.get('rejectedOptions'):
        assert 'complete menu was not validated' in result['reason']
    elif status == 'infeasible':
        assert 'requirements themselves impossible' in result['reason']
    else:
        assert 'do not claim a conflict' in result['reason']


def test_infeasible_alternative_repair_keeps_candidate_snapshot_separate_from_proposal(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    candidate['findingsAssessment']['groups'].append({
        'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['program_guidance'],
    })
    candidate['reviewFindings'].append({
        'draftPath': '/workouts/0',
        'evidencePaths': ['/draft/workouts/0', '/draft/workouts/1', '/draft'],
        'message': 'The plan has no plan-wide recovery guidance.',
    })
    arguments['addressedFindingIndexes'] = [0, 1]
    guidance = 'Keep the approved plan and trim the lowest-priority work if recovery falters.'
    arguments['edits']['programGuidance'] = guidance
    original_candidate = copy.deepcopy(candidate)
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: {'feasible': False, 'status': 'infeasible'})
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda *args: pytest.fail('An infeasible menu must not reach audit.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['attemptStatus'] == 'repair_menu_infeasible'
    assert result['candidateSnapshot'] == original_candidate
    assert result['candidateSnapshot'].get('programGuidance') is None
    assert result['submittedEdits']['programGuidance'] == guidance
    assert result['workouts'][1]['trainingDays'] == [6]
    assert candidate == original_candidate


def test_final_repair_scope_keeps_global_guidance_change_after_joint_solve(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    candidate['findingsAssessment']['groups'].append({
        'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['program_guidance'],
    })
    candidate['reviewFindings'].append({
        'draftPath': '/workouts/0',
        'evidencePaths': ['/draft/workouts/0', '/draft/workouts/1', '/draft'],
    })
    arguments['addressedFindingIndexes'] = [0, 1]
    guidance = 'Keep the approved plan and trim the lowest-priority work if recovery falters.'
    arguments['edits']['programGuidance'] = guidance
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda sessions, *args, **kwargs: {'feasible': True, 'status': 'optimal',
            'sessions': copy.deepcopy(sessions), 'occurrenceLineage': [[[0, 0]], [[1, 0]]]})

    class ReachedAudit(Exception):
        pass

    def check_audit_candidate(candidate_for_audit, workouts, *args):
        assert candidate_for_audit['programGuidance'] == guidance
        assert workouts[1]['trainingDays'] == [6]
        raise ReachedAudit

    monkeypatch.setattr(alternative_repair, '_audit_candidate', check_audit_candidate)
    with pytest.raises(ReachedAudit):
        alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)


def test_alternative_repair_rechecks_assessed_coverage_after_joint_solver(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *args, **kwargs: {'feasible': True, 'status': 'optimal',
            'sessions': copy.deepcopy(candidate['workouts']), 'occurrenceLineage': [[[0, 0]], [[1, 0]]]})
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda *args: pytest.fail('The solver undid the only assessed repair; reject before audit.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)
    assert result['attemptStatus'] == 'repair_failed'
    assert result['failureStage'] == 'final_repair_scope'
    assert result['jointSolve']['status'] == 'optimal'
    assert result['workouts'][1]['trainingDays'] == [5]
    assert result['errors'][0]['code'] == 'assessed_repair_not_addressed'


def test_alternative_repair_still_rejects_unchanged_schedule_edit(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case(training_days=(0, 6))

    def unexpected_audit(*args):
        pytest.fail('An unchanged workout day must be rejected before numerical audit.')

    monkeypatch.setattr(alternative_repair, '_audit_candidate', unexpected_audit)
    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)
    assert result['attemptStatus'] == 'repair_failed'
    assert result['failureStage'] == 'repair_admission'
    assert result['errors'][0]['code'] == 'assessed_repair_not_addressed'


def test_alternative_repair_stops_when_assessment_has_no_supported_repair_capability(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    candidate['findingsAssessment']['groups'][0]['disposition'] = 'unresolved_capability'
    monkeypatch.setattr('workout_generator_pkg.repair_capabilities.has_unresolved_capabilities', lambda value: True)
    monkeypatch.setattr(alternative_repair, 'compile_coordinated_repair',
        lambda *args: pytest.fail('Unsupported findings must not be sent back through model repair.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['outcome'] == 'unresolved'
    assert result['attemptStatus'] == 'capability_unresolved'
    assert result['candidateSnapshot']['repairCandidateId'] == candidate['repairCandidateId']


def _stub_repair_materialization(monkeypatch, audit):
    import workout_generator_pkg.alternative_repair as alternative_repair
    import workout_generator_pkg.cancellation as cancellation
    import workout_generator_pkg.planning_tools as planning_tools
    import workout_generator_pkg.allocation as allocation
    import workout_generator_pkg.review_assessment as review_assessment

    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    candidate.update(sourceDraftId='ACTIVE_DRAFT', sourceMenuFingerprint='source-menu',
        candidateMenuFingerprint='candidate-menu', originalRequirementsHash='requirements-hash',
        diagnosisCandidateId='DIAGNOSIS_1', requirements={'auditTargets': {}},
        candidateName='Alternative', review={'version': 1, 'findings': []}, reviewVersion=1)
    patch = [{'op': 'replace', 'path': '/workouts/1/trainingDays', 'value': [6]}]
    monkeypatch.setattr(alternative_repair, 'compile_coordinated_repair',
        lambda *args, **kwargs: ({'patch': patch}, [{'operationIndex': 0}]))
    monkeypatch.setattr(alternative_repair, 'validate_repair_scope', lambda *args: None)
    monkeypatch.setattr(allocation, 'qualify_workout_recipes',
        lambda client, workouts, *args, **kwargs: (copy.deepcopy(workouts), {'contracts': []}))
    monkeypatch.setattr(review_assessment, 'validate_assessment', lambda *args, **kwargs: None)
    def solve_preserving_candidate(sessions, *args, **kwargs):
        assert kwargs['preserve_source_selection'] is True
        return {'feasible': True, 'status': 'optimal', 'preserveSourceSelection': True,
            'selectionPolicyVersion': 10, 'problemFingerprint': 'preserved-repair-fingerprint',
            'sessions': copy.deepcopy(sessions), 'occurrenceLineage': [[[0, 0]], [[1, 0]]]}

    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', solve_preserving_candidate)
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda candidate, workouts, *args: ({'name': 'Alternative', 'workouts': copy.deepcopy(workouts)},
            {'plan': 'audited'}, copy.deepcopy(audit), {}))
    monkeypatch.setattr(alternative_repair, '_append_hypothetical_requirements', lambda *args: [])
    monkeypatch.setattr(planning_tools, 'render_draft', lambda *args: 'preview')
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda *args: 'library')
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION, assessment_hash
    review = {'version': REVIEW_VERSION, 'inputHash': 'stub-review',
        'findings': [{'severity': 'blocking', 'message': 'Review finding'}]}
    review['assessment'] = {'version': ASSESSMENT_VERSION,
        'inputHash': assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['session_labels'], 'reason': 'Correct the review finding.'}],
        'repairPlan': 'Correct the review finding.'}
    monkeypatch.setattr(cancellation, 'run_cancellable', lambda function, *args, **kwargs: {
        'passed': False, 'errors': [{'code': 'semantic_issue', 'message': 'Review finding'}],
        'review': review,
        'preview': 'rejected preview'})
    return candidate, arguments


def test_alternative_repair_numeric_rejection_has_resumable_failure_contract(monkeypatch):
    errors = [{'code': 'duration_exceeded', 'message': 'The plan exceeds its time limit.'}]
    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': errors})

    result = execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['passed'] is False
    assert result['outcome'] == 'unresolved'
    assert result['attemptStatus'] == 'repair_failed'
    assert result['errors'] == errors
    assert result['candidateSnapshot']['workouts'] == candidate['workouts']
    assert result['workouts'][1]['trainingDays'] == [6]
    assert result['submittedEdits'] == arguments['edits']
    assert 'proposal' not in result


def test_alternative_repair_review_rejection_saves_new_unapproved_revision(monkeypatch):
    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    original_id = candidate['repairCandidateId']
    review_errors = [{'code': 'semantic_issue', 'message': 'Review finding'}]

    result = execute_repair(arguments, candidate, [], {}, None, True, None)

    snapshot = result['candidateSnapshot']
    assert result['passed'] is False
    assert result['outcome'] == 'unresolved'
    assert result['attemptStatus'] == 'repair_review_failed'
    assert result['errors'] == review_errors
    assert result['jointSolve']['preserveSourceSelection'] is True
    assert result['jointSolve']['selectionPolicyVersion'] == 10
    assert result['jointSolve']['problemFingerprint'] == 'preserved-repair-fingerprint'
    assert snapshot['workouts'][1]['trainingDays'] == [6]
    assert snapshot['repairCandidateId'] != original_id
    assert snapshot['diagnosisCandidateId'] == 'DIAGNOSIS_1'
    assert snapshot['parentRepairCandidateId'] == original_id
    assert snapshot['sourceDraftId'] == 'ACTIVE_DRAFT'
    assert snapshot['baseDraftId'] == 'ACTIVE_DRAFT'
    assert snapshot['candidateMenuFingerprint']
    assert snapshot['audit']['errors'] == []
    assert snapshot['reviewErrors'] == review_errors
    assert snapshot['review']['findings'][0]['message'] == 'Review finding'
    assert not any(field in snapshot for field in ('currentDraft', 'findingsAssessment',
        'reviewFindings', 'errors', 'submissionCorrectionErrors', 'instruction'))
    assert 'proposal' not in result


def test_exercise_selection_repair_preserves_selected_placement_and_programming_evidence(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair

    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    candidate['findingsAssessment']['groups'][0]['repairDimensions'] = ['exercise_selection']
    patch = [{'op': 'replace', 'path': '/workouts/1/exercises/0/definition_id', 'value': 'LIBRARY_2'}]
    monkeypatch.setattr(alternative_repair, 'compile_coordinated_repair',
        lambda *args, **kwargs: ({'patch': patch}, [{'operationIndex': 0}]))
    receipt = {'priorityExecution': {'status': 'ran'}, 'priorityTradeoffs': {'items': []},
        'demandDistribution': {'status': 'available'}}
    observed = {}

    def solve(sessions, *args, **kwargs):
        observed['preserve_source_selection'] = kwargs['preserve_source_selection']
        return {'feasible': True, 'status': 'optimal',
            'preserveSourceSelection': kwargs['preserve_source_selection'],
            'sessions': copy.deepcopy(sessions), 'occurrenceLineage': [[[0, 0]], [[1, 0]]],
            **receipt}

    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', solve)

    result = execute_repair(arguments, candidate, [], {}, None, True, None)

    assert observed['preserve_source_selection'] is False
    assert result['workouts'][1]['exercises'][0]['definition_id'] == 'LIBRARY_2'
    assert result['workouts'][0]['exercises'][0]['definition_id'] == candidate['workouts'][0]['exercises'][0]['definition_id']
    assert result['jointSolve']['preserveSourceSelection'] is False
    assert result['jointSolve']['demandDistribution'] == receipt['demandDistribution']
    assert result['jointSolve']['priorityExecution'] == receipt['priorityExecution']
    assert result['jointSolve']['priorityTradeoffs'] == receipt['priorityTradeoffs']


def test_ordering_repair_keeps_source_selection_locked(monkeypatch):
    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    candidate['findingsAssessment']['groups'][0]['repairDimensions'] = ['ordering']

    result = execute_repair(arguments, candidate, [], {}, None, True, None)

    assert result['jointSolve']['preserveSourceSelection'] is True


def test_alternative_repair_review_timeout_preserves_audited_pending_candidate(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    import workout_generator_pkg.cancellation as cancellation

    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    monkeypatch.setattr(cancellation, 'run_cancellable',
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('review deadline')))

    result = execute_repair(arguments, candidate, [], {}, None, True, None)

    snapshot = result['candidateSnapshot']
    assert result['attemptStatus'] == 'review_timeout'
    assert result['passed'] is False
    assert snapshot['reviewPending'] is True
    assert snapshot['audit']['errors'] == []
    assert snapshot['workouts'][1]['trainingDays'] == [6]
    assert snapshot['diagnosisCandidateId'] == 'DIAGNOSIS_1'
    assert snapshot['parentRepairCandidateId'] == candidate['repairCandidateId']
    assert snapshot['repairCandidateId'] != candidate['repairCandidateId']
    assert result['jointSolve']['problemFingerprint'] == 'preserved-repair-fingerprint'
    assert 'review' not in snapshot or snapshot['review'] == {}
    assert 'proposal' not in result


def test_program_guidance_survives_repair_review_and_failed_revision(monkeypatch):
    import workout_generator_pkg.alternative_repair as alternative_repair
    import workout_generator_pkg.cancellation as cancellation

    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    candidate['programGuidance'] = 'Use stable double progression; keep two reps in reserve.'
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda candidate, workouts, *args: ({'name': 'Alternative', 'workouts': copy.deepcopy(workouts),
            **({'programGuidance': candidate.get('programGuidance')} if candidate.get('programGuidance') else {})},
            {'plan': 'audited'}, {'errors': []}, {}))
    original_id = candidate['repairCandidateId']
    patched_guidance = 'Use stable double progression; add load only after all sets reach the top of range.'
    monkeypatch.setattr(alternative_repair, 'compile_coordinated_repair',
        lambda *args, **kwargs: ({'patch': [
            {'op': 'replace', 'path': '/workouts/1/trainingDays', 'value': [6]},
            {'op': 'replace', 'path': '/programGuidance', 'value': patched_guidance},
        ]}, [{'operationIndex': 0}, {'operationIndex': 1}]))
    captured = {}

    def inspect_review(function, client, snapshot, review_messages, *args, **kwargs):
        from workout_generator_pkg.plan_review import REVIEW_VERSION
        from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION, assessment_hash
        captured['submittedDraft'] = copy.deepcopy(snapshot['submittedDraft'])
        captured['reviewMessages'] = copy.deepcopy(review_messages)
        review = {'version': REVIEW_VERSION, 'inputHash': 'guidance-review',
            'findings': [{'severity': 'blocking', 'message': 'Review finding'}]}
        review['assessment'] = {'version': ASSESSMENT_VERSION,
            'inputHash': assessment_hash(review),
            'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                'repairDimensions': ['session_labels'], 'reason': 'Correct the review finding.'}],
            'repairPlan': 'Correct the review finding.'}
        return {
            'passed': False,
            'errors': [{'code': 'semantic_issue', 'message': 'Review finding'}],
            'review': review,
            'preview': 'rejected preview',
        }

    monkeypatch.setattr(cancellation, 'run_cancellable', inspect_review)
    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    snapshot = result['candidateSnapshot']
    assert captured['submittedDraft']['programGuidance'] == patched_guidance
    assert snapshot['programGuidance'] == patched_guidance
    assert snapshot['repairCandidateId'] != original_id
    assert result['attemptStatus'] == 'repair_review_failed'
    assert result.get('proposal') is None


def test_unrelated_alternative_repair_carries_reviewed_redistribution_into_solver_and_snapshot(monkeypatch):
    from workout_generator_pkg.repair_contract import build_repair_contract, expand_redistributions

    candidate, arguments = _stub_repair_materialization(monkeypatch, {'errors': []})
    for workout in candidate['workouts']:
        workout['exercises'][0]['numWorkSets'] = 5
    _, manifest = expand_redistributions({'exerciseRedistributions': [{
        'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'],
        'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}, {'workouts': candidate['workouts']})
    candidate['repairContract'] = build_repair_contract([], {'workouts': candidate['workouts']},
        candidate['requirements'], manifest, requirements_id=candidate['requirementsId'])
    arguments['edits'] = {'programGuidance': 'Keep two repetitions in reserve.'}
    import workout_generator_pkg.alternative_repair as alternative_repair
    monkeypatch.setattr(alternative_repair, 'compile_coordinated_repair',
        lambda *args, **kwargs: ({'patch': [{'op': 'add', 'path': '/programGuidance',
            'value': arguments['edits']['programGuidance']}]}, [{'operationIndex': 0}]))
    captured = {}

    def solve(sessions, *args, **kwargs):
        captured['constraints'] = copy.deepcopy(kwargs.get('redistribution_constraints'))
        return {'feasible': True, 'status': 'optimal', 'preserveSourceSelection': True,
            'selectionPolicyVersion': 10, 'problemFingerprint': 'constrained-replay',
            'redistributionOptimization': {'goal': 'minimize_total_peak_work_sets_across_target_sessions',
                'status': 'optimal', 'optimal': True, 'totalPeakWorkSets': 5},
            'sessions': copy.deepcopy(sessions), 'occurrenceLineage': [[[0, 0]], [[1, 0]]]}

    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', solve)
    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert captured['constraints'][0]['weeklyWorkSets'] == 10
    assert captured['constraints'][0]['targetWorkoutIndexes'] == [0, 1]
    assert result['jointSolve']['redistributionOptimization']['optimal'] is True
    assert result['candidateSnapshot']['repairContract']['redistributions'][0]['weeklyWorkSets'] == 10
    assert result['candidateSnapshot']['jointSolve']['redistributionOptimization']['optimal'] is True


def test_program_guidance_owner_can_address_workout_evidence_without_occurrence_refs():
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair, validate_repair_scope,
    )
    from test_workout_generator_planning_tools import planning_case

    current = copy.deepcopy(planning_case()[3])
    current['workouts'] = [copy.deepcopy(current['workouts'][0]) for _ in range(3)]
    finding = {
        'draftPath': '/workouts/0',
        'evidencePaths': ['/draft/workouts/0', '/draft/workouts/1', '/draft/workouts/2', '/draft'],
        'message': 'The plan has no plan-wide recovery guidance.',
    }
    findings = [{} for _ in range(32)] + [finding]
    task = {
        'requirementsId': current['requirementsId'],
        'baseDraftId': 'REVISION_320',
        'findingsAssessment': {'groups': [{'findingIndexes': [32], 'disposition': 'repair',
            'repairDimensions': ['program_guidance']}]},
        'reviewFindings': findings,
    }
    arguments = {
        'requirementsId': current['requirementsId'],
        'baseDraftId': 'REVISION_320',
        'addressedFindingIndexes': [32],
        'edits': {'programGuidance': 'Keep the approved plan and reduce the lowest-priority work if recovery falters.'},
    }

    compiled, operation_refs = compile_coordinated_repair(arguments, task, current)
    validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': operation_refs}, current)
    assert compiled['patch'][0]['path'] == '/programGuidance'
    assert operation_refs == [[]]

    wrong_owner_task = copy.deepcopy(task)
    wrong_owner_task['findingsAssessment']['groups'][0]['repairDimensions'] = ['session_labels']
    wrong_owner_compiled, wrong_owner_refs = compile_coordinated_repair(arguments, wrong_owner_task, current)
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(wrong_owner_compiled,
            {**wrong_owner_task, '_compiledRepairOperationRefs': wrong_owner_refs}, current)


def test_hypothetical_review_context_includes_current_program_guidance():
    from workout_generator_pkg.alternative_repair import _append_hypothetical_requirements

    candidate = {'requirementsId': 'REQ_ALT', 'originalRequirementsId': 'REQ_ORIGINAL',
        'requirements': {'auditTargets': {}}, 'changes': [], 'workouts': [], 'audit': {},
        'programGuidance': 'Use controlled reps and leave two reps in reserve.',
        'candidateName': 'Alternative', 'review': {'version': 1, 'findings': []}}
    messages = _append_hypothetical_requirements(messages=[], candidate=candidate,
        original_record={'requirementsId': 'REQ_ORIGINAL', 'requirements': {'auditTargets': {}}},
        equipment={}, history=None, allow_educated_load_guesses=True)

    submitted = json.loads(messages[-1]['content'])['submittedDraft']
    assert submitted['programGuidance'] == candidate['programGuidance']
