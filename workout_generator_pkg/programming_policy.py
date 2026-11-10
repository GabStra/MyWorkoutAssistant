"""Approved programming preferences shared by compilation, comparison and reporting."""

import copy
import math
import re
from collections import Counter
from fractions import Fraction

from .cp_solver import _rational


INTERFERENCE_METRICS = ('priority_direct', 'priority_support', 'heavy_direct', 'heavy_support',
    'main_direct', 'main_support', 'adjacent_direct', 'adjacent_support')
EXECUTION_CATEGORIES = ('HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION', 'CORE')
SESSION_BALANCE_METRICS = ('session_exercise_balance', 'session_set_balance',
    'session_heavy_exercise_balance', 'session_heavy_set_balance')
arrangement_objectives = ('relative_role_concentration', 'relative_distribution', 'relative_distribution_worst')
GOAL_METRICS = ('volume_target', 'source_balance', 'workload_economy', 'heavy_workload_economy',
    *SESSION_BALANCE_METRICS, 'role_concentration', 'distribution',
    'movement_overlap', 'execution_complementarity', 'balance_control', 'exercise_count', 'exercise_preference',
    'exercise_distribution', 'setup_economy', 'setup_economy_transitions',
    'setup_economy_resource_switches', 'superset_lower_body_overlap', 'execution_blocks',
    *arrangement_objectives,
    *('ordering_' + name for name in INTERFERENCE_METRICS))
OBJECTIVE_TIERS_SCHEMA = {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': {
    'type': 'array', 'minItems': 1, 'maxItems': 30, 'items': {'type': 'object', 'properties': {
        'metric': {'type': 'string', 'pattern': '^(?:' + '|'.join(GOAL_METRICS) + '|(?:coverage|weekly_volume|weekly_effective_sets):[a-z][a-z0-9_]{0,59})$'},
        'target': {'type': 'number'}, 'scale': {'type': 'number', 'exclusiveMinimum': 0},
        'group': {'type': 'string', 'pattern': '^[a-z][a-z0-9_]{0,59}$'}},
        'required': ['metric', 'target', 'scale'], 'additionalProperties': False}},
    'description': 'Optional source-approved goal tiers. goalAggregation selects whether the combined total or worst normalized target miss is compared first within each tier. Optional group labels give each group equal total weight regardless of its field count; ungrouped goals retain weight one. A miss is max(0, (metric-target)/scale); reaching a target earns no further reward. An explicitly approved accepted shortfall may be a target for a reviewed-plan adjustment; it does not change the underlying preferred range or establish adequacy. coverage:ROLE uses negative weekly qualified working sets. weekly_volume:MUSCLE uses deviation outside its existing preferred weekly range. weekly_effective_sets:MUSCLE uses negative audited weekly effective sets, so a negative target can favour additional volume within that range. Scales explicitly define comparable shortfalls; do not invent them or infer physiological adequacy. An objectiveOrder goal_tier_N marker places existing tier N at that stage. Unmarked tiers precede remaining objectives. Goals before workload_economy have authority to select training dose. Explicit mixed tiers remain supported and can retain additional work for arrangement improvements, including relative exposure, session balance, interference or setup. When arrangement must conserve training dose, place its tier explicitly after standalone workload_economy. These post-workload tiers preserve selected weekly muscle and role doses, physical work and exercise membership while allowing session placement and compatible grouping to change. Separate tiers express priority between grouping, physical setup and distribution without inventing exchange rates. Omission preserves the existing policy. Hard requirements remain independent.'}
GOAL_AGGREGATION_SCHEMA = {'type': 'string', 'enum': ['worst_then_total', 'total_then_worst'],
    'description': 'Source-approved within-tier comparison: total_then_worst compares the sum of group-mean misses and ungrouped misses first, then the worst individual miss; worst_then_total reverses those two stages. Omission retains worst_then_total. Hard requirements do not change.'}


def session_balance_count(exercises, definitions, metric, work_sets=None):
    """Count prescribed work by category, without estimating personal fatigue."""
    if metric.startswith('session_heavy_'):
        if any(definitions.get(item['definition_id'], {}).get('exerciseCategory')
                not in EXECUTION_CATEGORIES for item in exercises):
            return None
        exercises = [item for item in exercises
            if definitions[item['definition_id']]['exerciseCategory'] == 'HEAVY_COMPOUND']
    if metric.endswith('set_balance'):
        return sum(item['numWorkSets'] if work_sets is None else work_sets for item in exercises)
    return len(exercises)


def normalize_programming_policy(requirements):
    """Keep source-owned fields intact; omission never invents a goal or a ranking."""
    return {key: copy.deepcopy(requirements[key]) for key in (
        'auditTargets', 'sessionsPerWeek', 'trainingDays', 'minimumRestDaysBetweenSessions', 'workingSetRIR',
        'requiredCoverage', 'exerciseRestrictions', 'executionRules', 'familySetBounds',
        'objectiveOrder', 'exerciseSelection', 'orderingPreferences',
        'preferenceResolution', 'objectiveTiers', 'goalAggregation',
        'generalWarmupSeconds', 'generalWarmupDefinitionId') if key in requirements}


