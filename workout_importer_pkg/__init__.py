"""Workout importer: workout text -> MyWorkoutAssistant WorkoutPlanPackage.

Handles ANY workout text - a gym "Workout of the Day" (fetched by date), a
strength session, a circuit, a Hyrox simulation - via ``cli.py``.

No heuristic parsing. One LLM setup step reads the whole workout alongside the
gym equipment catalog and the existing exercise library and decides what
equipment and which exercise definitions are missing; those are created through
the exercise library generator, and the workout generator builds the final
workout in strict library mode. Both generators and their validation gates do
the real work — the importer only orchestrates and merges.
"""

from workout_importer_pkg.fetch import fetch_wod

__all__ = ["fetch_wod"]
