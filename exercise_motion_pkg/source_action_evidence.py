"""Independent necessary observations for source actions, never exercise-name rules."""
from __future__ import annotations

import math
import re
from typing import Any


MIN_LANDMARK_CONFIDENCE = 0.65
MIN_ANGULAR_EXCURSION_DEGREES = 15.0
# Semantic questions did not change when completion admission became stricter.
EVENT_SEMANTICS_POLICY_VERSION = 11


def articulation_event_intervals(pose: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Propose local excursions, never infer an action from their geometry.

    Keep left/right tracks separate and do not interpolate occluded samples.
    The angular prominence only bounds noisy proposals; it cannot approve motion.
    """
    if not isinstance(pose, dict) or pose.get('coordinateSpace') != 'normalized_image_xy':
        return []
    width, height = pose.get('imageWidth'), pose.get('imageHeight')
    if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (width, height)):
        return []
    frames = pose.get('frames') or []
    events = {}
    for side in ('left', 'right'):
        for chain in (('shoulder', 'elbow', 'wrist'), ('hip', 'knee', 'ankle'),
                      ('hip', 'shoulder', 'wrist')):
            runs, run = [], []
            for frame in frames:
                time = frame.get('sourceTimeSec')
                angle = _joint_angle(frame, tuple(f'{side}_{name}' for name in chain), width / height)
                valid = type(time) in (int, float) and math.isfinite(time) and angle is not None
                if not valid or (run and (time <= run[-1][0] or time - run[-1][0] > .5)):
                    if run: runs.append(run)
                    run = []
                if not valid:
                    continue
                run.append((float(time), angle))
            if run: runs.append(run)
            for run in runs:
                # A direction reversal with a 15-degree excursion on both sides
                # provides context without filtering or retiming the source.
                turns = [0]
                direction = 0
                for i in range(1, len(run)):
                    delta = run[i][1] - run[turns[-1]][1]
                    if direction == 0:
                        if abs(delta) >= 15:
                            direction = 1 if delta > 0 else -1
                            extreme = i
                    elif (run[i][1] - run[extreme][1]) * direction >= 0:
                        extreme = i
                    elif abs(run[i][1] - run[extreme][1]) >= 15:
                        turns.append(extreme)
                        direction *= -1
                        extreme = i
                if direction:
                    turns.append(extreme)
                if turns[-1] != len(run) - 1:
                    turns.append(len(run) - 1)
                for a, b, c in zip(turns, turns[1:], turns[2:]):
                    prominence = min(abs(run[b][1] - run[a][1]), abs(run[b][1] - run[c][1]))
                    if prominence < 15:
                        continue
                    times = [run[i][0] for i in (a, b, c)]
                    key = tuple(times)
                    events.setdefault(key, {'times': times, 'tracks': []})['tracks'].append(f'{side}_{chain[1]}')
                # Both directions need proposals: a clean and a press can occupy
                # opposite halves of one arm excursion.
                for a, b in zip(turns, turns[1:]):
                    if abs(run[b][1] - run[a][1]) < 15:
                        continue
                    midpoint = (a + b) // 2
                    if not a < midpoint < b:
                        continue
                    times = [run[i][0] for i in (a, midpoint, b)]
                    events.setdefault(tuple(times), {'times': times, 'tracks': []})['tracks'].append(f'{side}_{chain[1]}')
    return [dict(event, id=f'event_{i + 1}', sampleTimes=[float(frame['sourceTimeSec']) for frame in frames
                if type(frame.get('sourceTimeSec')) in (int, float)
                and event['times'][0] <= frame['sourceTimeSec'] <= event['times'][-1]])
            for i, event in enumerate(sorted(events.values(),
                key=lambda event: (event['times'][0], event['times'][-1])))]


def ordered_event_coverage(phases: list[dict[str, Any]], events: list[dict[str, Any]],
                           labels: dict[str, list[str]], *, allow_cyclic_order: bool = False) -> list[dict[str, Any]]:
    """Find complete, nonoverlapping coverage; a missing event is unresolved."""
    if allow_cyclic_order:
        for offset in range(len(phases)):
            selected = ordered_event_coverage(phases[offset:] + phases[:offset], events, labels)
            if selected:
                return selected[-offset:] + selected[:-offset] if offset else selected
        return []
    paths = [([], -math.inf)]
    for phase in phases:
        next_paths = []
        for path, end in paths:
            for event in events:
                if (event['times'][0] >= end and phase['description'] in labels.get(event['id'], [])
                        and event['id'] not in {row['id'] for row in path}):
                    next_paths.append(([*path, event], event['times'][-1]))
        # The earliest finishing path dominates later paths for future coverage.
        paths = sorted(next_paths, key=lambda pair: pair[1])[:1]
        if not paths:
            return []
    return paths[0][0]


def event_review_sample_times(event: dict[str, Any], completion: dict[str, Any]) -> list[float]:
    """Keep measured witnesses and turning-point context at original resolution."""
    available = event.get('sampleTimes', event['times'])
    required = set(event['times'])
    required.update(time for witness in completion.get('witnesses', []) for time in witness['times'])
    peak = min(range(len(available)), key=lambda i: abs(available[i] - event['times'][1]))
    required.update(available[i] for i in (peak - 1, peak + 1) if 0 <= i < len(available))
    return sorted(time for time in required if time in available)


def required_pose_checks(description: str) -> list[str]:
    text = description.casefold().replace('-', ' ')
    # Only explicit positive action language establishes this obligation.
    if re.search(r'\b(?:no|without|avoid)\s+(?:an?\s+)?overhead\s+press', text):
        return []
    if re.search(r'\boverhead\s+(?:press|lockout)|\bpress\w*\b[^.;]*\boverhead\b', text):
        return ['overhead_reach']
    return []


def event_action_completion(description: str, pose: dict[str, Any] | None,
                            event: dict[str, Any]) -> dict[str, Any]:
    """Necessary measured witnesses, independent of the model's action label.

    Unknown action grammar remains unresolved. These checks corroborate motion;
    they do not establish exercise identity or accurate three-dimensional form.
    """
    text = description.casefold().replace('-', ' ')
    primitives = [name for name, matches in (
        ('overhead_press', required_pose_checks(description)),
        ('push_up', re.search(r'\bpush\s*up\b', text)),
        ('row', re.search(r'\brow(?:ing)?\b', text)),
        ('squat_clean', re.search(r'\bsquat\s+clean\b', text))) if matches]
    primitive = primitives[0] if len(primitives) == 1 else None
    result = {'passed': False, 'primitive': primitive, 'witnesses': [],
              'reason': 'action_completion_not_established' if primitive else 'unsupported_action_completion'}
    if primitive is None or not isinstance(pose, dict) or pose.get('coordinateSpace') != 'normalized_image_xy':
        return result
    width, height = pose.get('imageWidth'), pose.get('imageHeight')
    if not all(type(value) in (int, float) and math.isfinite(value) and value > 0 for value in (width, height)):
        return result
    start, end = event['times'][0], event['times'][-1]
    frames = [frame for frame in pose.get('frames', [])
              if type(frame.get('sourceTimeSec')) in (int, float)
              and math.isfinite(frame['sourceTimeSec']) and start <= frame['sourceTimeSec'] <= end]
    tracks = {}
    for side in ('left', 'right'):
        for name, chain in [('elbow', ('shoulder', 'elbow', 'wrist')),
                            ('upper_arm', ('hip', 'shoulder', 'elbow')),
                            ('knee', ('hip', 'knee', 'ankle'))]:
            runs, run = [], []
            for frame in frames:
                angle = _joint_angle(frame, tuple(f'{side}_{joint}' for joint in chain), width / height)
                if angle is None:
                    continue
                time = float(frame['sourceTimeSec'])
                if run and (time <= run[-1][0] or time - run[-1][0] > .5):
                    runs.append(run)
                    run = []
                # Missing samples are never filled; even measured flanks must
                # stay within the existing half-second observation gap limit.
                run.append((time, angle))
            if run: runs.append(run)
            tracks[side, name] = runs

    def motion(side: str, names: tuple[str, ...], kind: str) -> dict[str, Any] | None:
        for name in names:
            for run in tracks[side, name]:
                if kind == 'return' and abs(run[0][0] - start) > 1e-6:
                    # An occluded entry cannot establish the starting state of a return.
                    continue
                for i in range(1, len(run)):
                    left = (run[0] if kind == 'return' else
                            min(run[:i], key=lambda sample: sample[1]) if kind == 'extension' else
                            max(run[:i], key=lambda sample: sample[1]))
                    delta = (left[1] - run[i][1]) if kind != 'extension' else (run[i][1] - left[1])
                    if delta < MIN_ANGULAR_EXCURSION_DEGREES:
                        continue
                    times = [left[0], run[i][0]]
                    if kind == 'return':
                        # Return toward the observed entry state, not merely
                        # toward a partially lowered intermediate sample.
                        right = next((after for after in run[i + 1:]
                            if after[1] - run[i][1] >= MIN_ANGULAR_EXCURSION_DEGREES
                            and after[1] >= left[1] - MIN_ANGULAR_EXCURSION_DEGREES), None)
                        if right is None:
                            continue
                        times.append(right[0])
                    return {'side': side, 'track': name, 'motion': kind, 'times': times}
        return None

    each_side = bool(re.search(r'\beach side\b|\bboth sides\b|\balternat', text))
    bilateral = each_side or bool(re.search(r'\bboth (?:arms|hands)\b', text))
    witnesses = []
    if primitive in {'push_up', 'row'}:
        kind = ('flexion' if primitive == 'push_up' and re.search(r'\blower|\bdescend|\beccentric', text) else
                'extension' if primitive == 'push_up' and re.search(r'\brise|\bpush back|\bconcentric', text) else 'return')
        witnesses = [witness for side in ('left', 'right')
                     if (witness := motion(side, ('elbow', 'upper_arm') if primitive == 'row' else ('elbow',), kind))]
        passed = len(witnesses) >= (2 if bilateral else 1)
        if each_side and passed:
            passed = witnesses[0]['times'][1] != witnesses[1]['times'][1]
    elif primitive == 'overhead_press':
        reach = overhead_reach_samples(pose, single_arm=not bilateral)
        terminal = any(abs(sample['sourceTimeSec'] - end) <= 1e-6 for sample in reach['samples'])
        witnesses = [witness for side in ('left', 'right') if (witness := motion(side, ('elbow',), 'extension'))]
        final = next((frame for frame in frames if abs(frame['sourceTimeSec'] - end) <= 1e-6), {})
        aligned = False
        for side in ('left', 'right'):
            points = [_point(final, f'{side}_{joint}', width / height) for joint in ('shoulder', 'hip', 'ankle')]
            if all(point is not None for point in points):
                shoulder, hip, ankle = points
                aligned |= sum((shoulder[i] - hip[i]) * (hip[i] - ankle[i]) for i in (0, 1)) > 0
        passed = terminal and aligned and len(witnesses) >= (2 if bilateral else 1)
        result['terminalOverheadReach'] = terminal
        result['terminalBodyAlignment'] = aligned
    else:
        knees = [witness for side in ('left', 'right') if (witness := motion(side, ('knee',), 'flexion'))]
        arms = [witness for side in ('left', 'right') if (witness := motion(side, ('elbow',), 'flexion'))]
        # A clean must reach a catch near the shoulders, rather than merely
        # lower the body with the implements still below the hips.
        catch_sides = []
        final = next((frame for frame in frames if abs(frame['sourceTimeSec'] - end) <= 1e-6), {})
        for side in ('left', 'right'):
            points = [_point(final, f'{side}_{joint}', width / height) for joint in ('shoulder', 'hip', 'wrist')]
            if all(point is not None for point in points):
                shoulder, hip, wrist = points
                if math.dist(wrist, shoulder) < math.dist(wrist, hip):
                    catch_sides.append(side)
        witnesses = [*knees, *arms]
        passed = bool(knees and arms and catch_sides) and not any(
            abs(sample['sourceTimeSec'] - end) <= 1e-6
            for sample in overhead_reach_samples(pose, single_arm=True)['samples'])
        result['catchSides'] = catch_sides
    result.update(passed=passed, witnesses=witnesses,
                  reason=None if passed else 'action_completion_not_established')
    return result


def _point(frame: dict[str, Any], name: str, aspect: float) -> tuple[float, float] | None:
    value = (frame.get('joints') or {}).get(name)
    confidence = (frame.get('jointConfidence') or {}).get(name)
    if (not isinstance(value, (list, tuple)) or len(value) < 2
            or type(confidence) not in (int, float) or not math.isfinite(confidence)
            or confidence < MIN_LANDMARK_CONFIDENCE):
        return None
    x, y = value[:2]
    if (type(x) not in (int, float) or type(y) not in (int, float)
            or not math.isfinite(x) or not math.isfinite(y) or not (0 < x < 1 and 0 < y < 1)):
        return None
    return x * aspect, y


def _joint_angle(frame: dict[str, Any], names: tuple[str, ...], aspect: float) -> float | None:
    points = [_point(frame, name, aspect) for name in names]
    if any(point is None for point in points):
        return None
    a, b, c = points
    u, v = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
    denominator = math.hypot(*u) * math.hypot(*v)
    if denominator <= 1e-9:
        return None
    return math.degrees(math.acos(max(-1., min(1., sum(x*y for x, y in zip(u, v)) / denominator))))


def overhead_reach_samples(pose: dict[str, Any] | None, *, single_arm: bool = False) -> dict[str, Any]:
    """Require observed head and arm chains extending above it along the torso axis.

    A projection can corroborate an overhead reach, not prove a press or 3D lockout.
    Missing, cropped and ambiguous observations therefore never mean 'absent'.
    """
    if not isinstance(pose, dict) or pose.get('coordinateSpace') != 'normalized_image_xy':
        return {'status': 'unresolved', 'reason': 'verified_image_pose_missing', 'samples': []}
    width, height = pose.get('imageWidth'), pose.get('imageHeight')
    if (type(width) not in (int, float) or type(height) not in (int, float)
            or not math.isfinite(width) or not math.isfinite(height) or min(width, height) <= 0):
        return {'status': 'unresolved', 'reason': 'image_dimensions_missing', 'samples': []}
    aspect = width / height
    supported = []
    observable = 0
    for frame in pose.get('frames') or []:
        time = frame.get('sourceTimeSec')
        if type(time) not in (int, float) or not math.isfinite(time):
            continue
        names = ['nose', *[f'{side}_{joint}' for side in ('left', 'right')
                          for joint in ('hip', 'shoulder', 'elbow', 'wrist')]]
        points = {name: _point(frame, name, aspect) for name in names}
        anchors = [points[name] for name in ('nose', 'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder')]
        if any(point is None for point in anchors):
            continue
        shoulder = tuple((points['left_shoulder'][i] + points['right_shoulder'][i]) / 2 for i in (0, 1))
        hip = tuple((points['left_hip'][i] + points['right_hip'][i]) / 2 for i in (0, 1))
        axis = tuple(shoulder[i] - hip[i] for i in (0, 1))
        length = math.hypot(*axis)
        if length <= 1e-6:
            continue
        axis = tuple(value / length for value in axis)
        def elevation(point: tuple[float, float]) -> float:
            return sum((point[i] - shoulder[i]) * axis[i] for i in (0, 1))
        head_height = elevation(points['nose'])
        # A torso axis inconsistent with the observed head is not an upright reach observation.
        if head_height <= 0:
            continue
        sides = []
        available_sides = 0
        for side in ('left', 'right'):
            chain = [points[f'{side}_{joint}'] for joint in ('shoulder', 'elbow', 'wrist')]
            if any(point is None for point in chain):
                continue
            available_sides += 1
            shoulder_height, elbow_height, wrist_height = map(elevation, chain)
            if wrist_height > head_height and wrist_height > elbow_height > shoulder_height:
                sides.append(side)
        observable += int(available_sides >= (1 if single_arm else 2))
        if len(sides) >= (1 if single_arm else 2):
            supported.append({'sourceTimeSec': float(time), 'sides': sides})
    return {'status': 'corroborated' if supported else 'unresolved',
            'reason': 'visible_overhead_reach' if supported else 'overhead_reach_not_established',
            'observableSampleCount': observable, 'samples': supported}


def action_pose_grounding(requirements: list[dict[str, Any]],
                          pose: dict[str, Any] | None, *,
                          frames: list[dict[str, Any]] | None = None,
                          observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    checks = []
    for requirement in requirements:
        for check in required_pose_checks(requirement['description']):
            text = requirement['description'].casefold().replace('-', ' ')
            # Unspecified laterality cannot acquire a bilateral obligation here.
            bilateral = bool(re.search(r'\bboth (?:arms|hands)\b|\bdumbbells\b|\bbarbell\b', text))
            result = overhead_reach_samples(pose, single_arm=not bilateral)
            if observations is not None and result['status'] == 'corroborated':
                claim = next((row for row in observations if row.get('requirementId') == requirement['id']), {})
                sample_times = sorted({float(frame['sourceTimeSec']) for frame in (pose or {}).get('frames', [])
                                       if type(frame.get('sourceTimeSec')) in (int, float)
                                       and math.isfinite(frame['sourceTimeSec'])})
                supported_times = {sample['sourceTimeSec'] for sample in result['samples']}
                matched = []
                for frame in frames or []:
                    time = frame['timestampSeconds']
                    index = min(range(len(sample_times)), key=lambda i: abs(sample_times[i] - time))
                    # Match a citation only to the measured sample's local temporal cell.
                    gaps = [abs(sample_times[index] - sample_times[i])
                            for i in (index - 1, index + 1) if 0 <= i < len(sample_times)]
                    tolerance = min(gaps) / 2 if gaps else 0.0
                    if sample_times[index] in supported_times and abs(sample_times[index] - time) <= tolerance + 1e-6:
                        matched.append(frame['id'])
                result['corroboratedFrameIds'] = matched
                if claim.get('verdict') == 'supported' and not set(claim.get('evidenceFrameIds', [])).intersection(matched):
                    result.update(status='unresolved', reason='cited_frames_do_not_establish_overhead_reach')
            checks.append({'requirementId': requirement['id'], 'check': check, **result})
    unresolved = sorted({row['requirementId'] for row in checks if row['status'] != 'corroborated'})
    return {'required': bool(checks), 'passed': not unresolved,
            'reviewStatus': 'incomplete' if unresolved else 'passed',
            'unresolvedRequirementIds': unresolved, 'checks': checks,
            'authority': 'necessary_observations_only_not_semantic_approval'}
