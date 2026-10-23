"""Shared semantics for source-confirmed stationary surface contacts."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from copy import deepcopy
from typing import Any

import numpy as np

# Contact IK accepts angular residuals at this numerical precision (radians).
# Envelope validation must use the same precision after converting to degrees;
# this is solver roundoff tolerance, separate from source/anatomical allowances.
ANGLE_NUMERICAL_TOLERANCE_RADIANS = 1e-6
_FIT_SUPPORT_EVIDENCE_OVERRIDE: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar(
    "fit_support_evidence_override",
    default=None,
)


def _support_evidence_digest(evidence: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()


def _swap_support_evidence_sides(evidence: dict[str, Any]) -> dict[str, Any]:
    """Swap only anatomical labels; the operation is its own inverse."""
    def swap_side(name: str) -> str:
        if name.startswith("left_"):
            return "right_" + name[5:]
        if name.startswith("right_"):
            return "left_" + name[6:]
        return name

    def swap_observation_key(key: str) -> str:
        for side in ("left", "right"):
            if key.startswith(side) and key[len(side):] in {
                "Foot", "FootSurface", "Hand", "HandSurface",
            }:
                return ("right" if side == "left" else "left") + key[len(side):]
        return key

    joint_fields = {"jointName", "anchorJoint"}
    joint_list_fields = {"stationaryJoints", "joints", "endpoints"}

    def remap(value: Any, *, parent_key: str = "") -> Any:
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                mapped_key = key
                if parent_key == "feet" and key in {"left", "right"}:
                    mapped_key = "right" if key == "left" else "left"
                elif parent_key == "observation":
                    mapped_key = swap_observation_key(key)
                if key in joint_fields and isinstance(child, str):
                    result[mapped_key] = swap_side(child)
                elif key in joint_list_fields and isinstance(child, list):
                    result[mapped_key] = [swap_side(item) if isinstance(item, str) else remap(item)
                                          for item in child]
                else:
                    result[mapped_key] = remap(child, parent_key=key)
            return result
        if isinstance(value, list):
            return [remap(item, parent_key=parent_key) for item in value]
        return value

    return remap(deepcopy(evidence))


def _source_evidence_from_motion_space(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a mapped view and recover its canonical source labels."""
    mapping = evidence.get("motionSpaceMapping")
    if not isinstance(mapping, dict) or mapping.get("bilateralAssignment") != "swapped":
        return None
    expected_digest = mapping.get("sourceEvidenceSha256")
    if not isinstance(expected_digest, str):
        return None
    mapped_content = _without_fit_local_timing_metadata(evidence)
    mapped_content.pop("motionSpaceMapping", None)
    source_evidence = _swap_support_evidence_sides(mapped_content)
    if _support_evidence_digest(source_evidence) != expected_digest:
        return None
    return source_evidence


def _fit_support_evidence_identity(payload: dict[str, Any]) -> str:
    return _support_evidence_digest({
        "sourceFootSupportEvidence": payload.get("sourceFootSupportEvidence") or {},
        "sourcePoseCameraReference": payload.get("sourcePoseCameraReference"),
    })


def _recover_matching_cached_motion_support(payload: dict[str, Any], fallback_mapping: dict[str, Any]):
    """Return a self-validating rig view tied to a stale source mapping digest."""
    cached = payload.get("motionSpaceSupportEvidence")
    if not isinstance(cached, dict):
        return None
    cached_mapping = cached.get("motionSpaceMapping")
    if not isinstance(cached_mapping, dict):
        return None
    if (fallback_mapping.get("bilateralAssignment") != "swapped"
            or cached_mapping.get("bilateralAssignment") != "swapped"
            or fallback_mapping.get("sourceEvidenceSha256")
            != cached_mapping.get("sourceEvidenceSha256")
            or _source_evidence_from_motion_space(cached) is None):
        return None
    fallback = payload.get("sourceFootSupportEvidence")
    if not isinstance(fallback, dict):
        return None
    # The known bug replaced only bodySupport during materialization. Any
    # other difference may be a newer source contact/patch/identity update and
    # must remain authoritative rather than being overwritten by the cache.
    def source_fields(evidence: dict[str, Any]) -> dict[str, Any]:
        fields = deepcopy(evidence)
        fields.pop("bodySupport", None)
        fields.pop("motionSpaceMapping", None)
        return fields

    if source_fields(fallback) != source_fields(cached):
        return None
    camera_reference = payload.get("sourcePoseCameraReference") or {}
    camera = camera_reference.get("camera") if isinstance(camera_reference, dict) else None
    if not isinstance(camera, dict) or camera.get("bilateralAssignment") != "swapped":
        return None
    return cached


def source_support_mapping_unresolved(payload: dict[str, Any]) -> bool:
    """Block reuse/refitting when a mapped source view lost its canonical proof."""
    source = payload.get("sourceFootSupportEvidence")
    if not isinstance(source, dict):
        return False
    mapping = source.get("motionSpaceMapping")
    if not isinstance(mapping, dict) or _source_evidence_from_motion_space(source) is not None:
        return False
    return _recover_matching_cached_motion_support(payload, mapping) is None


@contextmanager
def fit_motion_space_support_evidence_scope(payload: dict[str, Any], evidence: dict[str, Any]):
    """Expose materialized rig-side support only during this fit call tree."""
    evidence = _fit_local_timed_support_evidence(payload, evidence)
    token = _FIT_SUPPORT_EVIDENCE_OVERRIDE.set(
        (_fit_support_evidence_identity(payload), evidence)
    )
    try:
        yield evidence
    finally:
        _FIT_SUPPORT_EVIDENCE_OVERRIDE.reset(token)


