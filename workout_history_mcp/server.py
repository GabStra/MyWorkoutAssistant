from __future__ import annotations

import os
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
from .loader import load_store


def _new_store():
    return load_store()


def create_mcp() -> FastMCP:
    host = os.environ.get("MYWORKOUT_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MYWORKOUT_MCP_PORT", "8000"))
    mcp = FastMCP(
        "MyWorkoutAssistant Workout History",
        instructions=(
            "Read-only access to a MyWorkoutAssistant AppBackup JSON. "
            "Use the resources for broad context and tools for targeted session or exercise history."
        ),
        host=host,
        port=port,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.resource("workout-history://athlete")
    def athlete_resource() -> dict[str, Any]:
        """Athlete profile and derived training context."""
        return _new_store().athlete_profile()

    @mcp.resource("workout-history://summary")
    def summary_resource() -> str:
        """Summary of athlete context, date range, workouts, and exercise index."""
        return summary_markdown(_new_store())

    @mcp.resource("workout-history://exercises")
    def exercises_resource() -> str:
        """Compact searchable exercise index."""
        return exercise_index_markdown(_new_store())

    @mcp.resource("workout-history://current-plan")
    def current_plan_resource() -> dict[str, Any]:
        """Current active workouts, exercise prescriptions, progression settings, and equipment."""
        return current_training_plan_data(_new_store())

    @mcp.tool()
    def get_athlete_profile() -> dict[str, Any]:
        """Return profile fields, derived history stats, and available equipment."""
        return _new_store().athlete_profile()

    @mcp.tool()
    def get_workout_history_summary() -> str:
        """Return a markdown summary of the full workout history backup."""
        return summary_markdown(_new_store())

    @mcp.tool()
    def list_workout_sessions(
        limit: int = 50,
        offset: int = 0,
        workout_name: str | None = None,
        exercise_name: str | None = None,
    ) -> dict[str, Any]:
        """List completed workout sessions with pagination metadata, newest first."""
        return session_list(
            _new_store(),
            limit=limit,
            offset=offset,
            workout_name=workout_name,
            exercise_name=exercise_name,
        )

    @mcp.tool()
    def get_session_markdown(workout_history_id: str) -> str:
        """Return markdown for one workout session by workout history id."""
        return session_markdown(_new_store(), workout_history_id)

    @mcp.tool()
    def list_exercises(query: str | None = None) -> list[dict[str, Any]]:
        """List exercises with ids, current config, planned sets, and recorded history counts."""
        return list_exercises_data(_new_store(), query=query)

    @mcp.tool()
    def get_exercise_history_markdown(exercise_id: str) -> str:
        """Return chronological markdown history for one exercise id."""
        return exercise_history_markdown(_new_store(), exercise_id)

    @mcp.tool()
    def get_current_training_plan(active_only: bool = True) -> dict[str, Any]:
        """Return current workouts, exercise prescriptions, progression settings, and equipment."""
        return current_training_plan_data(_new_store(), active_only=active_only)

    return mcp


mcp = create_mcp()


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
