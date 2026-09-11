import copy
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as b


def skeleton():
    joints = {
        "pelvis": [0, 1, 0], "neck": [0, 2, 0],
        "left_hip": [-0.15, 1, 0], "left_knee": [-0.15, 0.5, 0.3],
        "left_ankle": [-0.15, 0, 0], "left_foot": [-0.15, 0, 0.15],
        # Deliberately asymmetric: preserving source articulation must not mirror it.
        "right_hip": [0.15, 1, 0], "right_knee": [0.15, 0.5, 0.4],
        "right_ankle": [0.15, 0, 0], "right_foot": [0.15, 0, 0.15],
    }
    return {"fps": 30, "frames": [
        {"timeSec": i / 30, "sourceJoints": copy.deepcopy(joints), "joints": copy.deepcopy(joints)}
        for i in range(3)
    ]}


@pytest.mark.parametrize("distort", [False, True])
def test_foot_correction_cannot_invent_knee_articulation(monkeypatch, distort):
    payload = skeleton()
    original = copy.deepcopy(payload)
    monkeypatch.setattr(b, "suppress_post_ik_anatomical_spikes", lambda clip: (clip, {}))
    monkeypatch.setattr(b, "stabilize_distal_foot_heading", lambda clip: (clip, {}))

    def foot_correction(clip, evidence):
        proposed = copy.deepcopy(clip)
        if distort:
            for frame in proposed.frames:
                frame.joints["left_knee"] = (-0.15, 0.5, 0.05)
        return proposed, {"applied": True}

    monkeypatch.setattr(b, "stabilize_forefoot_ground_contacts", foot_correction)
    result, _ = b.constrain_baked_payload_to_source_articulation(payload, use_controlled_motion_fit=False)
    assert result["postBakeForefootContactConstraint"]["applied"] is (not distort)
    assert [f["joints"] for f in result["frames"]] == [f["joints"] for f in original["frames"]]


def test_export_audit_detects_cleanup_distortion_but_allows_source_asymmetry():
    payload = skeleton()
    assert not b.baked_leg_articulation_preservation_metrics(payload)["applied"]
    for frame in payload["frames"]:
        frame["joints"]["left_knee"] = [-0.15, 0.5, 0.05]
    result = b.baked_leg_articulation_preservation_metrics(payload)
    assert result["constrainedJoints"] == ["left_knee"]
    assert result["maximumPreventedExcessDegrees"] > 5
    assert "materialized_leg_articulation_changed_by_cleanup" in b.FINAL_OUTPUT_HARD_DETERMINISTIC_REJECTION_REASONS


def test_failed_second_view_cannot_fall_back_to_single_video(tmp_path, monkeypatch):
    html = tmp_path / "preview.html"
    html.write_text("html")
    data = tmp_path / "skeleton.json"
    data.write_text("{}")
    item = b.ReviewItem(0, 0, 0, "Press", "Press", tmp_path, html, data,
                        tmp_path / "old.webm", 1.0, 0.0, 1.0, {})
    calls = []

    def renderer(**kwargs):
        calls.append(kwargs["item"].settings_options["cameraYawDegrees"])
        assert kwargs["materialized_skeleton"] is True
        if len(calls) == 2:
            raise RuntimeError("opposite view unavailable")
        return [Path("primary.jpg")]

    monkeypatch.setattr(b, "render_review_window_contact_sheet", renderer)
    monkeypatch.setattr(b, "render_video_window_contact_sheet", lambda **kwargs: pytest.fail("single-view fallback"))
    with pytest.raises(b.ReviewFrameCaptureError, match="opposite view unavailable"):
        b.final_output_preview_contact_sheets(item, output_dir=tmp_path)
    assert calls == [135, 315]
