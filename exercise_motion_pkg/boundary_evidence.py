"""Arbitrate endpoint evidence without equating uncertainty with bad footage."""
import re
from typing import Any

ENDPOINT_OBSERVATION_PROMPT = (
    'Describe only the visible posture in this single image. Do not infer movement or exercise '
    'completion. Use unknown for hidden or ambiguous features. Return JSON: {"supportMode":"standing|'
    'kneeling|seated|lying|hanging|unknown","kneeState":"extended|flexed|deep_flexion|unknown","torso'
    'Orientation":"upright|hinged|horizontal|unknown","handHeight":"above_head|shoulder_chest|hip|bel'
    'ow_hips|unknown","stance":"narrow|shoulder_width|wide|split|unknown","description":"short '
    'visible evidence"}. Extended knees means straight knees; bent knees are flexed or deep_flexion. '
    'Torso orientation describes the torso, not whether the person is standing.'
)


def _known_observation(value: Any) -> bool:
    return isinstance(value, str) and value not in {"", "unknown", "any"}


def explicit_endpoint_requirements(exercise_name: str) -> dict[str, str]:
    """Use explicit target qualifiers, never generated pose guesses, as requirements.

    Multiple posture terms describe a transition and do not prescribe one fixed
    endpoint support mode. Other identity/equipment checks remain with sequence review.
    """
    modes = {mode for mode in ("standing", "kneeling", "seated", "lying", "hanging")
             if re.search(rf"\b{mode}\b", exercise_name.casefold())}
    return {"supportMode": next(iter(modes))} if len(modes) == 1 else {}


def assess_boundary_evidence(
    comparisons: list[dict[str, Any]], *, support_return: dict[str, Any],
    stable_camera: bool, completion_mode: str,
) -> dict[str, Any]:
    measured_mismatch = (stable_camera and support_return.get("available") is True
                         and support_return.get("passed") is False)
    start_rows = {row.get("field"): row for row in comparisons if row.get("endpoint") == "start"}
    end_rows = {row.get("field"): row for row in comparisons if row.get("endpoint") == "end"}
    repeated_identity_conflicts = [
        field for field, start in start_rows.items()
        if field in end_rows and start.get("requirementOrigin") == "exercise_definition"
        and end_rows[field].get("requirementOrigin") == "exercise_definition"
        and _known_observation(start.get("observed"))
        and start.get("observed") == end_rows[field].get("observed")
        and start.get("passed") is False and end_rows[field].get("passed") is False
    ]
    if repeated_identity_conflicts:
        return {"decision": "rejected", "passed": False, "blocking": True,
                "reason": "explicit_identity_conflict", "conflictingFields": repeated_identity_conflicts}
    # Compare observations directly, independently of generated ideal postures.
    visible_return_mismatch = any(
        field in end_rows and _known_observation(start.get("observed"))
        and _known_observation(end_rows[field].get("observed"))
        and start.get("observed") != end_rows[field].get("observed")
        for field, start in start_rows.items()
        if field in {"kneeState", "handHeight", "torsoOrientation"}
    )
    if completion_mode == "return_to_start" and measured_mismatch and visible_return_mismatch:
        return {"decision": "rejected", "passed": False, "blocking": True,
                "reason": "corroborated_endpoint_mismatch"}
    complete = bool(start_rows) and set(start_rows) == set(end_rows)
    known = complete and all(_known_observation(row.get("observed")) for row in comparisons)
    mismatches = [row for row in comparisons if row.get("passed") is not True]
    if known and not mismatches and not measured_mismatch:
        return {"decision": "accepted", "passed": True, "blocking": False,
                "reason": "endpoint_evidence_agrees"}
    repeated_conflicts = [
        field for field, start in start_rows.items() if field in end_rows
        and _known_observation(start.get("observed"))
        and start.get("observed") == end_rows[field].get("observed")
        and start.get("passed") is False and end_rows[field].get("passed") is False
    ]
    return {"decision": "needs_review", "passed": False, "blocking": False,
            "eligibleForReconstruction": True,
            "reason": "contract_observation_conflict" if repeated_conflicts else
                      "conflicting_endpoint_evidence" if known else "endpoint_evidence_unresolved",
            "conflictingFields": repeated_conflicts}
