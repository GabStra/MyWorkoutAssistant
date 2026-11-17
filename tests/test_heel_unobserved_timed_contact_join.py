from copy import deepcopy

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    materialize_timed_visual_contact_points,
    validated_body_support_contact_timeline,
)
from exercise_motion_pkg.contact_constraints import validated_support_contact_timeline_row
from exercise_motion_pkg.support_geometry import source_support_contact_conflicts


def _evidence(*, pitch_reference='heel_unobserved', patch_digest='a' * 64,
              timeline_state='full_sole'):
    digest = 'a' * 64
    observed = {
        'source': 'exact_source_visual_support_observation',
        'status': 'observed',
        'sourceVideoSha256': digest,
        'contactTimeline': {
            'schemaVersion': 1,
            'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'source': 'exact_source_visual_contact_timeline',
            'sourceVideoSha256': digest,
            'sourceClock': 'video_frame_zero_seconds',
            'status': 'observed',
            'requestSha256': 'request',
            'responseSha256': 'response',
            'samples': [{
                'sampleId': 'contact-left-pose-18',
                'sourceTimeSec': .6,
                'sourceFrameIndex': 18,
                'sourceFps': 30.,
                'sourcePoseFrameIndex': 18,
                'side': 'left',
                'contactState': timeline_state,
                'surface': 'ground' if timeline_state != 'unknown' else 'unknown',
                'visible': True,
                'sourceTrackStationary': True,
            }],
        },
    }
    return {
        'sourceVideoSha256': digest,
        'bodySupportObservation': observed,
        'footPatchEvidence': {
            'sourceVideoSha256': patch_digest,
            'feet': {'left': {
                'states': ['toe_only'],
                'pitchReferenceSource': pitch_reference,
            }},
        },
    }


def test_exact_fullsole_row_joins_only_its_heel_unobserved_toe_constraint():
    evidence = _evidence()
    raw_rows = validated_body_support_contact_timeline(evidence['bodySupportObservation'])
    assert raw_rows and raw_rows[0]['contactState'] == 'full_sole'

    frames = [{'sourceTimeSec': .6}]
    materialize_timed_visual_contact_points(
        evidence, frames, ['left_foot'], ground_contact_mode='continuous')
    assert len(evidence['supportContacts']) == 1
    contact = evidence['supportContacts'][0]
    assert contact['contactState'] == 'toe_only'
    assert contact['contactTimelineSampleId'] == 'contact-left-pose-18'
    assert contact['contactTimelineSourceTimeSec'] == .6
    assert contact['sourceTimeSec'] == .6
    joined = validated_support_contact_timeline_row(contact, evidence)
    assert joined and joined['contactState'] == 'full_sole'

    # The exact point remains bound to its sample, time, side and same-video
    # heel-uncertainty evidence. A full-sole constraint would upgrade the claim.
    for change in (
        {'contactState': 'full_sole'},
        {'contactTimelineSampleId': 'contact-left-pose-17'},
        {'sourceTimeSec': .61},
        {'contactTimelineSourceTimeSec': .61},
        {'jointName': 'right_foot'},
    ):
        assert validated_support_contact_timeline_row(
            {**contact, **change}, evidence) is None

    no_heel_proof = deepcopy(evidence)
    no_heel_proof['footPatchEvidence']['feet']['left'].pop('pitchReferenceSource')
    assert validated_support_contact_timeline_row(contact, no_heel_proof) is None
    wrong_patch_video = deepcopy(evidence)
    wrong_patch_video['footPatchEvidence']['sourceVideoSha256'] = 'b' * 64
    assert validated_support_contact_timeline_row(contact, wrong_patch_video) is None

    uncalibrated_fullsole = _evidence(pitch_reference=None)
    materialize_timed_visual_contact_points(
        uncalibrated_fullsole, frames, ['left_foot'], ground_contact_mode='continuous')
    uncalibrated_contact = uncalibrated_fullsole['supportContacts'][0]
    assert uncalibrated_contact['contactState'] == 'full_sole'
    assert validated_support_contact_timeline_row(
        uncalibrated_contact, uncalibrated_fullsole)

    # A source forefoot row can only authorize toe-only; unknown is not contact.
    forefoot = _evidence(timeline_state='forefoot')
    materialize_timed_visual_contact_points(
        forefoot, frames, ['left_foot'], ground_contact_mode='continuous')
    forefoot_contact = forefoot['supportContacts'][0]
    assert forefoot_contact['contactState'] == 'toe_only'
    assert validated_support_contact_timeline_row(
        {**forefoot_contact, 'contactState': 'full_sole'}, forefoot) is None

    unknown = _evidence(timeline_state='unknown')
    unknown_contact = {**contact, 'contactTimelineSourceVideoSha256': 'a' * 64}
    assert validated_support_contact_timeline_row(unknown_contact, unknown) is None
    no_contact = _evidence(timeline_state='no_contact')
    assert validated_body_support_contact_timeline(no_contact['bodySupportObservation']) is None
    assert validated_support_contact_timeline_row(unknown_contact, no_contact) is None


