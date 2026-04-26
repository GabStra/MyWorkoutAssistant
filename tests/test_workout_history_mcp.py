from __future__ import annotations

import asyncio
import json
from pathlib import Path

from workout_history_mcp.exporters import (
    current_training_plan_data,
    exercise_history_markdown,
    list_exercises_data,
    session_list,
    session_markdown,
)
from workout_history_mcp.loader import load_store
from workout_history_mcp.server import create_mcp


def fixture_backup() -> dict:
    workout_id = "11111111-1111-1111-1111-111111111111"
    bench_id = "22222222-2222-2222-2222-222222222222"
    pullup_id = "33333333-3333-3333-3333-333333333333"
    equipment_id = "44444444-4444-4444-4444-444444444444"
    accessory_id = "55555555-5555-5555-5555-555555555555"
    session_1 = "66666666-6666-6666-6666-666666666666"
    session_2 = "77777777-7777-7777-7777-777777777777"
    return {
        "WorkoutStore": {
            "birthDateYear": 1995,
            "weightKg": 80.0,
            "measuredMaxHeartRate": 190,
            "restingHeartRate": 55,
            "progressionPercentageAmount": 2.5,
            "equipments": [
                {
                    "id": equipment_id,
                    "type": "BARBELL",
                    "name": "Test Barbell",
                    "barWeight": 20.0,
                    "availablePlates": [{"weight": 20.0}, {"weight": 10.0}, {"weight": 2.5}],
                }
            ],
            "accessoryEquipments": [{"id": accessory_id, "type": "ACCESSORY", "name": "Pull-Up Bar"}],
            "workouts": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "Old Strength A",
                    "description": "Previous version",
                    "order": 0,
                    "enabled": True,
                    "isActive": False,
                    "nextVersionId": workout_id,
                    "workoutComponents": [
                        {
                            "id": bench_id,
                            "type": "Exercise",
                            "enabled": True,
                            "name": "Bench Press",
                            "notes": "",
                            "sets": [
                                {"id": "old-bench-1", "type": "WeightSet", "reps": 8, "weight": 75.0, "subCategory": "CalibrationPendingSet"}
                            ],
                            "exerciseType": "WEIGHT",
                            "equipmentId": equipment_id,
                            "bodyWeightPercentage": 0.0,
                            "progressionMode": "OFF",
                            "minReps": 6,
                            "maxReps": 10,
                            "minLoadPercent": 70.0,
                            "maxLoadPercent": 85.0,
                        },
                    ],
                },
                {
                    "id": workout_id,
                    "name": "Strength A",
                    "description": "Main strength session",
                    "order": 1,
                    "enabled": True,
                    "isActive": True,
                    "previousVersionId": "00000000-0000-0000-0000-000000000001",
                    "workoutComponents": [
                        {
                            "id": bench_id,
                            "type": "Exercise",
                            "enabled": True,
                            "name": "Bench Press",
                            "notes": "Pause first rep",
                            "sets": [
                                {"id": "planned-bench-1", "type": "WeightSet", "reps": 6, "weight": 82.5, "subCategory": "WorkSet"},
                                {"id": "planned-bench-rest", "type": "RestSet", "timeInSeconds": 90, "subCategory": "WorkSet"},
                            ],
                            "exerciseType": "WEIGHT",
                            "equipmentId": equipment_id,
                            "bodyWeightPercentage": 0.0,
                            "progressionMode": "AUTO_REGULATION",
                            "minReps": 6,
                            "maxReps": 12,
                            "minLoadPercent": 65.0,
                            "maxLoadPercent": 85.0,
                            "muscleGroups": ["FRONT_CHEST"],
                        },
                        {
                            "id": pullup_id,
                            "type": "Exercise",
                            "enabled": True,
                            "name": "Pull-Ups",
                            "notes": "",
                            "sets": [{"id": "planned-pullup-1", "type": "BodyWeightSet", "reps": 8, "additionalWeight": 5.0, "subCategory": "WorkSet"}],
                            "exerciseType": "BODY_WEIGHT",
                            "equipmentId": accessory_id,
                            "bodyWeightPercentage": 100.0,
                            "progressionMode": "DOUBLE_PROGRESSION",
                            "minReps": 6,
                            "maxReps": 12,
                        },
                    ],
                }
            ],
        },
        "WorkoutHistories": [
            {
                "id": session_1,
                "workoutId": workout_id,
                "date": "2026-01-01",
                "time": "08:00",
                "startTime": "2026-01-01T08:00:00",
                "duration": 3600,
                "heartBeatRecords": [100, 120],
                "isDone": True,
            },
            {
                "id": session_2,
                "workoutId": workout_id,
                "date": "2026-01-08",
                "time": "08:30",
                "startTime": "2026-01-08T08:30:00",
                "duration": 3900,
                "heartBeatRecords": [110, 130],
                "isDone": True,
            },
        ],
        "SetHistories": [
            {
                "id": "80000000-0000-0000-0000-000000000000",
                "workoutHistoryId": session_2,
                "exerciseId": bench_id,
                "setId": "90000000-0000-0000-0000-000000000000",
                "order": 0,
                "executionSequence": 0,
                "skipped": False,
                "setData": {
                    "type": "WeightSetData",
                    "actualReps": 5,
                    "actualWeight": 40.0,
                    "volume": 200.0,
                    "subCategory": "WarmupSet",
                },
            },
            {
                "id": "80000000-0000-0000-0000-000000000001",
                "workoutHistoryId": session_1,
                "exerciseId": bench_id,
                "setId": "90000000-0000-0000-0000-000000000001",
                "order": 0,
                "executionSequence": 0,
                "skipped": False,
                "equipmentIdSnapshot": equipment_id,
                "equipmentNameSnapshot": "Test Barbell",
                "setData": {
                    "type": "WeightSetData",
                    "actualReps": 5,
                    "actualWeight": 80.0,
                    "volume": 400.0,
                    "subCategory": "WorkSet",
                },
            },
            {
                "id": "80000000-0000-0000-0000-000000000002",
                "workoutHistoryId": session_2,
                "exerciseId": bench_id,
                "setId": "90000000-0000-0000-0000-000000000002",
                "order": 1,
                "executionSequence": 1,
                "skipped": False,
                "equipmentIdSnapshot": equipment_id,
                "equipmentNameSnapshot": "Test Barbell",
                "setData": {
                    "type": "WeightSetData",
                    "actualReps": 6,
                    "actualWeight": 82.5,
                    "volume": 495.0,
                    "subCategory": "WorkSet",
                },
            },
            {
                "id": "80000000-0000-0000-0000-000000000004",
                "workoutHistoryId": session_2,
                "exerciseId": bench_id,
                "setId": "90000000-0000-0000-0000-000000000004",
                "order": 2,
                "executionSequence": 2,
                "skipped": False,
                "startTime": "2026-01-08T08:35:00",
                "endTime": "2026-01-08T08:36:00",
                "setData": {
                    "type": "RestSetData",
                    "startTimer": 90,
                    "endTimer": 0,
                    "subCategory": "WorkSet",
                },
            },
            {
                "id": "80000000-0000-0000-0000-000000000003",
                "workoutHistoryId": session_2,
                "exerciseId": pullup_id,
                "setId": "90000000-0000-0000-0000-000000000003",
                "order": 1,
                "executionSequence": 1,
                "skipped": False,
                "setData": {
                    "type": "BodyWeightSetData",
                    "actualReps": 8,
                    "additionalWeight": 5.0,
                    "relativeBodyWeightInKg": 80.0,
                    "bodyWeightPercentageSnapshot": 100.0,
                    "volume": 680.0,
                    "subCategory": "WorkSet",
                },
            },
        ],
        "RestHistories": [
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "workoutHistoryId": session_2,
                "exerciseId": bench_id,
                "order": 0,
                "elapsedSeconds": 120,
                "plannedSeconds": 90,
            }
        ],
        "ExerciseSessionProgressions": [
            {
                "id": "bbbbbbbb-0000-0000-0000-000000000001",
                "workoutHistoryId": session_2,
                "exerciseId": bench_id,
                "expectedSets": [{"weight": 82.5, "reps": 6}],
                "progressionState": "PROGRESS",
                "vsExpected": "EQUAL",
                "vsPrevious": "ABOVE",
                "previousSessionVolume": 400.0,
                "expectedVolume": 495.0,
                "executedVolume": 495.0,
            }
        ],
        "ExerciseInfos": [],
        "WorkoutSchedules": [],
        "WorkoutRecords": [],
    }


