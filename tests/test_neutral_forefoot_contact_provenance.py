from copy import deepcopy

from exercise_motion_pkg.foot_contact_observation import (
    POLICY_VERSION as FOOT_PATCH_POLICY_VERSION,
    classify_foot_contacts,
)
from exercise_motion_pkg.contact_constraints import (
    _neutral_pitch_forefoot_patch_at_time,
)
from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    materialize_timed_visual_contact_points,
)
from exercise_motion_pkg.support_geometry import source_support_contact_conflicts


def _source_case(*, raised_heel=False, exact_fullsole_indices=(),
                 timeline_forefoot_indices=(6, 7, 8, 10)):
    digest = 'a' * 64
    count = 12
    fps = 30.0
    pose = {
        'sourceVideoSha256': digest,
        'sourceTimeOriginSec': 0.0,
        'imageWidth': 640,
        'imageHeight': 360,
        'frames': [],
    }
    observations = {
        'available': True,
        'source': 'fixture_exact_video_foot_landmarks',
        'sourceVideoSha256': digest,
        'imageWidth': 640,
        'imageHeight': 360,
        'fps': fps,
        'frames': [],
    }
    for index in range(count):
        timestamp = index / fps
        pose['frames'].append({
            'sourceTimeSec': timestamp,
            'joints': {'left_ankle': [.5, .5]},
        })
        heel_image = [.46, .5]
        heel_world = [0.0, 0.0, 0.0]
        if index >= 6:
            # Preserve neutral pitch while making the forefoot-only episode a
            # distinct yawed stance, so the test does not trigger the separate
            # neutral-calibration-indistinguishability path.
            heel_world = [.0268, 0.0, -.1]
        if raised_heel and 6 <= index < 9:
            heel_image = [.46, .45]
            heel_world = [.0268, -.07, -.1]
        points = {
            'left_ankle': ([.5, .5], [0.0, 0.0, 0.0]),
            'left_heel': (heel_image, heel_world),
            'left_toe': ([.56, .5], [.2, 0.0, 0.0]),
        }
        observations['frames'].append({
            'timeSeconds': timestamp,
            'joints': {
                name: {'image': image, 'world': world, 'confidence': .99}
                for name, (image, world) in points.items()
            },
        })

    timeline = {
        'schemaVersion': 1,
        'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
        'source': 'exact_source_visual_contact_timeline',
        'sourceVideoSha256': digest,
        'sourceClock': 'video_frame_zero_seconds',
        'status': 'observed',
        'requestSha256': 'fixture-request',
        'responseSha256': 'fixture-response',
        'samples': [{
                'sampleId': f'contact-left-pose-{index}',
                'sourceTimeSec': index / fps,
                'sourceFrameIndex': index,
                'sourcePoseFrameIndex': index,
                'sourceFps': fps,
                'side': 'left',
                'contactState': 'forefoot',
                'surface': 'ground',
                'visible': True,
                'sourceTrackStationary': True,
            } for index in timeline_forefoot_indices],
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySupportObservation': {
            'source': 'exact_source_visual_support_observation',
            'status': 'observed',
            'sourceVideoSha256': digest,
            'contactTimeline': timeline,
        },
        'stationarySoleIntervalReview': {
            'sourceVideoSha256': digest,
            'sourceFrameCount': count,
            'framesPerChunk': 6,
            'sourceFrameClockProof': {
                'receiptSha256': 'b' * 64,
                'outputVideoSha256': digest,
                'outputFrameCount': count,
                'outputFps': fps,
            },
            'feet': {'left': {
                'confirmed': True,
                'reviewedFrameCount': count,
                'sourcePoseTrackProof': {
                    'sourceVideoSha256': digest,
                    'sourcePoseFrameCount': count,
                    'stationary': True,
                },
                'decisions': [
                    'stationary_full_sole_ground',
                    'stationary_forefoot_ground',
                ],
                'frameObservations': [
                    {
                        'outputFrameIndex': index,
                        'sourceFrameIndex': 100 + index,
                        'sourcePoseFrameIndex': index,
                        'sourceTimeSec': index / fps,
                        'selectedSourceTimeSec': (100 + index) / fps,
                        'sourceFrameClockSha256': 'b' * 64,
                        'contactState': 'full_sole_ground',
                        'heelMotion': 'stationary',
                        'forefootMotion': 'stationary',
                    }
                    for index in exact_fullsole_indices
                ],
            }},
        },
        'footContactCandidates': [{
            'jointName': 'left_ankle',
            'supportKind': 'foot',
            'contactMotion': 'stationary',
            'sourceStartSample': 0,
            'sourceEndSample': count - 1,
            'sourceStartTimeSec': 0.0,
            'sourceEndTimeSec': (count - 1) / fps,
            'sourceTimeBasis': 'absolute_source_video',
        }],
    }
    patch = classify_foot_contacts(observations, evidence, pose)
    evidence['footPatchEvidence'] = patch
    return evidence, patch, observations, pose


def test_neutral_pitch_forefoot_provenance_joins_only_shared_forefoot_contact():
    evidence, patch, _, _ = _source_case()
    side = patch['feet']['left']
    assert patch['policyVersion'] == FOOT_PATCH_POLICY_VERSION
    assert side['pitchReferenceSource'] == 'relative_stance'
    assert side['states'][6:9] == ['toe_only'] * 3
    for index in (6, 7, 8):
        row = side['heelImageObservations'][index]
        assert row['heelStateEvidence'] == {
            'state': 'unknown',
            'reason': 'neutral_pitch_with_reviewed_forefoot_contact',
            'sourceFrameIndex': index,
            'sourceTimeSec': index / 30.0,
        }

    assert _neutral_pitch_forefoot_patch_at_time(evidence, 'left', 7 / 30.0)
    assert not _neutral_pitch_forefoot_patch_at_time(evidence, 'left', 7 / 30.0 + .01)
    assert not _neutral_pitch_forefoot_patch_at_time(evidence, 'right', 7 / 30.0)
    assert source_support_contact_conflicts(evidence, [{
        'side': 'left', 'contactState': 'full_sole', 'sourceTimeSec': 7 / 30.0,
    }]) == []

    materialize_timed_visual_contact_points(
        evidence, [{'sourceTimeSec': 10 / 30.0}], ['left_foot'],
        ground_contact_mode='continuous',
    )
    assert evidence['supportContacts'][0]['contactState'] == 'toe_only'


