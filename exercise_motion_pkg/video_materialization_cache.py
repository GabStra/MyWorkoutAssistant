"""Reuse the first verified encoding across workspaces; callers own frame clocks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from exercise_motion_pkg.process_lock import InterProcessFileLock
from exercise_motion_pkg.stage_cache import file_identity, load_stage, save_stage, stage_lock

_OPERATION = "video-materialization"
_SCHEMA_VERSION = 1
_LOCK_TIMEOUT_SECONDS = 600.0


class MaterializationNotProduced(RuntimeError):
    """The owning encoder could not produce a usable artifact for this key."""


def default_video_materialization_cache_dir(output_path: Path) -> Path:
    """Place reusable bytes inside the repository's global reconstruction cache."""
    from .pipeline import default_reconstruction_global_cache_dir

    return default_reconstruction_global_cache_dir(output_path.parent) / _OPERATION


def _strict_settings(settings: Mapping[str, Any]) -> str:
    if not isinstance(settings, Mapping) or not settings:
        raise ValueError("Video materialization settings must be a non-empty mapping.")
    try:
        return json.dumps(
            dict(settings),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Video materialization settings must be strict JSON.") from error


def _materialization_key(
    source_sha256: str,
    settings: Mapping[str, Any],
    suffix: str,
) -> str:
    payload = {
        "schemaVersion": _SCHEMA_VERSION,
        "sourceSha256": source_sha256,
        "settings": _strict_settings(settings),
        "suffix": suffix,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def materialize_cached(
    *,
    source_path: Path,
    output_path: Path,
    settings: Mapping[str, Any],
    cache_dir: Path,
    producer: Callable[[Path], None],
) -> Path:
    """Key by source content and encoder settings, never paths or clock receipts."""
    requested_output = Path(output_path).expanduser()
    resolved_source = Path(source_path).expanduser().resolve()
    resolved_output = requested_output.resolve()
    if resolved_source == resolved_output:
        raise ValueError("Video materialization output must differ from its source.")
    source_sha256 = file_identity(resolved_source).get("sha256")
    if not isinstance(source_sha256, str):
        raise FileNotFoundError(resolved_source)
    suffix = resolved_output.suffix.lower()
    if not suffix:
        raise ValueError("Video materialization output must have a file suffix.")

    key = _materialization_key(source_sha256, settings, suffix)
    cache_dir = Path(cache_dir).expanduser().resolve()
    record_path = cache_dir / f"{key}.json"
    cached_output = cache_dir / f"{key}{suffix}"
    with stage_lock(record_path), InterProcessFileLock(
        cache_dir / f"{key}.lock",
        stage=_OPERATION,
        timeout_seconds=_LOCK_TIMEOUT_SECONDS,
        stale_after_seconds=0.,
    ):
        cached = load_stage(record_path, key)
        cached_paths = cached.get("paths") if isinstance(cached, dict) else None
        record_is_current = (
            isinstance(cached_paths, list)
            and len(cached_paths) == 1
            and isinstance(cached_paths[0], str)
            and Path(cached_paths[0]).resolve() == cached_output
        )
        if not record_is_current:
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = cached_output.with_name(
                f"{cached_output.stem}.{uuid.uuid4().hex}.tmp{suffix}"
            )
            try:
                producer(temporary)
                if not temporary.is_file() or temporary.stat().st_size <= 0:
                    raise MaterializationNotProduced(
                        f"Producer created no non-empty output: {temporary}"
                    )
                os.replace(temporary, cached_output)
            finally:
                temporary.unlink(missing_ok=True)
            save_stage(
                record_path,
                key,
                {"paths": [str(cached_output)], "sourceSha256": source_sha256},
                [cached_output],
            )
            if load_stage(record_path, key) is None:
                raise MaterializationNotProduced(
                    f"Materialization record failed verification: {record_path}"
                )
        if resolved_output != cached_output:
            _atomic_copy(cached_output, resolved_output)
    return requested_output
