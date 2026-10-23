import json
import threading
import copy
import pytest
from types import SimpleNamespace

from workout_generator_pkg import api_client
from workout_generator_pkg.api_metrics import api_metrics_scope
from workout_generator_pkg.cancellation import run_cancellable


@pytest.mark.parametrize('streaming', [False, True])
def test_json_object_requests_always_include_provider_required_instruction(streaming):
    messages = [{'role':'user','content':'Repair these fields.'}]
    before = copy.deepcopy(messages)
    def create(**kwargs):
        assert any('json' in m.get('content','').lower() for m in kwargs['messages'])
        if streaming:
            return iter([SimpleNamespace(model='deepseek-flash',usage=None,choices=[SimpleNamespace(
                finish_reason='stop',delta=SimpleNamespace(content='{"patch":[]}'))])])
        return SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content='{"patch":[]}',tool_calls=None,reasoning_content=None))])
    client = SimpleNamespace(with_options=lambda **_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    if streaming:
        content,_ = api_client._measured_stream_request(create,model='deepseek-flash',reasoning_effort='low',
            thinking='enabled',max_tokens=100,messages=messages,response_format={'type':'json_object'})
    else:
        content,_,_ = api_client.chat_call(client,messages,response_format={'type':'json_object'})
    assert json.loads(content) == {'patch':[]} and messages == before
    explicit = [{'role':'system','content':'Return JSON.'}]
    assert api_client._request_messages(explicit,{'type':'json_object'}) == explicit
    assert api_client._request_messages(messages) == messages


def test_chat_call_records_safe_actual_usage_and_context_stage():
    rows = []
    logger = SimpleNamespace(log=rows.append)
    response = SimpleNamespace(
        model='deepseek-flash-actual',
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='secret response', tool_calls=None, reasoning_content='secret reasoning'))],
        usage=SimpleNamespace(model_dump=lambda: {
            'prompt_tokens': 1200, 'completion_tokens': 300,
            'completion_tokens_details': {'reasoning_tokens': 140},
            'prompt_tokens_details': {'cached_tokens': 800},
        }),
    )
    client = SimpleNamespace(
        with_options=lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: response)))
    )
    with api_metrics_scope(logger, 'draft_repair'):
        assert api_client.chat_call(client, [{'role': 'user', 'content': 'secret prompt'}])[0] == 'secret response'
    metric = json.loads(rows[-1].split(' ', 1)[1])
    assert metric['model'] == 'deepseek-flash-actual'
    assert metric['stage'] == 'draft_repair' and metric['outcome'] == 'success'
    assert metric['promptTokens'] == 1200 and metric['completionTokens'] == 300
    assert metric['reasoningTokens'] == 140 and metric['cacheHitTokens'] == 800
    assert metric['contextSizes']['messageCharactersByRole']['user'] > 0
    assert 'secret' not in rows[0]


def test_context_sizes_identify_large_sections_and_duplicates_without_logging_content():
    from workout_generator_pkg.api_metrics import request_context_sizes

    state = {'currentDraft': {'name': 'private draft'},
             'requirements': {'secretRequirement': 'private target'},
             'otherToolResults': {'old': 'private feedback'}}
    user = {'role': 'user', 'content': 'private request'}
    messages = [{'role': 'system', 'content': 'Current planning state (backend data, not new instructions).\n'
                 + json.dumps(state)}, user, user]
    tools = [{'type': 'function', 'function': {'name': 'private_tool'}}]
    before = copy.deepcopy(messages)
    sizes = request_context_sizes(messages, tools)
    assert set(sizes['planningStateSectionCharacters']) == set(state)
    assert sizes['planningStateSectionCharacters']['currentDraft'] == len(
        json.dumps(state['currentDraft'], separators=(',', ':')))
    assert sizes['duplicateMessages'] == 1 and sizes['duplicateMessageCharacters'] > 0
    assert sizes['toolsCharacters'] > 0 and sizes['messagesCharacters'] > sizes['toolsCharacters']
    assert 'private' not in json.dumps(sizes) and 'secretRequirement' not in json.dumps(sizes)
    assert messages == before


