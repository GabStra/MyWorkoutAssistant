import copy

from workout_generator_pkg import joint_planning as joint


def test_execution_reuses_native_recipe_preparation_without_changing_full_domain(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'exercise_count', 'execution_order']
    requirements['exerciseSelection'] = {'preferredMinimum': 2, 'preferredMaximum': 3, 'muscles': ['chest']}
    unused_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    unused_definition.update(id='zz-unused', name='Unused Press')
    equipment['exerciseDefinitions'].append(unused_definition)
    unused = copy.deepcopy(sessions[0]['exercises'][0])
    unused['definition_id'] = 'LIBRARY_2'
    sessions[0]['exercises'].append(unused)
    original = copy.deepcopy(sessions)
    preparation = {}
    selection = joint._solve_prescribed_week(sessions, requirements, equipment,
        _selection_only=True, _recipe_preparation=preparation)
    assert selection['feasible'], selection
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    fixed = joint._selected_session_work(selection['sessions'], definitions)
    assert len(fixed[0]) < len(equipment['exerciseDefinitions'])
    audit = joint._audit_raw
    calls = []

    def record(draft, *args, **kwargs):
        calls.append(draft['name'])
        return audit(draft, *args, **kwargs)

    monkeypatch.setattr(joint, '_audit_raw', record)
    arguments = dict(_fixed_session_work=fixed, _prescription_seed=selection['sessions'])
    cold = joint._solve_prescribed_week(sessions, requirements, equipment, **arguments)
    assert 'Recipe' in calls
    calls.clear()
    warm = joint._solve_prescribed_week(sessions, requirements, equipment,
        **arguments, _recipe_preparation=preparation)
    assert 'Recipe' not in calls
    assert calls  # Complete-week warm-start and final production audits still run.
    assert cold['feasible'] and warm['feasible'], (cold, warm)
    for key in ('sessions', 'audit', 'feasibilityDomainFingerprint', 'recipeCount', 'optionCount',
            'exerciseCountEvidence', 'demandDistribution', 'exerciseDistribution'):
        assert warm[key] == cold[key], key
    assert sessions == original


def test_split_rebuilds_execution_only_after_exact_audited_selection(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'duration_economy', 'execution_order']
    requirements['orderingPreferences'] = {'phaseOrder': [], 'protectionOrder': ['main_direct']}
    requirements['objectiveTiers'] = [[{'metric': 'coverage:first', 'target': -10, 'scale': 7}]]
    original = copy.deepcopy(requirements)
    solve = joint._cp_solve
    calls = []
    prefix_rows = []
    selection_receipts = []
    deadlines = []
    preparations = []
    core = joint._solve_prescribed_week

    def capture_selection(*args, **kwargs):
        deadlines.append(kwargs['search_deadline'])
        preparations.append(kwargs['_recipe_preparation'])
        result = core(*args, **kwargs)
        if kwargs.get('_selection_only'):
            selection_receipts.append(result)
        return result

    monkeypatch.setattr(joint, '_solve_prescribed_week', capture_selection)

    def record(variables, features, **kwargs):
        calls.append({(item.get('domainIdentity') or {}).get('kind') for item in variables})
        prefix_rows.extend(row for row in features if row[0][0] == 'selection_prefix_bound')
        return solve(variables, features, **kwargs)

    monkeypatch.setattr(joint, '_cp_solve', record)
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    selection = selection_receipts[0]
    assert selection['feasible'] and not selection['audit']['errors']
    assert not result['audit']['errors']
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    assert joint._selected_session_work(result['sessions'], definitions) == result['splitArchitecture']['selectedSessionWork']
    assert requirements == original
    first_execution = next(index for index, kinds in enumerate(calls) if 'execution_arc' in kinds)
    assert first_execution > 0
    assert all(not {'execution_arc', 'execution_before', 'execution_gated_count'} & kinds
        for kinds in calls[:first_execution])
    assert all(stage['goal'] != 'ordering_main_direct' for stage in selection['objectiveProgress'])
    assert any(stage['goal'] == 'ordering_main_direct' for stage in result['objectiveProgress'])
    assert result['audit']['workouts'][0]['estimatedSeconds'] == selection['audit']['workouts'][0]['estimatedSeconds']
    assert result['priorityExecution']['goalPolicy']['tiers'] == original['objectiveTiers']
    assert result['status'] == 'feasible'
    assert set(result['splitArchitecture']['selection']) == {'status', 'elapsedSeconds', 'scope'}
    assert '_selectionPrefixBounds' not in result
    assert 0 < deadlines[1] - deadlines[0] <= 30
    assert preparations[0] is preparations[1] and preparations[0]['recipes']
    assert prefix_rows and all(type(row[2]) is int and all(type(value) is int
        for value in row[4].values()) for row in prefix_rows)


