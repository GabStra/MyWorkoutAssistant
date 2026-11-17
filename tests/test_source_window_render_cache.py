from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.segment_detection import DetectionWindow


def test_source_window_cache_ignores_unrelated_bake_edits_and_checks_real_inputs(
    tmp_path, monkeypatch,
):
    fake_bake = tmp_path / "bake_and_rank.py"
    extractor = tmp_path / "segment_detection.py"
    video = tmp_path / "source.mp4"
    fake_bake.write_text("unrelated implementation", encoding="utf-8")
    extractor.write_text("extractor v1", encoding="utf-8")
    video.write_bytes(b"video v1")
    monkeypatch.setattr(bake, "__file__", str(fake_bake))

    render_calls = []

    def render(**kwargs):
        render_calls.append(kwargs)
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        sheet = output_dir / "contact_sheet.jpg"
        sheet.write_bytes(f"sheet-{len(render_calls)}".encode())
        (output_dir / "frame_01.jpg").write_bytes(b"frame")
        (output_dir / "contact_sheet_evidence.json").write_text("{}", encoding="utf-8")
        return [sheet]

    monkeypatch.setattr(bake, "_render_video_window_contact_sheet_uncached", render)
    output = tmp_path / "render"
    window = DetectionWindow(index=0, start_seconds=1.0, end_seconds=2.0)

    def invoke(*, frame_count=8, **kwargs):
        return bake.render_video_window_contact_sheet(
            video_path=video, window=window, output_dir=output,
            frame_count=frame_count, **kwargs,
        )

    first = invoke()
    assert len(render_calls) == 1

    # Changes elsewhere in bake_and_rank.py no longer poison the render cache.
    fake_bake.write_text("unrelated implementation changed", encoding="utf-8")
    assert invoke() == first
    assert len(render_calls) == 1

    # Every effective render argument participates in the key.
    invoke(contact_sheet_tile_width=321)
    invoke(frame_count=9)
    assert len(render_calls) == 3

    native_frame = tmp_path / "native.jpg"
    native_frame.write_bytes(b"native v1")
    invoke(native_frame_lookup={"1.000": native_frame})
    assert len(render_calls) == 4
    native_frame.write_bytes(b"native v2")
    invoke(native_frame_lookup={"1.000": native_frame})
    assert len(render_calls) == 5

    # Source and extractor changes invalidate; corrupt cached outputs are never reused.
    video.write_bytes(b"video v2")
    invoke()
    assert len(render_calls) == 6
    extractor.write_text("extractor v2", encoding="utf-8")
    invoke()
    assert len(render_calls) == 7
    first[0].write_bytes(b"corrupt")
    invoke()
    assert len(render_calls) == 8
