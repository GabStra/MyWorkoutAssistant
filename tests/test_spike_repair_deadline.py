import numpy as np
import pytest

from exercise_motion_pkg import controlled_motion as motion


@pytest.mark.parametrize("expire_at", ["entry", "decode", "scan"])
def test_spike_repair_stops_before_expensive_work_after_deadline(monkeypatch, expire_at):
    now = [10.0 if expire_at == "entry" else 0.0]
    calls = []
    monkeypatch.setattr(motion, "monotonic", lambda: now[0])
    class Rig:
        names = []
        def decode(self, coordinates):
            calls.append("decode")
            if expire_at == "decode":
                now[0] = 10.0
            return np.zeros((3, 1, 3))
    def scan(*args, **kwargs):
        calls.append("scan")
        now[0] = 10.0
        return {"introducedSpikes": {"events": [{"joint": "left_knee", "frameIndex": 1}]}}
    monkeypatch.setattr(motion, "relative_motion_quality", scan)
    def forbidden(*args, **kwargs):
        raise AssertionError("Expired spike repair must not prepare or run the solver")
    monkeypatch.setattr(motion, "_plant_chain_slots", forbidden)
    monkeypatch.setattr(motion, "_trf_playback_run_coupled", forbidden)
    coordinates = np.arange(9, dtype=float).reshape(3, 3)
    result = motion.project_introduced_spikes_coordinates(coordinates, Rig(), None, None, None,
        fps=30, deadline=10.0)
    np.testing.assert_array_equal(result, coordinates)
    assert calls == {"entry": [], "decode": ["decode"], "scan": ["decode", "scan"]}[expire_at]


@pytest.mark.parametrize("remaining", [0., .5])
def test_velocity_repair_cannot_extend_shared_deadline(monkeypatch, remaining):
    from types import SimpleNamespace
    from exercise_motion_pkg import physical_validation, rig_interpolation

    now = [10. - remaining]
    monkeypatch.setattr(motion, "monotonic", lambda: now[0])
    jumps = []
    def jump(*args):
        assert args[2] == 60.
        jumps.append(True)
        return 1. if len(jumps) == 1 else 0.
    monkeypatch.setattr(rig_interpolation, "frame_boundary_velocity_jump", jump)
    monkeypatch.setattr(physical_validation, "body_scale", lambda *args: 1.)
    monkeypatch.setattr(motion, "_sampling_payload", lambda *args: {})
    monkeypatch.setattr(motion, "temporal_coordinate_smooth", lambda values, **kwargs: values.copy())
    monkeypatch.setattr(motion, "_playback_failing_intervals", lambda *args, **kwargs: [0])
    deadlines = []
    def project(values, *args, deadline, **kwargs):
        deadlines.append(deadline)
        now[0] += .1
        return values.copy()
    monkeypatch.setattr(motion, "project_contact_plant_coordinates", project)
    monkeypatch.setattr(motion, "project_interval_playback_plants", project)
    rig = SimpleNamespace(names=['pelvis'], decode=lambda values: np.zeros((3, 1, 3)))
    coordinates = np.zeros((3, 6))
    result = motion.repair_playback_velocity_continuity(
        coordinates, rig, np.ones((3, 1), dtype=bool), np.zeros((3, 1, 3)),
        deadline=10., fps=60.)
    np.testing.assert_array_equal(result, coordinates)
    if remaining:
        assert len(deadlines) >= 2  # Stored-frame and interpolated contact repairs.
        assert all(deadline <= 10. for deadline in deadlines)
    else:
        assert not jumps and not deadlines
