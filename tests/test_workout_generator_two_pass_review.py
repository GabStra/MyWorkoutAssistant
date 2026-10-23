import copy
import json
from dataclasses import FrozenInstanceError

import pytest
from jsonschema import validate, ValidationError

from workout_generator_pkg import api_client, plan_review as review
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def setup_case():
    equipment, _, requirements, draft = planning_case()
    messages = requirement_messages(requirements)
    audited = audit_workout_plan(draft, equipment, messages)
    assert audited['passed']
    return equipment, messages, audited


def concern(data):
    ref = data['draft']['exercises'][0]['_reviewRef']
    return {'concernGroup': 'NEW_0', 'basis': 'uncertainty', 'severity': 'warning',
        'evidencePaths': [ref], 'decisionId': None, 'action': 'repair',
        'message': 'The prescribed effort conflicts with the approved target.'}


def assessment(disposition='repair', *, single_attempt=True):
    group = {'disposition': disposition,
        'repairDimensions': ['prescription'] if disposition == 'repair' else [],
        'repairObjectives': [],
        'reason': 'Correct the conflicting typed effort.' if disposition == 'repair' else 'Optional preference only.'}
    if single_attempt:
        group['evidenceRefs'] = []
        if disposition == 'repair':
            group['repairDimensions'] = ['prescription']
        return {'findingAssessments': {'FINDING_0': group},
            'repairPlan': 'Correct the typed effort while preserving the approved target.' if disposition == 'repair' else ''}
    group.update(findingIndexes=[0], errorKind='none', authorityEvidenceRefs=[], currentDataEvidenceRefs=[])
    return {'groups': [group],
        'repairPlan': 'Correct the typed effort while preserving the approved target.' if disposition == 'repair' else ''}


def test_review_failure_logs_the_exception_chain_for_masked_errors():
    class Logger:
        def __init__(self):
            self.entries = []
        def log(self, message):
            self.entries.append(message)

    cause = ValueError('unresolved reference')
    cause.ref = '#/$def/reference'
    error = FrozenInstanceError()
    error.__context__ = cause
    logger = Logger()
    assert review._review_failure(error, logger, 'independent_plan_review') == 'FrozenInstanceError: '
    assert logger.entries == [
        'independent_plan_review exception chain: FrozenInstanceError <- ValueError (ref=#/$def/reference)']


def discovery_payload(findings, data, options):
    payload = {'findings': findings}
    sources = options['output_schema']['properties'].get('requirementAssessments', {}).get('properties', {})
    if sources:
        payload['requirementAssessments'] = {key: {'status': 'supported',
            'reason': 'The controlled numerical fixture satisfies its source set target.',
            'evidencePaths': [data['audit']['_reviewRef']]} for key in sources}
    return payload


@pytest.mark.parametrize('disposition', ['repair', 'advisory', 'clarify'])
def test_two_calls_separate_discovery_from_disposition_and_ownership(monkeypatch, disposition):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        assert options['retry'] is False
        calls.append(data)
        if 'context' not in data:
            fields = options['output_schema']['properties']['findings']['items']['properties']
            assert set(fields) == {'message', 'evidencePaths', 'decisionId', 'action',
                                   'basis', 'concernGroup'}
            assessment_schema = options['output_schema']['properties']['requirementAssessments']['properties']['SOURCE_0']
            citation_items = assessment_schema['properties']['evidencePaths']['items']
            assert citation_items['type'] == 'string' and citation_items['enum']
            assert '$ref' not in json.dumps(options['output_schema'])
            finding = concern(data)
            finding['action'] = disposition
            payload = discovery_payload([finding], data, options)
        else:
            assert data['findings']['FINDING_0']['action'] == disposition
            item_schema = options['output_schema']['properties']['findingAssessments']['properties']['FINDING_0']
            assessment_disposition = 'repair' if disposition == 'clarify' else disposition
            fields = (item_schema.get('properties') or next(variant['properties'] for variant in item_schema['anyOf']
                if variant['properties']['disposition']['enum'] == [assessment_disposition]))
            assert 'authorityEvidenceRefs' not in fields and 'currentDataEvidenceRefs' not in fields
            assert 'unsupportedBehavior' not in request[0]['content']
            assert 'repairObjectives' in fields
            assert '_reviewRef' in json.dumps(data['context']['draft'])
            payload = assessment(assessment_disposition)
            payload['findingAssessments']['FINDING_0'] = {
                key: value for key, value in payload['findingAssessments']['FINDING_0'].items() if key in fields}
        validate(payload, options['output_schema'])
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    monkeypatch.setattr(review, '_confirm_review_corrections', lambda *a, **k: pytest.fail('No third call'))
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert len(calls) == 2
    assert 'assessment' in result['review'], result['review'].get('failure')
    assert result['passed'] is (disposition == 'advisory')
    assert result['review']['assessment']['groups'][0]['disposition'] == ('repair' if disposition == 'clarify' else disposition)
    assert result['review']['findings'][0]['action'] == disposition
    if disposition == 'repair':
        assert result['errors'][0]['repair'] == assessment()['repairPlan']
        assert result['errors'][0]['draftPath'].endswith('/exercises/0')
    if disposition == 'clarify':
        from workout_generator_pkg.interactive_shell import _preparation_repair_tools
        names = [tool['function']['name'] for tool in _preparation_repair_tools({'errors': result['errors']})]
        assert 'ask_user' in names


