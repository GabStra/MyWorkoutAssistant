import json
import pytest

from workout_generator_pkg import interactive_shell, plan_review
from workout_generator_pkg.interactive_shell import handle_function_call
from workout_generator_pkg.planning_decisions import resolved_decisions, saved_decisions
from workout_generator_pkg.planning_tools import requirements_approved, requirement_sources, set_workout_requirements
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _repair_reply(original, repaired):
    if not isinstance(original, dict):
        patch = [{'op': 'replace', 'path': '', 'value': repaired}]
    else:
        patch = [{'op': 'remove', 'path': '/' + key} for key in original.keys() - repaired.keys()]
        patch += [{'op': 'replace' if key in original else 'add', 'path': '/' + key, 'value': value}
                  for key, value in repaired.items() if key not in original or original[key] != value]
    return json.dumps({'patches': [patch]})


def test_schema_invalid_transport_reply_keeps_valid_blockers_during_finding_repair(monkeypatch):
    from jsonschema import ValidationError
    from workout_generator_pkg.api_client import StructuredResponseError
    first={'severity':'blocking','basis':'established_violation','path':'/draft',
        'message':'First issue.','evidencePaths':['/sourceMessages/SOURCE_0'],'repair':'Fix first issue.'}
    second={**first,'message':'Second issue.','repair':'Fix second issue.'}
    calls=[]
    def respond(client,request,**options):
        calls.append(1)
        if len(calls)==1:
            raise StructuredResponseError(json.dumps({'findings':[first,{**second,'extra':True}]}),ValidationError('extra field'))
        return json.dumps({'patches': [[{'op': 'remove', 'path': '/extra'}]]}),None,None
    monkeypatch.setattr(plan_review,'chat_call',respond)
    content,_,_=plan_review._review_call(None,[])
    findings=plan_review._validated_findings(None,[],content,lambda item:item,None,'test')
    assert len(calls)==2 and findings==[first,second]


def _review_truncation(cause='reasoning_budget_exhausted'):
    from workout_generator_pkg.api_client import TruncatedResponseError
    error = TruncatedResponseError.__new__(TruncatedResponseError)
    error.diagnostics = {
        'cause': cause,
        'usage': {'completion_tokens_details': {'reasoning_tokens': 7000}},
        'reasoningContent': 'Checked all original source requirements and found one omitted rule.',
        'toolCalls': [],
    }
    ValueError.__init__(error, 'synthetic review truncation')
    return error


def test_review_call_accepts_initial_review_without_retry(monkeypatch):
    calls = []

    def respond(_client, _request, **options):
        calls.append(options)
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    result, _, _ = plan_review._review_call(None, [{'role': 'user', 'content': 'source'}],
        reasoning_effort='low', max_tokens=8192, retry=True)

    assert json.loads(result) == {'findings': []}
    assert len(calls) == 1
    assert calls[0]['reasoning_effort'] == 'low' and calls[0]['retry'] is False


def test_review_call_recovers_reasoning_only_truncation_with_original_source_and_strict_schema(monkeypatch):
    from workout_generator_pkg.api_client import _strict_parameters_compatible
    schema = plan_review._strict_review_schema({'FACT_0': '/sourceMessages/SOURCE_0/content'})
    source_request = [
        {'role': 'system', 'content': 'Review source requirements.'},
        {'role': 'user', 'content': '{"sourceMessages":{"SOURCE_0":"do not reconfigure"}}'},
    ]
    calls = []

    def respond(_client, request, **options):
        calls.append((request, options))
        if len(calls) == 1:
            raise _review_truncation()
        assert request[:2] == source_request
        assert 'do not reconfigure' in json.dumps(request)
        assert 'Checked all original source requirements' in request[-1]['content']
        assert options['reasoning_effort'] is None and options['retry'] is False
        assert options['output_schema'] is schema and _strict_parameters_compatible(schema)
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    result, _, _ = plan_review._review_call(None, source_request,
        reasoning_effort='low', max_tokens=8192, retry=True, output_schema=schema)

    assert json.loads(result) == {'findings': []}
    assert len(calls) == 2
    assert calls[0][1]['retry'] is False and calls[0][1]['reasoning_effort'] == 'low'


def test_review_call_does_not_retry_again_after_recovery_truncates(monkeypatch):
    calls = []

    def respond(_client, _request, **_options):
        calls.append(1)
        raise _review_truncation()

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    with pytest.raises(Exception, match='synthetic review truncation'):
        plan_review._review_call(None, [{'role': 'user', 'content': 'original source'}],
            reasoning_effort='low', max_tokens=8192, retry=True,
            output_schema=plan_review._strict_review_schema({'FACT_0': '/source'}))

    assert len(calls) == 2


def test_review_serialization_keeps_evidence_before_changing_draft():
    context={'draft':{'exercises':[{'reps':8}]},'history':[{'reps':10}],
        'requirements':{'weeklySets':15},'audit':{'passed':True}}
    request,facts=plan_review._with_review_refs(context)
    revised={**context,'draft':{'exercises':[{'reps':9}]}}
    second,second_facts=plan_review._with_review_refs(revised)
    first_json,second_json=map(json.dumps,(request,second))
    assert first_json[:first_json.index('"draft"')] == second_json[:second_json.index('"draft"')]
    assert facts == second_facts and '/draft/exercises/0' in facts.values()
    assert request['history'][0]['reps'] == 10 and context['draft']['exercises'][0]['reps'] == 8


def test_review_references_do_not_advertise_the_uncitable_context_wrapper():
    from workout_generator_pkg.review_assessment import _evidence_categories
    context = {'requirements': {'coverage': [{'key': 'press'}]},
               'draft': {'exercises': [{'name': 'Press'}]}}
    request, facts = plan_review._with_review_refs(context)
    authority, current_data = _evidence_categories(facts)
    assert '_reviewRef' not in request and '' not in facts.values()
    assert request['requirements']['_reviewRef'] in authority
    assert request['draft']['_reviewRef'] in current_data
    assert '_reviewRef' not in context


