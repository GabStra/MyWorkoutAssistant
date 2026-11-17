"""Bounded independent review questions with reusable, conclusive answers."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
import json
import re
import threading
from typing import Any, Callable

from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_PARALLEL
from exercise_motion_pkg.stage_cache import cache_key, file_identity, load_stage, save_stage, stage_lock

STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION = 1


def with_schema_choice_vocabulary(prompt: str, schema: dict | None) -> str:
    """Decoder constraints do not tell the model which choice tokens mean what."""
    properties = schema.get('properties') if isinstance(schema, dict) else None
    # Nested evidence structures stay with the caller's format description.
    choices = {name: field['enum'] for name, field in
               (properties.items() if isinstance(properties, dict) else [])
               if isinstance(field, dict) and isinstance(field.get('enum'), list) and field['enum']
               and all(value is None or isinstance(value, (str, int, float, bool))
                       for value in field['enum'])}
    if not choices:
        return prompt
    def visible(token):
        text = token if isinstance(token, str) else json.dumps(token)
        return re.search(r'(?<!\w)' + re.escape(text) + r'(?!\w)', prompt) is not None
    if all(visible(name) and all(visible(value) for value in values)
           for name, values in choices.items()):
        return prompt
    return prompt + '\nAllowed JSON choices by field: ' + json.dumps(choices, separators=(',', ':'))

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_executor_workers = 0
_metrics_lock = threading.Lock()
_metrics = {"cacheHits": 0, "questionsAsked": 0, "executorWorkers": 0}


def _deadline_value(deadlines: Any) -> float | None:
    if deadlines is None:
        return None
    getter = getattr(deadlines, "get", None)
    if callable(getter):
        return getter()
    return getattr(deadlines, "value", None)


def question_cache_metrics() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics)


def _default_question_workers() -> int:
    return max(1, int(DEFAULT_LLAMA_CPP_PARALLEL or 1))


def _ensure_question_executor(workers: int) -> ThreadPoolExecutor:
    """Grow the shared pool up to the active VLM parallel slot count."""
    global _executor, _executor_workers
    target = max(_default_question_workers(), max(1, int(workers or 0)))
    with _executor_lock:
        if _executor is None or target > _executor_workers:
            previous = _executor
            _executor = ThreadPoolExecutor(
                max_workers=target,
                thread_name_prefix="source-review-question",
            )
            _executor_workers = target
            with _metrics_lock:
                _metrics["executorWorkers"] = target
            if previous is not None:
                previous.shutdown(wait=False)
        return _executor


def answer_question(*, directory: Path, name: str, prompt: str, frames: list[Path],
                    max_tokens: int, operation: Callable[[], tuple[str, Any]],
                    reusable: Callable[[Any], bool], identity: Any = None,
                    legacy_prompt: str | None = None) -> tuple[str, Any]:
    # Shared answers require an explicit model/policy identity. Preserve image
    # order while allowing identical regenerated artifacts at different paths.
    prompt = with_schema_choice_vocabulary(
        prompt, identity.get('schema') if isinstance(identity, dict) else None)
    request = {"prompt": prompt, "maxTokens": max_tokens,
               "structuredResponsePromptPolicyVersion": STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION}
    image_identity = ([file_identity(frame).get("sha256") for frame in frames]
                      if identity is not None and all(frame.is_file() for frame in frames) else None)
    key = (cache_key({**request, "identity": identity, "images": image_identity}, [])
           if image_identity is not None else cache_key(request, frames))
    legacy_key = _legacy_prompt_key(
        prompt=legacy_prompt, identity=identity, frames=frames, max_tokens=max_tokens,
        image_identity=image_identity)
    checkpoint = directory / name / key / "checkpoint.json"
    with stage_lock(checkpoint):
        cached = load_stage(checkpoint, key)
        if cached is not None and reusable(cached.get("parsed")):
            with _metrics_lock:
                _metrics["cacheHits"] += 1
            return cached["raw"], cached["parsed"]
        if legacy_key is not None and legacy_key != key:
            # Read-only migration: reuse a prior answer only under the exact old
            # prompt+images+policy identity. Never write or approve under it.
            legacy_checkpoint = directory / name / legacy_key / "checkpoint.json"
            with stage_lock(legacy_checkpoint):
                legacy_cached = load_stage(legacy_checkpoint, legacy_key)
            if legacy_cached is not None and reusable(legacy_cached.get("parsed")):
                with _metrics_lock:
                    _metrics["cacheHits"] += 1
                return legacy_cached["raw"], legacy_cached["parsed"]
        with _metrics_lock:
            _metrics["questionsAsked"] += 1
        raw, parsed = operation()
        if reusable(parsed):
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            prompt_path = checkpoint.with_name("prompt.txt")
            prompt_path.write_text(prompt, encoding="utf-8")
            save_stage(checkpoint, key, {"raw": raw, "parsed": parsed}, [prompt_path, *frames])
        return raw, parsed


def _legacy_prompt_key(*, prompt: str | None, identity: Any, frames: list[Path],
                       max_tokens: int, image_identity: list[str | None] | None) -> str | None:
    """Reproduce the exact pre-versioning cache key when a legacy prompt is supplied."""
    if prompt is None:
        return None
    prompt = with_schema_choice_vocabulary(
        prompt, identity.get('schema') if isinstance(identity, dict) else None)
    legacy_request = {"prompt": prompt, "maxTokens": max_tokens,
                      "structuredResponsePromptPolicyVersion": STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION}
    return (cache_key({**legacy_request, "identity": identity, "images": image_identity}, [])
            if image_identity is not None else cache_key(legacy_request, frames))


def run_questions(jobs: dict[str, Callable[[], Any]], caption_images: Callable[..., str]) -> dict[str, Any]:
    owner = getattr(caption_images, "__self__", None)
    if getattr(owner, "_max_active_calls", 1) <= 1:
        return {name: operation() for name, operation in jobs.items()}
    deadlines = getattr(owner, "_candidate_deadlines", None)
    deadline = _deadline_value(deadlines)
    executor = _ensure_question_executor(int(getattr(owner, "_max_active_calls", 0) or 0))

    def invoke(operation: Callable[[], Any]) -> Any:
        # Preserve the candidate budget when independent questions move to
        # review workers. ContextVar values are thread-local by design and do
        # not cross ThreadPoolExecutor boundaries without this explicit handoff.
        previous = _deadline_value(deadlines)
        deadline_token = None
        if deadlines is not None:
            setter = getattr(deadlines, "set", None)
            if callable(setter):
                deadline_token = setter(deadline)
            else:
                deadlines.value = deadline
        try:
            return operation()
        finally:
            if deadline_token is not None:
                deadlines.reset(deadline_token)
            elif deadlines is not None:
                deadlines.value = previous

    futures = {name: executor.submit(invoke, operation) for name, operation in jobs.items()}
    try:
        answers = {}
        for name, future in futures.items():
            while True:
                try:
                    answers[name] = future.result(timeout=0.2)
                    break
                except TimeoutError:
                    if future.done():
                        raise
        return answers
    except BaseException as exc:
        for future in futures.values():
            future.cancel()
        # Running calls keep their owning session's request deadline. Do not
        # start a second review wave while those calls still own its artifacts.
        if isinstance(exc, Exception):
            for future in futures.values():
                if not future.cancelled():
                    while not future.done():
                        threading.Event().wait(0.05)
        raise
