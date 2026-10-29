"""Artifact classes and transitions for reviewed exercise movements."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


FULL_CLIP_BAKE = "full_clip_bake"
CYCLE_SELECTION = "cycle_selection"
CYCLIC_REBAKE = "cyclic_rebake"
BOUNDED_MOVEMENT_SELECTION = "bounded_movement_selection"
BOUNDED_MOVEMENT_REBAKE = "bounded_movement_rebake"
PACKAGED_MOVEMENT = "packaged_movement"
MANUAL_REVIEW_PACKAGE = "manual_review_package"

TERMINAL_ARTIFACT_CLASSES = frozenset(
    {FULL_CLIP_BAKE, CYCLIC_REBAKE, BOUNDED_MOVEMENT_REBAKE}
)
PACKAGED_ARTIFACT_CLASSES = frozenset({PACKAGED_MOVEMENT, MANUAL_REVIEW_PACKAGE})
ARTIFACT_HISTORY_START_CLASSES = frozenset(
    {FULL_CLIP_BAKE, CYCLE_SELECTION, BOUNDED_MOVEMENT_SELECTION}
)
ALLOWED_ARTIFACT_TRANSITIONS = {
    FULL_CLIP_BAKE: frozenset({CYCLE_SELECTION, PACKAGED_MOVEMENT, MANUAL_REVIEW_PACKAGE}),
    CYCLE_SELECTION: frozenset({CYCLIC_REBAKE}),
    CYCLIC_REBAKE: frozenset({PACKAGED_MOVEMENT, MANUAL_REVIEW_PACKAGE}),
    BOUNDED_MOVEMENT_SELECTION: frozenset({BOUNDED_MOVEMENT_REBAKE}),
    BOUNDED_MOVEMENT_REBAKE: frozenset({PACKAGED_MOVEMENT, MANUAL_REVIEW_PACKAGE}),
}


def validate_artifact_history(history: list[str]) -> None:
    if not isinstance(history, list) or not history:
        raise ValueError("Artifact history must be a non-empty list")
    if any(not isinstance(value, str) for value in history):
        raise ValueError("Artifact history entries must be strings")
    if history[0] not in ARTIFACT_HISTORY_START_CLASSES:
        raise ValueError(f"Invalid movement artifact history start: {history[0]}")
    for current, next_class in zip(history, history[1:]):
        if next_class not in ALLOWED_ARTIFACT_TRANSITIONS.get(current, frozenset()):
            raise ValueError(f"Invalid movement artifact transition: {current} -> {next_class}")


def expected_artifact_terminal(artifact_class: str, required_class: str | None) -> bool:
    return artifact_class in TERMINAL_ARTIFACT_CLASSES and (
        required_class is None or artifact_class == required_class
    )


def validate_artifact_state(
    state: Any,
    *,
    movement_payload: dict[str, Any] | None = None,
    source_parent_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a persisted, pre-package movement state and return it."""
    if not isinstance(state, dict):
        raise ValueError("Artifact state must be an object")
    if type(state.get("schemaVersion")) is not int or state["schemaVersion"] != 1:
        raise ValueError("Unsupported artifact state schema version")
    artifact_class = state.get("artifactClass")
    if not isinstance(artifact_class, str):
        raise ValueError("Movement artifact class must be a string")
    if artifact_class not in TERMINAL_ARTIFACT_CLASSES:
        raise ValueError(f"Unknown movement artifact class: {artifact_class}")
    required_class = state.get("requiredClass")
    if required_class is not None and not isinstance(required_class, str):
        raise ValueError("Required movement artifact class must be a string")
    if required_class is not None and required_class not in TERMINAL_ARTIFACT_CLASSES:
        raise ValueError(f"Unknown required movement artifact class: {required_class}")
    history = state.get("history")
    validate_artifact_history(history)
    if history[-1] != artifact_class:
        raise ValueError("Artifact history does not end at the declared artifact class")
    if any(value in PACKAGED_ARTIFACT_CLASSES for value in history):
        raise ValueError("Movement artifact state cannot contain packaging transitions")
    persisted_lineage_complete = state.get("lineageComplete")
    if persisted_lineage_complete is not None and type(persisted_lineage_complete) is not bool:
        raise ValueError("Artifact lineage completeness must be a boolean")
    if artifact_class == FULL_CLIP_BAKE:
        lineage_complete = _has_complete_full_clip_lineage(
            history,
            state.get("selectionEvidence"),
        )
    elif artifact_class == CYCLIC_REBAKE:
        lineage_complete = _has_complete_cycle_lineage(
            history,
            state.get("selectionEvidence"),
        )
    elif artifact_class == BOUNDED_MOVEMENT_REBAKE:
        lineage_complete = _has_complete_bounded_lineage(
            history,
            state.get("selectionEvidence"),
        )
    else:
        lineage_complete = True
    if (
        persisted_lineage_complete is not None
        and persisted_lineage_complete != lineage_complete
    ):
        raise ValueError("Artifact lineage flag does not match its persisted evidence")
    if artifact_class == FULL_CLIP_BAKE and lineage_complete and movement_payload is not None:
        persisted_identity = state["selectionEvidence"]["fullClipBake"]
        if baked_payload_identity(movement_payload) != persisted_identity:
            raise ValueError("Full-clip bake identity does not match its movement payload")
    if artifact_class == CYCLIC_REBAKE and lineage_complete:
        evidence = state.get("selectionEvidence")
        if not _has_complete_cycle_lineage(history, evidence):
            raise ValueError("Cyclic rebake is missing its full-clip bake or cycle-selection evidence")
        if movement_payload is not None:
            persisted_identity = evidence["cyclicRebake"]
            if baked_payload_identity(movement_payload) != persisted_identity:
                raise ValueError("Cyclic rebake identity does not match its movement payload")
            if not _selection_interval_matches_payload(
                evidence["cycleSelection"]["interval"],
                movement_payload,
                source_interval=evidence["cycleSelection"].get("sourceInterval"),
            ):
                raise ValueError("Cyclic rebake interval does not match its selected-cycle evidence")
    if artifact_class == BOUNDED_MOVEMENT_REBAKE and lineage_complete:
        evidence = state.get("selectionEvidence")
        selection = evidence["boundedMovementSelection"]
        persisted_parent_identity = selection.get("sourceParent")
        if source_parent_payload is not None:
            if not isinstance(persisted_parent_identity, dict):
                raise ValueError(
                    "Bounded movement selection has no source-parent identity"
                )
            if baked_payload_identity(source_parent_payload) != persisted_parent_identity:
                raise ValueError(
                    "Bounded movement source-parent identity does not match its parent payload"
                )
            if "sourceInterval" in selection:
                expected_source_interval = _source_interval_for_selected_parent(
                    source_parent_payload, selection.get("interval") or {}
                )
                if expected_source_interval != selection.get("sourceInterval"):
                    raise ValueError(
                        "Bounded movement source interval does not match its parent payload"
                    )
        if movement_payload is not None:
            payload_loop = movement_payload.get("loop")
            payload_loop_enabled = (
                isinstance(payload_loop, dict) and payload_loop.get("enabled") is True
            )
            if evidence.get("loopEnabled") is not payload_loop_enabled:
                raise ValueError("Bounded rebake loop state does not match its movement payload")
            persisted_identity = evidence["boundedMovementRebake"]
            if baked_payload_identity(movement_payload) != persisted_identity:
                raise ValueError("Bounded rebake identity does not match its movement payload")
            if not _selection_interval_matches_payload(
                evidence["boundedMovementSelection"]["interval"],
                movement_payload,
                source_interval=evidence["boundedMovementSelection"].get("sourceInterval"),
            ):
                raise ValueError("Bounded rebake interval does not match its movement-selection evidence")
    expected_terminal = expected_artifact_terminal(artifact_class, required_class)
    if not lineage_complete:
        expected_terminal = False
    if type(state.get("terminal")) is not bool or state["terminal"] != expected_terminal:
        raise ValueError("Artifact terminal flag does not match its class and required class")
    evidence = state.get("selectionEvidence")
    if evidence is not None and not isinstance(evidence, dict):
        raise ValueError("Artifact selection evidence must be an object")
    return state


