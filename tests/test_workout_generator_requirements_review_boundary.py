import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import plan_review, planning_tools
from workout_generator_pkg.api_client import _strict_parameters_compatible
from test_workout_generator_planning_tools import planning_case


@pytest.mark.parametrize('weekly,sessions,share', [(9, 3, 3), (8, 4, 2)])
def test_existing_role_distribution_preference_exposes_code_computed_equal_shares(weekly, sessions, share):
    from workout_generator_pkg.requirement_accounting import requirement_implementation_checks

    requirements = {'sessionsPerWeek': sessions, 'objectiveOrder': ['role_concentration'],
        'requiredCoverage': [
            {'key': 'calves', 'scope': 'weekly', 'intent': 'development',
                'minimumWeeklySets': weekly, 'minimumSessions': sessions},
            {'key': 'lateral_delt', 'scope': 'weekly', 'intent': 'development',
                'minimumWeeklySets': 6, 'minimumSessions': 2},
            {'key': 'hip_dominant', 'scope': 'eachSession', 'intent': 'inclusion', 'minimumWeeklySets': 6},
        ]}
    check = requirement_implementation_checks(requirements)['role_distribution']
    assert check['minimumDoseEqualShares'] == {'calves': share}
    assert check['status'] == 'soft_objective_after_higher_ranked_priorities'
    assert 'not hard per-session minima' in check['answer']
    requirements['objectiveOrder'] = []
    assert 'role_distribution' not in requirement_implementation_checks(requirements)


def test_review_uses_effective_set_cap_instead_of_a_conflicting_generic_domain():
    equipment, requirements, _, _ = planning_case()
    requirements['executionRules'] = [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3}]
    candidate = planning_tools.set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'At most three sets per exercise per session.'}], equipment)
    context = plan_review._requirements_context(candidate)
    assert context['applicationWorkSetPolicy'] == {
        'rule': requirements['executionRules'][0], 'presentInRequirements': True}


def test_intake_reuses_shared_admission_and_confirmation_owners_without_new_workout_rules():
    from workout_generator_pkg.requirement_accounting import requirement_implementation_checks
    from workout_generator_pkg.repair_capabilities import CODE_OWNED_BEHAVIORS

    requirements = {'executionRules': [], 'requiredCoverage': []}
    checks = requirement_implementation_checks(requirements)
    for key in ('fixed_bodyweight_capability', 'requirements_confirmation'):
        assert checks[key]['answer'] == CODE_OWNED_BEHAVIORS[key]
        finding = {'check': 'implementation', 'implementationCheck': key, 'path': '/requirements'}
        assert plan_review._code_answered_requirement_finding(
            finding, {'implementationChecks': checks})['check'] == key
    assert requirements == {'executionRules': [], 'requiredCoverage': []}


def test_requirements_wire_schema_excludes_receipt_targets_and_assistant_evidence():
    context = {'requirements': {'executionRules': []},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Three sessions.'},
                           'SOURCE_1': {'role': 'assistant', 'content': 'Maybe four.'}},
        'structuredAuthority': {'matchedPaths': ['/requirements/sessionsPerWeek']}}
    _, facts = plan_review._with_review_refs(context)
    schema = plan_review._requirements_review_schema(context, facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    assert _strict_parameters_compatible(schema)
    props = schema['properties']['findings']['items']['anyOf'][0]['properties']
    targets = {facts[reference] for reference in props['path']['enum']}
    evidence = {facts[reference] for reference in props['evidencePaths']['items']['enum']}
    assert '/requirements' in targets
    assert not any(path.startswith('/structuredAuthority') for path in targets)
    assert '/sourceMessages/SOURCE_1' not in targets
    assert '/sourceMessages/SOURCE_0' in evidence
    assert '/requirements' in evidence
    assert not any(path.startswith('/sourceMessages/SOURCE_1') for path in evidence)


def test_code_verified_structured_source_uses_direct_structured_review_without_thinking_budget(monkeypatch):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, requirements, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Use these exact requirements.\n' +
        STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)}]
    candidate = planning_tools.set_workout_requirements(requirements, messages, equipment)
    calls = []

    def response(client, request, **options):
        calls.append(options)
        return json.dumps({'findings': []}), None, None

    monkeypatch.setattr(plan_review, '_review_call', response)
    result = plan_review.review_requirements(None, candidate, messages, equipment=equipment)
    assert len(calls) == 1 and calls[0]['reasoning_effort'] is None
    assert calls[0]['output_schema'] and result['sourceReview']['passed']
    assert result['requirements'] == candidate['requirements']


