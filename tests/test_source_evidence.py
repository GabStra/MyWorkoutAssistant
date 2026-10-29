import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_evidence import (
    MAX_OBSERVED_OBJECT_COUNT, POLICY_VERSION, aggregate_evidence, evidence_inventory,
    evidence_response_token_budget, evidence_schema, evidence_prompt, correct_incomplete_evidence,
    permits_cyclic_phase_order, return_cycle_evidence_choices, source_requirements,
    cycle_semantic_question, resolve_cycle_semantics,
    resolve_semantic_evidence,
)


def contract():
    return {'definingAction': 'Extend hips and knees, then bend and raise elbows outward without a front-rack catch.',
            'completionMode': 'distinct_end_state', 'actionDefinitionAuthority': 'structured_definition',
            'actionDefinitionStatus': 'defined', 'variantQualifiers': [],
            'motionContext': {'primaryEquipment': {'name': 'Barbell', 'type': 'BARBELL'}}}


def frames():
    return [{'id': f'{group}:{index}', 'sampling': group, 'timestampSeconds': index - 1}
            for group in ('uniform', 'motion') for index in (1, 2, 3)]


def supported(requirements, inventory):
    uniform = [f['id'] for f in inventory if f['sampling'] == 'uniform']
    motion = [f['id'] for f in inventory if f['sampling'] == 'motion']
    observations = []
    for requirement in requirements:
        rid = requirement['id']
        if rid == 'clean_interval':
            ids = uniform
        elif rid in {'action', 'completion'}:
            ids = motion[:requirement.get('minimumDistinctFrameCount', 2)]
        elif rid.startswith('phase_'):
            index = int(rid.split('_', 1)[1]) - 1
            ids = motion[index:index + 1]
        else:
            ids = motion[:1]
        observations.append({'requirementId': rid, 'verdict': 'supported',
                             'evidenceFrameIds': ids,
                             **({'observedObjectCount': requirement['minimumObjectCount']}
                                if 'minimumObjectCount' in requirement else {})})
    return {'observations': observations}


def semantic_reply(payload, requirements):
    labels = {row['id']: row['description'] for row in requirements}
    observations = {}
    for row in payload['observations']:
        label = labels[row['requirementId']]
        observations.setdefault(label, {**{key: value for key, value in row.items() if key != 'requirementId'},
                                        'requirement': label})
    return {'observations': list(observations.values())}


@pytest.mark.parametrize('fault', [None, 'mixed_ids', 'contradicted', 'wrong_requirement'])
def test_uniform_coverage_choice_is_expanded_by_code_only_for_explicit_supported_claim(fault):
    requirements, inventory = source_requirements(contract(), []), frames()
    payload = semantic_reply(supported(requirements, inventory), requirements)
    row = payload['observations'][-1] if fault != 'wrong_requirement' else payload['observations'][0]
    row['evidenceFrameIds'] = ['all_uniform_samples']
    if fault == 'mixed_ids': row['evidenceFrameIds'].append('uniform:1')
    if fault == 'contradicted': row['verdict'] = 'contradicted'
    normalized = resolve_semantic_evidence(payload, requirements, inventory)
    result = aggregate_evidence(normalized, requirements, inventory)
    assert result['passed'] is (fault is None)
    if fault is None:
        assert result['observations'][-1]['evidenceFrameIds'] == ['uniform:1', 'uniform:2', 'uniform:3']


@pytest.mark.parametrize('complete', [True, False])
def test_uniform_coverage_gets_one_targeted_correction(complete):
    requirements, inventory = source_requirements(contract(), []), frames()
    payload = supported(requirements, inventory)
    payload['observations'][-1]['evidenceFrameIds'] = ['uniform:1']
    calls = []

    def request(targeted, frames, prompt, schema):
        calls.append([row['id'] for row in targeted])
        reply = supported(targeted, frames)
        if not complete:
            reply['observations'][0]['evidenceFrameIds'] = ['uniform:1']
        return semantic_reply(reply, targeted)

    merged, receipt = correct_incomplete_evidence(payload, requirements, inventory, request)
    assert calls == [['clean_interval']]
    assert receipt['attempted'] is True
    assert aggregate_evidence(merged, requirements, inventory)['passed'] is complete
    assert merged['observations'][:-1] == payload['observations'][:-1]


@pytest.mark.parametrize('mode', ['stable_hold', 'active_travel'])
def test_continuous_action_does_not_promote_proposed_entry_exit_phases(mode):
    target = contract()
    target.update(completionMode=mode, requiredPhases=['Enter position', 'Finish countdown'],
                  requiredPhasesAuthority='contract_proposal',
                  motionContext={'exerciseDefinition': {'definingAction': 'Sustain the prescribed action'}})
    assert not any(row['id'].startswith('phase_') for row in source_requirements(target, []))
    target['motionContext']['exerciseDefinition']['requiredPhases'] = ['Explicit first action', 'Explicit second action']
    assert [row['description'] for row in source_requirements(target, [])
            if row['id'].startswith('phase_')] == ['Explicit first action', 'Explicit second action']
    target['requiredPhasesAuthority'] = 'trusted'
    assert [row['description'] for row in source_requirements(target, [])
            if row['id'].startswith('phase_')] == target['requiredPhases']


@pytest.mark.parametrize('fault', ['unknown_requirement', 'duplicate', 'missing', 'bad_frame',
                                 'string_boolean', 'empty', 'single_pose', 'coverage', 'prose'])