def resolve_exercise_choices(requirements, equipment):
    """Bind explicit names to unique library identities; permission never implies selection."""
    from .planning_tools import PlanningInputError

    selection = requirements.get('exerciseSelection') or {}
    names = {}
    for definition in equipment.get('exerciseDefinitions', []):
        names.setdefault(' '.join(definition['name'].casefold().split()), set()).add(definition['id'])

    def resolve(name):
        matches = names.get(' '.join(name.casefold().split()), set())
        if len(matches) != 1:
            raise PlanningInputError('exercise_choice_unresolved',
                f"Exercise choice '{name}' must identify exactly one available library definition.",
                '/exerciseSelection', 'Resolve the name against the current library or ask which definition is intended; do not omit or broaden the choice.')
        return next(iter(matches))

    return {'required': {resolve(name) for name in selection.get('requiredNames', [])},
        'preferred': {role: {resolve(name) for name in choices}
            for role, choices in selection.get('preferredByCoverage', {}).items()}}


def exercise_preference_cost(workouts, definitions, choices):
    """Count distinct nonpreferred definitions within each explicitly scoped role."""
    return sum(len({definitions[item['definition_id']]['id']
        for day in workouts for item in day.get('exercises', [])
        if role in item.get('satisfiesCoverage', [])
        and definitions[item['definition_id']]['id'] not in preferred})
        for role, preferred in choices['preferred'].items())


def semantic_selection_ids(selection, equipment):
    """A semantic menu owns membership, never prescriptions or evidence claims."""
    if selection is None:
        return None
    from .planning_tools import PlanningInputError
    identifiers = selection.get('definitionIds') if isinstance(selection, dict) else None
    available = {item['id'] for item in equipment.get('exerciseDefinitions', [])}
    if (not isinstance(selection, dict) or selection.get('mode') != 'selected_menu'
            or not isinstance(identifiers, list) or not identifiers
            or any(not isinstance(value, str) for value in identifiers)
            or len(set(identifiers)) != len(identifiers) or set(identifiers) - available):
        raise PlanningInputError('invalid_semantic_selection',
            'The semantic exercise menu must name unique current library identities.',
            '/semanticSelection', 'Select an executable menu from the current candidates; code must not infer or replace its members.')
    return set(identifiers)


def goal_tier_names(requirements):
    kinds = ('total', 'worst') if requirements.get('goalAggregation') == 'total_then_worst' else ('worst', 'total')
    return [f'goal_tier_{index}_{kind}' for index, _ in enumerate(requirements.get('objectiveTiers', []))
        for kind in kinds]


def expand_goal_tiers(requirements, objective_names):
    """Place explicit tier markers while retaining the legacy prepend for unmarked tiers."""
    names = goal_tier_names(requirements)
    tiers = {f'goal_tier_{index}': names[index * 2:index * 2 + 2]
        for index, _ in enumerate(requirements.get('objectiveTiers', []))}
    marked = set(requirements.get('objectiveOrder') or []) & tiers.keys()
    grouped = {goal['metric'] for tier in requirements.get('objectiveTiers', []) for goal in tier}
    result = [name for marker, stages in tiers.items() if marker not in marked for name in stages]
    for name in objective_names:
        if name in tiers:
            result.extend(tiers[name])
        elif name not in grouped:
            result.append(name)
    return list(dict.fromkeys(result))


def settled_dose_goal_stages(requirements):
    """Explicit post-workload tiers arrange the already selected weekly training doses."""
    order = requirements.get('objectiveOrder') or []
    if 'workload_economy' not in order:
        return set()
    following = set(order[order.index('workload_economy') + 1:])
    return {name for name in goal_tier_names(requirements)
        if name.rsplit('_', 1)[0] in following}


def goal_aggregation_text(requirements):
    total = 'the sum of per-group mean shortfalls and ungrouped shortfalls'
    worst = 'the worst individual normalized shortfall'
    first, second = (total, worst) if requirements.get('goalAggregation') == 'total_then_worst' else (worst, total)
    return f'minimize {first} in each tier, then {second}'


def goal_target_text(goal):
    metric = goal['metric']
    if metric.startswith('coverage:'):
        target = f"{metric.split(':', 1)[1].replace('_', ' ')} ≥ {-goal['target']:g} weekly working sets (soft)"
    elif metric.startswith('weekly_effective_sets:'):
        target = f"{metric.split(':', 1)[1].replace('_', ' ')} ≥ {-goal['target']:g} weekly effective sets (soft aspiration)"
    else:
        label = (metric.split(':', 1)[1].replace('_', ' ') + ' preferred-range deviation'
            if metric.startswith('weekly_volume:') else metric.replace('_', ' '))
        target = f"{label} ≤ {goal['target']:g}"
    return (target + f"; shortfall scale {goal['scale']:g}"
        + (f"; group {goal['group']}" if 'group' in goal else ''))


