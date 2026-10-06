from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_MODEL = "gemma-4-E4B-it"
DEFAULT_MIN_REP_SECONDS = 3.0
DEFAULT_MAX_REP_SECONDS = 10.0

@dataclass(frozen=True)
class ChunkEstimate:
    exercise: str
    rep_duration_min_sec: float
    rep_duration_max_sec: float
    movement_complexity: str
    chunk_seconds: float
    chunk_overlap_seconds: float
    source: str
    reason: str


def movement_complexity_from_contract(contract: Mapping[str, Any] | None) -> str | None:
    """Derive validation complexity from contract structure, not the exercise name.

    Complexity decides whether repetition-phase completeness is required and
    whether loop-continuity review applies, so it must reflect the requested
    movement's own contract. Returns None when the contract carries no
    structural evidence, leaving the caller on its generic fallback.
    """
    if not isinstance(contract, Mapping):
        return None
    movement_type = str(contract.get("movementType") or "").strip().lower()
    if movement_type in {"hold", "carry"}:
        return "long_duration"
    duration = contract.get("singleExecutionDurationSeconds")
    min_sec = coerce_float(duration.get("minSec")) if isinstance(duration, Mapping) else None
    if min_sec is not None and min_sec >= 15.0:
        return "long_duration"
    topology = contract.get("movementTopology")
    phases = topology.get("phases") if isinstance(topology, Mapping) else None
    phase_count = len(phases) if isinstance(phases, list) else 0
    if phase_count >= 5:
        return "multi_phase"
    if phase_count >= 3:
        return "compound"
    if phase_count >= 1:
        return "simple"
    if movement_type == "transition_sequence":
        return "multi_phase"
    if movement_type in {"repetition", "cyclic"}:
        return "compound"
    return None


def chunk_hint_from_contract(contract: Mapping[str, Any] | None) -> tuple[float, float, str, str] | None:
    """Read the one-execution duration hint from a usable contract."""
    if not isinstance(contract, Mapping):
        return None
    duration = contract.get("singleExecutionDurationSeconds")
    if not isinstance(duration, Mapping):
        return None
    min_sec = coerce_float(duration.get("minSec"))
    max_sec = coerce_float(duration.get("maxSec"))
    if min_sec is None or max_sec is None:
        return None
    complexity = movement_complexity_from_contract(contract) or "compound"
    reason = "Contract estimate for one complete execution of the requested movement."
    return min_sec, max_sec, complexity, reason


def estimate_chunking(
    *,
    exercise_name: str,
    litert_command: str = "",
    model: str = DEFAULT_MODEL,
    backend: str = "gpu",
    use_llm: bool = False,
    exercise_motion_contract: Mapping[str, Any] | None = None,
) -> ChunkEstimate:
    contract_hint = chunk_hint_from_contract(exercise_motion_contract)
    if contract_hint is not None:
        min_sec, max_sec, complexity, reason = contract_hint
        return build_chunk_estimate(
            exercise_name=exercise_name,
            min_sec=min_sec,
            max_sec=max_sec,
            complexity=complexity,
            source="contract",
            reason=reason,
        )

    if use_llm and litert_command:
        payload = call_litert_for_duration_estimate(
            exercise_name=exercise_name,
            litert_command=litert_command,
            model=model,
            backend=backend,
        )
        parsed = parse_duration_payload(payload)
        if parsed is not None:
            min_sec, max_sec, complexity, reason = parsed
            return build_chunk_estimate(
                exercise_name=exercise_name,
                min_sec=min_sec,
                max_sec=max_sec,
                complexity=complexity,
                source="litert_lm",
                reason=reason,
            )

    return build_chunk_estimate(
        exercise_name=exercise_name,
        min_sec=DEFAULT_MIN_REP_SECONDS,
        max_sec=DEFAULT_MAX_REP_SECONDS,
        complexity="unknown",
        source="fallback",
        reason="No contract duration hint or validated exercise-specific estimate was available.",
    )


def frames_for_chunk_seconds(chunk_seconds: float) -> int:
    if chunk_seconds <= 10.0:
        return 16
    if chunk_seconds <= 20.0:
        return 24
    if chunk_seconds <= 40.0:
        return 32
    return 40


def call_litert_for_duration_estimate(
    *,
    exercise_name: str,
    litert_command: str,
    model: str,
    backend: str,
) -> str:
    prompt = (
        "We are choosing video-review chunk settings for finding a usable exercise movement clip.\n"
        "Estimate the visible duration of one complete repetition or execution of the target exercise.\n"
        "Exclude setup time, rest time, talking, walking around, and multiple repetitions.\n"
        "The chunk must be long enough that one clean execution can fit entirely inside a single reviewed chunk, with slack for imperfect chunk boundaries.\n"
        "Use conservative values when unsure.\n"
        "Return JSON only with this schema:\n"
        "{"
        '"rep_duration_min_sec": number, '
        '"rep_duration_max_sec": number, '
        '"movement_complexity": "simple|compound|multi_phase|long_duration", '
        '"reason": "short reason"'
        "}\n"
        f"Exercise: {exercise_name}\n"
    )
    command = [
        litert_command,
        "run",
        model,
        "--backend",
        backend,
        "--prompt",
        prompt,
    ]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        return ""
    return process.stdout.strip()


def parse_duration_payload(raw: str) -> tuple[float, float, str, str] | None:
    payload = extract_json_object(raw)
    if not isinstance(payload, dict):
        return None
    min_sec = coerce_float(payload.get("rep_duration_min_sec"))
    max_sec = coerce_float(payload.get("rep_duration_max_sec"))
    if min_sec is None or max_sec is None:
        return None
    min_sec = clamp(min_sec, 1.0, 60.0)
    max_sec = clamp(max_sec, min_sec, 90.0)
    complexity = str(payload.get("movement_complexity") or "unknown").strip().lower()
    if complexity not in {"simple", "compound", "multi_phase", "long_duration"}:
        complexity = "unknown"
    reason = str(payload.get("reason") or "LiteRT-LM duration estimate.").strip()
    return min_sec, max_sec, complexity, reason


def build_chunk_estimate(
    *,
    exercise_name: str,
    min_sec: float,
    max_sec: float,
    complexity: str,
    source: str,
    reason: str,
) -> ChunkEstimate:
    min_sec = clamp(min_sec, 1.0, 60.0)
    max_sec = clamp(max_sec, min_sec, 90.0)
    chunk_seconds = float(math.ceil(clamp(max_sec * 1.35, 8.0, 90.0)))
    chunk_overlap_seconds = float(math.ceil(clamp(min_sec, 2.0, chunk_seconds * 0.35)))
    return ChunkEstimate(
        exercise=exercise_name,
        rep_duration_min_sec=round(min_sec, 2),
        rep_duration_max_sec=round(max_sec, 2),
        movement_complexity=complexity,
        chunk_seconds=chunk_seconds,
        chunk_overlap_seconds=chunk_overlap_seconds,
        source=source,
        reason=reason,
    )


def extract_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def normalize_exercise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def find_default_litert_command() -> str:
    found = shutil.which("litert-lm")
    return found or "litert-lm"