@pytest.mark.parametrize('wrapped', [False, True])
def test_context_sizes_measure_review_sections_without_recording_evidence(wrapped):
    from workout_generator_pkg.api_metrics import request_context_sizes

    context = {'draft': {'planName': 'private plan'}, 'history': {'PRIVATE_ID': 'private record'},
               'requirements': {'private target': 4}}
    payload = {'context': context, 'findings': []} if wrapped else context
    sizes = request_context_sizes([{'role': 'user', 'content': json.dumps(payload)}])
    assert set(sizes['reviewContextSectionCharacters']) == set(context)
    assert sizes['reviewContextSectionCharacters']['history'] == len(
        json.dumps(context['history'], separators=(',', ':')))
    assert sizes['planningStateSectionCharacters'] == {}
    assert 'private' not in json.dumps(sizes).lower()


def test_chat_call_retries_one_transient_provider_connection_error(monkeypatch):
    rows, calls = [], []
    class APIConnectionError(Exception):
        pass
    monkeypatch.setattr(api_client.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(api_client, '_log_connection_error', lambda *_a, **_k: None)
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise APIConnectionError('temporary connection failure')
        return SimpleNamespace(model='deepseek-flash', usage={'prompt_tokens': 20, 'completion_tokens': 5},
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
                content='ok', tool_calls=None, reasoning_content=None))])
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'retry_probe'):
        assert api_client.chat_call(client, [{'role': 'user', 'content': 'probe'}])[0] == 'ok'
    assert len(calls) == 2
    metrics = [json.loads(line.split('[api_metric] ', 1)[1]) for line in rows
               if '[api_metric] ' in line and '"outcome"' in line]
    outcomes = [metric['outcome'] for metric in metrics]
    assert outcomes == ['failure', 'success']


@pytest.mark.parametrize('effort', [None, 'low'])
def test_chat_thinking_mode_matches_request_and_metrics_without_mutating_history(effort):
    rows, requests = [], []
    messages = [{'role': 'assistant', 'content': 'Previous result', 'reasoning_content': 'Previous reasoning'},
                {'role': 'user', 'content': 'Repair JSON notes only.'}]
    before = copy.deepcopy(messages)
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(model='deepseek-flash', usage={'prompt_tokens': 20, 'completion_tokens': 5},
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{"patch":[]}', tool_calls=None))])
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'note_repair'):
        assert api_client.chat_call(client, messages, reasoning_effort=effort)[0] == '{"patch":[]}'
    mode = 'disabled' if effort is None else 'enabled'
    assert requests[0]['extra_body']['thinking']['type'] == mode
    assert ('reasoning_effort' in requests[0]) is (effort is not None)
    assert ('reasoning_content' in requests[0]['messages'][0]) is (effort is not None)
    metric = json.loads(rows[-1].split(' ', 1)[1])
    assert metric['thinking'] == mode and metric['reasoningEffort'] == effort
    assert messages == before


def test_malformed_chat_response_still_records_provider_usage():
    rows = []
    response = SimpleNamespace(model='deepseek-flash', choices=[],
        usage={'prompt_tokens':12,'completion_tokens':3})
    client = SimpleNamespace(with_options=lambda **_:SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__:response))))
    with api_metrics_scope(SimpleNamespace(log=rows.append),'probe'):
        with pytest.raises(IndexError):
            api_client.chat_call(client,[{'role':'user','content':'probe'}])
    metric=json.loads(rows[-1].split(' ',1)[1])
    assert metric['promptTokens'] == 12 and metric['completionTokens'] == 3
    assert metric['outcome'] == 'failure'


@pytest.mark.parametrize('submitted', [True, False])
def test_native_json_schema_reply_preserves_local_validation(submitted):
    options,requests,rows=[],[],[]
    schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
    def create(**kwargs):
        requests.append(kwargs)
        calls=[]
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(
            content='{"ok":true}' if submitted else 'unstructured',tool_calls=calls,reasoning_content=None))],usage={'prompt_tokens':12,'completion_tokens':3})
    def configure(**kwargs):
        options.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with api_metrics_scope(SimpleNamespace(log=rows.append),'review'):
        if submitted:
            content,calls,_=api_client.chat_call(SimpleNamespace(with_options=configure),[],output_schema=schema)
            assert json.loads(content)=={'ok':True} and calls is None
        else:
            with pytest.raises(ValueError):
                api_client.chat_call(SimpleNamespace(with_options=configure),[],output_schema=schema)
    assert options==[{'max_retries':0}]
    assert 'tools' not in requests[0] and 'tool_choice' not in requests[0]
    assert requests[0]['response_format'] == {'type': 'json_object'}
    assert requests[0]['messages'][-1]['content'].endswith(json.dumps(schema, separators=(',', ':')))
    assert json.loads(rows[-1].split(' ',1)[1])['completionTokens']==3


