"""Shared solver and contract boundary for coordinated repair candidates."""

import copy
import json


_UNBOUNDED_SOURCE_WORKING_SET_BUDGET = {
    'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None,
}


def _source_budget_claims_explicit_limit(value):
    from .joint_planning import _source_working_set_budget_identity

    if value is None:
        return False
    try:
        return _source_working_set_budget_identity([], value)['variableWeeklyWorkingSets'] is not None
    except ValueError:
        return True


def _valid_repair_source_working_set_budget(value):
    from .joint_planning import _source_working_set_budget_identity

    if value is None:
        return False
    try:
        _source_working_set_budget_identity([], value)
    except ValueError:
        return False
    return True


def _current_messages_have_unverified_explicit_budget(messages, requirements_id):
    from .planning_tools import _latest_result

    for tool_name in ('draft_workout_sessions', 'audit_workout_plan', 'prepare_workout_sessions'):
        _, owner = _latest_result(messages, tool_name)
        if not isinstance(owner, dict) or owner.get('requirementsId') != requirements_id:
            continue
        budgets = [owner.get('sourceWorkingSetBudget')]
        for key in ('jointPlanning', 'coordinatedJointPlanning', 'automaticAllocation'):
            nested = owner.get(key)
            if isinstance(nested, dict):
                budgets.append(nested.get('sourceWorkingSetBudget'))
        if any(_source_budget_claims_explicit_limit(value) for value in budgets):
            return True
    return False


def _repair_source_working_set_budget(workouts, requirements, equipment, restriction_policy, *,
                                      requirements_id, allow_educated_load_guesses,
                                      training_history, messages, redistribution_constraints):
    from .planning_tools import _latest_result
    from .session_drafting import source_working_set_budget_for_worker

    _, workers = _latest_result(messages, 'draft_workout_sessions')
    if isinstance(workers, dict) and workers.get('requirementsId') == requirements_id:
        source_budget = source_working_set_budget_for_worker(
            messages, workers, equipment, getattr(training_history, 'fingerprint', None))
        if source_budget is not None:
            return source_budget
        if isinstance(workers.get('proposedSubmission'), dict):
            return None

    # A direct audit without a worker source may reuse only its latest own proof.
    _, source_audit = _latest_result(messages, 'audit_workout_plan')
    source_draft = source_audit.get('submittedDraft') if isinstance(source_audit, dict) else None
    source_workouts = source_draft.get('workouts') if isinstance(source_draft, dict) else None
    if (not isinstance(source_audit, dict)
            or source_audit.get('requirementsId') != requirements_id
            or not isinstance(source_workouts, list)
            or not source_workouts):
        return None
    source_proof = source_audit.get('coordinatedJointPlanning') or source_audit.get('automaticAllocation') or {}
    if not isinstance(source_proof, dict) or source_proof.get('feasible') is not True:
        return None
    from .allocation import reusable_joint_receipt
    validated = reusable_joint_receipt(source_audit, requirements_id, source_workouts,
        requirements, equipment, messages, training_history, restriction_policy,
        allow_educated_load_guesses,
        preserve_source_selection=source_proof.get('preserveSourceSelection') is True,
        redistribution_constraints=source_proof.get('redistributionConstraints') or [])
    return copy.deepcopy(validated.get('sourceWorkingSetBudget')) if validated else None


def _current_audited_preservation_workouts(requirements_id, equipment, messages, training_history):
    """Return only the exact passing audited source, never the proposed repair counts."""
    from .planning_tools import _latest_result, library_fingerprint
    from .planning_decisions import resolved_decisions

    _, audit = _latest_result(messages, 'audit_workout_plan')
    history_fingerprint = getattr(training_history, 'fingerprint', None)
    try:
        decisions = resolved_decisions(messages)
    except (KeyError, TypeError, ValueError):
        return None
    if (not isinstance(audit, dict) or audit.get('passed') is not True or audit.get('errors')
            or not isinstance(audit.get('audit'), dict) or audit['audit'].get('errors')
            or audit.get('requirementsId') != requirements_id
            or audit.get('libraryFingerprint') != library_fingerprint(equipment)
            or audit.get('historyFingerprint') != history_fingerprint
            or audit.get('resolvedDecisions', {}) != decisions):
        return None
    source = audit.get('submittedDraft')
    if (not isinstance(source, dict) or source.get('requirementsId') != requirements_id
            or not isinstance(source.get('workouts'), list) or not source['workouts']):
        return None
    return copy.deepcopy(source['workouts'])


