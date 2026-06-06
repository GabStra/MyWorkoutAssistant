from __future__ import annotations

from pathlib import Path


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

    ranked_items = sorted(
        raw_results.items(),
        key=lambda item: _subject_frame_count(item[1]),
        reverse=True,
    )
    selected_key, payload = ranked_items[0]
    if not isinstance(payload, dict):
        raise ValueError(f"WHAM subject payload for '{selected_key}' must be a dict.")
    return selected_key, payload


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