def test_no_concerns_needs_one_call_and_receipt_is_reusable(monkeypatch):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(*args, **kwargs):
        calls.append(args)
        data = json.loads(args[1][-1]['content'])
        return json.dumps(discovery_payload([], data, kwargs)), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert result['passed'] and len(calls) == 1
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'audit', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(result['submittedDraft'])}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(result)}])
    review._require_review_receipt(result, messages, equipment)
    assert review.review_draft(None, audited, messages, equipment, two_pass=True)['passed']
    assert len(calls) == 1


def test_discovery_prose_citations_keep_their_meaning_after_assessment_renumbering(monkeypatch):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        calls.append(data)
        if 'context' not in data:
            item = concern(data)
            ref = data['audit']['_reviewRef']
            item['message'] = f'Check the audit ({ref}); FACT_999999 is unsupported.'
            return json.dumps(discovery_payload([item], data, options)), None, None
        finding = data['findings']['FINDING_0']
        assert finding['message'] == 'Check the audit (/audit); unresolved reviewer citation is unsupported.'
        assert finding['evidencePaths'] == ['/draft/exercises/0']
        assert finding['path'] == '/draft/exercises/0'
        payload = assessment()
        validate(payload, options['output_schema'])
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert len(calls) == 2, result.get('review')
    assert result['review']['assessment']['groups'][0]['evidencePaths'] == ['/draft/exercises/0']


@pytest.mark.parametrize('bad_stage', ['discovery', 'assessment'])
def test_invalid_output_fails_closed_without_form_correction(monkeypatch, bad_stage):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(client, request, **kwargs):
        data = json.loads(request[-1]['content']); calls.append(data)
        return (json.dumps(discovery_payload([concern(data)], data, kwargs)) if bad_stage == 'assessment' and len(calls) == 1
            else '{"unexpected":true}'), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert not result['passed'] and result['review']['failure'] and 'preview' not in result
    assert len(calls) == (1 if bad_stage == 'discovery' else 2)


