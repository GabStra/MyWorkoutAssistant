from __future__ import annotations

import math
from pathlib import Path


MAX_TRACK_STITCH_GAP_FRAMES = 2
MAX_TRACK_STITCH_OVERLAP_FRAMES = 5
MAX_TRACK_STITCH_TRANSLATION_METERS = 0.35
MAX_TRACK_STITCH_POSE_RMS_RADIANS = 0.60
TRACK_STITCH_POSE_BLEND_FRAMES = 12


def load_wham_results(wham_results_pkl: Path) -> dict[object, dict[str, object]]:
    try:
        import joblib  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "WHAM result loading requires joblib in the active environment."
        ) from exc

    raw = joblib.load(wham_results_pkl)
    if not isinstance(raw, dict):
        raise ValueError("WHAM results must load to a dict-like mapping keyed by subject id.")
    return dict(raw)


def select_wham_subject(
    raw_results: dict[object, dict[str, object]],
    *,
    subject_id: int | str | None = None,
) -> tuple[object, dict[str, object]]:
    if not raw_results:
        raise ValueError("WHAM results did not contain any subjects.")

    if subject_id is not None:
        for candidate_key, payload in raw_results.items():
            if str(candidate_key) == str(subject_id):
                if not isinstance(payload, dict):
                    raise ValueError(f"WHAM subject payload for '{candidate_key}' must be a dict.")
                return candidate_key, payload
        raise ValueError(f"WHAM results did not contain subject '{subject_id}'.")

    stitchable_tracks = [
        (key, payload)
        for key, payload in raw_results.items()
        if isinstance(payload, dict) and _frame_ids(payload)
    ]
    stitched = _longest_compatible_track_chain(stitchable_tracks)
    if stitched is not None:
        return stitched

    ranked_items = sorted(raw_results.items(), key=lambda item: _subject_frame_count(item[1]), reverse=True)
    selected_key, payload = ranked_items[0]
    if not isinstance(payload, dict):
        raise ValueError(f"WHAM subject payload for '{selected_key}' must be a dict.")
    return selected_key, payload


def _longest_compatible_track_chain(
    tracks: list[tuple[object, dict[str, object]]],
) -> tuple[object, dict[str, object]] | None:
    """Join WHAM ID fragments only when they form one continuous, spatially compatible track."""
    if not tracks:
        return None
    ordered = sorted(tracks, key=lambda item: (_frame_ids(item[1])[0], -len(_frame_ids(item[1]))))
    best_chain: list[tuple[object, dict[str, object]]] = []
    best_frame_count = 0
    for start_index, first in enumerate(ordered):
        chain = [first]
        covered_end = _frame_ids(first[1])[-1]
        remaining = ordered[start_index + 1 :]
        while True:
            compatible = [
                item
                for item in remaining
                if _frame_ids(item[1])[-1] > covered_end
                and _tracks_are_contiguous_and_compatible(chain[-1][1], item[1])
            ]
            if not compatible:
                break
            next_track = min(
                compatible,
                key=lambda item: (
                    abs(_frame_ids(item[1])[0] - covered_end),
                    _track_boundary_distance(chain[-1][1], item[1]),
                    -_frame_ids(item[1])[-1],
                ),
            )
            chain.append(next_track)
            covered_end = _frame_ids(next_track[1])[-1]
            remaining = [item for item in remaining if item is not next_track]
        unique_frames = len({frame_id for _, payload in chain for frame_id in _frame_ids(payload)})
        if unique_frames > best_frame_count:
            best_chain = chain
            best_frame_count = unique_frames

    if len(best_chain) <= 1:
        return None
    stitched_payload = _stitch_track_payloads([payload for _, payload in best_chain])
    stitched_key = "+".join(str(key) for key, _ in best_chain)
    return stitched_key, stitched_payload


