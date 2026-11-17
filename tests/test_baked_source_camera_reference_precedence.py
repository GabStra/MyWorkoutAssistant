import json

from exercise_motion_pkg import bake_and_rank as bake


def test_current_bound_passthrough_camera_beats_stale_structural_camera(tmp_path, monkeypatch):
    identity = {
        "selectedSegmentSha256": "1" * 64,
        "parentSourceSha256": "2" * 64,
        "selectedFrameClockReceiptSha256": "3" * 64,
        "sourcePosePayloadSha256": "4" * 64,
    }
    source_pose = {"frames": []}
    selected_video = tmp_path / "selected.mp4"
    cleaned_path = tmp_path / "cleaned" / "motion.cleaned.json"
    cleaned_path.parent.mkdir(parents=True)
    cleaned_path.write_text(json.dumps({
        "frames": [
            {"inferenceFrameIndex": 0, "joints": {"pelvis": [0.0, 0.0, 0.0]}},
            {"inferenceFrameIndex": 1, "joints": {"pelvis": [0.0, 1.0, 0.0]}},
        ],
        "metadata": {
            "reconstruction": {"sourceFrameClock": {"outputVideoPath": str(selected_video)}},
            "structuralRefinement": {"sourceGuidedArticulation": {"cameraRegistration": {
                "available": True,
                "cameraImageTransform": "stale-structural-transform",
                "sourceTimelineMappingIdentity": {**identity, "sourcePosePayloadSha256": "5" * 64},
            }}},
            "sourcePoseRegistration": {
                "policy": "pre_cleanup_fixed_camera",
                "sourcePose": {"_sourceTimelineMappingApplied": identity},
                "camera": {
                    "available": True,
                    "cameraImageTransform": "current-passthrough-transform",
                    "sourceTimelineMappingIdentity": identity,
                },
            },
        },
    }), encoding="utf-8")

    monkeypatch.setattr(bake, "source_frame_clock_path_for_video", lambda _path: tmp_path / "clock.json")
    monkeypatch.setattr(
        "exercise_motion_pkg.source_frame_clock.load_verified_source_frame_clock",
        lambda *_args, **_kwargs: {"frames": []},
    )
    monkeypatch.setattr(
        "exercise_motion_pkg.source_frame_clock.source_references_for_frame_ids",
        lambda _receipt, indexes: [
            {"sourceFrameIndex": index, "sourceTimeSec": float(index)} for index in indexes
        ],
    )
    monkeypatch.setattr(bake, "verified_source_timeline_mapping", lambda **_kwargs: identity)

    reference = bake.load_baked_source_camera_reference(tmp_path, source_pose)
    assert reference is not None
    assert reference["camera"]["cameraImageTransform"] == "current-passthrough-transform"
    assert reference["sourceTimelineMapping"] == identity
    assert [frame["sourceFrameIndex"] for frame in reference["coordinateReference"]["frames"]] == [0, 1]

    # A passthrough camera whose own retained-pose identity is stale is not
    # admitted, even though its camera object claims the current identity.
    cleaned = json.loads(cleaned_path.read_text(encoding="utf-8"))
    cleaned["metadata"]["sourcePoseRegistration"]["sourcePose"][
        "_sourceTimelineMappingApplied"] = {**identity, "sourcePosePayloadSha256": "6" * 64}
    cleaned_path.write_text(json.dumps(cleaned), encoding="utf-8")
    assert bake.load_baked_source_camera_reference(tmp_path, source_pose) is None

    # A structural registration remains a valid preferred source when it is
    # itself bound to the current verified mapping.
    cleaned["metadata"]["structuralRefinement"]["sourceGuidedArticulation"][
        "cameraRegistration"]["sourceTimelineMappingIdentity"] = identity
    cleaned_path.write_text(json.dumps(cleaned), encoding="utf-8")
    reference = bake.load_baked_source_camera_reference(tmp_path, source_pose)
    assert reference is not None
    assert reference["camera"]["cameraImageTransform"] == "stale-structural-transform"