def test_extraction_omission_selects_a_supported_field_while_source_obligations_stay_binding(monkeypatch):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, requirements, _, _ = planning_case()
    narrative = 'Show the exact final plan as a table. Keep the original reporting obligations. Train Monday, Wednesday and Friday.'
    messages = [{'role': 'user', 'content': narrative + '\n' + STRUCTURED_REQUIREMENTS_MARKER
                 + '\n' + json.dumps(requirements)}]
    candidate = planning_tools.set_workout_requirements(requirements, messages, equipment)
    context = plan_review._requirements_context(candidate)
    request_context, facts = plan_review._with_semantic_review_refs(context)
    schema = plan_review._requirements_review_schema(context, facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    assert _strict_parameters_compatible(schema)
    source = next(ref for ref, path in facts.items() if path == '/sourceMessages/SOURCE_0')
    finding = {'severity': 'warning', 'basis': 'established_violation', 'path': source,
        'message': 'Reporting instructions need a second structured carrier.', 'evidencePaths': [source],
        'repair': 'Copy reporting instructions into a field.', 'action': 'repair', 'decisionId': None,
        'newConflictEvidencePaths': [], 'check': 'source_omission', 'implementationCheck': None}
    for target in (source, 'APPROVED_REQUIREMENTS'):
        invalid = {**finding, 'path': target}
        with pytest.raises(ValidationError):
            validate({'findings': [invalid]}, schema)
        plan_review._normalize_finding_references(invalid, context, facts, root='/requirements')
        with pytest.raises(plan_review._FindingValidationError):
            plan_review._code_answered_requirement_finding(invalid, context)

    catalog = {item['field']: item for item in request_context['extractionFields']}
    assert not {'notes', 'requirementAccounting'} & catalog.keys()
    assert not catalog['trainingDays']['present']
    omission = {**finding, 'path': catalog['trainingDays']['_reviewRef'],
        'message': 'Explicitly requested training days are absent.', 'repair': 'Extract the requested weekdays.'}
    preservation = {**finding, 'check': 'implementation',
        'implementationCheck': 'source_instruction_preservation',
        'message': 'Are original reporting obligations retained?', 'repair': 'Explain source retention.'}
    validate({'findings': [preservation, omission]}, schema)
    calls = []

    def response(client, request, **options):
        calls.append(1)
        validate({'findings': [preservation, omission]}, options['output_schema'])
        assert narrative in json.loads(request[-1]['content'])['sourceMessages'][source]['content']
        return json.dumps({'findings': [preservation, omission]}), None, None

    monkeypatch.setattr(plan_review, '_review_call', response)
    before = copy.deepcopy(candidate)
    result = plan_review.review_requirements(None, candidate, messages, equipment=equipment)
    assert calls == [1] and candidate == before
    assert not result['passed'] and not result['sourceReview'].get('failure')
    assert result['requirements'] == candidate['requirements']
    assert [item['path'] for item in result['sourceReview']['findings']] == ['/requirements/trainingDays']
    assert result['sourceReview']['findings'][0]['severity'] == 'blocking'
    assert plan_review._requirements_findings_are_supported_repairs(result['sourceReview']['findings'], candidate)
    answer = result['sourceReview']['codeAnsweredChecks'][0]
    assert answer['check'] == 'source_instruction_preservation'
    assert 'not proof' in answer['answer'] and 'remain reviewable' in answer['answer']
    assert any(narrative in source['content'] for source in result['sourceMessages'])


def saved_case():
    root = Path(__file__).resolve().parents[1] / 'build/workout_intake_three_set_fresh_e2e_20261029'
    if not root.exists():
        pytest.skip('Retained live run is not present in this checkout.')
    identifier = json.loads((root / 'conversation_meta.json').read_text(encoding='utf-8'))['active_conversation_id']
    messages = json.loads((root / 'workouts/conversation_sessions' / identifier / 'messages.json').read_text(encoding='utf-8'))
    log = next((root / 'logs').glob('*.log')).read_text(encoding='utf-8')

    def logged(kind, stage):
        marker = f'[{kind}] {stage}: '
        return json.loads([line.split(marker, 1)[1] for line in log.splitlines() if marker in line][0])

    context = logged('request', 'requirements_source_review')
    payload = logged('response', 'requirements_source_review')
    selection = logged('response', 'requirements_source_citation_selection')
    return messages, context, payload, selection


def test_retained_response_exposes_the_previously_unbounded_metadata_subject():
    _, context, payload, selection = saved_case()
    _, facts = plan_review._with_review_refs(context)
    old_schema = plan_review._strict_review_schema(facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    validate(payload, old_schema)
    assert 'NONE' in selection['findingSourceReferences'].values()
    schema = plan_review._requirements_review_schema(context, facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    metadata = next(item for item in payload['findings'] if facts[item['path']] == '/structuredAuthority')
    assert metadata['check'] == 'authorization'
    with pytest.raises(ValidationError):
        validate(metadata['path'], schema['properties']['findings']['items']['anyOf'][0]['properties']['path'])


def test_retained_full_review_replay_needs_no_citation_retry_or_requirement_change(monkeypatch):
    messages, original_context, payload, _ = saved_case()
    _, original_facts = plan_review._with_review_refs(original_context)
    for finding in payload['findings']:
        plan_review._normalize_finding_references(finding, original_context, original_facts, root='/requirements')
    tool_index = next(index for index, message in enumerate(messages)
        if any(call['function']['name'] == 'set_workout_requirements' for call in message.get('tool_calls', [])))
    arguments = json.loads(messages[tool_index]['tool_calls'][0]['function']['arguments'])
    candidate = json.loads(messages[tool_index + 1]['content'])
    for key in ('sourceReview', 'errors', 'passed', 'jointDecisionReview', 'decisions',
                'proposedDecisions', 'requirementsReviewQuestion', 'instruction'):
        candidate.pop(key, None)
    before = copy.deepcopy(candidate['requirements'])
    calls = []

    def reply(*args, **kwargs):
        calls.append(1)
        assert 'structuredAuthority' not in json.loads(args[1][-1]['content'])
        assert len(calls) == 1, 'A metadata or decision provenance question must not require a citation call.'
        return json.dumps(payload), None, None

    monkeypatch.setattr(plan_review, '_review_call', reply)
    result = plan_review.review_requirements(None, candidate, messages[:tool_index],
        planning_decisions=arguments['planningDecisions'])
    assert len(calls) == 1
    assert not result['sourceReview'].get('failure'), result.get('errors')
    assert result['requirements'] == before
    assert len(result['sourceReview']['codeAnsweredChecks']) == 3
    assert len(result['sourceReview']['findings']) == 1
    assert result['sourceReview']['findings'][0]['decisionId'] == 'DECISION_3'
    assert any(item['check'] == 'code_owned_review_metadata'
               for item in result['sourceReview']['codeAnsweredChecks'])
    assert all('/sourceMessages/SOURCE_0' in item['evidencePaths']
               for item in result['sourceReview']['findings'])


def test_source_conflict_schema_cannot_target_an_authoritative_requirement_field():
    context = {'requirements': {'exerciseRestrictions': {'excludeNameTerms': ['pushdown machine']}},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Keep the named exception.'}}}
    _, facts = plan_review._with_review_refs(context)
    schema = plan_review._requirements_review_schema(context, facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    assert _strict_parameters_compatible(schema)
    finding = {'severity': 'blocking', 'basis': 'established_violation',
        'path': next(ref for ref, path in facts.items() if path == '/requirements/exerciseRestrictions'),
        'message': 'The restriction and exception conflict.',
        'evidencePaths': [next(ref for ref, path in facts.items() if path == '/sourceMessages/SOURCE_0')],
        'repair': 'Clarify the scope.', 'action': 'repair', 'decisionId': None,
        'newConflictEvidencePaths': [], 'check': 'source_conflict', 'implementationCheck': None}
    with pytest.raises(ValidationError):
        validate({'findings': [finding]}, schema)
    finding['path'] = finding['evidencePaths'][0]
    validate({'findings': [finding]}, schema)


@pytest.mark.parametrize('new_instruction', [False, True])
@pytest.mark.parametrize('family_bounds', ['omitted', 'empty'])
def test_complete_approved_snapshot_uses_code_validation_but_new_prose_still_gets_review(
        monkeypatch, new_instruction, family_bounds):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, targets, _, _ = planning_case()
    requirements = json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    requirements.update(auditTargets=targets['auditTargets'], sessionsPerWeek=1, preferredSessionSeconds=900, familySetBounds=[],
        requiredCoverage=[], exerciseRestrictions={'excludeNameTerms': [], 'exceptNameTerms': []}, executionRules=[
            {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3}])
    requirements.pop('objectiveTiers', None)  # This fixture replaces the goals' muscles and coverage roles.
    if family_bounds == 'omitted':
        requirements.pop('familySetBounds')
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)}]
    schema = planning_tools.workout_requirements_tool(equipment, messages)['function']['parameters']
    decision_schema = schema['properties']['planningDecisions']['properties']['decisions']['items']
    assert decision_schema['anyOf'] == [{'required': ['executionPrescription']}]
    if new_instruction:
        messages.append({'role': 'user', 'content': 'Also prioritize upper-body work.'})
    candidate = planning_tools.set_workout_requirements({}, messages, equipment)
    before = copy.deepcopy(candidate['requirements'])
    calls = []

    def reply(*a, **k):
        calls.append(1)
        return json.dumps({'findings': []}), None, None

    monkeypatch.setattr(plan_review, '_review_call', reply)
    result = plan_review.review_requirements(None, candidate, messages)
    assert result['passed'] and result['requirements'] == before
    assert len(calls) == int(new_instruction)
    assert not planning_tools.requirements_approved(messages, result)


@pytest.mark.parametrize('changed_field', ['familySetBounds', 'preferredSessionSeconds'])
def test_neutral_omission_cannot_hide_retained_bounds_or_an_unspecified_time_preference(monkeypatch, changed_field):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, targets, _, _ = planning_case()
    requirements = json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    requirements.update(auditTargets=targets['auditTargets'], sessionsPerWeek=1, preferredSessionSeconds=900, requiredCoverage=[],
        exerciseRestrictions={'excludeNameTerms': [], 'exceptNameTerms': []}, executionRules=[
            {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3}])
    requirements.pop('objectiveTiers', None)
    requirements.pop('familySetBounds', None)
    if changed_field == 'preferredSessionSeconds':
        requirements.pop(changed_field)
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)}]
    candidate = planning_tools.set_workout_requirements({}, messages, equipment)
    if changed_field == 'familySetBounds':
        # The merged candidate can retain a previously approved bound absent from the new snapshot.
        candidate['requirements']['familySetBounds'] = [{'exerciseFamilyId': 'retained_family', 'maximumWeeklySets': 9}]
    calls = []

    def reply(*args, **kwargs):
        calls.append(1)
        return json.dumps({'findings': []}), None, None

    monkeypatch.setattr(plan_review, '_review_call', reply)
    before = copy.deepcopy(candidate)
    result = plan_review.review_requirements(None, candidate, messages)
    assert calls == [1]
    assert result['passed'] and result['requirements'] == before['requirements']
    assert not result['sourceReview'].get('codeAnsweredChecks')
    assert candidate == before


