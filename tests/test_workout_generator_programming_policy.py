import copy
import json
from pathlib import Path

import pytest
from jsonschema import validate

from workout_generator_pkg.planning_tools import (
    _REQUIREMENTS, PlanningInputError, compile_coordinated_repair, coordinated_repair_tool,
    render_requirements,
)
from workout_generator_pkg.programming_guidelines import (
    GUIDELINE_POLICY, execution_interference_score, execution_order_is_admissible,
)
from workout_generator_pkg.programming_policy import (
    exercise_count_preference_facts, normalize_programming_policy, programming_policy_errors,
    assess_audited_programming_tradeoff,
)


def initial_requirements():
    return json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))


def test_approved_policy_jointly_ranks_quality_before_workload_without_weakening_hard_limits():
    from workout_generator_pkg.programming_policy import (
        INTERFERENCE_METRICS, expand_goal_tiers, selection_precedes_execution,
        settled_dose_goal_stages,
    )

    requirements = initial_requirements()
    validate(requirements, _REQUIREMENTS)
    assert not programming_policy_errors(requirements)
    assert len(requirements['objectiveTiers']) == 1
    goals = {goal['metric']: goal for goal in requirements['objectiveTiers'][0]}
    assert {goal['group'] for goal in goals.values()} == {
        'muscle_volume', 'movement_development', 'selection', 'interference', 'session_balance',
        'setup', 'exposure_distribution'}
    expected_scales = {'movement_overlap': 2, 'exercise_count': 5,
        'setup_economy': 40, 'execution_blocks': 40,
        'session_exercise_balance': 1, 'relative_distribution': 1, 'relative_distribution_worst': 1,
        'superset_lower_body_overlap': 3,
        **{'ordering_' + metric: 64 for metric in INTERFERENCE_METRICS}}
    assert all(goals[metric]['target'] == 0 and goals[metric]['scale'] == scale
        for metric, scale in expected_scales.items())
    assert requirements['goalAggregation'] == 'total_then_worst'
    assert not {'source_balance', 'role_concentration', 'distribution',
        'session_set_balance', 'setup_economy_resource_switches',
        'execution_complementarity', 'balance_control'} & goals.keys()
    assert goals['coverage:lateral_delt']['target'] == goals['coverage:vertical_pull']['target'] == -4
    assert not any(metric.startswith('weekly_effective_sets:') for metric in goals)
    order = requirements['objectiveOrder']
    expanded = expand_goal_tiers(requirements, order)
    assert expanded[:3] == ['goal_tier_0_total', 'goal_tier_0_worst', 'workload_economy']
    assert expanded.index('workload_economy') < expanded.index('session_set_balance')
    assert order.index('workload_economy') < order.index('setup_economy')
    assert 'relative_distribution' not in expanded
    assert not settled_dose_goal_stages(requirements)
    assert not selection_precedes_execution(requirements)
    assert not {'volume_target', 'source_balance', 'demand_distribution',
        'execution_complementarity', 'balance_control'} & set(order)
    assert requirements['exerciseSelection']['preferredMinimum'] == 0
    assert requirements['exerciseSelection']['requiredNames'] == ['Cable Crunch']
    assert requirements['orderingPreferences']['phaseOrder'] == [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION', 'CORE']]
    roles = {rule['key']: rule for rule in requirements['requiredCoverage']}
    assert all('minimumWeeklySets' not in role and 'minimumSessions' not in role
        for role in roles.values())
    assert roles['calves']['intent'] == roles['knee_flexion_hamstring']['intent'] == 'inclusion'
    policy = normalize_programming_policy(requirements)
    assert all(bounds['minimum'] == 0 and bounds['maximum'] is None
        for bounds in policy['auditTargets']['weeklyEffectiveSets'].values())
    assert all(bounds['preferredMinimum'] == 10 and bounds['preferredMaximum'] == 15
        for muscle, bounds in policy['auditTargets']['weeklyEffectiveSets'].items() if muscle != 'abs')
    assert policy['auditTargets']['weeklyEffectiveSets']['abs']['preferredMinimum'] == 9
    assert not {'maximumSessionSeconds'} & policy['auditTargets'].keys()
    assert not {'preferredSessionSeconds', 'durationBalanceToleranceSeconds'} & policy.keys()
    assert requirements['generalWarmupSeconds'] == 300
    warmup_rules = [rule for rule in requirements['executionRules'] if rule['kind'] == 'warmup']
    assert {rule['exerciseCategory'] for rule in warmup_rules} == {'HEAVY_COMPOUND', 'MODERATE_COMPOUND'}
    assert all(rule['coverageKey'] is None and rule['whenSupported'] for rule in warmup_rules)
    bounds = next(rule for rule in requirements['executionRules'] if rule['kind'] == 'workSets')
    assert (bounds['minimumSets'], bounds['maximumSets']) == (2, 3)
    structure = next(rule for rule in requirements['executionRules'] if rule['kind'] == 'sessionStructure')
    assert (structure['maximumExercises'], structure['maximumSupersets'], structure['maximumSupersetSize']) == (15, 3, 3)
    rests = {rule['context']: rule for rule in requirements['executionRules']
        if rule.get('context') in ('supersetTransition', 'supersetRound')}
    assert (rests['supersetTransition']['minimumSeconds'], rests['supersetTransition']['maximumSeconds']) == (0, 0)
    assert (rests['supersetRound']['minimumSeconds'], rests['supersetRound']['maximumSeconds']) == (60, 120)
    rendered = render_requirements(requirements)
    assert 'Required weekly exercise choices: Cable Crunch' in rendered
    assert 'unequal counts alone do not establish a violation' in rendered
    assert sum(rule['kind'] == 'coverageBalance' for rule in requirements['executionRules']) == 3


@pytest.mark.parametrize('group', ['', 'Bad group', None, 1])
def test_goal_group_labels_are_validated_at_schema_and_policy_boundaries(group):
    from jsonschema import ValidationError

    requirements = initial_requirements()
    requirements['objectiveTiers'][0][0]['group'] = group
    with pytest.raises(ValidationError):
        validate(requirements, _REQUIREMENTS)
    assert programming_policy_errors(requirements)[0]['message'] == (
        'Goal groups must be nonempty lowercase identifier labels.')


def test_weekly_count_uses_substantial_credit_and_deduplicates_exact_definitions():
    requirements = {'exerciseSelection': {'preferredMinimum': 2, 'preferredMaximum': 3,
        'muscles': ['chest', 'triceps', 'abs']}}
    press = {'id': 'PRESS', 'exerciseType': 'WEIGHT', 'muscleGroups': ['FRONT_CHEST'],
        'secondaryMuscleGroups': ['BACK_TRICEPS']}
    facts = exercise_count_preference_facts([press, copy.deepcopy(press)], requirements)
    assert facts['chest']['count'] == facts['triceps']['count'] == 1
    assert facts['chest']['primaryExerciseIds'] == ['PRESS']
    assert facts['triceps']['secondaryExerciseIds'] == ['PRESS']
    assert facts['chest']['shortfall'] == 1
    assert facts['abs']['count'] == 0
    assert facts['abs']['shortfall'] == 2
    assert 'execution evidence' in facts['chest']['complementarity']
    requirements['exerciseSelection']['muscles'] = ['pectoralis_clavicular']
    region = exercise_count_preference_facts([press], requirements)['pectoralis_clavicular']
    assert region['status'] == 'insufficient_evidence'
    assert region['count'] is None and region['shortfall'] is None
    assert region['unknownExerciseIds'] == ['PRESS']


def test_initial_policy_has_no_bonus_for_filling_volume_or_exercise_counts():
    from workout_generator_pkg.programming_policy import goal_programming_costs

    requirements = initial_requirements()
    costs = {goal['metric']: 0 for tier in requirements['objectiveTiers'] for goal in tier}
    # Actual within-range totals must not introduce an unapproved aspiration.
    lower = goal_programming_costs(requirements,
        {**costs, 'weekly_effective_sets:chest': -10}, {'lateral_delt': 4, 'vertical_pull': 4})
    upper = goal_programming_costs(requirements,
        {**costs, 'weekly_effective_sets:chest': -15}, {'lateral_delt': 4, 'vertical_pull': 4})
    assert lower == upper == {'goal_tier_0_worst': 0, 'goal_tier_0_total': 0,
        'goal_tier_1_worst': 0, 'goal_tier_1_total': 0}
    press = {'id': 'PRESS', 'exerciseType': 'WEIGHT', 'muscleGroups': ['FRONT_CHEST'],
        'secondaryMuscleGroups': ['BACK_TRICEPS']}
    one = exercise_count_preference_facts([press], requirements)['chest']
    assert one['shortfall'] == one['excess'] == 0
    four = exercise_count_preference_facts(
        [{**press, 'id': str(index)} for index in range(4)], requirements)['chest']
    assert four['shortfall'] == 0 and four['excess'] == 1


def test_order_categories_and_protection_are_explicit_and_independently_ranked():
    requirements = initial_requirements()
    requirements['orderingPreferences']['phaseOrder'] = [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]
    roles, keys = [set()] * 3, [(0, 'heavy'), (1, 'moderate'), (2, 'isolation')]
    assert execution_order_is_admissible([0, 1, 2], roles, keys, requirements)
    assert not execution_order_is_admissible([1, 0, 2], roles, keys, requirements)
    assert not execution_order_is_admissible([2, 1, 0], roles, keys, requirements)
    assert execution_order_is_admissible([2, 1, 0], roles, keys, {})
    profile = {'primary': {'chest': 2}, 'supporting': {}, 'priority': False,
        'heavy_primary': ['chest'], 'heavy_supporting': [], 'main_compound': True,
        'main_primary': ['chest'], 'main_supporting': []}
    requirements['orderingPreferences']['protectionOrder'] = ['heavy_direct', 'main_direct']
    assert execution_interference_score([0, 1], [profile, profile], requirements) == (2, 2, 2, 2)
    assert execution_interference_score([0, 1], [profile, profile], {}) == ()


def test_policy_rejects_conflicting_preference_fields_without_relaxing_hard_limits():
    requirements = initial_requirements()
    requirements['preferredSessionSeconds'] = 5500
    requirements['exerciseSelection']['preferredMinimum'] = 4
    requirements['orderingPreferences']['phaseOrder'][1].append('CORE')
    errors = programming_policy_errors(requirements)
    assert {error['path'] for error in errors} == {
        '/preferredSessionSeconds', '/exerciseSelection', '/orderingPreferences/phaseOrder'}
    assert requirements['auditTargets']['maximumSessionSeconds'] == 5400


def test_public_menu_repair_only_selects_code_candidate_or_none():
    from test_workout_generator_menu_selection import menu_case
    draft, task = menu_case()
    task['solverMenu'] = {'feasible': True, 'sessions': []}
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert set(schema['properties']) == {'requirementsId', 'baseDraftId', 'useSolverMenu'}
    submission = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'useSolverMenu': False}
    validate(submission, schema)
    original = copy.deepcopy(draft)
    with pytest.raises(PlanningInputError) as caught:
        compile_coordinated_repair(submission, task, draft)
    assert caught.value.code == 'solver_menu_declined'
    assert draft == original