def test_independent_review_uses_compact_semantic_refs_mapped_to_exact_paths():
    context = {
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Three days weekly.'}},
        'requirements': {'sessionsPerWeek': 3, 'executionRules': [{'kind': 'rest'}]},
        'finalArtifact': {'workouts': [
            {'name': 'Full Body A', 'components': [{'type': 'Superset', 'exercises': [
                {'type': 'Exercise', 'id': 'EXERCISE_0'}]}]},
            {'name': 'Full Body B', 'components': [{'type': 'Superset', 'exercises': [
                {'type': 'Exercise', 'id': 'EXERCISE_1'}]}]}],
            'programGuidance': 'Use the prescribed rest.'},
        'programmingSummary': {
            'sessions': [{'name': 'Full Body A', 'timingComponents': {'estimatedTotalSeconds': 4571}},
                         {'name': 'Full Body B', 'timingComponents': {'estimatedTotalSeconds': 4000}}],
            'exposures': {'LIBRARY_229': {'occurrences': [{'workingSets': 5}]}}},
        'history': {'LIBRARY_229': {'status': 'missing'}},
        'audit': {'workouts': [{'name': 'Full Body A'}, {'name': 'Full Body B'}]},
        'draft': {'exercises': [{'id': 'EXERCISE_0'}, {'id': 'EXERCISE_1'}],
                  'libraryDefinitions': {'LIBRARY_229': {'name': 'Nordic Curl'}}},
    }
    request, facts = plan_review._with_semantic_review_refs(context)

    assert facts['FINAL_ARTIFACT'] == '/finalArtifact'
    assert facts['FINAL_SESSION_A'] == '/finalArtifact/workouts/0'
    assert facts['FINAL_BLOCK_A_0'] == '/finalArtifact/workouts/0/components/0'
    assert facts['FINAL_EXERCISE_A_0_0'] == '/finalArtifact/workouts/0/components/0/exercises/0'
    assert facts['SUMMARY_SESSION_A'] == '/programmingSummary/sessions/0'
    assert facts['SUMMARY_EXPOSURE_LIBRARY_229'] == '/programmingSummary/exposures/LIBRARY_229'
    assert facts['HISTORY_LIBRARY_229'] == '/history/LIBRARY_229'
    assert facts['EXERCISE_0'] == '/draft/exercises/0'
    assert 'FACT_4571' not in facts and all(not key.startswith('FACT_') for key in facts)
    assert request['finalArtifact']['workouts'][0]['_reviewRef'] == 'FINAL_SESSION_A'
    assert request['programmingSummary']['sessions'][0]['_reviewRef'] == 'SUMMARY_SESSION_A'
    assert '_reviewRef' not in request['programmingSummary']['sessions'][0]['timingComponents']
    assert not plan_review._specific_changed_review_evidence('/finalArtifact')
    assert not plan_review._specific_changed_review_evidence('/finalArtifact/workouts/0')
    assert not plan_review._specific_changed_review_evidence('/finalArtifact/workouts/0/components/0', context)
    assert plan_review._specific_changed_review_evidence('/finalArtifact/workouts/0/components/0/exercises/0')


def test_saved_invalid_advisory_ref_is_rejected_then_corrected_without_changing_judgment():
    from pathlib import Path
    from jsonschema import ValidationError, validate

    fixture = Path(__file__).parent / 'fixtures' / 'workout_review_invalid_evidence.json'
    saved = json.loads(fixture.read_text(encoding='utf-8'))
    assert 'FACT_4571' in saved['findings'][0]['evidenceRefs']

    facts = {'FINAL_SESSION_A': '/finalArtifact/workouts/0',
             'SUMMARY_SESSION_A': '/programmingSummary/sessions/0'}
    evidence_schema = {'type': 'array', 'items': {'type': 'string', 'enum': sorted(facts)}}
    response_schema = {'type': 'object', 'properties': {'findings': {'type': 'array', 'items': {
        'anyOf': [{'type': 'object', 'properties': {
            'disposition': {'type': 'string', 'enum': ['advisory']},
            'evidenceRefs': evidence_schema},
            'required': ['disposition', 'evidenceRefs'], 'additionalProperties': True}]}}},
        'required': ['findings'], 'additionalProperties': True}
    with pytest.raises(ValidationError):
        validate(saved, response_schema)
    validate(saved, plan_review._review_schema_for_reference_salvage(response_schema))

    correction_schema = plan_review._review_correction_schema(saved, response_schema, {}, facts, [])
    assert set(correction_schema['properties']['findingCorrections']['properties']) == {'FINDING_0', 'FINDING_1'}
    correction = {'findingCorrections': {
        'FINDING_0': {'evidenceRefs': ['FINAL_SESSION_A']},
        'FINDING_1': {'evidenceRefs': ['SUMMARY_SESSION_A']}}}
    merged = plan_review._merge_review_correction(saved, correction, correction_schema, facts)

    assert [item['message'] for item in merged['findings']] == [item['message'] for item in saved['findings']]
    assert [item['disposition'] for item in merged['findings']] == [item['disposition'] for item in saved['findings']]
    assert [item['evidenceRefs'] for item in merged['findings']] == [
        ['FINAL_SESSION_A'], ['SUMMARY_SESSION_A']]
    assert facts[merged['findings'][0]['evidenceRefs'][0]] == '/finalArtifact/workouts/0'
    assert 'FACT_4571' not in facts


def test_audit_capability_guidance_respects_explicit_combined_region_agreement():
    from workout_generator_pkg.generation_audit import audit_policy, muscle_metadata_policy
    supported = {
        'back': ['BACK_UPPER_BACK'],
        'shoulders': ['BACK_DELTOIDS', 'FRONT_DELTOIDS'],
    }
    metadata_guidance = muscle_metadata_policy(supported)['interpretation']
    audit_guidance = audit_policy(supported)['capabilityLimits']

    for guidance in (metadata_guidance, audit_guidance):
        assert 'without explicit' in guidance
        assert 'Do not infer extra muscles' in guidance or 'do not infer subdivisions' in guidance
    assert 'When explicit agreement authorizes a combined target' in audit_guidance
    assert 'apply only the agreed aggregate target' in audit_guidance
    assert 'does not make their separate set totals auditable' in audit_guidance


