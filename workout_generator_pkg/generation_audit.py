"""Deterministic programming audit and bounded prescription repair."""

import copy
import json
import math

from .api_client import json_call_reasoner_only_with_loading
from .domain_ops import build_workout_structure
from .plan_contract import ContractValidationError, validate_plan_index_contract
from .muscle_roles import MUSCLE_LABELS, REGIONAL_MUSCLE_LABELS
from .repair_capabilities import RECOVERY_ADJUSTMENT_GUIDANCE


MUSCLES = {
    "chest": {"FRONT_CHEST"},
    "back": {"BACK_UPPER_BACK"},
    "quads": {"FRONT_QUADRICEPS"},
    "hamstrings": {"BACK_HAMSTRING"},
    "glutes": {"BACK_GLUTEAL"},
    "shoulders": {"FRONT_DELTOIDS", "BACK_DELTOIDS"},
    "biceps": {"FRONT_BICEPS"},
    "triceps": {"FRONT_TRICEPS", "BACK_TRICEPS"},
    "calves": {"FRONT_CALVES", "BACK_CALVES"},
    'abs': {'FRONT_ABS'}, 'obliques': {'FRONT_OBLIQUES'}, 'adductors': {'FRONT_ADDUCTORS', 'BACK_ADDUCTORS'},
    'forearms': {'FRONT_FOREARM', 'BACK_FOREARM'}, 'traps': {'FRONT_TRAPEZIUS', 'BACK_TRAPEZIUS'},
    'lowerBack': {'BACK_LOWER_BACK'}, 'tibialis': {'FRONT_TIBIALIS'}, 'neck': {'FRONT_NECK', 'BACK_NECK'},
    **{region: set() for region in REGIONAL_MUSCLE_LABELS},
}
REGIONAL_MUSCLE_PARENT = {
    'latissimus_dorsi': 'back', 'upper_back': 'back',
    'deltoid_anterior': 'shoulders', 'deltoid_lateral': 'shoulders', 'deltoid_posterior': 'shoulders',
    'pectoralis_clavicular': 'chest', 'pectoralis_sternocostal': 'chest',
}
ASSUMPTIONS = {
    "secondsPerRep": 3, "generalWarmupSeconds": 300,
    "generatedRampUpSecondsPerExercise": 120, "transitionSeconds": 60,
    "primarySetCredit": 1, "secondarySetCredit": 0.5,
}
CALIBRATION_TIMING = ('estimatedSeconds includes one app-inserted calibration performance for supported loaded exercises, using the first work set reps and the normal seconds-per-rep estimate. Declared between-side rest is included when applicable. Load selection, calibration interaction, retries, and actual execution time remain unknown.')
CONSERVATIVE_REP_TIMING_BASIS = ('For duration limits and balance, timing uses exact targetSetPrescriptions reps when present; otherwise it uses the plan entry maxReps. '
    'The separate emitted-prescription estimate uses the actual reps in the materialized workout sets.')
EXCLUDED_VOLUME_CATEGORIES = {"WarmupSet", "CalibrationSet"}
VOLUME_SET_TYPES = {'WEIGHT': 'WeightSet', 'BODY_WEIGHT': 'BodyWeightSet'}


def programming_demand_evidence():
    """State what library data can and cannot establish, before and after audit."""
    return {
        'known': ('Before prescription: library exercise type/category, movement identity, equipment, and primary/secondary '
            'muscle fields. After audit: prescribed work-set count, reps or duration, effort criteria, rest fields, and '
            'audited direct/indirect library muscle credits by occurrence and session.'),
        'interpretation': ('Movement roles and muscle credits describe the program and library accounting; they are not '
            'measurements of fatigue or proof that two exercises impose the same physical demand.'),
        'notRepresentedByCurrentLibraryFields': ['support configuration', 'trunk bracing demand', 'spinal loading',
            'grip demand', 'eccentric or unfamiliar-work demand', 'actual weekday spacing'],
        'personalTolerance': ('Unknown without comparable execution and recovery evidence; do not convert missing '
            'information into a failure or approval.'),
        'optionalLibraryProperties': ('Reviewed programmingDemands annotations carry explicit present/absent values and sources. '
            'Missing annotations stay unknown. They describe execution properties, not their severity, equivalent fatigue or personal capacity.'),
    }


def render_volume_disclosure(report, muscle):
    """Render the audited credits, never infer muscle roles from exercise names."""
    totals = report['weeklyVolume'][muscle]
    sources = {'direct': {}, 'indirect': {}}
    for workout in report['workouts']:
        frequency = workout['timesCompletedInAWeek']
        for contribution in workout['contributions']:
            credits = contribution['credits'].get(muscle, {})
            for role, entries in sources.items():
                credit = credits.get(role, 0) * frequency
                if credit:
                    entry = entries.setdefault(contribution['exercise'], {'sets': 0, 'credit': 0})
                    entry['sets'] += contribution['workingSets'] * frequency
                    entry['credit'] += credit
    text = (f"{MUSCLE_LABELS.get(muscle, muscle)}: {totals['effective']:g} effective sets weekly "
            f"({totals['direct']:g} direct + {totals['indirect']:g} weighted indirect).")
    for role, entries in sources.items():
        details = '; '.join(f"{name}: {entry['sets']:g} working sets weekly "
                            f"({entry['credit']:g} credited sets)" for name, entry in entries.items())
        text += f" {role.capitalize()} credit sources: {details or 'none'}."
    return text


def render_plan_disclosures(report, muscles=None, source_draft=None, coverage_rules=()):
    """One factual disclosure view for preview, review and export; no inferred anatomy."""
    muscles = report['weeklyVolume'] if muscles is None else muscles
    lines = ['Code-computed credit sources:']
    lines.extend(render_volume_disclosure(report, muscle) for muscle in muscles if muscle in report['weeklyVolume'])
    lines.append('These library-role credits are accounting inputs, not measurements of equivalent physiological stimulus.')
    reliance = report.get('muscleCreditReliance') or {}
    if reliance.get('weeklyTargets') or reliance.get('perSessionMinimums'):
        lines.extend(['', 'Muscle-credit reliance sensitivity (diagnostic):'])
        lines.append('Credits follow the selected exercise definitions’ primary (1.0) and secondary (0.5) muscle arrays. '
            'Physiological equivalence is unknown. The sensitivity below omits one definition’s assigned credits while '
            'holding the plan fixed; it is not a proposed reclassification, substitute, or feasibility result.')
        for item in reliance.get('weeklyTargets', []):
            dependencies = item.get('singleDefinitionDependencies', [])
            if dependencies:
                sources = '; '.join(f"{dependency['exerciseName']} contributes {dependency['effectiveCredit']:g}; "
                    f"omitting its assigned credits leaves {dependency['effectiveSetsWithoutDefinition']:g} "
                    f"({dependency['shortfallBelowMinimum']:g} below minimum)" for dependency in dependencies)
                lines.append(f"Weekly {MUSCLE_LABELS.get(item['muscle'], item['muscle'])} target "
                    f"{volume_target_text(item['approvedTarget'])} has {item['auditedEffectiveSets']:g} effective sets; "
                    f"each listed definition is individually decisive: {sources}.")
        for item in reliance.get('perSessionMinimums', []):
            dependencies = item.get('singleDefinitionDependencies', [])
            if dependencies:
                sources = '; '.join(f"{dependency['exerciseName']} contributes {dependency['effectiveCredit']:g}; "
                    f"omitting its assigned credits leaves {dependency['effectiveSetsWithoutDefinition']:g} "
                    f"({dependency['shortfallBelowMinimum']:g} below minimum)" for dependency in dependencies)
                lines.append(f"{item['session']} {MUSCLE_LABELS.get(item['muscle'], item['muscle'])} minimum "
                    f"{item['minimum']:g} has {item['auditedEffectiveSets']:g} effective sets; "
                    f"each listed definition is individually decisive: {sources}.")
    lines.extend(['', 'Credits use the library\'s tracked regions. Finer anatomical sub-region totals are not '
        'independently available; the exercise and movement distribution is reported below without inventing them.'])
    if 'back' in muscles:
        lines.append('Back detail — lats versus upper back: the library credits one combined region, '
            'so separate exercise attribution and relative development of these subregions are unverified. '
            'The horizontal-pull and vertical-pull rows below identify selected movement sources; '
            'these roles do not establish a measured allocation between lats and upper back.')
    if 'shoulders' in muscles:
        lines.append('Shoulder detail — anterior, lateral and rear deltoids: aggregate primary/secondary '
            'shoulder credits do not independently separate individual heads. The lateral-delt and rear-delt '
            'rows below identify movements explicitly assigned those roles. Pressing sources are listed '
            'in the shoulder credit sources and horizontal/vertical push rows; anterior-delt-specific '
            'attribution and relative head development remain unverified. These descriptions add no credits or quotas.')
    descriptions = {rule['key']: rule['description'] for rule in coverage_rules}
    sources = {}
    if source_draft:
        for day, source_day in zip(report['workouts'], source_draft.get('workouts', []), strict=True):
            frequency = day['timesCompletedInAWeek']
            for contribution, exercise in zip(day['contributions'], source_day['exercises'], strict=True):
                for role in set(exercise.get('satisfiesCoverage', [])):
                    entries = sources.setdefault(role, {})
                    name = contribution['exercise']
                    entries[name] = entries.get(name, 0) + contribution['workingSets'] * frequency
    for role, count in report.get('weeklyCoverageSets', {}).items():
        details = '; '.join(f'{name}: {sets:g} working sets weekly' for name, sets in sources.get(role, {}).items())
        lines.append(f"{descriptions.get(role, role.replace('_', ' '))}: {count:g} working sets weekly. "
                     + (details + '.' if details else ''))
    if report.get('coverageAccounting'):
        lines.append(report['coverageAccounting'])
    lines.extend(['', f"Total weekly working sets: {report['weeklyWorkingSets']} (each physical set counted once; warm-ups excluded)."])
    return '\n'.join(lines)