def test_unresolvable_output_schema_records_provider_usage_without_becoming_rejection(monkeypatch):
    from jsonschema import SchemaError

    rows = []
    call = SimpleNamespace(function=SimpleNamespace(name='emit_result', arguments='{"ok":"yes"}'))
    response = SimpleNamespace(model='test-model', choices=[SimpleNamespace(finish_reason='tool_calls',
        message=SimpleNamespace(content=None, tool_calls=[call], reasoning_content=None))],
        usage={'prompt_tokens': 12, 'completion_tokens': 3})
    endpoint = SimpleNamespace(base_url='https://api.example.com/v1', model='test-model', is_deepseek=False)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: response))))
    schema = {'type': 'object', 'properties': {'ok': {'type': 'string', '$ref': '#/$def/reference'}},
        'required': ['ok'], 'additionalProperties': False}

    with api_metrics_scope(SimpleNamespace(log=rows.append), 'independent_plan_review'):
        with pytest.raises(SchemaError) as raised:
            api_client.chat_call(client, [], output_schema=schema)

    assert raised.value.__cause__ is not None
    assert type(raised.value.__cause__).__name__ == '_WrappedReferencingError'
    metric = json.loads(next(row for row in rows if '"event":"api_request"' in row).split(' ', 1)[1])
    assert metric['outcome'] == 'failure' and metric['errorType'] == 'SchemaError'
    assert metric['promptTokens'] == 12 and metric['completionTokens'] == 3
    assert not any('rejected' in row for row in rows)


@pytest.mark.parametrize('content,valid', [(' {"ok":true} ',True),('{"ok":"wrong"}',False),
    ('{"ok":true,"extra":1}',False),('{"ok":"wrong"}}',False),('```json\n{"ok":true}\n```',False)])
def test_schema_reply_accepts_only_fully_valid_json_when_tool_not_called(content,valid):
    from jsonschema import ValidationError
    calls=[]
    schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(
            content=content,tool_calls=None,reasoning_content=None))],usage=None)
    client=SimpleNamespace(with_options=lambda **_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    if valid:
        result,tools,_=api_client.chat_call(client,[],output_schema=schema)
        assert json.loads(result)=={'ok':True} and tools is None
    else:
        with pytest.raises((ValueError,ValidationError)):
            api_client.chat_call(client,[],output_schema=schema)
    assert len(calls)==1


def test_deepseek_strict_structured_output_uses_beta_and_requires_emit_result(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    options, requests = [], []
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
              'required': ['ok'], 'additionalProperties': False}

    def create(**kwargs):
        requests.append(kwargs)
        call = SimpleNamespace(function=SimpleNamespace(name='emit_result', arguments='{"ok":true}'))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, tool_calls=[call], reasoning_content=None))], usage=None)

    client = SimpleNamespace(with_options=lambda **kwargs: (options.append(kwargs) or SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    content, tool_calls, _ = api_client.chat_call(client, [], reasoning_effort=None, output_schema=schema)

    assert json.loads(content) == {'ok': True} and tool_calls is None
    assert options == [{'max_retries': 0, 'base_url': 'https://api.deepseek.com/beta'}]
    assert requests[0]['tools'][0]['function']['strict'] is True
    assert requests[0]['tool_choice'] == {'type': 'function', 'function': {'name': 'emit_result'}}
    assert requests[0]['extra_body']['thinking']['type'] == 'disabled'
    assert 'response_format' not in requests[0]


def test_non_deepseek_preserves_existing_strict_tool_path_for_unsupported_schema(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.example.com/v1', model='test-model', is_deepseek=False)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    requests = []
    schema = {'type': 'object', 'properties': {'items': {'type': 'array', 'items': {'type': 'string'},
        'maxItems': 3}}, 'required': ['items'], 'additionalProperties': False}

    def create(**kwargs):
        requests.append(kwargs)
        call = SimpleNamespace(function=SimpleNamespace(name='emit_result', arguments='{"items":["a"]}'))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, tool_calls=[call], reasoning_content=None))], usage=None)

    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    content, _, _ = api_client.chat_call(client, [], reasoning_effort=None, output_schema=schema)

    assert json.loads(content) == {'items': ['a']}
    assert requests[0]['tools'][0]['function']['strict'] is True
    assert requests[0]['tool_choice'] == {'type': 'function', 'function': {'name': 'emit_result'}}
    assert 'response_format' not in requests[0]