def solve_repair_candidate(workouts, requirements, equipment, restriction_policy, *,
                           repair_contract, requirements_id, allow_educated_load_guesses,
                           training_history, messages, preserve_source_selection,
                           redistribution_constraints, balance=False,
                           validated_source_working_set_budget=None):
    from .joint_planning import solve_prescribed_week
    from .repair_contract import RepairContractError, carry_repair_contract, repair_contract_errors

    source_working_set_budget = None
    if validated_source_working_set_budget is not None:
        if _valid_repair_source_working_set_budget(validated_source_working_set_budget):
            source_working_set_budget = copy.deepcopy(validated_source_working_set_budget)
    else:
        source_working_set_budget = _repair_source_working_set_budget(
            workouts, requirements, equipment, restriction_policy,
            requirements_id=requirements_id,
            allow_educated_load_guesses=allow_educated_load_guesses,
            training_history=training_history, messages=messages,
            redistribution_constraints=redistribution_constraints)
    unresolved_explicit_cap = (
        _source_budget_claims_explicit_limit(validated_source_working_set_budget)
        if validated_source_working_set_budget is not None
        else _current_messages_have_unverified_explicit_budget(messages, requirements_id))
    if source_working_set_budget is None and unresolved_explicit_cap:
        return ({'feasible': False, 'status': 'unproven',
            'instruction': ('The repair was not solved because an explicit source-set cap could not be '
                'verified for the current requirements, library, history, and source artifact.'),
            'errors': [{'code': 'repair_source_budget_unverified', 'path': '/',
                'message': 'An explicit source working-set cap exists but its current authority could not be verified.'}]},
            copy.deepcopy(repair_contract), None, [])
    if source_working_set_budget is None:
        source_working_set_budget = copy.deepcopy(_UNBOUNDED_SOURCE_WORKING_SET_BUDGET)

    reviewed_source = current_reviewed_joint_source(None, requirements_id=requirements_id,
        equipment=equipment, messages=messages, training_history=training_history)
    reviewed_baseline_workouts = (copy.deepcopy(reviewed_source['submittedDraft']['workouts'])
        if reviewed_source else None)
    if (reviewed_baseline_workouts is None
            and 'preservation' in (requirements.get('objectiveOrder') or [])):
        reviewed_baseline_workouts = _current_audited_preservation_workouts(
            requirements_id, equipment, messages, training_history)
    joint = solve_prescribed_week(workouts, requirements, equipment, restriction_policy,
        allow_educated_load_guesses=allow_educated_load_guesses,
        training_history=training_history, messages=messages, balance=balance,
        preserve_source_selection=preserve_source_selection,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=source_working_set_budget,
        reviewed_baseline_workouts=reviewed_baseline_workouts)
    carried_contract = copy.deepcopy(repair_contract)
    carry_error = None
    contract_errors = []
    if joint.get('feasible') and carried_contract:
        try:
            carried_contract = carry_repair_contract(carried_contract, {}, {'workouts': workouts},
                {'workouts': joint['sessions']}, requirements_id=requirements_id)
        except RepairContractError as error:
            carry_error = error
        else:
            contract_errors = repair_contract_errors(carried_contract, {'workouts': joint['sessions']})
    return joint, carried_contract, carry_error, contract_errors