def test_structured_source_invalid_evidence_stays_unresolved(fault):
    requirements = source_requirements(contract(), [])
    inventory = frames()
    payload = supported(requirements, inventory)
    row = payload['observations'][0]
    if fault == 'unknown_requirement': row['requirementId'] = 'must_start_on_floor'
    elif fault == 'duplicate': payload['observations'].append(dict(row))
    elif fault == 'missing': payload['observations'].pop()
    elif fault == 'bad_frame': row['evidenceFrameIds'] = ['motion:39']
    elif fault == 'string_boolean': row['verdict'] = 'true'
    elif fault == 'empty': row['evidenceFrameIds'] = []
    elif fault == 'single_pose': row['evidenceFrameIds'] = ['uniform:1', 'motion:1']
    elif fault == 'coverage': payload['observations'][-1]['evidenceFrameIds'] = ['uniform:1']
    elif fault == 'prose': payload['observedExercise'] = 'deadlift'
    result = aggregate_evidence(payload, requirements, inventory)
    assert result['passed'] is False
    assert result['reviewStatus'] == 'incomplete'


def test_structured_source_grounded_contradiction_is_rejected_and_uncertainty_is_not():
    requirements, inventory = source_requirements(contract(), []), frames()
    payload = supported(requirements, inventory)
    assert aggregate_evidence(payload, requirements, inventory)['passed'] is True
    payload['observations'][0].update(verdict='contradicted', evidenceFrameIds=['motion:2'])
    assert aggregate_evidence(payload, requirements, inventory)['reviewStatus'] == 'rejected'
    payload['observations'][0].update(verdict='unresolved', evidenceFrameIds=[])
    assert aggregate_evidence(payload, requirements, inventory)['reviewStatus'] == 'incomplete'


def test_structured_source_approved_phases_are_checked_in_order():
    target = {**contract(), 'requiredPhases': ['extend legs', 'bend elbows']}
    requirements, inventory = source_requirements(target, []), frames()
    payload = supported(requirements, inventory)
    phases = [r for r in payload['observations'] if r['requirementId'].startswith('phase_')]
    phases[0]['evidenceFrameIds'], phases[1]['evidenceFrameIds'] = ['motion:2'], ['motion:1']
    assert 'phase_order_not_established' in aggregate_evidence(payload, requirements, inventory)['errors']
    phases[1]['evidenceFrameIds'] = ['motion:3']
    assert aggregate_evidence(payload, requirements, inventory)['passed'] is True


def test_return_to_start_accepts_one_cycle_rotation_but_not_reordering_or_anchored_rotation():
    target = {**contract(), 'movementType': 'repetition', 'completionMode': 'return_to_start',
              'requiredPhases': ['lower', 'rise']}
    requirements = source_requirements(target, [])
    inventory = frames()
    payload = supported(requirements, inventory)
    phases = [row for row in payload['observations'] if row['requirementId'].startswith('phase_')]
    phases[0]['evidenceFrameIds'] = ['motion:3']
    phases[1]['evidenceFrameIds'] = ['motion:1']
    assert aggregate_evidence(payload, requirements, inventory)['reviewStatus'] == 'incomplete'
    assert aggregate_evidence(payload, requirements, inventory,
        allow_cyclic_phase_order=True)['passed'] is True

    # A three-phase non-rotation must remain unresolved even though each
    # individual phase has a distinct timestamp.
    target3 = {**target, 'requiredPhases': ['lower', 'pause', 'rise']}
    requirements3 = source_requirements(target3, [])
    payload3 = supported(requirements3, inventory)
    by_id = {row['requirementId']: row for row in payload3['observations']}
    by_id['phase_1']['evidenceFrameIds'] = ['motion:1']
    by_id['phase_2']['evidenceFrameIds'] = ['motion:3']
    by_id['phase_3']['evidenceFrameIds'] = ['motion:2']
    assert 'phase_order_not_established' in aggregate_evidence(payload3, requirements3, inventory,
        allow_cyclic_phase_order=True)['errors']

    assert permits_cyclic_phase_order(target) is True
    assert permits_cyclic_phase_order({**target, 'startPoseConstraints': {'posture': 'standing'}}) is True
    assert permits_cyclic_phase_order({**target, 'source': 'user', 'validStartState': 'standing'}) is False


def test_retained_squat_incomplete_evidence_gets_one_targeted_correction_and_preserves_others():
    target = {**contract(), 'movementType': 'repetition', 'completionMode': 'return_to_start',
              'definingAction': 'Lower by bending the hips and knees, then rise to standing.',
              'requiredPhases': ['lower by bending the hips and knees', 'rise to standing']}
    requirements = source_requirements(target, [
        {'normalizedName': 'barbell', 'role': 'active_implement', 'minimumObjectCount': 1},
    ])
    inventory = [
        {'id': f'{group}:{index}', 'sampling': group,
         'timestampSeconds': (index - 1) * 0.125}
        for group, count in (('uniform', 16), ('motion', 28))
        for index in range(1, count + 1)
    ]
    initial = supported(requirements, inventory)
    by_id = {row['requirementId']: row for row in initial['observations']}
    by_id['completion']['evidenceFrameIds'] = ['uniform:1', 'uniform:16']
    by_id['phase_1']['evidenceFrameIds'] = ['uniform:1', 'uniform:16']
    by_id['phase_2']['evidenceFrameIds'] = ['uniform:1', 'uniform:16']
    first = aggregate_evidence(initial, requirements, inventory, allow_cyclic_phase_order=True)
    assert first['reviewStatus'] == 'incomplete'
    assert first['errors'] == ['sequence_evidence_missing', 'phase_order_not_established']
    assert first['correctionRequirementIds'] == ['completion', 'phase_1', 'phase_2']

    correction = {'observations': [
        {'requirementId': 'completion', 'verdict': 'supported',
         'evidenceFrameIds': ['uniform:1', 'motion:8', 'uniform:16']},
        # This cut begins at the bottom: rise is seen before the descent phase.
        {'requirementId': 'phase_1', 'verdict': 'supported',
         'evidenceFrameIds': ['motion:18', 'motion:28']},
        {'requirementId': 'phase_2', 'verdict': 'supported',
         'evidenceFrameIds': ['motion:6', 'motion:8']},
    ]}
    calls = []
    def request(targeted, choices, prompt, schema):
        calls.append((targeted, choices, prompt, schema))
        return semantic_reply(correction, targeted)
    merged, receipt = correct_incomplete_evidence(initial, requirements, inventory, request,
        allow_cyclic_phase_order=True)
    assert len(calls) == 1
    assert [item['id'] for item in calls[0][0]] == ['completion', 'phase_1', 'phase_2']
    assert calls[0][2].find('one cyclic rotation') >= 0
    rows = {row['requirementId']: row for row in merged['observations']}
    assert rows['action'] == by_id['action']
    assert rows['equipment_1'] == by_id['equipment_1']
    assert rows['clean_interval'] == by_id['clean_interval']
    assert receipt['attempted'] is True
    assert receipt['after']['passed'] is True
    # The production cache's retained-approval path reparses rawResponse. A
    # canonical merged response must round-trip through that same extractor.
    retained_raw = json.dumps(merged, separators=(',', ':'))
    reparsed = bake.extract_json_object(retained_raw)
    assert aggregate_evidence(reparsed, requirements, inventory,
        allow_cyclic_phase_order=True)['passed'] is True


