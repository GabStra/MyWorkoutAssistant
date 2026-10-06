"""Conservative, window-wide removal of persistent black video borders."""
from pathlib import Path

CONTACT_SHEET_CROP_POLICY_VERSION = 1


def persistent_border_crop(frame_paths: list[Path]) -> tuple[int, int, int, int] | None:
    """Return one safe (left, top, right, bottom) crop shared by every frame.

    Only nearly symmetric pairs of uniformly black edges qualify. All frames
    must decode with identical dimensions; changing framing or dark footage
    falls back to the original images. No person tracking or moving crop is used.
    """
    import cv2
    import numpy as np

    if len(frame_paths) < 4:
        return None
    bounds = []
    shape = None
    for path in frame_paths:
        frame = cv2.imread(str(path))
        if frame is None or (shape is not None and frame.shape != shape):
            return None
        shape = frame.shape
        height, width = shape[:2]
        # Require every pixel on a border line to be black, including overlaid
        # text and equipment. JPEG ringing is covered by the retained margin.
        content = np.max(frame, axis=2) > 12
        occupied_y, occupied_x = np.nonzero(content)
        if not occupied_x.size or np.mean(content) < 0.1:
            return None
        bounds.append((int(occupied_x.min()), int(occupied_y.min()),
                       int(occupied_x.max()) + 1, int(occupied_y.max()) + 1))
    left = min(b[0] for b in bounds)
    top = min(b[1] for b in bounds)
    right = max(b[2] for b in bounds)
    bottom = max(b[3] for b in bounds)

    def edge_pair(start: int, end: int, size: int, axis: int) -> tuple[int, int]:
        margin = max(4, round(size * 0.01))
        stable = all(abs(b[axis] - start) <= margin and abs(b[axis + 2] - end) <= margin for b in bounds)
        if (not stable or min(start, size - end) < max(8, size * 0.02)
                or abs(start - (size - end)) > max(8, size * 0.02)
                or end - start < max(64, size * 0.2)):
            return 0, size
        return max(0, start - margin), min(size, end + margin)

    left, right = edge_pair(left, right, width, 0)
    top, bottom = edge_pair(top, bottom, height, 1)
    if (left, top, right, bottom) == (0, 0, width, height):
        return None
    return left, top, right, bottom
