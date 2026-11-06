"""Bounded complete-artifact feedback after the fast selection/execution seed."""

import copy
import time


def _candidate_neighborhoods(sessions, seed_sessions, definitions):
    """Group related dose variables for search, without claiming interchangeable stimulus."""
    selected_ids = {definitions[item['definition_id']]['id']
        for day in seed_sessions for item in day['exercises']}
    groups, repetitions = {}, {}
    for day in sessions:
        for item in day['exercises']:
            definition = definitions[item['definition_id']]
            identifier = definition['id']
            # Shared primary tags only bound computation; native qualification still owns eligibility.
            key = tuple(sorted(definition.get('muscleGroups') or ())) or (identifier,)
            groups.setdefault(key, set()).add(identifier)
    for day in seed_sessions:
        counts = {}
        for item in day['exercises']:
            definition = definitions[item['definition_id']]
            key = tuple(sorted(definition.get('muscleGroups') or ())) or (definition['id'],)
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            repetitions[key] = repetitions.get(key, 0) + max(0, count - 1)
    groups = [(key, ids - selected_ids) for key, ids in groups.items() if ids - selected_ids]
    # Try repeated work first; this schedules search and never overrides the approved comparison policy.
    groups.sort(key=lambda entry: (-repetitions.get(entry[0], 0), len(entry[1]), entry[0]))
    # shortcut: cross-group unused additions remain unsearched; widen when a controlled comparison demonstrates a missed gain.
    return [selected_ids | ids for _, ids in groups] or [selected_ids]


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
        'scope': ('Warm-started coupled searches over selected definitions and groups of unused menu '
            'definitions sharing primary muscle tags. No individually beneficial substitution is required; '
            'counts, placement, grouping and order may change together. Tags bound computation, not '
            'substitution or stimulus claims. Original occurrence indexes and the full qualification '
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
    neighborhoods = _candidate_neighborhoods(sessions, seed['sessions'], definitions)
    evidence['neighborhood'] = {'selectedDefinitionIds': sorted(selected_ids),
        'fullMenuDefinitionCount': len(full_ids), 'plannedCount': len(neighborhoods), 'attempts': []}
    best, candidate = baseline, None
    for eligible_ids in neighborhoods:
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
        proposal = joint._solve_prescribed_week(sessions, requirements, equipment,
            **solve_arguments, _prescription_seed=best['workouts'][len(fixed):], search_deadline=search_deadline,
            _eligible_definition_ids=eligible_ids)
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
    candidate.update(status='feasible', jointModelStatus='feasible', optimizationScope=evidence['scope'])
    for key in ('objectiveProgress', 'priorityExecution', 'exerciseDistribution',
            'demandDistribution', 'arrangementRefinement', 'priorityTradeoffs'):
        scope_proof(candidate.get(key))
    candidate['priorityExecution']['scope'] = evidence['scope']
    candidate['arrangementRefinement']['scope'] = evidence['scope']
    return finish(candidate, 'promoted_complete_candidate')