def goal_total_weights(tier):
    """Average each explicit group; preserve legacy ungrouped goal weights."""
    counts = Counter(goal['group'] for goal in tier if 'group' in goal)
    return [Fraction(1, counts[goal['group']]) if 'group' in goal else Fraction(1)
        for goal in tier]


def goal_programming_costs(requirements, costs, coverage):
    """Score explicit aspirations; neither units nor unknown evidence become free gains."""
    result = {}
    for index, tier in enumerate(requirements.get('objectiveTiers', [])):
        misses = []
        for goal in tier:
            metric = goal['metric']
            value = costs.get(metric)
            if metric.startswith('coverage:'):
                value = coverage.get(metric.split(':', 1)[1]) if isinstance(coverage, dict) else None
                value = -value if type(value) in (int, float) else None
            if type(value) not in (int, float) or not math.isfinite(value):
                misses = None
                break
            misses.append(max(0, (_rational(value) - _rational(goal['target'])) / _rational(goal['scale'])))
        result[f'goal_tier_{index}_worst'] = float(max(misses)) if misses is not None else None
        result[f'goal_tier_{index}_total'] = (float(sum(miss * weight
            for miss, weight in zip(misses, goal_total_weights(tier)))) if misses is not None else None)
    return result


# Computational resolution, not a programming tolerance or an adequacy threshold.
RELATIVE_SHARE_UNITS = 1000


def relative_share_cost(numerator, denominator):
    """Round a nonnegative share upward on the same finite lattice as the solver."""
    numerator, denominator = _rational(numerator), _rational(denominator)
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError('Relative exposure requires 0 <= numerator <= denominator.')
    return math.ceil(RELATIVE_SHARE_UNITS * numerator / denominator) if denominator else 0


def add_relative_share_objective(variable, constraint, numerator_coeffs, denominator_coeffs,
        *, numerator_intercept=0, denominator_intercept=0, denominator_upper, label):
    """Compile a bounded share epigraph using the existing linear solver rows."""
    quantities = [denominator_intercept, denominator_upper, *denominator_coeffs.values()]
    if any(_rational(value).denominator != 1 or value < 0 for value in quantities):
        raise ValueError('Relative share denominators require nonnegative integer units.')
    upper = int(denominator_upper)
    if denominator_intercept > upper:
        raise ValueError('Relative share denominator upper bound excludes its intercept.')
    q = variable(upper=RELATIVE_SHARE_UNITS, domain_identity={
        'kind': 'relative_share', 'label': label})
    if not denominator_coeffs:
        denominator = int(denominator_intercept)
        if denominator:
            constraint(('relative_share', label, 'constant'), -math.inf, 0,
                {**{index: RELATIVE_SHARE_UNITS * value for index, value in numerator_coeffs.items()},
                    q: -denominator}, RELATIVE_SHARE_UNITS * numerator_intercept)
        else:
            constraint(('relative_share', label, 'empty'), 0, 0, {q: 1})
            constraint(('relative_share', label, 'empty_numerator'), 0, 0,
                numerator_coeffs, numerator_intercept)
        return q
    stride = math.gcd(int(denominator_intercept),
        *(int(value) for value in denominator_coeffs.values())) or 1
    # All possible denominators share this divisor; recipe exclusions may remove more.
    selectors = {dose: variable(domain_identity={
        'kind': 'relative_share_denominator', 'label': label, 'value': dose})
        for dose in range(0, upper + 1, stride)}
    constraint(('relative_share', label, 'one_denominator'), 1, 1,
        {index: 1 for index in selectors.values()})
    denominator_row = dict(denominator_coeffs)
    for dose, index in selectors.items():
        denominator_row[index] = -dose
    constraint(('relative_share', label, 'denominator'), 0, 0,
        denominator_row, denominator_intercept)
    bound = RELATIVE_SHARE_UNITS * upper
    for dose, index in selectors.items():
        row = {key: RELATIVE_SHARE_UNITS * value for key, value in numerator_coeffs.items()}
        row[index] = bound
        if dose:
            row[q] = -dose
        else:
            constraint(('relative_share', label, 'zero_dose'), -math.inf,
                RELATIVE_SHARE_UNITS, {q: 1, index: RELATIVE_SHARE_UNITS})
        constraint(('relative_share', label, dose), -math.inf, bound, row,
            RELATIVE_SHARE_UNITS * numerator_intercept)
    return q


