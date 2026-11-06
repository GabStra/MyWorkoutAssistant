"""OpenAI/DeepSeek API call helpers with retry and loading UX."""

from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
import copy
from collections import Counter
from contextlib import nullcontext
from datetime import datetime
from urllib.parse import urlparse
from jsonschema import validate, ValidationError, SchemaError
from .constants import (
    DEEPSEEK_CHAT_DEFAULT_TOKENS,
    DEEPSEEK_CHAT_MAX_TOKENS,
    DEEPSEEK_REASONER_DEFAULT_TOKENS,
    DEEPSEEK_REASONER_MAX_TOKENS,
    DEEPSEEK_PLANNING_TIMEOUT_SECONDS,
)
from .llm_config import resolve_llm_endpoint
from .logging_ui import LoadingIndicator
from .cancellation import check_cancelled, run_cancellable
from .image_attachments import prepare_image_messages, validate_image_request
from .api_metrics import (api_metrics_scope, current_api_metrics_scope, record_api_metric,
    begin_api_request, response_fingerprint, record_submission_rejection)

try:
    from openai import APIConnectionError
except ImportError:
    APIConnectionError = None

try:
    from httpx import RemoteProtocolError
except ImportError:
    try:
        from httpcore import RemoteProtocolError
    except ImportError:
        RemoteProtocolError = None


