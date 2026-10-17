"""Context-local metadata and safe summaries for model API requests."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar


_scope = ContextVar('workout_api_metrics_scope', default=(None, None))


@contextmanager
def api_metrics_scope(logger=None, stage=None):
    """Attach a stage and logger to nested API calls without logging prompt data."""
    current_logger, current_stage = _scope.get()
    token = _scope.set((logger or current_logger, stage or current_stage))
    try:
        yield
    finally:
        _scope.reset(token)


def current_api_metrics_scope():
    return _scope.get()


def record_api_metric(metric, logger=None):
    active_logger, active_stage = _scope.get()
    target = logger or active_logger
    if target is None:
        return
    if active_stage and not metric.get('stage'):
        metric['stage'] = active_stage
    target.log('[api_metric] ' + json.dumps(metric, separators=(',', ':'), sort_keys=True))
