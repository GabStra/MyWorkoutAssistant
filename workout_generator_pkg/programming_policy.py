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
GOAL_METRICS = ('time_budget', 'volume_target', 'source_balance', 'workload_economy',
    'duration_balance', 'duration_economy', 'role_concentration', 'distribution',
    'movement_overlap', 'execution_complementarity', 'balance_control', 'exercise_count',
    'exercise_distribution', 'setup_economy')
OBJECTIVE_TIERS_SCHEMA = {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': {
    'type': 'array', 'minItems': 1, 'maxItems': 30, 'items': {'type': 'object', 'properties': {
        'metric': {'type': 'string', 'pattern': '^(?:' + '|'.join(GOAL_METRICS) + '|(?:coverage|weekly_volume|weekly_effective_sets):[a-z][a-z0-9_]{0,59})$'},
        'target': {'type': 'number'}, 'scale': {'type': 'number', 'exclusiveMinimum': 0},
        'group': {'type': 'string', 'pattern': '^[a-z][a-z0-9_]{0,59}$'}},
        'required': ['metric', 'target', 'scale'], 'additionalProperties': False}},
    'description': 'Optional source-approved goal tiers. Within a tier minimize the worst normalized target miss, then the total of group means plus ungrouped misses. Optional group labels give each group equal total weight regardless of its field count; ungrouped goals retain weight one. A miss is max(0, (metric-target)/scale); reaching a target earns no further reward. coverage:ROLE uses negative weekly qualified working sets. weekly_volume:MUSCLE uses deviation outside its existing preferred weekly range. weekly_effective_sets:MUSCLE uses negative audited weekly effective sets, so a negative target can favour additional volume within that range. Scales explicitly define comparable shortfalls; do not invent them or infer physiological adequacy. Tiers precede remaining objectiveOrder tie-breakers. Omission preserves the existing policy. Hard requirements remain independent.'}


def normalize_programming_policy(requirements):
    """Keep source-owned fields intact; omission never invents a goal or a ranking."""
    return {key: copy.deepcopy(requirements[key]) for key in (
        'auditTargets', 'sessionsPerWeek', 'trainingDays', 'minimumRestDaysBetweenSessions', 'workingSetRIR',
        'requiredCoverage', 'exerciseRestrictions', 'executionRules', 'familySetBounds',
        'objectiveOrder', 'preferredSessionSeconds', 'exerciseSelection', 'orderingPreferences',
        'durationBalanceToleranceSeconds', 'preferenceResolution', 'objectiveTiers') if key in requirements}


def goal_tier_names(requirements):
    return [f'goal_tier_{index}_{kind}' for index, _ in enumerate(requirements.get('objectiveTiers', []))
        for kind in ('worst', 'total')]


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


def execution_order_phase(priority, requirements):
    phases = requirements.get('orderingPreferences', {}).get('phaseOrder', [])
    category = EXECUTION_CATEGORIES[priority]
    return next((index for index, categories in enumerate(phases) if category in categories), 0)


def execution_interference_metric_names(requirements):
    return tuple(requirements.get('orderingPreferences', {}).get('protectionOrder', []))


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
        and order.index('workload_economy') < order.index('execution_order'))


def assess_audited_programming_tradeoff(baseline, candidate, *, requirements,
        baseline_costs, candidate_costs, objective_names, same_selected_work):
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
    baseline_costs = baseline_costs if isinstance(baseline_costs, dict) else {}
    candidate_costs = candidate_costs if isinstance(candidate_costs, dict) else {}
    owners = {'distribution_worst': 'distribution',
        'role_concentration_tiebreak': 'role_concentration',
        'exercise_distribution_development': 'exercise_distribution',
        'superset_lower_body_overlap': 'movement_overlap',
        'setup_economy_transitions': 'setup_economy',
        'setup_economy_resource_switches': 'setup_economy'}
    names = list(objective_names)
    if 'setup_economy' in requested:
        names.append('setup_economy_resource_switches')
    if 'execution_order' in names:
        names.remove('execution_order')
        names.extend('ordering_' + name for name in execution_interference_metric_names(requirements))
    for name in dict.fromkeys(names):
        owner = 'execution_order' if name.startswith('ordering_') else owners.get(name, name)
        if owner not in requested or owner == 'execution_order' and not same_selected_work:
            continue
        before, after = baseline_costs.get(name), candidate_costs.get(name)
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
        relations = {row['objective']: relation for relation in ('improved', 'worsened', 'unchanged')
            for row in result[relation]}
        overlap_relation = relations.get('movement_overlap')
        if overlap_relation in ('improved', 'worsened'):
            for row in result['volumeChanges']:
                before, after = row['baselineEffectiveSets'], row['candidateEffectiveSets']
                if (row['preferredMinimum'] is not None
                        and ((overlap_relation == 'improved' and after < before)
                             or (overlap_relation == 'worsened' and after > before))):
                    # Equivalent-movement repetition versus soft dose needs an artifact choice, not a hidden exchange rate.
                    result['status'] = 'requires_programming_decision'
                    return result
        for row in result['goalTiers']:
            if any(not known_number(row[label]) for label in ('baseline', 'candidate')):
                result['unknownObjectives'].append(row['objective'])
                return result
            if row['baseline'] != row['candidate']:
                result['status'] = ('candidate_preferred' if row['candidate'] < row['baseline']
                    else 'baseline_preferred')
                return result
        grouped = {goal['metric'] for tier in requirements['objectiveTiers'] for goal in tier}
        relations = {row['objective']: relation for relation in ('improved', 'worsened', 'unchanged')
            for row in result[relation]}
        for name in names:
            if name in grouped:
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
    if ('trainingDays' in requirements and requirements.get('sessionsPerWeek') is not None
            and len(requirements['trainingDays']) != requirements['sessionsPerWeek']):
        errors.append(('trainingDays', 'Explicit weekdays must provide one day per approved weekly session.'))
    preferred = requirements.get('preferredSessionSeconds')
    hard = requirements.get('auditTargets', {}).get('maximumSessionSeconds')
    if preferred is not None and hard is not None and preferred > hard:
        errors.append(('preferredSessionSeconds', 'The preferred session budget exceeds the hard ceiling.'))
    selection = requirements.get('exerciseSelection')
    if selection and selection['preferredMinimum'] > selection['preferredMaximum']:
        errors.append(('exerciseSelection', 'The preferred exercise-count minimum exceeds its maximum.'))
    phases = requirements.get('orderingPreferences', {}).get('phaseOrder', [])
    categories = [category for phase in phases for category in phase]
    if len(categories) != len(set(categories)):
        errors.append(('orderingPreferences/phaseOrder', 'Each execution category may appear in only one phase.'))
    if categories and set(categories) != set(EXECUTION_CATEGORIES):
        errors.append(('orderingPreferences/phaseOrder', 'An explicit phase order must include every execution category.'))
    seen = set()
    coverage = {rule['key'] for rule in requirements.get('requiredCoverage', [])}
    for index, tier in enumerate(requirements.get('objectiveTiers', [])):
        for goal in tier:
            metric = goal['metric']
            if metric in seen:
                errors.append((f'objectiveTiers/{index}', 'Each metric may belong to only one goal tier.'))
            seen.add(metric)
            if metric.startswith(('weekly_volume:', 'weekly_effective_sets:')):
                bounds = requirements.get('auditTargets', {}).get('weeklyEffectiveSets', {}).get(metric.split(':', 1)[1], {})
                approved = ('preferredMinimum' in bounds and 'volume_target' in requirements.get('objectiveOrder', []))
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
