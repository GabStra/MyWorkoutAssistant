"""Cross-process coordination for one supervisor-owned llama.cpp vision server.

The shared server (see ``exercise_motion_pkg/SHARED_LLAMA_SERVER.md``) is owned
by the PowerShell supervisor, not by any Python client. Attached processes
coordinate through a session directory that mirrors the warm-worker contract
(``ready.json`` / ``heartbeat.json`` / ``stop`` markers), with one addition the
warm workers never needed: an exclusive-GPU quiesce protocol. GVHMR/RECONSTRUCTION
reconstruction can never co-reside with the ~7.9 GiB vision server, so a
process that needs the whole GPU must first prove that no attached process has
an in-flight VLM request before the server is stopped, and must ask the
supervisor to restart it afterwards.

Everything in this module is file- and OS-level only; the actual server stop is
injected as a callable so tests can fake it without touching real processes.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from exercise_motion_pkg.gpu_lock import process_identity, process_is_running
from exercise_motion_pkg.process_lock import InterProcessFileLock

SHARED_LLAMA_SESSION_DIR_ENV_VAR = "EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR"
INFLIGHT_DIRECTORY_NAME = "in-flight"
STOP_INTENT_FILE_NAME = "stop_intent.json"
START_REQUEST_FILE_NAME = "start_requested.json"
STOPPED_FILE_NAME = "stopped.json"
READY_FILE_NAME = "ready.json"
HEARTBEAT_FILE_NAME = "heartbeat.json"
TRANSITION_LOCK_FILE_NAME = "shared-llama-transition.lock"
TRANSITION_LOCK_TIMEOUT_SECONDS = 240.0
GENERATION_HOLDERS_DIRECTORY_NAME = "generation-holders"
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
    # Windows raises transient WinError 5 when another process still holds an
    # open handle on the destination (observed racing the contract-prefetch
    # session's shutdown); a short bounded retry absorbs it.
    for attempt in range(4):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.25 * (attempt + 1))


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


def write_generation_holder_marker(session_dir: Path, *, holder: str) -> Path:
    """Announce that this process is running an exclusive generation phase.

    Overlapping waves read these markers so a wave about to start its final
    VLM phase does not stop the warm reconstruction worker another wave is
    actively using, and so attached vision clients keep waiting for the
    supervised server restart until the foreign generation releases the GPU.
    """
    holders_dir = session_dir / GENERATION_HOLDERS_DIRECTORY_NAME
    marker = holders_dir / f"{os.getpid()}.json"
    _write_json_atomic(marker, {
        "pid": os.getpid(),
        "processIdentity": process_identity(os.getpid()),
        "holder": holder,
        "startedAtUnixSeconds": time.time(),
    })
    return marker


def clear_generation_holder_marker(session_dir: Path) -> None:
    holders_dir = session_dir / GENERATION_HOLDERS_DIRECTORY_NAME
    _remove(holders_dir / f"{os.getpid()}.json")


def live_foreign_generation_holders(session_dir: Path) -> list[dict[str, object]]:
    """Marker payloads for live generation phases owned by OTHER processes."""
    holders_dir = session_dir / GENERATION_HOLDERS_DIRECTORY_NAME
    holders: list[dict[str, object]] = []
    try:
        marker_paths = sorted(holders_dir.glob("*.json"))
    except OSError:
        return holders
    for marker_path in marker_paths:
        payload = _read_json(marker_path)
        if payload is None:
            continue
        pid = payload.get("pid")
        if isinstance(pid, int) and pid == os.getpid():
            continue
        if not _owner_is_live(payload):
            _remove(marker_path)
            continue
        holders.append(payload)
    return holders


@dataclass(frozen=True)
class InflightSnapshot:
    path: Path
    pid: int
    active_requests: int
    live: bool


class SharedLlamaExclusivePhaseActive(RuntimeError):
    """A foreign exclusive phase still held the shared server past the wait budget.

    Raised by the client-level request publisher's admission gate when a live
    stop-intent owned by another process does not clear within the request's
    wait budget; the request never started, so no server contact was made.
    """


def _publishing_only_stop_server() -> None:
    # Publishing-only coordinators never quiesce: a discovery/contract client
    # must never stop the supervisor's server. Loud failure if that changes.
    raise RuntimeError(
        "shared-llama request publishers never drive the exclusive quiesce protocol"
    )


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
        self._counted_lock = threading.Lock()
        self._counted_active_requests = 0
        self.quiesce_wait_seconds = 0.0
        self.quiesce_count = 0
        self.server_stop_count = 0
        self.restart_request_count = 0
        self.peak_foreign_active_requests = 0

    # --- registration -----------------------------------------------------

    def register(self) -> None:
        with self._counted_lock:
            self.publish_active_requests(self._counted_active_requests)

    def detach(self) -> None:
        """Leave the session: drop our counter and any markers we still own."""
        with self._counted_lock:
            # Keep the counter file while counted requests are still in flight;
            # a removed file would hide them from a foreign drainer.
            if self._counted_active_requests <= 0:
                _remove(self._counter_path)
        intent_path = self.session_dir / STOP_INTENT_FILE_NAME
        with self._transition_lock():
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

    def foreign_stop_intent_live(self) -> bool:
        """True while a *foreign* live process holds an exclusive GPU phase.

        Unlike :meth:`stop_intent_live`, our own intent does not count: the
        client-level publisher runs in processes that deliberately quiesce the
        server (wave exclusive phases), and requests dispatched from inside our
        own exclusive phase - e.g. contract prefetch through an isolated
        attached ranker - must proceed, not deadlock on ourselves.
        """
        payload = _read_json(self.session_dir / STOP_INTENT_FILE_NAME)
        pid = payload.get("pid") if payload is not None else None
        return (
            isinstance(pid, int)
            and pid != os.getpid()
            and _owner_is_live(payload)
        )

    def _owns_stop_intent(self, intent_path: Path) -> bool:
        payload = _read_json(intent_path)
        return payload is not None and payload.get("pid") == os.getpid()

    def _transition_lock(self) -> InterProcessFileLock:
        return InterProcessFileLock(
            self.session_dir / TRANSITION_LOCK_FILE_NAME,
            stage="shared_llama_transition",
            timeout_seconds=TRANSITION_LOCK_TIMEOUT_SECONDS,
            stale_after_seconds=TRANSITION_LOCK_TIMEOUT_SECONDS,
            poll_interval_seconds=self._poll_seconds,
        )

    # --- process-wide counted request scopes ---------------------------------

    def begin_counted_request(self) -> None:
        """Admit one request into this process's in-flight counter."""
        with self._counted_lock:
            self._counted_active_requests += 1
            self.publish_active_requests(self._counted_active_requests)

    def end_counted_request(self) -> None:
        """Release one request from this process's in-flight counter."""
        with self._counted_lock:
            self._counted_active_requests = max(0, self._counted_active_requests - 1)
            self.publish_active_requests(self._counted_active_requests)

    def counted_active_requests(self) -> int:
        with self._counted_lock:
            return self._counted_active_requests

    @contextlib.contextmanager
    def counted_request_scope(self, *, max_wait_seconds: float | None = None):
        """Count one in-flight request, gated on live foreign exclusive phases.

        Mirrors ``LazyLlamaCppVisionSession``'s caption admission: wait while a
        live foreign stop-intent exists (bounded by ``max_wait_seconds``; None
        waits indefinitely), then publish the counter *before* the wrapped
        request starts so the drainer's settle window observes it.
        """
        self._wait_out_foreign_stop_intent(max_wait_seconds)
        self.begin_counted_request()
        try:
            yield
        finally:
            self.end_counted_request()

    def _wait_out_foreign_stop_intent(self, max_wait_seconds: float | None) -> None:
        deadline = (
            time.monotonic() + max(0.0, float(max_wait_seconds))
            if max_wait_seconds is not None
            else None
        )
        while self.foreign_stop_intent_live():
            if deadline is not None and time.monotonic() >= deadline:
                raise SharedLlamaExclusivePhaseActive(
                    "shared llama server held by a foreign exclusive GPU phase for "
                    f"longer than the {max_wait_seconds}s request wait budget"
                )
            time.sleep(self._poll_seconds)

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
        """Publish intent atomically against startup, drain requests, and stop.

        Blocks until every live attached process reports zero in-flight VLM
        requests (two consecutive observations), then invokes the injected
        server stop so the GPU is exclusively ours when this returns. The
        shared transition lock closes the interval in which a supervisor could
        start the server between its admission check and readiness.
        """
        summary = QuiesceSummary()
        started = time.monotonic()
        intent_path = self.session_dir / STOP_INTENT_FILE_NAME
        while True:
            with self._transition_lock():
                acquired = self._try_acquire_stop_intent(intent_path, summary)
                if acquired:
                    with self._counted_lock:
                        # Publish intent and counter within the same transition
                        # as supervisor admission. Startup can never mistake
                        # the intentional intent-before-counter interval for
                        # an inactive handoff.
                        self.publish_active_requests(self._counted_active_requests)
            if acquired:
                break
            time.sleep(self._poll_seconds)
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
        with self._transition_lock():
            if self._owns_stop_intent(intent_path):
                _remove(intent_path)
            self._request_restart()
            with self._counted_lock:
                self.publish_active_requests(self._counted_active_requests)

    def _try_acquire_stop_intent(
        self,
        intent_path: Path,
        summary: QuiesceSummary,
    ) -> bool:
        payload = _read_json(intent_path)
        if (
            payload is not None
            and _owner_is_live(payload)
            and payload.get("pid") != os.getpid()
        ):
            return False
        if payload is not None and not _owner_is_live(payload):
            summary.reclaimed_stale_markers.append(STOP_INTENT_FILE_NAME)
        _write_json_atomic(intent_path, {
            "pid": os.getpid(),
            "processIdentity": self._identity,
            "requestedAtUnixSeconds": time.time(),
        })
        winner = _read_json(intent_path)
        return winner is not None and winner.get("pid") == os.getpid()

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