def test_deepseek_thinking_structured_output_preserves_reasoning_and_uses_json_fallback(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    options, requests = [], []
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
              'required': ['ok'], 'additionalProperties': False}

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='{"ok":true}', tool_calls=None, reasoning_content='kept reasoning'))], usage=None)

    client = SimpleNamespace(with_options=lambda **kwargs: (options.append(kwargs) or SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    content, tool_calls, reasoning = api_client.chat_call(client, [], reasoning_effort='low', output_schema=schema)

    assert json.loads(content) == {'ok': True} and tool_calls is None and reasoning == 'kept reasoning'
    assert options == [{'max_retries': 0}]
    assert requests[0]['response_format'] == {'type': 'json_object'}
    assert 'tools' not in requests[0] and 'tool_choice' not in requests[0]
    assert requests[0]['reasoning_effort'] == 'low'
    assert requests[0]['extra_body']['thinking']['type'] == 'enabled'


def test_deepseek_application_tools_use_strict_schema_without_changing_thinking(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    options, requests = [], []
    tool = {'type': 'function', 'function': {'name': 'choose', 'parameters': {
        'type': 'object', 'properties': {'choice': {'type': 'string'}},
        'required': ['choice'], 'additionalProperties': False}}}

    def create(**kwargs):
        requests.append(kwargs)
        call = SimpleNamespace(id='call_1', type='function', function=SimpleNamespace(name='choose', arguments='{"choice":"a"}'))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, tool_calls=[call], reasoning_content='reasoning'))], usage=None)

    client = SimpleNamespace(with_options=lambda **kwargs: (options.append(kwargs) or SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    _, calls, reasoning = api_client.chat_call(client, [], tools=[tool], reasoning_effort='low')

    assert calls[0].function.name == 'choose' and reasoning == 'reasoning'
    assert options == [{'max_retries': 0, 'base_url': 'https://api.deepseek.com/beta'}]
    assert requests[0]['tools'][0]['function']['strict'] is True
    assert requests[0]['reasoning_effort'] == 'low'
    assert requests[0]['extra_body']['thinking']['type'] == 'enabled'
    assert tool['function'].get('strict') is None


def test_deepseek_incompatible_application_schema_keeps_existing_json_tool_path(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    options, requests = [], []
    tool = {'type': 'function', 'function': {'name': 'choose', 'parameters': {
        'type': 'object', 'properties': {'choice': {'type': 'string', 'maxLength': 12}},
        'required': ['choice'], 'additionalProperties': False}}}

    def create(**kwargs):
        requests.append(kwargs)
        call = SimpleNamespace(id='call_1', type='function', function=SimpleNamespace(name='choose', arguments='{"choice":"a"}'))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, tool_calls=[call], reasoning_content=None))], usage=None)

    client = SimpleNamespace(with_options=lambda **kwargs: (options.append(kwargs) or SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    api_client.chat_call(client, [], tools=[tool], reasoning_effort=None)

    assert options == [{'max_retries': 0}]
    assert 'strict' not in requests[0]['tools'][0]['function']
    assert tool['function'].get('strict') is None


def test_assessed_menu_repair_projects_real_tools_and_requires_deepseek_strict(monkeypatch):
    import copy
    from test_workout_generator_redistribution_intent import intent_case
    from workout_generator_pkg.planning_tools import (GET_WORKOUT_DRAFT_TOOL, coordinated_repair_tool,
        workout_requirements_tool)
    from workout_generator_pkg.user_interaction import ASK_USER_TOOL
    from workout_generator_pkg.exercise_library_tools import (GET_EXERCISE_CANDIDATES_TOOL,
        exercise_library_search_tool)
    from workout_generator_pkg.training_history import GET_TRAINING_EVIDENCE_TOOL
    from workout_generator_pkg.planning_decisions import RECORD_PLANNING_DECISIONS_TOOL
    from workout_generator_pkg.allocation import ALLOCATE_WORKOUT_SETS_TOOL
    from workout_generator_pkg.user_interaction import (ACCEPT_WORKOUT_ALTERNATIVE_TOOL,
        PROPOSE_WORKOUT_ALTERNATIVES_TOOL)
    from workout_generator_pkg.constants import GENERATE_WORKOUT_TOOL
    from workout_generator_pkg.interactive_shell import _strict_assessed_menu_repair_tools
    from jsonschema import ValidationError, validate

    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    draft, task, _, _ = intent_case()
    additional = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    additional['definition_id'] = 'LIBRARY_1'
    draft['workouts'][0]['exercises'].append(additional)
    task['currentDraft'] = draft
    task['findingsAssessment']['groups'][0]['repairObjectives'][0]['exerciseRefs'] = [
        'EXERCISE_0', 'EXERCISE_2']
    task['findingsAssessment']['groups'][0]['repairDimensions'].append('exercise_selection')
    coordinated = coordinated_repair_tool(task)
    tools = [workout_requirements_tool({}, []), RECORD_PLANNING_DECISIONS_TOOL, GENERATE_WORKOUT_TOOL,
        exercise_library_search_tool({}), GET_EXERCISE_CANDIDATES_TOOL, coordinated,
        ALLOCATE_WORKOUT_SETS_TOOL, GET_WORKOUT_DRAFT_TOOL, PROPOSE_WORKOUT_ALTERNATIVES_TOOL,
        ACCEPT_WORKOUT_ALTERNATIVE_TOOL, GET_TRAINING_EVIDENCE_TOOL, ASK_USER_TOOL]
    tools, require_strict = _strict_assessed_menu_repair_tools(tools, coordinated, task)
    assert require_strict
    assert _strict_assessed_menu_repair_tools(tools, coordinated, {}) == (tools, False)
    names = {tool['function']['name'] for tool in tools}
    assert names.isdisjoint({'allocate_workout_sets', 'propose_workout_alternatives', 'generate_workout'})
    assert {'ask_user', 'search_exercise_library', 'get_exercise_candidates', 'get_workout_draft',
        'get_training_evidence'} <= names
    requests, options = [], []

    def create(**kwargs):
        requests.append(kwargs)
        call = SimpleNamespace(id='call_1', type='function', function=SimpleNamespace(
            name='ask_user', arguments='{"question":"Need one detail.","options":null,"recommendation":null}'))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, tool_calls=[call], reasoning_content=None))], usage=None)

    client = SimpleNamespace(with_options=lambda **kwargs: (options.append(kwargs) or SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    _, calls, _ = api_client.chat_call(client, [], tools=tools, reasoning_effort=None,
        require_strict_tool_delivery=require_strict)

    assert options == [{'max_retries': 0, 'base_url': 'https://api.deepseek.com/beta'}]
    assert all(tool['function']['strict'] is True
        and api_client._strict_parameters_compatible(tool['function']['parameters'])
        for tool in requests[0]['tools'])
    repair_wire = next(tool['function']['parameters'] for tool in requests[0]['tools']
        if tool['function']['name'] == 'audit_workout_plan')
    assert 'EXERCISE_0' not in json.dumps(repair_wire['properties']['sessionBlocks'])
    assert json.loads(calls[0].function.arguments) == {'question': 'Need one detail.'}
    assert coordinated['function'].get('strict') is None
    target_schema = coordinated['function']['parameters']['properties']['edits']['properties'][
        'redistributionTargets']['properties']['REDISTRIBUTION_0']
    with pytest.raises(ValidationError):
        validate(['WORKOUT_0'], target_schema)


def test_required_strict_tool_delivery_fails_before_api_for_unprojectable_schema(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    calls = []
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs)))))
    tool = {'type': 'function', 'function': {'name': 'bad', 'parameters': {
        'type': 'object', 'properties': {'value': {'$ref': '#/$defs/value'}},
        'required': ['value'], 'additionalProperties': False}}}

    with pytest.raises(ValueError, match='cannot project schema keywords'):
        api_client.chat_call(client, [], tools=[tool], reasoning_effort=None,
            require_strict_tool_delivery=True)

    assert calls == []


