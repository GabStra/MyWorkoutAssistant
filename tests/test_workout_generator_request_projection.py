import copy
import json

from workout_generator_pkg.interactive_shell import _bind_planning_intent
from workout_generator_pkg.planner_context import compact_planner_request, request_planning_state


def test_wire_projection_keeps_sources_candidate_evidence_and_open_findings():
    findings = [{'id': 'F1', 'detail': 'Keep this unresolved concern.'}]
    assessment = {'groups': [{'findingIds': ['F1']}]}
    decisions = {'choice': 'User approved this exact choice.'}
    state = {
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Keep exactly 9 sets.'}},
        'resolvedDecisions': decisions,
        'currentDraft': {'workouts': [{'exercises': [{'numWorkSets': 9}]}]},
        'trainingEvidence': {'LIBRARY_0': {'records': [1, 2]}},
        'otherToolResults': {'ask_user': {'userQuestion': {'question': 'Still unresolved?'}}},
        'lastAudit': {'errors': [{'code': 'open'}], 'reviewFindings': findings,
            'reviewWarnings': findings, 'findingsAssessment': assessment,
            'resolvedDecisions': decisions,
            'review': {'findings': findings, 'assessment': assessment,
                'sourceCoverage': ['SOURCE_0']}}}
    image = {'role': 'user', 'content': 'Original image context',
             'imageAttachments': [{'path': 'original.png', 'sha256': 'unchanged'}]}
    messages = [{'role': 'system', 'content': 'Current planning state (backend data).\n' + json.dumps(state)}, image]
    original = copy.deepcopy(messages)
    projected = compact_planner_request(messages)
    current = request_planning_state(projected)
    assert messages == original
    assert projected[-1] == image
    for field in ('sourceMessages', 'resolvedDecisions', 'currentDraft', 'trainingEvidence', 'otherToolResults'):
        assert current[field] == state[field]
    assert current['lastAudit']['errors'] == state['lastAudit']['errors']
    assert current['lastAudit']['reviewFindings'] == findings
    assert current['lastAudit']['findingsAssessment'] == assessment
    assert current['lastAudit']['review'] == {'sourceCoverage': ['SOURCE_0']}
    assert len(json.dumps(projected)) < len(json.dumps(messages))


def test_wire_projection_references_only_identical_shared_selection_facts():
    sources = {'SOURCE_0': {'role': 'user', 'content': 'Keep 111 kg and exactly 9 sets.'}}
    unknown = {'unsupported_trunk': {'status': 'unknown', 'source': None}}
    reviewed = {'source': 'exact-form evidence', 'limbMode': 'unilateral'}
    state = {
        'sourceMessages': sources,
        'resolvedDecisions': {'source': 'SOURCE_0', 'confirmedSetupAccess': {'retainedResources': ['Rack']}},
        'exerciseCandidates': {'LIBRARY_0': {'exerciseType': 'WEIGHT',
            'reviewedExecution': reviewed, 'programmingDemandFacts': unknown}},
        'cachedCandidateIndex': {'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT'}},
        'candidateAlternatives': {'LIBRARY_2': {'exerciseType': 'WEIGHT'}},
        'exerciseDemandEvidence': {
            'candidates': {'LIBRARY_0': {'exerciseType': 'WEIGHT', 'reviewedExecution': reviewed},
                'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT'},
                'LIBRARY_2': {'exerciseType': 'BODY_WEIGHT'},
                'LIBRARY_3': {'exerciseType': 'WEIGHT'}},
            'programmingDemandFacts': {'LIBRARY_0': unknown, 'LIBRARY_1': unknown},
            'demandDistribution': {'unavailableGroups': {'unsupported_trunk': ['LIBRARY_0', 'LIBRARY_1']}},
            'policy': {'unknownEvidence': 'Unknown is not absent or safe.'}},
        'parallelPreparation': {'sourceBudgetAuthority': {'sourceMessages': sources,
            'restrictionPolicy': {'excludedDefinitionIds': ['LIBRARY_3']}}},
        'rejectedWeekPreparation': {'sourceBudgetAuthority': {'sourceMessages': {'SOURCE_0': {'content': 'Old'}}}},
        'trainingEvidenceSummary': {'LIBRARY_1': {'relatedHistoryStatus': 'checked',
            'candidateConfigurationHistory': {'relatedLoadTransferSupported': False}}}}
    messages = [{'role': 'system', 'content': 'Current planning state (backend data).\n' + json.dumps(state)}]
    saved = copy.deepcopy(messages)
    projected = compact_planner_request(messages)
    current = request_planning_state(projected)
    demand = current['exerciseDemandEvidence']
    assert demand['candidates']['LIBRARY_0'] == {'factsRef': 'exerciseCandidates.LIBRARY_0'}
    assert demand['candidates']['LIBRARY_1'] == {'factsRef': 'cachedCandidateIndex.LIBRARY_1'}
    assert demand['programmingDemandFacts']['LIBRARY_0'] == {
        'factsRef': 'exerciseCandidates.LIBRARY_0.programmingDemandFacts'}
    assert demand['candidates']['LIBRARY_2'] == state['exerciseDemandEvidence']['candidates']['LIBRARY_2']
    assert demand['candidates']['LIBRARY_3'] == state['exerciseDemandEvidence']['candidates']['LIBRARY_3']
    assert demand['programmingDemandFacts']['LIBRARY_1'] == unknown
    assert current['parallelPreparation']['sourceBudgetAuthority'] == {
        'sourceMessagesRef': 'sourceMessages', 'restrictionPolicy': {'excludedDefinitionIds': ['LIBRARY_3']}}
    for field in ('sourceMessages', 'resolvedDecisions', 'exerciseCandidates', 'cachedCandidateIndex',
                  'candidateAlternatives', 'trainingEvidenceSummary', 'rejectedWeekPreparation'):
        assert current[field] == state[field]
    assert demand['demandDistribution'] == state['exerciseDemandEvidence']['demandDistribution']
    assert demand['policy'] == state['exerciseDemandEvidence']['policy']
    assert compact_planner_request(projected) == projected
    assert messages == saved
    assert len(json.dumps(projected)) < len(json.dumps(messages))