# ---------------------------------------------------------------------------
# Process-global in-flight request publisher
#
# Ownership rule (see SHARED_LLAMA_SERVER.md): within one process there is
# exactly ONE coordinator per resolved session dir (the registry below), and
# that coordinator owns this pid's `in-flight/<pid>.json` counter file. Wave
# sessions count their admitted requests through the coordinator's counted
# scopes while suspending the client-level publisher on their threads; every
# other shared-server request (discovery, contract prefetch, segment
# detection) is counted automatically by ``LlamaCppVisionClient.caption_images``
# wrapping the request in ``shared_llama_request_scope``. The publisher NEVER
# drives the quiesce protocol - discovery never stops the server - it only
# publishes this process's in-flight count and defers to foreign exclusive
# phases at admission.
# ---------------------------------------------------------------------------

_coordinator_registry_lock = threading.RLock()
_coordinator_registry: dict[Path, SharedLlamaServerCoordinator] = {}

_publisher_state_lock = threading.RLock()
_publisher_coordinator: SharedLlamaServerCoordinator | None = None
_publisher_refcount = 0
_publisher_atexit_registered = False
_publisher_thread_suppression = threading.local()


def shared_llama_coordinator_for(
    session_dir: Path,
    *,
    base_url: str | None,
    stop_server: Callable[[], object] | None = None,
) -> SharedLlamaServerCoordinator:
    """Return the one coordinator this process uses for ``session_dir``.

    Sessions pass their real ``stop_server`` (and may upgrade a coordinator
    first created publishing-only by an attaching ranker); publishing-only
    installers pass ``None`` so they never disarm an existing quiescer.
    """
    with _coordinator_registry_lock:
        coordinator = _coordinator_registry.get(session_dir)
        if coordinator is None:
            coordinator = SharedLlamaServerCoordinator(
                session_dir=session_dir,
                base_url=base_url,
                stop_server=stop_server if stop_server is not None else _publishing_only_stop_server,
            )
            _coordinator_registry[session_dir] = coordinator
        elif stop_server is not None:
            coordinator._stop_server = stop_server
        return coordinator


