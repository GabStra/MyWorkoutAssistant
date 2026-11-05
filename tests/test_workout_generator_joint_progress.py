from workout_generator_pkg import joint_planning
from test_workout_generator_joint_prescriptions import two_recipe_order_case


def test_joint_progress_preserves_stage_evidence_without_claiming_export_readiness(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'duration_balance', 'duration_economy']
    events = []
    original = joint_planning._cp_solve
    calls = []

    def feasible_first(*args, **kwargs):
        status, candidate = original(*args, **kwargs)
        calls.append(status)
        return ('feasible' if len(calls) == 1 and candidate is not None else status), candidate

    monkeypatch.setattr(joint_planning, '_cp_solve', feasible_first)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, progress=events.append)
    assert result['feasible'] and not result['audit']['errors']
    assert events[0]['phase'] == 'stage_started'
    assert events[0]['jointModelFeasibleIncumbentAvailable'] is False
    assert events[-1]['phase'] == 'stage_completed'
    assert events[-1]['jointModelFeasibleIncumbentAvailable'] is True
    assert events[-1]['objectiveProgress'] == result['objectiveProgress']
    assert events[-1]['solverDiagnostics'] == result['solverDiagnostics']
    assert events[0]['objectiveProgress'] == []
    assert all(event['feasible'] is False and event['productionAuditPending'] is True
        and event['problemFingerprint'] == result['problemFingerprint']
        and 'sessions' not in event for event in events)
    assert result['objectiveProgress'][0]['status'] == 'feasible'
    assert result['objectiveProgress'][-1]['goal'] == 'duration_economy'
    later_proofs = [stage for stage in result['objectiveProgress'][1:]
        if stage.get('conditionalOptimal')]
    assert later_proofs and all(stage['status'] == 'feasible'
        and not stage['retainedObjectiveBound']['provenOptimal'] for stage in later_proofs)


def test_shared_deadline_reserves_later_objectives_after_finding_an_incumbent(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'duration_economy', 'execution_order']
    requirements['orderingPreferences'] = {'phaseOrder': [], 'protectionOrder': ['main_direct']}
    requirements['objectiveTiers'] = [[{'metric': 'coverage:first', 'target': -20, 'scale': 10}]]
    clock = [0]
    monkeypatch.setattr(joint_planning.time, 'monotonic', lambda: clock[0])
    original = joint_planning._cp_solve
    budgets = []

    def exhaust_budget(*args, **kwargs):
        budgets.append(kwargs['timeout_seconds'])
        status, candidate = original(*args, **kwargs)
        clock[0] += kwargs['timeout_seconds']
        return ('feasible' if candidate is not None else status), candidate

    monkeypatch.setattr(joint_planning, '_cp_solve', exhaust_budget)
    result = joint_planning._solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, search_deadline=25)
    goals = [stage['goal'] for stage in result['objectiveProgress']]
    assert goals == ['goal_tier_0_worst', 'goal_tier_0_total',
        'workload_economy', 'duration_economy', 'ordering_main_direct']
    assert len(budgets) > 2 and sum(budgets) <= 25
    assert budgets[1] < 25 - budgets[0]
    assert result['feasible'] and result['status'] == 'feasible' and not result['audit']['errors']
    assert all(stage['retainedObjectiveBound']['provenOptimal'] is False
        for stage in result['objectiveProgress'])


def test_expired_shared_deadline_is_unproven_without_starting_search(monkeypatch):
    equipment, requirements, sessions = two_recipe_order_case()

    def unexpected_search(*args, **kwargs):
        raise AssertionError('An expired solve must not start another search.')

    monkeypatch.setattr(joint_planning, '_cp_solve', unexpected_search)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, search_deadline=joint_planning.time.monotonic() - 1)
    assert not result['feasible'] and result['status'] == 'unproven'
    assert result['searchBudget']['exhausted']
    assert result['solverDiagnostics'][-1]['returnReason'] == 'search_budget_exhausted'
