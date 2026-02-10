"""OpenAI/DeepSeek API call helpers with retry and loading UX."""

from __future__ import annotations

import json
import random
import threading
import time
import traceback
from typing import Any, Dict, Optional, Tuple

from .constants import (
    DEEPSEEK_CHAT_DEFAULT_TOKENS,
    DEEPSEEK_CHAT_MAX_TOKENS,
    DEEPSEEK_REASONER_DEFAULT_TOKENS,
    DEEPSEEK_REASONER_MAX_TOKENS,
)
from .logging_ui import LoadingIndicator

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

def chat_call(client, messages, tools=None):
    """
    Call deepseek-reasoner model for conversational responses with optional function calling.
    
    Args:
        client: OpenAI client
        messages: List of message dicts
        tools: Optional list of tool definitions for function calling
    
    Returns:
        tuple: (content, tool_calls) where content is the message content (or None) and 
               tool_calls is a list of tool calls (or None)
    """
    kwargs = {
        "model": "deepseek-reasoner",
        "messages": messages
    }
    if tools:
        kwargs["tools"] = tools
    
    resp = client.chat.completions.create(**kwargs)
    message = resp.choices[0].message
    content = message.content
    tool_calls = message.tool_calls if hasattr(message, 'tool_calls') and message.tool_calls else None
    return content, tool_calls


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


def test_connection(client, show_message=True, logger=None):
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
    if show_message or logger:
        _out("Testing connection to DeepSeek API...")
    
    try:
        # Make a minimal API call - just ask for a simple JSON response
        test_messages = [
            {"role": "system", "content": "You are a helpful assistant. Respond with valid JSON only."},
            {"role": "user", "content": 'Respond with {"status": "ok"} as JSON.'}
        ]
        
        # Use streaming mode for better high-traffic handling
        start_time = time.time()
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=test_messages,
            response_format={"type": "json_object"},
            max_tokens=10,
            stream=True  # Enable streaming for better high-traffic handling
        )
        
        content, finish_reason = _collect_streaming_response(stream, start_time)
        
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
        try:
            return func()
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


def _collect_streaming_response(stream, start_time=None):
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


def json_call(client, messages, max_tokens=DEEPSEEK_CHAT_DEFAULT_TOKENS):
    """
    Call deepseek-chat model for JSON generation using streaming mode.
    Streaming mode better handles keep-alive comments during high traffic periods.
    
    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    def _call():
        start_time = time.time()
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            stream=True  # Enable streaming for better high-traffic handling
        )
        return _collect_streaming_response(stream, start_time)
    
    return _retry_on_connection_error(_call, show_message=True)


def chat_call_with_loading(client, messages, tools=None, logger=None):
    """
    Wrapper for chat_call that shows loading indicator with timer and supports cancellation.
    
    Args:
        client: OpenAI client
        messages: List of message dicts
        tools: Optional list of tool definitions for function calling
        logger: Optional ConversationLogger for debug logging (loading start/stop)
    
    Returns:
        tuple: (content, tool_calls) where content is the message content (or None) and 
               tool_calls is a list of tool calls (or None)
    """
    loading = LoadingIndicator("Thinking")
    result = [None]
    exception = [None]
    cancelled = [False]
    
    def api_call():
        try:
            result[0] = chat_call(client, messages, tools)
        except KeyboardInterrupt:
            cancelled[0] = True
            exception[0] = KeyboardInterrupt()
        except Exception as e:
            exception[0] = e
    
    if logger:
        logger.log("Loading started: Thinking")
    loading.start()
    api_thread = threading.Thread(target=api_call, daemon=False)
    api_thread.start()
    
    try:
        api_thread.join()
    except KeyboardInterrupt:
        cancelled[0] = True
        loading.stop()
        if logger:
            logger.log_print("\nCancelled. Returning to prompt...")
        else:
            print("\nCancelled. Returning to prompt...")
        return None, None
    
    loading.stop()
    if logger:
        logger.log("Loading finished: Thinking")
    
    if cancelled[0]:
        if logger:
            logger.log_print("Cancelled. Returning to prompt...")
        else:
            print("Cancelled. Returning to prompt...")
        return None, None
    
    if exception[0]:
        if isinstance(exception[0], KeyboardInterrupt):
            if logger:
                logger.log_print("Cancelled. Returning to prompt...")
            else:
                print("Cancelled. Returning to prompt...")
            return None, None
        raise exception[0]
    
    return result[0]


def json_call_with_retry(client, messages):
    """
    Cascading retry logic for JSON generation.
    
    Strategy:
    1. Try json_call() with 4K tokens (deepseek-chat)
    2. If truncated, retry json_call() with 8K tokens (deepseek-chat max)
    3. If still truncated, fall back to json_call_large() with 32K tokens (deepseek-reasoner)
    4. If still truncated, retry json_call_large() with 64K tokens (deepseek-reasoner max)
    
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
    api_thread = threading.Thread(target=api_call, daemon=False)
    api_thread.start()
    
    try:
        api_thread.join()
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


def json_call_chat_max_with_loading(client, messages, loading_message="Generating", show_loading=True, logger=None):
    """
    Wrapper for json_call that uses deepseek-chat with maximum tokens (8K) from the start.
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
            content, finish_reason = json_call(client, messages, DEEPSEEK_CHAT_MAX_TOKENS)
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
    api_thread = threading.Thread(target=api_call, daemon=False)
    api_thread.start()
    
    try:
        api_thread.join()
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
    Use reasoner model for larger outputs (up to 64K max) using streaming mode.
    Streaming mode better handles keep-alive comments during high traffic periods.
    
    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    def _call():
        start_time = time.time()
        stream = client.chat.completions.create(
            model="deepseek-reasoner",  # 64K max output
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            stream=True  # Enable streaming for better high-traffic handling
        )
        return _collect_streaming_response(stream, start_time)
    
    return _retry_on_connection_error(_call, show_message=True)


def json_call_reasoner_only(client, messages):
    """
    Call deepseek-reasoner model for JSON generation with maximum tokens (64K) using streaming mode.
    This is the standard function for all JSON generation in the planner/emitter architecture.
    Streaming mode better handles keep-alive comments during high traffic periods.
    
    Returns:
        tuple: (content, finish_reason) where finish_reason indicates if response was truncated
    """
    def _call():
        start_time = time.time()
        stream = client.chat.completions.create(
            model="deepseek-reasoner",
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=DEEPSEEK_REASONER_MAX_TOKENS,  # Always use max (64K)
            stream=True  # Enable streaming for better high-traffic handling
        )
        return _collect_streaming_response(stream, start_time)
    
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
    api_thread = threading.Thread(target=api_call, daemon=False)
    api_thread.start()
    
    try:
        api_thread.join()
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


def json_call_reasoner_only_with_loading(client, messages, loading_message="Generating", show_loading=True, logger=None):
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
        try:
            content, finish_reason = json_call_reasoner_only(client, messages)
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
    
    api_thread = threading.Thread(target=api_call, daemon=False)
    api_thread.start()
    
    try:
        api_thread.join()
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


