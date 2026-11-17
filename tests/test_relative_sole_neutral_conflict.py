from exercise_motion_pkg.body_support_observation import POLICY_VERSION as BODY_SUPPORT_POLICY_VERSION
from exercise_motion_pkg import foot_contact_observation as foot
from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts


def _pose_and_observations(*, distinct_neutral_minority=False):
    video_sha = 'same-source-video'
    frames = []
    pose_frames = []
    for index in range(66):
        time = index / 30.
        raised = distinct_neutral_minority and (index < 54 or index >= 60)
        frames.append({'timeSeconds': time, 'joints': {
            'right_ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
            'right_heel': {'image': [.5, .55 if raised else .6],
                           'world': [0., -.1 if raised else 0., 0.], 'confidence': .99},
            'right_toe': {'image': [.65, .6], 'world': [.2, 0., 0.], 'confidence': .99},
        }})
        pose_frames.append({'sourceTimeSec': time, 'joints': {'right_ankle': [.5, .5]}})
    observations = {
        'available': True, 'source': 'mediapipe_full_heel_forefoot',
        'sourceVideoSha256': video_sha, 'fps': 30., 'imageWidth': 640, 'imageHeight': 360,
        'frames': frames,
    }
    source_pose = {
        'sourceTimeOriginSec': 0., 'sourcePoseSampleBoundaryToleranceSeconds': .001,
        'imageWidth': 640, 'imageHeight': 360, 'frames': pose_frames,
    }
    evidence = {
        'sourceVideoSha256': video_sha, 'contacts': [],
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'policyVersion': BODY_SUPPORT_POLICY_VERSION, 'sourceVideoSha256': video_sha,
            'observation': {'rightFoot': 'stationary_forefoot', 'rightFootSurface': 'ground'},
        },
        'stationarySoleIntervalReview': {
            'sourceVideoSha256': video_sha, 'sourceFrameCount': 66,
            'framesPerChunk': 6,
            'feet': {'right': {
                'confirmed': True, 'reviewedFrameCount': 66,
                'decisions': (['stationary_full_sole_ground'] * (10 if distinct_neutral_minority else 2)
                              + ['stationary_forefoot_ground']
                              + ['stationary_full_sole_ground'] * (0 if distinct_neutral_minority else 8)),
            }},
        },
    }
    return observations, evidence, source_pose


def test_indistinguishable_stationary_forefoot_cannot_calibrate_full_sole():
    observations, evidence, source_pose = _pose_and_observations()

    result = classify_foot_contacts(observations, evidence, source_pose)
    right = result['feet']['right']

    assert 'full_sole' not in right['states']
    assert right['states'] == ['toe_only'] * 66
    assert right['pitchReferenceSource'] == 'heel_unobserved'
    assert result['neutralCalibrationConflicts'][0]['reason'] == (
        'stationary_full_sole_and_forefoot_geometry_indistinguishable')
    assert result['neutralCalibrationConflicts'][0]['stationarySpanStartFrame'] == 0
    assert result['neutralCalibrationConflicts'][0]['stationarySpanEndFrame'] == 65
    assert result['neutralCalibrationConflicts'][0]['conflictingNeutralFrameRanges']
    assert all(channel['positiveClusterStable'] for name, channel in
               result['neutralCalibrationConflicts'][0]['geometry'].items()
               if name.endswith('Pitch'))


def test_distinct_neutral_subcluster_remains_calibratable_within_conflict_span():
    observations, evidence, source_pose = _pose_and_observations(distinct_neutral_minority=True)

    result = classify_foot_contacts(observations, evidence, source_pose)
    right = result['feet']['right']

    assert len(result['neutralCalibrationConflicts']) == 1
    assert result['neutralCalibrationConflicts'][0]['conflictingNeutralFrameRanges'] == [
        {'startFrame': 0, 'endFrame': 53}]
    assert right['states'][:54] == ['toe_only'] * 54
    assert right['states'][54:60] == ['full_sole'] * 6
    assert right['states'][60:] == ['toe_only'] * 6


