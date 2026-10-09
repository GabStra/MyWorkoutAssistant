
from exercise_motion_pkg.reconstruction_compat import loads_reconstruction_metadata
"""Content-checked checkpoints for expensive deterministic motion stages."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from typing import Any, Iterator

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
PROCESSING_ATTEMPT_ID = uuid.uuid4().hex


def advance_processing_attempt() -> str:
    """Start a new processing attempt so incomplete bake caches must refit."""
    global PROCESSING_ATTEMPT_ID
    PROCESSING_ATTEMPT_ID = uuid.uuid4().hex
    return PROCESSING_ATTEMPT_ID


def file_identity(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        return {"path": str(path), "exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest()}


def cache_key(settings: Any, inputs: list[Path]) -> str:
    payload = {"settings": settings, "inputs": [file_identity(path) for path in inputs]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@contextmanager
def stage_lock(path: Path) -> Iterator[None]:
    with _locks_guard:
        lock = _locks.setdefault(str(path.resolve()), threading.RLock())
    with lock:
        yield


def load_stage(path: Path, key: str) -> dict[str, Any] | None:
    try:
        record = loads_reconstruction_metadata(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("key") != key or not record.get("outputs") or not isinstance(record.get("payload"), dict):
            return None
        verified_output_paths = set()
        for identity in record["outputs"]:
            if not isinstance(identity, dict):
                return None
            identity_path = identity.get("path")
            if not isinstance(identity_path, str) or not identity.get("sha256"):
                return None
            if file_identity(Path(identity_path)) != identity:
                return None
            verified_output_paths.add(Path(identity_path).resolve())
        payload = record["payload"]
        cached_paths = payload.get("paths")
        if cached_paths is not None:
            if not isinstance(cached_paths, list) or not cached_paths:
                return None
            for cached_path in cached_paths:
                if not isinstance(cached_path, str) or Path(cached_path).resolve() not in verified_output_paths:
                    return None
        return payload
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def save_stage(path: Path, key: str, payload: dict[str, Any], outputs: list[Path]) -> None:
    identities = [file_identity(output) for output in outputs]
    if not identities or any(not identity.get("sha256") for identity in identities):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {"key": key, "outputs": identities, "payload": payload},
                stream,
                default=str,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cached_paths(checkpoint: Path, key: str, compute: Any, *, supporting_outputs: Any = None) -> list[Path]:
    """Reuse returned paths only while all consumer-required outputs are intact."""
    with stage_lock(checkpoint):
        cached = load_stage(checkpoint, key)
        path_values = cached.get("paths") if cached is not None else None
        if isinstance(path_values, list) and path_values and all(isinstance(value, str) for value in path_values):
            return [Path(value) for value in path_values]
        paths = compute()
        if paths:
            outputs = [*paths, *(supporting_outputs() if supporting_outputs is not None else [])]
            save_stage(checkpoint, key, {"paths": [str(path) for path in paths]},
                       list(dict.fromkeys(outputs)))
        return paths


def render_with_cpu_slot(compute: Any, *, task_name: str | None = None) -> Any:
    """Bound browser CPU pressure while other workers can submit GPU reviews."""
    from exercise_motion_pkg.browser_workers import run_browser_work
    return run_browser_work(compute, task_name=task_name)