def test_structured_source_review_does_not_rejudge_backend_authorization_metadata():
    context = {'requirements': {'executionRules': []},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Approved scoped amendment.'}},
        'structuredAuthority': {'matchedPaths': []}}
    _, facts = plan_review._with_review_refs(context)
    schema = plan_review._requirements_review_schema(context, facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    assert all('authorization' not in branch['properties']['check']['enum']
               for branch in schema['properties']['findings']['items']['anyOf'])


def test_requirements_updates_bind_current_base_in_code():
    from test_workout_generator_planning_tools import requirement_messages
    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    messages.append({'role': 'user', 'content': 'Change the frequency to three sessions per week.'})
    tool = planning_tools.workout_requirements_tool(equipment, messages)
    assert 'baseRequirementsId' not in tool['function']['parameters']['properties']
    updated = planning_tools.set_workout_requirements({'updates': {'sessionsPerWeek': 3}}, messages, equipment)
    assert updated['baseRequirementsId'] == stored['requirementsId']
    assert updated['requirements']['sessionsPerWeek'] == 3


def test_retained_cached_amendment_review_resolves_its_exact_historical_base():
    root = Path(__file__).resolve().parents[1] / 'build/workout_superset_capability_fresh_e2e_20261029'
    if not (root / 'conversation_meta.json').exists():
        pytest.skip('Retained failed amendment is unavailable.')
    identifier = json.loads((root / 'conversation_meta.json').read_text(encoding='utf-8'))['active_conversation_id']
    messages = json.loads((root / 'workouts/conversation_sessions' / identifier / 'messages.json').read_text(encoding='utf-8'))
    candidate_index = next(index for index, message in enumerate(messages)
        if message.get('role') == 'tool' and 'structuredAuthority.matchedPaths does not include' in message.get('content', ''))
    candidate = json.loads(messages[candidate_index]['content'])
    _, latest = planning_tools.latest_requirement_candidate(messages[:candidate_index + 1])
    assert latest['requirementsId'] != candidate['baseRequirementsId']
    scope = plan_review._requirements_review_scope(candidate, messages[:candidate_index + 1])
    assert scope is not None
    assert scope['baseRequirementsId'] == candidate['baseRequirementsId']
    assert scope['baseSourceReviewPassed'] is True
    assert '/executionRules/12' in scope['changedPaths']


def test_implementation_finding_cannot_omit_its_code_owned_check():
    context = {'requirements': {'executionRules': []},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Use my supplied requirements.'}},
        'structuredAuthority': {'matchedPaths': []},
        'implementationChecks': {'physical_set_count': {'answer': 'Count once.'}}}
    _, facts = plan_review._with_review_refs(context)
    schema = plan_review._requirements_review_schema(context, facts, plan_review._STRUCTURED_SOURCE_RESPONSE)
    source = next(ref for ref, path in facts.items() if path == '/sourceMessages/SOURCE_0')
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'path': source,
        'message': 'Question about accounting.', 'evidencePaths': [source], 'repair': 'Check counting.',
        'action': 'repair', 'decisionId': None, 'newConflictEvidencePaths': [],
        'check': 'implementation', 'implementationCheck': None}
    with pytest.raises(ValidationError):
        validate({'findings': [finding]}, schema)
    finding['implementationCheck'] = 'physical_set_count'
    validate({'findings': [finding]}, schema)
    assert _strict_parameters_compatible(schema)


