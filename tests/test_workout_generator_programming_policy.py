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


def test_approved_policy_preserves_soft_time_count_and_volume_authority():
    requirements = initial_requirements()
    validate(requirements, _REQUIREMENTS)
    assert not programming_policy_errors(requirements)
    assert requirements['objectiveOrder'][:3] == ['time_budget', 'volume_target', 'source_balance']
    goals = {goal['metric']: goal for tier in requirements['objectiveTiers'] for goal in tier}
    assert len(requirements['objectiveTiers']) == 1
    assert len(goals) == 30
    expected_scales = {'role_concentration': 6, 'distribution': 180, 'movement_overlap': 2,
        'exercise_count': 5, 'setup_economy': 40, 'duration_balance': 300}
    assert all(goals[metric]['target'] == 0 and goals[metric]['scale'] == scale
        for metric, scale in expected_scales.items())
    assert {goal['group'] for goal in goals.values()} == {'muscle_volume', 'movement_development',
        'selection', 'practical_execution', 'exposure_distribution'}
    assert {'source_balance', 'weekly_effective_sets:chest', 'role_concentration',
        'distribution', 'movement_overlap', 'exercise_count', 'setup_economy'} <= goals.keys()
    assert 'demand_distribution' not in goals
    assert not any(name.startswith('ordering_') for name in goals)
    assert goals['coverage:lateral_delt']['target'] == goals['coverage:vertical_pull']['target'] == -4
    order = requirements['objectiveOrder']
    assert order.index('balance_control') < order.index('workload_economy')
    assert order.index('source_balance') < order.index('duration_economy')
    assert order.index('execution_complementarity') < order.index('exercise_count')
    assert order.index('balance_control') < order.index('exercise_count')
    assert order.index('distribution') < order.index('exercise_count')
    assert order.index('role_concentration') < order.index('movement_overlap') < order.index('execution_order')
    roles = {rule['key']: rule for rule in requirements['requiredCoverage']}
    for key in ('hip_dominant', 'horizontal_push', 'horizontal_pull',
                'vertical_push', 'vertical_pull', 'lateral_delt'):
        assert roles[key]['intent'] == 'development'
        assert 'minimumWeeklySets' not in roles[key] and 'minimumSessions' not in roles[key]
    assert roles['knee_flexion_hamstring']['intent'] == 'inclusion'
    assert roles['calves']['intent'] == 'inclusion'
    assert 'development_emphasis' not in order and 'development_exposure' not in order
    policy = normalize_programming_policy(requirements)
    assert policy['preferredSessionSeconds'] == 4500
    assert policy['auditTargets']['maximumSessionSeconds'] == 5400
    assert all(bounds['minimum'] == 0 and bounds['maximum'] is None
        for bounds in policy['auditTargets']['weeklyEffectiveSets'].values())
    assert all(bounds['preferredMinimum'] == 10 and bounds['preferredMaximum'] == 15
        for bounds in policy['auditTargets']['weeklyEffectiveSets'].values())
    rendered = render_requirements(requirements)
    assert '75 minutes' in rendered and 'soft excess' in rendered
    assert 'Direct or substantial secondary credit qualifies' in rendered
    assert 'group practical_execution' in rendered
    rests = {rule['context']: rule for rule in requirements['executionRules']
        if rule.get('context') in ('supersetTransition', 'supersetRound')}
    assert (rests['supersetTransition']['minimumSeconds'], rests['supersetTransition']['maximumSeconds']) == (0, 0)
    assert (rests['supersetRound']['minimumSeconds'], rests['supersetRound']['maximumSeconds']) == (60, 120)
    assert 'require direct primary-muscle work in every session' not in GUIDELINE_POLICY['goalAuthority']
    assert 'Existing weekly effective-set ranges remain hard bounds' not in GUIDELINE_POLICY['deterministic']


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


def test_order_categories_and_protection_are_explicit_and_independently_ranked():
    requirements = initial_requirements()
    roles, keys = [set()] * 3, [(0, 'heavy'), (1, 'moderate'), (2, 'isolation')]
    assert execution_order_is_admissible([0, 1, 2], roles, keys, requirements)
    assert not execution_order_is_admissible([1, 0, 2], roles, keys, requirements)
    assert not execution_order_is_admissible([2, 1, 0], roles, keys, requirements)
    assert execution_order_is_admissible([2, 1, 0], roles, keys, {})
    profile = {'primary': {'chest': 2}, 'supporting': {}, 'priority': False,
        'heavy_primary': ['chest'], 'heavy_supporting': [], 'main_compound': True,
        'main_primary': ['chest'], 'main_supporting': []}
    requirements['orderingPreferences']['protectionOrder'] = ['heavy_direct', 'main_direct']
    assert execution_interference_score([0, 1], [profile, profile], requirements) == (2, 2)
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
    return assess_audited_programming_tradeoff(
        baseline if baseline is not None else {'audit': {'errors': []}},
        candidate if candidate is not None else {'audit': {'errors': []}},
        requirements=requirements, baseline_costs=before, candidate_costs=after,
        objective_names=requirements['objectiveOrder'], same_selected_work=same_selected_work)


def test_faster_execution_with_more_resource_switches_requires_a_programming_decision():
    before = {'duration_economy': 9294, 'setup_economy': 27, 'setup_economy_resource_switches': 19}
    after = {**before, 'duration_economy': 9264, 'setup_economy_resource_switches': 21}
    result = assess_tradeoff(before, after)
    assert result['status'] == 'requires_programming_decision'
    assert result['improved'] == [{'objective': 'duration_economy', 'baseline': 9294, 'candidate': 9264}]
    assert result['worsened'] == [{'objective': 'setup_economy_resource_switches', 'baseline': 19, 'candidate': 21}]


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
    after = {**before, 'duration_economy': 90, 'setup_economy_resource_switches': unknown}
    result = assess_tradeoff(before, after)
    assert result['status'] == 'unknown'
    assert result['unknownObjectives'] == ['setup_economy_resource_switches']
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
