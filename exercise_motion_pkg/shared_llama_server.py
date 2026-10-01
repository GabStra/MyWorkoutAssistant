"""Cross-process coordination for one supervisor-owned llama.cpp vision server.

The shared server (see ``exercise_motion_pkg/SHARED_LLAMA_SERVER.md``) is owned
by the PowerShell supervisor, not by any Python client. Attached processes
coordinate through a session directory that mirrors the warm-worker contract
(``ready.json`` / ``heartbeat.json`` / ``stop`` markers), with one addition the
warm workers never needed: an exclusive-GPU quiesce protocol. GVHMR/WHAM
reconstruction can never co-reside with the ~7.9 GiB vision server, so a
process that needs the whole GPU must first prove that no attached process has
an in-flight VLM request before the server is stopped, and must ask the
supervisor to restart it afterwards.

Everything in this module is file- and OS-level only; the actual server stop is
injected as a callable so tests can fake it without touching real processes.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from exercise_motion_pkg.gpu_lock import process_identity, process_is_running

SHARED_LLAMA_SESSION_DIR_ENV_VAR = "EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR"
INFLIGHT_DIRECTORY_NAME = "in-flight"
STOP_INTENT_FILE_NAME = "stop_intent.json"
START_REQUEST_FILE_NAME = "start_requested.json"
STOPPED_FILE_NAME = "stopped.json"
READY_FILE_NAME = "ready.json"
HEARTBEAT_FILE_NAME = "heartbeat.json"
# Two consecutive all-zero in-flight observations this far apart close the
# admission-vs-drain race: a request admitted just before a foreign stop-intent
# became visible publishes its counter before its HTTP call starts, so the
# second observation catches it unless the request already finished (in which
# case stopping the server is harmless).
DRAIN_SETTLE_SECONDS = 0.25
POLL_SECONDS = 0.25


def _parse_base_url_port(base_url: str | None) -> str:
    try:
        port = int(str(base_url or "").rstrip("/").rsplit(":", 1)[-1])
    except ValueError:
        return "default"
    return str(port)


def default_shared_llama_session_dir(base_url: str | None) -> Path:
    """Deterministic default so every process on one base_url agrees."""
    return (
        Path(tempfile.gettempdir())
        / f"myworkoutassistant-shared-llama-{_parse_base_url_port(base_url)}"
    )


def resolve_shared_llama_session_dir(
    configured: Path | None,
    *,
    base_url: str | None,
) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    raw = os.environ.get(SHARED_LLAMA_SESSION_DIR_ENV_VAR)
    if raw:
        return Path(raw).expanduser().resolve()
    return default_shared_llama_session_dir(base_url)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp_path, path)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _owner_is_live(payload: dict[str, object] | None) -> bool:
    """True when a marker's owning process is still running (this one always is)."""
    if payload is None:
        return False
    pid = payload.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if not process_is_running(pid):
        return False
    expected_identity = payload.get("processIdentity")
    if isinstance(expected_identity, int):
        actual_identity = process_identity(pid)
        if actual_identity is None or actual_identity != expected_identity:
            return False
    return True


@dataclass(frozen=True)
class InflightSnapshot:
    path: Path
    pid: int
    active_requests: int
    live: bool


@dataclass
class QuiesceSummary:
    """Observable outcome of one exclusive quiesce, for lifecycle events."""

    waited_seconds: float = 0.0
    peak_foreign_active_requests: int = 0
    stopped_server: bool = False
    reclaimed_stale_markers: list[str] = field(default_factory=list)