def render_optimization_disclosure(priority_execution):
    """Keep feasibility and incomplete balance optimization distinct for approval."""
    priority_execution = priority_execution or {}
    priorities = [entry for entry in priority_execution.get('approvedPriorities', [])
        if entry.get('owner') == 'joint_solver']
    development = priority_execution.get('developmentEmphasis') or {}
    development_roles = development.get('roleKeys') or []
    if not priorities and not development_roles:
        return ''
    meanings = {'optimal': 'best result proven within the supplied menu and preceding objectives',
        'feasible': 'valid candidate found; the approved balance hierarchy is not proven optimal',
        'unproven': 'bounded search did not establish this priority; this is not proof that improvement is impossible',
        'unavailable_evidence': 'not optimized because verified exercise evidence is unavailable'}
    lines = ['Programming-priority evidence:']
    lines.extend(f"{entry['priority'].replace('_', ' ')}: "
        + meanings.get(entry['status'], entry['status'].replace('_', ' ')) + '.' for entry in priorities)
    for entry in priorities:
        if entry.get('priority') != 'duration_balance':
            continue
        stage = entry.get('solverStage') or {}
        residual = stage.get('value')
        if isinstance(residual, (int, float)) and not isinstance(residual, bool) and math.isfinite(residual) and residual > 0:
            lines.append(f"Duration balance retains {residual:g} seconds of excess beyond the approved duration-similarity band; "
                'the preferred tolerance remains unmet.')
    concentration = priority_execution.get('structuralConcentration') or {}
    placement = concentration.get('rolePlacement') or {}
    if placement.get('profiles') and placement.get('status') != 'not_requested':
        status = effective_concentration_status(priority_execution, 'distribution',
            placement.get('solverStatus', placement.get('status', 'not_run')), include_following=True)
        peaks = [profile.get('peakSurplusPerOccurrence') for profile in placement['profiles']]
        peaks = [value for value in peaks if type(value) in (int, float) and math.isfinite(value)]
        peak_text = (f" The final largest role peak is {max(peaks):g} working sets above its frequency-weighted per-occasion average."
            if peaks else '')
        lines.append('Movement-role placement: ' + meanings.get(status, status.replace('_', ' ')) + '.'
            + peak_text + ' This placement comparison preserves weekly exercise-recipe doses and exact target counts; '
            'it does not add volume to make inclusion-only roles appear balanced. These counts describe structural distribution, not fatigue or personal suitability.')
        tie_status = placement.get('sumTieBreakStatus')
        if tie_status and tie_status != 'not_requested':
            peak_sum = placement.get('profilePeakSurplusSumPerOccurrence')
            sum_text = (f' The sum of distinct role-profile peak surpluses is {peak_sum:g} sets per occurrence.'
                if type(peak_sum) in (int, float) and math.isfinite(peak_sum) else '')
            lines.append('After preserving the worst role peak, the role-balance tie-break reduces the sum of '
                'distinct role-profile peak surpluses: ' + meanings.get(tie_status, tie_status.replace('_', ' '))
                + '.' + sum_text)
    union = concentration.get('verifiedDemandUnion')
    if union and union.get('optimizationStatus') != 'not_requested':
        union_stage = union.get('stage') or {}
        union_status = effective_concentration_status(priority_execution, 'demand_distribution',
            union_stage.get('solverStatus', union.get('optimizationStatus') or union_stage.get('status') or 'not_run'))
        lines.append('Verified-demand co-location: ' + meanings.get(union_status,
            union_status.replace('_', ' '))
            + '. The comparison counts each physical working set once across verified-present properties. '
            'Unavailable properties remain unknown; this is not a fatigue-equivalence score.')
        unavailable_groups = sorted(union.get('unavailableGroups', {}))
        if union.get('status') in ('partial', 'partial_fixed_evidence'):
            unknown_text = ', '.join(unavailable_groups) or 'some fixed-workout properties'
            lines.append('Demand-distribution optimization includes only fully classified groups. ' +
                f'{unknown_text} remain unclassified, so this result and later priorities are conditional on the known evidence; ' +
                'they do not establish a complete demand-distribution optimum.')
    family_distribution = priority_execution.get('exerciseDistribution') or {}
    if family_distribution and family_distribution.get('status') != 'not_requested':
        lines.append('Exercise-family distribution compares only maximal completely classified qualified role pools, '
            'without charging strict subset pools again for the same sets. '
            'Source-backed variants share one family; unclassified pools are omitted, never counted as diverse. '
            'Family identity establishes neither fatigue equivalence nor personal suitability.')
        for profile in family_distribution.get('profiles', []):
            families = '; '.join('/'.join(profile['familyDefinitions'][family]) + f': {sets:g} weekly working sets'
                for family, sets in profile.get('weeklyWorkingSetsByFamily', {}).items())
            lines.append(', '.join(profile['roles']) + ' family exposures — ' + families + '.')
    if development_roles:
        role_names = ', '.join(role.replace('_', ' ') for role in development_roles)
        combined = development.get('combinedExposure')
        status = development.get('status', 'not_run')
        optimization_requested = status != 'not_requested'
        comparison = ('maximize the minimum weekly raw working-set exposure'
            if optimization_requested else 'no additional exposure optimization was requested')
        if combined is not None and optimization_requested:
            comparison += ', then maximize combined exposure without reducing that minimum or worsening preceding approved balance objectives'
        source_budget = development.get('sourceBudget') or {}
        has_active_cap = source_budget.get('status') == 'applied'
        development_meanings = {
            'optimal': ('best minimum exposure proven within the supplied menu and active source-set cap'
                if has_active_cap else 'best minimum exposure proven within the supplied menu and preceding objectives'),
            'optimal_zero_lower_bound': ('best minimum exposure proven at the objective lower bound within the supplied menu and active source-set cap'
                if has_active_cap else 'best minimum exposure proven at the objective lower bound within the supplied menu and preceding objectives'),
            'feasible': ('a candidate was found, but the best exposure within this source-set cap is not proven'
                if has_active_cap else 'a candidate was found, but the best exposure within the supplied menu is not proven'),
            'source_budget_conflict_requires_review': (
                'the source-set cap blocked a candidate; an uncapped diagnostic found hard feasibility, '
                'so this is a budget conflict, not proof that hard requirements are infeasible. Review is required; no export candidate is available'),
            'source_budget_unproven_requires_review': (
                'the capped solve could not prove a candidate; an uncapped diagnostic found hard feasibility, '
                'so fit under this budget is unresolved, not proof that hard requirements are infeasible. Review is required; no export candidate is available'),
            'unavailable_evidence': 'not optimized because verified evidence is unavailable',
            'not_run': 'not run',
            'not_run_after_solver_stop': 'not run after an earlier solver stop',
            'not_requested': 'not requested',
        }
        if combined is not None and optimization_requested:
            development_meanings.update({
                'optimal': 'best minimum and combined exposure proven within the supplied menu and preceding objectives',
                'optimal_zero_lower_bound': 'best minimum and combined exposure proven within the supplied menu and preceding objectives',
            })
        attained = development.get('minimumWeeklyWorkingSets')
        attained_text = (f'; attained minimum {_format_weekly_sets(attained)} raw working sets/week'
            if attained is not None and status in ('optimal', 'optimal_zero_lower_bound', 'feasible') else '')
        role_exposure = development.get('roleWeeklyWorkingSets') or {}
        if role_exposure:
            attained_text += '; final role exposure ' + ', '.join(
                f'{role.replace("_", " ")}: {_format_weekly_sets(sets)} raw working sets/week'
                for role, sets in sorted(role_exposure.items()))
        if optimization_requested and combined and combined.get('weeklyWorkingSets') is not None:
            attained_text += f'; combined development-role exposure {_format_weekly_sets(combined["weeklyWorkingSets"])} role-set credits/week'
        scope_sentence = (
            ('This compares allocations within the reported working-set budget; '
                if has_active_cap else 'This compares allocations under the approved hard constraints; ')
            if optimization_requested else
            'These are final role-exposure counts; they do not '
        )
        lines.append(
            f'Development allocation across {role_names}: {comparison}. '
            f'{_development_source_budget_text(source_budget)} '
            f'Result: {development_meanings.get(status, status.replace("_", " "))}{attained_text}. '
            + scope_sentence
            + ('establish adequate stimulus or personal suitability.' if not optimization_requested else
                'it does not establish adequate stimulus or personal suitability.'))
        if combined is not None and optimization_requested:
            lines.append('Development-role exposures can overlap; their combined count is not a count of distinct physical sets.')
        menu_limits = development.get('menuLimits') or {}
        if (menu_limits.get('status') == 'proven_upper_bounds'
                or menu_limits.get('status') == 'infeasible_relaxation' and menu_limits.get('roleUpperBounds')):
            limits_text = ', '.join(f'{role.replace("_", " ")}: {_format_weekly_sets(value)}'
                for role, value in sorted(menu_limits.get('roleUpperBounds', {}).items()))
            lines.append(f'Pre-prescription menu upper bounds (weekly role sets): {limits_text}. '
                'These individual volume/coverage/budget bounds omit timing, grouping and integer selection; '
                'they are not target doses or proof of adequate development.'
                + (' The disclosed menu limits were explicitly accepted.' if menu_limits.get('accepted') else ''))
            for role, constraints in sorted(menu_limits.get('roleUpperBoundConstraints', {}).items()):
                binding = [item for item in constraints if item.get('kind') != 'source_set_cap']
                cap = next((item for item in constraints if item.get('kind') == 'source_set_cap'), None)
                if not binding:
                    continue
                parts = [f"{item['key'].replace('_', ' ')} {item['kind'].replace('weekly_muscle_', '').replace('required_coverage_', '').replace('_', ' ')} {item['limit']:g}"
                    for item in binding]
                cap_text = (f" The source-set cap of {cap['limit']:g} was nonbinding, with {cap.get('slack', 0):g} sets of slack."
                    if cap and cap.get('slack', 0) > 1e-6 else '')
                lines.append(f"The {role.replace('_', ' ')} menu ceiling is bound by "
                    + ', '.join(parts) + '.' + cap_text
                    + ' Raising a nonbinding set cap alone cannot change this continuous bound.')
                frequency = menu_limits.get('minimumSessionRequirements', {}).get(role)
                if frequency:
                    lines.append(f"The menu ceiling comparison does not prove the approved minimum of "
                        f"{frequency['minimumSessions']} weekly sessions for {role.replace('_', ' ')}; "
                        'session placement is checked by the joint plan audit.')
            for conflict in menu_limits.get('approvedMinimumConflicts', []):
                lines.append(f"Qualified-menu conflict for {conflict['role'].replace('_', ' ')}: approved "
                    f"{conflict['kind']} minimum {conflict.get('required', conflict.get('requiredSessions'))} "
                    f"exceeds the continuous qualified-menu upper bound "
                    f"{conflict['qualifiedMenuUpperBound']:g}. This identifies a current-menu conflict, not a universal impossibility.")
        elif menu_limits.get('status') == 'infeasible_relaxation':
            lines.append('The current qualified menu conflicts with at least one approved continuous volume, role or source-set bound; '
                'this does not establish that another qualified menu is infeasible.')
        elif menu_limits:
            lines.append('Pre-prescription development limits were not proven; no menu ceiling is established.')
        coupling = menu_limits.get('volumeCreditCoupling') or {}
        for profile in coupling.get('profileLowerBounds', []):
            members = profile.get('members', [])
            profile_name = ', '.join(item.get('name') or item.get('id') or 'unnamed definition'
                for item in members)
            credits = ', '.join(f'{muscle.replace("_", " ")} {value:g}'
                for muscle, value in profile.get('creditsPerWorkingSet', {}).items())
            active = ', '.join(f"{item['muscle'].replace('_', ' ')} {item['boundary']} {item['targetSets']:g}"
                for item in profile.get('activeWeeklyVolumeTargets', []))
            boundary_text = (f' At this witness, active approved weekly target boundaries are {active}.'
                if active else '')
            lines.append(f"Continuous credit-only witness: the supplied menu requires at least "
                f"{profile.get('minimumWeeklyWorkingSets', 0):g} weekly working sets from the "
                f"{profile_name or 'reported exercise profile'} profile ({credits}).{boundary_text} "
                'These boundaries co-occur in one minimizing witness; this does not prove any single target causes the floor or that changing a target improves a complete plan.')
        scope = development.get('scope')
        if (optimization_requested and isinstance(scope, str) and scope
                and source_budget.get('status') != 'unbounded_by_user'):
            lines.append(f'Scope: {scope}')
    proven_statuses = {'optimal', 'optimal_zero_lower_bound', 'no_applicable_options'}
    incomplete = any(entry['status'] not in proven_statuses for entry in priorities)
    incomplete = incomplete or (bool(development_roles)
        and development.get('status') not in ('optimal', 'optimal_zero_lower_bound', 'not_requested'))
    if incomplete:
        lines.append('Quality completion: incomplete. At least one requested optimization is feasible only, '
            'unproven, or unavailable under the recorded evidence and search scope. A passing native audit '
            'or accepted export does not establish that objective as achieved; personal suitability remains unverified.')
    else:
        lines.append('Quality completion: requested optimization stages are proven or have no applicable options within their recorded menu, '
            'evidence and preceding-priority scopes. Native compliance and export acceptance are separate checks; '
            'this result does not establish adequate stimulus or personal suitability.')
    return '\n'.join(lines)


def effective_concentration_status(priority_execution, parent_priority, solver_status, *, include_following=False):
    """Do not report a polish as globally optimal when its priority prefix is unproven."""
    proven = ('optimal', 'optimal_zero_lower_bound')
    if solver_status not in proven:
        return solver_status
    priorities = priority_execution.get('approvedPriorities', [])
    parent = next((entry for entry in priorities if entry.get('priority') == parent_priority), None)
    if parent and parent.get('status') not in proven:
        return 'feasible'
    if include_following:
        for entry in priorities:
            if entry.get('owner') != 'joint_solver':
                continue
            if entry.get('status') not in (*proven, 'no_applicable_options'):
                return 'feasible'
    return solver_status