def test_strict_review_schema_restricts_citations_without_mutating_local_validation():
    import copy
    from jsonschema import validate,ValidationError
    from workout_generator_pkg.api_client import _strict_parameters_compatible
    original=copy.deepcopy(plan_review._PLAN_RESPONSE)
    schema=plan_review._strict_review_schema({'FACT_0':'','FACT_1':'/draft'},original)
    finding={'severity':'blocking','basis':'established_violation','path':'FACT_1','message':'Missing exercise.',
        'evidencePaths':['FACT_0'],'repair':'Restore exercise.','action':'repair','decisionId':None,
        'newConflictEvidencePaths':[],'muscleTargets':[]}
    validate({'findings':[finding]},schema)
    assert original==plan_review._PLAN_RESPONSE
    with pytest.raises(ValidationError):
        validate({'findings':[{**finding,'path':'FACT_999'}]},schema)
    with pytest.raises(ValidationError):
        validate({'findings':[{**finding,'unexpected':True}]},schema)
    assert _strict_parameters_compatible(schema)
    assert '$def' not in schema
    decision_id = schema['properties']['findings']['items']['properties']['decisionId']
    assert set(decision_id) == {'anyOf', 'description'}
    assert decision_id['anyOf'] == [
        {'type': 'string', 'pattern': '^DECISION_[0-9]+$'}, {'type': 'null'}]
    def check(value):
        if isinstance(value,dict):
            assert not {'minLength','maxLength','minItems','maxItems','uniqueItems'} & value.keys()
            if value.get('type')=='object':
                assert set(value['required'])==set(value['properties']) and value['additionalProperties'] is False
            for child in value.values(): check(child)
        elif isinstance(value,list):
            for child in value: check(child)
    check(schema)


@pytest.mark.parametrize('malformed', ['bad item', None, []])
def test_finding_repair_accepts_non_object_entries_and_keeps_valid_blockers(monkeypatch, malformed):
    blocker = {'severity': 'blocking', 'path': '/draft/exercises/0',
        'message': 'The exercise conflicts with the requested plan.',
        'evidencePaths': ['/sourceMessages/SOURCE_0'], 'repair': 'Replace the exercise.'}
    repaired = {'severity': 'warning', 'path': '/draft/exercises/1',
        'message': 'The exercise could use more detail.',
        'evidencePaths': ['/sourceMessages/SOURCE_0'], 'repair': 'Add the missing detail.'}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (_repair_reply(malformed, repaired), None, None))

    findings = plan_review._validated_findings(None, [], json.dumps({'findings': [blocker, malformed]}),
        lambda finding: finding, None, 'test')

    assert findings == [blocker, repaired]


@pytest.mark.parametrize('field', ['message', 'repair', 'basis'])
def test_reference_repair_cannot_rewrite_other_valid_finding_fields(monkeypatch, field):
    blocker = {'severity': 'blocking', 'path': '/draft', 'basis': 'established_violation',
        'message': 'A confirmed requirement is violated.', 'evidencePaths': ['/source'], 'repair': 'Restore the requirement.'}
    invalid = {**blocker, 'path': '/invalid'}
    corrected = {**invalid, 'path': '/draft', field: 'Different finding.' if field != 'basis' else 'uncertainty'}
    calls = []
    def respond(client, request, **kwargs):
        calls.append(1)
        permissions = json.loads(request[-1]['content'])['invalidFindings'][0]['permittedPaths']
        assert '/path' in permissions['exact'] and '/message' not in permissions['exact']
        return _repair_reply(invalid, corrected), None, None
    def normalize(finding):
        if finding['path'] == '/invalid':
            raise ValueError('Invalid reference.')
        return finding
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    with pytest.raises(plan_review.ReviewOutputError) as error:
        plan_review._validated_findings(None, [], json.dumps({'findings': [blocker, invalid]}), normalize, None, 'test')
    assert error.value.findings == [blocker] and calls == [1]


def test_fixing_a_finding_schema_error_does_not_authorize_retargeting_it(monkeypatch):
    original = {'severity': 'blocking', 'path': '/draft/exercises/0', 'message': '',
        'evidencePaths': ['/source'], 'repair': 'Restore the requirement.'}
    repaired = {**original, 'message': 'The requirement is violated.', 'path': '/draft/exercises/1'}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (_repair_reply(original, repaired), None, None))
    with pytest.raises(plan_review.ReviewOutputError, match='outside allowed error'):
        plan_review._validated_findings(None, [], json.dumps({'findings': [original]}), lambda f: f, None, 'test')


@pytest.mark.parametrize('rewrite_evidence', [False, True])
def test_missing_muscle_targets_repair_preserves_evidence_scope(monkeypatch, rewrite_evidence):
    original = {'basis': 'uncertainty', 'severity': 'warning', 'action': 'clarify', 'path': 'FACT_486',
        'message': 'Session duration depends on declared setup assumptions.',
        'evidencePaths': ['FACT_517'], 'repair': 'Disclose the timing uncertainty.'}
    repaired = {**original, 'muscleTargets': []}
    if rewrite_evidence:
        repaired['evidencePaths'] = ['FACT_486', 'FACT_517']

    def respond(client, request, **options):
        correction = json.loads(request[-1]['content'])
        assert 'Do not repeat unchanged fields' in correction['task']
        assert correction['invalidFindings'][0]['permittedPaths'] == {
            'exact': ['/muscleTargets'], 'descendants': ['/muscleTargets']}
        return _repair_reply(original, repaired), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    def validate_findings():
        return plan_review._validated_findings(None, [], json.dumps({'findings': [original]}),
            lambda finding: finding, None, 'test', schema=plan_review._PLAN_RESPONSE,
            finding_schema=plan_review._PLAN_FINDING)

    if rewrite_evidence:
        with pytest.raises(plan_review.ReviewOutputError, match='outside allowed error'):
            validate_findings()
    else:
        assert validate_findings() == [repaired]


@pytest.mark.parametrize('stage', ['requirements', 'decision', 'joint'])
@pytest.mark.parametrize('basis,severity,passed', [
    ('established_violation', 'warning', False), ('uncertainty', 'blocking', True)])
