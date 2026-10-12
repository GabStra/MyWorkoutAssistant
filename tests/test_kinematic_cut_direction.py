from types import SimpleNamespace

from exercise_motion_pkg import kinematic_cut


def test_distinct_end_fallback_can_select_second_half_of_cycle(monkeypatch):
    cycle = kinematic_cut.Cycle(0.0, 4.0, 1.0, 4.0, 2.0)
    monkeypatch.setattr(kinematic_cut, "detect_cycles", lambda _: [cycle])
    # The clip starts in the requested end pose, then resets and performs the action.
    monkeypatch.setattr(
        kinematic_cut, "_state_score_at",
        lambda frames, signal, time, constraints: float(
            (time == 2.0) == (constraints == {"handHeight": "shoulder_chest"})
        ),
    )
    proposals = kinematic_cut._distinct_end_state_excursion_proposals(
        [], SimpleNamespace(quality=0.8, explained_variance_ratio=0.9),
        {"startPoseConstraints": {"handHeight": "shoulder_chest"},
         "endPoseConstraints": {"handHeight": "above_head"}},
        max_proposals=1,
    )
    assert [(p.start_seconds, p.end_seconds) for p in proposals] == [(2.0, 4.0)]
