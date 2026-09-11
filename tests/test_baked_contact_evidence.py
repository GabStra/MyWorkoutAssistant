import copy

import pytest

from exercise_motion_pkg import bake_and_rank as b


def test_baked_contacts_are_rebased_to_selected_frames_without_changing_source():
    evidence = {"contacts": [{"jointName": "left_foot", "startRatio": 0., "endRatio": .5},
                              {"jointName": "right_foot", "startRatio": .8, "endRatio": 1.}]}
    original = copy.deepcopy(evidence)
    payload = {"source": {"frameCount": 101}, "frames": [{"sourceFrameIndex": 25}, {"sourceFrameIndex": 75}],
               "selectedPreviewSettings": {"sourceFootSupportEvidence": evidence}}
    result = b.baked_source_support_evidence(payload)
    assert result["contacts"] == [{"jointName": "left_foot", "startRatio": 0., "endRatio": .5}]
    assert evidence == original
    payload["sourceFootSupportEvidence"] = result
    assert b.baked_source_support_evidence(payload) is result  # Do not slice twice.


def test_bake_without_contact_evidence_does_not_invent_ground_support():
    assert b.baked_source_support_evidence({"frames": []}) is None


def test_post_bake_solver_receives_retained_evidence_and_exports_its_floor(monkeypatch):
    joints = {"pelvis": [0., 1., 0.], "neck": [0., 1.7, 0.]}
    for side, x in (("left", -.2), ("right", .2)):
        joints.update({f"{side}_hip": [x, 1., 0.], f"{side}_knee": [x, .5, .2],
                       f"{side}_ankle": [x, 0., 0.], f"{side}_foot": [x, 0., .15]})
    evidence = {"contacts": [{"jointName": "left_foot", "contactState": "full_sole"}]}
    payload = {"fps": 30, "jointNames": list(joints), "frames": [
        {"timeSec": i / 30., "joints": copy.deepcopy(joints), "sourceJoints": copy.deepcopy(joints)} for i in range(8)],
        "selectedPreviewSettings": {"sourceFootSupportEvidence": evidence}}
    monkeypatch.setattr(b, "constrain_to_source_articulation_envelope", lambda source, proposed, **kw: (proposed, {"applied": False}))
    monkeypatch.setattr(b, "suppress_post_ik_anatomical_spikes", lambda clip: (clip, {"applied": False}))
    monkeypatch.setattr(b, "stabilize_distal_foot_heading", lambda clip: (clip, {"applied": False}))
    def contact_solver(clip, observed):
        assert observed == evidence
        return clip, {"applied": True, "supportPlaneY": -.02}
    monkeypatch.setattr(b, "stabilize_forefoot_ground_contacts", contact_solver)
    result, _ = b.constrain_baked_payload_to_source_articulation(payload, use_controlled_motion_fit=False)
    assert result["sourceFootSupportEvidence"] == evidence
    assert result["renderFloorY"] == pytest.approx(-.02)