class SharedLlamaServerCoordinator:
    """One attached process's handle on the shared llama.cpp server session dir.

    An attached process publishes its concurrent VLM request count as a counter
    file, blocks new VLM admissions while any live stop-intent exists, and - when
    it needs the whole GPU - runs the drain-then-stop quiesce sequence before
    its exclusive operation and requests a supervisor restart afterwards.
    """

    def __init__(
        self,
        session_dir: Path,
        *,
        base_url: str | None,
        stop_server: Callable[[], object],
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self.session_dir = session_dir
        self.base_url = base_url
        self._stop_server = stop_server
        self._poll_seconds = max(0.05, float(poll_seconds))
        self._inflight_dir = session_dir / INFLIGHT_DIRECTORY_NAME
        self._counter_path = self._inflight_dir / f"{os.getpid()}.json"
        self._identity = process_identity(os.getpid())
        self.quiesce_wait_seconds = 0.0
        self.quiesce_count = 0
        self.server_stop_count = 0
        self.restart_request_count = 0
        self.peak_foreign_active_requests = 0

    # --- registration -----------------------------------------------------

    def register(self) -> None:
        self.publish_active_requests(0)

    def detach(self) -> None:
        """Leave the session: drop our counter and any markers we still own."""
        _remove(self._counter_path)
        intent_path = self.session_dir / STOP_INTENT_FILE_NAME
        if self._owns_stop_intent(intent_path):
            _remove(intent_path)
            self._request_restart()

    def publish_active_requests(self, count: int) -> None:
        _write_json_atomic(self._counter_path, {
            "pid": os.getpid(),
            "processIdentity": self._identity,
            "activeRequests": max(0, int(count)),
            "updatedAtUnixSeconds": time.time(),
        })

    # --- admission gating -------------------------------------------------

    def stop_intent_live(self) -> bool:
        """True while any live process has declared an exclusive GPU phase."""
        return _owner_is_live(_read_json(self.session_dir / STOP_INTENT_FILE_NAME))

    def _owns_stop_intent(self, intent_path: Path) -> bool:
        payload = _read_json(intent_path)
        return payload is not None and payload.get("pid") == os.getpid()

    # --- in-flight observation ---------------------------------------------

    def inflight_snapshots(self) -> list[InflightSnapshot]:
        snapshots: list[InflightSnapshot] = []
        try:
            counter_paths = sorted(self._inflight_dir.glob("*.json"))
        except OSError:
            return snapshots
        for counter_path in counter_paths:
            if counter_path == self._counter_path:
                continue
            payload = _read_json(counter_path)
            if payload is None:
                continue
            pid = payload.get("pid")
            active = payload.get("activeRequests")
            snapshots.append(InflightSnapshot(
                path=counter_path,
                pid=pid if isinstance(pid, int) else 0,
                active_requests=active if isinstance(active, int) else 0,
                live=_owner_is_live(payload),
            ))
        return snapshots

    # --- exclusive quiesce --------------------------------------------------

    def begin_exclusive_phase(self) -> QuiesceSummary:
        """Stop-intent -> drain attached in-flight requests -> stop the server.

        Blocks until every live attached process reports zero in-flight VLM
        requests (two consecutive observations), then invokes the injected
        server stop so the GPU is exclusively ours when this returns.
        """
        summary = QuiesceSummary()
        started = time.monotonic()
        intent_path = self.session_dir / STOP_INTENT_FILE_NAME
        self._acquire_stop_intent(intent_path, summary)
        self.publish_active_requests(0)
        self._drain_foreign_inflight(summary)
        summary.stopped_server = self._stop_shared_server()
        _write_json_atomic(self.session_dir / STOPPED_FILE_NAME, {
            "stoppedByPid": os.getpid(),
            "stoppedAtUnixSeconds": time.time(),
        })
        summary.waited_seconds = time.monotonic() - started
        self.quiesce_wait_seconds += summary.waited_seconds
        self.quiesce_count += 1
        return summary

    def end_exclusive_phase(self) -> None:
        """Release the GPU back to vision work and ask for the server restart."""
        intent_path = self.session_dir / STOP_INTENT_FILE_NAME
        if self._owns_stop_intent(intent_path):
            _remove(intent_path)
        self._request_restart()
        self.publish_active_requests(0)

    def _acquire_stop_intent(self, intent_path: Path, summary: QuiesceSummary) -> None:
        while True:
            payload = _read_json(intent_path)
            if payload is not None and _owner_is_live(payload) and payload.get("pid") != os.getpid():
                # Another process holds the GPU exclusively; its end_exclusive
                # (or its death, which makes the intent stale) releases us.
                time.sleep(self._poll_seconds)
                continue
            if payload is not None and not _owner_is_live(payload):
                summary.reclaimed_stale_markers.append(STOP_INTENT_FILE_NAME)
            _write_json_atomic(intent_path, {
                "pid": os.getpid(),
                "processIdentity": self._identity,
                "requestedAtUnixSeconds": time.time(),
            })
            # Optimistic-lock check: a concurrent writer that landed after us
            # must win; cross-process exclusive phases are additionally
            # serialized by the global GPU stage locks.
            winner = _read_json(intent_path)
            if winner is not None and winner.get("pid") == os.getpid():
                return
            time.sleep(self._poll_seconds)

    def _drain_foreign_inflight(self, summary: QuiesceSummary) -> None:
        settled_observations = 0
        while True:
            snapshots = self.inflight_snapshots()
            # Crashed clients leave their counters behind; drop them so the
            # directory stays meaningful and a recycled pid starts clean.
            for snapshot in snapshots:
                if not snapshot.live:
                    _remove(snapshot.path)
                    summary.reclaimed_stale_markers.append(snapshot.path.name)
            if sum(
                snapshot.active_requests for snapshot in snapshots if snapshot.live
            ) == 0:
                settled_observations += 1
                if settled_observations >= 2:
                    return
                time.sleep(DRAIN_SETTLE_SECONDS)
                continue
            self.peak_foreign_active_requests = max(
                self.peak_foreign_active_requests,
                sum(s.active_requests for s in snapshots if s.live),
            )
            settled_observations = 0
            time.sleep(self._poll_seconds)

    def _stop_shared_server(self) -> bool:
        try:
            self._stop_server()
        except Exception:
            # The stop helper is best-effort (netstat + taskkill); a failed
            # kill surfaces immediately when the exclusive phase OOMs, which
            # is louder and more actionable than blocking here.
            return False
        self.server_stop_count += 1
        return True

    def _request_restart(self) -> None:
        _write_json_atomic(self.session_dir / START_REQUEST_FILE_NAME, {
            "requestedByPid": os.getpid(),
            "processIdentity": self._identity,
            "requestedAtUnixSeconds": time.time(),
        })
        self.restart_request_count += 1

    # --- observability -------------------------------------------------------

    def metrics(self) -> dict[str, object]:
        return {
            "sharedVisionQuiesceCount": self.quiesce_count,
            "sharedVisionQuiesceWaitSeconds": round(self.quiesce_wait_seconds, 3),
            "sharedVisionServerStopCount": self.server_stop_count,
            "sharedVisionRestartRequestCount": self.restart_request_count,
            "sharedVisionPeakForeignActiveRequests": self.peak_foreign_active_requests,
        }
