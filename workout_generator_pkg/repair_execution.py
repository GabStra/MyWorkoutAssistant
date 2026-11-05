"""Shared solver and acceptance boundary for coordinated candidates."""

import copy
import json
from pathlib import Path


_UNBOUNDED_SOURCE_WORKING_SET_BUDGET = {
    'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None,
}


def reviewed_incumbent_reference(messages_path, snapshot):
    """Pin an existing reviewed receipt, without copying its document into model context."""
    from .domain_ops import reviewable_workout_artifact
    from .planning_tools import _fingerprint

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('review'), dict):
        raise ValueError('The incumbent needs an independently reviewed snapshot.')
    review = snapshot['review']
    artifact = review.get('reviewedArtifact') or {}
    if (not isinstance(artifact, dict) or not isinstance(snapshot.get('audit'), dict)
            or not isinstance(snapshot.get('submittedDraft'), dict)):
        raise ValueError('The incumbent needs its exact draft, audit and reviewed artifact.')
    if (snapshot.get('passed') is not True or snapshot.get('errors')
            or snapshot.get('audit', {}).get('errors') or review.get('failure')
            or not isinstance(snapshot.get('planIndex'), dict)
            or not isinstance(snapshot.get('submittedDraft', {}).get('workouts'), list)
            or not isinstance(review.get('assessment'), dict)
            or any(group.get('disposition') in ('repair', 'unresolved_capability')
                   for group in review['assessment'].get('groups', []))
            or not snapshot.get('draftId')
            or reviewable_workout_artifact(snapshot['planIndex'], artifact.get('programGuidance', '')) != artifact):
        raise ValueError('The incumbent must be an exact passing audited and independently reviewed artifact.')
    return {'messagesPath': str(Path(messages_path).resolve()),
            'draftId': snapshot['draftId'], 'receiptHash': _fingerprint(snapshot)}


def select_incumbent_conversation(messages_path):
    from .planning_tools import _latest_result

    messages = json.loads(Path(messages_path).read_text(encoding='utf-8'))
    if not isinstance(messages, list):
        raise ValueError('The incumbent conversation must contain a message array.')
    _, snapshot = _latest_result(messages, 'audit_workout_plan')
    return reviewed_incumbent_reference(messages_path, snapshot)


def bind_incumbent_reference(messages, reference):
    if reference is not None:
        owner = next(message for message in messages if message.get('role') == 'system')
        owner['incumbentPlan'] = copy.deepcopy(reference)


def _incumbent_source(reference):
    from .planning_tools import _fingerprint, _latest_result

    messages = json.loads(Path(reference['messagesPath']).read_text(encoding='utf-8'))
    if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
        raise ValueError('The incumbent conversation must contain a message array.')
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool':
            continue
        try:
            snapshot = json.loads(message.get('content') or '')
        except (ValueError, TypeError):
            continue
        if (isinstance(snapshot, dict) and snapshot.get('draftId') == reference['draftId']
                and _fingerprint(snapshot) == reference['receiptHash']):
            reviewed_incumbent_reference(reference['messagesPath'], snapshot)
            _, requirements = _latest_result(messages[:index + 1], 'set_workout_requirements')
            if requirements.get('requirementsId') != snapshot.get('requirementsId'):
                break
            return messages[:index + 1], snapshot, requirements
    raise ValueError('The pinned incumbent receipt is missing or changed; select its reviewed conversation again.')


def _comparison_user_sources(record):
    sources = record.get('sourceMessages') or []
    if isinstance(sources, dict):
        sources = sources.values()
    return [{'content': source.get('content', ''),
             'images': [{key: image[key] for key in ('sha256', 'textOffset') if key in image}
                        for image in source.get('imageAttachments', source.get('images', []))]}
            for source in sources if source.get('role') == 'user']