def role_concentration_keys(requirements):
    from .recipe_contracts import CODE_OWNED_DIRECT_COVERAGE_ROLES
    targets = requirements.get('auditTargets') or {}
    targeted = {key.replace('lowerBack', 'lower_back') for scope in (
        'weeklyEffectiveSets', 'perSessionEffectiveSets') for key in targets.get(scope, {})}
    sessions = requirements.get('sessionsPerWeek')
    return sorted({rule['key'] for rule in requirements.get('requiredCoverage', [])
        if ((rule['key'] in CODE_OWNED_DIRECT_COVERAGE_ROLES and rule['key'] in targeted)
            or rule.get('intent') == 'development')
        and (rule.get('scope') == 'eachSession' or sessions is not None
            and rule.get('minimumSessions') is not None and rule['minimumSessions'] >= sessions)})


def conserved_coverage_roles(requirements):
    """Preserve dose authority while inclusion minima remain native constraints."""
    roles = {rule['key'] for rule in requirements.get('requiredCoverage', [])
        if rule.get('intent') != 'inclusion'}
    roles.update(goal['metric'].split(':', 1)[1]
        for tier in requirements.get('objectiveTiers', []) for goal in tier
        if goal['metric'].startswith('coverage:'))
    for rule in requirements.get('executionRules', []):
        if rule.get('kind') == 'coverageBalance':
            roles.update((rule['first'], rule['second']))
    return sorted(roles)


def same_weekly_training_doses(baseline, candidate, requirements):
    """Compare dose identities; None preserves unknown evidence instead of implying a mismatch."""
    targets = requirements.get('auditTargets', {})
    muscles = set(targets.get('weeklyEffectiveSets', {})) | set(targets.get('perSessionEffectiveSets', {}))
    roles = conserved_coverage_roles(requirements)

    def identity(value):
        audit = value.get('audit', {})
        if unknown_exposure_muscles(audit, requirements, muscles=muscles):
            return None
        workouts = value.get('workouts', audit.get('workouts', []))
        frequencies = [day.get('timesCompletedInAWeek') for day in workouts]
        if not frequencies or any(type(frequency) is not int or frequency < 1 for frequency in frequencies):
            return None
        doses = [audit.get('weeklyVolume', {}).get(muscle, {}).get('effective') for muscle in sorted(muscles)]
        doses.extend(audit.get('weeklyCoverageSets', {}).get(role) for role in sorted(roles))
        if any(type(dose) not in (int, float) or not math.isfinite(dose) or dose < 0 for dose in doses):
            return None
        return tuple(frequencies), tuple(_rational(dose) for dose in doses)

    before, after = identity(baseline), identity(candidate)
    return None if before is None or after is None else before == after


def marked_arrangement_comparable(baseline, candidate, requirements):
    """Keep physical work and selected references fixed within the shared candidate domain."""
    same_doses = same_weekly_training_doses(baseline, candidate, requirements)
    if same_doses is not True:
        return same_doses

    def identity(value):
        audit = value.get('audit', {})
        physical_sets = audit.get('weeklyWorkingSets')
        workouts = value.get('workouts', audit.get('workouts'))
        if (type(physical_sets) not in (int, float) or not math.isfinite(physical_sets)
                or physical_sets < 0 or not isinstance(workouts, list)):
            return None
        selected = set()
        for day in workouts:
            for item in day.get('exercises', []):
                count, reference = item.get('numWorkSets'), item.get('definition_id')
                if type(count) is not int or count < 0 or not isinstance(reference, str):
                    return None
                if count:
                    selected.add(reference)
        return _rational(physical_sets), selected

    before, after = identity(baseline), identity(candidate)
    return None if before is None or after is None else before == after


def muscle_distribution_scope(requirements):
    """Balance supported muscle groups independently of approved volume bounds."""
    from .muscle_roles import MUSCLE_LABELS, REGIONAL_MUSCLE_PARENT

    targets = requirements.get('auditTargets', {})
    targeted = set(targets.get('weeklyEffectiveSets', {})) | set(targets.get('perSessionEffectiveSets', {}))
    regions = targeted & REGIONAL_MUSCLE_PARENT.keys()
    return sorted((set(MUSCLE_LABELS) | targeted)
        - {REGIONAL_MUSCLE_PARENT[region] for region in regions})


def unknown_exposure_muscles(audit, requirements, *, muscles=None):
    muscles = set(muscle_distribution_scope(requirements) if muscles is None else muscles)
    unknown = {muscle for muscle in muscles if audit.get('regionalTargetEvidence', {}).get(
        muscle, {}).get('status') == 'unknown_selected_aggregate_contributions'}
    evidence = audit.get('volumePreferenceEvidence', {})
    unknown.update(row['muscle'] for scope in ('weekly', 'perSession') for row in evidence.get(scope, [])
        if row.get('muscle') in muscles and row.get('status') == 'unknown')
    return unknown


