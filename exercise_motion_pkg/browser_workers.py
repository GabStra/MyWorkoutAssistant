"""Reuse Chromium on dedicated threads, with a fresh context for every job."""
import atexit
from concurrent.futures import Future, TimeoutError
from contextlib import contextmanager
from functools import wraps
from queue import Queue
import threading
import time
from typing import Any, Callable, Iterator


class BrowserWorkers:
    def __init__(self, workers: int = 4) -> None:
        self._queue: Queue = Queue()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        if workers < 1:
            raise ValueError("Browser worker count must be positive")
        self._workers = workers
        self._closed = False
        self._metrics = {"completedJobs": 0, "failedJobs": 0, "browserLaunchCount": 0,
                         "browserReuseCount": 0, "cleanupFailures": 0,
                         "queueWaitSeconds": 0.0, "jobSeconds": 0.0}

    def run(self, operation: Callable[[], Any]) -> Any:
        if getattr(self._local, "active", False):
            return operation()
        future = Future()
        with self._lock:
            if self._closed:
                raise RuntimeError("Browser workers are closed")
            if not self._threads:
                for index in range(self._workers):
                    thread = threading.Thread(target=self._work, name=f"motion-browser-{index}", daemon=True)
                    self._threads.append(thread)
                    thread.start()
            self._queue.put((future, operation, time.perf_counter()))
        try:
            while True:
                try:
                    return future.result(timeout=0.2)
                except TimeoutError:
                    if future.done():
                        raise
        except BaseException:
            future.cancel()
            raise

    def _work(self) -> None:
        self._local.active = True
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    break
                future, operation, submitted = job
                if not future.set_running_or_notify_cancel():
                    continue
                started = time.perf_counter()
                error = None
                try:
                    result = operation()
                except BaseException as exc:
                    error = exc
                    with self._lock:
                        self._metrics["failedJobs"] += 1
                finally:
                    with self._lock:
                        self._metrics["completedJobs"] += 1
                        self._metrics["queueWaitSeconds"] += started - submitted
                        self._metrics["jobSeconds"] += time.perf_counter() - started
                if error is not None:
                    future.set_exception(error)
                else:
                    future.set_result(result)
        finally:
            self._discard_browser()

    def _discard_browser(self) -> None:
        browser = getattr(self._local, "browser", None)
        runtime = getattr(self._local, "runtime", None)
        self._local.browser = self._local.runtime = None
        for resource, method in ((browser, "close"), (runtime, "stop")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    # Keep the original job error and still stop the driver.
                    with self._lock:
                        self._metrics["cleanupFailures"] += 1

    @contextmanager
    def session(self, launch: Callable[..., Any]) -> Iterator[Any]:
        if not getattr(self._local, "active", False):
            raise RuntimeError("Playwright must stay on its owning browser worker")
        if getattr(self._local, "browser", None) is None:
            from playwright.sync_api import sync_playwright
            self._local.runtime = sync_playwright().start()
            try:
                self._local.browser = launch(self._local.runtime)
                with self._lock:
                    self._metrics["browserLaunchCount"] += 1
            except BaseException:
                self._discard_browser()
                raise
        else:
            with self._lock:
                self._metrics["browserReuseCount"] += 1
        browser = self._local.browser
        initial_contexts = set(browser.contexts)
        try:
            yield browser
        except BaseException:
            # Failed pages or disconnected processes must not poison later jobs.
            self._discard_browser()
            raise
        finally:
            if getattr(self._local, "browser", None) is browser:
                try:
                    for context in list(browser.contexts):
                        if context not in initial_contexts:
                            context.close()
                except Exception:
                    self._discard_browser()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for _thread in self._threads:
                self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=5.0)

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {"workerLimit": self._workers, **self._metrics}


from exercise_motion_pkg.resource_budget import browser_worker_limit

_workers = BrowserWorkers(browser_worker_limit())
atexit.register(_workers.close)


def browser_worker(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        return _workers.run(lambda: function(*args, **kwargs))
    return wrapped


def browser_session(launch: Callable[..., Any]) -> Any:
    return _workers.session(launch)


def run_browser_work(operation: Callable[[], Any]) -> Any:
    return _workers.run(operation)


def browser_worker_metrics() -> dict[str, Any]:
    return _workers.metrics()