def test_duplicate_candidate_facts_share_exact_evidence_without_merging_identity_or_unknowns():
    unknown = {'status': 'unknown', 'source': None,
        'limitation': 'Missing evidence does not establish adequate regional training. ' * 12}
    sourced = {**unknown, 'status': 'present', 'source': 'reviewed annotation'}
    state = {
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Exclude all deadlift variants; keep exactly 9 sets.'}},
        'requirements': {'maximumSets': 9},
        'restrictionPolicy': {'excludedDefinitionIds': ['LIBRARY_9']},
        'resolvedDecisions': {'DECISION_0': {'sourceReferences': ['SOURCE_0'], 'choice': 'Keep the stated exclusion.'}},
        'trainingEvidence': {'LIBRARY_1': {'candidateConfigurationHistory': {'sources': [
            {'sourceReference': 'LIBRARY_2', 'sourceMovementRelation': 'related_not_equivalent'}]}}},
        'historyExecutionContexts': {'CONTEXT_0': {'source': 'actual logged configuration'}},
        'exerciseCandidates': {
            'LIBRARY_0': {'name': 'First movement', 'regionalMuscleFacts': unknown,
                'programmingDemandFacts': unknown},
            'LIBRARY_1': {'name': 'Distinct movement', 'regionalMuscleFacts': unknown,
                'programmingDemandFacts': sourced}},
        'cachedCandidateIndex': {'LIBRARY_2': {'name': 'Cached movement',
            'regionalMuscleFacts': sourced, 'programmingDemandFacts': unknown}},
        'candidateAlternatives': {'LIBRARY_3': {'name': 'Alternative movement',
            'regionalMuscleFacts': unknown}}}
    messages = [{'role': 'system', 'content': 'Current planning state (backend data).\n' + json.dumps(state)}]
    original = copy.deepcopy(messages)
    projected = compact_planner_request(messages)
    current = request_planning_state(projected)
    assert current['exerciseCandidates']['LIBRARY_1']['regionalMuscleFacts'] == {
        'factsRef': 'exerciseCandidates.LIBRARY_0.regionalMuscleFacts'}
    assert current['cachedCandidateIndex']['LIBRARY_2']['programmingDemandFacts'] == {
        'factsRef': 'exerciseCandidates.LIBRARY_0.programmingDemandFacts'}
    assert current['exerciseCandidates']['LIBRARY_1']['programmingDemandFacts'] == sourced
    assert current['cachedCandidateIndex']['LIBRARY_2']['regionalMuscleFacts'] == sourced
    restored = copy.deepcopy(current)
    for collection in ('exerciseCandidates', 'cachedCandidateIndex', 'candidateAlternatives'):
        for entry in restored[collection].values():
            for field in ('regionalMuscleFacts', 'programmingDemandFacts'):
                if isinstance(entry.get(field), dict) and 'factsRef' in entry[field]:
                    target_collection, reference, target_field = entry[field]['factsRef'].split('.')
                    entry[field] = current[target_collection][reference][target_field]
    assert restored == state
    assert compact_planner_request(projected) == projected
    assert messages == original
    assert len(json.dumps(projected)) < len(json.dumps(messages))


