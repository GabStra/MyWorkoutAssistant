from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


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


KNOWN_DURATION_HINTS: dict[str, tuple[float, float, str, str]] = {
    "pull up": (2.0, 6.0, "simple", "A pull-up is usually a short single-phase vertical pulling repetition."),
    "pull-up": (2.0, 6.0, "simple", "A pull-up is usually a short single-phase vertical pulling repetition."),
    "push up": (2.0, 6.0, "simple", "A push-up is usually a short controlled bodyweight repetition."),
    "push-up": (2.0, 6.0, "simple", "A push-up is usually a short controlled bodyweight repetition."),
    "squat": (3.0, 8.0, "compound", "A squat needs enough time for descent, bottom position, and ascent."),
    "deadlift": (2.0, 7.0, "compound", "A deadlift is usually a short hinge lift with setup excluded."),
    "bench press": (2.0, 7.0, "compound", "A bench press repetition includes controlled lowering and pressing."),
    "clean": (4.0, 12.0, "multi_phase", "A clean includes pull, catch, and recovery phases."),
    "clean and jerk": (6.0, 18.0, "multi_phase", "A clean and jerk includes clean, recovery, dip, drive, catch, and stabilization."),
    "snatch": (4.0, 14.0, "multi_phase", "A snatch includes pull, turnover, catch, and stabilization."),
    "turkish get up": (20.0, 60.0, "long_duration", "A Turkish get-up is a long multi-position floor-to-standing movement."),
    "turkish get-up": (20.0, 60.0, "long_duration", "A Turkish get-up is a long multi-position floor-to-standing movement."),
}


def estimate_chunking(
    *,
    exercise_name: str,
    litert_command: str,
    model: str = DEFAULT_MODEL,
    backend: str = "gpu",
    use_llm: bool = True,
) -> ChunkEstimate:
    normalized = normalize_exercise_name(exercise_name)
    known = KNOWN_DURATION_HINTS.get(normalized)
    if known is not None:
        min_sec, max_sec, complexity, reason = known
        return build_chunk_estimate(
            exercise_name=exercise_name,
            min_sec=min_sec,
            max_sec=max_sec,
            complexity=complexity,
            source="known_hint",
            reason=reason,
        )

    if use_llm:
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
        reason="No validated exercise-specific estimate was available.",
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