def assess_tradeoff(before, after, *, requirements=None, baseline=None, candidate=None,
                    same_selected_work=True):
    requirements = requirements or {'objectiveOrder': ['duration_economy', 'setup_economy']}
    before = {'setup_economy_transitions': 0, **before}
    after = {'setup_economy_transitions': 0, **after}
    return assess_audited_programming_tradeoff(
        baseline if baseline is not None else {'audit': {'errors': []}},
        candidate if candidate is not None else {'audit': {'errors': []}},
        requirements=requirements, baseline_costs=before, candidate_costs=after,
        objective_names=requirements['objectiveOrder'], same_selected_work=same_selected_work)


def test_faster_execution_with_more_physical_inventory_switches_requires_tradeoff():
    before = {'duration_economy': 9294, 'setup_economy': 27, 'setup_economy_resource_switches': 19}
    after = {**before, 'duration_economy': 9264, 'setup_economy_resource_switches': 21}
    result = assess_tradeoff(before, after)
    assert result['status'] == 'requires_programming_decision'
    assert result['improved'] == [{'objective': 'duration_economy', 'baseline': 9294, 'candidate': 9264}]
    assert result['worsened'] == [{'objective': 'setup_economy_resource_switches', 'baseline': 19, 'candidate': 21}]


@pytest.mark.parametrize('candidate_dose,arrangement_cost,status', [
    (10, .2, 'candidate_dominates'), (10, None, 'candidate_dominates'),
    (12, .2, 'baseline_dominates'), (12, None, 'unknown')])
