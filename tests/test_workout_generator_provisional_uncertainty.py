import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import plan_review, review_assessment as assessment
from workout_generator_pkg.repair_capabilities import repair_capability_contract


RUN_DIR = Path('build/workout_joint_priority_solver_20261023/incumbent_handoff_e2e_20261023')
MIXED_RUN_DIR = Path('build/workout_joint_priority_solver_20261023/soft_tradeoff_evidence_e2e_20261023')


def _saved_case():
    summary = json.loads((RUN_DIR / 'validation_summary.json').read_text(encoding='utf-8'))
    log_path = RUN_DIR / 'logs/conversation_2ce00164.log'
    request_line = next(line for line in log_path.read_text(encoding='utf-8').splitlines()
        if '[request] independent_plan_review: ' in line)
    context = json.loads(request_line.split('[request] independent_plan_review: ', 1)[1])
    fact_paths = {}

    def index_facts(value, path=''):
        if isinstance(value, dict):
            if isinstance(value.get('_reviewRef'), str):
                fact_paths[value['_reviewRef']] = path
            for key, child in value.items():
                if key != '_reviewRef':
                    escaped = str(key).replace('~', '~0').replace('/', '~1')
                    index_facts(child, path + '/' + escaped)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                index_facts(child, path + '/' + str(index))

    index_facts(context)
    finding = copy.deepcopy(summary['discoveryFindings'][3])
    saved_assessment = summary['assessment']['findingAssessments']['FINDING_3']
    raw_fact_refs = list(finding['evidencePaths'])
    evidence_paths = [fact_paths[reference] for reference in raw_fact_refs]
    assert '/programmingSummary/sessions/0/timingComponents' in evidence_paths
    assert '/programmingSummary/sessions/2/timingComponents' in evidence_paths
    finding.update(severity='blocking', path=evidence_paths[0], evidencePaths=evidence_paths)
    context['repairCapabilityContract'] = repair_capability_contract()
    review = {'inputHash': 'retained-e2e-review', 'findings': [finding],
        'scopeResults': {'execution': {'findings': [copy.deepcopy(finding)]}}}
    return finding, saved_assessment, context, review, raw_fact_refs


def _current_context():
    log_path = next((MIXED_RUN_DIR / 'logs').glob('conversation_*.log'))
    request_line = next(line for line in log_path.read_text(encoding='utf-8').splitlines()
        if '[request] independent_plan_review: ' in line)
    context = json.loads(request_line.split('[request] independent_plan_review: ', 1)[1])
    context['repairCapabilityContract'] = repair_capability_contract()
    return context


def _timing_finding(context, session_index, *, concern_group='NEW_3'):
    path = f'/programmingSummary/sessions/{session_index}/timingComponents'
    return {'severity': 'blocking', 'basis': 'material_uncertainty', 'action': 'repair',
        'concernGroup': concern_group, 'path': path, 'evidencePaths': [path]}


def test_retained_estimate_uncertainty_can_be_adjudicated_and_canonicalized(monkeypatch):
    finding, saved_assessment, context, review, raw_fact_refs = _saved_case()
    assert raw_fact_refs == ['FACT_94', 'FACT_112', 'FACT_805', 'FACT_879',
        'FACT_882', 'FACT_883', 'FACT_511', 'FACT_561']
    captured = []

    def call(_client, _request, **kwargs):
        schema = kwargs['output_schema']
        entry = schema['properties']['findingAssessments']['properties']['FINDING_0']
        advisory = next(variant for variant in entry['anyOf']
            if variant['properties']['disposition']['enum'] == ['advisory'])
        assert 'authorityEvidenceRefs' not in advisory['properties']
        assert 'currentDataEvidenceRefs' not in advisory['properties']
        captured.append(True)
        return json.dumps({'findingAssessments': {'FINDING_0': {
            'disposition': 'advisory', 'repairDimensions': [], 'repairObjectives': [],
            'reason': saved_assessment['reason']}}, 'repairPlan': ''}), None, None

    monkeypatch.setattr(assessment, '_review_call', call)
    assessed = assessment.assess_findings(None, context, review, single_attempt=True,
        evidence_context=context)
    review['assessment'] = assessed
    assert captured == [True]
    assert '/reviewAuthority' in assessed['groups'][0]['evidencePaths']
    assert '/programmingSummary/sessions/2/timingComponents' in assessed['groups'][0]['evidencePaths']
    assert review['findings'][0]['basis'] == 'material_uncertainty'
    assessment.canonicalize_provisional_advisories(review, context)
    assert review['findings'][0]['basis'] == 'uncertainty'
    assert review['findings'][0]['severity'] == 'warning'
    assert review['findings'][0]['action'] == 'advisory'
    assert review['scopeResults']['execution']['findings'][0] == review['findings'][0]
    assert assessment.validate_assessment(review, context) is review['assessment']


def test_carried_material_uncertainty_remains_blocking():
    finding, _, context, review, _ = _saved_case()
    finding['concernGroup'] = 'ISSUE_3'
    assessment_group = {'findingIndexes': [0], 'disposition': 'advisory',
        'repairDimensions': [], 'repairObjectives': [], 'reason': 'An estimate concern.',
        'evidencePaths': ['/reviewAuthority', '/programmingSummary/sessions/2/timingComponents']}
    review['assessment'] = {'version': assessment.VERSION,
        'inputHash': assessment.assessment_hash(review), 'groups': [assessment_group],
        'repairPlan': ''}
    with pytest.raises(ValueError, match='blocking finding'):
        assessment.validate_assessment(review, context)


