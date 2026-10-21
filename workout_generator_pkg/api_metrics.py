"""Context-local metadata and safe summaries for model API requests."""

from __future__ import annotations

import json
import uuid
import threading
from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar


_scope = ContextVar('workout_api_metrics_scope', default=(None, None))
_budget = ContextVar('workout_planning_budget', default=None)


def start_planning_budget(max_calls=64):
    """Bound model-call count for one planning attempt without an elapsed-time cap."""
    _budget.set({'calls': 0, 'maxCalls': max_calls, 'lock': threading.Lock()})


def remaining_request_timeout(timeout):
    return timeout


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


def request_context_sizes(messages, tools=None):
    """Measure serialized context without retaining prompt text or estimating tokens."""
    def encoded(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    roles, sections, review_sections, seen = {}, {}, {}, set()
    duplicates = duplicate_characters = 0
    for message in messages or []:
        serialized = encoded(message)
        role = message.get('role')
        role = role if role in ('system', 'developer', 'user', 'assistant', 'tool') else 'other'
        roles[role] = roles.get(role, 0) + len(serialized)
        if serialized in seen:
            duplicates += 1
            duplicate_characters += len(serialized)
        seen.add(serialized)
        content = message.get('content')
        if not isinstance(content, str):
            continue
        planning_snapshot = content.startswith('Current planning state')
        if not planning_snapshot and not content.lstrip().startswith('{'):
            continue
        try:
            state = json.loads(content.split('\n', 1)[1] if planning_snapshot else content)
        except (ValueError, IndexError):
            continue
        if not isinstance(state, dict):
            continue
        if not planning_snapshot:
            state = state.get('context', state)
            if not isinstance(state, dict) or 'draft' not in state:
                continue
        measured = sections if planning_snapshot else review_sections
        for key in ('requirements', 'sourceMessages', 'restrictionPolicy', 'currentDraft',
                    'alternativeRepairTask', 'repairTask', 'exerciseCandidates', 'candidateAlternatives',
                    'cachedCandidateIndex', 'trainingEvidence', 'candidateHistorySummaries',
                    'equipmentLoadOptions', 'otherToolResults', 'draft', 'audit', 'history',
                    'historyExecutionContexts', 'equipment', 'progressionCapabilities',
                    'qualifiedRecipeContracts', 'repairCapabilityContract'):
            if key in state:
                measured[key] = measured.get(key, 0) + len(encoded(state[key]))
    return {'messagesCharacters': len(encoded(messages or [])),
            'toolsCharacters': len(encoded(tools or [])), 'messageCharactersByRole': roles,
            'planningStateSectionCharacters': sections, 'reviewContextSectionCharacters': review_sections,
            'duplicateMessages': duplicates,
            'duplicateMessageCharacters': duplicate_characters}


def begin_api_request(model, *, messages=None, tools=None):
    budget = _budget.get()
    if budget is not None:
        with budget['lock']:
            if budget['calls'] >= budget['maxCalls']:
                raise RuntimeError('Planning call budget exhausted. Resume saved work explicitly; do not claim impossibility.')
            budget['calls'] += 1
    request = {'requestId':uuid.uuid4().hex, 'requestStartedAtUTC':datetime.now(timezone.utc).isoformat()}
    if messages is not None:
        request['contextSizes'] = request_context_sizes(messages, tools)
    record_api_metric({'event':'api_request_started','model':model,**request})
    return request


def record_api_metric(metric, logger=None):
    active_logger, active_stage = _scope.get()
    target = logger or active_logger
    if target is None:
        return
    metric = dict(metric)
    if metric.get('event') == 'api_request':
        from .usage_reporting import quote_cost
        metric['requestFinishedAtUTC'] = datetime.now(timezone.utc).isoformat()
        metric['costEstimate'] = quote_cost(metric)
    if active_stage and not metric.get('stage'):
        metric['stage'] = active_stage
    target.log('[api_metric] ' + json.dumps(metric, separators=(',', ':'), sort_keys=True))
