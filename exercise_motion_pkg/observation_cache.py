"""Bounded, session-local reuse of identical endpoint observations."""
from collections import OrderedDict
from concurrent.futures import Future
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable, Any


class ObservationCache:
    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max(1, max_entries)
        self._lock = threading.Lock()
        self._results: OrderedDict[str, str] = OrderedDict()
        self._pending: dict[str, Future[str]] = {}
        self.hits = 0
        self.misses = 0
        self.coalesced = 0

    def get_or_compute(
        self, *, frame_paths: list[Path], prompt: str, settings: dict[str, Any],
        compute: Callable[[], str], cacheable: Callable[[str], bool], timeout: float | None = None,
    ) -> str:
        digest = hashlib.sha256(json.dumps(
            {"prompt": prompt, "settings": settings}, sort_keys=True, default=str,
        ).encode("utf-8"))
        for path in frame_paths:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        key = digest.hexdigest()
        with self._lock:
            if key in self._results:
                self.hits += 1
                self._results.move_to_end(key)
                return self._results[key]
            future = self._pending.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._pending[key] = future
                self.misses += 1
            else:
                self.coalesced += 1
        if not owner:
            return future.result(timeout=timeout)
        try:
            result = compute()
            retain = cacheable(result)
        except BaseException as exc:
            with self._lock:
                self._pending.pop(key, None)
                future.set_exception(exc)
            raise
        with self._lock:
            if retain:
                self._results[key] = result
                while len(self._results) > self.max_entries:
                    self._results.popitem(last=False)
            future.set_result(result)
            self._pending.pop(key, None)
        return result

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self.hits, "misses": self.misses, "coalescedRequests": self.coalesced,
                    "entries": len(self._results), "capacity": self.max_entries}
