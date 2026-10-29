import copy
from collections import Counter

from workout_generator_pkg import joint_planning
from test_workout_generator_joint_prescriptions import prescription_case, two_recipe_order_case
from test_workout_generator_joint_candidate_comparison import _candidate, _context, _requirements


def test_economy_precedes_distribution_and_preserves_each_selected_weekly_dose(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    requirements['objectiveOrder'] = ['workload_economy', 'distribution']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 7, 'maximum': 12}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 1, 'maximum': 12}
    requirements['requiredCoverage'] = [
        {'key': 'push', 'scope': 'eachSession', 'description': 'A push in every session'}]
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition.update(id='second', name='Second press')
    equipment['exerciseDefinitions'].append(definition)
    for day in sessions:
        first = day['exercises'][0]
        first['satisfiesCoverage'] = ['push']
        second = copy.deepcopy(first)
        second['definition_id'] = 'LIBRARY_1'
        day['exercises'].append(second)

    captured = []
    original = joint_planning._lock_weekly_recipe_doses

    def lock(features, chosen, options, days, roles):
        doses = Counter()
        for index, day, _, option in options:
            for item in option['items']:
                doses[item['definition_id']] += (chosen[index] * option['count']
                    * days[day]['timesCompletedInAWeek'])
        captured.append(+doses)
        return original(features, chosen, options, days, roles)

    monkeypatch.setattr(joint_planning, '_lock_weekly_recipe_doses', lock)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert not result['audit']['errors']
    assert result['audit']['weeklyWorkingSets'] == 7
    doses = Counter()
    for day in result['sessions']:
        for item in day['exercises']:
            doses[item['definition_id']] += item['numWorkSets'] * day['timesCompletedInAWeek']
    assert captured == [doses]
    economy, distribution = result['objectiveProgress'][:2]
    assert economy['goal'] == 'workload_economy' and economy['value'] == 7
    assert distribution['goal'] == 'distribution' and distribution['weeklyDosesLocked'] is True


def test_economy_counts_each_superset_member_and_training_occurrence():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 2
    requirements['objectiveOrder'] = ['workload_economy']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 20, 'maximum': 24}
    sessions[0].update(timesCompletedInAWeek=2, trainingDays=[0, 3])
    for item in sessions[0]['exercises']:
        item.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterExerciseSeconds=0,
                    restAfterSupersetExerciseSeconds=30)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)

    assert result['feasible'], result
    assert result['audit']['weeklyWorkingSets'] == 20
    assert result['objectiveProgress'][0]['value'] == 20
    assert all(item['numWorkSets'] == 5 for item in result['sessions'][0]['exercises'])
    assert len({item['superset'] for item in result['sessions'][0]['exercises']}) == 1


def test_explicit_cap_is_binding_without_any_development_label():
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy']
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        source_working_set_budget={'source': 'user_approved', 'variableWeeklyWorkingSets': 9})

    assert result['feasible'] is False
    assert result['status'] == 'source_budget_conflict_requires_review'
    assert result['sourceBudgetDiagnostic']['uncappedHardFeasibilityStatus'] in ('optimal', 'feasible')


def test_audited_candidate_comparison_uses_the_same_physical_workload_cost():
    context = _context()
    context['sourceWorkingSetBudget'] = {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}
    result = joint_planning.compare_audited_joint_candidates(
        _candidate([3, 3]), _candidate([2, 2]),
        requirements=_requirements(['duration_balance', 'workload_economy']), context=context)

    assert result['decision'] == 'promote_candidate', result
    assert result['firstDifferingObjective'] == 'workload_economy'
    assert result['comparisons'][-1]['baselineCost'] == 6
    assert result['comparisons'][-1]['candidateCost'] == 4


def test_malformed_explicit_cap_cannot_become_an_unbounded_repair(monkeypatch):
    from workout_generator_pkg import repair_execution

    def unexpected_solve(*args, **kwargs):
        raise AssertionError('A malformed explicit workload limit must not reach the solver')

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', unexpected_solve)
    result, _, _, _ = repair_execution.solve_repair_candidate([], {}, {}, {},
        repair_contract={}, requirements_id='REQ', allow_educated_load_guesses=True,
        training_history=None, messages=[], preserve_source_selection=False,
        redistribution_constraints=[], validated_source_working_set_budget={
            'source': 'user_approved', 'variableWeeklyWorkingSets': None})

    assert result['feasible'] is False
    assert result['errors'][0]['code'] == 'repair_source_budget_unverified'
