import copy
import json

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import plan_review
from workout_generator_pkg.planning_tools import PlanningInputError, _structured_repair_coverage
from workout_generator_pkg.planner_context import _finding_movement_references
from workout_generator_pkg.review_assessment import finding_redistribution_objective_choices
from workout_generator_pkg.review_subjects import (
    bind_review_subject_references, compile_review_subjects, render_review_judgment, review_subject_catalog, validate_review_subjects)
from test_workout_generator_single_review import setup_case, response_for


def subject_case():
    items = [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': 'FRONT', 'name': 'Front Squat', 'numWorkSets': 5},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'FRONT', 'name': 'Front Squat', 'numWorkSets': 3},
        {'id': 'EXERCISE_2', 'libraryDefinitionId': 'HACK', 'name': 'Hack Squat', 'numWorkSets': 2},
        {'id': 'EXERCISE_3', 'libraryDefinitionId': 'BACK', 'name': 'Back Squat', 'numWorkSets': 3},
    ]
    days = [{'name': name, 'timesCompletedInAWeek': 1, 'exerciseIds': ids}
        for name, ids in [('A', ['EXERCISE_0']), ('B', ['EXERCISE_1']), ('C', ['EXERCISE_2', 'EXERCISE_3'])]]
    context = {'draft': {'exercises': items, 'workouts': days, 'libraryDefinitions': {
        key: {'name': key} for key in ('FRONT', 'HACK', 'BACK')}},
        'programmingSummary': {'exposures': {'FRONT': {'weeklyWorkingSets': 8}}},
        'finalArtifact': {'workouts': [{'components': [{'type': 'Exercise', **items[i]}
            for i in indexes]} for indexes in ([0], [1], [2, 3])]}}
    refs = {'FRONT_FACT': '/programmingSummary/exposures/FRONT',
        'C_CONTEXT': '/finalArtifact/workouts/2', 'HACK_FACT': '/draft/exercises/2'}
    return context, refs


def test_subjects_preserve_exercise_identity_counts_and_absent_sessions():
    context, refs = subject_case()
    catalog = review_subject_catalog(context)
    selected, facts = compile_review_subjects(['FRONT'], catalog, context)
    assert selected == ['EXERCISE_0', 'EXERCISE_1']
    assert facts[0]['weeklyWorkingSets'] == 8
    assert [day['sets'] for day in facts[0]['sessionWorkingSets']] == [5, 3, 0]
    _, reason = render_review_judgment('fatigue_recovery', 'concentration_tradeoff', facts)
    assert 'Front Squat: 8 weekly sets' in reason and 'C 0' in reason
    assert 'Hack Squat' not in reason and '13' not in reason
    _, combined = compile_review_subjects(['FRONT', 'WORKOUT_2'], catalog, context)
    assert {item['name']: item['weeklyWorkingSets'] for item in combined} == {
        'Front Squat': 8, 'Hack Squat': 2, 'Back Squat': 3}


def test_subject_catalog_is_canonical_and_alias_binding_preserves_scope():
    context, facts = subject_case()
    catalog = review_subject_catalog(context)
    assert set(catalog) == {'FRONT', 'HACK', 'BACK', 'EXERCISE_0', 'EXERCISE_1',
        'EXERCISE_2', 'EXERCISE_3', 'WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2'}
    assert bind_review_subject_references(['FRONT_FACT', 'C_CONTEXT'], catalog, facts, context) == [
        'FRONT', 'WORKOUT_2']
    assert bind_review_subject_references(['EXERCISE_0'], catalog, facts, context) == ['EXERCISE_0']
    assert bind_review_subject_references(['UNKNOWN'], catalog, facts, context) == ['UNKNOWN']
    with pytest.raises(ValueError, match='Unknown review subjects'):
        compile_review_subjects(['UNKNOWN'], catalog, context)
    with pytest.raises(ValueError, match='distinct'):
        compile_review_subjects(bind_review_subject_references(['FRONT', 'FRONT'], catalog, facts, context),
            catalog, context)


@pytest.mark.parametrize('correction_kind', ['valid', 'unknown', 'empty', 'changed_disposition'])
def test_unknown_subject_recovery_changes_only_reference_fields(monkeypatch, correction_kind):
    equipment, messages, audited, _ = setup_case()
    original = None
    calls = []

    def respond(client, request, **options):
        nonlocal original
        schema = options['output_schema']
        if not calls:
            data = json.loads(request[-1]['content'])
            known = next(iter(data['reviewSubjects']))
            original = {'message': 'fatigue_recovery', 'reason': 'recovery_uncertainty',
                'subjectRefs': [known, 'UNKNOWN'],
                'evidenceRefs': [data['sourceMessages']['SOURCE_0']['_reviewRef']],
                'basis': 'uncertainty', 'disposition': 'advisory', 'errorKind': 'none',
                'concernGroup': 'NEW', 'decisionId': 'none'}
            payload = {'findings': [original], 'sourceCoverage': {
                key: True for key in schema['properties']['sourceCoverage']['properties']}}
            calls.append(known)
            return json.dumps(payload), None, None
        entry = schema['properties']['findingCorrections']['properties']['FINDING_0']
        assert set(entry['properties']) == {'subjectRefs'}
        assert 'findings' not in schema['properties']
        corrected = next(ref for ref in entry['properties']['subjectRefs']['items']['enum'] if ref != calls[0])
        calls.append(corrected)
        fields = {'subjectRefs': [corrected]}
        if correction_kind == 'unknown':
            fields['subjectRefs'] = ['UNKNOWN']
        elif correction_kind == 'empty':
            fields['subjectRefs'] = []
        elif correction_kind == 'changed_disposition':
            fields['disposition'] = 'repair'
        return json.dumps({'findingCorrections': {'FINDING_0': fields}}), None, None

    monkeypatch.setattr(plan_review, '_review_call', respond)
    result = plan_review.review_draft(None, audited, messages, equipment)
    assert len(calls) == 2
    if correction_kind != 'valid':
        assert not result['passed'] and result['review'].get('failure')
        return
    assert result['passed']
    finding = result['review']['findings'][0]
    assert finding['reviewConcern'] == original['message']
    assert finding['reviewJudgment'] == original['reason']
    assert finding['basis'] == original['basis'] and finding['action'] == 'advisory'
    assert finding['subjectRefs'] == calls
    assert result['review']['assessment']['groups'][0]['disposition'] == 'advisory'