def test_code_owned_cycle_choices_prevent_three_bottom_frames_from_proving_completion():
    target = {**contract(), 'completionMode': 'return_to_start',
              'requiredPhases': ['lower', 'rise']}
    requirements = source_requirements(target, [])
    inventory = [
        {'id': 'uniform:1', 'sampling': 'uniform', 'timestampSeconds': 0.0},
        {'id': 'motion:9', 'sampling': 'motion', 'timestampSeconds': 1.0},
        {'id': 'uniform:16', 'sampling': 'uniform', 'timestampSeconds': 2.0},
        {'id': 'motion:12', 'sampling': 'motion', 'timestampSeconds': 1.5},
    ]
    pose = {'sourcePoseSampleBoundaryToleranceSeconds': 0.25, 'frames': [
        {'sourceTimeSec': 0.0}, {'sourceTimeSec': 0.5}, {'sourceTimeSec': 1.0},
        {'sourceTimeSec': 1.5}, {'sourceTimeSec': 2.0},
    ]}
    metrics = {'required': True, 'passed': True, 'hasCompleteMajorCycle': True,
        'hasSingleMajorCycle': True, 'phaseSignalEvidence': {'resolved': True},
        'majorPhaseSequence': ['low', 'high', 'low'], 'sampleCount': 5,
        'maxFrameIndex': 2, 'minFrameIndex': 4, 'edgeMarginFrameCount': 1}
    choices = return_cycle_evidence_choices(metrics, pose, inventory)
    assert choices['roleFrameIds'] == {
        'start': 'uniform:1', 'excursion': 'motion:9', 'return': 'uniform:16'}

    payload = supported(requirements, inventory)
    rows = {row['requirementId']: row for row in payload['observations']}
    rows['completion']['evidenceFrameIds'] = ['uniform:1', 'motion:12', 'uniform:16']
    rows['phase_1']['evidenceFrameIds'] = ['uniform:1', 'uniform:16']
    rows['phase_2']['evidenceFrameIds'] = ['uniform:1', 'uniform:16']
    result = aggregate_evidence(payload, requirements, inventory,
        allow_cyclic_phase_order=True, cycle_choices=choices)
    assert result['reviewStatus'] == 'incomplete'
    assert 'cycle_role_evidence_missing' in result['errors']

    # The correction lets the model assign semantics, not invent numeric refs.
    merged, receipt = correct_incomplete_evidence(payload, requirements, inventory,
        lambda targeted, allowed, prompt, schema: {
            'earlier_interval_action': 'rise',
            'later_interval_action': 'lower',
        }, allow_cyclic_phase_order=True, cycle_choices=choices)
    assert receipt['after']['passed'] is True
    merged_rows = {row['requirementId']: row for row in merged['observations']}
    assert merged_rows['completion']['evidenceFrameIds'] == [
        'uniform:1', 'motion:9', 'uniform:16']
    assert merged_rows['phase_1']['evidenceFrameIds'] == ['motion:9', 'uniform:16']
    assert merged_rows['phase_2']['evidenceFrameIds'] == ['uniform:1', 'motion:9']

    sparse = return_cycle_evidence_choices(metrics, pose, [
        {'id': 'uniform:1', 'sampling': 'uniform', 'timestampSeconds': 0.0},
        {'id': 'motion:1', 'sampling': 'motion', 'timestampSeconds': 0.25},
        {'id': 'uniform:16', 'sampling': 'uniform', 'timestampSeconds': 2.0},
    ])
    assert sparse is None


def test_structurally_invalid_initial_evidence_is_not_salvaged_by_targeted_correction():
    requirements = source_requirements({**contract(), 'movementType': 'repetition',
        'completionMode': 'return_to_start'}, [])
    inventory = frames()
    payload = supported(requirements, inventory)
    payload['unexpected'] = 'must remain invalid'
    calls = []
    merged, receipt = correct_incomplete_evidence(payload, requirements, inventory,
        lambda *args: calls.append(args) or {'observations': []})
    assert calls == []
    assert merged == payload
    assert receipt['attempted'] is False
    assert receipt['before']['reviewStatus'] == 'incomplete'


@pytest.mark.parametrize('fault', [None, 'duplicate_action', 'unknown_action', 'unresolved',
                                  'missing_action', 'extra_field', 'wrong_equipment_count'])