def _format_weekly_sets(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return f'{value:g}'
    return 'unknown'


def _development_source_budget_text(source_budget):
    if source_budget.get('status') == 'unbounded_by_user':
        return ('No user-set weekly working-set cap was supplied; other approved hard requirements '
            'still bound the selected plan.')
    variable_budget = _format_weekly_sets(source_budget.get('variableSourceWorkingSets',
        source_budget.get('sourceSubmittedWorkingSets')))
    fixed_sets = _format_weekly_sets(source_budget.get('fixedExistingWorkingSets'))
    total_budget = _format_weekly_sets(source_budget.get('sourceBudgetWeeklyWorkingSets'))
    variable_cap = _format_weekly_sets(source_budget.get('variableMenuCapWorkingSets',
        source_budget.get('variableSourceWorkingSets', source_budget.get('sourceSubmittedWorkingSets'))))
    source_names = {
        'code_preparation_hard_feasible_set_allocation': 'code-prepared hard-feasible allocation',
        'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions':
            'code-prepared workout allocation plus existing sessions',
        'submitted_candidate_session_counts': 'submitted candidate session counts',
    }
    source = source_budget.get('source')
    source_label = source_names.get(source, 'recorded source')
    return (f'Source budget ({source_label}): {variable_budget} weekly variable-session sets, plus '
        f'{fixed_sets} fixed-session sets; {total_budget} total source weekly sets. '
        f'The variable-menu cap is {variable_cap} weekly sets; fixed-session sets remain constant.')


def render_program_guidance(report, muscles=None, source_draft=None, coverage_rules=(), *, priority_execution=None):
    """Render requirement exceptions and code-computed disclosures for the final artifact."""
    overrides = report.get('requirementOverrides', {})
    exceptions = '\n'.join(f"{overrides['status'].capitalize()} requirement exception: {change['path']} "
        f"{change['from']} to {change['to']}. All unlisted requirements remain binding."
        for change in overrides.get('changes', []))
    optimization = render_optimization_disclosure(priority_execution or report.get('priorityExecution'))
    return (exceptions + '\n\n' if exceptions else '') + RECOVERY_ADJUSTMENT_GUIDANCE + ('\n\n' + optimization if optimization else '') + '\n\n' + render_plan_disclosures(
        report, muscles, source_draft, coverage_rules)


def build_programming_summary(report, emitted_report, source_draft, plan_index, review_draft,
                              progression_capabilities, weekly_targets, final_artifact=None,
                              requirements=None, priority_execution=None, priority_tradeoffs=None,
                              demand_distribution=None, definition_demand_facts_by_ref=None):
    """Build reviewer facts from audited prescriptions while retaining occurrence identity."""
    if final_artifact is None:
        from .domain_ops import reviewable_workout_artifact
        final_artifact = reviewable_workout_artifact(plan_index, '')
    plan_exercises = {exercise['id']: exercise for exercise in plan_index['exercises']}
    review_exercises = {exercise['id']: exercise for exercise in review_draft['exercises']}
    sources_by_exercise = {}
    for source_day, plan_day in zip(source_draft['workouts'], plan_index['workouts'], strict=True):
        for source, identifier in zip(source_day['exercises'], plan_day['exerciseIds'], strict=True):
            plan_exercise = plan_exercises[identifier]
            review_exercise = review_exercises[identifier]
            if source['definition_id'] != review_exercise['libraryDefinitionId']:
                raise ValueError(f'Exercise occurrence {identifier} does not match its submitted definition.')
            sources_by_exercise[identifier] = (source, plan_exercise, plan_day, review_exercise)

    exposures = {}
    regional_weekly = {region: {'knownWeeklyEffectiveSets': 0, 'unknownOccurrences': [],
        'evidenceSources': set(), 'aggregateParentWorkingSetCredits': 0}
        for region in REGIONAL_MUSCLE_LABELS}
    contributions_by_exercise = {item['exerciseId']: item for day in report['workouts']
        for item in day['contributions']}
    library_definitions = review_draft.get('libraryDefinitions', {})
    from .recipe_contracts import regional_muscle_facts
    for identifier, (source, plan_exercise, plan_day, review_exercise) in sources_by_exercise.items():
        reference = review_exercise['libraryDefinitionId']
        definition = copy.deepcopy(library_definitions.get(reference, {}))
        definition['id'] = plan_exercise.get('libraryDefinitionId') or source['definition_id']
        regional_facts = regional_muscle_facts(definition, source['numWorkSets'])
        contribution = contributions_by_exercise.get(identifier, {})
        occurrence_regional = {'known': {}, 'unknownRegions': []}
        frequency = plan_day['timesCompletedInAWeek']
        for region, fact in regional_facts.items():
            parent = REGIONAL_MUSCLE_PARENT[region]
            parent_credit = contribution.get('credits', {}).get(parent, {})
            parent_credit_sets = parent_credit.get('direct', 0) + parent_credit.get('indirect', 0)
            totals = regional_weekly[region]
            totals['aggregateParentWorkingSetCredits'] += parent_credit_sets * frequency
            if fact['status'] == 'present':
                weekly_sets = fact['effectiveSets'] * frequency
                occurrence_regional['known'][region] = {
                    'effectiveSets': fact['effectiveSets'], 'weeklyEffectiveSets': weekly_sets,
                    'source': fact['source']}
                totals['knownWeeklyEffectiveSets'] += weekly_sets
                totals['evidenceSources'].add(fact['source'])
            elif parent_credit_sets:
                occurrence_regional['unknownRegions'].append(region)
                totals['unknownOccurrences'].append({
                    'exerciseId': identifier, 'exercise': plan_exercise['name'],
                    'session': plan_day['name'], 'sessionsPerWeek': frequency,
                    'aggregateParentWorkingSetCredits': parent_credit_sets * frequency})
        entry = exposures.setdefault(reference, {'name': plan_exercise['name'],
            'weeklyWorkingSets': 0, 'occurrences': []})
        count = source['numWorkSets'] * plan_day['timesCompletedInAWeek']
        contribution = contributions_by_exercise.get(identifier, {})
        entry['weeklyWorkingSets'] += count
        entry['occurrences'].append({'exercise': identifier, 'session': plan_day['name'], 'sets': source['numWorkSets'],
            'sessionsPerWeek': plan_day['timesCompletedInAWeek'],
            'category': plan_exercise.get('exerciseCategory'),
            'exerciseType': plan_exercise.get('exerciseType'),
            'movementRef': copy.deepcopy(plan_exercise.get('movementRef')),
            'programmingDemandFacts': copy.deepcopy((definition_demand_facts_by_ref or {}).get(reference, {})),
            'equipmentId': plan_exercise.get('equipmentId'),
            'requiredAccessoryEquipmentIds': copy.deepcopy(plan_exercise.get('requiredAccessoryEquipmentIds', [])),
            'primaryMuscles': copy.deepcopy(plan_exercise.get('muscleGroups', [])),
            'secondaryMuscles': copy.deepcopy(plan_exercise.get('secondaryMuscleGroups', [])),
            'roles': source.get('satisfiesCoverage', []),
            'prescribedReps': ([source['minReps'], source['maxReps']]
                if source.get('minReps') is not None and source.get('maxReps') is not None else None),
            'prescribedDurationSeconds': source.get('durationSeconds'),
            'effortAcceptance': source.get('effortAcceptance'),
            'restBetweenSetsSeconds': source.get('restBetweenSetsSeconds'),
            'restAfterExerciseSeconds': source.get('restAfterExerciseSeconds'),
            'intraSetRestInSeconds': source.get('intraSetRestInSeconds'),
            'weeklyMuscleCredits': {muscle: {role: value * plan_day['timesCompletedInAWeek']
                for role, value in credits.items()} for muscle, credits in contribution.get('credits', {}).items()},
            'regionalMuscleEvidence': occurrence_regional,
            'loadCeilingKg': progression_capabilities.get(reference, {}).get('maximumSelectableLoadKg'),
            'capacityEvidenceStatus': progression_capabilities.get(reference, {}).get('evidenceStatus', 'unknown')})

    coverage_requirements = []
    coverage_balance_evidence = []
    development_receipt = (priority_execution or {}).get('developmentEmphasis') or {}
    if requirements:
        coverage_sessions = report.get('workouts', [])
        weekly_coverage = report.get('weeklyCoverageSets', {})
        for requirement in requirements.get('requiredCoverage', []):
            key = requirement['key']
            session_counts = [day.get('coverageSets', {}).get(key, 0) for day in coverage_sessions]
            present = (all(count > 0 for count in session_counts)
                if requirement['scope'] == 'eachSession' else weekly_coverage.get(key, 0) > 0)
            intent = requirement.get('intent', 'inclusion')
            coverage_requirements.append({
                'key': key, 'description': requirement['description'], 'scope': requirement['scope'],
                **({'intent': requirement['intent']} if requirement.get('intent') is not None else {}),
                'weeklyWorkingSets': weekly_coverage.get(key, 0),
                'sessionWorkingSets': [{'session': day['name'], 'workingSets': count}
                    for day, count in zip(coverage_sessions, session_counts, strict=True)],
                **({'minimumWeeklySets': requirement['minimumWeeklySets']}
                    if 'minimumWeeklySets' in requirement else {}),
                **({'attainedMinimumWeeklySets': weekly_coverage.get(key, 0)}
                    if 'minimumWeeklySets' in requirement else {}),
                **({'minimumSessions': requirement['minimumSessions']}
                    if 'minimumSessions' in requirement else {}),
                **({'attainedMinimumSessions': sum((1 if count > 0 else 0)
                    * day.get('timesCompletedInAWeek', 1)
                    for day, count in zip(coverage_sessions, session_counts, strict=True))}
                    if 'minimumSessions' in requirement else {}),
                'acceptanceStatus': (_development_acceptance_status(development_receipt, key, requirement,
                    weekly_coverage.get(key, 0), sum((1 if count > 0 else 0)
                    * day.get('timesCompletedInAWeek', 1)
                    for day, count in zip(coverage_sessions, session_counts, strict=True)))
                    if intent == 'development' or 'minimumWeeklySets' in requirement or 'minimumSessions' in requirement else
                    'required_presence_met' if present else 'required_presence_missing'),
                'adequacyStatus': ('not_established_by_programming_minima'
                    if intent == 'development' and ('minimumWeeklySets' in requirement or 'minimumSessions' in requirement) else
                    'unverified_no_explicit_dose_or_frequency_threshold'
                    if intent == 'development' else 'not_a_development_claim'),
                'interpretation': (_development_summary_interpretation(development_receipt)
                    if requirement.get('intent') == 'development' and development_receipt.get('roleKeys') else
                    'Development intent is qualitative; these exposure counts do not by themselves establish adequate development.'
                    if requirement.get('intent') == 'development' else
                    'Required role presence follows scope; these counts do not set a minimum dose.')})
        for rule in requirements.get('executionRules', []):
            if rule['kind'] != 'coverageBalance':
                continue
            pair = {'first': rule['first'], 'second': rule['second'], 'scope': rule['scope']}
            relationship = rule.get('relationship', 'balanced')
            pair['relationship'] = relationship
            if rule['scope'] == 'weekly':
                pair['workingSets'] = {key: weekly_coverage.get(key, 0)
                    for key in (rule['first'], rule['second'])}
                counts = pair['workingSets']
                if relationship == 'first_not_less_than_second':
                    pair['comparisonOutcome'] = ('met' if counts[rule['first']] >= counts[rule['second']]
                        else 'first_below_second')
                else:
                    pair['absoluteDifference'] = abs(counts[rule['first']] - counts[rule['second']])
            else:
                pair['sessions'] = [{'session': day['name'], 'workingSets': {
                    key: day.get('coverageSets', {}).get(key, 0)
                    for key in (rule['first'], rule['second'])}}
                    for day in coverage_sessions]
                for session in pair['sessions']:
                    counts = session['workingSets']
                    if relationship == 'first_not_less_than_second':
                        session['comparisonOutcome'] = ('met' if counts[rule['first']] >= counts[rule['second']]
                            else 'first_below_second')
                    else:
                        session['absoluteDifference'] = abs(counts[rule['first']] - counts[rule['second']])
            pair['interpretation'] = (
                ('The preferred comparison is for the first role to have at least as many counted working sets as the second; this is a soft objective, not a hard quota.'
                    if relationship == 'first_not_less_than_second' else
                    'Requested qualitative balance relationship; no numeric tolerance is approved. Unequal counts alone are not a violation.')
                + ' Coverage roles may overlap.')
            coverage_balance_evidence.append(pair)

    sessions = []
    for day, emitted, artifact_day in zip(report['workouts'], emitted_report['workouts'],
                                          final_artifact['workouts'], strict=True):
        setup_by_exercise = {item['exerciseId']: item for item in emitted.get('setupEstimates', [])}
        exercise_order = []
        transitions = []
        previous_block_last = None
        pending_rest_seconds = 0
        for component in artifact_day['components']:
            if component['type'] == 'Rest':
                if previous_block_last is not None:
                    pending_rest_seconds += component['timeInSeconds']
                continue
            exercises = (component.get('exercises', []) if component['type'] == 'Superset'
                         else [component] if component['type'] == 'Exercise' else [])
            if not exercises:
                continue
            current_block = [{'id': exercise['id'], 'name': exercise['name']} for exercise in exercises]
            exercise_order.extend(current_block)
            if previous_block_last is not None:
                current = current_block[0]
                setup_seconds = setup_by_exercise.get(current['id'], {}).get('seconds')
                transitions.append({
                    'scope': 'between_blocks',
                    'fromExerciseId': previous_block_last['id'], 'toExerciseId': current['id'],
                    'recoveryOwner': {'exerciseRef': previous_block_last['id'],
                        'field': 'restAfterExerciseSeconds'},
                    'setupOwner': {'exerciseRef': current['id'], 'field': 'setupSeconds'},
                    'betweenExerciseRestComponentSeconds': pending_rest_seconds,
                    'estimatedSetupSeconds': setup_seconds,
                    'setupScope': 'one_time_before_destination_block',
                    'estimatedTransitionSeconds': (pending_rest_seconds + setup_seconds
                        if setup_seconds is not None else None),
                })
            previous_block_last = current_block[-1]
            pending_rest_seconds = 0
        timing = emitted['timing']
        sessions.append({
            'name': day['name'], 'muscles': {muscle: day['volume'].get(muscle) for muscle in weekly_targets},
            'movementSets': day.get('coverageSets', {}), 'conservativeEstimatedSeconds': day['estimatedSeconds'],
            'emittedPrescriptionEstimatedSeconds': emitted['estimatedSeconds'],
            'finalExerciseOrder': exercise_order,
            'timingComponents': {
                'prescribedRecoveryRestSeconds': timing['restSeconds'],
                'estimatedSetupSeconds': timing['transitionSeconds'],
                'estimatedTotalSeconds': emitted['estimatedSeconds'],
                'transitions': transitions,
                'setupScope': 'One-time allowance before each exercise after the first; not repeated per set or superset round.',
                'supersetRoundSetup': 'Repeated equipment changes between superset members are not estimated; treat their duration as unknown.',
                'note': ('Transition rows show separate Rest components and one-time setup estimates between blocks. Setup is not prescribed recovery and is not repeated each superset round. '
                    'Prescribed set, explicit Rest, and superset-round rests are included in prescribedRecoveryRestSeconds. All components are already included in estimatedTotalSeconds.'),
            },
        })

    timing_assumptions = copy.deepcopy(report['assumptions'])
    if report.get('timingRepBasis'):
        timing_assumptions['repCountBasis'] = report['timingRepBasis']
    summary = {'sessions': sessions,
        'exposures': exposures, 'timingAssumptions': timing_assumptions, 'executionTimeVerified': False,
        'muscleCreditReliance': copy.deepcopy(report.get('muscleCreditReliance', {})),
        'regionalMuscleSummary': {region: {
            'status': ('unknown_selected_aggregate_contributions' if totals['unknownOccurrences'] else
                'no_selected_aggregate_parent_exposure' if not totals['aggregateParentWorkingSetCredits'] else
                'source_backed_selected_contributions'),
            'weeklyEffectiveSets': (None if totals['unknownOccurrences'] else totals['knownWeeklyEffectiveSets']),
            'knownWeeklyEffectiveSets': totals['knownWeeklyEffectiveSets'],
            'aggregateParentWorkingSetCredits': totals['aggregateParentWorkingSetCredits'],
            'evidenceSources': sorted(totals['evidenceSources']),
            'unknownOccurrences': totals['unknownOccurrences']}
            for region, totals in regional_weekly.items()},
        'demandEvidence': programming_demand_evidence(),
        'techniqueLimitations': 'Only library movement identity and typed effort criteria are available. Unspecified technique is unknown; do not infer elbow position or anatomical stimulus from a movement name.',
        'personalRecoveryAndTolerance': 'Not established from plan text. Missing comparable performance or recovery data is uncertainty, not proof of incapacity or suitability.'}
    if requirements is not None:
        summary['coverageRequirements'] = coverage_requirements
        summary['coverageBalanceEvidence'] = coverage_balance_evidence
        credit_candidates = {source['definition_id']: {
            'id': source['definition_id'], 'name': exercise['name'],
            'creditsPerWorkingSet': muscle_credits_per_set(exercise)}
            for source, exercise, _, _ in sources_by_exercise.values()}
        summary['volumeCreditCoupling'] = muscle_credit_coupling_evidence(
            list(credit_candidates.values()), requirements)
    if priority_execution is not None:
        summary['priorityExecution'] = copy.deepcopy(priority_execution)
    if priority_tradeoffs is not None:
        summary['priorityTradeoffs'] = copy.deepcopy(priority_tradeoffs)
    if demand_distribution is not None:
        summary['demandDistribution'] = copy.deepcopy(demand_distribution)
    return summary


def _development_summary_interpretation(development):
    roles = ', '.join(role.replace('_', ' ') for role in development.get('roleKeys', []))
    status = development.get('status', 'not_run')
    budget_text = _development_source_budget_text(development.get('sourceBudget') or {})
    if status == 'source_budget_conflict_requires_review':
        return (f'Development allocation across {roles} could not fit the active source-set budget. '
            f'{budget_text} The uncapped diagnostic found hard feasibility; this is a budget conflict, not proof '
            'that the hard requirements are infeasible. No export candidate is available.')
    if status == 'source_budget_unproven_requires_review':
        return (f'Development allocation across {roles} remains unproven under the active source-set budget. '
            f'{budget_text} The uncapped diagnostic found hard feasibility; this does not prove the hard requirements '
            'are infeasible. No export candidate is available.')
    if status in ('optimal', 'optimal_zero_lower_bound', 'feasible'):
        attained = development.get('minimumWeeklyWorkingSets')
        result = (f' The selected minimum was {_format_weekly_sets(attained)} raw working sets/week.'
            if attained is not None else '')
        return (f'Development intent is qualitative; the solver compared relative weekly raw-set exposure across '
            f'{roles} within the reported source-set budget. {budget_text}{result}'
            + (' It then compared combined development-role exposure without reducing that minimum or worsening preceding approved balance objectives.'
               if development.get('combinedExposure') is not None else '')
            + ' This comparison sets no minimum '
            'and does not establish adequate development or personal suitability.')
    return 'Development intent is qualitative; these exposure counts do not by themselves establish adequate development.'


def _development_acceptance_status(development, role, requirement=None, weekly_sets=0, sessions=0):
    """Keep explicit planning minima separate from solver ranking and adequacy."""
    requirement = requirement or {}
    if 'minimumWeeklySets' in requirement or 'minimumSessions' in requirement:
        weekly_met = weekly_sets >= requirement.get('minimumWeeklySets', 0)
        sessions_met = sessions >= requirement.get('minimumSessions', 0)
        return 'approved_programming_minima_met' if weekly_met and sessions_met else 'approved_programming_minima_unmet'
    if role not in development.get('roleKeys', []):
        return 'development_objective_not_run'
    status = development.get('status', 'not_run')
    if status in ('optimal', 'optimal_zero_lower_bound'):
        return 'exposure_optimized_within_reported_scope'
    if status == 'feasible':
        return 'exposure_feasible_optimality_unproven'
    if status == 'unavailable_evidence':
        return 'exposure_not_optimized_evidence_unavailable'
    return 'exposure_unresolved_' + status


def available_muscle_targets(equipment=None):
    if equipment is None or 'exerciseDefinitions' not in equipment:
        return {muscle: sorted(tags) for muscle, tags in MUSCLES.items()
            if muscle not in REGIONAL_MUSCLE_LABELS}
    available = {muscle for definition in equipment.get('exerciseDefinitions', []) for muscle in muscle_credits_per_set(definition)}
    return {muscle: sorted(tags) for muscle, tags in MUSCLES.items() if muscle in available}


def muscle_metadata_policy(supported):
    return {
        'interpretation': ('Aggregate targets use library muscleGroups (primary, 1 credit/set) and secondaryMuscleGroups '
            '(secondary, 0.5 credit/set), with primary precedence. Separately requested anatomical subregions use only '
            'source-backed regional annotations; missing annotations are unknown and never become zero or an aggregate '
            'back/shoulder substitute. Regional credits are reported separately and are not added to aggregate totals. '
            'These are accounting conventions, not measured stimulus.'),
        'bodyMapTargetMapping': {tag: sorted(muscle for muscle, tags in MUSCLES.items()
            if tag in tags and muscle in supported and muscle not in REGIONAL_MUSCLE_LABELS)
            for tags in supported.values() for tag in tags},
        'regionalTargetLabels': {region: label for region, label in REGIONAL_MUSCLE_LABELS.items()
            if region in supported}}


def audit_policy(muscle_targets=None):
    """Expose the estimator's inputs as well as its default overheads."""
    supported = available_muscle_targets() if muscle_targets is None else muscle_targets
    return {**ASSUMPTIONS,
        'supportedMuscleTargets': supported,
        'muscleLabels': {key: value for key, value in {**MUSCLE_LABELS, 'back': 'Back (combined lats and upper back)',
            'shoulders': 'Shoulders (combined deltoids)'}.items() if key in supported},
        'capabilityLimits': 'Aggregate supportedMuscleTargets come from the library primary and secondary muscle arrays. Separately named regional targets are supported only when reviewed source-backed anatomy annotations exist for the participating exercises; an unannotated contribution remains unknown and cannot be inferred from an aggregate back, shoulder or chest credit. Regional credits are audited separately from aggregate totals. Do not invent regional credits or silently replace a regional target with its aggregate parent; explain incomplete evidence and resolve it before planning.',
        'prescribedRests': 'Explicit between-set rests, workout rest components and per-member superset rests are counted separately from setup transitions. The final superset recovery is omitted after the last round.',
        'setupTiming': 'setupSeconds is a one-time allowance before each exercise after the first; it is separate from prescribed rest and is not repeated per set or superset round. Repeated equipment changes within a superset are not estimated here. The final audit reuses these estimates by occurrence ID; they are not measurements or duration guarantees.',
        'unilateralWork': 'Both sides of each set plus the prescribed between-side rest count for time; the working set counts once for muscle volume.',
        'volumeAccounting': 'Credits follow library primary/secondary roles. A working set may credit multiple muscles; summing muscle credits does not count distinct sets.',
        'precision': 'Duration is an estimate using the defaults above, plus prescribed work and rests; it is not a second-precise prediction.'}


def validate_audit_targets(targets):
    if not isinstance(targets, dict):
        raise ContractValidationError("PlanIndex must include auditTargets with agreed numeric goals (empty volume maps and null time limit when unspecified).")
    for field in ("weeklyEffectiveSets", "perSessionEffectiveSets"):
        values = targets.get(field, {})
        if not isinstance(values, dict) or set(values) - MUSCLES.keys():
            raise ContractValidationError(f"auditTargets.{field} must map supported muscle names to minimum/maximum ranges.")
        for muscle, bounds in values.items():
            if not isinstance(bounds, dict) or 'minimum' not in bounds or 'maximum' not in bounds:
                raise ContractValidationError(f"Invalid {field} range for {muscle}.")
            lower, upper = bounds.get("minimum"), bounds.get("maximum")
            if (type(lower) not in (int, float) or not math.isfinite(lower) or not 0 <= lower <= 100
                    or upper is not None and (type(upper) not in (int, float)
                        or not math.isfinite(upper) or upper < lower or upper > 100)):
                raise ContractValidationError(f"Invalid {field} range for {muscle}: {bounds}.")
    limit = targets.get("maximumSessionSeconds")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        raise ContractValidationError("auditTargets.maximumSessionSeconds must be a positive integer or null.")


def volume_target_bounds(bounds):
    """Return numeric solver bounds for an explicit volume floor and optional cap."""
    return bounds['minimum'], math.inf if bounds['maximum'] is None else bounds['maximum']


def volume_target_text(bounds):
    """Render an explicit volume range without inventing an upper limit."""
    minimum, maximum = volume_target_bounds(bounds)
    return f"{minimum:g}–{maximum:g}" if math.isfinite(maximum) else f"≥ {minimum:g}"


def _is_work_set(item):
    return item.get("type") in VOLUME_SET_TYPES.values() and item.get("subCategory", "WorkSet") not in EXCLUDED_VOLUME_CATEGORIES


def _empty_volume():
    return {muscle: {"direct": 0, "indirect": 0, "effective": 0} for muscle in MUSCLES}


def muscle_credits_per_set(exercise):
    if exercise.get('exerciseType') is not None and exercise['exerciseType'] not in VOLUME_SET_TYPES:
        return {}
    primary = set(exercise.get("muscleGroups") or [])
    secondary = set(exercise.get("secondaryMuscleGroups") or [])
    credits = {}
    for muscle, tags in MUSCLES.items():
        if muscle in REGIONAL_MUSCLE_LABELS:
            continue
        direct = ASSUMPTIONS["primarySetCredit"] if primary & tags else 0
        indirect = ASSUMPTIONS["secondarySetCredit"] if not direct and secondary & tags else 0
        if direct or indirect:
            credits[muscle] = {"direct": direct, "indirect": indirect}
    from .recipe_contracts import regional_muscle_credit_roles
    regional_definition = {**exercise, 'id': exercise.get('libraryDefinitionId', exercise.get('id'))}
    credits.update(regional_muscle_credit_roles(regional_definition))
    return credits


def muscle_credit_coupling_evidence(candidates, requirements, *, selected_definition_ids=None):
    """Bound candidate-profile exposure in a continuous weekly-volume relaxation."""
    import numpy as np
    from scipy.optimize import linprog

    failure = {'status': 'unproven', 'scope': 'supplied_candidate_pool_continuous_volume_only_relaxation',
        'profileLowerBounds': [],
        'interpretation': 'Bounds apply only to this supplied pool under continuous weekly volume targets. '
            'They are not prescriptions and omit coverage, session structure, timing and personal suitability. '
            'An unproven result supplies no bound; other candidate pools are not tested. '
            'Active target boundaries are reported at one minimizing witness only; they do not identify an individual causal constraint or prove that changing a target improves a complete plan.'}
    targets = (requirements or {}).get('auditTargets', {}).get('weeklyEffectiveSets', {})
    if not isinstance(candidates, (list, tuple)) or not isinstance(targets, dict) or not targets:
        return failure
    muscles = list(targets)
    if any(muscle not in MUSCLES for muscle in muscles):
        return failure
    selected_ids = None
    if selected_definition_ids is not None:
        if (not isinstance(selected_definition_ids, (list, tuple, set, frozenset))
                or any(not isinstance(reference, str) for reference in selected_definition_ids)):
            return {**failure, 'menuRelief': {'status': 'unproven', 'improvements': []}}
        selected_ids = set(selected_definition_ids)
    bounds = []
    for muscle in muscles:
        target = targets[muscle]
        if not isinstance(target, dict):
            return failure
        try:
            minimum, maximum = volume_target_bounds(target)
        except (KeyError, TypeError):
            return failure
        if (type(minimum) not in (int, float) or not math.isfinite(minimum) or minimum < 0
                or maximum != math.inf and (type(maximum) not in (int, float)
                    or not math.isfinite(maximum) or maximum < minimum or maximum > 100)):
            return failure
        bounds.append((minimum, maximum))
    profiles = {}
    members = {}
    profile_by_definition = {}
    conflicting_definition_profiles = False
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get('creditsPerWorkingSet'), dict):
            return failure
        credit_map = candidate['creditsPerWorkingSet']
        vector = []
        for muscle in muscles:
            credit = credit_map.get(muscle, {})
            if not isinstance(credit, dict):
                return failure
            parts = (credit.get('direct', 0), credit.get('indirect', 0))
            if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                   for value in parts):
                return failure
            value = sum(parts)
            vector.append(float(value))
        key = tuple(vector)
        profiles.setdefault(key, len(profiles))
        members.setdefault(key, []).append({'id': candidate.get('id'), 'name': candidate.get('name')})
        if isinstance(candidate.get('id'), str):
            prior_profile = profile_by_definition.get(candidate['id'])
            if prior_profile is not None and prior_profile != key:
                conflicting_definition_profiles = True
            profile_by_definition[candidate['id']] = key
    if not profiles or len(profiles) > 128:
        return failure
    if selected_ids is not None and conflicting_definition_profiles:
        return {**failure, 'menuRelief': {'status': 'unproven', 'improvements': []}}

    selected_profiles = None
    if selected_definition_ids is not None:
        if not selected_ids or not selected_ids.issubset(profile_by_definition):
            return {**failure, 'menuRelief': {'status': 'unproven', 'improvements': []}}
        selected_profiles = {profile_by_definition[reference] for reference in selected_ids}

    profile_keys = list(profiles)
    selected_keys = [key for key in profile_keys if selected_profiles is None or key in selected_profiles]
    primary_matrix = np.array(selected_keys, dtype=float).T
    full_matrix = np.array(profile_keys, dtype=float).T

    def constraints(matrix):
        rows, limits = [], []
        for index, (minimum, maximum) in enumerate(bounds):
            if math.isfinite(maximum):
                rows.append(matrix[index])
                limits.append(maximum)
            rows.append(-matrix[index])
            limits.append(-minimum)
        return rows, limits

    primary_rows, primary_limits = constraints(primary_matrix)
    full_rows, full_limits = constraints(full_matrix)
    options = {'time_limit': 0.05}
    feasible = linprog(np.zeros(len(selected_keys)), A_ub=primary_rows, b_ub=primary_limits,
        bounds=(0, None), method='highs', options=options)
    if feasible.status == 2:
        return {**failure, 'status': 'infeasible_relaxation',
            **({'menuRelief': {'status': 'unproven', 'improvements': []}} if selected_ids is not None else {})}
    if not feasible.success:
        return {**failure,
            **({'menuRelief': {'status': 'unproven', 'improvements': []}} if selected_ids is not None else {})}

    lower_bounds = []
    selected_profile_lower_bounds = {}
    for index, key in enumerate(selected_keys):
        objective = np.zeros(len(selected_keys))
        objective[index] = 1
        result = linprog(objective, A_ub=primary_rows, b_ub=primary_limits,
            bounds=(0, None), method='highs', options=options)
        if not result.success:
            return {**failure,
                **({'menuRelief': {'status': 'unproven', 'improvements': []}} if selected_ids is not None else {})}
        selected_profile_lower_bounds[key] = float(result.fun)
        if result.fun > 1e-7:
            achieved = {muscle: sum(float(profile[target_index]) * float(sets)
                for profile, sets in zip(selected_keys, result.x, strict=True))
                for target_index, muscle in enumerate(muscles)}
            active_targets = []
            for muscle, (minimum, maximum) in zip(muscles, bounds, strict=True):
                if abs(achieved[muscle] - minimum) <= 1e-6:
                    active_targets.append({'muscle': muscle, 'boundary': 'minimum',
                        'targetSets': minimum, 'achievedSets': round(achieved[muscle], 6)})
                if math.isfinite(maximum) and abs(achieved[muscle] - maximum) <= 1e-6:
                    active_targets.append({'muscle': muscle, 'boundary': 'maximum',
                        'targetSets': maximum, 'achievedSets': round(achieved[muscle], 6)})
            profile_members = [member for member in members[key]
                if selected_ids is None or member.get('id') in selected_ids]
            lower_bounds.append({'members': profile_members,
                'creditsPerWorkingSet': {muscle: value for muscle, value in zip(muscles, key) if value},
                'minimumWeeklyWorkingSets': float(result.fun),
                'activeWeeklyVolumeTargets': active_targets})

    result = {**failure, 'status': 'proven', 'profileLowerBounds': lower_bounds}
    if selected_ids is None:
        return result

    profile_index = {key: index for index, key in enumerate(profile_keys)}
    improvements = []
    for key in selected_keys:
        selected_minimum = selected_profile_lower_bounds[key]
        if selected_minimum <= 1e-7:
            continue
        objective = np.zeros(len(profile_keys))
        objective[profile_index[key]] = 1
        union_result = linprog(objective, A_ub=full_rows, b_ub=full_limits,
            bounds=(0, None), method='highs', options=options)
        if not union_result.success:
            result['menuRelief'] = {'status': 'unproven', 'improvements': []}
            return result
        retrieved_minimum = float(union_result.fun)
        if selected_minimum - retrieved_minimum <= 1e-7:
            continue
        witness_profiles = []
        for witness_key, witness_index in profile_index.items():
            count = float(union_result.x[witness_index])
            if witness_key in selected_profiles or count <= 1e-7:
                continue
            choices = [member for member in members[witness_key]
                if isinstance(member.get('id'), str) and member['id'] not in selected_ids]
            if not choices:
                continue
            witness_profiles.append({
                'creditsPerWorkingSet': {muscle: value for muscle, value in zip(muscles, witness_key) if value},
                'relaxedWeeklyWorkingSets': count,
                'definitionChoices': choices,
            })
        if witness_profiles:
            improvements.append({
                'selectedDefinitions': [member for member in members[key] if member.get('id') in selected_ids],
                'selectedCreditsPerWorkingSet': {muscle: value for muscle, value in zip(muscles, key) if value},
                'minimumWeeklyWorkingSetsSelectedPool': selected_minimum,
                'minimumWeeklyWorkingSetsRetrievedPool': retrieved_minimum,
                'outsideMenuWitnessProfiles': witness_profiles,
            })
    result['menuRelief'] = {
        'status': 'proven',
        'scope': 'selected_menu_vs_retrieved_pool_continuous_weekly_volume_relaxation',
        'improvements': improvements,
        'interpretation': 'Each witness is a continuous credit-only alternative under the approved weekly volume bands. It ignores coverage, session placement, integer counts, duration, capacity, and recipe qualification; it is a candidate choice for review, not an admitted or executable substitution. Selected choices still require the existing recipe qualification and joint audit.',
    }
    return result