def motion_space_support_evidence(
    payload: dict[str, Any],
    *,
    evidence_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return support evidence named in the baked rig's left/right space.

    Source observations retain their original anatomical labels. When camera
    registration assigns those labels to the opposite rig sides, cache a
    remapped view for constraints while leaving the source evidence untouched.
    """
    active_fit_evidence = _FIT_SUPPORT_EVIDENCE_OVERRIDE.get()
    if (
        evidence_override is None
        and active_fit_evidence is not None
        and active_fit_evidence[0] == _fit_support_evidence_identity(payload)
    ):
        return active_fit_evidence[1]

    evidence = evidence_override if isinstance(evidence_override, dict) else (
        payload.get("sourceFootSupportEvidence") or {}
    )
    camera_reference = payload.get("sourcePoseCameraReference") or {}
    camera = camera_reference.get("camera") if isinstance(camera_reference, dict) else None
    camera_is_swapped = isinstance(camera, dict) and camera.get("bilateralAssignment") == "swapped"

    if isinstance(evidence.get("motionSpaceMapping"), dict):
        source_evidence = _source_evidence_from_motion_space(evidence)
        if source_evidence is not None:
            return _fit_local_timed_support_evidence(
                payload, evidence if camera_is_swapped else source_evidence)
        # A stale or modified motion-space view must not silently constrain the
        # opposite rig side. A valid, separately stored mapped view can recover
        # the original source evidence only when both views carry the same
        # original source digest. This handles older artifacts that overwrote
        # the canonical field after materialization without weakening the
        # bilateral mapping check.
        fallback = payload.get("sourceFootSupportEvidence")
        fallback_mapping = (fallback.get("motionSpaceMapping")
                            if isinstance(fallback, dict) else None)
        if isinstance(fallback_mapping, dict):
            recovered = _recover_matching_cached_motion_support(payload, fallback_mapping)
            if recovered is not None:
                return _fit_local_timed_support_evidence(payload, recovered)
        if not isinstance(fallback, dict) or isinstance(fallback_mapping, dict):
            return {}
        evidence = fallback

    if not camera_is_swapped:
        return _fit_local_timed_support_evidence(payload, evidence)

    source_digest = _support_evidence_digest(evidence)
    cached = payload.get("motionSpaceSupportEvidence")
    if isinstance(cached, dict):
        cached_source_evidence = _source_evidence_from_motion_space(cached)
        if (cached_source_evidence is not None
                and _support_evidence_digest(cached_source_evidence) == source_digest):
            return _fit_local_timed_support_evidence(payload, cached)
    mapped = _swap_support_evidence_sides(evidence)
    mapped["motionSpaceMapping"] = {
        "source": "sourceFootSupportEvidence",
        "bilateralAssignment": "swapped",
        "sourceEvidenceSha256": source_digest,
    }
    payload["motionSpaceSupportEvidence"] = mapped
    return _fit_local_timed_support_evidence(payload, mapped)


def mapped_foot_patch_state_indices(evidence, frame_times, frame_count=None):
    """Map fit source-clock samples to native patch rows; unresolved rows are -1.

    Absolute source-video timestamps are required whenever either track declares
    a clock. The equal-length legacy mapping is retained only for clockless,
    same-length tracks, where index identity is the only available authority.
    """
    patch = (evidence or {}).get('footPatchEvidence') or {}
    states_by_side = patch.get('feet') or {}
    first_side = next((value for value in states_by_side.values()
                       if isinstance(value, dict) and isinstance(value.get('states'), list)), None)
    states = first_side.get('states') if isinstance(first_side, dict) else None
    times = [] if frame_times is None else list(frame_times)
    count = len(times) if frame_count is None else int(frame_count)
    unresolved = np.full(max(0, count), -1, dtype=int)
    if not isinstance(states, list) or not states or len(times) != count:
        return unresolved

    patch_declares_clock = (
        patch.get('sourceTimeBasis') is not None
        or patch.get('sourceTimesSec') is not None
    )
    fit_has_clock = any(value is not None for value in times)
    if not patch_declares_clock and not fit_has_clock:
        if len(states) == count:
            return np.arange(count, dtype=int)
        return unresolved
    if patch.get('sourceTimeBasis') != 'absolute_source_video':
        return unresolved

    native_times = patch.get('sourceTimesSec')
    if not isinstance(native_times, list) or len(native_times) != len(states):
        return unresolved
    if any(
        isinstance(value, dict) and isinstance(value.get('states'), list)
        and len(value['states']) != len(native_times)
        for value in states_by_side.values()
    ):
        return unresolved
    try:
        native_times = np.asarray(native_times, dtype=float)
        fit_times = np.asarray([
            np.nan if value is None else float(value) for value in times
        ], dtype=float)
        fps = float(patch.get('sourceFps'))
    except (TypeError, ValueError, OverflowError):
        return unresolved
    if (not np.isfinite(native_times).all() or not np.isfinite(fps) or fps <= 0.
            or np.any(np.diff(native_times) <= 0.)):
        return unresolved
    tolerance = .5 / fps + 1e-6
    mapped = unresolved.copy()
    for frame_index, time_value in enumerate(fit_times):
        if not np.isfinite(time_value):
            continue
        # Tolerance resolves resampling only inside observed coverage. It never
        # extends support before the first or after the last source observation.
        if time_value < native_times[0] - 1e-9 or time_value > native_times[-1] + 1e-9:
            continue
        native_index = int(np.argmin(np.abs(native_times - time_value)))
        if abs(float(native_times[native_index] - time_value)) <= tolerance:
            mapped[frame_index] = native_index
    return mapped


def _fit_patch_contact_runs(evidence, frame_times, native_times, native_count):
    """Build conservative timed contact runs from both source observations."""
    patch = (evidence or {}).get('footPatchEvidence') or {}
    states_by_side = patch.get('feet') or {}
    unresolved = [(-1, -1)] * len(frame_times)
    if patch.get('sourceTimeBasis') != 'absolute_source_video':
        return unresolved, {}, ({}, {})
    try:
        native_times = np.asarray(native_times, dtype=float)
        source_fps = float(patch.get('sourceFps'))
        fit_times = np.asarray([
            np.nan if value is None else float(value) for value in frame_times
        ], dtype=float)
    except (TypeError, ValueError, OverflowError):
        return unresolved, {}, ({}, {})
    frame_count = len(frame_times)
    if any(isinstance(value, dict)
           and isinstance(value.get('states'), list)
           and len(value['states']) != native_count
           for value in states_by_side.values()):
        return unresolved, {}, ({}, {})
    if (native_times.shape != (native_count,) or not np.isfinite(native_times).all()
            or not np.isfinite(source_fps) or source_fps <= 0.
            or np.any(np.diff(native_times) <= 0.)):
        return unresolved, {}, ({}, {})

    # A bracket is either one exact native observation or the two observations
    # surrounding the fit time. Large/dropout gaps and out-of-coverage times
    # stay unresolved rather than carrying contact authority across them.
    brackets = [(-1, -1)] * frame_count
    max_gap = 1.5 / source_fps + 1e-6
    for frame_index, time_value in enumerate(fit_times):
        if (not np.isfinite(time_value) or time_value < native_times[0] - 1e-9
                or time_value > native_times[-1] + 1e-9):
            continue
        upper = int(np.searchsorted(native_times, time_value, side='left'))
        if (upper < native_count
                and abs(float(native_times[upper] - time_value)) <= 1e-9):
            brackets[frame_index] = (upper, upper)
            continue
        lower = upper - 1
        if (lower >= 0 and upper < native_count
                and native_times[upper] - native_times[lower] <= max_gap):
            brackets[frame_index] = (lower, upper)

    # Each observed interval contributes anchor identity only at rows whose
    # actual patch state agrees with that interval. Conflicting identities are
    # marked ambiguous and cannot authorize either endpoint.
    owners = {}
    for side in ('left', 'right'):
        side_record = states_by_side.get(side)
        states = side_record.get('states') if isinstance(side_record, dict) else None
        if not isinstance(states, list) or len(states) != native_count:
            continue
        toe_anchor = [None] * native_count
        ankle_anchor = [None] * native_count
        for key in ('contacts', 'supportContacts'):
            for contact in (evidence or {}).get(key) or []:
                if (not isinstance(contact, dict)
                        or contact.get('supportKind') != 'observed_foot_patch'
                        or contact.get('jointName') != f'{side}_foot'):
                    continue
                state = str(contact.get('contactState') or '').casefold()
                try:
                    start = int(round(float(contact['startRatio']) * (native_count - 1)))
                    end = int(round(float(contact['endRatio']) * (native_count - 1)))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if not (0 <= start <= end < native_count):
                    continue
                for row in range(start, end + 1):
                    if str(states[row]).casefold() != state:
                        continue
                    if state in {'full_sole', 'toe_only'}:
                        group = contact.get('anchorGroupId')
                        if group is not None:
                            toe_anchor[row] = (group if toe_anchor[row] in (None, group)
                                               else False)
                    if state == 'full_sole':
                        group = contact.get('ankleAnchorGroupId')
                        if group is not None:
                            ankle_anchor[row] = (group if ankle_anchor[row] in (None, group)
                                                 else False)
        owners[side] = (states, toe_anchor, ankle_anchor)

    toe_bridges = {}
    fullsole_bridges = {}

    def one_contact_interval_covers(side, state, lower, upper, *, toe_group=None,
                                    ankle_group=None):
        for key in ('contacts', 'supportContacts'):
            for contact in (evidence or {}).get(key) or []:
                if (not isinstance(contact, dict)
                        or contact.get('supportKind') != 'observed_foot_patch'
                        or contact.get('jointName') != f'{side}_foot'
                        or str(contact.get('contactState') or '').casefold() != state
                        or (toe_group is not None
                            and contact.get('anchorGroupId') != toe_group)
                        or (ankle_group is not None
                            and contact.get('ankleAnchorGroupId') != ankle_group)):
                    continue
                try:
                    start = int(round(float(contact['startRatio']) * (native_count - 1)))
                    end = int(round(float(contact['endRatio']) * (native_count - 1)))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if start <= lower <= upper <= end:
                    return True
        return False

    for frame_index, (lower, upper) in enumerate(brackets):
        if lower < 0 or upper < 0 or lower == upper:
            continue
        for side, (states, toe_anchor, ankle_anchor) in owners.items():
            first, second = str(states[lower]).casefold(), str(states[upper]).casefold()
            group0, group1 = toe_anchor[lower], toe_anchor[upper]
            if (first in {'full_sole', 'toe_only'}
                    and second in {'full_sole', 'toe_only'}
                    and group0 not in (None, False) and group0 == group1):
                if (first != second or not one_contact_interval_covers(
                        side, first, lower, upper, toe_group=group0)):
                    toe_bridges.setdefault((side, group0), []).append(frame_index)
            ankle0, ankle1 = ankle_anchor[lower], ankle_anchor[upper]
            if (first == second == 'full_sole'
                    and ankle0 not in (None, False) and ankle0 == ankle1
                    and group0 not in (None, False) and group0 == group1
                    and not one_contact_interval_covers(
                        side, 'full_sole', lower, upper,
                        toe_group=group0, ankle_group=ankle0)):
                fullsole_bridges.setdefault((side, ankle0), []).append(frame_index)

    return brackets, owners, (toe_bridges, fullsole_bridges)


def _fit_local_timed_support_evidence(payload, evidence):
    """Attach ephemeral frame-clock mappings without changing cached authority."""
    if not isinstance(evidence, dict):
        return evidence if isinstance(evidence, dict) else {}
    frames = payload.get('frames') or []
    if not frames:
        return evidence
    patch = evidence.get('footPatchEvidence') or {}
    if patch.get('available') is not True:
        return evidence
    frame_times = [
        None if frame.get('syntheticLoopBridge') else frame.get('sourceTimeSec')
        for frame in frames if isinstance(frame, dict)
    ]
    if len(frame_times) != len(frames):
        return evidence
    states_by_side = patch.get('feet') or {}
    representative = next((value.get('states') for value in states_by_side.values()
                           if isinstance(value, dict) and isinstance(value.get('states'), list)), None)
    if not isinstance(representative, list) or not representative:
        return evidence
    has_patch_clock = (patch.get('sourceTimeBasis') is not None
                       or patch.get('sourceTimesSec') is not None)
    has_fit_clock = any(frame.get('sourceTimeSec') is not None
                        for frame in frames if isinstance(frame, dict))
    if (not has_patch_clock and not has_fit_clock
            and len(representative) == len(frames)):
        # Equal-length clockless legacy tracks have an unambiguous index map.
        # Keep their canonical view compact; consumers already use indices.
        return evidence
    evidence = _without_fit_local_timing_metadata(evidence)
    state_indices = mapped_foot_patch_state_indices(evidence, frame_times, len(frames))
    result = deepcopy(evidence)
    result['_fitFrameStateIndices'] = state_indices.tolist()
    result['_fitFrameCount'] = len(frames)
    brackets, owners, bridges = _fit_patch_contact_runs(
        evidence, frame_times, patch.get('sourceTimesSec'), len(representative))

    # Convert observed patch interval ratios through their native observation
    # rows. A fit sample between native rows is owned only when both bracket
    # observations support that same contact state and anchor.
    native_count = len(representative)
    for key in ('contacts', 'supportContacts'):
        records = result.get(key)
        if not isinstance(records, list):
            continue
        for contact in records:
            if (not isinstance(contact, dict)
                    or contact.get('supportKind') != 'observed_foot_patch'
                    or contact.get('startRatio') is None
                    or contact.get('endRatio') is None):
                continue
            try:
                start_ratio, end_ratio = float(contact['startRatio']), float(contact['endRatio'])
            except (TypeError, ValueError, OverflowError):
                contact['_fitFrameBounds'] = None
                continue
            if (not np.isfinite(start_ratio) or not np.isfinite(end_ratio)
                    or start_ratio < 0. or end_ratio > 1. or start_ratio > end_ratio):
                contact['_fitFrameBounds'] = None
                continue
            native_start = int(round(start_ratio * (native_count - 1)))
            native_end = int(round(end_ratio * (native_count - 1)))
            active = np.zeros(len(frames), dtype=bool)
            joint = str(contact.get('jointName') or '')
            side, separator, part = joint.partition('_')
            owner = owners.get(side)
            state = str(contact.get('contactState') or '').casefold()
            if owner is None:
                contact['_fitFrameRuns'] = []
                contact['_fitFrameCount'] = len(frames)
                continue
            states, toe_anchors, ankle_anchors = owner
            for frame_index, (lower, upper) in enumerate(brackets):
                if lower < 0 or upper < 0:
                    continue
                interval_matches = (native_start <= lower <= native_end
                                    and native_start <= upper <= native_end)
                state_matches = (
                    str(states[lower]).casefold() == state
                    and str(states[upper]).casefold() == state)
                if lower == upper:
                    interval_matches = native_start <= lower <= native_end
                    state_matches = str(states[lower]).casefold() == state
                if lower != upper and interval_matches and state_matches:
                    toe_group = contact.get('anchorGroupId')
                    ankle_group = contact.get('ankleAnchorGroupId')
                    if state == 'full_sole':
                        state_matches = (
                            toe_group is not None and ankle_group is not None
                            and toe_anchors[lower] == toe_group == toe_anchors[upper]
                            and ankle_anchors[lower] == ankle_group == ankle_anchors[upper])
                    elif state == 'toe_only':
                        state_matches = (
                            toe_group is not None
                            and toe_anchors[lower] == toe_group == toe_anchors[upper])
                if interval_matches and state_matches:
                    active[frame_index] = True
            contact['_fitFrameRuns'] = _contiguous_runs(active)
            contact['_fitFrameCount'] = len(frames)

    # The toe anchor persists across adjacent full-sole/toe-only observations
    # with the same identity. Emit it as a toe-only bridge so the ankle remains
    # governed by the stricter full-sole interval above.
    toe_bridges, fullsole_bridges = bridges
    for (side, anchor_id), indexes in toe_bridges.items():
        source_entry = next(((key, contact) for key in ('contacts', 'supportContacts')
                             for contact in evidence.get(key) or []
                             if isinstance(contact, dict)
                             and contact.get('supportKind') == 'observed_foot_patch'
                             and contact.get('jointName') == f'{side}_foot'
                             and contact.get('contactState') == 'toe_only'
                             and contact.get('anchorGroupId') == anchor_id), None)
        if source_entry is None:
            continue
        source_key, source = source_entry
        bridge = {**source, 'contactState': 'toe_only', '_fitGeneratedBridge': True,
                  '_fitFrameRuns': _contiguous_runs(np.isin(np.arange(len(frames)), indexes)),
                  '_fitFrameCount': len(frames)}
        result.setdefault(source_key, []).append(bridge)
    for (side, anchor_id), indexes in fullsole_bridges.items():
        source_entry = next(((key, contact) for key in ('contacts', 'supportContacts')
                             for contact in evidence.get(key) or []
                             if isinstance(contact, dict)
                             and contact.get('supportKind') == 'observed_foot_patch'
                             and contact.get('jointName') == f'{side}_foot'
                             and contact.get('contactState') == 'full_sole'
                             and contact.get('ankleAnchorGroupId') == anchor_id), None)
        if source_entry is None:
            continue
        source_key, source = source_entry
        bridge = {**source, '_fitGeneratedBridge': True,
                  '_fitFrameRuns': _contiguous_runs(np.isin(np.arange(len(frames)), indexes)),
                  '_fitFrameCount': len(frames)}
        result.setdefault(source_key, []).append(bridge)
    return result


def _contiguous_runs(mask):
    indexes = np.flatnonzero(mask)
    if not len(indexes):
        return []
    breaks = np.flatnonzero(np.diff(indexes) > 1) + 1
    return [[int(run[0]), int(run[-1])] for run in np.split(indexes, breaks)]


def _without_fit_local_timing_metadata(evidence):
    """Strip derived fit-clock fields before validating a canonical cache hash."""
    cleaned = deepcopy(evidence)
    if not isinstance(cleaned, dict):
        return cleaned
    cleaned.pop('_fitFrameStateIndices', None)
    cleaned.pop('_fitFrameCount', None)
    for key in ('contacts', 'supportContacts'):
        records = cleaned.get(key)
        if not isinstance(records, list):
            continue
        cleaned[key] = [contact for contact in records
                        if not (isinstance(contact, dict)
                                and contact.get('_fitGeneratedBridge') is True)]
        for contact in cleaned[key]:
            if isinstance(contact, dict):
                contact.pop('_fitFrameBounds', None)
                contact.pop('_fitFrameRuns', None)
                contact.pop('_fitFrameCount', None)
    return cleaned


def has_continuous_ankle_support(evidence, side):
    """Only a fully observed sole track can preserve a legacy whole-clip ankle pin."""
    foot = ((evidence or {}).get('feet') or {}).get(side) or {}
    states = (((evidence or {}).get('footPatchEvidence') or {}).get('feet') or {}).get(side) or {}
    patch = (evidence or {}).get('footPatchEvidence') or {}
    if patch.get('available') is True:
        if foot.get('reconstructed3dSupport'):
            return False
        track = states.get('states') or []
        if not track or any(str(state).casefold() != 'full_sole' for state in track):
            return False
    return bool(foot.get('continuousSupport') and is_stationary_contact(foot)
                and not any(state in {'toe_only', 'heel_only', 'airborne'}
                            for state in states.get('states') or []))


def motion_support_contacts(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize modern and legacy support evidence without inventing contacts."""
    evidence = evidence or {}
    contacts = list(evidence.get("contacts") or []) + list(evidence.get("supportContacts") or [])
    for side, record in (evidence.get("feet") or {}).items():
        if isinstance(record, dict) and has_continuous_ankle_support(evidence, side):
            contact = {**record, "jointName": record.get("jointName", f"{side}_ankle"),
                       "startRatio": 0.0, "endRatio": 1.0}
            state_indexes = evidence.get('_fitFrameStateIndices')
            if isinstance(state_indexes, list):
                side_states = (((evidence.get('footPatchEvidence') or {}).get('feet') or {})
                               .get(side) or {}).get('states') or []
                active = [index >= 0 and index < len(side_states)
                          and str(side_states[index]).casefold() == 'full_sole'
                          for index in state_indexes]
                contact['_fitFrameRuns'] = _contiguous_runs(active)
                contact['_fitFrameCount'] = len(state_indexes)
            contacts.append(contact)
    patch_available = (evidence.get('footPatchEvidence') or {}).get('available') is True
    expanded = []
    for contact in contacts:
        if (not isinstance(contact, dict)
                or (patch_available and contact.get('reconstructed3dSupport')
                    and str(contact.get('jointName') or '').endswith(('_ankle', '_foot', '_heel')))):
            continue
        if '_fitFrameRuns' in contact:
            for start, end in contact['_fitFrameRuns']:
                expanded.append({**contact, '_fitFrameBounds': [start, end]})
        elif '_fitFrameBounds' not in contact or contact.get('_fitFrameBounds') is not None:
            expanded.append(contact)
    return expanded


def is_stationary_contact(contact: dict[str, Any]) -> bool:
    """Surface proximity alone does not authorize a tangential lock."""
    if str(contact.get("surfaceKind") or "").startswith("contract_"):
        # A generated posture plus a slow image-space joint is not observed
        # physical contact. Treat it as advisory, including cached evidence.
        return False
    motion = str(contact.get("contactMotion") or "").casefold()
    if motion in {"sliding", "rolling", "moving", "unknown"}:
        return False
    if contact.get("allowSliding") is True:
        return False
    if contact.get("verticalOnly") is True:
        return motion == "stationary"
    return True


def contact_frame_bounds(contact: dict[str, Any], count: int) -> tuple[int, int]:
    if '_fitFrameBounds' in contact:
        if contact.get('_fitFrameCount') not in (None, count):
            return 0, -1
        bounds = contact.get('_fitFrameBounds')
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            return 0, -1
        return int(bounds[0]), int(bounds[1])
    start = (
        round(float(contact["startRatio"]) * (count - 1))
        if contact.get("startRatio") is not None else int(contact.get("startFrame", 0))
    )
    end = (
        round(float(contact["endRatio"]) * (count - 1))
        if contact.get("endRatio") is not None else int(contact.get("endFrame", count - 1))
    )
    return max(0, min(count - 1, start)), max(0, min(count - 1, end))


def _airborne_epoch_track(evidence, joint_name, count):
    """Map explicit release epochs to fit frames with one pass over patch states."""
    side = str(joint_name).split("_", 1)[0]
    patch = (evidence or {}).get("footPatchEvidence") or {}
    foot = (patch.get("feet") or {}).get(side)
    states = foot.get("states") if isinstance(foot, dict) else None
    if not isinstance(states, (list, tuple)) or not states:
        return None
    if count <= 0:
        return []
    state_indexes = (evidence or {}).get('_fitFrameStateIndices')
    if isinstance(state_indexes, list) and len(state_indexes) == count:
        state_indexes = np.asarray(state_indexes, dtype=int)
    elif len(states) == count:
        state_indexes = np.arange(count, dtype=int)
    else:
        return None
    epoch = 0
    was_airborne = False
    epochs = []
    for state_index in state_indexes:
        if state_index < 0 or state_index >= len(states):
            epochs.append(None)
            was_airborne = None
            continue
        state = states[state_index]
        airborne = str(state).casefold() == "airborne"
        if airborne and was_airborne is False:
            epoch += 1
        was_airborne = airborne
        epochs.append(epoch)
    return epochs


def _airborne_scoped_anchor_id(group_id, epoch):
    if group_id is None:
        return None
    group_id = str(group_id)
    if epoch is None or epoch == 0:
        return group_id
    return f"{group_id}:after_airborne:{epoch}"


def is_observed_ground_contact(contact, evidence):
    """Use explicit contact and source-reviewed surface identity before legacy inference."""
    surface = str(contact.get('surfaceKind') or '').lower()
    if surface:
        return surface in {'ground', 'floor', 'ground_plane'}
    if contact.get('supportKind') == 'observed_foot_patch':
        observation = (evidence or {}).get('bodySupportObservation') or {}
        observed = observation.get('observation') if isinstance(observation, dict) else None
        if (isinstance(observation, dict) and observation.get('status') == 'observed'
                and isinstance(observed, dict)):
            side = str(contact.get('jointName') or '').split('_', 1)[0]
            observed_surface = str(observed.get(f'{side}FootSurface') or '').strip().lower()
            if observed_surface:
                return observed_surface == 'ground'
    return (contact.get('supportKind') == 'observed_foot_patch'
            and (evidence or {}).get('sharedSupportPlaneY') is not None)


def observed_ground_contact_mask(evidence, names, count):
    """Only observed stationary toe/sole contacts own a floor-height anchor."""
    result = np.zeros((count, len(names)), dtype=bool)
    support = (evidence or {}).get('bodySupport') or {}
    calibrated = set(support.get('stationaryJoints', [])) if (
        support.get('required') and support.get('status') == 'confirmed') else set()
    for contact in motion_support_contacts(evidence):
        name = str(contact.get('jointName') or '')
        if (name not in names or name in calibrated or not name.endswith('_foot')
                or contact.get('contactState') == 'heel_only'
                or not is_stationary_contact(contact)
                or not is_observed_ground_contact(contact, evidence)):
            continue
        start, end = contact_frame_bounds(contact, count)
        result[start:end+1, names.index(name)] = True
    return result


def vertical_only_contact_mask(evidence, names, count):
    """Select stationary contacts that constrain height without a tangent pin."""
    result = np.zeros((count, len(names)), dtype=bool)
    for contact in motion_support_contacts(evidence):
        if (contact.get('verticalOnly') is not True
                and (contact.get('contactState') != 'toe_only'
                     or contact.get('verticalOnly') is False)):
            continue
        if not is_stationary_contact(contact) or contact.get('contactState') == 'heel_only':
            continue
        name = str(contact.get('jointName') or '')
        if name not in names:
            continue
        start, end = contact_frame_bounds(contact, count)
        result[start:end + 1, names.index(name)] = True
    return result


def stationary_contact_anchor_ids(evidence, names, count):
    """Transport observed anchor identity without adding contact frames."""
    result = np.full((count, len(names)), None, dtype=object)
    airborne_epochs = {}
    for contact in motion_support_contacts(evidence):
        if not is_stationary_contact(contact):
            continue
        name = contact.get('jointName', '')
        identities = {name: contact.get('anchorGroupId')}
        if contact.get('contactState') == 'full_sole' and name.endswith('_foot'):
            identities[name.replace('_foot', '_ankle')] = contact.get('ankleAnchorGroupId')
        start, end = contact_frame_bounds(contact, count)
        for joint, group in identities.items():
            if joint not in names or group is None:
                continue
            joint_index = names.index(joint)
            side = joint.split('_', 1)[0]
            if side not in airborne_epochs:
                airborne_epochs[side] = _airborne_epoch_track(evidence, joint, count)
            epochs = airborne_epochs[side]
            for frame_index in range(start, end + 1):
                result[frame_index, joint_index] = _airborne_scoped_anchor_id(
                    group, None if epochs is None else epochs[frame_index],
                )
    return result


def vertical_only_contact_targets(points, evidence, names, *, floor=None):
    """Return height-only targets while leaving each contact's tangent free."""
    values = np.asarray(points, dtype=float)
    mask = vertical_only_contact_mask(evidence, names, len(values))
    targets = values.copy()
    if not np.any(mask):
        return mask, targets
    anchor_ids = stationary_contact_anchor_ids(evidence, names, len(values))
    for joint in range(len(names)):
        track, _ = stationary_target_track(
            values[:, joint], mask[:, joint], anchor_ids=anchor_ids[:, joint],
        )
        targets[:, joint] = track
    ground = observed_ground_contact_mask(evidence, names, len(values)) & mask
    ground_y = floor if floor is not None else (evidence or {}).get('sharedSupportPlaneY')
    try:
        ground_y = float(ground_y)
    except (TypeError, ValueError, OverflowError):
        ground_y = None
    if ground_y is not None and np.isfinite(ground_y):
        targets[:, :, 1][ground] = ground_y
    return mask, targets


def stationary_target_track(
    points: np.ndarray, mask: np.ndarray, *, fps: float | None = None, anchor_ids=None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """One immutable anchor per connected stance, never across a release.

    With timing available, fit anchors together with free spans so independent
    stance medians cannot compress reconstruction drift into a short release.
    Each stance still has exactly one anchor; releases remain unconstrained.
    """
    targets = points.copy()
    episodes = []
    edges = np.diff(np.r_[False, mask, False].astype(int))
    for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        anchor = np.median(points[start:stop], axis=0)
        targets[start:stop] = anchor
        episodes.append({
            "startFrame": int(start), "endFrame": int(stop - 1),
            "anchor": anchor.tolist(),
            "baselineMaxDistanceFromAnchor": float(np.max(
                np.linalg.norm(points[start:stop] - anchor, axis=1)
            )),
        })
    if fps is None and anchor_ids is not None:
        for group in {value for value in anchor_ids[mask] if value is not None}:
            shared = mask & (anchor_ids == group)
            targets[shared] = np.median(points[shared], axis=0)
    if fps is not None and len(points) >= 3 and episodes:
        from scipy.sparse import csr_matrix, diags, eye
        from scipy.sparse.linalg import spsolve

        groups = np.arange(len(points))
        observed_groups = {}
        for episode in episodes:
            start, stop = episode["startFrame"], episode["endFrame"] + 1
            anchor_id = anchor_ids[start] if anchor_ids is not None else None
            owner = observed_groups.setdefault(anchor_id, start) if anchor_id is not None else start
            groups[start:stop] = owner
        _, columns = np.unique(groups, return_inverse=True)
        mapping = csr_matrix((np.ones(len(points)), (np.arange(len(points)), columns)),
                             shape=(len(points), int(columns.max()) + 1))
        difference = diags([np.ones(len(points) - 2), -2 * np.ones(len(points) - 2),
                            np.ones(len(points) - 2)], [0, 1, 2], shape=(len(points) - 2, len(points)))
        system = eye(len(points)) + (max(fps, 1.) * .15)**4 * difference.T @ difference
        # Robust episode centers supply the data term. Equal columns impose
        # stationary contact exactly rather than smoothing a planted foot.
        anchors = spsolve((mapping.T @ system @ mapping).tocsc(), mapping.T @ targets)
        targets = np.asarray(mapping @ anchors)
    for episode in episodes:
        start, stop = episode["startFrame"], episode["endFrame"] + 1
        anchor = targets[start]
        episode["anchor"] = anchor.tolist()
        episode["baselineMaxDistanceFromAnchor"] = float(np.max(
            np.linalg.norm(points[start:stop] - anchor, axis=1)))
    return targets, episodes


class InfeasibleContactCorrection(ValueError):
    """A contact proposal cannot satisfy its geometric constraints."""


def calibrate_shared_contact_pair(points, mask, anchor_ids, *, distance, ground_mask, floor):
    """Calibrate linked stationary anchors without splitting their identities.

    Each node is one observed anchor, each edge one fixed-length foot. The small
    static solve changes anchor positions, never contact intervals or releases.
    Calibration is bounded to ten percent of the segment length; larger source
    disagreements need new evidence rather than a substantially rewritten stance.
    """
    from scipy.optimize import minimize

    groups = np.full(mask.shape, -1, dtype=int)
    members = []
    for joint in range(2):
        identities = {}
        episode = -1
        for frame in range(len(points)):
            if not mask[frame, joint]:
                continue
            if frame == 0 or not mask[frame - 1, joint]:
                episode += 1
            identity = anchor_ids[frame, joint]
            key = ('observed', identity) if identity is not None else ('episode', episode)
            if key not in identities:
                identities[key] = len(members)
                members.append((joint, []))
            group = identities[key]
            groups[frame, joint] = group
            members[group][1].append(frame)
    reference = np.asarray([np.mean(points[frames, joint], axis=0) for joint, frames in members])
    weights = np.asarray([len(frames) for _, frames in members], dtype=float)
    weights /= weights.max()
    edges = np.unique(groups[np.all(mask, axis=1)], axis=0)
    first, last = edges.T
    length_squared = float(distance)**2
    allowance = .1 * float(distance)
    bounds = [(value - allowance, value + allowance) for value in reference.ravel()]
    for group, (joint, frames) in enumerate(members):
        if floor is not None and np.any(ground_mask[frames, joint]):
            bounds[group * 3 + 1] = (float(floor), float(floor))

    def objective(values):
        delta = values.reshape(-1, 3) - reference
        return .5 * np.sum(weights[:, None] * delta**2) / length_squared

    def gradient(values):
        return (weights[:, None] * (values.reshape(-1, 3) - reference) / length_squared).ravel()

    def lengths(values):
        values = values.reshape(-1, 3)
        return np.sum((values[first] - values[last])**2, axis=1) / length_squared - 1.

    def length_jacobian(values):
        values = values.reshape(-1, 3)
        delta = 2. * (values[first] - values[last]) / length_squared
        jacobian = np.zeros((len(edges), len(reference), 3))
        jacobian[np.arange(len(edges)), first] = delta
        jacobian[np.arange(len(edges)), last] = -delta
        return jacobian.reshape(len(edges), -1)

    def correction_limits(values):
        return 1. - np.sum((values.reshape(-1, 3) - reference)**2, axis=1) / allowance**2

    def correction_jacobian(values):
        jacobian = np.zeros((len(reference), len(reference), 3))
        indexes = np.arange(len(reference))
        jacobian[indexes, indexes] = -2. * (values.reshape(-1, 3) - reference) / allowance**2
        return jacobian.reshape(len(reference), -1)

    solved = minimize(objective, reference.ravel(), jac=gradient, method='SLSQP', bounds=bounds,
                      constraints=[{'type': 'eq', 'fun': lengths, 'jac': length_jacobian},
                                   {'type': 'ineq', 'fun': correction_limits, 'jac': correction_jacobian}],
                      options={'maxiter': 100, 'ftol': 1e-12})
    calibrated = solved.x.reshape(-1, 3)
    errors = np.abs(np.linalg.norm(calibrated[first] - calibrated[last], axis=1) - distance)
    if (not solved.success or not np.isfinite(calibrated).all() or np.max(errors) > 1e-7
            or np.max(np.linalg.norm(calibrated - reference, axis=1)) > allowance + 1e-7):
        raise InfeasibleContactCorrection('Stationary anchors cannot share rigid lengths within the calibration allowance')
    result = points.copy()
    for group, (joint, frames) in enumerate(members):
        result[frames, joint] = calibrated[group]
    return result


def reachable_root_track(
    count: int, fps: float, constraints: list[tuple[np.ndarray, np.ndarray, float]],
) -> np.ndarray:
    """Fit one smooth body translation inside all active chain reach balls.

    Entries contain frame indexes, target-minus-root offsets, and rigid reach.
    This changes neither body proportions nor contact anchors.
    """
    from scipy.linalg import cho_factor, cho_solve

    correction = np.zeros((count, 3))
    if not constraints:
        return correction
    indexes = np.concatenate([item[0] for item in constraints])
    offsets = np.concatenate([item[1] for item in constraints])
    radii = np.concatenate([np.full(len(item[0]), item[2]) for item in constraints])
    if np.all(np.linalg.norm(offsets, axis=1) <= radii):
        return correction
    second_difference = np.diff(np.eye(count), n=2, axis=0)
    system = np.eye(count) + (max(fps, 1.0) * 0.10)**4 * second_difference.T @ second_difference

    # Split smooth trajectory fitting from convex reach-ball projections.
    # The factorization is reused; no per-frame nonlinear optimization.
    penalty = 10.0
    factor = cho_factor(2 * system + penalty * np.diag(np.bincount(indexes, minlength=count)))
    projected = offsets.copy()
    dual = np.zeros_like(projected)
    constraint_counts = np.diag(np.bincount(indexes, minlength=count))
    for iteration in range(4000):
        rhs = np.zeros_like(correction)
        np.add.at(rhs, indexes, penalty * (projected - dual))
        correction = cho_solve(factor, rhs)
        previous = projected.copy()
        relative = correction[indexes] + dual - offsets
        projected = offsets + relative * np.minimum(
            1, radii / np.maximum(np.linalg.norm(relative, axis=1), 1e-10)
        )[:, None]
        residual = correction[indexes] - projected
        dual += residual
        if np.max(np.abs(residual)) < 1e-7 and np.max(np.abs(projected - previous)) < 1e-7:
            break
        # A fixed penalty can stall close to a contact boundary and exhaust
        # the budget on a feasible trajectory. Balance primal feasibility
        # against dual convergence; rescale the scaled dual when rho changes.
        if (iteration + 1) % 50 == 0:
            primal_norm = float(np.linalg.norm(residual))
            dual_norm = penalty * float(np.linalg.norm(projected - previous))
            new_penalty = penalty
            if primal_norm > 10 * dual_norm:
                new_penalty = min(penalty * 2, 1e6)
            elif dual_norm > 10 * primal_norm:
                new_penalty = max(penalty / 2, 1e-4)
            if new_penalty != penalty:
                dual *= penalty / new_penalty
                penalty = new_penalty
                factor = cho_factor(2 * system + penalty * constraint_counts)
    maximum_excess = float(np.max(np.linalg.norm(correction[indexes] - offsets, axis=1) - radii))
    if maximum_excess > 1e-6:
        raise InfeasibleContactCorrection(f"Support trajectory solver did not reach feasibility; reach excess {maximum_excess:.6g}")
    return correction
