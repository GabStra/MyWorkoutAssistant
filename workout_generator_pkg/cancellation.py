"""Interrupt network waits without allowing abandoned work to schedule more requests."""

import threading
import time
from contextvars import copy_context


_local = threading.local()


def check_cancelled():
    event = getattr(_local, "cancel_event", None)
    if event is not None and event.is_set():
        raise KeyboardInterrupt


def run_cancellable(function, *args, cancel_event=None, deadline_seconds=None, **kwargs):
    event = cancel_event or getattr(_local, "cancel_event", None) or threading.Event()
    finished = threading.Event()
    started = time.monotonic()
    result, errors = [], []

    def run():
        _local.cancel_event = event
        try:
            check_cancelled()
            result.append(function(*args, **kwargs))
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    if event.is_set():
        raise KeyboardInterrupt
    # An abandoned socket request must not keep the CLI alive at exit.
    context = copy_context()
    threading.Thread(target=context.run, args=(run,), daemon=True).start()
    try:
        while not finished.wait(0.1):
            if deadline_seconds is not None and time.monotonic() - started >= deadline_seconds:
                raise TimeoutError(f"Model request exceeded its {deadline_seconds}s deadline. No automatic retry was started; simplify the request or retry explicitly.")
            if event.is_set():
                raise KeyboardInterrupt
        if event.is_set():
            raise KeyboardInterrupt
        if errors:
            raise errors[0]
        return result[0]
    except KeyboardInterrupt:
        event.set()
        raise