def test_all_review_stages_classify_severity_from_basis(monkeypatch, stage, basis, severity, passed):
    equipment, arguments, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Keep the requested workout targets.'}]
    candidate = set_workout_requirements(arguments, messages, equipment)
    proposal = {'decisions': [{'topic': 'Targets', 'choice': 'Keep the requested workout targets.',
        'sourceReferences': ['SOURCE_0']}]}

    def respond(client, request, **options):
        if stage in ('decision', 'joint'):
            assert plan_review._DECISION_SCOPE_INSTRUCTIONS in request[0]['content']
        context = json.loads(request[-1]['content'])
        target = context['requirements'] if stage == 'requirements' else context['decisions']['DECISION_0']
        # Source uncertainty is a warning unless it requests clarification; decision reviews
        # independently classify severity from the basis rather than the model's label.
        reported_severity = (severity if stage == 'decision' or basis == 'established_violation'
                             else 'warning')
        finding = {'basis': basis, 'severity': reported_severity, 'action': 'repair',
            'path': target['_reviewRef'],
            'message': 'Check the extracted choice against the original instructions.',
            'evidencePaths': [context['sourceMessages']['SOURCE_0']['_reviewRef']],
            'repair': 'Preserve the requested targets.'}
        return json.dumps({'findings': [finding]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    if stage == 'decision':
        result = plan_review.record_planning_decisions(None, proposal, messages, equipment=equipment)
        receipt = result['decisionReview']
    else:
        result = plan_review.review_requirements(None, candidate, messages,
            planning_decisions=proposal if stage == 'joint' else None)
        receipt = result['sourceReview']
    assert result['passed'] is passed, result
    assert receipt['findings'][0]['severity'] == ('warning' if passed else 'blocking')
    if stage == 'joint' and not passed:
        assert not result['jointDecisionReview']['passed'] and result['decisions'] == {}


def test_rejected_implementation_decision_preserves_authorized_interpretation(monkeypatch):
    equipment, _, _, _ = planning_case()
    settled = {'DECISION_0': {'topic': 'Balance accounting', 'choice': 'Count each physical set once.',
        'sourceReferences': ['SOURCE_0']}}
    messages = [{'role': 'user', 'content': 'For balance accounting, count each physical set once.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'choice', 'function': {'name': 'record_planning_decisions'}}]},
        {'role': 'tool', 'tool_call_id': 'choice', 'content': json.dumps({
            'passed': True, 'decisionReview': {'passed': True}, 'decisions': settled})},
        {'role': 'user', 'content': 'Repair the workout fatigue concerns, preserving approved targets.'}]
    proposal = {'decisions': [{'topic': 'Fixed weekly allocation',
        'choice': 'Keep exactly twelve sets of the current isolation movement.', 'sourceReferences': ['SOURCE_1']}]}

    def reject(client, request, **options):
        assert plan_review._DECISION_SCOPE_INSTRUCTIONS in request[0]['content']
        context = json.loads(request[-1]['content'])
        return json.dumps({'findings': [{'basis': 'established_violation', 'severity': 'blocking',
            'path': context['decisions']['DECISION_1']['_reviewRef'],
            'evidencePaths': [context['sourceMessages']['SOURCE_1']['_reviewRef']],
            'message': 'Delegating repair does not fix the planner-selected set counts.',
            'repair': 'Repair the draft without recording its set allocation as a user constraint.'}]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', reject)
    result = plan_review.record_planning_decisions(None, proposal, messages, equipment=equipment)
    assert not result['passed']
    assert result['decisions'] == settled == saved_decisions(messages)
    assert result['decisionReview']['version'] == plan_review.DECISION_REVIEW_VERSION


@pytest.mark.parametrize('field', ['action', 'decisionId'])
@pytest.mark.parametrize('missing_muscle_targets', [False, True])
def test_decision_finding_repairs_only_the_invalid_field(monkeypatch, field, missing_muscle_targets):
    original = {'severity': 'blocking', 'basis': 'established_violation', 'path': '/draft',
        'message': 'The recorded decision conflicts with the draft.', 'evidencePaths': ['/sourceMessages/SOURCE_0'],
        'repair': 'Apply the recorded decision.', 'decisionId': 'DECISION_0'}
    if field == 'decisionId':
        original.update(decisionId='DECISION_99', action='repair')
    repaired = {**original, field: 'repair' if field == 'action' else 'DECISION_0'}
    if missing_muscle_targets:
        repaired['muscleTargets'] = []
    context = {'draft': {}, 'sourceMessages': {'SOURCE_0': {}},
        'resolvedDecisions': {'DECISION_0': {'choice': 'Keep the targets.'}}}

    def respond(client, request, **options):
        permissions = json.loads(request[-1]['content'])['invalidFindings'][0]['permittedPaths']
        assert set(permissions['exact']) == {'/' + field} | ({'/muscleTargets'} if missing_muscle_targets else set())
        return _repair_reply(original, repaired), None, None

    def normalize(finding):
        plan_review._normalize_finding_references(finding, context, {})
        plan_review._check_decision_finding(finding, context)
        return finding

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    result = plan_review._validated_findings(None, [], json.dumps({'findings': [original]}), normalize, None, 'test',
        schema=plan_review._PLAN_RESPONSE if missing_muscle_targets else plan_review._RESPONSE,
        finding_schema=plan_review._PLAN_FINDING if missing_muscle_targets else plan_review._FINDING)
    assert result[0] == {**repaired, 'newConflictEvidencePaths': []}


@pytest.mark.parametrize('rewrite_valid_reference', [False, True])
def test_schema_and_reference_errors_share_one_scoped_repair(monkeypatch, rewrite_valid_reference):
    original = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair', 'path': 'FACT_999',
        'message': 'The draft conflicts with the source.', 'evidencePaths': ['FACT_998', 'FACT_1'],
        'newConflictEvidencePaths': ['FACT_1'], 'repair': 'Preserve the source requirement.'}
    repaired = {**original, 'path': 'FACT_0', 'evidencePaths': ['FACT_1'], 'muscleTargets': []}
    if rewrite_valid_reference:
        repaired['newConflictEvidencePaths'] = ['FACT_0']
    context = {'draft': {}, 'sourceMessages': {'SOURCE_0': {}}}
    facts = {'FACT_0': '/draft', 'FACT_1': '/sourceMessages/SOURCE_0'}
    calls = []

    def respond(client, request, **options):
        calls.append(request)
        permissions = json.loads(request[-1]['content'])['invalidFindings'][0]['permittedPaths']
        assert set(permissions['exact']) == {'/path', '/evidencePaths', '/muscleTargets'}
        assert permissions['descendants'] == ['/evidencePaths', '/muscleTargets']
        return _repair_reply(original, repaired), None, None

    def normalize(finding):
        plan_review._normalize_finding_references(finding, context, facts)
        return finding

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    def validate_findings():
        return plan_review._validated_findings(None, [], json.dumps({'findings': [original]}), normalize,
            None, 'test', schema=plan_review._PLAN_RESPONSE, finding_schema=plan_review._PLAN_FINDING)

    if rewrite_valid_reference:
        with pytest.raises(plan_review.ReviewOutputError, match='outside allowed error'):
            validate_findings()
    else:
        result = validate_findings()[0]
        assert result['path'] == '/draft' and result['muscleTargets'] == []
        assert result['evidencePaths'] == ['/sourceMessages/SOURCE_0']
        assert result['newConflictEvidencePaths'] == ['/sourceMessages/SOURCE_0']
    assert len(calls) == 1


def _without_refs(value):
    if isinstance(value, dict):
        return {key: _without_refs(child) for key, child in value.items() if key != '_reviewRef'}
    if isinstance(value, list):
        return [_without_refs(child) for child in value]
    return value


def test_independent_review_maps_fact_refs_to_exact_draft_paths(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)

    def respond(client, request, **options):
        context = json.loads(request[-1]['content'])
        if 'draft' not in context:
            return '{"findings":[]}', None, None
        assert 'every finding also requires muscleTargets' in request[0]['content']
        assert context['draft']['exercises'][0]['_reviewRef'].startswith('FACT_')
        assert '_reviewRef' not in draft['workouts'][0]['exercises'][0]
        finding = {'severity': 'blocking', 'basis': 'established_violation', 'action': 'repair', 'muscleTargets': [],
            'path': context['draft']['exercises'][0]['_reviewRef'],
            'message': 'The exercise conflicts with a stated execution requirement.',
            'evidencePaths': [context['sourceMessages']['SOURCE_0']['_reviewRef']],
            'repair': 'Use an exercise that satisfies the stated execution requirement.'}
        return json.dumps({'findings': [finding]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    def assess_single_mapping_finding(client, context, review, logger=None, **options):
        return {'version': plan_review.ASSESSMENT_VERSION,
            'inputHash': plan_review.assessment_hash(review),
            'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                'repairDimensions': ['exercise_selection'],
                'reason': 'The selected movement conflicts with the source requirement.'}],
            'repairPlan': 'Replace the movement with a source-compatible choice.'}
    monkeypatch.setattr(plan_review, 'assess_findings', assess_single_mapping_finding)
    monkeypatch.setattr(plan_review, '_confirm_review_corrections', lambda *args, **kwargs: None)
    original_review_draft = interactive_shell.review_draft
    def run_legacy_review_path(*args, **kwargs):
        return original_review_draft(*args, **(kwargs | {'two_pass': False}))
    monkeypatch.setattr(interactive_shell, 'review_draft', run_legacy_review_path)
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert result['errors'][0].get('draftPath') == '/workouts/0/exercises/0', result['errors']
    assert result['review']['findings'][0]['path'] == '/draft/exercises/0'
    assert result['review']['findings'][0]['evidencePaths'] == ['/sourceMessages/SOURCE_0']


def test_joint_requirements_and_decision_review_approves_and_saves_once(monkeypatch):
    equipment, requirements, stored, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Set up the requested workout targets.'},
        {'role': 'user', 'content': 'For balance accounting, count each working set once.'}]
    candidate = set_workout_requirements(requirements, messages, equipment)
    decision_proposal = {'decisions': [{'topic': 'Balance accounting',
        'choice': 'Count each working set once for movement balance.', 'sourceReferences': ['SOURCE_1']}]}
    calls = []

    def approve(client, request, **options):
        calls.append(request)
        context = json.loads(request[-1]['content'])
        assert _without_refs(context['requirements']) == plan_review._extracted_context(candidate)
        assert context['newDecisionIds'] == ['DECISION_0']
        assert context['decisions']['DECISION_0']['choice'] == decision_proposal['decisions'][0]['choice']
        assert context['sourceMessages']['SOURCE_1']['_reviewRef'].startswith('FACT_')
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, 'chat_call', approve)
    result = plan_review.review_requirements(None, candidate, messages, planning_decisions=decision_proposal)
    assert result['passed'] and result['jointDecisionReview']['passed'], result.get('errors') or result.get('sourceReview')
    assert result['sourceReview']['inputHash'] == plan_review._hash(plan_review._requirements_context(result))
    assert 'User-authorized planning choices:' in result['requirementsPreview']
    assert len(calls) == 1

    call_id = 'requirements-joint'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(result)},
        {'role': 'assistant', 'content': result['requirementsPreview'],
         'canonicalRequirementsPreview': result['requirementsId']},
        {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'},
    ])
    assert saved_decisions(messages) == result['decisions']
    assert requirements_approved(messages, result)
    repeated_candidate = set_workout_requirements(requirements, messages, equipment)
    repeated = plan_review.review_requirements(None, repeated_candidate, messages, planning_decisions=decision_proposal)
    assert repeated['passed'] and repeated['sourceReview']['inputHash'] == result['sourceReview']['inputHash']
    assert len(calls) == 1