def _incumbent_under_current_authority(messages, equipment, history_fingerprint):
    """Load a pinned source only while its approved authority still matches."""
    from .planning_decisions import resolved_decisions
    from .planning_tools import _latest_result, library_fingerprint
    from .requirement_accounting import comparison_requirements

    reference = next((message['incumbentPlan'] for message in messages
        if message.get('role') == 'system' and message.get('incumbentPlan')), None)
    if reference is None:
        return None
    source_messages, source, original = _incumbent_source(reference)
    _, current = _latest_result(messages, 'set_workout_requirements')
    if (comparison_requirements(original['requirements']) != comparison_requirements(current['requirements'])
            or not _comparison_user_sources(original)
            or _comparison_user_sources(original) != _comparison_user_sources(current)
            or original.get('restrictionPolicy') != current.get('restrictionPolicy')
            or source.get('resolvedDecisions', {}) != resolved_decisions(messages)
            or source.get('libraryFingerprint') != library_fingerprint(equipment)
            or source.get('historyFingerprint') != history_fingerprint):
        return None
    return source_messages, source


def incumbent_candidate_references(messages, equipment, history_fingerprint=None):
    """Offer incumbent definitions to normal preparation without borrowing loads or approval."""
    retained = _incumbent_under_current_authority(messages, equipment, history_fingerprint)
    if retained is None:
        return []
    _, source = retained
    return sorted({item['definition_id'] for day in source['submittedDraft']['workouts']
        for item in day['exercises']})


def incumbent_recipe_contracts(messages, equipment, history_fingerprint, input_hashes, roles,
                               definitions, review_feedback_by_definition):
    """Recover missing exact-context evidence agreeing with every pinned final occurrence."""
    from .recipe_contracts import _retained_contracts

    eligible_hashes = {ref: value for ref, value in input_hashes.items()
        if not (review_feedback_by_definition or {}).get(ref)}
    if not eligible_hashes:
        return {}, []
    retained = _incumbent_under_current_authority(messages, equipment, history_fingerprint)
    if retained is None:
        return {}, []
    source_messages, source = retained
    occurrence_roles = {}
    for day in source['submittedDraft']['workouts']:
        for item in day['exercises']:
            ref = item['definition_id']
            if ref not in eligible_hashes:
                continue
            assigned = item.get('satisfiesCoverage')
            if (not isinstance(assigned, list) or not all(isinstance(role, str) for role in assigned)
                    or len(assigned) != len(set(assigned)) or set(assigned) - roles):
                occurrence_roles[ref] = None
            elif ref not in occurrence_roles:
                occurrence_roles[ref] = set(assigned)
            elif occurrence_roles[ref] != set(assigned):
                occurrence_roles[ref] = None
    contracts, conflicts = _retained_contracts(
        source_messages, source.get('recipeQualification'), eligible_hashes, roles, definitions)
    conflicted = {item['definition_id'] for item in conflicts}
    return {ref: contract for ref, contract in contracts.items()
        if ref not in conflicted and occurrence_roles.get(ref) == set(contract['satisfiesCoverage'])}, conflicts