def reset_shared_llama_process_state_for_tests() -> None:
    """Drop the process-global registry/publisher (test isolation only)."""
    global _publisher_coordinator, _publisher_refcount
    with _publisher_state_lock:
        _publisher_coordinator = None
        _publisher_refcount = 0
    with _coordinator_registry_lock:
        _coordinator_registry.clear()


@contextlib.contextmanager
def suspend_shared_llama_request_publisher():
    """Mark the current thread as already counted by a wave session.

    ``LazyLlamaCppVisionSession`` publishes its admitted-request count itself,
    so the client-level publisher must stay silent for requests made on its
    threads while it owns them - otherwise the same request would be counted
    twice. Re-entrant per thread.
    """
    previous = getattr(_publisher_thread_suppression, "depth", 0)
    _publisher_thread_suppression.depth = previous + 1
    try:
        yield
    finally:
        _publisher_thread_suppression.depth = previous


def _publisher_requests_suppressed() -> bool:
    return getattr(_publisher_thread_suppression, "depth", 0) > 0


def install_shared_llama_request_publisher(
    *,
    base_url: str | None = None,
    session_dir: Path | None = None,
    coordinator: SharedLlamaServerCoordinator | None = None,
) -> SharedLlamaServerCoordinator | None:
    """Attach this process to the shared session dir for request counting.

    Lazily creates the publishing-only coordinator from the first attaching
    client's settings (``resolve_shared_llama_session_dir``), registers it, and
    detaches on interpreter exit. Refcounted: each install must be matched by
    one :func:`detach_shared_llama_request_publisher`. The first installed
    session dir wins for the process - every attaching client is expected to
    resolve the same dir (env var / port default).
    """
    global _publisher_coordinator, _publisher_refcount, _publisher_atexit_registered
    with _publisher_state_lock:
        if coordinator is None:
            if _publisher_coordinator is not None:
                _publisher_refcount += 1
                return _publisher_coordinator
            resolved = resolve_shared_llama_session_dir(session_dir, base_url=base_url)
            coordinator = shared_llama_coordinator_for(resolved, base_url=base_url)
        elif _publisher_coordinator is not None and _publisher_coordinator is not coordinator:
            # A wave session adopting its own coordinator after another dir was
            # installed: keep the first-installed dir, as any ranker would.
            _publisher_refcount += 1
            return _publisher_coordinator
        if _publisher_coordinator is None:
            _publisher_coordinator = coordinator
            _publisher_refcount = 0
            if not _publisher_atexit_registered:
                atexit.register(detach_shared_llama_request_publisher)
                _publisher_atexit_registered = True
        _publisher_refcount += 1
        coordinator.register()
        return _publisher_coordinator


def detach_shared_llama_request_publisher() -> None:
    """Release one publisher attachment; the last one leaves the session dir."""
    global _publisher_coordinator, _publisher_refcount
    with _publisher_state_lock:
        if _publisher_coordinator is None:
            return
        _publisher_refcount = max(0, _publisher_refcount - 1)
        if _publisher_refcount > 0:
            return
        coordinator = _publisher_coordinator
        _publisher_coordinator = None
        _publisher_refcount = 0
    coordinator.detach()


@contextlib.contextmanager
def shared_llama_request_scope(*, timeout_seconds: float | None = None):
    """Wrap one shared-server vision request with this process's counter.

    No-op unless a publisher is installed for this process, or the calling
    thread is already counted by a wave session (suspended). Otherwise: wait
    out any live foreign exclusive phase (bounded by ``timeout_seconds``,
    mirroring the wave session's admission gate), then +1 the in-flight
    counter for the whole request - including exception paths - and -1 it in
    ``finally`` so any quiescing client drains us before stopping the server.
    """
    with _publisher_state_lock:
        coordinator = _publisher_coordinator
    if coordinator is None or _publisher_requests_suppressed():
        yield
        return
    with coordinator.counted_request_scope(max_wait_seconds=timeout_seconds):
        yield

