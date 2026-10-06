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
        captured["kw"] = dict(kw)
        print(
            "captured repair entry",
            "equip_passed_in", kw.get("equipment") is not None,
            flush=True,
        )
    return orig(coordinates, rig, pinned, contact_targets, **kw)


cm.repair_playback_velocity_continuity = wrap
working = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
for key in ("fixedRig", "controlledMotionFit", "observedCycleProposals"):
    working.pop(key, None)
working["loop"] = {**(working.get("loop") or {}), "enabled": True}
cm.fit_controlled_motion(working, timeout_seconds=180.0)

if "c" not in captured:
    print("NO CAPTURE — velocity repair never called")
    raise SystemExit(1)

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


def play(values):
    return cm._playback_contact_sample_error(
        values, rig, pinned, targets, cyclic=cyclic
    )


def limit(values):
    return 0.001 * body_scale(rig.decode(values), names)


print("entry equip_arg", equipment is not None)
print("entry", play(coords), jump(coords), limit(coords), jump(coords) > limit(coords))
# mimic Stage-C: no equipment after grip cleared
out = orig(
    coords, rig, pinned, targets, cyclic=cyclic, sigma=0.75,
    names=None, equipment=None, floor=floor,
)
print("repair_no_equip", play(out), jump(out), limit(out),
      "ok_vel", jump(out) < limit(out), "ok_play", play(out) < 0.0005)
out2 = orig(
    coords, rig, pinned, targets, cyclic=cyclic, sigma=0.75,
    names=names, equipment=equipment, floor=floor,
)
print("repair_with_equip", play(out2), jump(out2), limit(out2),
      "ok_vel", jump(out2) < limit(out2), "ok_play", play(out2) < 0.0005)
