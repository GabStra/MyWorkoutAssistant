import hashlib

import pytest

from exercise_motion_pkg import source_frame_clock, source_support_stage


def test_generic_body_review_accepts_verified_direct_and_nested_pose_shapes(tmp_path, monkeypatch):
    video = tmp_path / "selected.mp4"
    video.write_bytes(b"selected video bytes")
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    clock_path = source_frame_clock.source_frame_clock_path_for_video(video)
    clock_path.write_text('{"fixture":"clock receipt"}', encoding="utf-8")

    def load_clock(path, *, expected_video_path):
        assert path == clock_path
        assert expected_video_path.resolve() == video.resolve()
        return {"outputFps": 10.0}

    monkeypatch.setattr(source_frame_clock, "load_verified_source_frame_clock", load_clock)
    frames = [
        {"sourceTimeSec": 0.0, "frameIndex": 0},
        {"sourceTimeSec": 0.1, "frameIndex": 1},
    ]
    payload = {"coordinateSpace": "normalized_image_xy", "frames": frames}
    references = [
        {"sourceVideoSha256": digest, **payload},
        {"sourceVideoSha256": digest, "pose": payload},
    ]
    requirements = {"required": [{"region": "chest", "side": "center"}]}

    for reference in references:
        rows = source_support_stage._generic_body_surface_review_records(
            requirements, video, reference,
        )
        assert len(rows) == 1
        observations = rows[0]["record"]["sourceEvidence"]["observations"]
        assert [item["sourceFrameIndex"] for item in observations] == [0, 1]
        assert rows[0]["record"]["sourceEvidence"]["sourceVideoSha256"] == digest

    wrong_video = {"sourceVideoSha256": "0" * 64, "pose": payload}
    with pytest.raises(ValueError, match="different source video"):
        source_support_stage._generic_body_surface_review_records(
            requirements, video, wrong_video,
        )
