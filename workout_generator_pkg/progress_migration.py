"""Migrate generation progress files across internal step-schema versions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def migrate_progress_schema_v2_layout_step(progress: Dict[str, Any]) -> bool:
    """
    Normalize saved progress into the current schema.

    Current expectations:
    - workout layout lives on Step 1 PlanIndex workout entries
    - exercise entries in Step 1 include the deterministic exercise details needed by Step 3
    - pipeline steps are numbered 0..7 (no standalone layout step)

    Returns True if any in-memory migration was applied.
    """
    sd = progress.get("step_data")
    if not isinstance(sd, dict):
        return False

    migrated = False
    plan_index = sd.get("step_1_plan_index")

    # Collapse the temporary standalone layout step back into Step 1 workout rows.
    if isinstance(plan_index, dict) and isinstance(sd.get("step_4_workout_layouts"), dict):
        by_id = {
            wo.get("id"): wo
            for wo in plan_index.get("workouts", []) or []
            if isinstance(wo, dict) and wo.get("id")
        }
        for wid, layout in sd["step_4_workout_layouts"].items():
            if wid not in by_id or not isinstance(layout, dict):
                continue
            target = by_id[wid]
            for key in ("exerciseIds", "restToNextSeconds", "supersetGroups", "hasSupersets", "hasRestComponents"):
                if key in layout:
                    target[key] = deepcopy(layout[key])
        sd.pop("step_4_workout_layouts", None)
        migrated = True

    # Shift step payloads back down if they came from the temporary extra-step pipeline.
    renames = (
        ("step_5_workout_structures", "step_4_workout_structures"),
        ("step_6_placeholder_workout_store", "step_5_placeholder_workout_store"),
        ("step_7_validated_placeholder_store", "step_6_validated_placeholder_store"),
        ("step_7_best_json", "step_6_best_json"),
        ("step_7_best_error_count", "step_6_best_error_count"),
        ("step_7_current_attempt", "step_6_current_attempt"),
        ("step_8_final_workout_store", "step_7_final_workout_store"),
    )
    for old_key, new_key in renames:
        if old_key in sd:
            sd[new_key] = sd.pop(old_key)
            migrated = True

    cur = progress.get("current_step")
    if isinstance(cur, int) and cur >= 5 and migrated:
        progress["current_step"] = cur - 1

    return migrated
