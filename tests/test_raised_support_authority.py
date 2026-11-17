from copy import deepcopy

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION, POLICY_VERSION, materialize_stationary_sole_support,
)
from exercise_motion_pkg.contact_constraints import (
    is_stationary_contact, observed_ground_contact_mask, observed_support_contact_mask,
    validated_support_contact_timeline_row,
)
from exercise_motion_pkg.controlled_motion import source_support_authority
from exercise_motion_pkg.support_geometry import pre_reconstruction_source_support_readiness


def _evidence():
    digest = 'a' * 64
    evidence = {'sourceVideoSha256': digest, 'bodySupportObservation': {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
        'sourceClock': 'video_frame_zero_seconds',
        'observation': {'leftFoot': 'moving', 'leftFootSurface': 'raised_surface'},
        'contactTimeline': {
            'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': digest,
            'status': 'observed', 'sourceClock': 'video_frame_zero_seconds', 'samples': [{
                'sampleId': f'left-{index}', 'side': 'left', 'contactState': 'forefoot',
                'surface': 'raised_surface', 'visible': True, 'sourceTrackStationary': True,
                'sourceTimeSec': float(index), 'sourceFrameIndex': index * 30,
                'sourceFps': 30., 'sourcePoseFrameIndex': index} for index in range(2)]}}}
    frames = [{'sourceTimeSec': float(index)} for index in range(2)]
    materialized = materialize_stationary_sole_support({
        'sourceFootSupportEvidence': evidence, 'frames': frames, 'groundContactMode': 'continuous'})
    return evidence, materialized, frames


def test_raised_support_defers_fit_validation_without_claiming_ground():
    source, evidence, frames = _evidence()
    assert observed_support_contact_mask(evidence, ['left_foot'], 2).sum() == 2
    assert observed_ground_contact_mask(evidence, ['left_foot'], 2).sum() == 0
    readiness = pre_reconstruction_source_support_readiness(
        source, source_frames=frames, ground_contact_mode='continuous')
    assert readiness['passed'] and readiness['requiredSourceSupportValidationDeferred']
    authority = source_support_authority({'groundContactMode': 'continuous'}, evidence, {})
    assert authority['required'] and authority['status'] == 'unresolved'
    assert authority['observedGroundAnchorSampleCount'] == 0
    assert 'sharedSupportPlaneY' not in evidence


def test_raised_anchor_requires_exact_join_and_current_source_identity():
    _, evidence, _ = _evidence()
    contact = evidence['supportContacts'][0]
    assert validated_support_contact_timeline_row(contact, evidence)
    for change in ({'contactTimelineSampleId': 'forged'}, {'sourceTimeSec': .25},
                   {'jointName': 'right_foot'}, {'reviewOnly': True},
                   {'supportKind': 'unobserved_model_contact'}):
        altered = {**contact, **change}
        assert validated_support_contact_timeline_row(altered, evidence) is None
    wrong_source = deepcopy(evidence)
    wrong_source['sourceVideoSha256'] = 'b' * 64
    assert validated_support_contact_timeline_row(contact, wrong_source) is None
    assert observed_support_contact_mask(wrong_source, ['left_foot'], 2).sum() == 0


def test_review_only_contact_never_becomes_stationary():
    assert not is_stationary_contact({
        'reviewOnly': True, 'contactMotion': 'stationary', 'surfaceKind': 'ground'})
