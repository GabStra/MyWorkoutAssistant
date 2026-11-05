"""Bounded complete-artifact feedback after the fast selection/execution seed."""

import copy
import time


def _useful_unused_definitions(seed, sessions, baseline, requirements, equipment,
                               definitions, selected_ids, context, solve_arguments, deadline):
    """Bound admission by audited improvements under the approved comparison policy."""
    from jsonschema import ValidationError
    from . import joint_planning as joint
    from .cancellation import check_cancelled
    from .exercise_contracts import execution_semantics_problem
    from .planning_decisions import execution_decision_definitions
    from .programming_guidelines import approved_work_set_bounds
    from .training_history import apply_native_load_calibration_policy

    started = time.monotonic()
    # shortcut: reserve most remaining time for coupled search; expand exchanges only with measured payoff.
    exchange_deadline = started + min(10, max(0, deadline - started - 5) / 4)
    stats = {'evaluatedExchangeCount': 0, 'feasibleExchangeCount': 0,
        'beneficialExchangeCount': 0, 'evaluatedDefinitionIds': [],
        'scope': ('One-occurrence exchanges keep incumbent counts, grouping and placement; exact per-set '
            'prescriptions stay fixed. Native complete-week audit and the approved candidate comparator '
            'rank improvements. Exchanges requiring coordinated dose or grouping changes may be missed.')}
    messages = solve_arguments.get('messages') or []
    history = solve_arguments.get('training_history')
    validate_loads = None
    if history:
        validate_loads = (history.load_suitability_validator(messages, equipment)
            if hasattr(history, 'load_suitability_validator') else
            lambda plan: history.load_suitability_errors(plan, messages, equipment))
    execution_definitions = execution_decision_definitions(messages, equipment)
    definitions = {reference: execution_definitions.get(definition['id'], definition)
        for reference, definition in definitions.items()}
    recipes = list({joint._recipe_signature(block): block[0]
        for block in joint._blocks(sessions, standalone=True)
        if len(block) == 1 and definitions[block[0]['definition_id']]['id'] not in selected_ids}.values())
    unused_ids = {definitions[recipe['definition_id']]['id'] for recipe in recipes}
    best = []
    considered_ids, evaluated_ids = set(), set()
    exhausted = False
    for day_index, day in enumerate(seed['sessions']):
        for item_index, incumbent in enumerate(day['exercises']):
            for recipe in recipes:
                check_cancelled()
                if time.monotonic() >= exchange_deadline:
                    exhausted = True
                    break
                identifier = definitions[recipe['definition_id']]['id']
                considered_ids.add(identifier)
                count = incumbent['numWorkSets']
                bounds = approved_work_set_bounds(recipe, definitions[recipe['definition_id']], requirements)
                exact = recipe.get('targetSetPrescriptions')
                if (not bounds['minimum'] <= count <= bounds['maximum']
                        or exact and len(exact) != count
                        or execution_semantics_problem(recipe, definitions[recipe['definition_id']])):
                    continue
                replacement = copy.deepcopy(recipe)
                replacement.update(numWorkSets=count, allocationBounds=bounds,
                    superset=incumbent.get('superset'))
                if incumbent.get('superset') is not None:
                    for field in ('restAfterSupersetExerciseSeconds', 'restAfterExerciseSeconds'):
                        replacement[field] = incumbent[field]
                block = [replacement]
                if incumbent.get('superset') is not None:
                    block = [replacement if index == item_index else copy.deepcopy(item)
                        for index, item in enumerate(day['exercises'])
                        if item.get('superset') == incumbent['superset']]
                for variant in joint._rest_options(block, requirements, definitions, count):
                    check_cancelled()
                    if time.monotonic() >= exchange_deadline:
                        exhausted = True
                        break
                    workouts = copy.deepcopy(baseline['workouts'])
                    target = workouts[len(context['fixedWorkouts']) + day_index]['exercises']
                    positions = ([item_index] if incumbent.get('superset') is None else
                        [index for index, item in enumerate(day['exercises'])
                            if item.get('superset') == incumbent['superset']])
                    for position, item in zip(positions, variant):
                        target[position] = copy.deepcopy(item)
                    draft = {'requirementsId': 'refinement', 'name': 'Candidate exchange', 'workouts': workouts}
                    stats['evaluatedExchangeCount'] += 1
                    evaluated_ids.add(identifier)
                    try:
                        joint._DRAFT_VALIDATOR.validate(draft)
                        plan, audit = joint._audit_raw(draft, equipment, requirements,
                            solve_arguments.get('restriction_policy') or {},
                            solve_arguments.get('allow_educated_load_guesses', True),
                            execution_definitions=execution_definitions)
                        apply_native_load_calibration_policy(plan, messages, equipment,
                            getattr(history, 'fingerprint', None), allow_educated_load_guesses=
                            solve_arguments.get('allow_educated_load_guesses', True))
                        joint.audit_execution_rules(draft, requirements, audit, plan)
                        joint.audit_execution_details(draft, requirements, audit)
                        if validate_loads:
                            audit['errors'].extend(validate_loads(plan))
                    except (ValueError, ValidationError):
                        continue
                    candidate = {'workouts': workouts, 'audit': audit, 'searchStatus': 'exchange_witness'}
                    if joint._candidate_audit_errors(candidate, requirements, context):
                        continue
                    stats['feasibleExchangeCount'] += 1
                    comparison = joint.compare_audited_joint_candidates(baseline, candidate,
                        requirements=requirements, context=context)
                    if comparison['decision'] != 'promote_candidate':
                        continue
                    stats['beneficialExchangeCount'] += 1
                    existing = next((entry for entry in best if entry['id'] == identifier), None)
                    if existing and joint.compare_audited_joint_candidates(existing['candidate'], candidate,
                            requirements=requirements, context=context)['decision'] != 'promote_candidate':
                        continue
                    best = [entry for entry in best if entry['id'] != identifier]
                    position = next((index for index, entry in enumerate(best)
                        if joint.compare_audited_joint_candidates(entry['candidate'], candidate,
                            requirements=requirements, context=context)['decision'] == 'promote_candidate'), len(best))
                    best.insert(position, {'id': identifier, 'candidate': candidate,
                        'firstDifferingObjective': comparison['firstDifferingObjective']})
                    best = best[:2]
                if exhausted:
                    break
            if exhausted:
                break
        if exhausted:
            break
    stats.update(consideredDefinitionIds=sorted(considered_ids),
        evaluatedDefinitionIds=sorted(evaluated_ids), unexaminedDefinitionCount=len(unused_ids - considered_ids),
        uniqueRecipeCount=len(recipes), budgetExhausted=exhausted,
        elapsedSeconds=time.monotonic() - started,
        admittedWitnesses=[{'definitionId': entry['id'],
            'firstDifferingObjective': entry['firstDifferingObjective']} for entry in best],
        fallback='selected_definitions_only' if not best else None)
    return [entry['id'] for entry in best], stats


