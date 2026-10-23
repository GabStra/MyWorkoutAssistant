"""Frame-grounded source observations; Python, rather than prose, owns approval."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


POLICY_VERSION = 3
MAX_TIMING_EVIDENCE_SAMPLE_GAP_SECONDS = 1.0
MAX_OBSERVED_OBJECT_COUNT = 2_147_483_647


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
    phase_ordered = all(
        max(left['timestampSeconds'] for left in earlier['sampleBins'])
        < min(right['timestampSeconds'] for right in later['sampleBins'])
        for earlier, later in zip(ordered_rows, ordered_rows[1:])
        if earlier['sampleBins'] and later['sampleBins']
    ) if ordered else True
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


def source_requirements(contract: dict[str, Any], equipment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Only the reviewed action supplies semantic requirements. Generated posture
    # expectations and exercise-name guesses never acquire authority here.
    action = str(contract.get('definingAction') or '').strip()
    if not action:
        raise ValueError('Source review needs a defined action')
    requirements = [{'id': 'action', 'description': action, 'minimumDistinctFrameCount': 2}]
    for index, phase in enumerate(contract.get('requiredPhases') or []):
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
                                   frames: list[dict[str, Any]]) -> int:
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
            'requirementId': requirement['id'],
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


def evidence_schema(requirements: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    observation_schemas = []
    for requirement in requirements:
        eligible_frames = frames
        if requirement.get('id') == 'clean_interval':
            eligible_frames = [frame for frame in frames if frame.get('sampling') == 'uniform']
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
        observation_schemas.append({
            'type': 'object', 'additionalProperties': False,
            'required': ['requirementId', 'verdict', 'evidenceFrameIds'],
            'properties': properties,
        })
    return {'type': 'object', 'additionalProperties': False, 'required': ['observations'], 'properties': {
        'observations': {'type': 'array', 'minItems': len(requirements), 'maxItems': len(requirements), 'items': {
            'oneOf': observation_schemas,
        }},
    }}


def evidence_prompt(requirements: list[dict[str, Any]], frames: list[dict[str, Any]]) -> str:
    return (
        'Inspect the supplied source images directly. Return structured source evidence, never an exercise name '
        'or another reviewer\'s description. Requirements below are exhaustive; do not invent start height, '
        'stance, catch or other variant requirements. Equipment roles specify required use and object count. '
        'A support surface requires actual body contact; background equipment does not establish use. '
        'For each exact requirementId return supported, contradicted or unresolved and only the minimum exact '
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
        'that minimum plus one sample for each separately required phase. phase_ requirements '
        'are ordered: cite no more than two samples for each phase from the same execution, '
        'not a mixture of different repetitions. Clean interval evidence must cover all supplied uniform frames. '
        'For clean_interval, cite every uniform frame ID and no motion frame IDs. '
        'Images are supplied in uniform order followed by motion order; image numbers in the inventory are local '
        'to each sampling group. tileNumber is the number printed in the image. '
        'Never invent timestamps or frame IDs. Return only JSON matching the supplied schema.\n'
        'Requirements: ' + json.dumps(requirements) + '\nFrame inventory: ' + json.dumps(frames)
        + '\nSchema: ' + json.dumps(evidence_schema(requirements, frames))
    )


def aggregate_evidence(payload: Any, requirements: list[dict[str, Any]],
                       frames: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {r['id'] for r in requirements}
    available = {f['id']: f for f in frames}
    observations = payload.get('observations') if isinstance(payload, dict) else None
    errors = []
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
                continue
        if rid == 'clean_interval' and verdict == 'supported':
            uniform_ids = {f['id'] for f in frames if f['sampling'] == 'uniform'}
            if not uniform_ids.issubset(ids):
                errors.append('uniform_coverage_missing')
                continue
        if rid == 'clean_interval' and any(available[i].get('sampling') != 'uniform' for i in ids):
            errors.append('clean_interval_motion_frame_not_allowed')
            continue
        if len(ids) > evidence_frame_id_limit(requirement, requirements, frames):
            errors.append('too_many_frame_references')
            continue
        resolved[rid] = observation
    previous_span = None
    for requirement in requirements:
        rid = requirement['id']
        observation = resolved.get(rid)
        if not rid.startswith('phase_') or not observation or observation['verdict'] != 'supported':
            continue
        times = [available[i]['timestampSeconds'] for i in observation['evidenceFrameIds']]
        span = min(times), max(times)
        if previous_span is not None and (span[0] < previous_span[1] or span[0] <= previous_span[0]):
            errors.append('phase_order_not_established')
        previous_span = span
    unresolved = sorted(expected - resolved.keys() | {k for k, v in resolved.items() if v['verdict'] == 'unresolved'})
    contradicted = sorted(k for k, v in resolved.items() if v['verdict'] == 'contradicted')
    # A malformed reply cannot supply a conclusive rejection either.
    status = 'incomplete' if errors or unresolved else 'rejected' if contradicted else 'passed'
    return {'passed': status == 'passed', 'reviewStatus': status, 'errors': errors,
            'unresolvedRequirementIds': unresolved, 'contradictedRequirementIds': contradicted,
            'observations': list(resolved.values())}