def test_projection_omits_obsolete_previews_and_unrelated_loads_without_mutating_evidence(monkeypatch):
    equipment, messages, audited = setup_case()
    messages.extend([{'role': 'assistant', 'canonicalAlternativePreview': 'ALT_old', 'content': 'Obsolete draft'},
        {'role': 'assistant', 'content': 'Which interpretation?'}, {'role': 'user', 'content': 'The first one.'}])
    boundary = len(messages)-1
    context = review._context(audited, messages, equipment, None, boundary)
    context['history']['LIBRARY_0'] = {'status': 'found', 'sessions': [{'load': 10}],
        'relatedMovementHistory': [{'reference': 'LIBRARY_99', 'name': 'Other lift', 'load': 100}]}
    context['history']['LIBRARY_99'] = {'name': 'Other lift', 'sessions': [{'load': 100}]}
    context['history']['LIBRARY_98'] = {'name': 'Unrelated lift', 'sessions': [{'load': 200}]}
    original = copy.deepcopy(context)
    calls = []
    def respond(client, request, **kwargs):
        data = json.loads(request[-1]['content']); calls.append(data)
        if 'context' not in data:
            assert 'LIBRARY_99' not in data['history']
            assert 'load' not in data['history']['LIBRARY_0']['relatedMovementHistory'][0]
            sources = str(data['sourceMessages'])
            assert 'Obsolete draft' not in sources and 'Which interpretation?' in sources and 'The first one.' in sources
            item = concern(data)
            item['evidencePaths'] = [data['audit']['_reviewRef']]
            return json.dumps({'findings': [item]}), None, None
        assert data['context']['history']['LIBRARY_0']['relatedMovementHistory'][0]['load'] == 100
        assert 'LIBRARY_99' in data['context']['history']
        assert 'LIBRARY_98' not in data['context']['history']
        return json.dumps(assessment()), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review._review_complete_draft(None, context, audited, messages, boundary, None)
    assert len(calls) == 2 and result['assessment']['groups'][0]['disposition'] == 'repair'
    assert context == original


@pytest.mark.parametrize('status,disposition', [('resolved_by_change', 'repair'), ('open', 'advisory')])
def test_carried_blocker_cannot_be_dropped_or_demoted(monkeypatch, status, disposition):
    equipment, messages, audited = setup_case()
    context = review._context(audited, messages, equipment, None, len(messages)-1)
    context['reviewChecklist'] = {'findings': {'OBLIGATION_test': {
        'finding': {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
            'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0'],
            'message': 'A prior contradiction.', 'repair': 'Correct the cue.', 'muscleTargets': []},
        'changedDraftPaths': [], 'sourceCount': 100}}}
    calls = []
    def respond(client, request, **kwargs):
        data = json.loads(request[-1]['content']); calls.append(data)
        if 'context' in data:
            return json.dumps(assessment(disposition)), None, None
        payload = {'findings': [], 'blockerResolutions': {'ISSUE_0': {
            'status': status, 'reason': 'The cue is unchanged.',
            'evidencePaths': [data['draft']['exercises'][0]['_reviewRef']]}}}
        requirement_schema = kwargs['output_schema']['properties'].get('requirementAssessments', {}).get('properties', {})
        if requirement_schema:
            payload['requirementAssessments'] = {key: {'status': 'supported',
                'reason': 'The approved requirement is represented.',
                'evidencePaths': [data['audit']['_reviewRef']]} for key in requirement_schema}
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    def adjudicate(client, assessment_context, receipt, logger=None, **kwargs):
        item = receipt['findings'][0]
        if disposition == 'advisory':
            return {'version': review.ASSESSMENT_VERSION, 'inputHash': review.assessment_hash(receipt),
                'groups': [{'findingIndexes': [0], 'disposition': 'advisory',
                    'repairDimensions': [], 'repairObjectives': [],
                    'reason': 'This is only a preference.', 'errorKind': 'none',
                    'authorityEvidenceRefs': [], 'evidencePaths': [item['path'], *item['evidencePaths']]}],
                'repairPlan': ''}
        return {'version': review.ASSESSMENT_VERSION, 'inputHash': review.assessment_hash(receipt),
            'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                'repairDimensions': ['prescription'], 'repairObjectives': [],
                'reason': 'The prior contradiction remains actionable.', 'errorKind': 'none',
                'authorityEvidenceRefs': [], 'evidencePaths': [item['path'], *item['evidencePaths']]}],
            'repairPlan': 'Preserve the requirement while correcting the contradiction.'}
    monkeypatch.setattr(review, 'assess_findings', adjudicate)
    if status == 'resolved_by_change':
        result = review._review_complete_draft(None, context, audited, messages, len(messages)-1, None)
        assert result['scopeResults']['execution']['blockerResolutions']['OBLIGATION_test']['status'] == 'open'
        assert result['findings'][0]['severity'] == 'blocking'
        assert result['assessment']['groups'][0]['disposition'] == 'repair'
    else:
        with pytest.raises(ValueError, match='cannot waive'):
            review._review_complete_draft(None, context, audited, messages, len(messages)-1, None)
    assert len(calls) == 1



