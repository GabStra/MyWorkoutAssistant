"""Frame-grounded source observations; Python, rather than prose, owns approval."""
from __future__ import annotations

import hashlib
import json
import math
import copy
from pathlib import Path
from typing import Any


POLICY_VERSION = 15
ALL_UNIFORM_SAMPLES = 'all_uniform_samples'
MAX_TIMING_EVIDENCE_SAMPLE_GAP_SECONDS = 1.0
MAX_OBSERVED_OBJECT_COUNT = 2_147_483_647
SOURCE_REFERENCE_VISUAL_REVIEW_SPEC_POLICY_VERSION = 1
# Model-facing frame fields. Hash provenance stays in code-owned cache/evidence
# metadata; the decoder only needs stable identity, grouping, image and time.
EVIDENCE_PROMPT_FRAME_FIELDS = ('id', 'sampling', 'image', 'tileNumber', 'timestampSeconds')


def source_reference_review_context(
    mapping: Any,
    *,
    target_exercise_name: str,
    target_contract: dict[str, Any],
) -> dict[str, Any] | None:
    """Project a producer-validated external-load waiver for review and cache use.

    The projection is deliberately separate from ``target_contract``. It can
    identify an approved motion reference and waive only external-load
    visibility; it never edits the target definition or grants a positive
    review decision.
    """
    if mapping is None:
        return None
    if not isinstance(mapping, dict) or not isinstance(target_contract, dict):
        raise ValueError('source reference review context must be structured data')

    def required_text(key: str) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'source reference mapping is missing {key}')
        return value.strip()

    def require_sha256(key: str) -> str:
        value = required_text(key).casefold()
        if (len(value) != 64
                or any(character not in '0123456789abcdef' for character in value)):
            raise ValueError(f'source reference mapping has invalid {key}')
        return value

    source_id = required_text('sourceExerciseId')
    source_name = required_text('sourceExerciseName')
    target_id = required_text('exerciseId')
    target_name = required_text('exerciseName')
    contract_name = str(target_contract.get('exerciseName') or target_exercise_name).strip()
    if (not isinstance(target_exercise_name, str) or not target_exercise_name.strip()
            or target_name.casefold() != target_exercise_name.strip().casefold()
            or contract_name.casefold() != target_exercise_name.strip().casefold()):
        raise ValueError('source reference mapping does not target the current exercise contract')
    if source_id == target_id:
        raise ValueError('source reference mapping must name distinct source and target exercises')
    approval_difference_text = mapping.get('approvalAllowedDifference')
    if (mapping.get('motionReferenceOnly') is not True
            or mapping.get('allowedDifference') != 'external_load_not_shown'
            or not isinstance(approval_difference_text, str)
            or not approval_difference_text.strip()
            or mapping.get('approvalAuthority') != 'explicit_user_approval'
            or mapping.get('exportedExerciseUnchanged') is not True
            or mapping.get('approvalUserAnswerPresent') is not True):
        raise ValueError('source reference mapping does not contain the approved scoped waiver')
    mapping_sha = require_sha256('mappingSha256')
    approval_sha = require_sha256('approvalSha256')
    target_context = mapping.get('motionContext')
    if not isinstance(target_context, dict):
        raise ValueError('source reference mapping has no target motion context')
    source_context = mapping.get('sourceMotionContext')
    if not isinstance(source_context, dict):
        raise ValueError('source reference mapping has no authenticated source motion context')

    contract_bytes = json.dumps(
        target_contract, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False,
    ).encode('utf-8')
    context = {
        'schemaVersion': 1,
        'sourceExerciseId': source_id,
        'sourceExerciseName': source_name,
        'targetExerciseId': target_id,
        'targetExerciseName': target_name,
        'allowedDifference': 'external_load_not_shown',
        'approvalAllowedDifference': approval_difference_text.strip(),
        'approvalAuthority': 'explicit_user_approval',
        'approvalSha256': approval_sha,
        'mappingSha256': mapping_sha,
        'targetContractSha256': hashlib.sha256(contract_bytes).hexdigest(),
        'targetContractPolicyVersion': target_contract.get('contractPolicyVersion'),
        'targetRequiredPhases': copy.deepcopy(target_contract.get('requiredPhases') or []),
        'targetCompletionMode': target_contract.get('completionMode'),
        'sourceMotionContext': source_context,
    }
    for field in ('sourceMotionContextSha256', 'targetMotionContextSha256'):
        value = mapping.get(field)
        if field == 'sourceMotionContextSha256' and value is None:
            raise ValueError('source reference mapping is missing sourceMotionContextSha256')
        if value is not None:
            if (not isinstance(value, str) or len(value) != 64
                    or any(character not in '0123456789abcdefABCDEF' for character in value)):
                raise ValueError(f'source reference mapping has invalid {field}')
            context[field] = value.casefold()
    source_context_bytes = json.dumps(
        source_context, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False,
    ).encode('utf-8')
    if hashlib.sha256(source_context_bytes).hexdigest() != context['sourceMotionContextSha256']:
        raise ValueError('source reference mapping has mismatched sourceMotionContextSha256')
    return context


