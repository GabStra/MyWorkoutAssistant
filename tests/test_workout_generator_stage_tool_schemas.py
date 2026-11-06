import copy
import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import api_client, interactive_shell
from workout_generator_pkg.constants import GENERATE_WORKOUT_TOOL
from workout_generator_pkg.user_interaction import ACCEPT_WORKOUT_ALTERNATIVE_TOOL, ASK_USER_TOOL


def _without_descriptions(value):
    if isinstance(value, dict):
        return {key: _without_descriptions(child) for key, child in value.items() if key != 'description'}
    if isinstance(value, list):
        return [_without_descriptions(child) for child in value]
    return value


def test_wire_guidance_sharing_preserves_shapes_and_canonical_argument_recovery(monkeypatch):
    guidance = 'Preserve the explicit source-stated exact numerical quantity and its units; never infer a replacement.'
    optional = {'type': 'integer', 'minimum': 1, 'description': guidance}
    schema = {'type': 'object', 'properties': {'first': optional, 'second': optional},
        'anyOf': [{'required': ['first']}, {'required': ['second']}], 'additionalProperties': False}
    tools = [{'type': 'function', 'function': {'name': 'select', 'parameters': schema}}]
    saved = copy.deepcopy(tools)
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='tool_calls', message=SimpleNamespace(
            content=None, reasoning_content=None, tool_calls=[SimpleNamespace(id='selected', type='function',
                function=SimpleNamespace(name='select', arguments='{"first":111,"second":null}}'))]))], usage=None)

    client = SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(api_client, 'resolve_llm_endpoint', lambda: SimpleNamespace(
        base_url='https://api.deepseek.com', model='deepseek-flash', is_deepseek=True))
    _, calls, _ = api_client.chat_call(client, [], tools, reasoning_effort=None,
        require_strict_tool_delivery=True, retry=False)
    delivered = requests[0]['tools'][0]['function']['parameters']
    original_wire = api_client._strict_wire_schema(schema)
    assert _without_descriptions(delivered) == _without_descriptions(original_wire)
    assert json.dumps(delivered).count(guidance) == 1
    assert len(json.dumps(delivered)) < len(json.dumps(original_wire))
    assert api_client._strict_schema_compatible(delivered)
    validate({'first': 111, 'second': None}, delivered)
    with pytest.raises(ValidationError):
        validate({'first': None, 'second': None}, delivered)
    assert json.loads(calls[0].function.arguments) == {'first': 111}
    validate(json.loads(calls[0].function.arguments), schema)
    assert tools == saved


@pytest.mark.parametrize('content,attachments,names,proposal_id', [
    ('Repair the draft', {}, {'ask_user'}, None),
    ('CONFIRM GENERATE', {}, {'generate_workout', 'ask_user'}, None),
    ('CONFIRM GENERATE', {'imageAttachments': ['image']}, {'ask_user'}, None),
    ('APPROVE ALTERNATIVE ALT_123', {}, {'accept_workout_alternative', 'ask_user'}, 'ALT_123'),
    ('APPROVE ALTERNATIVE ALT_123', {'images': ['image']}, {'ask_user'}, None),
])
def test_stage_shapes_follow_existing_exact_approval_gates(content, attachments, names, proposal_id):
    tools = [GENERATE_WORKOUT_TOOL, ACCEPT_WORKOUT_ALTERNATIVE_TOOL, ASK_USER_TOOL]
    saved = copy.deepcopy(tools)
    projected = interactive_shell._authorized_action_tools(tools, [{'role': 'user', 'content': content, **attachments}])
    assert {tool['function']['name'] for tool in projected} == names
    if proposal_id:
        accept = next(tool for tool in projected if tool['function']['name'] == 'accept_workout_alternative')
        validate({'proposalId': proposal_id}, accept['function']['parameters'])
        with pytest.raises(ValidationError):
            validate({'proposalId': 'ALT_other'}, accept['function']['parameters'])
    assert tools == saved


def test_alternative_approval_stays_available_after_bare_continue():
    tools = [ACCEPT_WORKOUT_ALTERNATIVE_TOOL, ASK_USER_TOOL]
    messages = [{'role': 'user', 'content': 'APPROVE ALTERNATIVE ALT_123'},
                {'role': 'user', 'content': '/continue'}]
    assert len(interactive_shell._authorized_action_tools(tools, messages)) == 2
    messages.append({'role': 'user', 'content': 'Change the proposal instead.'})
    assert interactive_shell._authorized_action_tools(tools, messages) == [ASK_USER_TOOL]