def test_disputed_withdrawal_stops_without_fabricating_confirmation(monkeypatch):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(client, request, **kwargs):
        data = json.loads(request[-1]['content']); calls.append(data)
        if 'context' not in data:
            item = concern(data)
            return json.dumps(discovery_payload([item], data, kwargs)), None, None
        payload = assessment('withdrawn_review_error')
        group = payload['findingAssessments']['FINDING_0']
        group.update(errorKind='contradicted_by_current_data',
            evidenceRefs=[data['context']['requirements']['_reviewRef']])
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    confirmations = []
    def cannot_confirm(*args):
        confirmations.append(True)
        raise ValueError('Missing responsible independent review confirmation.')
    monkeypatch.setattr(review, '_confirm_review_corrections', cannot_confirm)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert not result['passed'] and len(calls) == 2 and confirmations == [True]
    assert 'responsible independent review' in result['review']['failure']


def test_default_path_uses_bounded_review_without_a_harness_override(monkeypatch):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(*args, **kwargs):
        calls.append(args)
        data = json.loads(args[1][-1]['content'])
        return json.dumps(discovery_payload([], data, kwargs)), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    monkeypatch.setattr(review, '_review_part', lambda *a, **k: pytest.fail('No split-review fan-out by default'))
    result = review.review_draft(None, audited, messages, equipment)
    assert result['passed'] and len(calls) == 1


def test_explicit_split_review_remains_available_for_comparison(monkeypatch):
    equipment, messages, audited = setup_case()
    monkeypatch.setattr(review, '_review_complete_draft', lambda *a: pytest.fail('Explicit split-review control'))
    monkeypatch.setattr(review, '_review_part', lambda *a, **k: {'findings': []})
    result = review.review_draft(None, audited, messages, equipment, two_pass=False)
    assert result['passed']


@pytest.mark.parametrize('route', ['two_pass', 'execution', 'confirmation'])
def test_every_review_route_keeps_historical_addresses_out_of_current_citations(monkeypatch, route):
    equipment, messages, audited = setup_case()
    boundary = len(messages)-1
    context = review._context(audited, messages, equipment, None, boundary)
    prior = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
        'path': '/draft/exercises/999', 'evidencePaths': ['/draft/exercises/999'],
        'draftPath': '/workouts/0/exercises/999', 'reviewScope': 'execution',
        'message': 'Old cue at FACT_998 (/draft/exercises/999) on EXERCISE_999 conflicts with the stop rule.',
        'repair': 'Correct /workouts/0/exercises/999/placementNotes.', 'muscleTargets': []}
    changes = ['/workouts/0/exercises/0/minReps']
    context['reviewChecklist'] = {'findings': {'OBLIGATION_old': {'finding': prior,
        'references': [], 'changedDraftPaths': changes, 'sourceCount': 100}},
        'changedDraftPaths': changes, 'sourceCount': 100}
    context['acceptedStructureReview'] = {'passed': True, 'version': 1, 'inputHash': 'old',
        'findings': [copy.deepcopy(prior)], 'scopeResults': {'execution': {'findings': [copy.deepcopy(prior)]}}}
    original = copy.deepcopy(context)
    calls = []
    def respond(client, request, **options):
        data = json.loads(request[-1]['content']); calls.append(data)
        summary = data['previousBlockingFindings']['ISSUE_0']
        assert not {'path', 'evidencePaths', 'draftPath', 'newConflictEvidencePaths'} & summary.keys()
        for past in (summary, data['acceptedStructureReview']):
            text = json.dumps(past)
            assert '/draft/exercises/999' not in text and '/workouts/0' not in text
            assert 'FACT_998' not in text and 'EXERCISE_999' not in text
            assert 'conflicts with the stop rule' in text
        current = data['draft']['exercises'][0]['_reviewRef']
        assert current in data['previousBlockingChangedPaths']['ISSUE_0']
        allowed = options['output_schema']['$def']['reference']['enum']
        assert set(data['previousBlockingChangedPaths']['ISSUE_0']) <= set(allowed)
        item = {'status': 'resolved_by_change', 'reason': 'The affected cue changed.', 'evidencePaths': [current]}
        if route == 'execution':
            item['action'] = 'none'
        elif route == 'confirmation':
            item.update(status='withdrawn_review_error', disposition='withdrawn_review_error',
                repairDimensions=[])
        payload = {'findings': [], 'blockerResolutions': {'ISSUE_0': item}}
        validate(payload, options['output_schema'])
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    if route == 'two_pass':
        result = review._review_complete_draft(None, context, audited, messages, boundary, None)
        assert not result['findings']
    else:
        part = review._with_blocker_checklist('execution', review._execution_review_context(context), context)
        if route == 'confirmation':
            part['confirmationOnly'] = True
        result = review._review_part(None, 'execution', part, context, audited, messages, boundary, None)
        assert result['blockerResolutions']['OBLIGATION_old']['status'] != 'open'
    assert len(calls) == 1 and context == original