def write_fixture(tmp_path: Path) -> Path:
    backup_path = tmp_path / "backup.json"
    backup_path.write_text(json.dumps(fixture_backup()), encoding="utf-8")
    return backup_path


def test_athlete_profile_extracts_backup_fields_and_derived_stats(tmp_path: Path) -> None:
    store = load_store(write_fixture(tmp_path))

    profile = store.athlete_profile()

    assert profile["birth_year"] == 1995
    assert profile["age"] >= 30
    assert profile["body_weight_kg"] == 80.0
    assert profile["measured_max_heart_rate"] == 190
    assert profile["resting_heart_rate"] == 55
    assert profile["progression_percentage_amount"] == 2.5
    assert profile["training_start_date"] == "2026-01-01"
    assert profile["training_end_date"] == "2026-01-08"
    assert profile["completed_session_count"] == 2
    assert profile["total_recorded_sets"] == 3
    assert profile["exercise_count"] == 2
    assert "Test Barbell" in profile["available_equipment"]
    assert "Pull-Up Bar" in profile["available_accessories"]


def test_exercise_markdown_includes_chronological_sets_formula_and_equipment(tmp_path: Path) -> None:
    store = load_store(write_fixture(tmp_path))
    pullup_id = "33333333-3333-3333-3333-333333333333"

    markdown = exercise_history_markdown(store, pullup_id)

    assert "# Pull-Ups" in markdown
    assert "#### Athlete Context" in markdown
    assert "#### Body Weight Load" in markdown
    assert "Relative BW = session BW x 100%" in markdown
    assert "80 kg relative BW (80 kg x 100%) + 5 kg equipment = 85 kg x 8" in markdown
    assert "Pull-Up Bar" in markdown