def relative_exposure_costs(workouts, audit, requirements, role_evidence=None):
    """Measure distribution independently of dose; zero exposure proves no adequacy."""
    days = audit.get('workouts', [])
    frequencies = [day.get('timesCompletedInAWeek', 1) for day in workouts]
    names = ('relative_role_concentration', 'relative_distribution', 'relative_distribution_worst')
    if len(days) != len(frequencies) or any(type(value) is not int or value < 1 for value in frequencies):
        return dict.fromkeys(names)
    occurrences = sum(frequencies)
    if not days:
        return dict.fromkeys(names, 0)

    def doses(section, key):
        values = [day.get(section, {}).get(key) for day in days]
        if section == 'volume':
            values = [value.get('effective') if isinstance(value, dict) else None for value in values]
        return values if all(type(value) in (int, float) and math.isfinite(value)
            and value >= 0 for value in values) else None

    role_costs = []
    for role in role_concentration_keys(requirements):
        values = doses('coverageSets', role)
        if values is None:
            role_costs = None
            break
        weekly = sum(value * frequency for value, frequency in zip(values, frequencies))
        role_costs.append(relative_share_cost(max(0, occurrences * max(values) - weekly),
            (occurrences - 1) * weekly))
    muscles = muscle_distribution_scope(requirements)
    muscle_costs = None if unknown_exposure_muscles(audit, requirements) else []
    for muscle in sorted(muscles) if muscle_costs is not None else []:
        values = doses('volume', muscle)
        if values is None:
            muscle_costs = None
            break
        weekly = sum(value * frequency for value, frequency in zip(values, frequencies))
        muscle_costs.append(relative_share_cost(sum(frequency * abs(occurrences * value - weekly)
            for value, frequency in zip(values, frequencies)), 2 * (occurrences - 1) * weekly))
    return {'relative_role_concentration': (max(role_costs, default=0) / RELATIVE_SHARE_UNITS
                if role_costs is not None else None),
        'relative_distribution': (sum(muscle_costs) / (RELATIVE_SHARE_UNITS * len(muscles))
                if muscle_costs and muscles else 0 if muscle_costs is not None else None),
        'relative_distribution_worst': (max(muscle_costs, default=0) / RELATIVE_SHARE_UNITS
                if muscle_costs is not None else None)}


def execution_order_phase(priority, requirements):
    if priority == -1:
        return -1
    phases = requirements.get('orderingPreferences', {}).get('phaseOrder', [])
    category = EXECUTION_CATEGORIES[priority]
    return next((index for index, categories in enumerate(phases) if category in categories), 0)


def execution_interference_metric_names(requirements):
    """Resolve ties within each protected exposure before moving to the next metric."""
    return tuple(component
        for name in requirements.get('orderingPreferences', {}).get('protectionOrder', [])
        for component in ((name, name + '_total') if name.startswith(('heavy_', 'main_')) else (name,)))


def source_balance_dose_components(requirements):
    """Balance settled exposure within connected roles without pinning each role."""
    if requirements.get('objectiveTiers'):
        return []  # Explicit aspirations own dose; an intermediate incumbent does not.
    order = requirements.get('objectiveOrder') or []
    if 'source_balance' not in order:
        return []
    preceding = order[:order.index('source_balance')]
    volume_preferences = any('preferredMinimum' in bounds
        for key in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
        for bounds in requirements.get('auditTargets', {}).get(key, {}).values())
    if 'workload_economy' not in preceding and not ('volume_target' in preceding and volume_preferences):
        return []
    components = []
    for scope in ('weekly', 'eachSession'):
        groups = []
        for rule in requirements.get('executionRules', []):
            if rule.get('kind') != 'coverageBalance' or rule.get('scope') != scope:
                continue
            connected = {rule['first'], rule['second']}
            separate = []
            for group in groups:
                if connected & group:
                    connected.update(group)
                else:
                    separate.append(group)
            groups = separate + [connected]
        components.extend({'scope': scope, 'roles': sorted(group)}
            for group in sorted(groups, key=lambda group: sorted(group)))
    return components


def selection_precedes_execution(requirements):
    order = requirements.get('objectiveOrder') or []
    return ('execution_order' in order and 'workload_economy' in order
        and order.index('workload_economy') < order.index('execution_order')
        and not any(goal['metric'].startswith('ordering_')
            or goal['metric'] in ('setup_economy_transitions', 'setup_economy_resource_switches')
            for tier in requirements.get('objectiveTiers', []) for goal in tier))


