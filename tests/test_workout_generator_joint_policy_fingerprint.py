import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_workout_generator_joint_prescriptions import two_recipe_order_case
from workout_generator_pkg import joint_planning


@pytest.mark.parametrize('policy_key', ['candidateOrdering', 'exerciseDistribution'])
def test_joint_fingerprints_include_code_owned_policy_descriptor(monkeypatch, policy_key):
    equipment, requirements, sessions = two_recipe_order_case()
    problem_before = joint_planning.joint_problem_fingerprint(sessions, requirements, equipment)
    objective_before = joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment)

    changed_policy = copy.deepcopy(joint_planning.JOINT_POLICY_DESCRIPTOR)
    changed_policy[policy_key] = 'different_policy_for_test'
    monkeypatch.setattr(joint_planning, 'JOINT_POLICY_DESCRIPTOR', changed_policy)

    assert joint_planning.joint_problem_fingerprint(sessions, requirements, equipment) != problem_before
    assert joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment) != objective_before


def test_joint_fingerprints_include_code_owned_source_working_set_budget():
    equipment, requirements, sessions = two_recipe_order_case()
    first = {'source': 'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
             'variableWeeklyWorkingSets': 6, 'preparationId': 'PREP_1'}
    changed = {**first, 'variableWeeklyWorkingSets': 8}

    assert joint_planning.joint_problem_fingerprint(sessions, requirements, equipment,
        source_working_set_budget=first) != joint_planning.joint_problem_fingerprint(
            sessions, requirements, equipment, source_working_set_budget=changed)
    assert joint_planning.joint_objective_input_fingerprint(sessions, requirements, equipment,
        source_working_set_budget=first) != joint_planning.joint_objective_input_fingerprint(
            sessions, requirements, equipment, source_working_set_budget=changed)
