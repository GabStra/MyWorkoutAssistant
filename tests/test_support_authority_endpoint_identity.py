from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
)
from exercise_motion_pkg.controlled_motion import source_support_authority


def support_evidence(*, bound=True, include_timeline=True):
    source_digest = 'selected-source-sha256'
    observation_digest = source_digest if bound else 'different-source-sha256'
    observation = {
        'status': 'observed',
        'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': observation_digest,
        'policyVersion': POLICY_VERSION,
        'observation': {
            'leftHand': 'stationary_support',
            'rightHand': 'stationary_support',
            'leftHandContactSurface': 'fixed_bar',
            'rightHandContactSurface': 'fixed_bar',
            'handsSameHorizontalSurface': True,
        },
    }
    if include_timeline:
        observation['contactTimeline'] = {
            'schemaVersion': 1,
            'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'source': 'exact_source_visual_contact_timeline',
            'sourceVideoSha256': observation_digest,
            'sourceClock': 'video_frame_zero_seconds',
            'status': 'observed',
            'samples': [
                {
                    'sampleId': f'{side}-wrist-{frame}',
                    'sourceTimeSec': frame / 30.,
                    'sourceFrameIndex': frame,
                    'sourceFps': 30.,
                    'sourcePoseFrameIndex': frame,
                    'side': side,
                    'landmark': 'joint',
                    'jointName': f'{side}_wrist',
                    'contactState': 'direct_contact',
                    'surface': 'fixed_bar',
                    'visible': True,
                    'sourceTrackStationary': True,
                }
                for side in ('left', 'right') for frame in (0, 30)
            ],
        }
    return {
        'sourceVideoSha256': source_digest,
        'bodySupportObservation': observation,
        'bodySupport': {
            'required': True,
            'status': 'confirmed',
            'stationaryJoints': ['left_hand', 'right_hand'],
        },
    }


def test_materialized_hand_anchors_still_fail_without_bound_observation():
    for evidence in (
            support_evidence(bound=False),
            support_evidence(include_timeline=False)):
        result = source_support_authority(
            {'groundContactMode': 'none'}, evidence, {})

        assert result['status'] == 'unresolved'
        assert result['passed'] is False
        assert result['bodySupportConfirmed'] is False
        assert 'observed_stationary_support_anchor_unavailable' in (
            result['unresolvedReasons'])