def test_indistinguishable_neutral_conflict_only_joins_exact_forefoot_subset():
    evidence = _evidence(pitch_reference='relative_stance')
    digest = evidence['sourceVideoSha256']
    patch = evidence['footPatchEvidence']
    patch.update({
        'sourcePoseVideoSha256': digest,
        'sourceTimeBasis': 'absolute_source_video',
        'sourceFrameCount': 2,
        'sourcePoseFrameCount': 2,
        'sourceTimesSec': [.6, .7],
        'neutralCalibrationConflicts': [{
            'side': 'left',
            'stationarySpanStartFrame': 0,
            'stationarySpanEndFrame': 1,
            'conflictingNeutralFrameRanges': [{'startFrame': 0, 'endFrame': 0}],
            'positiveMode': 'forefoot',
            'indistinguishable': True,
            'reason': 'stationary_full_sole_and_forefoot_geometry_indistinguishable',
        }],
    })
    patch['feet']['left']['states'] = ['toe_only', 'toe_only']
    timeline = evidence['bodySupportObservation']['contactTimeline']
    timeline['sourceClock'] = 'video_frame_zero_seconds'
    timeline['samples'][0].update({'sourceFrameIndex': 18, 'sourcePoseFrameIndex': 18})
    timeline['samples'].append({
        **timeline['samples'][0],
        'sampleId': 'contact-left-pose-21',
        'sourceTimeSec': .7,
        'sourceFrameIndex': 21,
        'sourcePoseFrameIndex': 21,
    })

    frames = [{'sourceTimeSec': .6}, {'sourceTimeSec': .7}]
    materialize_timed_visual_contact_points(
        evidence, frames, ['left_foot'], ground_contact_mode='continuous')
    first, second = evidence['supportContacts']
    assert first['contactState'] == 'toe_only'
    assert validated_support_contact_timeline_row(first, evidence) is not None
    # The same full-sole observation is not downgraded at an adjacent time
    # outside the explicit ambiguity range.
    assert second['contactState'] == 'full_sole'
    assert validated_support_contact_timeline_row(second, evidence) is not None
    assert source_support_contact_conflicts(evidence, [
        {'side': 'left', 'contactState': 'full_sole', 'sourceTimeSec': .6},
        {'side': 'left', 'contactState': 'full_sole', 'sourceTimeSec': .7},
    ]) == [{
        'side': 'left', 'rigSide': 'left', 'sourceTimeSec': .7,
        'visualState': 'full_sole', 'patchState': 'toe_only',
    }]

    # The ambiguous source row cannot be promoted to a heel/full-sole anchor.
    assert validated_support_contact_timeline_row(
        {**first, 'contactState': 'full_sole'}, evidence) is None

    stale = deepcopy(evidence)
    stale['footPatchEvidence']['sourceVideoSha256'] = 'b' * 64
    materialize_timed_visual_contact_points(
        stale, frames, ['left_foot'], ground_contact_mode='continuous')
    assert stale['supportContacts'][0]['contactState'] == 'full_sole'