@pytest.mark.parametrize('failure', ['missing_authority', 'decision_is_not_source', 'invalid_path', 'invented_citation'])
def test_code_carried_evidence_does_not_supply_missing_proof(monkeypatch, failure):
    from workout_generator_pkg.review_assessment import assess_findings
    context = {'draft': {'exercises': [{}]}, 'requirements': {}, 'resolvedDecisions': {'DECISION_0': {}}}
    finding = {'severity': 'warning', 'action': 'repair', 'path': '/draft/exercises/0',
        'evidencePaths': ['/draft/exercises/0'], 'message': 'Check this cue.'}
    payload = assessment('withdrawn_review_error' if failure in ('missing_authority', 'decision_is_not_source') else 'advisory',
        single_attempt=False)
    if failure in ('missing_authority', 'decision_is_not_source'):
        payload['groups'][0]['errorKind'] = 'contradicted_by_current_data'
        if failure == 'decision_is_not_source':
            finding['evidencePaths'].append('/resolvedDecisions/DECISION_0')
    elif failure == 'invalid_path':
        finding['evidencePaths'] = ['/draft/nonexistent']
    else:
        payload['groups'][0]['authorityEvidenceRefs'] = ['FACT_999999']
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    original = copy.deepcopy(finding)
    with pytest.raises((ValueError, KeyError, ValidationError)):
        assess_findings(None, context, {'inputHash': 'current', 'findings': [finding]}, single_attempt=True)
    assert calls == [1, 1] and finding == original


def test_retry_false_prevents_connection_retry_and_reasoning_fallback(monkeypatch):
    error = api_client.TruncatedResponseError.__new__(api_client.TruncatedResponseError)
    error.diagnostics = {'cause': 'reasoning_budget_exhausted'}
    attempts = []
    def call(*args, **kwargs):
        attempts.append(kwargs)
        raise error
    monkeypatch.setattr(api_client, '_chat_call_once', call)
    with pytest.raises(api_client.TruncatedResponseError):
        api_client.chat_call(None, [], retry=False)
    assert len(attempts) == 1