def test_selection_context_uses_one_shared_preflight_without_losing_blocker_evidence(monkeypatch):
    from workout_generator_pkg import session_drafting
    from workout_generator_pkg.planner_context import _preparation_selection_context
    options = {'admissibleDefinitionIds': ['LIBRARY_0'], 'unresolvedConfigurations': {
        'LIBRARY_1': [{'code': 'unverified_fixed_bodyweight_capability', 'sourceReference': 'SOURCE_1'}]}}
    calls = []
    def preflight(messages, equipment, history):
        calls.append((messages, equipment, history))
        return options
    monkeypatch.setattr(session_drafting, 'preparation_selection_options', preflight)
    state = {'requirementsApproved': True, 'constructionTask': {'stage': 'choose_movements'},
        'requirements': {}, 'exerciseCandidates': {'LIBRARY_0': {'name': 'Admitted'},
            'LIBRARY_1': {'name': 'Needs an answer'}},
        'candidateAlternatives': {'LIBRARY_1': {'name': 'Needs an answer'}},
        'cachedCandidateIndex': {'LIBRARY_1': {'name': 'Needs an answer'}},
        'exerciseDemandEvidence': {},
        'sourceMessages': {'SOURCE_1': {'role': 'user', 'content': 'No capability established.'}},
        'trainingEvidenceSummary': {'LIBRARY_1': {'status': 'unknown', 'relatedLoadTransferSupported': False}}}
    sources = copy.deepcopy(state['sourceMessages'])
    evidence = copy.deepcopy(state['trainingEvidenceSummary'])
    _preparation_selection_context(state, ['original'], {'library': True}, 'history')
    assert calls == [(['original'], {'library': True}, 'history')]
    assert state['preparationSelectionOptions'] == options
    assert set(state['exerciseCandidates']) == {'LIBRARY_0'}
    assert state['candidateAlternatives'] == state['cachedCandidateIndex'] == {}
    assert set(state['exerciseDemandEvidence']['programmingDemandFacts']) == {'LIBRARY_0'}
    assert state['sourceMessages'] == sources
    assert state['trainingEvidenceSummary'] == evidence


def test_fresh_shell_ignores_a_previous_export_incumbent(tmp_path, monkeypatch):
    from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
    from workout_generator_pkg.conversation_meta import save_incumbent_reference
    from workout_generator_pkg.conversation_store import list_conversations, load_conversation_record
    save_incumbent_reference({'messagesPath': 'previous.json', 'draftId': 'A'}, str(tmp_path))
    deps = make_shell_deps(tmp_path, chat_results=[('Ready', None), ('Ready again', None)],
                           generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ['A new plan with the same goals', '/clear', 'Another fresh plan', '/exit'])
    records = [load_conversation_record(row['conversation_id'], str(tmp_path))
               for row in list_conversations(str(tmp_path))]
    assert len(records) == 2
    for record in records:
        assert record['metadata']['planningIntent'] == 'fresh'
        assert record['messages'][0]['planningIntent'] == 'fresh'
        assert all('incumbentPlan' not in message for message in record['messages'])


def test_explicit_edit_intent_survives_resume_without_global_inheritance():
    reference = {'messagesPath': 'approved.json', 'draftId': 'A'}
    messages = [{'role': 'system', 'content': 'Application'}]
    _bind_planning_intent(messages, reference)
    _bind_planning_intent(messages)
    assert messages[0]['planningIntent'] == 'edit'
    assert messages[0]['incumbentPlan'] == reference


def test_declined_solver_menu_pauses_with_user_question():
    from workout_generator_pkg.interactive_shell import _solver_menu_decline_question
    result = {'passed': False, 'errors': [{'code': 'solver_menu_declined'}]}
    _solver_menu_decline_question(result)
    assert result['userQuestion']['options']
    assert 'unchanged' in result['userQuestion']['reason']