@pytest.mark.parametrize('corrected', [True, False])
def test_schema_rejected_review_gets_one_bounded_correction(monkeypatch, corrected):
    schema = {'type': 'object', 'properties': {'check': {'enum': ['source_omission']}},
              'required': ['check'], 'additionalProperties': False}
    rejected = {'check': 'source_conflict'}
    calls = []

    def respond(client, request, **options):
        calls.append(request)
        if len(calls) == 1 or not corrected:
            try:
                validate(rejected, schema)
            except ValidationError as error:
                raise plan_review.StructuredResponseError(json.dumps(rejected), error)
        return json.dumps({'check': 'source_omission'}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    if corrected:
        result, _, _ = plan_review._review_call(None, [], retry=True, output_schema=schema)
        validate(json.loads(result), schema)
    else:
        with pytest.raises(plan_review.StructuredResponseError):
            plan_review._review_call(None, [], retry=True, output_schema=schema)
    assert len(calls) == 2
    assert json.loads(calls[1][-1]['content'])['rejectedResponse'] == rejected


def _review_ref_paths(context):
    references = {}
    def visit(value, path=''):
        if isinstance(value, dict):
            if value.get('_reviewRef'):
                references[value['_reviewRef']] = path
            for key, child in value.items():
                if key != '_reviewRef':
                    visit(child, path + '/' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + '/' + str(index))
    visit(context)
    return references


def test_retained_rejected_source_findings_replay_with_semantic_refs_and_code_provenance(monkeypatch):
    root = Path(__file__).resolve().parents[1] / '.codex/workout_quality_validation_20261104'
    evidence = root / 'rejected_source_review.json'
    transcript = root / 'workouts/conversation_sessions/21faea24-b1d4-4504-b66d-c6cd2d1a3235/messages.json'
    if not evidence.exists() or not transcript.exists():
        pytest.skip('Retained source-review response is unavailable.')
    rejected = json.loads(evidence.read_text(encoding='utf-8'))
    with pytest.raises(ValidationError):
        validate(rejected['response'], rejected['schema'])
    messages = json.loads(transcript.read_text(encoding='utf-8'))
    index, candidate = next((index, json.loads(message['content'])) for index, message in enumerate(messages)
        if message.get('role') == 'tool' and message.get('content', '').startswith('{')
        and json.loads(message['content']).get('sourceReview', {}).get('failure'))
    before = copy.deepcopy(candidate['requirements'])
    calls = []
    def replay(client, request, **options):
        calls.append(1)
        assert len(calls) == 1, 'Known source provenance must not require a citation retry.'
        context = json.loads(request[-1]['content'])
        facts = _review_ref_paths(context)
        assert not any(reference.startswith('FACT_') for reference in facts)
        assert 'COVERAGE_VERTICAL_PULL_WEEKLY' in facts and 'DECISION_0' in facts
        by_path = {path: reference for reference, path in facts.items()}
        response = copy.deepcopy(rejected['response'])
        for finding in response['findings']:
            finding['path'] = by_path[rejected['facts'][finding['path']]]
            for field in ('evidencePaths', 'newConflictEvidencePaths'):
                finding[field] = [by_path[rejected['facts'][reference]] for reference in finding[field]]
        validate(response, options['output_schema'])
        return json.dumps(response), None, None
    monkeypatch.setattr(plan_review, 'chat_call', replay)
    result = plan_review.review_requirements(None, candidate, messages[:index - 1])
    assert not result['sourceReview'].get('failure'), result.get('errors')
    assert result['passed'] and len(calls) == 1
    assert result['requirements'] == before
    actual = result['sourceReview']['findings']
    assert len(actual) == len(rejected['response']['findings']) == 3
    for found, original in zip(actual, rejected['response']['findings']):
        assert found['message'] == original['message'] and found['repair'] == original['repair']
        assert found['severity'] == 'warning' and found['action'] == 'clarify'
        assert '/sourceMessages/SOURCE_0' in found['evidencePaths']
        assert original['message'] in result['requirementsPreview']


@pytest.mark.parametrize(('severity', 'basis', 'check', 'passed'), [
    ('warning', 'uncertainty', 'scope_ambiguity', True),
    ('blocking', 'uncertainty', 'scope_ambiguity', False),
    ('warning', 'established_violation', 'source_omission', False),
    ('warning', 'uncertainty', 'source_conflict', False),
])
def test_source_review_preserves_uncertainty_severity_but_blocks_material_findings(monkeypatch, severity, basis, check, passed):
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER
    equipment, _, stored, _ = planning_case()
    requirements = stored['requirements']
    messages = [{'role': 'user', 'content': STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements)},
                {'role': 'user', 'content': 'Also consider whether future exercise qualification is uncertain.'}]
    candidate = planning_tools.set_workout_requirements({}, messages, equipment)
    def replay(client, request, **options):
        context = json.loads(request[-1]['content'])
        assert context['sourceMessages']['SOURCE_0']['_reviewRef'] == 'SOURCE_0'
        facts = _review_ref_paths(context)
        by_path = {path: reference for reference, path in facts.items()}
        target = 'SOURCE_1' if check == 'source_conflict' else by_path['/requirements/auditTargets']
        if check == 'source_omission':
            target = next(field['_reviewRef'] for field in context['extractionFields']
                          if field['field'] == 'auditTargets')
        response = {'findings': [{'severity': severity, 'basis': basis, 'check': check,
            'path': target, 'message': 'Future qualification remains uncertain.',
            'evidencePaths': [target], 'repair': 'Keep the qualification gate in the planning stage.',
            'action': 'clarify', 'decisionId': None, 'newConflictEvidencePaths': [], 'implementationCheck': None}]}
        validate(response, options['output_schema'])
        return json.dumps(response), None, None
    monkeypatch.setattr(plan_review, 'chat_call', replay)
    result = plan_review.review_requirements(None, candidate, messages)
    assert not result['sourceReview'].get('failure'), result.get('errors')
    assert result['passed'] is passed
    assert len(result['sourceReview']['findings']) == 1
    assert result['sourceReview']['findings'][0]['severity'] == ('warning' if passed else 'blocking')
    assert result['requirements'] == requirements


