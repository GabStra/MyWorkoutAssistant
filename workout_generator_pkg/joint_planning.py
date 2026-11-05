"""Choose an executable week from finite, validated prescription recipes."""

import copy
import hashlib
import itertools
import json
import math
import time
from collections import Counter
from fractions import Fraction

from jsonschema import Draft7Validator, ValidationError

from .allocation import _audit_raw, _MILP_SOLUTION_TOLERANCE
from .cp_solver import solve as _cp_solve, SolverSession, _rational
from .generation_audit import (ASSUMPTIONS, MUSCLES, effective_concentration_status,
                               setup_resource_profile, executable_setup_evidence,
                               validate_family_set_bounds, weekly_family_set_counts,
                               volume_target_bounds, preferred_volume_target_bounds,
                               volume_preference_deviation, _setup_evidence_for_blocks,
                               _setup_resource_transition, _setup_profile_at_set)
from .planning_tools import _DRAFT_SCHEMA
from .programming_policy import (source_balance_dose_components, selection_precedes_execution,
    goal_tier_names, goal_programming_costs, goal_total_weights)
from .programming_guidelines import (
    approved_work_set_bounds, session_work_set_caps, audit_execution_details, audit_execution_rules,
    audit_training_schedule, complete_training_schedule,
    session_structure_limits,
    EXECUTION_ORDER_POLICY, execution_block_priority, execution_member_order,
    execution_block_order_key, execution_order_indices, execution_order_predecessors, equipment_setup_resources,
    movement_overlap_roles, execution_interference_profile, superset_lower_body_pair_sets,
    superset_resource_relation, superset_setup_compatibility,
)
from .programming_demands import (
    demand_distribution_inputs, demand_union_exposure_input, definition_demand_facts,
)
from .recipe_contracts import (
    progression_capability, progression_margin, recorded_evidence, reviewed_exercise_family_evidence,
    reviewed_execution_properties, CODE_OWNED_DIRECT_COVERAGE_ROLES,
)

SELECTION_POLICY_VERSION = 11
RECORDED_EVIDENCE_POLICY_VERSION = 1
_SOLVER_STAGE_SECONDS = 60
_SOLVER_SEARCH_SECONDS = 120
_SOLVER_REFINEMENT_SECONDS = 10
JOINT_POLICY_DESCRIPTOR = {
    'candidateOrdering': 'approved_explicit_policy_cp_sat_joint_optional_block_circuit; sequence_scores_compare_same_selected_session_work_only',
    'developmentEmphasis': 'explicit_approved_order_only_with_binding_coverage_floors',
    'sourceBalance': 'preserve_connected_approved_role_totals_after_prior_volume_or_workload_selection; individual_roles_remain_selectable',
    'workloadEconomy': 'physical_weekly_sets_before_dose_preserving_distribution',
    'structuralConcentration': 'worst_then_sum_targeted_primary_muscle_and_development_role_peaks; selection_before_sequence_preserves_physical_workload_and_prior_objective_faces; other_policies_preserve_training_doses',
    'muscleDistribution': 'selection_before_sequence_allows_within_preference_muscle_and_role_dose_changes_at_fixed_physical_workload; other_policies_preserve_training_doses',
    'exerciseDistribution': 'reviewed_family_peaks_development_before_inclusion_with_fixed_weekly_development_role_doses_when_workload_precedes_diversity',
    'supersetSelection': 'specific_role_or_reviewed_family_overlap_shared_by_selection_and_comparison; enumerate_audited_compatible_pairs_including_reviewed_weekly_dose_references; prefer_fewer_repeated_major_lower_body_pair_sets_after_movement_overlap_before_duration; no_fatigue_prediction',
    'groupArrangement': 'compare_per_session_keep_split_variants_as_complete_weeks_then_native_audit_the_selected_week; preserve_dose_and_occurrence_lineage',
}
JOINT_REPAIRABLE_AUDIT_ERRORS = frozenset({
    'volume_below_target', 'volume_above_target', 'duration_exceeded',
    'superset_set_count_mismatch', 'execution_sessionStructure', 'execution_order',
    'execution_supersetNoReconfiguration',
    'required_coverage_weekly_sets_below_minimum',
    'required_coverage_sessions_below_minimum',
})
_CODE_PREPARATION_BUDGET_SEEDS = frozenset({
    'code_preparation_volume_only_seed',
    'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
    'submitted_candidate_session_counts',
    'solver_derived_hard_feasible_baseline',
})


def prescription_fingerprint(sessions):
    return hashlib.sha256(json.dumps([{key: value for key, value in day.items() if key not in ('name', 'description')}
        | {'exercises': [{key: value for key, value in item.items() if key not in ('placementNotes', 'satisfiesCoverage')} for item in day['exercises']]}
        for day in sessions], sort_keys=True).encode()).hexdigest()


