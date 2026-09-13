"""One candidate budget and resumable, content-addressed anatomy repairs."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import threading
from pathlib import Path
from time import monotonic


_CURRENT = ContextVar('movement_fit_session', default=None)
_CPU_FIT_LOCK = threading.RLock()


@contextmanager
def cpu_fit_slot():
    """Avoid competing Python-heavy solvers; queueing consumes no fit budget."""
    queued = monotonic()
    with _CPU_FIT_LOCK:
        waited = monotonic()-queued
        session = current_fit_session()
        if session is not None and session.started is not None:
            session.started += waited
        yield waited


class CandidateFitSession:
    def __init__(self, workspace=None, *, budget_seconds=300.):
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
def candidate_fit_session(workspace=None, *, budget_seconds=300.):
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
