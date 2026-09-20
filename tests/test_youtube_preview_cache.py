from pathlib import Path

import cv2
import numpy as np

from exercise_motion_pkg import youtube


def test_preview_cache_ignores_metadata_and_repairs_unreadable_video(tmp_path: Path):
    source = tmp_path / 'download.mp4'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 10., (32, 32))
    assert writer.isOpened()
    try:
        for value in (0, 100, 200):
            writer.write(np.full((32, 32, 3), value, dtype=np.uint8))
    finally:
        writer.release()
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'preview.json').write_text('{"downloaded": true}')
    target = cache / 'preview.mp4'
    target.write_bytes(b'incomplete video')
    assert youtube.find_cached_youtube_preview(cache, 'preview') is None
    assert youtube.cache_youtube_preview(source, cache, 'preview') == target
    assert youtube.find_cached_youtube_preview(cache, 'preview') == target
    assert target.read_bytes() == source.read_bytes()
    # A formerly valid path must be rechecked after replacement, rather than
    # retaining its positive memoized decode verdict.
    target.write_bytes(b'new incomplete video')
    assert youtube.find_cached_youtube_preview(cache, 'preview') is None