def assess_audited_programming_tradeoff(baseline, candidate, *, requirements,
        baseline_costs, candidate_costs, objective_names, same_selected_work,
        same_selected_weekly_work=False):
    """Compare supplied native facts without assigning exchange rates to preferences."""
    result = {'status': 'unknown', 'improved': [], 'worsened': [], 'unchanged': [],
        'unknownObjectives': [], 'developmentChanges': [], 'hardErrors': {}}
    audits = {}
    for label, value in (('baseline', baseline), ('candidate', candidate)):
        audit = value.get('audit') if isinstance(value, dict) else None
        audits[label] = audit if isinstance(audit, dict) else {}
        errors = audits[label].get('errors')
        result['hardErrors'][label] = copy.deepcopy(errors) if isinstance(errors, list) else None
        if not isinstance(errors, list):
            result['unknownObjectives'].append('native_audit:' + label)
    if any(result['hardErrors'].values()):
        result['status'] = 'hard_violation'
        return result
    if any(value is None for value in result['hardErrors'].values()):
        return result

    def known_number(value):
        return type(value) in (int, float) and math.isfinite(value)

    requested = set(requirements.get('objectiveOrder') or [])
    grouped = {goal['metric'] for tier in requirements.get('objectiveTiers', []) for goal in tier}
    baseline_costs = baseline_costs if isinstance(baseline_costs, dict) else {}
    candidate_costs = candidate_costs if isinstance(candidate_costs, dict) else {}
    owners = {'distribution_worst': 'distribution',
        'relative_distribution_worst': 'relative_distribution',
        'role_concentration_tiebreak': 'role_concentration',
        'exercise_distribution_development': 'exercise_distribution',
        'superset_lower_body_overlap': 'movement_overlap',
        'execution_blocks': 'setup_economy',
        'setup_economy_transitions': 'setup_economy',
        'setup_economy_resource_switches': 'setup_economy'}
    setup_refinements = ('setup_economy_transitions', 'setup_economy_resource_switches')
    names = list(objective_names)
    if 'setup_economy' in requested:
        names.extend(setup_refinements)
    if 'execution_order' in names:
        names.remove('execution_order')
        names.extend('ordering_' + name for name in execution_interference_metric_names(requirements))
    arrangement_comparable = same_weekly_training_doses(baseline, candidate, requirements)
    for name in dict.fromkeys(names):
        if name.startswith('goal_tier_'):
            continue
        owner = 'execution_order' if name.startswith('ordering_') else owners.get(name, name)
        if owner not in requested or (owner == 'execution_order'
                and not (same_selected_work or same_selected_weekly_work) and name not in grouped):
            continue
        before, after = baseline_costs.get(name), candidate_costs.get(name)
        if name in arrangement_objectives and name not in grouped:
            if arrangement_comparable is False:
                result.setdefault('inapplicableObjectives', []).append({'objective': name,
                    'baseline': before, 'candidate': after, 'reason': 'weekly_training_doses_differ'})
                continue
            if arrangement_comparable is None:
                result['unknownObjectives'].append(name)
                continue
        if not known_number(before) or not known_number(after):
            result['unknownObjectives'].append(name)
            continue
        relation = 'improved' if after < before else 'worsened' if after > before else 'unchanged'
        result[relation].append({'objective': name, 'baseline': before, 'candidate': after})

    for role in sorted({rule['key'] for rule in requirements.get('requiredCoverage', [])
            if rule.get('intent') == 'development'}):
        coverage = [audit.get('weeklyCoverageSets') for audit in (audits['baseline'], audits['candidate'])]
        before, after = [counts.get(role) if isinstance(counts, dict) else None for counts in coverage]
        if not known_number(before) or not known_number(after):
            result['unknownObjectives'].append('development_role:' + role)
        elif before != after:
            result['developmentChanges'].append({'role': role,
                'baselineWorkingSets': before, 'candidateWorkingSets': after})
    result['volumeChanges'] = []
    for muscle, bounds in requirements.get('auditTargets', {}).get('weeklyEffectiveSets', {}).items():
        before, after = [audit.get('weeklyVolume', {}).get(muscle, {}).get('effective')
            for audit in (audits['baseline'], audits['candidate'])]
        if known_number(before) and known_number(after) and before != after:
            result['volumeChanges'].append({'muscle': muscle, 'baselineEffectiveSets': before,
                'candidateEffectiveSets': after, 'preferredMinimum': bounds.get('preferredMinimum'),
                'preferredMaximum': bounds.get('preferredMaximum')})
    if result['unknownObjectives'] and not requirements.get('objectiveTiers'):
        return result
    if requirements.get('objectiveTiers'):
        tier_names = goal_tier_names(requirements)
        result['goalTiers'] = [{'objective': name, 'baseline': baseline_costs.get(name),
            'candidate': candidate_costs.get(name)} for name in tier_names]
        settled_stages = settled_dose_goal_stages(requirements)
        marked_comparable = (marked_arrangement_comparable(baseline, candidate, requirements)
            if settled_stages else None)
        relations = {row['objective']: relation for relation in ('improved', 'worsened', 'unchanged')
            for row in result[relation]}
        for name in expand_goal_tiers(requirements, names):
            if name in tier_names:
                before, after = baseline_costs.get(name), candidate_costs.get(name)
                if name in settled_stages:
                    if marked_comparable is False:
                        result.setdefault('inapplicableObjectives', []).append({'objective': name,
                            'baseline': before, 'candidate': after, 'reason': 'selected_weekly_work_or_training_doses_differ'})
                        continue
                    if marked_comparable is None:
                        result['unknownObjectives'].append(name)
                        return result
                if not known_number(before) or not known_number(after):
                    result['unknownObjectives'].append(name)
                    return result
                if before != after:
                    result['status'] = 'candidate_preferred' if after < before else 'baseline_preferred'
                    return result
                continue
            if name in result['unknownObjectives']:
                return result
            if relations.get(name) in (None, 'unchanged'):
                continue
            if name.startswith('exercise_distribution') and result['developmentChanges']:
                result['status'] = 'requires_programming_decision'
            else:
                result['status'] = 'candidate_preferred' if relations[name] == 'improved' else 'baseline_preferred'
            return result
        if result['unknownObjectives']:
            return result
        result['status'] = 'equivalent'
        return result
    if result['developmentChanges'] or result['improved'] and result['worsened']:
        result['status'] = 'requires_programming_decision'
    elif result['improved']:
        result['status'] = 'candidate_dominates'
    elif result['worsened']:
        result['status'] = 'baseline_dominates'
    else:
        result['status'] = 'equivalent'
    return result