def test_joint_review_does_not_save_decisions_when_any_finding_blocks(monkeypatch):
    equipment, requirements, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Set up the requested workout targets.'},
        {'role': 'user', 'content': 'I delegate the balance convention to the planner.'}]
    candidate = set_workout_requirements(requirements, messages, equipment)
    proposal = {'decisions': [{'topic': 'Balance accounting',
        'choice': 'Count each working set once for movement balance.', 'sourceReferences': ['SOURCE_1']}]}

    def reject(client, request, **options):
        context = json.loads(request[-1]['content'])
        return json.dumps({'findings': [{'severity': 'blocking',
            'path': context['decisions']['DECISION_0']['_reviewRef'],
            'message': 'The decision overstates what the audit can verify.',
            'evidencePaths': [context['sourceMessages']['SOURCE_1']['_reviewRef']],
            'repair': 'Clarify the supported counting convention.'}]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', reject)
    result = plan_review.review_requirements(None, candidate, messages, planning_decisions=proposal)
    assert not result['passed'] and not result['jointDecisionReview']['passed']
    assert result['resolvedDecisions'] == {}
    assert saved_decisions(messages) == {}


def test_joint_choice_replacement_keeps_only_the_new_choice_active(monkeypatch):
    equipment, requirements, stored, _ = planning_case()
    messages = requirement_messages(stored) + [{'role': 'user', 'content': 'Count overlapping credits separately.'}]
    first = {'decisions': [{'topic': 'Balance accounting', 'choice': 'Count each set once.',
        'sourceReferences': ['SOURCE_1']}]}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    first_result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', first, equipment)['result'])
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'choice0', 'function': {'name': 'record_planning_decisions'}}]},
        {'role': 'tool', 'tool_call_id': 'choice0', 'content': json.dumps(first_result)},
        {'role': 'user', 'content': 'Change that choice: count each overlapping muscle credit separately.'},
    ])
    candidate = dict(stored, sourceMessages=requirement_sources(messages),
        resolvedDecisions=resolved_decisions(messages))
    replacement = {'decisions': [{'topic': 'Balance accounting', 'choice': 'Count each overlapping muscle credit separately.',
        'sourceReferences': ['SOURCE_2'], 'supersedes': 'DECISION_0', 'reason': 'The user explicitly changed the choice.'}]}
    result = plan_review.review_requirements(None, candidate, messages, planning_decisions=replacement)
    assert result['passed'] and result['decisions']['DECISION_0']['supersededBy'] == 'DECISION_1'
    assert list(result['resolvedDecisions']) == ['DECISION_1']
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements-joint', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements-joint', 'content': json.dumps(result)},
    ])
    assert list(resolved_decisions(messages)) == ['DECISION_1']


