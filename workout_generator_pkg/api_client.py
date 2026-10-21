"""OpenAI/DeepSeek API call helpers with retry and loading UX."""

from __future__ import annotations

import json
import random
import time
import traceback
from contextlib import nullcontext
from jsonschema import validate, ValidationError
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
from .api_metrics import api_metrics_scope, current_api_metrics_scope, record_api_metric, begin_api_request, remaining_request_timeout

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
        usage = getattr(response, 'usage', None)
        usage = usage.model_dump() if hasattr(usage, 'model_dump') else None
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


def _request_messages(messages, response_format=None):
    prepared = prepare_image_messages(messages)
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


def chat_call(client, messages, tools=None, *, reasoning_effort="high", max_tokens=DEEPSEEK_REASONER_MAX_TOKENS, timeout=DEEPSEEK_PLANNING_TIMEOUT_SECONDS, response_format=None, output_schema=None, tool_choice=None):
    options = dict(max_tokens=max_tokens, timeout=timeout, response_format=response_format,
                   output_schema=output_schema, tool_choice=tool_choice)
    def call(effort):
        return _retry_on_connection_error(
            lambda: _chat_call_once(client, messages, tools, reasoning_effort=effort, **options),
            max_retries=2, base_delay=1)
    try:
        return call(reasoning_effort)
    except TruncatedResponseError as error:
        if reasoning_effort is None or error.diagnostics['cause'] != 'reasoning_budget_exhausted':
            raise
        # No answer was emitted; retry the same task once without the exhausted reasoning channel.
        return call(None)


def _chat_call_once(client, messages, tools=None, *, reasoning_effort, max_tokens, timeout, response_format, output_schema, tool_choice=None):
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
    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs['tool_choice'] = tool_choice
    if response_format is not None:
        kwargs['response_format'] = response_format
    if output_schema is not None:
        if tools:
            raise ValueError('Structured replies cannot also execute application tools.')
        kwargs.pop('response_format', None)
        kwargs['messages'] = [*kwargs['messages'], {'role':'system', 'content':
            'Submit the final result through emit_result exactly once, following its schema.'}]
        kwargs['tools'] = [{'type':'function','function':{'name':'emit_result',
            'description':'Submit the final structured result.','strict':True,'parameters':output_schema}}]
    validate_image_request(kwargs)
    
    started = time.monotonic()
    request = begin_api_request(endpoint.model, messages=kwargs['messages'], tools=kwargs.get('tools'))
    resp = None
    try:
        options = {'max_retries':0}
        if output_schema is not None and endpoint.is_deepseek:
            options['base_url'] = 'https://api.deepseek.com/beta'
        resp = run_cancellable(client.with_options(**options).chat.completions.create, deadline_seconds=remaining_request_timeout(timeout), **kwargs)
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            error = TruncatedResponseError(resp, max_tokens, reasoning_effort)
            _record_chat_metric(resp, started, model=endpoint.model, reasoning_effort=reasoning_effort,
                                max_tokens=max_tokens, timeout=timeout, outcome='truncated', request=request)
            raise error
        message = resp.choices[0].message
        content = message.content
        tool_calls = message.tool_calls if hasattr(message, 'tool_calls') and message.tool_calls else None
        if output_schema is not None:
            if tool_calls and (len(tool_calls) != 1 or tool_calls[0].function.name != 'emit_result'):
                raise ValueError('Structured response did not submit exactly one emit_result call.')
            request['structuredOutputDelivery'] = 'strict_tool' if tool_calls else 'validated_json'
            if tool_calls:
                content = tool_calls[0].function.arguments
            try:
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError as error:
                    if error.msg != 'Extra data':
                        raise
                    payload, end = json.JSONDecoder().raw_decode(content, len(content) - len(content.lstrip()))
                    # Ignore only redundant outer closers after one complete object, never additional data.
                    if not isinstance(payload, dict) or set(content[end:].strip()) != {'}'}:
                        raise error
                    content = content[:end]
                    request['structuredOutputSyntaxRepair'] = 'redundant_terminal_closers'
                validate(payload, output_schema)
            except ValidationError as error:
                raise StructuredResponseError(content,error) from error
            tool_calls = None
        _record_chat_metric(resp, started, model=endpoint.model, reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens, timeout=timeout, outcome='success', request=request)
        return content, tool_calls, getattr(message, "reasoning_content", None)
    except BaseException as error:
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
                    "headers": dict(getattr(req, 'headers', {})) if hasattr(req, 'headers') else None,
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
                content, finish_reason = run_cancellable(_measured_stream_request,
                    client.chat.completions.create,
                    model=model or endpoint.model, reasoning_effort=None, thinking='disabled',
                    max_tokens=10, messages=test_messages,
                    response_format={"type": "json_object"}, stream=True,
                    **({'extra_body': {"thinking": {"type": "disabled"}}} if endpoint.is_deepseek else {}),
                )
        
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


