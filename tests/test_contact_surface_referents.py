from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
    _contact_surface_referent_guidance,
    _nonfoot_contact_timeline_prompt,
    validated_body_support_answer,
    validated_body_support_contact_timeline,
)


def test_nonfoot_prompt_treats_floor_as_a_support_category_with_a_covering():
    prompt = _nonfoot_contact_timeline_prompt({
        'side': 'right',
        'contactRegion': 'knee',
        'jointName': 'right_knee',
        'expectedSurface': 'floor',
    })

    assert 'candidate surface category floor' in prompt
    assert 'visible mat or pad covering it' in prompt
    assert 'without claiming bare-floor contact or a known floor height' in prompt
    assert 'no_contact for visible separation' in prompt
    assert 'unresolved when the interface is hidden or ambiguous' in prompt
    assert 'joint-center position, proximity and stationarity are not contact evidence' in prompt
    assert 'right_knee marker is an anatomical locator, not a contact point' in prompt


def test_coarse_and_timed_prompts_share_surface_referents_without_geometry_claims():
    guidance = _contact_surface_referent_guidance()

    assert 'floor means the floor-level support face' in guidance
    assert 'bench means its visible support face, including upholstery or a pad' in guidance
    assert 'fixed_bar means the fixed bar or a visible pad, roller, or restraint attached to it' in guidance
    assert 'does not establish' in guidance


def test_old_contact_timeline_receipt_is_invalidated_by_referent_policy():
    timeline = {
        'schemaVersion': 1,
        'policyVersion': 7,
        'source': 'exact_source_visual_contact_timeline',
        'sourceVideoSha256': 'source-hash',
        'sourceClock': 'video_frame_zero_seconds',
        'status': 'observed',
        'samples': [],
    }

    assert CONTACT_TIMELINE_POLICY_VERSION == 8
    assert validated_body_support_contact_timeline(
        timeline, expected_video_sha256='source-hash') is None
    timeline['policyVersion'] = CONTACT_TIMELINE_POLICY_VERSION
    assert validated_body_support_contact_timeline(
        timeline, expected_video_sha256='source-hash') == []


def test_old_coarse_floor_observation_is_invalidated_by_referent_policy():
    observation = {
        'status': 'observed',
        'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': 'source-hash',
        'policyVersion': 6,
        'observation': {
            'rightKnee': 'stationary_support',
            'rightKneeContactSurface': 'floor',
        },
    }

    assert POLICY_VERSION == 7
    assert validated_body_support_answer(observation) is None
    observation['policyVersion'] = POLICY_VERSION
    assert validated_body_support_answer(observation) == observation['observation']