def test_shell_sends_compact_projection_to_real_api_client(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg import interactive_shell, api_client
    equipment, _, _, _ = planning_case()
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    findings = [{'id': 'F1', 'detail': 'Retain this concern'}]
    snapshot = {'requirementsApproved': False, 'sourceMessages': {},
        'lastAudit': {'reviewFindings': findings, 'reviewWarnings': findings,
                      'review': {'findings': findings}}}
    full = [{'role': 'system', 'content': 'Current planning state (backend data).\n' + json.dumps(snapshot)}]
    original = copy.deepcopy(full)
    monkeypatch.setattr(interactive_shell, '_messages_for_api', lambda *_args: full)
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com/beta', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    sent = []
    def create(**kwargs):
        sent.append(kwargs['messages'])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='Ready', tool_calls=None, reasoning_content=None))], usage=None)
    client = SimpleNamespace(with_options=lambda **_kwargs: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    deps.chat_call_with_loading = lambda _client, messages, tools, logger, **_options: api_client.chat_call(
        client, messages, tools=tools, reasoning_effort=None, require_strict_tool_delivery=True)
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    inputs = iter(['Use the original requirements.', '/exit'])
    monkeypatch.setattr('builtins.input', lambda _prompt='': next(inputs))
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    interactive_shell.main(deps=deps)
    assert len(sent) == 1
    audit = request_planning_state(sent[0])['lastAudit']
    assert audit['reviewFindings'] == findings
    assert 'reviewWarnings' not in audit and 'findings' not in audit['review']
    assert full == original


def test_empty_configuration_domain_reaches_question_instead_of_selection(tmp_path, monkeypatch):
    from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg import interactive_shell

    equipment, _, _, _ = planning_case()
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    snapshot = {'requirementsApproved': True, 'sourceMessages': {},
        'constructionTask': {'action': 'Choose movements', 'stage': 'choose_movements',
                             'remainingWeeklySessions': 2},
        'preparationRepairTask': {'allowedDefinitionIds': []},
        'preparationSelectionOptions': {'admissibleDefinitionIds': [],
            'unresolvedConfigurations': {'LIBRARY_0': [{'code': 'unverified_fixed_bodyweight_capability'}]},
            'unresolvedConfigurationNames': {'LIBRARY_0': 'Push-Up'}}}
    monkeypatch.setattr(interactive_shell, 'requirements_approved', lambda *args: True)
    monkeypatch.setattr(interactive_shell, 'pending_reaudit', lambda *args: None)
    monkeypatch.setattr(interactive_shell, 'request_planning_state', lambda *args: snapshot)
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    observed = []

    def respond(client, messages, tools, logger, **options):
        observed.append(tools)
        assert tools == [interactive_shell.ASK_USER_TOOL]
        assert options['tool_choice']['function']['name'] == interactive_shell.ASK_USER_TOOL['function']['name']
        return 'Can you perform this exact push-up configuration?', None, None

    deps.chat_call_with_loading = respond
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    run_shell(monkeypatch, deps, ['Choose a workout', '/exit'])
    assert len(observed) == 1


def test_selection_profiles_enforce_admissible_choices_at_provider_boundary(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from workout_generator_pkg import api_client, session_drafting
    from workout_generator_pkg.planner_context import planner_response_profile

    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    tool = session_drafting.prepare_workout_sessions_tool([], {},
        selection_options={'admissibleDefinitionIds': ['LIBRARY_0']})
    for state in ({'constructionTask': {'stage': 'choose_movements', 'remainingWeeklySessions': 3}},
                  {'preparationRepairTask': {'needsAlternatives': True, 'errors': []}}):
        captured = {}

        class CapturedRequest(Exception):
            pass

        def create(**kwargs):
            captured.update(kwargs)
            raise CapturedRequest()

        def with_options(**kwargs):
            captured['clientOptions'] = kwargs
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        profile = {key: value for key, value in planner_response_profile(state).items() if key != 'activity'}
        with pytest.raises(CapturedRequest):
            api_client.chat_call(SimpleNamespace(with_options=with_options),
                [{'role': 'user', 'content': 'Select an admissible movement.'}], tools=[tool], retry=False, **profile)
        delivered = captured['tools'][0]['function']
        assert delivered['strict'] is True
        assert captured['clientOptions']['base_url'] == 'https://api.deepseek.com/beta'
        choice = delivered['parameters']['properties']['sessions']['items']['properties'][
            'blocks']['items']['properties']['exercises']['items']['properties']['definition_id']
        assert choice['enum'] == ['LIBRARY_0']

    ordinary_repair = planner_response_profile({'preparationRepairTask': {'errors': []}})
    assert ordinary_repair['reasoning_effort'] == 'low'
    assert not ordinary_repair.get('require_strict_tool_delivery')
