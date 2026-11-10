"""Bounded complete-artifact feedback after the fast selection/execution seed."""

import copy
import time


def _candidate_neighborhoods(sessions, seed_sessions, definitions):
    """Reallocate selected work first, then admit the complete qualified menu."""
    selected_ids = {definitions[item['definition_id']]['id']
        for day in seed_sessions for item in day['exercises']}
    full_ids = {definitions[item['definition_id']]['id']
        for day in sessions for item in day['exercises']}
    return [selected_ids, full_ids] if selected_ids != full_ids else [selected_ids]


def _bounded_candidate(candidate, scope):
    def scope_proof(value):
        if isinstance(value, list):
            for item in value:
                scope_proof(item)
        elif isinstance(value, dict):
            for key in ('status', 'solverStatus', 'optimizationStatus', 'sumTieBreakStatus'):
                if value.get(key) in ('optimal', 'optimal_zero_lower_bound'):
                    value.update({key: 'feasible', 'neighborhoodOptimal': True})
            if value.get('provenOptimal'):
                value.update(provenOptimal=False, neighborhoodOptimal=True)
            if 'goal' in value or 'priority' in value:
                value['scope'] = 'bounded_complete_candidate_neighborhood'
            if 'individualOptimumClaimed' in value:
                value['individualOptimumClaimed'] = False
            for item in list(value.values()):
                scope_proof(item)

    candidate = copy.deepcopy(candidate)
    candidate.update(status='feasible', jointModelStatus='feasible', optimizationScope=scope)
    for key in ('objectiveProgress', 'priorityExecution', 'exerciseDistribution',
            'demandDistribution', 'arrangementRefinement', 'priorityTradeoffs'):
        scope_proof(candidate.get(key))
    candidate['priorityExecution']['scope'] = scope
    candidate['arrangementRefinement']['scope'] = scope
    return candidate


