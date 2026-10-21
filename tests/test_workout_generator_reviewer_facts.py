import json
import pytest

from workout_generator_pkg import plan_review
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


def test_strict_review_schema_restricts_citations_without_mutating_local_validation():
    import copy
    from jsonschema import validate,ValidationError
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
    original = {'basis': 'uncertainty', 'severity': 'warning', 'path': 'FACT_486',
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
        finding = {'basis': basis, 'severity': severity, 'path': target['_reviewRef'],
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
    assert result['passed'] is passed
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
    original = {'severity': 'blocking', 'basis': 'established_violation', 'path': 'FACT_999',
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
        assert 'every finding also requires muscleTargets' in request[0]['content']
        context = json.loads(request[-1]['content'])
        assert context['draft']['exercises'][0]['_reviewRef'].startswith('FACT_')
        assert '_reviewRef' not in draft['workouts'][0]['exercises'][0]
        finding = {'severity': 'blocking', 'basis': 'established_violation', 'muscleTargets': [],
            'path': context['draft']['exercises'][0]['_reviewRef'],
            'message': 'The exercise conflicts with a stated execution requirement.',
            'evidencePaths': [context['sourceMessages']['SOURCE_0']['_reviewRef']],
            'repair': 'Use an exercise that satisfies the stated execution requirement.'}
        return json.dumps({'findings': [finding]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
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
