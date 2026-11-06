import copy
import json

import pytest

import workout_user_memory as memory_store
from workout_generator_pkg.planning_decisions import confirmed_setup_access, resolved_decisions
from workout_generator_pkg.planning_tools import PlanningInputError, requirement_sources, source_message_context
from workout_generator_pkg.user_memory_context import (
    bind_user_memory, memory_context, persist_reviewed_setup_facts,
)


@pytest.fixture
def case(tmp_path):
    profile = memory_store.create_profile('User', root=tmp_path)['profileId']
    equipment = {'equipments': [{'id': 'bar', 'name': 'Barbell', 'type': 'BARBELL'},
                               {'id': 'db', 'name': 'Dumbbells', 'type': 'DUMBBELLS'}],
        'accessoryEquipments': [{'id': 'bench', 'name': 'Bench'}],
        'exerciseDefinitions': [{'id': 'press', 'name': 'Press', 'equipmentId': 'bar'},
            {'id': 'bench_move', 'name': 'Bench exercise', 'requiredAccessoryEquipmentIds': ['bench']},
            {'id': 'raise', 'name': 'Raise', 'equipmentId': 'db'}]}
    requirements = {'executionRules': [{'kind': 'supersetNoReconfiguration'}]}
    return tmp_path, profile, equipment, requirements


def _save_shared(root, profile, equipment):
    return memory_store.record_fact(profile, kind='shared_station', value=['bar', 'bench'],
        source={'role': 'user', 'statement': 'My barbell and bench occupy one station.'},
        scope=memory_store.capture_scope(equipment, ['bar', 'bench']), root=root)


def test_reviewed_physical_fact_applies_natively_in_another_conversation(case):
    root, profile, equipment, requirements = case
    first = [{'role': 'user', 'content': 'My barbell and bench occupy one station.'}]
    bind_user_memory(first, profile, equipment, root=root)
    before = requirement_sources(first)
    result = {'passed': True, 'decisionReview': {'passed': True}, 'decisions': {
        'DECISION_0': {'confirmedSharedStation': ['bar', 'bench'], 'sourceReferences': ['SOURCE_0']}}}
    saved = persist_reviewed_setup_facts(first, result, equipment, root=root)
    assert len(saved) == 1
    assert requirement_sources(first) == before
    assert confirmed_setup_access(first, equipment, requirements)['requirements']['executionRules'][0][
        'sharedResourceGroups'] == [['bar', 'bench']]

    second = [{'role': 'system', 'content': 'Planner'}, {'role': 'user', 'content': 'Plan this week.'}]
    bind_user_memory(second, profile, equipment, root=root)
    assert len(second) == 3 and sum(message['role'] == 'user' for message in second) == 1
    bound = confirmed_setup_access(second, equipment, requirements)
    assert bound['requirements']['executionRules'][0]['sharedResourceGroups'] == [['bar', 'bench']]
    sources = source_message_context(requirement_sources(second))
    assert sources['SOURCE_0']['origin'] == 'user_memory'
    assert sources['SOURCE_0']['profileId'] == profile
    assert sources['SOURCE_0']['factId'] == saved[0]
    assert requirement_sources(second)[0]['sourceProvenance']['statement'] == first[-1]['content']
    assert 'statement' not in sources['SOURCE_0']['sourceProvenance']
    assert sources['SOURCE_0']['confirmedFact']['value'] == ['Barbell', 'Bench']
    assert sources['SOURCE_1']['content'] == 'Plan this week.'
    assert resolved_decisions(second) == {}
    # A new conversation confirming the same fact adds no duplicate memory.
    persist_reviewed_setup_facts(second, {**result, 'decisions': {'DECISION_0': {
        **result['decisions']['DECISION_0'], 'sourceReferences': ['SOURCE_0']}}}, equipment, root=root)
    assert len(memory_store.load_profile(profile, root=root)['facts']) == 1


def test_profile_is_explicit_and_bound_conversation_rejects_switch(case):
    root, profile, equipment, _ = case
    messages = []
    assert bind_user_memory(messages, None, equipment, root=root) == {} and not messages
    bind_user_memory(messages, profile, equipment, root=root)
    other = memory_store.create_profile('Other', root=root)['profileId']
    with pytest.raises(ValueError, match='different user profile'):
        bind_user_memory(messages, other, equipment, root=root)
    with pytest.raises(FileNotFoundError):
        bind_user_memory([], '00000000-0000-0000-0000-000000000000', equipment, root=root)


