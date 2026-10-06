"""Rank reconstruction evidence without rejecting every occluded source."""
import math


def observability_ranking_adjustment(observability):
    """Use the same advisory evidence weight at every source ordering stage."""
    if not isinstance(observability, dict) or not observability.get('available'):
        return 0.
    score = observability.get('score')
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        return 0.
    return .15 * (max(0., min(1., score)) - .5)


REGION_JOINTS = {
    'hands': ('left_wrist', 'right_wrist'),
    'elbows': ('left_elbow', 'right_elbow'),
    'shoulders': ('left_shoulder', 'right_shoulder'),
    'torso': ('left_shoulder', 'right_shoulder', 'left_hip', 'right_hip'),
    'hips': ('left_hip', 'right_hip'), 'knees': ('left_knee', 'right_knee'),
    'feet': ('left_ankle', 'right_ankle'), 'head': ('nose',),
    'upper_limb': ('left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist'),
    'lower_limb': ('left_hip', 'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle'),
}


def required_region_observation_metrics(payload, contract=None):
    """Require some observed evidence of every explicitly required region.

    This only rejects completely absent regions. One visible side is enough:
    ordinary self-occlusion must not impose a frontal camera or symmetry.
    Intermittent gaps remain a separate reconstruction-quality concern.
    """
    contract = contract if isinstance(contract, dict) else {}
    spec = contract.get('observableMotionSpec') or contract
    regions = spec.get('mustBeVisibleRegions', []) if isinstance(spec, dict) else []
    regions = [region for region in regions if region in REGION_JOINTS]
    frames = payload.get('frames') or []
    normalized = payload.get('coordinateSpace') == 'normalized_image_xy'
    active_side = str(contract.get('activeSide') or '').lower()
    counts = {}
    for region in regions:
        names = REGION_JOINTS[region]
        if region == 'head':
            names = (*names, 'head', 'neck', 'left_eye', 'right_eye', 'left_ear', 'right_ear')
        if active_side in ('left', 'right'):
            other = 'right_' if active_side == 'left' else 'left_'
            names = tuple(name for name in names if not name.startswith(other))
        count = 0
        for frame in frames:
            joints = frame.get('joints') or {}
            confidence = frame.get('jointConfidence') or {}
            for name in names:
                point = joints.get(name)
                if (isinstance(point, (list, tuple)) and len(point) >= 2
                        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point[:2])
                        and (not normalized or all(0. <= v <= 1. for v in point[:2]))
                        and isinstance(confidence.get(name, 1.), (int, float))
                        and confidence.get(name, 1.) >= .35):
                    count += 1
                    break
        counts[region] = count
    missing = [region for region, count in counts.items() if count == 0]
    return {'required': bool(regions), 'available': bool(frames), 'passed': not missing,
            'observedFrameCounts': counts, 'missingRegions': missing,
            'reason': 'required_source_regions_unobserved' if missing else 'required_source_regions_observed'}


def reconstruction_observability(frames, contract=None):
    """Measure relevant-joint coverage and gaps; returned score is advisory."""
    contract = contract if isinstance(contract, dict) else {}
    spec = contract.get('observableMotionSpec') or contract
    if not isinstance(spec, dict):
        spec = contract
    regions = spec.get('mustBeVisibleRegions') or spec.get('primaryMovingRegions') or []
    names = sorted({name for region in regions for name in REGION_JOINTS.get(region, ())})
    if not names:
        names = sorted({name for region in ('hands', 'elbows', 'torso', 'feet') for name in REGION_JOINTS[region]})
    active_side = str(contract.get('activeSide') or '').lower()
    if active_side not in ('left', 'right') and contract.get('handRelationship') == 'single':
        # The observed active hand determines the side; exercise labels do not.
        counts = {side: sum(side+'_wrist' in (frame.get('joints') or {}) for frame in frames)
                  for side in ('left', 'right')}
        if counts['left'] != counts['right']:
            active_side = max(counts, key=counts.get)
    if active_side in ('left', 'right'):
        other = 'right_' if active_side == 'left' else 'left_'
        names = [name for name in names if not name.startswith(other)]
    if not frames:
        return {'available': False, 'score': .5, 'advisoryOnly': True, 'reason': 'no_pose_samples'}
    coverage = {}
    longest_gaps = {}
    for name in names:
        observed = []
        for frame in frames:
            point = (frame.get('joints') or {}).get(name)
            observed.append(isinstance(point, (list, tuple)) and len(point) >= 2
                            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point[:2]))
        coverage[name] = sum(observed)/len(frames)
        longest = current = 0
        for present in observed:
            current = 0 if present else current+1
            longest = max(longest, current)
        longest_gaps[name] = longest/len(frames)
    average = sum(coverage.values())/len(names)
    minimum = min(coverage.values())
    worst_gap = max(longest_gaps.values())
    # Brief occlusion is a ranking cost, never a new binary visibility gate.
    score = .5*average + .3*minimum + .2*(1.-worst_gap)
    return {'available': True, 'advisoryOnly': True, 'policyVersion': 1,
            'score': score, 'frameCount': len(frames), 'jointCoverage': coverage,
            'longestMissingRunRatios': longest_gaps,
            'persistentMissingJoints': [name for name in names if coverage[name] < .5],
            'reason': 'observed_reconstruction_evidence'}