def test_measured_cycle_semantics_owns_references_and_completion(fault):
    target = {**contract(), 'movementType': 'repetition', 'completionMode': 'return_to_start',
              'requiredPhases': ['lower', 'rise']}
    requirements = source_requirements(target, [{'normalizedName': 'barbell', 'minimumObjectCount': 1}])
    inventory = frames()
    choices = {'roleFrameIds': {'start': 'uniform:1', 'excursion': 'uniform:2', 'return': 'uniform:3'},
               'spanChoices': [{'frameIds': ['uniform:1', 'uniform:2']},
                               {'frameIds': ['uniform:2', 'uniform:3']}]}
    semantic = [row for row in requirements if row['id'] != 'completion'
                and not row['id'].startswith('phase_')]
    payload = supported(semantic, [row for row in inventory if row['sampling'] == 'uniform'])
    # This fixture helper normally cites motion samples; the semantic request
    # only supplies the uniform sheet plus separately attached role images.
    for row in payload['observations']:
        if row['requirementId'] != 'clean_interval':
            row['evidenceFrameIds'] = ['uniform:1', 'uniform:2'] if row['requirementId'] == 'action' else ['uniform:1']
    payload.update(earlier_interval_action='rise', later_interval_action='lower')
    prompt, schema = cycle_semantic_question(requirements, inventory, first_role_image=2)
    assert 'phase_1' not in prompt and 'cycle_span_1' not in prompt
    assert json.dumps(schema) in prompt
    assert 'completionVerdict' not in schema['properties']
    assert schema['properties']['earlier_interval_action']['enum'] == ['lower', 'rise', 'unresolved']
    if fault == 'duplicate_action':
        payload['later_interval_action'] = 'rise'
    elif fault == 'unknown_action':
        payload['earlier_interval_action'] = 'invented action'
    elif fault == 'unresolved':
        payload['earlier_interval_action'] = 'unresolved'
    elif fault == 'missing_action':
        del payload['later_interval_action']
    elif fault == 'extra_field':
        payload['completionVerdict'] = 'supported'
    elif fault == 'wrong_equipment_count':
        next(row for row in payload['observations'] if row['requirementId'] == 'equipment_1')['observedObjectCount'] = 0
    normalized = resolve_cycle_semantics(payload, requirements, inventory, choices)
    result = aggregate_evidence(normalized, requirements, inventory,
                                allow_cyclic_phase_order=True, cycle_choices=choices)
    assert result['passed'] is (fault is None)
    if fault is None:
        rows = {row['requirementId']: row for row in normalized['observations']}
        assert rows['phase_2']['evidenceFrameIds'] == ['uniform:1', 'uniform:2']
        assert rows['phase_1']['evidenceFrameIds'] == ['uniform:2', 'uniform:3']
        assert rows['completion']['evidenceFrameIds'] == ['uniform:1', 'uniform:2', 'uniform:3']


@pytest.mark.parametrize('mode,phases', [
    ('return_to_start', ['stand ready', 'lower', 'reach depth', 'rise']),
    ('distinct_end_state', ['push up', 'row one side', 'row the other side', 'squat clean', 'overhead press']),
    ('alternating_pair', ['perform left side', 'perform right side']),
    ('stable_hold', ['maintain active support']),
    ('active_travel', ['sustain loaded travel']),
    ('representative_cycle', ['drive', 'recover', 'continue the cycle']),
])
def test_semantic_protocol_covers_completion_modes_without_phase_ids(mode, phases):
    target = {**contract(), 'completionMode': mode, 'requiredPhases': phases}
    requirements = source_requirements(target, [{'normalizedName': 'implement', 'minimumObjectCount': 1}])
    inventory = [{'id': f'{group}:{index}', 'sampling': group, 'timestampSeconds': float(index - 1)}
                 for group in ('uniform', 'motion') for index in range(1, len(phases) + 4)]
    schema = evidence_schema(requirements, inventory, semantic_labels=True)
    prompt = evidence_prompt(requirements, inventory, semantic_labels=True)
    assert 'phase_1' not in prompt and 'requirementId' not in prompt
    assert all('requirementId' not in row['properties']
               for row in schema['properties']['observations']['items']['oneOf'])
    original = supported(requirements, inventory)
    wire = semantic_reply(original, requirements)
    normalized = resolve_semantic_evidence(wire, requirements)
    assert normalized == original
    assert aggregate_evidence(normalized, requirements, inventory)['passed'] is True
    if len(phases) > 1:
        rows = [row for row in normalized['observations'] if row['requirementId'].startswith('phase_')]
        rows[0]['evidenceFrameIds'], rows[-1]['evidenceFrameIds'] = (
            rows[-1]['evidenceFrameIds'], rows[0]['evidenceFrameIds'])
        assert aggregate_evidence(normalized, requirements, inventory)['passed'] is False


@pytest.mark.parametrize('fault', ['unknown_label', 'duplicate', 'extra_field', 'legacy_id', 'missing_count'])
def test_semantic_protocol_cannot_launder_invalid_claims(fault):
    requirements = source_requirements(contract(), [{'normalizedName': 'implement', 'minimumObjectCount': 1}])
    inventory = frames()
    payload = semantic_reply(supported(requirements, inventory), requirements)
    if fault == 'unknown_label':
        payload['observations'][0]['requirement'] = 'a claim not supplied by code'
    elif fault == 'duplicate':
        payload['observations'].append(dict(payload['observations'][0]))
    elif fault == 'extra_field':
        payload['observations'][0]['invented'] = True
    elif fault == 'legacy_id':
        payload = supported(requirements, inventory)
    else:
        next(row for row in payload['observations'] if 'observedObjectCount' in row).pop('observedObjectCount')
    normalized = resolve_semantic_evidence(payload, requirements)
    assert aggregate_evidence(normalized, requirements, inventory)['passed'] is False