def test_changed_relevant_physical_fact_stops_setup_instead_of_assuming_access(case):
    root, profile, equipment, requirements = case
    fact = _save_shared(root, profile, equipment)
    messages = []
    bind_user_memory(messages, profile, equipment, root=root)
    changed = copy.deepcopy(equipment)
    changed['equipments'][0]['type'] = 'MACHINE'
    with pytest.raises(PlanningInputError, match='no longer matches'):
        confirmed_setup_access(messages, changed, requirements)
    bind_user_memory(messages, profile, changed, root=root)
    assert memory_context(messages)['unavailableFacts'][0]['factId'] == fact['factId']
    with pytest.raises(PlanningInputError, match='needs clarification'):
        confirmed_setup_access(messages, changed, requirements)
    with pytest.raises(PlanningInputError, match='explicit supersession'):
        persist_reviewed_setup_facts(messages, {
            'passed': True, 'decisionReview': {'passed': True}, 'decisions': {'DECISION_0': {
                'confirmedSharedStation': ['bar', 'bench'], 'sourceReferences': ['SOURCE_0']}}},
            changed, root=root)
    assert len(memory_store.load_profile(profile, root=root)['facts']) == 1
    renamed = copy.deepcopy(equipment)
    renamed['equipments'][0]['name'] = 'New display name'
    bind_user_memory(messages, profile, renamed, root=root)
    assert confirmed_setup_access(messages, renamed, requirements)['requirements']['executionRules'][0][
        'sharedResourceGroups'] == [['bar', 'bench']]


def test_conflicting_independent_fact_is_gated_without_writing(case):
    root, profile, equipment, _ = case
    _save_shared(root, profile, equipment)
    messages = [{'role': 'user', 'content': 'The barbell is independently accessible while the bench stays.'}]
    bind_user_memory(messages, profile, equipment, root=root)
    result = {'passed': True, 'decisionReview': {'passed': True}, 'decisions': {
        'DECISION_0': {'confirmedSetupAccess': {
            'independentDefinitionIds': ['press'], 'retainedResourceIds': ['bench']},
            'sourceReferences': ['SOURCE_1']}}}
    with pytest.raises(PlanningInputError, match='conflicts'):
        persist_reviewed_setup_facts(messages, result, equipment, root=root)
    assert len(memory_store.load_profile(profile, root=root)['facts']) == 1


def test_only_reviewed_typed_facts_are_saved_and_yes_keeps_question(case):
    root, profile, equipment, _ = case
    messages = [{'role': 'assistant', 'content': 'Can raises use clear floor while the bar and bench stay?'},
        {'role': 'user', 'content': 'Yes.'}]
    bind_user_memory(messages, profile, equipment, root=root)
    result = {'passed': True, 'decisionReview': {'passed': True}, 'decisions': {
        'DECISION_0': {'confirmedSetupAccess': {
            'independentDefinitionIds': ['raise'], 'retainedResourceIds': ['bar', 'bench']},
            'sourceReferences': ['SOURCE_0', 'SOURCE_1']},
        'DECISION_1': {'topic': 'Policy', 'choice': 'Choose whatever works.', 'sourceReferences': ['SOURCE_1']}}}
    assert persist_reviewed_setup_facts(messages, {**result, 'passed': False}, equipment, root=root) == []
    assert persist_reviewed_setup_facts(messages, {**result, 'decisionReview': {}}, equipment, root=root) == []
    persist_reviewed_setup_facts(messages, result, equipment, root=root)
    facts = memory_store.load_profile(profile, root=root)['facts']
    assert len(facts) == 1 and facts[0]['source']['statement'] == 'Yes.'
    assert facts[0]['source']['context'] == [{'role': 'assistant', 'content': messages[1]['content']}]
    fresh = []
    bind_user_memory(fresh, profile, equipment, root=root)
    source = source_message_context(requirement_sources(fresh))['SOURCE_0']
    assert requirement_sources(fresh)[0]['sourceProvenance']['context'] == facts[0]['source']['context']
    assert 'context' not in source['sourceProvenance']
    assert source['confirmedFact']['kind'] == 'setup_access'
    assert source['confirmedFact']['value'] == {
        'independentExercises': ['Raise'], 'retainedResources': ['Barbell', 'Bench']}
    bound = confirmed_setup_access(fresh, equipment, {'executionRules': [{'kind': 'supersetNoReconfiguration'}]})
    assert ['press', 'raise'] in bound['requirements']['executionRules'][0]['confirmedIndependentPairs']