def exercise_count_credits(definition):
    """Direct or substantial assistance qualifies; reviewed incidental work has zero credit."""
    from .generation_audit import muscle_credits_per_set
    return {muscle: values['direct'] + values['indirect']
            for muscle, values in muscle_credits_per_set(definition).items()
            if values['direct'] + values['indirect'] > 0}


def qualified_exercise_ids_by_muscle(definitions):
    """Count exact qualified definitions once across the week, including repeated sessions."""
    qualified = {}
    for definition in definitions:
        identifier = (definition.get('libraryDefinitionId') or definition.get('exerciseDefinitionId')
            or definition.get('definition_id') or definition.get('id'))
        if identifier is None:
            continue
        for muscle in exercise_count_credits(definition):
            qualified.setdefault(muscle, set()).add(identifier)
    return qualified


def exercise_count_preference_facts(definitions, requirements):
    from .generation_audit import muscle_credits_per_set, REGIONAL_MUSCLE_PARENT
    preference = requirements.get('exerciseSelection')
    if not preference:
        return {}
    primary, secondary, unknown = {}, {}, {}
    for definition in definitions:
        identifier = (definition.get('libraryDefinitionId') or definition.get('exerciseDefinitionId')
            or definition.get('definition_id') or definition.get('id'))
        if identifier is None:
            continue
        credits = muscle_credits_per_set(definition)
        for muscle, values in credits.items():
            if values['direct'] > 0:
                primary.setdefault(muscle, set()).add(identifier)
            elif values['indirect'] > 0:
                secondary.setdefault(muscle, set()).add(identifier)
        for region, parent in REGIONAL_MUSCLE_PARENT.items():
            if region not in credits and parent in credits:
                unknown.setdefault(region, set()).add(identifier)
    minimum, maximum = preference['preferredMinimum'], preference['preferredMaximum']
    facts = {}
    for muscle in preference['muscles']:
        direct = primary.get(muscle, set())
        indirect = secondary.get(muscle, set()) - direct
        qualified = direct | indirect
        incomplete = bool(unknown.get(muscle))
        facts[muscle] = {'exerciseIds': sorted(qualified),
            'primaryExerciseIds': sorted(direct), 'secondaryExerciseIds': sorted(indirect),
            'unknownExerciseIds': sorted(unknown.get(muscle, set())),
            'status': 'insufficient_evidence' if incomplete else 'known',
            'count': None if incomplete else len(qualified), 'knownCount': len(qualified),
            'preferredMinimum': minimum, 'preferredMaximum': maximum,
            'shortfall': None if incomplete else max(0, minimum - len(qualified)),
            'excess': None if incomplete else max(0, len(qualified) - maximum),
            'complementarity': 'Requires execution evidence; count and family diversity do not prove ROM or muscle-length coverage.'}
    return facts


