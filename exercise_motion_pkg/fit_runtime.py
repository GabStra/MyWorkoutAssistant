"""One candidate budget and resumable, content-addressed anatomy repairs."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import threading
from pathlib import Path
from time import monotonic

from .resource_budget import cpu_fit_slot_limit


_CURRENT = ContextVar('movement_fit_session', default=None)
_SPECULATIVE_FIT = ContextVar('speculative_fit', default=False)
_FIT_GUARD = threading.Condition(threading.Lock())
_FIT_IN_USE = 0
_PRIORITY_WORKSPACES: set[str] = set()
_ACTIVE_SPECULATIVE_WORKSPACES: set[str] = set()
_ABANDONED_SPECULATIVE_WORKSPACES: set[str] = set()


class SpeculativePrefetchAbandoned(Exception):
    """Speculative prefetch yielded because final validation owns the workspace."""


# Default covers multi-cycle observed fits for longer clips without unbounded waits.
DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS = 360.


def _workspace_key(workspace) -> str | None:
    if workspace is None:
        return None
    return str(Path(workspace).expanduser().resolve())


@contextmanager
def speculative_fit_context():
    """Mark prefetch bake/fit so finalization priority can preempt it."""
    token = _SPECULATIVE_FIT.set(True)
    try:
        yield
    finally:
        _SPECULATIVE_FIT.reset(token)


@contextmanager
def speculative_workspace(workspace):
    """Track speculative prefetch for a workspace across browser-worker threads."""
    key = _workspace_key(workspace)
    if key is None:
        yield
        return
    with _FIT_GUARD:
        _ACTIVE_SPECULATIVE_WORKSPACES.add(key)
        _FIT_GUARD.notify_all()
    try:
        yield
    finally:
        with _FIT_GUARD:
            _ACTIVE_SPECULATIVE_WORKSPACES.discard(key)
            _FIT_GUARD.notify_all()


def active_speculative_workspace(workspace) -> bool:
    key = _workspace_key(workspace)
    if key is None:
        return False
    with _FIT_GUARD:
        return key in _ACTIVE_SPECULATIVE_WORKSPACES


def abandon_speculative_workspace(workspace) -> None:
    """Stop speculative prefetch/fit for a workspace entering final validation."""
    key = _workspace_key(workspace)
    if key is None:
        return
    with _FIT_GUARD:
        _ABANDONED_SPECULATIVE_WORKSPACES.add(key)
        _FIT_GUARD.notify_all()


def speculative_prefetch_abandoned(workspace) -> bool:
    key = _workspace_key(workspace)
    if key is None:
        return False
    with _FIT_GUARD:
        return key in _ABANDONED_SPECULATIVE_WORKSPACES


def fit_should_yield_for_priority() -> bool:
    """Speculative fits yield whenever any final validation needs the CPU fit."""
    session = current_fit_session()
    workspace = _workspace_key(session.path.parent) if session is not None and session.path else None
    with _FIT_GUARD:
        speculative = bool(_SPECULATIVE_FIT.get()) or (
            workspace is not None and workspace in _ACTIVE_SPECULATIVE_WORKSPACES
        )
        if not speculative:
            return False
        return bool(_PRIORITY_WORKSPACES) or (
            workspace is not None and workspace in _ABANDONED_SPECULATIVE_WORKSPACES
        )


@contextmanager
def prioritize_fit_workspaces(workspaces):
    """Prefer CPU fitting for candidates about to enter final validation."""
    keys = {_workspace_key(workspace) for workspace in workspaces}
    keys.discard(None)
    if not keys:
        yield
        return
    with _FIT_GUARD:
        _PRIORITY_WORKSPACES.update(keys)
        _FIT_GUARD.notify_all()
    try:
        yield
    finally:
        with _FIT_GUARD:
            _PRIORITY_WORKSPACES.difference_update(keys)
            _FIT_GUARD.notify_all()


@contextmanager
def cpu_fit_slot():
    """Bound concurrent Python-heavy solvers; queueing consumes no fit budget."""
    global _FIT_IN_USE
    queued = monotonic()
    session = current_fit_session()
    workspace = _workspace_key(session.path.parent) if session is not None and session.path else None
    slot_limit = max(1, int(cpu_fit_slot_limit()))
    with _FIT_GUARD:
        speculative = bool(_SPECULATIVE_FIT.get()) or (
            workspace is not None and workspace in _ACTIVE_SPECULATIVE_WORKSPACES
        )
        # Limited concurrent fits (coding headroom). Speculative work yields the
        # whole fit pool while any final validation is prioritized. Abandoned
        # speculative workspaces must not reacquire.
        while True:
            if (
                speculative
                and workspace is not None
                and workspace in _ABANDONED_SPECULATIVE_WORKSPACES
            ):
                raise SpeculativePrefetchAbandoned()
            blocked_for_priority = (
                speculative and bool(_PRIORITY_WORKSPACES)
            ) or (
                not speculative
                and _PRIORITY_WORKSPACES
                and (workspace is None or workspace not in _PRIORITY_WORKSPACES)
            )
            if _FIT_IN_USE < slot_limit and not blocked_for_priority:
                break
            _FIT_GUARD.wait(timeout=0.25)
        _FIT_IN_USE += 1
        waited = monotonic() - queued
        if session is not None and session.started is not None:
            session.started += waited
    try:
        yield waited
    finally:
        with _FIT_GUARD:
            _FIT_IN_USE = max(0, _FIT_IN_USE - 1)
            _FIT_GUARD.notify_all()


class CandidateFitSession:
    def __init__(self, workspace=None, *, budget_seconds=DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS):
        self.budget_seconds = budget_seconds
        self.started = None
        self.path = Path(workspace)/'anatomy_repair_checkpoint.json' if workspace else None
        self.repairs = {}
        self.trajectories = {}
        self.results = {}
        self.fit_calls = 0
        self.reused_fits = 0
        self.reused_frames = 0
        self.cache_namespace = hashlib.sha256(b''.join(
            Path(__file__).with_name(name).read_bytes() for name in
            ('anatomical_repair.py', 'controlled_motion.py', 'physical_validation.py')
        )).hexdigest()
        if self.path:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if value.get('version') == 1 and value.get('namespace') == self.cache_namespace:
                    repairs = value.get('repairs', {})
                    if isinstance(repairs, dict):
                        self.repairs = repairs
                    trajectories = value.get('trajectories', {})
                    if isinstance(trajectories, dict):
                        self.trajectories = trajectories
            except (OSError, ValueError, AttributeError):
                pass

    def remaining(self):
        if self.started is None:
            self.started = monotonic()
        return max(0., self.budget_seconds-(monotonic()-self.started))

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'version': 1, 'namespace': self.cache_namespace,
                                            'repairs': self.repairs,
                                            'trajectories': self.trajectories}), encoding='utf-8')
            temporary.replace(self.path)


def current_fit_session():
    return _CURRENT.get()


def fit_input_key(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@contextmanager
def candidate_fit_session(workspace=None, *, budget_seconds=DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS):
    existing = current_fit_session()
    if existing is not None:
        yield existing
        return
    session = CandidateFitSession(workspace, budget_seconds=budget_seconds)
    token = _CURRENT.set(session)
    try:
        yield session
    finally:
        try:
            session.save()
        finally:
            _CURRENT.reset(token)
