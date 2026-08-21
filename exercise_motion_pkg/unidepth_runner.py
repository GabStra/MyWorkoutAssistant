"""Lazy UniDepth inference helpers for video-grounded floor estimation."""

from __future__ import annotations

import os
import sys
import threading
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from exercise_motion_pkg.gpu_lock import gpu_stage_lock
from exercise_motion_pkg.video_utils import read_basic_video_metadata

UNIDEPTH_ENABLED_ENV_VAR = "EXERCISE_MOTION_UNIDEPTH_ENABLED"
DEFAULT_UNIDEPTH_MODEL_ID = "lpiccinelli/unidepth-v2-vits14"
DEFAULT_MAX_DEPTH_SAMPLES = 5

_MODEL_CACHE_LOCK = threading.RLock()
_MODEL_CACHE: dict[tuple[str, str], Any] = {}
_MODEL_LOAD_COUNT = 0
_MODEL_CACHE_HIT_COUNT = 0


@dataclass(frozen=True)
class DepthFrameSample:
    time_seconds: float
    frame_index: int
    width: int
    height: int
    source_width: int
    source_height: int
    depth: np.ndarray
    intrinsics: np.ndarray
    points: np.ndarray
    model_name: str


def default_unidepth_root() -> Path:
    return Path(__file__).resolve().parent.parent / "third_party" / "UniDepth"


def unidepth_enabled() -> bool:
    raw = os.environ.get(UNIDEPTH_ENABLED_ENV_VAR, "1").strip().casefold()
    return raw not in {"0", "false", "no", "off"}


def is_unidepth_runtime_available(*, unidepth_root: Path | None = None) -> bool:
    if not unidepth_enabled():
        return False
    root = (unidepth_root or default_unidepth_root()).resolve()
    if not root.is_dir():
        return False
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def _ensure_unidepth_on_path(unidepth_root: Path) -> None:
    root_str = str(unidepth_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _load_unidepth_model(*, device: str, model_id: str, unidepth_root: Path) -> tuple[Any, str]:
    global _MODEL_CACHE_HIT_COUNT, _MODEL_LOAD_COUNT
    _ensure_unidepth_on_path(unidepth_root)
    import torch
    from unidepth.models.unidepthv2.unidepthv2 import UniDepthV2

    resolved_device = device if device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
    cache_key = (str(unidepth_root.resolve()), model_id)
    with _MODEL_CACHE_LOCK:
        model = _MODEL_CACHE.get(cache_key)
        if model is None:
            model = UniDepthV2.from_pretrained(model_id)
            model.eval()
            _MODEL_CACHE[cache_key] = model
            _MODEL_LOAD_COUNT += 1
        else:
            _MODEL_CACHE_HIT_COUNT += 1
        model = model.to(resolved_device)
    return model, resolved_device


def offload_cached_unidepth_models() -> None:
    """Keep weights reusable in host RAM while releasing all CUDA storage."""
    with _MODEL_CACHE_LOCK:
        if not _MODEL_CACHE:
            return
        for model in _MODEL_CACHE.values():
            try:
                model.to("cpu")
            except Exception:
                continue
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def unidepth_model_cache_metrics() -> dict[str, int]:
    with _MODEL_CACHE_LOCK:
        return {
            "modelCount": len(_MODEL_CACHE),
            "modelLoadCount": _MODEL_LOAD_COUNT,
            "modelCacheHitCount": _MODEL_CACHE_HIT_COUNT,
        }


def clear_cached_unidepth_models() -> None:
    global _MODEL_CACHE_HIT_COUNT, _MODEL_LOAD_COUNT
    offload_cached_unidepth_models()
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()
        _MODEL_LOAD_COUNT = 0
        _MODEL_CACHE_HIT_COUNT = 0
    gc.collect()


def _read_video_frame(video_path: Path, frame_index: int) -> np.ndarray | None:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index))
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return np.asarray(rgb)
    finally:
        capture.release()


