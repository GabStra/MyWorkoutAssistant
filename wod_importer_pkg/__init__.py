"""WOD importer: gym "Workout of the Day" text -> MyWorkoutAssistant WorkoutPlanPackage.

Pipeline (all deterministic except nothing — the gym's WOD texts are formulaic enough
that a heuristic parser covers them; unparsed lines are surfaced, never silently dropped):

1. fetch   — GET the GymAutoBook dashboard endpoint (localhost, must run on the PC
             where the GymAutoBook service runs).
2. parse   — raw text -> WodIR (blocks: timed/amrap/rft/emom/chipper/rest).
3. map     — movements -> exercise definitions: synonym table, then library match,
             else auto-created definitions/equipment with deterministic UUIDs.
4. encode  — IR -> workout components under near-zero-interaction rules:
             * fixed-time blocks and EMOM minutes -> auto-start/auto-stop countdown
               sets (advance with zero taps)
             * AMRAP -> superset with estimated rounds (tap to advance, finish early
               at the cap)
             * rounds-for-time -> superset with N rounds
             * chippers -> flat tap-through list
             * reps/weights are never user-entered; prescribed values ride along.
5. emit    — schemaVersion 2 WorkoutPlanPackage JSON, ready for the phone import flow.

Deterministic uuid5 ids everywhere: the same movement name always yields the same
definition/equipment id, so packages regenerated on different days merge cleanly.
"""

from wod_importer_pkg.fetch import fetch_wod
from wod_importer_pkg.parse import parse_wod
from wod_importer_pkg.build import build_package

__all__ = ["fetch_wod", "parse_wod", "build_package"]
