import copy
import math

import pytest

from exercise_motion_pkg.bake_and_rank import apply_source_contact_sequence_correction


@pytest.mark.parametrize("contact_state,existing_pitch", [
    ("full_sole", None), ("full_sole", 0.2), ("forefoot", None),
])
def test_contact_correction_keeps_material_calibration(contact_state, existing_pitch):
    frames = [{"frameIndex": i, "timeSec": i / 30, "joints": {
        "pelvis": [i * .01, 1, 0], "right_ankle": [i * .01, .05, 0],
        "right_foot": [i * .01, 0, .1],
    }} for i in range(12)]
    payload = {"fps": 30, "jointNames": ["pelvis", "right_ankle", "right_foot"],
               "frames": frames}
    if existing_pitch is not None:
        payload["footRestPitchRadians"] = {"right": existing_pitch}
    before = copy.deepcopy(payload)
    evidence = {"contacts": [{
        "jointName": "right_foot", "startFrame": 0, "endFrame": 11,
        "contactState": contact_state, "contactMotion": "stationary",
        "supportKind": "observed_foot_patch", "surfaceKind": "ground",
    }]}
    corrected, metrics = apply_source_contact_sequence_correction(payload, evidence)
    assert metrics["applied"]
    assert payload == before
    pitches = corrected.get("footRestPitchRadians", {})
    assert "left" not in pitches
    if contact_state == "forefoot":
        assert "right" not in pitches
    else:
        assert pitches["right"] == pytest.approx(
            existing_pitch if existing_pitch is not None else -math.atan(.5))