def test_semantic_claim_can_satisfy_phase_and_variant_without_duplicate_model_questions():
    target = {**contract(), 'requiredPhases': ['floor start', 'pull', 'catch', 'stand'],
              'variantQualifiers': ['floor start', 'front-rack catch']}
    requirements = source_requirements(target, [])
    inventory = [{'id': f'{group}:{index}', 'sampling': group, 'timestampSeconds': float(index - 1)}
                 for group in ('uniform', 'motion') for index in range(1, 8)]
    wire = semantic_reply(supported(requirements, inventory), requirements)
    schema = evidence_schema(requirements, inventory, semantic_labels=True)
    assert schema['properties']['observations']['minItems'] == len(requirements) - 1
    floor_start = next(row for row in schema['properties']['observations']['items']['oneOf']
                       if row['properties']['requirement']['enum'] == ['floor start'])
    assert floor_start['properties']['evidenceFrameIds']['maxItems'] == 1
    normalized = resolve_semantic_evidence(wire, requirements)
    assert aggregate_evidence(normalized, requirements, inventory)['passed'] is True
    rows = {row['requirementId']: row for row in normalized['observations']}
    assert rows['phase_1']['evidenceFrameIds'] == rows['variant_1']['evidenceFrameIds']
    repeated_phase = source_requirements({**target, 'requiredPhases': ['pull', 'pull']}, [])
    assert resolve_semantic_evidence(semantic_reply(supported(repeated_phase, inventory), repeated_phase),
                                     repeated_phase) == {'observations': []}


def test_structured_source_schema_uses_only_supplied_requirement_and_frame_ids():
    requirements, inventory = source_requirements(contract(), []), frames()
    schema = evidence_schema(requirements, inventory)
    rows = schema['properties']['observations']['items']['oneOf']
    row_schemas = {row['properties']['requirementId']['enum'][0]: row for row in rows}
    fields = row_schemas['action']['properties']
    assert list(row_schemas) == ['action', 'completion', 'clean_interval']
    assert fields['evidenceFrameIds']['items']['enum'] == [f['id'] for f in inventory]
    assert row_schemas['action']['properties']['evidenceFrameIds']['maxItems'] == 2
    assert 'observedObjectCount' not in row_schemas['action']['properties']
    assert 'observedObjectCount' not in row_schemas['completion']['properties']
    assert row_schemas['clean_interval']['properties']['evidenceFrameIds']['maxItems'] == 3
    assert row_schemas['clean_interval']['properties']['evidenceFrameIds']['items']['enum'] == [
        f['id'] for f in inventory if f['sampling'] == 'uniform']
    assert schema['additionalProperties'] is False


def test_structured_source_preserves_equipment_quantity_and_hold_completion():
    target = {**contract(), 'completionMode': 'stable_hold'}
    requirements = source_requirements(target, [{'normalizedName': 'dumbbell',
        'role': 'active_implement', 'minimumObjectCount': 2}])
    equipment = next(r for r in requirements if r['id'] == 'equipment_1')
    assert json.loads(equipment['description'])['minimumObjectCount'] == 2
    payload = supported(requirements, frames())
    equipment_observation = next(r for r in payload['observations'] if r['requirementId'] == 'equipment_1')
    equipment_observation['observedObjectCount'] = 1
    assert 'equipment_quantity_unverified' in aggregate_evidence(payload, requirements, frames())['errors']
    equipment_observation['observedObjectCount'] = 2
    assert aggregate_evidence(payload, requirements, frames())['passed'] is True
    completion = next(r for r in requirements if r['id'] == 'completion')
    assert 'entry and release are not required' in completion['description']
    assert 'at the cited instants' in evidence_prompt(requirements, frames())
    equipment_observation['observedObjectCount'] = MAX_OBSERVED_OBJECT_COUNT + 1
    assert 'equipment_quantity_unverified' in aggregate_evidence(payload, requirements, frames())['errors']


def test_non_equipment_observed_count_is_non_authoritative_metadata():
    requirements, inventory = source_requirements(contract(), []), frames()
    payload = supported(requirements, inventory)
    for row in payload['observations']:
        row['observedObjectCount'] = 1
    result = aggregate_evidence(payload, requirements, inventory)
    assert result['passed'] is True
    assert all('observedObjectCount' not in row for row in result['observations'])


def test_return_to_start_completion_requires_three_distinct_source_times():
    target = {**contract(), 'completionMode': 'return_to_start'}
    requirements, inventory = source_requirements(target, []), frames()
    completion = next(row for row in requirements if row['id'] == 'completion')
    assert completion['minimumDistinctFrameCount'] == 3
    schema_rows = evidence_schema(requirements, inventory)['properties']['observations']['items']['oneOf']
    row_schema = next(row for row in schema_rows
                      if row['properties']['requirementId']['enum'] == ['completion'])
    assert row_schema['properties']['evidenceFrameIds']['maxItems'] == 3
    payload = supported(requirements, inventory)
    assert aggregate_evidence(payload, requirements, inventory)['passed'] is True
    completion_row = next(row for row in payload['observations'] if row['requirementId'] == 'completion')
    completion_row['evidenceFrameIds'] = ['motion:1', 'motion:3']
    result = aggregate_evidence(payload, requirements, inventory)
    assert 'sequence_evidence_missing' in result['errors']
    assert result['reviewStatus'] == 'incomplete'
    prompt = evidence_prompt(requirements, inventory)
    assert 'meaningful start, action excursion and return' in prompt