def current_reviewed_joint_source(source, *, requirements_id, equipment, messages, training_history):
    """Find a reviewed source under the current requirements, library and instruction authority."""
    from .planning_tools import library_fingerprint

    history_fingerprint = getattr(training_history, 'fingerprint', None)
    decisions = None
    try:
        from .planning_decisions import resolved_decisions
        decisions = resolved_decisions(messages)
    except (KeyError, TypeError, ValueError):
        return None

    def current_reviewed(value):
        if (not isinstance(value, dict) or value.get('passed') is not True
                or value.get('errors') or not isinstance(value.get('audit'), dict)
                or value['audit'].get('errors') or not isinstance(value.get('submittedDraft'), dict)
                or not isinstance(value['submittedDraft'].get('workouts'), list)
                or value.get('requirementsId') != requirements_id
                or value.get('libraryFingerprint') != library_fingerprint(equipment)
                or value.get('historyFingerprint') != history_fingerprint
                or value.get('resolvedDecisions', {}) != decisions):
            return False
        try:
            from .plan_review import require_current_review
            require_current_review(value, messages, equipment, training_history)
        except (KeyError, TypeError, ValueError):
            return False
        return True

    if current_reviewed(source):
        return source
    call_names = {call.get('id'): call.get('function', {}).get('name')
        for message in messages for call in message.get('tool_calls', [])}
    for message in reversed(messages):
        if (message.get('role') != 'tool'
                or call_names.get(message.get('tool_call_id')) != 'audit_workout_plan'):
            continue
        try:
            prior = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if current_reviewed(prior):
            return prior
    return None


def compare_reviewed_joint_candidate(source, candidate, *, requirements, requirements_id,
                                     equipment, messages, training_history,
                                     restriction_policy, source_working_set_budget, qualification=None,
                                     review_feedback_by_definition=None):
    """Compare a reviewed repair with its exact current reviewed source, if one exists."""
    authority = {'requirements_id': requirements_id, 'equipment': equipment,
        'messages': messages, 'training_history': training_history}
    source = current_reviewed_joint_source(source, **authority)
    if source is None:
        return None

    if current_reviewed_joint_source(candidate, **authority) is not candidate:
        return {
            'decision': 'incomparable', 'reason': 'candidate_not_currently_reviewed',
            'firstDifferingObjective': None, 'comparisons': [],
        }

    if source.get('submittedDraft') == candidate.get('submittedDraft'):
        return {
            'decision': 'retain_baseline', 'reason': 'same_reviewed_source_artifact',
            'firstDifferingObjective': None, 'comparisons': [],
        }

    if not isinstance(source.get('submittedDraft', {}).get('workouts'), list):
        return None

    from .allocation import _joint_candidate_comparison_context
    from .joint_planning import compare_audited_joint_candidates
    source_workouts = source['submittedDraft'].get('workouts')
    candidate_workouts = ((candidate.get('submittedDraft') or {}).get('workouts')
        if isinstance(candidate, dict) else None)
    context = _joint_candidate_comparison_context(
        source_workouts, candidate_workouts, requirements, equipment, messages,
        training_history, restriction_policy, source_working_set_budget,
        qualification=qualification,
        review_feedback_by_definition=review_feedback_by_definition)
    return compare_audited_joint_candidates(
        {'workouts': source_workouts, 'audit': source['audit'], 'searchStatus': 'reviewed_source'},
        {'workouts': candidate_workouts, 'audit': candidate['audit'], 'searchStatus': 'reviewed_candidate'},
        requirements=requirements, context=context or {})


def apply_repair_promotion_gate(result, comparison):
    """Require a human choice when a reviewed repair is worse or incomparable."""
    if (not isinstance(comparison, dict) or comparison.get('decision') == 'promote_candidate'
            or comparison.get('reason') == 'same_reviewed_source_artifact'):
        return result
    result = copy.deepcopy(result)
    result['jointCandidateComparison'] = copy.deepcopy(comparison)
    result['jointPromotionGate'] = copy.deepcopy(comparison)
    result['passed'] = False
    result['errors'] = [*(result.get('errors') or []), {
        'code': 'joint_candidate_not_proven_improvement',
        'message': 'The reviewed repair is not proven to improve the current reviewed source under the same approved comparison authority.',
        'owner': 'generator',
    }]
    result['instruction'] = ('The candidate passed its repair, audit, and semantic review, but the shared objective comparison '
        'did not prove it better than the current reviewed source. Keep both artifacts and their comparison; ask the user '
        'which one to use. Do not treat this candidate as the approved preview or export it.')
    result.pop('preview', None)
    result.pop('planIndex', None)
    return result