def test_unobserved_heel_is_not_a_full_sole_conflict_but_explicit_lift_is():
    from copy import deepcopy
    from exercise_motion_pkg.support_geometry import source_support_contact_conflicts

    observations, evidence, source_pose = _pose_and_observations()
    patch = classify_foot_contacts(observations, evidence, source_pose)
    assert patch['feet']['right']['states'] == ['toe_only'] * 66
    assert patch['feet']['right']['pitchReferenceSource'] == 'heel_unobserved'
    evidence = {**evidence, 'footPatchEvidence': patch}
    full_sole_rows = [
        {'side': 'right', 'contactState': 'full_sole', 'sourceTimeSec': index / 30.}
        for index in range(66)
    ]

    # The patch proves forefoot contact but has no calibrated heel state.
    assert source_support_contact_conflicts(evidence, full_sole_rows) == []

    # With an observed neutral reference, the same toe_only state means that
    # the heel is raised; a full-sole claim at that time is a hard conflict.
    raised_heel = deepcopy(evidence)
    raised_heel['footPatchEvidence']['feet']['right']['pitchReferenceSource'] = 'relative_stance'
    conflicts = source_support_contact_conflicts(raised_heel, full_sole_rows)
    assert len(conflicts) == 66
    assert conflicts[0]['patchState'] == 'toe_only'

    # Missing/unknown provenance retains the previous conservative conflict.
    unbound_reference = deepcopy(evidence)
    unbound_reference['footPatchEvidence']['feet']['right'].pop('pitchReferenceSource')
    assert len(source_support_contact_conflicts(unbound_reference, full_sole_rows)) == 66

    # Unknown heel state never erases the observed positive forefoot contact.
    airborne_rows = [{**full_sole_rows[0], 'contactState': 'airborne'}]
    assert source_support_contact_conflicts(evidence, airborne_rows) == [
        {'side': 'right', 'rigSide': 'right', 'sourceTimeSec': 0.,
         'visualState': 'airborne', 'patchState': 'toe_only'}]

    # Keep existing hard disagreement behavior for other state pairs; the
    # unobserved-heel exception is deliberately limited to this one case.
    full_patch = deepcopy(evidence)
    full_patch['footPatchEvidence']['feet']['right']['states'] = ['full_sole'] * 66
    forefoot_rows = [
        {'side': 'right', 'contactState': 'forefoot', 'sourceTimeSec': index / 30.}
        for index in range(66)
    ]
    assert len(source_support_contact_conflicts(full_patch, forefoot_rows)) == 66


def test_unobserved_heel_preserves_reviewed_forefoot_interval_without_heel_plane():
    from copy import deepcopy
    from exercise_motion_pkg.body_support_observation import materialize_stationary_sole_support
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    observations, evidence, source_pose = _pose_and_observations()
    patch = classify_foot_contacts(observations, evidence, source_pose)
    evidence['footPatchEvidence'] = patch
    review = evidence['stationarySoleIntervalReview']['feet']['right']
    review['decisions'] = ['stationary_full_sole_ground'] * 11
    payload = {
        'jointNames': ['right_ankle', 'right_foot'],
        'groundContactMode': 'intermittent',
        'frames': [
            {'sourceTimeSec': index / 30., 'joints': {
                'right_ankle': [0., .1, 0.], 'right_foot': [0., 0., .1]}}
            for index in range(66)],
        'sourceFootSupportEvidence': evidence,
    }

    materialized = materialize_stationary_sole_support(payload)
    interval = [row for row in materialized.get('contacts', [])
                if row.get('supportKind') == 'observed_source_stance_interval']
    assert len(interval) == 1
    assert interval[0]['contactState'] == 'toe_only'
    assert not materialized.get('bodySupport', {}).get('soleContacts')
    pins = contact_mask(payload, payload['jointNames'], 66, support_evidence=materialized)
    assert pins[:, 1].all() and not pins[:, 0].any()
    assert materialized['bodySupportObservation']['observation']['rightFoot'] == 'stationary_forefoot'

    # Mixed review chunks still cannot promote the calibrated-looking chunks
    # into heel/ankle anchors when this patch has no heel reference.
    mixed = deepcopy(payload)
    mixed['sourceFootSupportEvidence']['stationarySoleIntervalReview']['feet']['right']['decisions'] = (
        ['stationary_full_sole_ground', 'stationary_forefoot_ground']
        + ['stationary_full_sole_ground'] * 9)
    mixed_materialized = materialize_stationary_sole_support(mixed)
    mixed_intervals = [row for row in mixed_materialized.get('contacts', [])
                       if row.get('supportKind') == 'observed_source_stance_interval']
    assert len(mixed_intervals) == 1 and mixed_intervals[0]['contactState'] == 'toe_only'
    assert not any(row.get('contactState') == 'full_sole'
                   and row.get('supportKind') == 'observed_source_stance_interval'
                   for row in mixed_materialized.get('contacts', []))

    # A calibrated toe_only state retains its prior contradiction behavior.
    for provenance, extra_state in [('relative_stance', None), (None, None),
                                    ('heel_unobserved', 'airborne')]:
        altered = deepcopy(payload)
        foot = altered['sourceFootSupportEvidence']['footPatchEvidence']['feet']['right']
        if provenance is None:
            foot.pop('pitchReferenceSource', None)
        else:
            foot['pitchReferenceSource'] = provenance
        if extra_state:
            foot['states'][20] = extra_state
        result = materialize_stationary_sole_support(altered)
        assert not any(row.get('supportKind') == 'observed_source_stance_interval'
                       for row in result.get('contacts', []))


def test_wrong_video_digest_returns_all_empty_review_masks():
    observations, evidence, _ = _pose_and_observations()
    evidence['sourceVideoSha256'] = 'different-video'

    masks = foot._reviewed_sole_mode_masks(evidence, observations, 'right')

    assert len(masks) == 5
    assert all(mask.shape == (66,) and not mask.any() for mask in masks)