def _tracks_are_contiguous_and_compatible(
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    left_ids = _frame_ids(left)
    right_ids = _frame_ids(right)
    if not left_ids or not right_ids:
        return False
    gap = right_ids[0] - left_ids[-1]
    if gap < -MAX_TRACK_STITCH_OVERLAP_FRAMES or gap > MAX_TRACK_STITCH_GAP_FRAMES:
        return False
    left_index = len(left_ids) - 1
    right_index = 0
    if right_ids[0] <= left_ids[-1]:
        shared_frame = left_ids[-1]
        if shared_frame not in right_ids:
            return False
        right_index = right_ids.index(shared_frame)
    translation_distance = _row_distance(left.get("trans"), left_index, right.get("trans"), right_index)
    pose_rms = _row_rms_distance(left.get("pose"), left_index, right.get("pose"), right_index)
    return (
        translation_distance is not None
        and translation_distance <= MAX_TRACK_STITCH_TRANSLATION_METERS
        and pose_rms is not None
        and pose_rms <= MAX_TRACK_STITCH_POSE_RMS_RADIANS
    )


def _track_boundary_distance(left: dict[str, object], right: dict[str, object]) -> float:
    left_ids = _frame_ids(left)
    right_ids = _frame_ids(right)
    right_index = right_ids.index(left_ids[-1]) if left_ids[-1] in right_ids else 0
    distance = _row_distance(left.get("trans"), len(left_ids) - 1, right.get("trans"), right_index)
    return distance if distance is not None else float("inf")


def _row_distance(left: object, left_index: int, right: object, right_index: int) -> float | None:
    try:
        left_row = left[left_index]  # type: ignore[index]
        right_row = right[right_index]  # type: ignore[index]
        differences = [float(a) - float(b) for a, b in zip(left_row, right_row)]
    except (IndexError, TypeError, ValueError):
        return None
    return math.sqrt(sum(value * value for value in differences)) if differences else None


def _row_rms_distance(left: object, left_index: int, right: object, right_index: int) -> float | None:
    try:
        left_row = left[left_index]  # type: ignore[index]
        right_row = right[right_index]  # type: ignore[index]
        differences = [float(a) - float(b) for a, b in zip(left_row, right_row)]
    except (IndexError, TypeError, ValueError):
        return None
    return math.sqrt(sum(value * value for value in differences) / len(differences)) if differences else None


def _stitch_track_payloads(payloads: list[dict[str, object]]) -> dict[str, object]:
    import numpy as np  # type: ignore

    frame_ids_by_payload = [_frame_ids(payload) for payload in payloads]
    keep_indices: list[list[int]] = []
    last_frame_id: int | None = None
    for frame_ids in frame_ids_by_payload:
        indices = [index for index, frame_id in enumerate(frame_ids) if last_frame_id is None or frame_id > last_frame_id]
        keep_indices.append(indices)
        if indices:
            last_frame_id = frame_ids[indices[-1]]

    stitched = dict(payloads[0])
    common_keys = set.intersection(*(set(payload) for payload in payloads))
    kept_frame_ids = [
        [frame_ids[index] for index in indices]
        for frame_ids, indices in zip(frame_ids_by_payload, keep_indices)
        if indices
    ]
    for key in common_keys:
        values = [payload[key] for payload in payloads]
        if not all(hasattr(value, "shape") and len(value.shape) >= 1 for value in values):  # type: ignore[attr-defined]
            continue
        if not all(int(value.shape[0]) == len(frame_ids) for value, frame_ids in zip(values, frame_ids_by_payload)):  # type: ignore[index]
            continue
        chunks = [value[indices].copy() for value, indices in zip(values, keep_indices) if indices]  # type: ignore[index]
        if key in {"trans", "trans_world"}:
            _align_translation_chunks(chunks, kept_frame_ids)
        elif key in {"pose", "pose_world"}:
            _blend_pose_chunk_boundaries(chunks, kept_frame_ids)
        stitched[key] = np.concatenate(chunks, axis=0)
    return stitched


def _align_translation_chunks(chunks: list[object], frame_ids: list[list[int]]) -> None:
    """Remove arbitrary per-track origin jumps while preserving boundary velocity."""
    for index in range(1, len(chunks)):
        previous = chunks[index - 1]
        current = chunks[index]
        previous_ids = frame_ids[index - 1]
        current_ids = frame_ids[index]
        if len(previous) <= 0 or len(current) <= 0:  # type: ignore[arg-type]
            continue
        velocity = previous[-1] * 0.0  # type: ignore[index,operator]
        if len(previous) >= 2 and previous_ids[-1] > previous_ids[-2]:  # type: ignore[arg-type]
            velocity = (previous[-1] - previous[-2]) / (previous_ids[-1] - previous_ids[-2])  # type: ignore[index,operator]
        frame_gap = max(1, current_ids[0] - previous_ids[-1])
        expected_first = previous[-1] + velocity * frame_gap  # type: ignore[index,operator]
        current += expected_first - current[0]  # type: ignore[index,operator]


def _blend_pose_chunk_boundaries(chunks: list[object], frame_ids: list[list[int]]) -> None:
    """Ease small pose-coordinate resets introduced when WHAM assigns a new track ID."""
    for index in range(1, len(chunks)):
        previous = chunks[index - 1]
        current = chunks[index]
        previous_ids = frame_ids[index - 1]
        current_ids = frame_ids[index]
        if len(previous) <= 0 or len(current) <= 0:  # type: ignore[arg-type]
            continue
        velocity = previous[-1] * 0.0  # type: ignore[index,operator]
        if len(previous) >= 2 and previous_ids[-1] > previous_ids[-2]:  # type: ignore[arg-type]
            velocity = (previous[-1] - previous[-2]) / (previous_ids[-1] - previous_ids[-2])  # type: ignore[index,operator]
        frame_gap = max(1, current_ids[0] - previous_ids[-1])
        correction = previous[-1] + velocity * frame_gap - current[0]  # type: ignore[index,operator]
        blend_count = min(TRACK_STITCH_POSE_BLEND_FRAMES, len(current))  # type: ignore[arg-type]
        for frame_index in range(blend_count):
            weight = 1.0 - (frame_index / max(1, blend_count))
            current[frame_index] += correction * weight  # type: ignore[index,operator]


def _frame_ids(payload: dict[str, object]) -> list[int]:
    frame_ids = payload.get("frame_ids")
    if frame_ids is None or not hasattr(frame_ids, "__len__"):
        return []
    try:
        return [int(value) for value in frame_ids]  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return []


def resolve_wham_coordinate_keys(coordinate_space: str) -> tuple[str, str]:
    normalized = coordinate_space.strip().lower()
    if normalized == "world":
        return "pose_world", "trans_world"
    if normalized == "camera":
        return "pose", "trans"
    raise ValueError("coordinate_space must be either 'world' or 'camera'.")


def _subject_frame_count(payload: object) -> int:
    if not isinstance(payload, dict):
        return -1
    frame_ids = payload.get("frame_ids")
    if hasattr(frame_ids, "__len__"):
        return int(len(frame_ids))  # type: ignore[arg-type]
    pose = payload.get("pose_world") or payload.get("pose")
    if hasattr(pose, "shape") and len(pose.shape) >= 1:  # type: ignore[attr-defined]
        return int(pose.shape[0])  # type: ignore[index]
    return -1
