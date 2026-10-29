from unittest.mock import patch

from workout_generator_pkg import allocation, repair_execution
from test_workout_generator_development_emphasis import development_case


UNBOUNDED_BUDGET = {'source': 'unbounded_by_user', 'variableWeeklyWorkingSets': None}


def test_prepared_allocation_normalizes_generated_seed_without_enforcing_it():
    sessions = [{'timesCompletedInAWeek': 1, 'exercises': [{
        'definition_id': 'LIBRARY_0', 'numWorkSets': 1, 'superset': None,
        'allocationBounds': {'minimum': 1, 'maximum': 10}}]}]
    candidates = {'LIBRARY_0': {'creditsPerWorkingSet': {'chest': {'direct': 1}}}}
    requirements = {'auditTargets': {'weeklyEffectiveSets': {'chest': {
        'minimum': 5, 'maximum': 6}}}}

    result = allocation.allocate_prepared_sets(sessions, candidates, requirements,
        select_movements=True, source_working_set_budget={
            'source': 'code_preparation_volume_only_seed', 'variableWeeklyWorkingSets': 1,
            'preparationId': 'PREP_SEED'})

    assert result['feasible'] is True
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] >= 5
    assert result['sourceWorkingSetBudget'] == UNBOUNDED_BUDGET


def _repair_inputs():
    equipment, requirements, workouts = development_case(source_counts=(3, 3), target_total=8)
    return equipment, requirements, [workouts[0]]


def test_development_repair_without_user_cap_uses_explicit_unbounded_sentinel():
    equipment, requirements, workouts = _repair_inputs()
    requirements['requiredCoverage'] = [{'key': 'role_a', 'scope': 'weekly',
        'intent': 'development', 'minimumWeeklySets': 2}]
    expected_joint = {'feasible': True, 'sessions': workouts}

    with patch('workout_generator_pkg.repair_execution._repair_source_working_set_budget',
               return_value=None), \
         patch('workout_generator_pkg.repair_execution.current_reviewed_joint_source',
               return_value=None), \
         patch('workout_generator_pkg.joint_planning.solve_prescribed_week',
               return_value=expected_joint) as solve:
        joint, contract, error, errors = repair_execution.solve_repair_candidate(
            workouts, requirements, equipment, {}, repair_contract={}, requirements_id='REQ_1',
            allow_educated_load_guesses=False, training_history=None, messages=[],
            preserve_source_selection=False, redistribution_constraints=[])

    assert joint is expected_joint
    assert contract == {}
    assert error is None
    assert errors == []
    assert solve.call_args.kwargs['source_working_set_budget'] == UNBOUNDED_BUDGET


def test_repair_keeps_unverified_explicit_cap_as_a_hard_stop():
    equipment, requirements, workouts = _repair_inputs()
    requirements['requiredCoverage'] = [{'key': 'role_a', 'scope': 'weekly',
        'intent': 'development', 'minimumWeeklySets': 2}]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'worker_call', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'worker_call', 'content': (
            '{"requirementsId":"REQ_1","proposedSubmission":{"workouts":[]},'
            '"jointPlanning":{"sourceWorkingSetBudget":{"source":"user_approved_cap",'
            '"variableWeeklyWorkingSets":6}}}')},
    ]

    with patch('workout_generator_pkg.repair_execution._repair_source_working_set_budget',
               return_value=None), \
         patch('workout_generator_pkg.joint_planning.solve_prescribed_week') as solve:
        joint, _, _, _ = repair_execution.solve_repair_candidate(
            workouts, requirements, equipment, {}, repair_contract={}, requirements_id='REQ_1',
            allow_educated_load_guesses=False, training_history=None, messages=messages,
            preserve_source_selection=False, redistribution_constraints=[])

    assert joint['status'] == 'unproven'
    assert joint['errors'][0]['code'] == 'repair_source_budget_unverified'
    solve.assert_not_called()


def test_repair_passes_an_explicit_numeric_cap_even_without_preparation_id():
    equipment, requirements, workouts = _repair_inputs()
    cap = {'source': 'user_approved_cap', 'variableWeeklyWorkingSets': 6}
    expected_joint = {'feasible': True, 'sessions': workouts}

    with patch('workout_generator_pkg.repair_execution.current_reviewed_joint_source',
               return_value=None), \
         patch('workout_generator_pkg.joint_planning.solve_prescribed_week',
               return_value=expected_joint) as solve:
        repair_execution.solve_repair_candidate(
            workouts, requirements, equipment, {}, repair_contract={}, requirements_id='REQ_1',
            allow_educated_load_guesses=False, training_history=None, messages=[],
            preserve_source_selection=False, redistribution_constraints=[],
            validated_source_working_set_budget=cap)

    assert solve.call_args.kwargs['source_working_set_budget'] == cap


def test_comparison_context_canonicalizes_unbounded_and_generated_budget_sources():
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, requirements, stored, draft = planning_case()
    requirements = dict(requirements)
    requirements['requiredCoverage'] = []
    messages = requirement_messages(stored)
    workouts = draft['workouts']
    budgets = [None, UNBOUNDED_BUDGET, {
        'source': 'code_preparation_volume_only_seed', 'variableWeeklyWorkingSets': 9,
        'preparationId': 'PREP_OLD'}]
    contexts = [allocation._joint_candidate_comparison_context(
        workouts, workouts, requirements, equipment, messages, None, {}, budget)
        for budget in budgets]
    explicit_cap = {'source': 'user_approved_cap', 'variableWeeklyWorkingSets': 50}
    explicit_context = allocation._joint_candidate_comparison_context(
        workouts, workouts, requirements, equipment, messages, None, {}, explicit_cap)

    assert all(context is not None for context in contexts)
    assert all(context['sourceWorkingSetBudget'] == UNBOUNDED_BUDGET for context in contexts)
    assert explicit_context['sourceWorkingSetBudget'] == explicit_cap