def test_retained_squat_inventory_uses_bounded_citations_and_uniform_only_clean_interval():
    target = {**contract(), 'completionMode': 'return_to_start',
              'definingAction': 'With the barbell supported across the upper back, lower the body by bending the hips and knees, then rise back to standing.',
              'requiredPhases': ['With the barbell supported across the upper back, lower the body by bending the hips and knees, then rise back to standing.']}
    roles = [
        {'normalizedName': 'barbell', 'role': 'active_implement', 'minimumObjectCount': 1},
        {'normalizedName': 'squat rack', 'role': 'support_surface', 'minimumObjectCount': 1},
    ]
    requirements = source_requirements(target, roles)
    inventory = [
        {'id': f'{group}:{index}', 'sampling': group, 'timestampSeconds': (index - 1) / 3}
        for group, count in (('uniform', 16), ('motion', 28))
        for index in range(1, count + 1)
    ]
    schema = evidence_schema(requirements, inventory)
    item_schema = schema['properties']['observations']['items']
    row_schemas = {row['properties']['requirementId']['enum'][0]: row for row in item_schema['oneOf']}
    action_cap = row_schemas['action']['properties']['evidenceFrameIds']['maxItems']
    clean_cap = sum(frame['sampling'] == 'uniform' for frame in inventory)
    assert action_cap == 2  # this retained contract has no separate phase requirement
    complex_requirements = source_requirements(
        {**target, 'requiredPhases': ['Pause at the bottom', 'Rise to standing']}, roles)
    complex_schema = evidence_schema(complex_requirements, inventory)
    complex_rows = {row['properties']['requirementId']['enum'][0]: row
                    for row in complex_schema['properties']['observations']['items']['oneOf']}
    assert complex_rows['action']['properties']['evidenceFrameIds']['maxItems'] == 4
    assert clean_cap == 16
    assert POLICY_VERSION == 7
    budget = evidence_response_token_budget(requirements, inventory)
    assert 256 <= budget < 1536
    prompt = evidence_prompt(requirements, inventory)
    assert 'every uniform frame ID and no motion frame IDs' in prompt

    payload = supported(requirements, inventory)
    by_id = {row['requirementId']: row for row in payload['observations']}
    by_id['action']['evidenceFrameIds'] = ['motion:1', 'motion:8']
    by_id['completion']['evidenceFrameIds'] = ['motion:3', 'motion:9', 'motion:16']
    by_id['clean_interval']['evidenceFrameIds'] = [f'uniform:{i}' for i in range(1, 17)]
    assert aggregate_evidence(payload, requirements, inventory)['passed'] is True

    by_id['action']['evidenceFrameIds'].append('motion:12')
    assert 'too_many_frame_references' in aggregate_evidence(payload, requirements, inventory)['errors']
    by_id['action']['evidenceFrameIds'].pop()
    by_id['clean_interval']['evidenceFrameIds'].append('motion:1')
    assert 'clean_interval_motion_frame_not_allowed' in aggregate_evidence(payload, requirements, inventory)['errors']


def test_retained_truncated_squat_response_is_incomplete_under_new_bounded_policy():
    retained = Path('build/exercise_motion/cut-search-20261023/live-production-v2/barbell-back-squat/workspace/'
        'barbell-back-squat-001-d9xf-fwge5m/source-review-cache/'
        '07a057efcdbdfd62e756c706b61467a08607a11866a0908e7eed37d594784a61/'
        'two_scale_source_validation.json')
    if not retained.is_file():
        pytest.skip('retained production failure artifact is not present')
    artifact = json.loads(retained.read_text(encoding='utf-8'))
    requirements, inventory = artifact['requirements'], artifact['frameInventory']
    raw = artifact['gates']['structuredEvidence']['rawResponse']
    assert len(inventory) == 44
    assert sum(frame['sampling'] == 'uniform' for frame in inventory) == 16
    assert sum(frame['sampling'] == 'motion' for frame in inventory) == 28
    assert bake.extract_json_object(raw) is None
    assert aggregate_evidence(None, requirements, inventory)['reviewStatus'] == 'incomplete'
    rows = evidence_schema(requirements, inventory)['properties']['observations']['items']['oneOf']
    row_schemas = {row['properties']['requirementId']['enum'][0]: row for row in rows}
    equipment = [json.loads(row['description']) for row in artifact['requirements']
                 if str(row['id']).startswith('equipment_')]
    requirements = source_requirements(artifact['exerciseMotionContract'], equipment)
    rows = evidence_schema(requirements, inventory)['properties']['observations']['items']['oneOf']
    row_schemas = {row['properties']['requirementId']['enum'][0]: row for row in rows}
    assert row_schemas['action']['properties']['evidenceFrameIds']['maxItems'] == 2
    assert row_schemas['equipment_1']['properties']['evidenceFrameIds']['maxItems'] == 1
    assert row_schemas['equipment_2']['properties']['evidenceFrameIds']['maxItems'] == 1
    assert row_schemas['clean_interval']['properties']['evidenceFrameIds']['maxItems'] == 16
    assert row_schemas['completion']['properties']['evidenceFrameIds']['maxItems'] == 3
    assert evidence_response_token_budget(requirements, inventory) < 1536


def test_retained_complete_squat_response_ignores_non_equipment_count_fields():
    retained = Path('build/exercise_motion/cut-search-20261023/live-production-v2/barbell-back-squat/workspace/'
        'barbell-back-squat-001-d9xf-fwge5m/source-review-cache/'
        'd8805811563bc86ad1d189c8ecc88ac1cad50b8ab6bc69c3f792615577599ba1/'
        'two_scale_source_validation.json')
    if not retained.is_file():
        pytest.skip('retained production response artifact is not present')
    artifact = json.loads(retained.read_text(encoding='utf-8'))
    requirements, inventory = artifact['requirements'], artifact['frameInventory']
    response = artifact['gates']['structuredEvidence']['response']
    result = aggregate_evidence(response, requirements, inventory)
    assert result['errors'] == []
    assert result['reviewStatus'] == 'passed'
    assert all('observedObjectCount' not in row for row in result['observations']
               if not str(row['requirementId']).startswith('equipment_'))