def test_nullable_type_union_keeps_constraints_only_on_compatible_branch():
    projected_integer = api_client._strict_wire_schema({
        'type': ['integer', 'null'], 'minimum': 0,
    })['anyOf']
    assert projected_integer == [
        {'type': 'integer', 'minimum': 0},
        {'type': 'null'},
    ]

    projected_string = api_client._strict_wire_schema({
        'type': ['string', 'null'], 'pattern': '^[A-Z]+$',
    })['anyOf']
    assert projected_string == [
        {'type': 'string', 'pattern': '^[A-Z]+$'},
        {'type': 'null'},
    ]

    projected_array = api_client._strict_wire_schema({
        'type': ['array', 'null'], 'items': {'type': 'string'},
    })['anyOf']
    assert projected_array == [
        {'type': 'array', 'items': {'type': 'string'}},
        {'type': 'null'},
    ]

    projected_enum = api_client._strict_wire_schema({
        'type': ['integer', 'null'], 'enum': [1],
    })['anyOf']
    assert projected_enum == [{'type': 'integer', 'enum': [1]}]


def test_required_strict_tool_delivery_rejects_unknown_provider_before_api(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.example.com/v1', model='test', is_deepseek=False)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    calls = []
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs)))))
    tool = {'type': 'function', 'function': {'name': 'choose', 'parameters': {
        'type': 'object', 'properties': {'choice': {'type': 'string'}},
        'required': ['choice'], 'additionalProperties': False}}}

    with pytest.raises(ValueError, match='not supported by the configured provider'):
        api_client.chat_call(client, [], tools=[tool], require_strict_tool_delivery=True)

    assert calls == []