def validate_packaged_artifact_state(
    state: Any,
    *,
    movement_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a terminal package state and its allowed transition from a movement."""
    if not isinstance(state, dict):
        raise ValueError("Packaged artifact state must be an object")
    if type(state.get("schemaVersion")) is not int or state["schemaVersion"] != 1:
        raise ValueError("Unsupported packaged artifact state schema version")
    artifact_class = state.get("artifactClass")
    if not isinstance(artifact_class, str):
        raise ValueError("Packaged artifact class must be a string")
    if artifact_class not in PACKAGED_ARTIFACT_CLASSES:
        raise ValueError(f"Unknown packaged artifact class: {artifact_class}")
    expected_approval = artifact_class == PACKAGED_MOVEMENT
    if (
        type(state.get("approvedMovement")) is not bool
        or state["approvedMovement"] != expected_approval
    ):
        raise ValueError("Packaged artifact approval flag does not match its class")
    if type(state.get("terminal")) is not bool or state["terminal"] is not True:
        raise ValueError("Packaged artifact state must be terminal")
    parent_class = state.get("parentArtifactClass")
    if not isinstance(parent_class, str):
        raise ValueError("Packaged movement parent class must be a string")
    if parent_class not in TERMINAL_ARTIFACT_CLASSES:
        raise ValueError(f"Unknown packaged movement parent class: {parent_class}")
    history = state.get("history")
    validate_artifact_history(history)
    if len(history) < 2 or history[-2] != parent_class or history[-1] != artifact_class:
        raise ValueError("Packaged artifact history does not match its parent and package class")
    if movement_state is None:
        if "parentTerminal" not in state:
            raise ValueError("Packaged artifact state is missing its parent terminal status")
        movement_state = {
            "schemaVersion": 1,
            "artifactClass": parent_class,
            "requiredClass": state.get("requiredClass"),
            "terminal": state.get("parentTerminal"),
            "lineageComplete": state.get("lineageComplete"),
            "history": history[:-1],
            "selectionEvidence": state.get("selectionEvidence", {}),
        }
    movement_state = validate_artifact_state(movement_state)
    if (
        movement_state["artifactClass"] != parent_class
        or movement_state["history"] != history[:-1]
        or (
            "parentTerminal" in state
            and state["parentTerminal"] != movement_state["terminal"]
        )
        or (
            "requiredClass" in state
            and state["requiredClass"] != movement_state.get("requiredClass")
        )
        or (
            "lineageComplete" in state
            and state["lineageComplete"] != movement_state.get("lineageComplete")
        )
        or (
            "selectionEvidence" in state
            and state["selectionEvidence"] != movement_state.get("selectionEvidence", {})
        )
    ):
        raise ValueError("Packaged artifact state differs from its persisted movement parent")
    if expected_approval and not movement_state["terminal"]:
        raise ValueError("An unaccepted movement cannot be packaged as approved")
    return state


def build_packaged_artifact_state(
    movement_state: dict[str, Any],
    *,
    package_class: str,
) -> dict[str, Any]:
    """Append a permitted package transition to a validated movement state."""
    validate_artifact_state(movement_state)
    if package_class not in PACKAGED_ARTIFACT_CLASSES:
        raise ValueError(f"Unknown package class: {package_class}")
    if package_class == PACKAGED_MOVEMENT and not movement_state["terminal"]:
        raise ValueError("An unaccepted movement cannot be packaged as approved")
    packaged_state = {
        "schemaVersion": 1,
        "artifactClass": package_class,
        "terminal": True,
        "approvedMovement": package_class == PACKAGED_MOVEMENT,
        "parentArtifactClass": movement_state["artifactClass"],
        "parentTerminal": movement_state["terminal"],
        "lineageComplete": movement_state.get("lineageComplete"),
        "requiredClass": movement_state.get("requiredClass"),
        "selectionEvidence": movement_state.get("selectionEvidence", {}),
        "history": [*movement_state["history"], package_class],
    }
    validate_packaged_artifact_state(packaged_state, movement_state=movement_state)
    return packaged_state


def classify_baked_artifact(
    *,
    loop_enabled: bool,
    requires_cycle: bool,
    completion_mode: str,
    selection_class: str,
) -> str:
    """Classify a baked Wear artifact from its contract and actual loop state."""
    if requires_cycle:
        return CYCLIC_REBAKE if loop_enabled else FULL_CLIP_BAKE
    if completion_mode == "distinct_end_state":
        return (
            BOUNDED_MOVEMENT_REBAKE
            if selection_class == BOUNDED_MOVEMENT_SELECTION
            else FULL_CLIP_BAKE
        )
    if selection_class == BOUNDED_MOVEMENT_SELECTION:
        return BOUNDED_MOVEMENT_REBAKE
    return CYCLIC_REBAKE if loop_enabled else FULL_CLIP_BAKE


def build_artifact_state(
    *,
    artifact_class: str,
    selection_class: str,
    required_class: str | None,
    selection_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record the concrete state transition and whether it may be packaged."""
    if artifact_class == CYCLIC_REBAKE:
        if selection_class not in {FULL_CLIP_BAKE, CYCLE_SELECTION}:
            raise ValueError(f"Invalid source class for cyclic rebake: {selection_class}")
        lineage_complete = _has_complete_cycle_lineage(
            [FULL_CLIP_BAKE, CYCLE_SELECTION, CYCLIC_REBAKE],
            selection_evidence,
        )
        history = (
            [FULL_CLIP_BAKE, CYCLE_SELECTION, CYCLIC_REBAKE]
            if lineage_complete
            else [CYCLE_SELECTION, CYCLIC_REBAKE]
        )
    elif artifact_class == BOUNDED_MOVEMENT_REBAKE:
        if selection_class != BOUNDED_MOVEMENT_SELECTION:
            raise ValueError(
                f"Invalid source class for bounded movement rebake: {selection_class}"
            )
        history = [BOUNDED_MOVEMENT_SELECTION, BOUNDED_MOVEMENT_REBAKE]
        lineage_complete = _has_complete_bounded_lineage(history, selection_evidence)
    elif artifact_class == FULL_CLIP_BAKE:
        history = [FULL_CLIP_BAKE]
        lineage_complete = _has_complete_full_clip_lineage(history, selection_evidence)
    else:
        history = [FULL_CLIP_BAKE]
        lineage_complete = True
    validate_artifact_history(history)

    state = {
        "schemaVersion": 1,
        "artifactClass": artifact_class,
        "requiredClass": required_class,
        "terminal": expected_artifact_terminal(artifact_class, required_class) and lineage_complete,
        "lineageComplete": lineage_complete,
        "history": history,
        "selectionEvidence": selection_evidence or {},
    }
    validate_artifact_state(state)
    return state


def baked_payload_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a content identity for a baked source movement."""
    if not isinstance(payload, dict) or not isinstance(payload.get("frames"), list):
        raise ValueError("A baked payload identity requires frames")
    identity_payload = {
        "kind": payload.get("kind"),
        "source": payload.get("source"),
        "fps": payload.get("fps"),
        "frameCount": payload.get("frameCount"),
        "jointNames": payload.get("jointNames"),
        "rootJoint": payload.get("rootJoint"),
        "loop": payload.get("loop"),
        "selectedPreviewSettings": payload.get("selectedPreviewSettings"),
        "bakedPreviewConfiguration": payload.get("bakedPreviewConfiguration"),
        "wearDisplay": payload.get("wearDisplay"),
        "renderFloorY": payload.get("renderFloorY"),
        "groundContactMode": payload.get("groundContactMode"),
        "elevatedSupportSurfaces": payload.get("elevatedSupportSurfaces"),
        "bounds": payload.get("bounds"),
        "frames": payload["frames"],
    }
    encoded = json.dumps(
        identity_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        "algorithm": "sha256",
        "identityVersion": 2,
        "contentSha256": hashlib.sha256(encoded).hexdigest(),
        "frameCount": len(payload["frames"]),
        "fps": payload.get("fps"),
    }


def cycle_selection_evidence(
    full_clip_payload: dict[str, Any],
    selected_interval: dict[str, Any],
) -> dict[str, Any]:
    """Bind a selected interval to the full-clip bake from which it was cut."""
    full_clip_identity = baked_payload_identity(full_clip_payload)
    interval = _selection_interval(selected_interval)
    if not _is_valid_selection_interval(interval):
        raise ValueError("Cycle selection is missing complete source interval bounds")
    source_interval = _source_interval_for_selected_parent(full_clip_payload, interval)
    selection_payload = {
        "fullClipContentSha256": full_clip_identity["contentSha256"],
        "interval": interval,
        **({"sourceInterval": source_interval} if source_interval is not None else {}),
    }
    selection_id = _selection_id(selection_payload)
    return {
        "fullClipBake": full_clip_identity,
        "cycleSelection": {
            "selectionId": selection_id,
            "interval": interval,
            **({"sourceInterval": source_interval} if source_interval is not None else {}),
        },
    }


def bounded_movement_selection_evidence(
    selected_interval: dict[str, Any],
    *,
    source_parent_payload: dict[str, Any],
) -> dict[str, Any]:
    """Bind a new bounded selection to its interval and source-parent bake."""
    interval = _selection_interval(selected_interval)
    if not _is_valid_selection_interval(interval):
        raise ValueError("Bounded movement selection is missing complete source interval bounds")
    source_parent_identity = baked_payload_identity(source_parent_payload)
    source_interval = _source_interval_for_selected_parent(source_parent_payload, interval)
    selection_payload = {
        "sourceParentContentSha256": source_parent_identity["contentSha256"],
        "interval": interval,
        **({"sourceInterval": source_interval} if source_interval is not None else {}),
    }
    return {
        "sourceParent": source_parent_identity,
        "selectionId": _selection_id(selection_payload),
        "interval": interval,
        **({"sourceInterval": source_interval} if source_interval is not None else {}),
    }


def _source_interval_for_selected_parent(
    parent_payload: dict[str, Any], interval: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve selected local bounds to exact retained source endpoints."""
    frames = parent_payload.get("frames") if isinstance(parent_payload, dict) else None
    if not isinstance(frames, list):
        return None
    source_frames = [frame for frame in frames if isinstance(frame, dict)
                     and not frame.get("syntheticLoopBridge")]
    start_index, end_index = interval["startFrame"], interval["endFrame"]
    if end_index >= len(source_frames):
        return None
    first, last = source_frames[start_index], source_frames[end_index]
    try:
        first_time = float(first["timeSec"])
        last_time = float(last["timeSec"])
        start_time = float(interval["startTimeSec"])
        end_time = float(interval["endTimeSec"])
        first_source_time = float(first["sourceTimeSec"])
        last_source_time = float(last["sourceTimeSec"])
        first_source_frame = first["sourceFrameIndex"]
        last_source_frame = last["sourceFrameIndex"]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        type(first_source_frame) is not int
        or type(last_source_frame) is not int
        or not all(math.isfinite(value) for value in (
            first_time, last_time, start_time, end_time,
            first_source_time, last_source_time,
        ))
        or not math.isclose(first_time, start_time, rel_tol=0.0, abs_tol=1e-6)
        or not math.isclose(last_time, end_time, rel_tol=0.0, abs_tol=1e-6)
        or last_source_frame <= first_source_frame
        or last_source_time <= first_source_time
    ):
        return None
    return {
        "type": interval["type"],
        "startFrame": first_source_frame,
        "endFrame": last_source_frame,
        "startTimeSec": first_source_time,
        "endTimeSec": last_source_time,
        "durationSec": last_source_time - first_source_time,
    }