def test_numeric_fact_spelling_normalizes_only_citation_identity():
    from workout_generator_pkg.plan_review import _canonical_review_content
    import json
    schema = {'$def': {'reference': {'enum': ['FACT_99']}}}
    payload = {'findings': [{'path': 'FACT_099', 'evidencePaths': ['FACT_0099', 'FACT_100'],
        'message': 'FACT_099 remains verbatim evidence text.'}]}
    result = json.loads(_canonical_review_content(json.dumps(payload), schema))
    assert result['findings'][0]['path'] == 'FACT_99'
    assert result['findings'][0]['evidencePaths'] == ['FACT_99', 'FACT_100']
    assert result['findings'][0]['message'] == payload['findings'][0]['message']


@pytest.mark.parametrize('metadata,accepted', [
    ({'type': 'json_object'}, True), ({'type': 'advisory'}, False), ({'extra': True}, False)])
def test_review_transport_tag_is_ignored_without_accepting_unknown_content(metadata, accepted):
    from jsonschema import validate, ValidationError
    from workout_generator_pkg.plan_review import _canonical_review_content, _strict_review_schema
    schema = _strict_review_schema({'FACT_0': '/draft'})
    payload = json.loads(_canonical_review_content(json.dumps({'findings': [], **metadata}), schema))
    if accepted:
        validate(payload, schema)
        assert payload == {'findings': []}
    else:
        with pytest.raises(ValidationError):
            validate(payload, schema)