def _retry_on_connection_error(func, max_retries=5, base_delay=2, show_message=False):
    """
    Helper function to retry a callable on connection errors with exponential backoff.
    
    Args:
        func: Callable to execute
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
        show_message: If True, print retry messages
    
    Returns:
        Result of func()
    
    Raises:
        Original exception if not a connection error or if retries exhausted
    """
    for attempt in range(max_retries):
        check_cancelled()
        try:
            return run_cancellable(func)
        except Exception as e:
            # Check if it's a connection error that we should retry
            # Check the exception type and its chain (for wrapped exceptions)
            error_type = type(e).__name__
            error_str = str(e).lower()
            error_type_str = str(type(e))
            
            # Check exception chain for underlying errors
            cause = getattr(e, '__cause__', None)
            context = getattr(e, 'context', None)
            
            # Build a comprehensive error message to check
            full_error_str = error_str
            if cause:
                full_error_str += " " + str(cause).lower()
                full_error_str += " " + str(type(cause)).lower()
            if context:
                full_error_str += " " + str(context).lower()
                full_error_str += " " + str(type(context)).lower()
            
            # Check using imported exception types if available
            is_connection_error = False
            if APIConnectionError and isinstance(e, APIConnectionError):
                is_connection_error = True
            elif RemoteProtocolError and isinstance(e, RemoteProtocolError):
                is_connection_error = True
            elif cause and RemoteProtocolError and isinstance(cause, RemoteProtocolError):
                is_connection_error = True
            elif cause and APIConnectionError and isinstance(cause, APIConnectionError):
                is_connection_error = True
            else:
                # Fallback to string matching
                is_connection_error = (
                    "APIConnectionError" in error_type or
                    "ConnectionError" in error_type or
                    "RemoteProtocolError" in error_type_str or
                    "RemoteProtocolError" in full_error_str or
                    "httpx.RemoteProtocolError" in error_type_str or
                    "httpcore.RemoteProtocolError" in error_type_str or
                    "peer closed connection" in full_error_str or
                    "incomplete chunked read" in full_error_str or
                    (cause and ("RemoteProtocolError" in str(type(cause)) or "ConnectionError" in str(type(cause))))
                )
            
            if is_connection_error:
                # Log the connection error to file
                error_file = _log_connection_error(e, attempt + 1, max_retries)
                if error_file and show_message:
                    print(f"  Connection error logged to: {os.path.basename(error_file)}")
                
                if attempt < max_retries - 1:
                    # Calculate exponential backoff delay with jitter
                    delay = base_delay * (2 ** attempt)
                    # Add random jitter (0-1 second) to avoid thundering herd
                    jitter = random.uniform(0, 1)
                    total_delay = delay + jitter
                    if show_message:
                        print(f"  Connection error (attempt {attempt + 1}/{max_retries}), retrying in {total_delay:.1f}s...")
                    time.sleep(total_delay)
                    continue
                else:
                    # Out of retries - log final failure
                    if show_message:
                        print(f"  Connection error: All {max_retries} retry attempts exhausted.")
                    raise
            else:
                # Not a retryable error
                raise


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
    if reasoning_effort is not None:
        request_kwargs['reasoning_effort'] = reasoning_effort
    validate_image_request({'model': model, 'max_tokens': max_tokens, **request_kwargs})
    request = begin_api_request(model, messages=request_kwargs.get('messages'), tools=request_kwargs.get('tools'))
    try:
        stream = create(model=model, max_tokens=max_tokens, **request_kwargs)
        result = _collect_streaming_response(stream, usage_collector=usage)
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
    """
    Call the endpoint in non-thinking mode for JSON generation using streaming.
    Streaming mode better handles keep-alive comments during high traffic periods.

    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    endpoint = resolve_llm_endpoint()

    def _call():
        return _measured_stream_request(client.chat.completions.create,
            model=model or endpoint.model, reasoning_effort=None, thinking='disabled', max_tokens=max_tokens,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,  # Enable streaming for better high-traffic handling
            **({'extra_body': {"thinking": {"type": "disabled"}}} if endpoint.is_deepseek else {}),
        )

    return _retry_on_connection_error(_call, show_message=True)


def chat_call_with_loading(client, messages, tools=None, logger=None, *, reasoning_effort='high', activity='Thinking',
                           max_tokens=DEEPSEEK_REASONER_MAX_TOKENS, timeout=DEEPSEEK_PLANNING_TIMEOUT_SECONDS,
                           tool_choice=None):
    """
    Wrapper for chat_call that shows loading indicator with timer and supports cancellation.

    Args:
        client: OpenAI client
        messages: List of message dicts
        tools: Optional list of tool definitions for function calling
        logger: Optional ConversationLogger for debug logging (loading start/stop)

    Returns:
        tuple: (content, tool_calls, reasoning_content), or three None values on cancellation.
    """
    endpoint = resolve_llm_endpoint()
    mode = f'thinking, {reasoning_effort} effort' if reasoning_effort is not None else 'non-thinking'
    loading = LoadingIndicator(f"{activity} | {endpoint.model}, {mode}")
    started = time.monotonic()
    result = [None]
    exception = [None]
    cancelled = [False]
    
    def api_call():
        _, active_stage = current_api_metrics_scope()
        with api_metrics_scope(logger, active_stage or activity):
            try:
                call_options = {'reasoning_effort': reasoning_effort, 'max_tokens': max_tokens,
                                'timeout': timeout}
                if tool_choice is not None:
                    call_options['tool_choice'] = tool_choice
                result[0] = chat_call(client, messages, tools, **call_options)
            except KeyboardInterrupt:
                cancelled[0] = True
                exception[0] = KeyboardInterrupt()
            except Exception as e:
                exception[0] = e
    
    if logger:
        deadline = f'{timeout}s' if timeout else 'none'
        logger.log(f"Loading started: {activity} (effort={reasoning_effort}, model={endpoint.model}, thinking={'enabled' if reasoning_effort is not None else 'disabled'}, max_tokens={max_tokens}, deadline={deadline})")
    loading.start()
    try:
        run_cancellable(api_call)
    except KeyboardInterrupt:
        cancelled[0] = True
        loading.stop()
        if logger:
            logger.log_print("\nCancelled. Returning to prompt...")
        else:
            print("\nCancelled. Returning to prompt...")
        return None, None, None
    
    loading.stop()
    if logger:
        logger.log(f"Loading finished: {activity} ({time.monotonic() - started:.2f}s)")
    
    if cancelled[0]:
        if logger:
            logger.log_print("Cancelled. Returning to prompt...")
        else:
            print("Cancelled. Returning to prompt...")
        return None, None, None
    
    if exception[0]:
        if isinstance(exception[0], KeyboardInterrupt):
            if logger:
                logger.log_print("Cancelled. Returning to prompt...")
            else:
                print("Cancelled. Returning to prompt...")
            return None, None, None
        if logger and isinstance(exception[0], TruncatedResponseError):
            logger.log_response('rejected truncated planning response',
                                json.dumps(exception[0].diagnostics, ensure_ascii=False), truncate_at=0)
        raise exception[0]
    
    if logger:
        logger.log_print(f"{'Repair' if activity == 'Repairing draft' else 'Planning'} response ready ({time.monotonic() - started:.1f}s).")
    return result[0]


def json_call_with_retry(client, messages):
    """
    Cascading retry logic for JSON generation.
    
    Strategy:
    1. Try non-thinking JSON generation with 4K tokens.
    2. If truncated, retry non-thinking generation with 8K tokens.
    3. If still truncated, use thinking mode with 32K tokens.
    4. If still truncated, retry thinking mode with 64K tokens.
    
    Returns:
        str: JSON content, or None if cancelled
    """
    # Helper to check if response is truncated
    def is_truncated(content, finish_reason):
        """Check if response is truncated based on finish_reason or JSON completeness."""
        if finish_reason == "length":
            return True
        if not is_json_complete(content):
            return True
        return False
    
    # Step 1: Try with chat model at default (4K)
    content, finish_reason = json_call(client, messages, DEEPSEEK_CHAT_DEFAULT_TOKENS)
    if not is_truncated(content, finish_reason):
        return content
    
    # Step 2: Retry with chat model at max (8K)
    if finish_reason == "length":
        print("  Response truncated at 4K, retrying with 8K tokens...")
    content, finish_reason = json_call(client, messages, DEEPSEEK_CHAT_MAX_TOKENS)
    if not is_truncated(content, finish_reason):
        return content
    
    # Step 3: Fall back to reasoner model at default (32K)
    if finish_reason == "length" or not is_json_complete(content):
        print("  Still truncated at 8K, switching to reasoner model (32K)...")
    content, finish_reason = json_call_large(client, messages, DEEPSEEK_REASONER_DEFAULT_TOKENS)
    if not is_truncated(content, finish_reason):
        return content
    
    # Step 4: Retry with reasoner model at max (64K)
    if finish_reason == "length" or not is_json_complete(content):
        print("  Still truncated at 32K, retrying with 64K tokens...")
    content, finish_reason = json_call_large(client, messages, DEEPSEEK_REASONER_MAX_TOKENS)
    if is_truncated(content, finish_reason):
        raise ValueError(
            f"Response still truncated after all retries (64K max). "
            f"Finish reason: {finish_reason}. "
            f"Consider breaking the request into smaller parts."
        )
    
    return content


def json_call_with_loading(client, messages, max_tokens=None):
    """
    Wrapper for json_call_with_retry that shows loading indicator with timer and supports cancellation.
    
    Note: max_tokens parameter is ignored - cascading retry logic handles token limits automatically.
    """
    loading = LoadingIndicator("Generating")
    result = [None]
    exception = [None]
    cancelled = [False]
    
    def api_call():
        try:
            result[0] = json_call_with_retry(client, messages)
        except KeyboardInterrupt:
            cancelled[0] = True
            exception[0] = KeyboardInterrupt()
        except Exception as e:
            exception[0] = e
    
    loading.start()
    try:
        run_cancellable(api_call)
    except KeyboardInterrupt:
        cancelled[0] = True
        loading.stop()
        print("\nCancelled. Returning to prompt...")
        return None
    
    loading.stop()
    
    if cancelled[0]:
        print("Cancelled. Returning to prompt...")
        return None
    
    if exception[0]:
        if isinstance(exception[0], KeyboardInterrupt):
            print("Cancelled. Returning to prompt...")
            return None
        raise exception[0]
    
    return result[0]


def json_call_chat_max_with_loading(client, messages, loading_message="Generating", show_loading=True, logger=None, *, model=None):
    """
    Wrapper for non-thinking JSON generation with an 8K output budget.
    Includes loading indicator and cancellation support. Includes retry logic for connection errors.
    
    Args:
        client: OpenAI client
        messages: List of message dicts
        loading_message: Custom message for loading indicator
        show_loading: If False, skip the loading indicator (useful for parallel execution)
        logger: Optional ConversationLogger for debug logging (loading start/stop)
    
    Returns:
        str: JSON content, or None if cancelled
    """
    loading = None
    if show_loading:
        loading = LoadingIndicator(loading_message)
    result = [None]
    exception = [None]
    cancelled = [False]
    
    def api_call():
        try:
            content, finish_reason = json_call(
                client, messages, DEEPSEEK_CHAT_MAX_TOKENS,
                **({"model": model} if model else {}),
            )
            if finish_reason == "length":
                raise ValueError("Response truncated at 8K max tokens. Consider breaking the request into smaller parts.")
            result[0] = content
        except KeyboardInterrupt:
            cancelled[0] = True
            exception[0] = KeyboardInterrupt()
        except Exception as e:
            exception[0] = e
    
    if loading:
        if logger:
            logger.log("Loading started: " + loading_message)
        loading.start()
    try:
        run_cancellable(api_call)
    except KeyboardInterrupt:
        cancelled[0] = True
        if loading:
            loading.stop()
        if logger:
            logger.log_print("\nCancelled. Returning to prompt...")
        else:
            print("\nCancelled. Returning to prompt...")
        return None
    
    if loading:
        loading.stop()
        if logger:
            logger.log("Loading finished: " + loading_message)
    
    if cancelled[0]:
        if logger:
            logger.log_print("Cancelled. Returning to prompt...")
        else:
            print("Cancelled. Returning to prompt...")
        return None
    
    if exception[0]:
        if isinstance(exception[0], KeyboardInterrupt):
            if logger:
                logger.log_print("Cancelled. Returning to prompt...")
            else:
                print("Cancelled. Returning to prompt...")
            return None
        raise exception[0]
    
    return result[0]


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
    """
    Use thinking mode for larger outputs with streaming.
    Streaming mode better handles keep-alive comments during high traffic periods.

    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    endpoint = resolve_llm_endpoint()

    def _call():
        return _measured_stream_request(client.chat.completions.create,
            model=endpoint.model, reasoning_effort='high', thinking='enabled', max_tokens=max_tokens,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,  # Enable streaming for better high-traffic handling
            **({'extra_body': {"thinking": {"type": "enabled"}}} if endpoint.is_deepseek else {}),
        )

    return _retry_on_connection_error(_call, show_message=True)