def _source_working_set_budget_identity(sessions, source_working_set_budget):
    if source_working_set_budget is None:
        return {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    if source_working_set_budget == {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}:
        return {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    if (not isinstance(source_working_set_budget, dict)
            or type(source_working_set_budget.get('variableWeeklyWorkingSets')) is not int
            or source_working_set_budget['variableWeeklyWorkingSets'] < 0
            or not isinstance(source_working_set_budget.get('source'), str)
            or not source_working_set_budget['source']
            or ('preparationId' in source_working_set_budget
                and not isinstance(source_working_set_budget['preparationId'], str))):
        raise ValueError('Malformed code-owned source working-set budget provenance.')
    if source_working_set_budget['source'] in _CODE_PREPARATION_BUDGET_SEEDS:
        # A generated allocation is a search seed, not an approved workload limit.
        return {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    result = {'source': source_working_set_budget['source'],
        'variableWeeklyWorkingSets': source_working_set_budget['variableWeeklyWorkingSets']}
    if source_working_set_budget.get('preparationId'):
        result['preparationId'] = source_working_set_budget['preparationId']
    return result


def _reviewed_dose_reference_identity(workouts):
    """Canonicalize the reviewed weekly dose used only as a final tie-break."""
    if workouts is None:
        return None
    if isinstance(workouts, dict):
        frequency = workouts.get('frequency')
        weekly_sets = workouts.get('weeklySetsByDefinition')
        if (set(workouts) != {'frequency', 'weeklySetsByDefinition'}
                or type(frequency) is not int or frequency < 1
                or not isinstance(weekly_sets, dict)
                or any(not isinstance(reference, str) or not reference
                    or type(count) is not int or count < 0
                    for reference, count in weekly_sets.items())):
            raise ValueError('Malformed canonical reviewed workout-dose reference.')
        return {'frequency': frequency,
            'weeklySetsByDefinition': dict(sorted(weekly_sets.items()))}
    if not isinstance(workouts, list):
        raise ValueError('Malformed reviewed workout-dose reference.')
    weekly_sets = Counter()
    frequency_total = 0
    for workout in workouts:
        frequency = workout.get('timesCompletedInAWeek') if isinstance(workout, dict) else None
        exercises = workout.get('exercises') if isinstance(workout, dict) else None
        if type(frequency) is not int or frequency < 1 or not isinstance(exercises, list):
            raise ValueError('Malformed reviewed workout-dose reference.')
        frequency_total += frequency
        for item in exercises:
            if (not isinstance(item, dict) or not isinstance(item.get('definition_id'), str)
                    or type(item.get('numWorkSets')) is not int or item['numWorkSets'] < 0):
                raise ValueError('Malformed reviewed workout-dose reference.')
            weekly_sets[item['definition_id']] += item['numWorkSets'] * frequency
    return {'frequency': frequency_total,
        'weeklySetsByDefinition': dict(sorted(weekly_sets.items()))}


def _ordered_joint_objective_names(requirements, available):
    """Return the same shared lexicographic goal order used by the joint solver."""
    approved_order = requirements.get('objectiveOrder')
    objective_order = list(approved_order) if approved_order is not None else ['preservation']
    ordered = [name for name in objective_order if available.get(name, False)]
    if 'execution_order' in ordered:
        from .programming_policy import execution_interference_metric_names
        index = ordered.index('execution_order')
        ordered[index:index + 1] = ['ordering_' + name
            for name in execution_interference_metric_names(requirements)]
    if 'demand_distribution' in objective_order and available.get('demand_colocation', False):
        demand_index = next((index for index, name in enumerate(ordered)
            if name == 'demand_distribution'), None)
        if demand_index is not None:
            ordered.insert(demand_index + 1, 'demand_colocation')
    if 'movement_overlap' in ordered and available.get('superset_lower_body_overlap', False):
        ordered.insert(ordered.index('movement_overlap') + 1, 'superset_lower_body_overlap')
    if 'distribution' in ordered and available.get('distribution_worst', False):
        ordered.insert(ordered.index('distribution'), 'distribution_worst')
    if 'role_concentration' in ordered and available.get('role_concentration_tiebreak', False):
        role_index = ordered.index('role_concentration')
        ordered.insert(role_index + 1, 'role_concentration_tiebreak')
    if ('duration_economy' in ordered and 'setup_economy' in (approved_order or [])
            and available.get('setup_economy_transitions', False)):
        ordered.insert(ordered.index('duration_economy') + 1, 'setup_economy_transitions')
    if 'setup_economy' in ordered and available.get('setup_economy_resource_switches', False):
        # Moving between ready resources is a tie-break after audited duration and known changes.
        after = max(ordered.index(name) for name in (
            'setup_economy', 'duration_economy', 'setup_economy_transitions') if name in ordered)
        ordered.insert(after + 1, 'setup_economy_resource_switches')
    if selection_precedes_execution(requirements):
        sequence_tiebreaks = [name for name in ('setup_economy_transitions', 'setup_economy_resource_switches')
            if name in ordered]
        ordering = [name for name in ordered if name.startswith('ordering_')]
        if ordering:
            ordered = [name for name in ordered if name not in sequence_tiebreaks]
            after = ordered.index(ordering[-1]) + 1
            ordered[after:after] = sequence_tiebreaks
    grouped = {goal['metric'] for tier in requirements.get('objectiveTiers', []) for goal in tier}
    return [name for name in goal_tier_names(requirements) if available.get(name)] + [
        name for name in ordered if name not in grouped]


def _goal_programming_objectives(variable, constraint, variables, requirements, objective_costs, offsets):
    """Compile the same target misses used by native candidate comparison."""
    goals = []
    for tier_index, tier in enumerate(requirements.get('objectiveTiers', [])):
        misses, bounds = {}, []
        for goal_index, (goal, weight) in enumerate(zip(tier, goal_total_weights(tier))):
            metric = goal['metric']
            if metric not in objective_costs:
                raise ValueError(f'Goal metric has no executable evidence: {metric}.')
            scale = _rational(goal['scale'])
            coefficients = {index: float(_rational(value) / scale)
                for index, value in objective_costs[metric].items()}
            offset = float((_rational(offsets.get(metric, 0)) - _rational(goal['target'])) / scale)
            upper = max(0, math.ceil(_rational(offset) + sum(_rational(value) * _rational(variables[index][
                'upper' if value >= 0 else 'lower']) for index, value in coefficients.items())))
            miss = variable(upper=upper, integer=False, domain_identity={
                'kind': 'goal_target_miss', 'tier': tier_index, 'metric': metric})
            constraint(('goal_target_miss', tier_index, goal_index), -math.inf, 0,
                {**coefficients, miss: -1}, offset)
            misses[miss] = float(weight)
            bounds.append(upper)
        peak = variable(upper=max(bounds), integer=False,
            domain_identity={'kind': 'goal_tier_peak', 'tier': tier_index})
        for miss in misses:
            constraint(('goal_tier_peak', tier_index, miss), -math.inf, 0, {miss: 1, peak: -1})
        goals.extend([(f'goal_tier_{tier_index}_worst', {peak: 1}),
            (f'goal_tier_{tier_index}_total', misses)])
    return goals


def _candidate_setup_transition_evidence(workout, definitions, requirements=None):
    """Use the same executed transition evidence as the final artifact audit."""
    groups = [group for rule in (requirements or {}).get('executionRules', [])
        if rule.get('kind') == 'supersetNoReconfiguration' for group in rule.get('sharedResourceGroups', [])]
    evidence = executable_setup_evidence(workout, definitions, groups)
    return {key: evidence[key] for key in ('preparationTaskCount',
        'resourceReferenceReturnCount', 'scheduledTransitionOccurrenceCount',
        'knownDeclaredChanges', 'unknownTransitions', 'unknownConfigurationTransitions',
        'declaredResourceSwitches', 'resourceIdentityComplete',
        'physicalConfigurationTransitions', 'knownPhysicalConfigurationChanges',
        'sameDeclaredPhysicalConfigurationStates', 'unknownPhysicalConfigurationTransitions',
        'physicalConfigurationEvidencePartial', 'physicalResourceIndependenceVerified',
        'physicalConfigurationInterpretation')}


def evaluate_audited_execution(candidate, definitions, requirements):
    """Describe the audited execution, independently of objective order or search claims."""
    workouts, audit = candidate['workouts'], candidate['audit']
    sessions = []
    for index, (workout, day) in enumerate(zip(workouts, audit['workouts'], strict=True)):
        exercises = workout.get('exercises', [])
        missing = sorted({item['definition_id'] for item in exercises} - set(definitions))
        if missing:
            setup = {'status': 'unavailable_definition_evidence', 'missingDefinitionReferences': missing}
        else:
            setup = _candidate_setup_transition_evidence(workout, definitions, requirements)
        groups = [list(members) for _, members in itertools.groupby(enumerate(exercises),
            lambda entry: ('group', entry[1]['superset']) if entry[1].get('superset') is not None
                else ('single', entry[0]))]
        sessions.append({'workoutIndex': index, 'name': workout.get('name'),
            'timesCompletedInAWeek': workout.get('timesCompletedInAWeek', 1),
            'exerciseCount': len(exercises),
            'uniqueDefinitionCount': len({item['definition_id'] for item in exercises}),
            'workingSets': sum(item['numWorkSets'] for item in exercises),
            'supersetCount': sum(len(group) > 1 for group in groups),
            'estimatedSeconds': day['estimatedSeconds'],
            'coverageSets': copy.deepcopy(day.get('coverageSets', {})),
            'effectiveMuscleSets': {muscle: value['effective']
                for muscle, value in day.get('volume', {}).items()},
            'setup': setup})
    durations = [day['estimatedSeconds'] for day in sessions]
    complete_setup = all('knownDeclaredChanges' in day['setup'] for day in sessions)
    return {'sessions': sessions,
        'weeklyWorkingSets': sum(day['workingSets'] * day['timesCompletedInAWeek'] for day in sessions),
        'weeklyEstimatedSeconds': sum(day['estimatedSeconds'] * day['timesCompletedInAWeek'] for day in sessions),
        'durationSpreadSeconds': max(durations, default=0) - min(durations, default=0),
        'durationBalanceToleranceSeconds': requirements.get('durationBalanceToleranceSeconds', 0),
        'weeklyKnownSetupChanges': (sum(day['setup']['knownDeclaredChanges'] * day['timesCompletedInAWeek']
            for day in sessions) if complete_setup else None),
        'weeklyUnknownSetupTransitions': (sum(day['setup']['unknownTransitions'] * day['timesCompletedInAWeek']
            for day in sessions) if complete_setup else None),
        'weeklyDeclaredResourceSwitches': (sum(day['setup']['declaredResourceSwitches']
            * day['timesCompletedInAWeek'] for day in sessions)
            if all(day['setup'].get('resourceIdentityComplete') for day in sessions) else None),
        'weeklyKnownPhysicalConfigurationChanges': (sum(day['setup']['knownPhysicalConfigurationChanges']
            * day['timesCompletedInAWeek'] for day in sessions) if complete_setup else None),
        'weeklySameDeclaredPhysicalConfigurationStates': (sum(day['setup']['sameDeclaredPhysicalConfigurationStates']
            * day['timesCompletedInAWeek'] for day in sessions) if complete_setup else None),
        'weeklyUnknownPhysicalConfigurationTransitions': (sum(day['setup']['unknownPhysicalConfigurationTransitions']
            * day['timesCompletedInAWeek'] for day in sessions) if complete_setup else None),
        'scope': 'Exact audited execution; times are estimates, overlap is accounting, and neither establishes personal '
            'fatigue or suitability. Physical configuration facts compare sourced partial requirements, not actual '
            'retained equipment state, independent inventory, measured setup time or proof of no physical setup action.'}


def _attempted_objective_order(approved_order, stages, fallback_order=None):
    """List approved objectives whose solver stages were actually attempted."""
    objective_order = approved_order if approved_order is not None else (fallback_order or [])
    attempted = {stage.get('goal') for stage in stages if isinstance(stage, dict)}
    if 'distribution_worst' in attempted:
        attempted.add('distribution')
    return [name for name in objective_order if name in attempted
        or name == 'execution_order' and any(goal.startswith('ordering_') for goal in attempted)]


def _candidate_audit_errors(candidate, requirements, context):
    workouts = candidate.get('workouts')
    audit = candidate.get('audit')
    if not isinstance(workouts, list) or not workouts or not isinstance(audit, dict):
        return ['missing_native_workouts_or_audit']
    native_errors = audit.get('errors') or []
    native_error_codes = [error.get('code') if isinstance(error, dict) else error
        for error in native_errors]
    native_errors_are_repairable = bool(native_error_codes) and all(
        code in JOINT_REPAIRABLE_AUDIT_ERRORS for code in native_error_codes)
    native_audit_has_errors = bool(native_error_codes)
    audit_workouts = audit.get('workouts')
    weekly_coverage = audit.get('weeklyCoverageSets')
    if (not isinstance(audit_workouts, list) or len(audit_workouts) != len(workouts)
            or not isinstance(weekly_coverage, dict)):
        return ['native_audit_shape_mismatch']
    role_evidence = context.get('qualifiedRoleEvidence')
    if not isinstance(role_evidence, dict):
        return ['missing_shared_qualified_role_evidence']
    budget = context.get('sourceWorkingSetBudget')
    try:
        budget = _source_working_set_budget_identity([], budget)
    except ValueError:
        return ['malformed_shared_source_budget']
    weekly_sets = 0
    fixed_workouts = context.get('fixedWorkouts', [])
    if (not isinstance(fixed_workouts, list)
            or workouts[:len(fixed_workouts)] != fixed_workouts):
        return ['fixed_workout_prefix_mismatch']
    for workout in workouts[len(fixed_workouts):]:
        if not isinstance(workout, dict) or not isinstance(workout.get('exercises'), list):
            return ['malformed_workout']
        frequency = workout.get('timesCompletedInAWeek', 1)
        if type(frequency) is not int or frequency < 1:
            return ['malformed_workout_frequency']
        for item in workout['exercises']:
            if not isinstance(item, dict):
                return ['malformed_exercise']
            definition_id = item.get('definition_id')
            qualified_roles = role_evidence.get(definition_id)
            if not isinstance(definition_id, str) or qualified_roles is None:
                return ['exercise_outside_shared_qualification_union']
            if isinstance(qualified_roles, dict):
                qualified_roles = qualified_roles.get('roles')
            if not isinstance(qualified_roles, (list, tuple, set)):
                return ['malformed_shared_qualification_evidence']
            claimed_roles = item.get('satisfiesCoverage', [])
            if (not isinstance(claimed_roles, list)
                    or set(claimed_roles) != set(qualified_roles)):
                return ['candidate_role_claim_exceeds_qualified_evidence']
            instance_id = item.get('id')
            audit_role_map = audit.get('coverageByExercise')
            if instance_id and isinstance(audit_role_map, dict):
                audited_roles = audit_role_map.get(instance_id)
                if (not isinstance(audited_roles, list)
                        or set(audited_roles) != set(claimed_roles)):
                    return ['native_audit_role_map_mismatch']
            sets = item.get('numWorkSets')
            if type(sets) is not int or sets < 0:
                return ['malformed_working_set_count']
            weekly_sets += sets * frequency
    if (budget['variableWeeklyWorkingSets'] is not None
            and weekly_sets > budget['variableWeeklyWorkingSets']):
        return ['candidate_exceeds_shared_source_budget']
    if any(not isinstance(day, dict) or type(day.get('estimatedSeconds')) not in (int, float)
           or not math.isfinite(day['estimatedSeconds'])
           or not isinstance(day.get('volume'), dict)
           or not isinstance(day.get('coverageSets'), dict)
           for day in audit_workouts):
        return ['native_audit_missing_comparison_fields']
    if native_audit_has_errors:
        return (['native_audit_has_errors'] if native_errors_are_repairable
            else ['native_audit_has_unclassified_errors'])
    return []


def _exercise_distribution_profiles(definitions_by_role, required_roles, family_by_reference,
                                    role_intents=None):
    """Compare sourced families only within completely classified executable role pools."""
    role_intents = role_intents or {}
    profile_roles = {}
    for role in required_roles:
        definitions = tuple(sorted(set(definitions_by_role.get(role, ()))))
        if (len(definitions) >= 2 and all(ref in family_by_reference for ref in definitions)
                and len({family_by_reference[ref] for ref in definitions}) >= 2):
            profile_roles.setdefault(definitions, []).append(role)
    profiles = [{'roles': sorted(roles),
             'intent': ('development' if any(role_intents.get(role) == 'development'
                 for role in roles) else 'inclusion'), 'definitionRefs': list(definitions),
             'familyDefinitions': {family: [ref for ref in definitions if family_by_reference[ref] == family]
                for family in sorted({family_by_reference[ref] for ref in definitions})}}
        for definitions, roles in sorted(profile_roles.items())]
    # Inclusion pools must not suppress a development pool, or vice versa.
    return [profile for profile in profiles if not any(
        profile['intent'] == other['intent']
        and set(profile['definitionRefs']) < set(other['definitionRefs']) for other in profiles)]


def _add_exercise_distribution_objective(variable, constraint, option_variables, sessions,
                                         fixed_workouts, required_roles, family_by_reference,
                                         role_intents=None):
    definitions_by_role = {role: set() for role in required_roles}
    for _, _, _, option in option_variables:
        for item in option['items']:
            for role in set(item.get('satisfiesCoverage', [])) & set(definitions_by_role):
                if role:
                    definitions_by_role[role].add(item['definition_id'])
    for workout in fixed_workouts:
        for item in workout.get('exercises', []):
            for role in set(item.get('satisfiesCoverage', [])) & set(definitions_by_role):
                definitions_by_role[role].add(item['definition_id'])
    profiles = _exercise_distribution_profiles(definitions_by_role, required_roles,
        family_by_reference, role_intents)
    costs, peaks = {}, []
    for profile_index, profile in enumerate(profiles):
        refs = set(profile['definitionRefs'])
        fixed_weekly = {family: sum(item.get('numWorkSets', 0)
                * workout.get('timesCompletedInAWeek', 1)
            for workout in fixed_workouts for item in workout.get('exercises', [])
            if item.get('definition_id') in family_refs)
            for family, family_refs in profile['familyDefinitions'].items()}
        upper = sum(fixed_weekly.values()) + sum(
            option['count'] * sessions[day]['timesCompletedInAWeek']
                * sum(item.get('definition_id') in refs for item in option['items'])
            for _, day, _, option in option_variables)
        peak = variable(upper=upper, lower=max(fixed_weekly.values(), default=0),
            integer=False, domain_identity={'kind': 'exercise_distribution_peak',
                'profileIndex': profile_index, 'roles': profile['roles'],
                'definitionRefs': profile['definitionRefs']})
        costs[peak] = 1
        peaks.append((profile, peak))
        for family, family_refs in profile['familyDefinitions'].items():
            coefficients = {index: option['count'] * sessions[day]['timesCompletedInAWeek']
                    * sum(item.get('definition_id') in family_refs for item in option['items'])
                for index, day, _, option in option_variables
                if any(item.get('definition_id') in family_refs for item in option['items'])}
            constraint(('exercise_distribution', profile_index, family), -math.inf, 0,
                {**coefficients, peak: -1}, fixed_weekly[family])
    return costs, profiles, peaks


def _add_execution_complementarity_objective(variable, constraint, option_variables, sessions,
                                             required_roles, execution_by_reference):
    """Prefer reviewed bilateral/unilateral limb-form mixes within the same role."""
    costs, pairs_by_day, roles, inventory = {}, {}, {}, {
        'verifiedComplementaryPairs': [], 'knownOtherModePairs': [], 'unresolvedPairs': []}
    for day_index in range(len(sessions)):
        definitions_by_role = {}
        for _, day, _, option in option_variables:
            if day != day_index:
                continue
            for item in option['items']:
                for role in movement_overlap_roles(item.get('satisfiesCoverage', [])) & set(required_roles):
                    definitions_by_role.setdefault(role, set()).add(item['definition_id'])
                    roles.setdefault((day_index, item['definition_id']), set()).add(role)
        pairs = set()
        for definitions in definitions_by_role.values():
            pairs.update(itertools.combinations(sorted(definitions), 2))
        pairs_by_day[day_index] = sorted(pairs)

    for day_index, pairs in pairs_by_day.items():
        frequency = sessions[day_index]['timesCompletedInAWeek']
        active_by_reference = {}
        for first, second in pairs:
            first_mode = execution_by_reference.get(first, {}).get('limbMode')
            second_mode = execution_by_reference.get(second, {}).get('limbMode')
            pair_evidence = {'workoutIndex': day_index, 'roleKeys': sorted(
                    roles.get((day_index, first), set()) & roles.get((day_index, second), set())),
                'definitionReferences': [first, second], 'limbModes': [first_mode, second_mode]}
            if {first_mode, second_mode} == {'bilateral', 'unilateral'}:
                inventory['verifiedComplementaryPairs'].append(pair_evidence)
                continue
            if first_mode is None or second_mode is None:
                inventory['unresolvedPairs'].append(pair_evidence)
            else:
                inventory['knownOtherModePairs'].append(pair_evidence)
            for reference in (first, second):
                if reference in active_by_reference:
                    continue
                matching = [index for index, option_day, _, option in option_variables
                    if option_day == day_index and any(item['definition_id'] == reference
                        and movement_overlap_roles(item.get('satisfiesCoverage', []))
                            & roles.get((day_index, reference), set())
                        for item in option['items'])]
                active = variable(domain_identity={'kind': 'execution_role_definition_active',
                    'workoutIndex': day_index, 'definitionRef': reference})
                active_by_reference[reference] = active
                for index in matching:
                    constraint(('execution_role_definition_selected', day_index, reference, index),
                        -math.inf, 0, {index: 1, active: -1})
                constraint(('execution_role_definition_active', day_index, reference),
                    -math.inf, 0, {active: 1, **dict.fromkeys(matching, -1)})
            pair_var = variable(domain_identity={'kind': 'execution_complementarity_pair',
                'workoutIndex': day_index, 'definitionRefs': [first, second]})
            costs[pair_var] = frequency
            constraint(('execution_complementarity_pair_used', day_index, first, second),
                -1, math.inf, {pair_var: 1, active_by_reference[first]: -1,
                    active_by_reference[second]: -1})
            for reference in (first, second):
                constraint(('execution_complementarity_pair_selected', day_index, first, second, reference),
                    -math.inf, 0, {pair_var: 1, active_by_reference[reference]: -1})
    return costs, inventory


def _add_balance_control_objective(variable, constraint, option_variables, sessions,
                                   eligible_references, fixed_workouts):
    """Reward one verified weekly balance-control exposure, without rewarding extra sets."""
    fixed_present = any(item.get('definition_id') in eligible_references
        for workout in fixed_workouts for item in workout.get('exercises', []))
    if fixed_present:
        return {}
    options = [index for index, _, _, option in option_variables
        if any(item['definition_id'] in eligible_references for item in option['items'])]
    if not options:
        return {}
    active = variable(upper=1, lower=0, integer=True,
        domain_identity={'kind': 'verified_balance_control_weekly_presence'})
    for index in options:
        # Recipe-option variables are binary; one selected occurrence is enough.
        constraint(('balance_control_presence_requires_selected_option', index), -math.inf, 0,
            {index: 1, active: -1})
    constraint(('balance_control_presence_requires_eligible_option',), -math.inf, 0,
        {active: 1, **dict.fromkeys(options, -1)})
    missing = variable(upper=1, lower=0, integer=True,
        domain_identity={'kind': 'verified_balance_control_weekly_absence'})
    constraint(('balance_control_presence_or_absence'), 1, 1, {active: 1, missing: 1})
    return {missing: 1}


def _add_reviewed_dose_preservation_objective(variable, constraint, option_variables,
                                               sessions, reference):
    if reference is None:
        return {}, 0
    if (not isinstance(reference, dict)
            or reference.get('frequency') != sum(session['timesCompletedInAWeek'] for session in sessions)
            or not isinstance(reference.get('weeklySetsByDefinition'), dict)):
        raise ValueError('The reviewed dose reference does not match the current session schedule.')

    baseline = reference['weeklySetsByDefinition']
    candidate_definitions = {item['definition_id'] for _, day_index, _, option in option_variables
        for item in option['items']}
    costs = {}

    fixed_offset = 0
    for definition_ref in sorted(candidate_definitions | set(baseline)):
        target = baseline.get(definition_ref, 0)
        coefficients = {index: option['count'] * sessions[day_index]['timesCompletedInAWeek'] * sum(
            item['definition_id'] == definition_ref for item in option['items'])
            for index, day_index, _, option in option_variables
            if any(item['definition_id'] == definition_ref for item in option['items'])}
        if not coefficients:
            fixed_offset += target
            continue
        upper = target + sum(coefficients.values())
        deviation = variable(upper=upper, lower=0, integer=False,
            domain_identity={'kind': 'reviewed_dose_deviation', 'definitionRef': definition_ref})
        constraint(('reviewed_dose_deviation', definition_ref, 1), -math.inf, 0,
            {**coefficients, deviation: -1}, -target)
        constraint(('reviewed_dose_deviation', definition_ref, -1), -math.inf, 0,
            {**{index: -value for index, value in coefficients.items()}, deviation: -1}, target)
        costs[deviation] = 1
    return costs, fixed_offset


def _exercise_distribution_summary(workouts, profiles, stage, requested, family_evidence,
                                   development_stage=None, dose_locking=None):
    weekly_sets_by_definition = {}
    for workout in workouts:
        frequency = workout.get('timesCompletedInAWeek', 1)
        for item in workout.get('exercises', []):
            reference = item.get('definition_id')
            weekly_sets_by_definition[reference] = weekly_sets_by_definition.get(reference, 0) + (
                item.get('numWorkSets', 0) * frequency)
    profile_summaries = []
    for profile in profiles:
        exposure = {reference: weekly_sets_by_definition.get(reference, 0)
            for reference in profile['definitionRefs']}
        family_exposure = {family: sum(exposure[ref] for ref in refs)
            for family, refs in profile['familyDefinitions'].items()}
        profile_summaries.append({**copy.deepcopy(profile),
            'weeklyWorkingSetsByDefinition': exposure,
            'weeklyWorkingSetsByFamily': family_exposure,
            'peakFamilyWeeklyWorkingSets': max(family_exposure.values(), default=0)})
    development_profile_count = sum(profile.get('intent') == 'development' for profile in profiles)
    return {
        'status': stage.get('status') if stage else
            'not_requested' if not requested else 'no_completely_reviewed_alternative_family_pools'
            if not profiles else 'not_run_after_solver_stop',
        'objectiveValue': stage.get('value') if stage else None,
        'unit': 'sum_of_peak_family_weekly_working_sets_per_deduplicated_role_profile',
        'profiles': profile_summaries,
        'familyEvidence': copy.deepcopy(family_evidence),
        'developmentPriority': ({'status': development_stage.get('status'),
            'objectiveValue': development_stage.get('value'),
            'profileCount': development_profile_count}
            if development_stage else {'status': ('not_run_after_solver_stop' if development_profile_count
                else 'no_multifamily_development_profiles'),
                'objectiveValue': None,
                'profileCount': development_profile_count}),
        'doseLocking': copy.deepcopy(dose_locking or {
            'scope': 'not_applied', 'roleWeeklyWorkingSets': {}}),
        'knownScope': ('Only maximal completely family-classified qualified role pools represented by executable recipes '
            'in this menu. Unclassified pools are omitted, never scored as diverse. '
            'Strict subset pools are removed within the same intent; overlapping development and inclusion pools '
            'remain separate preferences. '
            'This is not the full library or a fatigue, adequacy, or suitability score.'),
        'interpretation': ('Development-profile family concentration is optimized before total family concentration. '
            'When workload_economy precedes family distribution, weekly totals for explicitly intended development '
            'roles are held at the workload-stage values while exercise-family choices can change. Inclusion-role '
            'amounts remain free to change subject to hard requirements. Otherwise, family distribution preserves '
            'only approved hard floors.'),
    }


def _weekly_role_dose_coefficients(option_variables, sessions, required_roles):
    coefficients = {role: {} for role in required_roles}
    for index, day_index, _, option in option_variables:
        frequency = sessions[day_index]['timesCompletedInAWeek']
        for role in required_roles:
            exposure = option['coverage'].get(role, 0) * frequency
            if exposure:
                coefficients[role][index] = exposure
    return coefficients


def _weekly_role_doses(chosen, coefficients, required_roles, fixed_coverage=None):
    fixed_coverage = fixed_coverage or {}
    return {role: fixed_coverage.get(role, 0) + sum(
        value * chosen[index] for index, value in coefficients.get(role, {}).items())
        for role in required_roles}


def _lock_weekly_role_doses(features, chosen, coefficients, required_roles):
    """Preserve qualified weekly role totals while leaving recipe choice free."""
    locked = _weekly_role_doses(chosen, coefficients, required_roles)
    for role, values in coefficients.items():
        target = sum(value * chosen[index] for index, value in values.items())
        features.append((('exercise_distribution_role_dose', role), target, target, 0, values))
    return locked


def _role_concentration_keys(requirements):
    targets = requirements.get('auditTargets') or {}
    targeted_muscles = {key.replace('lowerBack', 'lower_back') for scope in (
        'weeklyEffectiveSets', 'perSessionEffectiveSets') for key in (targets.get(scope) or {})}
    session_count = requirements.get('sessionsPerWeek')
    # Inclusion and an explicit partial-week development frequency do not imply equal daily doses.
    return sorted({rule['key'] for rule in requirements.get('requiredCoverage', [])
        if (rule['key'] in CODE_OWNED_DIRECT_COVERAGE_ROLES and rule['key'] in targeted_muscles)
        or (rule.get('intent') == 'development' and (rule.get('scope') == 'eachSession'
            or rule.get('minimumSessions') is None
            or session_count is not None and rule['minimumSessions'] >= session_count))})


def _unknown_volume_preference_targets(report, requirements):
    targets = {muscle for key in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
        for muscle, bounds in requirements.get('auditTargets', {}).get(key, {}).items()
        if preferred_volume_target_bounds(bounds) is not None}
    unknown = {muscle for muscle in targets if report.get('regionalTargetEvidence', {}).get(
        muscle, {}).get('status') == 'unknown_selected_aggregate_contributions'}
    evidence = report.get('volumePreferenceEvidence', {})
    unknown.update(item['muscle'] for key in ('weekly', 'perSession') for item in evidence.get(key, [])
        if item.get('muscle') in targets and item.get('status') == 'unknown')
    return unknown


def _joint_candidate_objective_costs(candidate, requirements, context):
    """Score the audited artifact with solver-equivalent objective formulas.

    Role peak comparison costs retain the solver's raw frequency-scaled numerator;
    the solver receipt separately reports per-occurrence values after division by
    total training frequency.
    """
    workouts, report = candidate['workouts'], candidate['audit']
    audited_days = report['workouts']
    frequencies = [workout.get('timesCompletedInAWeek', 1) for workout in workouts]
    total_frequency = sum(frequencies)
    costs = {}
    if 'execution_order' in (requirements.get('objectiveOrder') or []):
        from .programming_guidelines import execution_interference_score
        from .programming_policy import execution_interference_metric_names
        names = execution_interference_metric_names(requirements)
        definitions = context.get('setupDefinitions')
        sequence_costs = {name: 0 for name in names}
        if definitions is not None:
            known = True
            for workout in workouts[len(context.get('fixedWorkouts', [])):]:
                blocks = list(_blocks([workout]))
                profiles = [execution_interference_profile(
                    [definitions[item['definition_id']] for item in block],
                    [item['numWorkSets'] for item in block],
                    set().union(*(set(item.get('satisfiesCoverage', [])) for item in block)), requirements)
                    for block in blocks]
                known &= all(profile['known'] for profile in profiles)
                values = execution_interference_score(list(range(len(blocks))), profiles, requirements)
                for name, value in zip(names, values):
                    sequence_costs[name] += value * workout.get('timesCompletedInAWeek', 1)
            costs.update({'ordering_' + name: value if known else None
                for name, value in sequence_costs.items()})
    if 'exercise_count' in (requirements.get('objectiveOrder') or []):
        from .programming_policy import exercise_count_preference_facts
        definitions = context.get('setupDefinitions')
        costs['exercise_count'] = None
        if definitions is not None:
            domain_refs = context.get('qualifiedRoleEvidence', definitions).keys()
            domain_facts = exercise_count_preference_facts(
                [definitions[reference] for reference in domain_refs if reference in definitions], requirements)
            selected_facts = exercise_count_preference_facts([
                definitions[item['definition_id']] for workout in workouts
                for item in workout.get('exercises', [])], requirements)
            known_muscles = {muscle for muscle, fact in domain_facts.items() if fact['count'] is not None}
            costs['exercise_count'] = (sum(fact['shortfall'] + fact['excess']
                for muscle, fact in selected_facts.items()
                if muscle in known_muscles and fact['count'] is not None) if known_muscles else None)
    if 'setup_economy' in (requirements.get('objectiveOrder') or []):
        definitions = context.get('setupDefinitions')
        costs['setup_economy'] = None
        if definitions is not None and all(item['definition_id'] in definitions
                for workout in workouts for item in workout.get('exercises', [])):
            variable_workouts = workouts[len(context.get('fixedWorkouts', [])):]
            costs['setup_economy'] = sum(len({json.dumps(setup_resource_profile(
                definitions[item['definition_id']], item)['preparationTaskKey'],
                sort_keys=True, separators=(',', ':')) for item in workout.get('exercises', [])})
                * workout.get('timesCompletedInAWeek', 1) for workout in variable_workouts)
            transition_evidence = [_candidate_setup_transition_evidence(workout, definitions, requirements)
                for workout in variable_workouts]
            costs['setup_economy_transitions'] = sum(
                row['knownDeclaredChanges'] * workout.get('timesCompletedInAWeek', 1)
                for row, workout in zip(transition_evidence, variable_workouts))
            costs['setup_economy_transition_unknowns'] = sum(
                row['unknownTransitions'] * workout.get('timesCompletedInAWeek', 1)
                for row, workout in zip(transition_evidence, variable_workouts))
            costs['setup_economy_resource_switches'] = (sum(
                row['declaredResourceSwitches'] * workout.get('timesCompletedInAWeek', 1)
                for row, workout in zip(transition_evidence, variable_workouts))
                if all(row['resourceIdentityComplete'] for row in transition_evidence) else None)

    if 'movement_overlap' in (requirements.get('objectiveOrder') or []):
        costs['movement_overlap'] = sum(workout.get('timesCompletedInAWeek', 1) * len(
            overlapping_movement_pairs(workout.get('exercises', []),
                (context.get('exerciseFamilyEvidence') or {}).get('familyByReference')))
            for workout in workouts[len(context.get('fixedWorkouts', [])):])


    if 'movement_overlap' in (requirements.get('objectiveOrder') or []) and context.get('setupDefinitions') is not None:
        definitions = context['setupDefinitions']
        paired = 0
        for workout in workouts[len(context.get('fixedWorkouts', [])):]:
            groups = []
            for item in workout.get('exercises', []):
                if groups and item.get('superset') is not None and groups[-1][-1].get('superset') == item['superset']:
                    groups[-1].append(item)
                else:
                    groups.append([item])
            paired += workout.get('timesCompletedInAWeek', 1) * sum(superset_lower_body_pair_sets(
                [definitions[item['definition_id']] for item in group],
                [item['numWorkSets'] for item in group]) for group in groups)
        costs['superset_lower_body_overlap'] = paired

    if 'workload_economy' in (requirements.get('objectiveOrder') or []):
        costs['workload_economy'] = sum(item['numWorkSets'] * workout.get('timesCompletedInAWeek', 1)
            for workout in workouts[len(context.get('fixedWorkouts', [])):]
            for item in workout.get('exercises', []))

    targets = requirements.get('auditTargets', {})
    if 'volume_target' in (requirements.get('objectiveOrder') or []):
        cost = 0.0
        for scope, key in (('weekly', 'weeklyEffectiveSets'), ('session', 'perSessionEffectiveSets')):
            for muscle, bounds in targets.get(key, {}).items():
                if 'preferredMinimum' not in bounds:
                    continue
                volumes = ([report.get('weeklyVolume', {})] if scope == 'weekly' else
                    [day.get('volume', {}) for day in audited_days])
                for volume in volumes:
                    actual = volume.get(muscle, {}).get('effective')
                    if type(actual) not in (int, float) or not math.isfinite(actual):
                        return None
                    cost += volume_preference_deviation(actual, bounds)
        costs['volume_target'] = cost
        if _unknown_volume_preference_targets(report, requirements):
            costs['volume_target'] = None
    muscle_keys = set(targets.get('weeklyEffectiveSets', {})) | set(
        targets.get('perSessionEffectiveSets', {}))
    if total_frequency and muscle_keys:
        score = 0.0
        worst_deviation = 0.0
        for muscle in muscle_keys:
            weekly = report.get('weeklyVolume', {}).get(muscle, {}).get('effective')
            if type(weekly) not in (int, float) or not math.isfinite(weekly):
                return None
            for day, frequency in zip(audited_days, frequencies):
                session_value = day.get('volume', {}).get(muscle, {}).get('effective')
                if type(session_value) not in (int, float) or not math.isfinite(session_value):
                    return None
                deviation = 2 * abs(total_frequency * session_value - weekly)
                worst_deviation = max(worst_deviation, deviation)
                score += frequency * deviation
        costs['distribution_worst'] = worst_deviation
        costs['distribution'] = score

    duration_values = [day['estimatedSeconds'] for day in audited_days]
    if 'time_budget' in (requirements.get('objectiveOrder') or []) and requirements.get('preferredSessionSeconds') is not None:
        costs['time_budget'] = sum(max(0, value - requirements['preferredSessionSeconds']) * frequency
            for value, frequency in zip(duration_values, frequencies))
    if 'duration_economy' in (requirements.get('objectiveOrder') or []):
        costs['duration_economy'] = sum(day['estimatedSeconds'] * frequency
            for day, frequency in zip(audited_days, frequencies))
    if 'duration_balance' in (requirements.get('objectiveOrder') or []) and len(duration_values) > 1:
        tolerance = requirements.get('durationBalanceToleranceSeconds', 0)
        costs['duration_balance'] = max(0, max(duration_values) - min(duration_values) - tolerance)

    coverage_rules = [rule for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'coverageBalance']
    if coverage_rules:
        balance_score = 0
        for rule in coverage_rules:
            scopes = [report.get('weeklyCoverageSets', {})] if rule.get('scope') == 'weekly' else [
                day.get('coverageSets', {}) for day in audited_days]
            for counts in scopes:
                first, second = counts.get(rule['first'], 0), counts.get(rule['second'], 0)
                balance_score += (max(0, second - first)
                    if rule.get('relationship') == 'first_not_less_than_second'
                    else abs(first - second))
        costs['source_balance'] = balance_score

    concentration_roles = _role_concentration_keys(requirements)
    if ('role_concentration' in (requirements.get('objectiveOrder') or [])
            and concentration_roles and total_frequency):
        peak_surplus = 0.0
        profile_surplus_by_signature = {}
        weekly_coverage = report.get('weeklyCoverageSets', {})
        role_evidence = context.get('qualifiedRoleEvidence') or {}
        evidence_references = sorted(role_evidence)
        fixed_workouts = context.get('fixedWorkouts') or []
        for role in concentration_roles:
            weekly = weekly_coverage.get(role)
            if type(weekly) not in (int, float) or not math.isfinite(weekly):
                return None
            role_membership = tuple(reference for reference in evidence_references
                if reference in role_evidence and role in set(
                    role_evidence[reference].get('roles', [])
                    if isinstance(role_evidence[reference], dict) else role_evidence[reference]))
            fixed_exposure = tuple((workout.get('timesCompletedInAWeek', 1), sum(
                item.get('numWorkSets', 0) for item in workout.get('exercises', [])
                if role in item.get('satisfiesCoverage', []))) for workout in fixed_workouts)
            profile_signature = ((role_membership, fixed_exposure) if evidence_references
                else (role, fixed_exposure))
            profile_peak = 0.0
            for day, frequency in zip(audited_days, frequencies):
                session_value = day.get('coverageSets', {}).get(role, 0)
                if type(session_value) not in (int, float) or not math.isfinite(session_value):
                    return None
                surplus = total_frequency * session_value - weekly
                peak_surplus = max(peak_surplus, surplus)
                profile_peak = max(profile_peak, surplus)
            profile_surplus_by_signature[profile_signature] = max(0.0, profile_peak)
        costs['role_concentration'] = max(0.0, peak_surplus)
        costs['role_concentration_tiebreak'] = sum(profile_surplus_by_signature.values())

    development_roles = sorted(rule['key'] for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') == 'development')
    if development_roles:
        weekly_coverage = report['weeklyCoverageSets']
        role_totals = {role: weekly_coverage.get(role, 0) for role in development_roles}
        costs['development_emphasis'] = -min(role_totals.values())
        costs['development_exposure'] = -sum(role_totals.values())

    objective_order = requirements.get('objectiveOrder') or []
    if 'exercise_distribution' in objective_order:
        role_evidence = context.get('qualifiedRoleEvidence')
        if not isinstance(role_evidence, dict):
            costs['exercise_distribution'] = None
        else:
            required_roles = [rule['key'] for rule in requirements.get('requiredCoverage', [])]
            role_intents = {rule['key']: rule.get('intent') for rule in requirements.get('requiredCoverage', [])}
            definitions_by_role = {role: [] for role in required_roles}
            for definition_ref, qualified_roles in role_evidence.items():
                if isinstance(qualified_roles, dict):
                    qualified_roles = qualified_roles.get('roles', [])
                for role in set(qualified_roles or ()) & set(required_roles):
                    definitions_by_role[role].append(definition_ref)
            family_evidence = context.get('exerciseFamilyEvidence') or {}
            profiles = _exercise_distribution_profiles(definitions_by_role, required_roles,
                family_evidence.get('familyByReference') or {}, role_intents)
            weekly_sets_by_definition = {}
            for workout, frequency in zip(workouts, frequencies):
                for item in workout.get('exercises', []):
                    definition_ref = item['definition_id']
                    weekly_sets_by_definition[definition_ref] = weekly_sets_by_definition.get(
                        definition_ref, 0) + item['numWorkSets'] * frequency
            profile_costs = {profile_index: max(
                (sum(weekly_sets_by_definition.get(ref, 0) for ref in family_refs)
                    for family_refs in profile['familyDefinitions'].values()), default=0)
                for profile_index, profile in enumerate(profiles)}
            costs['exercise_distribution'] = sum(profile_costs.values())
            development_cost = sum(profile_costs[index] for index, profile in enumerate(profiles)
                if profile.get('intent') == 'development')
            if any(profile.get('intent') == 'development' for profile in profiles):
                costs['exercise_distribution_development'] = development_cost
            if not profiles:
                costs['exercise_distribution'] = None

    execution_properties = context.get('executionPropertiesByReference')
    if 'execution_complementarity' in objective_order:
        if not isinstance(execution_properties, dict):
            costs['execution_complementarity'] = None
        else:
            pair_cost = 0
            required_movement_roles = {rule['key'] for rule in requirements.get('requiredCoverage', [])}
            for workout in workouts[len(context.get('fixedWorkouts', [])):]:
                role_by_definition = {}
                for item in workout.get('exercises', []):
                    roles = movement_overlap_roles(item.get('satisfiesCoverage', [])) & required_movement_roles
                    if roles:
                        role_by_definition.setdefault(item['definition_id'], set()).update(roles)
                for first, second in itertools.combinations(sorted(role_by_definition), 2):
                    if not role_by_definition[first] & role_by_definition[second]:
                        continue
                    modes = {execution_properties.get(reference, {}).get('limbMode')
                        for reference in (first, second)}
                    if modes != {'bilateral', 'unilateral'}:
                        pair_cost += workout.get('timesCompletedInAWeek', 1)
            costs['execution_complementarity'] = pair_cost

    if 'balance_control' in objective_order:
        if not isinstance(execution_properties, dict):
            costs['balance_control'] = None
        else:
            eligible = set(context.get('balanceControlCandidateReferences') or [])
            selected = {item['definition_id'] for workout in workouts
                for item in workout.get('exercises', [])}
            costs['balance_control'] = (0 if selected & eligible else 1) if eligible else None

    demand_evidence = context.get('demandEvidence')
    demand_groups = (demand_evidence or {}).get('groups')
    if ('demand_distribution' in (requirements.get('objectiveOrder') or [])
            and (not isinstance(demand_evidence, dict)
                 or demand_evidence.get('status') != 'available'
                 or not isinstance(demand_groups, dict)
                 or any(not isinstance(group.get('presentDefinitionRefs'), list)
                        for group in demand_groups.values()))):
        costs['demand_distribution'] = None
        costs['demand_colocation'] = None
    elif isinstance(demand_groups, dict):
        by_session = []
        for workout in workouts:
            day_counts = {}
            for item in workout.get('exercises', []):
                definition_id = item.get('definition_id')
                sets = item.get('numWorkSets', 0)
                for key, group in demand_groups.items():
                    if definition_id in set(group['presentDefinitionRefs']):
                        day_counts[key] = day_counts.get(key, 0) + sets
            by_session.append(day_counts)
        costs['demand_distribution'] = sum(max((day.get(key, 0) for day in by_session), default=0)
            for key in demand_groups)
        union = context.get('demandUnion')
        if union and not isinstance(union.get('presentDefinitionRefs'), list):
            costs['demand_colocation'] = None
        union_ids = set((union or {}).get('presentDefinitionRefs', []))
        if union_ids:
            costs['demand_colocation'] = max((sum(item.get('numWorkSets', 0)
                for item in workout.get('exercises', []) if item.get('definition_id') in union_ids)
                for workout in workouts), default=0)

    if 'preservation' in (requirements.get('objectiveOrder') or []):
        costs['preservation'] = None

    for tier in requirements.get('objectiveTiers', []):
        for goal in tier:
            if goal['metric'].startswith(('weekly_volume:', 'weekly_effective_sets:')):
                muscle = goal['metric'].split(':', 1)[1]
                bounds = requirements.get('auditTargets', {}).get('weeklyEffectiveSets', {}).get(muscle, {})
                actual = report.get('weeklyVolume', {}).get(muscle, {}).get('effective')
                costs[goal['metric']] = ((-actual if goal['metric'].startswith('weekly_effective_sets:')
                    else volume_preference_deviation(actual, bounds))
                    if type(actual) in (int, float) and 'preferredMinimum' in bounds
                    and muscle not in _unknown_volume_preference_targets(report, requirements) else None)
    costs.update(goal_programming_costs(requirements, costs, report.get('weeklyCoverageSets')))
    return costs


def _development_role_weekly_doses(candidate, requirements):
    weekly = candidate.get('audit', {}).get('weeklyCoverageSets', {})
    return {rule['key']: weekly.get(rule['key'], 0)
        for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') == 'development'}


def _source_balance_doses(candidate, requirements):
    report = candidate['audit']
    return [{'scope': component['scope'], 'roles': component['roles'],
        'combinedWorkingSetExposure': [sum(counts.get(role, 0) for role in component['roles'])
            for counts in ([report.get('weeklyCoverageSets', {})]
                if component['scope'] == 'weekly' else
                [day.get('coverageSets', {}) for day in report.get('workouts', [])])]}
        for component in source_balance_dose_components(requirements)]


def _selected_session_work(workouts, definitions):
    selected = []
    for day in workouts:
        counts = Counter()
        for item in day.get('exercises', []):
            reference = item['definition_id']
            identifier = definitions.get(reference, {}).get('id', reference)
            counts[identifier] += item['numWorkSets']
        selected.append(dict(sorted(counts.items())))
    return selected


def compare_audited_joint_candidates(baseline, candidate, *, requirements, context):
    """Compare two code-audited weeks without treating a new menu as the same solver domain.

    This is a numeric promotion decision only. A `retain_baseline` result does not
    resolve or discard review/repair obligations attached to either candidate.
    """
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {'decision': 'incomparable', 'reason': 'malformed_candidate_input',
            'firstDifferingObjective': None, 'comparisons': []}
    result = {
        'decision': 'incomparable', 'reason': None, 'firstDifferingObjective': None,
        'comparisons': [], 'baselineSearchStatus': baseline.get('searchStatus'),
        'candidateSearchStatus': candidate.get('searchStatus'),
    }
    if not isinstance(requirements, dict) or not isinstance(context, dict):
        result['reason'] = 'missing_shared_approved_context'
        return result
    required_context = ('restrictionPolicy', 'libraryFingerprint', 'historyFingerprint',
        'sourceWorkingSetBudget', 'qualifiedRoleEvidence', 'demandEvidence', 'demandUnion')
    if any(key not in context for key in required_context):
        result['reason'] = 'incomplete_shared_approved_context'
        return result
    if (not isinstance(context['restrictionPolicy'], dict)
            or not isinstance(context['libraryFingerprint'], str)
            or not context['libraryFingerprint']):
        result['reason'] = 'invalid_shared_authority_context'
        return result

    baseline_errors = _candidate_audit_errors(baseline, requirements, context)
    candidate_errors = _candidate_audit_errors(candidate, requirements, context)
    result['baselineAuditErrors'] = baseline_errors
    result['candidateAuditErrors'] = candidate_errors
    baseline_has_only_native_audit_errors = baseline_errors == ['native_audit_has_errors']
    if baseline_errors and not baseline_has_only_native_audit_errors:
        result['reason'] = 'baseline_not_eligible_for_comparison'
        return result
    if candidate_errors:
        if baseline_has_only_native_audit_errors:
            result['reason'] = 'neither_candidate_is_scope_valid_and_natively_feasible'
            return result
        result['decision'] = 'retain_baseline'
        result['reason'] = 'candidate_failed_native_audit_or_scope_checks'
        return result

    if baseline['audit'].get('targets') != candidate['audit'].get('targets'):
        result['reason'] = 'audit_target_context_mismatch'
        return result
    if baseline['audit'].get('targets') != requirements.get('auditTargets'):
        result['reason'] = 'native_audit_does_not_match_approved_targets'
        return result

    definitions = context.get('setupDefinitions') or {}
    result['executionEvaluation'] = {
        'baseline': evaluate_audited_execution(baseline, definitions, requirements),
        'candidate': evaluate_audited_execution(candidate, definitions, requirements),
        'scope': 'Pairwise comparison of these audited artifacts, not proof of the best possible plan.'}

    if baseline_has_only_native_audit_errors:
        result['decision'] = 'promote_candidate'
        result['firstDifferingObjective'] = 'native_audit_feasibility'
        result['reason'] = 'hard_feasibility_restored'
        return result

    baseline_costs = _joint_candidate_objective_costs(baseline, requirements, context)
    candidate_costs = _joint_candidate_objective_costs(candidate, requirements, context)
    if baseline_costs is None or candidate_costs is None:
        result['reason'] = 'native_audit_missing_objective_values'
        return result
    result['objectiveCosts'] = {'baseline': baseline_costs, 'candidate': candidate_costs}
    available = {name: (baseline_costs.get(name) is not None
        and candidate_costs.get(name) is not None)
        for name in set(baseline_costs) | set(candidate_costs)}
    if 'execution_order' in (requirements.get('objectiveOrder') or []):
        available['execution_order'] = True
    if 'setup_economy_transitions' in available:
        complete_setup_evidence = (baseline_costs.get('setup_economy_transition_unknowns') == 0
            and candidate_costs.get('setup_economy_transition_unknowns') == 0)
        available['setup_economy_transitions'] = complete_setup_evidence
        if not complete_setup_evidence:
            result['setupTransitionEvidence'] = {
                'baselineUnknownEdges': baseline_costs.get('setup_economy_transition_unknowns'),
                'candidateUnknownEdges': candidate_costs.get('setup_economy_transition_unknowns'),
                'status': 'not_compared_unknown_configuration',
                'scoring': 'known_declared_changes_only; unknown_edges_not_scored'}
    if 'demand_distribution' in (requirements.get('objectiveOrder') or []):
        available['demand_distribution'] = True
    if 'preservation' in (requirements.get('objectiveOrder') or []):
        available['preservation'] = True
    if 'exercise_distribution' in (requirements.get('objectiveOrder') or []):
        available['exercise_distribution'] = True
    if 'progression' in (requirements.get('objectiveOrder') or []):
        available['progression'] = True
    if 'setup_economy' in (requirements.get('objectiveOrder') or []):
        # An unmeasurable approved priority must not silently disappear before duration.
        available['setup_economy'] = True
    if ('volume_target' in (requirements.get('objectiveOrder') or [])
            and any(preferred_volume_target_bounds(bounds) is not None
                for key in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
                for bounds in requirements.get('auditTargets', {}).get(key, {}).values())):
        available['volume_target'] = True
    if ('role_concentration' in (requirements.get('objectiveOrder') or [])
            and _role_concentration_keys(requirements)):
        available['role_concentration'] = True
        available['role_concentration_tiebreak'] = True
    ordered = _ordered_joint_objective_names(requirements, available)
    if requirements.get('preferenceResolution') == 'explicit_tradeoffs':
        from .programming_policy import assess_audited_programming_tradeoff
        requested = requirements.get('objectiveOrder') or []
        names = list(dict.fromkeys([*ordered, *(name for name in requested
            if name in baseline_costs or name in candidate_costs)]))
        assessment = assess_audited_programming_tradeoff(baseline, candidate,
            requirements=requirements, baseline_costs=baseline_costs,
            candidate_costs=candidate_costs, objective_names=names,
            same_selected_work=(_selected_session_work(baseline['workouts'], definitions)
                == _selected_session_work(candidate['workouts'], definitions)))
        result['programmingTradeoff'] = assessment
        result['comparisons'] = [{**entry, 'baselineCost': entry['baseline'],
            'candidateCost': entry['candidate'], 'status': relation}
            for relation in ('improved', 'worsened', 'unchanged') for entry in assessment[relation]]
        status = assessment['status']
        result['decision'] = ('promote_candidate' if status in ('candidate_dominates', 'candidate_preferred') else
            'retain_baseline' if status in ('baseline_dominates', 'baseline_preferred', 'equivalent', 'hard_violation') else
            'incomparable')
        result['reason'] = ('soft_preference_tradeoff_requires_decision'
            if status in ('requires_programming_decision', 'unknown') else
            'audited_preference_' + status)
        return result
    if 'setup_economy_transitions' in ordered:
        result['setupTransitionEvidence'] = {
            'baselineUnknownEdges': baseline_costs['setup_economy_transition_unknowns'],
            'candidateUnknownEdges': candidate_costs['setup_economy_transition_unknowns'],
            'status': 'compared_complete_declared_configuration_evidence',
            'scoring': 'known_declared_changes_only; unknown_edges_not_scored'}
    for objective in ordered:
        if objective.startswith('ordering_'):
            baseline_work = _selected_session_work(baseline['workouts'], definitions)
            candidate_work = _selected_session_work(candidate['workouts'], definitions)
            if baseline_work != candidate_work:
                result['firstDifferingObjective'] = 'execution_order'
                result['reason'] = 'execution_order_requires_same_selected_session_work'
                result['comparisons'].append({'objective': 'execution_order',
                    'status': 'incomparable_selected_session_work',
                    'baselineSelectedSessionWork': baseline_work,
                    'candidateSelectedSessionWork': candidate_work})
                return result
        if objective == 'progression':
            result['firstDifferingObjective'] = objective
            result['reason'] = 'progression_requires_app_owned_evidence'
            return result
        if objective == 'preservation':
            result['comparisons'].append({'objective': objective,
                'baselineCost': None, 'candidateCost': None,
                'status': 'baseline_retained_on_tie'})
            result['firstDifferingObjective'] = objective
            result['decision'] = 'retain_baseline'
            result['reason'] = 'preservation_tie_break_retains_saved_baseline'
            return result
        baseline_value = baseline_costs.get(objective)
        candidate_value = candidate_costs.get(objective)
        if objective == 'source_balance':
            baseline_doses = _source_balance_doses(baseline, requirements)
            candidate_doses = _source_balance_doses(candidate, requirements)
            lower_exposure = any(after < before
                for baseline_dose, candidate_dose in zip(baseline_doses, candidate_doses)
                for before, after in zip(baseline_dose['combinedWorkingSetExposure'],
                    candidate_dose['combinedWorkingSetExposure']))
            if (baseline_doses != candidate_doses
                    and (not selection_precedes_execution(requirements) or lower_exposure)):
                result['firstDifferingObjective'] = objective
                result['reason'] = 'combined_role_doses_differ_at_source_balance'
                result['comparisons'].append({'objective': objective,
                    'status': 'incomparable_combined_role_doses',
                    'baselineCombinedRoleDoses': baseline_doses,
                    'candidateCombinedRoleDoses': candidate_doses})
                return result
        if objective == 'exercise_distribution':
            approved_order = requirements.get('objectiveOrder') or []
            workload_precedes_family = ('workload_economy' in approved_order
                and 'exercise_distribution' in approved_order
                and approved_order.index('workload_economy') < approved_order.index('exercise_distribution'))
            if workload_precedes_family:
                baseline_roles = _development_role_weekly_doses(baseline, requirements)
                candidate_roles = _development_role_weekly_doses(candidate, requirements)
                if baseline_roles != candidate_roles:
                    result['firstDifferingObjective'] = objective
                    result['reason'] = 'development_role_doses_differ_at_exercise_distribution'
                    result['comparisons'].append({'objective': objective,
                        'status': 'incomparable_development_role_doses',
                        'baselineDevelopmentRoleWeeklyWorkingSets': baseline_roles,
                        'candidateDevelopmentRoleWeeklyWorkingSets': candidate_roles})
                    return result
        if baseline_value is None or candidate_value is None:
            result['reason'] = ('higher_priority_demand_evidence_unavailable'
                if objective in ('demand_distribution', 'demand_colocation')
                else f'objective_evidence_unavailable:{objective}')
            return result
        if objective == 'exercise_distribution':
            baseline_development = baseline_costs.get('exercise_distribution_development')
            candidate_development = candidate_costs.get('exercise_distribution_development')
            if baseline_development is not None or candidate_development is not None:
                if baseline_development is None or candidate_development is None:
                    result['reason'] = 'objective_evidence_unavailable:exercise_distribution_development'
                    return result
                development_status = ('tie' if math.isclose(baseline_development,
                    candidate_development, abs_tol=1e-9) else
                    'candidate_better' if candidate_development < baseline_development else 'baseline_better')
                result['comparisons'].append({'objective': 'exercise_distribution_development',
                    'baselineCost': baseline_development,
                    'candidateCost': candidate_development,
                    'status': development_status})
                if development_status != 'tie':
                    result['firstDifferingObjective'] = objective
                    result['decision'] = ('promote_candidate' if development_status == 'candidate_better'
                        else 'retain_baseline')
                    result['reason'] = 'first_differing_approved_objective'
                    return result
        comparison = {'objective': objective, 'baselineCost': baseline_value,
            'candidateCost': candidate_value,
            'status': 'tie' if math.isclose(baseline_value, candidate_value, abs_tol=1e-9)
                else 'candidate_better' if candidate_value < baseline_value else 'baseline_better'}
        if objective in ('role_concentration', 'role_concentration_tiebreak'):
            comparison['unit'] = 'frequency_scaled_peak_surplus'
        elif objective == 'superset_lower_body_overlap':
            comparison['unit'] = 'weekly_paired_major_lower_body_sets'
        elif objective == 'setup_economy_transitions':
            comparison['unit'] = 'known_declared_resource_or_load_changes_per_week'
        elif objective == 'setup_economy_resource_switches':
            comparison['unit'] = 'declared_resource_reference_switches_per_week; not physical changeover time'
        result['comparisons'].append(comparison)
        if comparison['status'] != 'tie':
            result['firstDifferingObjective'] = objective
            if objective == 'progression':
                result['reason'] = f'objective_requires_unavailable_comparison:{objective}'
                return result
            result['decision'] = ('promote_candidate' if comparison['status'] == 'candidate_better'
                else 'retain_baseline')
            result['reason'] = 'first_differing_approved_objective'
            return result
    result['decision'] = 'retain_baseline'
    result['reason'] = 'no_numeric_improvement_baseline_wins_tie'
    return result


def candidate_menu_fingerprint(workouts):
    """Identify substantive movement choices, placements, and pairings only.

    Numeric allocation, labels, local coaching notes, and other metadata do not
    expand the candidate menu. The source order and superset membership do,
    because they change executable placement and setup choices.
    """
    canonical = []
    for day in workouts or []:
        blocks, index = [], 0
        exercises = day.get('exercises', [])
        while index < len(exercises):
            item = exercises[index]
            group = item.get('superset')
            members = [item.get('definition_id')]
            index += 1
            if group is not None:
                while index < len(exercises) and exercises[index].get('superset') == group:
                    members.append(exercises[index].get('definition_id'))
                    index += 1
            blocks.append({'members': members, 'paired': len(members) > 1})
        canonical.append({'timesCompletedInAWeek': day.get('timesCompletedInAWeek'), 'blocks': blocks})
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def joint_problem_fingerprint(sessions, requirements, equipment, history=None, messages=None,
                              *, restriction_policy=None, existing=None,
                              allow_educated_load_guesses=True,
                              preserve_source_selection=False,
                              redistribution_constraints=None,
                              source_working_set_budget=None,
                              reviewed_baseline_workouts=None):
    from .planning_tools import AUDIT_VERSION, library_fingerprint
    from .planning_decisions import _active_reusable_decision_state, resolved_decisions

    current_history = getattr(history, 'fingerprint', None)
    library_hash = library_fingerprint(equipment)
    sessions = complete_training_schedule(sessions, requirements, (existing or {}).get('workouts', []))
    full_workouts = [*(existing or {}).get('workouts', []), *sessions]
    payload = {'requirements': requirements,
        'inputWorkouts': [{key: value for key, value in day.items() if key not in ('name', 'description')}
                          for day in full_workouts],
        'prescriptionFingerprint': prescription_fingerprint(full_workouts),
        'libraryFingerprint': library_hash, 'historyFingerprint': current_history,
        'recordedEvidencePolicyVersion': RECORDED_EVIDENCE_POLICY_VERSION,
        'recordedEvidence': _selected_recorded_evidence(
            messages or [], library_hash, current_history, equipment, full_workouts),
        'selectionPolicyVersion': SELECTION_POLICY_VERSION, 'auditVersion': AUDIT_VERSION,
        'jointPolicy': JOINT_POLICY_DESCRIPTOR,
        'exerciseFamilyEvidence': reviewed_exercise_family_evidence(equipment),
        'executionProperties': reviewed_execution_properties(equipment),
        'sourceWorkingSetBudget': _source_working_set_budget_identity(sessions, source_working_set_budget),
        'reviewedDoseReference': _reviewed_dose_reference_identity(reviewed_baseline_workouts),
        'preserveSourceSelection': bool(preserve_source_selection),
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': allow_educated_load_guesses}
    decisions = _active_reusable_decision_state(resolved_decisions(messages or []))
    if decisions:
        payload['resolvedPlanningDecisions'] = decisions
    if redistribution_constraints:
        payload['redistributionConstraints'] = copy.deepcopy(redistribution_constraints)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _selected_recorded_evidence(messages, library_hash, history_fingerprint, equipment, sessions):
    """Hash only history evidence used by the solver for these selected recipes."""
    selected_references = {item.get('definition_id') for day in sessions
        for item in day.get('exercises', []) if isinstance(item, dict)}
    definitions = sorted((equipment or {}).get('exerciseDefinitions', []), key=lambda item: item['id'])
    selected_definition_ids = {definition['id'] for index, definition in enumerate(definitions)
        if f'LIBRARY_{index}' in selected_references}
    evidence = recorded_evidence(messages, library_hash, history_fingerprint, equipment=equipment)
    return {definition_id: item for definition_id, item in evidence.items()
        if definition_id in selected_definition_ids}


def _joint_model_domain_fingerprint(variables, features, *, library_hash, history_fingerprint,
                                    evidence, restriction_policy, allow_educated_load_guesses,
                                    preserve_source_selection):
    """Hash the actual finite-domain rows, variable bounds and source identities.

    Objective coefficients and current count seeds are intentionally omitted. The
    option identities carry generated counts, muscle credits and timing; matrix
    rows bind those alternatives to every hard feasibility constraint.
    """
    def finite_value(value):
        if isinstance(value, float) and math.isinf(value):
            return 'Infinity' if value > 0 else '-Infinity'
        return value

    optional_objective_slack = {'coverage_balance_deviation', 'distribution_deviation', 'distribution_peak',
                                'duration_balance_bound',
                                'duration_balance_excess', 'demand_distribution_peak',
                                'development_exposure_deficit', 'role_concentration_peak',
                                'role_concentration_profile_peak',
                                'demand_colocation_peak', 'exercise_distribution_peak',
                                'goal_target_miss', 'goal_tier_peak'}
    feasibility_indexes = [index for index, variable in enumerate(variables)
        if not (isinstance(variable.get('domainIdentity'), dict)
            and variable['domainIdentity'].get('kind') in optional_objective_slack)]
    index_map = {old: new for new, old in enumerate(feasibility_indexes)}
    variable_domain = [{
        'lower': finite_value(variable['lower']),
        'upper': finite_value(variable['upper']),
        'integer': variable.get('integer', True),
        'identity': variable.get('domainIdentity'),
    } for index, variable in enumerate(variables) if index in index_map]
    rows = []
    for label, lower, upper, intercept, coefficients in features:
        # These deviations are optional objective slack. They can never turn an
        # otherwise infeasible plan into a feasible one, so omit their variables
        # and rows from the hard feasibility domain identity.
        if isinstance(label, tuple) and label and label[0] in (
                'coverage_balance', 'distribution_deviation', 'distribution_peak',
                'demand_distribution_peak', 'duration_balance',
                'development_emphasis', 'role_concentration', 'demand_colocation',
                'role_concentration_peak', 'role_concentration_profile_peak',
                'demand_colocation_peak', 'exercise_distribution', 'goal_target_miss', 'goal_tier_peak'):
            continue
        coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                             else enumerate(coefficients))
        rows.append({
            'label': label,
            'lower': finite_value(lower),
            'upper': finite_value(upper),
            'intercept': finite_value(intercept),
            'coefficients': [[index_map[index], value] for index, value in sorted(coefficient_items)
                             if value and index in index_map],
        })
    payload = {
        'modelDomainVersion': 2,
        'variables': variable_domain,
        'constraints': rows,
        'libraryFingerprint': library_hash,
        'historyFingerprint': history_fingerprint,
        'recordedEvidencePolicyVersion': RECORDED_EVIDENCE_POLICY_VERSION,
        'recordedEvidence': evidence,
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': bool(allow_educated_load_guesses),
        'preserveSourceSelection': bool(preserve_source_selection),
        'selectionPolicyVersion': SELECTION_POLICY_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def _canonicalize_objective_epigraphs(variables, features, candidate, goals, *, auxiliary_lattice=None):
    """Canonicalize epigraphs and recheck their source rows at solver tolerance."""
    def exact(value):
        try:
            return _rational(value)
        except ValueError:
            # Legacy tolerance diagnostics accept arbitrary floats; CP admission remains strict.
            if auxiliary_lattice is None and type(value) is float and math.isfinite(value):
                return Fraction(value)
            raise
    epigraph_kinds = {'coverage_balance_deviation', 'distribution_deviation', 'distribution_peak',
                      'duration_balance_bound',
                      'duration_balance_excess', 'volume_target_deviation',
                      'time_budget_excess', 'exercise_count_deviation', 'execution_exposure_peak',
                      'demand_distribution_peak', 'redistribution_peak', 'development_exposure_deficit',
                      'role_concentration_peak', 'role_concentration_profile_peak',
                      'demand_colocation_peak', 'exercise_distribution_peak', 'goal_target_miss', 'goal_tier_peak'}
    costs = {index: cost for _, goal_costs in goals for index, cost in goal_costs.items() if cost}
    duration_balance_requested = any(name == 'duration_balance' for name, _ in goals)
    values = list(candidate)
    rows_by_epigraph = {index: [] for index, variable in enumerate(variables)
        if (variable.get('domainIdentity') or {}).get('kind') in epigraph_kinds}
    for row in features:
        coefficients = row[4]
        coefficient_items = coefficients.items() if isinstance(coefficients, dict) else enumerate(coefficients)
        for index, coefficient in coefficient_items:
            if coefficient and index in rows_by_epigraph:
                rows_by_epigraph[index].append(row)
    if duration_balance_requested:
        _canonicalize_duration_balance_face(variables, features, values)
    for index, variable in enumerate(variables):
        identity = variable.get('domainIdentity')
        if not isinstance(identity, dict):
            continue
        kind = identity.get('kind')
        if kind not in epigraph_kinds:
            continue
        lower, upper = variable['lower'], variable['upper']
        if auxiliary_lattice is not None:
            lower, upper = exact(lower), exact(upper)
        for _, row_lower, row_upper, intercept, coefficients in rows_by_epigraph[index]:
            coefficient = (coefficients.get(index, 0) if isinstance(coefficients, dict)
                            else coefficients[index] if index < len(coefficients) else 0)
            if not coefficient:
                continue
            coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                                 else enumerate(coefficients))
            # Preserve the exact CP lattice while reconstructing derived values.
            rest = exact(intercept) + sum(exact(value) * exact(values[column])
                for column, value in coefficient_items if column != index)
            exact_coefficient = exact(coefficient)
            if coefficient > 0:
                if math.isfinite(row_lower):
                    bound = (exact(row_lower) - rest) / exact_coefficient
                    lower = max(lower, bound if auxiliary_lattice is not None else float(bound))
                if math.isfinite(row_upper):
                    bound = (exact(row_upper) - rest) / exact_coefficient
                    upper = min(upper, bound if auxiliary_lattice is not None else float(bound))
            else:
                if math.isfinite(row_upper):
                    bound = (exact(row_upper) - rest) / exact_coefficient
                    lower = max(lower, bound if auxiliary_lattice is not None else float(bound))
                if math.isfinite(row_lower):
                    bound = (exact(row_lower) - rest) / exact_coefficient
                    upper = min(upper, bound if auxiliary_lattice is not None else float(bound))
        tolerance = _MILP_SOLUTION_TOLERANCE
        if lower > upper + tolerance:
            raise RuntimeError(
                f"Epigraph {identity!r} has no feasible canonical value for the selected options "
                f"(lower={lower!r}, upper={upper!r}).")
        if auxiliary_lattice is not None:
            scale = 1 if variable.get('integer', True) else auxiliary_lattice
            lower = Fraction(math.ceil(lower * scale), scale)
            upper = Fraction(math.floor(upper * scale), scale)
            if lower > upper:
                raise RuntimeError(f'Epigraph {identity!r} has no feasible value on the CP auxiliary lattice.')
        elif variable.get('integer', True):
            lower, upper = math.ceil(lower - tolerance), math.floor(upper + tolerance)
        if lower > upper:
            # There is no exact interval, but the discrepancy is within the
            # solver's documented feasibility tolerance. Preserve the incumbent
            # and let the complete source-row check decide feasibility.
            values[index] = candidate[index]
        elif kind == 'duration_balance_bound' and duration_balance_requested:
            values[index] = lower if identity.get('bound') == 'maximum' else upper
        elif index not in costs:
            # Some derived epigraphs are not objective tie-breakers. Clamp only
            # numerical drift; do not invent a preference for their value.
            values[index] = min(max(candidate[index], lower), upper)
        else:
            values[index] = lower if costs[index] > 0 else upper
        if auxiliary_lattice is not None:
            values[index] = float(values[index])
    for label, lower, upper, intercept, coefficients in features:
        coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                             else enumerate(coefficients))
        if auxiliary_lattice is not None:
            activity = exact(intercept) + sum(exact(value) * exact(values[index])
                for index, value in coefficient_items)
            valid = ((not math.isfinite(lower) or activity >= exact(lower))
                and (not math.isfinite(upper) or activity <= exact(upper)))
        else:
            activity = math.fsum((intercept, *(value * values[index] for index, value in coefficient_items)))
            valid = lower - _MILP_SOLUTION_TOLERANCE <= activity <= upper + _MILP_SOLUTION_TOLERANCE
        if not valid:
            lower_slack = activity - lower if math.isfinite(lower) else math.inf
            upper_slack = upper - activity if math.isfinite(upper) else math.inf
            raise RuntimeError(
                f"Canonical epigraphs violate joint-planning row {label!r}: "
                f"activity={activity!r}, bounds=({lower!r}, {upper!r}), "
                f"slack=({lower_slack!r}, {upper_slack!r}).")
    return values


def _exact_objective_value(values, costs, offset=0):
    return _rational(offset) + sum(_rational(cost) * _rational(values[index])
        for index, cost in costs.items())


def _objective_variable_bound(variables, costs, offset=0, *, exact=False):
    """Return a proven separable lower bound from variable bounds, or None."""
    bound = _rational(offset)
    for index, cost in costs.items():
        if cost == 0:
            continue
        variable = variables[index]
        endpoint = variable.get('lower', 0) if cost > 0 else variable.get('upper')
        if endpoint is None or not math.isfinite(endpoint):
            return None
        bound += _rational(cost) * _rational(endpoint)
    return bound if exact else float(bound)


def _canonicalize_duration_balance_face(variables, features, values):
    """Derive max, min and tolerance excess together from the selected session durations."""
    maximum_index = minimum_index = excess_index = None
    for index, variable in enumerate(variables):
        identity = variable.get('domainIdentity') or {}
        if identity.get('kind') == 'duration_balance_bound':
            if identity.get('bound') == 'maximum':
                maximum_index = index
            elif identity.get('bound') == 'minimum':
                minimum_index = index
        elif identity.get('kind') == 'duration_balance_excess':
            excess_index = index
    if maximum_index is None or minimum_index is None:
        return values

    durations = []
    for label, _, _, intercept, coefficients in features:
        if not (isinstance(label, tuple) and len(label) == 3
                and label[0] == 'duration_balance' and label[2] == 'maximum'):
            continue
        coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                             else enumerate(coefficients))
        durations.append(math.fsum((intercept, *(coefficient * values[index]
            for index, coefficient in coefficient_items if index != maximum_index))))
    if not durations:
        return values

    maximum, minimum = max(durations), min(durations)
    values[maximum_index] = maximum
    values[minimum_index] = minimum
    if excess_index is not None:
        tolerance = next((upper for label, _, upper, _, _ in features
            if label == ('duration_balance', 'tolerance')), 0)
        values[excess_index] = max(0, maximum - minimum - tolerance)
    return values


def _prepared_selection_seed(messages, equipment, training_history, sessions, definitions):
    """Use only the current successful preparation's selected sessions as a solve seed."""
    if not messages:
        return None
    from .planning_tools import (_latest_result, active_requirement_result,
        library_fingerprint, requirement_sources, source_message_context)

    _, requirements_receipt = active_requirement_result(messages)
    _, prepared = _latest_result(messages, 'prepare_workout_sessions')
    _, workers = _latest_result(messages, 'draft_workout_sessions')
    requirements_id = requirements_receipt.get('requirementsId')
    current_history = getattr(training_history, 'fingerprint', None)
    if (not isinstance(prepared, dict) or not prepared.get('setAllocation', {}).get('feasible')
            or not isinstance(workers, dict)
            or not requirements_id
            or prepared.get('requirementsId') != requirements_id
            or prepared.get('libraryFingerprint') != library_fingerprint(equipment)
            or prepared.get('historyFingerprint') != current_history
            or prepared.get('sourceMessages') != source_message_context(requirement_sources(messages))
            or prepared.get('preparationId') != workers.get('preparationId')
            or prepared.get('baseDraftId') != workers.get('baseDraftId')):
        return None
    seed_sessions = prepared.get('sessions')
    if not isinstance(seed_sessions, list) or len(seed_sessions) != len(sessions):
        return None
    filtered_seed_sessions = []
    for source, candidate in zip(seed_sessions, sessions):
        if (source.get('timesCompletedInAWeek') != candidate.get('timesCompletedInAWeek')
                or source.get('trainingDays') != candidate.get('trainingDays')):
            return None
        candidate_ids = {definitions.get(item.get('definition_id'), {}).get('id', item.get('definition_id'))
            for item in candidate.get('exercises', [])}
        exercises = [copy.deepcopy(item) for item in source.get('exercises', [])
            if definitions.get(item.get('definition_id'), {}).get('id', item.get('definition_id'))
                in candidate_ids]
        if not exercises:
            return None
        filtered = copy.deepcopy(source)
        filtered['exercises'] = exercises
        filtered_seed_sessions.append(filtered)
    return filtered_seed_sessions


def _saved_prescription_seeds(messages):
    """Retained source documents are hints only; current native checks still apply."""
    calls = {call.get('id'): call.get('function', {}).get('name')
        for message in messages or [] for call in message.get('tool_calls', [])}
    for message in reversed(messages or []):
        if message.get('role') != 'tool' or calls.get(message.get('tool_call_id')) != 'audit_workout_plan':
            continue
        try:
            receipt = json.loads(message.get('content', '{}'))
        except (ValueError, TypeError):
            continue
        draft = receipt.get('submittedDraft') if isinstance(receipt, dict) else None
        if isinstance(draft, dict) and isinstance(draft.get('workouts'), list):
            yield draft['workouts']


def _prescription_decision_hint(candidate, sessions, day_blocks, variables, requirements, audit):
    """Map an audited source to exact finite recipe choices without fixing them."""
    if len(candidate) != len(sessions):
        return None
    ignored = {'allocationBounds', 'placementNotes', 'superset', 'satisfiesCoverage'}
    item_key = lambda item: {key: value for key, value in item.items() if key not in ignored}
    selected, selected_blocks, reconstructed = {}, [], copy.deepcopy(sessions)
    for day_index, (day, source, blocks) in enumerate(zip(candidate, sessions, day_blocks)):
        if any(day.get(key) != source.get(key) for key in ('timesCompletedInAWeek', 'trainingDays')):
            return None
        used_positions, block_order, items = set(), [], []
        for desired in _blocks([day]):
            match = None
            for block_index, block in enumerate(blocks):
                if block_index in block_order:
                    continue
                for index, option in block['optionValues'].items():
                    recipe = block['optionRecipes'][index]
                    positions = {tuple(position) for position in recipe['sourcePositions']}
                    if positions & used_positions:
                        continue
                    if [item_key(item) for item in desired] == [item_key(item) for item in option['items']]:
                        match = block_index, index, positions
                        break
                if match is not None:
                    break
            if match is None:
                return None
            block_index, option_index, positions = match
            used_positions.update(positions)
            block_order.append(block_index)
            selected[option_index] = 1
        try:
            local_order = execution_order_indices([blocks[index]['recipe']['roles'] for index in block_order],
                [_block_order_key(blocks, index) for index in block_order], requirements)
        except ValueError:
            return None
        block_order = [block_order[index] for index in local_order]
        for block_index in block_order:
            block = blocks[block_index]
            option = next(option for index, option in block['optionValues'].items() if index in selected)
            for item in copy.deepcopy(option['items']):
                item['superset'] = f'HINT_{block_index}' if len(option['items']) > 1 else None
                items.append(item)
        reconstructed[day_index]['exercises'] = items
        selected_blocks.append(block_order)
    if not audit(reconstructed):
        return None
    hint = {index: int(index in selected) for index, variable in enumerate(variables)
        if (variable.get('domainIdentity') or {}).get('kind') == 'recipe_option'}
    for day_index, (blocks, order) in enumerate(zip(day_blocks, selected_blocks)):
        nodes = [0, *(index + 1 for index in order), 0]
        edges = set(zip(nodes, nodes[1:])) | {(index + 1, index + 1)
            for index in range(len(blocks)) if index not in order}
        for index, variable in enumerate(variables):
            identity = variable.get('domainIdentity') or {}
            if identity.get('workoutIndex') != day_index:
                continue
            kind = identity.get('kind')
            if kind == 'execution_arc':
                hint[index] = int((identity['tail'], identity['head']) in edges)
            elif kind in ('execution_presence', 'execution_rank', 'execution_set_count'):
                block_index = identity['blockIndex']
                if kind == 'execution_presence':
                    hint[index] = int(block_index in order)
                elif kind == 'execution_rank':
                    hint[index] = order.index(block_index) + 1 if block_index in order else 0
                else:
                    hint[index] = next((option['count'] for option_index, option in blocks[block_index]['optionValues'].items()
                        if option_index in selected), 0)
            elif kind == 'first_block':
                hint[index] = int(bool(order) and blocks[order[0]]['first'] == index)
            elif kind == 'execution_before':
                before, after = identity['before'], identity['after']
                hint[index] = int(before in order and after in order and order.index(before) < order.index(after))
    return hint


def _repair_candidate_binding(messages, candidate_id):
    calls = {call.get('id'): call.get('function', {})
             for message in messages or [] for call in message.get('tool_calls', [])}
    diagnosed = []
    for index, message in enumerate(messages or []):
        if calls.get(message.get('tool_call_id'), {}).get('name') != 'propose_workout_alternatives':
            continue
        try:
            payload = json.loads(message.get('content', ''))
        except (TypeError, ValueError):
            continue
        for candidate in payload.get('alternativeRepairCandidates', []):
            if candidate.get('repairCandidateId') == candidate_id:
                return candidate
            diagnosed.append((index, candidate))
    # A failed independent review creates a new materialized revision ID. Resolve
    # it through the same validated lineage authority used by planner resumption.
    from .alternative_repair import _latest_materialized_reviewed_candidate
    for index, candidate in reversed(diagnosed):
        materialized = _latest_materialized_reviewed_candidate(messages, candidate, after_index=index)
        if materialized and materialized.get('repairCandidateId') == candidate_id:
            return materialized
    return None


def _current_repair_identity(messages):
    for message in reversed(messages or []):
        if message.get('role') != 'assistant':
            continue
        for call in reversed(message.get('tool_calls', [])):
            function = call.get('function', {})
            if function.get('name') != 'repair_workout_alternative':
                continue
            try:
                arguments = json.loads(function.get('arguments', '{}'))
            except (TypeError, ValueError):
                continue
            candidate_id = arguments.get('repairCandidateId')
            source_candidate = _repair_candidate_binding(messages, candidate_id)
            if not source_candidate:
                continue
            expected_original = arguments.get('originalRequirementsId')
            if expected_original != source_candidate.get('originalRequirementsId'):
                continue
            return source_candidate
    return None


def _known_infeasible_repair_domain(messages, domain_fingerprint,
                                    library_hash, history_fingerprint):
    """Find a proven prior repair-domain failure for this exact candidate authority."""
    source_candidate = _current_repair_identity(messages)
    if not source_candidate:
        return None
    calls = {call.get('id'): call.get('function', {})
             for message in messages or [] for call in message.get('tool_calls', [])}
    for index in reversed(range(len(messages or []))):
        message = messages[index]
        if calls.get(message.get('tool_call_id'), {}).get('name') != 'repair_workout_alternative':
            continue
        try:
            result = json.loads(message.get('content', ''))
        except (TypeError, ValueError):
            continue
        receipt = result.get('jointSolve') if isinstance(result, dict) else None
        snapshot = result.get('candidateSnapshot') if isinstance(result, dict) else None
        if (not isinstance(receipt, dict) or receipt.get('status') != 'infeasible'
                or result.get('attemptStatus') != 'repair_menu_infeasible'
                or receipt.get('rejectedOptions')
                or not isinstance(snapshot, dict)):
            continue
        bound_keys = ('repairCandidateId', 'originalRequirementsId', 'originalRequirementsHash',
                      'requirementsId', 'sourceDraftId', 'sourceMenuFingerprint',
                      'libraryFingerprint', 'trainingHistoryFingerprint')
        if any(snapshot.get(key, snapshot.get('baseDraftId') if key == 'sourceDraftId' else None)
               != source_candidate.get(key, source_candidate.get('baseDraftId') if key == 'sourceDraftId' else None)
               for key in bound_keys):
            continue
        if (result.get('repairCandidateId') != source_candidate.get('repairCandidateId')
                or result.get('originalRequirementsId') != source_candidate.get('originalRequirementsId')
                or result.get('requirementsId') != source_candidate.get('requirementsId')
                or result.get('libraryFingerprint') != library_hash
                or result.get('trainingHistoryFingerprint') != history_fingerprint):
            continue
        prior_domain = receipt.get('feasibilityDomainFingerprint')
        prior_policy = receipt.get('selectionPolicyVersion')
        if (prior_domain and prior_domain == domain_fingerprint
                and prior_policy == SELECTION_POLICY_VERSION
                and receipt.get('preserveSourceSelection') is True):
            return {'receipt': copy.deepcopy(receipt), 'sourceResultIndex': index,
                    'match': 'generated_model_domain'}
    return None


def _priority_execution(approved_order, objective_costs, stages, goal_names, balance_rules,
                        demand_evidence_status='unavailable', development_roles=(),
                        development_budget=None, execution_selection=None,
                        volume_target_evidence_status='available'):
    """Expose the owner and actual solver outcome for approved soft priorities."""
    stage_by_goal = {stage['goal']: stage for stage in stages}
    solver_owners = {'execution_order': 'joint_solver', 'time_budget': 'joint_solver',
                     'exercise_count': 'joint_solver',
                     'source_balance': 'joint_solver', 'distribution': 'joint_solver', 'role_concentration': 'joint_solver', 'duration_balance': 'joint_solver',
                     'demand_distribution': 'joint_solver', 'development_emphasis': 'joint_solver',
                     'development_exposure': 'joint_solver',
                     'workload_economy': 'joint_solver', 'volume_target': 'joint_solver', 'setup_economy': 'joint_solver',
                     'duration_economy': 'joint_solver', 'movement_overlap': 'joint_solver',
                     'exercise_distribution': 'joint_solver', 'execution_complementarity': 'joint_solver',
                     'balance_control': 'joint_solver', 'preservation': 'joint_solver'}
    priorities = []
    priority_statuses = {}
    development_stage = next((stage for stage in stages if stage.get('goal') == 'development_emphasis'), None)
    development_exposure_stage = next((stage for stage in stages
        if stage.get('goal') == 'development_exposure'), None)
    development_exposure_planned = 'development_exposure' in goal_names
    development_exposure_status = (development_exposure_stage.get('status')
        if development_exposure_stage else
        'not_run_after_solver_stop' if development_exposure_planned else
        'no_applicable_options' if 'development_exposure' in (approved_order or []) else 'not_requested')
    if development_exposure_stage and development_exposure_status in (
            'optimal', 'optimal_zero_lower_bound'):
        exposure_position = goal_names.index('development_exposure')
        for preceding in goal_names[:exposure_position]:
            preceding_stage = next((stage for stage in stages
                if stage.get('goal') == preceding), None)
            if preceding_stage:
                if preceding_stage.get('status') not in ('optimal', 'optimal_zero_lower_bound'):
                    development_exposure_status = 'feasible'
                    break
            elif preceding == 'demand_distribution' and demand_evidence_status != 'available':
                development_exposure_status = 'feasible'
                break
            elif any(objective_costs.get(preceding, {}).values()):
                development_exposure_status = 'feasible'
                break
    development_goal_position = (goal_names.index('development_emphasis')
        if 'development_emphasis' in goal_names else None)
    development_preceding_priorities = (goal_names[:development_goal_position]
        if development_goal_position is not None else [])
    if 'demand_distribution' in (approved_order or []) and 'demand_distribution' not in goal_names:
        development_preceding_priorities = ['demand_distribution', *development_preceding_priorities]
    development_status = (development_budget.get('status') if development_budget
        and development_budget.get('status') in ('source_budget_conflict_requires_review',
            'source_budget_unproven_requires_review', 'hard_infeasible', 'hard_feasibility_unproven')
        else development_stage.get('status') if development_stage
        else 'not_requested' if 'development_emphasis' not in (approved_order or []) else 'not_run')
    if development_stage and development_stage.get('status') in (
            'optimal', 'optimal_zero_lower_bound', 'feasible'):
        for preceding in development_preceding_priorities:
            preceding_stage = next((stage for stage in stages if stage.get('goal') == preceding), None)
            if preceding_stage and preceding_stage.get('status') not in ('optimal', 'optimal_zero_lower_bound'):
                development_status = 'feasible'
                break
            if preceding == 'demand_distribution' and demand_evidence_status != 'available':
                development_status = 'feasible'
                break
            if (preceding_stage is None and preceding != 'progression'
                    and any(objective_costs.get(preceding, {}).values())):
                development_status = 'feasible'
                break
        if development_exposure_planned and development_exposure_status not in (
                'optimal', 'optimal_zero_lower_bound'):
            development_status = 'feasible'
    for position, priority in enumerate(approved_order or []):
        owner = ('movement_selection_and_review' if priority == 'progression'
                 else solver_owners[priority])
        stage = stage_by_goal.get(priority)
        if priority == 'execution_order':
            planned = [name for name in goal_names if name.startswith('ordering_')]
            completed = [stage_by_goal[name] for name in planned if name in stage_by_goal]
            stage = ({'status': ('optimal' if all(item['status'] in ('optimal', 'optimal_zero_lower_bound')
                for item in completed) else 'feasible')
                if len(completed) == len(planned) else 'not_run_after_solver_stop',
                'value': {item['goal']: item.get('value') for item in completed}}
                if planned else {'status': 'unavailable_evidence'})
        if priority == 'progression':
            status = 'outside_joint_solver'
        elif stage:
            status = stage['status']
        elif priority == 'volume_target' and volume_target_evidence_status == 'unavailable_evidence':
            status = 'unavailable_evidence'
        elif priority == 'demand_distribution' and demand_evidence_status == 'unavailable':
            status = 'unavailable_evidence'
        elif priority == 'demand_distribution' and not any(objective_costs[priority].values()):
            status = 'no_positive_exposure'
        elif priority == 'balance_control' and execution_selection:
            status = execution_selection.get('balanceControl', {}).get('status', 'unavailable_evidence')
        elif priority == 'execution_complementarity' and execution_selection:
            status = execution_selection.get('complementarity', {}).get('status', 'unavailable_evidence')
        elif priority == 'exercise_count' and not objective_costs[priority]:
            status = 'unavailable_evidence'
        elif not any(objective_costs[priority].values()):
            status = 'no_applicable_options'
        elif priority in goal_names:
            status = 'not_run_after_solver_stop'
        else:
            status = 'not_run'
        if stage and status in ('optimal', 'optimal_zero_lower_bound'):
            prefix_proven = True
            for preceding in (approved_order or [])[:position]:
                if preceding == 'progression':
                    continue
                preceding_status = priority_statuses.get(preceding)
                if preceding_status is not None:
                    if preceding_status not in ('optimal', 'optimal_zero_lower_bound', 'no_applicable_options'):
                        prefix_proven = False
                        break
                    continue
                prior_stage = stage_by_goal.get(preceding)
                if prior_stage:
                    if prior_stage.get('status') not in ('optimal', 'optimal_zero_lower_bound'):
                        prefix_proven = False
                        break
                elif preceding == 'demand_distribution':
                    if demand_evidence_status != 'available':
                        prefix_proven = False
                        break
                elif any(objective_costs.get(preceding, {}).values()):
                    prefix_proven = False
                    break
            if not prefix_proven:
                status = 'feasible'
            if priority == 'distribution':
                worst_stage = stage_by_goal.get('distribution_worst')
                if worst_stage and worst_stage.get('status') not in ('optimal', 'optimal_zero_lower_bound'):
                    status = 'feasible'
            if priority == 'role_concentration':
                tie_break_stage = stage_by_goal.get('role_concentration_tiebreak')
                if ('role_concentration_tiebreak' in goal_names
                        and (not tie_break_stage or tie_break_stage.get('status') not in (
                            'optimal', 'optimal_zero_lower_bound'))):
                    status = 'feasible'
            if (development_goal_position is not None
                    and priority in goal_names
                    and development_goal_position < goal_names.index(priority)
                    and development_status not in ('optimal', 'optimal_zero_lower_bound')):
                status = 'feasible'
            if priority == 'exercise_distribution' and 'exercise_distribution_development' in goal_names:
                development_family_stage = stage_by_goal.get('exercise_distribution_development')
                if not development_family_stage or development_family_stage.get('status') not in (
                        'optimal', 'optimal_zero_lower_bound'):
                    status = 'feasible'
        priority_statuses[priority] = status
        priority_entry = {'priority': priority, 'owner': owner, 'status': status,
            'solverStage': copy.deepcopy(stage) if stage else None}
        if priority == 'movement_overlap' and 'superset_lower_body_overlap' in goal_names:
            paired_stage = stage_by_goal.get('superset_lower_body_overlap')
            priority_entry['subStages'] = [copy.deepcopy(paired_stage) if paired_stage else {
                'goal': 'superset_lower_body_overlap', 'status': 'not_run_after_solver_stop'}]
            priority_entry['interpretation'] = ('Repeated paired sets from two major lower-body movements; '
                'an exposure preference, not a fatigue prediction or hard cap.')
            if not paired_stage or paired_stage.get('status') not in ('optimal', 'optimal_zero_lower_bound'):
                priority_entry['status'] = 'feasible' if stage else status
                priority_statuses[priority] = priority_entry['status']
        if priority == 'distribution':
            sub_stages = []
            for name in ('distribution_worst', 'distribution'):
                sub_stage = stage_by_goal.get(name)
                if sub_stage is None:
                    sub_stage = {'goal': name, 'status': ('not_run_after_solver_stop'
                        if name in goal_names else 'not_requested'), 'planned': name in goal_names}
                sub_stages.append(sub_stage)
            priority_entry['subStages'] = copy.deepcopy(sub_stages)
        if priority == 'role_concentration':
            tie_break_stage = stage_by_goal.get('role_concentration_tiebreak')
            if tie_break_stage is None and 'role_concentration_tiebreak' in goal_names:
                tie_break_stage = {'goal': 'role_concentration_tiebreak',
                    'status': 'not_run_after_solver_stop', 'planned': True}
            priority_entry['subStages'] = ([copy.deepcopy(tie_break_stage)]
                if tie_break_stage else [])
        priorities.append(priority_entry)

    balance_stage = stage_by_goal.get('source_balance')
    balance_approved = 'source_balance' in (approved_order or [])
    if balance_approved:
        balance_status = (priority_statuses.get('source_balance', balance_stage['status']) if balance_stage else
            'no_applicable_options' if not any(objective_costs['source_balance'].values()) else
            'not_run_after_solver_stop' if 'source_balance' in goal_names else 'not_run')
    else:
        balance_status = 'semantic_review_required'
    balances = [{'kind': 'coverageBalance', 'first': rule['first'], 'second': rule['second'],
                 'scope': rule['scope'],
                 **({'relationship': rule['relationship']} if 'relationship' in rule else {}),
                 'owner': 'joint_solver' if balance_approved else 'semantic_review',
                 'status': balance_status,
                 'solverStage': copy.deepcopy(balance_stage) if balance_stage else None}
                for rule in balance_rules]
    development = {'owner': 'joint_solver', 'policy': JOINT_POLICY_DESCRIPTOR['developmentEmphasis'],
        'status': development_status,
        'source': 'approved requiredCoverage entries with intent=development',
        'roleKeys': sorted(development_roles),
        'comparison': 'maximize the minimum weekly raw working-set exposure across development roles',
        'unit': 'weekly_raw_working_sets',
        'minimumWeeklyWorkingSets': None,
        'roleWeeklyWorkingSets': None,
        'optimizationStageMinimumWeeklyWorkingSets': (
            development_stage.get('value') if development_stage else None),
        'optimizationStageRoleWeeklyWorkingSets': (
            copy.deepcopy(development_stage.get('roleWeeklyWorkingSets'))
            if development_stage else None),
        'combinedExposure': {
            'status': development_exposure_status,
            'weeklyWorkingSets': (development_exposure_stage.get('value')
                if development_exposure_stage else sum(
                    (development_stage or {}).get('roleWeeklyWorkingSets', {}).values())),
            'roleWeeklyWorkingSets': copy.deepcopy(
                development_exposure_stage.get('roleWeeklyWorkingSets')
                if development_exposure_stage else
                (development_stage or {}).get('roleWeeklyWorkingSets')),
            'unit': 'sum_of_weekly_qualified_role_working_sets',
            'solverStage': copy.deepcopy(development_exposure_stage),
        },
        'solverStage': copy.deepcopy(development_stage),
        'sourceBudget': copy.deepcopy(development_budget),
        'scope': ('Qualified executable recipes in the supplied finite menu, under approved hard constraints and the recorded source weekly set budget. '
                  'A solver score describes the selected tags; it does not establish accurate role classification, adequate stimulus, '
                  'exercise capability, or physiological suitability.')}
    return {'approvedPriorities': priorities, 'coverageBalance': balances,
            'developmentEmphasis': development}


def _finalize_development_exposure(priority_execution, weekly_coverage_sets):
    """Report selected exposure from the final audited plan, separately from the stage snapshot."""
    development = priority_execution.get('developmentEmphasis') or {}
    role_keys = development.get('roleKeys') or []
    if not role_keys:
        return
    role_totals = {role: weekly_coverage_sets.get(role, 0) for role in role_keys}
    development['roleWeeklyWorkingSets'] = role_totals
    development['minimumWeeklyWorkingSets'] = min(role_totals.values(), default=0)
    development['finalExposureSource'] = 'final_production_audit'


def _attach_concentration_substage(priority_execution, priority, stage):
    if not stage:
        return
    item = next((entry for entry in priority_execution.get('approvedPriorities', [])
        if entry.get('priority') == priority), None)
    if item is None:
        return
    item.setdefault('subStages', []).append(copy.deepcopy(stage))
    if (stage.get('status') not in ('optimal', 'optimal_zero_lower_bound')
            and item.get('status') in ('optimal', 'optimal_zero_lower_bound')):
        item['status'] = 'feasible'


def _add_peak_surplus_objective(variable, constraint, option_variables, sessions, profiles, kind,
                                profile_index_offset=0):
    """Minimize the worst per-occasion peak surplus across source-backed profiles."""
    fixed_frequencies = profiles[0]['fixedFrequencies'] if profiles else []
    total_frequency = sum(day.get('timesCompletedInAWeek', 1) for day in sessions) + sum(fixed_frequencies)
    if not total_frequency or not profiles:
        return None
    upper = 0
    for profile in profiles:
        for day_index in range(len(sessions)):
            upper = max(upper, total_frequency * sum(
                profile['exposureByOption'].get(index, 0)
                for index, variable_day, _, _ in option_variables if variable_day == day_index))
        upper = max(upper, total_frequency * max(profile['fixedExposures'], default=0))
    peak = variable(upper=upper, integer=False, domain_identity={'kind': kind})
    for local_profile_index, profile in enumerate(profiles):
        profile_index = profile_index_offset + local_profile_index
        fixed_weekly = sum(exposure * frequency for exposure, frequency in zip(
            profile['fixedExposures'], profile['fixedFrequencies']))
        for day_index in range(len(sessions)):
            coefficients = {index: total_frequency * profile['exposureByOption'].get(index, 0)
                for index, variable_day, _, _ in option_variables
                if variable_day == day_index and profile['exposureByOption'].get(index, 0)}
            for index, variable_day, _, _ in option_variables:
                exposure = profile['exposureByOption'].get(index, 0)
                if exposure:
                    coefficients[index] = coefficients.get(index, 0) - sessions[variable_day].get(
                        'timesCompletedInAWeek', 1) * exposure
            coefficients[peak] = -1
            constraint((kind, profile_index, 'session', day_index), -math.inf, 0,
                coefficients, -fixed_weekly)
        for workout_index, (exposure, frequency) in enumerate(zip(
                profile['fixedExposures'], profile['fixedFrequencies'])):
            coefficients = {index: -sessions[day_index].get('timesCompletedInAWeek', 1)
                * profile['exposureByOption'].get(index, 0)
                for index, day_index, _, _ in option_variables
                if profile['exposureByOption'].get(index, 0)}
            coefficients[peak] = -1
            constraint((kind, profile_index, 'fixed', workout_index), -math.inf, 0,
                coefficients, total_frequency * exposure - fixed_weekly)
    return peak


def _peak_surplus_value(chosen, profile, option_variables, sessions):
    total_frequency = sum(day.get('timesCompletedInAWeek', 1) for day in sessions) + sum(
        profile['fixedFrequencies'])
    fixed_weekly = sum(exposure * frequency for exposure, frequency in zip(
        profile['fixedExposures'], profile['fixedFrequencies']))
    weekly = fixed_weekly + sum(sessions[day].get('timesCompletedInAWeek', 1)
        * profile['exposureByOption'].get(index, 0) * chosen[index]
        for index, day, _, _ in option_variables)
    per_session = [sum(profile['exposureByOption'].get(index, 0) * chosen[index]
        for index, day, _, _ in option_variables if day == session_index)
        for session_index in range(len(sessions))]
    per_session.extend(profile['fixedExposures'])
    return max([0, *(total_frequency * value - weekly for value in per_session)]) / total_frequency


def _add_peak_session_exposure_objective(variable, constraint, option_variables, sessions,
                                         profile, kind):
    """Minimize the maximum unique prescribed sets in any one session occurrence."""
    per_day = [{index: profile['exposureByOption'].get(index, 0)
        for index, day, _, _ in option_variables if day == day_index
        and profile['exposureByOption'].get(index, 0)} for day_index in range(len(sessions))]
    upper = max([0, *(sum(values.values()) for values in per_day),
        *profile['fixedExposures']])
    peak = variable(upper=upper, integer=False, domain_identity={'kind': kind})
    for day_index, coefficients in enumerate(per_day):
        constraint((kind, 'session', day_index), -math.inf, 0, {**coefficients, peak: -1})
    for workout_index, exposure in enumerate(profile['fixedExposures']):
        constraint((kind, 'fixed', workout_index), -math.inf, 0, {peak: -1}, exposure)
    return peak


def _peak_session_exposure_value(chosen, profile, option_variables, sessions):
    per_day = [sum(profile['exposureByOption'].get(index, 0) * chosen[index]
        for index, day, _, _ in option_variables if day == day_index)
        for day_index in range(len(sessions))]
    return max([0, *per_day, *profile['fixedExposures']])


def _lock_weekly_training_doses(features, chosen, option_variables, sessions, required_roles, muscles):
    """Settle training doses while leaving qualified exercise identities selectable."""
    physical = {index: option['count'] * len(option['items']) * sessions[day]['timesCompletedInAWeek']
        for index, day, _, option in option_variables}
    doses = {('physical_sets',): physical}
    doses.update({('coverage', role): coefficients for role, coefficients in
        _weekly_role_dose_coefficients(option_variables, sessions, required_roles).items()})
    for muscle in muscles:
        doses[('muscle', muscle)] = {index: option['volume'].get(muscle, {}).get('effective', 0)
            * sessions[day]['timesCompletedInAWeek'] for index, day, _, option in option_variables}
    for label, coefficients in doses.items():
        target = sum(value * chosen[index] for index, value in coefficients.items())
        features.append((('training_dose_conservation', *label), target, target, 0, coefficients))


def _lock_source_balance_doses(features, chosen, option_variables, sessions, requirements, base_report):
    locked = []
    for component_index, component in enumerate(source_balance_dose_components(requirements)):
        roles, scope = component['roles'], component['scope']
        weekly = scope == 'weekly'
        combined = []
        for day_index in ([None] if weekly else range(len(sessions))):
            coefficients = {index: sum(option['coverage'].get(role, 0) for role in roles)
                * (sessions[day]['timesCompletedInAWeek'] if weekly else 1)
                for index, day, _, option in option_variables if weekly or day == day_index}
            target = sum(value * chosen[index] for index, value in coefficients.items())
            # Fixed physical workload may exchange isolation work for more balanced compounds.
            upper = math.inf if selection_precedes_execution(requirements) else target
            features.append((('source_balance_dose_conservation', component_index, day_index),
                target, upper, 0, coefficients))
            combined.append(target + (sum((base_report or {}).get('weeklyCoverageSets', {}).get(role, 0)
                for role in roles) if weekly else 0))
        locked.append({'scope': scope, 'roles': roles, 'combinedWorkingSetExposure': combined})
    return locked


def _lock_selected_session_work(features, chosen, option_variables, sessions, definitions):
    selected = []
    for day_index in range(len(sessions)):
        by_definition = {}
        for index, day, _, option in option_variables:
            if day != day_index:
                continue
            for item in option['items']:
                identifier = definitions[item['definition_id']]['id']
                coefficients = by_definition.setdefault(identifier, {})
                coefficients[index] = coefficients.get(index, 0) + option['count']
        counts = {}
        for identifier, coefficients in by_definition.items():
            target = sum(value * chosen[index] for index, value in coefficients.items())
            features.append((('execution_selected_work', day_index, identifier), target, target, 0, coefficients))
            if target:
                counts[identifier] = target
        selected.append(dict(sorted(counts.items())))
    return selected


def _demand_distribution_summary(workouts, fixed_workouts, demand_inputs, definitions,
                                 objective_stage=None, objective_requested=False,
                                 fixed_unavailable_groups=None):
    """Report verified set exposure without treating missing tags as zero."""
    id_by_reference = {reference: definition['id'] for reference, definition in definitions.items()}
    id_by_reference.update({definition['id']: definition['id'] for definition in definitions.values()})
    groups = []
    all_workouts = [*(fixed_workouts or []), *(workouts or [])]
    for key, group in sorted(demand_inputs.get('groups', {}).items()):
        present_ids = set(group.get('presentDefinitionIds', []))
        session_exposure = []
        for index, day in enumerate(all_workouts):
            sets = sum(item.get('numWorkSets', 0) for item in day.get('exercises', [])
                if id_by_reference.get(item.get('definition_id')) in present_ids)
            frequency = day.get('timesCompletedInAWeek', 1)
            session_exposure.append({'workoutIndex': index, 'sessionName': day.get('name'),
                'sessionExposureSets': sets, 'timesCompletedInAWeek': frequency,
                'weeklyExposureSets': sets * frequency})
        groups.append({'key': key, 'label': group.get('label'),
            'presentDefinitionIds': sorted(present_ids),
            'evidenceByDefinition': copy.deepcopy(group.get('evidenceByDefinition', {})),
            'sessionExposureSets': session_exposure,
            'weeklyExposureSets': sum(item['weeklyExposureSets'] for item in session_exposure),
            'peakSessionExposureSets': max((item['sessionExposureSets'] for item in session_exposure), default=0)})

    evidence_status = demand_inputs.get('status', 'unavailable')
    unavailable_groups = copy.deepcopy(demand_inputs.get('unavailableGroups', {}))
    fixed_unknown = bool(fixed_unavailable_groups)
    if fixed_unknown:
        status = 'partial_fixed_evidence'
    elif evidence_status == 'unavailable':
        status = 'unavailable'
    elif unavailable_groups:
        status = 'partial_evidence'
    elif objective_stage:
        status = objective_stage['status']
    elif objective_requested:
        status = 'no_positive_exposure'
    else:
        status = 'available_not_optimized'
    optimization_status = ((
        'optimal_for_known_fixed_exposure_with_fixed_unknowns'
        if fixed_unknown and objective_stage['status'] == 'optimal' else
        'feasible_for_known_fixed_exposure_with_fixed_unknowns'
        if fixed_unknown else objective_stage['status']) if objective_stage else
        'not_requested' if not objective_requested else
        'not_run_fixed_unknowns' if fixed_unknown else
        'unavailable_evidence' if evidence_status == 'unavailable' else 'no_positive_exposure')
    return {'status': status, 'evidenceStatus': evidence_status,
        'optimizationStatus': optimization_status, 'groups': groups,
        'unavailableGroups': unavailable_groups,
        'fixedUnavailableGroups': copy.deepcopy(fixed_unavailable_groups or {}),
        'fixedEvidenceStatus': 'partial' if fixed_unavailable_groups else 'available',
        'proofScope': ('Counts only the supplied candidate recipes and fixed existing workouts with reviewed library tags. '
            'Only demand groups fully classified across the selectable recipes enter the objective; when other groups are '
            'unknown, any solver optimum is conditional on the listed known groups and says nothing about the unknown groups. '
            'When fixed tags are unknown, the optimum applies only to known fixed exposure and is not a complete-week optimum; '
            'unknown fixed definitions are listed separately and do not disable the variable-menu evidence gate. '
            'Working-set exposure is not a fatigue score, tolerance estimate, or personal-suitability finding.')}


def joint_objective_input_fingerprint(sessions, requirements, equipment, history=None, messages=None,
                                      *, restriction_policy=None, allow_educated_load_guesses=True,
                                      preserve_source_selection=False, redistribution_constraints=None,
                                      source_working_set_budget=None,
                                      reviewed_baseline_workouts=None):
    """Bind reusable solver work to the prescription/objective, ignoring only within-session order and display metadata."""
    from .planning_tools import AUDIT_VERSION, library_fingerprint
    from .planning_decisions import _active_reusable_decision_state, resolved_decisions

    library_hash = library_fingerprint(equipment)
    canonical_sessions = []
    for day in sessions:
        blocks = [block for block in _blocks([day])]
        blocks.sort(key=lambda block: json.dumps(block, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        # Setup time depends on the first block. Preserve it in the identity even
        # though the rest of the submitted order is irrelevant to these objectives.
        first_block = (next(_blocks([day]), [])
            if requirements.get('auditTargets', {}).get('maximumSessionSeconds') is not None else None)
        canonical_sessions.append({'timesCompletedInAWeek': day['timesCompletedInAWeek'],
            'firstBlock': first_block,
            'blocks': blocks})
    payload = {'requirements': requirements, 'objectiveInput': canonical_sessions,
        'libraryFingerprint': library_hash, 'historyFingerprint': getattr(history, 'fingerprint', None),
        'recordedEvidencePolicyVersion': RECORDED_EVIDENCE_POLICY_VERSION,
        'recordedEvidence': _selected_recorded_evidence(
            messages or [], library_hash, getattr(history, 'fingerprint', None), equipment, sessions),
        'selectionPolicyVersion': SELECTION_POLICY_VERSION, 'auditVersion': AUDIT_VERSION,
        'jointPolicy': JOINT_POLICY_DESCRIPTOR,
        'exerciseFamilyEvidence': reviewed_exercise_family_evidence(equipment),
        'executionProperties': reviewed_execution_properties(equipment),
        'sourceWorkingSetBudget': _source_working_set_budget_identity(sessions, source_working_set_budget),
        'reviewedDoseReference': _reviewed_dose_reference_identity(reviewed_baseline_workouts),
        'preserveSourceSelection': bool(preserve_source_selection),
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': allow_educated_load_guesses}
    decisions = _active_reusable_decision_state(resolved_decisions(messages or []))
    if decisions:
        payload['resolvedPlanningDecisions'] = decisions
    if redistribution_constraints:
        payload['redistributionConstraints'] = copy.deepcopy(redistribution_constraints)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

_DRAFT_VALIDATOR = Draft7Validator(_DRAFT_SCHEMA)


def _blocks(sessions, standalone=False):
    for block, _ in _blocks_with_source_positions(sessions, standalone=standalone):
        yield block


def _blocks_with_source_positions(sessions, standalone=False):
    seen = {}
    for workout_index, day in enumerate(sessions):
        occurrences = {}
        for _, members in itertools.groupby(enumerate(day['exercises']),
                lambda entry: ('group', entry[1]['superset']) if entry[1]['superset'] is not None
                    else ('single', entry[0])):
            entries = list(members)
            positions = [(workout_index, index) for index, _ in entries]
            block = copy.deepcopy([item for _, item in entries])
            for item in block:
                item['superset'] = 'RECIPE' if len(block) > 1 else None
            key = json.dumps(block, sort_keys=True)
            occurrences[key] = occurrences.get(key, 0) + 1
            if occurrences[key] <= seen.get(key, 0):
                continue
            seen[key] = occurrences[key]
            yield block, positions
            if standalone and len(block) > 1:
                # Proposed pairing is optional; retain round recovery before applying approved straight-set ranges.
                recovery = sum(item['restAfterSupersetExerciseSeconds'] for item in block)
                for item, position in zip(block, positions):
                    single = copy.deepcopy(item)
                    single.update(superset=None, restBetweenSetsSeconds=recovery,
                                  restAfterSupersetExerciseSeconds=0)
                    yield [single], [position]


def prescription_patch(before, after, occurrence_lineage=None):
    """Create a patch that reproduces the solver result."""
    if occurrence_lineage is not None:
        return _lineage_prescription_patch(before, after, occurrence_lineage)
    patch = []
    for day_index, (old, new) in enumerate(zip(before, after)):
        for field in ('name', 'description'):
            if old.get(field) != new.get(field):
                patch.append({'op': 'replace', 'path': f'/workouts/{day_index}/{field}', 'value': new[field]})
        path = f'/workouts/{day_index}/exercises'
        if [e['definition_id'] for e in old['exercises']] != [e['definition_id'] for e in new['exercises']]:
            patch.extend({'op': 'remove', 'path': f'{path}/{i}'} for i in reversed(range(len(old['exercises']))))
            patch.extend({'op': 'add', 'path': path + '/-', 'value': copy.deepcopy(item)} for item in new['exercises'])
            continue
        for index, (a, b) in enumerate(zip(old['exercises'], new['exercises'])):
            for key in sorted(a.keys() | b.keys()):
                field = f'{path}/{index}/{key}'
                if key not in b:
                    patch.append({'op': 'remove', 'path': field})
                elif key not in a or a[key] != b[key]:
                    patch.append({'op': 'replace' if key in a else 'add', 'path': field, 'value': copy.deepcopy(b[key])})
    return patch


def _lineage_prescription_patch(before, after, occurrence_lineage):
    if len(after) != len(before) or len(occurrence_lineage) != len(after):
        raise ValueError('Solver occurrence lineage does not match the submitted workout schedule.')
    source_tokens = {(workout, exercise) for workout, day in enumerate(before)
                     for exercise in range(len(day['exercises']))}
    retained, patch = set(), []
    for workout, (day, solved, lineage) in enumerate(zip(before, after, occurrence_lineage)):
        if len(solved['exercises']) != len(lineage):
            raise ValueError('Solver occurrence lineage does not match the solved exercise list.')
        for solved_index, source in enumerate(lineage):
            if source is None:
                continue
            token = tuple(source)
            if token not in source_tokens or token in retained:
                raise ValueError('Solver occurrence lineage contains a missing or repeated source occurrence.')
            retained.add(token)
            source_workout, source_index = token
            original = before[source_workout]['exercises'][source_index]
            solved_item = solved['exercises'][solved_index]
            if original['definition_id'] != solved_item['definition_id']:
                raise ValueError('Solver occurrence lineage changes an exercise definition.')
            for key in sorted(original.keys() | solved_item.keys()):
                field = f'/workouts/{source_workout}/exercises/{source_index}/{key}'
                if key not in solved_item:
                    patch.append({'op': 'remove', 'path': field})
                elif key not in original or original[key] != solved_item[key]:
                    patch.append({'op': 'replace' if key in original else 'add', 'path': field,
                                  'value': copy.deepcopy(solved_item[key])})
        for field in ('name', 'description', 'trainingDays', 'timesCompletedInAWeek'):
            if day.get(field) != solved.get(field):
                patch.append({'op': 'replace', 'path': f'/workouts/{workout}/{field}',
                              'value': copy.deepcopy(solved.get(field))})

    tokens_by_workout = [[(workout, index) for index in range(len(day['exercises']))]
                         for workout, day in enumerate(before)]
    for workout in range(len(tokens_by_workout)):
        for index in reversed(range(len(tokens_by_workout[workout]))):
            if tokens_by_workout[workout][index] not in retained:
                patch.append({'op': 'remove', 'path': f'/workouts/{workout}/exercises/{index}'})
                tokens_by_workout[workout].pop(index)

    for workout, (solved, lineage) in enumerate(zip(after, occurrence_lineage)):
        for index, source in enumerate(lineage):
            if source is None:
                patch.append({'op': 'add', 'path': f'/workouts/{workout}/exercises/{index}',
                              'value': copy.deepcopy(solved['exercises'][index])})
                tokens_by_workout[workout].insert(index, None)
                continue
            token = tuple(source)
            source_workout = next((i for i, tokens in enumerate(tokens_by_workout) if token in tokens), None)
            if source_workout is None:
                raise ValueError('Solver occurrence lineage lost a retained source occurrence.')
            source_index = tokens_by_workout[source_workout].index(token)
            if source_workout != workout or source_index != index:
                patch.append({'op': 'move', 'from': f'/workouts/{source_workout}/exercises/{source_index}',
                              'path': f'/workouts/{workout}/exercises/{index}'})
                tokens_by_workout[source_workout].pop(source_index)
                tokens_by_workout[workout].insert(index, token)
    return patch


def _rest_options(block, requirements, definitions, work_set_count):
    """Only explicit approved ranges authorize automatic rest changes."""
    yield block
    minimum = copy.deepcopy(block)
    for index, item in enumerate(minimum):
        context = 'straightSets' if len(block) == 1 else (
            'supersetRound' if index == len(block) - 1 else 'supersetTransition')
        rules = [rule for rule in requirements.get('executionRules', []) if rule['kind'] == 'rest'
            and rule['context'] == context
            and (context == 'supersetTransition' or work_set_count > 1)
            and (rule['coverageKey'] is None or rule['coverageKey'] in item.get('satisfiesCoverage', []))
            and (not rule.get('exerciseCategory')
                 or rule['exerciseCategory'] == definitions[item['definition_id']].get('exerciseCategory'))]
        if rules:
            lower = max(rule['minimumSeconds'] for rule in rules)
            upper = min(rule['maximumSeconds'] for rule in rules)
            if lower > upper:
                return
            field = 'restBetweenSetsSeconds' if len(block) == 1 else 'restAfterSupersetExerciseSeconds'
            item[field] = lower
    if minimum != block:
        yield minimum


def _recipe_signature(block):
    return json.dumps([{key: value for key, value in item.items() if key not in ('numWorkSets', 'allocationBounds')}
                       for item in block], sort_keys=True)


def _superset_pair_rejection(first, second, definitions, requirements, equipment):
    first_definition = definitions[first['definition_id']]
    second_definition = definitions[second['definition_id']]
    first_roles = set(first.get('satisfiesCoverage', []))
    second_roles = set(second.get('satisfiesCoverage', []))
    families = {ref: definition.get('reviewedExerciseFamily', {}).get('exerciseFamilyId')
        for ref, definition in ((first['definition_id'], first_definition),
                                (second['definition_id'], second_definition))}
    if overlapping_movement_pairs([first, second], families):
        return 'shared_movement_role'
    setup = superset_setup_compatibility(first_definition, second_definition, requirements,
        first_roles, second_roles)
    if setup['status'] == 'incompatible':
        return 'shared_physical_station'
    if setup['status'] == 'unknown' and setup['confirmationRequired']:
        return 'simultaneous_access_unconfirmed'

    first_phase = execution_block_priority([first_definition])
    second_phase = execution_block_priority([second_definition])
    from .programming_policy import execution_order_phase
    if (3 in (first_phase, second_phase) and min(first_phase, second_phase) < 2
            and execution_order_phase(first_phase, requirements) != execution_order_phase(second_phase, requirements)):
        return 'main_work_core_order_conflict'

    for rule in requirements.get('executionRules', []):
        if rule.get('kind') != 'order':
            continue
        before, after = rule['before'], rule['after']
        if ((before in first_roles and after in second_roles)
                or (before in second_roles and after in first_roles)):
            return 'explicit_order_conflict'

    first_primary = {muscle for muscle, tags in MUSCLES.items()
        if tags & set(first_definition.get('muscleGroups', []))}
    second_primary = {muscle for muscle, tags in MUSCLES.items()
        if tags & set(second_definition.get('muscleGroups', []))}
    first_supporting = {muscle for muscle, tags in MUSCLES.items()
        if tags & set(first_definition.get('secondaryMuscleGroups', []))} - first_primary
    second_supporting = {muscle for muscle, tags in MUSCLES.items()
        if tags & set(second_definition.get('secondaryMuscleGroups', []))} - second_primary
    if not first_primary or not second_primary:
        return 'primary_muscle_evidence_unknown'
    if 'secondaryMuscleGroups' not in first_definition or 'secondaryMuscleGroups' not in second_definition:
        return 'supporting_muscle_evidence_unknown'
    if first_primary & second_primary:
        return 'shared_primary_muscle'
    if first_primary & second_supporting or second_primary & first_supporting:
        return 'primary_supporting_muscle_interference'

    equipment_by_id = {item.get('id'): item for item in equipment.get('equipments', [])}
    relation = superset_resource_relation(first_definition, second_definition, equipment_by_id)
    if relation in {'identity_unknown', 'potentially_shared_family', 'same_record'}:
        # Native calibration selects loads per exercise, so it cannot prove a
        # single usable setting for two exercises sharing physical equipment.
        if (first_definition.get('requiresLoadCalibration') or second_definition.get('requiresLoadCalibration')
                or first.get('requiresLoadCalibration') or second.get('requiresLoadCalibration')):
            return 'shared_equipment_load_unverified'
        first_targets = first.get('targetSetPrescriptions') or []
        second_targets = second.get('targetSetPrescriptions') or []
        if not first_targets or len(first_targets) != len(second_targets):
            return 'shared_equipment_load_unverified'
        for a, b in zip(first_targets, second_targets):
            first_load = next(((key, a[key]) for key in ('weight', 'additionalWeight') if key in a), None)
            second_load = next(((key, b[key]) for key in ('weight', 'additionalWeight') if key in b), None)
            if first_load is None or first_load != second_load:
                return 'shared_equipment_load_unverified'
    first_accessories = set(first_definition.get('requiredAccessoryEquipmentIds', []))
    second_accessories = set(second_definition.get('requiredAccessoryEquipmentIds', []))
    cross_member_resource_overlap = (
        first_accessories & second_accessories
        or first_accessories & {second_definition.get('equipmentId')}
        or second_accessories & {first_definition.get('equipmentId')})
    if cross_member_resource_overlap:
        return 'shared_accessory_configuration_unverified'

    return None


def _generated_superset_pair(first, second, requirements, definitions):
    # Outer exercise rest does not prescribe recovery between superset members.
    pair = [copy.deepcopy(first), copy.deepcopy(second)]
    for item in pair:
        item['superset'] = 'CODE_GENERATED'
    round_recovery = max(item['restBetweenSetsSeconds'] for item in pair)
    pair[0]['restAfterExerciseSeconds'] = 0
    pair[1]['restAfterSupersetExerciseSeconds'] = round_recovery
    for item in pair:
        item['restBetweenSetsSeconds'] = 0
    return list(_rest_options(pair, requirements, definitions,
        max(item['numWorkSets'] for item in pair)))[-1]


def overlapping_movement_pairs(items, family_by_reference=None):
    """Count shared specific roles or reviewed families once; broad muscle/plane labels do not qualify."""
    family_by_reference = family_by_reference or {}
    roles = {}
    for item in items:
        roles.setdefault(item['definition_id'], set()).update(
            movement_overlap_roles(item.get('satisfiesCoverage', [])))
    return [(first, second) for first, second in itertools.combinations(sorted(roles), 2)
            if roles[first] & roles[second] or family_by_reference.get(first)
            and family_by_reference.get(first) == family_by_reference.get(second)]


def _execution_order(blocks, chosen, requirements):
    if blocks and 'sequenceArcs' in blocks[0]:
        successors = {tail: head for (tail, head), index in blocks[0]['sequenceArcs'].items()
            if tail != head and chosen[index]}
        order, node = [], successors.get(0, 0)
        while node:
            if node - 1 in order:
                raise ValueError('CP-SAT returned a cyclic execution path without the depot.')
            order.append(node - 1)
            node = successors[node]
        return order
    selected = [index for index, block in enumerate(blocks) if any(chosen[option] for option in block['options'])]
    profiles = None
    if 'movement_overlap' in (requirements.get('objectiveOrder') or []):
        profiles = []
        for index in selected:
            block = blocks[index]
            option = next(block['optionValues'][option] for option in block['options'] if chosen[option])
            profile = copy.deepcopy(block['recipe']['interferencePerRound'])
            for field in ('primary', 'supporting'):
                profile[field] = {muscle: count * option['count'] for muscle, count in profile[field].items()}
            profiles.append(profile)
    order = execution_order_indices([blocks[index]['recipe']['roles'] for index in selected],
        [_block_order_key(blocks, index, chosen) for index in selected], requirements,
        [blocks[index]['recipe'].get('setupResources', frozenset()) for index in selected], profiles,
        [next(blocks[index]['optionValues'][option]['setupProfiles']
            for option in blocks[index]['options'] if chosen[option]) for index in selected],
        [next(blocks[index]['optionValues'][option]['count']
            for option in blocks[index]['options'] if chosen[option]) for index in selected])
    return [selected[index] for index in order]


def _block_order_key(blocks, index, chosen=None):
    block = blocks[index]
    counts = None
    if chosen is not None and 'optionValues' in block:
        option = next(block['optionValues'][option_index] for option_index in block['options']
            if chosen[option_index])
        counts = [item['numWorkSets'] for item in option['items']]
    definitions = block['recipe'].get('definitionRecords') or [
        {'id': reference} for reference in sorted(block['recipe'].get('definitions', []))]
    return execution_block_order_key(definitions, counts)


def _minimum_block_work_sets(block):
    return {reference: min(sum(item['numWorkSets'] for item in option['items']
            if item['definition_id'] == reference) for option in block['optionValues'].values())
        for reference in block['recipe']['definitions']}


def _quotient_execution_blocks(blocks, session_caps):
    """Share a physical visit only when actual cap rows forbid selecting both variants."""
    groups, buckets = [], {}
    for original_index, block in enumerate(blocks):
        recipe = block['recipe']
        identity = (tuple(recipe['identity']), tuple(sorted(recipe['roles'])), recipe['orderPriority'],
            json.dumps(recipe['interferencePerRound'], sort_keys=True))
        minimum_sets = _minimum_block_work_sets(block)
        target = next((group for group in buckets.get(identity, [])
            if all(any(minimum_sets.get(reference, 0) + previous.get(reference, 0) > cap
                    for reference, cap in session_caps.items()) for previous in group['variantMinimumSets'])), None)
        if target is None:
            target = {**block, 'options': list(block['options']),
                'recipeIndexes': list(block['recipeIndexes']), 'optionValues': dict(block['optionValues']),
                'optionRecipes': dict(block['optionRecipes']), 'optionsByRecipe': dict(block['optionsByRecipe']),
                'sourceVariantIndexes': [original_index], 'variantMinimumSets': [minimum_sets]}
            groups.append(target)
            buckets.setdefault(identity, []).append(target)
        else:
            target['options'].extend(block['options'])
            target['recipeIndexes'].extend(block['recipeIndexes'])
            target['optionValues'].update(block['optionValues'])
            target['optionRecipes'].update(block['optionRecipes'])
            target['optionsByRecipe'].update(block['optionsByRecipe'])
            target['sourceVariantIndexes'].append(original_index)
            target['variantMinimumSets'].append(minimum_sets)
    return groups


def _add_selection_order_feasibility(blocks, requirements, variable, constraint, day_index):
    """Require an acyclic selected precedence graph without constructing execution pairs."""
    predecessors = execution_order_predecessors([block['recipe']['roles'] for block in blocks], requirements)
    if not any(predecessors.values()):
        return
    size = len(blocks)
    present, ranks = [], []
    for block_index, block in enumerate(blocks):
        presence = variable(domain_identity={'kind': 'execution_presence',
            'workoutIndex': day_index, 'blockIndex': block_index})
        rank = variable(upper=size, domain_identity={'kind': 'execution_rank',
            'workoutIndex': day_index, 'blockIndex': block_index})
        present.append(presence)
        ranks.append(rank)
        constraint(('execution_presence', day_index, block_index), 0, 0,
            {presence: 1, **dict.fromkeys(block['options'], -1)})
        constraint(('execution_rank_selected', day_index, block_index), -math.inf, 0,
            {rank: 1, presence: -size})
    for after, before_set in predecessors.items():
        for before in before_set:
            constraint(('execution_precedence', day_index, before, after), 1 - 2 * (size + 1), math.inf,
                {ranks[after]: 1, ranks[before]: -1,
                 present[before]: -size - 1, present[after]: -size - 1})


def _split_execution_goal(name):
    return name.startswith('ordering_') or name in (
        'execution_order', 'setup_economy_transitions', 'setup_economy_resource_switches')


def solve_prescribed_week(sessions, requirements, equipment, restriction_policy=None, existing=None,
                          allow_educated_load_guesses=True, *, training_history=None, messages=None, balance=False,
                          preserve_source_selection=False, redistribution_constraints=None,
                          source_working_set_budget=None, reviewed_baseline_workouts=None, progress=None,
                          search_deadline=None):
    """Settle selection before execution when the approved policy supports that split."""
    started = time.monotonic()
    search_deadline = started + _SOLVER_SEARCH_SECONDS if search_deadline is None else search_deadline
    refinement_reserve = min(20, max(0, search_deadline - started) / 6)
    arguments = dict(restriction_policy=restriction_policy, existing=existing,
        allow_educated_load_guesses=allow_educated_load_guesses, training_history=training_history,
        messages=messages, balance=balance, preserve_source_selection=preserve_source_selection,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=source_working_set_budget,
        reviewed_baseline_workouts=reviewed_baseline_workouts, progress=progress,
        search_deadline=search_deadline)
    order = requirements.get('objectiveOrder') or []
    supported = (selection_precedes_execution(requirements) and order[-1] == 'execution_order'
        and not any(_split_execution_goal(goal['metric'])
            for tier in requirements.get('objectiveTiers', []) for goal in tier))
    if not supported:
        return _solve_prescribed_week(sessions, requirements, equipment, **arguments)
    selection = _solve_prescribed_week(sessions, requirements, equipment,
        **{**arguments, 'search_deadline': search_deadline - min(45, max(0, search_deadline - started) * 3 / 8)},
        _selection_only=True)
    prefix_bounds = selection.pop('_selectionPrefixBounds', {})
    if not selection.get('feasible'):
        return selection
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    selected_work = _selected_session_work(selection['sessions'], definitions)
    result = _solve_prescribed_week(sessions, requirements, equipment,
        **{**arguments, 'search_deadline': search_deadline - refinement_reserve},
        _fixed_session_work=selected_work,
        _selection_prefix_bounds=prefix_bounds,
        _selection_prefix_stages={stage['goal']: stage for stage in selection['objectiveProgress']},
        _prescription_seed=selection['sessions'])
    execution = {'status': result.get('status'), 'elapsedSeconds': result.get('elapsedSeconds')}
    execution_diagnostics = result.get('solverDiagnostics', [])
    if not result.get('feasible'):
        execution['instruction'] = result.get('instruction')
        result = selection
        for priority in result['priorityExecution']['approvedPriorities']:
            if priority['priority'] == 'execution_order':
                priority.update(status='not_run_after_solver_stop', solverStage={
                    'status': execution['status'], 'scope': 'fixed_selected_work_execution_attempt'})
    result['splitArchitecture'] = {'selection': {'status': selection['status'],
        'elapsedSeconds': selection.get('elapsedSeconds'),
        'scope': selection.get('optimizationScope')},
        'execution': execution,
        'selectedSessionWork': selected_work,
        'scope': 'Exact audited recipe timing; execution is conditional on fixed per-session definition counts and attained selection-prefix bounds.'}
    result['solverDiagnostics'] = selection.get('solverDiagnostics', []) + execution_diagnostics
    result['elapsedSeconds'] = time.monotonic() - started
    result['searchBudget'] = {'limitSeconds': max(0, search_deadline - started),
        'remainingSeconds': max(0, search_deadline - time.monotonic()),
        'exhausted': time.monotonic() >= search_deadline,
        'scope': 'shared_selection_and_fixed_work_execution_search_including_model_preparation; final_audit_may_finish_after_deadline'}
    if result.get('feasible'):
        result['status'] = 'feasible'
        result['jointModelStatus'] = 'feasible'
        result['optimizationScope'] = ('Selection-prefix proof comes from the full recipe menu; execution proof is conditional '
            'on fixed per-session definition counts and attained prefix bounds. No joint global optimum is claimed.')
        result['arrangementRefinement']['scope'] = (
            'Execution grouping, allowed rests and ordering for fixed per-session definition counts under attained selection-prefix bounds.')
        for priority in result['priorityExecution']['approvedPriorities']:
            if priority['priority'] == 'execution_order':
                priority['scope'] = 'fixed_per_session_definition_counts_and_attained_selection_prefix'
    if result.get('feasible'):
        from .candidate_refinement import refine_complete_candidate
        result = refine_complete_candidate(result, sessions, requirements, equipment, **arguments)
        result['elapsedSeconds'] = time.monotonic() - started
        result['searchBudget'] = {'limitSeconds': max(0, search_deadline - started),
            'remainingSeconds': max(0, search_deadline - time.monotonic()),
            'exhausted': time.monotonic() >= search_deadline,
            'scope': 'shared_selection_execution_and_complete_candidate_refinement; final_audit_may_finish_after_deadline'}
    return result


def _add_execution_sequence(blocks, requirements, variable, constraint, day_index, frequency,
                            session_caps=None):
    """Couple optional block selection, opener and exact ordered execution facts."""
    from .programming_guidelines import execution_order_phase, execution_interference_metric_names
    size = len(blocks)
    # Existing session caps already forbid these visits together, in any execution order.
    minimum_sets = [_minimum_block_work_sets(block) for block in blocks] if session_caps else []
    incompatible = {(before, after) for before, after in itertools.permutations(range(size), 2)
        if any(minimum_sets[before].get(reference, 0) + minimum_sets[after].get(reference, 0) > cap
            for reference, cap in session_caps.items())} if session_caps else set()
    predecessors = execution_order_predecessors([block['recipe']['roles'] for block in blocks], requirements)
    ranks, present, counts, arcs = [], [], [], {}
    costs = {name: {} for name in ('setup_economy_transitions', 'setup_economy_resource_switches')}
    metric_names = execution_interference_metric_names(requirements)
    known_anatomy = all(block['recipe']['interferencePerRound']['known'] for block in blocks)
    phases = [execution_order_phase(block['recipe']['orderPriority'], requirements) for block in blocks]
    needs_rank = (any(predecessors.values()) or len(set(phases)) > 1
        or 'execution_order' in (requirements.get('objectiveOrder') or [])
        and known_anatomy and any(not name.startswith('adjacent_') for name in metric_names))
    if 'execution_order' in (requirements.get('objectiveOrder') or []) and known_anatomy:
        costs.update({'ordering_' + name: {} for name in metric_names})

    def conjunction(indices, identity):
        result = variable(domain_identity={'kind': 'execution_conjunction', **identity})
        for index in indices:
            constraint(('execution_conjunction_upper', result, index), -math.inf, 0, {result: 1, index: -1})
        constraint(('execution_conjunction_lower', result), 1 - len(indices), math.inf,
            {result: 1, **dict.fromkeys(indices, -1)})
        return result

    def gated_count(flag, count, upper):
        result = variable(upper=upper, domain_identity={'kind': 'execution_gated_count',
            'workoutIndex': day_index, 'flag': flag, 'count': count})
        constraint(('execution_gated_count', result, 'flag'), -math.inf, 0, {result: 1, flag: -upper})
        constraint(('execution_gated_count', result, 'count'), -math.inf, 0, {result: 1, count: -1})
        constraint(('execution_gated_count', result, 'lower'), -upper, math.inf,
            {result: 1, count: -1, flag: -upper})
        return result

    for block_index, block in enumerate(blocks):
        presence = variable(domain_identity={'kind': 'execution_presence', 'workoutIndex': day_index,
            'blockIndex': block_index})
        present.append(presence)
        constraint(('execution_presence', day_index, block_index), 0, 0,
            {presence: 1, **dict.fromkeys(block['options'], -1)})
        rank = variable(upper=size, domain_identity={'kind': 'execution_rank',
            'workoutIndex': day_index, 'blockIndex': block_index})
        ranks.append(rank)
        constraint(('execution_rank_selected', day_index, block_index), -math.inf, 0,
            {rank: 1, presence: -size})
        count_upper = max(option['count'] for option in block['optionValues'].values())
        count = variable(upper=count_upper, domain_identity={'kind': 'execution_set_count',
            'workoutIndex': day_index, 'blockIndex': block_index})
        counts.append((count, count_upper))
        constraint(('execution_set_count', day_index, block_index), 0, 0,
            {count: 1, **{index: -option['count'] for index, option in block['optionValues'].items()}})
    for tail in range(size + 1):
        for head in range(size + 1):
            if tail == head == 0:
                continue
            if tail and head and (tail - 1, head - 1) in incompatible:
                continue
            arc = variable(domain_identity={'kind': 'execution_arc', 'workoutIndex': day_index,
                'tail': tail, 'head': head})
            arcs[tail, head] = arc
            if tail == head:
                constraint(('execution_absence_loop', day_index, tail), 1, 1, {arc: 1, present[tail - 1]: 1})
            elif tail == 0:
                constraint(('execution_first', day_index, head), 0, 0, {arc: 1, blocks[head - 1]['first']: -1})
            elif head and needs_rank:
                constraint(('execution_successor_rank', day_index, tail, head), 1 - size - 1, math.inf,
                    {ranks[head - 1]: 1, ranks[tail - 1]: -1, arc: -size - 1})
    if blocks:
        blocks[0]['sequenceArcs'] = arcs
    for after, before_set in predecessors.items():
        for before in before_set:
            constraint(('execution_precedence', day_index, before, after), 1 - 2 * (size + 1), math.inf,
                {ranks[after]: 1, ranks[before]: -1,
                 present[before]: -size - 1, present[after]: -size - 1})
    before_variables = {}
    for before, after in (itertools.permutations(range(size), 2) if needs_rank else []):
        if (before, after) in incompatible:
            continue
        pair = variable(domain_identity={'kind': 'execution_before', 'workoutIndex': day_index,
            'before': before, 'after': after})
        before_variables[before, after] = pair
        for presence in (present[before], present[after]):
            constraint(('execution_before_presence', pair, presence), -math.inf, 0, {pair: 1, presence: -1})
        constraint(('execution_before_rank', pair), -size, math.inf,
            {ranks[after]: 1, ranks[before]: -1, pair: -size - 1})
        constraint(('execution_before_reverse', pair), -math.inf, 2 * (size + 1),
            {ranks[after]: 1, ranks[before]: -1, pair: -size - 1,
             present[before]: size + 1, present[after]: size + 1})
    for lower, higher in itertools.permutations(range(size), 2):
        if phases[lower] >= phases[higher] or (lower, higher) in incompatible:
            continue
        coefficients = {before_variables[lower, higher]: 1, present[lower]: -1, present[higher]: -1}
        for predecessor in predecessors[lower]:
            coefficients[present[predecessor]] = coefficients.get(present[predecessor], 0) + 1
            if predecessor != higher and (predecessor, higher) not in incompatible:
                pair = before_variables[predecessor, higher]
                coefficients[pair] = coefficients.get(pair, 0) - 1
        constraint(('execution_phase_ready', day_index, lower, higher), -1, math.inf, coefficients)

    profile_groups = []
    setup_known = resource_known = True
    for block_index, block in enumerate(blocks):
        groups = {}
        for index, option in block['optionValues'].items():
            profiles, rounds = option['setupProfiles'], option['count']
            internal = _setup_evidence_for_blocks([{'profiles': profiles, 'rounds': rounds,
                'componentIndex': 0, 'exerciseRefs': [], 'kind': 'superset' if len(profiles) > 1 else 'exercise'}])
            costs['setup_economy_transitions'][index] = frequency * internal['knownDeclaredChanges']
            costs['setup_economy_resource_switches'][index] = frequency * internal['declaredResourceSwitches']
            setup_known &= internal['unknownTransitions'] == 0
            resource_known &= internal['resourceIdentityComplete']
            first = _setup_profile_at_set(profiles[0], 0)
            last = _setup_profile_at_set(profiles[-1], rounds - 1)
            key = json.dumps([first, last], sort_keys=True)
            groups.setdefault(key, {'first': first, 'last': last, 'options': []})['options'].append(index)
        for group in groups.values():
            if len(groups) == 1:
                group['active'] = present[block_index]
            else:
                group['active'] = variable(domain_identity={'kind': 'execution_setup_variant',
                    'workoutIndex': day_index, 'blockIndex': block_index})
                constraint(('execution_setup_variant', group['active']), 0, 0,
                    {group['active']: 1, **dict.fromkeys(group['options'], -1)})
        profile_groups.append(list(groups.values()))
    for before, after in itertools.permutations(range(size), 2):
        arc = arcs.get((before + 1, after + 1))
        for first, second in itertools.product(profile_groups[before], profile_groups[after]):
            evidence = _setup_resource_transition(first['last'], second['first'])
            # Preserve the menu's evidence status even when its edge is impossible.
            setup_known &= evidence['declaredResourceChange'] is not None
            resource_known &= first['last']['resourceEvidence'] == second['first']['resourceEvidence'] == 'declared_references'
            changed = evidence['declaredResourceChange'] is True
            switched = evidence['resourceSelection'] == 'changed_references'
            if arc is not None and (changed or switched):
                edge = (arc if len(profile_groups[before]) == len(profile_groups[after]) == 1 else
                    conjunction([arc, first['active'], second['active']], {'workoutIndex': day_index}))
                if changed:
                    costs['setup_economy_transitions'][edge] = frequency
                if switched:
                    costs['setup_economy_resource_switches'][edge] = frequency
    if not setup_known:
        costs['setup_economy_transitions'] = {}
    if not resource_known:
        costs['setup_economy_resource_switches'] = {}

    if 'execution_order' in (requirements.get('objectiveOrder') or []) and known_anatomy:
        profiles = [block['recipe']['interferencePerRound'] for block in blocks]
        cumulative = {name: [{} for _ in blocks] for name in metric_names if not name.startswith('adjacent_')}
        for before, after in itertools.permutations(range(size), 2):
            if (before, after) in incompatible:
                continue
            pair = before_variables.get((before, after))
            source, receiver = profiles[before], profiles[after]
            gated = adjacent = None
            for name in metric_names:
                if name.startswith('priority_') and not receiver['priority']:
                    continue
                if name.startswith('heavy_') and not receiver['heavy_primary']:
                    continue
                if name.startswith('main_') and not receiver['main_primary']:
                    continue
                prefix = 'heavy' if name.startswith('heavy_') else 'main' if name.startswith('main_') else None
                direct = receiver[prefix + '_primary'] if prefix else receiver['primary']
                secondary = receiver[prefix + '_supporting'] if prefix else receiver['supporting']
                coefficient = (sum(source['primary'].get(muscle, 0) for muscle in direct)
                    if name.endswith('_direct') else
                    sum(source['supporting'].get(muscle, 0) for muscle in direct)
                    + sum(source['primary'].get(muscle, 0) + source['supporting'].get(muscle, 0)
                        for muscle in secondary if muscle not in direct))
                if not coefficient:
                    continue
                if name.startswith('adjacent_'):
                    if adjacent is None:
                        adjacent = gated_count(arcs[before + 1, after + 1], *counts[before])
                    costs['ordering_' + name][adjacent] = coefficient * frequency
                else:
                    if gated is None:
                        gated = gated_count(pair, *counts[before])
                    cumulative[name][after][gated] = coefficient
        for name, expressions in cumulative.items():
            if name.startswith('priority_'):
                for expression in expressions:
                    for index, coefficient in expression.items():
                        costs['ordering_' + name][index] = coefficient * frequency
            else:
                upper = sum(count[1] for count in counts) * max(1, max(
                    (sum(expression.values()) for expression in expressions), default=0))
                peak = variable(upper=upper, domain_identity={'kind': 'execution_exposure_peak',
                    'workoutIndex': day_index, 'metric': name})
                costs['ordering_' + name][peak] = frequency
                for after, expression in enumerate(expressions):
                    constraint(('execution_exposure_peak', day_index, name, after), -math.inf, 0,
                        {**expression, peak: -1})
    return costs, {'anatomyComplete': known_anatomy, 'setupTransitionsComplete': bool(setup_known),
        'resourceReferencesComplete': bool(resource_known)}


def refine_group_arrangements(sessions, requirements, equipment, restriction_policy=None,
                              allow_educated_load_guesses=True, *, source_sessions=None,
                              occurrence_lineage=None, existing=None, baseline_audit=None,
                              context, training_history=None, messages=None, execution_definitions=None):
    """Compare complete keep/split arrangements of an already selected weekly dose."""
    from .programming_guidelines import canonical_execution_order_draft
    from .training_history import apply_native_load_calibration_policy
    from .planning_decisions import execution_decision_definitions, confirmed_setup_access

    requirements = confirmed_setup_access(messages or [], equipment, requirements)['requirements']
    execution_definitions = (execution_decision_definitions(messages or [], equipment)
        if execution_definitions is None else execution_definitions)
    fixed = copy.deepcopy((existing or {}).get('workouts', []))
    definitions = {f'LIBRARY_{index}': execution_definitions.get(value['id'], value)
        for index, value in enumerate(
        sorted(equipment.get('exerciseDefinitions', []), key=lambda value: value['id']))}
    definitions.update({value['id']: value for value in definitions.values()})
    context = {**context, 'setupDefinitions': definitions}
    source_sessions = source_sessions if source_sessions is not None else sessions
    lineage = (copy.deepcopy(occurrence_lineage) if occurrence_lineage is not None else
        [[[day, index] for index in range(len(value['exercises']))]
            for day, value in enumerate(sessions)])
    if len(lineage) != len(sessions) or any(len(tokens) != len(day['exercises'])
            for tokens, day in zip(lineage, sessions)):
        raise ValueError('Arrangement refinement requires exact occurrence lineage.')
    stats = {'evaluatedSessionVariantCount': 0, 'fullWeekAuditCount': 0}
    validate_loads = None
    if training_history:
        validate_loads = (training_history.load_suitability_validator(messages, equipment)
            if hasattr(training_history, 'load_suitability_validator') else
            lambda plan: training_history.load_suitability_errors(plan, messages, equipment))

    def audit(workouts, *, session_only=False):
        draft = {'name': 'Joint arrangements', 'workouts': copy.deepcopy(workouts)}
        plan, report = _audit_raw(draft, equipment, requirements, restriction_policy,
            allow_educated_load_guesses, apply_family_bounds=not session_only,
            execution_definitions=execution_definitions)
        apply_native_load_calibration_policy(plan, messages or [], equipment,
            getattr(training_history, 'fingerprint', None),
            allow_educated_load_guesses=allow_educated_load_guesses)
        audit_execution_rules(draft, requirements, report, plan)
        audit_execution_details(draft, requirements, report)
        if validate_loads:
            report['errors'].extend(validate_loads(plan))
        stats['evaluatedSessionVariantCount' if session_only else 'fullWeekAuditCount'] += 1
        return report

    baseline_audit = copy.deepcopy(baseline_audit) if baseline_audit is not None else audit(fixed + sessions)
    baseline = {'workouts': fixed + copy.deepcopy(sessions), 'audit': baseline_audit,
        'searchStatus': 'selected_joint_week'}
    output = {'sessions': copy.deepcopy(sessions), 'audit': baseline_audit,
        'occurrenceLineage': lineage, 'status': 'not_requested', 'selectedMask': None,
        'comparisons': [], 'frontier': [], **stats,
        'scope': 'Keep/split choices for the selected groups at approved minimum rests and shared canonical ordering; selection and dose are fixed.'}
    if not set(requirements.get('objectiveOrder') or []) & {
            'setup_economy', 'duration_economy', 'duration_balance'}:
        return output

    dose_fields = ('definition_id', 'minReps', 'maxReps', 'durationSeconds',
        'workSetTemplate', 'targetSetPrescriptions', 'effortAcceptance',
        'requiresLoadCalibration', 'generateWarmUpSets', 'intraSetRestInSeconds',
        'repDurationSeconds')

    def straight_source(item, token):
        if token is not None:
            day, index = token
            if 0 <= day < len(source_sessions) and 0 <= index < len(source_sessions[day]['exercises']):
                source = source_sessions[day]['exercises'][index]
                if source.get('superset') is None and all(
                        source.get(key) == item.get(key) for key in dose_fields):
                    return source
        candidates = [source for day in source_sessions for source in day['exercises']
            if source.get('superset') is None
            and all(source.get(key) == item.get(key) for key in dose_fields)]
        recovery_fields = ('restBetweenSetsSeconds', 'restAfterExerciseSeconds', 'setupSeconds')
        if candidates and all(all(source.get(key) == candidates[0].get(key)
                for key in recovery_fields) for source in candidates):
            return candidates[0]
        return None

    groups_by_day = []
    for day_index, day in enumerate(sessions):
        groups = []
        for group, entries in itertools.groupby(enumerate(day['exercises']),
                lambda entry: entry[1].get('superset')):
            positions = [position for position, _ in entries]
            if group is not None and len(positions) > 1:
                sources = [straight_source(day['exercises'][position], lineage[day_index][position])
                    for position in positions]
                if all(source is not None for source in sources):
                    groups.append((group, positions, sources))
        groups_by_day.append(groups)
    if not any(groups_by_day):
        output['status'] = 'no_splittable_groups'
        return output
    # shortcut: enumerate at most eight arrangements per session, revisit for approved sessions above three groups.
    if any(len(groups) > 3 for groups in groups_by_day):
        output['status'] = 'not_searched_session_group_limit'
        return output

    variants_by_day = []
    rejected = Counter()
    for day_index, (day, groups) in enumerate(zip(sessions, groups_by_day)):
        variants = []
        for mask in itertools.product((False, True), repeat=len(groups)):
            variant = copy.deepcopy(day)
            for (_, positions, sources), split in zip(groups, mask):
                if split:
                    for position, source in zip(positions, sources):
                        item = variant['exercises'][position]
                        item.update(superset=None, restAfterSupersetExerciseSeconds=0)
                        for field in ('restBetweenSetsSeconds', 'restAfterExerciseSeconds', 'setupSeconds'):
                            if field in source:
                                item[field] = copy.deepcopy(source[field])
                            else:
                                item.pop(field, None)
                        item.update(list(_rest_options([item], requirements, definitions,
                            item['numWorkSets']))[-1][0])
            for index, item in enumerate(variant['exercises']):
                item['_arrangementOccurrenceIndex'] = index
            ordered = canonical_execution_order_draft({'workouts': [variant]}, requirements, equipment)
            if ordered is None:
                rejected['canonical_order_unavailable'] += 1
                continue
            variant = ordered['workouts'][0]
            tokens = [lineage[day_index][item.pop('_arrangementOccurrenceIndex')]
                for item in variant['exercises']]
            try:
                report = audit([variant], session_only=True)
            except (ValueError, ValidationError):
                rejected['invalid_arrangement'] += 1
                continue
            blockers = [error for error in report['errors']
                if not error['code'].startswith('schedule_')
                and error.get('scope') != 'weekly'
                and error['code'] not in ('required_coverage_weekly_sets_below_minimum',
                    'required_coverage_sessions_below_minimum')]
            if blockers:
                rejected.update(error['code'] for error in blockers)
                continue
            variants.append({'session': variant, 'lineage': tokens,
                'audit': report['workouts'][0], 'mask': ''.join('1' if split else '0' for split in mask)})
        variants_by_day.append(variants)
    output.update(stats, rejectedSessionFindingCounts=dict(rejected))
    if any(not variants for variants in variants_by_day):
        output['status'] = 'no_valid_session_arrangement'
        return output

    combination_count = math.prod(len(variants) for variants in variants_by_day)
    # shortcut: bound the Cartesian comparison, revisit with a decomposed search for larger schedules.
    if combination_count > 4096:
        output.update(status='not_searched_weekly_combination_limit',
            availableWeeklyCombinationCount=combination_count, weeklyCombinationSearchLimit=4096)
        return output

    candidates = []
    variable_paths = tuple(f'/workouts/{index}' for index in range(len(fixed), len(fixed) + len(sessions)))
    invariant_errors = [error for error in baseline_audit.get('errors', [])
        if error['code'].startswith('schedule_') or not any(
            error.get('path') == path or error.get('path', '').startswith(path + '/')
            for path in variable_paths)]
    for combination in itertools.product(*variants_by_day):
        workouts = fixed + [variant['session'] for variant in combination]
        # Only execution timing/order changes; dose aggregates remain the audited baseline's.
        report = {**baseline_audit, 'errors': invariant_errors,
            'workouts': baseline_audit['workouts'][:len(fixed)] + [variant['audit'] for variant in combination]}
        candidate = {'workouts': workouts, 'audit': report,
            'searchStatus': 'complete_group_arrangement_comparison'}
        mask = '/'.join(variant['mask'] for variant in combination)
        evaluation = evaluate_audited_execution(candidate, definitions, requirements)
        candidates.append({'candidate': candidate, 'combination': combination, 'mask': mask,
            'evaluation': {key: evaluation[key] for key in ('weeklyEstimatedSeconds',
                'weeklyDeclaredResourceSwitches', 'durationSpreadSeconds')}})

    remaining = list(candidates)
    selected = None
    while remaining:
        best_candidate, best = baseline, None
        for entry in remaining:
            comparison = compare_audited_joint_candidates(best_candidate, entry['candidate'],
                requirements=requirements, context=context)
            if comparison['decision'] == 'promote_candidate':
                best_candidate, best = entry['candidate'], entry
        if best is None:
            break
        final_report = audit(best_candidate['workouts'])
        for field in ('weeklyWorkingSets', 'weeklyVolume', 'weeklyCoverageSets'):
            if final_report.get(field) != baseline_audit.get(field):
                raise ValueError(f'Arrangement refinement changed the selected dose: {field}.')
        for before, after in zip(baseline_audit['workouts'], final_report['workouts'], strict=True):
            if any(before.get(field) != after.get(field)
                    for field in ('workingSets', 'volume', 'coverageSets')):
                raise ValueError('Arrangement refinement changed a selected session dose.')
        if not final_report['errors']:
            selected = best
            selected['candidate']['audit'] = final_report
            break
        remaining.remove(best)
        best['nativeErrors'] = [error['code'] for error in final_report['errors']]

    known = [entry for entry in candidates if not entry.get('nativeErrors')
        and entry['evaluation']['weeklyDeclaredResourceSwitches'] is not None]
    def frontier_cost(entry):
        return (entry['evaluation']['weeklyEstimatedSeconds'],
            entry['evaluation']['weeklyDeclaredResourceSwitches'],
            entry['evaluation']['durationSpreadSeconds'])
    frontier = [entry for entry in known if not any(
        all(a <= b for a, b in zip(frontier_cost(other), frontier_cost(entry)))
        and frontier_cost(other) != frontier_cost(entry) for other in known)]
    summaries = ([selected] if selected is not None else []) + sorted(frontier, key=frontier_cost)
    summarized = set()
    for entry in summaries:
        if entry['mask'] in summarized:
            continue
        summarized.add(entry['mask'])
        comparison = compare_audited_joint_candidates(baseline, entry['candidate'],
            requirements=requirements, context=context)
        output['comparisons'].append({'mask': entry['mask'], **entry['evaluation'],
            'decision': comparison['decision'], 'reason': comparison['reason'],
            'firstDifferingObjective': comparison['firstDifferingObjective']})
        if len(output['comparisons']) == 3:
            break
    output.update(frontier=[entry['mask'] for entry in sorted(frontier, key=frontier_cost)[:3]],
        frontierCount=len(frontier), fullyAuditedRejectedCombinationCount=sum(
            bool(entry.get('nativeErrors')) for entry in candidates))
    if selected is not None:
        output.update(sessions=copy.deepcopy(selected['candidate']['workouts'][len(fixed):]),
            audit=selected['candidate']['audit'], selectedMask=selected['mask'],
            occurrenceLineage=[copy.deepcopy(variant['lineage']) for variant in selected['combination']])
    output.update(stats, status='complete_group_arrangement_comparison',
        evaluatedWeeklyCombinationCount=len(candidates))
    return output


def _solve_prescribed_week(sessions, requirements, equipment, restriction_policy=None, existing=None,
                          allow_educated_load_guesses=True, *, training_history=None, messages=None, balance=False,
                          preserve_source_selection=False, redistribution_constraints=None,
                          source_working_set_budget=None, reviewed_baseline_workouts=None, progress=None,
                          search_deadline=None,
                          _selection_only=False, _fixed_session_work=None,
                          _selection_prefix_bounds=None, _selection_prefix_stages=None, _prescription_seed=None,
                          _eligible_definition_ids=None):
    """Solve selection, placement, counts, grouping, allowed rests and ordering together.

    Options keep supported loads/reps, tempo, calibration and warm-ups intact. All
    timing coefficients come from the production audit, not a second time model.
    """
    started = time.monotonic()
    search_deadline = started + _SOLVER_SEARCH_SECONDS if search_deadline is None else search_deadline
    cp_session = SolverSession()
    try:
        _DRAFT_VALIDATOR.validate({'requirementsId': 'recipes', 'name': 'Recipes', 'workouts': sessions})
    except ValidationError as error:
        return {'feasible': False, 'status': 'invalid_options', 'instruction': error.message}
    fixed_workouts = (existing or {}).get('workouts', [])
    sessions = complete_training_schedule(sessions, requirements, fixed_workouts)
    schedule_report = {'issues': [], 'errors': []}
    audit_training_schedule([*fixed_workouts, *sessions], requirements, schedule_report)
    if schedule_report['errors']:
        return {'feasible': False, 'status': 'invalid_schedule', 'errors': schedule_report['errors'],
            'instruction': 'Correct the calendar before solving; preserve qualified recipes and explicit user weekdays.'}
    try:
        normalized_source_budget = _source_working_set_budget_identity(sessions, source_working_set_budget)
        reviewed_dose_reference = _reviewed_dose_reference_identity(reviewed_baseline_workouts)
    except ValueError as error:
        return {'feasible': False, 'status': 'invalid_options', 'instruction': str(error)}
    if reviewed_dose_reference is not None and (
            reviewed_dose_reference['frequency'] != sum(day['timesCompletedInAWeek'] for day in sessions)):
        return {'feasible': False, 'status': 'invalid_options',
            'instruction': 'The reviewed dose reference does not match the current session schedule.'}
    proof = {'problemFingerprint': joint_problem_fingerprint(sessions, requirements, equipment,
        training_history, messages, restriction_policy=restriction_policy, existing=existing,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=preserve_source_selection,
        redistribution_constraints=redistribution_constraints,
        source_working_set_budget=normalized_source_budget,
        reviewed_baseline_workouts=reviewed_baseline_workouts),
        'sourceWorkingSetBudget': copy.deepcopy(normalized_source_budget),
        'reviewedDoseReference': copy.deepcopy(reviewed_dose_reference),
        'reviewedDoseReferenceAvailable': reviewed_dose_reference is not None}
    from .planning_decisions import execution_decision_definitions, confirmed_setup_access
    approved_requirements = requirements
    setup_access = confirmed_setup_access(messages or [], equipment, requirements)
    requirements = setup_access['requirements']
    execution_definitions = execution_decision_definitions(messages or [], equipment)
    if setup_access['bindings']:
        proof['confirmedSetupAccess'] = setup_access['bindings']
    if execution_definitions:
        proof['executionPrescriptions'] = {identifier: definition['reviewedExecution']['setMode']
            for identifier, definition in execution_definitions.items()}
    frequency = sum(day['timesCompletedInAWeek'] for day in [*(existing or {}).get('workouts', []), *sessions])
    if requirements.get('sessionsPerWeek') is not None and frequency != requirements['sessionsPerWeek']:
        return {**proof, 'feasible': False, 'status': 'invalid_schedule',
                'instruction': 'The recipe schedule does not match the approved weekly frequency. Correct the schedule; do not relax requirements.'}
    definitions = {f'LIBRARY_{index}': execution_definitions.get(value['id'], value)
        for index, value in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    unknown = {item['definition_id'] for day in sessions for item in day['exercises']} - definitions.keys()
    if unknown:
        return {**proof, 'feasible': False, 'status': 'invalid_options',
                'instruction': f'Unknown prescription library references: {sorted(unknown)}.'}
    fixed_source_workouts = (existing or {}).get('workouts', [])
    fixed_existing_working_sets = sum(item.get('numWorkSets', 0)
        * workout.get('timesCompletedInAWeek', 1)
        for workout in fixed_source_workouts for item in workout.get('exercises', []))
    submitted_variable_working_sets = sum(item.get('numWorkSets', 0)
        * day.get('timesCompletedInAWeek', 1)
        for day in sessions for item in day.get('exercises', []))
    variable_source_working_sets = normalized_source_budget['variableWeeklyWorkingSets']
    source_budget_source = normalized_source_budget['source']
    definitions_by_id = {definition['id']: definition for definition in definitions.values()}
    fixed_references = {item['definition_id'] for day in fixed_source_workouts
        for item in day.get('exercises', [])}
    fixed_unavailable_groups = {}
    fixed_present_ids = {}
    for key in ('unsupported_trunk', 'axial_loading', 'eccentric_emphasis'):
        unknown_ids, present_ids = [], []
        for reference in sorted(fixed_references):
            definition = definitions.get(reference) or definitions_by_id.get(reference)
            if definition is None:
                unknown_ids.append(reference)
                continue
            fact = definition_demand_facts(definition)[key]
            if fact['status'] == 'unknown':
                unknown_ids.append(definition['id'])
            elif fact['status'] == 'present':
                present_ids.append(definition['id'])
        if unknown_ids:
            fixed_unavailable_groups[key] = unknown_ids
        fixed_present_ids[key] = present_ids
    demand_inputs = {'groups': {}, 'unavailableGroups': {}, 'status': 'unavailable'}
    demand_present_refs = {}
    variables, constraints, recipes, rejected = [], [], [], []
    structure_limits = session_structure_limits(requirements)
    from .planning_tools import library_fingerprint
    from .training_history import apply_native_load_calibration_policy
    evidence = recorded_evidence(messages or [], library_fingerprint(equipment),
        getattr(training_history, 'fingerprint', None), equipment=equipment)
    capabilities = {ref: progression_capability(definition, equipment, evidence.get(definition['id']))
                    for ref, definition in definitions.items() if any(
                        item['definition_id'] == ref for day in sessions for item in day['exercises'])}
    source_blocks_by_identity = []
    source_blocks = []
    source_recipe_positions = []
    recipe_candidates = []
    superset_candidates = {'enabled': False, 'sourceGroupCount': 0, 'codeGeneratedCandidateCount': 0,
        'compiledCandidateCount': 0, 'compileCacheHits': 0, 'uniqueRecipeCompileCount': 0,
        'rejectionCounts': {}, 'rejectedCandidates': [],
        'selectedSourceGroupCount': 0, 'selectedCodeGeneratedGroupCount': 0}
    practical_objective = bool({'execution_order', 'time_budget', 'duration_economy', 'setup_economy'} &
        set(requirements.get('objectiveOrder') or []))
    # A reviewed weekly-dose reference does not freeze execution grouping.
    generate_superset_candidates = not redistribution_constraints and practical_objective
    if generate_superset_candidates:
        superset_candidates['enabled'] = True
    elif redistribution_constraints:
        superset_candidates['disabledReason'] = 'targeted_redistribution'
    else:
        superset_candidates['disabledReason'] = 'no_execution_or_practical_objective'
    for workout_index, day in enumerate(sessions):
        occurrence_by_signature = Counter()
        indexed = {}
        for block, positions in _blocks_with_source_positions([day]):
            signature = _recipe_signature(block)
            occurrence = occurrence_by_signature[signature]
            occurrence_by_signature[signature] += 1
            indexed[(signature, occurrence)] = (block,
                [(workout_index, index) for _, index in positions])
        source_blocks.append(indexed)
    for workout_index, day in enumerate(sessions):
        occurrence_by_signature = Counter()
        indexed = {}
        day_candidates = [(block, [(workout_index, index) for _, index in positions], False)
            for block, positions in _blocks_with_source_positions([day], standalone=True)
            if _eligible_definition_ids is None or all(
                definitions[item['definition_id']]['id'] in _eligible_definition_ids for item in block)]
        superset_candidates['sourceGroupCount'] += sum(1 for block, _, _ in day_candidates
            if len(block) > 1 and any(item.get('superset') is not None for item in block))
        if generate_superset_candidates:
            singletons = [(block[0], positions[0][1]) for block, positions, _ in day_candidates if len(block) == 1]
            submitted_groups = {frozenset(index for _, index in positions)
                for block, positions, _ in day_candidates if len(block) > 1}
            for (first, first_position), (second, second_position) in itertools.combinations(singletons, 2):
                if first_position == second_position or frozenset((first_position, second_position)) in submitted_groups:
                    continue
                reason = _superset_pair_rejection(first, second, definitions, requirements, equipment)
                if reason:
                    superset_candidates['rejectionCounts'][reason] = (
                        superset_candidates['rejectionCounts'].get(reason, 0) + 1)
                    if len(superset_candidates['rejectedCandidates']) < 100:
                        superset_candidates['rejectedCandidates'].append({'workoutIndex': workout_index,
                            'sourcePositions': [[workout_index, first_position], [workout_index, second_position]],
                            'definitionIds': [first['definition_id'], second['definition_id']], 'reason': reason})
                    continue
                pair_positions = [(first, first_position), (second, second_position)]
                member_order = execution_member_order([definitions[item['definition_id']]
                    for item, _ in pair_positions], requirements)
                pair_positions = [pair_positions[index] for index in member_order]
                pair = _generated_superset_pair(pair_positions[0][0], pair_positions[1][0],
                    requirements, definitions)
                day_candidates.append((pair, [(workout_index, position)
                    for _, position in pair_positions], True))
                superset_candidates['codeGeneratedCandidateCount'] += 1
        recipe_candidates.append(day_candidates)
        for block, positions, _ in day_candidates:
            signature = _recipe_signature(block)
            occurrence = occurrence_by_signature[signature]
            occurrence_by_signature[signature] += 1
            indexed[(signature, occurrence)] = copy.deepcopy(positions)
        source_recipe_positions.append(indexed)
    for day in sessions:
        source_blocks_by_identity.append([
            tuple(item['definition_id'] for item in block) for block in _blocks([day])])
    recipe_occurrences = [{} for _ in sessions]
    validate_loads = None
    if training_history:
        validate_loads = (training_history.load_suitability_validator(messages, equipment)
            if hasattr(training_history, 'load_suitability_validator') else
            lambda plan: training_history.load_suitability_errors(plan, messages, equipment))

    def variable(upper=1, cost=0, domain_identity=None, lower=0, integer=True):
        index = len(variables)
        variables.append({'lower': lower, 'upper': upper, 'current': [], 'members': [],
                          'objectiveCost': cost, 'domainIdentity': domain_identity, 'integer': integer})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((label, lower, upper, intercept, coefficients))

    # The joint solve may replace or detach an unsafe submitted superset, but
    # that exact recipe must still fail per-recipe validation. Keep this
    # grouping-only error out of the recipe-local set of tolerated numeric
    # audit findings so an unusable source pair cannot enter the qualified domain.
    numeric_errors = JOINT_REPAIRABLE_AUDIT_ERRORS - {'execution_supersetNoReconfiguration'}
    unknown_volume_preferences = set()
    compiled_recipe_cache = {}
    unresolved_execution = {}
    from .exercise_contracts import execution_semantics_problem
    # Audit one recipe once per count; those contributions are reusable in every session.
    for workout_index, day_candidates in enumerate(recipe_candidates):
        for block, source_positions, generated in day_candidates:
            execution_errors = []
            for item, (_, source_index) in zip(block, source_positions):
                problem = execution_semantics_problem(item, definitions[item['definition_id']])
                if problem:
                    error = {'code': 'execution_semantics_unresolved',
                        'definition_id': item['definition_id'],
                        'canonicalDefinitionId': definitions[item['definition_id']]['id'],
                        'path': f'/workouts/{workout_index}/exercises/{source_index}',
                        'message': problem, 'roles': item.get('satisfiesCoverage', [])}
                    unresolved_execution[item['definition_id']] = error
                    execution_errors.append(error)
            if execution_errors:
                rejected.extend(execution_errors)
                continue
            maximum_group_size = structure_limits.get('maximumSupersetSize')
            if (maximum_group_size is not None and len(block) > maximum_group_size
                    and any(item.get('superset') is not None for item in block)):
                rejected.append({'code': 'execution_sessionStructure', 'workoutIndex': workout_index,
                    'sourcePositions': copy.deepcopy(source_positions), 'limit': 'maximumSupersetSize',
                    'actual': len(block), 'maximum': maximum_group_size})
                continue
            signature = _recipe_signature(block)
            source_key = next((key for key, positions in source_recipe_positions[workout_index].items()
                if key[0] == signature and positions == source_positions), None)
            if source_key is None:
                return {**proof, 'feasible': False, 'status': 'invalid_options',
                    'errors': [{'code': 'recipe_source_identity_missing', 'workoutIndex': workout_index,
                        'sourcePositions': copy.deepcopy(source_positions)}],
                    'instruction': ('A submitted movement recipe could not be bound to its exact source occurrence. '
                        'Preserve the input; no infeasibility was established.')}
            source_signature_occurrence = source_key[1]
            member_order = execution_member_order([definitions[item['definition_id']] for item in block], requirements)
            rest_slots = [(item['restAfterSupersetExerciseSeconds'], item['restAfterExerciseSeconds']) for item in block]
            block = [copy.deepcopy(block[index]) for index in member_order]
            source_positions = [source_positions[index] for index in member_order]
            if member_order != list(range(len(block))):
                for item, (recovery, outer_rest) in zip(block, rest_slots):
                    item['restAfterSupersetExerciseSeconds'] = recovery
                    item['restAfterExerciseSeconds'] = outer_rest
            compiled_cache_key = json.dumps(block, sort_keys=True, separators=(',', ':'))
            recipe_identity = tuple(item['definition_id'] for item in block)
            recipe_occurrence = recipe_occurrences[workout_index].get(recipe_identity, 0)
            recipe_occurrences[workout_index][recipe_identity] = recipe_occurrence + 1
            cached_recipe = compiled_recipe_cache.get(compiled_cache_key)
            if cached_recipe is not None:
                recipe = copy.deepcopy(cached_recipe)
                recipe.update(sourceSignatureOccurrence=source_signature_occurrence,
                    sourcePositions=source_positions, memberOrder=member_order,
                    supersetOrigin='code_generated' if generated else 'source',
                    occurrence=recipe_occurrence)
                recipes.append(recipe)
                superset_candidates['compileCacheHits'] += 1
                if generated:
                    superset_candidates['compiledCandidateCount'] += 1
                continue
            superset_candidates['uniqueRecipeCompileCount'] += 1
            bounds = [approved_work_set_bounds(item, definitions[item['definition_id']], requirements) for item in block]
            lower, upper = max(b['minimum'] for b in bounds), min(b['maximum'] for b in bounds)
            exact = {item['numWorkSets'] for item in block if item.get('targetSetPrescriptions')}
            if exact:
                if len(exact) != 1:
                    rejected.append({'code': 'incompatible_exact_group_counts'})
                    continue
                lower, upper = max(lower, next(iter(exact))), min(upper, next(iter(exact)))
            options = []
            for count in range(lower, upper + 1):
                for variant in _rest_options(block, requirements, definitions, count):
                    items = copy.deepcopy(variant)
                    for item, bound in zip(items, bounds):
                        item.update(numWorkSets=count, allocationBounds=bound)
                        item.setdefault('setupSeconds', ASSUMPTIONS['transitionSeconds'])
                    day = {'name': 'Recipe', 'description': 'Prescription option', 'timesCompletedInAWeek': 1,
                           'exercises': items}
                    draft = {'requirementsId': 'recipe', 'name': 'Recipe', 'workouts': [day]}
                    try:
                        _DRAFT_VALIDATOR.validate(draft)
                        plan, report = _audit_raw(draft, equipment, requirements, restriction_policy,
                            allow_educated_load_guesses, apply_family_bounds=False,
                            execution_definitions=execution_definitions)
                        apply_native_load_calibration_policy(plan, messages or [], equipment,
                            getattr(training_history, 'fingerprint', None),
                            allow_educated_load_guesses=allow_educated_load_guesses)
                        audit_execution_rules(draft, requirements, report, plan)
                        details = {'issues': [], 'errors': []}
                        audit_execution_details(draft, requirements, details)
                        report['errors'].extend(e for e in details['errors'] if not e['code'].startswith('schedule_'))
                    except (ValueError, ValidationError) as error:
                        rejected.append({'code': 'invalid_recipe', 'message': getattr(error, 'message', str(error))})
                        continue
                    # A single recipe supplies coverage contributions; the joint model and final
                    # audit enforce complete session/weekly coverage, not this recipe screen.
                    blockers = [error for error in report['errors']
                        if error['code'] not in numeric_errors and error['code'] not in (
                            'required_coverage_missing', 'required_coverage_weekly_sets_below_minimum',
                            'required_coverage_sessions_below_minimum')]
                    if blockers:
                        rejected.extend(blockers)
                        continue
                    if validate_loads:
                        load_errors = validate_loads(plan)
                        if load_errors:
                            rejected.extend(load_errors)
                            continue
                    unknown_volume_preferences.update(_unknown_volume_preference_targets(report, requirements))
                    workout = report['workouts'][0]
                    options.append({'items': items, 'count': count, 'volume': workout['volume'],
                        'coverage': workout.get('coverageSets', {}),
                        'seconds': workout['estimatedSeconds'] - ASSUMPTIONS['generalWarmupSeconds']})
            if options:
                recipes.append({'options': options,
                    'setup': options[0]['items'][0].get('setupSeconds', ASSUMPTIONS['transitionSeconds']),
                    'signature': signature, 'sourceSignatureOccurrence': source_signature_occurrence,
                    'sourcePositions': source_positions, 'memberOrder': member_order,
                    'supersetOrigin': 'code_generated' if generated else 'source',
                    'identity': recipe_identity, 'occurrence': recipe_occurrence,
                    'roles': set().union(*(set(item.get('satisfiesCoverage', [])) for item in block)),
                    'orderPriority': execution_block_priority([definitions[item['definition_id']] for item in block]),
                    'definitions': {item['definition_id'] for item in block},
                    'definitionRecords': [copy.deepcopy(definitions[item['definition_id']]) for item in block]})
                for option in recipes[-1]['options']:
                    option['setupProfiles'] = [setup_resource_profile(definitions[item['definition_id']], item)
                        for item in option['items']]
                    option['setupTaskKeys'] = frozenset(json.dumps(profile['preparationTaskKey'],
                        sort_keys=True, separators=(',', ':')) for profile in option['setupProfiles'])
                recipe_roles = recipes[-1]['roles']
                recipes[-1]['interferencePerRound'] = execution_interference_profile(
                    [definitions[item['definition_id']] for item in block], [1] * len(block), recipe_roles, requirements)
                recipes[-1]['setupResources'] = equipment_setup_resources(
                    [definitions[item['definition_id']] for item in block])
                compiled_recipe_cache[compiled_cache_key] = copy.deepcopy(recipes[-1])
                if generated:
                    superset_candidates['compiledCandidateCount'] += 1
            elif generated and len(superset_candidates['rejectedCandidates']) < 100:
                superset_candidates['rejectedCandidates'].append({'workoutIndex': workout_index,
                    'sourcePositions': copy.deepcopy(source_positions),
                    'definitionIds': [item['definition_id'] for item in block],
                    'reason': 'no_executable_prescription_option'})
    proof['supersetCandidates'] = copy.deepcopy(superset_candidates)
    available_roles = {role for recipe in recipes for option in recipe['options']
        for role, exposure in option['coverage'].items() if exposure}
    available_roles.update(role for day in fixed_source_workouts for item in day.get('exercises', [])
        for role in item.get('satisfiesCoverage', []))
    missing_roles = {rule['key'] for rule in requirements.get('requiredCoverage', [])} - available_roles
    blocked_execution = [error for error in unresolved_execution.values()
        if not recipes or missing_roles & set(error['roles'])]
    if blocked_execution:
        return {**proof, 'feasible': False, 'status': 'execution_semantics_unresolved',
            'errors': blocked_execution, 'rejectedOptions': rejected[:20],
            'userQuestion': {
                'question': ('The required movement needs an explicit execution and rep/time counting basis. '
                    'Is a logged set one complete sequence with total reps/time, or is the prescription repeated per side/direction?'),
                'options': ['One complete sequence; reps/time are total',
                    'Repeat prescribed reps/time on each side or direction'],
                'executionChoices': [{'definition_id': error['definition_id'],
                    'canonicalDefinitionId': error['canonicalDefinitionId'], 'path': error['path']}
                    for error in blocked_execution]},
            'instruction': ('Resolve the qualitative execution choice through record_planning_decisions with source provenance; '
                'do not retry numeric prescriptions, assume personal capability, or claim the approved requirements are infeasible.')}
    if not recipes:
        return {**proof, 'feasible': False, 'status': 'invalid_options', 'rejectedOptions': rejected[:20],
                'instruction': 'No executable prescription options remain. Correct the supplied recipes; preserve approved requirements.'}

    # Demand properties inform selection only after each submitted recipe has at
    # least one executable prescription. Invalid or unusable menu entries cannot
    # disable the evidence gate for choices the solver can actually make.
    selectable_references = set().union(*(recipe['definitions'] for recipe in recipes))
    selectable_definitions = [definitions[reference] for reference in sorted(selectable_references)]
    demand_inputs = demand_distribution_inputs(selectable_definitions)
    for key, group in demand_inputs.get('groups', {}).items():
        merged_present_ids = set(group.get('presentDefinitionIds', [])) | set(fixed_present_ids.get(key, []))
        group['presentDefinitionIds'] = sorted(merged_present_ids)
        for reference, definition in definitions.items():
            if definition['id'] in fixed_present_ids.get(key, []):
                group.setdefault('evidenceByDefinition', {})[definition['id']] = \
                    definition_demand_facts(definition)[key]['source']
        demand_present_refs[key] = ({reference for reference, definition in definitions.items()
            if definition['id'] in merged_present_ids} | merged_present_ids)
    proof['demandDistribution'] = _demand_distribution_summary(
        [], fixed_source_workouts, demand_inputs, definitions,
        objective_requested='demand_distribution' in (requirements.get('objectiveOrder') or []),
        fixed_unavailable_groups=fixed_unavailable_groups)

    day_blocks, option_variables = [], []
    execution_costs, execution_evidence = {}, []
    for day_index, day in enumerate(sessions):
        blocks, blocks_by_source = [], {}
        for recipe_index, recipe in enumerate(recipes):
            if (preserve_source_selection and not redistribution_constraints
                    and any(position[0] != day_index for position in recipe['sourcePositions'])):
                continue
            allowed_options = recipe['options']
            if _fixed_session_work is not None:
                fixed_counts = _fixed_session_work[day_index]
                allowed_options = [option for option in allowed_options
                    if all(sum(item['numWorkSets'] for item in option['items']
                        if item['definition_id'] == reference) <= fixed_counts.get(definitions[reference]['id'], 0)
                        for reference in recipe['definitions'])]
            if not allowed_options:
                continue
            indices = []
            for option in allowed_options:
                index = variable(domain_identity={
                    'kind': 'recipe_option', 'workoutIndex': day_index,
                    'sourcePositions': recipe['sourcePositions'],
                    'definitionIds': list(recipe['identity']),
                    'workSetCount': option['count'], 'volume': option['volume'],
                    'coverage': option['coverage'], 'seconds': option['seconds'],
                })
                indices.append(index)
                option_variables.append((index, day_index, recipe_index, option))
            constraint(('recipe_choice', day_index, recipe_index), 0, 1, dict.fromkeys(indices, 1))
            source_key = (recipe['signature'], recipe['sourceSignatureOccurrence'])
            block = blocks_by_source.get(source_key)
            if block is None:
                block = {'options': [], 'recipeIndexes': [], 'recipe': recipe,
                         'setup': recipe['setup']}
                blocks_by_source[source_key] = block
                blocks.append(block)
            elif (block['recipe']['identity'] != recipe['identity'] or block['setup'] != recipe['setup']
                  or block['recipe']['roles'] != recipe['roles']
                  or block['recipe']['orderPriority'] != recipe['orderPriority']
                  or block['recipe']['definitions'] != recipe['definitions']):
                return {**proof, 'feasible': False, 'status': 'invalid_options',
                    'instruction': 'A physical source-block key merged incompatible movement, setup or role data. Preserve the input; no infeasibility was established.'}
            block['options'].extend(indices)
            block['recipeIndexes'].append(recipe_index)
            # Repeated count/rest alternatives share a single presence and first-use variable.
            block['optionsByRecipe'] = block.get('optionsByRecipe', {})
            block['optionsByRecipe'][recipe_index] = indices
            block['optionValues'] = block.get('optionValues', {})
            block['optionValues'].update(zip(indices, allowed_options))
            block.setdefault('optionRecipes', {}).update(dict.fromkeys(indices, recipe))
        missing_source_keys = set(source_blocks[day_index]) - set(blocks_by_source)
        if preserve_source_selection and missing_source_keys and _fixed_session_work is None:
            missing = [{'workoutIndex': day_index,
                'sourcePositions': copy.deepcopy(source_blocks[day_index][key][1])}
                for key in sorted(missing_source_keys)]
            return {**proof, 'feasible': False, 'status': 'invalid_options',
                'errors': [{'code': 'submitted_block_without_executable_options', **entry} for entry in missing],
                'instruction': ('At least one submitted movement block has no executable prescription option. '
                    'The preserved-selection solve did not omit or replace it; correct that block or request an explicit structural alternative.')}
        for block_index, block in enumerate(blocks):
            choice = {index: 1 for index in block['options']}
            source_key = (block['recipe']['signature'], block['recipe']['sourceSignatureOccurrence'])
            source_block = source_key in source_blocks[day_index]
            if preserve_source_selection and not redistribution_constraints:
                # Preserve source occurrences, while allowing compatible grouping to change.
                selected_bounds = (0, 1)
            elif preserve_source_selection:
                selected_bounds = (1, 1) if source_block else (0, 0)
            else:
                selected_bounds = (0, 1)
            constraint(('physical_block_choice', day_index, block_index), *selected_bounds, choice)
        positions_used = sorted({tuple(position) for block in blocks
            for position in block['recipe']['sourcePositions']})
        for source_position in positions_used:
            consuming_options = [option for block in blocks
                if source_position in {tuple(position) for position in block['recipe']['sourcePositions']}
                for option in block['options']]
            retained_occurrence = (preserve_source_selection and not redistribution_constraints
                and source_position[0] == day_index)
            constraint(('source_occurrence_use', day_index, *source_position),
                1 if retained_occurrence else -math.inf, 1,
                dict.fromkeys(consuming_options, 1))
        for reference in sorted(set().union(*(r['definitions'] for r in recipes))):
            inventory = max(sum(item['definition_id'] == reference for item in source['exercises']) for source in sessions)
            constraint(('movement_inventory', day_index, reference), 0, inventory,
                {i: 1 for b in blocks if reference in b['recipe']['definitions'] for i in b['options']})
        day_options = [(index, option) for index, option_day, _, option in option_variables
                       if option_day == day_index]
        session_caps = session_work_set_caps(
                [item for _, option in day_options for item in option['items']],
                definitions, requirements)
        for reference, maximum in session_caps.items():
            coefficients = {index: sum(item['numWorkSets'] for item in option['items']
                                      if item['definition_id'] == reference)
                            for index, option in day_options
                            if any(item['definition_id'] == reference for item in option['items'])}
            constraint(('exercise_session_work_sets', day_index, reference),
                       -math.inf, maximum, coefficients)
        for limit_name, coefficient in (
                ('maximumExercises', lambda option: len(option['items'])),
                ('maximumSupersets', lambda option: int(len(option['items']) > 1))):
            limit = structure_limits.get(limit_name)
            if limit is not None:
                coefficients = {index: coefficient(option)
                    for index, option_day, _, option in option_variables
                    if option_day == day_index and coefficient(option)}
                constraint(('session_structure', limit_name, day_index), -math.inf, limit, coefficients)
        blocks = _quotient_execution_blocks(blocks, session_caps)
        day_blocks.append(blocks)
        if _fixed_session_work is not None:
            for canonical_id, count in _fixed_session_work[day_index].items():
                constraint(('execution_selected_work', day_index, canonical_id), count, count,
                    {index: sum(item['numWorkSets'] for item in option['items']
                        if definitions[item['definition_id']]['id'] == canonical_id)
                        for index, option_day, _, option in option_variables if option_day == day_index})
        if _selection_only:
            _add_selection_order_feasibility(blocks, requirements, variable, constraint, day_index)
            execution_evidence.append({'anatomyComplete': False,
                'setupTransitionsComplete': False, 'resourceReferencesComplete': False})
            continue
        for block_index, block in enumerate(blocks):
            block['first'] = variable(domain_identity={'kind': 'first_block', 'workoutIndex': day_index,
                'definitionIds': list(block['recipe']['identity']),
                'sourceVariantCount': len(block['sourceVariantIndexes']),
                'coverageRoles': sorted(block['recipe']['roles'])})
            constraint(('first_selected', day_index, block_index), -math.inf, 0,
                {block['first']: 1, **dict.fromkeys(block['options'], -1)})
        constraint(('first_block', day_index), 1, 1, {b['first']: 1 for b in blocks})
        sequence_costs, sequence_evidence = _add_execution_sequence(blocks, requirements,
            variable, constraint, day_index, day['timesCompletedInAWeek'], session_caps)
        for name, coefficients in sequence_costs.items():
            execution_costs.setdefault(name, {}).update(coefficients)
        execution_evidence.append(sequence_evidence)

    base_report = None
    if existing:
        _, base_report = _audit_raw(existing, equipment, requirements, restriction_policy,
            allow_educated_load_guesses, execution_definitions=execution_definitions)
        unknown_volume_preferences.update(_unknown_volume_preference_targets(base_report, requirements))
    volume_target_evidence_status = 'unavailable_evidence' if unknown_volume_preferences else 'available'
    if 'volume_target' in (requirements.get('objectiveOrder') or []):
        proof['volumeTargetEvidence'] = {'status': volume_target_evidence_status,
            'unknownMuscles': sorted(unknown_volume_preferences),
            'scope': 'executable_candidate_menu_and_fixed_workouts'}
    targets = requirements['auditTargets']
    volume_target_costs = {}
    for scope, key in (('weekly', 'weeklyEffectiveSets'), ('session', 'perSessionEffectiveSets')):
        for muscle, bounds in targets.get(key, {}).items():
            for day_index in ([None] if scope == 'weekly' else range(len(sessions))):
                coefficients = {i: option['volume'][muscle]['effective'] * (
                    sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                    for i, d, _, option in option_variables if day_index is None or d == day_index}
                intercept = base_report['weeklyVolume'][muscle]['effective'] if base_report and day_index is None else 0
                constraint((scope, day_index, muscle), *volume_target_bounds(bounds), coefficients, intercept)
                if ('volume_target' in (requirements.get('objectiveOrder') or [])
                        and not unknown_volume_preferences
                        and 'preferredMinimum' in bounds):
                    for side, bound in zip(('minimum', 'maximum'), preferred_volume_target_bounds(bounds)):
                        if not math.isfinite(bound):
                            continue
                        sign = -1 if side == 'minimum' else 1
                        offset = sign * (intercept - bound)
                        upper = max(0, offset) + sum(max(0, sign * value) for value in coefficients.values())
                        deviation = variable(upper=upper, integer=False,
                            domain_identity={'kind': 'volume_target_deviation', 'scope': scope,
                                'workoutIndex': day_index, 'muscle': muscle, 'bound': side})
                        volume_target_costs[deviation] = 1
                        constraint(('volume_target', scope, day_index, muscle, side), -math.inf, 0,
                            {**{index: sign * value for index, value in coefficients.items()}, deviation: -1}, offset)
            if (scope == 'session' and base_report
                    and not unknown_volume_preferences
                    and 'volume_target' in (requirements.get('objectiveOrder') or [])
                    and 'preferredMinimum' in bounds):
                fixed_cost = sum(volume_preference_deviation(
                    day['volume'][muscle]['effective'], bounds) for day in base_report.get('workouts', []))
                if fixed_cost:
                    fixed_deviation = variable(lower=fixed_cost, upper=fixed_cost, integer=False,
                        domain_identity={'kind': 'fixed_volume_target_deviation', 'muscle': muscle})
                    volume_target_costs[fixed_deviation] = 1
    for rule in requirements.get('requiredCoverage', []):
        for day_index in ([None] if rule['scope'] == 'weekly' else range(len(sessions))):
            coefficients = {i: option['coverage'].get(rule['key'], 0) * (
                sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                for i, d, _, option in option_variables if day_index is None or d == day_index}
            intercept = (base_report.get('weeklyCoverageSets', {}).get(rule['key'], 0)
                         if base_report and day_index is None else 0)
            constraint(('coverage', day_index, rule['key']), 1, math.inf, coefficients, intercept)
        weekly_minimum = rule.get('minimumWeeklySets')
        if weekly_minimum is not None:
            coefficients = {index: option['coverage'].get(rule['key'], 0)
                * sessions[day_index]['timesCompletedInAWeek']
                for index, day_index, _, option in option_variables
                if option['coverage'].get(rule['key'], 0)}
            intercept = (base_report or {}).get('weeklyCoverageSets', {}).get(rule['key'], 0)
            constraint(('coverage_minimum_weekly_sets', rule['key']), weekly_minimum,
                math.inf, coefficients, intercept)
        minimum_sessions = rule.get('minimumSessions')
        if minimum_sessions is not None:
            fixed_sessions = sum(workout.get('timesCompletedInAWeek', 1)
                for workout, audited in zip(fixed_source_workouts,
                    (base_report or {}).get('workouts', []))
                if audited.get('coverageSets', {}).get(rule['key'], 0) > 0)
            session_coefficients = {}
            for day_index, blocks in enumerate(day_blocks):
                covered_options = [index for block in blocks for index in block['options']
                    if block['optionValues'][index]['coverage'].get(rule['key'], 0)]
                covered_blocks = sum(any(block['optionValues'][index]['coverage'].get(rule['key'], 0)
                    for index in block['options']) for block in blocks)
                if not covered_options:
                    continue
                active = variable(domain_identity={'kind': 'coverage_session_active',
                    'role': rule['key'], 'workoutIndex': day_index})
                session_coefficients[active] = sessions[day_index]['timesCompletedInAWeek']
                constraint(('coverage_session_active_requires_selected', rule['key'], day_index),
                    0, math.inf, {**dict.fromkeys(covered_options, 1), active: -1})
                constraint(('coverage_session_active_requires_coverage', rule['key'], day_index),
                    -math.inf, 0, {**dict.fromkeys(covered_options, 1), active: -covered_blocks})
            constraint(('coverage_minimum_sessions', rule['key']),
                minimum_sessions, math.inf, session_coefficients, fixed_sessions)
    duration_expressions = []
    if targets.get('maximumSessionSeconds') is not None or any(
            name in (requirements.get('objectiveOrder') or []) for name in ('duration_balance', 'duration_economy', 'time_budget')):
        for day_index, blocks in enumerate(day_blocks):
            coefficients = {i: option['seconds'] for i, d, _, option in option_variables if d == day_index}
            duration_expressions.append((coefficients, ASSUMPTIONS['generalWarmupSeconds']))
            if targets.get('maximumSessionSeconds') is not None:
                constraint(('duration', day_index), -math.inf, targets['maximumSessionSeconds'], coefficients,
                           ASSUMPTIONS['generalWarmupSeconds'])
    duration_costs = {}
    time_budget_costs = {}
    preferred_seconds = requirements.get('preferredSessionSeconds')
    if 'time_budget' in (requirements.get('objectiveOrder') or []) and preferred_seconds is not None:
        for day_index, (coefficients, intercept) in enumerate(duration_expressions):
            upper = max(0, intercept + sum(coefficients.values()) - preferred_seconds)
            excess = variable(upper=upper, integer=False,
                domain_identity={'kind': 'time_budget_excess', 'workoutIndex': day_index})
            constraint(('time_budget', day_index), -math.inf, preferred_seconds,
                {**coefficients, excess: -1}, intercept)
            time_budget_costs[excess] = sessions[day_index]['timesCompletedInAWeek']
        fixed_excess = sum(max(0, workout['estimatedSeconds'] - preferred_seconds)
            * source.get('timesCompletedInAWeek', 1)
            for workout, source in zip((base_report or {}).get('workouts', []), fixed_source_workouts))
        if fixed_excess:
            fixed = variable(lower=fixed_excess, upper=fixed_excess, integer=False,
                domain_identity={'kind': 'time_budget_excess', 'scope': 'fixed_workouts'})
            time_budget_costs[fixed] = 1
    if 'duration_economy' in (requirements.get('objectiveOrder') or []):
        for day_index, (coefficients, _) in enumerate(duration_expressions):
            for index, value in coefficients.items():
                duration_costs[index] = value * sessions[day_index]['timesCompletedInAWeek']
    duration_balance_costs = {}
    if 'duration_balance' in (requirements.get('objectiveOrder') or []):
        duration_expressions.extend(({}, workout['estimatedSeconds'])
            for workout in (base_report or {}).get('workouts', []))
        if len(duration_expressions) > 1:
            upper = max(intercept + sum(max(0, value) for value in coefficients.values())
                        for coefficients, intercept in duration_expressions)
            longest = variable(upper=upper, integer=False,
                domain_identity={'kind': 'duration_balance_bound', 'bound': 'maximum'})
            shortest = variable(upper=upper, integer=False,
                domain_identity={'kind': 'duration_balance_bound', 'bound': 'minimum'})
            for index, (coefficients, intercept) in enumerate(duration_expressions):
                constraint(('duration_balance', index, 'maximum'), -math.inf, 0,
                    {**coefficients, longest: -1}, intercept)
                constraint(('duration_balance', index, 'minimum'), -math.inf, 0,
                    {**{key: -value for key, value in coefficients.items()}, shortest: 1}, -intercept)
            tolerance_seconds = requirements.get('durationBalanceToleranceSeconds', 0)
            if tolerance_seconds:
                excess = variable(upper=upper, integer=False,
                    domain_identity={'kind': 'duration_balance_excess'})
                constraint(('duration_balance', 'tolerance'), -math.inf, tolerance_seconds,
                    {longest: 1, shortest: -1, excess: -1})
                duration_balance_costs = {excess: 1}
            else:
                duration_balance_costs = {longest: 1, shortest: -1}
    # Distribution is concentration of effective muscle work across training
    # occasions, so splitting one session's dose across recipe variants must not
    # change its score. Fixed existing workouts contribute to both the weekly
    # average and its deviation cost when solving only the remaining sessions.
    distribution_costs = {}
    distribution_worst_costs = {}
    total_training_occurrences = frequency
    if total_training_occurrences:
        base_weekly_volume = (base_report or {}).get('weeklyVolume', {})
        fixed_workouts = (base_report or {}).get('workouts', [])
        muscles = set(targets.get('weeklyEffectiveSets', {})) | set(targets.get('perSessionEffectiveSets', {}))
        for muscle in sorted(muscles):
            weekly_intercept = base_weekly_volume.get(muscle, {}).get('effective', 0)
            # Scale by twice the weekly occurrence count. Effective-set credits
            # are integral or half-integral, so all solver coefficients remain
            # integral even though deviation variables use the integer domain.
            weekly_coefficients = {index: (sessions[day_index]['timesCompletedInAWeek']
                * option['volume'].get(muscle, {}).get('effective', 0))
                for index, day_index, _, option in option_variables}
            for day_index, day in enumerate(sessions):
                coefficients = {index: -2 * value for index, value in weekly_coefficients.items()}
                for index, option_day, _, option in option_variables:
                    if option_day == day_index:
                        coefficients[index] += 2 * total_training_occurrences * option['volume'].get(
                            muscle, {}).get('effective', 0)
                intercept = -2 * weekly_intercept
                upper = sum(abs(value) for value in coefficients.values()) + abs(intercept)
                deviation = variable(upper=upper, domain_identity={'kind': 'distribution_deviation',
                    'muscle': muscle, 'workoutIndex': day_index, 'fixed': False})
                distribution_costs[deviation] = day['timesCompletedInAWeek']
                for sign in (-1, 1):
                    constraint(('distribution_deviation', muscle, day_index, sign), -math.inf, 0,
                        {**{index: sign * value for index, value in coefficients.items()}, deviation: -1},
                        sign * intercept)
            for workout_index, workout in enumerate(fixed_workouts):
                session_volume = workout.get('volume', {}).get(muscle, {}).get('effective', 0)
                coefficients = {index: -2 * value for index, value in weekly_coefficients.items()}
                intercept = 2 * (total_training_occurrences * session_volume - weekly_intercept)
                upper = sum(abs(value) for value in coefficients.values()) + abs(intercept)
                deviation = variable(upper=upper, domain_identity={'kind': 'distribution_deviation',
                    'muscle': muscle, 'workoutIndex': workout_index, 'fixed': True})
                distribution_costs[deviation] = workout.get('timesCompletedInAWeek', 1)
                for sign in (-1, 1):
                    constraint(('distribution_deviation', muscle, 'fixed', workout_index, sign), -math.inf, 0,
                        {**{index: sign * value for index, value in coefficients.items()}, deviation: -1},
                        sign * intercept)
        if distribution_costs:
            worst = variable(upper=max(variables[index]['upper'] for index in distribution_costs),
                domain_identity={'kind': 'distribution_peak'})
            distribution_worst_costs[worst] = 1
            for deviation in distribution_costs:
                constraint(('distribution_peak', deviation), -math.inf, 0,
                    {deviation: 1, worst: -1})
    development_roles = sorted(rule['key'] for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') == 'development')
    development_emphasis_costs = {}
    development_exposure_costs = {}
    development_exposure_upper = None
    if development_roles:
        fixed_coverage = (base_report or {}).get('weeklyCoverageSets', {})
        maximum_by_role = {}
        for role in development_roles:
            maximum_by_role[role] = fixed_coverage.get(role, 0) + sum(
                max((block['optionValues'][index]['count']
                     * block['optionValues'][index]['coverage'].get(role, 0)
                     * sessions[day_index]['timesCompletedInAWeek']
                     for index in block['options']), default=0)
                for day_index, blocks in enumerate(day_blocks) for block in blocks)
        development_exposure_upper = min(maximum_by_role.values(), default=0)
        deficit = variable(upper=development_exposure_upper, lower=0,
            domain_identity={'kind': 'development_exposure_deficit', 'roleKeys': development_roles})
        development_emphasis_costs[deficit] = 1
        for role in development_roles:
            coefficients = {index: option['coverage'].get(role, 0)
                * sessions[day_index]['timesCompletedInAWeek']
                for index, day_index, _, option in option_variables
                if option['coverage'].get(role, 0)}
            constraint(('development_emphasis', role), development_exposure_upper, math.inf,
                {**coefficients, deficit: 1}, fixed_coverage.get(role, 0))
        for index, day_index, _, option in option_variables:
            combined_exposure = sum(option['coverage'].get(role, 0) for role in development_roles)
            if combined_exposure:
                development_exposure_costs[index] = (
                    -combined_exposure * sessions[day_index]['timesCompletedInAWeek'])
    demand_distribution_costs = {}
    fixed_demand_exposure = {key: [sum(item.get('numWorkSets', 0)
            for item in day.get('exercises', [])
            if item.get('definition_id') in refs)
        for day in fixed_source_workouts]
        for key, refs in demand_present_refs.items()}
    for key, refs in demand_present_refs.items():
        option_day_by_index = {index: day_index for index, day_index, _, _ in option_variables}
        option_exposures = {index: option['count'] * sum(
            item['definition_id'] in refs for item in option['items'])
            for index, _, _, option in option_variables
            if any(item['definition_id'] in refs for item in option['items'])}
        if not option_exposures:
            continue
        fixed_peak = max(fixed_demand_exposure[key], default=0)
        peak_upper = fixed_peak + sum(option_exposures.values())
        peak = variable(upper=peak_upper, lower=fixed_peak,
            domain_identity={'kind': 'demand_distribution_peak', 'group': key})
        demand_distribution_costs[peak] = 1
        for day_index in range(len(sessions)):
            coefficients = {index: exposure for index, exposure in option_exposures.items()
                if option_day_by_index[index] == day_index}
            if coefficients:
                constraint(('demand_distribution_peak', key, day_index), -math.inf, 0,
                    {**coefficients, peak: -1})
    balance_rules = [rule for rule in requirements.get('executionRules', []) if rule['kind'] == 'coverageBalance']
    balance_costs = {}
    for rule_index, rule in enumerate(balance_rules):
        for day_index in ([None] if rule['scope'] == 'weekly' else range(len(sessions))):
            coefficients = {i: (option['coverage'].get(rule['first'], 0) - option['coverage'].get(rule['second'], 0))
                * (sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                for i, d, _, option in option_variables if day_index is None or d == day_index}
            intercept = ((base_report.get('weeklyCoverageSets', {}).get(rule['first'], 0)
                          - base_report.get('weeklyCoverageSets', {}).get(rule['second'], 0))
                         if base_report and day_index is None else 0)
            maximum = sum(abs(v) for v in coefficients.values()) + abs(intercept)
            deviation = variable(upper=maximum, domain_identity={'kind': 'coverage_balance_deviation',
                'ruleIndex': rule_index, 'scope': rule['scope'], 'workoutIndex': day_index,
                'first': rule['first'], 'second': rule['second']})
            balance_costs[deviation] = 1
            for sign in ((-1,) if rule.get('relationship') == 'first_not_less_than_second' else (-1, 1)):
                constraint(('coverage_balance', rule_index, day_index, sign), -math.inf, 0,
                           {**{i: sign * value for i, value in coefficients.items()}, deviation: -1}, sign * intercept)
    from .repair_contract import redistribution_recipe_signature, normalized_target_signature
    redistribution_peak_costs = {}
    for group_index, group in enumerate(redistribution_constraints or []):
        signature = group.get('recipeSignature')
        weekly_work_sets = group.get('weeklyWorkSets')
        if not isinstance(signature, str) or type(weekly_work_sets) is not int or weekly_work_sets < 1:
            return {**proof, 'feasible': False, 'status': 'invalid_options',
                'instruction': 'A typed redistribution constraint is malformed; preserve the candidate and report the constraint error.'}
        target_workouts = group.get('targetWorkoutIndexes')
        if (not isinstance(target_workouts, list)
                or any(type(index) is not int or index < 0 or index >= len(sessions)
                       for index in target_workouts)
                or len(set(target_workouts)) < 2):
            return {**proof, 'feasible': False, 'status': 'invalid_options',
                'instruction': 'A typed redistribution constraint has fewer than two distinct target sessions; preserve the repair evidence and revise the structural proposal.'}
        matching_options = [(index, day_index, option) for index, day_index, _, option in option_variables
            if len(option['items']) == 1
            and redistribution_recipe_signature(option['items'][0]) == signature]
        coefficients = {index: option['count'] * sessions[day_index]['timesCompletedInAWeek']
            for index, day_index, option in matching_options if day_index in target_workouts}
        if not coefficients:
            return {**proof, 'feasible': False, 'status': 'invalid_options',
                'instruction': 'A redistributed source recipe has no executable solver options; preserve the repair evidence and revise the structure.'}
        # The outcome contract covers the complete matching recipe family. A
        # target-only exact total is insufficient: a matching source occurrence
        # outside the explicit targets could otherwise survive unnoticed.
        outside_target_coefficients = {index: 1 for index, day_index, _ in matching_options
            if day_index not in target_workouts}
        if outside_target_coefficients:
            constraint(('redistribute_outside_targets', group_index), -math.inf, 0,
                outside_target_coefficients)
        constraint(('redistribute_work', group_index), weekly_work_sets, weekly_work_sets, coefficients)
        peak = variable(upper=weekly_work_sets, lower=1,
            domain_identity={'kind': 'redistribution_peak', 'groupIndex': group_index,
                'recipeSignature': signature, 'targetWorkoutIndexes': target_workouts})
        redistribution_peak_costs[peak] = 1
        for workout_index in target_workouts:
            session_coefficients = {index: option['count'] * len(option['items'])
                * sessions[day_index]['timesCompletedInAWeek']
                for index, day_index, recipe_index, option in option_variables
                if day_index == workout_index
                and len(option['items']) == 1
                and redistribution_recipe_signature(option['items'][0]) == signature}
            if session_coefficients:
                session_coefficients[peak] = -1
                constraint(('redistribute_peak', group_index, workout_index), -math.inf, 0,
                    session_coefficients)
        exact_targets = group.get('exactSetTargets')
        if exact_targets is not None:
            expected = Counter(normalized_target_signature(value) for value in exact_targets)
            for target_index, (target_value, target_count) in enumerate(sorted(expected.items())):
                target_coefficients = {}
                for index, day_index, recipe_index, option in option_variables:
                    if (day_index not in target_workouts or len(option['items']) != 1
                            or redistribution_recipe_signature(option['items'][0]) != signature):
                        continue
                    count = sum(
                        Counter(normalized_target_signature(value)
                            for value in (item.get('targetSetPrescriptions')
                                or [None] * item['numWorkSets']))[target_value]
                        for item in option['items'])
                    if count:
                        target_coefficients[index] = count
                constraint(('redistribute_target', group_index, target_index), target_count, target_count,
                    target_coefficients)
    required_roles = sorted({rule['key'] for rule in requirements.get('requiredCoverage', [])})
    role_intents = {rule['key']: rule.get('intent') for rule in requirements.get('requiredCoverage', [])}
    fixed_frequencies = [workout.get('timesCompletedInAWeek', 1) for workout in fixed_source_workouts]
    role_profiles, role_profile_index = [], {}
    for role in _role_concentration_keys(requirements):
        exposure_by_option = {index: option['coverage'].get(role, 0)
            for index, _, _, option in option_variables if option['coverage'].get(role, 0)}
        fixed_exposures = [sum(item.get('numWorkSets', 0) for item in workout.get('exercises', [])
            if role in item.get('satisfiesCoverage', [])) for workout in fixed_source_workouts]
        if not exposure_by_option and not any(fixed_exposures):
            continue
        qualified_definition_ids = tuple(sorted({item.get('definition_id')
            for _, _, _, option in option_variables for item in option['items']
            if role in item.get('satisfiesCoverage', [])} | {item.get('definition_id')
                for workout in fixed_source_workouts for item in workout.get('exercises', [])
                if role in item.get('satisfiesCoverage', [])}))
        signature = (qualified_definition_ids,
                     tuple(fixed_exposures), tuple(fixed_frequencies))
        if signature in role_profile_index:
            role_profiles[role_profile_index[signature]]['labels'].append(role)
            continue
        role_profile_index[signature] = len(role_profiles)
        role_profiles.append({'key': role, 'labels': [role], 'exposureByOption': exposure_by_option,
            'fixedExposures': fixed_exposures, 'fixedFrequencies': fixed_frequencies})
    role_concentration_costs = {}
    role_concentration_tiebreak_costs = {}
    role_peak = _add_peak_surplus_objective(variable, constraint, option_variables, sessions,
        role_profiles, 'role_concentration_peak')
    if role_peak is not None:
        role_concentration_costs[role_peak] = 1
        for profile_index, profile in enumerate(role_profiles):
            profile_peak = _add_peak_surplus_objective(variable, constraint, option_variables,
                sessions, [profile], 'role_concentration_profile_peak',
                profile_index_offset=profile_index)
            if profile_peak is not None:
                role_concentration_tiebreak_costs[profile_peak] = 1

    exercise_distribution_requested = 'exercise_distribution' in (requirements.get('objectiveOrder') or [])
    executable_references = {item['definition_id'] for _, _, _, option in option_variables
        for item in option['items']} | {item['definition_id'] for workout in fixed_source_workouts
        for item in workout.get('exercises', [])}
    all_family_evidence = reviewed_exercise_family_evidence(equipment)
    id_to_reference = {definition['id']: reference for reference, definition in definitions.items()}
    family_evidence = {'familyByReference': {}, 'sourcesByReference': {}, 'unclassifiedReferences': []}
    for reference in sorted(executable_references):
        canonical = reference if reference in definitions else id_to_reference.get(reference)
        if canonical in all_family_evidence['familyByReference']:
            family_evidence['familyByReference'][reference] = all_family_evidence['familyByReference'][canonical]
            family_evidence['sourcesByReference'][reference] = all_family_evidence['sourcesByReference'][canonical]
        else:
            family_evidence['unclassifiedReferences'].append(reference)
    execution_reference_by_reference = {reference: (reference if reference in definitions
        else id_to_reference.get(reference)) for reference in executable_references}
    execution_library_references = sorted({reference for reference in execution_reference_by_reference.values()
        if reference in definitions})
    all_execution_evidence = reviewed_execution_properties(equipment, execution_library_references)
    execution_properties_by_canonical = all_execution_evidence.get('propertiesByReference') or {}
    execution_by_reference = {reference: execution_properties_by_canonical[canonical]
        for reference, canonical in execution_reference_by_reference.items()
        if canonical in execution_properties_by_canonical}
    execution_unclassified = sorted(reference for reference, canonical in execution_reference_by_reference.items()
        if canonical not in execution_properties_by_canonical)
    execution_complementarity_costs, execution_complementarity_inventory = {}, {
        'verifiedComplementaryPairs': [], 'knownOtherModePairs': [], 'unresolvedPairs': []}
    if 'execution_complementarity' in (requirements.get('objectiveOrder') or []):
        execution_complementarity_costs, execution_complementarity_inventory = (
            _add_execution_complementarity_objective(variable, constraint, option_variables,
                sessions, required_roles, execution_by_reference))
    balance_target_muscles = set((requirements.get('auditTargets') or {}).get('weeklyEffectiveSets', {}))
    balance_target_muscles.update((requirements.get('auditTargets') or {}).get('perSessionEffectiveSets', {}))
    def balance_eligible(item):
        definition = definitions.get(item.get('definition_id')) or definitions_by_id.get(item.get('definition_id'))
        muscles = {muscle for muscle, tags in MUSCLES.items()
            if definition and tags & set(definition.get('muscleGroups', []))}
        return bool(set(item.get('satisfiesCoverage', [])) & set(required_roles)
            or muscles & balance_target_muscles)

    balance_pool_references = {item['definition_id'] for _, _, _, option in option_variables
        for item in option['items'] if balance_eligible(item)}
    fixed_balance_pool_references = {item.get('definition_id') for workout in fixed_source_workouts
        for item in workout.get('exercises', []) if balance_eligible(item)}
    balance_control_references = {reference for reference in balance_pool_references
        if execution_by_reference.get(reference, {}).get('balanceControl') is True}
    fixed_balance_control_references = {reference for reference in fixed_balance_pool_references
        if execution_by_reference.get(reference, {}).get('balanceControl') is True}
    balance_control_unknown_references = sorted(reference for reference in
        balance_pool_references | fixed_balance_pool_references
        if 'balanceControl' not in execution_by_reference.get(reference, {}))
    balance_control_costs = {}
    if ('balance_control' in (requirements.get('objectiveOrder') or [])
            and not fixed_balance_control_references):
        balance_control_costs = _add_balance_control_objective(variable, constraint,
            option_variables, sessions, balance_control_references, fixed_source_workouts)
    proof['executionSelection'] = {
        'complementarity': {'status': ('available' if execution_complementarity_costs else
            'candidate_menu_has_verified_pair' if execution_complementarity_inventory['verifiedComplementaryPairs'] else
            'unavailable_evidence' if execution_unclassified or execution_complementarity_inventory['unresolvedPairs']
                else 'no_applicable_options'),
            'evidenceScope': 'executable_candidate_menu_not_selected_plan',
            'propertyScope': 'reviewed_limb_form_only; ROM, muscle_length_and_joint_angle_complementarity_remain_unverified',
            **copy.deepcopy(execution_complementarity_inventory)},
        'sourcesByReference': {reference: copy.deepcopy(all_execution_evidence['sourcesByReference'][canonical])
            for reference, canonical in execution_reference_by_reference.items()
            if canonical in all_execution_evidence['sourcesByReference']},
        'balanceControl': {'status': ('satisfied_by_fixed_selection' if fixed_balance_control_references else
            'available' if balance_control_references else
            'unavailable_evidence' if balance_control_unknown_references else 'no_reviewed_eligible_candidates'),
            'eligibleDefinitionReferences': sorted(balance_control_references | fixed_balance_control_references),
            'unclassifiedDefinitionReferences': balance_control_unknown_references},
    }
    family_bound_errors = validate_family_set_bounds(
        requirements, all_family_evidence.get('familyByReference') or {})
    if family_bound_errors:
        return {**proof, 'feasible': False, 'status': 'invalid_options',
            'errors': family_bound_errors,
            'instruction': 'Approved family set bounds are invalid or refer to unreviewed families. Resolve the evidence or bounds before solving.'}
    family_bounds = requirements.get('familySetBounds') or []
    if family_bounds:
        fixed_family_sets = weekly_family_set_counts(
            fixed_source_workouts, family_evidence['familyByReference'])
        for bound in family_bounds:
            family = bound['exerciseFamilyId']
            coefficients = {index: option['count'] * sessions[day]['timesCompletedInAWeek']
                    * sum(family_evidence['familyByReference'].get(item['definition_id']) == family
                        for item in option['items'])
                for index, day, _, option in option_variables
                if any(family_evidence['familyByReference'].get(item['definition_id']) == family
                    for item in option['items'])}
            minimum = bound.get('minimumWeeklySets', 0)
            maximum = bound.get('maximumWeeklySets', math.inf)
            constraint(('family_weekly_sets', family), minimum, maximum, coefficients,
                fixed_family_sets.get(family, 0))
    exercise_exposure_rule = next((rule for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'exerciseExposure'), None)
    if exercise_exposure_rule:
        definition_id_by_reference = {reference: definition['id']
            for reference, definition in definitions.items()}
        definition_id_by_reference.update({definition['id']: definition['id']
            for definition in definitions.values()})
        executable_definition_ids = {definition_id_by_reference.get(item['definition_id'], item['definition_id'])
            for _, _, _, option in option_variables for item in option['items']}
        executable_definition_ids.update(definition_id_by_reference.get(item['definition_id'], item['definition_id'])
            for workout in fixed_source_workouts for item in workout.get('exercises', []))
        for definition_id in sorted(executable_definition_ids):
            if 'maximumWeeklySets' in exercise_exposure_rule:
                fixed_sets = sum(item.get('numWorkSets', 0)
                    * workout.get('timesCompletedInAWeek', 1)
                    for workout in fixed_source_workouts for item in workout.get('exercises', [])
                    if definition_id_by_reference.get(item.get('definition_id'), item.get('definition_id')) == definition_id)
                coefficients = {index: option['count'] * sessions[day_index]['timesCompletedInAWeek']
                    * sum(definition_id_by_reference.get(item['definition_id'], item['definition_id']) == definition_id
                        for item in option['items'])
                    for index, day_index, _, option in option_variables
                    if any(definition_id_by_reference.get(item['definition_id'], item['definition_id']) == definition_id
                        for item in option['items'])}
                constraint(('exercise_exposure_weekly_sets', definition_id), -math.inf,
                    exercise_exposure_rule['maximumWeeklySets'], coefficients, fixed_sets)
            if 'maximumSessionsPerWeek' in exercise_exposure_rule:
                fixed_sessions = sum(workout.get('timesCompletedInAWeek', 1)
                    for workout in fixed_source_workouts
                    if any(definition_id_by_reference.get(item.get('definition_id'), item.get('definition_id')) == definition_id
                        for item in workout.get('exercises', [])))
                session_coefficients = {}
                for day_index, day in enumerate(sessions):
                    matching_options = [index for index, option_day, _, option in option_variables
                        if option_day == day_index and any(
                            definition_id_by_reference.get(item['definition_id'], item['definition_id']) == definition_id
                            for item in option['items'])]
                    if not matching_options:
                        continue
                    active = variable(domain_identity={'kind': 'exercise_session_active',
                        'exerciseDefinitionId': definition_id, 'workoutIndex': day_index})
                    constraint(('exercise_session_active_requires_selected', definition_id, day_index),
                        -math.inf, 0, {active: 1, **{index: -1 for index in matching_options}})
                    constraint(('exercise_session_active_required_by_selected', definition_id, day_index),
                        -math.inf, 0, {**{index: 1 for index in matching_options}, active: -len(matching_options)})
                    session_coefficients[active] = day['timesCompletedInAWeek']
                constraint(('exercise_exposure_sessions', definition_id), -math.inf,
                    exercise_exposure_rule['maximumSessionsPerWeek'], session_coefficients, fixed_sessions)
    if exercise_distribution_requested:
        exercise_distribution_costs, exercise_distribution_profiles, exercise_distribution_peaks = (
            _add_exercise_distribution_objective(variable, constraint, option_variables, sessions,
                fixed_source_workouts, required_roles, family_evidence['familyByReference'], role_intents))
    else:
        exercise_distribution_costs, exercise_distribution_profiles, exercise_distribution_peaks = {}, [], []

    demand_union = demand_union_exposure_input(demand_inputs)
    demand_union_profile, demand_colocation_costs = None, {}
    if demand_union:
        union_ids = set(demand_union['presentDefinitionIds'])
        union_refs = {reference for reference, definition in definitions.items()
            if definition['id'] in union_ids} | union_ids
        exposure_by_option = {index: option['count'] * sum(
            item.get('definition_id') in union_refs for item in option['items'])
            for index, _, _, option in option_variables
            if any(item.get('definition_id') in union_refs for item in option['items'])}
        fixed_exposures = [sum(item.get('numWorkSets', 0) for item in workout.get('exercises', [])
            if item.get('definition_id') in union_refs) for workout in fixed_source_workouts]
        if exposure_by_option:
            demand_union_profile = {'key': 'verified_demand_union', 'exposureByOption': exposure_by_option,
                'fixedExposures': fixed_exposures, 'fixedFrequencies': fixed_frequencies}
            demand_peak = _add_peak_session_exposure_objective(variable, constraint, option_variables,
                sessions, demand_union_profile, 'demand_colocation_peak')
            if demand_peak is not None:
                demand_colocation_costs[demand_peak] = 1
    preferences, preservation_offset = _add_reviewed_dose_preservation_objective(
        variable, constraint, option_variables, sessions, reviewed_dose_reference)
    exercise_count_costs = {}
    exercise_count_evidence = {}
    if 'exercise_count' in (requirements.get('objectiveOrder') or []) and requirements.get('exerciseSelection'):
        from .programming_policy import qualified_exercise_ids_by_muscle, exercise_count_preference_facts
        preference = requirements['exerciseSelection']
        canonical = lambda definition: (definition.get('libraryDefinitionId') or definition.get('exerciseDefinitionId')
            or definition.get('definition_id') or definition.get('id'))
        domain_references = selectable_references | {item['definition_id']
            for day in fixed_source_workouts for item in day.get('exercises', [])}
        domain_definitions = [definitions[reference] for reference in domain_references]
        qualified = qualified_exercise_ids_by_muscle(domain_definitions)
        exercise_count_evidence = exercise_count_preference_facts(domain_definitions, requirements)
        fixed_ids = {canonical(definitions[item['definition_id']])
            for day in fixed_source_workouts for item in day.get('exercises', [])}
        active_by_definition = {}
        for identifier in set().union(*(qualified.get(muscle, set()) for muscle in preference['muscles'])):
            matching = [index for index, _, _, option in option_variables
                if any(canonical(definitions[item['definition_id']]) == identifier for item in option['items'])]
            active = variable(lower=int(identifier in fixed_ids),
                domain_identity={'kind': 'qualified_definition_active', 'definitionId': identifier})
            active_by_definition[identifier] = active
            for index in matching:
                constraint(('qualified_definition_active', identifier, index), -math.inf, 0, {index: 1, active: -1})
            if identifier not in fixed_ids:
                constraint(('qualified_definition_used', identifier), -math.inf, 0,
                    {active: 1, **dict.fromkeys(matching, -1)})
        for muscle in preference['muscles']:
            if exercise_count_evidence[muscle]['count'] is None:
                continue
            counts = {active_by_definition[identifier]: 1 for identifier in qualified.get(muscle, set())}
            for side, bound in (('minimum', preference['preferredMinimum']), ('maximum', preference['preferredMaximum'])):
                deviation = variable(upper=max(bound, len(counts)),
                    domain_identity={'kind': 'exercise_count_deviation', 'muscle': muscle, 'side': side})
                sign = -1 if side == 'minimum' else 1
                constraint(('exercise_count', muscle, side), -math.inf, sign * bound,
                    {**{index: sign for index in counts}, deviation: -1})
                exercise_count_costs[deviation] = 1
    features = constraints
    from .planning_tools import library_fingerprint
    library_hash = library_fingerprint(equipment)
    history_fingerprint = getattr(training_history, 'fingerprint', None)
    overlap_costs = {}
    if 'movement_overlap' in (requirements.get('objectiveOrder') or []):
        for day_index, day in enumerate(sessions):
            options = [(index, option) for index, option_day, _, option in option_variables
                       if option_day == day_index]
            pairs = overlapping_movement_pairs([item for _, option in options for item in option['items']],
                family_evidence['familyByReference'])
            active_by_reference = {}
            for reference in sorted({reference for pair in pairs for reference in pair}):
                matching = [index for index, option in options
                            if any(item['definition_id'] == reference for item in option['items'])]
                active = variable(domain_identity={'kind': 'movement_overlap_active',
                    'workoutIndex': day_index, 'definitionRef': reference})
                active_by_reference[reference] = active
                for index in matching:
                    constraint(('movement_overlap_active', day_index, reference, index),
                        -math.inf, 0, {index: 1, active: -1})
                constraint(('movement_overlap_used', day_index, reference),
                    -math.inf, 0, {active: 1, **dict.fromkeys(matching, -1)})
            for first, second in pairs:
                pair = variable(domain_identity={'kind': 'movement_overlap_pair',
                    'workoutIndex': day_index, 'definitionRefs': [first, second]})
                overlap_costs[pair] = day['timesCompletedInAWeek']
                constraint(('movement_overlap_pair', day_index, first, second),
                    -1, math.inf, {pair: 1, active_by_reference[first]: -1, active_by_reference[second]: -1})
                for reference in (first, second):
                    constraint(('movement_overlap_pair_selected', day_index, first, second, reference),
                        -math.inf, 0, {pair: 1, active_by_reference[reference]: -1})
    setup_costs = {}
    if 'setup_economy' in (requirements.get('objectiveOrder') or []):
        for day_index, blocks in enumerate(day_blocks):
            frequency = sessions[day_index]['timesCompletedInAWeek']
            tasks = sorted(set().union(*(option['setupTaskKeys']
                for block in blocks for option in block['optionValues'].values())))
            for task_key in tasks:
                options = [index for block in blocks for index, option in block['optionValues'].items()
                    if task_key in option['setupTaskKeys']]
                active = variable(domain_identity={'kind': 'preparation_task',
                    'workoutIndex': day_index, 'taskKey': json.loads(task_key)})
                setup_costs[active] = frequency
                for index in options:
                    constraint(('preparation_task', day_index, task_key, index),
                        -math.inf, 0, {index: 1, active: -1})
                constraint(('preparation_task_used', day_index, task_key),
                    -math.inf, 0, {active: 1, **dict.fromkeys(options, -1)})
    feasibility_domain_fingerprint = _joint_model_domain_fingerprint(
        variables, features, library_hash=library_hash, history_fingerprint=history_fingerprint,
        evidence=evidence, restriction_policy=restriction_policy,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=preserve_source_selection)
    proof.update(feasibilityDomainFingerprint=feasibility_domain_fingerprint)
    known_infeasible = (None if rejected else _known_infeasible_repair_domain(
        messages, feasibility_domain_fingerprint, library_hash, history_fingerprint))
    if known_infeasible:
        previous = known_infeasible['receipt']
        return {**proof, 'feasible': False, 'status': 'infeasible',
            'knownPriorInfeasibility': True,
            'knownInfeasibleDomainMatch': known_infeasible['match'],
            'recipeCount': sum(len(recipe['options']) for recipe in recipes),
            'optionCount': len(option_variables),
            'consideredConstraints': copy.deepcopy(previous.get('consideredConstraints', [])),
            'objectiveProgress': copy.deepcopy(previous.get('objectiveProgress', [])),
            **({'redistributionOptimization': copy.deepcopy(previous.get('redistributionOptimization'))}
                if redistribution_constraints else {}),
            'preserveSourceSelection': bool(preserve_source_selection),
            'selectionPolicyVersion': SELECTION_POLICY_VERSION,
            'instruction': ('This exact exercise-prescription feasibility domain was already proven infeasible for this saved alternative. '
                'Changing non-fixed numWorkSets seeds, labels or coaching text does not change the domain. Make a structural or '
                'prescription-domain change that alters the executable options, or use the explicit validated trade-off route; '
                'do not submit another count-only repair or claim the approved requirements are globally impossible.')}
    workload_costs = {index: option['count'] * len(option['items'])
        * sessions[day_index]['timesCompletedInAWeek']
        for index, day_index, _, option in option_variables}
    if any(not row['setupTransitionsComplete'] for row in execution_evidence):
        execution_costs['setup_economy_transitions'] = {}
    if any(not row['resourceReferencesComplete'] for row in execution_evidence):
        execution_costs['setup_economy_resource_switches'] = {}
    if any(not row['anatomyComplete'] for row in execution_evidence):
        execution_costs = {name: coefficients for name, coefficients in execution_costs.items()
            if not name.startswith('ordering_')}
    objective_costs = {**execution_costs, 'execution_order': {},
                       'time_budget': time_budget_costs, 'exercise_count': exercise_count_costs,
                       'demand_distribution': demand_distribution_costs, 'duration_balance': duration_balance_costs,
                       'duration_economy': duration_costs,
                       'movement_overlap': overlap_costs,
                       'superset_lower_body_overlap': {index: sessions[day_index]['timesCompletedInAWeek']
                           * superset_lower_body_pair_sets([definitions[item['definition_id']]
                               for item in option['items']], [option['count']] * len(option['items']))
                           for index, day_index, _, option in option_variables},
                       'source_balance': balance_costs, 'distribution': distribution_costs,
                       'exercise_distribution': exercise_distribution_costs,
                       'execution_complementarity': execution_complementarity_costs,
                       'balance_control': balance_control_costs,
                       'development_emphasis': development_emphasis_costs,
                       'development_exposure': development_exposure_costs,
                       'role_concentration': role_concentration_costs,
                       'role_concentration_tiebreak': role_concentration_tiebreak_costs,
                       'setup_economy': setup_costs,
                       'workload_economy': workload_costs, 'volume_target': volume_target_costs, 'preservation': preferences,
                       'distribution_worst': distribution_worst_costs}
    approved_order = requirements.get('objectiveOrder')
    objective_order = (list(approved_order) if approved_order is not None else
        ['preservation'] if reviewed_dose_reference is not None else [])
    objective_available = {name: bool(values) for name, values in objective_costs.items()}
    objective_available.update({
        'execution_order': ('execution_order' in (requirements.get('objectiveOrder') or [])
            and all(row['anatomyComplete'] for row in execution_evidence)),
        'movement_overlap': bool(overlap_costs) or any(objective_costs['superset_lower_body_overlap'].values()),
        'development_emphasis': bool(development_emphasis_costs),
        'development_exposure': bool(development_exposure_costs),
        'demand_colocation': bool(demand_colocation_costs),
        'role_concentration': bool(role_concentration_costs),
        'role_concentration_tiebreak': bool(role_concentration_tiebreak_costs),
        'exercise_distribution': bool(exercise_distribution_costs),
        'execution_complementarity': bool(execution_complementarity_costs)
            or bool(execution_complementarity_inventory['verifiedComplementaryPairs']),
        'balance_control': bool(balance_control_costs),
        'distribution_worst': bool(distribution_worst_costs),
    })
    if objective_available['execution_order']:
        from .programming_policy import execution_interference_metric_names
        objective_available.update({'ordering_' + name: True
            for name in execution_interference_metric_names(requirements)})
    ordered_names = _ordered_joint_objective_names(requirements, objective_available)
    development_family_costs = {peak: 1 for profile, peak in exercise_distribution_peaks
        if profile.get('intent') == 'development'}
    workload_precedes_family = ('workload_economy' in objective_order
        and 'exercise_distribution' in objective_order
        and objective_order.index('workload_economy') < objective_order.index('exercise_distribution'))
    ordered_goals = []
    for name in ordered_names:
        if name == 'exercise_distribution' and development_family_costs:
            ordered_goals.append(('exercise_distribution_development', development_family_costs))
        ordered_goals.append((name, {
        'development_emphasis': development_emphasis_costs,
        'development_exposure': development_exposure_costs,
        'demand_colocation': demand_colocation_costs,
        'role_concentration': role_concentration_costs,
        'role_concentration_tiebreak': role_concentration_tiebreak_costs,
        }.get(name, objective_costs.get(name, {}))))
    goal_coefficients = {name: coefficients for name, coefficients in objective_costs.items()
        if objective_available.get(name)}
    goal_offsets = {'duration_economy': sum(intercept * day['timesCompletedInAWeek']
        for (_, intercept), day in zip(duration_expressions, sessions))
        + sum(day['estimatedSeconds'] * source.get('timesCompletedInAWeek', 1)
            for day, source in zip((base_report or {}).get('workouts', []), fixed_source_workouts))}
    for rule in requirements.get('requiredCoverage', []):
        metric = 'coverage:' + rule['key']
        goal_coefficients[metric] = {index: -option['coverage'].get(rule['key'], 0)
            * sessions[day]['timesCompletedInAWeek'] for index, day, _, option in option_variables}
        goal_offsets[metric] = -(base_report or {}).get('weeklyCoverageSets', {}).get(rule['key'], 0)
    for muscle, bounds in targets.get('weeklyEffectiveSets', {}).items():
        if 'preferredMinimum' in bounds and muscle not in unknown_volume_preferences:
            goal_coefficients['weekly_effective_sets:' + muscle] = {
                index: -option['volume'][muscle]['effective'] * sessions[day]['timesCompletedInAWeek']
                for index, day, _, option in option_variables}
            goal_offsets['weekly_effective_sets:' + muscle] = -(base_report or {}).get(
                'weeklyVolume', {}).get(muscle, {}).get('effective', 0)
            goal_coefficients['weekly_volume:' + muscle] = {index: 1 for index, item in enumerate(variables)
                if (item.get('domainIdentity') or {}).get('kind') == 'volume_target_deviation'
                and item['domainIdentity'].get('scope') == 'weekly'
                and item['domainIdentity'].get('muscle') == muscle}
    if unknown_volume_preferences:
        goal_coefficients.pop('volume_target', None)
    try:
        tier_goals = _goal_programming_objectives(variable, constraint, variables,
            requirements, goal_coefficients, goal_offsets)
    except ValueError as error:
        return {**proof, 'feasible': False, 'status': 'goal_evidence_unavailable',
            'instruction': str(error), 'userQuestion': {'question': str(error), 'options': []}}
    goals = ([('redistribution_spread', redistribution_peak_costs)] if redistribution_peak_costs else []) + tier_goals + ordered_goals
    preservation_is_approved = approved_order is None or 'preservation' in objective_order
    role_concentration_planned = any(name == 'role_concentration' for name, _ in goals)
    if preferences and approved_order is not None and not preservation_is_approved:
        if role_concentration_planned:
            role_position = next(index for index, (name, _) in enumerate(goals)
                if name == 'role_concentration')
            goals.insert(role_position, ('dose_selection', preferences))
        else:
            goals.append(('neutral_preservation', preferences))
    if _selection_only:
        goals = list(itertools.takewhile(lambda goal: not _split_execution_goal(goal[0]),
            (goal for goal in goals if goal[0] != 'neutral_preservation')))
    for name, costs in goals:
        if _selection_prefix_bounds is not None and name in _selection_prefix_bounds:
            bound = _selection_prefix_bounds[name]
            lattice = math.lcm(bound.denominator, *(_rational(cost).denominator for cost in costs.values()))
            features.append((('selection_prefix_bound', name), -math.inf,
                int(bound * lattice), 0,
                {index: int(_rational(cost) * lattice) for index, cost in costs.items()}))
    chosen, stages, status = None, [], 'unproven'
    solver_diagnostics = []
    search_budget = {'limitSeconds': max(0, search_deadline - started),
        'scope': 'shared_search_including_model_preparation; final_audit_may_finish_after_deadline'}
    proof['searchBudget'] = search_budget

    def run_search(current, rows, *, diagnostics, incumbent=None, preserve_current=False,
                   stage_limit=_SOLVER_STAGE_SECONDS):
        remaining = max(0, search_deadline - time.monotonic())
        search_budget.update(remainingSeconds=remaining, exhausted=remaining <= 0)
        diagnostics['sharedBudgetRemainingSeconds'] = remaining
        if remaining <= 0:
            diagnostics.update(terminationStatus='NOT_RUN', returnReason='search_budget_exhausted',
                requestedBudgetSeconds=0, searchBudgetSeconds=0)
            return 'unproven', None
        return _cp_solve(current, rows, timeout_seconds=min(stage_limit, remaining),
            preserve_current=preserve_current, diagnostics=diagnostics,
            incumbent=incumbent, session=cp_session)

    def publish_progress(phase, objective):
        if progress is not None:
            progress({'status': 'optimizing', 'feasible': False, 'phase': phase,
                'activeObjective': objective, 'problemFingerprint': proof['problemFingerprint'],
                'jointModelFeasibleIncumbentAvailable': chosen is not None,
                'productionAuditPending': True, 'elapsedSeconds': time.monotonic() - started,
                'objectiveProgress': copy.deepcopy(stages),
                'solverDiagnostics': copy.deepcopy(solver_diagnostics)})

    def audit_hint(workouts):
        draft = {'name': 'Retained prescription hint', 'workouts': copy.deepcopy(fixed_source_workouts) + workouts}
        try:
            plan, report = _audit_raw(draft, equipment, requirements, restriction_policy,
                allow_educated_load_guesses, execution_definitions=execution_definitions)
            audit_execution_rules(draft, requirements, report, plan)
            audit_execution_details(draft, requirements, report)
            return not report['errors'] and (not validate_loads or not validate_loads(plan))
        except (ValueError, ValidationError):
            return False

    prescription_hint = None
    candidates = ([_prescription_seed] if _prescription_seed is not None else []) + (
        [reviewed_baseline_workouts] if reviewed_baseline_workouts is not None else [])
    for candidate in itertools.chain(candidates, _saved_prescription_seeds(messages), [sessions]):
        prescription_hint = _prescription_decision_hint(
            candidate, sessions, day_blocks, variables, requirements, audit_hint)
        if prescription_hint is not None:
            break
    proof['prescriptionWarmStart'] = {'status': 'native_audited_recipe_decision_hint'
        if prescription_hint is not None else 'no_matching_native_audited_source',
        'decisionCount': len(prescription_hint or {}), 'selectionFixed': _fixed_session_work is not None,
        'solverFeasibilityEstablished': False}

    development_budget = None
    if development_roles or variable_source_working_sets is not None:
        development_budget = {
            'status': 'applied' if variable_source_working_sets is not None else 'unbounded_by_user',
            'source': source_budget_source,
            'variableSourceWorkingSets': variable_source_working_sets,
            'fixedExistingWorkingSets': fixed_existing_working_sets,
            'sourceBudgetWeeklyWorkingSets': (variable_source_working_sets + fixed_existing_working_sets
                if variable_source_working_sets is not None else None),
            'variableMenuCapWorkingSets': variable_source_working_sets,
        }
    if variable_source_working_sets is not None:
        uncapped_features = features
        features = list(features)
        features.append((('development_source_budget', source_budget_source),
            -math.inf, variable_source_working_sets, 0, workload_costs))
        feasibility_variables = [{**variable, 'objectiveCost': 0} for variable in variables]
        diagnostic = {'goal': 'development_budget_feasibility'}
        publish_progress('stage_started', diagnostic['goal'])
        capped_status, capped_candidate = run_search(feasibility_variables, features,
            diagnostics=diagnostic, incumbent=prescription_hint)
        solver_diagnostics.append(diagnostic)
        stages.append({'goal': 'development_budget_feasibility', 'status': capped_status})
        publish_progress('stage_completed', diagnostic['goal'])
        if capped_candidate is None:
            diagnostic = {'goal': 'uncapped_hard_feasibility_diagnostic'}
            publish_progress('stage_started', diagnostic['goal'])
            uncapped_status, uncapped_candidate = run_search(feasibility_variables, uncapped_features,
                diagnostics=diagnostic, incumbent=prescription_hint)
            solver_diagnostics.append(diagnostic)
            stages.append({'goal': 'uncapped_hard_feasibility_diagnostic', 'status': uncapped_status,
                           'diagnosticOnly': True})
            publish_progress('stage_completed', diagnostic['goal'])
            if uncapped_candidate is not None:
                budget_status = ('source_budget_conflict_requires_review' if capped_status == 'infeasible'
                                 else 'source_budget_unproven_requires_review')
                instruction = ('The explicit weekly working-set limit has no verified feasible candidate. '
                    'An uncapped hard-feasible candidate is diagnostic only; obtain approval before changing the limit.')
            else:
                budget_status = 'infeasible' if uncapped_status == 'infeasible' else 'unproven'
                instruction = ('No combination in the supplied executable pool satisfies the hard model.'
                    if uncapped_status == 'infeasible' else
                    'The bounded solve did not establish hard feasibility or infeasibility.')
            development_budget['status'] = budget_status
            return {**proof, 'feasible': False, 'status': budget_status,
                'recipeCount': sum(len(recipe['options']) for recipe in recipes),
                'optionCount': len(option_variables), 'rejectedOptions': rejected[:20],
                'objectiveProgress': stages, 'solverDiagnostics': solver_diagnostics,
                'priorityExecution': _priority_execution(approved_order, objective_costs, stages,
                    [name for name, _ in goals], balance_rules,
                    demand_inputs.get('status', 'unavailable'), development_roles, development_budget,
                    proof.get('executionSelection'), volume_target_evidence_status),
                'sourceBudgetDiagnostic': {'cappedStatus': capped_status,
                    'uncappedHardFeasibilityStatus': uncapped_status, 'diagnosticOnly': True},
                'instruction': instruction}
        chosen = capped_candidate
    source_menu_seed = None
    if (chosen is None and prescription_hint is None and not preserve_source_selection and not redistribution_constraints
            and reviewed_baseline_workouts is None):
        prepared_seed_sessions = _prepared_selection_seed(
            messages, equipment, training_history, sessions, definitions)
        if prepared_seed_sessions is not None:
            seed_references_by_day = [{
                definitions.get(item.get('definition_id'), {}).get('id', item.get('definition_id'))
                for item in day.get('exercises', [])}
                for day in prepared_seed_sessions]
            allowed_by_day = [set() for _ in sessions]
            option_by_index = {index: option for index, _, _, option in option_variables}
            source_options_by_day = [set() for _ in sessions]
            for index, day_index, recipe_index, option in option_variables:
                canonical_ids = {definitions.get(item['definition_id'], {}).get('id', item['definition_id'])
                    for item in option['items']}
                if canonical_ids and canonical_ids.issubset(seed_references_by_day[day_index]):
                    allowed_by_day[day_index].add(index)
                    source_options_by_day[day_index].add(index)

            # The seed may use only the prepared selection plus executable options
            # needed to supply a hard coverage or direct-muscle target absent from it.
            target_muscles = set(targets.get('weeklyEffectiveSets', {})) | set(
                targets.get('perSessionEffectiveSets', {}))
            required_roles_for_seed = {rule['key'] for rule in requirements.get('requiredCoverage', [])}
            supplemented_roles = [set() for _ in sessions]
            for day_index in range(len(sessions)):
                supplied_roles = {role for index in source_options_by_day[day_index]
                    for role, amount in option_by_index[index]['coverage'].items() if amount > 0}
                supplied_muscles = {muscle for index in source_options_by_day[day_index]
                    for muscle, values in option_by_index[index]['volume'].items()
                    if values.get('effective', 0) > 0}
                missing_roles = required_roles_for_seed - supplied_roles
                missing_muscles = target_muscles - supplied_muscles
                for index, option_day, _, option in option_variables:
                    if option_day != day_index:
                        continue
                    added_roles = {role for role, amount in option['coverage'].items()
                        if amount > 0 and role in missing_roles}
                    added_muscles = {muscle for muscle, values in option['volume'].items()
                        if values.get('effective', 0) > 0 and muscle in missing_muscles}
                    if added_roles or added_muscles:
                        allowed_by_day[day_index].add(index)
                        supplemented_roles[day_index].update(added_roles)

            allowed_options = set().union(*allowed_by_day) if allowed_by_day else set()
            source_option_count = sum(map(len, source_options_by_day))
            if allowed_options and all(allowed_by_day):
                seed_goal, seed_costs = goals[0] if goals else ('feasibility', {})
                seed_variables = []
                for index, item in enumerate(variables):
                    seeded = {**item, 'objectiveCost': seed_costs.get(index, 0)}
                    if index in option_by_index and index not in allowed_options:
                        seeded['upper'] = 0
                    seed_variables.append(seeded)
                seed_diagnostic = {'goal': 'prepared_source_menu_seed', 'seedObjective': seed_goal}
                publish_progress('stage_started', seed_diagnostic['goal'])
                seed_status, seed_candidate = run_search(seed_variables, features,
                    diagnostics=seed_diagnostic, stage_limit=5)
                solver_diagnostics.append(seed_diagnostic)
                if seed_candidate is not None:
                    chosen = _canonicalize_objective_epigraphs(variables, features,
                        seed_candidate, goals, auxiliary_lattice=cp_session.auxiliary_lattice)
                publish_progress('stage_completed', seed_diagnostic['goal'])
                source_menu_seed = {
                    'status': seed_status,
                    'candidateAvailable': seed_candidate is not None,
                    'sourceRecipeOptionCount': source_option_count,
                    'allowedRecipeOptionCount': len(allowed_options),
                    'supplementedRolesBySession': [sorted(roles) for roles in supplemented_roles],
                    'objective': seed_goal,
                    'objectiveValue': (sum(cost * chosen[index] for index, cost in seed_costs.items())
                        if chosen is not None else None),
                }
            else:
                source_menu_seed = {'status': 'not_applicable',
                    'reason': 'prepared_selection_has_no_complete_executable_seed',
                    'sourceRecipeOptionCount': source_option_count,
                    'allowedRecipeOptionCount': len(allowed_options)}
    if source_menu_seed is not None:
        proof['preparedSourceMenuSeed'] = source_menu_seed
    order_policy = {'policy': JOINT_POLICY_DESCRIPTOR['candidateOrdering'],
                    'mode': ('cp_sat_selection_with_canonical_audited_execution' if _selection_only else
                        'cp_sat_optional_block_circuit_joint_selection_and_sequence'), 'reviewRequired': False}
    if not goals:
        current = [{**variable, 'objectiveCost': 0} for variable in variables]
        diagnostic = {'goal': 'feasibility'}
        stage_status, chosen = run_search(current, features, diagnostics=diagnostic,
            incumbent=prescription_hint)
        solver_diagnostics.append(diagnostic)
        if chosen is None:
            status = stage_status
        else:
            status = 'optimal' if stage_status == 'optimal' else 'feasible'
    doses_locked = False
    selected_work_locked = _fixed_session_work is not None
    selected_work = copy.deepcopy(_fixed_session_work)
    selection_before_sequence = selection_precedes_execution(requirements)
    dose_locking_processed = False
    development_role_set = {rule['key'] for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') == 'development'}
    inclusion_roles = sorted(set(required_roles) - development_role_set)
    exercise_distribution_dose_locking = {
        'scope': 'not_applied', 'roleWeeklyWorkingSets': {}, 'unlockedInclusionRoles': inclusion_roles}
    for position, (name, costs) in enumerate(goals):
        if _selection_prefix_stages is not None and name in _selection_prefix_stages:
            stages.append({**copy.deepcopy(_selection_prefix_stages[name]),
                'scope': 'full_recipe_menu_selection_prefix_before_fixed_work_execution'})
            continue
        if time.monotonic() >= search_deadline:
            solver_diagnostics.append({'goal': name, 'terminationStatus': 'NOT_RUN',
                'returnReason': 'search_budget_exhausted', 'sharedBudgetRemainingSeconds': 0})
            break
        publish_progress('stage_started', name)
        if (chosen is not None and not selected_work_locked and name.startswith('ordering_')
                and any(goal in ('volume_target', 'workload_economy', 'source_balance',
                    'role_concentration', 'distribution', 'exercise_count') for goal, _ in goals[:position])):
            selected_work = _lock_selected_session_work(features, chosen,
                option_variables, sessions, definitions)
            selected_work_locked = True
        source_balance_doses = (_lock_source_balance_doses(features, chosen, option_variables,
            sessions, requirements, base_report) if name == 'source_balance' and chosen is not None else [])
        if (chosen is not None and not dose_locking_processed
                and workload_precedes_family
                and name in ('exercise_distribution_development', 'exercise_distribution')):
            dose_locking_processed = True
            locked_roles = sorted(development_role_set)
            locked_doses = (_lock_weekly_role_doses(features, chosen,
                _weekly_role_dose_coefficients(option_variables, sessions, locked_roles), locked_roles)
                if locked_roles else {})
            fixed_coverage = (base_report or {}).get('weeklyCoverageSets', {})
            exercise_distribution_dose_locking = {
                'scope': ('development_role_weekly_totals_after_workload_economy'
                    if locked_roles else 'no_development_roles_to_lock'),
                'applied': bool(locked_roles),
                'roleWeeklyWorkingSets': {role: fixed_coverage.get(role, 0) + locked_doses.get(role, 0)
                    for role in locked_roles},
                'unlockedInclusionRoles': inclusion_roles,
            }
        if chosen is not None and not doses_locked and not selection_before_sequence and (name in ('role_concentration',
                'movement_overlap', 'execution_complementarity', 'balance_control')
                or name in ('distribution_worst', 'distribution')
                and 'workload_economy' in [goal for goal, _ in goals[:position]]):
            _lock_weekly_training_doses(features, chosen, option_variables, sessions, required_roles,
                set(targets.get('weeklyEffectiveSets', {})) | set(targets.get('perSessionEffectiveSets', {})))
            doses_locked = True
        current = [{**variable, 'objectiveCost': costs.get(index, 0)} for index, variable in enumerate(variables)]
        preservation_stage = name in ('preservation', 'neutral_preservation', 'dose_selection')
        score_offset = preservation_offset if preservation_stage else 0
        score_bound = _objective_variable_bound(variables, costs, score_offset, exact=True)
        incumbent_score = (_exact_objective_value(chosen, costs, score_offset)
            if chosen is not None else None)
        incumbent_proves_bound = (incumbent_score is not None and score_bound is not None
            and incumbent_score == score_bound)
        if incumbent_proves_bound:
            stage_status = ('optimal_zero_lower_bound' if score_bound == 0 else 'optimal')
            candidate = chosen
        else:
            diagnostic = {'goal': name}
            stage_limit = (min(_SOLVER_STAGE_SECONDS, max(0, search_deadline - time.monotonic()) / 3)
                if name.startswith('goal_tier_') and name.endswith('_worst')
                else _SOLVER_STAGE_SECONDS if name.startswith('goal_tier_') or chosen is None
                else _SOLVER_REFINEMENT_SECONDS)
            if chosen is not None:
                # Reserve a share for each remaining objective before refining this feasible week.
                pending_searches = sum(bool(future_costs) for future_name, future_costs in goals[position:]
                    if _selection_prefix_stages is None or future_name not in _selection_prefix_stages)
                stage_limit = min(stage_limit,
                    max(0, search_deadline - time.monotonic()) / max(1, pending_searches))
            stage_status, candidate = run_search(current, features,
                stage_limit=stage_limit,
                preserve_current=preservation_stage, diagnostics=diagnostic,
                incumbent=chosen if chosen is not None else prescription_hint)
            solver_diagnostics.append(diagnostic)
        prior_bounds_proven = all(stage['status'] in ('optimal', 'optimal_zero_lower_bound')
            for stage in stages if not stage.get('diagnosticOnly'))
        conditional_optimal = (stage_status in ('optimal', 'optimal_zero_lower_bound')
            and not prior_bounds_proven)
        stages.append({'goal': name, 'status': stage_status,
            'priorObjectiveBoundsProven': prior_bounds_proven,
            **({'status': 'feasible', 'conditionalOptimal': True,
                'conditionalSolverStatus': stage_status,
                'optimalityScope': 'attained_unproven_prior_objective_upper_bounds'}
                if conditional_optimal else {}),
            **({'selectedSessionWork': selected_work,
                'selectionFixed': selected_work_locked,
                'scope': 'sequence_and_compatible_grouping_for_selected_per_session_definition_counts'}
                if name.startswith('ordering_') else {}),
            **({'combinedRoleDoseConservation': source_balance_doses,
                'doseLockScope': ('connected_approved_balance_role_minimum_exposure; physical_workload_and_prior_objectives_remain_fixed'
                    if selection_before_sequence else
                    'connected_approved_balance_roles_only; individual_role_doses_remain_selectable')}
                if name == 'source_balance' else {}),
            **({'globalVariableBound': float(score_bound),
                'boundWitness': 'feasible_incumbent'} if incumbent_proves_bound else {}),
            **({'weeklyDosesLocked': doses_locked,
                'physicalWeeklyWorkloadFixed': selection_before_sequence
                    and any(goal == 'workload_economy' for goal, _ in goals[:position]),
                'doseLockScope': ('physical_weekly_workload_and_prior_objective_faces; muscle_and_role_totals_remain_selectable'
                    if selection_before_sequence else
                    'weekly_physical_sets_effective_muscle_and_qualified_role_totals; exercise_identities_remain_selectable')}
                if name in ('distribution', 'movement_overlap', 'execution_complementarity', 'balance_control') else {})})
        if candidate is None:
            if chosen is None:
                status = stage_status
            publish_progress('stage_completed', name)
            break
        candidate = _canonicalize_objective_epigraphs(variables, features, candidate, goals,
            auxiliary_lattice=cp_session.auxiliary_lattice)
        chosen = candidate
        score = float(_exact_objective_value(chosen, costs))
        if preservation_stage:
            stages[-1]['value'] = score + preservation_offset
        elif name == 'role_concentration':
            total_frequency = sum(day.get('timesCompletedInAWeek', 1) for day in sessions) + sum(fixed_frequencies)
            peak_value = chosen[next(iter(costs))]
            stages[-1]['value'] = peak_value / total_frequency if total_frequency else None
            stages[-1]['unit'] = 'sets_above_frequency_weighted_mean_per_training_occurrence'
            stages[-1]['solverObjectiveValue'] = score
        elif name == 'role_concentration_tiebreak':
            total_frequency = sum(day.get('timesCompletedInAWeek', 1) for day in sessions) + sum(fixed_frequencies)
            stages[-1]['value'] = score / total_frequency if total_frequency else None
            stages[-1]['unit'] = 'sum_of_deduplicated_role_profile_peak_surpluses_per_occurrence'
            stages[-1]['solverObjectiveValue'] = score
        elif name == 'superset_lower_body_overlap':
            stages[-1]['value'] = score
            stages[-1]['unit'] = 'weekly_paired_major_lower_body_sets'
            stages[-1]['interpretation'] = 'Raw repeated paired-set exposure, not predicted fatigue or personal tolerance.'
        elif name == 'execution_complementarity':
            stages[-1]['value'] = score
            stages[-1]['unit'] = 'same_role_pairs_without_reviewed_limb_form_complementarity_per_week'
            stages[-1]['candidateMenuUnresolvedPairCount'] = len(execution_complementarity_inventory['unresolvedPairs'])
            stages[-1]['evidenceScope'] = 'selected_plan_pair_cost; unresolved_count_describes_candidate_menu'
        elif name == 'balance_control':
            stages[-1]['value'] = 1 - score
            stages[-1]['unit'] = 'verified_weekly_balance_control_presence'
        elif name == 'volume_target':
            stages[-1]['value'] = score
            stages[-1]['unit'] = 'effective_sets_outside_preferred_ranges'
        elif name == 'demand_colocation':
            stages[-1]['value'] = chosen[next(iter(costs))]
            stages[-1]['unit'] = 'unique_working_sets_per_training_occurrence'
        elif name == 'distribution_worst':
            stage_value = chosen[next(iter(costs))]
            stages[-1]['value'] = stage_value / (2 * total_training_occurrences)
            stages[-1]['unit'] = 'effective_sets_from_weekly_mean'
            stages[-1]['solverObjectiveValue'] = stage_value
        elif name == 'development_emphasis':
            fixed_coverage = (base_report or {}).get('weeklyCoverageSets', {})
            role_totals = {role: fixed_coverage.get(role, 0) + sum(
                option['coverage'].get(role, 0) * sessions[day_index]['timesCompletedInAWeek']
                * chosen[index]
                for index, day_index, _, option in option_variables)
                for role in development_roles}
            stages[-1]['value'] = min(role_totals.values(), default=0)
            stages[-1]['objectiveValue'] = score
            stages[-1]['roleWeeklyWorkingSets'] = role_totals
        elif name == 'development_exposure':
            fixed_coverage = (base_report or {}).get('weeklyCoverageSets', {})
            role_totals = {role: fixed_coverage.get(role, 0) + sum(
                option['coverage'].get(role, 0) * sessions[day_index]['timesCompletedInAWeek']
                * chosen[index]
                for index, day_index, _, option in option_variables)
                for role in development_roles}
            stages[-1]['value'] = sum(role_totals.values())
            stages[-1]['unit'] = 'sum_of_weekly_qualified_role_working_sets'
            stages[-1]['objectiveValue'] = score
            stages[-1]['roleWeeklyWorkingSets'] = role_totals
        else:
            stages[-1]['value'] = score
        # Dose selection precedes role placement but is deliberately not a final
        # preservation lock; its weekly quantities are locked by role polish.
        if name == 'dose_selection':
            stages[-1]['scope'] = 'weekly_dose_selection_before_role_placement'
            stages[-1]['finalScoreLocked'] = False
        else:
            features.append((('objective', name),
                score if name == 'workload_economy' and selection_before_sequence else -math.inf,
                score, 0, costs))
            stages[-1]['retainedObjectiveBound'] = {'value': score,
                'relation': ('equal' if name == 'workload_economy' and selection_before_sequence else 'at_most'),
                'provenOptimal': prior_bounds_proven and stage_status in ('optimal', 'optimal_zero_lower_bound')}
        publish_progress('stage_completed', name)
    if chosen is not None and goals:
        goal_stages = [stage for stage in stages if stage.get('goal') in {name for name, _ in goals}]
        status = ('optimal' if len(goal_stages) == len(goals)
                  and all(stage['status'] in ('optimal', 'optimal_zero_lower_bound')
                          for stage in goal_stages) else 'feasible')
    if chosen is not None and unknown_volume_preferences and 'volume_target' in objective_order:
        status = 'feasible'
    dose_selection_stage = next((stage for stage in stages if stage.get('goal') == 'dose_selection'), None)
    if chosen is not None and dose_selection_stage:
        dose_selection_stage['finalCandidateValue'] = sum(
            value * chosen[index] for index, value in preferences.items()) + preservation_offset
    proof['prescriptionWarmStart']['solverFeasibilityEstablished'] = chosen is not None
    remaining = max(0, search_deadline - time.monotonic())
    search_budget.update(remainingSeconds=remaining, exhausted=remaining <= 0)
    receipt = {**proof, 'feasible': chosen is not None, 'status': status,
               'solverBackend': 'ortools_cp_sat',
               'optimizationScope': ('Finite qualified recipe selection prefix; canonical execution is audited, not optimized.'
                   if _selection_only else
                   'Finite qualified recipe menu, including optional grouping and full session execution circuits; optimality is conditional on attained earlier objective stages.'),
               'recipeCount': sum(len(recipe['options']) for recipe in recipes),
               'optionCount': len(option_variables), 'rejectedOptions': rejected[:20],
               'physicalBlockCount': sum(len(blocks) for blocks in day_blocks),
               'physicalVisitQuotient': {'unmergedSourceVariantCount': sum(
                   len(block['sourceVariantIndexes']) for blocks in day_blocks for block in blocks),
                   'physicalVisitCount': sum(len(blocks) for blocks in day_blocks),
                   'proof': 'Every merged pair has equal ordered members, roles, category and interference facts, and selecting both violates an unchanged per-definition session set-cap row.'},
               'firstVariableCount': sum(len(blocks) for blocks in day_blocks),
               'sourceOrderConstraintCount': sum(label[0] == 'first_respects_source_order'
                   for label, _, _, _, _ in features),
               'orderingConstraintCount': sum(label[0].startswith('execution_')
                   for label, _, _, _, _ in features),
               'executionSequenceEvidence': execution_evidence,
               'exerciseCountEvidence': exercise_count_evidence,
               'objectiveProgress': stages,
               'solverDiagnostics': solver_diagnostics,
               'priorityExecution': _priority_execution(approved_order, objective_costs, stages,
                   [name for name, _ in goals], balance_rules, demand_inputs.get('status', 'unavailable'),
                   development_roles, development_budget, proof.get('executionSelection'), volume_target_evidence_status),
               'objectiveOrderUsed': _attempted_objective_order(
                   approved_order, stages, objective_order),
               'neutralTieBreak': (('weekly_dose_selection_before_role_placement'
                                    if role_concentration_planned else 'preservation')
                                   if preferences and approved_order is not None
                                   and not preservation_is_approved else None),
               'approvedObjectiveOrder': approved_order,
               'preserveSourceSelection': bool(preserve_source_selection),
               **({'redistributionOptimization': {
                   'goal': 'minimize_total_peak_work_sets_across_target_sessions',
                   'status': next((stage['status'] for stage in stages
                       if stage.get('goal') == 'redistribution_spread'), 'not_run'),
                   'optimal': next((stage['status'] for stage in stages
                       if stage.get('goal') == 'redistribution_spread'), None)
                       in ('optimal', 'optimal_zero_lower_bound'),
                   'totalPeakWorkSets': next((stage.get('value') for stage in stages
                       if stage.get('goal') == 'redistribution_spread'), None),
               }} if redistribution_constraints else {}),
               'objectiveInputFingerprint': joint_objective_input_fingerprint(sessions, approved_requirements, equipment,
                   training_history, messages, restriction_policy=restriction_policy,
                   allow_educated_load_guesses=allow_educated_load_guesses,
                   preserve_source_selection=preserve_source_selection,
                   redistribution_constraints=redistribution_constraints,
                   source_working_set_budget=normalized_source_budget,
                   reviewed_baseline_workouts=reviewed_baseline_workouts),
               'candidateOrderPolicy': order_policy,
               'jointPolicy': copy.deepcopy(JOINT_POLICY_DESCRIPTOR),
               'jointModelStatus': status,
               'objectivePolicy': 'approved' if approved_order is not None else 'preserve_candidate_only',
               'legacyBalanceHintApplied': False, 'selectionPolicyVersion': SELECTION_POLICY_VERSION}
    if (chosen is not None and receipt['status'] == 'optimal'
            and any(entry['owner'] == 'joint_solver' and entry['status'] == 'unavailable_evidence'
                for entry in receipt['priorityExecution']['approvedPriorities'])):
        receipt['status'] = 'feasible'
    if chosen is None:
        # Diagnose approved constraints together; never spend unbounded time minimizing a conflict.
        receipt['consideredConstraints'] = [str(label) for label, _, _, _, _ in features
            if label[0] in ('weekly', 'session', 'coverage', 'duration', 'approved_order',
                'exercise_exposure_weekly_sets', 'exercise_exposure_sessions')]
        receipt['instruction'] = ('No combination in the supplied prescription menu satisfies the joint model.'
            if status == 'infeasible' else 'The bounded joint solve did not prove feasibility or infeasibility.') + (
            ' Preserve all approved targets. Add or correct substantive prescription/movement options; '
            'do not repeat count-only allocation or claim every possible workout is infeasible.')
        return receipt
    result = copy.deepcopy(sessions)
    occurrence_lineage = [[] for _ in sessions]
    lineage_claims = []
    candidate_order_changes = []
    selected_superset_origins = []
    for day_index, blocks in enumerate(day_blocks):
        items = []
        execution_order = _execution_order(blocks, chosen, requirements)
        submitted_blocks = source_blocks_by_identity[day_index]
        solved_blocks = [blocks[index]['recipe']['identity'] for index in execution_order]
        submitted_counts, solved_counts = Counter(submitted_blocks), Counter(solved_blocks)
        removed_blocks = submitted_counts - solved_counts
        added_blocks = solved_counts - submitted_counts
        submitted_occurrences, solved_occurrences = {}, {}
        submitted_tokens, solved_tokens = [], []
        for identity in submitted_blocks:
            occurrence = submitted_occurrences.get(identity, 0)
            submitted_occurrences[identity] = occurrence + 1
            submitted_tokens.append((identity, occurrence))
        for identity in solved_blocks:
            occurrence = solved_occurrences.get(identity, 0)
            solved_occurrences[identity] = occurrence + 1
            solved_tokens.append((identity, occurrence))
        common_tokens = set(submitted_tokens) & set(solved_tokens)
        retained_submitted = [token for token in submitted_tokens if token in common_tokens]
        retained_solved = [token for token in solved_tokens if token in common_tokens]
        reordered = retained_submitted != retained_solved
        if removed_blocks or added_blocks or reordered:
            reasons = []
            if reordered:
                reasons.append('reordered retained blocks')
            if removed_blocks or added_blocks:
                reasons.append('changed session block selection or placement')
            candidate_order_changes.append({
                'workoutIndex': day_index,
                'submittedOrder': [list(identity) for identity in submitted_blocks],
                'solvedOrder': [list(identity) for identity in solved_blocks],
                'removedBlocks': [list(identity) for identity, count in removed_blocks.items() for _ in range(count)],
                'addedBlocks': [list(identity) for identity, count in added_blocks.items() for _ in range(count)],
                'retainedOrderChanged': reordered,
                'reason': 'The solver ' + ' and '.join(reasons)
                          + '; independent session review should reassess the candidate arrangement.',
            })
        for block_index in execution_order:
            block = blocks[block_index]
            selected_indices = [index for index in block['options'] if chosen[index]]
            selected = [block['optionValues'][index] for index in selected_indices]
            if selected:
                selected_recipe = block['optionRecipes'][selected_indices[0]]
                if len(selected[0]['items']) > 1:
                    selected_superset_origins.append(selected_recipe['supersetOrigin'])
                lineage_start = len(items)
                for item in copy.deepcopy(selected[0]['items']):
                    item['superset'] = f'JOINT_{day_index}_{block_index}' if item['superset'] is not None else None
                    items.append(item)
                    occurrence_lineage[day_index].append(None)
                source_key = (selected_recipe['signature'], selected_recipe['sourceSignatureOccurrence'])
                local_positions = source_recipe_positions[day_index].get(source_key)
                if local_positions is not None:
                    local_positions = [local_positions[index] for index in selected_recipe['memberOrder']]
                lineage_claims.append((source_key, day_index, lineage_start,
                    copy.deepcopy(local_positions), copy.deepcopy(selected_recipe['sourcePositions'])))
        result[day_index]['exercises'] = items
    assigned_source_positions = set()
    pending_claims = []
    for claim in lineage_claims:
        _, workout, start, local_positions, origin_positions = claim
        if local_positions is None:
            pending_claims.append(claim)
            continue
        positions = local_positions
        if start + len(positions) > len(result[workout]['exercises']):
            return {**receipt, 'feasible': False, 'status': 'unverified',
                'errors': [{'code': 'invalid_occurrence_lineage', 'workoutIndex': workout}],
                'instruction': 'The solver recipe lost its source occurrence mapping; preserve the candidate and report the lineage validation failure.'}
        mapped_positions = []
        for position in positions:
            token = tuple(position)
            if token in assigned_source_positions:
                return {**receipt, 'feasible': False, 'status': 'unverified',
                    'errors': [{'code': 'duplicate_source_lineage', 'sourceOccurrence': list(token)}],
                    'instruction': 'A submitted occurrence was assigned to multiple solved movements; preserve the candidate and report the lineage validation failure.'}
            mapped_positions.append(list(position))
            assigned_source_positions.add(token)
        occurrence_lineage[workout][start:start + len(positions)] = mapped_positions
    for _, workout, start, local_positions, origin_positions in pending_claims:
        if start + len(origin_positions) > len(result[workout]['exercises']):
            return {**receipt, 'feasible': False, 'status': 'unverified',
                'errors': [{'code': 'invalid_occurrence_lineage', 'workoutIndex': workout}],
                'instruction': 'The solver recipe lost its source occurrence mapping; preserve the candidate and report the lineage validation failure.'}
        mapped_positions = []
        for position in origin_positions:
            token = tuple(position)
            mapped_positions.append(list(position) if token not in assigned_source_positions else None)
            assigned_source_positions.add(token)
        occurrence_lineage[workout][start:start + len(origin_positions)] = mapped_positions
    draft = {'name': 'Joint week', 'workouts': copy.deepcopy((existing or {}).get('workouts', [])) + result}
    plan, report = _audit_raw(draft, equipment, requirements, restriction_policy,
        allow_educated_load_guesses, execution_definitions=execution_definitions)
    apply_native_load_calibration_policy(plan, messages or [], equipment,
        getattr(training_history, 'fingerprint', None),
        allow_educated_load_guesses=allow_educated_load_guesses)
    audit_execution_rules(draft, requirements, report, plan)
    audit_execution_details(draft, requirements, report)
    if validate_loads:
        report['errors'].extend(validate_loads(plan))
    if report['errors']:
        return {**receipt, 'feasible': False, 'status': 'unverified', 'errors': report['errors'],
                'failedCandidateDraft': copy.deepcopy(draft),
                'nativeAuditReport': copy.deepcopy(report),
                'instruction': 'The assembled week failed the production audit. Preserve recipes and report this joint-planning validation failure; do not export or enter count-only repair.'}
    receipt['arrangementRefinement'] = {'status': ('canonical_audited_selection_candidate'
        if _selection_only else 'integrated_in_cp_sat'),
        'scope': ('Selection prefix uses exact recipe timing; canonical execution passed the production audit.'
            if _selection_only else
            'Selection, prescriptions, grouping and full execution sequence share the same bounded recipe model.')}
    _finalize_development_exposure(receipt['priorityExecution'], report.get('weeklyCoverageSets', {}))
    if requirements.get('objectiveTiers'):
        grouped = {goal['metric'] for tier in requirements['objectiveTiers'] for goal in tier}
        receipt['priorityExecution']['goalPolicy'] = {
            'tiers': copy.deepcopy(requirements['objectiveTiers']),
            'stages': [copy.deepcopy(stage) for stage in stages if stage['goal'].startswith('goal_tier_')],
            'scope': 'Shared normalized target misses; individual metrics are not independently minimized. Targets do not establish physiological adequacy.'}
        for priority in receipt['priorityExecution']['approvedPriorities']:
            if priority['priority'] in grouped:
                priority.update(status='feasible', optimizationMode='shared_goal_tier',
                    individualOptimumClaimed=False)
    balance_stage = next((stage for stage in stages if stage['goal'] == 'source_balance'), None)
    demand_stage = next((stage for stage in stages if stage['goal'] == 'demand_distribution'), None)
    balance_priority_status = next((item['status'] for item in receipt['priorityExecution']['approvedPriorities']
        if item['priority'] == 'source_balance'), None)
    balance_prefix_proven = balance_priority_status in ('optimal', 'optimal_zero_lower_bound')
    balance_scope = ('Supplied executable recipes, hard constraints and attained preceding objectives only; '
        'not all eligible library exercises or personal suitability. A later-stage optimum is conditional on '
        'the scores attained at preceding priorities; if any preceding approved solver priority is only feasible, '
        'unavailable, or not run, this residual is not proven minimal across the full approved priority order.')
    tradeoffs = []
    for rule in balance_rules:
        scopes = [(None, report.get('weeklyCoverageSets', {}))] if rule['scope'] == 'weekly' else [
            (index, day.get('coverageSets', {})) for index, day in enumerate(report['workouts'])]
        for workout_index, counts in scopes:
            first, second = counts.get(rule['first'], 0), counts.get(rule['second'], 0)
            deviation = (max(0, second - first) if rule.get('relationship') == 'first_not_less_than_second'
                         else abs(first - second))
            if deviation:
                tradeoffs.append({'first': rule['first'], 'second': rule['second'],
                    'relationship': rule.get('relationship', 'balanced'), 'scope': rule['scope'],
                    'workoutIndex': workout_index, 'firstSets': first, 'secondSets': second,
                    'deviation': deviation,
                    'status': ('residual_at_approved_optimum' if balance_stage and balance_prefix_proven
                               else 'residual_not_proven_minimal'),
                    'scopeOfProof': balance_scope})
    receipt['priorityTradeoffs'] = tradeoffs
    receipt['demandDistribution'] = _demand_distribution_summary(
        result, fixed_source_workouts, demand_inputs, definitions, demand_stage,
        objective_requested='demand_distribution' in objective_order,
        fixed_unavailable_groups=fixed_unavailable_groups)
    role_stage = next((stage for stage in stages if stage.get('goal') == 'role_concentration'), None)
    demand_colocation_stage = next((stage for stage in stages if stage.get('goal') == 'demand_colocation'), None)
    role_stage_planned = any(name == 'role_concentration' for name, _ in goals)
    demand_colocation_planned = any(name == 'demand_colocation' for name, _ in goals)
    if role_stage_planned and role_stage is None:
        role_stage = {'goal': 'role_concentration', 'status': 'not_run_after_solver_stop', 'planned': True}
    if demand_colocation_planned and demand_colocation_stage is None:
        demand_colocation_stage = {'goal': 'demand_colocation',
            'status': 'not_run_after_solver_stop', 'planned': True}
    role_tiebreak_stage = next((stage for stage in stages
        if stage.get('goal') == 'role_concentration_tiebreak'), None)
    if role_stage_planned and role_tiebreak_stage is None:
        role_tiebreak_stage = {'goal': 'role_concentration_tiebreak',
            'status': 'not_run_after_solver_stop', 'planned': True}
    if role_stage and role_stage.get('status') in ('optimal', 'optimal_zero_lower_bound'):
        role_solver_status = role_stage['status']
        role_stage = {**role_stage, 'solverStatus': role_solver_status}
    if demand_colocation_stage and demand_colocation_stage.get('status') in ('optimal', 'optimal_zero_lower_bound'):
        demand_solver_status = demand_colocation_stage['status']
        demand_colocation_stage = {**demand_colocation_stage, 'solverStatus': demand_solver_status,
            'status': effective_concentration_status(receipt['priorityExecution'], 'demand_distribution',
                demand_solver_status)}
    role_priority = next((entry for entry in receipt['priorityExecution'].get('approvedPriorities', [])
        if entry.get('priority') == 'role_concentration'), None)
    role_stage_statuses = [(role_stage or {}).get('status'),
        (role_tiebreak_stage or {}).get('status')]
    role_solver_status = ('optimal' if role_stage_statuses
        and all(value in ('optimal', 'optimal_zero_lower_bound') for value in role_stage_statuses)
        else next((value for value in role_stage_statuses
            if value not in ('optimal', 'optimal_zero_lower_bound')), 'not_run_after_solver_stop'))
    role_status = (role_priority.get('status') if role_priority else
        'no_applicable_options' if 'role_concentration' in objective_order and not role_profiles else
        'not_requested')
    _attach_concentration_substage(receipt['priorityExecution'], 'demand_distribution', demand_colocation_stage)
    role_exposure = []
    for profile in role_profiles:
        weekly = sum(exposure * frequency for exposure, frequency in zip(
            profile['fixedExposures'], profile['fixedFrequencies'])) + sum(
                sessions[day].get('timesCompletedInAWeek', 1)
                * profile['exposureByOption'].get(index, 0) * chosen[index]
                for index, day, _, _ in option_variables)
        session_sets = [sum(profile['exposureByOption'].get(index, 0) * chosen[index]
            for index, day, _, _ in option_variables if day == session_index)
            for session_index in range(len(sessions))]
        role_exposure.append({'roles': profile['labels'], 'weeklyWorkingSets': weekly,
            'variableSessionSets': session_sets,
            'fixedSessionSets': list(profile['fixedExposures']),
            'peakSurplusPerOccurrence': _peak_surplus_value(chosen, profile, option_variables, sessions)})
    role_peak_sum = sum(profile['peakSurplusPerOccurrence'] for profile in role_exposure)
    if demand_colocation_stage:
        demand_union_status = demand_colocation_stage['status']
    elif 'demand_distribution' not in objective_order:
        demand_union_status = 'not_requested'
    elif demand_union is None:
        demand_union_status = ('unavailable_evidence' if demand_inputs.get('status') != 'available'
            else 'redundant_or_no_additional_union')
    elif demand_union_profile is None:
        demand_union_status = 'no_selectable_exposure'
    else:
        demand_union_status = 'not_run_after_solver_stop'
    demand_union_summary = ({**copy.deepcopy(demand_union),
        'optimizationStatus': demand_union_status,
        'stage': copy.deepcopy(demand_colocation_stage),
        'peakSessionExposureSets': (_peak_session_exposure_value(chosen, demand_union_profile,
            option_variables, sessions) if demand_union_profile else None)} if demand_union else {
        'optimizationStatus': demand_union_status, 'status': demand_inputs.get('status'),
        'unavailableGroups': copy.deepcopy(demand_inputs.get('unavailableGroups', {}))})
    if not role_stage_planned and 'distribution' in objective_order and not role_profiles:
        role_status = 'no_qualified_variable_roles'
    receipt['priorityExecution']['structuralConcentration'] = {
        'policy': JOINT_POLICY_DESCRIPTOR['structuralConcentration'],
        'rolePlacement': {'status': role_status,
            'solverStatus': role_solver_status if role_stage_planned else role_status,
            'unit': 'sets_above_frequency_weighted_mean_per_training_occurrence',
            'profiles': role_exposure,
            'profilePeakSurplusSumPerOccurrence': role_peak_sum,
            'sumTieBreakStatus': (role_tiebreak_stage or {}).get('status',
                'not_run_after_solver_stop' if role_stage_planned else 'not_requested')},
        'verifiedDemandUnion': demand_union_summary,
    }
    exercise_distribution_stage = next((stage for stage in stages
        if stage.get('goal') == 'exercise_distribution'), None)
    exercise_distribution_development_stage = next((stage for stage in stages
        if stage.get('goal') == 'exercise_distribution_development'), None)
    dose_locking = copy.deepcopy(exercise_distribution_dose_locking)
    if dose_locking.get('applied'):
        final_role_totals = (report or {}).get('weeklyCoverageSets', {})
        dose_locking['finalWeeklyWorkingSetsByRole'] = {
            role: final_role_totals.get(role, 0) for role in dose_locking['roleWeeklyWorkingSets']}
        dose_locking['matchesLockedDose'] = all(
            dose_locking['roleWeeklyWorkingSets'].get(role, 0)
            == dose_locking['finalWeeklyWorkingSetsByRole'].get(role, 0)
            for role in dose_locking['roleWeeklyWorkingSets'])
    receipt['exerciseDistribution'] = _exercise_distribution_summary(
        draft['workouts'], exercise_distribution_profiles, exercise_distribution_stage,
        requested='exercise_distribution' in objective_order, family_evidence=family_evidence,
        development_stage=exercise_distribution_development_stage, dose_locking=dose_locking)
    if 'jointModelStatus' in receipt:
        distribution = receipt['exerciseDistribution']
        for summary in (distribution, distribution['developmentPriority']):
            if summary.get('status') in ('optimal', 'optimal_zero_lower_bound'):
                summary.update(status='feasible',
                    solverStageScope='joint_model_before_complete_arrangement_comparison')
        role_placement = receipt['priorityExecution']['structuralConcentration']['rolePlacement']
        if role_placement['sumTieBreakStatus'] in ('optimal', 'optimal_zero_lower_bound'):
            role_placement.update(sumTieBreakStatus='feasible',
                solverStageScope='joint_model_before_complete_arrangement_comparison')
    receipt['priorityExecution']['exerciseDistribution'] = copy.deepcopy(receipt['exerciseDistribution'])
    superset_candidates['selectedSourceGroupCount'] = selected_superset_origins.count('source')
    superset_candidates['selectedCodeGeneratedGroupCount'] = selected_superset_origins.count('code_generated')
    receipt['supersetCandidates'] = copy.deepcopy(superset_candidates)
    if _selection_only:
        receipt['_selectionPrefixBounds'] = {name: _exact_objective_value(chosen, costs)
            for name, costs in goals if any(stage['goal'] == name and 'value' in stage for stage in stages)}
    receipt['executionEvaluation'] = evaluate_audited_execution(
        {'workouts': draft['workouts'], 'audit': report},
        {**definitions_by_id, **definitions}, requirements)
    return {**receipt, 'objectiveInputFingerprint': joint_objective_input_fingerprint(result, approved_requirements, equipment,
                training_history, messages, restriction_policy=restriction_policy,
                allow_educated_load_guesses=allow_educated_load_guesses,
                preserve_source_selection=preserve_source_selection,
                redistribution_constraints=redistribution_constraints,
                source_working_set_budget=normalized_source_budget,
                reviewed_baseline_workouts=reviewed_baseline_workouts),
            'candidateOrderPolicy': {**order_policy,
                'reviewRequired': bool(candidate_order_changes)},
            'sessions': result, 'occurrenceLineage': occurrence_lineage,
            'audit': report, 'elapsedSeconds': time.monotonic() - started,
            'candidateOrderChanges': candidate_order_changes,
            'candidateOrderReviewRequired': bool(candidate_order_changes),
            'solvedPrescriptionHash': prescription_fingerprint(draft['workouts']),
            'progressionMargins': [{'definition_id': item['definition_id'],
                **progression_margin(item, capabilities[item['definition_id']])} for day in result for item in day['exercises']],
            'coverageBalance': [{'first': rule['first'], 'second': rule['second'], 'scope': rule['scope'],
                'authority': 'Source-approved qualitative goal; no hard numerical tolerance was invented.'}
                for rule in balance_rules]}
