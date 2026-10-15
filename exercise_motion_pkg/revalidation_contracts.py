"""Read current discovery contracts without tying reuse to the current VLM model."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from exercise_motion_pkg.youtube import (
    EXERCISE_MOTION_CONTRACT_CACHE_VERSION, ExerciseEntry,
    exercise_motion_contract_is_usable,
    exercise_motion_contract_uses_candidate_evidence,
    normalize_definition_exercise_motion_contract_response,
)


class RevalidationContractCache:
    def __init__(self, directory: Path):
        self._contracts: dict[str, list[dict[str, Any]]] = {}
        for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(payload, dict):
                    continue
                contract = payload.get('contract')
                if payload.get('schemaVersion') != EXERCISE_MOTION_CONTRACT_CACHE_VERSION or not isinstance(contract, dict):
                    continue
                if exercise_motion_contract_uses_candidate_evidence(contract):
                    continue
                key = str(contract.get('exerciseName') or '').casefold().strip()
                self._contracts.setdefault(key, []).append({**contract, 'cachePath': str(path), 'cacheStatus': 'reused'})
            except (OSError, ValueError, TypeError):
                continue

    def resolve(self, name: str, context: dict[str, Any]) -> dict[str, Any] | None:
        exercise = ExerciseEntry(exercise_id='', name=name, slug='', motion_context=context)
        for contract in self._contracts.get(name.casefold().strip(), []):
            if contract.get('motionContext', {}) != context:
                continue
            if contract.get('contractScope') == 'definition_only' and contract.get('contractPolicyVersion') == 34:
                try:
                    spec = contract.get('observableMotionSpec') or {}
                    contract = normalize_definition_exercise_motion_contract_response(
                        {**contract, 'primaryAxis': spec.get('primaryAxis'),
                         'motionPattern': spec.get('motionPattern')},
                        exercise=exercise, source='migrated_revalidation_contract')
                except (ValueError, AttributeError):
                    continue
            if exercise_motion_contract_is_usable(contract, exercise=exercise):
                return dict(contract)
        return None


def with_revalidation_contract(entry: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    if contract is None:
        return entry
    result = dict(entry)
    result['candidate'] = {**(entry.get('candidate') or {}), 'exerciseMotionContract': contract}
    ranking = dict(entry.get('ranking') or {})
    ranking['payload'] = {**(ranking.get('payload') or {}), 'exerciseMotionContract': contract}
    result['ranking'] = ranking
    return result
