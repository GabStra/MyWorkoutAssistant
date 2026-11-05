"""Console logging and loading indicators."""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from rich.cells import set_cell_size


def write_progress_line(text=""):
    """Erase the previous status and leave the last column free to avoid wrapping."""
    width = max(0, shutil.get_terminal_size().columns - 1)
    text = text.replace("\n", " ").replace("\r", " ")
    sys.stdout.write("\r" + set_cell_size(text, width) + "\r")
    sys.stdout.flush()


def print_markdown(text, logger, paged=False):
    """Render terminal output while preserving raw Markdown in logs and pipes."""
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    if not console.is_terminal:
        logger.log_print(f"Assistant> {text}")
        return
    logger.log(f"Assistant> {text}")
    if paged:
        with console.pager(styles=True):
            console.print(Markdown(text))
    else:
        console.print("Assistant>", style="bold cyan")
        console.print(Markdown(text))


def format_question(question):
    lines = [question['question'], '']
    recommendation = question.get('recommendation', {})
    lines.extend(f"{index}. {option}" + (' (Recommended)' if index == recommendation.get('option') else '')
                 for index, option in enumerate(question['options'], 1))
    if recommendation:
        lines.extend(['', 'Why: ' + recommendation['reason']])
    hint = 'Choose a listed number, or type your own response.' if question['options'] else 'Type your own response.'
    lines.extend(['', hint, 'You can ask a question, suggest changes or give another answer. Use /ml for multiple lines; commands remain available.'])
    return '\n'.join(lines)


def print_question(question, logger):
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    text = format_question(question)
    console = Console()
    if console.is_terminal:
        logger.log('Question> ' + text)
        console.print(Panel(Text(text), title='Your choice', border_style='cyan'))
    else:
        logger.log_print('Question> ' + text)


class ConversationLogger:
    """
    Per-conversation debug logger. Writes timestamped lines to a log file.
    Use log_print for lines that should also go to stdout.
    """

    def __init__(self, log_path):
        self._path = log_path
        self._closed = False
        self._lock = threading.Lock()

    @property
    def log_filepath(self):
        return self._path

    def _timestamp(self):
        return datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")

    def _write(self, msg):
        with self._lock:
            try:
                if self._closed:
                    raise RuntimeError('Logger is closed')
                with open(self._path, 'a', encoding='utf-8') as log_file:
                    log_file.write(self._timestamp() + msg + "\n")
            except Exception as e:
                raise RuntimeError(f"Cannot write conversation log {self._path}: {e}") from e

    def log(self, msg):
        """Write timestamped line to log file only."""
        self._write(msg)

    def log_print(self, msg):
        """Write to log and print to stdout."""
        self._write(msg)
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"))

    def log_section(self, title):
        """Write a section header to the log."""
        self._write("--- " + title + " ---")

    def log_request(self, label, summary):
        """Log an API request (label + summary)."""
        self._write("[request] " + label + ": " + str(summary))

    def log_response(self, label, content, truncate_at=8000):
        """Log an API response; truncate large content."""
        s = str(content) if content is not None else ""
        if truncate_at and len(s) > truncate_at:
            s = s[:truncate_at] + f"... [truncated, total {len(s)} chars]"
        self._write("[response] " + label + ": " + s)

    def flush(self):
        # Each entry is already flushed and closed before returning.
        pass

    def close(self):
        with self._lock:
            self._closed = True


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

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def update(self, message):
        self.message = message

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
            waiting = " — still waiting; Ctrl+C to cancel" if elapsed >= 60 else ""
            write_progress_line(f"{self.message} {spinner[i % len(spinner)]} ({elapsed}s){waiting}")
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
            write_progress_line()
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
            write_progress_line(f"{self.message} {spinner[i % len(spinner)]} ({completed}/{self.total}, {elapsed}s)")
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
        write_progress_line()
        with self._lock:
            self._stop_printed = True


# Ensure any active spinner stops cleanly on interpreter exit.
_INDICATOR_HOOKS_REGISTERED = False
if not _INDICATOR_HOOKS_REGISTERED:
    _INDICATOR_HOOKS_REGISTERED = True

    def _noop_cleanup() -> None:
        return

    atexit.register(_noop_cleanup)