def test_two_pass_assessment_uses_strict_provider_shape_and_full_local_validation(monkeypatch):
    from types import SimpleNamespace
    from workout_generator_pkg.review_assessment import assess_findings

    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    monkeypatch.setattr(review, 'chat_call', api_client.chat_call)
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        arguments = json.dumps({'findingAssessments': {'FINDING_0': {'disposition': 'repair',
            'repairDimensions': [], 'repairObjectives': [], 'reason': 'A correction is needed.',
            'resolution': {'kind': 'candidate_edit',
                'requirementPaths': [], 'unsupportedBehavior': None}}}, 'repairPlan': ''})
        call = SimpleNamespace(function=SimpleNamespace(name='emit_result', arguments=arguments))
        message = SimpleNamespace(content=None, tool_calls=[call], reasoning_content=None)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=message)], usage=None)

    completions = SimpleNamespace(create=create)
    configured = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = SimpleNamespace(with_options=lambda **_: configured)
    review_receipt = {'inputHash': 'review-input', 'findings': [{'severity': 'blocking',
        'action': 'repair', 'path': '/draft/workouts/0', 'evidencePaths': ['/draft/workouts/0'],
        'message': 'The correction needs a supported repair.'}]}

    with pytest.raises(ValueError, match='repair dimension'):
        assess_findings(client, {'draft': {'workouts': [{}]}, 'evaluationContract': {'active': True}},
            review_receipt, single_attempt=True)

    request = requests[0]
    provider_schema = request['tools'][0]['function']['parameters']
    group_schema = provider_schema['properties']['findingAssessments']['properties']['FINDING_0']
    variants = group_schema['anyOf']
    repair_variant = next(variant for variant in variants
        if variant['properties']['disposition']['enum'] == ['repair'])
    withdrawal_variant = next(variant for variant in variants
        if variant['properties']['disposition']['enum'] == ['withdrawn_review_error'])
    assert request['tools'][0]['function']['strict'] is True
    assert request['extra_body']['thinking']['type'] == 'disabled'
    assert 'reasoning_effort' not in request
    assert provider_schema['type'] == 'object'
    assert 'allOf' not in json.dumps(provider_schema)
    assert 'uniqueItems' not in json.dumps(provider_schema)
    assert 'minItems' not in json.dumps(provider_schema)
    assert 'authorityEvidenceRefs' not in repair_variant['properties']
    assert {'evidenceRefs', 'errorKind'} <= set(withdrawal_variant['required'])
    assert {'type': 'null'} in repair_variant['properties']['resolution']['properties'][
        'unsupportedBehavior']['anyOf']


def test_assessment_wire_excludes_illegal_dispositions_from_saved_failure(monkeypatch):
    from pathlib import Path
    from workout_generator_pkg.review_assessment import assess_findings, _allowed_dispositions
    from workout_generator_pkg.api_client import _strict_parameters_compatible
    root = Path('build/workout_joint_priority_solver_20261023/fresh_review_boundary_continuation1_20261023')
    saved = json.loads((root / 'independent_findings_assessment_response.json').read_text(encoding='utf-8'))
    discovery = json.loads((root / 'independent_plan_review_response.json').read_text(encoding='utf-8'))
    findings = [{**item, 'severity': review._finding_severity(item),
        'path': '/draft/workouts/0', 'evidencePaths': ['/draft/workouts/0']}
        for item in discovery['findings']]
    # Include advisory and nonblocking repairable concerns to check both directions.
    findings.extend([{'severity': 'warning', 'action': action, 'path': '/draft/workouts/0',
        'evidencePaths': ['/draft/workouts/0'], 'message': 'Controlled concern.'}
        for action in ('advisory', 'repair')])
    calls = []
    class Captured(Exception):
        pass
    def respond(client, request, **options):
        calls.append(options)
        schema = options['output_schema']
        assert _strict_parameters_compatible(schema)
        entries = schema['properties']['findingAssessments']['properties']
        for index, finding in enumerate(findings):
            offered = {v['properties']['disposition']['enum'][0]
                       for v in entries[f'FINDING_{index}']['anyOf']}
            assert offered == _allowed_dispositions(finding)
        assert 'advisory' not in _allowed_dispositions(findings[2])
        assert 'advisory' not in _allowed_dispositions(findings[3])
        assert _allowed_dispositions(findings[4]) == {'advisory', 'withdrawn_review_error'}
        assert len(_allowed_dispositions(findings[5])) == 4
        payload = copy.deepcopy(saved)
        for index in (4, 5):
            payload['findingAssessments'][f'FINDING_{index}'] = {
                'disposition': 'advisory', 'repairDimensions': [], 'repairObjectives': [], 'reason': 'Optional.'}
        with pytest.raises(ValidationError):
            validate(payload, schema)
        for index in (2, 3):
            payload['findingAssessments'][f'FINDING_{index}']['disposition'] = 'unresolved_capability'
        validate(payload, schema)
        raise Captured
    monkeypatch.setattr(review, '_review_call', respond)
    with pytest.raises(Captured):
        assess_findings(None, {'draft': {'workouts': [{}]}},
            {'inputHash': 'saved-boundary', 'findings': findings}, single_attempt=True)
    assert len(calls) == 1 and calls[0]['retry'] is False


