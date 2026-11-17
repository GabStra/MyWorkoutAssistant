"""Direct, resumable compilation for an explicitly prescribed workout plan."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)


class _MetricCollector:
    def __init__(self):
        self.lines = []

    def log(self, message):
        self.lines.append(message)

    def events(self):
        events = []
        for line in self.lines:
            marker = line.find('[api_metric] ')
            if marker < 0:
                continue
            try:
                event = json.loads(line[marker + len('[api_metric] '):])
            except (TypeError, ValueError):
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


def run_prescribed_plan(
    source_path, library, equipment, *, training_history=None,
    allow_educated_load_guesses=True, state_dir=None, output_dir=None,
    output_file=None, source_loader=None, compiler=None, extract=None, client=None,
    audit_requirements=None, model_settings=None, logger=None,
):
    """Load explicit source facts, refresh compatibility, and compile a PlanIndex.

    Source facts are cached independently from library and history dependent
    mapping. A changed source invalidates extraction; any changed identity
    invalidates export and recompiles from the current structured plan.
    """
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    collector = _MetricCollector()
    stage_started = time.monotonic()
    repair_attempts = 0
    source_path = Path(source_path).resolve()
    try:
        initial_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError:
        initial_source_hash = _hash(str(source_path))
    state_root = (Path(state_dir) if state_dir else
                  Path(output_dir or os.getcwd()) / "prescribed_plans" / initial_source_hash[:16])
    facts_path = state_root / "source_facts.json"
    plan_path = state_root / "active_plan.json"
    diagnostics_path = state_root / "compatibility.json"
    identity_path = state_root / "identity.json"
    metrics_path = state_root / "workflow_metrics.json"

    from .prescribed_source import (extract_prescribed_facts, load_prescribed_source,
                                    map_prescribed_facts)
    custom_source_loader = source_loader is not None
    if source_loader is None:
        source_loader = load_prescribed_source
    if compiler is None:
        from .generation_pipeline import compile_plan_index as compiler
    from .planning_tools import library_fingerprint

    identities = {}
    try:
        raw_hash = initial_source_hash
        library_identity = library_fingerprint(library)
        history_identity = getattr(training_history, "fingerprint", None) or _hash(None)
        if model_settings is None:
            try:
                from .llm_config import resolve_llm_endpoint
                endpoint = resolve_llm_endpoint()
                effective_model_settings = {'model': endpoint.model, 'baseUrl': endpoint.base_url}
            except Exception:
                effective_model_settings = {}
        else:
            effective_model_settings = model_settings
        # Version 2 adds explicit recurring-session/track facts.
        extractor_identity = _hash({'version': 2, 'model': effective_model_settings})
        settings = {
            "model": effective_model_settings,
            "allowEducatedLoadGuesses": bool(allow_educated_load_guesses),
        }
        identities = {
            "source": raw_hash,
            "library": library_identity,
            "history": history_identity,
            "model": _hash(settings.get("model")),
            "settings": _hash(settings),
        }
        previous_identity = json.loads(identity_path.read_text(encoding='utf-8')) if identity_path.is_file() else {}
        previous_plan_hash = previous_identity.get('planHash')
        source_changed = bool(previous_identity.get('source') and previous_identity['source'] != raw_hash)
        if source_changed and plan_path.is_file():
            result = {
                "success": False, "filepath": None,
                "error": "Source changed since this state directory's PlanIndex was created; the existing editable plan was preserved.",
                "plan_file": str(plan_path), "diagnostics_file": str(diagnostics_path),
            }
            _write_json(diagnostics_path, {"error": result["error"],
                "sourceHash": raw_hash, "previousSourceHash": previous_identity.get("source")})
            _write_metrics(metrics_path, started, identities, result, started_at=started_at)
            return result
        cached = json.loads(facts_path.read_text(encoding='utf-8')) if facts_path.is_file() else {}
        facts_reused = (source_path.suffix.lower() not in {'.json'}
                        and cached.get('sourceHash') == raw_hash
                        and cached.get('extractorIdentity') == extractor_identity)
        current_facts_hash = _hash(cached.get('extracted')) if cached else None
        facts_edited = bool(facts_reused and (
            (previous_identity.get('factsHash') and previous_identity['factsHash'] != current_facts_hash)
            or (cached.get('factsDigest') and cached['factsDigest'] != current_facts_hash)))
        compile_started = None
        with_stage_start = time.monotonic()
        existing_plan = json.loads(plan_path.read_text(encoding='utf-8')) if plan_path.is_file() else None
        user_edited_plan = (existing_plan is not None and previous_plan_hash is not None
                            and _hash(existing_plan) != previous_plan_hash)
        repair_attempts = int(bool(user_edited_plan or facts_edited))
        if user_edited_plan and source_path.suffix.lower() == '.json' and not custom_source_loader:
            loaded = {"planIndex": existing_plan, "source": {"sha256": raw_hash}, "unresolved": []}
        elif custom_source_loader:
            loaded = source_loader(source_path, library, extract=extract)
        elif source_path.suffix.lower() == '.json':
            # Structured PlanIndex input does not need source extraction.
            loaded = source_loader(source_path, library, extract=extract)
        else:
            if facts_reused:
                extracted = cached['extracted']
                if facts_edited:
                    cached['factsDigest'] = _hash(cached.get('extracted'))
                    _write_json(facts_path, cached)
            else:
                from .api_metrics import api_metrics_scope
                if extract is None:
                    import httpx
                    from .llm_config import build_llm_client
                    client = client or build_llm_client(
                        http_client=httpx.Client(timeout=httpx.Timeout(None, connect=60.0)), max_retries=0)
                with api_metrics_scope(collector, 'prescribed_source_interpretation'):
                    extracted = extract_prescribed_facts(source_path, extract=extract, client=client)
                _write_json(facts_path, {'sourceHash': raw_hash,
                    'extractorIdentity': extractor_identity, 'extracted': extracted,
                    'factsDigest': _hash(extracted)})
                cached = {'sourceHash': raw_hash, 'extractorIdentity': extractor_identity,
                          'extracted': extracted, 'factsDigest': _hash(extracted)}
            loaded = map_prescribed_facts(extracted, library)
        if not isinstance(loaded, dict):
            raise ValueError("Prescribed source adapter must return a PlanIndex dictionary.")
        if not isinstance(loaded.get("planIndex"), dict) and not user_edited_plan:
            unresolved = loaded.get('unresolved') or []
            if unresolved:
                editable_path = plan_path if plan_path.is_file() else (facts_path if facts_path.is_file() else source_path)
                _write_json(diagnostics_path, {"unresolved": unresolved, "sourceHash": raw_hash,
                    "editableFile": str(editable_path)})
                result = {"success": False, "filepath": None,
                    "error": "Prescribed source needs definition or equipment mapping.",
                    "plan_file": str(editable_path), "editable_file": str(editable_path),
                    "diagnostics_file": str(diagnostics_path),
                    "unresolved": unresolved}
                identities['factsHash'] = _hash(cached.get('extracted')) if cached else None
                _write_json(identity_path, identities)
                _write_metrics(metrics_path, started, identities, result, collector.events(),
                    {"sourceInterpretation": time.monotonic() - stage_started},
                    repair_attempts=repair_attempts, started_at=started_at)
                return result
            raise ValueError("Prescribed source adapter did not return a PlanIndex dictionary.")
        source = loaded.get("source") or {}
        source_identity = source.get("sha256") or source.get("hash") or raw_hash
        identities["source"] = source_identity
        identities['factsHash'] = _hash(cached.get('extracted')) if cached else None
        plan_index = loaded.get('planIndex')
        if user_edited_plan:
            # Preserve explicit operator repairs. The deterministic compiler
            # reruns all current library/history and app-package gates below.
            plan_index = existing_plan
        _write_json(plan_path, plan_index)
        unresolved = [] if user_edited_plan else (loaded.get("unresolved") or [])
        if unresolved:
            _write_json(diagnostics_path, {"unresolved": unresolved, "identities": identities})
            result = {"success": False, "filepath": None,
                      "error": "Prescribed source needs definition or equipment mapping; edit active_plan.json and resolve compatibility diagnostics.",
                      "plan_file": str(plan_path), "diagnostics_file": str(diagnostics_path),
                      "unresolved": unresolved}
            identities['planHash'] = _hash(plan_index)
            _write_metrics(metrics_path, started, identities, result, collector.events(),
                           {'sourceInterpretation': time.monotonic() - with_stage_start},
                           reused_stages=['sourceFacts'] if facts_reused else [],
                           repair_attempts=repair_attempts, started_at=started_at)
            _write_json(identity_path, identities)
            return result

        _write_json(diagnostics_path, {"unresolved": [], "identities": identities})
        identities['planHash'] = _hash(plan_index)
        _write_json(identity_path, identities)
        protected = {source_path.resolve(), plan_path.resolve(), facts_path.resolve(),
                     diagnostics_path.resolve(), identity_path.resolve(), metrics_path.resolve()}
        if output_file and Path(output_file).resolve() in protected:
            raise ValueError('The package output path must not overwrite the source or prescribed state files.')
        # Never serve an earlier output: deterministic compilation always runs
        # after loading the current source and refreshing compatibility.
        compile_started = time.monotonic()
        result = compiler(
            plan_index, equipment, training_history=training_history,
            allow_educated_load_guesses=allow_educated_load_guesses,
            output_dir=output_dir, output_file=output_file, logger=logger,
            audit_requirements=audit_requirements,
        )
        result = dict(result or {})
        result.setdefault("plan_file", str(plan_path))
        result.setdefault("diagnostics_file", str(diagnostics_path))
        identities['planHash'] = _hash(plan_index)
        _write_json(identity_path, identities)
        _write_metrics(metrics_path, started, identities, result, collector.events(),
                       {'sourceInterpretation': compile_started - with_stage_start,
                        'deterministicCompile': time.monotonic() - compile_started},
                       reused_stages=['sourceFacts'] if facts_reused else [],
                       repair_attempts=repair_attempts, started_at=started_at)
        return result
    except Exception as error:
        result = {"success": False, "filepath": None, "error": str(error),
                  "plan_file": str(plan_path), "diagnostics_file": str(diagnostics_path)}
        _write_json(diagnostics_path, {"error": str(error)})
        _write_metrics(metrics_path, started, identities, result, collector.events(),
                       {'sourceInterpretation': time.monotonic() - stage_started},
                       repair_attempts=repair_attempts, started_at=started_at)
        return result


def _write_metrics(path, started, identities, result, api_events=(), stage_times=None,
                   reused_stages=(), repair_attempts=0, started_at=None):
    from .usage_reporting import build_workflow_metrics
    finished_at = datetime.now(timezone.utc).isoformat()
    metrics = build_workflow_metrics(api_events, total_wall_seconds=time.monotonic() - started,
        stage_times=stage_times, identity=identities, valid_package=bool(result.get("success")),
        reused_stages=reused_stages, repair_attempts=repair_attempts)
    attempts_dir = Path(path).parent / 'attempts'
    attempts_dir.mkdir(parents=True, exist_ok=True)
    index_path = attempts_dir / 'index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.is_file() else {'attempts': []}
    attempt_id = uuid.uuid4().hex
    receipt = {**metrics, 'attemptId': attempt_id, 'startedAtUTC': started_at,
               'finishedAtUTC': finished_at}
    same_source = [item for item in index.get('attempts', [])
                   if isinstance(item, dict) and item.get('identity', {}).get('source') == identities.get('source')]
    previous = []
    for item in same_source:
        previous_path = attempts_dir / f"{item.get('attemptId')}.json"
        if previous_path.is_file():
            saved = json.loads(previous_path.read_text(encoding='utf-8'))
            if saved.get('identity', {}).get('source') == identities.get('source'):
                previous.append(saved)
    all_receipts = [*previous, receipt]
    first_started = min((item.get('startedAtUTC') for item in all_receipts if item.get('startedAtUTC')), default=started_at)
    elapsed_since_first = max(0.0, (datetime.fromisoformat(finished_at) -
        datetime.fromisoformat(first_started)).total_seconds())
    metrics['attemptId'] = attempt_id
    metrics['attemptReceipt'] = str(attempts_dir / f'{attempt_id}.json')
    metrics['attemptCountForSource'] = len(all_receipts)
    metrics['latestRunWallSeconds'] = metrics['totalWallSeconds']
    metrics['cumulativeRunWallSecondsForSource'] = round(sum(item.get('totalWallSeconds', 0) for item in all_receipts), 3)
    metrics['elapsedSinceFirstAttemptSecondsForSource'] = round(elapsed_since_first, 3)
    metrics['elapsedSinceFirstAttemptNote'] = (
        'Elapsed time includes idle time between attempts, including operator repair time; '
        'cumulativeRunWallSecondsForSource sums only measured run durations.')
    metrics['cumulativeRepairAttemptsForSource'] = sum(item.get('repairAttempts', 0) for item in all_receipts)
    metrics['cumulativeApiCallsForSource'] = (sum(item.get('apiCalls', 0) for item in all_receipts)
        if all(isinstance(item.get('apiCalls'), int) for item in all_receipts) else None)
    token_keys = ('promptTokens', 'completionTokens', 'reasoningTokens', 'cacheHitTokens', 'cacheMissTokens')
    metrics['cumulativeTokenTotalsForSource'] = {
        key: (sum(item.get('tokenTotals', {}).get(key, 0) for item in all_receipts)
              if all(isinstance(item.get('tokenTotals', {}).get(key), int) for item in all_receipts) else None)
        for key in token_keys}
    receipt.update({key: value for key, value in metrics.items() if key not in receipt})
    _write_json(attempts_dir / f'{attempt_id}.json', receipt)
    index.setdefault('attempts', []).append({'attemptId': attempt_id, 'identity': identities,
        'startedAtUTC': started_at, 'finishedAtUTC': finished_at,
        'totalWallSeconds': metrics['totalWallSeconds'], 'repairAttempts': metrics['repairAttempts'],
        'apiCalls': metrics['apiCalls']})
    _write_json(index_path, index)
    _write_json(path, metrics)
