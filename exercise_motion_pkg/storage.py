"""Keep enough storage for checkpoints before starting expensive motion work."""
from pathlib import Path
import errno
import shutil


INSUFFICIENT_STORAGE_EXIT_CODE = 75
DEFAULT_STORAGE_RESERVE_BYTES = 2 * 1024**3


class InsufficientStorageError(OSError):
    pass


def is_storage_failure(error: Exception) -> bool:
    return isinstance(error, InsufficientStorageError) or (
        isinstance(error, OSError) and error.errno == errno.ENOSPC)


def require_storage_reserve(path: Path, *, reserve_bytes: int = DEFAULT_STORAGE_RESERVE_BYTES) -> None:
    existing = path.expanduser().resolve()
    while not existing.exists():
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    if free < reserve_bytes:
        raise InsufficientStorageError(
            f"Motion processing stopped before exhausting storage: {free / 1024**3:.2f} GiB free, "
            f"{reserve_bytes / 1024**3:.2f} GiB required at {existing}. "
            "Free space and resume the saved checkpoints.")
