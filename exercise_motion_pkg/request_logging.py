"""Route concurrent service tasks to their owning request log."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from contextvars import ContextVar


_REQUEST_STREAM = ContextVar('motion_request_log', default=None)


class _RequestStream:
    def __init__(self, fallback):
        self.fallback = fallback

    def write(self, text):
        return (_REQUEST_STREAM.get() or self.fallback).write(text)

    def flush(self):
        return (_REQUEST_STREAM.get() or self.fallback).flush()

    def __getattr__(self, name):
        return getattr(self.fallback, name)


@contextmanager
def route_request_logs():
    import sys
    with redirect_stdout(_RequestStream(sys.stdout)), redirect_stderr(_RequestStream(sys.stderr)):
        yield


@contextmanager
def request_log(stream):
    token = _REQUEST_STREAM.set(stream)
    try:
        yield
    finally:
        _REQUEST_STREAM.reset(token)