def compare_incumbent_candidate(candidate, messages, equipment, history=None):
    """Re-audit the pinned incumbent and compare exact plans under the same authority."""
    from .allocation import _joint_candidate_comparison_context
    from .joint_planning import compare_audited_joint_candidates, prescription_fingerprint
    from .planning_decisions import _active_reusable_decision_state, resolved_decisions
    from .planning_tools import _latest_result, audit_workout_plan, library_fingerprint
    from .programming_guidelines import canonical_execution_order_draft
    from .requirement_accounting import comparison_requirements

    reference = next((message['incumbentPlan'] for message in messages
        if message.get('role') == 'system' and message.get('incumbentPlan')), None)
    if reference is None:
        return None
    comparison = {'decision': 'incomparable', 'reason': None, 'comparisons': [],
                  'firstDifferingObjective': None, 'incumbent': copy.deepcopy(reference)}
    try:
        source_messages, source, original = _incumbent_source(reference)
        _, current = _latest_result(messages, 'set_workout_requirements')
        if candidate.get('resolvedDecisions', {}) != resolved_decisions(messages):
            return {**comparison, 'reason': 'candidate_decisions_not_current'}
        if source.get('resolvedDecisions', {}) != resolved_decisions(source_messages):
            return {**comparison, 'reason': 'incumbent_decisions_not_current'}
        if comparison_requirements(original['requirements']) != comparison_requirements(current['requirements']):
            return {**comparison, 'decision': 'inapplicable', 'reason': 'different_approved_requirements'}
        if (not _comparison_user_sources(original)
                or _comparison_user_sources(original) != _comparison_user_sources(current)
                or original.get('restrictionPolicy') != current.get('restrictionPolicy')
                or source.get('libraryFingerprint') != library_fingerprint(equipment)
                or source.get('libraryFingerprint') != candidate.get('libraryFingerprint')
                or source.get('historyFingerprint') != candidate.get('historyFingerprint')
                or source.get('allowEducatedLoadGuesses') != candidate.get('allowEducatedLoadGuesses')):
            return {**comparison, 'reason': 'incumbent_authority_differs'}
        if source.get('historyFingerprint') != getattr(history, 'fingerprint', None):
            return {**comparison, 'reason': 'current_history_required_for_incumbent_revalidation'}
        if (_active_reusable_decision_state(source.get('resolvedDecisions', {}))
                != _active_reusable_decision_state(candidate.get('resolvedDecisions', {}))):
            return {**comparison, 'decision': 'inapplicable', 'reason': 'different_approved_decisions'}
        draft = canonical_execution_order_draft(source['submittedDraft'], original['requirements'], equipment)
        baseline = audit_workout_plan(draft, equipment, source_messages,
            candidate['allowEducatedLoadGuesses'], history)
        if not baseline.get('passed'):
            return {**comparison, 'reason': 'incumbent_failed_current_native_audit',
                    'baselineAuditErrors': baseline.get('errors', [])}
        baseline_workouts = baseline['submittedDraft']['workouts']
        candidate_workouts = candidate['submittedDraft']['workouts']
        context = _joint_candidate_comparison_context(baseline_workouts, candidate_workouts,
            current['requirements'], equipment, messages, history, current.get('restrictionPolicy', {}),
            None, qualification=candidate.get('recipeQualification'))
        if context is None:
            return {**comparison, 'reason': 'missing_shared_comparison_context'}
        # A historical passing review remains role evidence, not current semantic approval.
        # Re-ordering its main work does not manufacture a fresh model judgment.
        roles = {}
        for snapshot in (source, candidate):
            for day in snapshot['submittedDraft']['workouts']:
                for item in day['exercises']:
                    ref, assigned = item['definition_id'], item['satisfiesCoverage']
                    if ref in roles and set(roles[ref]) != set(assigned):
                        return {**comparison, 'reason': 'reviewed_role_evidence_conflicts', 'definition_id': ref}
                    roles[ref] = assigned
        for ref, assigned in context['qualifiedRoleEvidence'].items():
            if ref in roles and set(roles[ref]) != set(assigned):
                return {**comparison, 'reason': 'current_role_evidence_conflicts', 'definition_id': ref}
        context['qualifiedRoleEvidence'].update(roles)
        result = compare_audited_joint_candidates(
            {'workouts': baseline_workouts, 'audit': baseline['audit'], 'searchStatus': 'revalidated_incumbent'},
            {'workouts': candidate_workouts, 'audit': candidate['audit'], 'searchStatus': 'reviewed_candidate'},
            requirements=current['requirements'], context=context)
        from .planning_decisions import candidate_acceptance_scope
        result['baselineAcceptanceScope'] = candidate_acceptance_scope(baseline)
        result['incumbent'] = copy.deepcopy(reference)
        result['incumbentNeedsCurrentSemanticReview'] = True
        if (not result.get('baselineAuditErrors') and not result.get('candidateAuditErrors')
                and prescription_fingerprint(baseline_workouts) == prescription_fingerprint(candidate_workouts)):
            result.update(reason='same_reviewed_source_artifact', decision='retain_baseline')
        return result
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {**comparison, 'reason': 'incumbent_revalidation_failed', 'detail': str(error)}