def test_structured_source_unresolved_visual_evidence_does_not_repeat_question(tmp_path, monkeypatch):
    from exercise_motion_pkg import source_review_preflight as preflight
    item = bake.RankedCandidate(0, 0, 'high-pull', 'High Pull', 'high-pull', {'videoId': 'id'})
    request = SimpleNamespace(two_scale_source_validation=True, workspace=tmp_path)
    monkeypatch.setattr(bake, 'read_basic_video_metadata', lambda path: SimpleNamespace(duration_seconds=3.))
    monkeypatch.setattr(bake, 'final_output_source_contact_sheets', lambda *a, **k: [])
    monkeypatch.setattr(bake, 'pre_reconstruction_exact_source_phase_reference_metrics', lambda item: {})
    monkeypatch.setattr(bake, 'validate_source_pose_endpoints_against_contract', lambda *a, **k: {})
    calls = []
    def validate(*args, **kwargs):
        calls.append(True)
        return {'sourceEvidencePolicyVersion': 1, 'passed': False, 'reviewStatus': 'incomplete',
                'gates': {'structuredEvidence': {'errors': [], 'unresolvedRequirementIds': ['action']}}}
    monkeypatch.setattr(bake, 'validate_two_scale_source_with_caption_images', validate)
    with pytest.raises(preflight.SourceReviewIncomplete, match='expand'):
        preflight.review_prepared_source(item, request=request, selected_video=tmp_path / 'video.mp4',
            contract=contract(), caption_images=lambda **kwargs: '{}')
    assert len(calls) == 1


def make_sheet(tmp_path, name):
    directory = tmp_path / name
    directory.mkdir()
    sheet = directory / 'contact_sheet_01.jpg'
    sheet.write_bytes(b'supplied image')
    (directory / 'contact_sheet_evidence.json').write_text(json.dumps({'sheets': {sheet.name: {
        'sha256': hashlib.sha256(sheet.read_bytes()).hexdigest(),
        'frames': [{'number': i, 'timestampSeconds': i - 1} for i in (1, 2, 3)],
    }}}))
    return sheet


def test_structured_source_inventory_rejects_changed_image(tmp_path):
    sheet = make_sheet(tmp_path, 'uniform')
    assert len(evidence_inventory({'uniform': [sheet]})) == 3
    sheet.write_bytes(b'changed')
    with pytest.raises(ValueError, match='differs'):
        evidence_inventory({'uniform': [sheet]})


def test_structured_source_manifest_matches_rendered_tiles(tmp_path):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from exercise_motion_pkg.segment_detection import build_frame_contact_sheets
    images = []
    for index in range(3):
        path = tmp_path / f'frame_{index}.jpg'
        assert cv2.imwrite(str(path), np.full((80, 80, 3), index * 80, dtype=np.uint8))
        images.append(path)
    sheets = build_frame_contact_sheets(frame_paths=images, timestamps=[0., .2, .6],
        output_dir=tmp_path / 'sheets', columns=2, tile_width=160, frames_per_sheet=2,
        jpeg_quality=90, sequence_labels=True)
    inventory = evidence_inventory({'uniform': sheets})
    assert [(f['tileNumber'], f['timestampSeconds'], f['image']) for f in inventory] == [
        (1, 0., 1), (2, .2, 1), (3, .6, 2)]
    images[-1].write_bytes(b'corrupt')
    assert build_frame_contact_sheets(frame_paths=images, timestamps=[0., .2, .6],
        output_dir=tmp_path / 'broken', columns=2, tile_width=160, frames_per_sheet=2,
        jpeg_quality=90) == []


@pytest.mark.parametrize('answer', ['supported', 'old_high_pull_prose', 'endpoint_conflict'])
def test_structured_source_production_uses_one_grounded_call_without_prose_adjudication(tmp_path, monkeypatch, answer):
    uniform, motion = make_sheet(tmp_path, 'uniform'), make_sheet(tmp_path, 'motion')
    target = contract()
    item = SimpleNamespace(exercise_name='Clean Grip High Pull', candidate_workspace=tmp_path, candidate={})
    monkeypatch.setattr(bake, 'final_output_source_video_window', lambda *a: None)
    monkeypatch.setattr(bake, 'final_output_motion_contact_sheets', lambda *a, **k: [motion])
    monkeypatch.setattr(bake, 'resolve_two_scale_exercise_motion_contract', lambda *a, **k: (target, None, None))
    monkeypatch.setattr(bake, 'validate_source_pose_endpoints_against_contract', lambda *a, **k: {
        'available': answer == 'endpoint_conflict', 'passed': answer != 'endpoint_conflict'})
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        assert kwargs['frame_paths'] == [uniform, motion]
        assert kwargs['response_schema']['additionalProperties'] is False
        assert 'Audit only' not in kwargs['prompt']
        if answer == 'old_high_pull_prose':
            return json.dumps({'corroboratedConflict': False, 'targetIdentitySupported': 'false',
                               'corroboratedContradictions': ['deadlift; must start at thighs']})
        requirements = source_requirements(target, bake.two_scale_equipment_role_requirements(item.exercise_name, target))
        inventory = evidence_inventory({'uniform': [uniform], 'motion': [motion]})
        assert kwargs['max_tokens'] == evidence_response_token_budget(requirements, inventory, semantic_labels=True)
        return json.dumps(semantic_reply(supported(requirements, inventory), requirements))
    result = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
        output_dir=tmp_path / 'review', caption_images=caption, exercise_motion_contract=target)
    assert len(calls) == 1
    assert result['passed'] is (answer == 'supported')
    if answer == 'old_high_pull_prose':
        assert result['reviewStatus'] == 'incomplete'
        assert bake.two_scale_source_validation_needs_repair(result) is False
        assert bake.cache_repaired_source_review(result, {'valid': True, 'resolved': True}) is False
    elif answer == 'endpoint_conflict':
        assert result['rejectionReasons'] == ['two_scale_source_pose_contract_mismatch']


