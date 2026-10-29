import pytest

from workout_generator_pkg.user_interaction import preference_comparison_priorities


def test_priority_comparison_uses_approved_order_without_semantic_accounting():
    requirements = {'objectiveOrder': ['demand_distribution', 'duration_balance']}
    audit = {'coordinatedJointPlanning': {'priorityExecution': {'approvedPriorities': [
        {'priority': 'demand_distribution', 'status': 'unavailable_evidence'},
        {'priority': 'duration_balance', 'status': 'optimal'},
    ]}}}
    selected = preference_comparison_priorities(
        audit, requirements, ['duration_balance', 'demand_distribution'])
    assert [row['priority'] for row in selected] == requirements['objectiveOrder']
    assert selected[0]['execution']['status'] == 'unavailable_evidence'
    assert selected[1]['execution']['status'] == 'optimal'
    assert all(row['basis'] == 'requested_comparison' for row in selected)
    selected[0]['execution']['status'] = 'changed'
    assert audit['coordinatedJointPlanning']['priorityExecution']['approvedPriorities'][0]['status'] == 'unavailable_evidence'


@pytest.mark.parametrize('selection', [[], ['duration_balance', 'duration_balance'],
    ['invented_priority'], ['demand_distribution'], 'duration_balance'])
def test_priority_comparison_rejects_missing_or_unapproved_evidence(selection):
    requirements = {'objectiveOrder': ['duration_balance', 'demand_distribution']}
    audit = {'automaticAllocation': {'priorityExecution': {'approvedPriorities': [
        {'priority': 'duration_balance', 'status': 'feasible'},
    ]}}}
    with pytest.raises(ValueError):
        preference_comparison_priorities(audit, requirements, selection)