def _has_complete_cycle_lineage(history: Any, evidence: Any) -> bool:
    if history != [FULL_CLIP_BAKE, CYCLE_SELECTION, CYCLIC_REBAKE]:
        return False
    if not isinstance(evidence, dict):
        return False
    full_clip = evidence.get("fullClipBake")
    selection = evidence.get("cycleSelection")
    if not isinstance(full_clip, dict) or not isinstance(selection, dict):
        return False
    full_clip_digest = full_clip.get("contentSha256")
    selection_id = selection.get("selectionId")
    interval = selection.get("interval")
    source_interval = selection.get("sourceInterval")
    cyclic_rebake = evidence.get("cyclicRebake")
    cyclic_rebake_digest = (
        cyclic_rebake.get("contentSha256")
        if isinstance(cyclic_rebake, dict)
        else None
    )
    if not _has_valid_payload_identity(full_clip):
        return False
    if not _has_valid_payload_identity(cyclic_rebake):
        return False
    if (not _is_valid_selection_interval(interval)
            or (source_interval is not None
                and not _is_valid_selection_interval(source_interval))):
        return False
    if interval["endFrame"] >= full_clip["frameCount"]:
        return False
    try:
        expected_selection_id = _selection_id({
            "fullClipContentSha256": full_clip_digest,
            "interval": interval,
            **({"sourceInterval": source_interval} if source_interval is not None else {}),
        })
    except (TypeError, ValueError):
        return False
    return (
        isinstance(selection_id, str)
        and selection_id == expected_selection_id
        and isinstance(cyclic_rebake_digest, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", cyclic_rebake_digest))
    )


def _has_complete_full_clip_lineage(history: Any, evidence: Any) -> bool:
    return (
        history == [FULL_CLIP_BAKE]
        and isinstance(evidence, dict)
        and _has_valid_payload_identity(evidence.get("fullClipBake"))
    )


def _has_complete_bounded_lineage(history: Any, evidence: Any) -> bool:
    if history != [BOUNDED_MOVEMENT_SELECTION, BOUNDED_MOVEMENT_REBAKE]:
        return False
    if not isinstance(evidence, dict):
        return False
    # A bounded selection must preserve its distinct start and end states.
    # A cyclic payload cannot be terminal for this artifact class.
    if evidence.get("loopEnabled") is not False:
        return False
    selection = evidence.get("boundedMovementSelection")
    rebake = evidence.get("boundedMovementRebake")
    if not isinstance(selection, dict) or not isinstance(rebake, dict):
        return False
    interval = selection.get("interval")
    selection_id = selection.get("selectionId")
    if not _is_valid_selection_interval(interval) or not _has_valid_payload_identity(rebake):
        return False
    source_parent = selection.get("sourceParent")
    if "sourceInterval" in selection and not _is_valid_selection_interval(
        selection.get("sourceInterval")
    ):
        return False
    source_interval = selection.get("sourceInterval")
    if source_interval is not None and source_parent is None:
        return False
    if source_parent is None:
        # Schema-v1 artifacts written before parent binding remain readable.
        selection_identity = {"interval": interval}
    else:
        if not _has_valid_payload_identity(source_parent):
            return False
        selection_identity = {
            "sourceParentContentSha256": source_parent["contentSha256"],
            "interval": interval,
        }
    if source_interval is not None:
        selection_identity["sourceInterval"] = source_interval
    expected_selection_id = _selection_id(selection_identity)
    return isinstance(selection_id, str) and selection_id == expected_selection_id


def _selection_interval(selected_interval: dict[str, Any]) -> dict[str, Any]:
    return {
        key: selected_interval.get(key)
        for key in (
            "type",
            "startFrame",
            "endFrame",
            "startTimeSec",
            "endTimeSec",
            "durationSec",
        )
        if key in selected_interval
    }


def _is_valid_selection_interval(interval: Any) -> bool:
    if not isinstance(interval, dict):
        return False
    if not isinstance(interval.get("type"), str) or not interval["type"].strip():
        return False
    start_frame = interval.get("startFrame")
    end_frame = interval.get("endFrame")
    start_time = interval.get("startTimeSec")
    end_time = interval.get("endTimeSec")
    duration = interval.get("durationSec")
    if (
        type(start_frame) is not int
        or type(end_frame) is not int
        or start_frame < 0
        or end_frame <= start_frame
    ):
        return False
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in (start_time, end_time, duration)
    ):
        return False
    return (
        float(start_time) >= 0.0
        and float(end_time) > float(start_time)
        and float(duration) > 0.0
        and math.isclose(
            float(duration),
            float(end_time) - float(start_time),
            rel_tol=0.0,
            abs_tol=1e-6,
        )
    )


