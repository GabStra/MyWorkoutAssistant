"""Console logging and loading indicators."""

from __future__ import annotations

import atexit
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

from .paths import get_log_dir


class ConversationLogger:
    """Simple conversation and debug logger."""

    def __init__(self, script_dir: Optional[str] = None):
        self.script_dir = script_dir
        self.log_dir = get_log_dir(script_dir)
        self.conversation_id = str(uuid.uuid4())
        self.log_filepath = os.path.join(self.log_dir, f"conversation_{self.conversation_id[:8]}.log")
        self._lock = threading.Lock()

    def _write(self, line: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out = f"[{timestamp}] {line}\n"
        with self._lock:
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                f.write(out)

    def log(self, line: str) -> None:
        self._write(line)

    def log_print(self, line: str) -> None:
        print(line)
        self._write(line)

    def log_section(self, title: str) -> None:
        self._write(f"--- {title} ---")

    def log_request(self, label: str, content: str) -> None:
        self._write(f"[request] {label}: {content}")

    def log_response(self, label: str, content: str, truncate_at: int = 8000) -> None:
        s = str(content)
        if truncate_at and len(s) > truncate_at:
            s = s[:truncate_at] + f"... [truncated, total {len(s)} chars]"
        self._write(f"[response] {label}: {s}")


class PrefixLogger:
    """Logger adapter that prefixes all log messages."""

    def __init__(self, logger: ConversationLogger, prefix: str):
        self._logger = logger
        self._prefix = prefix
        self.is_parallel = True

    def log(self, line: str) -> None:
        self._logger.log(self._prefix + line)

    def log_print(self, line: str) -> None:
        self._logger.log_print(self._prefix + line)

    def log_section(self, title: str) -> None:
        self._logger.log_section(self._prefix + title)

    def log_request(self, label: str, content: str) -> None:
        self._logger.log_request(self._prefix + label, content)

    def log_response(self, label: str, content: str, truncate_at: int = 8000) -> None:
        self._logger.log_response(self._prefix + label, content, truncate_at=truncate_at)


class LoadingIndicator:
    """Terminal spinner."""

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self.running = False
        self.thread = None
        self.start_time = None
        self._stop_printed = False
        self._lock = threading.Lock()

    def _animate(self) -> None:
        spinner = ["|", "/", "-", "\\"]
        i = 0
        while self.running:
            elapsed = int(time.time() - self.start_time) if self.start_time else 0
            sys.stdout.write(f"\r{self.message} {spinner[i % len(spinner)]} ({elapsed}s)")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.running = True
            self.start_time = time.time()
            self._stop_printed = False
            self.thread = threading.Thread(target=self._animate)
            self.thread.daemon = True
            self.thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._stop_printed:
                return
            self.running = False
            if self.thread:
                self.thread.join(timeout=0.5)
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()
            self._stop_printed = True


class ParallelLoadingIndicator:
    """Progress indicator for parallel operations."""

    def __init__(self, message: str, total: int):
        self.message = message
        self.total = total
        self.completed = 0
        self.running = False
        self.thread = None
        self.start_time = None
        self._lock = threading.Lock()
        self._stop_printed = False

    def increment(self) -> None:
        with self._lock:
            self.completed += 1

    def _animate(self) -> None:
        spinner = ["|", "/", "-", "\\"]
        i = 0
        while self.running:
            with self._lock:
                completed = self.completed
            elapsed = int(time.time() - self.start_time) if self.start_time else 0
            sys.stdout.write(
                f"\r{self.message} {spinner[i % len(spinner)]} ({completed}/{self.total}, {elapsed}s)"
            )
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.running = True
            self.start_time = time.time()
            self._stop_printed = False
            self.thread = threading.Thread(target=self._animate)
            self.thread.daemon = True
            self.thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._stop_printed:
                return
            self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        sys.stdout.write("\r" + " " * 120 + "\r")
        sys.stdout.flush()
        with self._lock:
            self._stop_printed = True


# Ensure any active spinner stops cleanly on interpreter exit.
_INDICATOR_HOOKS_REGISTERED = False
if not _INDICATOR_HOOKS_REGISTERED:
    _INDICATOR_HOOKS_REGISTERED = True

    def _noop_cleanup() -> None:
        return

    atexit.register(_noop_cleanup)