def development_menu_limits(candidates, requirements, coverage_by_reference, *,
                            source_set_cap, training_occurrences, minimum_work_sets):
    """Bound development exposure before prescriptions, using qualified roles only."""
    import numpy as np
    from scipy.optimize import linprog

    selected = set(coverage_by_reference)
    coupling = muscle_credit_coupling_evidence(candidates, requirements,
        selected_definition_ids=sorted(selected))
    result = {'status': 'unproven', 'roleUpperBounds': {}, 'volumeCreditCoupling': coupling,
        'scope': 'qualified_menu_continuous_volume_coverage_and_source_budget_relaxation',
        'minimumSessionRequirements': {rule['key']: {'minimumSessions': rule['minimumSessions'],
            'status': 'not_proven_by_continuous_menu_bound'}
            for rule in requirements.get('requiredCoverage', []) if 'minimumSessions' in rule},
        'interpretation': ('Individual upper bounds omit timing, grouping, and integer selection. '
            'They are menu limits, not target doses, joint attainability, or suitability findings. Session-count minima are not proven by this continuous relaxation.')}
    result['diagnosticRoleUpperBounds'] = {}
    result['diagnosticMinimumConflicts'] = []
    if coupling.get('status') not in ('proven', 'infeasible_relaxation'):
        return result
    by_reference = {item['id']: item for item in candidates}
    if len(by_reference) != len(candidates) or not selected.issubset(by_reference):
        return result
    entries = [by_reference[reference] for reference in sorted(selected)]
    targets = requirements.get('auditTargets', {}).get('weeklyEffectiveSets', {})
    rows, limits, row_owners = [], [], []
    explicit_rows, explicit_limits, explicit_owners = [], [], []
    all_explicit_rows, all_explicit_limits = [], []
    for muscle, target in targets.items():
        credits = [sum(item['creditsPerWorkingSet'].get(muscle, {}).values()) for item in entries]
        minimum, maximum = volume_target_bounds(target)
        if math.isfinite(maximum):
            rows.append(credits)
            limits.append(maximum)
            row_owners.append({'kind': 'weekly_muscle_maximum', 'key': muscle, 'limit': maximum})
        rows.append([-value for value in credits])
        limits.append(-minimum)
        row_owners.append({'kind': 'weekly_muscle_minimum', 'key': muscle, 'limit': minimum})
    for rule in requirements.get('requiredCoverage', []):
        count = training_occurrences if rule['scope'] == 'eachSession' else 1
        if rule.get('minimumSessions', 0) > training_occurrences:
            result['status'] = 'infeasible_relaxation'
            result['approvedMinimumConflicts'] = [{'role': rule['key'],
                'minimumSessions': rule['minimumSessions'], 'availableTrainingSessions': training_occurrences}]
            return result
        role_coefficients = [-int(rule['key'] in coverage_by_reference[item['id']]) for item in entries]
        required_floors = []
        if 'minimumWeeklySets' in rule:
            required_floors.append((rule['minimumWeeklySets'], 'approved_weekly_sets_minimum'))
        if 'minimumSessions' in rule:
            required_floors.append((minimum_work_sets * rule['minimumSessions'], 'necessary_weekly_sets_for_session_minimum'))
        for floor, kind in required_floors:
            explicit_rows.append(role_coefficients)
            explicit_limits.append(-floor)
            explicit_owners.append({'kind': kind, 'key': rule['key'], 'limit': floor,
                'minimumSessions': rule.get('minimumSessions'),
                'placementModeled': False if 'minimumSessions' in rule else None})
            all_explicit_rows.append([-int(rule['key'] in coverage_by_reference.get(item['id'], [])) for item in candidates])
            all_explicit_limits.append(-floor)
        base_floor = minimum_work_sets * count
        rows.append(role_coefficients)
        limits.append(-base_floor)
        row_owners.append({'kind': 'required_coverage_minimum', 'key': rule['key'],
            'limit': base_floor, 'scope': rule['scope']})
    if source_set_cap is not None:
        rows.append([1] * len(entries))
        limits.append(source_set_cap)
        row_owners.append({'kind': 'source_set_cap', 'limit': source_set_cap})
    all_rows, all_limits = [], []
    for muscle, target in targets.items():
        credits = [sum(item['creditsPerWorkingSet'].get(muscle, {}).values()) for item in candidates]
        minimum, maximum = volume_target_bounds(target)
        if math.isfinite(maximum):
            all_rows.append(credits)
            all_limits.append(maximum)
        all_rows.append([-value for value in credits])
        all_limits.append(-minimum)
    for rule in requirements.get('requiredCoverage', []):
        count = training_occurrences if rule['scope'] == 'eachSession' else 1
        weekly_floor = minimum_work_sets * count
        all_rows.append([-int(rule['key'] in coverage_by_reference.get(item['id'], [])) for item in candidates])
        all_limits.append(-weekly_floor)
    all_rows.extend(all_explicit_rows)
    all_limits.extend(all_explicit_limits)
    if source_set_cap is not None:
        all_rows.append([1] * len(candidates))
        all_limits.append(source_set_cap)
        all_rows_without_source_cap = all_rows[:-1]
        all_limits_without_source_cap = all_limits[:-1]
    else:
        all_rows_without_source_cap = all_rows
        all_limits_without_source_cap = all_limits
    menu_relief = {'status': 'proven',
        'scope': 'qualified_development_role_upper_bound_with_credit_only_unqualified_menu_choices',
        'improvements': [],
        'interpretation': ('Outside definitions contribute zero qualified coverage. These continuous witnesses show only that their library credit profiles may loosen a qualified role ceiling; '
            'they are unqualified and do not prove role suitability, executable selection, or personal suitability.')}
    result['developmentRoleRelief'] = menu_relief
    hard_feasibility = linprog(np.zeros(len(entries)), A_ub=rows + explicit_rows,
        b_ub=limits + explicit_limits, bounds=(0, None), method='highs', options={'time_limit': 1})
    result['hardFeasibilityStatus'] = 'feasible_relaxation' if hard_feasibility.success else (
        'infeasible_relaxation' if hard_feasibility.status == 2 else 'unproven')
    # A proven hard infeasibility is monotonic: later optional bound/relief
    # solves may time out, but cannot make this menu admissible again.
    if result['hardFeasibilityStatus'] == 'infeasible_relaxation':
        result['status'] = 'infeasible_relaxation'
        selected_entries = [item for item in entries if item['id'] in selected]
        selected_ids = {item['id'] for item in selected_entries}
        outside_profiles = {}
        for item in candidates:
            if item['id'] in selected_ids:
                continue
            profile = tuple(float(sum(item['creditsPerWorkingSet'].get(muscle, {}).values()))
                for muscle in targets)
            outside_profiles.setdefault(profile, []).append(item)
        addition_proofs = []
        unproven_profile_count = 0
        for profile, profile_definitions in sorted(outside_profiles.items()):
            variable_count = len(selected_entries) + 1
            profile_rows, profile_limits = [], []
            for muscle_index, (muscle, target) in enumerate(targets.items()):
                coefficients = [sum(item['creditsPerWorkingSet'].get(muscle, {}).values())
                    for item in selected_entries] + [profile[muscle_index]]
                minimum, maximum = volume_target_bounds(target)
                if math.isfinite(maximum):
                    profile_rows.append(coefficients)
                    profile_limits.append(maximum)
                profile_rows.append([-value for value in coefficients])
                profile_limits.append(-minimum)
            for rule in requirements.get('requiredCoverage', []):
                count = training_occurrences if rule['scope'] == 'eachSession' else 1
                coefficients = [-int(rule['key'] in coverage_by_reference.get(item['id'], []))
                    for item in selected_entries] + [0]
                profile_rows.append(coefficients)
                profile_limits.append(-minimum_work_sets * count)
                if 'minimumWeeklySets' in rule:
                    profile_rows.append(coefficients)
                    profile_limits.append(-rule['minimumWeeklySets'])
                if 'minimumSessions' in rule:
                    profile_rows.append(coefficients)
                    profile_limits.append(-minimum_work_sets * rule['minimumSessions'])
            if source_set_cap is not None:
                profile_rows.append([1] * variable_count)
                profile_limits.append(source_set_cap)
            addition = linprog(np.zeros(variable_count), A_ub=profile_rows,
                b_ub=profile_limits, bounds=(0, None), method='highs',
                options={'time_limit': 1})
            if addition.success:
                addition_proofs.append({
                    'definitionChoices': [{'id': item.get('id'), 'name': item.get('name')}
                        for item in profile_definitions],
                    'creditsPerWorkingSet': {muscle: value for muscle, value in zip(targets, profile)
                        if value},
                    'qualificationStatus': 'unqualified',
                    'qualifiedRoleContribution': 0,
                    'hardFeasibilityStatus': 'feasible_relaxation',
                    'sourceSetCapApplied': source_set_cap is not None,
                    **({'sourceSetCap': source_set_cap} if source_set_cap is not None else {}),
                })
            elif addition.status != 2:
                unproven_profile_count += 1
        menu_relief['singleAdditionFeasibility'] = {
            'status': ('feasible_relaxation' if addition_proofs else
                'unproven' if unproven_profile_count else 'no_single_addition_proven'),
            'scope': 'selected_qualified_menu_plus_one_unqualified_credit_profile_continuous_hard_relaxation',
            'sourceSetCapApplied': source_set_cap is not None,
            **({'sourceSetCap': source_set_cap} if source_set_cap is not None else {}),
            'additions': addition_proofs,
            'unprovenProfileCount': unproven_profile_count,
            'interpretation': ('Each listed outside credit profile restores the full weekly volume and qualified-role floor relaxation when added once to this selected menu. Outside candidates contribute zero qualified roles. This does not prove integer set counts, placement, timing, executable qualification, or suitability.'),
        }
    result['approvedMinimumConflicts'] = []
    for rule in requirements.get('requiredCoverage', []):
        if rule.get('intent') != 'development':
            continue
        role = rule['key']
        objective = [-int(role in coverage_by_reference[item['id']]) for item in entries]
        other_role_minima = [(row, limit, owner) for row, limit, owner in
            zip(explicit_rows, explicit_limits, explicit_owners, strict=True) if owner['key'] != role]
        role_rows = rows + [item[0] for item in other_role_minima]
        role_limits = limits + [item[1] for item in other_role_minima]
        role_owners = row_owners + [item[2] for item in other_role_minima]
        bound = linprog(np.array(objective), A_ub=role_rows, b_ub=role_limits,
            bounds=(0, None), method='highs', options={'time_limit': 1})
        budget_diagnostic = False
        if not bound.success:
            if bound.status == 2 and source_set_cap is not None:
                # When the frozen source cap masks a role bound, compute a
                # diagnostic ceiling with the same volume, coverage and other-
                # role constraints. This is not admissible under the cap.
                role_rows_without_budget = [row for row, owner in
                    zip(role_rows, role_owners, strict=True) if owner['kind'] != 'source_set_cap']
                role_limits_without_budget = [limit for owner, limit in
                    zip(role_owners, role_limits, strict=True) if owner['kind'] != 'source_set_cap']
                role_owners_without_budget = [owner for owner in role_owners
                    if owner['kind'] != 'source_set_cap']
                bound = linprog(np.array(objective), A_ub=role_rows_without_budget,
                    b_ub=role_limits_without_budget, bounds=(0, None), method='highs',
                    options={'time_limit': 1})
                if not bound.success:
                    # Another role's conflict still must not hide this role's
                    # ceiling when the diagnostic relaxation cannot resolve it.
                    continue
                role_rows, role_limits, role_owners = (role_rows_without_budget,
                    role_limits_without_budget, role_owners_without_budget)
                budget_diagnostic = True
            else:
                return result
        selected_upper = max(0, round(float(-bound.fun), 6))
        if budget_diagnostic:
            result['diagnosticRoleUpperBounds'][role] = {
                'weeklySets': selected_upper,
                'sourceSetCap': source_set_cap,
                'sourceSetCapExcluded': True,
                'diagnosticOnly': True,
            }
        else:
            result['roleUpperBounds'][role] = selected_upper
        binding_constraints = []
        if bound.x is not None:
            for row, limit, owner in zip(role_rows, role_limits, role_owners, strict=True):
                if owner['kind'] == 'source_set_cap':
                    continue
                if abs(limit - float(np.dot(row, bound.x))) > 1e-6:
                    continue
                if owner['kind'] in ('weekly_muscle_maximum', 'weekly_muscle_minimum'):
                    achieved = sum(float(item['creditsPerWorkingSet'].get(owner['key'], {}).get('direct', 0)
                                         + item['creditsPerWorkingSet'].get(owner['key'], {}).get('indirect', 0))
                        * float(sets) for item, sets in zip(entries, bound.x, strict=True))
                    binding_constraints.append({**owner, 'achieved': round(achieved, 6)})
                elif owner['kind'] == 'required_coverage_minimum':
                    achieved = sum(float(owner['key'] in coverage_by_reference[item['id']]) * float(sets)
                        for item, sets in zip(entries, bound.x, strict=True))
                    binding_constraints.append({**owner, 'achieved': round(achieved, 6)})
                elif owner['kind'] in ('approved_weekly_sets_minimum',
                                       'necessary_weekly_sets_for_session_minimum'):
                    achieved = sum(float(owner['key'] in coverage_by_reference[item['id']]) * float(sets)
                        for item, sets in zip(entries, bound.x, strict=True))
                    binding_constraints.append({**owner, 'achieved': round(achieved, 6)})
        total_sets = float(sum(bound.x))
        if budget_diagnostic:
            binding_constraints.append({'kind': 'source_set_cap', 'limit': source_set_cap,
                'excluded': True, 'diagnosticOnly': True})
        elif source_set_cap is not None:
            binding_constraints.append({'kind': 'source_set_cap', 'limit': source_set_cap,
                'achieved': round(total_sets, 6),
                'slack': round(max(0, source_set_cap - total_sets), 6),
                'binding': total_sets >= source_set_cap - 1e-6})
        target_constraints_key = ('diagnosticRoleUpperBoundConstraints' if budget_diagnostic
                                  else 'roleUpperBoundConstraints')
        result.setdefault(target_constraints_key, {})[role] = binding_constraints
        if 'minimumWeeklySets' in rule and rule['minimumWeeklySets'] > selected_upper + 1e-7:
            conflict = {'role': role, 'kind': 'minimumWeeklySets', 'required': rule['minimumWeeklySets'],
                'qualifiedMenuUpperBound': selected_upper}
            if budget_diagnostic:
                result['diagnosticMinimumConflicts'].append({**conflict,
                    'sourceSetCap': source_set_cap, 'sourceSetCapExcluded': True, 'diagnosticOnly': True})
            else:
                result['approvedMinimumConflicts'].append(conflict)
            # The no-cap diagnostic relaxes the feasible region further. If
            # even that upper bound misses the approved floor, infeasibility
            # holds for the capped menu as well.
            result['status'] = 'infeasible_relaxation'
        session_floor = minimum_work_sets * rule.get('minimumSessions', 0)
        if session_floor > selected_upper + 1e-7:
            conflict = {'role': role,
                'kind': 'minimumSessions', 'requiredSessions': rule['minimumSessions'],
                'necessaryWeeklySetFloor': session_floor, 'qualifiedMenuUpperBound': selected_upper}
            if budget_diagnostic:
                result['diagnosticMinimumConflicts'].append({**conflict,
                    'sourceSetCap': source_set_cap, 'sourceSetCapExcluded': True, 'diagnosticOnly': True})
            else:
                result['approvedMinimumConflicts'].append(conflict)
            # As above, a floor missed under the expanded diagnostic region
            # proves it cannot be met under the real source cap.
            result['status'] = 'infeasible_relaxation'
        outside_bound = linprog(np.array([-int(role in coverage_by_reference.get(item['id'], []))
            for item in candidates]),
            A_ub=(all_rows_without_source_cap if budget_diagnostic else all_rows),
            b_ub=(all_limits_without_source_cap if budget_diagnostic else all_limits),
            bounds=(0, None), method='highs', options={'time_limit': 1})
        if not outside_bound.success:
            menu_relief['status'] = 'partial' if menu_relief['improvements'] else 'unproven'
            continue
        relaxed_upper = max(0, round(float(-outside_bound.fun), 6))
        if relaxed_upper <= selected_upper + 1e-7:
            continue
        active_profiles = {}
        for index, item in enumerate(candidates):
            if item['id'] in selected or outside_bound.x[index] <= 1e-7:
                continue
            profile = tuple(sum(item['creditsPerWorkingSet'].get(muscle, {}).values()) for muscle in targets)
            active_profiles.setdefault(profile, index)
        witnesses = []
        selected_indices = [index for index, item in enumerate(candidates) if item['id'] in selected]
        for profile, representative_index in sorted(active_profiles.items()):
            profile_indices = selected_indices + [representative_index]
            profile_bound = linprog(np.array([-int(role in coverage_by_reference.get(candidates[index]['id'], []))
                for index in profile_indices]),
                A_ub=[[row[index] for index in profile_indices] for row in
                    (all_rows_without_source_cap if budget_diagnostic else all_rows)],
                b_ub=(all_limits_without_source_cap if budget_diagnostic else all_limits),
                bounds=(0, None), method='highs', options={'time_limit': 1})
            if not profile_bound.success or -profile_bound.fun <= selected_upper + 1e-7:
                continue
            definitions = []
            for item in candidates:
                if item['id'] in selected:
                    continue
                candidate_profile = tuple(sum(item['creditsPerWorkingSet'].get(muscle, {}).values())
                    for muscle in targets)
                if candidate_profile == profile:
                    definitions.append({'id': item['id'], 'name': item.get('name')})
            witnesses.append({
                'creditsPerWorkingSet': {muscle: credit for muscle, credit in zip(targets, profile) if credit},
                'profileRelaxedUpperBound': max(0, round(float(-profile_bound.fun), 6)),
                'relaxedWeeklyWorkingSets': round(float(profile_bound.x[-1]), 6),
                'definitionChoices': [{'id': item['id'], 'name': item.get('name')}
                    for item in definitions],
                'qualificationStatus': 'unqualified',
                'qualifiedRoleContribution': 0,
                **({'sourceSetCap': source_set_cap, 'sourceSetCapExcluded': True,
                    'diagnosticOnly': True} if budget_diagnostic else {}),
            })
        if witnesses:
            menu_relief['improvements'].append({'role': role,
                'selectedMenuUpperBound': selected_upper,
                'creditOnlyRelaxedUpperBound': relaxed_upper,
                **({'sourceSetCap': source_set_cap, 'sourceSetCapExcluded': True,
                    'diagnosticOnly': True} if budget_diagnostic else {}),
                'outsideMenuWitnessProfiles': witnesses})
    result['developmentRoleRelief'] = menu_relief
    result['status'] = ('infeasible_relaxation'
        if (result.get('status') == 'infeasible_relaxation'
            or result['hardFeasibilityStatus'] == 'infeasible_relaxation'
            or result['approvedMinimumConflicts'] or result['diagnosticMinimumConflicts'])
        else 'proven_upper_bounds')
    return result


