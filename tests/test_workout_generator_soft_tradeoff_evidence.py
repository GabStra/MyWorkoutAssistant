import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import plan_review, review_assessment


RUN = Path('build/workout_joint_priority_solver_20261023/soft_tradeoff_evidence_e2e_20261023')


def _saved_case():
    log = next((RUN / 'logs').glob('conversation_*.log'))
    request_line = next(line for line in log.read_text(encoding='utf-8').splitlines()
        if '[request] independent_plan_review: ' in line)
    context_with_refs = json.loads(request_line.split('[request] independent_plan_review: ', 1)[1])
    facts = {}

    def visit(value, path=''):
        if isinstance(value, dict):
            if isinstance(value.get('_reviewRef'), str):
                facts[value['_reviewRef']] = path
            for key, child in value.items():
                if key != '_reviewRef':
                    escaped = str(key).replace('~', '~0').replace('/', '~1')
                    visit(child, path + '/' + escaped)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + '/' + str(index))

    visit(context_with_refs)

    def strip_refs(value):
        if isinstance(value, dict):
            return {key: strip_refs(child) for key, child in value.items() if key != '_reviewRef'}
        if isinstance(value, list):
            return [strip_refs(child) for child in value]
        return value

    context = strip_refs(context_with_refs)
    discovery = json.loads((RUN / 'independent_plan_review_response.json').read_text(encoding='utf-8'))
    assessment = json.loads((RUN / 'independent_findings_assessment_response.json').read_text(encoding='utf-8'))
    findings, answers = [], []
    for index, finding in enumerate(discovery['findings']):
        if finding['basis'] != 'soft_tradeoff':
            continue
        finding = copy.deepcopy(finding)
        finding['evidencePaths'] = [facts[reference] for reference in finding['evidencePaths']]
        finding['path'] = finding['evidencePaths'][0]
        findings.append(finding)
        answer = copy.deepcopy(assessment['findingAssessments'][f'FINDING_{index}'])
        # The retained model answered the previous wire shape; replay its judgment
        # with citation fields omitted because current Python owns those paths.
        answer.pop('authorityEvidenceRefs', None)
        answer.pop('currentDataEvidenceRefs', None)
        answers.append(answer)
    assert len(findings) == 3
    return context, findings, answers


def _review_with_group(context, finding, evidence_paths):
    review = {'inputHash': 'saved-review', 'findings': [copy.deepcopy(finding)]}
    review['assessment'] = {'version': review_assessment.VERSION,
        'inputHash': review_assessment.assessment_hash(review), 'repairPlan': '',
        'groups': [{'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
            'repairObjectives': [], 'reason': 'This is a supported optional tradeoff.',
            'evidencePaths': evidence_paths}]}
    return review


@pytest.mark.parametrize('authority_paths,valid', [
    (['/sourceMessages/SOURCE_0', '/programmingGuidelines'], True),
    (['/programmingGuidelines'], False),
])
def test_policy_support_does_not_replace_user_source_authority(authority_paths, valid):
    context, findings, _ = _saved_case()
    finding = findings[0]
    current_path = next(path for path in finding['evidencePaths']
        if path.startswith(('/programmingSummary/', '/audit/', '/draft/', '/finalArtifact/')))
    review = _review_with_group(context, finding, [*authority_paths, current_path])
    if valid:
        assert review_assessment.validate_assessment(review, context)
    else:
        with pytest.raises(ValueError, match='approved source authority'):
            review_assessment.validate_assessment(review, context)


def test_valid_source_authority_without_current_plan_evidence_is_rejected():
    context, findings, _ = _saved_case()
    review = _review_with_group(context, findings[0], [
        '/sourceMessages/SOURCE_0', '/programmingGuidelines'])
    with pytest.raises(ValueError, match='current-plan evidence'):
        review_assessment.validate_assessment(review, context)