def test_arrangement_tradeoff_only_compares_matching_weekly_doses(candidate_dose, arrangement_cost, status):
    requirements = {'objectiveOrder': ['workload_economy', 'relative_distribution'],
        'requiredCoverage': [{'key': 'upper_push', 'intent': 'inclusion'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'preferredMinimum': 10, 'preferredMaximum': 15}}}}
    def plan(dose):
        return {'workouts': [{'timesCompletedInAWeek': 1}] * 3, 'audit': {'errors': [],
            'weeklyVolume': {'chest': {'effective': dose}}, 'weeklyCoverageSets': {'upper_push': dose}}}
    result = assess_tradeoff({'workload_economy': 12, 'relative_distribution': .1},
        {'workload_economy': candidate_dose, 'relative_distribution': arrangement_cost},
        requirements=requirements, baseline=plan(12), candidate=plan(candidate_dose))
    assert result['status'] == status
    if candidate_dose != 12:
        assert not result['unknownObjectives']
        assert result['inapplicableObjectives'] == [{'objective': 'relative_distribution',
            'baseline': .1, 'candidate': arrangement_cost,
            'reason': 'weekly_training_doses_differ'}]
        assert all(row['objective'] != 'relative_distribution' for relation in ('improved', 'worsened', 'unchanged')
            for row in result[relation])
    else:
        assert 'inapplicableObjectives' not in result
    unknown_dose = plan(12)
    unknown_dose['audit']['weeklyCoverageSets'] = {}
    unknown = assess_tradeoff({'workload_economy': 12, 'relative_distribution': .1},
        {'workload_economy': 12, 'relative_distribution': .2},
        requirements=requirements, baseline=plan(12), candidate=unknown_dose)
    assert unknown['status'] == 'unknown'
    assert unknown['unknownObjectives'] == ['relative_distribution']
    assert 'inapplicableObjectives' not in unknown