@pytest.mark.parametrize(('rest_seconds', 'setup_seconds'), [(0, 60), (120, 30)])
def test_programming_summary_separates_recovery_rest_from_setup(rest_seconds, setup_seconds):
    from workout_generator_pkg.generation_audit import audit_workout_package, build_programming_summary

    components = [
        {'type': 'Exercise', 'id': 'EXERCISE_0', 'name': 'Press', 'sets': [
            {'type': 'WeightSet', 'subCategory': 'WorkSet', 'reps': 1, 'weight': 10}]},
        {'type': 'Rest', 'timeInSeconds': rest_seconds},
        {'type': 'Exercise', 'id': 'EXERCISE_1', 'name': 'Row', 'sets': [
            {'type': 'WeightSet', 'subCategory': 'WorkSet', 'reps': 1, 'weight': 10}]},
    ]
    final_artifact = {'workouts': [{'name': 'Day', 'components': components}]}
    emitted_report = audit_workout_package(
        {'workouts': [{'name': 'Day', 'workoutComponents': components}]}, {},
        setup_seconds_by_exercise={'EXERCISE_1': setup_seconds})
    source_draft = {'workouts': [{'name': 'Day', 'exercises': [
        {'definition_id': 'def_press', 'numWorkSets': 1},
        {'definition_id': 'def_row', 'numWorkSets': 1}]}]}
    plan_index = {
        'exercises': [
            {'id': 'EXERCISE_0', 'name': 'Press'}, {'id': 'EXERCISE_1', 'name': 'Row'}],
        'workouts': [{'name': 'Day', 'exerciseIds': ['EXERCISE_0', 'EXERCISE_1'],
            'timesCompletedInAWeek': 1}],
    }
    review_draft = {'exercises': [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': 'def_press'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'def_row'}]}

    summary = build_programming_summary(emitted_report, emitted_report, source_draft, plan_index,
        review_draft, {}, {}, final_artifact=final_artifact)

    session = summary['sessions'][0]
    timing = session['timingComponents']
    transition = timing['transitions'][0]
    assert session['finalExerciseOrder'] == [
        {'id': 'EXERCISE_0', 'name': 'Press'}, {'id': 'EXERCISE_1', 'name': 'Row'}]
    assert timing['prescribedRecoveryRestSeconds'] == rest_seconds
    assert timing['estimatedSetupSeconds'] == setup_seconds
    assert timing['estimatedTotalSeconds'] == 300 + 6 + rest_seconds + setup_seconds
    assert transition == {
        'scope': 'between_blocks',
        'fromExerciseId': 'EXERCISE_0', 'toExerciseId': 'EXERCISE_1',
        'recoveryOwner': {'exerciseRef': 'EXERCISE_0', 'field': 'restAfterExerciseSeconds'},
        'setupOwner': {'exerciseRef': 'EXERCISE_1', 'field': 'setupSeconds'},
        'betweenExerciseRestComponentSeconds': rest_seconds,
        'estimatedSetupSeconds': setup_seconds,
        'setupScope': 'one_time_before_destination_block',
        'estimatedTransitionSeconds': rest_seconds + setup_seconds,
    }
    assert emitted_report['workouts'][0]['setupEstimates'][0]['scope'] == 'one_time_before_exercise'
    assert 'not repeated per set or superset round' in timing['setupScope']
    assert 'unknown' in timing['supersetRoundSetup']


def test_programming_summary_exposes_hard_coverage_and_qualitative_balance_facts():
    from workout_generator_pkg.generation_audit import audit_workout_package, build_programming_summary

    def exercise(identifier, name, reps, sets):
        return {'type': 'Exercise', 'id': identifier, 'name': name, 'sets': [
            {'type': 'WeightSet', 'subCategory': 'WorkSet', 'reps': reps, 'weight': 10}
            for _ in range(sets)]}

    press = exercise('EXERCISE_0', 'Press', 1, 4)
    press.update(exerciseType='WEIGHT', exerciseCategory='MODERATE_COMPOUND',
        muscleGroups=['FRONT_CHEST'], secondaryMuscleGroups=['BACK_TRICEPS'], equipmentId='EQUIPMENT_0')
    row = exercise('EXERCISE_1', 'Row', 1, 3)
    row.update(exerciseType='WEIGHT', exerciseCategory='MODERATE_COMPOUND',
        muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=['BACK_BICEPS'], equipmentId='EQUIPMENT_1',
        requiredAccessoryEquipmentIds=['ACCESSORY_0'])
    components = [press, row]
    final_artifact = {'workouts': [{'name': 'Day', 'components': components}]}
    coverage = {'EXERCISE_0': ['horizontal_push'], 'EXERCISE_1': ['horizontal_pull']}
    report = audit_workout_package(
        {'workouts': [{'name': 'Day', 'workoutComponents': components}]}, {}, coverage_by_exercise=coverage)
    source_draft = {'workouts': [{'name': 'Day', 'exercises': [
        {'definition_id': 'def_press', 'numWorkSets': 4, 'satisfiesCoverage': ['horizontal_push']},
        {'definition_id': 'def_row', 'numWorkSets': 3, 'satisfiesCoverage': ['horizontal_pull']}]}]}
    plan_index = {'exercises': [
        {'id': 'EXERCISE_0', 'name': 'Press', 'exerciseType': 'WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND',
            'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': ['BACK_TRICEPS'], 'equipmentId': 'EQUIPMENT_0'},
        {'id': 'EXERCISE_1', 'name': 'Row', 'exerciseType': 'WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND',
            'muscleGroups': ['BACK_UPPER_BACK'], 'secondaryMuscleGroups': ['BACK_BICEPS'], 'equipmentId': 'EQUIPMENT_1',
            'requiredAccessoryEquipmentIds': ['ACCESSORY_0']}],
        'workouts': [{'name': 'Day', 'exerciseIds': ['EXERCISE_0', 'EXERCISE_1'], 'timesCompletedInAWeek': 1}]}
    review_draft = {'exercises': [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': 'def_press'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'def_row'}]}
    requirements = {'requiredCoverage': [
        {'key': 'horizontal_push', 'description': 'Horizontal pressing', 'scope': 'weekly', 'intent': 'development'},
        {'key': 'horizontal_pull', 'description': 'Horizontal pulling', 'scope': 'weekly', 'intent': 'inclusion'}],
        'executionRules': [
            {'kind': 'coverageBalance', 'first': 'horizontal_push', 'second': 'horizontal_pull',
             'scope': 'weekly', 'relationship': 'balanced'},
            {'kind': 'coverageBalance', 'first': 'horizontal_push', 'second': 'horizontal_pull',
             'scope': 'eachSession', 'relationship': 'first_not_less_than_second'}]}
    priority_execution = {'approvedPriorities': [{'priority': 'distribution', 'owner': 'solver', 'status': 'ran'}],
        'coverageBalance': [{'first': 'horizontal_push', 'second': 'horizontal_pull',
            'scope': 'weekly', 'owner': 'semantic_review', 'status': 'semantic_review_required'}]}
    priority_tradeoffs = [{'first': 'horizontal_push', 'second': 'horizontal_pull', 'relationship': 'balanced',
        'scope': 'weekly', 'firstSets': 4, 'secondSets': 3, 'deviation': 1,
        'status': 'residual_at_approved_optimum',
        'scopeOfProof': 'Submitted recipes and hard constraints only; other menus were not searched.'}]
    requirements['auditTargets'] = {'weeklyEffectiveSets': {
        'chest': {'minimum': 4, 'maximum': 5}, 'back': {'minimum': 3, 'maximum': 5}}}

    summary = build_programming_summary(report, report, source_draft, plan_index, review_draft, {}, {},
        final_artifact=final_artifact, requirements=requirements, priority_execution=priority_execution,
        priority_tradeoffs=priority_tradeoffs)

    assert [(item['key'], item['weeklyWorkingSets'], item['scope']) for item in summary['coverageRequirements']] == [
        ('horizontal_push', 4, 'weekly'), ('horizontal_pull', 3, 'weekly')]
    assert summary['coverageRequirements'][0]['intent'] == 'development'
    assert 'do not by themselves establish adequate development' in summary['coverageRequirements'][0]['interpretation']
    assert summary['priorityExecution'] == priority_execution
    credit_bounds = summary['volumeCreditCoupling']
    assert credit_bounds['status'] == 'proven'
    assert {profile['members'][0]['id']: profile['minimumWeeklyWorkingSets']
        for profile in credit_bounds['profileLowerBounds']} == {'def_press': 4, 'def_row': 3}
    priority_execution['developmentEmphasis'] = {
        'owner': 'joint_solver', 'status': 'optimal', 'roleKeys': ['horizontal_push'],
        'minimumWeeklyWorkingSets': 3,
        'sourceBudget': {'source': 'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
            'variableSourceWorkingSets': 22, 'fixedExistingWorkingSets': 4,
            'sourceBudgetWeeklyWorkingSets': 26, 'variableMenuCapWorkingSets': 22},
    }
    development_summary = build_programming_summary(report, report, source_draft, plan_index,
        review_draft, {}, {}, final_artifact=final_artifact, requirements=requirements,
        priority_execution=priority_execution, priority_tradeoffs=priority_tradeoffs)
    development_interpretation = development_summary['coverageRequirements'][0]['interpretation']
    assert 'relative weekly raw-set exposure across horizontal push within the reported source-set budget' in development_interpretation
    assert 'Source budget (code-prepared workout allocation plus existing sessions)' in development_interpretation
    assert 'variable-menu cap is 22 weekly sets' in development_interpretation
    assert 'selected minimum was 3 raw working sets/week' in development_interpretation
    assert 'sets no minimum and does not establish adequate development' in development_interpretation
    assert summary['coverageRequirements'][1]['intent'] == 'inclusion'
    assert summary['coverageBalanceEvidence'][0]['workingSets'] == {'horizontal_push': 4, 'horizontal_pull': 3}
    assert summary['coverageBalanceEvidence'][0]['relationship'] == 'balanced'
    assert summary['coverageBalanceEvidence'][0]['absoluteDifference'] == 1
    assert summary['coverageBalanceEvidence'][1]['sessions'][0]['workingSets'] == {
        'horizontal_push': 4, 'horizontal_pull': 3}
    assert summary['coverageBalanceEvidence'][1]['relationship'] == 'first_not_less_than_second'
    assert summary['coverageBalanceEvidence'][1]['sessions'][0]['comparisonOutcome'] == 'met'
    assert 'no numeric tolerance' in summary['coverageBalanceEvidence'][0]['interpretation']
    assert 'unequal counts alone are not a violation' in summary['coverageBalanceEvidence'][0]['interpretation'].lower()
    assert summary['priorityTradeoffs'] == priority_tradeoffs
    press_occurrence = summary['exposures']['def_press']['occurrences'][0]
    assert press_occurrence['primaryMuscles'] == ['FRONT_CHEST']
    assert press_occurrence['restBetweenSetsSeconds'] is None
    assert press_occurrence['weeklyMuscleCredits']['chest']['direct'] == 4
    row_occurrence = summary['exposures']['def_row']['occurrences'][0]
    assert row_occurrence['requiredAccessoryEquipmentIds'] == ['ACCESSORY_0']
    assert 'not measurements of fatigue' in summary['demandEvidence']['interpretation']
    assert 'support configuration' in summary['demandEvidence']['notRepresentedByCurrentLibraryFields']
    from workout_generator_pkg.planner_context import _compact_programming_selection_facts
    selection_facts = _compact_programming_selection_facts(summary)
    assert selection_facts['coverageRequirements'][0]['intent'] == 'development'
    assert selection_facts['coverageBalanceEvidence'][1]['relationship'] == 'first_not_less_than_second'
    assert selection_facts['demandEvidence'] == summary['demandEvidence']
    assert selection_facts['priorityTradeoffs'] == priority_tradeoffs


def test_requirement_review_marks_application_workset_floor_as_code_owned():
    from workout_generator_pkg.programming_guidelines import MINIMUM_WORK_SETS_RULE

    candidate = {'requirements': {'executionRules': [MINIMUM_WORK_SETS_RULE]},
        'sourceMessages': [], 'restrictionPolicy': {}, 'resolvedDecisions': {}}
    context = plan_review._requirements_context(candidate)

    assert context['applicationWorkSetPolicy'] == {
        'rule': MINIMUM_WORK_SETS_RULE, 'presentInRequirements': True}


def test_programming_summary_does_not_present_superset_internal_timing_as_a_block_transition():
    from workout_generator_pkg.generation_audit import audit_workout_package, build_programming_summary

    def exercise(identifier, name, sets):
        return {'type': 'Exercise', 'id': identifier, 'name': name, 'sets': [
            {'type': 'WeightSet', 'subCategory': 'WorkSet', 'reps': 1, 'weight': 10} for _ in range(sets)]}

    first = exercise('EXERCISE_0', 'Press', 1)
    superset_members = [exercise('EXERCISE_1', 'Row', 2), exercise('EXERCISE_2', 'Fly', 2)]
    components = [first, {'type': 'Superset', 'exercises': superset_members,
        'restSecondsByExercise': {'EXERCISE_1': 60, 'EXERCISE_2': 30}}]
    final_artifact = {'workouts': [{'name': 'Day', 'components': components}]}
    emitted_report = audit_workout_package(
        {'workouts': [{'name': 'Day', 'workoutComponents': components}]}, {},
        setup_seconds_by_exercise={'EXERCISE_1': 60, 'EXERCISE_2': 60})
    source_draft = {'workouts': [{'name': 'Day', 'exercises': [
        {'definition_id': 'def_press', 'numWorkSets': 1},
        {'definition_id': 'def_row', 'numWorkSets': 2},
        {'definition_id': 'def_fly', 'numWorkSets': 2}]}]}
    plan_index = {
        'exercises': [
            {'id': 'EXERCISE_0', 'name': 'Press'}, {'id': 'EXERCISE_1', 'name': 'Row'},
            {'id': 'EXERCISE_2', 'name': 'Fly'}],
        'workouts': [{'name': 'Day', 'exerciseIds': ['EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2'],
            'timesCompletedInAWeek': 1}],
    }
    review_draft = {'exercises': [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': 'def_press'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'def_row'},
        {'id': 'EXERCISE_2', 'libraryDefinitionId': 'def_fly'}]}

    summary = build_programming_summary(emitted_report, emitted_report, source_draft, plan_index,
        review_draft, {}, {}, final_artifact=final_artifact)

    session = summary['sessions'][0]
    timing = session['timingComponents']
    assert [exercise['id'] for exercise in session['finalExerciseOrder']] == [
        'EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2']
    assert timing['prescribedRecoveryRestSeconds'] == 150
    assert timing['estimatedSetupSeconds'] == 120
    assert timing['estimatedTotalSeconds'] == 585
    assert timing['transitions'] == [{
        'scope': 'between_blocks', 'fromExerciseId': 'EXERCISE_0', 'toExerciseId': 'EXERCISE_1',
        'recoveryOwner': {'exerciseRef': 'EXERCISE_0', 'field': 'restAfterExerciseSeconds'},
        'setupOwner': {'exerciseRef': 'EXERCISE_1', 'field': 'setupSeconds'},
        'betweenExerciseRestComponentSeconds': 0, 'estimatedSetupSeconds': 60,
        'setupScope': 'one_time_before_destination_block',
        'estimatedTransitionSeconds': 60,
    }]