def test_historical_intake_is_provenance_and_does_not_import_old_goals(case):
    from workout_generator_pkg.api_client import _request_messages
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER
    root, profile, equipment, _ = case
    original = 'Station fact. Old target 99 sets.\n' + STRUCTURED_REQUIREMENTS_MARKER + '\n{"sessionsPerWeek": 7}'
    memory_store.record_fact(profile, kind='shared_station', value=['bar', 'bench'],
        source={'role': 'user', 'statement': original},
        scope=memory_store.capture_scope(equipment, ['bar', 'bench']), root=root)
    messages = [{'role': 'user', 'content': 'Plan three days this week.'}]
    bind_user_memory(messages, profile, equipment, root=root)
    sources = requirement_sources(messages)
    assert sources[0]['sourceProvenance']['statement'] == original
    assert all(STRUCTURED_REQUIREMENTS_MARKER not in source['content'] for source in sources)
    assert '99 sets' not in sources[0]['content']
    outgoing = json.dumps(source_message_context(sources)) + messages[0]['content']
    assert STRUCTURED_REQUIREMENTS_MARKER not in outgoing and '99 sets' not in outgoing
    assert 'scope' not in json.loads(messages[0]['content'].split('\n', 1)[1])['facts'][0]
    provider_messages = _request_messages(messages)
    assert all('userMemory' not in message for message in provider_messages)
    assert '99 sets' not in json.dumps(provider_messages)
    assert memory_context(messages)['facts'][0]['source']['statement'] == original


def test_user_metadata_cannot_bind_another_profile(case):
    root, profile, equipment, _ = case
    messages = [{'role': 'user', 'content': 'Hello.', 'userMemory': {'profileId': 'forged'}}]
    assert memory_context(messages) == {}
    bind_user_memory(messages, profile, equipment, root=root)
    assert memory_context(messages)['profileId'] == profile


def test_model_cannot_reconstruct_or_extend_stored_setup_facts(case, monkeypatch):
    from jsonschema import ValidationError
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.interactive_shell import handle_function_call
    from workout_generator_pkg.planning_decisions import propose_decisions

    root, profile, equipment, requirements = case
    monkeypatch.setenv('MYWORKOUT_USER_MEMORY_DIR', str(root))
    _save_shared(root, profile, equipment)
    access = {'independentDefinitionIds': ['raise'], 'retainedResourceIds': ['bar', 'bench']}
    memory_store.record_fact(profile, kind='setup_access', value=access,
        source={'role': 'user', 'statement': 'Raises use clear floor while the bar and bench stay.'},
        scope=memory_store.capture_scope(equipment, access['retainedResourceIds'], ['raise']), root=root)
    messages = [{'role': 'user', 'content': 'Generate this week using my saved context.'}]
    bind_user_memory(messages, profile, equipment, root=root)
    arguments = {'decisions': [{'topic': 'Reconstructed access', 'choice': 'Wrong exercise is accessible.',
        'sourceReferences': ['SOURCE_1'], 'confirmedSetupAccess': {
            'independentExercises': ['Invented exercise'], 'retainedResources': ['Invented station']}}]}
    proposal = propose_decisions(arguments, messages, equipment)
    assert proposal['newDecisionIds'] == [] and proposal['decisions'] == {}
    monkeypatch.setattr(plan_review, '_review_call', lambda *a, **k: pytest.fail('Stored facts need no model review'))
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', arguments, equipment)['result'])
    assert result['passed'] and result['decisions'] == {}
    bound = confirmed_setup_access(messages, equipment, requirements)['requirements']['executionRules'][0]
    assert bound['sharedResourceGroups'] == [['bar', 'bench']]
    assert ['press', 'raise'] in bound['confirmedIndependentPairs']
    repeated = copy.deepcopy(arguments)
    repeated['decisions'][0].update(sourceReferences=['SOURCE_2'], choice='Unrelated model interpretation.',
        confirmedSetupAccess={'independentExercises': ['Raise'], 'retainedResources': ['Bench', 'Barbell']})
    assert propose_decisions(repeated, messages, equipment)['newDecisionIds'] == []
    changed = copy.deepcopy(arguments)
    changed['decisions'][0]['sourceReferences'] = ['SOURCE_2']
    with pytest.raises(ValidationError):
        propose_decisions(changed, messages, equipment)