def apply_incumbent_promotion_gate(result, messages, equipment, history=None):
    if not result.get('passed'):
        return result
    comparison = compare_incumbent_candidate(result, messages, equipment, history)
    if comparison is None:
        return result
    result = copy.deepcopy(result)
    result['incumbentComparison'] = comparison
    if comparison.get('decision') == 'inapplicable':
        return result
    result = apply_repair_promotion_gate(result, comparison, messages=messages)
    if (not result.get('passed') and not result.get('programmingDecision')
            and not result.get('programmingDecisionChoices')):
        objective = comparison.get('firstDifferingObjective')
        label = 'movement balance' if objective == 'source_balance' else (objective or '').replace('_', ' ')
        explanation = (f'The incumbent wins at the first differing approved priority: {label}. '
                       if objective else 'An improvement could not be verified from the available evidence. ')
        result['userQuestion'] = {
            'question': ('This candidate passed audit and review. An improvement over the saved incumbent is not established. '
                         + explanation +
                         'Both artifacts are retained; no requirement was changed.'),
            'options': ['Keep the incumbent; stop this replacement.',
                        'Investigate a controlled alternative under the same requirements.'],
            'recommendation': {'option': 1, 'reason': 'A passing review alone does not establish an improvement.'},
        }
    return result


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
    comparison = compare_audited_joint_candidates(
        {'workouts': source_workouts, 'audit': source['audit'], 'searchStatus': 'reviewed_source'},
        {'workouts': candidate_workouts, 'audit': candidate['audit'], 'searchStatus': 'reviewed_candidate'},
        requirements=requirements, context=context or {})
    from .planning_decisions import candidate_acceptance_scope
    comparison['baselineAcceptanceScope'] = candidate_acceptance_scope(source)
    return comparison


def programming_decision_choices(result, comparison=None):
    """Offer artifact choices only for a code-proven, natively feasible preference conflict."""
    from .planning_decisions import candidate_acceptance_scope
    comparison = comparison or result.get('jointPromotionGate') or result.get('jointCandidateComparison')
    if not isinstance(comparison, dict):
        return {}
    tradeoff = comparison.get('programmingTradeoff')
    if (not isinstance(tradeoff, dict) or tradeoff.get('status') not in ('requires_programming_decision', 'unknown')
            or comparison.get('baselineAuditErrors') != [] or comparison.get('candidateAuditErrors') != []
            or tradeoff.get('hardErrors', {}).get('baseline') != []
            or tradeoff.get('hardErrors', {}).get('candidate') != []
            or not isinstance(comparison.get('baselineAcceptanceScope'), dict)
            or any(error.get('code') != 'joint_candidate_not_proven_improvement'
                   for error in result.get('errors', []))):
        return {}
    scope = candidate_acceptance_scope(result)
    if scope is None:
        return {}
    baseline_scope = comparison['baselineAcceptanceScope']
    if (not isinstance(baseline_scope.get('requirementsId'), str)
            or baseline_scope['requirementsId'] != scope['requirementsId']
            or not isinstance(baseline_scope.get('workoutsFingerprint'), str)
            or baseline_scope.get('libraryFingerprint') != scope['libraryFingerprint']
            or baseline_scope.get('historyFingerprint') != scope['historyFingerprint']):
        return {}
    scope = {**scope, 'baselineAcceptanceScope': copy.deepcopy(comparison['baselineAcceptanceScope']),
        'programmingTradeoff': copy.deepcopy(tradeoff)}
    return {
        'CONCERN_programming_retain_baseline': {'label': 'Retain the baseline and its displayed preference tradeoffs.',
            'selection': 'baseline', 'acceptedCandidateScope': copy.deepcopy(scope)},
        'CONCERN_programming_use_candidate': {'label': 'Use the candidate and accept its displayed preference tradeoffs and evidence limits.',
            'selection': 'candidate', 'acceptedCandidateScope': copy.deepcopy(scope)},
    }


def resolved_programming_selection(messages, result, comparison=None):
    """Resolve an authorized artifact choice without changing its review or evidence."""
    from .planning_tools import latest_requirement_candidate
    from .planning_decisions import resolved_decisions
    _, requirements = latest_requirement_candidate(messages)
    if (requirements.get('requirementsId') != result.get('requirementsId')
            or requirements.get('requirements', {}).get('preferenceResolution') != 'explicit_tradeoffs'):
        return None
    choices = programming_decision_choices(result, comparison)
    for identifier, decision in resolved_decisions(messages).items():
        choice = choices.get(decision.get('acceptedConcernGroupId'))
        if choice and decision.get('acceptedCandidateScope') == choice['acceptedCandidateScope']:
            return {'decisionId': identifier, 'selection': choice['selection']}
    return None


