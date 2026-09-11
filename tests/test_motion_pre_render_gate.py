import copy
import json
from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake


def test_rejected_geometry_never_renders_and_remains_diagnosable(tmp_path, monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/dumbbell-thruster-renderer.json").read_text())
    payload["jointNames"] = list(payload["frames"][0]["joints"])
    for index, frame in enumerate(payload["frames"]):
        frame["timeSec"] = index / 30
    payload["frames"][50]["joints"]["left_wrist"][0] += 2
    artifact = bake.BakedLoopArtifact(-1, tmp_path / "skeleton.json", tmp_path / "preview.webm", payload)
    monkeypatch.setattr(bake, "render_baked_wear_frames_with_playwright",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rejected output rendered")))
    bake.render_prechecked_baked_artifacts(None, [artifact], tmp_path)
    gate = json.loads(artifact.skeleton_path.read_text())["preRenderDeterministicGate"]
    assert not gate["passed"]
    assert gate["rejectionReasons"]
    assert not artifact.review_video_path.exists()


def test_usable_geometry_renders_after_precheck(tmp_path, monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/dumbbell-thruster-renderer.json").read_text())
    payload.update(jointNames=list(payload["frames"][0]["joints"]), frameCount=len(payload["frames"]))
    for index, frame in enumerate(payload["frames"]):
        frame["timeSec"] = index / 30
    before = copy.deepcopy(payload["frames"])
    artifact = bake.BakedLoopArtifact(-1, tmp_path / "skeleton.json", tmp_path / "preview.webm", payload)
    calls = []
    def render(*args, **kwargs):
        assert artifact.export_payload["preRenderDeterministicGate"]["passed"]
        calls.append("render")
        return ["data:image/png;base64,unused"] * len(kwargs["frame_indices"])
    monkeypatch.setattr(bake, "render_baked_wear_frames_with_playwright", render)
    monkeypatch.setattr(bake, "write_validated_review_video_from_data_urls", lambda urls, path, fps: (path, {"passed": True}))
    bake.render_prechecked_baked_artifacts(None, [artifact], tmp_path)
    assert calls == ["render"]
    assert payload["frames"] == before