def test_contextual_citations_cannot_expand_repair_subjects():
    context, _ = subject_case()
    front_refs = ['EXERCISE_0', 'EXERCISE_1']
    choices = [{'kind': 'redistribute_work', 'exerciseRefs': front_refs, 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_2'], 'minimumSessions': 2}]
    context['redistributionObjectiveChoices'] = choices
    finding = {'subjectExerciseRefs': front_refs,
        'subjectFacts': [{'definitionRef': 'FRONT'}],
        'evidencePaths': ['/finalArtifact/workouts/2', '/draft/exercises/2']}
    assert _finding_movement_references(finding, {}) == {'FRONT'}
    assert finding_redistribution_objective_choices(finding, context) == [choices[0]]
    source = {'workouts': [{'exercises': [{'definition_id': context['draft']['exercises'][int(ref.rsplit('_', 1)[1])]['libraryDefinitionId']}
        for ref in day['exerciseIds']]} for day in context['draft']['workouts']]}
    task = {'reviewFindings': [finding], 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['exercise_selection']}]}}
    patch = {'addressedFindingIndexes': [0], 'patch': [
        {'op': 'replace', 'path': '/workouts/2/exercises/0/definition_id', 'value': 'OTHER'}]}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        _structured_repair_coverage(patch, task, source)
    patch['patch'][0]['path'] = '/workouts/0/exercises/0/definition_id'
    _structured_repair_coverage(patch, task, source)


def test_production_review_selects_categories_and_code_renders_facts(monkeypatch):
    equipment, messages, audited, context = setup_case()
    calls = []

    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        schema = options['output_schema']
        subject = next(iter(data['reviewSubjects']))
        finding = {'message': 'fatigue_recovery', 'reason': 'recovery_uncertainty',
            'subjectRefs': [subject], 'evidenceRefs': [data['sourceMessages']['SOURCE_0']['_reviewRef']],
            'basis': 'uncertainty', 'disposition': 'advisory', 'errorKind': 'none',
            'concernGroup': 'NEW', 'decisionId': 'none'}
        payload = response_for(data, schema, [finding])
        false_claim = copy.deepcopy(payload)
        false_claim['findings'][0]['message'] = 'Front Squat has 13 weekly sets including Session C.'
        with pytest.raises(ValidationError):
            validate(false_claim, schema)
        calls.append(payload)
        return json.dumps(payload), None, None

    monkeypatch.setattr(plan_review, '_review_call', respond)
    result = plan_review.review_draft(None, audited, messages, equipment)
    assert result['passed'] and len(calls) == 1
    finding = result['review']['findings'][0]
    assert finding['subjectFacts'] and 'Code-owned exposure:' in finding['repair']
    validate_review_subjects(result['review'], context)
    plan_review._require_review_receipt(result, messages, equipment)
    tampered = copy.deepcopy(result['review'])
    tampered['findings'][0]['subjectFacts'][0]['weeklyWorkingSets'] = 13
    with pytest.raises(ValueError, match='subject facts'):
        validate_review_subjects(tampered, context)


def test_legacy_text_only_finding_cannot_supply_cached_factual_premises():
    context, _ = subject_case()
    with pytest.raises(ValueError, match='subjects'):
        validate_review_subjects({'findings': [{'message': 'Front Squat has 13 sets.'}]}, context)


def test_withdrawal_judgments_cannot_authorize_repairs_and_qualitative_edits_need_an_outcome(monkeypatch):
    equipment, messages, audited, context = setup_case()

    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        schema = options['output_schema']
        subject = next(iter(data['reviewSubjects']))
        payload = response_for(data, schema, [{'message': 'fatigue_recovery', 'reason': 'concentration_tradeoff',
            'subjectRefs': [subject], 'evidenceRefs': [data['sourceMessages']['SOURCE_0']['_reviewRef']],
            'basis': 'material_uncertainty', 'disposition': 'repair', 'errorKind': 'none',
            'concernGroup': 'NEW', 'decisionId': 'none', 'repairDimensions': ['prescription']}])
        invalid = copy.deepcopy(payload)
        invalid['findings'][0]['reason'] = 'contradicted_by_current_data'
        with pytest.raises(ValidationError):
            validate(invalid, schema)
        return json.dumps(payload), None, None

    monkeypatch.setattr(plan_review, '_review_call', respond)
    result = plan_review.review_draft(None, audited, messages, equipment)
    assert not result['passed']
    group = result['review']['assessment']['groups'][0]
    assert group['disposition'] == 'unresolved_capability' and group['repairDimensions'] == []
    tampered = copy.deepcopy(result['review'])
    tampered['findings'][0]['reviewJudgment'] = 'contradicted_by_current_data'
    with pytest.raises(ValueError, match='Withdrawal judgments'):
        validate_review_subjects(tampered, context)
