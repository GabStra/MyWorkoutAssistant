import pytest

from exercise_motion_pkg.controlled_motion import stage_fit_solver_deadline


@pytest.mark.parametrize('stage', ['A', 'B'])
def test_contact_and_policy_stages_keep_their_block_fence(stage):
    assert stage_fit_solver_deadline(
        stage, current_deadline=90., polish_until=119., fit_deadline=120.) == 90.


@pytest.mark.parametrize('polish_until,fit_deadline,expected', [
    (119., 120., 119.),
    (120., 118., 118.),
])
def test_temporal_stage_uses_remaining_time_inside_both_outer_fences(
        polish_until, fit_deadline, expected):
    assert stage_fit_solver_deadline(
        'C', current_deadline=90., polish_until=polish_until,
        fit_deadline=fit_deadline) == expected
