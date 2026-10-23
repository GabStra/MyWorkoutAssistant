import copy
import json

import pytest

from workout_generator_pkg import plan_review
from workout_generator_pkg.generation_audit import render_plan_disclosures
from workout_generator_pkg.planning_tools import (
    PlanningInputError, _bind_effort_acceptance, audit_workout_plan, effort_acceptance_guidance,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages


CRITERIA = {'acceptanceCriterion': 'Count only repetitions with controlled lowering.',
    'terminationCriterion': 'Stop when controlled lowering can no longer be maintained.'}


@pytest.mark.parametrize('kind', ['rir_range', 'technical_criteria'])
def test_approved_rir_and_technical_criteria_coexist_and_render(kind):
    exercise = {'effortAcceptance': {'kind': kind, **CRITERIA}}
    raw_rendered = effort_acceptance_guidance(exercise['effortAcceptance'], {'minimum': 1, 'maximum': 2})
    assert '1–2 RIR (approved target)' in raw_rendered and all(value in raw_rendered for value in CRITERIA.values())
    draft = {'workouts': [{'exercises': [exercise]}]}
    _bind_effort_acceptance(draft, {'minimum': 1, 'maximum': 2})
    acceptance = exercise['effortAcceptance']
    assert acceptance == {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2, **CRITERIA}
    rendered = effort_acceptance_guidance(acceptance, {'minimum': 1, 'maximum': 2})
    assert '1–2 RIR (approved target)' in rendered
    assert all(value in rendered for value in CRITERIA.values())


@pytest.mark.parametrize('acceptance,code', [
    ({'kind': 'rir_range', 'minimumRIR': 2, 'maximumRIR': 3}, 'effort_acceptance_conflicts_with_requirement'),
    ({'kind': 'rir_range', 'minimumRIR': True, 'maximumRIR': 2}, 'invalid_effort_acceptance'),
    ({'kind': 'invented'}, 'invalid_effort_acceptance'),
    ({'kind': 'rir_range', 'acceptanceCriterion': CRITERIA['acceptanceCriterion']}, 'invalid_effort_acceptance'),
])
def test_combining_criteria_does_not_weaken_validation(acceptance, code):
    with pytest.raises(PlanningInputError) as raised:
        _bind_effort_acceptance({'workouts': [{'exercises': [{'effortAcceptance': acceptance}]}]},
            {'minimum': 1, 'maximum': 2})
    assert raised.value.code == code


def test_same_prescription_inherits_one_criterion_without_overwriting_explicit_variants():
    first = {'definition_id': 'LIBRARY_0', 'minReps': 5, 'maxReps': 8, 'numWorkSets': 3,
        'placementNotes': 'Set up near the wall.', 'effortAcceptance': {'kind': 'rir_range', **CRITERIA}}
    second = {**copy.deepcopy(first), 'numWorkSets': 2, 'placementNotes': 'Set up on the mat.'}
    second.pop('effortAcceptance')
    draft = {'workouts': [{'exercises': [first, second]}]}
    _bind_effort_acceptance(draft, {'minimum': 1, 'maximum': 2})
    assert first['effortAcceptance'] == second['effortAcceptance']
    assert [first['numWorkSets'], second['numWorkSets']] == [3, 2]
    assert second['placementNotes'] == 'Set up on the mat.'
    second['effortAcceptance']['acceptanceCriterion'] = 'Count only repetitions reaching the marked depth.'
    third = {**copy.deepcopy(first), 'effortAcceptance': {'kind': 'rir_range'}}
    draft['workouts'][0]['exercises'].append(third)
    _bind_effort_acceptance(draft, {'minimum': 1, 'maximum': 2})
    assert second['effortAcceptance']['acceptanceCriterion'] != first['effortAcceptance']['acceptanceCriterion']
    assert third['effortAcceptance']['acceptanceCriterion'] is None


def test_discovery_sees_typed_criteria_and_the_same_code_disclosure_as_preview(monkeypatch):
    equipment, _, requirements, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first['numWorkSets'] = 3
    second = copy.deepcopy(first)
    second.update(numWorkSets=2, placementNotes='Use the same controlled range on the mat.')
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(requirements)
    audited = audit_workout_plan(draft, equipment, messages)
    assert audited['passed']
    calls = []
    def respond(client, request, **kwargs):
        data = json.loads(request[-1]['content']); calls.append(data)
        text = data['coachingComparison']
        assert first['placementNotes'] not in text and second['placementNotes'] not in text
        assert 'placementNotes' not in json.dumps(data)
        assert 'effortAcceptance' in text
        assert all(e['id'] in text for e in data['draft']['exercises'])
        disclosures = render_plan_disclosures(audited['audit'], requirements['requirements']['auditTargets']['weeklyEffectiveSets'], draft)
        assert disclosures in data['finalArtifact']['programGuidance'] and disclosures in audited['preview']
        assert 'renderedDisclosures' not in data
        def text_leaves(value):
            if isinstance(value, dict):
                return [text for child in value.values() for text in text_leaves(child)]
            if isinstance(value, list):
                return [text for child in value for text in text_leaves(child)]
            return [value] if isinstance(value, str) else []
        assert sum(text.count(disclosures) for text in text_leaves(data)) == 1
        assessments = {key: {'status': 'supported', 'reason': 'The extracted target matches the source.',
            'evidencePaths': [value['_reviewRef']]}
            for key, value in data['sourceMessages'].items() if value.get('role') == 'user'}
        return json.dumps({'findings': [], 'requirementAssessments': assessments}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)
    assert plan_review.review_draft(None, audited, messages, equipment, two_pass=True)['passed']
    assert len(calls) == 1


def test_code_disclosures_ignore_legacy_advice_and_reductions_fail_numeric_audit():
    equipment, _, stored, draft = planning_case()
    draft['programGuidance'] = 'Recovery adjustment: remove one working set; do not compensate elsewhere.'
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    context = plan_review._context(result, messages, equipment, None, len(messages)-1)
    guidance = context['finalArtifact']['programGuidance']
    assert draft['programGuidance'] not in guidance and draft['programGuidance'] not in result['preview']
    from workout_generator_pkg.repair_capabilities import RECOVERY_ADJUSTMENT_GUIDANCE
    assert context['repairCapabilityContract']['codeOwnedBehaviors']['recovery_adjustment'] == RECOVERY_ADJUSTMENT_GUIDANCE
    assert RECOVERY_ADJUSTMENT_GUIDANCE in guidance
    assert 'request a re-audit before changing set counts' in guidance
    assert 'the audit rejects reductions that breach them' in guidance
    assert guidance in result['preview']
    reduced = copy.deepcopy(draft)
    reduced['workouts'][0]['exercises'][0]['numWorkSets'] -= 1
    failed = audit_workout_plan(reduced, equipment, messages)
    assert not failed['passed']
    assert any(e.get('muscle') == 'chest' and e.get('actual') == 4 and e.get('minimum') == 5 for e in failed['errors'])
    assert stored['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] == 5


@pytest.mark.parametrize('change', ['order', 'sets', 'guidance'])
def test_reviewed_artifact_detects_changes_after_materialization(change):
    from workout_generator_pkg.domain_ops import reviewable_workout_artifact
    equipment, _, stored, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first['numWorkSets'] = 3
    second = copy.deepcopy(first)
    second['numWorkSets'] = 2
    draft['workouts'][0]['exercises'].append(second)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']
    expected = reviewable_workout_artifact(result['planIndex'], 'Reviewed guidance')
    actual = {'workouts': [{**day, 'workoutComponents': copy.deepcopy(day['components'])} for day in expected['workouts']]}
    assert reviewable_workout_artifact(result['planIndex'], 'Reviewed guidance', actual) == expected
    components = actual['workouts'][0]['workoutComponents']
    if change == 'order':
        components.reverse()
    elif change == 'sets':
        components[0]['sets'][0]['reps'] += 1
    else:
        components[0]['notes'] += ' Unreviewed advice.'
    assert reviewable_workout_artifact(result['planIndex'], 'Reviewed guidance', actual) != expected


@pytest.mark.parametrize('invalid', [None, 'omitted_requirement', 'unsupported_correction'])
def test_qualitative_requirement_coverage_is_explicit_without_inventing_capacity(monkeypatch, invalid):
    from jsonschema import ValidationError
    from workout_generator_pkg.review_assessment import validate_assessment
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = plan_review._context(result, messages, equipment, None, len(messages)-1)
    context['requirements']['requirementAccounting'] = [
        {'instruction': 'Balance movement patterns without exact set equality.', 'enforcement': 'semantic_check', 'sourceReferences': ['SOURCE_0']},
        {'instruction': 'Manage recovery and individual fatigue.', 'enforcement': 'semantic_check', 'sourceReferences': ['SOURCE_0']}]
    calls = []
    def respond(client, request, **options):
        calls.append(request)
        checks = {'0': {'status': 'supported', 'reason': 'No exact-equality requirement or ban on repeated exercises.', 'evidencePaths': []},
            '1': {'status': 'insufficient_evidence', 'reason': 'Personal recovery and performance are unknown.', 'evidencePaths': []}}
        if invalid == 'omitted_requirement':
            checks.pop('1')
        elif invalid == 'unsupported_correction':
            checks['1']['status'] = 'needs_correction'
        references = options['output_schema']['properties']['requirementAssessments']['required']
        return json.dumps({'findings': [], 'requirementAssessments': {
            references[int(index)]: check for index, check in checks.items()}}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)
    if invalid:
        with pytest.raises((ValueError, ValidationError)):
            plan_review._review_complete_draft(None, context, result, messages, len(messages)-1, None)
    else:
        review = plan_review._review_complete_draft(None, context, result, messages, len(messages)-1, None)
        assert review['requirementAssessments']['1']['status'] == 'insufficient_evidence'
        validate_assessment(review, context, require_confirmation=True)
        review['requirementAssessments']['1']['status'] = 'supported'
        with pytest.raises(ValueError, match='stale'):
            validate_assessment(review, context)
    assert len(calls) == 1

def test_final_artifact_audit_includes_superset_members_and_their_timing():
    from workout_generator_pkg.domain_ops import reviewable_workout_artifact
    from workout_generator_pkg.generation_audit import audit_workout_package
    equipment, _, stored, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first.update(numWorkSets=3, superset='PAIR', restBetweenSetsSeconds=0,
                 restAfterSupersetExerciseSeconds=60, repDurationSeconds=5)
    second = copy.deepcopy(first)
    draft['workouts'][0]['exercises'].append(second)
    audited = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert audited['passed']
    artifact = reviewable_workout_artifact(audited['planIndex'], '')
    group = next(c for c in artifact['workouts'][0]['components'] if c['type'] == 'Superset')
    assert all(e['type'] == 'Exercise' for e in group['exercises'])
    report = audit_workout_package({'workouts': [{**day, 'workoutComponents': day['components']}
        for day in artifact['workouts']]}, stored['requirements']['auditTargets'],
        rep_duration_seconds_by_exercise={e['id']: 5 for e in group['exercises']})
    assert report['weeklyWorkingSets'] == 6
    assert report['workouts'][0]['timing']['workSeconds'] == 240



@pytest.mark.parametrize('explicit_criteria', [False, True])
def test_definition_replacement_does_not_inherit_old_movement_criteria(explicit_criteria):
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    from workout_generator_pkg.json_patching import apply_json_patch
    _, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item['effortAcceptance'] = {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2,
        'acceptanceCriterion': 'Fly with soft elbows.', 'terminationCriterion': 'Stop when the fly range shortens.'}
    fields = {'definition_id': 'LIBRARY_1'}
    if explicit_criteria:
        fields['effortAcceptance'] = {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2,
            'acceptanceCriterion': 'Row toward the torso.', 'terminationCriterion': 'Stop when the torso rocks.'}
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'currentDraft': draft}
    args = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': fields}]}}
    compiled, _ = compile_coordinated_repair(args, task, draft)
    after = apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises'][0]['effortAcceptance']
    assert after['minimumRIR'] == 1 and after['maximumRIR'] == 2
    assert after.get('acceptanceCriterion') == ('Row toward the torso.' if explicit_criteria else None)
    assert draft['workouts'][0]['exercises'][0]['effortAcceptance']['acceptanceCriterion'] == 'Fly with soft elbows.'


def test_qualitative_correction_links_native_finding_without_model_indexes(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = plan_review._context(result, messages, equipment, None, len(messages)-1)
    context['requirements']['requirementAccounting'] = [
        {'instruction': 'Use the approved effort.', 'enforcement': 'semantic_check', 'sourceReferences': ['SOURCE_0']}]
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        if 'context' not in data:
            key = options['output_schema']['properties']['requirementAssessments']['required'][0]
            check = options['output_schema']['properties']['requirementAssessments']['properties'][key]
            assert 'findingIndexes' not in check['properties']
            ref = data['draft']['exercises'][0]['_reviewRef']
            source_ref = data['sourceMessages'][key]['_reviewRef']
            return json.dumps({'findings': [{
                'concernGroup': 'NEW_0', 'basis': 'established_violation', 'severity': 'blocking',
                'action': 'repair', 'decisionId': None,
                'message': 'Effort conflicts with the approved target.',
                'evidencePaths': [ref, source_ref]}], 'requirementAssessments': {key: {
                'status': 'needs_correction', 'reason': 'Effort conflicts with the approved target.',
                'evidencePaths': [ref]}}}), None, None
        assert data['findings']['FINDING_0']['action'] == 'repair'
        assert data['findings']['FINDING_0']['evidencePaths'] == [
            '/draft/exercises/0', '/sourceMessages/SOURCE_0']
        review_context = data['context']
        artifact_modes = [component.get('progressionMode')
            for day in review_context['finalArtifact']['workouts'] for component in day['components']
            if component.get('type') == 'Exercise']
        assert 'AUTO_REGULATION' in artifact_modes
        assert 'app_native_rep_load_progression' in review_context['repairCapabilityContract']['codeOwnedBehaviors']
        return json.dumps({'findingAssessments': {'FINDING_0': {'disposition': 'repair',
            'repairDimensions': ['prescription'], 'repairObjectives': [], 'reason': 'Correct the typed effort.'}},
            'repairPlan': 'Correct the typed effort.'}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)
    reviewed = plan_review._review_complete_draft(None, context, result, messages, len(messages)-1, None)
    assert reviewed['requirementAssessments']['SOURCE_0']['findingIndexes'] == [0]
    assert reviewed['assessment']['groups'][0]['disposition'] == 'repair'


def test_exposure_change_citation_tracks_structured_source_identity():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    context = plan_review._context(result, messages, equipment, None, len(messages)-1)
    path = '/programmingSummary/exposures/LIBRARY_0'
    assert plan_review._blocker_change_cited(path,
        {'changedDraftPaths': ['/workouts/0/exercises/0/numWorkSets']}, context, result)
    assert not plan_review._blocker_change_cited(path,
        {'changedDraftPaths': ['/workouts/0/description']}, context, result)
    assert not plan_review._blocker_change_cited('/programmingSummary/exposures/LIBRARY_99',
        {'changedDraftPaths': ['/workouts/0/exercises/0/numWorkSets']}, context, result)
    assert not plan_review._blocker_change_cited(path, {'changedDraftPaths': []}, context, result)


def test_programming_summary_preserves_same_library_occurrence_identity():
    equipment, _, stored, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first['numWorkSets'] = 3
    second = copy.deepcopy(first)
    second.update(numWorkSets=2, minReps=6, maxReps=8, restBetweenSetsSeconds=120)
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(stored)

    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed'], result['errors']
    context = plan_review._context(result, messages, equipment, None, len(messages) - 1)
    summary = context['programmingSummary']

    assert set(summary) == {'sessions', 'exposures', 'timingAssumptions', 'executionTimeVerified',
        'techniqueLimitations', 'personalRecoveryAndTolerance'}
    exposure = summary['exposures']['LIBRARY_0']
    assert exposure['weeklyWorkingSets'] == 5
    assert [(item['exercise'], item['sets']) for item in exposure['occurrences']] == [
        ('EXERCISE_0', 3), ('EXERCISE_1', 2)]
    assert set(summary['sessions'][0]) == {'name', 'muscles', 'movementSets',
        'conservativeEstimatedSeconds', 'emittedPrescriptionEstimatedSeconds',
        'finalExerciseOrder', 'timingComponents'}
    assert summary['sessions'][0]['muscles']['chest'] == {
        'direct': 5, 'indirect': 0, 'effective': 5}


def test_review_distinguishes_selected_menu_from_equipment_eligible_library():
    equipment, _, stored, draft = planning_case()
    equipment['exerciseDefinitions'].extend([
        {'id': 'z_row', 'name': 'Row', 'exerciseType': 'REPS', 'equipmentId': None,
         'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['BACK'], 'secondaryMuscleGroups': [],
         'exerciseCategory': 'MODERATE_COMPOUND'},
        {'id': 'zz_loaded', 'name': 'Loaded press', 'exerciseType': 'REPS', 'equipmentId': 'UNOWNED',
         'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
         'exerciseCategory': 'HEAVY_COMPOUND'},
    ])
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed'], result['errors']

    context = plan_review._context(result, messages, equipment, None, len(messages) - 1)
    scope = context['librarySelectionScope']

    assert scope == {
        'eligibilityBasis': ['owned_equipment', 'required_accessories', 'approved_exclusions'],
        'eligibleDefinitionCount': 2,
        'selectedEligibleDefinitionCount': 1,
        'unselectedEligibleDefinitionCount': 1,
        'unselectedByMuscleGroup': {'BACK': 1},
        'eligibilityEstablishesSuitability': False,
    }
    from workout_generator_pkg.review_assessment import _CURRENT_DATA_ROOTS, _evidence_categories
    for projected in (plan_review._execution_review_context(context),
                      plan_review._evidence_review_context(context, [context['draft']['exercises'][0]['id']])):
        assert projected['librarySelectionScope'] == scope
        _, facts = plan_review._with_review_refs(projected)
        scope_refs = [reference for reference, path in facts.items() if path == '/librarySelectionScope']
        _, current_data = _evidence_categories(facts)
        assert scope_refs and scope_refs[0] in current_data
    assert '/librarySelectionScope' in _CURRENT_DATA_ROOTS


@pytest.mark.parametrize('provided', [False, True])
def test_export_parity_uses_reviewed_resource_identity_for_uuid_conversion(provided):
    from workout_generator_pkg.domain_ops import reviewable_workout_artifact
    equipment, _, stored, draft = planning_case()
    gear_uuid = '11111111-1111-4111-8111-111111111111'
    accessory_uuid = '22222222-2222-4222-8222-222222222222'
    gear_id = gear_uuid if provided else 'EQUIPMENT_0'
    accessory_id = accessory_uuid if provided else 'ACCESSORY_0'
    equipment['equipments'] = [{'id': gear_id, 'name': 'Weight vest', 'type': 'WEIGHTVEST',
        'availableWeights': [{'weight': 1}, {'weight': 2}]}]
    equipment['accessoryEquipments'] = [{'id': accessory_id, 'name': 'Support', 'type': 'ACCESSORY'}]
    equipment['exerciseDefinitions'][0].update(equipmentId=gear_id, requiredAccessoryEquipmentIds=[accessory_id])
    audited = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert audited['passed'], audited['errors']
    plan = audited['planIndex']
    expected = reviewable_workout_artifact(plan, 'Reviewed guidance')
    mapping = {'EQUIPMENT_0': gear_uuid, 'ACCESSORY_0': accessory_uuid,
        'EXERCISE_0': '33333333-3333-4333-8333-333333333333',
        'WORKOUT_0': '44444444-4444-4444-8444-444444444444'}
    def convert(value):
        if isinstance(value, dict):
            return {mapping.get(k, k): convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return mapping.get(value, value) if isinstance(value, str) else value
    actual = convert({'workouts': [{**day, 'workoutComponents': day['components']} for day in expected['workouts']]})
    assert reviewable_workout_artifact(plan, 'Reviewed guidance', actual, mapping) == expected
    actual['workouts'][0]['workoutComponents'][0]['equipmentId'] = '55555555-5555-4555-8555-555555555555'
    assert reviewable_workout_artifact(plan, 'Reviewed guidance', actual, mapping) != expected


def test_region_disclosure_is_code_owned_and_does_not_invent_subregion_attribution():
    from workout_generator_pkg.generation_audit import render_plan_disclosures
    report = {'weeklyVolume': {key: {'effective': 0, 'direct': 0, 'indirect': 0}
        for key in ('back', 'shoulders')}, 'workouts': [], 'weeklyWorkingSets': 0}
    original = copy.deepcopy(report)
    text = render_plan_disclosures(report)
    assert 'lats versus upper back' in text and 'separate exercise attribution' in text
    assert 'anterior, lateral and rear deltoids' in text
    assert 'anterior-delt-specific attribution and relative head development remain unverified' in text
    assert 'These descriptions add no credits or quotas.' in text
    assert report == original
    assert 'Shoulder detail' not in render_plan_disclosures(report, muscles=['back'])