@pytest.mark.parametrize('invalid_reference', [False, True])
def test_discovery_metadata_cannot_override_canonical_review(monkeypatch, invalid_reference):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        calls.append(data)
        if 'context' not in data:
            fields = options['output_schema']['properties']['findings']['items']['properties']
            assert 'severity' not in fields
            refs = fields['evidencePaths']['items']['enum'][:9]
            assert len(refs) == 9
            item = concern(data)
            item.update(basis='established_violation', severity='warning',
                evidencePaths=[*refs, refs[0]], disposition='advisory')
            if invalid_reference:
                item['evidencePaths'].append('FACT_unknown')
            payload = discovery_payload([item], data, options)
            payload.update(type='json_object', assessment={'disposition': 'advisory'})
            return json.dumps(payload), None, None
        finding = data['findings']['FINDING_0']
        assert finding['severity'] == 'blocking'
        assert 'disposition' not in finding
        assert len(finding['evidencePaths']) == 9
        assert len(set(finding['evidencePaths'])) == 9
        return json.dumps(assessment()), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    monkeypatch.setattr(review, '_confirm_review_corrections', lambda *a, **k: pytest.fail('No formatting repair'))
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert not result['passed']
    if invalid_reference:
        assert len(calls) == 1
        assert result['review']['failure']
    else:
        assert len(calls) == 2
        assert result['review']['assessment']['groups'][0]['disposition'] == 'repair'


@pytest.mark.parametrize('shared_evidence,disposition', [(True, 'repair'), (True, 'advisory'), (False, 'repair')])
def test_source_correction_links_shared_evidence_without_synthetic_findings(monkeypatch, shared_evidence, disposition):
    equipment, messages, audited = setup_case()
    calls = []
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        calls.append(data)
        if 'context' in data:
            return json.dumps(assessment(disposition)), None, None
        item = concern(data)
        payload = discovery_payload([item], data, options)
        for entry in payload['requirementAssessments'].values():
            entry.update(status='needs_correction',
                evidencePaths=item['evidencePaths'] if shared_evidence else [data['audit']['_reviewRef']])
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert not result['passed']
    assert len(calls) == (2 if shared_evidence else 1)
    if shared_evidence and disposition == 'repair':
        assert len(result['review']['findings']) == 1
        assert result['review']['requirementAssessments']['SOURCE_0']['findingIndexes'] == [0]
    else:
        assert result['review']['failure']


def test_carried_finding_rebinds_current_citations_after_artifact_reordering(monkeypatch):
    equipment, messages, audited = setup_case()
    context = review._context(audited, messages, equipment, None, len(messages)-1)
    prior = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair',
        'path': '/finalArtifact/workouts/0/components/999', 'draftPath': '/workouts/0/exercises/999',
        'evidencePaths': ['/finalArtifact/workouts/0/components/999'],
        'message': 'Retained execution concern.', 'repair': 'Correct it.', 'muscleTargets': []}
    context['reviewChecklist'] = {'findings': {'OBLIGATION_test': {
        'finding': prior, 'changedDraftPaths': [], 'sourceCount': 100}}}
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        if 'context' not in data:
            requirement_schema = options['output_schema']['properties']['requirementAssessments']['properties']
            payload = {'findings': [], 'blockerResolutions': {'ISSUE_0': {
                'status': 'open', 'reason': 'The current occurrence still needs correction.',
                'evidencePaths': [data['draft']['exercises'][0]['_reviewRef']]}},
                'requirementAssessments': {key: {'status': 'supported',
                    'reason': 'The approved source is represented.',
                    'evidencePaths': [data['audit']['_reviewRef']]} for key in requirement_schema}}
            return json.dumps(payload), None, None
        finding = data['findings']['FINDING_0']
        assert finding['path'] == '/draft/exercises/0'
        assert finding['draftPath'] == '/workouts/0/exercises/0'
        return json.dumps(assessment()), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review._review_complete_draft(None, context, audited, messages, len(messages)-1, None)
    assert result['findings'][0]['path'] == '/draft/exercises/0'
    assert result['assessment']['groups'][0]['disposition'] == 'repair'
    assert prior['path'].endswith('/999') and prior['draftPath'].endswith('/999')


