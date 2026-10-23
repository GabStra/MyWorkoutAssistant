import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_evidence import (
    MAX_OBSERVED_OBJECT_COUNT, POLICY_VERSION, aggregate_evidence, evidence_inventory,
    evidence_response_token_budget, evidence_schema, evidence_prompt,
    source_requirements,
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
    assert POLICY_VERSION == 3
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
        assert kwargs['max_tokens'] == evidence_response_token_budget(requirements, inventory)
        return json.dumps(supported(requirements, inventory))
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