def json_call_reasoner_only(client, messages, *, model=None):
    """
    Call the endpoint in thinking mode for JSON generation with a 64K output budget.
    This is the standard function for all JSON generation in the planner/emitter architecture.
    Streaming mode better handles keep-alive comments during high traffic periods.

    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    endpoint = resolve_llm_endpoint()

    def _call():
        return _measured_stream_request(client.chat.completions.create,
            model=model or endpoint.model, reasoning_effort='high', thinking='enabled', max_tokens=DEEPSEEK_REASONER_MAX_TOKENS,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,  # Enable streaming for better high-traffic handling
            **({'extra_body': {"thinking": {"type": "enabled"}}} if endpoint.is_deepseek else {}),
        )

    return _retry_on_connection_error(_call, show_message=True)


def json_call_large_with_retry(client, messages):
    """
    Retry logic for large JSON generation using reasoner model.
    
    Strategy:
    1. Try json_call_large() with 32K tokens (default)
    2. If truncated, retry with 64K tokens (max)
    
    Returns:
        str: JSON content, or None if cancelled
    """
    # Helper to check if response is truncated
    def is_truncated(content, finish_reason):
        """Check if response is truncated based on finish_reason or JSON completeness."""
        if finish_reason == "length":
            return True
        if not is_json_complete(content):
            return True
        return False
    
    # Step 1: Try with reasoner model at default (32K)
    content, finish_reason = json_call_large(client, messages, DEEPSEEK_REASONER_DEFAULT_TOKENS)
    if not is_truncated(content, finish_reason):
        return content
    
    # Step 2: Retry with reasoner model at max (64K)
    if finish_reason == "length" or not is_json_complete(content):
        print("  Response truncated at 32K, retrying with 64K tokens...")
    content, finish_reason = json_call_large(client, messages, DEEPSEEK_REASONER_MAX_TOKENS)
    if is_truncated(content, finish_reason):
        raise ValueError(
            f"Response still truncated after retry (64K max). "
            f"Finish reason: {finish_reason}. "
            f"Consider breaking the request into smaller parts."
        )
    
    return content


def json_call_large_with_loading(client, messages, max_tokens=None):
    """
    Wrapper for json_call_large_with_retry that shows loading indicator with timer and supports cancellation.
    
    Note: max_tokens parameter is ignored - retry logic handles token limits automatically.
    """
    loading = LoadingIndicator("Generating (large output)")
    result = [None]
    exception = [None]
    cancelled = [False]
    
    def api_call():
        try:
            result[0] = json_call_large_with_retry(client, messages)
        except KeyboardInterrupt:
            cancelled[0] = True
            exception[0] = KeyboardInterrupt()
        except Exception as e:
            exception[0] = e
    
    loading.start()
    try:
        run_cancellable(api_call)
    except KeyboardInterrupt:
        cancelled[0] = True
        loading.stop()
        print("\nCancelled. Returning to prompt...")
        return None
    
    loading.stop()
    
    if cancelled[0]:
        print("Cancelled. Returning to prompt...")
        return None
    
    if exception[0]:
        if isinstance(exception[0], KeyboardInterrupt):
            print("Cancelled. Returning to prompt...")
            return None
        raise exception[0]
    
    return result[0]


def json_call_reasoner_only_with_loading(client, messages, loading_message="Generating", show_loading=True, logger=None, *, model=None):
    """
    Wrapper for json_call_reasoner_only that shows loading indicator with timer and supports cancellation.
    This is the standard function for all JSON generation in the planner/emitter architecture.
    Includes retry logic for connection errors.
    
    Args:
        client: OpenAI client
        messages: List of message dicts
        loading_message: Custom message for loading indicator
        show_loading: If False, skip the loading indicator (useful for parallel execution)
        logger: Optional ConversationLogger for debug logging (loading start/stop)
    
    Returns:
        str: JSON content, or None if cancelled
    """
    result = [None]
    exception = [None]
    cancelled = [False]
    
    def api_call():
        _, active_stage = current_api_metrics_scope()
        with api_metrics_scope(logger, active_stage or loading_message or 'json_generation'):
            try:
                content, finish_reason = json_call_reasoner_only(
                    client, messages, **({"model": model} if model else {}),
                )
                if finish_reason == "length":
                    raise ValueError("Response truncated at 64K max tokens. Consider breaking the request into smaller parts.")
                result[0] = content
            except KeyboardInterrupt:
                cancelled[0] = True
                exception[0] = KeyboardInterrupt()
            except Exception as e:
                exception[0] = e
    
    loading = None
    if show_loading:
        loading = LoadingIndicator(loading_message)
        if logger:
            logger.log("Loading started: " + loading_message)
        loading.start()
    
    try:
        run_cancellable(api_call)
    except KeyboardInterrupt:
        cancelled[0] = True
        if loading:
            loading.stop()
        if logger:
            logger.log_print("\nCancelled. Returning to prompt...")
        else:
            print("\nCancelled. Returning to prompt...")
        return None
    
    if loading:
        loading.stop()
        if logger:
            logger.log("Loading finished: " + loading_message)
    
    if cancelled[0]:
        if logger:
            logger.log_print("Cancelled. Returning to prompt...")
        else:
            print("Cancelled. Returning to prompt...")
        return None
    
    if exception[0]:
        if isinstance(exception[0], KeyboardInterrupt):
            if logger:
                logger.log_print("Cancelled. Returning to prompt...")
            else:
                print("Cancelled. Returning to prompt...")
            return None
        raise exception[0]
    
    return result[0]


def estimate_output_size(workout_count, exercise_count_per_workout=5):
    """Rough estimate: ~100-200 tokens per exercise, ~50 tokens overhead per workout."""
    estimated = (workout_count * 50) + (workout_count * exercise_count_per_workout * 150)
    return estimated


