import copy
import hashlib
import json

import pytest

from exercise_motion_pkg.source_evidence import (
    source_reference_review_context,
    source_reference_review_context_sha256,
    source_reference_review_prompt_section,
    source_reference_visual_review_contract,
    source_requirements,
)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _mapping():
    source_context = _source_context()
    context_hash = hashlib.sha256(json.dumps(
        source_context, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode()).hexdigest()
    return {
        'sourceExerciseId': 'source-id',
        'sourceExerciseName': 'Pull-Up',
        'exerciseId': 'target-id',
        'exerciseName': 'Weighted Vest Pull-Up',
        'motionReferenceOnly': True,
        'allowedDifference': 'external_load_not_shown',
        'approvalAllowedDifference': 'External weighted vest need not be visible in the motion reference',
        'approvalAuthority': 'explicit_user_approval',
        'exportedExerciseUnchanged': True,
        'approvalUserAnswerPresent': True,
        'mappingSha256': _sha('mapping'),
        'approvalSha256': _sha('approval'),
        'motionContext': {'equipment': 'weighted vest'},
        'sourceMotionContext': source_context,
        'sourceMotionContextSha256': context_hash,
    }


def _source_context():
    return {
        'exerciseDefinition': {
            'definingAction': 'Hang from the pull-up bar, pull upward until the chin clears, then lower to hang.',
            'completionMode': 'return_to_start',
            'variantQualifiers': ['Strict pull-up without kipping.'],
            'requiredPhases': ['Pull upward from the hang', 'Lower back to the starting hang'],
            'bilateralExecution': {'arms': 'mirrored', 'legs': 'mirrored', 'torso': 'sagittal'},
        },
    }


def _contract():
    return {
        'exerciseName': 'Weighted Vest Pull-Up',
        'contractPolicyVersion': 39,
        'definingAction': 'Hang from the pull-up bar wearing a weighted vest, pull upward until the chin clears, then lower to hang.',
        'completionMode': 'return_to_start',
        'variantQualifiers': ['Strict pull-up with a weighted vest, without kipping.'],
        'requiredPhases': ['Pull upward from the hang', 'Lower back to the starting hang'],
        'bilateralExecution': {'arms': 'mirrored', 'legs': 'mirrored', 'torso': 'sagittal'},
        'motionContext': {'exerciseDefinition': {
            'bilateralExecution': {'arms': 'mirrored', 'legs': 'mirrored', 'torso': 'sagittal'},
        }},
    }


def test_verified_mapping_adds_scoped_prompt_context_without_mutating_target():
    mapping, target = _mapping(), _contract()
    original_mapping, original_target = copy.deepcopy(mapping), copy.deepcopy(target)
    context = source_reference_review_context(
        mapping, target_exercise_name='Weighted Vest Pull-Up', target_contract=target)
    prompt = source_reference_review_prompt_section(context)

    assert context['sourceExerciseName'] == 'Pull-Up'
    assert context['targetExerciseName'] == target['exerciseName']
    assert context['approvalAllowedDifference'] == mapping['approvalAllowedDifference']
    assert context['sourceMotionContextSha256'] == mapping['sourceMotionContextSha256']
    assert context['targetContractSha256'] == hashlib.sha256(
        json.dumps(target, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                   allow_nan=False).encode()).hexdigest()
    assert source_reference_review_context_sha256(context)
    assert 'absence of the weighted vest or other external load alone is not an identity mismatch' in prompt.casefold()
    assert 'unchanged target required phases in order' in prompt.casefold()
    assert 'A different action, grip, support setup, or other non-waived variant remains a rejection' in prompt
    assert 'do not change the exported target exercise' in prompt
    assert mapping == original_mapping
    assert target == original_target


@pytest.mark.parametrize('change', [
    {'allowedDifference': 'wrong_grip_allowed'},
    {'approvalAllowedDifference': ''},
    {'approvalAuthority': 'unverified'},
    {'exportedExerciseUnchanged': False},
    {'approvalUserAnswerPresent': False},
])
def test_unapproved_or_broader_mapping_fails_closed(change):
    mapping = {**_mapping(), **change}
    with pytest.raises(ValueError):
        source_reference_review_context(
            mapping, target_exercise_name='Weighted Vest Pull-Up', target_contract=_contract())


def test_mapping_for_other_target_is_not_applied():
    with pytest.raises(ValueError, match='does not target'):
        source_reference_review_context(
            _mapping(), target_exercise_name='Pull-Up', target_contract=_contract())


def test_prompt_context_is_optional_and_absence_has_no_waiver():
    assert source_reference_review_context(None, target_exercise_name='Pull-Up',
                                           target_contract=_contract()) is None
    assert source_reference_review_prompt_section(None) == ''


def test_source_requirement_view_uses_authenticated_source_action_and_variant_only():
    target = _contract()
    original = copy.deepcopy(target)
    context = source_reference_review_context(
        _mapping(), target_exercise_name='Weighted Vest Pull-Up', target_contract=target)
    equipment = [{'name': 'Pull-Up Station', 'role': 'unknown_required_equipment'}]

    requirements = source_requirements(target, equipment, source_reference_context=context)
    by_id = {row['id']: row for row in requirements}

    assert 'weighted vest' not in by_id['action']['description'].casefold()
    assert by_id['variant_1']['description'] == 'Strict pull-up without kipping.'
    assert [by_id['phase_1']['description'], by_id['phase_2']['description']] == target['requiredPhases']
    assert by_id['equipment_1']['description'] == json.dumps(equipment[0], sort_keys=True)
    assert by_id['completion']['description'].startswith('A complete execution including meaningful start')
    assert target == original


def test_mapped_source_candidate_prompt_uses_source_identity_without_vest_requirement():
    from exercise_motion_pkg.bake_and_rank import (
        DetectionWindow,
        SourceCutCandidate,
        build_source_cut_candidate_choice_prompt,
        two_scale_equipment_role_requirements,
    )

    target = _contract()
    target['motionContext']['primaryEquipment'] = {
        'id': 'vest-id', 'type': 'WEIGHTVEST', 'name': 'Weight Vest',
    }
    target['motionContext']['requiredAccessories'] = [
        {'id': 'station-id', 'type': 'ACCESSORY', 'name': 'Pull-Up Station'},
    ]
    target['motionContext']['exerciseDefinition'].update({
        'definingAction': 'Hang wearing a weighted vest and return to hang.',
        'variantQualifiers': ['Weighted vest required.'],
        'nonWaivedConstraint': 'Maintain a strict bar grip.',
    })
    original = copy.deepcopy(target)
    context = source_reference_review_context(
        _mapping(), target_exercise_name=target['exerciseName'], target_contract=target)
    visual_contract = source_reference_visual_review_contract(target, context)
    requirements = two_scale_equipment_role_requirements(
        visual_contract['exerciseName'], visual_contract)
    candidate = SourceCutCandidate(
        candidate_id='A', window=DetectionWindow(index=0, start_seconds=0.0, end_seconds=2.95),
        frame_paths=[],
    )

    prompt = build_source_cut_candidate_choice_prompt(
        exercise_name=target['exerciseName'], candidate_title=target['exerciseName'],
        candidate=candidate, exercise_motion_contract=target,
        source_reference_context=context,
    )
    normalized_prompt = prompt.casefold()

    assert visual_contract['exerciseName'] == 'Pull-Up'
    assert visual_contract['definingAction'] == _source_context()['exerciseDefinition']['definingAction']
    assert visual_contract['variantQualifiers'] == ['Strict pull-up without kipping.']
    assert visual_contract['motionContext']['exerciseDefinition']['definingAction'] == visual_contract['definingAction']
    assert visual_contract['motionContext']['exerciseDefinition']['variantQualifiers'] == visual_contract['variantQualifiers']
    assert visual_contract['motionContext']['exerciseDefinition']['nonWaivedConstraint'] == 'Maintain a strict bar grip.'
    assert visual_contract['requiredPhases'] == target['requiredPhases']
    assert visual_contract['completionMode'] == target['completionMode']
    assert 'primaryEquipment' not in visual_contract['motionContext']
    assert requirements == [{
        'name': 'Pull-Up Station', 'normalizedName': 'pull up station',
        'role': 'unknown_required_equipment',
    }]
    assert 'source exercise: pull-up' in normalized_prompt
    assert 'primary visible-motion identity: pull-up' in normalized_prompt
    assert 'unchanged export target: weighted vest pull-up' in normalized_prompt
    assert 'pull upward from the hang' in normalized_prompt
    assert 'lower back to the starting hang' in normalized_prompt
    assert 'pull-up station' in normalized_prompt
    assert 'absence of the weighted vest' in normalized_prompt
    assert 'source-authored visible action: hang from the pull-up bar' in normalized_prompt
    assert 'unchanged target required phases in order: ["pull upward from the hang", "lower back to the starting hang"]' in normalized_prompt
    assert 'wearing a weighted vest' not in normalized_prompt
    assert 'weighted vest must be visible' not in normalized_prompt
    assert 'every visible exercise-changing qualifier in the supplied primary exercise identity' in normalized_prompt
    assert target == original
    assert context['targetContractSha256'] == hashlib.sha256(
        json.dumps(original, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                   allow_nan=False).encode()).hexdigest()


def test_source_requirement_view_fails_closed_on_phase_or_source_digest_mismatch():
    target = _contract()
    mapping = _mapping()
    mapping['sourceMotionContext']['exerciseDefinition']['requiredPhases'] = ['different action']
    with pytest.raises(ValueError, match='mismatched sourceMotionContextSha256'):
        source_reference_review_context(
            mapping, target_exercise_name='Weighted Vest Pull-Up', target_contract=target)

    mapping = _mapping()
    context = source_reference_review_context(
        mapping, target_exercise_name='Weighted Vest Pull-Up', target_contract=target)
    context['sourceMotionContext']['exerciseDefinition']['requiredPhases'] = ['different action']
    with pytest.raises(ValueError, match='digest mismatch'):
        source_requirements(target, [], source_reference_context=context)


def test_nordic_external_load_is_omitted_but_setup_accessory_remains_required():
    source_context = {
        'exerciseDefinition': {
            'definingAction': 'Kneel with ankles anchored, lower through knee extension, then flex knees to return upright.',
            'completionMode': 'return_to_start',
            'variantQualifiers': ['Unassisted bodyweight Nordic curl, with anchored ankles and full movement range.'],
            'requiredPhases': [
                'Lower forward through knee extension while maintaining hip alignment',
                'Return to upright kneeling through knee flexion',
            ],
            'bilateralExecution': {'legs': 'mirrored'},
        },
    }
    target = {
        'exerciseName': 'Weighted Vest Nordic Curl',
        'contractPolicyVersion': 39,
        'definingAction': 'Kneel with ankles anchored and a weighted vest on, lower through knee extension, then return upright.',
        'completionMode': 'return_to_start',
        'variantQualifiers': ['Anchored Nordic curl wearing a weighted vest, without hand assistance.'],
        'requiredPhases': source_context['exerciseDefinition']['requiredPhases'],
        'bilateralExecution': {'legs': 'mirrored'},
        'motionContext': {
            'exerciseDefinition': {'bilateralExecution': {'legs': 'mirrored'}},
            'primaryEquipment': {'id': 'vest-id', 'name': 'Weight Vest', 'type': 'WEIGHTVEST'},
            'requiredAccessories': [{'id': 'setup-id', 'name': 'Nordic Curl Setup', 'type': 'ACCESSORY'}],
        },
    }
    mapping = _mapping()
    mapping.update({
        'sourceExerciseId': 'nordic-source-id',
        'sourceExerciseName': 'Nordic Curl',
        'exerciseId': 'nordic-target-id',
        'exerciseName': target['exerciseName'],
        'motionContext': target['motionContext'],
        'sourceMotionContext': source_context,
        'sourceMotionContextSha256': hashlib.sha256(json.dumps(
            source_context, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode()).hexdigest(),
    })
    normalized = source_reference_review_context(
        mapping, target_exercise_name=target['exerciseName'], target_contract=target)
    target_equipment = [
        {'name': 'Weight Vest', 'normalizedName': 'weight vest', 'role': 'active_implement'},
        {'name': 'Nordic Curl Setup', 'normalizedName': 'nordic curl setup',
         'role': 'unknown_required_equipment'},
    ]

    requirements = source_requirements(target, target_equipment, source_reference_context=normalized)
    by_id = {row['id']: row for row in requirements}

    assert 'weighted vest' not in by_id['action']['description'].casefold()
    assert all('vest' not in row['description'].casefold()
               for key, row in by_id.items() if key.startswith('variant_'))
    assert [row['name'] for row in target_equipment] == ['Weight Vest', 'Nordic Curl Setup']
    assert list(role['role'] for role in target_equipment) == ['active_implement', 'unknown_required_equipment']
    assert len([row for row in requirements if row['id'].startswith('equipment_')]) == 1
    assert by_id['equipment_1']['description'] == json.dumps(target_equipment[1], sort_keys=True)


def test_pullup_station_remains_required_under_load_waiver():
    target = _contract()
    mapping = _mapping()
    normalized = source_reference_review_context(
        mapping, target_exercise_name=target['exerciseName'], target_contract=target)
    roles = [{'name': 'Pull-Up Station', 'normalizedName': 'pull up station',
              'role': 'unknown_required_equipment'}]
    requirements = source_requirements(target, roles, source_reference_context=normalized)
    equipment = [row for row in requirements if row['id'].startswith('equipment_')]
    assert len(equipment) == 1
    assert 'Pull-Up Station' in equipment[0]['description']
