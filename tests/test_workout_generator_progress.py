import io
import os
import threading

import pytest
from rich.cells import cell_len
from workout_generator_pkg import logging_ui, cli


@pytest.mark.parametrize('columns', [24, 120])
def test_status_redraw_clears_long_lines_without_wrapping(monkeypatch, columns):
    output = io.StringIO()
    monkeypatch.setattr(logging_ui.sys, 'stdout', output)
    monkeypatch.setattr(logging_ui.shutil, 'get_terminal_size', lambda: os.terminal_size((columns, 24)))
    logging_ui.write_progress_line('Searching exercises 界 ' * 15 + 'Ctrl+C to cancel')
    logging_ui.write_progress_line('Thinking | (46s)')
    logging_ui.write_progress_line()
    frames = [part for part in output.getvalue().split('\r') if part]
    assert all(cell_len(frame) == columns - 1 for frame in frames)
    assert frames[1].rstrip() == 'Thinking | (46s)'
    assert frames[-1] == ' ' * (columns - 1)
    assert '\n' not in output.getvalue()


@pytest.mark.parametrize('kind', [logging_ui.LoadingIndicator, logging_ui.ParallelLoadingIndicator,
                                  cli.LoadingIndicator, cli.ParallelLoadingIndicator])
def test_spinner_stops_before_clearing_and_can_restart(monkeypatch, kind):
    wrote = threading.Event()
    lines = []
    def write(text=''):
        lines.append(text)
        wrote.set()
    monkeypatch.setattr(logging_ui, 'write_progress_line', write)
    monkeypatch.setattr(cli, 'write_progress_line', write)
    indicator = kind('Thinking', 2) if 'Parallel' in kind.__name__ else kind('Thinking')
    for _ in range(2):
        wrote.clear()
        indicator.start()
        assert wrote.wait(2)
        indicator.stop()
        assert not indicator.thread.is_alive()
        assert lines[-1] == ''