def test_continue_recompiles_only_a_redundant_memory_setup_failure(case):
    from test_workout_generator_planning_decisions import store
    from workout_generator_pkg.interactive_shell import _requirements_review_retry_arguments

    root, profile, equipment, requirements = case
    _save_shared(root, profile, equipment)
    messages = [{'role': 'user', 'content': 'Generate this week.'}]
    bind_user_memory(messages, profile, equipment, root=root)
    decisions = {'decisions': [{'topic': 'Copied setup', 'choice': 'Incorrect copied names',
        'sourceReferences': ['SOURCE_0'], 'confirmedSharedStation': ['Invented resource']}]}
    result = {'passed': False, 'requirementsId': 'REQUIREMENTS_test', 'requirements': requirements,
        'sourceReview': {'passed': False, 'findings': [{'severity': 'blocking'}]},
        'errors': [{'code': 'decision_source_finding'}], 'proposedDecisions': {'DECISION_0': decisions['decisions'][0]}}
    store(messages, 'set_workout_requirements', {'planningDecisions': decisions}, result, 'failed-memory-copy')
    messages.append({'role': 'user', 'content': '/continue'})
    store(messages, 'set_workout_requirements', {'updates': {}},
        {'passed': False, 'errors': [{'code': 'invalid_setup_confirmation'}]}, 'rejected-repair-form')
    assert _requirements_review_retry_arguments(messages, '/continue', equipment) == {
        'updates': {}, 'planningDecisions': decisions}
    messages[3]['content'] = json.dumps({**result, 'errors': [{'code': 'requirement_source_finding'}]})
    assert _requirements_review_retry_arguments(messages, '/continue', equipment) is None


def test_unresolved_restriction_opens_native_question_instead_of_model_retry():
    from workout_generator_pkg.planning_tools import planning_tool_failure
    failure = planning_tool_failure('set_workout_requirements', PlanningInputError(
        'unresolved_restriction', 'Cannot resolve restriction terms: unknown equipment',
        '/exerciseRestrictions', 'Ask for clarification.'))
    assert not failure['passed']
    assert 'unknown equipment' in failure['userQuestion']['question']
    assert failure['userQuestion']['options'] == []
    assert failure['instruction'].startswith('Wait for the user clarification.')


@pytest.mark.parametrize('numeric_answer', [True, False])
def test_production_review_persists_question_without_model_copying_its_source(tmp_path, monkeypatch, numeric_answer):
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.interactive_shell import handle_function_call
    from workout_generator_pkg.user_interaction import answer_question, clarification_question
    from test_workout_generator_context_decisions import context_case

    monkeypatch.setenv('MYWORKOUT_USER_MEMORY_DIR', str(tmp_path))
    profile = memory_store.create_profile('User')['profileId']
    equipment, requirements, _, arguments = context_case()
    question = clarification_question({'question': 'Can lateral raises use clear floor while the barbell and bench stay?',
        'options': ['Yes, the floor remains accessible.', 'No, it is blocked.']})
    answer = '1' if numeric_answer else 'Yes.'
    messages = [{'role': 'assistant', 'content': question['question']},
        {'role': 'user', 'content': answer_question(question, answer) if numeric_answer else answer,
         **({'userInteraction': {'question': question, 'input': answer}} if numeric_answer else {})}]
    bind_user_memory(messages, profile, equipment)
    arguments['decisions'] = [arguments['decisions'][0]]
    arguments['decisions'][0]['sourceReferences'] = ['SOURCE_1']
    monkeypatch.setattr(plan_review, 'chat_call', lambda *args, **kwargs: ('{"findings":[]}', None, None))
    result = json.loads(handle_function_call(None, messages,
        'record_planning_decisions', arguments, equipment)['result'])
    assert result['passed']
    fact, = memory_store.load_profile(profile)['facts']
    assert fact['value'] == {'independentDefinitionIds': ['raise'], 'retainedResourceIds': ['bar', 'bench']}
    assert fact['source']['statement'] == messages[-1]['content']
    context = fact['source']['context']
    if numeric_answer:
        assert {'role': 'assistant', 'content': json.dumps(question, ensure_ascii=False, sort_keys=True)} in context
        assert {'role': 'user', 'content': '1'} in context
    else:
        assert context == [{'role': 'assistant', 'content': question['question']}]
    assert len(context) == len({(item['role'], item['content']) for item in context})
    fresh = []
    bind_user_memory(fresh, profile, equipment)
    bound = confirmed_setup_access(fresh, equipment, requirements)
    assert bound['requirements']['executionRules'][0]['confirmedIndependentPairs'] == [['press', 'raise']]
