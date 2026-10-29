"""Choose an executable week from finite, validated prescription recipes."""

import copy
import hashlib
import itertools
import json
import math
import time
from collections import Counter

from jsonschema import Draft7Validator, ValidationError

from .allocation import _audit_raw, _milp_solve, _MILP_SOLUTION_TOLERANCE
from .generation_audit import (ASSUMPTIONS, effective_concentration_status,
                               validate_family_set_bounds, weekly_family_set_counts,
                               volume_target_bounds)
from .planning_tools import _DRAFT_SCHEMA
from .programming_guidelines import (
    approved_work_set_bounds, audit_execution_details, audit_execution_rules,
    session_structure_limits,
    EXECUTION_ORDER_POLICY, execution_block_priority, execution_member_order,
    execution_order_indices, execution_order_predecessors,
)
from .programming_demands import (
    demand_distribution_inputs, demand_union_exposure_input, definition_demand_facts,
)
from .recipe_contracts import (
    progression_capability, progression_margin, recorded_evidence, reviewed_exercise_family_evidence,
)

SELECTION_POLICY_VERSION = 11
RECORDED_EVIDENCE_POLICY_VERSION = 1
_SOLVER_STAGE_SECONDS = 60
JOINT_POLICY_DESCRIPTOR = {
    'candidateOrdering': EXECUTION_ORDER_POLICY,
    'developmentEmphasis': 'explicit_approved_order_only_with_binding_coverage_floors',
    'workloadEconomy': 'physical_weekly_sets_before_dose_preserving_distribution',
    'structuralConcentration': 'dose_preserving_worst_then_sum_deduplicated_role_peaks_before_final_muscle_distribution_only_after_workload_economy_and_verified_demand_union_session_peak',
    'exerciseDistribution': 'reviewed_family_peaks_development_before_inclusion_with_fixed_weekly_development_role_doses_when_workload_precedes_diversity',
}
JOINT_REPAIRABLE_AUDIT_ERRORS = frozenset({
    'volume_below_target', 'volume_above_target', 'duration_exceeded',
    'superset_set_count_mismatch', 'execution_sessionStructure', 'execution_order',
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
    if 'demand_distribution' in objective_order and available.get('demand_colocation', False):
        demand_index = next((index for index, name in enumerate(ordered)
            if name == 'demand_distribution'), None)
        if demand_index is not None:
            ordered.insert(demand_index + 1, 'demand_colocation')
    if 'distribution' in objective_order and available.get('role_concentration', False):
        role_goals = ['role_concentration']
        if available.get('role_concentration_tiebreak', False):
            role_goals.append('role_concentration_tiebreak')
        distribution_index = objective_order.index('distribution')
        distribution_is_final_approved_priority = not objective_order[distribution_index + 1:]
        economy_precedes_distribution = (
            'workload_economy' in objective_order
            and objective_order.index('workload_economy') < distribution_index)
        if (economy_precedes_distribution and distribution_is_final_approved_priority
                and 'distribution' in ordered):
            ordered[ordered.index('distribution'):ordered.index('distribution')] = role_goals
        else:
            ordered.extend(role_goals)
    return ordered


def _attempted_objective_order(approved_order, stages, fallback_order=None):
    """List approved objectives whose solver stages were actually attempted."""
    objective_order = approved_order if approved_order is not None else (fallback_order or [])
    attempted = {stage.get('goal') for stage in stages if isinstance(stage, dict)}
    return [name for name in objective_order if name in attempted]


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

    if 'workload_economy' in (requirements.get('objectiveOrder') or []):
        costs['workload_economy'] = sum(item['numWorkSets'] * workout.get('timesCompletedInAWeek', 1)
            for workout in workouts[len(context.get('fixedWorkouts', [])):]
            for item in workout.get('exercises', []))

    targets = requirements.get('auditTargets', {})
    muscle_keys = set(targets.get('weeklyEffectiveSets', {})) | set(
        targets.get('perSessionEffectiveSets', {}))
    if total_frequency and muscle_keys:
        score = 0.0
        for muscle in muscle_keys:
            weekly = report.get('weeklyVolume', {}).get(muscle, {}).get('effective')
            if type(weekly) not in (int, float) or not math.isfinite(weekly):
                return None
            for day, frequency in zip(audited_days, frequencies):
                session_value = day.get('volume', {}).get(muscle, {}).get('effective')
                if type(session_value) not in (int, float) or not math.isfinite(session_value):
                    return None
                score += 2 * frequency * abs(total_frequency * session_value - weekly)
        costs['distribution'] = score

    duration_values = [day['estimatedSeconds'] for day in audited_days]
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

    concentration_roles = sorted({rule['key'] for rule in requirements.get('requiredCoverage', [])})
    if ('distribution' in (requirements.get('objectiveOrder') or [])
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

    return costs


def _development_role_weekly_doses(candidate, requirements):
    weekly = candidate.get('audit', {}).get('weeklyCoverageSets', {})
    return {rule['key']: weekly.get(rule['key'], 0)
        for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') == 'development'}


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
    available = {name: (baseline_costs.get(name) is not None
        and candidate_costs.get(name) is not None)
        for name in set(baseline_costs) | set(candidate_costs)}
    if 'demand_distribution' in (requirements.get('objectiveOrder') or []):
        available['demand_distribution'] = True
    if 'preservation' in (requirements.get('objectiveOrder') or []):
        available['preservation'] = True
    if 'exercise_distribution' in (requirements.get('objectiveOrder') or []):
        available['exercise_distribution'] = True
    if 'progression' in (requirements.get('objectiveOrder') or []):
        available['progression'] = True
    if ('distribution' in (requirements.get('objectiveOrder') or [])
            and requirements.get('requiredCoverage')):
        available['role_concentration'] = True
        available['role_concentration_tiebreak'] = True
    ordered = _ordered_joint_objective_names(requirements, available)
    for objective in ordered:
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

    current_history = getattr(history, 'fingerprint', None)
    library_hash = library_fingerprint(equipment)
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
        'sourceWorkingSetBudget': _source_working_set_budget_identity(sessions, source_working_set_budget),
        'reviewedDoseReference': _reviewed_dose_reference_identity(reviewed_baseline_workouts),
        'preserveSourceSelection': bool(preserve_source_selection),
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': allow_educated_load_guesses}
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
    evidence = recorded_evidence(messages, library_hash, history_fingerprint)
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

    optional_objective_slack = {'coverage_balance_deviation', 'distribution_deviation', 'duration_balance_bound',
                                'duration_balance_excess', 'demand_distribution_peak',
                                'development_exposure_deficit', 'role_concentration_peak',
                                'role_concentration_profile_peak',
                                'demand_colocation_peak', 'exercise_distribution_peak'}
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
                'coverage_balance', 'distribution_deviation', 'demand_distribution_peak', 'duration_balance',
                'development_emphasis', 'role_concentration', 'demand_colocation',
                'role_concentration_peak', 'role_concentration_profile_peak',
                'demand_colocation_peak', 'exercise_distribution'):
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


def _canonicalize_objective_epigraphs(variables, features, candidate, goals):
    """Canonicalize epigraphs and recheck their source rows at solver tolerance."""
    epigraph_kinds = {'coverage_balance_deviation', 'distribution_deviation', 'duration_balance_bound',
                      'duration_balance_excess',
                      'demand_distribution_peak', 'redistribution_peak', 'development_exposure_deficit',
                      'role_concentration_peak', 'role_concentration_profile_peak',
                      'demand_colocation_peak', 'exercise_distribution_peak'}
    costs = {index: cost for _, goal_costs in goals for index, cost in goal_costs.items() if cost}
    duration_balance_requested = any(name == 'duration_balance' for name, _ in goals)
    values = list(candidate)
    for index, variable in enumerate(variables):
        identity = variable.get('domainIdentity')
        if not isinstance(identity, dict):
            continue
        kind = identity.get('kind')
        if kind not in epigraph_kinds:
            continue
        lower, upper = variable['lower'], variable['upper']
        for _, row_lower, row_upper, intercept, coefficients in features:
            coefficient = (coefficients.get(index, 0) if isinstance(coefficients, dict)
                            else coefficients[index] if index < len(coefficients) else 0)
            if not coefficient:
                continue
            coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                                 else enumerate(coefficients))
            rest = math.fsum((intercept, *(value * values[column] for column, value in coefficient_items
                                           if column != index)))
            if coefficient > 0:
                if math.isfinite(row_lower):
                    lower = max(lower, (row_lower - rest) / coefficient)
                if math.isfinite(row_upper):
                    upper = min(upper, (row_upper - rest) / coefficient)
            else:
                if math.isfinite(row_upper):
                    lower = max(lower, (row_upper - rest) / coefficient)
                if math.isfinite(row_lower):
                    upper = min(upper, (row_lower - rest) / coefficient)
        tolerance = _MILP_SOLUTION_TOLERANCE
        if lower > upper + tolerance:
            raise RuntimeError(
                f"Epigraph {identity!r} has no feasible canonical value for the selected options "
                f"(lower={lower!r}, upper={upper!r}).")
        if variable.get('integer', True):
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
    for label, lower, upper, intercept, coefficients in features:
        coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                             else enumerate(coefficients))
        activity = math.fsum((intercept, *(value * values[index] for index, value in coefficient_items)))
        if not lower - _MILP_SOLUTION_TOLERANCE <= activity <= upper + _MILP_SOLUTION_TOLERANCE:
            lower_slack = activity - lower if math.isfinite(lower) else math.inf
            upper_slack = upper - activity if math.isfinite(upper) else math.inf
            raise RuntimeError(
                f"Canonical epigraphs violate joint-planning row {label!r}: "
                f"activity={activity!r}, bounds=({lower!r}, {upper!r}), "
                f"slack=({lower_slack!r}, {upper_slack!r}).")
    return values


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
                        development_budget=None):
    """Expose the owner and actual solver outcome for approved soft priorities."""
    stage_by_goal = {stage['goal']: stage for stage in stages}
    solver_owners = {'source_balance': 'joint_solver', 'distribution': 'joint_solver', 'duration_balance': 'joint_solver',
                     'demand_distribution': 'joint_solver', 'development_emphasis': 'joint_solver',
                     'development_exposure': 'joint_solver',
                     'workload_economy': 'joint_solver',
                     'exercise_distribution': 'joint_solver', 'preservation': 'joint_solver'}
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
        if priority == 'progression':
            status = 'outside_joint_solver'
        elif stage:
            status = stage['status']
        elif priority == 'demand_distribution' and demand_evidence_status == 'unavailable':
            status = 'unavailable_evidence'
        elif priority == 'demand_distribution' and not any(objective_costs[priority].values()):
            status = 'no_positive_exposure'
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
        priorities.append({'priority': priority, 'owner': owner, 'status': status,
                           'solverStage': copy.deepcopy(stage) if stage else None})

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


