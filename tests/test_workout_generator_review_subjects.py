import copy
import json

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import plan_review
from workout_generator_pkg.planning_tools import PlanningInputError, _structured_repair_coverage, audit_workout_plan
from workout_generator_pkg.planner_context import _finding_movement_references
from workout_generator_pkg.review_assessment import finding_redistribution_objective_choices
from workout_generator_pkg.review_subjects import (
    bind_review_subject_references, compile_review_subjects, compile_review_execution_facts,
    render_review_judgment, review_subject_catalog, validate_review_subjects)
from test_workout_generator_single_review import setup_case, response_for


@pytest.mark.parametrize('status', ['compatible', 'unknown', 'incompatible'])
def test_access_confirmation_uses_exact_group_identities_and_preserves_real_station_conflicts(status):
    from workout_generator_pkg.review_subjects import superset_access_facts, confirmed_superset_access

    context, _ = subject_case()
    context['draft']['libraryDefinitions']['HACK'].update(id='hack', equipmentId='rack')
    context['draft']['libraryDefinitions']['BACK'].update(id='back', equipmentId='floor')
    context['finalArtifact']['workouts'][2]['components'] = [{'type': 'Superset', 'exercises': [
        {'id': 'EXERCISE_2'}, {'id': 'EXERCISE_3'}]}]
    rule = {'kind': 'supersetNoReconfiguration', 'coverageKey': None,
        'sharedResourceGroups': [['rack', 'bar']], 'confirmedIndependentPairs': [['hack', 'back']]}
    context['requirements'] = {'executionRules': [rule]}
    context['setupAccessBindings'] = [{'pair': ['hack', 'back'], 'sourceReferences': ['SOURCE_0']}]
    if status == 'unknown':
        rule['confirmedIndependentPairs'] = []
    elif status == 'incompatible':
        context['draft']['libraryDefinitions']['BACK']['equipmentId'] = 'bar'
    facts = superset_access_facts(context)
    assert len(facts) == 1 and facts[0]['status'] == status
    assert facts[0]['changeoverTimeVerified'] is False
    assert facts[0]['sourceReferences'] == ['SOURCE_0']
    assert facts[0]['bindingPaths'] == ['/setupAccessBindings/0']
    refs = ['EXERCISE_2', 'EXERCISE_3']
    assert bool(confirmed_superset_access(context, refs)) == (status == 'compatible')
    assert not confirmed_superset_access(context, ['EXERCISE_0', 'EXERCISE_2'])
    assert bool(confirmed_superset_access(context, ['EXERCISE_0', *refs],
        simultaneous_only=True)) == (status == 'compatible')
    assert not confirmed_superset_access(context, ['EXERCISE_0'], simultaneous_only=True)
    if status == 'compatible':
        with pytest.raises(ValueError, match='Confirmed simultaneous access'):
            validate_review_subjects({'findings': [{'subjectRefs': refs,
                'reviewJudgment': 'setup_simultaneous_access_uncertainty'}]}, context)
        context['draft']['libraryDefinitions']['HACK']['id'] = 'changed_configuration'
        assert not confirmed_superset_access(context, refs)


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
        'Front Squat': 8}
    session_refs, _ = compile_review_subjects(['WORKOUT_2'], catalog, context)
    assert session_refs == ['EXERCISE_2', 'EXERCISE_3']


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
                'qualitativeRationale': 'The selected recovery exposure lacks supporting personal history.',
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


