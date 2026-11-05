import copy

import pytest

from workout_generator_pkg import allocation, joint_planning
from test_workout_generator_planning_tools import planning_case


def preference_case():
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets'] = {
        'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': None,
            'preferredMinimum': 10, 'preferredMaximum': 15}},
        'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 5400}
    requirements['objectiveOrder'] = ['volume_target', 'workload_economy']
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 20}]
    draft['workouts'][0]['exercises'][0].pop('placementNotes', None)
    return equipment, requirements, draft['workouts']


@pytest.mark.parametrize('preferred, expected', [(True, 10), (False, 2)])
def test_joint_volume_preference_runs_only_when_ranked_and_precedes_workload(preferred, expected):
    equipment, requirements, sessions = preference_case()
    if not preferred:
        requirements['objectiveOrder'].remove('volume_target')
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'], result
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == expected
    if preferred:
        priority = next(item for item in result['priorityExecution']['approvedPriorities']
            if item['priority'] == 'volume_target')
        assert priority['owner'] == 'joint_solver'
        assert priority['solverStage']['value'] == 0


def test_joint_volume_preference_yields_to_hard_cap_and_matches_audited_comparison():
    equipment, requirements, sessions = preference_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 1300
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'], result
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == 8
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'volume_target')
    assert stage['value'] == 2
    _, audit = allocation._audit_raw({'name': 'Test', 'workouts': result['sessions']}, equipment, requirements, None, True)
    candidate = {'workouts': result['sessions'], 'audit': audit}
    assert joint_planning._joint_candidate_objective_costs(candidate, requirements, {})['volume_target'] == 2


def test_joint_volume_preference_counts_fixed_workouts_frequency_and_session_shortfall():
    equipment, requirements, sessions = preference_case()
    fixed = copy.deepcopy(sessions[0])
    fixed['timesCompletedInAWeek'] = 2
    fixed['exercises'][0]['numWorkSets'] = 3
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {
        'minimum': 0, 'maximum': None, 'preferredMinimum': 6, 'preferredMaximum': 8}
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        existing={'name': 'Test', 'workouts': [fixed]}, preserve_source_selection=True)
    assert result['feasible'], result
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == 6
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'volume_target')
    assert stage['value'] == 3
    _, audit = allocation._audit_raw({'name': 'Test', 'workouts': [fixed] + result['sessions']}, equipment, requirements, None, True)
    candidate = {'workouts': [fixed] + result['sessions'], 'audit': audit}
    assert audit['weeklyVolume']['chest']['effective'] == 12
    assert joint_planning._joint_candidate_objective_costs(candidate, requirements,
        {'fixedWorkouts': [fixed]})['volume_target'] == stage['value']


def test_prepared_selection_prefers_numeric_band_without_hard_floor():
    _, requirements, _ = preference_case()
    sessions = [{'name': 'Day A', 'timesCompletedInAWeek': 2, 'exercises': [{
        'definition_id': 'press', 'numWorkSets': 2, 'allocationBounds': {'minimum': 2, 'maximum': 8},
        'superset': None, 'satisfiesCoverage': []}]}]
    candidates = {'press': {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}}
    result = allocation.allocate_prepared_sets(sessions, candidates, requirements, select_movements=True)
    assert result['feasible'], result
    count = result['sessions'][0]['exercises'][0]['numWorkSets']
    assert 10 <= 2 * count <= 15
    objective = result['selectionPreview']['objectives'][0]
    assert objective['priority'] == 'volume_target'
    assert objective['baselineCost'] == 6
    assert objective['proposalCost'] == 0