def test_session_markdown_includes_context_summary_and_progression(tmp_path: Path) -> None:
    store = load_store(write_fixture(tmp_path))
    session_2 = "77777777-7777-7777-7777-777777777777"

    markdown = session_markdown(store, session_2)

    assert "# Strength A" in markdown
    assert "#### Athlete Context" in markdown
    assert "## Session Summary" in markdown
    assert "### Bench Press" in markdown
    assert "- Sets: 82.5x6" in markdown
    assert "2:00 elapsed (1:30 planned)" in markdown
    assert "1:00 elapsed (1:30 planned)" in markdown
    assert "40x5" not in markdown
    assert "PROGRESS" in markdown


def test_session_list_returns_pagination_and_hr_summary(tmp_path: Path) -> None:
    store = load_store(write_fixture(tmp_path))

    page = session_list(store, limit=1)

    assert page["total"] == 2
    assert page["has_more"] is True
    assert page["items"][0]["heart_rate"]["average_bpm"] == 120
    assert page["items"][0]["heart_rate"]["max_hr_basis_bpm"] == 190
    assert page["items"][0]["heart_rate"]["resting_hr_basis_bpm"] == 55
    assert page["items"][0]["heart_rate"]["zone_time"] == {"Z0": "00:01", "Z1": "00:01"}


def test_list_exercises_supports_query(tmp_path: Path) -> None:
    store = load_store(write_fixture(tmp_path))

    rows = list_exercises_data(store, query="bench")

    assert [row["name"] for row in rows] == ["Bench Press"]
    assert rows[0]["session_count"] == 2
    assert rows[0]["progression_mode"] == "AUTO_REGULATION"
    assert rows[0]["planned_sets"][0]["weight_kg"] == 82.5


def test_current_training_plan_includes_exercise_config_and_equipment(tmp_path: Path) -> None:
    store = load_store(write_fixture(tmp_path))

    plan = current_training_plan_data(store)

    bench = plan["workouts"][0]["components"][0]
    assert bench["name"] == "Bench Press"
    assert bench["equipment_name"] == "Test Barbell"
    assert bench["planned_sets"][0]["weight_kg"] == 82.5
    assert bench["progression_mode"] == "AUTO_REGULATION"
    assert plan["equipment"]["equipment"][0]["bar_weight_kg"] == 20.0


def test_server_registers_resources_and_tools_without_auth(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MYWORKOUT_BACKUP_PATH", str(write_fixture(tmp_path)))

    mcp = create_mcp()
    tools = asyncio.run(mcp.list_tools())
    resources = asyncio.run(mcp.list_resources())

    tool_names = {tool.name for tool in tools}
    resource_uris = {str(resource.uri) for resource in resources}
    assert "get_athlete_profile" in tool_names
    assert "get_current_training_plan" in tool_names
    assert "get_full_history_markdown" not in tool_names
    assert "workout-history://athlete" in resource_uris
    assert "workout-history://current-plan" in resource_uris
    assert "workout-history://full" not in resource_uris
    assert getattr(mcp, "_token_verifier", None) is None
    assert mcp.settings.transport_security.enable_dns_rebinding_protection is False