def test_qualitative_source_identity_is_explicit_and_does_not_depend_on_accounting_ledger(monkeypatch):
    equipment, _, stored, draft = planning_case()
    stored['sourceMessages'] = [
        {'messageIndex': 0, 'role': 'user', 'content': 'Plan 5-6 chest sets. Prioritize progression headroom.'},
        {'messageIndex': 1, 'role': 'user', 'content': 'Keep recovery manageable.'}]
    messages = requirement_messages(stored)
    audited = audit_workout_plan(draft, equipment, messages)
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        keys = options['output_schema']['properties']['requirementAssessments']['required']
        assert keys == ['SOURCE_0', 'SOURCE_1']
        assert 'requirementAccounting' not in data['requirements']
        by_reference = {key: data['sourceMessages'][key]['_reviewRef'] for key in keys}
        return json.dumps({'findings': [], 'requirementAssessments': {
            key: {'status': 'insufficient_evidence',
                'reason': data['sourceMessages'][key]['content'],
                'evidencePaths': [by_reference[key]]} for key in keys}}), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    checks = result['review']['requirementAssessments']
    assert checks['SOURCE_0']['reason'] == 'Plan 5-6 chest sets. Prioritize progression headroom.'
    assert checks['SOURCE_1']['reason'] == 'Keep recovery manageable.'


def test_source_assessment_cannot_be_omitted_but_legacy_ledger_receipts_still_validate():
    from workout_generator_pkg.review_assessment import VERSION, assessment_hash, validate_assessment

    def receipt(checks):
        review_receipt = {'findings': [], 'requirementAssessments': checks,
            'inputHash': 'input', 'assessment': {'version': VERSION, 'groups': [], 'repairPlan': ''}}
        review_receipt['assessment']['inputHash'] = assessment_hash(review_receipt)
        return review_receipt

    source_context = {'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Keep recovery manageable.'}},
        'requirements': {}}
    with pytest.raises(ValueError, match='source block'):
        validate_assessment(receipt({}), source_context)

    legacy_context = {'sourceMessages': source_context['sourceMessages'], 'requirements': {
        'requirementAccounting': [{'enforcement': 'semantic_check'}]}}
    validate_assessment(receipt({'0': {'status': 'supported', 'reason': 'Reviewed.', 'findingIndexes': []}}),
        legacy_context)


def test_discovery_reads_rendered_guidance_once_in_exact_final_artifact(monkeypatch):
    equipment, messages, audited = setup_case()
    original = copy.deepcopy(audited)
    def respond(client, request, **options):
        data = json.loads(request[-1]['content'])
        occurrence = data['draft']['exercises'][0]
        final = data['finalArtifact']['workouts'][0]['components'][0]
        assert final['id'] == occurrence['id']
        assert final['notes'] == original['planIndex']['exercises'][0]['notes']
        assert 'notes' not in occurrence
        assert 'programGuidance' not in data['draft']
        assert data['finalArtifact']['programGuidance']
        assert occurrence['coachingAuthority']['effortAcceptance']
        for key in ('generatedProgression', 'generatedEffortAcceptance'):
            assert not occurrence['coachingAuthority'].get(key)
        requirement_schema = options['output_schema']['properties']['requirementAssessments']['properties']
        payload = {'findings': [], 'requirementAssessments': {
            key: {'status': 'supported', 'reason': 'The approved source is represented.',
                'evidencePaths': [data['audit']['_reviewRef']]} for key in requirement_schema}}
        blocker_schema = options['output_schema']['properties'].get('blockerResolutions', {})
        if blocker_schema.get('properties'):
            payload['blockerResolutions'] = {}
        return json.dumps(payload), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    result = review.review_draft(None, audited, messages, equipment, two_pass=True)
    assert result['passed'], result.get('review', {}).get('failure')
    assert audited == original
