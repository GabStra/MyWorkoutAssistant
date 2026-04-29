from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .exporters import (
    current_training_plan_data,
    exercise_history_markdown,
    exercise_index_markdown,
    list_exercises_data,
    session_list,
    session_markdown,
    summary_markdown,
)
from .loader import WorkoutHistoryStore, backup_path_from_env, load_store
from .tool_errors import ToolFailure


def _load_store_or_failure() -> WorkoutHistoryStore | ToolFailure:
    path = backup_path_from_env()
    try:
        return load_store(path)
    except Exception as exc:
        return ToolFailure.from_load_exception(exc, path)


def _with_store_str(factory: Callable[[WorkoutHistoryStore], str], *, label: str) -> str:
    loaded = _load_store_or_failure()
    if isinstance(loaded, ToolFailure):
        return loaded.as_markdown()
    try:
        return factory(loaded)
    except ValueError as exc:
        return ToolFailure.from_value_error(exc, tool=label).as_markdown()
    except Exception as exc:
        return ToolFailure.unexpected(exc, tool=label).as_markdown()


def _with_store_dict(factory: Callable[[WorkoutHistoryStore], dict[str, Any]], *, label: str) -> dict[str, Any]:
    loaded = _load_store_or_failure()
    if isinstance(loaded, ToolFailure):
        return loaded.as_dict()
    try:
        return factory(loaded)
    except ValueError as exc:
        return ToolFailure.from_value_error(exc, tool=label).as_dict()
    except Exception as exc:
        return ToolFailure.unexpected(exc, tool=label).as_dict()


def _with_store_list(
    factory: Callable[[WorkoutHistoryStore], list[dict[str, Any]]],
    *,
    label: str,
) -> list[dict[str, Any]] | dict[str, Any]:
    loaded = _load_store_or_failure()
    if isinstance(loaded, ToolFailure):
        return loaded.as_dict()
    try:
        return factory(loaded)
    except Exception as exc:
        return ToolFailure.unexpected(exc, tool=label).as_dict()


def create_mcp() -> FastMCP:
    host = os.environ.get("MYWORKOUT_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MYWORKOUT_MCP_PORT", "8000"))
    mcp = FastMCP(
        "MyWorkoutAssistant Workout History",
        instructions=(
            "Read-only access to a MyWorkoutAssistant AppBackup JSON. "
            "Use the resources for broad context and tools for targeted session or exercise history. "
            "When a tool or resource fails, JSON payloads include ok=false with error and optional hint; "
            "markdown tools return a '# Tool error' document instead of raising."
        ),
        host=host,
        port=port,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.resource("workout-history://athlete")
    def athlete_resource() -> dict[str, Any]:
        """Athlete profile and derived training context."""
        return _with_store_dict(lambda store: store.athlete_profile(), label="workout-history://athlete")

    @mcp.resource("workout-history://summary")
    def summary_resource() -> str:
        """Summary of athlete context, date range, workouts, and exercise index."""
        return _with_store_str(lambda store: summary_markdown(store), label="workout-history://summary")

    @mcp.resource("workout-history://exercises")
    def exercises_resource() -> str:
        """Compact searchable exercise index."""
        return _with_store_str(lambda store: exercise_index_markdown(store), label="workout-history://exercises")

    @mcp.resource("workout-history://current-plan")
    def current_plan_resource() -> dict[str, Any]:
        """Current active workouts, exercise prescriptions, progression settings, and equipment."""
        return _with_store_dict(lambda store: current_training_plan_data(store), label="workout-history://current-plan")

    @mcp.tool()
    def get_athlete_profile() -> dict[str, Any]:
        """Return profile fields, derived history stats, and available equipment.

        On failure returns a JSON object with ok=false, error, and optional hint instead of raising.
        """
        return _with_store_dict(lambda store: store.athlete_profile(), label="get_athlete_profile")

    @mcp.tool()
    def get_workout_history_summary() -> str:
        """Return a markdown summary of the full workout history backup.

        On failure returns a markdown document headed '# Tool error' instead of raising.
        """
        return _with_store_str(lambda store: summary_markdown(store), label="get_workout_history_summary")

    @mcp.tool()
    def list_workout_sessions(
        limit: int = 50,
        offset: int = 0,
        workout_name: str | None = None,
        exercise_name: str | None = None,
    ) -> dict[str, Any]:
        """List completed workout sessions with pagination metadata, newest first.

        On failure returns a JSON object with ok=false, error, and optional hint instead of raising.
        """
        return _with_store_dict(
            lambda store: session_list(
                store,
                limit=limit,
                offset=offset,
                workout_name=workout_name,
                exercise_name=exercise_name,
            ),
            label="list_workout_sessions",
        )

    @mcp.tool()
    def get_session_markdown(workout_history_id: str) -> str:
        """Return markdown for one workout session by workout history id.

        On failure returns a markdown document headed '# Tool error' instead of raising.
        """
        return _with_store_str(
            lambda store: session_markdown(store, workout_history_id),
            label="get_session_markdown",
        )

    @mcp.tool()
    def list_exercises(query: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
        """List exercises with ids, current config, planned sets, and recorded history counts.

        On failure returns a JSON object with ok=false, error, and optional hint instead of a list.
        """
        return _with_store_list(
            lambda store: list_exercises_data(store, query=query),
            label="list_exercises",
        )

    @mcp.tool()
    def get_exercise_history_markdown(exercise_id: str) -> str:
        """Return chronological markdown history for one exercise id.

        On failure returns a markdown document headed '# Tool error' instead of raising.
        """
        return _with_store_str(
            lambda store: exercise_history_markdown(store, exercise_id),
            label="get_exercise_history_markdown",
        )

    @mcp.tool()
    def get_current_training_plan(active_only: bool = True) -> dict[str, Any]:
        """Return current workouts, exercise prescriptions, progression settings, and equipment.

        On failure returns a JSON object with ok=false, error, and optional hint instead of raising.
        """
        return _with_store_dict(
            lambda store: current_training_plan_data(store, active_only=active_only),
            label="get_current_training_plan",
        )

    return mcp


mcp = create_mcp()


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
