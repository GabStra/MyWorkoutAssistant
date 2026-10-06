import copy
import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg import controlled_motion as cm
from exercise_motion_pkg.physical_validation import body_scale
from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump
from exercise_motion_pkg.rig_playback import sample_rig

path = Path(
    r"build/exercise_motion/exercise-library/barbell-good-morning/bake/"
    r"barbell-good-morning-001-nwyx81aftos/wear/skeleton.baked.full-input.adaptive-baseline.json"
)
captured = {}
orig = cm.repair_playback_velocity_continuity


def wrap(coordinates, rig, pinned, contact_targets, **kw):
    if "c" not in captured:
        captured["c"] = np.asarray(coordinates, float).copy()
        captured["rig"] = rig
        captured["pinned"] = pinned
        captured["targets"] = contact_targets
        captured["kw"] = kw
        print("captured", flush=True)
    return orig(coordinates, rig, pinned, contact_targets, **kw)


cm.repair_playback_velocity_continuity = wrap
working = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
working.pop("fixedRig", None)
working.pop("controlledMotionFit", None)
working.pop("observedCycleProposals", None)
working["loop"] = {**(working.get("loop") or {}), "enabled": True}
cm.fit_controlled_motion(working)

coords = captured["c"]
rig = captured["rig"]
pinned = captured["pinned"]
targets = captured["targets"]
kw = captured["kw"]
cyclic = kw.get("cyclic", False)
floor = kw.get("floor")
names = rig.names
equipment = kw.get("equipment")


def jump(values):
    knots = np.arange(1, len(values) - 1)
    payload = cm._sampling_payload(rig, values)
    return frame_boundary_velocity_jump(
        lambda cursors: sample_rig(payload, cursors, wrap=cyclic), knots, 30.0
    )


def limit(values):
    return 0.001 * body_scale(rig.decode(values), names)


def report(label, values):
    play = cm._playback_contact_sample_error(values, rig, pinned, targets, cyclic=cyclic)
    j = jump(values)
    print(label, "playC", play, "jump", j, "limit", limit(values), "ok_vel", j < limit(values), flush=True)


report("entry", coords)
s = cm.temporal_coordinate_smooth(coords, cyclic=cyclic, sigma=0.85)
report("smooth", s)
s = cm.project_contact_plant_coordinates(s, rig, pinned, targets, max_nfev=24, freeze_root=True)
report("keyplant", s)
s2 = cm.project_interval_playback_plants(s, rig, pinned, targets, cyclic=cyclic, floor=floor, max_nfev=16)
report("midplant", s2)
s3 = cm._root_shift_failing_playback_intervals(
    s, rig, pinned, targets, cyclic=cyclic, floor=floor,
    failing=cm._playback_failing_intervals(s, rig, pinned, targets, cyclic=cyclic, floor=floor),
    passes=8,
)
s3 = cm.project_contact_plant_coordinates(s3, rig, pinned, targets, max_nfev=20, freeze_root=True)
report("rootshift+key", s3)
# smooth again lightly
s4 = cm.temporal_coordinate_smooth(s2, cyclic=cyclic, sigma=0.4)
s4 = cm.project_contact_plant_coordinates(s4, rig, pinned, targets, max_nfev=20, freeze_root=True)
report("midplant+resmooth+key", s4)
if equipment:
    s5 = cm.project_rigid_pair_grip_coordinates(s4, rig, names, equipment, pinned=pinned, max_nfev=20)
    s5 = cm.project_playback_rigid_pair_grip(s5, rig, names, equipment, pinned=pinned, cyclic=cyclic, max_nfev=12)
    s5 = cm.project_contact_plant_coordinates(s5, rig, pinned, targets, max_nfev=16, freeze_root=True)
    report("plus_grip", s5)