def refine_complete_candidate(seed, sessions, requirements, equipment, *, search_deadline,
                              context=None, **solve_arguments):
    """Compare coupled dose/grouping/order neighborhoods under one shared deadline."""
    from . import joint_planning as joint
    from .allocation import _joint_candidate_comparison_context
    from .planning_decisions import confirmed_setup_access, execution_decision_definitions

    started = time.monotonic()
    evidence = {'status': 'not_attempted', 'attemptedCandidateCount': 0,
        'completedCandidateCount': 0, 'promotedCandidateCount': 0,
        'qualifiedMenuOccurrenceCount': sum(len(day['exercises']) for day in sessions),
        'qualifiedMenuDefinitionCount': len({item['definition_id']
            for day in sessions for item in day['exercises']}),
        'scope': ('Warm-started coupled searches over selected definitions followed by the full qualified menu. '
            'Cross-muscle additions may participate together; no individually beneficial substitution is required. '
            'Counts, placement, grouping and order may change together. Original occurrence indexes and the full qualification '
            'context are retained. The bounded search does not establish a global optimum.')}

    def finish(best, status):
        return {**best, 'completeCandidateRefinement': {**evidence, 'status': status,
            'elapsedSeconds': time.monotonic() - started}}

    if not seed.get('feasible') or seed.get('audit', {}).get('errors'):
        return finish(seed, 'skipped_without_audited_feasible_seed')
    if solve_arguments.get('preserve_source_selection'):
        return finish(seed, 'skipped_preserved_source_selection')
    # shortcut: avoid constructing another coupled model below five seconds, revisit with measured preparation costs.
    if search_deadline - time.monotonic() < 5:
        return finish(seed, 'skipped_insufficient_remaining_budget')
    fixed = copy.deepcopy((solve_arguments.get('existing') or {}).get('workouts', []))
    if context is None:
        context = _joint_candidate_comparison_context(fixed + seed['sessions'], fixed + sessions,
            requirements, equipment, solve_arguments.get('messages') or [],
            solve_arguments.get('training_history'), solve_arguments.get('restriction_policy') or {},
            solve_arguments.get('source_working_set_budget'))
    if context is None:
        return finish(seed, 'skipped_missing_shared_qualification_context')
    messages = solve_arguments.get('messages') or []
    comparison_requirements = confirmed_setup_access(messages, equipment, requirements)['requirements']
    execution_definitions = execution_decision_definitions(messages, equipment)
    context = {**context, 'fixedWorkouts': fixed,
        'setupDefinitions': {reference: execution_definitions.get(definition['id'], definition)
            for reference, definition in (context.get('setupDefinitions') or {}).items()}}
    baseline = {'workouts': fixed + seed['sessions'], 'audit': seed['audit'],
        'searchStatus': seed.get('status')}
    if joint._candidate_audit_errors(baseline, comparison_requirements, context):
        return finish(seed, 'skipped_ineligible_seed_context')
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda definition: definition['id']))}
    definitions.update({definition['id']: definition for definition in definitions.values()})
    unsupported = {item['definition_id'] for day in [*sessions, *seed['sessions']]
        for item in day['exercises']} - definitions.keys()
    if unsupported:
        evidence['unsupportedDefinitionReferences'] = sorted(unsupported)
        return finish(seed, 'skipped_unsupported_recipe_reference')
    full_ids = {definitions[item['definition_id']]['id']
        for day in sessions for item in day['exercises']}
    selected_ids = {definitions[item['definition_id']]['id']
        for day in seed['sessions'] for item in day['exercises']}
    if solve_arguments.get('semantic_selection') is not None:
        # Membership may change only in a saved hypothetical artifact awaiting semantic selection.
        evidence['scope'] = ('One bounded omission-relaxed search within the selected qualified definitions. '
            'Required exercises and approved constraints remain binding. A changed menu awaits semantic selection.')
        evidence['attemptedCandidateCount'] = 1
        proposal = joint._solve_prescribed_week(sessions, requirements, equipment,
            **{**solve_arguments, 'semantic_selection': None},
            _prescription_seed=seed['sessions'], search_deadline=search_deadline,
            _eligible_definition_ids=selected_ids, _comparison_context=context)
        evidence['omissionSearchStatus'] = proposal.get('status')
        if not proposal.get('feasible') or proposal.get('audit', {}).get('errors'):
            return finish(seed, 'retained_semantic_menu_after_incomplete_omission_search')
        evidence['completedCandidateCount'] = 1
        alternative_ids = {definitions[item['definition_id']]['id']
            for day in proposal['sessions'] for item in day['exercises']}
        if not alternative_ids or not alternative_ids <= selected_ids:
            return finish(seed, 'retained_semantic_menu_without_omission_alternative')
        selection = {**copy.deepcopy(solve_arguments['semantic_selection']),
            'definitionIds': sorted(alternative_ids), 'fixedWorkouts': fixed}
        from .generation_audit import audit_semantic_selection
        audit_semantic_selection(proposal['audit'], {'workouts': fixed + proposal['sessions']},
            selection, equipment)
        finished = {'workouts': fixed + proposal['sessions'], 'audit': proposal['audit'],
            'searchStatus': proposal.get('status')}
        comparison = joint.compare_audited_joint_candidates(baseline, finished,
            requirements=comparison_requirements, context=context)
        evidence['comparison'] = comparison
        if alternative_ids == selected_ids:
            if comparison.get('decision') == 'promote_candidate':
                evidence['promotedCandidateCount'] = 1
                return finish(_bounded_candidate(proposal, evidence['scope']), 'promoted_complete_candidate')
            return finish(seed, 'retained_semantic_menu_after_audited_comparison')
        if comparison.get('candidateAuditErrors') or comparison.get('decision') not in (
                'promote_candidate', 'requires_programming_decision'):
            return finish(seed, 'retained_semantic_menu_after_omission_comparison')
        scope = 'Bounded omission-relaxed search within the selected qualified menu; semantic selection is pending.'
        proposal = _bounded_candidate(proposal, scope)
        # The omission-relaxed search cannot authorize membership or reusable exact-menu proofs.
        for key in ('problemFingerprint', 'objectiveInputFingerprint', 'semanticSelection'):
            proposal.pop(key, None)
        evidence['semanticMenuAlternative'] = {
            'sessions': proposal.pop('sessions'), 'audit': proposal.pop('audit'),
            'semanticSelection': selection, 'jointPlanning': proposal,
            'omittedDefinitionIds': sorted(selected_ids - alternative_ids)}
        return finish(seed, 'semantic_menu_alternative_requires_selection')
    neighborhoods = _candidate_neighborhoods(sessions, seed['sessions'], definitions)
    evidence['neighborhood'] = {'selectedDefinitionIds': sorted(selected_ids),
        'fullMenuDefinitionCount': len(full_ids), 'plannedCount': len(neighborhoods), 'attempts': []}
    best, candidate = baseline, None
    for index, eligible_ids in enumerate(neighborhoods):
        remaining = search_deadline - time.monotonic()
        if remaining < 5:
            break
        eligible_ids = eligible_ids | {definitions[item['definition_id']]['id']
            for day in best['workouts'][len(fixed):] for item in day['exercises']}
        attempt = {'addedDefinitionIds': sorted(eligible_ids - selected_ids),
            'eligibleDefinitionCount': len(eligible_ids),
            'omittedDefinitionCount': len(full_ids - eligible_ids)}
        evidence['neighborhood']['attempts'].append(attempt)
        evidence['attemptedCandidateCount'] += 1
        pending = len(neighborhoods) - index
        attempt_deadline = (search_deadline if pending == 1 else
            min(search_deadline, time.monotonic() + remaining / pending))
        proposal = joint._solve_prescribed_week(sessions, requirements, equipment,
            **solve_arguments, _prescription_seed=best['workouts'][len(fixed):], search_deadline=attempt_deadline,
            _eligible_definition_ids=eligible_ids, _comparison_context=context)
        attempt['searchStatus'] = proposal.get('status')
        attempt['model'] = {key: proposal[key] for key in (
            'recipeCount', 'optionCount', 'physicalBlockCount', 'orderingConstraintCount') if key in proposal}
        attempt['searchBudget'] = proposal.get('searchBudget')
        attempt['solverDiagnostics'] = proposal.get('solverDiagnostics', [])
        attempt['prescriptionWarmStart'] = proposal.get('prescriptionWarmStart')
        if not proposal.get('feasible'):
            continue
        evidence['completedCandidateCount'] += 1
        finished = {'workouts': fixed + proposal['sessions'], 'audit': proposal['audit'],
            'searchStatus': proposal.get('status')}
        comparison = joint.compare_audited_joint_candidates(best, finished,
            requirements=comparison_requirements, context=context)
        attempt['comparison'] = comparison
        if comparison['decision'] == 'promote_candidate':
            best, candidate = finished, proposal
            evidence['promotedCandidateCount'] += 1
    if candidate is None:
        status = ('retained_seed_after_audited_comparison' if evidence['completedCandidateCount']
            else 'retained_seed_after_incomplete_candidate')
        return finish(seed, status)
    evidence['comparison'] = joint.compare_audited_joint_candidates(baseline, best,
        requirements=comparison_requirements, context=context)
    evidence['candidateModel'] = {key: candidate[key] for key in (
        'recipeCount', 'optionCount', 'physicalBlockCount', 'orderingConstraintCount') if key in candidate}

    return finish(_bounded_candidate(candidate, evidence['scope']), 'promoted_complete_candidate')
