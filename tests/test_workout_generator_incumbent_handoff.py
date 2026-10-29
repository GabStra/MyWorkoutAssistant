import copy

import pytest

from workout_generator_pkg import allocation, joint_planning


def _variables():
    return [{'lower': 0, 'upper': 10, 'minimumWhenSelected': 2,
        'current': [3], 'members': [{}], 'objectiveCost': 1}]


def test_validated_incumbent_reaches_highs_with_required_auxiliary_values(monkeypatch):
    original = allocation._milp_with_incumbent
    starts = []
    def capture(objective, integrality, bounds, constraints, options, initial_values):
        starts.append(initial_values)
        return original(objective, integrality, bounds, constraints, options, initial_values)
    monkeypatch.setattr(allocation, '_milp_with_incumbent', capture)
    diagnostic = {}
    status, result = allocation._milp_solve(_variables(), [(('floor',), 2, 10, 0, {0: 1})],
        incumbent=[5], preserve_current=False, diagnostics=diagnostic)
    assert starts == [[5, 2, 1]]  # Primary count, absolute deviation, activation.
    assert status == 'optimal' and result == [2]
    assert diagnostic['incumbentSupplied'] and diagnostic['incumbentValidated']
    assert diagnostic['backend'] == 'highspy'


@pytest.mark.parametrize('incumbent', [[], [1], [11], [2.5], [float('nan')]])
def test_incumbent_cannot_bypass_current_domain_or_objective_lock(monkeypatch, incumbent):
    monkeypatch.setattr(allocation, '_milp_with_incumbent',
        lambda *args: pytest.fail('Invalid start reached the solver'))
    with pytest.raises(ValueError, match='incumbent'):
        allocation._milp_solve(_variables(), [(('objective_lock',), 3, 10, 0, {0: 1})],
            incumbent=incumbent, preserve_current=False)


def test_joint_stage_passes_previous_candidate_and_preserves_exact_audit(monkeypatch):
    from test_workout_generator_joint_prescriptions import _distribution_solver_case
    equipment, requirements, sessions, _ = _distribution_solver_case([4])
    sessions[0]['exercises'][0].update(numWorkSets=5, workSetTemplate={'reps': 8})
    sessions[0]['exercises'][0].pop('targetSetPrescriptions')
    original = joint_planning._milp_solve
    calls = []
    def capture(variables, features, **options):
        if calls:
            assert options['incumbent'] == calls[-1]
        result = original(variables, features, **options)
        calls.append(result[1])
        return result
    monkeypatch.setattr(joint_planning, '_milp_solve', capture)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True)
    assert len(calls) >= 2
    assert result['feasible'] and not result['audit']['errors']
    assert result['solverDiagnostics'][1]['incumbentSupplied']


def test_joint_receipt_reuse_uses_numeric_fingerprint_across_requirements_id_refresh():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.joint_planning import joint_objective_input_fingerprint
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, stored, draft = planning_case()
    sessions = draft['workouts']
    budget = joint_planning._source_working_set_budget_identity(sessions, None)
    receipt = {'feasible': True, 'status': 'optimal',
        'selectionPolicyVersion': joint_planning.SELECTION_POLICY_VERSION,
        'preserveSourceSelection': False,
        'objectivePolicy': ('approved' if requirements.get('objectiveOrder') is not None
                            else 'preserve_candidate_only'),
        'approvedObjectiveOrder': requirements.get('objectiveOrder'),
        'sourceWorkingSetBudget': budget,
        'objectiveInputFingerprint': joint_objective_input_fingerprint(
            sessions, requirements, equipment, source_working_set_budget=budget)}
    owner = {'requirementsId': 'REQUIREMENTS_BEFORE_SOURCE_REFRESH',
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'coordinatedJointPlanning': receipt}

    reusable = allocation.reusable_joint_receipt(owner, stored['requirementsId'], sessions,
        requirements, equipment, [], source_working_set_budget=budget)
    assert reusable == receipt

    changed_bound = copy.deepcopy(requirements)
    changed_bound['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] += 1
    changed_order = copy.deepcopy(requirements)
    changed_order['objectiveOrder'] = ['distribution']
    changed_order_receipt = {**receipt, 'objectivePolicy': 'approved',
        'approvedObjectiveOrder': changed_order['objectiveOrder']}
    changed_order_owner = {**owner, 'coordinatedJointPlanning': changed_order_receipt}
    changed_restrictions = {'excludedDefinitionIds': ['LIBRARY_0']}

    assert allocation.reusable_joint_receipt(owner, stored['requirementsId'], sessions,
        changed_bound, equipment, [], source_working_set_budget=budget) is None
    assert allocation.reusable_joint_receipt(changed_order_owner, stored['requirementsId'], sessions,
        changed_order, equipment, [], source_working_set_budget=budget) is None
    assert allocation.reusable_joint_receipt(owner, stored['requirementsId'], sessions,
        requirements, equipment, [], restriction_policy=changed_restrictions,
        source_working_set_budget=budget) is None