def refine_complete_candidate(seed, sessions, requirements, equipment, *, search_deadline,
                              context=None, **solve_arguments):
    """Try one coupled recipe neighborhood and retain the best natively audited week."""
    from . import joint_planning as joint
    from .allocation import _joint_candidate_comparison_context
    from .planning_decisions import confirmed_setup_access, execution_decision_definitions

    started = time.monotonic()
    evidence = {'status': 'not_attempted', 'attemptedCandidateCount': 0,
        'completedCandidateCount': 0, 'promotedCandidateCount': 0,
        'qualifiedMenuOccurrenceCount': sum(len(day['exercises']) for day in sessions),
        'qualifiedMenuDefinitionCount': len({item['definition_id']
            for day in sessions for item in day['exercises']}),
        'scope': ('One warm-started coupled search over selected definitions plus at most two unused '
            'qualified definitions with audited beneficial exchange witnesses under the approved objectives, '
            'including selection, placement, counts, grouping '
            'and execution. Original recipe occurrence indexes are retained. The bounded neighborhood '
            'and omitted alternatives do not establish a quality target or a global optimum.')}

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
    added_ids, exchange_evidence = _useful_unused_definitions(seed, sessions, baseline,
        comparison_requirements, equipment, definitions, selected_ids, context, solve_arguments, search_deadline)
    evidence['exchangeScreening'] = exchange_evidence
    eligible_ids = selected_ids | set(added_ids)
    evidence['neighborhood'] = {'selectedDefinitionIds': sorted(selected_ids),
        'addedDefinitionIds': added_ids, 'eligibleDefinitionCount': len(eligible_ids),
        'fullMenuDefinitionCount': len(full_ids), 'omittedDefinitionCount': len(full_ids - eligible_ids),
        'eligibleMenuOccurrenceCount': sum(definitions[item['definition_id']]['id'] in eligible_ids
            for day in sessions for item in day['exercises'])}
    if search_deadline - time.monotonic() < 5:
        return finish(seed, 'skipped_insufficient_remaining_budget')

    evidence['attemptedCandidateCount'] = 1
    candidate = joint._solve_prescribed_week(sessions, requirements, equipment,
        **solve_arguments, _prescription_seed=seed['sessions'], search_deadline=search_deadline,
        _eligible_definition_ids=eligible_ids)
    evidence['candidateSearchStatus'] = candidate.get('status')
    evidence['candidateModel'] = {key: candidate[key] for key in (
        'recipeCount', 'optionCount', 'physicalBlockCount', 'orderingConstraintCount') if key in candidate}
    evidence['solverDiagnostics'] = candidate.get('solverDiagnostics', [])
    evidence['searchBudget'] = candidate.get('searchBudget')
    if not candidate.get('feasible'):
        return finish(seed, 'retained_seed_after_incomplete_candidate')

    evidence['completedCandidateCount'] = 1
    comparison = joint.compare_audited_joint_candidates(baseline,
        {'workouts': fixed + candidate['sessions'], 'audit': candidate['audit'],
            'searchStatus': candidate.get('status')}, requirements=comparison_requirements, context=context)
    evidence['comparison'] = comparison
    if comparison['decision'] != 'promote_candidate':
        return finish(seed, 'retained_seed_after_audited_comparison')

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
    evidence['promotedCandidateCount'] = 1
    return finish(candidate, 'promoted_complete_candidate')