@pytest.mark.parametrize('seconds,status', [(100, 'baseline_preferred'), (200, 'candidate_preferred')])
def test_explicit_shared_goal_ranking_precedes_overlap_volume_tradeoff(seconds, status):
    from workout_generator_pkg.programming_policy import goal_programming_costs

    requirements = {'objectiveOrder': ['volume_target', 'movement_overlap', 'time_budget'],
        'objectiveTiers': [[{'metric': 'movement_overlap', 'target': 0, 'scale': 2},
            {'metric': 'time_budget', 'target': 0, 'scale': 100}]],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {
            'minimum': 0, 'maximum': None, 'preferredMinimum': 10, 'preferredMaximum': 15}}}}
    before = {'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 12}}}}
    after = {'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 10}}}}
    left = {'volume_target': 0, 'movement_overlap': 2, 'time_budget': seconds}
    right = {'volume_target': 0, 'movement_overlap': 1, 'time_budget': 150}
    result = assess_tradeoff({**left, **goal_programming_costs(requirements, left, {})},
        {**right, **goal_programming_costs(requirements, right, {})},
        requirements=requirements, baseline=before, candidate=after)
    assert result['status'] == status
    assert result['volumeChanges'][0]['baselineEffectiveSets'] == 12
    assert result['volumeChanges'][0]['candidateEffectiveSets'] == 10


@pytest.mark.parametrize('seconds,status', [(90, 'candidate_dominates'), (110, 'baseline_dominates'),
    (100, 'equivalent')])
def test_complete_pareto_comparison_does_not_invent_exchange_rates(seconds, status):
    before = {'duration_economy': 100, 'setup_economy': 2, 'setup_economy_resource_switches': 1}
    result = assess_tradeoff(before, {**before, 'duration_economy': seconds})
    assert result['status'] == status
    assert not result['unknownObjectives']


def test_preference_resolution_is_preserved_only_when_explicitly_supplied():
    assert 'preferenceResolution' not in normalize_programming_policy({})
    assert normalize_programming_policy({'preferenceResolution': 'explicit_tradeoffs'}) == {
        'preferenceResolution': 'explicit_tradeoffs'}


@pytest.mark.parametrize('unknown', [None, float('nan'), float('inf'), True])
def test_missing_or_invalid_setup_evidence_is_unknown_not_zero(unknown):
    before = {'duration_economy': 100, 'setup_economy': 2, 'setup_economy_resource_switches': 1}
    after = {**before, 'duration_economy': 90, 'setup_economy': unknown}
    result = assess_tradeoff(before, after)
    assert result['status'] == 'unknown'
    assert result['unknownObjectives'] == ['setup_economy']
    assert not result['worsened']


def test_development_quantity_change_is_a_choice_not_a_bonus_or_adequacy_claim():
    requirements = {'objectiveOrder': ['volume_target'],
        'requiredCoverage': [{'key': 'lateral_delt', 'intent': 'development'}]}
    baseline = {'audit': {'errors': [], 'weeklyCoverageSets': {'lateral_delt': 2}}}
    candidate = {'audit': {'errors': [], 'weeklyCoverageSets': {'lateral_delt': 3}}}
    result = assess_tradeoff({'volume_target': 0}, {'volume_target': 1},
        requirements=requirements, baseline=baseline, candidate=candidate)
    assert result['status'] == 'requires_programming_decision'
    assert result['developmentChanges'] == [{'role': 'lateral_delt',
        'baselineWorkingSets': 2, 'candidateWorkingSets': 3}]
    assert not result['improved']
    candidate['audit']['weeklyCoverageSets'] = {}
    missing = assess_tradeoff({'volume_target': 0}, {'volume_target': 0},
        requirements=requirements, baseline=baseline, candidate=candidate)
    assert missing['status'] == 'unknown'
    assert missing['unknownObjectives'] == ['development_role:lateral_delt']


def test_sequence_scores_are_compared_only_for_the_same_selected_work():
    requirements = {'objectiveOrder': ['duration_economy', 'execution_order'],
        'orderingPreferences': {'protectionOrder': ['adjacent_direct']}}
    before = {'duration_economy': 100, 'ordering_adjacent_direct': 0, 'development_exposure': -2}
    after = {'duration_economy': 90, 'ordering_adjacent_direct': 2, 'development_exposure': -8}
    assert assess_tradeoff(before, after, requirements=requirements,
        same_selected_work=False)['status'] == 'candidate_dominates'
    same = assess_tradeoff(before, after, requirements=requirements)
    assert same['status'] == 'requires_programming_decision'
    assert same['worsened'][0]['objective'] == 'ordering_adjacent_direct'
    assert all(row['objective'] != 'development_exposure'
        for key in ('improved', 'worsened', 'unchanged') for row in same[key])


def test_native_hard_violation_and_missing_audit_cannot_be_promoted_by_soft_scores():
    requirements = {'objectiveOrder': ['duration_economy']}
    result = assess_tradeoff({'duration_economy': 100}, {'duration_economy': 50},
        requirements=requirements, candidate={'audit': {'errors': [{'code': 'execution_rest'}]}})
    assert result['status'] == 'hard_violation'
    assert result['hardErrors']['candidate'] == [{'code': 'execution_rest'}]
    missing = assess_tradeoff({'duration_economy': 100}, {'duration_economy': 50},
        requirements=requirements, candidate={})
    assert missing['status'] == 'unknown' and 'native_audit:candidate' in missing['unknownObjectives']


def test_missing_primary_inventory_prevents_switch_comparison():
    before = {'duration_economy': 100, 'setup_economy': 2, 'setup_economy_resource_switches': 1}
    result = assess_tradeoff(before, {**before, 'setup_economy_resource_switches': None})
    assert result['status'] == 'unknown'
    assert result['unknownObjectives'] == ['setup_economy_resource_switches']