def add_audit_issue(report, code, message, repair, path="/workouts", **details):
    report["issues"].append(message)
    report["errors"].append({"code": code, "path": path, "message": message, "repair": repair, **details})


def validate_family_set_bounds(requirements, family_by_reference):
    """Validate user-approved weekly family bounds against sourced family IDs."""
    bounds = requirements.get('familySetBounds', [])
    errors = []
    if not isinstance(bounds, list):
        return [{'code': 'invalid_family_set_bounds', 'path': '/familySetBounds',
            'message': 'Family set bounds must be a list.',
            'repair': 'Correct the approved family set bounds before planning.'}]
    available = set((family_by_reference or {}).values())
    seen = set()
    for index, item in enumerate(bounds):
        path = f'/familySetBounds/{index}'
        if not isinstance(item, dict):
            errors.append({'code': 'invalid_family_set_bounds', 'path': path,
                'message': 'Each family set bound must be an object.',
                'repair': 'Select a reviewed exercise family and provide an approved weekly bound.'})
            continue
        unknown_fields = set(item) - {'exerciseFamilyId', 'minimumWeeklySets', 'maximumWeeklySets'}
        if unknown_fields:
            errors.append({'code': 'invalid_family_set_bounds', 'path': path,
                'message': 'Family set bounds contain unsupported fields.',
                'repair': 'Keep only exerciseFamilyId, minimumWeeklySets, and maximumWeeklySets.',
                'unsupportedFields': sorted(unknown_fields)})
        family = item.get('exerciseFamilyId')
        minimum, maximum = item.get('minimumWeeklySets'), item.get('maximumWeeklySets')
        if not isinstance(family, str) or not family:
            errors.append({'code': 'invalid_family_set_bounds', 'path': path + '/exerciseFamilyId',
                'message': 'A family set bound requires a reviewed exerciseFamilyId.',
                'repair': 'Select a family from the reviewed family choices.'})
            continue
        if family in seen:
            errors.append({'code': 'duplicate_family_set_bound', 'path': path + '/exerciseFamilyId',
                'message': f'Family {family} has more than one weekly bound.',
                'repair': 'Combine the approved minimum and maximum into one family bound.',
                'exerciseFamilyId': family})
        seen.add(family)
        if family not in available:
            errors.append({'code': 'unrepresentable_family_set_bound', 'path': path + '/exerciseFamilyId',
                'message': f'Family {family} has no currently reviewed exercise definitions.',
                'repair': 'Choose a family from current reviewed library evidence or resolve the evidence gap.',
                'exerciseFamilyId': family})
        for field, value in (('minimumWeeklySets', minimum), ('maximumWeeklySets', maximum)):
            if value is not None and (type(value) is not int or value < 0):
                errors.append({'code': 'invalid_family_set_bounds', 'path': path + '/' + field,
                    'message': f'{field} must be a nonnegative integer.',
                    'repair': 'Provide an explicitly approved nonnegative integer bound.'})
        if minimum is None and maximum is None:
            errors.append({'code': 'invalid_family_set_bounds', 'path': path,
                'message': 'A family set bound must include a minimum or maximum.',
                'repair': 'Provide an explicitly approved minimum or maximum; equal values express a target.'})
        elif (type(minimum) is int and minimum >= 0 and type(maximum) is int and maximum >= 0
                and maximum < minimum):
            errors.append({'code': 'invalid_family_set_bounds', 'path': path,
                'message': 'The maximum weekly family dose cannot be below its minimum.',
                'repair': 'Provide compatible approved bounds.'})
    return errors