def test_measured_cycle_production_separates_semantic_questions_and_keeps_canonical_evidence(tmp_path, monkeypatch):
    uniform, motion = make_sheet(tmp_path, 'uniform'), make_sheet(tmp_path, 'motion')
    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact source')
    target = {**contract(), 'movementType': 'repetition', 'completionMode': 'return_to_start',
              'requiredPhases': ['lower', 'rise']}
    item = SimpleNamespace(exercise_name='Cyclic action', candidate_workspace=tmp_path,
                           candidate={}, source_review_video_path=video)
    choices = {'roleFrameIds': {'start': 'uniform:1', 'excursion': 'uniform:2', 'return': 'uniform:3'},
               'spanChoices': [{'frameIds': ['uniform:1', 'uniform:2']},
                               {'frameIds': ['uniform:2', 'uniform:3']}]}
    role_images = [tmp_path / f'role-{role}.jpg' for role in ('start', 'excursion', 'return')]
    for path in role_images:
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(bake, 'final_output_source_video_window',
                        lambda *a: (video, bake.DetectionWindow(index=0, start_seconds=0., end_seconds=2.)))
    monkeypatch.setattr(bake, 'final_output_motion_contact_sheets', lambda *a, **k: [motion])
    monkeypatch.setattr(bake, 'resolve_two_scale_exercise_motion_contract', lambda *a, **k: (target, None, None))
    monkeypatch.setattr(bake, 'validate_source_pose_endpoints_against_contract', lambda *a, **k: {'available': True, 'passed': True})
    monkeypatch.setattr(bake, 'load_verified_source_pose_reference', lambda *a: {})
    monkeypatch.setattr('exercise_motion_pkg.source_evidence.return_cycle_evidence_choices', lambda *a: choices)
    monkeypatch.setattr(bake, 'source_cycle_role_frames', lambda *a: role_images)
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        assert 'phase_1' not in kwargs['prompt'] and 'cycle_span_1' not in kwargs['prompt']
        if 'observations' not in kwargs['response_schema']['properties']:
            assert kwargs['frame_paths'] == role_images
            return json.dumps({'earlier_interval_action': 'rise', 'later_interval_action': 'lower'})
        assert kwargs['frame_paths'] == [uniform]
        assert 'Interpret the defining action cyclically too' in kwargs['prompt']
        requirements = source_requirements(target, bake.two_scale_equipment_role_requirements(item.exercise_name, target))
        semantic = [row for row in requirements if row['id'] != 'completion' and not row['id'].startswith('phase_')]
        payload = supported(semantic, evidence_inventory({'uniform': [uniform]}))
        for row in payload['observations']:
            if row['requirementId'] != 'clean_interval':
                row['evidenceFrameIds'] = ['uniform:1', 'uniform:2'] if row['requirementId'] == 'action' else ['uniform:1']
        return json.dumps(payload)
    class Reviewer:
        settings = SimpleNamespace(llama_cpp_model='test-vision')
        def caption(self, **kwargs):
            return caption(**kwargs)
    reviewer = Reviewer()
    result = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
        output_dir=tmp_path / 'review', caption_images=reviewer.caption, exercise_motion_contract=target,
        source_phase_metrics={'sourceVideoPath': str(video), 'sourcePoseReferencePath': str(tmp_path / 'pose.json')})
    assert result['passed'] is True
    assert len(calls) == 2
    gate = result['gates']['structuredEvidence']
    assert bake.extract_json_object(gate['rawResponse']) == gate['response']
    assert gate['correction']['mode'] == 'measured_cycle_semantics'
    assert gate['correction']['attempted'] is False
    cached = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
        output_dir=tmp_path / 'review', caption_images=reviewer.caption, exercise_motion_contract=target,
        source_phase_metrics={'sourceVideoPath': str(video), 'sourcePoseReferencePath': str(tmp_path / 'pose.json')})
    assert cached['sourceReviewCache']['cacheHit'] is True
    # Losing the aggregate receipt must not force the two retained judgments to repeat.
    Path(cached['sourceReviewCache']['checkpoint']).unlink()
    recovered = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
        output_dir=tmp_path / 'review', caption_images=reviewer.caption, exercise_motion_contract=target,
        source_phase_metrics={'sourceVideoPath': str(video), 'sourcePoseReferencePath': str(tmp_path / 'pose.json')})
    assert recovered['passed'] is True
    assert len(calls) == 2


def test_cycle_role_frames_cache_invalidates_source_and_does_not_keep_partial_extraction(tmp_path, monkeypatch):
    video = tmp_path / 'source.mp4'
    video.write_bytes(b'source A')
    choices = {'roleTimes': {'start': 0., 'excursion': 1., 'return': 2.}}
    calls = []
    def extract(**kwargs):
        calls.append(kwargs)
        assert kwargs['output_dir'].is_dir()
        paths = [kwargs['output_dir'] / f'frame-{index}.jpg' for index in range(3)]
        for path in paths:
            path.write_bytes(video.read_bytes() + path.name.encode())
        return paths[:2] if len(calls) == 1 else paths
    monkeypatch.setattr(bake, 'extract_window_frames_with_ffmpeg', extract)
    with pytest.raises(ValueError, match='all be extracted'):
        bake.source_cycle_role_frames(video, choices, tmp_path / 'roles')
    paths = bake.source_cycle_role_frames(video, choices, tmp_path / 'roles')
    assert len(paths) == 3
    assert bake.source_cycle_role_frames(video, choices, tmp_path / 'roles') == paths
    assert len(calls) == 2
    video.write_bytes(b'source B')
    bake.source_cycle_role_frames(video, choices, tmp_path / 'roles')
    assert len(calls) == 3
    paths[0].write_bytes(b'corrupt')
    bake.source_cycle_role_frames(video, choices, tmp_path / 'roles')
    assert len(calls) == 4