def _lock_weekly_recipe_doses(features, chosen, option_variables, sessions, required_roles):
    """Keep the incumbent recipe doses and qualified coverage totals during placement polishing."""
    from .repair_contract import normalized_target_signature, redistribution_recipe_signature

    recipe_coefficients, target_coefficients = {}, {}
    physical_coefficients = {}
    coverage_coefficients = _weekly_role_dose_coefficients(option_variables, sessions, required_roles)
    for index, day_index, _, option in option_variables:
        frequency = sessions[day_index]['timesCompletedInAWeek']
        physical_coefficients[index] = option['count'] * len(option['items']) * frequency
        for item in option['items']:
            signature = redistribution_recipe_signature(item)
            recipe_coefficients.setdefault(signature, {})[index] = recipe_coefficients.setdefault(signature, {}).get(index, 0) + option['count'] * frequency
            for target in item.get('targetSetPrescriptions', []):
                target_key = (signature, normalized_target_signature(target))
                target_coefficients.setdefault(target_key, {})[index] = target_coefficients.setdefault(target_key, {}).get(index, 0) + frequency
    def lock(label, coefficients):
        target = sum(value * chosen[index] for index, value in coefficients.items())
        features.append((label, target, target, 0, coefficients))

    lock(('placement_conservation', 'physical_sets'), physical_coefficients)
    for signature, coefficients in recipe_coefficients.items():
        lock(('placement_conservation', 'recipe_dose', signature), coefficients)
    for target_key, coefficients in target_coefficients.items():
        lock(('placement_conservation', 'exact_targets', *target_key), coefficients)
    for role, coefficients in coverage_coefficients.items():
        lock(('placement_conservation', 'coverage', role), coefficients)


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
        'sourceWorkingSetBudget': _source_working_set_budget_identity(sessions, source_working_set_budget),
        'reviewedDoseReference': _reviewed_dose_reference_identity(reviewed_baseline_workouts),
        'preserveSourceSelection': bool(preserve_source_selection),
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': allow_educated_load_guesses}
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


