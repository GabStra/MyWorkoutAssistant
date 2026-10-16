import threading
import time

import pytest

from workout_generator_pkg import cli, exercise_library_tools
from workout_generator_pkg.cancellation import check_cancelled, run_cancellable


def test_cancelled_network_wait_returns_before_request_finishes():
    cancel, release, started, finished = [threading.Event() for _ in range(4)]
    followup = []

    def request():
        started.set()
        try:
            release.wait(5)
            check_cancelled()
            followup.append("another request")
        finally:
            finished.set()

    def cancel_when_started():
        assert started.wait(2)
        cancel.set()

    timer = threading.Thread(target=cancel_when_started, daemon=True)
    timer.start()
    before = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_cancellable(request, cancel_event=cancel)
        assert time.monotonic() - before < 1
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(2)
        timer.join(2)
    assert followup == []


@pytest.mark.parametrize("operation", ["emission", "search"])
def test_parallel_interrupt_does_not_wait_for_active_requests(monkeypatch, operation):
    started, release = threading.Event(), threading.Event()
    requests = []

    def blocked(*args, **kwargs):
        requests.append(args[0] if operation == "emission" else "search")
        started.set()
        release.wait(5)
        return ({"ok": True}, None) if operation == "emission" else ('{"matches":[[]]}', None, None)

    def interrupt(*args, **kwargs):
        assert started.wait(2)
        raise KeyboardInterrupt

    module = cli if operation == "emission" else exercise_library_tools
    monkeypatch.setattr(module, "wait", interrupt)
    if operation == "search":
        monkeypatch.setattr(module, "chat_call", blocked)
    before = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            if operation == "emission":
                cli.parallel_emit_items([("first", {}), ("queued", {})], blocked, "Emit", max_workers=1)
            else:
                module._semantic_matches(object(), ["press"], [{"name": "Press"}])
        assert time.monotonic() - before < 1
        if operation == "emission":
            assert requests == ["first"]
    finally:
        release.set()