def test_supported_timing_repair_cannot_be_classified_as_missing_capability():
    context = _current_context()
    finding = _timing_finding(context, 0)
    allowed = assessment._allowed_dispositions(finding, context)
    assert 'repair' in allowed
    assert 'unresolved_capability' not in allowed
    assert assessment._provisional_timing_repair_available(finding, context)

    # A cited session without a superset, or without known distinct member
    # equipment, keeps the existing unsupported-capability disposition.
    assert 'unresolved_capability' in assessment._allowed_dispositions(
        _timing_finding(context, 1), context)
    session = context['draft']['workouts'][2]
    group = session['supersetGroups'][0]
    exercises = {item['id']: item for item in context['draft']['exercises']}
    definitions = context['draft']['libraryDefinitions']
    member_definitions = [definitions[exercises[exercise_id]['libraryDefinitionId']]
        for exercise_id in group['exerciseIds']]
    known_id = member_definitions[0]['equipmentId']
    for definition in member_definitions:
        definition['equipmentId'] = known_id
        definition['requiredAccessoryEquipmentIds'] = []
    session['supersetGroups'] = [group]
    assert 'unresolved_capability' in assessment._allowed_dispositions(
        _timing_finding(context, 2), context)

    unknown_context = _current_context()
    unknown_session = unknown_context['draft']['workouts'][0]
    unknown_group = unknown_session['supersetGroups'][0]
    unknown_exercises = {item['id']: item for item in unknown_context['draft']['exercises']}
    unknown_definitions = unknown_context['draft']['libraryDefinitions']
    for exercise_id in unknown_group['exerciseIds']:
        definition = unknown_definitions[unknown_exercises[exercise_id]['libraryDefinitionId']]
        definition['equipmentId'] = None
        definition['requiredAccessoryEquipmentIds'] = ['UNKNOWN_EQUIPMENT']
    assert 'unresolved_capability' in assessment._allowed_dispositions(
        _timing_finding(unknown_context, 0), unknown_context)

    incomplete_timing_context = _current_context()
    incomplete_timing = incomplete_timing_context['programmingSummary']['sessions'][0]['timingComponents']
    incomplete_timing.pop('supersetRoundSetup', None)
    assert 'unresolved_capability' in assessment._allowed_dispositions(
        _timing_finding(incomplete_timing_context, 0), incomplete_timing_context)

    carried = _timing_finding(context, 2, concern_group='ISSUE_3')
    assert 'unresolved_capability' in assessment._allowed_dispositions(carried, context)


def test_reduced_model_context_does_not_reopen_code_owned_timing_capability(monkeypatch):
    context = _current_context()
    finding = _timing_finding(context, 0)
    review = {'inputHash': 'retained-e2e-review', 'findings': [finding]}
    evidence_context = copy.deepcopy(context)
    evidence_context.pop('draft')
    observed = {}

    def respond(_client, request, **kwargs):
        schema = kwargs['output_schema']
        entry = schema['properties']['findingAssessments']['properties']['FINDING_0']
        dispositions = {branch['properties']['disposition']['enum'][0]
            for branch in entry['anyOf']}
        observed['dispositions'] = dispositions
        observed['model_saw_draft'] = '"draft"' in request[-1]['content']
        return json.dumps({'findingAssessments': {'FINDING_0': {
            'disposition': 'repair', 'repairDimensions': ['session_timing'],
            'repairObjectives': [], 'reason': 'Use the supported rest repair.'}},
            'repairPlan': 'Normalize the selected superset transition.'}), None, None

    monkeypatch.setattr(assessment, '_review_call', respond)
    review['assessment'] = assessment.assess_findings(None, context, review,
        single_attempt=True, evidence_context=evidence_context)
    assert 'unresolved_capability' not in observed['dispositions']
    assert 'repair' in observed['dispositions']
    assert observed['model_saw_draft'] is False
    assert assessment.validate_assessment(review, context)


def test_material_unknown_without_governing_authority_stays_blocking():
    finding, _, context, review, _ = _saved_case()
    context.pop('reviewAuthority')
    review['assessment'] = {'version': assessment.VERSION,
        'inputHash': assessment.assessment_hash(review), 'groups': [{
            'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
            'repairObjectives': [], 'reason': 'The cumulative time risk remains unresolved.',
            'evidencePaths': ['/programmingSummary/sessions/2/timingComponents']}], 'repairPlan': ''}
    with pytest.raises(ValueError, match='code-owned review authority'):
        assessment.validate_assessment(review, context)


def test_personal_capability_unknown_cannot_use_generic_authority_and_current_data():
    finding, _, context, review, _ = _saved_case()
    finding.update(path='/draft/workouts/0/exercises/0',
        evidencePaths=['/draft/workouts/0/exercises/0'])
    review['assessment'] = {'version': assessment.VERSION,
        'inputHash': assessment.assessment_hash(review), 'groups': [{
            'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
            'repairObjectives': [], 'reason': 'Personal capability is unknown.',
            'evidencePaths': ['/reviewAuthority', '/draft/workouts/0/exercises/0']}], 'repairPlan': ''}
    with pytest.raises(ValueError, match='structured timing evidence'):
        assessment.validate_assessment(review, context)
