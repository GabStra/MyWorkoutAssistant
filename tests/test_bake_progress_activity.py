from exercise_motion_pkg.bake_and_rank import bake_and_rank_progress, bake_progress_activity


def test_bake_progress_activity_forwards_progress_lines():
    seen = []
    with bake_progress_activity(seen.append):
        bake_and_rank_progress("candidate 1/1 starting")
    assert seen == ["candidate 1/1 starting"]