def test_saved_setup_rationale_cannot_replace_code_owned_session_and_equipment_facts(monkeypatch):
    _, messages, audited, context = setup_case()
    rationale = ('The source asks for a program that is practical to set up and complete, but every session '
        'is eleven or more separate barbell/rack configurations at straight sets with no supersets, '
        'and preparation-task identity, rack return and station re-approach are unmeasured; '
        'the emitted notes assert a fixed one-minute changeover that no measurement supports, '
        'so actual elapsed time remains unknown rather than approximately seventy-five minutes.')
    template = context['draft']['exercises'][0]
    definition = template['libraryDefinitionId']
    context['draft']['libraryDefinitions'][definition]['equipmentId'] = 'vest'
    context['draft']['libraryDefinitions']['OTHER'] = {
        **context['draft']['libraryDefinitions'][definition], 'equipmentId': 'dumbbells'}
    context['equipment']['equipments'] = [
        {'id': 'vest', 'name': 'Vest', 'type': 'WEIGHTVEST'},
        {'id': 'dumbbells', 'name': 'Dumbbell pair', 'type': 'DUMBBELLS'}]
    context['draft']['exercises'] = []
    context['draft']['workouts'] = []
    context['finalArtifact']['workouts'] = []
    for index, count in enumerate((11, 11, 10)):
        items = [{**template, 'id': f'EXERCISE_{len(context["draft"]["exercises"]) + offset}',
            'libraryDefinitionId': definition if offset % 2 else 'OTHER'} for offset in range(count)]
        context['draft']['exercises'].extend(items)
        context['draft']['workouts'].append({'name': f'Session {index + 1}',
            'exerciseIds': [item['id'] for item in items]})
        context['finalArtifact']['workouts'].append({'name': f'Session {index + 1}',
            'components': [{'type': 'Exercise', 'id': item['id']} for item in items]})

    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        return json.dumps(response_for(data, options['output_schema'], [{
            'message': 'guidance_consistency', 'reason': 'unsupported_behavior',
            'qualitativeRationale': rationale, 'subjectRefs': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2'],
            'evidenceRefs': [data['finalArtifact']['_reviewRef']], 'basis': 'uncertainty',
            'disposition': 'advisory', 'errorKind': 'none', 'concernGroup': 'NEW', 'decisionId': 'none'}])), None, None

    monkeypatch.setattr(plan_review, '_review_call', respond)
    result = plan_review._review_complete_draft(None, context, audited, messages, len(messages) - 1, None)
    finding = result['findings'][0]
    assert finding['qualitativeRationale'] == rationale
    assert [day['exerciseOccurrences'] for day in finding['executionFacts']] == [11, 11, 10]
    for rendered in (finding['message'], finding['repair'], result['assessment']['groups'][0]['reason']):
        assert rationale not in rendered and 'barbell/rack configurations' not in rendered
        assert 'Session 3: 10 exercise occurrences' in rendered
        assert 'Vest (WEIGHTVEST)' in rendered and 'Dumbbell pair (DUMBBELLS)' in rendered
    validate_review_subjects(result, context)
    result['reviewBaseHash'] = plan_review._review_base_hash(context)
    result['reviewLedgerOutputFingerprint'] = plan_review._review_ledger_fingerprint(context)
    assert plan_review._review_cache_matches(result, context)
    tampered = copy.deepcopy(result)
    tampered['findings'][0]['message'] += ' Reviewer rationale: ' + rationale
    assert not plan_review._review_cache_matches(tampered, context)
    with pytest.raises(ValueError, match='rendered from code-owned'):
        validate_review_subjects(tampered, context)
    blocks = context['finalArtifact']['workouts'][0]['components']
    context['finalArtifact']['workouts'][0]['components'] = [
        {'type': 'Superset', 'exercises': blocks[:2]}, *blocks[2:]]
    updated = compile_review_execution_facts(finding['subjectExerciseRefs'], context)
    assert updated[0]['exerciseOccurrences'] == 11
    assert updated[0]['straightSetExercises'] == 9 and updated[0]['supersetGroups'] == 1
    with pytest.raises(ValueError, match='execution facts'):
        validate_review_subjects(result, context)