def test_unknown_source_provenance_keeps_the_bounded_user_only_selector(monkeypatch):
    context = {'requirements': {'auditTargets': {}}, 'auditPolicy': {'assumptions': []},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Use the stated limits.'},
                           'SOURCE_1': {'role': 'assistant', 'content': 'An unsupported suggestion.'}}}
    request, facts = plan_review._with_semantic_review_refs(context)
    finding = {'path': '/requirements/auditTargets', 'message': 'A source instruction may be missing.',
        'evidencePaths': ['/auditPolicy'], 'repair': 'Check its original source.'}
    plan_review._attach_known_source_references(finding, context)
    assert finding['evidencePaths'] == ['/auditPolicy']
    calls = []
    def select(client, messages, **options):
        calls.append(1)
        schema = options['output_schema']
        assert schema['properties']['findingSourceReferences']['properties']['FINDING_A']['enum'] == ['NONE', 'SOURCE_0']
        return '{"findingSourceReferences":{"FINDING_A":"SOURCE_0"}}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', select)
    plan_review._select_missing_source_references(None, request, facts, [finding], None)
    assert len(calls) == 1
    assert finding['evidencePaths'] == ['/auditPolicy', '/sourceMessages/SOURCE_0']
    plan_review._select_missing_source_references(None, request, facts, [finding], None)
    assert len(calls) == 1