def test_deepseek_strict_compatible_schema_rejects_body_fallback(monkeypatch):
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
              'required': ['ok'], 'additionalProperties': False}
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
        content='{"ok":true}', tool_calls=None, reasoning_content=None))], usage=None)
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: response))))

    with pytest.raises(ValueError, match='exactly one emit_result'):
        api_client.chat_call(client, [], reasoning_effort=None, output_schema=schema)


def test_metrics_context_survives_cancellable_worker_thread():
    rows = []
    logger = SimpleNamespace(log=rows.append)
    with api_metrics_scope(logger, 'semantic_search'):
        run_cancellable(lambda: api_client.record_api_metric({'event': 'check'}))
    metric = json.loads(rows[-1].split(' ', 1)[1])
    assert metric['stage'] == 'semantic_search'


def test_failed_call_records_failure_without_prompt_content():
    rows = []
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: (_ for _ in ()).throw(TimeoutError('late'))))))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'independent_review'):
        try:
            api_client.chat_call(client, [{'role': 'user', 'content': 'private'}])
        except TimeoutError:
            pass
        else:
            raise AssertionError('expected request failure')
    metric = json.loads(rows[-1].split(' ', 1)[1])
    assert metric['outcome'] == 'failure' and metric['errorType'] == 'TimeoutError'
    assert 'private' not in rows[0]


def test_streaming_generation_records_provider_usage_and_actual_model():
    rows, requests = [], []
    usage = SimpleNamespace(model_dump=lambda: {
        'prompt_tokens': 900, 'completion_tokens': 240,
        'completion_tokens_details': {'reasoning_tokens': 100},
        'prompt_cache_hit_tokens': 700, 'prompt_cache_miss_tokens': 200,
    })
    chunks = [
        SimpleNamespace(model='deepseek-flash-actual', choices=[SimpleNamespace(
            finish_reason=None, delta=SimpleNamespace(content='{"ok":'))], usage=None),
        SimpleNamespace(model='deepseek-flash-actual', choices=[SimpleNamespace(
            finish_reason='stop', delta=SimpleNamespace(content='true}'))], usage=None),
        SimpleNamespace(model='deepseek-flash-actual', choices=[], usage=usage),
    ]

    def create(**kwargs):
        requests.append(kwargs)
        return iter(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'exercise_emission'):
        content, finish = api_client.json_call_reasoner_only(client, [])
    metric = json.loads(rows[-1].split(' ', 1)[1])
    assert content == '{"ok":true}' and finish == 'stop'
    assert requests[0]['stream_options'] == {'include_usage': True}
    assert metric['model'] == 'deepseek-flash-actual' and metric['stage'] == 'exercise_emission'
    assert metric['thinking'] == 'enabled' and metric['reasoningEffort'] == 'high'
    assert (metric['promptTokens'], metric['completionTokens'], metric['reasoningTokens']) == (900, 240, 100)
    assert metric['cacheHitTokens'] == 700 and metric['cacheMissTokens'] == 200


def test_each_stream_retry_attempt_gets_its_own_metric(monkeypatch):
    rows, calls = [], []

    class ProviderConnectionError(Exception):
        pass

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ProviderConnectionError('connection lost')
        return iter([SimpleNamespace(model='deepseek-flash', choices=[SimpleNamespace(
            finish_reason='stop', delta=SimpleNamespace(content='{}'))], usage=SimpleNamespace(model_dump=lambda: {
                'prompt_tokens': 10, 'completion_tokens': 2, 'completion_tokens_details': {'reasoning_tokens': 0},
                'prompt_cache_hit_tokens': 0,
            }))])

    monkeypatch.setattr(api_client, '_log_connection_error', lambda *args, **kwargs: None)
    monkeypatch.setattr(api_client.time, 'sleep', lambda *_: None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'json_repair'):
        assert api_client.json_call(client, [], max_tokens=128) == ('{}', 'stop')
    metrics = [json.loads(row.split(' ', 1)[1]) for row in rows if json.loads(row.split(' ', 1)[1])['event'] == 'api_request']
    assert len(calls) == len(metrics) == 2
    assert [metric['outcome'] for metric in metrics] == ['failure', 'success']
    assert all(metric['stage'] == 'json_repair' for metric in metrics)
    assert metrics[0]['promptTokens'] is None
    assert metrics[1]['cacheHitTokens'] == 0