def programming_policy_errors(requirements):
    errors = []
    order = requirements.get('objectiveOrder') or []
    tiers = requirements.get('objectiveTiers', [])
    grouped = {goal['metric'] for tier in tiers for goal in tier}
    markers = [name for name in order if name.startswith('goal_tier_')]
    for marker in markers:
        if not re.fullmatch('goal_tier_[0-7]', marker) or int(marker.removeprefix('goal_tier_')) >= len(tiers):
            errors.append(('objectiveOrder', 'Each goal_tier_N marker must refer to an existing tier from 0 to 7.'))
        if markers.count(marker) > 1:
            errors.append(('objectiveOrder', 'Each goal tier may have only one objectiveOrder marker.'))
    if settled_dose_goal_stages(requirements) and any(goal['metric'] == 'workload_economy'
            for tier in tiers for goal in tier):
        errors.append(('objectiveTiers',
            'Post-workload tiers require a standalone workload_economy stage to fix the selected weekly doses.'))
    if any(metric in order and metric not in grouped and ('workload_economy' not in order
            or order.index('workload_economy') > order.index(metric)) for metric in arrangement_objectives):
        errors.append(('objectiveOrder',
            'Relative exposure arrangement requires workload_economy earlier in objectiveOrder to settle the weekly dose.'))
    aggregation = requirements.get('goalAggregation')
    if aggregation is not None and (aggregation not in GOAL_AGGREGATION_SCHEMA['enum']
            or not requirements.get('objectiveTiers')):
        errors.append(('goalAggregation', 'An approved aggregation mode requires nonempty goal tiers.'))
    if ('trainingDays' in requirements and requirements.get('sessionsPerWeek') is not None
            and len(requirements['trainingDays']) != requirements['sessionsPerWeek']):
        errors.append(('trainingDays', 'Explicit weekdays must provide one day per approved weekly session.'))
    selection = requirements.get('exerciseSelection')
    if selection and selection['preferredMinimum'] > selection['preferredMaximum']:
        errors.append(('exerciseSelection', 'The preferred exercise-count minimum exceeds its maximum.'))
    if selection and selection.get('preferredByCoverage'):
        if 'exercise_preference' not in order:
            errors.append(('objectiveOrder', 'Scoped exercise preferences require an explicitly ranked exercise_preference objective.'))
        if set(selection['preferredByCoverage']) - {rule['key'] for rule in requirements.get('requiredCoverage', [])}:
            errors.append(('exerciseSelection/preferredByCoverage', 'Exercise preferences must refer to approved coverage roles.'))
    phases = requirements.get('orderingPreferences', {}).get('phaseOrder', [])
    categories = [category for phase in phases for category in phase]
    if len(categories) != len(set(categories)):
        errors.append(('orderingPreferences/phaseOrder', 'Each execution category may appear in only one phase.'))
    if categories and set(categories) != set(EXECUTION_CATEGORIES):
        errors.append(('orderingPreferences/phaseOrder', 'An explicit phase order must include every execution category.'))
    seen = set()
    coverage = {rule['key'] for rule in requirements.get('requiredCoverage', [])}
    for index, tier in enumerate(requirements.get('objectiveTiers', [])):
        marker = f'goal_tier_{index}'
        explicitly_placed = marker in order
        after_workload = (explicitly_placed and 'workload_economy' in order
            and order.index('workload_economy') < order.index(marker))
        for goal in tier:
            metric = goal['metric']
            if after_workload and (metric.startswith(('coverage:', 'weekly_volume:', 'weekly_effective_sets:'))
                    or metric in ('volume_target', 'source_balance', 'workload_economy')):
                errors.append((f'objectiveTiers/{index}',
                    'Post-workload goal tiers must preserve selected weekly doses and cannot contain dose-selection goals.'))
            if metric in seen:
                errors.append((f'objectiveTiers/{index}', 'Each metric may belong to only one goal tier.'))
            seen.add(metric)
            if metric.startswith(('weekly_volume:', 'weekly_effective_sets:')):
                bounds = requirements.get('auditTargets', {}).get('weeklyEffectiveSets', {}).get(metric.split(':', 1)[1], {})
                approved = 'preferredMinimum' in bounds
            elif metric.startswith('ordering_'):
                approved = ('execution_order' in requirements.get('objectiveOrder', [])
                    and metric.removeprefix('ordering_') in requirements.get(
                        'orderingPreferences', {}).get('protectionOrder', []))
            elif metric in ('setup_economy_transitions', 'setup_economy_resource_switches', 'execution_blocks'):
                approved = 'setup_economy' in order
            elif metric == 'relative_distribution_worst':
                approved = 'relative_distribution' in order
            elif metric == 'superset_lower_body_overlap':
                approved = 'movement_overlap' in order
            else:
                approved = (metric.split(':', 1)[1] in coverage if metric.startswith('coverage:')
                    else metric in requirements.get('objectiveOrder', []))
            if not approved:
                errors.append((f'objectiveTiers/{index}', 'Each goal must refer to an approved coverage role or ranked objective.'))
            if (any(type(goal[key]) not in (int, float) or not math.isfinite(goal[key])
                    for key in ('target', 'scale')) or goal['scale'] <= 0):
                errors.append((f'objectiveTiers/{index}', 'Goal targets and positive scales must be finite numbers.'))
            if 'group' in goal and (not isinstance(goal['group'], str)
                    or not re.fullmatch('[a-z][a-z0-9_]{0,59}', goal['group'])):
                errors.append((f'objectiveTiers/{index}', 'Goal groups must be nonempty lowercase identifier labels.'))
    return [{'code': 'invalid_programming_policy', 'path': '/' + path, 'message': message,
        'repair': 'Correct the structured policy against the original source; preserve unrelated approved fields.'}
        for path, message in errors]