def _execution_order(blocks, chosen, requirements):
    selected = [index for index, block in enumerate(blocks) if any(chosen[option] for option in block['options'])]
    order = execution_order_indices([blocks[index]['recipe']['roles'] for index in selected],
        [_block_order_key(blocks, index) for index in selected], requirements)
    return [selected[index] for index in order]


def _block_order_key(blocks, index):
    block = blocks[index]
    return (block['recipe']['orderPriority'], block['sourceRank'], index)


def _constrain_first_block_order(blocks, selected_coefficients, requirements, variable, constraint, day_index):
    """Encode the stable topological first block with readiness and prefix sums."""
    predecessors = execution_order_predecessors([block['recipe']['roles'] for block in blocks], requirements)

    ready_variables = []
    for index, block in enumerate(blocks):
        ready = variable(domain_identity={'kind': 'first_block_ready', 'workoutIndex': day_index,
            'sourcePositions': block['recipe']['sourcePositions'],
            'definitionIds': list(block['recipe']['identity'])})
        ready_variables.append(ready)
        selected = selected_coefficients[index]
        constraint(('first_block_ready_selected', day_index, index), -math.inf, 0,
            {ready: 1, **{option: -coefficient for option, coefficient in selected.items()}})
        no_predecessor = {ready: 1, **{option: -coefficient for option, coefficient in selected.items()}}
        for predecessor_index in sorted(predecessors[index]):
            predecessor_selected = selected_coefficients[predecessor_index]
            constraint(('first_block_ready_predecessor', day_index, predecessor_index, index),
                -math.inf, 1, {ready: 1, **predecessor_selected})
            for option, coefficient in predecessor_selected.items():
                no_predecessor[option] = no_predecessor.get(option, 0) + coefficient
        constraint(('first_block_ready_if_unblocked', day_index, index), 0, math.inf, no_predecessor)

    ordered_indices = sorted(range(len(blocks)), key=lambda index: _block_order_key(blocks, index))
    prefix = None
    for position, index in enumerate(ordered_indices):
        block = blocks[index]
        constraint(('first_respects_source_order', day_index, index, 'ready'), -math.inf, 0,
            {block['first']: 1, ready_variables[index]: -1})
        if prefix is not None:
            constraint(('first_respects_source_order', day_index, index, 'prefix'), -math.inf, 1,
                {block['first']: 1, prefix: 1})
        if position < len(ordered_indices) - 1:
            next_prefix = variable(integer=False,
                domain_identity={'kind': 'first_block_prefix', 'workoutIndex': day_index,
                    'sourceRank': block['sourceRank'], 'sourcePositions': block['recipe']['sourcePositions']})
            if prefix is not None:
                constraint(('first_block_ready_prefix', day_index, position, 'carry'), -math.inf, 0,
                    {prefix: 1, next_prefix: -1})
            constraint(('first_block_ready_prefix', day_index, position, 'include'), -math.inf, 0,
                {ready_variables[index]: 1, next_prefix: -1})
            constraint(('first_block_ready_prefix', day_index, position, 'bound'), -math.inf, 0,
                {next_prefix: 1, ready_variables[index]: -1,
                 **({prefix: -1} if prefix is not None else {})})
            prefix = next_prefix