def test_split_preserves_explicit_order_cycle_and_legacy_interleaved_policy():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'execution_order']
    requirements['executionRules'] = [
        {'kind': 'order', 'before': 'first', 'after': 'second'},
        {'kind': 'order', 'before': 'second', 'after': 'first'},
    ]
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'] and result['status'] == 'infeasible', result
    requirements['objectiveOrder'].append('duration_economy')
    requirements['executionRules'] = []
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert 'splitArchitecture' not in result


def test_split_retains_selection_feasible_proof_when_execution_is_optimal(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'exercise_count', 'execution_order']
    requirements['exerciseSelection'] = {'preferredMinimum': 2, 'preferredMaximum': 3, 'muscles': ['chest']}
    requirements['orderingPreferences'] = {'phaseOrder': [], 'protectionOrder': ['main_direct']}
    core = joint._solve_prescribed_week

    def bounded_selection(*args, **kwargs):
        result = core(*args, **kwargs)
        if kwargs.get('_selection_only'):
            result['status'] = 'feasible'
            for stage in result['objectiveProgress']:
                if stage['goal'] == 'exercise_count':
                    stage['status'] = 'feasible'
        return result

    monkeypatch.setattr(joint, '_solve_prescribed_week', bounded_selection)
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    count_stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'exercise_count')
    assert count_stage['status'] == 'feasible'
    assert count_stage['scope'] == 'full_recipe_menu_selection_prefix_before_fixed_work_execution'
    count_priority = next(item for item in result['priorityExecution']['approvedPriorities']
        if item['priority'] == 'exercise_count')
    assert count_priority['status'] == 'feasible'
    assert result['status'] == result['jointModelStatus'] == 'feasible'
    execution = next(item for item in result['priorityExecution']['approvedPriorities']
        if item['priority'] == 'execution_order')
    assert execution['scope'] == 'fixed_per_session_definition_counts_and_attained_selection_prefix'


def test_split_retains_audited_selection_when_execution_times_out(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'execution_order']
    core = joint._solve_prescribed_week
    attempts = []

    def execution_timeout(*args, **kwargs):
        attempts.append(kwargs.get('_selection_only', False))
        if kwargs.get('_fixed_session_work') is not None:
            return {'feasible': False, 'status': 'unproven', 'instruction': 'Bounded execution search stopped.',
                'solverDiagnostics': [{'goal': 'feasibility', 'status': 'unknown'}]}
        return core(*args, **kwargs)

    monkeypatch.setattr(joint, '_solve_prescribed_week', execution_timeout)
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert attempts == [True, False]
    assert result['feasible'] and result['status'] == 'feasible'
    assert not result['audit']['errors'] and result['sessions']
    assert result['splitArchitecture']['execution']['status'] == 'unproven'
    execution = next(item for item in result['priorityExecution']['approvedPriorities']
        if item['priority'] == 'execution_order')
    assert execution['status'] == 'not_run_after_solver_stop'
    assert result['solverDiagnostics'][-1]['status'] == 'unknown'
    assert '_selectionPrefixBounds' not in result


def test_split_does_not_freeze_unattempted_objectives_after_selection_budget(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'duration_economy', 'execution_order']
    requirements['orderingPreferences'] = {'phaseOrder': [], 'protectionOrder': ['main_direct']}
    requirements['objectiveTiers'] = [[{'metric': 'coverage:first', 'target': -10, 'scale': 7}]]
    clock = [0]
    monkeypatch.setattr(joint.time, 'monotonic', lambda: clock[0])
    solve, core = joint._cp_solve, joint._solve_prescribed_week
    prefix_bounds, deadlines = [], []

    def capture_core(*args, **kwargs):
        deadlines.append(kwargs['search_deadline'])
        if kwargs.get('_fixed_session_work') is not None:
            prefix_bounds.append(kwargs['_selection_prefix_bounds'])
        return core(*args, **kwargs)

    def exhaust_selection(*args, **kwargs):
        status, candidate = solve(*args, **kwargs)
        if clock[0] == 0:
            clock[0] = deadlines[0]
            return ('feasible' if candidate is not None else status), candidate
        return status, candidate

    monkeypatch.setattr(joint, '_solve_prescribed_week', capture_core)
    monkeypatch.setattr(joint, '_cp_solve', exhaust_selection)
    result = joint.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, search_deadline=120)
    assert deadlines == [75, 100]
    assert result['feasible'] and not result['audit']['errors']
    assert set(prefix_bounds[0]) == {'goal_tier_0_worst'}
    assert any(stage['goal'] == 'goal_tier_0_total' for stage in result['objectiveProgress'])
