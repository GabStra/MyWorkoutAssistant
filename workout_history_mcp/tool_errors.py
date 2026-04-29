from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HINT_EXERCISE_ID = (
    "Use `list_exercises` or the `workout-history://exercises` resource for valid `exercise_id` values. "
    "Do not pass `workout_history_id` from `list_workout_sessions` — that identifies a completed session, not an exercise."
)

HINT_SESSION_ID = (
    "Use `list_workout_sessions` and pass the `workout_history_id` field from a returned item."
)


@dataclass(frozen=True)
class ToolFailure:
    """Structured tool/resource failure; convert to markdown or JSON for the MCP client."""

    message: str
    hint: str | None = None

    def as_markdown(self) -> str:
        lines = ["# Tool error", "", self.message.strip()]
        if self.hint:
            lines.extend(["", "## What to try", self.hint.strip()])
        return "\n".join(lines).rstrip() + "\n"

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "error": self.message.strip()}
        if self.hint:
            payload["hint"] = self.hint.strip()
        return payload

    @staticmethod
    def from_load_exception(exc: BaseException, backup_path: Path) -> ToolFailure:
        shown = str(backup_path)
        if isinstance(exc, FileNotFoundError):
            return ToolFailure(
                message=f"Backup file not found: {shown}",
                hint=(
                    "Set environment variable MYWORKOUT_BACKUP_PATH to the absolute path of your AppBackup JSON, "
                    "or place merged_workout_store_backup.json at the repository root."
                ),
            )
        if isinstance(exc, json.JSONDecodeError):
            return ToolFailure(
                message=f"Backup JSON is invalid ({shown}): {exc.msg} at line {exc.lineno}, column {exc.colno}.",
                hint="Re-export the backup from the app or repair the JSON file.",
            )
        if isinstance(exc, UnicodeDecodeError):
            return ToolFailure(
                message=f"Backup file is not valid UTF-8 ({shown}): {exc.reason}.",
                hint="Save the backup as UTF-8 or re-export from the app.",
            )
        if isinstance(exc, OSError):
            return ToolFailure(
                message=f"Could not read backup ({shown}): {type(exc).__name__}: {exc}",
                hint="Check file permissions and that the path is reachable from the MCP server host.",
            )
        return ToolFailure(
            message=f"Could not load backup ({shown}): {type(exc).__name__}: {exc}",
            hint="Verify MYWORKOUT_BACKUP_PATH and that the file is a complete AppBackup export.",
        )

    @staticmethod
    def from_value_error(exc: ValueError, *, tool: str) -> ToolFailure:
        text = str(exc).strip()
        if text.startswith("Exercise not found:"):
            return ToolFailure(message=text, hint=HINT_EXERCISE_ID)
        if text.startswith("Workout session not found:"):
            return ToolFailure(message=text, hint=HINT_SESSION_ID)
        return ToolFailure(
            message=text or f"{tool} rejected the input.",
            hint=None,
        )

    @staticmethod
    def unexpected(exc: BaseException, *, tool: str) -> ToolFailure:
        return ToolFailure(
            message=f"{tool} failed with {type(exc).__name__}: {exc}",
            hint="If this repeats, verify the backup file and report the error with the tool name and exception type.",
        )