def family_set_audit_options(requirements, equipment):
    """Build the shared audit kwargs for approved family bounds, if any."""
    options = {}
    if requirements.get('familySetBounds'):
        from .recipe_contracts import (library_definitions_by_reference,
            reviewed_exercise_family_evidence)
        evidence = reviewed_exercise_family_evidence(equipment or {})
        definitions = library_definitions_by_reference(equipment or {})
        family_by_reference = evidence.get('familyByReference', {})
        for reference, family in tuple(family_by_reference.items()):
            family_by_reference[definitions[reference]['id']] = family
        options.update(family_set_requirements=requirements, family_by_reference=family_by_reference)
    if any(rule.get('kind') == 'exerciseExposure' for rule in requirements.get('executionRules', [])):
        from .recipe_contracts import library_definitions_by_reference
        definitions = library_definitions_by_reference(equipment or {})
        by_reference = {reference: definition['id'] for reference, definition in definitions.items()}
        by_reference.update({definition['id']: definition['id'] for definition in definitions.values()})
        options.update(exercise_exposure_requirements=requirements,
            exercise_definition_by_reference=by_reference)
    return options


def weekly_family_set_counts(workouts, family_by_reference):
    """Count reviewed family exposure from exercise prescriptions and weekly frequency."""
    counts = {}
    for workout in workouts:
        frequency = workout.get('timesCompletedInAWeek', 1)
        for exercise in workout.get('exercises', []):
            reference = exercise.get('definition_id', exercise.get('libraryDefinitionId', exercise.get('id')))
            family = (family_by_reference or {}).get(reference)
            if family is not None:
                sets = exercise.get('numWorkSets')
                if sets is None:
                    sets = sum(_is_work_set(item) for item in exercise.get('sets', []))
                counts[family] = counts.get(family, 0) + sets * frequency
    return counts


def audit_family_set_bounds(report, package, requirements, family_by_reference):
    """Apply approved weekly family bounds to the audited executable package."""
    bounds = requirements.get('familySetBounds', [])
    if not bounds:
        return
    errors = validate_family_set_bounds(requirements, family_by_reference)
    if errors:
        report['errors'].extend(errors)
        report['issues'].extend(error['message'] for error in errors)
        return
    workouts = []
    unknown = set()
    for workout in package.get('workouts', []):
        if workout.get('enabled') is False:
            continue
        exercises = []
        for component in workout.get('workoutComponents', []):
            if component.get('enabled') is False:
                continue
            members = (component.get('exercises', []) if component.get('type') == 'Superset'
                else [component] if component.get('type') == 'Exercise' else [])
            for exercise in members:
                if exercise.get('enabled') is False:
                    continue
                reference = exercise.get('libraryDefinitionId', exercise.get('exerciseDefinitionId',
                    exercise.get('definition_id', exercise.get('id'))))
                if reference not in family_by_reference:
                    unknown.add(reference)
                exercises.append(exercise)
        workouts.append({'timesCompletedInAWeek': workout.get('timesCompletedInAWeek', 1),
            'exercises': exercises})
    if unknown:
        add_audit_issue(report, 'family_bound_evidence_unknown',
            'Approved weekly family bounds cannot be verified because selected exercises lack reviewed family evidence.',
            'Use selected exercises with reviewed family assignments or resolve the library evidence gap before continuing.',
            path='/workouts', exerciseReferences=sorted(unknown))
        return
    counts = weekly_family_set_counts(workouts, family_by_reference)
    for bound in bounds:
        counts.setdefault(bound['exerciseFamilyId'], 0)
    report['weeklyFamilyWorkingSets'] = counts
    for index, bound in enumerate(bounds):
        family = bound['exerciseFamilyId']
        actual = counts.get(family, 0)
        minimum, maximum = bound.get('minimumWeeklySets'), bound.get('maximumWeeklySets')
        if minimum is not None and actual < minimum:
            add_audit_issue(report, 'family_weekly_sets_below_minimum',
                f'Exercise family {family} has {actual} weekly working sets, below its approved minimum of {minimum}.',
                'Adjust the selected family exposure to the approved minimum and re-audit.',
                path=f'/familySetBounds/{index}', exerciseFamilyId=family, actual=actual, minimum=minimum)
        if maximum is not None and actual > maximum:
            add_audit_issue(report, 'family_weekly_sets_above_maximum',
                f'Exercise family {family} has {actual} weekly working sets, above its approved maximum of {maximum}.',
                'Reduce the selected family exposure to the approved maximum and re-audit.',
                path=f'/familySetBounds/{index}', exerciseFamilyId=family, actual=actual, maximum=maximum)


def audit_exercise_exposure(report, package, requirements, definition_by_reference):
    """Audit global per-definition caps against active exported exercise components."""
    from .programming_guidelines import exercise_exposure_cap_errors, exercise_exposure_counts
    rules = [rule for rule in requirements.get('executionRules', [])
             if rule.get('kind') == 'exerciseExposure']
    if not rules:
        return
    rule = rules[0]
    workouts = []
    for workout in package.get('workouts', []):
        if workout.get('enabled') is False:
            continue
        exercises = []
        for component in workout.get('workoutComponents', []):
            if component.get('enabled') is False:
                continue
            members = (component.get('exercises', []) if component.get('type') == 'Superset'
                else [component] if component.get('type') == 'Exercise' else [])
            for exercise in members:
                if exercise.get('enabled') is False:
                    continue
                reference = exercise.get('libraryDefinitionId', exercise.get('exerciseDefinitionId',
                    exercise.get('definition_id', exercise.get('id'))))
                exercises.append({**exercise, 'definition_id': reference})
        workouts.append({'timesCompletedInAWeek': workout.get('timesCompletedInAWeek', 1),
            'exercises': exercises})
    counts, unknown = exercise_exposure_counts({'workouts': workouts},
        definition_id_by_reference=definition_by_reference or {}, require_mapped_identity=True)
    report['weeklyExerciseExposure'] = counts
    if unknown:
        add_audit_issue(report, 'exercise_exposure_identity_unknown',
            'An approved per-exercise cap cannot be verified because active exported exercises lack a mapped library definition ID.',
            'Restore a current libraryDefinitionId for every active exercise and re-audit.',
            path='/workouts', exerciseReferences=sorted(set(str(value) for value in unknown)))
        return
    for error in exercise_exposure_cap_errors(counts, rule):
        add_audit_issue(report, error['code'],
            f"Exercise definition {error['exerciseDefinitionId']} has {error['actual']:g} weekly {error['label']}; approved maximum is {error['maximum']}.",
            'Change the exercise selection or its exposure to meet the approved cap, preserving all other requirements; re-audit.',
            path='/executionRules', exerciseDefinitionId=error['exerciseDefinitionId'],
            actual=error['actual'], maximum=error['maximum'])


def _native_calibration_work_seconds(exercise, sets, rep_seconds, sides, first_work_reps=None):
    supports_calibration = (exercise.get('exerciseType') == 'WEIGHT' or
        (exercise.get('exerciseType') == 'BODY_WEIGHT' and exercise.get('equipmentId') is not None))
    if (exercise.get('requiresLoadCalibration') is not True or not supports_calibration or
            any(item.get('subCategory') == 'CalibrationSet' for item in sets)):
        return 0
    first_work_set = next((item for item in sets
        if item.get('type') in ('WeightSet', 'BodyWeightSet') and
        item.get('subCategory', 'WorkSet') in ('WorkSet', 'CalibrationPendingSet')), None)
    if first_work_set is None:
        return 0
    reps = first_work_set.get('reps', 0) if first_work_reps is None else first_work_reps
    return reps * rep_seconds * sides