def test_offline_benchmark_compares_logs_without_double_counting_nested_audit(tmp_path):
    from scripts.benchmark_workout_planning import analyze_log, render_comparison

    path = tmp_path / 'run.log'
    path.write_text('\n'.join([
        '[2026-10-16 10:00:00] [request] repair: private payload',
        '[2026-10-16 10:00:05] [api_metric] {"event":"api_request","stage":"draft","outcome":"success","elapsedSeconds":4,"promptTokens":100,"completionTokens":20,"reasoningTokens":9}',
        '[2026-10-16 10:00:05] Tool audit_workout_plan finished (5.00s)',
        '[2026-10-16 10:00:05] Planning paused: reviewer failed',
    ]), encoding='utf-8')
    summary = analyze_log(path)
    assert summary['status'] == 'paused' and summary['wallSeconds'] == 5
    assert summary['apiRequestSecondsSum'] == 4
    assert summary['plannerResponseSeconds'] == 0
    assert 'private payload' not in render_comparison([summary])


def test_benchmark_does_not_treat_missing_usage_as_zero(tmp_path):
    from scripts.benchmark_workout_planning import analyze_log

    path = tmp_path / 'partial.log'
    path.write_text('\n'.join([
        '[2026-10-16 10:00:00] [api_metric] {"event":"api_request","outcome":"success","elapsedSeconds":1,"promptTokens":100,"completionTokens":20,"reasoningTokens":10}',
        '[2026-10-16 10:00:01] [api_metric] {"event":"api_request","outcome":"failure","elapsedSeconds":1,"promptTokens":null,"completionTokens":null,"reasoningTokens":null}',
    ]), encoding='utf-8')
    summary = analyze_log(path)
    assert summary['promptTokens'] is None and summary['completionTokens'] is None
    assert summary['apiFailures'] == 1


def test_benchmark_counts_early_structure_review(tmp_path):
    from scripts.benchmark_workout_planning import analyze_log
    path = tmp_path / 'structure.log'
    path.write_text('[2026-10-18 10:00:00] [api_metric] ' + json.dumps({
        'event': 'api_request', 'stage': 'independent_structure_review', 'outcome': 'success',
        'elapsedSeconds': 1, 'promptTokens': 100, 'completionTokens': 10}), encoding='utf-8')
    assert analyze_log(path)['independentReviewRequests'] == 1


@pytest.mark.parametrize('suffix,accepted', [('}', True), ('}} \n', True), (']', False),
    (' {"findings": []}', False), (' trailing text', False)])
def test_strict_reply_recovers_only_redundant_terminal_object_closers(suffix, accepted):
    payload = {'findings': [{'severity': 'blocking', 'message': 'Keep this finding.'},
                            {'severity': 'warning', 'message': 'Keep this warning.'}]}
    raw = json.dumps(payload) + suffix
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
        content='', tool_calls=[SimpleNamespace(function=SimpleNamespace(name='emit_result', arguments=raw))],
        reasoning_content=None))], usage={'prompt_tokens': 12, 'completion_tokens': 3})
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **__: response))))
    rows = []
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'review'):
        if accepted:
            content, _, _ = api_client.chat_call(client, [], output_schema={'type': 'object', 'required': ['findings']})
            assert json.loads(content) == payload
            assert json.loads(rows[-1].split(' ', 1)[1])['structuredOutputSyntaxRepair'] == 'redundant_terminal_closers'
        else:
            with pytest.raises(json.JSONDecodeError):
                api_client.chat_call(client, [], output_schema={'type': 'object', 'required': ['findings']})


