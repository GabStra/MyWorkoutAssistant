"""One candidate budget and resumable, content-addressed anatomy repairs."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import threading
from pathlib import Path
from time import monotonic


_CURRENT = ContextVar('movement_fit_session', default=None)
_FIT_GUARD = threading.Condition(threading.Lock())
_FIT_BUSY = False
_PRIORITY_WORKSPACES: set[str] = set()
# Default covers multi-cycle observed fits for longer clips without unbounded waits.
DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS = 360.


def _workspace_key(workspace) -> str | None:
    if workspace is None:
        return None
    return str(Path(workspace).expanduser().resolve())


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
    """Avoid competing Python-heavy solvers; queueing consumes no fit budget."""
    global _FIT_BUSY
    queued = monotonic()
    session = current_fit_session()
    workspace = _workspace_key(session.path.parent) if session is not None and session.path else None
    with _FIT_GUARD:
        while _FIT_BUSY or (_PRIORITY_WORKSPACES and workspace not in _PRIORITY_WORKSPACES):
            _FIT_GUARD.wait(timeout=0.25)
        _FIT_BUSY = True
        waited = monotonic() - queued
        if session is not None and session.started is not None:
            session.started += waited
    try:
        yield waited
    finally:
        with _FIT_GUARD:
            _FIT_BUSY = False
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