def audit_workout_package(package, targets, *, setup_seconds_by_exercise=None, coverage_by_exercise=None,
                          rep_duration_seconds_by_exercise=None, timing_reps_by_exercise=None,
                          family_set_requirements=None, family_by_reference=None,
                          exercise_exposure_requirements=None, exercise_definition_by_reference=None):
    validate_audit_targets(targets)
    if (coverage_by_exercise is not None or rep_duration_seconds_by_exercise is not None
            or timing_reps_by_exercise is not None):
        identifiers = {exercise['id'] for workout in package.get('workouts', []) for component in workout.get('workoutComponents', [])
                       for exercise in (component.get('exercises', []) if component.get('type') == 'Superset' else [component])
                       if exercise.get('type') == 'Exercise'}
    if coverage_by_exercise is not None:
        if not isinstance(coverage_by_exercise, dict) or any(
                not isinstance(keys, list) or any(not isinstance(key, str) or not key for key in keys)
                for keys in coverage_by_exercise.values()):
            raise ValueError('Coverage metadata must map exercise IDs to lists of coverage keys.')
        if set(coverage_by_exercise) - identifiers:
            raise ValueError('Coverage metadata references unknown exercise IDs.')
    if rep_duration_seconds_by_exercise is not None:
        if not isinstance(rep_duration_seconds_by_exercise, dict) or any(
                type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0
                for seconds in rep_duration_seconds_by_exercise.values()):
            raise ValueError('Per-rep duration metadata must map exercise IDs to positive finite seconds.')
        if set(rep_duration_seconds_by_exercise) - identifiers:
            raise ValueError('Per-rep duration metadata references unknown exercise IDs.')
    if timing_reps_by_exercise is not None:
        if not isinstance(timing_reps_by_exercise, dict):
            raise ValueError('Timing reps metadata must map exercise IDs to work-set rep lists.')
        rep_set_counts = {}
        for workout in package.get('workouts', []):
            for component in workout.get('workoutComponents', []):
                exercises = (component.get('exercises', []) if component.get('type') == 'Superset'
                             else [component] if component.get('type') == 'Exercise' else [])
                for exercise in exercises:
                    count = sum(_is_work_set(item) for item in exercise.get('sets', []))
                    if count and any(item.get('type') in VOLUME_SET_TYPES.values()
                                     for item in exercise.get('sets', []) if _is_work_set(item)):
                        rep_set_counts[exercise['id']] = count
        if set(timing_reps_by_exercise) != set(rep_set_counts):
            raise ValueError('Timing reps metadata must cover exactly the rep-based exercise IDs in the audited package.')
        for identifier, reps in timing_reps_by_exercise.items():
            if (not isinstance(reps, list) or len(reps) != rep_set_counts[identifier]
                    or any(type(value) is not int or value < 1 for value in reps)):
                raise ValueError(f'Timing reps for {identifier} must contain one positive integer per emitted work set.')
    weekly = _empty_volume()
    report = {"assumptions": ASSUMPTIONS, "targets": copy.deepcopy(targets), "workouts": [], "weeklyVolume": weekly,
              "weeklyWorkingSets": 0, "issues": [], "errors": []}
    report['calibrationTiming'] = CALIBRATION_TIMING
    regional_targets = ({muscle for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
        for muscle in targets.get(field, {})} & REGIONAL_MUSCLE_LABELS.keys())
    regional_unknowns = {region: [] for region in regional_targets}
    coverage_keys = sorted({key for keys in (coverage_by_exercise or {}).values() for key in keys})
    if coverage_by_exercise is not None:
        report['coverageByExercise'] = copy.deepcopy(coverage_by_exercise)
        report['weeklyCoverageSets'] = dict.fromkeys(coverage_keys, 0)
        report['coverageAccounting'] = ('Working sets counted by source-backed coverage assignments; independent execution review verifies mapping completeness and movement suitability. '
            'One physical set may satisfy multiple roles. Coverage rows overlap and must not be summed as distinct sets.')
    if rep_duration_seconds_by_exercise is not None:
        report['repDurationSecondsByExercise'] = copy.deepcopy(rep_duration_seconds_by_exercise)
    timing_rep_basis = package.get('timingRepBasis')
    if timing_reps_by_exercise is not None or timing_rep_basis:
        report['timingRepBasis'] = CONSERVATIVE_REP_TIMING_BASIS
    for workout_index, workout in enumerate(package.get("workouts", [])):
        if workout.get("enabled") is False:
            continue
        volume = _empty_volume()
        timing = {"workSeconds": 0, "restSeconds": 0, "generalWarmupSeconds": ASSUMPTIONS["generalWarmupSeconds"], "rampUpSeconds": 0, "transitionSeconds": 0, "calibrationSeconds": 0}
        contributions = []
        logical_sets = 0
        coverage = dict.fromkeys(coverage_keys, 0)
        exercises_seen = 0
        setup_estimates = []

        def add_exercise(exercise, selected_sets=None, standalone=True):
            nonlocal logical_sets, exercises_seen
            sets = exercise.get("sets", []) if selected_sets is None else selected_sets
            rep_seconds = (rep_duration_seconds_by_exercise or {}).get(exercise['id'], exercise.get('repDurationSeconds', ASSUMPTIONS['secondsPerRep']))
            if type(rep_seconds) not in (int, float) or not math.isfinite(rep_seconds) or rep_seconds <= 0:
                raise ValueError('Per-rep duration must be positive finite seconds.')
            work_sets = [item for item in sets if _is_work_set(item)]
            count = len(work_sets)
            timing_reps = (timing_reps_by_exercise or {}).get(exercise['id'])
            if timing_reps is not None and len(timing_reps) < count:
                raise ValueError(f'Timing reps for {exercise["id"]} do not cover the selected workout sets.')
            logical_sets += count
            for key in set((coverage_by_exercise or {}).get(exercise['id'], [])):
                coverage[key] += count
            exercises_seen += 1
            if exercises_seen > 1:
                seconds = (setup_seconds_by_exercise or {}).get(exercise['id'], exercise.get('setupSeconds'))
                if seconds is not None and (type(seconds) is not int or not 0 <= seconds <= 1800):
                    add_audit_issue(report, 'invalid_setup_time', 'Setup time must be an integer from 0 to 1800 seconds.',
                        'Correct the declared setup estimate and re-audit; negative or invalid values cannot reduce session duration.',
                        path=f'/workouts/{workout_index}/exercises/{exercises_seen - 1}/setupSeconds', exerciseId=exercise['id'])
                    seconds = None
                setup_estimates.append({'exerciseId': exercise['id'],
                    'seconds': ASSUMPTIONS['transitionSeconds'] if seconds is None else seconds,
                    'scope': 'one_time_before_exercise',
                    'basis': 'default_allowance' if seconds is None else 'declared_estimate'})
            credits = {}
            per_set_credits = muscle_credits_per_set(exercise)
            if regional_targets:
                from .recipe_contracts import regional_muscle_facts
                regional_definition = {**exercise,
                    'id': exercise.get('libraryDefinitionId', exercise.get('id'))}
                regional_facts = regional_muscle_facts(regional_definition)
                for region in regional_targets:
                    parent_credit = per_set_credits.get(REGIONAL_MUSCLE_PARENT[region], {})
                    if (parent_credit.get('direct', 0) or parent_credit.get('indirect', 0)) and regional_facts[region]['status'] == 'unknown':
                        regional_unknowns[region].append({'exerciseId': exercise['id'],
                            'exercise': exercise['name'], 'workingSets': count})
            for muscle, per_set in per_set_credits.items():
                direct, indirect = count * per_set["direct"], count * per_set["indirect"]
                volume[muscle]["direct"] += direct
                volume[muscle]["indirect"] += indirect
                volume[muscle]["effective"] += direct + indirect
                if direct or indirect:
                    credits[muscle] = {"direct": direct, "indirect": indirect}
            contributions.append({"exerciseId": exercise["id"], "exercise": exercise["name"], "workingSets": count, "credits": credits})
            sides = 2 if exercise.get("intraSetRestInSeconds") is not None else 1
            calibration_work_seconds = _native_calibration_work_seconds(exercise, sets, rep_seconds, sides,
                timing_reps[0] if timing_reps else None)
            timing['calibrationSeconds'] += calibration_work_seconds
            if calibration_work_seconds and sides == 2:
                timing['restSeconds'] += exercise['intraSetRestInSeconds']
            work_set_index = 0
            for item in sets:
                kind = item.get("type")
                if sides == 2 and kind in ("WeightSet", "BodyWeightSet", "EnduranceSet", "TimedDurationSet"):
                    timing["restSeconds"] += exercise["intraSetRestInSeconds"]
                if kind == "RestSet":
                    if standalone:
                        timing["restSeconds"] += item["timeInSeconds"]
                elif kind in ("WeightSet", "BodyWeightSet"):
                    field = "calibrationSeconds" if item.get("subCategory") == "CalibrationSet" else "workSeconds"
                    reps = item['reps']
                    if _is_work_set(item) and timing_reps is not None:
                        reps = timing_reps[work_set_index]
                    timing[field] += reps * rep_seconds * sides
                elif kind in ("EnduranceSet", "TimedDurationSet"):
                    duration = item.get("timeInMillis", 0) / 1000
                    field = "calibrationSeconds" if item.get("subCategory") == "CalibrationSet" else "workSeconds"
                    timing[field] += duration * sides
                    if duration <= 0 and targets.get("maximumSessionSeconds"):
                        add_audit_issue(report, "unknown_duration", f"{workout['name']}: {exercise['name']} has no fixed duration; session duration cannot be validated.",
                                        "Supply a fixed duration if compatible with the requested exercise; otherwise ask the user how to resolve the time constraint.",
                                        path=f"/workouts/{workout_index}", exerciseId=exercise["id"])
                elif kind == "RunningSet" and targets.get("maximumSessionSeconds"):
                    add_audit_issue(report, "unknown_running_duration", f"{workout['name']}: running duration cannot be inferred from distance alone.",
                                    "Distance alone cannot satisfy a hard duration check. Ask the user for an appropriate fixed-duration prescription or an agreed constraint change.",
                                    path=f"/workouts/{workout_index}", exerciseId=exercise["id"])
                if _is_work_set(item):
                    work_set_index += 1
            if exercise.get("generateWarmUpSets") and not any(s.get("subCategory") == "WarmupSet" for s in sets):
                timing["rampUpSeconds"] += ASSUMPTIONS["generatedRampUpSecondsPerExercise"]
        for component in workout.get("workoutComponents", []):
            if component.get("enabled") is False:
                continue
            kind = component.get("type")
            if kind == "Exercise":
                add_exercise(component)
            elif kind == "Rest":
                timing["restSeconds"] += component["timeInSeconds"]
            elif kind == "Superset":
                members = [e for e in component.get("exercises", []) if e.get("enabled") is not False]
                member_sets = [[s for s in e.get("sets", []) if s.get("type") != "RestSet"] for e in members]
                counts = [sum(s.get("subCategory") not in EXCLUDED_VOLUME_CATEGORIES for s in sets) for sets in member_sets]
                if not counts:
                    continue
                if len(set(counts)) != 1:
                    add_audit_issue(report, "superset_set_count_mismatch", f"{workout['name']}: superset work-set counts {counts} differ; the app runs only the shortest member.",
                                    "Give all members equal working-set counts, or separate them into straight sets or different groups. Recheck all volume and duration targets.",
                                    path=f"/workouts/{workout_index}", exerciseIds=[e["id"] for e in members], actual=counts)
                rounds = min(counts)
                if rounds == 0:
                    add_audit_issue(report, "empty_superset", f"{workout['name']}: superset has no executable work rounds.",
                                    "Provide executable working sets for every superset member or remove the empty group.", path=f"/workouts/{workout_index}")
                    continue
                before_work, before_rest = timing["workSeconds"], timing["restSeconds"]
                before = before_work + before_rest
                for exercise, sets in zip(members, member_sets):
                    warmups = [s for s in sets if s.get("subCategory") in EXCLUDED_VOLUME_CATEGORIES]
                    work = [s for s in sets if s.get("subCategory") not in EXCLUDED_VOLUME_CATEGORIES][:rounds]
                    add_exercise(exercise, warmups + work, standalone=False)
                rests = component.get("restSecondsByExercise", {})
                timing["restSeconds"] += rounds * sum(rests.get(e["id"], 0) for e in members) - rests.get(members[-1]["id"], 0)
                if component.get("timeCapSeconds") or component.get("amrap"):
                    if targets.get("weeklyEffectiveSets") or targets.get("perSessionEffectiveSets"):
                        add_audit_issue(report, "unbounded_volume", f"{workout['name']}: time-capped/AMRAP volume is not an exact prescribed set count.",
                                        "Exact set-volume targets require finite prescribed rounds. If AMRAP is required, ask the user to resolve that conflict.", path=f"/workouts/{workout_index}")
                    if component.get("timeCapSeconds"):
                        timing["workSeconds"] = before_work + component["timeCapSeconds"]
                        timing["restSeconds"] = before_rest
                if component.get("roundDurationSeconds"):
                    elapsed = timing["workSeconds"] + timing["restSeconds"] - before
                    timing["restSeconds"] += max(0, rounds * component["roundDurationSeconds"] - elapsed)
        timing["transitionSeconds"] = sum(item['seconds'] for item in setup_estimates)
        seconds = sum(timing.values())
        result = {"name": workout["name"], "workingSets": logical_sets, "volume": volume, "contributions": contributions, "timing": timing, "estimatedSeconds": seconds}
        result['setupEstimates'] = setup_estimates
        report["workouts"].append(result)
        # shortcut: each enabled workout runs once weekly unless frequency is supplied; audit phases separately for periodized packages.
        frequency = workout.get("timesCompletedInAWeek") or 1
        result['timesCompletedInAWeek'] = frequency
        report['weeklyWorkingSets'] += logical_sets * frequency
        if coverage_by_exercise is not None:
            result['coverageSets'] = coverage
            for key, count in coverage.items():
                report['weeklyCoverageSets'][key] += count * frequency
        for muscle in MUSCLES:
            for field in weekly[muscle]:
                weekly[muscle][field] += volume[muscle][field] * frequency
        limit = targets.get("maximumSessionSeconds")
        if limit and seconds > limit:
            add_audit_issue(report, "duration_exceeded", f"{workout['name']}: estimated duration {seconds:.0f}s exceeds {limit}s by {seconds-limit:.0f}s; breakdown={timing}.",
                            "Use the timing breakdown to reduce work, rests or setup costs within the user's agreed constraints. Preserve all volume targets and re-audit. If no feasible draft is found, ask the user for a tradeoff instead of relaxing requirements.",
                            path=f"/workouts/{workout_index}", actual=seconds, maximum=limit, excessSeconds=seconds-limit)
    if regional_targets:
        report['regionalTargetEvidence'] = {}
        for region in sorted(regional_targets):
            unknown = regional_unknowns[region]
            report['regionalTargetEvidence'][region] = {
                'status': 'unknown_selected_aggregate_contributions' if unknown else 'source_backed_selected_contributions',
                'unknownOccurrences': unknown,
                'interpretation': ('Some selected aggregate-region exercises lack separate sourced attribution for this target; '
                    'no regional zero or compliance claim is inferred.' if unknown else
                    'Selected exercise contributions to this target have source-backed regional attribution.')}
            if unknown:
                add_audit_issue(report, 'regional_target_evidence_unknown',
                    f"{REGIONAL_MUSCLE_LABELS[region]} target cannot be fully audited because selected aggregate-region contributions lack sourced regional attribution.",
                    'Use only source-backed regional credits for this target or ask the user to resolve the evidence gap; do not treat aggregate credits as regional sets.',
                    path='/auditTargets', muscle=region, unknownOccurrences=unknown)
    for workout_index, workout in enumerate(report['workouts']):
        _check_volume(workout['volume'], targets.get('perSessionEffectiveSets', {}),
            workout['name'], report, workout_index)
    _check_volume(weekly, targets.get('weeklyEffectiveSets', {}), 'Weekly', report)
    if family_set_requirements and family_set_requirements.get('familySetBounds'):
        audit_family_set_bounds(report, package, family_set_requirements, family_by_reference or {})
    if exercise_exposure_requirements:
        audit_exercise_exposure(report, package, exercise_exposure_requirements,
            exercise_definition_by_reference or {})
    report['muscleCreditReliance'] = muscle_credit_reliance_sensitivity(package, report)
    return report


def audit_coverage_minimums(report, coverage_rules):
    """Check explicitly approved role-dose and frequency minima from audited role assignments."""
    evidence = report.setdefault('coverageMinimumEvidence', {})
    for rule in coverage_rules or ():
        key = rule['key']
        weekly_sets = report.get('weeklyCoverageSets', {}).get(key, 0)
        actual_sessions = sum((1 if day.get('coverageSets', {}).get(key, 0) > 0 else 0)
            * day.get('timesCompletedInAWeek', 1) for day in report.get('workouts', []))
        item = {'weeklyWorkingSets': weekly_sets, 'weeklyTrainingSessions': actual_sessions}
        if 'minimumWeeklySets' in rule:
            item['minimumWeeklySets'] = rule['minimumWeeklySets']
            item['weeklySetsStatus'] = 'met' if weekly_sets >= rule['minimumWeeklySets'] else 'below_minimum'
        if 'minimumSessions' in rule:
            item['minimumSessions'] = rule['minimumSessions']
            item['sessionsStatus'] = 'met' if actual_sessions >= rule['minimumSessions'] else 'below_minimum'
        evidence[key] = item
        if 'minimumWeeklySets' in rule and weekly_sets < rule['minimumWeeklySets']:
            add_audit_issue(report, 'required_coverage_weekly_sets_below_minimum',
                f"Coverage role {key} has {weekly_sets:g} weekly working sets; required minimum is {rule['minimumWeeklySets']:g}.",
                'Add qualified work for the approved role and re-audit; preserve every other requirement.',
                path='/requiredCoverage', coverageKey=key, actual=weekly_sets, minimum=rule['minimumWeeklySets'])
        if 'minimumSessions' in rule:
            if actual_sessions < rule['minimumSessions']:
                add_audit_issue(report, 'required_coverage_sessions_below_minimum',
                    f"Coverage role {key} appears in {actual_sessions} weekly training sessions; required minimum is {rule['minimumSessions']}.",
                    'Place qualified work for the approved role in enough distinct weekly training sessions; preserve every other requirement.',
                    path='/requiredCoverage', coverageKey=key, actual=actual_sessions, minimum=rule['minimumSessions'])
    return report


