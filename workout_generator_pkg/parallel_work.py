"""Run independent proposals concurrently; publish results only in the caller thread."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
import threading

from .cancellation import run_cancellable, check_cancelled


def parallel_proposals(jobs, on_result=None):
    cancelled = threading.Event()
    pool = ThreadPoolExecutor(max_workers=min(3, len(jobs))) if jobs else None
    results = {}
    failures = []
    try:
        pending = {pool.submit(copy_context().run, run_cancellable, function,
                               cancel_event=cancelled): key for key, function in jobs}
        while pending:
            check_cancelled()
            done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                key = pending.pop(future)
                try:
                    results[key] = future.result()
                except Exception as error:
                    failures.append(error)
                    continue
                if on_result:
                    on_result(key, results[key])
        if failures:
            raise failures[0]
        return {key: results[key] for key, _ in jobs}
    finally:
        cancelled.set()
        if pool:
            pool.shutdown(wait=False, cancel_futures=True)
