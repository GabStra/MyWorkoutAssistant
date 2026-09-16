"""Bounded independent review questions with reusable, conclusive answers."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
import threading
from typing import Any, Callable

from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_PARALLEL
from exercise_motion_pkg.stage_cache import cache_key, load_stage, save_stage, stage_lock

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_executor_workers = 0
_metrics_lock = threading.Lock()
_metrics = {"cacheHits": 0, "questionsAsked": 0, "executorWorkers": 0}


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
                    reusable: Callable[[Any], bool]) -> tuple[str, Any]:
    key = cache_key({"prompt": prompt, "maxTokens": max_tokens}, frames)
    checkpoint = directory / name / key / "checkpoint.json"
    with stage_lock(checkpoint):
        cached = load_stage(checkpoint, key)
        if cached is not None and reusable(cached.get("parsed")):
            with _metrics_lock:
                _metrics["cacheHits"] += 1
            return cached["raw"], cached["parsed"]
        with _metrics_lock:
            _metrics["questionsAsked"] += 1
        raw, parsed = operation()
        if reusable(parsed):
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            prompt_path = checkpoint.with_name("prompt.txt")
            prompt_path.write_text(prompt, encoding="utf-8")
            save_stage(checkpoint, key, {"raw": raw, "parsed": parsed}, [prompt_path, *frames])
        return raw, parsed


def run_questions(jobs: dict[str, Callable[[], Any]], caption_images: Callable[..., str]) -> dict[str, Any]:
    owner = getattr(caption_images, "__self__", None)
    if getattr(owner, "_max_active_calls", 1) <= 1:
        return {name: operation() for name, operation in jobs.items()}
    deadlines = getattr(owner, "_candidate_deadlines", None)
    deadline = getattr(deadlines, "value", None)
    executor = _ensure_question_executor(int(getattr(owner, "_max_active_calls", 0) or 0))

    def invoke(operation: Callable[[], Any]) -> Any:
        # Session deadlines are thread-local; preserve the candidate's budget
        # when its independent questions move to shared review workers.
        previous = getattr(deadlines, "value", None)
        if deadlines is not None:
            deadlines.value = deadline
        try:
            return operation()
        finally:
            if deadlines is not None:
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