def test_audited_comparator_prefers_band_before_fewer_sets_and_reports_excess():
    from test_workout_generator_joint_candidate_comparison import _candidate, _context

    targets = {'weeklyEffectiveSets': {'CHEST': {'minimum': 0, 'maximum': None,
        'preferredMinimum': 6, 'preferredMaximum': 8}}}
    requirements = {'auditTargets': targets, 'requiredCoverage': [], 'executionRules': [],
        'objectiveOrder': ['volume_target', 'workload_economy']}
    baseline, candidate = _candidate([2]), _candidate([6])
    for item in (baseline, candidate):
        item['audit']['targets'] = copy.deepcopy(targets)
    result = joint_planning.compare_audited_joint_candidates(baseline, candidate,
        requirements=requirements, context=_context())
    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'volume_target'
    assert result['objectiveCosts']['baseline']['volume_target'] == 4
    assert result['objectiveCosts']['candidate']['volume_target'] == 0
    excess = _candidate([10])
    excess['audit']['targets'] = copy.deepcopy(targets)
    assert joint_planning._joint_candidate_objective_costs(excess, requirements, {})['volume_target'] == 2


def test_automatic_allocation_runs_for_soft_volume_goal_without_hard_failure(monkeypatch):
    from test_workout_generator_allocation import _audited_messages
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Barbell', 'type': 'BARBELL',
        'barWeight': 20, 'sleeveLength': 100, 'availablePlates': []}]
    equipment['exerciseDefinitions'][0].update(exerciseType='WEIGHT', equipmentId='EQUIPMENT_0',
        bodyWeightPercentage=None)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'].update(
        minimum=0, maximum=None, preferredMinimum=10, preferredMaximum=15)
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['objectiveOrder'] = ['volume_target']
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Prefer 10-15 weekly chest sets, within the session time limit.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages, result = _audited_messages(equipment, stored, draft)
    assert result['passed'], result.get('errors')
    calls = []

    def no_candidate(*args, **kwargs):
        calls.append(kwargs)
        return {'feasible': False, 'status': 'unproven', 'instruction': 'No test candidate.'}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', no_candidate)
    allocation.auto_allocate_workout(result, equipment, messages)
    assert len(calls) == 1


def test_unknown_regional_preference_stays_unavailable_in_solver_and_comparator():
    from test_workout_generator_joint_candidate_comparison import _context

    equipment, requirements, sessions = preference_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'pectoralis_clavicular': {'minimum': 0, 'maximum': None,
            'preferredMinimum': 10, 'preferredMaximum': 15}}
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert result['feasible'], result
    assert result['status'] == 'feasible'
    assert result['volumeTargetEvidence']['status'] == 'unavailable_evidence'
    priority = next(item for item in result['priorityExecution']['approvedPriorities']
        if item['priority'] == 'volume_target')
    assert priority['status'] == 'unavailable_evidence' and priority['solverStage'] is None
    _, audit = allocation._audit_raw({'name': 'Test', 'workouts': result['sessions']},
        equipment, requirements, None, True)
    assert audit['weeklyVolume']['pectoralis_clavicular']['effective'] == 0
    assert audit['volumePreferenceEvidence']['weekly'][0]['actual'] is None
    candidate = {'workouts': result['sessions'], 'audit': audit}
    assert joint_planning._joint_candidate_objective_costs(candidate, requirements, {})['volume_target'] is None
    # The other approved objective must not win a comparison by treating unknown credit as zero.
    candidate['searchStatus'] = 'selected_joint_week'
    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_0': []}
    context['exerciseFamilyEvidence'] = {'familyByReference': {'LIBRARY_0': 'FAMILY_0'}}
    compared = joint_planning.compare_audited_joint_candidates(candidate, copy.deepcopy(candidate),
        requirements=requirements, context=context)
    assert compared['decision'] == 'incomparable'
    assert compared['reason'] == 'objective_evidence_unavailable:volume_target'
    prepared = allocation.allocate_prepared_sets(sessions, {'LIBRARY_0': {
        'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}},
        'regionalMuscleFacts': {'pectoralis_clavicular': {'status': 'unknown'}}}},
        requirements, select_movements=True)
    assert prepared['feasible'], prepared
    assert prepared['selectionPreview']['objectiveStatus'] == 'unavailable_evidence'
    assert prepared['selectionPreview']['objectives'][0]['status'] == 'unavailable_evidence'