def _selection_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _selection_interval_matches_payload(
    interval: dict[str, Any],
    payload: dict[str, Any],
    *,
    source_interval: dict[str, Any] | None = None,
) -> bool:
    selected_frame_count = interval["endFrame"] - interval["startFrame"] + 1
    if source_interval is not None:
        interval = source_interval
    loop = payload.get("loop")
    if not isinstance(loop, dict):
        return False
    pairs = (
        ("startFrame", "sourceStartFrame"),
        ("endFrame", "sourceEndFrame"),
        ("startTimeSec", "sourceStartTimeSec"),
        ("endTimeSec", "sourceEndTimeSec"),
    )
    for interval_key, loop_key in pairs:
        selected_value = interval.get(interval_key)
        payload_value = loop.get(loop_key)
        if interval_key.endswith("Frame"):
            if type(payload_value) is not int or selected_value != payload_value:
                return False
        else:
            if (
                not isinstance(payload_value, (int, float))
                or isinstance(payload_value, bool)
                or not math.isfinite(float(payload_value))
                or not math.isclose(
                    float(selected_value),
                    float(payload_value),
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
            ):
                return False
    frames = payload.get("frames")
    if not isinstance(frames, list):
        return False
    source_frames = []
    for frame in frames:
        if not isinstance(frame, dict):
            return False
        if not bool(frame.get("syntheticLoopBridge")):
            source_frames.append(frame)
    if not source_frames:
        return False
    if source_interval is not None and len(source_frames) != selected_frame_count:
        return False
    first_frame = source_frames[0]
    last_frame = source_frames[-1]
    for expected, actual in (
        (interval["startFrame"], first_frame.get("sourceFrameIndex")),
        (interval["endFrame"], last_frame.get("sourceFrameIndex")),
    ):
        if type(actual) is not int or actual != expected:
            return False
    for expected, actual in (
        (interval["startTimeSec"], first_frame.get("sourceTimeSec")),
        (interval["endTimeSec"], last_frame.get("sourceTimeSec")),
    ):
        if (
            not isinstance(actual, (int, float))
            or isinstance(actual, bool)
            or not math.isfinite(float(actual))
            or not math.isclose(float(expected), float(actual), rel_tol=0.0, abs_tol=1e-6)
        ):
            return False

    start_frame = interval["startFrame"]
    end_frame = interval["endFrame"]
    start_time = float(interval["startTimeSec"])
    end_time = float(interval["endTimeSec"])
    previous_source_frame_index = None
    previous_source_time = None
    for frame in source_frames:
        source_frame_index = frame.get("sourceFrameIndex")
        source_time = frame.get("sourceTimeSec")
        if (
            type(source_frame_index) is not int
            or source_frame_index < start_frame
            or source_frame_index > end_frame
            or not isinstance(source_time, (int, float))
            or isinstance(source_time, bool)
            or not math.isfinite(float(source_time))
        ):
            return False
        source_time = float(source_time)
        if (
            source_time < start_time - 1e-6
            or source_time > end_time + 1e-6
            or (
                previous_source_frame_index is not None
                and source_frame_index < previous_source_frame_index
            )
            or (
                previous_source_time is not None
                and source_time < previous_source_time
            )
        ):
            return False
        previous_source_frame_index = source_frame_index
        previous_source_time = source_time
    return True


def _has_valid_payload_identity(identity: Any) -> bool:
    if (
        not isinstance(identity, dict)
        or identity.get("algorithm") != "sha256"
        or type(identity.get("identityVersion")) is not int
        or identity["identityVersion"] != 2
    ):
        return False
    digest = identity.get("contentSha256")
    frame_count = identity.get("frameCount")
    fps = identity.get("fps")
    return (
        isinstance(digest, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", digest))
        and type(frame_count) is int
        and frame_count > 0
        and isinstance(fps, (int, float))
        and not isinstance(fps, bool)
        and math.isfinite(float(fps))
        and float(fps) > 0
    )


def artifact_class_gate(
    *,
    artifact_class: str,
    accepted_classes: set[str] | frozenset[str],
    gate_name: str,
) -> dict[str, Any]:
    accepted = sorted(accepted_classes)
    return {
        "gate": gate_name,
        "passed": artifact_class in accepted_classes,
        "artifactClass": artifact_class,
        "acceptedArtifactClasses": accepted,
        "rejectionReasons": (
            [] if artifact_class in accepted_classes else ["artifact_class_not_accepted"]
        ),
    }
