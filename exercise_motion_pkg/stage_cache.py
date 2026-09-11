"""Content-checked checkpoints for expensive deterministic motion stages."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import threading
import uuid
from typing import Any, Iterator

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
PROCESSING_ATTEMPT_ID = uuid.uuid4().hex


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
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("key") != key or not record.get("outputs") or not isinstance(record.get("payload"), dict):
            return None
        for identity in record["outputs"]:
            if not identity.get("sha256") or file_identity(Path(identity["path"])) != identity:
                return None
        return record["payload"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def save_stage(path: Path, key: str, payload: dict[str, Any], outputs: list[Path]) -> None:
    identities = [file_identity(output) for output in outputs]
    if not identities or any(not identity.get("sha256") for identity in identities):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps({"key": key, "outputs": identities, "payload": payload},
                                        default=str), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def cached_paths(checkpoint: Path, key: str, compute: Any) -> list[Path]:
    with stage_lock(checkpoint):
        cached = load_stage(checkpoint, key)
        if cached is not None:
            return [Path(value) for value in cached["paths"]]
        paths = compute()
        if paths:
            save_stage(checkpoint, key, {"paths": [str(path) for path in paths]}, paths)
        return paths


def render_with_cpu_slot(compute: Any) -> Any:
    """Bound browser CPU pressure while other workers can submit GPU reviews."""
    from exercise_motion_pkg.browser_workers import run_browser_work
    return run_browser_work(compute)