def apply_repair_promotion_gate(result, comparison, *, messages=None):
    """Require a human choice when a reviewed repair is worse or incomparable."""
    if (not isinstance(comparison, dict) or comparison.get('decision') == 'promote_candidate'
            or comparison.get('reason') == 'same_reviewed_source_artifact'):
        return result
    result = copy.deepcopy(result)
    result.pop('programmingDecisionChoices', None)
    result.pop('programmingDecision', None)
    result['jointCandidateComparison'] = copy.deepcopy(comparison)
    result['jointPromotionGate'] = copy.deepcopy(comparison)
    choices = programming_decision_choices(result, comparison)
    from .planning_tools import latest_requirement_candidate
    _, requirements = latest_requirement_candidate(messages or [])
    current_policy = (requirements.get('requirementsId') == result.get('requirementsId')
        and requirements.get('requirements', {}).get('preferenceResolution') == 'explicit_tradeoffs')
    if messages is not None and not current_policy:
        choices = {}
    if choices:
        result['programmingDecisionChoices'] = copy.deepcopy(choices)
        selected = resolved_programming_selection(messages or [], result, comparison)
        if selected:
            result['programmingDecision'] = selected
            if selected['selection'] == 'candidate':
                # Acceptance selects an artifact; it does not manufacture semantic review or confirmation.
                return result
            result['passed'] = False
            result['instruction'] = 'The source-backed programming decision retains the baseline. Stop this replacement; do not repair or export the candidate.'
            result.pop('preview', None)
            result.pop('planIndex', None)
            result.pop('userQuestion', None)
            return result
    result['passed'] = False
    result['errors'] = [*[error for error in result.get('errors', [])
        if error.get('code') != 'joint_candidate_not_proven_improvement'], {
        'code': 'joint_candidate_not_proven_improvement',
        'message': 'The reviewed repair is not proven to improve the current reviewed source under the same approved comparison authority.',
        'owner': 'generator',
    }]
    result['instruction'] = ('The shared objective comparison '
        'did not prove it better than the current reviewed source. Keep both artifacts and their comparison; ask the user '
        'which one to use. Do not treat this candidate as the approved preview or export it.')
    if choices:
        result['instruction'] = ('Both alternatives pass native validation. Keep their displayed preference comparison and evidence limits; '
            'record the user choice before continuing normal final review. This choice does not authorize export.')
        tradeoff = comparison['programmingTradeoff']
        lines = ['Both artifacts pass native validation. Baseline -> candidate:']
        lines.extend(f"Weekly {row['muscle']}: {row['baselineEffectiveSets']} -> {row['candidateEffectiveSets']} effective sets; preferred {row['preferredMinimum']} to {row['preferredMaximum']}"
            for row in tradeoff.get('volumeChanges', []))
        for category in ('improved', 'worsened'):
            lines.extend(f"{category.title()}: {row['objective']}: {row['baseline']} -> {row['candidate']}"
                for row in tradeoff.get(category, []))
        lines.extend(f"Development exposure ({row['role']}): {row['baselineWorkingSets']} -> {row['candidateWorkingSets']} working sets/week"
            for row in tradeoff.get('developmentChanges', []))
        if tradeoff.get('unknownObjectives'):
            lines.append('Unverified: ' + ', '.join(tradeoff['unknownObjectives']))
        question = lines[0]
        for line in lines[1:]:
            if len(question) + len(line) > 1750:
                question += '\nFurther comparison facts are retained in the programming comparison.'
                break
            question += '\n' + line
        result['userQuestion'] = {'question': question + '\nChoose the artifact to retain. Requirements and evidence remain unchanged; review and export confirmation still follow.',
            'options': [choice['label'] for choice in choices.values()]}
    result.pop('preview', None)
    result.pop('planIndex', None)
    return result