def _select_sample_times(duration_seconds: float, *, max_samples: int) -> list[float]:
    if duration_seconds <= 1e-6:
        return [0.0]
    sample_count = max(1, min(max_samples, max(3, int(round(duration_seconds * 2.0)))))
    if sample_count == 1:
        return [duration_seconds * 0.5]
    return [
        duration_seconds * (index + 1) / (sample_count + 1)
        for index in range(sample_count)
    ]


def _tensorize_rgb(frame_rgb: np.ndarray, *, device: str) -> Any:
    import torch

    return torch.from_numpy(frame_rgb).permute(2, 0, 1).to(device)


def _depth_predictions_to_arrays(predictions: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    depth_value = predictions.get("depth")
    points_value = predictions.get("points")
    intrinsics_value = predictions.get("intrinsics")
    if depth_value is None or points_value is None or intrinsics_value is None:
        raise RuntimeError("UniDepth prediction missing depth, points, or intrinsics")

    def to_numpy(value: Any) -> np.ndarray:
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            return np.asarray(value.numpy())
        return np.asarray(value)

    depth = np.squeeze(to_numpy(depth_value)).astype(np.float64)
    points = np.squeeze(to_numpy(points_value)).astype(np.float64)
    intrinsics = np.squeeze(to_numpy(intrinsics_value)).astype(np.float64)
    if depth.ndim != 2:
        raise RuntimeError(f"Unexpected UniDepth depth shape: {depth.shape}")
    if points.ndim == 3 and points.shape[0] == 3 and points.shape[-1] != 3:
        points = np.transpose(points, (1, 2, 0))
    if points.ndim != 3 or points.shape[-1] != 3:
        raise RuntimeError(f"Unexpected UniDepth points shape: {points.shape}")
    if intrinsics.shape != (3, 3):
        raise RuntimeError(f"Unexpected UniDepth intrinsics shape: {intrinsics.shape}")
    return depth, points, intrinsics


def infer_depth_samples_for_video(
    *,
    video_path: Path,
    sample_times_seconds: list[float] | None = None,
    max_samples: int = DEFAULT_MAX_DEPTH_SAMPLES,
    device: str = "auto",
    model_id: str = DEFAULT_UNIDEPTH_MODEL_ID,
    unidepth_root: Path | None = None,
) -> list[DepthFrameSample]:
    """Run UniDepth on evenly spaced frames from ``video_path``."""
    root = (unidepth_root or default_unidepth_root()).resolve()
    if not is_unidepth_runtime_available(unidepth_root=root):
        return []

    metadata = read_basic_video_metadata(video_path)
    if metadata.frame_count <= 0 or metadata.fps <= 0.0:
        return []

    duration_seconds = max(0.0, (metadata.frame_count - 1) / metadata.fps)
    times = (
        list(sample_times_seconds)
        if sample_times_seconds
        else _select_sample_times(duration_seconds, max_samples=max_samples)
    )
    if not times:
        return []

    samples: list[DepthFrameSample] = []
    with gpu_stage_lock(stage="unidepth"):
        import torch

        model, resolved_device = _load_unidepth_model(
            device=device,
            model_id=model_id,
            unidepth_root=root,
        )
        try:
            with torch.inference_mode():
                for time_seconds in times:
                    frame_index = int(round(max(0.0, time_seconds) * metadata.fps))
                    frame_index = min(frame_index, max(0, metadata.frame_count - 1))
                    frame_rgb = _read_video_frame(video_path, frame_index)
                    if frame_rgb is None:
                        continue
                    source_height, source_width = frame_rgb.shape[:2]
                    rgb = _tensorize_rgb(frame_rgb, device=resolved_device)
                    predictions = model.infer(rgb)
                    depth, points, intrinsics = _depth_predictions_to_arrays(predictions)
                    height, width = depth.shape
                    samples.append(
                        DepthFrameSample(
                            time_seconds=time_seconds,
                            frame_index=frame_index,
                            width=width,
                            height=height,
                            source_width=source_width,
                            source_height=source_height,
                            depth=depth,
                            intrinsics=intrinsics,
                            points=points,
                            model_name=model_id,
                        )
                    )
        finally:
            # A later VLM phase needs nearly all 12 GiB. Retain only host-side
            # weights so the next depth request avoids from_pretrained cost.
            offload_cached_unidepth_models()
    return samples