def test_requirements_intake_real_siblings_use_strict_provider_delivery(monkeypatch):
    from jsonschema import ValidationError, validate
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    from workout_generator_pkg.planning_decisions import RECORD_PLANNING_DECISIONS_TOOL
    from workout_generator_pkg.user_interaction import ASK_USER_TOOL
    from test_workout_generator_planning_tools import planning_case
    equipment, _, _, _ = planning_case()
    endpoint = SimpleNamespace(base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True)
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: endpoint)
    requests, options, rows = [], [], []
    arguments = {'auditTargets': {'weeklyEffectiveSets': {}, 'perSessionEffectiveSets': {},
                                 'maximumSessionSeconds': None}, 'sessionsPerWeek': 3}
    raw_arguments = json.dumps(arguments, separators=(',', ':')) + '}}}'
    def create(**kwargs):
        requests.append(kwargs)
        call = SimpleNamespace(id='call_1', type='function', function=SimpleNamespace(
            name='set_workout_requirements', arguments=raw_arguments))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, tool_calls=[call], reasoning_content=None))], usage=None)
    client = SimpleNamespace(with_options=lambda **kwargs: (options.append(kwargs) or SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    tools = [workout_requirements_tool(equipment), RECORD_PLANNING_DECISIONS_TOOL, ASK_USER_TOOL]
    original = copy.deepcopy(tools)
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'Extracting workout requirements'):
        _, calls, _ = api_client.chat_call(client, [], tools=tools, reasoning_effort=None,
            require_strict_tool_delivery=True)
    assert options == [{'max_retries': 0, 'base_url': 'https://api.deepseek.com/beta'}]
    assert all(t['function']['strict'] and api_client._strict_parameters_compatible(
        t['function']['parameters']) for t in requests[0]['tools'])
    assert tools == original
    assert json.loads(calls[0].function.arguments) == arguments
    requirement_wire = next(t['function'] for t in requests[0]['tools']
        if t['function']['name'] == 'set_workout_requirements')
    requirement_schema = original[0]['function']['parameters']
    wire_coverage = requirement_wire['parameters']['properties']['requiredCoverage']
    wire_array = next(branch for branch in wire_coverage['anyOf'] if branch.get('type') == 'array')
    assert wire_array['items']['properties']['key']['enum'] == requirement_schema[
        'properties']['requiredCoverage']['items']['properties']['key']['enum']
    with pytest.raises(ValidationError):
        validate({'key': 'unknown_role', 'scope': 'weekly'},
                 requirement_schema['properties']['requiredCoverage']['items'])
    invalid_arguments = {**arguments, 'requiredCoverage': [{'key': 'unknown_role', 'scope': 'weekly'}]}
    recovered_invalid = api_client._recover_strict_tool_argument_syntax(
        json.dumps(invalid_arguments, separators=(',', ':')) + '}}}', requirement_schema)
    assert json.loads(recovered_invalid) == invalid_arguments
    with pytest.raises(ValidationError):
        validate(invalid_arguments, requirement_schema)
    request_metric = json.loads(next(row for row in rows if '"event":"api_request"' in row).split(' ', 1)[1])
    repair = request_metric['strictToolSyntaxRepairs'][0]
    assert repair['kind'] == 'redundant_terminal_closers' and repair['rawArguments'] == raw_arguments
    assert repair['rawArgumentsFingerprint'] != repair['acceptedArgumentsFingerprint']
    assert api_client._recover_strict_tool_argument_syntax(raw_arguments + ' trailing', requirement_schema) is None


def test_optional_nullable_union_flattens_provider_branches_without_losing_constraints():
    from jsonschema import validate, ValidationError
    schema = {'type': 'object', 'properties': {
        'supersedes': {'anyOf': [{'type': 'string', 'pattern': '^DECISION_[0-9]+$'},
                                 {'type': 'null'}]}}, 'required': [], 'additionalProperties': False}
    original = copy.deepcopy(schema)
    wire = api_client._strict_wire_schema(schema)
    assert wire['properties']['supersedes']['anyOf'] == [
        {'type': 'string', 'pattern': '^DECISION_[0-9]+$'}, {'type': 'null'}]
    validate({'supersedes': None}, wire)
    validate({'supersedes': 'DECISION_12'}, wire)
    with pytest.raises(ValidationError):
        validate({'supersedes': 'anything'}, wire)
    assert schema == original
    nested = {'anyOf': [{'anyOf': [{'type': 'string'}, {'type': 'null'}]}, {'type': 'null'}]}
    assert not api_client._strict_schema_compatible(nested)
    assert api_client._strict_wire_schema(nested) == {'anyOf': [{'type': 'string'}, {'type': 'null'}]}