def source_reference_visual_review_contract(
    target_contract: dict[str, Any],
    source_reference_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the single model-facing visual contract for a mapped source.

    Source identity/action/variants define what visible motion is reviewed.
    Target phases, completion, biomechanics, and non-waived infrastructure stay
    authoritative. The returned projection is detached from the immutable target
    contract, which remains the authority for export and audit hashes.
    """
    if source_reference_context is None:
        return target_contract
    if not isinstance(target_contract, dict):
        raise ValueError('target contract must be structured data')
    if source_reference_review_context_sha256(source_reference_context) is None:
        raise ValueError('source-reference context is not normalized')
    target_name = str(target_contract.get('exerciseName') or '').strip()
    if (source_reference_context.get('schemaVersion') != 1
            or source_reference_context.get('allowedDifference') != 'external_load_not_shown'
            or source_reference_context.get('targetExerciseName', '').casefold() != target_name.casefold()
            or source_reference_context.get('targetContractSha256') != hashlib.sha256(
                json.dumps(target_contract, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()):
        raise ValueError('source-reference context is not bound to the current target contract')
    source_context = source_reference_context.get('sourceMotionContext')
    source_digest = source_reference_context.get('sourceMotionContextSha256')
    if not isinstance(source_context, dict) or not isinstance(source_digest, str):
        raise ValueError('source-reference context has no authenticated source definition')
    source_context_digest = hashlib.sha256(json.dumps(
        source_context, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False,
    ).encode('utf-8')).hexdigest()
    if source_context_digest != source_digest:
        raise ValueError('source motion context digest mismatch')
    source_definition = source_context.get('exerciseDefinition')
    if not isinstance(source_definition, dict):
        raise ValueError('source motion context has no authored exercise definition')
    action = source_definition.get('definingAction')
    qualifiers = source_definition.get('variantQualifiers', [])
    target_phases = target_contract.get('requiredPhases') or []
    target_mode = target_contract.get('completionMode')
    if (not isinstance(action, str) or not action.strip()
            or not isinstance(qualifiers, list)
            or any(not isinstance(value, str) or not value.strip() for value in qualifiers)
            or source_definition.get('requiredPhases') != target_phases
            or source_definition.get('completionMode') != target_mode):
        raise ValueError('source definition conflicts with target phases or completion')
    source_bilateral = source_definition.get('bilateralExecution')
    target_bilateral = target_contract.get('bilateralExecution')
    if target_bilateral is None:
        target_motion_context = target_contract.get('motionContext')
        target_definition = (target_motion_context.get('exerciseDefinition')
                            if isinstance(target_motion_context, dict) else None)
        target_bilateral = (target_definition.get('bilateralExecution')
                            if isinstance(target_definition, dict) else None)
    if target_bilateral is not None and source_bilateral != target_bilateral:
        raise ValueError('source definition conflicts with target bilateral execution')
    view = copy.deepcopy(target_contract)
    view['exerciseName'] = str(source_reference_context['sourceExerciseName']).strip()
    view['definingAction'] = action.strip()
    view['variantQualifiers'] = list(qualifiers)

    # A target advisory paragraph may restate the waived load as a visual
    # requirement. Do not serialize it into the source-visual prompt. The
    # authenticated source definition supplies visible action/variant wording;
    # the target's structured phases and constraints remain below.
    view.pop('advisoryText', None)
    view.pop('reviewNotes', None)
    motion_context = view.get('motionContext')
    if isinstance(motion_context, dict):
        motion_context = copy.deepcopy(motion_context)
        primary = motion_context.get('primaryEquipment')
        if (isinstance(primary, dict)
                and str(primary.get('type') or '').strip().upper() == 'WEIGHTVEST'):
            motion_context.pop('primaryEquipment', None)
        # Keep the target's structured, non-waived requirements while replacing
        # only identity/action/variant wording with authenticated source text.
        visual_definition = motion_context.get('exerciseDefinition')
        visual_definition = copy.deepcopy(visual_definition) if isinstance(visual_definition, dict) else {}
        visual_definition['definingAction'] = action.strip()
        visual_definition['variantQualifiers'] = list(qualifiers)
        motion_context['exerciseDefinition'] = visual_definition
        view['motionContext'] = motion_context
    return view


def source_reference_requirement_view(
    target_contract: dict[str, Any],
    source_reference_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compatibility name for the canonical source-visual contract projection."""
    return source_reference_visual_review_contract(target_contract, source_reference_context)


def source_reference_review_context_sha256(context: dict[str, Any] | None) -> str | None:
    """Return a stable cache identity for normalized source-reference context."""
    if context is None:
        return None
    canonical = json.dumps(context, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def source_reference_visual_review_spec_sha256(
    target_contract: dict[str, Any],
    source_reference_context: dict[str, Any] | None,
) -> str | None:
    """Bind mapped reviews to the exact sanitized visual contract and policy."""
    if source_reference_context is None:
        return None
    visual_contract = source_reference_visual_review_contract(
        target_contract, source_reference_context,
    )
    payload = {
        'policyVersion': SOURCE_REFERENCE_VISUAL_REVIEW_SPEC_POLICY_VERSION,
        'sourceReferenceReviewContextSha256': source_reference_review_context_sha256(
            source_reference_context,
        ),
        'targetContractSha256': source_reference_context.get('targetContractSha256'),
        'visualContract': visual_contract,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def source_reference_review_prompt_section(context: dict[str, Any] | None) -> str:
    """Describe a verified source mapping without changing target requirements."""
    if context is None:
        return ''
    if (not isinstance(context, dict) or context.get('schemaVersion') != 1
            or context.get('allowedDifference') != 'external_load_not_shown'
            or context.get('approvalAuthority') != 'explicit_user_approval'
            or context.get('sourceExerciseId') == context.get('targetExerciseId')):
        raise ValueError('source reference review context is not normalized')
    source_name = str(context.get('sourceExerciseName') or '').strip()
    target_name = str(context.get('targetExerciseName') or '').strip()
    source_definition = (context.get('sourceMotionContext') or {}).get('exerciseDefinition')
    if not isinstance(source_definition, dict):
        raise ValueError('source reference review context has no source action definition')
    source_action = source_definition.get('definingAction')
    source_variants = source_definition.get('variantQualifiers')
    target_phases = context.get('targetRequiredPhases')
    target_completion = context.get('targetCompletionMode')
    if (not source_name or not target_name
            or not isinstance(source_action, str) or not source_action.strip()
            or not isinstance(source_variants, list)
            or any(not isinstance(value, str) or not value.strip() for value in source_variants)
            or not isinstance(target_phases, list)
            or not target_phases
            or any(not isinstance(value, str) or not value.strip() for value in target_phases)
            or not isinstance(target_completion, str) or not target_completion.strip()
            or any(not isinstance(context.get(key), str) or len(context[key]) != 64
                   or any(character not in '0123456789abcdef' for character in context[key])
                   for key in ('approvalSha256', 'mappingSha256', 'targetContractSha256'))):
        raise ValueError('source reference review context has no source/target identity')
    return (
        '\n\nCode-verified approved motion-reference mapping (target export remains unchanged):\n'
        f'Primary visible-motion identity: {source_name} (source ID {context["sourceExerciseId"]}).\n'
        f'Unchanged export target: {target_name} (target ID {context["targetExerciseId"]}).\n'
        f'Source-authored visible action: {source_action.strip()}\n'
        f'Source-authored visible variants: {json.dumps(source_variants, ensure_ascii=False)}\n'
        f'Unchanged target completion mode: {target_completion}.\n'
        f'Unchanged target required phases in order: {json.dumps(target_phases, ensure_ascii=False)}\n'
        'Judge visible identity, defining action, and variant from the authenticated source definition. '
        'The explicit user approval waives only visibility of the target external load; absence of the weighted '
        'vest or other external load alone is not an identity mismatch or rejection. '
        'Continue to require the unchanged target phases, completion mode, support relationships, biomechanics, '
        'and all non-waived equipment and constraints. A different action, grip, support setup, or other '
        'non-waived variant remains a rejection. Do not claim the source footage shows an external load, '
        'and do not change the exported target exercise.\n'
    )


def evidence_prompt_inventory(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project the exact frame inventory without leaking code-only hash fields."""
    return [{field: frame[field] for field in EVIDENCE_PROMPT_FRAME_FIELDS if field in frame}
            for frame in frames]


def evidence_inventory(groups: dict[str, list[Path]]) -> list[dict[str, Any]]:
    inventory = []
    for group, sheets in groups.items():
        manifests = {}
        for sheet in sheets:
            if sheet.parent not in manifests:
                manifests[sheet.parent] = json.loads(
                    (sheet.parent / 'contact_sheet_evidence.json').read_text(encoding='utf-8'))
            record = manifests[sheet.parent]['sheets'][sheet.name]
            if record['sha256'] != hashlib.sha256(sheet.read_bytes()).hexdigest():
                raise ValueError('Contact sheet differs from its evidence manifest')
            for frame in record['frames']:
                timestamp = frame['timestampSeconds']
                if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
                    raise ValueError('Invalid source frame timestamp')
                inventory.append({
                    'id': f"{group}:{frame['number']}", 'sampling': group,
                    'image': sheets.index(sheet) + 1, 'tileNumber': frame['number'],
                    'timestampSeconds': timestamp, 'sheetSha256': record['sha256'],
                })
    if not inventory or len({f['id'] for f in inventory}) != len(inventory):
        raise ValueError('Missing or duplicate source frame IDs')
    return inventory


def temporal_observation_bins(
    observations: Any,
    expected_ids: list[str],
    frames: list[dict[str, Any]],
    *,
    id_field: str,
    source_time_offset_seconds: float = 0.0,
    require_visible: bool = False,
    ordered: bool = True,
) -> dict[str, Any]:
    """Resolve cited samples to exact source times without inventing phase boundaries."""
    available = {str(frame.get('id')): frame for frame in frames if isinstance(frame, dict)}
    rows = observations if isinstance(observations, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if not isinstance(source_time_offset_seconds, (int, float)) or not math.isfinite(source_time_offset_seconds):
        source_time_offset_seconds = 0.0
        errors.append('invalid_source_time_offset')
    for row in rows:
        if not isinstance(row, dict):
            errors.append('invalid_observation')
            continue
        observation_id = str(row.get(id_field) or '').strip()
        if not observation_id or observation_id not in expected_ids or observation_id in by_id:
            errors.append('unknown_or_duplicate_observation')
            continue
        if require_visible and row.get('visible') is not True:
            errors.append(f'not_visible:{observation_id}')
            by_id[observation_id] = {'evidenceFrameIds': [], 'sampleBins': []}
            continue
        frame_ids = row.get('evidenceFrameIds')
        if (not isinstance(frame_ids, list) or not frame_ids
                or any(not isinstance(frame_id, str) or frame_id not in available for frame_id in frame_ids)
                or len(set(frame_ids)) != len(frame_ids)):
            errors.append(f'missing_or_invalid_frame_ids:{observation_id}')
            by_id[observation_id] = {'evidenceFrameIds': [], 'sampleBins': []}
            continue
        referenced = []
        for frame_id in frame_ids:
            frame = available[frame_id]
            timestamp = frame.get('timestampSeconds')
            if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
                errors.append(f'invalid_frame_timestamp:{observation_id}')
                continue
            referenced.append({
                'frameId': frame_id,
                'timestampSeconds': float(timestamp),
                'sourceTimestampSeconds': float(timestamp) + float(source_time_offset_seconds),
                'sheetSha256': frame.get('sheetSha256'),
                'tileNumber': frame.get('tileNumber'),
            })
        referenced.sort(key=lambda item: item['timestampSeconds'])
        bins = []
        for item in referenced:
            timestamp = item['timestampSeconds']
            # The exact sample is represented by the midpoint to its adjacent
            # verified samples. This is only a sampling-uncertainty bin, not a
            # phase's start/end interval.
            bins.append({
                **item,
                'sourceBinStartSeconds': float(timestamp),
                'sourceBinEndSeconds': float(timestamp),
            })
        by_id[observation_id] = {'evidenceFrameIds': list(frame_ids), 'sampleBins': bins}

    missing = [item for item in expected_ids if item not in by_id]
    if missing:
        errors.extend(f'missing_observation:{item}' for item in missing)
    ordered_rows = [by_id[item] for item in expected_ids if item in by_id]
    observed_times = [
        item['timestampSeconds']
        for row in ordered_rows
        for item in row['sampleBins']
    ]
    phase_times = [
        sorted({item['timestampSeconds'] for item in row['sampleBins']})
        for row in ordered_rows
    ]
    # A transition frame may legitimately support both neighboring actions.
    # Still require every action to have at least one distinct time sample and
    # require the centers of those samples to follow the approved order.
    unique_phase_times = [
        [timestamp for timestamp in times if sum(timestamp in other for other in phase_times) == 1]
        for times in phase_times
    ]
    centers = [
        sum(times) / len(times) if times else None
        for times in phase_times
    ]
    phase_ordered = (
        all(unique_phase_times)
        and all(
            isinstance(left, (int, float)) and isinstance(right, (int, float)) and left < right
            for left, right in zip(centers, centers[1:])
        )
    ) if ordered and len(ordered_rows) > 1 else True
    if not phase_ordered and len(ordered_rows) > 1:
        errors.append('observation_order_not_established')
    timeline = sorted({
        float(frame['timestampSeconds'])
        for frame in frames
        if isinstance(frame, dict)
        and isinstance(frame.get('timestampSeconds'), (int, float))
        and math.isfinite(frame['timestampSeconds'])
    })
    sample_gaps = [right - left for left, right in zip(timeline, timeline[1:])]
    if sample_gaps and max(sample_gaps) > MAX_TIMING_EVIDENCE_SAMPLE_GAP_SECONDS:
        errors.append('sample_gap_too_large_for_timing')
    # Widen exact cited samples to their conservative midpoint cells. Wide
    # gaps remain unresolved above rather than creating a falsely precise bin.
    for row in by_id.values():
        for sample in row['sampleBins']:
            timestamp = sample['timestampSeconds']
            index = timeline.index(timestamp) if timestamp in timeline else None
            if index is None:
                continue
            left = (timeline[index - 1] + timestamp) / 2.0 if index else timestamp
            right = (timestamp + timeline[index + 1]) / 2.0 if index + 1 < len(timeline) else timestamp
            sample['sourceBinStartSeconds'] = left + float(source_time_offset_seconds)
            sample['sourceBinEndSeconds'] = right + float(source_time_offset_seconds)
            sample['sampleGapSeconds'] = max(timestamp - left, right - timestamp) * 2.0
    resolved = not errors and len(by_id) == len(expected_ids)
    return {
        'status': 'sampled' if resolved else 'unresolved',
        'continuousCoverage': 'unresolved',
        'reason': None if resolved else (errors[0] if errors else 'incomplete_observations'),
        'expectedIds': list(expected_ids),
        'sampleBinsById': {item: by_id[item] for item in expected_ids if item in by_id},
        'sampleFrameCount': len(timeline),
        'sourceTimeOffsetSeconds': float(source_time_offset_seconds),
        'maximumAdjacentSampleGapSeconds': max(sample_gaps) if sample_gaps else None,
        'maximumObservedPhaseGapSeconds': (
            max(
                (right - left for left, right in zip(observed_times, observed_times[1:])),
                default=None,
            ) if ordered else None
        ),
        'maximumAllowedAdjacentSampleGapSeconds': MAX_TIMING_EVIDENCE_SAMPLE_GAP_SECONDS,
        'errors': errors,
    }


def temporal_evidence_covers_candidate(
    timing: dict[str, Any] | None,
    *,
    start_seconds: float,
    end_seconds: float,
) -> dict[str, Any]:
    """Require every cited sample bin to fit wholly inside a proposed child cut."""
    if not isinstance(timing, dict) or timing.get('status') != 'sampled':
        return {'eligible': False, 'reason': 'timing_evidence_unresolved', 'missingIds': []}
    if (not math.isfinite(start_seconds) or not math.isfinite(end_seconds)
            or end_seconds <= start_seconds):
        return {'eligible': False, 'reason': 'invalid_candidate_interval', 'missingIds': []}
    expected = timing.get('expectedIds')
    bins_by_id = timing.get('sampleBinsById')
    if not isinstance(expected, list) or not expected or not isinstance(bins_by_id, dict):
        return {'eligible': False, 'reason': 'timing_evidence_unresolved', 'missingIds': []}
    missing = []
    for observation_id in expected:
        row = bins_by_id.get(observation_id)
        bins = row.get('sampleBins') if isinstance(row, dict) else None
        if not isinstance(bins, list) or not bins or any(
            not isinstance(item, dict)
            or not isinstance(item.get('sourceBinStartSeconds'), (int, float))
            or not isinstance(item.get('sourceBinEndSeconds'), (int, float))
            or not math.isfinite(item['sourceBinStartSeconds'])
            or not math.isfinite(item['sourceBinEndSeconds'])
            or item['sourceBinStartSeconds'] < start_seconds
            or item['sourceBinEndSeconds'] > end_seconds
            for item in bins
        ):
            missing.append(str(observation_id))
    return {
        'eligible': not missing,
        'reason': None if not missing else 'candidate_does_not_cover_evidence_bins',
        'missingIds': missing,
    }


def source_requirements(
    contract: dict[str, Any],
    equipment: list[dict[str, Any]],
    *,
    source_reference_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Only the reviewed action supplies semantic requirements. Generated posture
    # expectations and exercise-name guesses never acquire authority here.
    if source_reference_context is not None:
        source_reference_review_context_sha256(source_reference_context)
        equipment = source_reference_observation_equipment(contract, equipment, source_reference_context)
        contract = source_reference_requirement_view(contract, source_reference_context)
    action = str(contract.get('definingAction') or '').strip()
    if not action:
        raise ValueError('Source review needs a defined action')
    requirements = [{'id': 'action', 'description': action, 'minimumDistinctFrameCount': 2}]
    phases = contract.get('requiredPhases') or []
    context = contract.get('motionContext') or {}
    definition = context.get('exerciseDefinition') or {}
    if ((contract.get('completionMode') in {'stable_hold', 'active_travel'} or len(phases) >= 3)
            and definition.get('definingAction')
            and contract.get('requiredPhasesAuthority') not in {'structured_definition', 'trusted'}):
        # Inferred sequence/entry checklists cannot add obligations to a reviewed action.
        phases = definition.get('requiredPhases') or []
    for index, phase in enumerate(phases):
        if isinstance(phase, str) and phase.strip().rstrip('.') != action.rstrip('.'):
            requirements.append({'id': f'phase_{index + 1}', 'description': phase.strip()})
    for index, qualifier in enumerate(contract.get('variantQualifiers') or []):
        requirements.append({'id': f'variant_{index + 1}', 'description': str(qualifier)})
    for index, role in enumerate(equipment):
        requirements.append({'id': f'equipment_{index + 1}', 'description': json.dumps(role, sort_keys=True),
                             'minimumObjectCount': int(role.get('minimumObjectCount', 1))})
    mode = contract.get('completionMode')
    completion = {
        'return_to_start': 'A complete execution including meaningful start, action excursion and return to the starting state is visible.',
        'distinct_end_state': 'A complete execution including meaningful start and the finish of the defining action is visible. A return is not required.',
        'alternating_pair': 'Both sides of the prescribed alternating action are visible as one complete pair.',
        'stable_hold': 'The prescribed active hold and support are visibly sustained across time; entry and release are not required.',
        'active_travel': 'The prescribed travel action is visibly sustained across time; entry and stopping are not required.',
        'representative_cycle': 'A representative complete cycle of the prescribed ongoing action is visible.',
    }.get(mode)
    if completion is None:
        raise ValueError('Unknown completion mode')
    requirements.extend([
        {'id': 'completion', 'description': completion,
         'minimumDistinctFrameCount': 3 if mode == 'return_to_start' else 2},
        {'id': 'clean_interval', 'description': 'Uniformly sampled frames show exercise content or normal between-repetition transitions, without instruction gestures, unrelated exercise, setup or cleanup. A prescribed active hold is exercise content.'},
    ])
    return requirements


def source_reference_observation_equipment(
    target_contract: dict[str, Any],
    equipment: list[dict[str, Any]],
    source_reference_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Omit only a typed weighted vest from source visibility requirements.

    The production target contract remains unchanged. A setup fixture, bar,
    dumbbell, or other equipment role remains required.
    """
    if (source_reference_context.get('schemaVersion') != 1
            or source_reference_context.get('allowedDifference') != 'external_load_not_shown'):
        raise ValueError('source-reference equipment projection lacks its scoped approval')
    context = target_contract.get('motionContext')
    primary = context.get('primaryEquipment') if isinstance(context, dict) else None
    if not isinstance(primary, dict) or str(primary.get('type') or '').strip().upper() != 'WEIGHTVEST':
        return equipment
    primary_name = str(primary.get('name') or '').strip()
    if not primary_name:
        raise ValueError('weighted-vest primary equipment has no authenticated identity')
    matching_indices = [
        index for index, role in enumerate(equipment)
        if isinstance(role, dict)
        and role.get('role') == 'active_implement'
        and str(role.get('name') or '').strip().casefold() == primary_name.casefold()
    ]
    if len(matching_indices) != 1:
        raise ValueError('weighted-vest source requirement does not match target primary equipment')
    waived_index = matching_indices[0]
    return [role for index, role in enumerate(equipment) if index != waived_index]


def permits_cyclic_phase_order(contract: dict[str, Any] | None) -> bool:
    """A return-to-start cycle may be cut at any point unless its start is prescribed."""
    if not isinstance(contract, dict) or contract.get('completionMode') != 'return_to_start':
        return False
    if str(contract.get('movementType') or '').strip().casefold() not in {'repetition', 'cyclic'}:
        return False
    # Pose constraints and start/end labels can be generated advisory fields.
    # Only explicit library/user/manual provenance can anchor the cut boundary.
    explicit_authority = (
        str(contract.get('authority') or '').casefold() == 'explicit'
        or str(contract.get('source') or '').casefold()
        in {'exercise_definition', 'user', 'manual', 'library'}
    )
    if not explicit_authority:
        return True
    if contract.get('startPoseConstraints'):
        return False
    if any(str(contract.get(key) or '').strip()
           for key in ('validStartState', 'requiredStartPosture', 'startState')):
        return False
    topology = contract.get('movementTopology')
    topology_start = topology.get('startState') if isinstance(topology, dict) else None
    if isinstance(topology_start, dict):
        label = str(topology_start.get('label') or '').strip().casefold()
        if label and label != 'unspecified':
            return False
    return True


def return_cycle_evidence_choices(phase_metrics: dict[str, Any] | None,
                                  pose_reference: dict[str, Any] | None,
                                  frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Bind a simple two-phase return cycle to verified pose extrema and source-frame IDs."""
    if not isinstance(phase_metrics, dict) or not isinstance(pose_reference, dict):
        return None
    if (phase_metrics.get('required') is not True or phase_metrics.get('passed') is not True
            or phase_metrics.get('hasCompleteMajorCycle') is not True
            or not isinstance(phase_metrics.get('phaseSignalEvidence'), dict)
            or phase_metrics['phaseSignalEvidence'].get('resolved') is not True):
        return None
    sequence = phase_metrics.get('majorPhaseSequence')
    single_cycle = phase_metrics.get('hasSingleMajorCycle') is True
    if single_cycle and sequence not in (['low', 'high', 'low'], ['high', 'low', 'high']):
        return None
    pose_frames = pose_reference.get('frames')
    if not isinstance(pose_frames, list) or len(pose_frames) < 3:
        return None
    sample_indices = phase_metrics.get('sampleFrameIndices')
    if sample_indices is not None:
        if (not isinstance(sample_indices, list)
                or any(type(index) is not int or not 0 <= index < len(pose_frames)
                       for index in sample_indices)
                or any(right <= left for left, right in zip(sample_indices, sample_indices[1:]))):
            return None
        pose_frames = [pose_frames[index] for index in sample_indices]
    if len(pose_frames) < 3 or phase_metrics.get('sampleCount') != len(pose_frames):
        return None
    timestamps = [frame.get('sourceTimeSec') if isinstance(frame, dict) else None
                  for frame in pose_frames]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in timestamps):
        return None
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        return None
    if single_cycle:
        extremum_key = 'maxFrameIndex' if sequence == ['low', 'high', 'low'] else 'minFrameIndex'
        extremum_index = phase_metrics.get(extremum_key)
        edge_margin = phase_metrics.get('edgeMarginFrameCount')
        if (type(extremum_index) is not int or type(edge_margin) is not int
                or extremum_index < edge_margin or extremum_index > len(pose_frames) - 1 - edge_margin):
            return None
        role_indices = (0, extremum_index, len(pose_frames) - 1)
    else:
        runs = phase_metrics.get('majorPhaseRuns')
        if not isinstance(runs, list) or len(runs) < 3:
            return None
        previous_end = -1
        for run in runs:
            if not isinstance(run, dict) or run.get('phase') not in {'low', 'high'}:
                return None
            bounds = [run.get(key) for key in ('startFrameIndex', 'extremumFrameIndex', 'endFrameIndex')]
            if (any(type(index) is not int for index in bounds)
                    or not previous_end < bounds[0] <= bounds[1] <= bounds[2] < len(pose_frames)):
                return None
            previous_end = bounds[2]
        if [run['phase'] for run in runs] != sequence:
            return None
        triple = next((runs[index:index + 3] for index in range(len(runs) - 2)
                       if [run['phase'] for run in runs[index:index + 3]]
                       in (['low', 'high', 'low'], ['high', 'low', 'high'])), None)
        if triple is None:
            return None
        role_indices = (triple[0]['startFrameIndex'], triple[1]['extremumFrameIndex'],
                        triple[2]['endFrameIndex'])
        if not role_indices[0] < role_indices[1] < role_indices[2]:
            return None
        sequence = [run['phase'] for run in triple]
    if not frames:
        return None
    available_frames = [frame for frame in frames if isinstance(frame, dict)
                        and isinstance(frame.get('timestampSeconds'), (int, float))
                        and math.isfinite(frame['timestampSeconds'])]
    if not available_frames:
        return None

    boundary_tolerance = pose_reference.get('sourcePoseSampleBoundaryToleranceSeconds')
    if not isinstance(boundary_tolerance, (int, float)) or not math.isfinite(boundary_tolerance):
        gaps = [right - left for left, right in zip(timestamps, timestamps[1:])]
        if not gaps:
            return None
        boundary_tolerance = min(gaps) / 2.0

    additional_frames = []
    def nearest_frame(pose_time: float, role: str) -> dict[str, Any]:
        frame = min(available_frames, key=lambda frame: (
            abs(float(frame['timestampSeconds']) - pose_time),
            0 if frame.get('sampling') == 'motion' else 1,
            str(frame.get('id') or ''),
        ))
        if abs(float(frame['timestampSeconds']) - pose_time) > float(boundary_tolerance):
            # The role renderer extracts this exact measured exposure separately.
            frame = {'id': f'cycle:{role}', 'sampling': 'cycle', 'timestampSeconds': pose_time}
            additional_frames.append(frame)
        return frame

    role_names = ('start', 'excursion', 'return')
    role_frames = {name: nearest_frame(float(timestamps[index]), name)
                   for name, index in zip(role_names, role_indices)}
    if any(frame is None for frame in role_frames.values()):
        return None
    role_ids = [str(role_frames[name].get('id') or '') for name in role_names]
    role_times = [float(role_frames[name]['timestampSeconds']) for name in role_names]
    if (any(not frame_id for frame_id in role_ids) or len(set(role_ids)) != 3
            or not role_times[0] < role_times[1] < role_times[2]):
        return None
    return {
        'choiceId': 'verified_return_cycle',
        'additionalFrames': additional_frames,
        'sequence': list(sequence),
        'roleFrameIds': dict(zip(role_names, role_ids)),
        'roleTimes': dict(zip(role_names, role_times)),
        'spanChoices': [
            {'spanChoiceId': 'cycle_span_1', 'frameIds': [role_ids[0], role_ids[1]]},
            {'spanChoiceId': 'cycle_span_2', 'frameIds': [role_ids[1], role_ids[2]]},
        ],
    }


def evidence_frame_id_limit(requirement: dict[str, Any], requirements: list[dict[str, Any]],
                            frames: list[dict[str, Any]]) -> int:
    """Bound citations to the observations needed to establish this requirement."""
    frame_count = len(frames)
    rid = str(requirement.get('id') or '')
    if rid == 'clean_interval':
        return sum(frame.get('sampling') == 'uniform' for frame in frames)
    if rid in {'action', 'completion'}:
        minimum_distinct = max(2, int(requirement.get('minimumDistinctFrameCount', 2)))
        phase_count = sum(
            str(row.get('id') or '').startswith('phase_')
            for row in requirements
        )
        # Each explicit phase adds one citation slot beyond the minimum needed
        # to establish the sequence required by the reviewed completion mode.
        return min(frame_count, minimum_distinct + phase_count)
    if rid.startswith('phase_'):
        # A pair can establish a phase span while keeping citations local.
        return min(frame_count, 2)
    # A single sample can show a variant or overlapping equipment roles. The
    # separate observedObjectCount field verifies object quantity.
    return min(frame_count, 1)


def evidence_response_token_budget(requirements: list[dict[str, Any]],
                                   frames: list[dict[str, Any]], *, semantic_labels: bool = False) -> int:
    """Size the response allowance from the largest schema-valid compact reply."""
    if not requirements or not frames:
        return 256
    observations = []
    for requirement in requirements:
        limit = evidence_frame_id_limit(requirement, requirements, frames)
        eligible_frames = frames
        if requirement.get('id') == 'clean_interval':
            eligible_frames = [frame for frame in frames if frame.get('sampling') == 'uniform']
        longest_ids = sorted((str(frame['id']) for frame in eligible_frames), key=len, reverse=True)
        row = {
            **({'requirement': requirement['description']} if semantic_labels else
               {'requirementId': requirement['id']}),
            'verdict': 'supported',
            'evidenceFrameIds': longest_ids[:limit],
        }
        if 'minimumObjectCount' in requirement:
            row['observedObjectCount'] = MAX_OBSERVED_OBJECT_COUNT
        observations.append(row)
    maximum_json = json.dumps({'observations': observations}, separators=(',', ':'))
    # The UTF-8 byte length is a conservative token upper bound for this ASCII
    # response shape. Leave 512 tokens for JSON formatting and wrapper tokens.
    return max(256, len(maximum_json.encode('utf-8')) + 512)


def evidence_schema(requirements: list[dict[str, Any]], frames: list[dict[str, Any]], *,
                    cycle_choices: dict[str, Any] | None = None,
                    semantic_labels: bool = False) -> dict[str, Any]:
    observation_schemas = []
    for requirement in requirements:
        eligible_frames = frames
        if requirement.get('id') == 'clean_interval':
            eligible_frames = [frame for frame in frames if frame.get('sampling') == 'uniform']
        elif requirement.get('id') == 'completion' and isinstance(cycle_choices, dict):
            role_ids = set((cycle_choices.get('roleFrameIds') or {}).values())
            eligible_frames = [frame for frame in frames if frame.get('id') in role_ids]
        properties = {
            'requirementId': {'type': 'string', 'enum': [requirement['id']]},
            'verdict': {'type': 'string', 'enum': ['supported', 'contradicted', 'unresolved']},
            'evidenceFrameIds': {
                'type': 'array', 'uniqueItems': True,
                'maxItems': evidence_frame_id_limit(requirement, requirements, frames),
                'items': {'type': 'string', 'enum': [frame['id'] for frame in eligible_frames]},
            },
        }
        if 'minimumObjectCount' in requirement:
            properties['observedObjectCount'] = {
                'type': 'integer', 'minimum': 0, 'maximum': MAX_OBSERVED_OBJECT_COUNT,
            }
        identity_field = 'requirement' if semantic_labels else 'requirementId'
        if semantic_labels:
            properties.pop('requirementId')
            properties['requirement'] = {'type': 'string', 'enum': [requirement['description']]}
            if requirement['id'] == 'clean_interval':
                properties['evidenceFrameIds']['items']['enum'].append(ALL_UNIFORM_SAMPLES)
        observation_schemas.append({
            'type': 'object', 'additionalProperties': False,
            'required': [identity_field, 'verdict', 'evidenceFrameIds'],
            'properties': properties,
        })
    if semantic_labels:
        # The same visible fact can satisfy a phase and a variant without
        # asking twice; retain the strictest evidence bounds of both owners.
        by_label = {}
        for row in observation_schemas:
            label = row['properties']['requirement']['enum'][0]
            if label not in by_label:
                by_label[label] = row
                continue
            existing = by_label[label]['properties']
            evidence = existing['evidenceFrameIds']
            other = row['properties']['evidenceFrameIds']
            evidence['maxItems'] = min(evidence['maxItems'], other['maxItems'])
            evidence['items']['enum'] = [value for value in evidence['items']['enum']
                                         if value in other['items']['enum']]
            if 'observedObjectCount' in row['properties']:
                existing['observedObjectCount'] = row['properties']['observedObjectCount']
        observation_schemas = list(by_label.values())
    return {'type': 'object', 'additionalProperties': False, 'required': ['observations'], 'properties': {
        'observations': {'type': 'array', 'minItems': len(observation_schemas), 'maxItems': len(observation_schemas), 'items': {
            'oneOf': observation_schemas,
        }},
    }}


def evidence_prompt(requirements: list[dict[str, Any]], frames: list[dict[str, Any]], *,
                    allow_cyclic_phase_order: bool = False,
                    cycle_choices: dict[str, Any] | None = None,
                    semantic_labels: bool = False,
                    legacy_wire: bool = False,
                    source_reference_context: dict[str, Any] | None = None) -> str:
    identity_instruction = ('For each supplied requirement description select supported, contradicted or unresolved. '
                            'Requirement descriptions identify semantic claims, not their chronological positions. '
                            if semantic_labels else
                            'For each exact requirementId return supported, contradicted or unresolved. ')
    display_requirements = ([{**{key: value for key, value in row.items() if key != 'id'},
                             'kind': next((kind for kind in ('phase', 'variant', 'equipment')
                                           if row['id'].startswith(kind + '_')), row['id'])}
                             for row in requirements]
                            if semantic_labels else requirements)
    if semantic_labels:
        unique = {}
        for row in display_requirements:
            label = row['description']
            if label not in unique:
                unique[label] = row
            else:
                for bound in ('minimumDistinctFrameCount', 'minimumObjectCount'):
                    if bound in row:
                        unique[label][bound] = max(row[bound], unique[label].get(bound, 0))
        display_requirements = list(unique.values())
    instruction = (
        'Inspect the supplied source images directly. Return structured source evidence, never an exercise name '
        'or another reviewer\'s description. Requirements below are exhaustive; do not invent start height, '
        'stance, catch or other variant requirements. Equipment roles specify required use and object count. '
        'A support surface requires actual body contact; background equipment does not establish use. '
        + identity_instruction + 'Cite only the minimum exact '
        'evidenceFrameIds needed to establish it. Reuse the same frame ID for overlapping roles instead of '
        'listing redundant examples. '
        'For equipment requirements also return observedObjectCount as an integer count of the required '
        'physical objects visibly engaged at the cited instants, not objects in the background. This is point '
        'evidence and does not claim uninterrupted use between cited frames; any required action phases are '
        'checked independently. Include observedObjectCount only on equipment rows. Missing or uncertain count '
        'cannot support a quantity requirement. '
        'Supported and contradicted both require visible evidence. Unseen action is unresolved, not contradicted. '
        'Action and completion require at least the minimumDistinctFrameCount shown in that requirement, at '
        'distinct chronological source times, not one pose. A return_to_start completion needs evidence of '
        'meaningful start, action excursion and return; do not invent exact event timestamps. Cite no more than '
        'that minimum plus one sample for each separately required phase. The supplied action phases '
        'are ordered: cite no more than two samples for each phase from the same execution, '
        'not a mixture of different repetitions. '
        + ('For this return-to-start cycle, the selected interval may begin mid-cycle: accept exactly one cyclic '
           'rotation of the listed phase order when every phase has a distinct, non-overlapping chronological '
           'span within the same complete cycle. Interpret the defining action cyclically too: its first '
           'verb does not prescribe the first frame. All required actions and the return must still be '
           'visible. Explicit start/end requirements and variant qualifiers remain mandatory; rotation '
           'does not waive them. Do not accept arbitrary reordering. '
           if allow_cyclic_phase_order else '')
        + ('For completion, a separate verified source-pose cycle is available. Cite every supplied '
           'role-bound frame ID for start, interior excursion and return; if the images do not confirm '
           'that complete cycle, mark completion unresolved. For phase requirements, one bounded correction '
           'may assign each phase only to one of the code-provided cycle spans. '
           if isinstance(cycle_choices, dict) else '')
        + (('For the clean-interval requirement, select evidenceFrameIds ["all_uniform_samples"] only '
            'when every supplied uniform sample was inspected and supports the verdict. Code expands '
            'that choice to the exact sampled frame IDs. A contradiction must cite the specific offending '
            'uniform frame IDs; uncertain visibility remains unresolved. '
            if semantic_labels else 'Clean interval evidence must cover all supplied uniform frames. '
            'For clean_interval, cite every uniform frame ID and no motion frame IDs. ')
           if any(row['id'] == 'clean_interval' for row in requirements) else '')
        + 'Images are supplied in uniform order followed by motion order; image numbers in the inventory are local '
        'to each sampling group. tileNumber is the number printed in the image. '
        'Never invent timestamps or frame IDs. Return only JSON matching the supplied schema.\n'
    )
    if legacy_wire:
        # Exact pre-projection serialization, used only to read prior review
        # caches under their original prompt key. Never sent to the model.
        return (instruction + 'Requirements: ' + json.dumps(display_requirements)
                + '\nFrame inventory: ' + json.dumps(frames)
                + '\nSchema: ' + json.dumps(evidence_schema(
                    requirements, frames, cycle_choices=cycle_choices, semantic_labels=semantic_labels)))
    identity_field = 'requirement' if semantic_labels else 'requirementId'
    identity_kind = 'description' if semantic_labels else 'requirement ID'
    object_count_shape = (', "observedObjectCount": <integer>' if any(
        'minimumObjectCount' in row for row in requirements) else '')
    response_shape = (
        '{"observations": [{"' + identity_field + '": <exact supplied ' + identity_kind
        + '>, "verdict": "supported" | "contradicted" | "unresolved", '
        + '"evidenceFrameIds": [<exact supplied frame IDs>]' + object_count_shape + '}]}')
    prompt = (
        instruction + 'Response shape: ' + response_shape
        + '. The structured response schema supplied to the decoder is authoritative; follow it exactly.\n'
        'Requirements: ' + json.dumps(display_requirements)
        + '\nFrame inventory: ' + json.dumps(evidence_prompt_inventory(frames), separators=(',', ':'))
    )
    if source_reference_context is not None and not legacy_wire:
        prompt += source_reference_review_prompt_section(source_reference_context)
    return prompt


def resolve_semantic_evidence(payload: Any, requirements: list[dict[str, Any]],
                              frames: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Keep logical requirement identities inside code for every completion mode."""
    by_label = {}
    for row in requirements:
        by_label.setdefault(row['description'], []).append(row['id'])
    if any(sum(rid.startswith('phase_') for rid in ids) > 1 for ids in by_label.values()):
        # Repeated occurrences of the same action need separate temporal context.
        return {'observations': []}
    if not isinstance(payload, dict) or set(payload) != {'observations'}:
        return {'observations': []}
    observations = payload['observations']
    if not isinstance(observations, list):
        return {'observations': []}
    normalized = []
    for row in observations:
        if (not isinstance(row, dict) or set(row) - {'requirement', 'verdict', 'evidenceFrameIds', 'observedObjectCount'}
                or not {'requirement', 'verdict', 'evidenceFrameIds'}.issubset(row)
                or not isinstance(row['requirement'], str) or row['requirement'] not in by_label):
            return {'observations': []}
        if isinstance(row['evidenceFrameIds'], list) and ALL_UNIFORM_SAMPLES in row['evidenceFrameIds']:
            if (by_label[row['requirement']] != ['clean_interval'] or row['verdict'] != 'supported'
                    or row['evidenceFrameIds'] != [ALL_UNIFORM_SAMPLES] or not frames):
                return {'observations': []}
            row = {**row, 'evidenceFrameIds': [frame['id'] for frame in frames
                                             if frame.get('sampling') == 'uniform']}
        normalized.extend({**{key: value for key, value in row.items() if key != 'requirement'},
                           'requirementId': rid} for rid in by_label[row['requirement']])
    return {'observations': normalized}


def aggregate_evidence(payload: Any, requirements: list[dict[str, Any]],
                       frames: list[dict[str, Any]], *,
                       allow_cyclic_phase_order: bool = False,
                       cycle_choices: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = {r['id'] for r in requirements}
    available = {f['id']: f for f in frames}
    observations = payload.get('observations') if isinstance(payload, dict) else None
    errors = []
    correction_ids = set()
    resolved = {}
    if not isinstance(payload, dict) or set(payload) != {'observations'} or not isinstance(observations, list):
        errors.append('invalid_observation_schema')
        observations = []
    for observation in observations:
        required_fields = {'requirementId', 'verdict', 'evidenceFrameIds'}
        if (not isinstance(observation, dict) or not required_fields.issubset(observation)
                or set(observation) - required_fields - {'observedObjectCount'}):
            errors.append('invalid_observation_schema')
            continue
        rid, verdict, ids = (observation[k] for k in ('requirementId', 'verdict', 'evidenceFrameIds'))
        if not isinstance(rid, str) or rid not in expected or rid in resolved:
            errors.append('unknown_or_duplicate_requirement')
            continue
        if (not isinstance(verdict, str) or verdict not in {'supported', 'contradicted', 'unresolved'}
                or not isinstance(ids, list) or any(not isinstance(i, str) or i not in available for i in ids)
                or len(set(ids)) != len(ids)):
            errors.append('invalid_verdict_or_frame_reference')
            correction_ids.add(rid)
            continue
        if verdict != 'unresolved' and not ids:
            errors.append('missing_frame_evidence')
            continue
        requirement = next(r for r in requirements if r['id'] == rid)
        minimum_count = requirement.get('minimumObjectCount')
        count = observation.get('observedObjectCount')
        if minimum_count is None and 'observedObjectCount' in observation:
            # Older/loose schema decoders sometimes emit this optional field on
            # every row. It has no meaning outside equipment and never affects
            # a verdict there, so discard it rather than treating it as count
            # evidence or invalidating otherwise complete observations.
            observation = {key: value for key, value in observation.items()
                           if key != 'observedObjectCount'}
        if (minimum_count is not None and 'observedObjectCount' in observation
                and (type(count) is not int or count < 0 or count > MAX_OBSERVED_OBJECT_COUNT)
                or minimum_count is not None and verdict == 'supported'
                and (type(count) is not int or count < minimum_count)):
            errors.append('equipment_quantity_unverified')
            continue
        if rid in {'action', 'completion'} and verdict == 'supported':
            minimum_distinct = max(2, int(requirement.get('minimumDistinctFrameCount', 2)))
            if len({available[i]['timestampSeconds'] for i in ids}) < minimum_distinct:
                errors.append('sequence_evidence_missing')
                if rid == 'completion':
                    correction_ids.add(rid)
                continue
        if rid == 'completion' and verdict == 'supported' and isinstance(cycle_choices, dict):
            role_ids = set((cycle_choices.get('roleFrameIds') or {}).values())
            if not role_ids.issubset(ids):
                errors.append('cycle_role_evidence_missing')
                correction_ids.add(rid)
                continue
        if rid == 'clean_interval' and verdict == 'supported':
            uniform_ids = {f['id'] for f in frames if f['sampling'] == 'uniform'}
            if not uniform_ids.issubset(ids):
                errors.append('uniform_coverage_missing')
                correction_ids.add(rid)
                continue
        if rid == 'clean_interval' and any(available[i].get('sampling') != 'uniform' for i in ids):
            errors.append('clean_interval_motion_frame_not_allowed')
            continue
        if len(ids) > evidence_frame_id_limit(requirement, requirements, frames):
            errors.append('too_many_frame_references')
            continue
        resolved[rid] = observation
    failed_phase_ids = set()
    phase_spans = []
    for requirement in requirements:
        rid = requirement['id']
        observation = resolved.get(rid)
        if not rid.startswith('phase_') or not observation or observation['verdict'] != 'supported':
            continue
        times = [available[i]['timestampSeconds'] for i in observation['evidenceFrameIds']]
        span = min(times), max(times)
        phase_spans.append((rid, int(rid.removeprefix('phase_')), span))
    if len(phase_spans) == sum(r['id'].startswith('phase_') for r in requirements) and len(phase_spans) > 1:
        chronological = sorted(phase_spans, key=lambda entry: (entry[2][0], entry[2][1]))
        no_overlap = all(left[2][1] <= right[2][0]
                         for left, right in zip(chronological, chronological[1:]))
        indices = [entry[1] for entry in chronological]
        ordered = indices == sorted(indices)
        if allow_cyclic_phase_order:
            # A valid cut may rotate the prescribed order once, but it cannot
            # skip, duplicate, or arbitrarily permute phase identities.
            expected_indices = [int(r['id'].removeprefix('phase_'))
                                for r in requirements if r['id'].startswith('phase_')]
            ordered = any(indices == expected_indices[offset:] + expected_indices[:offset]
                          for offset in range(len(expected_indices)))
        if not no_overlap or not ordered:
            errors.append('phase_order_not_established')
            failed_phase_ids.update(entry[0] for entry in phase_spans)
    correction_ids.update(failed_phase_ids)
    correction_ids.update(
        rid for rid, observation in resolved.items()
        if (rid == 'completion' or rid.startswith('phase_')) and observation['verdict'] == 'unresolved'
    )
    unresolved = sorted(expected - resolved.keys() | {k for k, v in resolved.items() if v['verdict'] == 'unresolved'}
                        | failed_phase_ids)
    contradicted = sorted(k for k, v in resolved.items() if v['verdict'] == 'contradicted')
    # A malformed reply cannot supply a conclusive rejection either.
    status = 'incomplete' if errors or unresolved else 'rejected' if contradicted else 'passed'
    return {'passed': status == 'passed', 'reviewStatus': status, 'errors': errors,
            'unresolvedRequirementIds': unresolved, 'contradictedRequirementIds': contradicted,
            'correctionRequirementIds': sorted(correction_ids),
            'observations': list(resolved.values())}


_INTERVAL_ACTION_FIELDS = ('earlier_interval_action', 'later_interval_action')


def cycle_semantic_question(requirements: list[dict[str, Any]], frames: list[dict[str, Any]],
                            *, first_role_image: int,
                            review_defining_action: bool = False) -> tuple[str, dict[str, Any]]:
    """Ask for observed actions, never a mapping between numbered phase namespaces."""
    phases = [row for row in requirements if row['id'].startswith('phase_')]
    labels = [row['description'] for row in phases]
    if len(labels) != 2 or len(set(labels)) != 2 or 'unresolved' in labels:
        raise ValueError('A measured two-phase cycle needs two distinct action descriptions')
    schema = {'type': 'object', 'additionalProperties': False,
              'required': list(_INTERVAL_ACTION_FIELDS),
              'properties': {field: {'type': 'string', 'enum': [*labels, 'unresolved']}
                             for field in _INTERVAL_ACTION_FIELDS}}
    action = next((row['description'] for row in requirements if row['id'] == 'action'), None)
    if review_defining_action:
        if not action:
            raise ValueError('Measured action review needs the reviewed defining action')
        schema['required'].append('reviewed_action_visibility')
        schema['properties']['reviewed_action_visibility'] = {
            'type': 'string', 'enum': ['supported', 'contradicted', 'unresolved']}
    prompt = (
        f'The three supplied images (attachments {first_role_image}, {first_role_image + 1}, '
        f'{first_role_image + 2}) are chronological source frames: start, measured interior '
        'excursion, return. For each interval select the action visibly occurring between its '
        'endpoint images. earlier_interval_action means start to excursion; '
        'later_interval_action means excursion to return. Choose the action description from '
        'the supplied choices, not its order in the definition. Do not assume the clip begins '
        'standing. Use unresolved if the action is not visually established. Code independently '
        'verified cycle timing and return; do not recalculate completeness or output any numeric '
        'references. Choices: ' + json.dumps([*labels, 'unresolved'])
        + ('\nReviewed defining action (preserved in full): ' + action
           + '\nJudge whether these source images visibly establish the entire reviewed action, '
             'including its stated endpoint relationship. Use unresolved when that relationship '
             'is occluded or unclear; motion toward an endpoint alone does not establish it. '
             'Return only the qualitative reviewed_action_visibility verdict; code owns its '
             'source-frame references.' if review_defining_action else '')
        + '\nOutput schema: ' + json.dumps(schema)
    )
    return prompt, schema


def verified_source_pair_execution_unit(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Bind a source-owned unit through the existing verified selected-to-parent time map."""
    authority = payload.get('preReconstructionSourceIntervalAuthority') or {}
    unit = authority.get('sourcePairExecutionUnit')
    mapping = (payload.get('sourcePoseCameraReference') or {}).get('sourceTimelineMapping') or {}
    if not isinstance(unit, dict):
        return None
    hashes = [unit.get(key) for key in ('sourceVideoSha256', 'sourceOriginalVideoSha256',
                                      'sourceManifestSha256', 'selectedFrameClockSha256')]
    if not all(isinstance(value, str) and len(value) == 64
               and all(char in '0123456789abcdefABCDEF' for char in value) for value in hashes):
        return None
    if not (authority.get('authoritative') is True and unit.get('executionUnitComplete') is True
            and unit.get('requiredSourceExposuresRetained') is True and mapping.get('verified') is True
            and unit.get('sourceVideoSha256') == mapping.get('selectedSegmentSha256')
            and unit.get('sourceOriginalVideoSha256') == mapping.get('parentSourceSha256')
            and unit.get('sourceManifestSha256') == mapping.get('selectionReceiptSha256')
            and unit.get('selectedFrameClockSha256') == mapping.get('selectedFrameClockReceiptSha256')):
        return None
    members = unit.get('memberIntervals')
    try:
        if (len(members) != 2 or members[0]['endSeconds'] != members[1]['startSeconds']
                or not all(math.isfinite(float(value)) for member in members for value in member.values())
                or not all(member['startSeconds'] < member['peakSeconds'] < member['endSeconds']
                           for member in members)):
            return None
    except (TypeError, KeyError):
        return None
    return unit


def paired_cycle_semantic_question(requirements: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Review code-enumerated member actions and side coverage, never infer sides from signal sign."""
    phases = [row['description'] for row in requirements if row['id'].startswith('phase_')]
    if len(phases) != 2 or len(set(phases)) != 2:
        raise ValueError('A paired return unit needs two distinct reviewed actions')
    action = next(row['description'] for row in requirements if row['id'] == 'action')
    qualifiers = [row['description'] for row in requirements if row['id'].startswith('variant_')]
    properties = {f'{member}_{interval}_action': {'type': 'string', 'enum': [*phases, 'unresolved']}
                  for member in ('first', 'second') for interval in ('earlier', 'later')}
    properties.update({f'{member}_action_visibility': {'type': 'string',
                       'enum': ['supported', 'contradicted', 'unresolved']}
                       for member in ('first', 'second')})
    properties['required_side_coverage'] = {'type': 'string', 'enum': [
        'distinct_required_sides', 'same_side', 'not_required', 'unresolved']}
    schema = {'type': 'object', 'additionalProperties': False,
              'required': list(properties), 'properties': properties}
    prompt = ('The five chronological source images show first start, first excursion, shared '
              'return/second start, second excursion, final return. Code owns these exposures, '
              'their order and measured return timing. For each member choose the visible action '
              'from start to excursion and excursion to return. Judge the full reviewed action '
              'for EACH member. Separately judge whether the reviewed qualifiers require both '
              'sides and whether DISTINCT required sides are visibly demonstrated. Repeated '
              'same-side actions, opposite image motion, PCA sign and an unseen body side do '
              'not establish distinct-side coverage. Use unresolved for ambiguity. Do not output '
              'timestamps, frame references or counts. Reviewed defining action: ' + action
              + '\nReviewed qualifiers: ' + json.dumps(qualifiers)
              + '\nAction choices: ' + json.dumps(phases)
              + '\nOutput schema: ' + json.dumps(schema))
    return prompt, schema


def resolve_paired_cycle_semantics(payload: Any, requirements: list[dict[str, Any]]) -> dict[str, Any]:
    """Code owns the number of members and accepts only complete, distinct-side observed actions."""
    try:
        _, schema = paired_cycle_semantic_question(requirements)
    except (ValueError, StopIteration):
        return {'passed': False, 'memberActionsPassed': [False, False],
                'distinctRequiredSideCoverage': False}
    valid = isinstance(payload, dict) and set(payload) == set(schema['properties'])
    if valid:
        valid = all(value in schema['properties'][key]['enum'] for key, value in payload.items())
    phases = {row['description'] for row in requirements if row['id'].startswith('phase_')}
    members = [bool(valid and payload[f'{member}_action_visibility'] == 'supported'
                    and {payload[f'{member}_earlier_action'], payload[f'{member}_later_action']} == phases)
               for member in ('first', 'second')]
    return {'passed': bool(all(members) and payload.get('required_side_coverage') == 'distinct_required_sides'),
            'memberActionsPassed': members,
            'distinctRequiredSideCoverage': bool(valid and payload['required_side_coverage'] == 'distinct_required_sides')}


def resolve_cycle_semantics(payload: Any, requirements: list[dict[str, Any]],
                            frames: list[dict[str, Any]], cycle_choices: dict[str, Any]) -> dict[str, Any]:
    """Bind semantic selections to measured spans and derive completion in code."""
    action_review = isinstance(payload, dict) and 'reviewed_action_visibility' in payload
    semantic = [row for row in requirements if row['id'] != 'completion'
                and (row['id'] != 'action' or not action_review)
                and not row['id'].startswith('phase_')]
    expected = set(_INTERVAL_ACTION_FIELDS) | ({'observations'} if semantic else set())
    if action_review:
        expected.add('reviewed_action_visibility')
        if payload['reviewed_action_visibility'] not in {'supported', 'contradicted', 'unresolved'}:
            return {'observations': []}
    if not isinstance(payload, dict) or set(payload) != expected:
        return {'observations': []}
    rows = payload.get('observations', [])
    if semantic and aggregate_evidence({'observations': rows}, semantic,
            [frame for frame in frames if frame['sampling'] == 'uniform'])['errors']:
        return {'observations': []}
    phases = [row for row in requirements if row['id'].startswith('phase_')]
    by_label = {row['description']: row['id'] for row in phases}
    if len(phases) != 2 or len(by_label) != 2 or 'unresolved' in by_label:
        return {'observations': []}
    selections = [payload.get(field) for field in _INTERVAL_ACTION_FIELDS]
    if any(not isinstance(label, str) or label not in {*by_label, 'unresolved'} for label in selections):
        return {'observations': []}
    spans = cycle_choices.get('spanChoices', [])
    role_ids = cycle_choices.get('roleFrameIds', {})
    if (len(spans) != 2 or set(role_ids) != {'start', 'excursion', 'return'}
            or any(not isinstance(span, dict) or not isinstance(span.get('frameIds'), list)
                   or len(span['frameIds']) != 2 for span in spans)):
        return {'observations': []}
    resolved = len(set(selections)) == 2 and set(selections) == set(by_label)
    result = list(rows)
    if action_review:
        result.append({'requirementId': 'action', 'verdict': payload['reviewed_action_visibility'],
                       'evidenceFrameIds': [role_ids[key] for key in ('start', 'excursion', 'return')]})
    if resolved:
        result.extend({'requirementId': by_label[label], 'verdict': 'supported',
                       'evidenceFrameIds': list(span['frameIds'])}
                      for label, span in zip(selections, spans))
    else:
        result.extend({'requirementId': phase['id'], 'verdict': 'unresolved', 'evidenceFrameIds': []}
                      for phase in phases)
    if any(row['id'] == 'completion' for row in requirements):
        result.append({'requirementId': 'completion',
                       'verdict': 'supported' if resolved else 'unresolved',
                       'evidenceFrameIds': [role_ids[key] for key in ('start', 'excursion', 'return')]
                       if resolved else []})
    return {'observations': result}


def correct_incomplete_evidence(payload: Any, requirements: list[dict[str, Any]],
                                frames: list[dict[str, Any]],
                                request_correction: Any, *,
                                allow_cyclic_phase_order: bool = False,
                                cycle_choices: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    """Make one targeted follow-up for incomplete temporal evidence."""
    initial = aggregate_evidence(payload, requirements, frames,
                                 allow_cyclic_phase_order=allow_cyclic_phase_order,
                                 cycle_choices=cycle_choices)
    correction_ids = initial['correctionRequirementIds']
    correctable_errors = {'sequence_evidence_missing', 'phase_order_not_established',
                          'cycle_role_evidence_missing', 'uniform_coverage_missing',
                          'invalid_verdict_or_frame_reference'}
    if not correction_ids or any(error not in correctable_errors for error in initial['errors']):
        return payload, {'attempted': False, 'requirementIds': [], 'before': initial,
                         'after': initial}
    by_id = {requirement['id']: requirement for requirement in requirements}
    targeted = [by_id[rid] for rid in correction_ids if rid in by_id]
    if not targeted:
        return payload, {'attempted': False, 'requirementIds': [], 'before': initial,
                         'after': initial}
    use_cycle_choices = isinstance(cycle_choices, dict) and any(
        row['id'].startswith('phase_') or row['id'] == 'completion' for row in targeted)
    if use_cycle_choices:
        targeted = [row for row in requirements
                    if row['id'].startswith('phase_') or row['id'] == 'completion']
        prompt, correction_schema = cycle_semantic_question(targeted, frames, first_role_image=1)
    else:
        prompt = evidence_prompt(targeted, frames,
                                 allow_cyclic_phase_order=allow_cyclic_phase_order,
                                 semantic_labels=True)
        prompt += ('\nMake one bounded correction for only these requirements. Prior validator errors: '
                   + json.dumps(initial['errors']))
        correction_schema = evidence_schema(targeted, frames, semantic_labels=True)
    targeted_ids = {row['id'] for row in targeted}
    corrected_payload = request_correction(targeted, frames, prompt, correction_schema)
    if use_cycle_choices:
        corrected_payload = resolve_cycle_semantics(corrected_payload, targeted, frames, cycle_choices)
    else:
        corrected_payload = resolve_semantic_evidence(corrected_payload, targeted, frames)
    corrected = aggregate_evidence(corrected_payload, targeted, frames,
                                   allow_cyclic_phase_order=allow_cyclic_phase_order,
                                   cycle_choices=cycle_choices)
    if corrected['reviewStatus'] == 'incomplete':
        # Do not salvage rows from a malformed or partial follow-up: doing so
        # could turn an invalid structured response into a passing merged one.
        return payload, {'attempted': True, 'requirementIds': [r['id'] for r in targeted],
                         'before': initial, 'correction': corrected, 'after': initial}
    retained = [row for row in (payload.get('observations', []) if isinstance(payload, dict) else [])
                if isinstance(row, dict) and row.get('requirementId') not in targeted_ids]
    replacements = corrected_payload.get('observations', []) if isinstance(corrected_payload, dict) else []
    merged = {'observations': retained + [row for row in replacements if isinstance(row, dict)]}
    after = aggregate_evidence(merged, requirements, frames,
                               allow_cyclic_phase_order=allow_cyclic_phase_order,
                               cycle_choices=cycle_choices)
    return merged, {'attempted': True, 'requirementIds': [r['id'] for r in targeted],
                    'before': initial, 'correction': corrected, 'after': after}
