#!/usr/bin/env python3
"""Headless driver for the interactive workout generator shell.

The shell's REPL reads every reply through ``builtins.input``; this driver
replaces it with a poller that returns one line at a time from a plain text
file. An operator (human or agent) appends one line per turn to the inputs file
while tailing the session log, so a real LLM generation can be babysitted
unattended: answer questions, approve requirements, and send the exact
generation confirmation when the preview passes.

The shell's own conversation persistence still records everything under
workouts/conversation_sessions, and stdout carries the full transcript.

Usage (run from the repository root):
  python scripts/generate_wod_headless.py \
      --inputs-file build/wod_session/inputs.txt \
      -- equipment/library shell flags as known by workout_generator.py
"""

from __future__ import annotations

import argparse
import builtins
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

POLL_SECONDS = 2.0


def make_scripted_input(inputs_path: pathlib.Path, echo: Callable[[str], None]) -> Callable[..., str]:
    inputs_path.parent.mkdir(parents=True, exist_ok=True)
    inputs_path.touch(exist_ok=True)
    consumed = 0

    def scripted_input(prompt: str = "") -> str:
        nonlocal consumed
        while True:
            lines = inputs_path.read_text(encoding="utf-8").splitlines()
            if len(lines) > consumed:
                line = lines[consumed].strip()
                consumed += 1
                # "@file:<path>" replies with the whole file: multi-line first
                # messages (guidance + WOD text) stay readable.
                if line.startswith("@file:"):
                    payload = pathlib.Path(line[len("@file:"):]).read_text(encoding="utf-8")
                    echo(f"{prompt}<file {line[len('@file:'):]} ({len(payload)} chars)>")
                    return payload
                echo(f"{prompt}{line}")
                return line
            time.sleep(POLL_SECONDS)

    return scripted_input


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-file", required=True,
                        help="Plain text file; each appended line is the next shell reply")
    args, shell_args = parser.parse_known_args()
    while shell_args and shell_args[0] == "--":
        shell_args.pop(0)

    inputs_path = pathlib.Path(args.inputs_file)
    banner = f"[headless] session start {time.strftime('%Y-%m-%d %H:%M:%S')}; inputs file: {inputs_path}"
    print(banner, flush=True)

    def echo(line: str) -> None:
        print(f"[headless reply] {line}", flush=True)

    builtins.input = make_scripted_input(inputs_path, echo)

    from workout_generator_pkg.llm_config import load_env_files
    load_env_files()

    from workout_generator_pkg import interactive_shell

    sys.argv = ["workout_generator.py", *shell_args]
    interactive_shell.main()
    print("[headless] session end", flush=True)


if __name__ == "__main__":
    main()