def solve_prescribed_week(sessions, requirements, equipment, restriction_policy=None, existing=None,
                          allow_educated_load_guesses=True, *, training_history=None, messages=None, balance=False,
                          preserve_source_selection=False, redistribution_constraints=None,
                          source_working_set_budget=None, reviewed_baseline_workouts=None):
    """Solve selection, placement, counts, grouping, allowed rests and ordering together.

    Options keep supported loads/reps, tempo, calibration and warm-ups intact. All
    timing coefficients come from the production audit, not a second time model.
    """
    started = time.monotonic()
    try:
        _DRAFT_VALIDATOR.validate({'requirementsId': 'recipes', 'name': 'Recipes', 'workouts': sessions})
    except ValidationError as error:
        return {'feasible': False, 'status': 'invalid_options', 'instruction': error.message}
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
    frequency = sum(day['timesCompletedInAWeek'] for day in [*(existing or {}).get('workouts', []), *sessions])
    if requirements.get('sessionsPerWeek') is not None and frequency != requirements['sessionsPerWeek']:
        return {**proof, 'feasible': False, 'status': 'invalid_schedule',
                'instruction': 'The recipe schedule does not match the approved weekly frequency. Correct the schedule; do not relax requirements.'}
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(
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
    evidence = recorded_evidence(messages or [], library_fingerprint(equipment), getattr(training_history, 'fingerprint', None))
    capabilities = {ref: progression_capability(definition, equipment, evidence.get(definition['id']))
                    for ref, definition in definitions.items() if any(
                        item['definition_id'] == ref for day in sessions for item in day['exercises'])}
    source_ranks_by_identity = []
    source_blocks_by_identity = []
    source_blocks = []
    source_recipe_positions = []
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
        for block, positions in _blocks_with_source_positions([day], standalone=True):
            signature = _recipe_signature(block)
            occurrence = occurrence_by_signature[signature]
            occurrence_by_signature[signature] += 1
            indexed[(signature, occurrence)] = [(workout_index, index) for _, index in positions]
        source_recipe_positions.append(indexed)
    for day in sessions:
        ranks, blocks, counts = {}, [], {}
        for rank, block in enumerate(_blocks([day])):
            identity = tuple(item['definition_id'] for item in block)
            occurrence = counts.get(identity, 0)
            counts[identity] = occurrence + 1
            ranks.setdefault(identity, []).append(rank)
            blocks.append(identity)
        source_ranks_by_identity.append(ranks)
        source_blocks_by_identity.append(blocks)
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

    numeric_errors = JOINT_REPAIRABLE_AUDIT_ERRORS
    # Audit one recipe once per count; those contributions are reusable in every session.
    for block, source_positions in _blocks_with_source_positions(sessions, standalone=True):
        workout_index = source_positions[0][0]
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
        member_order = execution_member_order([definitions[item['definition_id']] for item in block])
        rest_slots = [(item['restAfterSupersetExerciseSeconds'], item['restAfterExerciseSeconds']) for item in block]
        block = [copy.deepcopy(block[index]) for index in member_order]
        source_positions = [source_positions[index] for index in member_order]
        if member_order != list(range(len(block))):
            for item, (recovery, outer_rest) in zip(block, rest_slots):
                item['restAfterSupersetExerciseSeconds'] = recovery
                item['restAfterExerciseSeconds'] = outer_rest
        recipe_identity = tuple(item['definition_id'] for item in block)
        recipe_occurrence = recipe_occurrences[workout_index].get(recipe_identity, 0)
        recipe_occurrences[workout_index][recipe_identity] = recipe_occurrence + 1
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
                    # Singleton recipe audits lose whether this exercise may follow another one.
                    item.setdefault('setupSeconds', ASSUMPTIONS['transitionSeconds'])
                day = {'name': 'Recipe', 'description': 'Prescription option', 'timesCompletedInAWeek': 1,
                       'exercises': items}
                draft = {'requirementsId': 'recipe', 'name': 'Recipe', 'workouts': [day]}
                try:
                    _DRAFT_VALIDATOR.validate(draft)
                    plan, report = _audit_raw(draft, equipment, requirements, restriction_policy,
                        allow_educated_load_guesses, apply_family_bounds=False)
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
                workout = report['workouts'][0]
                setup = items[0].get('setupSeconds', ASSUMPTIONS['transitionSeconds'])
                options.append({'items': items, 'count': count, 'volume': workout['volume'],
                    'coverage': workout.get('coverageSets', {}),
                    'seconds': workout['estimatedSeconds'] - ASSUMPTIONS['generalWarmupSeconds'] + setup})
        if options:
            recipes.append({'options': options,
                'setup': options[0]['items'][0].get('setupSeconds', ASSUMPTIONS['transitionSeconds']),
                'signature': signature, 'sourceSignatureOccurrence': source_signature_occurrence,
                'sourcePositions': source_positions, 'memberOrder': member_order,
                'identity': recipe_identity, 'occurrence': recipe_occurrence,
                'roles': set().union(*(set(item.get('satisfiesCoverage', [])) for item in block)),
                'orderPriority': execution_block_priority([definitions[item['definition_id']] for item in block]),
                'definitions': {item['definition_id'] for item in block}})
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
    for day_index, day in enumerate(sessions):
        blocks, blocks_by_source = [], {}
        for recipe_index, recipe in enumerate(recipes):
            indices = []
            for option in recipe['options']:
                index = variable(domain_identity={
                    'kind': 'recipe_option', 'workoutIndex': day_index,
                    'sourcePositions': recipe['sourcePositions'],
                    'definitionIds': list(recipe['identity']),
                    'workSetCount': option['count'], 'volume': option['volume'],
                    'coverage': option['coverage'], 'seconds': option['seconds'],
                })
                # Internal hint for exact count-series compression in the MILP
                # backend. The key is deliberately excluded from domainIdentity:
                # it is an equivalent formulation hint, not a feasibility rule.
                variables[index]['countSeriesKey'] = (
                    day_index, recipe_index, _recipe_signature(option['items']))
                variables[index]['countSeriesValue'] = option['count']
                indices.append(index)
                option_variables.append((index, day_index, recipe_index, option))
            constraint(('recipe_choice', day_index, recipe_index), 0, 1, dict.fromkeys(indices, 1))
            source_key = (recipe['signature'], recipe['sourceSignatureOccurrence'])
            block = blocks_by_source.get(source_key)
            if block is None:
                source_identity = tuple(sessions[workout]['exercises'][index]['definition_id']
                    for workout, index in sorted(recipe['sourcePositions']))
                identity_ranks = source_ranks_by_identity[day_index].get(source_identity, [])
                source_rank = (identity_ranks[recipe['occurrence']] if recipe['occurrence'] < len(identity_ranks)
                               else identity_ranks[-1] if identity_ranks
                               else len(recipes) + recipe_index)
                block = {'options': [], 'recipeIndexes': [], 'recipe': recipe,
                         'sourceRank': source_rank, 'setup': recipe['setup'], 'first': variable(
                             domain_identity={'kind': 'first_block', 'workoutIndex': day_index,
                                 'sourcePositions': recipe['sourcePositions'],
                                 'definitionIds': list(recipe['identity']),
                                 'setupSeconds': recipe['setup'],
                                 'coverageRoles': sorted(recipe['roles'])})}
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
            block['optionValues'].update(zip(indices, recipe['options']))
            if requirements['auditTargets'].get('maximumSessionSeconds') and 'setupSeconds' not in recipe['options'][0]['items'][0]:
                constraint(('missing_setup_only_first', day_index, recipe_index), -math.inf, 0,
                           {block['first']: -1, **dict.fromkeys(indices, 1)})
        missing_source_keys = set(source_blocks[day_index]) - set(blocks_by_source)
        if preserve_source_selection and missing_source_keys:
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
            if preserve_source_selection:
                selected_bounds = (1, 1) if source_block else (0, 0)
            else:
                selected_bounds = (0, 1)
            constraint(('physical_block_choice', day_index, block_index), *selected_bounds, choice)
            constraint(('first_selected', day_index, block_index), -math.inf, 0,
                       {block['first']: 1, **{index: -1 for index in block['options']}})
        day_blocks.append(blocks)
        constraint(('first_block', day_index), 1, 1, {b['first']: 1 for b in blocks})
        for reference in sorted(set().union(*(r['definitions'] for r in recipes))):
            inventory = max(sum(item['definition_id'] == reference for item in source['exercises']) for source in sessions)
            constraint(('movement_inventory', day_index, reference), 0, inventory,
                {i: 1 for b in blocks if reference in b['recipe']['definitions'] for i in b['options']})
        for limit_name, coefficient in (
                ('maximumExercises', lambda option: len(option['items'])),
                ('maximumSupersets', lambda option: int(len(option['items']) > 1))):
            limit = structure_limits.get(limit_name)
            if limit is not None:
                coefficients = {index: coefficient(option)
                    for index, option_day, _, option in option_variables
                    if option_day == day_index and coefficient(option)}
                constraint(('session_structure', limit_name, day_index), -math.inf, limit, coefficients)
        # The selected first block must match the deterministic stable topological
        # order used to build the candidate: approved order edges first, submitted
        # source order among currently-ready blocks. This keeps setup arithmetic
        # exact without spending another MILP pass to choose an order.
        selected_coefficients = [{option: 1 for option in block['options']} for block in blocks]
        _constrain_first_block_order(blocks, selected_coefficients, requirements,
            variable, constraint, day_index)

    base_report = None
    if existing:
        _, base_report = _audit_raw(existing, equipment, requirements, restriction_policy, allow_educated_load_guesses)
    targets = requirements['auditTargets']
    for scope, key in (('weekly', 'weeklyEffectiveSets'), ('session', 'perSessionEffectiveSets')):
        for muscle, bounds in targets.get(key, {}).items():
            for day_index in ([None] if scope == 'weekly' else range(len(sessions))):
                coefficients = {i: option['volume'][muscle]['effective'] * (
                    sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                    for i, d, _, option in option_variables if day_index is None or d == day_index}
                intercept = base_report['weeklyVolume'][muscle]['effective'] if base_report and day_index is None else 0
                constraint((scope, day_index, muscle), *volume_target_bounds(bounds), coefficients, intercept)
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
    if targets.get('maximumSessionSeconds') is not None or 'duration_balance' in (requirements.get('objectiveOrder') or []):
        for day_index, blocks in enumerate(day_blocks):
            coefficients = {i: option['seconds'] for i, d, _, option in option_variables if d == day_index}
            coefficients.update({b['first']: -b['setup'] for b in blocks})
            duration_expressions.append((coefficients, ASSUMPTIONS['generalWarmupSeconds']))
            if targets.get('maximumSessionSeconds') is not None:
                constraint(('duration', day_index), -math.inf, targets['maximumSessionSeconds'], coefficients,
                           ASSUMPTIONS['generalWarmupSeconds'])
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
    for role in required_roles:
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
    features = constraints
    from .planning_tools import library_fingerprint
    library_hash = library_fingerprint(equipment)
    history_fingerprint = getattr(training_history, 'fingerprint', None)
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
    objective_costs = {'demand_distribution': demand_distribution_costs, 'duration_balance': duration_balance_costs,
                       'source_balance': balance_costs, 'distribution': distribution_costs,
                       'exercise_distribution': exercise_distribution_costs,
                       'development_emphasis': development_emphasis_costs,
                       'development_exposure': development_exposure_costs,
                       'workload_economy': workload_costs, 'preservation': preferences}
    approved_order = requirements.get('objectiveOrder')
    objective_order = (list(approved_order) if approved_order is not None else
        ['preservation'] if reviewed_dose_reference is not None else [])
    objective_available = {name: bool(values) for name, values in objective_costs.items()}
    objective_available.update({
        'development_emphasis': bool(development_emphasis_costs),
        'development_exposure': bool(development_exposure_costs),
        'demand_colocation': bool(demand_colocation_costs),
        'role_concentration': bool(role_concentration_costs),
        'role_concentration_tiebreak': bool(role_concentration_tiebreak_costs),
        'exercise_distribution': bool(exercise_distribution_costs),
    })
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
    goals = ([('redistribution_spread', redistribution_peak_costs)] if redistribution_peak_costs else []) + ordered_goals
    preservation_is_approved = approved_order is None or 'preservation' in objective_order
    role_concentration_planned = any(name == 'role_concentration' for name, _ in goals)
    if preferences and approved_order is not None and not preservation_is_approved:
        if role_concentration_planned:
            role_position = next(index for index, (name, _) in enumerate(goals)
                if name == 'role_concentration')
            goals.insert(role_position, ('dose_selection', preferences))
        else:
            goals.append(('neutral_preservation', preferences))
    chosen, stages, status = None, [], 'unproven'
    solver_diagnostics = []
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
        capped_status, capped_candidate = _milp_solve(feasibility_variables, features,
            timeout_seconds=_SOLVER_STAGE_SECONDS, preserve_current=False, diagnostics=diagnostic)
        solver_diagnostics.append(diagnostic)
        stages.append({'goal': 'development_budget_feasibility', 'status': capped_status})
        if capped_candidate is None:
            diagnostic = {'goal': 'uncapped_hard_feasibility_diagnostic'}
            uncapped_status, uncapped_candidate = _milp_solve(feasibility_variables, uncapped_features,
                timeout_seconds=_SOLVER_STAGE_SECONDS, preserve_current=False, diagnostics=diagnostic)
            solver_diagnostics.append(diagnostic)
            stages.append({'goal': 'uncapped_hard_feasibility_diagnostic', 'status': uncapped_status,
                           'diagnosticOnly': True})
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
                    demand_inputs.get('status', 'unavailable'), development_roles, development_budget),
                'sourceBudgetDiagnostic': {'cappedStatus': capped_status,
                    'uncappedHardFeasibilityStatus': uncapped_status, 'diagnosticOnly': True},
                'instruction': instruction}
        chosen = capped_candidate
    # Exercise order is a construction constraint, not an optimization goal.
    # The shared block policy and approved edges determine order and first setup,
    # so no separate order MILP is needed.
    order_policy = {'policy': JOINT_POLICY_DESCRIPTOR['candidateOrdering'],
                    'mode': 'stable_topological', 'reviewRequired': False}
    if not goals:
        current = [{**variable, 'objectiveCost': 0} for variable in variables]
        diagnostic = {'goal': 'feasibility'}
        stage_status, chosen = _milp_solve(current, features, timeout_seconds=_SOLVER_STAGE_SECONDS,
                                           preserve_current=False, diagnostics=diagnostic)
        solver_diagnostics.append(diagnostic)
        if chosen is None:
            status = stage_status
        else:
            status = 'optimal' if stage_status == 'optimal' else 'feasible'
    doses_locked = False
    dose_locking_processed = False
    development_role_set = {rule['key'] for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') == 'development'}
    inclusion_roles = sorted(set(required_roles) - development_role_set)
    exercise_distribution_dose_locking = {
        'scope': 'not_applied', 'roleWeeklyWorkingSets': {}, 'unlockedInclusionRoles': inclusion_roles}
    for position, (name, costs) in enumerate(goals):
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
        if chosen is not None and not doses_locked and (name == 'role_concentration'
                or name == 'distribution' and 'workload_economy' in [goal for goal, _ in goals[:position]]):
            _lock_weekly_recipe_doses(features, chosen, option_variables, sessions, required_roles)
            doses_locked = True
        current = [{**variable, 'objectiveCost': costs.get(index, 0)} for index, variable in enumerate(variables)]
        preservation_stage = name in ('preservation', 'neutral_preservation', 'dose_selection')
        zero_preservation_incumbent = (preservation_stage and chosen is not None
            and sum(cost * chosen[index] for index, cost in costs.items()) + preservation_offset <= 1e-7)
        if zero_preservation_incumbent:
            stage_status, candidate = 'optimal_zero_lower_bound', chosen
        else:
            diagnostic = {'goal': name}
            stage_status, candidate = _milp_solve(current, features, timeout_seconds=_SOLVER_STAGE_SECONDS,
                                                  preserve_current=preservation_stage, diagnostics=diagnostic,
                                                  incumbent=chosen)
            solver_diagnostics.append(diagnostic)
        stages.append({'goal': name, 'status': stage_status,
            **({'weeklyDosesLocked': doses_locked} if name == 'distribution' else {})})
        if candidate is None:
            if chosen is None:
                status = stage_status
            break
        candidate = _canonicalize_objective_epigraphs(variables, features, candidate, goals)
        chosen = candidate
        score = sum(cost * chosen[index] for index, cost in costs.items())
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
        elif name == 'demand_colocation':
            stages[-1]['value'] = chosen[next(iter(costs))]
            stages[-1]['unit'] = 'unique_working_sets_per_training_occurrence'
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
            features.append((('objective', name), -math.inf, score + 1e-7, 0, costs))
    if chosen is not None and goals:
        goal_stages = [stage for stage in stages if stage.get('goal') in {name for name, _ in goals}]
        status = ('optimal' if len(goal_stages) == len(goals)
                  and all(stage['status'] in ('optimal', 'optimal_zero_lower_bound')
                          for stage in goal_stages) else 'feasible')
    dose_selection_stage = next((stage for stage in stages if stage.get('goal') == 'dose_selection'), None)
    if chosen is not None and dose_selection_stage:
        dose_selection_stage['finalCandidateValue'] = sum(
            value * chosen[index] for index, value in preferences.items()) + preservation_offset
    receipt = {**proof, 'feasible': chosen is not None, 'status': status,
               'recipeCount': sum(len(recipe['options']) for recipe in recipes),
               'optionCount': len(option_variables), 'rejectedOptions': rejected[:20],
               'physicalBlockCount': sum(len(blocks) for blocks in day_blocks),
               'firstVariableCount': sum(len(blocks) for blocks in day_blocks),
               'sourceOrderConstraintCount': sum(label[0] == 'first_respects_source_order'
                   for label, _, _, _, _ in features),
               'orderingConstraintCount': sum(label[0].startswith('first_block_ready')
                   or label[0] == 'first_respects_source_order' for label, _, _, _, _ in features),
               'objectiveProgress': stages,
               'solverDiagnostics': solver_diagnostics,
               'priorityExecution': _priority_execution(approved_order, objective_costs, stages,
                   [name for name, _ in goals], balance_rules, demand_inputs.get('status', 'unavailable'),
                   development_roles, development_budget),
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
               'objectiveInputFingerprint': joint_objective_input_fingerprint(sessions, requirements, equipment,
                   training_history, messages, restriction_policy=restriction_policy,
                   allow_educated_load_guesses=allow_educated_load_guesses,
                   preserve_source_selection=preserve_source_selection,
                   redistribution_constraints=redistribution_constraints,
                   source_working_set_budget=normalized_source_budget,
                   reviewed_baseline_workouts=reviewed_baseline_workouts),
               'candidateOrderPolicy': order_policy,
               'jointPolicy': copy.deepcopy(JOINT_POLICY_DESCRIPTOR),
               'objectivePolicy': 'approved' if approved_order is not None else 'preserve_candidate_only',
               'legacyBalanceHintApplied': False, 'selectionPolicyVersion': SELECTION_POLICY_VERSION}
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
            selected = [block['optionValues'][index] for index in block['options'] if chosen[index]]
            if selected:
                lineage_start = len(items)
                for item in copy.deepcopy(selected[0]['items']):
                    item['superset'] = f'JOINT_{day_index}_{block_index}' if item['superset'] is not None else None
                    items.append(item)
                    occurrence_lineage[day_index].append(None)
                source_key = (block['recipe']['signature'], block['recipe']['sourceSignatureOccurrence'])
                local_positions = source_recipe_positions[day_index].get(source_key)
                if local_positions is not None:
                    local_positions = [local_positions[index] for index in block['recipe']['memberOrder']]
                lineage_claims.append((source_key, day_index, lineage_start,
                    copy.deepcopy(local_positions), copy.deepcopy(block['recipe']['sourcePositions'])))
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
    plan, report = _audit_raw(draft, equipment, requirements, restriction_policy, allow_educated_load_guesses)
    apply_native_load_calibration_policy(plan, messages or [], equipment,
        getattr(training_history, 'fingerprint', None),
        allow_educated_load_guesses=allow_educated_load_guesses)
    audit_execution_rules(draft, requirements, report, plan)
    audit_execution_details(draft, requirements, report)
    if validate_loads:
        report['errors'].extend(validate_loads(plan))
    if report['errors']:
        return {**receipt, 'feasible': False, 'status': 'unverified', 'errors': report['errors'],
                'instruction': 'The assembled week failed the production audit. Preserve recipes and report this joint-planning validation failure; do not export or enter count-only repair.'}
    _finalize_development_exposure(receipt['priorityExecution'], report.get('weeklyCoverageSets', {}))
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
    if role_stage and role_stage.get('status') in ('optimal', 'optimal_zero_lower_bound'):
        role_solver_status = role_stage['status']
        role_stage = {**role_stage, 'solverStatus': role_solver_status,
            'status': effective_concentration_status(receipt['priorityExecution'], 'distribution',
                role_solver_status, include_following=True)}
    if demand_colocation_stage and demand_colocation_stage.get('status') in ('optimal', 'optimal_zero_lower_bound'):
        demand_solver_status = demand_colocation_stage['status']
        demand_colocation_stage = {**demand_colocation_stage, 'solverStatus': demand_solver_status,
            'status': effective_concentration_status(receipt['priorityExecution'], 'demand_distribution',
                demand_solver_status)}
    _attach_concentration_substage(receipt['priorityExecution'], 'distribution', role_stage)
    role_tiebreak_stage = next((stage for stage in stages
        if stage.get('goal') == 'role_concentration_tiebreak'), None)
    if role_stage_planned and role_tiebreak_stage is None:
        role_tiebreak_stage = {'goal': 'role_concentration_tiebreak',
            'status': 'not_run_after_solver_stop', 'planned': True}
    if role_tiebreak_stage and role_tiebreak_stage.get('status') in ('optimal', 'optimal_zero_lower_bound'):
        role_tiebreak_solver_status = role_tiebreak_stage['status']
        role_tiebreak_stage = {**role_tiebreak_stage,
            'solverStatus': role_tiebreak_solver_status,
            'status': effective_concentration_status(receipt['priorityExecution'], 'distribution',
                role_tiebreak_solver_status, include_following=True)}
    _attach_concentration_substage(receipt['priorityExecution'], 'distribution', role_tiebreak_stage)
    role_stage_statuses = [(role_stage or {}).get('status'),
        (role_tiebreak_stage or {}).get('status')]
    role_solver_status = ('optimal' if role_stage_statuses
        and all(value in ('optimal', 'optimal_zero_lower_bound') for value in role_stage_statuses)
        else next((value for value in role_stage_statuses
            if value not in ('optimal', 'optimal_zero_lower_bound')), 'not_run_after_solver_stop'))
    role_status = (effective_concentration_status(receipt['priorityExecution'], 'distribution',
        role_solver_status, include_following=True) if role_stage_planned else
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
    receipt['priorityExecution']['exerciseDistribution'] = copy.deepcopy(receipt['exerciseDistribution'])
    return {**receipt, 'objectiveInputFingerprint': joint_objective_input_fingerprint(result, requirements, equipment,
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