def _check_volume(volume, targets, label, report, workout_index=None):
    for muscle, bounds in targets.items():
        if report.get('regionalTargetEvidence', {}).get(muscle, {}).get('status') == 'unknown_selected_aggregate_contributions':
            continue
        actual = volume[muscle]["effective"]
        minimum, maximum = volume_target_bounds(bounds)
        if not minimum <= actual <= maximum:
            below = actual < minimum
            difference = minimum - actual if below else actual - maximum
            add_audit_issue(report, "volume_below_target" if below else "volume_above_target",
                            f"{label} {muscle}: {actual:g} effective sets (direct={volume[muscle]['direct']:g}, indirect={volume[muscle]['indirect']:g}); required {volume_target_text(bounds)}.",
                            f"{'Increase' if below else 'Reduce'} effective {muscle} volume by adjusting working-set counts or exercise selection. Use the report's per-exercise contributions; preserve library muscle roles and agreed targets, and re-audit volume and duration together.",
                            path="/workouts" if workout_index is None else f"/workouts/{workout_index}/exercises",
                            scope="weekly" if workout_index is None else "per_session", muscle=muscle,
                            actual=actual, minimum=minimum,
                            maximum=None if not math.isfinite(maximum) else maximum,
                            difference=difference)


def _volume_target_status(value, bounds):
    minimum, maximum = volume_target_bounds(bounds)
    if value < minimum:
        return 'below_minimum'
    if value > maximum:
        return 'above_maximum'
    return 'within_target'


def muscle_credit_reliance_sensitivity(package, report):
    """Show which approved volume bounds depend on one definition's assigned credits."""
    definition_credits = {}
    session_credits = {}
    unmapped = []
    active_workouts = [workout for workout in package.get('workouts', [])
        if workout.get('enabled') is not False]
    for session_index, (workout, audited_day) in enumerate(zip(active_workouts, report.get('workouts', []), strict=True)):
        frequency = audited_day['timesCompletedInAWeek']
        contributions = {item['exerciseId']: item for item in audited_day['contributions']}
        for component in workout.get('workoutComponents', []):
            if component.get('enabled') is False:
                continue
            exercises = (component.get('exercises', []) if component.get('type') == 'Superset'
                else [component] if component.get('type') == 'Exercise' else [])
            for exercise in exercises:
                if exercise.get('enabled') is False:
                    continue
                contribution = contributions.get(exercise['id'], {})
                credits = contribution.get('credits', {})
                if not credits:
                    continue
                definition_id = (exercise.get('libraryDefinitionId') or exercise.get('exerciseDefinitionId')
                    or exercise.get('definition_id'))
                if not isinstance(definition_id, str) or not definition_id:
                    unmapped.append({'exerciseId': exercise['id'], 'exerciseName': exercise.get('name'),
                        'sessionIndex': session_index, 'session': audited_day['name'], 'muscles': sorted(credits)})
                    continue
                entry = definition_credits.setdefault(definition_id, {
                    'exerciseDefinitionId': definition_id, 'exerciseName': exercise.get('name'),
                    'libraryMuscleGroups': sorted(set(exercise.get('muscleGroups') or [])),
                    'librarySecondaryMuscleGroups': sorted(set(exercise.get('secondaryMuscleGroups') or [])),
                    'weeklyWorkingSets': 0, 'weeklyCredits': {}})
                entry['weeklyWorkingSets'] += contribution.get('workingSets', 0) * frequency
                session_entry = session_credits.setdefault((session_index, definition_id), {
                    'exerciseDefinitionId': definition_id, 'exerciseName': exercise.get('name'),
                    'credits': {}})
                for muscle, parts in credits.items():
                    values = entry['weeklyCredits'].setdefault(muscle, {'direct': 0, 'weightedIndirect': 0})
                    values['direct'] += parts.get('direct', 0) * frequency
                    values['weightedIndirect'] += parts.get('indirect', 0) * frequency
                    session_values = session_entry['credits'].setdefault(muscle,
                        {'direct': 0, 'weightedIndirect': 0})
                    session_values['direct'] += parts.get('direct', 0)
                    session_values['weightedIndirect'] += parts.get('indirect', 0)

    weekly_targets = []
    for muscle, bounds in report.get('targets', {}).get('weeklyEffectiveSets', {}).items():
        if muscle in REGIONAL_MUSCLE_LABELS:
            continue
        actual = report['weeklyVolume'][muscle]['effective']
        status = _volume_target_status(actual, bounds)
        dependencies = []
        identity_complete = not any(muscle in item['muscles'] for item in unmapped)
        if status == 'within_target' and identity_complete:
            for entry in definition_credits.values():
                parts = entry['weeklyCredits'].get(muscle, {})
                credit = parts.get('direct', 0) + parts.get('weightedIndirect', 0)
                after = actual - credit
                after_status = _volume_target_status(after, bounds)
                if credit and after_status != 'within_target':
                    dependencies.append({**{key: entry[key] for key in (
                        'exerciseDefinitionId', 'exerciseName', 'libraryMuscleGroups',
                        'librarySecondaryMuscleGroups', 'weeklyWorkingSets')},
                        'directCredit': parts.get('direct', 0),
                        'weightedIndirectCredit': parts.get('weightedIndirect', 0),
                        'effectiveCredit': credit, 'effectiveSetsWithoutDefinition': after,
                        'resultingStatus': after_status,
                        **({'shortfallBelowMinimum': bounds['minimum'] - after}
                            if after_status == 'below_minimum' else {})})
        weekly_targets.append({'muscle': muscle, 'approvedTarget': copy.deepcopy(bounds),
            'auditedEffectiveSets': actual, 'status': status,
            'identityComplete': identity_complete,
            'singleDefinitionDependencies': dependencies})

    per_session_minimums = []
    for muscle, bounds in report.get('targets', {}).get('perSessionEffectiveSets', {}).items():
        if muscle in REGIONAL_MUSCLE_LABELS:
            continue
        minimum = bounds['minimum']
        if minimum <= 0:
            continue
        for session_index, day in enumerate(report.get('workouts', [])):
            actual = day['volume'][muscle]['effective']
            dependencies = []
            identity_complete = not any(muscle in item['muscles'] and
                item.get('sessionIndex') == session_index for item in unmapped)
            if actual >= minimum and identity_complete:
                for (definition_session_index, _), entry in session_credits.items():
                    if definition_session_index != session_index:
                        continue
                    parts = entry['credits'].get(muscle, {})
                    credit = parts.get('direct', 0) + parts.get('weightedIndirect', 0)
                    after = actual - credit
                    if credit and after < minimum:
                        dependencies.append({**{key: entry[key] for key in (
                            'exerciseDefinitionId', 'exerciseName')},
                            'directCredit': parts.get('direct', 0),
                            'weightedIndirectCredit': parts.get('weightedIndirect', 0),
                            'effectiveCredit': credit, 'effectiveSetsWithoutDefinition': after,
                            'sessionIndex': session_index, 'shortfallBelowMinimum': minimum - after})
            per_session_minimums.append({'muscle': muscle, 'session': day['name'],
                'sessionIndex': session_index,
                'minimum': minimum, 'auditedEffectiveSets': actual,
                'status': 'meets_minimum' if actual >= minimum else 'below_minimum',
                'identityComplete': identity_complete,
                'singleDefinitionDependencies': dependencies})
    return {'source': 'canonical exercise definition muscleGroups and secondaryMuscleGroups fields',
        'accountingRule': 'primary=1.0; secondary=0.5; primary takes precedence',
        'physiologicalEquivalence': 'unknown',
        'interpretation': ('Single-definition omission is a sensitivity diagnostic with the plan held fixed. '
            'It does not propose changing library roles, establish a feasible replacement, or prove stimulus equivalence.'),
        'unmappedCreditOccurrences': unmapped,
        'weeklyTargets': weekly_targets, 'perSessionMinimums': per_session_minimums}


def plan_audit_package(plan, allow_educated_load_guesses=True):
    """Use upper rep targets before emission; actual emitted reps can only take less time."""
    by_id = {}
    for entry in plan["exercises"]:
        exercise = copy.deepcopy(entry)
        exercise["type"] = "Exercise"
        loaded = entry["exerciseType"] == "WEIGHT" or (entry["exerciseType"] == "BODY_WEIGHT" and entry.get("equipmentId") is not None)
        exercise["requiresLoadCalibration"] = entry.get("requiresLoadCalibration",
            loaded and (not allow_educated_load_guesses or not entry.get("targetSetPrescriptions")))
        sets = []
        for index in range(entry.get("numWorkSets", 1)):
            if index:
                sets.append({"type": "RestSet", "timeInSeconds": entry.get("restBetweenSetsSeconds", 0)})
            if entry["exerciseType"] in ("WEIGHT", "BODY_WEIGHT"):
                targets = entry.get("targetSetPrescriptions") or []
                reps = targets[index]["reps"] if targets else entry["maxReps"]
                sets.append({"type": "WeightSet" if entry["exerciseType"] == "WEIGHT" else "BodyWeightSet", "reps": reps})
            elif entry["exerciseType"] == "RUNNING":
                sets.append({"type": "RunningSet"})
            else:
                sets.append({"type": "EnduranceSet", "timeInMillis": entry.get("timeInMillis", 0)})
        exercise["sets"] = sets
        by_id[entry["id"]] = exercise
    workouts = []
    for workout in plan["workouts"]:
        structure = build_workout_structure(workout)
        components = []
        for component in structure["workoutComponents"]:
            kind = component["componentType"]
            if kind == "Exercise":
                components.append(by_id[component["exerciseId"]])
            elif kind == "Superset":
                components.append({**component, "type": kind, "exercises": [by_id[i] for i in component["exerciseIds"]]})
            else:
                components.append({"type": kind, "timeInSeconds": component["timeInSeconds"]})
        workouts.append({**workout, "workoutComponents": components})
    return {"workouts": workouts, 'timingRepBasis': CONSERVATIVE_REP_TIMING_BASIS}


def plan_timing_reps_by_exercise(plan, allow_educated_load_guesses=True):
    """Return the same rep counts used by the planned timing audit, keyed by exercise ID."""
    package = plan_audit_package(plan, allow_educated_load_guesses)
    result = {}
    for workout in package.get('workouts', []):
        for component in workout.get('workoutComponents', []):
            exercises = (component.get('exercises', []) if component.get('type') == 'Superset'
                         else [component] if component.get('type') == 'Exercise' else [])
            for exercise in exercises:
                reps = [item['reps'] for item in exercise.get('sets', [])
                        if _is_work_set(item) and item.get('type') in VOLUME_SET_TYPES.values()]
                if reps:
                    result[exercise['id']] = reps
    return result


def audit_and_repair_plan(client, plan, provided_equipment, logger=None, max_repairs=2, allow_educated_load_guesses=True):
    targets = copy.deepcopy(plan.get("auditTargets", {}))
    validate_audit_targets(targets)
    applied_changes = []
    for attempt in range(max_repairs + 1):
        report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), targets)
        if not report["issues"]:
            report["prescriptionChanges"] = applied_changes
            return plan, report
        if logger:
            logger.log_print("Programming audit failed: " + " | ".join(report["issues"]))
        if attempt == max_repairs:
            raise ValueError("Programming targets remain infeasible after bounded repair: " + " | ".join(report["issues"]))
        contributions = {item["exerciseId"]: item for workout in report["workouts"] for item in workout["contributions"]}
        repair_exercises = []
        for exercise in plan["exercises"]:
            contribution = contributions.get(exercise["id"], {})
            count = contribution.get("workingSets", 0)
            repair_exercises.append({
                "exerciseId": exercise["id"], "name": exercise["name"], "workingSets": exercise.get("numWorkSets"),
                "creditsPerWorkingSet": {muscle: (credit["direct"] + credit["indirect"]) / count for muscle, credit in contribution.get("credits", {}).items() if count},
                "maxReps": exercise.get("maxReps"), "restBetweenSetsSeconds": exercise.get("restBetweenSetsSeconds"),
                "countsLocked": bool(exercise.get("targetSetPrescriptions")),
            })
        messages = [
            {"role": "system", "content": (
                "Repair ONLY working-set counts of the supplied plan to satisfy the deterministic audit. "
                "Keep identities, equipment, exercise order, rests, warm-ups, rep ranges and target bounds unchanged. "
                "Superset members must retain equal work-set counts. Never alter exact targetSetPrescriptions. "
                "If infeasible, return changes=[]. "
                "Use the supplied creditsPerWorkingSet coefficients for arithmetic. Correct the FULL shortfall/excess in one attempt, "
                "not one set at a time. Budget additional work and rests against each session's remaining time. "
                'Output JSON only: {"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":4}]}.'
            )},
            {"role": "user", "content": json.dumps({"exercises": repair_exercises, "workouts": plan["workouts"], "audit": report}, separators=(",", ":"))},
        ]
        if logger:
            logger.log_request("repair_programming_audit", messages[-1]["content"])
        content = json_call_reasoner_only_with_loading(client, messages, "Repairing programming audit", show_loading=True, logger=logger)
        if content is None:
            raise KeyboardInterrupt
        if logger:
            logger.log_response("repair_programming_audit", content or "")
        changes = json.loads(content).get("changes")
        if not isinstance(changes, list) or not changes:
            raise ValueError("Model could not repair programming targets without changing the confirmed constraints: " + " | ".join(report["issues"]))
        repaired = copy.deepcopy(plan)
        by_id = {e["id"]: e for e in repaired["exercises"]}
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) - {"exerciseId", "numWorkSets"}:
                raise ValueError("Audit repair may change only working-set counts and placement notes")
            exercise_id, count = change.get("exerciseId"), change.get("numWorkSets")
            if exercise_id not in by_id or exercise_id in seen or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
                raise ValueError("Invalid or duplicate exercise/count in audit repair")
            seen.add(exercise_id)
            if by_id[exercise_id].get("targetSetPrescriptions"):
                raise ValueError("Audit repair cannot overwrite exact user-prescribed sets")
            applied_changes.append({"exerciseId": exercise_id, "name": by_id[exercise_id]["name"], "previousWorkingSets": by_id[exercise_id]["numWorkSets"], "workingSets": count})
            if logger:
                logger.log_print(f"  Audit repair {attempt+1}/{max_repairs}: {by_id[exercise_id]['name']} working sets {by_id[exercise_id]['numWorkSets']} -> {count}")
            by_id[exercise_id].update(numWorkSets=count)
        validate_plan_index_contract(repaired, provided_equipment)
        plan = repaired