@pytest.mark.parametrize('judgment', ['execution_conflict', 'source_conflict'])
def test_review_rationale_survives_review_and_scoped_correction(monkeypatch, judgment):
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, requirements, draft = planning_case()
    messages = requirement_messages(requirements)
    audited = audit_workout_plan(draft, equipment, messages)
    # This test isolates review serialization from the unrelated fixture capability gate.
    audited['passed'] = True
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    context = plan_review._context(audited, messages, equipment, None, boundary)
    calls = []
    rationale = ('Two different loaded trunk movements overlap in the weekly plan.'
        if judgment == 'execution_conflict'
        else 'The source requires avoiding both loaded trunk movements in the same plan.')

    def respond(client, request, **options):
        schema = options['output_schema']
        if not calls:
            data = json.loads(request[-1]['content'])
            variants = schema['properties']['findings']['items']['anyOf']
            variant = next(item for item in variants
                if item['properties']['disposition']['enum'] == ['advisory'])
            assert 'qualitativeRationale' in variant['required']
            assert not {'EXERCISE_ID', 'FACT_REFERENCE'}.intersection(variant['properties'])
            finding = {'message': 'practical_execution', 'reason': judgment,
                'subjectRefs': [next(iter(data['reviewSubjects']))],
                'evidenceRefs': [data['sourceMessages']['SOURCE_0']['_reviewRef']],
                'basis': 'uncertainty', 'disposition': 'advisory', 'errorKind': 'none',
                'concernGroup': 'NEW', 'decisionId': 'none'}
            retained = {**finding, 'reason': 'role_mismatch', 'concernGroup': 'NEW',
                'qualitativeRationale': 'This selected movement does not support its intended role.'}
            calls.append('initial')
            proposal = {'findings': [finding, retained], 'sourceCoverage': {
                key: True for key in schema['properties']['sourceCoverage']['properties']}}
            return json.dumps(proposal), None, None
        assert schema['required'] == ['findingCorrections']
        correction = schema['properties']['findingCorrections']['properties']['FINDING_0']
        assert correction['required'] == ['qualitativeRationale']
        assert set(correction['properties']) == {'qualitativeRationale'}
        calls.append('correction')
        return json.dumps({'findingCorrections': {'FINDING_0': {'qualitativeRationale': rationale}}}), None, None

    monkeypatch.setattr(plan_review, '_review_call', respond)
    result = plan_review.review_draft(None, audited, messages, equipment)
    assert result['passed'] and calls == ['initial', 'correction'], (calls, result.get('review', {}).get('failure'))
    finding, retained = result['review']['findings']
    assert finding['qualitativeRationale'] == rationale
    assert rationale not in finding['message'] and rationale not in finding['repair']
    assert 'Code-owned exposure:' in finding['repair']
    assert retained['qualitativeRationale'] == 'This selected movement does not support its intended role.'
    validate_review_subjects(result['review'], context)
    assert _prior_rationale(finding) == finding['qualitativeRationale']
    cached = copy.deepcopy(result['review'])
    cached['findings'][0].pop('qualitativeRationale')
    assert not plan_review._review_cache_matches(cached, context)
    with pytest.raises(ValueError, match='preserve its reviewer rationale'):
        validate_review_subjects(cached, context)


def _prior_rationale(finding):
    return plan_review._prior_finding_summary(finding).get('qualitativeRationale')


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


def test_setup_findings_identify_missing_fact_without_expanding_exact_pair():
    from workout_generator_pkg.review_subjects import LIVE_JUDGMENTS

    context, _ = subject_case()
    catalog = review_subject_catalog(context)
    refs, facts = compile_review_subjects(['EXERCISE_2', 'WORKOUT_2'], catalog, context)
    assert refs == ['EXERCISE_2']
    assert 'setup_uncertainty' not in LIVE_JUDGMENTS
    rationale = 'The pair needs a usable open area alongside the station.'
    execution_facts = compile_review_execution_facts(refs, context)
    message, reason = render_review_judgment('equipment_setup', 'setup_floor_clearance_uncertainty', facts,
        execution_facts)
    assert 'clear floor space' in message and 'Hack Squat' in message
    assert 'Back Squat' not in message
    finding = {'subjectRefs': ['EXERCISE_2', 'WORKOUT_2'], 'subjectExerciseRefs': refs,
        'subjectWorkoutRefs': ['WORKOUT_2'], 'subjectFacts': facts,
        'reviewConcern': 'equipment_setup', 'reviewJudgment': 'setup_floor_clearance_uncertainty',
        'qualitativeRationale': rationale, 'message': message, 'repair': reason, 'executionFacts': execution_facts}
    validate_review_subjects({'findings': [finding], 'assessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'unresolved_capability'}]}}, context)
    _, timing = render_review_judgment('equipment_setup', 'setup_changeover_time_uncertainty', facts)
    assert 'unmeasured estimate, not a user-confirmed time' in timing
