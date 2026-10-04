"""One candidate budget and resumable, content-addressed anatomy repairs."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import threading
import uuid
from pathlib import Path
from time import monotonic

from .resource_budget import cpu_fit_slot_limit
from .motion_scheduler import cpu_resource_slot
from .stage_cache import stage_lock


_CURRENT = ContextVar('movement_fit_session', default=None)
_SPECULATIVE_FIT = ContextVar('speculative_fit', default=False)
_FIT_GUARD = threading.Condition(threading.Lock())
_FIT_IN_USE = 0
_PRIORITY_WORKSPACES: set[str] = set()
_ACTIVE_SPECULATIVE_WORKSPACES: set[str] = set()
_ABANDONED_SPECULATIVE_WORKSPACES: set[str] = set()

# Threads inside prioritize_fit_workspaces must never block on the priority
# gate: two finalizations can otherwise deadlock (one holds the WHAM-exclusive
# section and waits for a fit slot, the other holds its priority context open
# and waits for the exclusive section). Priority reorders work; it must not
# gate correctness.
_PRIORITY_DEPTH = ContextVar('fit_priority_depth', default=0)

# A stale priority registration (a thread that died between enter and exit,
# or any future leak) must not wedge the pipeline permanently. Priority
# preemption only reorders work, so after this grace a blocked fit proceeds.
PRIORITY_BLOCK_GRACE_SECONDS = 120.0


class SpeculativePrefetchAbandoned(Exception):
    """Speculative prefetch yielded because final validation owns the workspace."""


class FitSlotTimeout(TimeoutError):
    """A fit could not acquire a CPU lane within its available budget."""

    def __init__(self, waited_seconds: float) -> None:
        self.waited_seconds = max(0.0, float(waited_seconds))
        super().__init__(
            "Timed out waiting for a CPU fit lane after "
            f"{self.waited_seconds:.1f}s"
        )


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
        speculative = bool(_SPECULATIVE_FIT.get())
        if not speculative:
            return False
        if _PRIORITY_DEPTH.get() > 0:
            # This thread's own finalization owns the priority: yielding to it
            # would abort the fit that finalization is waiting for.
            return False
        return bool(_PRIORITY_WORKSPACES) or (
            workspace is not None and workspace in _ABANDONED_SPECULATIVE_WORKSPACES
        )


@contextmanager
def prioritize_fit_workspaces(workspaces):
    """Prefer CPU fitting for candidates about to enter final validation."""
    keys = {_workspace_key(workspace) for workspace in workspaces}
    keys.discard(None)
    token = _PRIORITY_DEPTH.set(_PRIORITY_DEPTH.get() + 1)
    try:
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
    finally:
        _PRIORITY_DEPTH.reset(token)


@contextmanager
def cpu_fit_slot(*, timeout_seconds=None):
    """Bound concurrent solvers and stop waiting when the candidate budget expires."""
    global _FIT_IN_USE
    queued = monotonic()
    session = current_fit_session()
    workspace = _workspace_key(session.path.parent) if session is not None and session.path else None
    slot_limit = max(1, int(cpu_fit_slot_limit()))
    wait_budget = timeout_seconds
    if wait_budget is None:
        wait_budget = (
            session.remaining()
            if session is not None
            else DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS
        )
    deadline = queued + max(0.0, float(wait_budget))

    def fit_admission_locked():
        speculative = bool(_SPECULATIVE_FIT.get())
        own_priority = _PRIORITY_DEPTH.get() > 0
        priority = own_priority or (
            workspace is not None and workspace in _PRIORITY_WORKSPACES
        )
        abandoned = (
            speculative
            and workspace is not None
            and workspace in _ABANDONED_SPECULATIVE_WORKSPACES
        )
        priority_blocked = (
            not own_priority
            and (
                (speculative and bool(_PRIORITY_WORKSPACES))
                or (
                    not speculative
                    and _PRIORITY_WORKSPACES
                    and workspace is not None
                    and workspace not in _PRIORITY_WORKSPACES
                )
            )
        )
        return priority, abandoned, priority_blocked

    while True:
        with _FIT_GUARD:
            wait_started = monotonic()
            while True:
                priority, abandoned, priority_blocked = fit_admission_locked()
                if abandoned:
                    raise SpeculativePrefetchAbandoned()
                if priority_blocked and monotonic() - wait_started > PRIORITY_BLOCK_GRACE_SECONDS:
                    # Priority preemption is an ordering optimization; a stale
                    # registration must never wedge the pipeline permanently.
                    print(
                        f"[fit-runtime] priority block exceeded "
                        f"{PRIORITY_BLOCK_GRACE_SECONDS:.0f}s; proceeding",
                        flush=True,
                    )
                    priority_blocked = False
                if _FIT_IN_USE < slot_limit and not priority_blocked:
                    break
                remaining = deadline - monotonic()
                if remaining <= 0.0:
                    waited = monotonic() - queued
                    if session is not None and session.started is not None:
                        session.started += waited
                    raise FitSlotTimeout(waited)
                _FIT_GUARD.wait(timeout=min(0.25, remaining))

        # Do not reserve a fit lane while waiting for shared CPU admission. A
        # final-validation request can then pass queued speculative fits.
        machine_slot = cpu_resource_slot(
            priority=priority,
            timeout_seconds=max(0.0, deadline - monotonic()),
        )
        try:
            machine_slot.__enter__()
        except TimeoutError as exc:
            waited = monotonic() - queued
            if session is not None and session.started is not None:
                session.started += waited
            raise FitSlotTimeout(waited) from exc
        try:
            with _FIT_GUARD:
                priority, abandoned, priority_blocked = fit_admission_locked()
                if abandoned:
                    raise SpeculativePrefetchAbandoned()
                if _FIT_IN_USE >= slot_limit or priority_blocked:
                    continue
                _FIT_IN_USE += 1
            try:
                waited = monotonic() - queued
                if session is not None and session.started is not None:
                    session.started += waited
                yield waited
                return
            finally:
                with _FIT_GUARD:
                    _FIT_IN_USE = max(0, _FIT_IN_USE - 1)
                    _FIT_GUARD.notify_all()
        finally:
            machine_slot.__exit__(None, None, None)


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
        self.cache_namespace = fit_cache_source_namespace()
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
            # Prefetch can finish saving while finalization starts the same
            # candidate. Each writer owns its temporary file; serialize the
            # replacement so they cannot truncate or rename each other's work.
            with stage_lock(self.path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    temporary.write_text(json.dumps({'version': 1, 'namespace': self.cache_namespace,
                                                    'repairs': self.repairs,
                                                    'trajectories': self.trajectories}), encoding='utf-8')
                    temporary.replace(self.path)
                finally:
                    temporary.unlink(missing_ok=True)


def current_fit_session():
    return _CURRENT.get()


def fit_input_key(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# Persisted fitter results depend on this local import closure. Keep local
# imports covered; bake_and_rank.py has its own scoped selected-bake digest.
FIT_CACHE_SOURCE_MODULES = (
    'anatomical_repair.py',
    'articulation_trajectory.py',
    'body_support_observation.py',
    'bilateral_evidence.py',
    'browser_workers.py',
    'cleanup.py',
    'contact_constraints.py',
    'contact_pinning.py',
    'contact_trajectory.py',
    'controlled_motion.py',
    'equipment_constraints.py',
    'fit_runtime.py',
    'foot_contact_observation.py',
    'foot_kinematics.py',
    'ground.py',
    'heel_contacts.py',
    'kinematic_policy.py',
    'limb_bend_repair.py',
    'loop_cycles.py',
    'loop_seam.py',
    'models.py',
    'motion_io.py',
    'motion_placement.py',
    'motion_scheduler.py',
    'physical_validation.py',
    'pose_fidelity.py',
    'preview.py',
    'process_lock.py',
    'repetition_phase.py',
    'render_geometry.py',
    'resource_budget.py',
    'rig_interpolation.py',
    'rig_playback.py',
    'scene_placement.py',
    'sequence_stabilization.py',
    'smpl_joint_names.py',
    'source_pose_evidence.py',
    'stage_cache.py',
    'structural_refinement.py',
    'support_alignment.py',
    'support_geometry.py',
    'temporal_contact_solver.py',
    'temporal_quality.py',
    'whole_body_repair.py',
)


def fit_cache_source_paths():
    """Return source files whose changes invalidate persisted fitter results."""
    return tuple(Path(__file__).with_name(name) for name in FIT_CACHE_SOURCE_MODULES)


def fit_cache_source_namespace(source_paths=None):
    """Bind persisted fit reuse to the fitter and its motion constraint code."""
    paths = (
        fit_cache_source_paths()
        if source_paths is None
        else tuple(Path(path) for path in source_paths)
    )
    digest = hashlib.sha256()
    for path in paths:
        name = path.name.encode('utf-8')
        source = path.read_bytes()
        digest.update(len(name).to_bytes(4, 'big'))
        digest.update(name)
        digest.update(len(source).to_bytes(8, 'big'))
        digest.update(source)
    return digest.hexdigest()


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