class TruncatedResponseError(ValueError):
    """Keep rejected output for diagnostics without accepting it as a plan or tool call."""

    def __init__(self, response, max_tokens, reasoning_effort):
        message = getattr(response.choices[0], 'message', None)
        usage = _usage_dict(response) or None
        reasoning_tokens = ((usage or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
        completion_tokens = (usage or {}).get('completion_tokens')
        has_output = bool(getattr(message, 'content', None) or getattr(message, 'tool_calls', None))
        reasoning_exhausted = (not has_output and isinstance(reasoning_tokens, int)
                              and reasoning_tokens > 0 and reasoning_tokens == completion_tokens)
        cause = 'reasoning_budget_exhausted' if reasoning_exhausted else 'completion_length_limit'
        explanation = ('The model exhausted the budget in reasoning before emitting an answer or tool call. '
                       if reasoning_exhausted else '')
        mode = f'{reasoning_effort}-effort' if reasoning_effort is not None else 'non-thinking'
        super().__init__(f"Response truncated at the {max_tokens}-token {mode} budget. {explanation}No truncated output was accepted. Your saved draft and completed lookups are preserved; resume the next bounded task instead of repeating a whole-plan rewrite.")
        self.diagnostics = {
            'finishReason': 'length', 'maxTokens': max_tokens, 'reasoningEffort': reasoning_effort,
            'cause': cause, 'usage': usage,
            'content': getattr(message, 'content', None),
            'reasoningContent': getattr(message, 'reasoning_content', None),
            'toolCalls': [call.model_dump() for call in (getattr(message, 'tool_calls', None) or [])],
        }


class StructuredResponseError(ValueError):
    """Keep a complete JSON result available for the caller's bounded schema repair."""
    def __init__(self, content, error):
        super().__init__(f'Structured output failed schema validation: {error.message}')
        self.content = content


_STRICT_SCHEMA_KEYWORDS = {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'anyOf',
                           'description', 'pattern', 'minimum', 'maximum', 'exclusiveMinimum',
                           'exclusiveMaximum', 'multipleOf'}


def _strict_schema_compatible(schema):
    """Accept only already-valid strict subsets; never rewrite schema meaning."""
    if not isinstance(schema, dict) or set(schema) - _STRICT_SCHEMA_KEYWORDS:
        return False
    if 'anyOf' in schema:
        return (set(schema) <= {'anyOf', 'description'} and isinstance(schema['anyOf'], list)
                and bool(schema['anyOf']) and all(isinstance(item, dict) and 'type' in item
                    and _strict_schema_compatible(item) for item in schema['anyOf']))
    kind = schema.get('type')
    if kind == 'object':
        properties = schema.get('properties')
        required = schema.get('required')
        return (isinstance(properties, dict) and isinstance(required, list)
                and len(required) == len(properties) and set(required) == set(properties)
                and schema.get('additionalProperties') is False
                and all(_strict_schema_compatible(value) for value in properties.values()))
    if kind == 'array':
        return isinstance(schema.get('items'), dict) and _strict_schema_compatible(schema['items'])
    if kind not in ('string', 'number', 'integer', 'boolean', 'null'):
        return False
    if 'enum' in schema and not isinstance(schema['enum'], list):
        return False
    return True


def _strict_parameters_compatible(schema):
    return isinstance(schema, dict) and schema.get('type') == 'object' and _strict_schema_compatible(schema)


def _strict_provider(endpoint):
    parsed = urlparse(endpoint.base_url)
    if parsed.scheme != 'https':
        return None
    path = parsed.path.rstrip('/')
    if parsed.hostname == 'api.deepseek.com' and path in ('', '/beta'):
        return ('deepseek', endpoint.base_url.rstrip('/') if path == '/beta'
                else endpoint.base_url.rstrip('/') + '/beta')
    return None


def _strict_application_tools(tools, provider):
    if not tools or provider is None or not all(
            isinstance(tool, dict) and tool.get('type') == 'function'
            and isinstance(tool.get('function'), dict)
            and _strict_parameters_compatible(tool['function'].get('parameters')) for tool in tools):
        return None
    strict_tools = json.loads(json.dumps(tools))
    for tool in strict_tools:
        tool['function']['strict'] = True
    return strict_tools


def _compact_tool_descriptions(tools):
    """Share exact repeated guidance on the wire; keep canonical schemas untouched."""
    descriptions = []

    def visit(schema):
        if not isinstance(schema, dict):
            return
        if isinstance(schema.get('description'), str):
            descriptions.append(schema)
        for child in schema.get('properties', {}).values():
            visit(child)
        visit(schema.get('items'))
        for keyword in ('anyOf', 'oneOf', 'allOf'):
            for child in schema.get(keyword, []):
                visit(child)

    projected = json.loads(json.dumps(tools))
    for tool in projected:
        visit(tool.get('function', {}).get('parameters'))
    counts = Counter(schema['description'] for schema in descriptions)
    shared = {}
    for schema in descriptions:
        description = schema['description']
        if counts[description] < 2 or len(description) < 80:
            continue
        if description not in shared:
            shared[description] = f'G{len(shared) + 1}'
            schema['description'] = f'[{shared[description]}] {description}'
        else:
            schema['description'] = f'See shared guidance {shared[description]}.'
    return projected


def _strict_wire_schema(schema):
    """Project a local tool schema onto DeepSeek's strict subset without changing local validation."""
    if not isinstance(schema, dict):
        raise ValueError('Strict tool delivery requires an object JSON schema.')
    unsupported = set(schema) - _STRICT_SCHEMA_KEYWORDS - {
        'const', 'oneOf', 'minItems', 'maxItems', 'uniqueItems', 'minProperties', 'maxProperties',
        'minLength', 'maxLength', 'pattern', 'minimum', 'maximum', 'exclusiveMinimum',
        'exclusiveMaximum', 'multipleOf',
    }
    if unsupported:
        raise ValueError('Strict tool delivery cannot project schema keywords: ' + ', '.join(sorted(unsupported)))

    if schema.get('type') == 'object' and 'anyOf' in schema:
        branches = schema['anyOf']
        if not branches or any(set(branch) != {'required'} for branch in branches):
            raise ValueError('Strict tool delivery cannot project object alternatives except required fields.')
        # Strict unions need complete typed branches, not constraints on a sibling object.
        base = {key: value for key, value in schema.items() if key != 'anyOf'}
        return {'anyOf': [_strict_wire_schema({**base, 'required': list(dict.fromkeys(
            [*base.get('required', []), *branch['required']]))}) for branch in branches]}

    if 'enum' in schema and (schema.get('type') in ('array', 'object')
            or not schema.get('type') and any(isinstance(value, (dict, list)) for value in schema['enum'])):
        values = schema['enum']
        if not values:
            raise ValueError('Strict tool delivery cannot project an empty enum.')
        result = {'anyOf': [_schema_for_choice(value) for value in values]}
        if schema.get('description'):
            result['description'] = schema['description']
        if not _strict_schema_compatible(result):
            raise ValueError('Strict tool delivery could not project a composite enum.')
        return result
    result = {key: json.loads(json.dumps(value)) for key, value in schema.items()
              if key not in {'const', 'oneOf', 'minItems', 'maxItems', 'uniqueItems', 'minProperties',
                             'maxProperties', 'minLength', 'maxLength'}}
    if 'const' in schema:
        value = schema['const']
        if value is None:
            result['type'] = 'null'
        elif isinstance(value, (str, int, float, bool)):
            result['type'] = ('boolean' if isinstance(value, bool) else 'integer' if isinstance(value, int)
                              else 'number' if isinstance(value, float) else 'string')
            result['enum'] = [value]
        else:
            result = _schema_for_choice(value)
    if 'oneOf' in schema:
        result['anyOf'] = [_strict_wire_schema(branch) for branch in schema['oneOf']]
    elif 'anyOf' in schema:
        result['anyOf'] = [_strict_wire_schema(branch) for branch in schema['anyOf']]
    kind = result.get('type')
    if isinstance(kind, list):
        description = result.pop('description', None)
        constraints = {key: value for key, value in result.items() if key not in {'type', 'anyOf'}}
        applicable = {
            'string': {'enum', 'pattern'},
            'integer': {'enum', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'},
            'number': {'enum', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'},
            'boolean': {'enum'},
            'null': set(),
            'array': {'enum', 'items'},
            'object': {'enum', 'properties', 'required', 'additionalProperties'},
        }
        result.clear()
        branches = []
        for value in kind:
            if value not in applicable:
                raise ValueError(f'Strict tool delivery cannot project type: {value}')
            if value == 'null' and isinstance(constraints.get('enum'), list) and None not in constraints['enum']:
                continue
            branch = {'type': value}
            if value != 'null':
                branch.update({key: item for key, item in constraints.items() if key in applicable[value]})
                enum = branch.get('enum')
                if isinstance(enum, list):
                    matching_values = [item for item in enum if _schema_value_matches_type(item, value)]
                    if not matching_values:
                        continue
                    branch['enum'] = matching_values
            branches.append(_strict_wire_schema(branch))
        if not branches:
            raise ValueError('Strict tool delivery cannot project a type union with no allowed branches.')
        result['anyOf'] = branches
        if description is not None:
            result['description'] = description
    if 'enum' in schema and not kind:
        values = schema['enum']
        if not values:
            raise ValueError('Strict tool delivery cannot project an empty enum.')
        if all(isinstance(value, str) for value in values):
            result['type'] = 'string'
        elif all(isinstance(value, (dict, list)) for value in values):
            result.pop('enum', None)
            result['anyOf'] = [_schema_for_choice(value) for value in values]
        else:
            raise ValueError('Strict tool delivery cannot project a mixed or non-string enum.')
    if result.get('type') == 'object':
        properties = result.get('properties')
        if not isinstance(properties, dict):
            raise ValueError('Strict tool delivery requires object properties.')
        if schema.get('additionalProperties') is not False:
            raise ValueError('Strict tool delivery cannot close an object that permits additional properties.')
        original_required = set(schema.get('required', []))
        result['properties'] = {
            name: _strict_wire_schema(value if name in original_required else {
                'anyOf': [value, {'type': 'null'}]})
            for name, value in properties.items()
        }
        result['required'] = list(properties)
        result['additionalProperties'] = False
    if result.get('type') == 'array':
        result['items'] = _strict_wire_schema(result.get('items'))
    if 'anyOf' in result:
        # Optional nullable fields must not introduce an untyped union branch.
        branches = []
        for branch in result['anyOf']:
            for choice in branch.get('anyOf', [branch]):
                if choice not in branches:
                    branches.append(choice)
        result['anyOf'] = branches
    if not _strict_schema_compatible(result):
        raise ValueError('Strict tool delivery could not produce a compatible provider schema.')
    return result


def _schema_value_matches_type(value, kind):
    if kind == 'null':
        return value is None
    if kind == 'boolean':
        return isinstance(value, bool)
    if kind == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == 'string':
        return isinstance(value, str)
    if kind == 'array':
        return isinstance(value, list)
    if kind == 'object':
        return isinstance(value, dict)
    return False


def _schema_for_choice(value):
    """Build a strict-valid shape for one enumerated composite choice."""
    if isinstance(value, dict):
        properties = {key: _schema_for_choice(item) for key, item in value.items()}
        return {'type': 'object', 'properties': properties, 'required': list(properties),
                'additionalProperties': False}
    if isinstance(value, list):
        if not value:
            return {'type': 'array', 'items': {'type': 'string'}}
        item_schemas = [_schema_for_choice(item) for item in value]
        if all(isinstance(item, str) for item in value):
            return {'type': 'array', 'items': {'type': 'string', 'enum': list(dict.fromkeys(value))}}
        return {'type': 'array', 'items': {'anyOf': item_schemas}}
    if value is None:
        return {'type': 'null'}
    if isinstance(value, bool):
        return {'type': 'boolean', 'enum': [value]}
    if isinstance(value, int):
        return {'type': 'integer', 'enum': [value]}
    if isinstance(value, float):
        return {'type': 'number', 'enum': [value]}
    if isinstance(value, str):
        return {'type': 'string', 'enum': [value]}
    raise ValueError('Strict tool delivery cannot project this enumerated value.')


def _normalize_transport_metadata(payload, schema):
    """Remove the exact JSON-mode marker only when the closed schema has no such field."""
    if (isinstance(payload, dict) and payload.get('type') == 'json_object'
            and isinstance(schema, dict) and schema.get('additionalProperties') is False
            and 'type' not in schema.get('properties', {}) and not schema.get('patternProperties')):
        return {key: value for key, value in payload.items() if key != 'type'}
    return payload


def _normalize_strict_tool_arguments(arguments, original_schema):
    """Turn strict-schema null placeholders back into omitted optional properties."""
    try:
        value = _normalize_transport_metadata(json.loads(arguments), original_schema)
    except (TypeError, json.JSONDecodeError):
        return arguments

    def allows_null(schema):
        if not isinstance(schema, dict):
            return False
        if schema.get('type') == 'null' or 'null' in (schema.get('type') if isinstance(schema.get('type'), list) else []):
            return True
        if schema.get('const', object()) is None or None in schema.get('enum', []):
            return True
        return any(allows_null(branch) for key in ('oneOf', 'anyOf') for branch in schema.get(key, []))

    def normalize(node, schema):
        if (isinstance(schema, dict) and not isinstance(schema.get('properties'), dict)
                and ('oneOf' in schema or 'anyOf' in schema)):
            variants = schema.get('oneOf', schema.get('anyOf', []))
            for variant in variants:
                candidate = json.loads(json.dumps(node))
                normalize(candidate, variant)
                try:
                    validate(candidate, schema)
                    if isinstance(node, dict) and isinstance(candidate, dict):
                        node.clear()
                        node.update(candidate)
                    elif isinstance(node, list) and isinstance(candidate, list):
                        node[:] = candidate
                    return
                except ValidationError:
                    pass
            return
        if isinstance(node, dict) and isinstance(schema, dict) and isinstance(schema.get('properties'), dict):
            required = set(schema.get('required', []))
            for key in list(node):
                child_schema = schema['properties'].get(key)
                if child_schema is None:
                    continue
                if node[key] is None and key not in required and not allows_null(child_schema):
                    node.pop(key)
                else:
                    normalize(node[key], child_schema)
        elif isinstance(node, list) and isinstance(schema, dict) and isinstance(schema.get('items'), dict):
            for item in node:
                normalize(item, schema['items'])

    normalize(value, original_schema)
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _decode_json_with_terminal_closer_repair(content, schema=None):
    """Decode JSON, tolerating only redundant terminal object-closing braces."""
    repaired = False
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        if error.msg != 'Extra data':
            raise
        payload, end = json.JSONDecoder().raw_decode(content, len(content) - len(content.lstrip()))
        trailing = content[end:].strip()
        if not isinstance(payload, dict) or not trailing or any(character != '}' for character in trailing):
            raise error
        content, repaired = content[:end], True
    normalized = _normalize_transport_metadata(payload, schema)
    if normalized is not payload:
        content = json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))
    return content, normalized, repaired


def _recover_strict_tool_argument_syntax(arguments, original_schema):
    """Repair only redundant terminal braces, leaving semantic validation to the application boundary."""
    try:
        normalized, payload, repaired = _decode_json_with_terminal_closer_repair(arguments)
    except (TypeError, json.JSONDecodeError):
        return None
    if not repaired:
        return None
    return _normalize_strict_tool_arguments(normalized, original_schema)


def _request_messages(messages, response_format=None):
    prepared = prepare_image_messages([{key: value for key, value in message.items() if key != 'userMemory'}
                                       for message in messages])
    if response_format and response_format.get('type') == 'json_object':
        text = []
        for message in prepared:
            content = message.get('content')
            if isinstance(content, str):
                text.append(content)
            elif isinstance(content, list):
                text.extend(part['text'] for part in content
                            if isinstance(part, dict) and isinstance(part.get('text'), str))
        if not any('json' in value.lower() for value in text):
            prepared = [{'role': 'system', 'content': 'Return one valid JSON object.'}, *prepared]
    return prepared


def chat_call(client, messages, tools=None, *, reasoning_effort="high", max_tokens=DEEPSEEK_REASONER_MAX_TOKENS, timeout=DEEPSEEK_PLANNING_TIMEOUT_SECONDS, response_format=None, output_schema=None, tool_choice=None, retry=True, require_strict_tool_delivery=False):
    return call_model(client, messages, tools, reasoning_effort=reasoning_effort,
        max_tokens=max_tokens, timeout=timeout, response_format=response_format,
        output_schema=output_schema, tool_choice=tool_choice, retry=retry,
        require_strict_tool_delivery=require_strict_tool_delivery)


def call_model(client, messages, tools=None, *, json_mode=False, model=None, reasoning_effort='high',
               max_tokens=DEEPSEEK_REASONER_MAX_TOKENS, timeout=DEEPSEEK_PLANNING_TIMEOUT_SECONDS,
               response_format=None, output_schema=None, tool_choice=None, retry=True,
               require_strict_tool_delivery=False):
    """Run one request with at most one recovery attempt, preserving its model and budget.

    Streaming JSON returns (content, finish_reason); chat returns
    (content, tool_calls, reasoning_content).
    """
    if json_mode and (tools or output_schema is not None or tool_choice is not None or require_strict_tool_delivery):
        raise ValueError('Streaming JSON generation cannot execute tools or structured tool delivery.')
    if model is not None and not json_mode:
        raise ValueError('Chat model selection belongs to the configured endpoint.')
    endpoint = resolve_llm_endpoint() if json_mode else None

    def call(effort):
        if not json_mode:
            return _chat_call_once(client, messages, tools, reasoning_effort=effort,
                max_tokens=max_tokens, timeout=timeout, response_format=response_format,
                output_schema=output_schema, tool_choice=tool_choice,
                require_strict_tool_delivery=require_strict_tool_delivery)
        configured = client.with_options(max_retries=0) if hasattr(client, 'with_options') else client
        return _measured_stream_request(configured.chat.completions.create,
            model=model or endpoint.model, reasoning_effort=effort,
            thinking='enabled' if effort is not None else 'disabled', max_tokens=max_tokens,
            timeout=timeout, messages=messages, response_format=response_format or {'type': 'json_object'},
            stream=True,
            **({'extra_body': {'thinking': {'type': 'enabled' if effort is not None else 'disabled'}}}
               if endpoint.is_deepseek else {}))

    return _retry_model_call(call, reasoning_effort=reasoning_effort, max_attempts=2 if retry else 1)


def _chat_call_once(client, messages, tools=None, *, reasoning_effort, max_tokens, timeout, response_format, output_schema,
                    tool_choice=None, require_strict_tool_delivery=False):
    """
    Call the configured LLM endpoint for conversational responses with optional function calling.

    Args:
        client: OpenAI client
        messages: List of message dicts
        tools: Optional list of tool definitions for function calling

    Returns:
        tuple: (content, tool_calls, reasoning_content). Preserve reasoning in conversation history.
    """
    endpoint = resolve_llm_endpoint()
    strict_provider = _strict_provider(endpoint)
    if require_strict_tool_delivery and (not tools or output_schema is not None):
        raise ValueError('Strict application-tool delivery requires application tools and no structured output schema.')
    if require_strict_tool_delivery and endpoint.is_deepseek and strict_provider is None:
        raise ValueError('Strict application-tool delivery requires the configured DeepSeek beta endpoint.')
    if (require_strict_tool_delivery and not endpoint.is_deepseek
            and urlparse(endpoint.base_url).hostname != 'api.openai.com'):
        raise ValueError('Strict application-tool delivery is not supported by the configured provider.')
    strict_output_schema = bool(output_schema is not None and (
        not endpoint.is_deepseek or (_strict_parameters_compatible(output_schema)
                                     and strict_provider and reasoning_effort is None)))
    original_tool_schemas = {tool['function']['name']: tool['function']['parameters'] for tool in (tools or [])
                             if isinstance(tool, dict) and isinstance(tool.get('function'), dict)
                             and isinstance(tool['function'].get('name'), str)
                             and isinstance(tool['function'].get('parameters'), dict)}
    if require_strict_tool_delivery:
        strict_application_tools = copy.deepcopy(tools)
        for tool in strict_application_tools:
            if not isinstance(tool, dict) or tool.get('type') != 'function' or not isinstance(tool.get('function'), dict):
                raise ValueError('Strict application-tool delivery requires function tools only.')
            parameters = tool['function'].get('parameters')
            tool['function']['parameters'] = _strict_wire_schema(parameters)
            tool['function']['strict'] = True
    else:
        strict_application_tools = (_strict_application_tools(tools, strict_provider)
                                    if output_schema is None else None)
    deepseek_base_url = strict_provider[1] if strict_provider else None
    structured_output_mode = None
    request_messages = _request_messages(messages, response_format)
    if endpoint.is_deepseek and reasoning_effort is not None:
        request_messages = [
            {"reasoning_content": "", **message} if message.get("role") == "assistant" else message
            for message in request_messages
        ]
    else:
        request_messages = [{key: value for key, value in message.items() if key != 'reasoning_content'}
                            for message in request_messages]
    kwargs = {
        "model": endpoint.model,
        "messages": request_messages,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if reasoning_effort is not None:
        kwargs['reasoning_effort'] = reasoning_effort
    if endpoint.is_deepseek:
        kwargs['extra_body'] = {"thinking": {"type": "enabled" if reasoning_effort is not None else "disabled"}}
    if strict_application_tools is not None:
        kwargs['tools'] = strict_application_tools
    elif tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs['tool_choice'] = tool_choice
    if response_format is not None:
        kwargs['response_format'] = response_format
    if output_schema is not None:
        if tools:
            raise ValueError('Structured replies cannot also execute application tools.')
        if strict_output_schema:
            kwargs.pop('response_format', None)
            kwargs['tools'] = [{'type': 'function', 'function': {'name': 'emit_result',
                'description': 'Submit the final structured result.', 'strict': True, 'parameters': output_schema}}]
            kwargs['tool_choice'] = {'type': 'function', 'function': {'name': 'emit_result'}}
            structured_output_mode = 'strict_tool'
        else:
            kwargs['response_format'] = {'type': 'json_object'}
            kwargs.pop('tool_choice', None)
            kwargs['messages'] = [*kwargs['messages'], {'role': 'system', 'content':
                'Return one JSON object matching this schema: ' + json.dumps(output_schema, separators=(',', ':'))}]
            structured_output_mode = 'validated_json'
    if kwargs.get('tools'):
        kwargs['tools'] = _compact_tool_descriptions(kwargs['tools'])
    validate_image_request(kwargs)
    
    started = time.monotonic()
    request = begin_api_request(endpoint.model, messages=kwargs['messages'], tools=kwargs.get('tools'))
    if structured_output_mode:
        request['structuredOutputMode'] = structured_output_mode
    uses_deepseek_strict = bool(deepseek_base_url and (
        strict_output_schema or strict_application_tools is not None or require_strict_tool_delivery))
    if uses_deepseek_strict:
        request['strictEndpoint'] = 'deepseek_beta'
    resp = None
    try:
        client_options = {'max_retries': 0}
        if uses_deepseek_strict:
            client_options['base_url'] = deepseek_base_url
        resp = run_cancellable(client.with_options(**client_options).chat.completions.create, deadline_seconds=timeout, **kwargs)
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            error = TruncatedResponseError(resp, max_tokens, reasoning_effort)
            _record_chat_metric(resp, started, model=endpoint.model, reasoning_effort=reasoning_effort,
                                max_tokens=max_tokens, timeout=timeout, outcome='truncated', request=request)
            raise error
        message = resp.choices[0].message
        content = message.content
        request['responseFingerprint'] = response_fingerprint(content)
        tool_calls = message.tool_calls if hasattr(message, 'tool_calls') and message.tool_calls else None
        if tool_calls and original_tool_schemas:
            tool_calls = copy.deepcopy(tool_calls)
            syntax_repairs = []
            for tool_call in tool_calls:
                schema = original_tool_schemas.get(tool_call.function.name)
                if schema is not None:
                    raw_arguments = tool_call.function.arguments
                    if not require_strict_tool_delivery:
                        try:
                            payload = json.loads(raw_arguments)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        normalized = _normalize_transport_metadata(payload, schema)
                        if normalized is not payload:
                            tool_call.function.arguments = json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))
                        continue
                    recovered = _recover_strict_tool_argument_syntax(raw_arguments, schema)
                    if recovered is not None:
                        tool_call.function.arguments = recovered
                        syntax_repairs.append({
                            'toolName': tool_call.function.name,
                            'kind': 'redundant_terminal_closers',
                            'rawArguments': raw_arguments,
                            'rawArgumentsFingerprint': response_fingerprint(raw_arguments),
                            'acceptedArgumentsFingerprint': response_fingerprint(recovered),
                        })
                    else:
                        tool_call.function.arguments = _normalize_strict_tool_arguments(
                            tool_call.function.arguments, schema)
            if syntax_repairs:
                request['strictToolSyntaxRepairs'] = syntax_repairs
        if output_schema is not None:
            if strict_output_schema and (not tool_calls or len(tool_calls) != 1
                    or tool_calls[0].function.name != 'emit_result'):
                raise ValueError('Strict structured output must submit exactly one emit_result tool call.')
            if tool_calls and (len(tool_calls) != 1 or tool_calls[0].function.name != 'emit_result'):
                raise ValueError('Structured response did not submit exactly one emit_result call.')
            request['structuredOutputDelivery'] = 'strict_tool' if strict_output_schema else 'validated_json'
            if tool_calls:
                content = tool_calls[0].function.arguments
                request['responseFingerprint'] = response_fingerprint(content)
            try:
                content, payload, syntax_repaired = _decode_json_with_terminal_closer_repair(content, output_schema)
                if syntax_repaired:
                    request['structuredOutputSyntaxRepair'] = 'redundant_terminal_closers'
            except json.JSONDecodeError:
                raise
            try:
                validate(payload, output_schema)
            except ValidationError as error:
                raise StructuredResponseError(content,error) from error
            except SchemaError:
                raise
            except Exception as error:
                raise SchemaError('Structured output schema could not be evaluated.') from error
            tool_calls = None
        request['responseFingerprint'] = response_fingerprint(content)
        _record_chat_metric(resp, started, model=endpoint.model, reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens, timeout=timeout, outcome='success', request=request)
        return content, tool_calls, getattr(message, "reasoning_content", None)
    except BaseException as error:
        if isinstance(error, (ValueError, ValidationError)) and resp is not None:
            record_submission_rejection(error, request_id=request['requestId'])
        if output_schema is not None and resp is not None and not hasattr(error, 'diagnostics'):
            choice = next(iter(getattr(resp, 'choices', None) or []), None)
            message = getattr(choice, 'message', None)
            error.diagnostics = {'finishReason':getattr(choice, 'finish_reason', None),
                'content':getattr(message, 'content', None),
                'toolCalls':[{'name':getattr(getattr(call, 'function', None), 'name', None),
                              'arguments':getattr(getattr(call, 'function', None), 'arguments', None)}
                             for call in (getattr(message, 'tool_calls', None) or [])]}
        if not isinstance(error, TruncatedResponseError):
            _record_chat_metric(resp, started, model=endpoint.model, reasoning_effort=reasoning_effort,
                                max_tokens=max_tokens, timeout=timeout,
                                outcome='cancelled' if isinstance(error, KeyboardInterrupt) else 'failure',
                                error_type=type(error).__name__, request=request)
        raise


def _usage_dict(response):
    usage = getattr(response, 'usage', None)
    if hasattr(usage, 'model_dump'):
        return usage.model_dump()
    return usage if isinstance(usage, dict) else {}


def _record_chat_metric(response, started, *, model, reasoning_effort, max_tokens, timeout,
                        outcome, error_type=None, request=None):
    usage = _usage_dict(response) if response is not None else {}
    details = usage.get('completion_tokens_details') or {}
    prompt_details = usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
    metric = {
        'event': 'api_request', 'outcome': outcome, **(request or {}),
        'providerRequestId':getattr(response,'id',None),
        'model': getattr(response, 'model', None) or model,
        'reasoningEffort': reasoning_effort, 'thinking': 'enabled' if reasoning_effort is not None else 'disabled',
        'maxTokens': max_tokens, 'timeoutSeconds': timeout,
        'elapsedSeconds': round(time.monotonic() - started, 3),
        'promptTokens': usage.get('prompt_tokens', usage.get('input_tokens')),
        'completionTokens': usage.get('completion_tokens', usage.get('output_tokens')),
        'reasoningTokens': details.get('reasoning_tokens'),
        'cacheHitTokens': next((value for value in (
            usage.get('prompt_cache_hit_tokens'), usage.get('cached_tokens'),
            prompt_details.get('cached_tokens'), prompt_details.get('cache_read_tokens')) if value is not None), None),
        'cacheMissTokens': usage.get('prompt_cache_miss_tokens'),
    }
    if error_type:
        metric['errorType'] = error_type
    choice = next(iter(getattr(response, 'choices', None) or []), None)
    message = getattr(choice, 'message', None)
    metric['submissionIds'] = [call.id for call in (getattr(message, 'tool_calls', None) or [])
                               if getattr(call, 'id', None)]
    record_api_metric(metric)


def _log_connection_error(exception, attempt, max_retries, script_dir=None):
    """
    Log connection error details to a file for debugging.
    
    Args:
        exception: The exception that occurred
        attempt: Current attempt number (1-based)
        max_retries: Maximum number of retries
        script_dir: Directory where the script is located (defaults to current directory)
    
    Returns:
        str: Path to the saved error file, or None if saving failed
    """
    try:
        # Determine the base directory (where the script is located)
        if script_dir is None:
            try:
                script_dir = _default_script_dir()
            except (NameError, AttributeError):
                script_dir = os.getcwd()
        
        # Create errors directory if it doesn't exist
        errors_dir = os.path.join(script_dir, "errors")
        os.makedirs(errors_dir, exist_ok=True)
        
        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"connection_error_{timestamp}_attempt{attempt}.json"
        filepath = os.path.join(errors_dir, filename)
        
        # Get full traceback
        tb_str = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        
        # Get exception chain information
        cause = getattr(exception, '__cause__', None)
        context = getattr(exception, 'context', None)
        
        # Prepare error data
        error_data = {
            "timestamp": datetime.now().isoformat(),
            "attempt": attempt,
            "max_retries": max_retries,
            "exception_type": type(exception).__name__,
            "exception_module": type(exception).__module__ if hasattr(type(exception), '__module__') else None,
            "exception_message": str(exception),
            "exception_repr": repr(exception),
            "traceback": tb_str,
            "exception_chain": {}
        }
        
        # Add cause information if available
        if cause:
            error_data["exception_chain"]["cause"] = {
                "type": type(cause).__name__,
                "module": type(cause).__module__ if hasattr(type(cause), '__module__') else None,
                "message": str(cause),
                "repr": repr(cause)
            }
            try:
                error_data["exception_chain"]["cause"]["traceback"] = ''.join(
                    traceback.format_exception(type(cause), cause, cause.__traceback__)
                )
            except:
                pass
        
        # Add context information if available
        if context:
            error_data["exception_chain"]["context"] = {
                "type": type(context).__name__,
                "module": type(context).__module__ if hasattr(type(context), '__module__') else None,
                "message": str(context),
                "repr": repr(context)
            }
            try:
                error_data["exception_chain"]["context"]["traceback"] = ''.join(
                    traceback.format_exception(type(context), context, context.__traceback__)
                )
            except:
                pass
        
        # Add request information if available (from OpenAI exceptions)
        if hasattr(exception, 'request'):
            try:
                req = exception.request
                error_data["request_info"] = {
                    "method": getattr(req, 'method', None),
                    "url": str(getattr(req, 'url', None)) if hasattr(req, 'url') else None,
                    "headers": {key: value for key, value in getattr(req, 'headers', {}).items()
                                if key.lower() in ('content-type', 'x-request-id', 'request-id')},
                }
            except:
                pass
        
        # Write error to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)
        
        return filepath
    except Exception as e:
        print(f"Error saving connection error to file: {e}", file=sys.stderr)
        return None


def test_connection(client, show_message=True, logger=None, *, model=None):
    """
    Test connection to DeepSeek API with a minimal request using streaming mode.
    
    Args:
        client: OpenAI client
        show_message: If True, print status messages
        logger: Optional ConversationLogger for debug logging (log_print for messages)
    
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    def _out(msg):
        if logger:
            logger.log_print(msg)
        elif show_message:
            print(msg)
    endpoint = resolve_llm_endpoint()
    if show_message or logger:
        _out(f"Testing connection to {endpoint.base_url}...")

    try:
        # Make a minimal API call - just ask for a simple JSON response
        test_messages = [
            {"role": "system", "content": "You are a helpful assistant. Respond with valid JSON only."},
            {"role": "user", "content": 'Respond with {"status": "ok"} as JSON.'}
        ]

        # Use streaming mode for better high-traffic handling
        with LoadingIndicator("Testing API connection") if show_message or logger else nullcontext():
            with api_metrics_scope(logger, 'connection_test'):
                content, finish_reason = call_model(client, test_messages, json_mode=True,
                    model=model, reasoning_effort=None, max_tokens=10, retry=False)
        
        if content:
            if show_message or logger:
                _out("✓ Connection test successful")
            return True, None
        else:
            error_msg = "Connection test failed: Empty response from API"
            if show_message or logger:
                _out(f"✗ {error_msg}")
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Connection test failed: {str(e)}"
        if show_message or logger:
            _out(f"✗ {error_msg}")
        return False, error_msg


def _is_connection_error(error):
    causes = [error, getattr(error, '__cause__', None), getattr(error, '__context__', None),
              getattr(error, 'context', None)]
    for cause in causes:
        if cause is None:
            continue
        if ((APIConnectionError and isinstance(cause, APIConnectionError))
                or (RemoteProtocolError and isinstance(cause, RemoteProtocolError))):
            return True
        name, message = type(cause).__name__, str(cause).lower()
        if ('ConnectionError' in name or 'RemoteProtocolError' in name
                or 'peer closed connection' in message or 'incomplete chunked read' in message):
            return True
    return False


def _retry_model_call(call, *, reasoning_effort=None, max_attempts=2, base_delay=1, show_message=False):
    """Share one attempt limit between connection recovery and empty reasoning recovery."""
    for attempt in range(max_attempts):
        check_cancelled()
        try:
            return call(reasoning_effort)
        except Exception as error:
            if isinstance(error, TruncatedResponseError):
                if (attempt + 1 >= max_attempts or reasoning_effort is None
                        or error.diagnostics['cause'] != 'reasoning_budget_exhausted'):
                    raise
                reasoning_effort = None
                continue
            if not _is_connection_error(error):
                raise
            error_file = _log_connection_error(error, attempt + 1, max_attempts)
            if error_file and show_message:
                print(f'  Connection error logged to: {os.path.basename(error_file)}')
            if attempt + 1 >= max_attempts:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            if show_message:
                print(f'  Connection error (attempt {attempt + 1}/{max_attempts}), retrying in {delay:.1f}s...')
            time.sleep(delay)


def _retry_on_connection_error(func, max_retries=2, base_delay=1, show_message=False):
    return _retry_model_call(lambda _: run_cancellable(func), max_attempts=max_retries,
                             base_delay=base_delay, show_message=show_message)


def _collect_streaming_response(stream, start_time=None, usage_collector=None):
    """
    Collect chunks from a streaming response and reconstruct the full content.
    Handles keep-alive comments during high traffic periods.
    
    Args:
        stream: Streaming response from OpenAI API
        start_time: Optional start time for logging wait duration
    
    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    content_parts = []
    finish_reason = None
    for chunk in stream:
        check_cancelled()
        if usage_collector is not None:
            model_name = getattr(chunk, 'model', None)
            if model_name:
                usage_collector['model'] = model_name
            usage = getattr(chunk, 'usage', None)
            if usage is not None:
                usage_collector['usage'] = usage.model_dump() if hasattr(usage, 'model_dump') else usage
        if chunk.choices and len(chunk.choices) > 0:
            choice = chunk.choices[0]
            # Check for finish_reason first (may be in choice, not delta)
            if hasattr(choice, 'finish_reason') and choice.finish_reason:
                finish_reason = choice.finish_reason
            
            # Get content from delta
            if hasattr(choice, 'delta') and choice.delta:
                delta = choice.delta
                if hasattr(delta, 'content') and delta.content:
                    content_parts.append(delta.content)
    
    content = ''.join(content_parts)
    return content, finish_reason


def _measured_stream_request(create, *, model, reasoning_effort, thinking, max_tokens,
                             timeout=None, **kwargs):
    """Measure one provider request, including one retry attempt, without retaining content."""
    started = time.monotonic()
    usage = {}
    request_kwargs = dict(kwargs)
    if 'messages' in request_kwargs:
        request_kwargs['messages'] = _request_messages(request_kwargs['messages'], request_kwargs.get('response_format'))
    request_kwargs['stream_options'] = {'include_usage': True}
    request_kwargs['timeout'] = timeout
    if reasoning_effort is not None:
        request_kwargs['reasoning_effort'] = reasoning_effort
    validate_image_request({'model': model, 'max_tokens': max_tokens, **request_kwargs})
    request = begin_api_request(model, messages=request_kwargs.get('messages'), tools=request_kwargs.get('tools'))
    def collect():
        stream = create(model=model, max_tokens=max_tokens, **request_kwargs)
        try:
            return _collect_streaming_response(stream, usage_collector=usage)
        finally:
            if callable(getattr(stream, 'close', None)):
                stream.close()

    try:
        result = run_cancellable(collect, deadline_seconds=timeout)
        outcome = 'truncated' if result[1] == 'length' else 'success'
        _record_stream_metric(usage, started, model=model, reasoning_effort=reasoning_effort,
                              thinking=thinking, max_tokens=max_tokens, timeout=timeout, outcome=outcome, request=request)
        return result
    except BaseException as error:
        _record_stream_metric(usage, started, model=model, reasoning_effort=reasoning_effort,
                              thinking=thinking, max_tokens=max_tokens, timeout=timeout,
                              outcome='cancelled' if isinstance(error, KeyboardInterrupt) else 'failure',
                              error_type=type(error).__name__, request=request)
        raise


def _record_stream_metric(collected, started, *, model, reasoning_effort, thinking,
                          max_tokens, timeout, outcome, error_type=None, request=None):
    usage = collected.get('usage') or {}
    if hasattr(usage, 'model_dump'):
        usage = usage.model_dump()
    details = usage.get('completion_tokens_details') or {}
    prompt_details = usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
    metric = {
        'event': 'api_request', 'outcome': outcome, **(request or {}),
        'model': collected.get('model') or model,
        'reasoningEffort': reasoning_effort, 'thinking': thinking,
        'maxTokens': max_tokens, 'timeoutSeconds': timeout,
        'elapsedSeconds': round(time.monotonic() - started, 3),
        'promptTokens': usage.get('prompt_tokens', usage.get('input_tokens')),
        'completionTokens': usage.get('completion_tokens', usage.get('output_tokens')),
        'reasoningTokens': details.get('reasoning_tokens'),
        'cacheHitTokens': next((value for value in (
            usage.get('prompt_cache_hit_tokens'), usage.get('cached_tokens'),
            prompt_details.get('cached_tokens'), prompt_details.get('cache_read_tokens')) if value is not None), None),
        'cacheMissTokens': usage.get('prompt_cache_miss_tokens'),
    }
    if error_type:
        metric['errorType'] = error_type
    record_api_metric(metric)


def json_call(client, messages, max_tokens=DEEPSEEK_CHAT_DEFAULT_TOKENS, *, model=None):
    return call_model(client, messages, json_mode=True, model=model, reasoning_effort=None,
                      max_tokens=max_tokens)


def _run_model_call(call, *, loading_message='Generating', show_loading=True, logger=None,
                    stage=None, cancelled_result=None, loading_details=None, response_label=None):
    """Own loading cleanup, context propagation, cancellation and rejected-output logging."""
    started = time.monotonic()
    loading = LoadingIndicator(loading_message) if show_loading else None
    _, active_stage = current_api_metrics_scope()
    with api_metrics_scope(logger, active_stage or stage or loading_message or 'json_generation'):
        if loading:
            if logger:
                logger.log('Loading started: ' + (loading_details or loading_message))
        try:
            with loading if loading else nullcontext():
                result = run_cancellable(call)
        except KeyboardInterrupt:
            (logger.log_print if logger else print)('Cancelled. Returning to prompt...')
            return cancelled_result
        except TruncatedResponseError as error:
            if logger:
                logger.log_response('rejected truncated planning response',
                                    json.dumps(error.diagnostics, ensure_ascii=False), truncate_at=0)
            raise
        finally:
            if loading and logger:
                logger.log(f'Loading finished: {stage or loading_message} ({time.monotonic() - started:.2f}s)')
        if logger and response_label:
            logger.log_print(f'{response_label} response ready ({time.monotonic() - started:.1f}s).')
        return result


def chat_call_with_loading(client, messages, tools=None, logger=None, *, reasoning_effort='high', activity='Thinking',
                           max_tokens=DEEPSEEK_REASONER_MAX_TOKENS, timeout=DEEPSEEK_PLANNING_TIMEOUT_SECONDS,
                           tool_choice=None, require_strict_tool_delivery=False):
    endpoint = resolve_llm_endpoint()
    mode = f'thinking, {reasoning_effort} effort' if reasoning_effort is not None else 'non-thinking'
    options = {'reasoning_effort': reasoning_effort, 'max_tokens': max_tokens, 'timeout': timeout}
    if tool_choice is not None:
        options['tool_choice'] = tool_choice
    if require_strict_tool_delivery:
        options['require_strict_tool_delivery'] = True
    deadline = f'{timeout}s' if timeout else 'none'
    details = (f"{activity} (effort={reasoning_effort}, model={endpoint.model}, "
               f"thinking={'enabled' if reasoning_effort is not None else 'disabled'}, "
               f"max_tokens={max_tokens}, deadline={deadline})")
    return _run_model_call(lambda: chat_call(client, messages, tools, **options),
        loading_message=f'{activity} | {endpoint.model}, {mode}', logger=logger, stage=activity,
        cancelled_result=(None, None, None), loading_details=details,
        response_label='Repair' if activity == 'Repairing draft' else 'Planning')


def _json_content(result, max_tokens, *, require_complete=False):
    content, finish_reason = result
    if finish_reason == 'length':
        raise ValueError(f'Response truncated at {max_tokens} max tokens. Consider breaking the request into smaller parts.')
    if require_complete and not is_json_complete(content):
        raise ValueError('Model response is not a complete JSON object or array.')
    return content


def json_call_with_retry(client, messages, max_tokens=DEEPSEEK_CHAT_DEFAULT_TOKENS):
    """Use the shared bounded connection policy without escalating budget or thinking mode."""
    return _json_content(json_call(client, messages, max_tokens), max_tokens, require_complete=True)


def json_call_with_loading(client, messages, max_tokens=None):
    budget = DEEPSEEK_CHAT_DEFAULT_TOKENS if max_tokens is None else max_tokens
    return _run_model_call(lambda: json_call_with_retry(client, messages, budget))


def json_call_chat_max_with_loading(client, messages, loading_message='Generating', show_loading=True, logger=None, *, model=None):
    return _run_model_call(lambda: _json_content(json_call(client, messages, DEEPSEEK_CHAT_MAX_TOKENS,
        **({'model': model} if model else {})), DEEPSEEK_CHAT_MAX_TOKENS),
        loading_message=loading_message, show_loading=show_loading, logger=logger)


def is_json_complete(json_str):
    """
    Check if JSON appears complete (not truncated at output limit).
    
    Works with partial JSON structures (equipment, exercises, workout structure)
    as well as full WorkoutStore structures.
    """
    if not json_str or not json_str.strip():
        return False
    
    try:
        data = json.loads(json_str)
        # If it parses successfully, check for structural completeness
        if isinstance(data, dict):
            # For full WorkoutStore structure
            if "workouts" in data and "equipments" in data:
                return True
            # For partial structures (equipment, exercises, workout structure)
            # Check if arrays are properly closed by verifying structure
            if "equipments" in data:
                return isinstance(data["equipments"], list)
            if "exercises" in data:
                return isinstance(data["exercises"], list)
            if "workoutMetadata" in data and "workoutComponents" in data:
                return isinstance(data["workoutComponents"], list)
            # If it's a valid dict and parses, assume complete
            return True
        elif isinstance(data, list):
            # If it's a list, assume complete if it parses
            return True
        return False
    except json.JSONDecodeError:
        # Check if error suggests truncation (missing closing braces)
        brace_diff = json_str.count('{') - json_str.count('}')
        bracket_diff = json_str.count('[') - json_str.count(']')
        if brace_diff > 0 or bracket_diff > 0:
            return False  # Likely truncated
        # If braces/brackets are balanced but JSON is invalid, it might still be truncated
        # Check if the string ends abruptly (common truncation pattern)
        trimmed = json_str.rstrip()
        if trimmed and not trimmed.endswith(('}', ']', '"')):
            # Doesn't end with valid JSON terminator
            return False
        return False  # JSON decode error suggests incomplete


def json_call_large(client, messages, max_tokens=DEEPSEEK_REASONER_DEFAULT_TOKENS):
    return call_model(client, messages, json_mode=True, reasoning_effort='high', max_tokens=max_tokens)


def json_call_reasoner_only(client, messages, *, model=None):
    return call_model(client, messages, json_mode=True, model=model, reasoning_effort='high',
                      max_tokens=DEEPSEEK_REASONER_MAX_TOKENS)


def json_call_large_with_retry(client, messages, max_tokens=DEEPSEEK_REASONER_DEFAULT_TOKENS):
    return _json_content(json_call_large(client, messages, max_tokens), max_tokens, require_complete=True)


def json_call_large_with_loading(client, messages, max_tokens=None):
    budget = DEEPSEEK_REASONER_DEFAULT_TOKENS if max_tokens is None else max_tokens
    return _run_model_call(lambda: json_call_large_with_retry(client, messages, budget),
                           loading_message='Generating (large output)')


def json_call_reasoner_only_with_loading(client, messages, loading_message='Generating', show_loading=True, logger=None, *, model=None):
    return _run_model_call(lambda: _json_content(json_call_reasoner_only(client, messages,
        **({'model': model} if model else {})), DEEPSEEK_REASONER_MAX_TOKENS),
        loading_message=loading_message, show_loading=show_loading, logger=logger)


def estimate_output_size(workout_count, exercise_count_per_workout=5):
    """Rough estimate: ~100-200 tokens per exercise, ~50 tokens overhead per workout."""
    estimated = (workout_count * 50) + (workout_count * exercise_count_per_workout * 150)
    return estimated