def test_actual_raised_heel_toe_only_remains_a_conflict():
    evidence, patch, _, _ = _source_case(raised_heel=True)
    side = patch['feet']['left']
    assert side['states'][6:9] == ['toe_only'] * 3
    assert all('heelStateEvidence' not in side['heelImageObservations'][index]
               for index in (6, 7, 8))
    assert not _neutral_pitch_forefoot_patch_at_time(evidence, 'left', 7 / 30.0)
    assert source_support_contact_conflicts(evidence, [{
        'side': 'left', 'contactState': 'full_sole', 'sourceTimeSec': 7 / 30.0,
    }]) == [{
        'side': 'left', 'rigSide': 'left', 'sourceTimeSec': 7 / 30.0,
        'visualState': 'full_sole', 'patchState': 'toe_only',
    }]


def test_review_only_forefoot_row_does_not_override_same_time_fullsole_patch():
    digest = 'a' * 64
    evidence = {
        'sourceVideoSha256': digest,
        'footPatchEvidence': {
            'sourceVideoSha256': digest,
            'sourceTimesSec': [1.8018, 2.3356666666666666],
            'feet': {'left': {'states': ['full_sole', 'full_sole']}},
        },
        'bodySupportObservation': {'sourceVideoSha256': digest},
    }
    rows = [
        {
            'side': 'left', 'contactState': 'forefoot', 'sourceTimeSec': 1.8018,
            'visible': True, 'sourceTrackStationary': True,
        },
        {
            'side': 'left', 'contactState': 'forefoot', 'sourceTimeSec': 2.3356666666666666,
            'visible': True, 'sourceTrackStationary': False, 'reviewOnly': True,
        },
    ]

    assert source_support_contact_conflicts(evidence, rows) == [{
        'side': 'left', 'rigSide': 'left', 'sourceTimeSec': 1.8018,
        'visualState': 'forefoot', 'patchState': 'full_sole',
    }]


def test_exact_clock_bound_fullsole_rows_override_coarse_forefoot_chunk():
    evidence, patch, observations, pose = _source_case(
        exact_fullsole_indices=(6, 7, 8), timeline_forefoot_indices=(10,))
    side = patch['feet']['left']
    assert side['states'][6:9] == ['full_sole'] * 3
    assert all('heelStateEvidence' not in side['heelImageObservations'][index]
               for index in (6, 7, 8))
    assert source_support_contact_conflicts(evidence, [{
        'side': 'left', 'contactState': 'full_sole', 'sourceTimeSec': 7 / 30.0,
    }]) == []

    stale = deepcopy(evidence)
    stale['stationarySoleIntervalReview']['feet']['left']['frameObservations'][1][
        'sourceFrameClockSha256'] = 'c' * 64
    stale_patch = classify_foot_contacts(observations, stale, pose)
    assert stale_patch['feet']['left']['states'][7] != 'full_sole'


def test_conflicting_exact_sole_reviews_retain_forefoot_without_a_winner():
    from exercise_motion_pkg.foot_contact_observation import _reviewed_sole_mode_masks

    evidence, _, observations, pose = _source_case(
        exact_fullsole_indices=(7,), timeline_forefoot_indices=(7,))
    conflicts = []
    neutral, contact, forefoot, heel_only, _, exact_fullsole = _reviewed_sole_mode_masks(
        evidence, observations, 'left', pose, conflicts=conflicts)

    assert not exact_fullsole[7]
    assert not neutral[7] and contact[7] and forefoot[7] and not heel_only[7]
    assert conflicts == [{
        'side': 'left', 'frameIndex': 7, 'sourceTimeSec': 7 / 30.0,
        'atlasContactState': 'full_sole', 'bodyContactState': 'forefoot',
        'bodyReviewOnly': False, 'reason': 'conflicting_exact_sole_reviews',
    }]
    assert classify_foot_contacts(observations, evidence, pose)['feet']['left']['states'][7] == 'toe_only'


def test_review_only_sole_row_cannot_override_exact_atlas_review():
    from exercise_motion_pkg.foot_contact_observation import _reviewed_sole_mode_masks

    evidence, _, observations, pose = _source_case(
        exact_fullsole_indices=(7,), timeline_forefoot_indices=(7,))
    sample = evidence['bodySupportObservation']['contactTimeline']['samples'][0]
    sample['reviewOnly'] = True
    sample['sourceTrackStationary'] = False
    conflicts = []
    neutral, contact, forefoot, _, _, exact_fullsole = _reviewed_sole_mode_masks(
        evidence, observations, 'left', pose, conflicts=conflicts)

    assert exact_fullsole[7] and neutral[7] and not forefoot[7]
    assert conflicts == [{
        'side': 'left', 'frameIndex': 7, 'sourceTimeSec': 7 / 30.0,
        'atlasContactState': 'full_sole', 'bodyContactState': 'forefoot',
        'bodyReviewOnly': True,
        'reason': 'review_only_row_does_not_override_exact_sole_review',
    }]
