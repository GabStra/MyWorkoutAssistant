from __future__ import annotations

import json
import copy
import io
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from workout_generator_pkg.constants import EXACT_GENERATION_CONFIRMATION
from workout_generator_pkg.conversation_meta import get_active_conversation_id
from workout_generator_pkg.conversation_store import (
    list_conversations,
    load_active_conversation_record,
    load_conversation_record,
    resolve_conversation_id,
    save_conversation,
    set_active_conversation,
)
from workout_generator_pkg import interactive_shell


@pytest.mark.parametrize("terminal", [True, False])
def test_markdown_renderer_preserves_logs_and_plain_redirected_output(monkeypatch, terminal):
    from rich.console import Console
    from workout_generator_pkg.logging_ui import print_markdown
    output = io.StringIO()
    console = Console(file=output, force_terminal=terminal, color_system=None, width=80)
    pager = []
    monkeypatch.setattr(console, "pager", lambda **kwargs: pager.append(kwargs) or nullcontext())
    monkeypatch.setattr("rich.console.Console", lambda: console)
    logged = []
    logger = SimpleNamespace(log=logged.append, log_print=lambda text: (logged.append(text), output.write(text)))
    markdown = "# Day A\n\n| Exercise | Sets |\n| --- | --- |\n| Squat | 3 |"
    print_markdown(markdown, logger, paged=True)
    assert logged == [f"Assistant> {markdown}"]
    assert "Squat" in output.getvalue()
    assert pager == ([{"styles": True}] if terminal else [])
    if not terminal:
        assert output.getvalue() == f"Assistant> {markdown}"


def test_mid_turn_requirements_intake_drops_stale_draft_tools(monkeypatch, tmp_path):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.api_client import _strict_wire_schema

    equipment, _, _, _ = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    approved = [True]
    monkeypatch.setattr(interactive_shell, 'requirements_approved', lambda *a: True)
    monkeypatch.setattr(interactive_shell, 'pending_reaudit', lambda *a: None)
    monkeypatch.setattr(interactive_shell, 'request_planning_state', lambda *a: {
        'requirementsApproved': approved[0], 'sourceMessages': {}, 'resolvedDecisions': {}})
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    observed = []

    def respond(client, messages, tools, logger, **options):
        names = {tool['function']['name'] for tool in tools}
        observed.append(names)
        if len(observed) == 1:
            assert 'generate_workout' in names
            approved[0] = False
            return None, [FakeToolCall('invalid-update', 'function',
                FakeFunction('set_workout_requirements', '{"invalid":true}'))], None
        assert names == {'set_workout_requirements', 'record_planning_decisions',
                         interactive_shell.ASK_USER_TOOL['function']['name']}
        assert options['require_strict_tool_delivery'] is True
        for tool in tools:
            _strict_wire_schema(tool['function']['parameters'])
        return 'Please correct the requirements update.', None, None

    deps.chat_call_with_loading = respond
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    inputs = iter(['Review the saved workout', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    interactive_shell.main(deps=deps)
    assert len(observed) == 2


def test_view_reopens_latest_assistant_markdown(monkeypatch, tmp_path):
    rendered = []
    monkeypatch.setattr(interactive_shell, "print_markdown", lambda text, logger, paged=False: rendered.append((text, paged)))
    deps = make_shell_deps(tmp_path, chat_results=[("# Workout preview", None)], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ["Plan a workout", "/view", "/exit"])
    assert rendered == [("# Workout preview", False), ("# Workout preview", True)]


def test_saved_turns_render_assistant_markdown_without_changing_history(monkeypatch):
    rendered, plain = [], []
    monkeypatch.setattr(interactive_shell, "print_markdown", lambda text, logger: rendered.append(text))
    messages = [{"role": "user", "content": "# Requirements"},
                {"role": "assistant", "content": "# Day A\n\n| Exercise | Sets |\n| --- | --- |\n| Squat | 3 |"}]
    original = copy.deepcopy(messages)
    interactive_shell._render_turns(messages, SimpleNamespace(log_print=plain.append))
    assert rendered == [messages[1]["content"]]
    assert "# Requirements" in plain
    assert messages == original


def test_unvalidated_repair_text_is_not_shown_before_its_audit(monkeypatch, tmp_path):
    rendered = []
    monkeypatch.setattr(interactive_shell, 'print_markdown', lambda text, logger, paged=False: rendered.append(text))
    call = FakeToolCall('repair', 'function', FakeFunction('audit_workout_plan', '{}'))
    deps = make_shell_deps(tmp_path, chat_results=[('INVALID_REPAIR_PROPOSAL', [call]), ('Please clarify the remaining constraint.', None)],
                           generation_results=[], generation_calls=[])
    deps.handle_function_call = lambda *a, **k: {'result': json.dumps({'passed': False, 'errors': [
        {'code': 'invalid_arguments', 'repair': 'Keep reps inside the allowed range.'}]}), 'should_exit': False, 'generation_result': None}
    run_shell(monkeypatch, deps, ['Repair my draft', '/exit'])
    assert 'INVALID_REPAIR_PROPOSAL' not in rendered
    messages = load_active_conversation_record(str(tmp_path))['messages']
    proposal = next(m for m in messages if m.get('content') == 'INVALID_REPAIR_PROPOSAL')
    assert proposal['unvalidatedProposal']
    outgoing = interactive_shell._messages_for_api(messages)
    assert all('unvalidatedProposal' not in m for m in outgoing)
    labels = []
    interactive_shell._render_turns([proposal], SimpleNamespace(log_print=labels.append))
    assert any('Unvalidated' in line for line in labels)


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    type: str
    function: FakeFunction


class FakeTimeout:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class FakeHttpClient:
    def __init__(self, timeout=None):
        self.timeout = timeout


class FakeHttpxModule:
    Timeout = FakeTimeout
    Client = FakeHttpClient


class FakeOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeLogger:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.lines: list[str] = []
        self.closed = False

    def log(self, line: str) -> None:
        self.lines.append(line)

    def log_print(self, line: str) -> None:
        self.lines.append(line)
        print(line)

    def log_section(self, title: str) -> None:
        self.lines.append(f"--- {title} ---")

    def log_request(self, label: str, content: str) -> None:
        self.lines.append(f"[request] {label}: {content}")

    def log_response(self, label: str, content: str, truncate_at: int = 8000) -> None:
        self.lines.append(f"[response] {label}: {content}")

    def close(self) -> None:
        self.closed = True


def write_progress_file(script_dir: Path, session_id: str, step: int = 3) -> None:
    progress_dir = script_dir / "workouts" / "generation_progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    path = progress_dir / f"progress_2026-05-12_120000_{session_id[:8]}.json"
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "timestamp": "2026-05-12T12:00:00",
                "current_step": step,
                "custom_prompt": "",
                "conversation_hash": "hash",
                "id_manager_state": {},
            }
        ),
        encoding="utf-8",
    )


def test_malformed_tool_arguments_are_reported_without_executing_empty_arguments(tmp_path, monkeypatch):
    invalid = FakeToolCall('malformed', 'function', FakeFunction('set_workout_requirements', '{"sessionsPerWeek":3}}'))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [invalid]), ('Please retry the corrected request.', None)],
                           generation_results=[], generation_calls=[])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py'])
    inputs = iter(['Create a workout', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    feedback = next(json.loads(m['content']) for m in messages if m.get('tool_call_id') == 'malformed')
    assert feedback['errors'][0]['code'] == 'invalid_tool_json'
    assert 'Extra data' in feedback['errors'][0]['message']
    assert 'no arguments were executed' in feedback['errors'][0]['repair']


def make_shell_deps(tmp_path: Path, *, chat_results, generation_results, generation_calls) -> SimpleNamespace:
    chat_iter = iter(chat_results)
    generation_iter = iter(generation_results)

    def chat_call_with_loading(client, api_messages, tools, logger, **options):
        result = next(chat_iter)
        if result[1]:
            # Simulate a model using the current backend-issued requirements ID.
            current = next((json.loads(m['content'].split('\n', 1)[1]).get('requirementsId')
                for m in api_messages if (m.get('content') or '').startswith('Current planning state')), None)
            if current:
                for call in result[1]:
                    if call.function.name == 'audit_workout_plan':
                        args = json.loads(call.function.arguments)
                        args['requirementsId'] = current
                        call.function.arguments = json.dumps(args)
        return (*result, "test reasoning") if len(result) == 2 else result

    def execute_workout_generation(
        client,
        messages,
        custom_prompt="",
        resume_session_id=None,
        provided_equipment=None,
        logger=None,
        script_dir=None,
        deps=None,
        force_use_reasoner=None,
        allow_educated_load_guesses=False,
        training_history=None,
    ):
        generation_calls.append(
            {
                "custom_prompt": custom_prompt,
                "resume_session_id": resume_session_id,
                "message_count": len(messages),
            }
        )
        return next(generation_iter)

    def handle_function_call(*args, **kwargs):
        kwargs["deps"] = SimpleNamespace(execute_workout_generation=execute_workout_generation)
        def review_response(client, request, **options):
            content = ('{"readOnly":true,"reason":"Explanation question only."}'
                       if request[0]['content'].startswith('Classify follow-up conversation') else '{"findings":[]}')
            return content, None, None
        with patch('workout_generator_pkg.plan_review.chat_call', side_effect=review_response):
            return interactive_shell.handle_function_call(*args, **kwargs)

    return SimpleNamespace(
        default_script_dir=lambda: str(tmp_path),
        load_equipment_from_file=lambda path: {},
        load_conversation=interactive_shell.resolve_shell_deps().load_conversation,
        load_active_conversation_record=load_active_conversation_record,
        load_conversation_record=load_conversation_record,
        list_conversations=list_conversations,
        set_active_conversation=set_active_conversation,
        update_conversation_metadata=lambda conversation_id, metadata, script_dir=None: metadata,
        resolve_conversation_id=resolve_conversation_id,
        has_equipment_in_messages=lambda messages: False,
        format_equipment_for_conversation=lambda equipment: "equipment",
        base_system_prompt="base system prompt",
        load_conversation_meta=lambda script_dir=None: {},
        save_conversation_meta=lambda conversation_id, script_dir=None: None,
        get_log_dir=lambda script_dir=None: str(tmp_path / "logs"),
        ConversationLogger=FakeLogger,
        chat_call_with_loading=chat_call_with_loading,
        generate_workout_tool={"type": "function", "function": {"name": "generate_workout",
            "parameters": {"type": "object", "properties": {}}}},
        handle_function_call=handle_function_call,
        execute_workout_generation=execute_workout_generation,
        save_conversation=save_conversation,
        list_available_progress=interactive_shell.resolve_shell_deps().list_available_progress,
        delete_progress_file=interactive_shell.resolve_shell_deps().delete_progress_file,
        conversation_file=str(tmp_path / "conversation_history.json"),
        OpenAI=FakeOpenAI,
        httpx=FakeHttpxModule,
    )


def run_shell(monkeypatch: pytest.MonkeyPatch, deps: SimpleNamespace, inputs: list[str]) -> None:
    values = iter(inputs)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(values))
    monkeypatch.setattr("sys.argv", ["workout_generator.py"])
    interactive_shell.main(deps=deps)


@pytest.mark.parametrize("stage", ["prompt", "multiline", "tool"])
def test_ctrl_c_returns_to_prompt_without_losing_tool_history(monkeypatch, tmp_path, stage):
    results = [("Looking up exercises", [FakeToolCall("interrupted", "function", FakeFunction("search_exercise_library", "{}"))])]
    deps = make_shell_deps(tmp_path, chat_results=results, generation_results=[], generation_calls=[])

    def interrupt_tool(*args, **kwargs):
        raise KeyboardInterrupt

    deps.handle_function_call = interrupt_tool
    inputs = iter({
        "prompt": [KeyboardInterrupt(), "/exit"],
        "multiline": ["/ml", "partial requirements", KeyboardInterrupt(), "/exit"],
        "tool": ["Find exercises", "/exit"],
    }[stage])

    def input_value(prompt=""):
        value = next(inputs)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", input_value)
    monkeypatch.setattr("sys.argv", ["workout_generator.py"])
    interactive_shell.main(deps=deps)
    record = load_active_conversation_record(str(tmp_path))
    if stage == "tool":
        assert any(message.get("content") == "Find exercises" for message in record["messages"])
        result = next(message for message in record["messages"] if message.get("tool_call_id") == "interrupted")
        assert "cancelled by the user" in result["content"]


def test_shell_combines_independent_search_calls_and_preserves_tool_responses(monkeypatch, tmp_path):
    calls = []
    def search_group(searches, equipment, client, messages, progress=None, on_result=None):
        calls.append(searches)
        progress(0, 2)
        progress(2, 2)
        results = {call_id: {"results": []} for call_id, _ in searches}
        for call_id, payload in results.items():
            on_result(call_id, payload)
        return results
    monkeypatch.setattr(interactive_shell, "execute_library_searches", search_group)
    tools = [FakeToolCall(name, "function", FakeFunction("search_exercise_library", json.dumps({"queries": [name]})))
             for name in ("push", "pull")]
    from test_workout_generator_planning_tools import planning_case
    requirements = planning_case()[1]
    initial = [FakeToolCall('requirements', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements)))]
    deps = make_shell_deps(tmp_path, chat_results=[(None, initial), (None, tools), ("Ready to plan.", None)],
                           generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ["Plan full body", "CONFIRM REQUIREMENTS", "/exit"])
    assert len(calls) == 1 and len(calls[0]) == 2
    record = load_active_conversation_record(str(tmp_path))
    results = [m for m in record["messages"] if m.get("role") == "tool" and m.get("tool_call_id") != "requirements"]
    assert [m["tool_call_id"] for m in results] == ["push", "pull"]
    assert all(json.loads(m["content"]) == {"results": []} for m in results)


@pytest.mark.parametrize('batch_kind', ['mixed', 'combined_search'])
def test_completed_lookup_is_saved_before_another_lookup_is_cancelled(monkeypatch, tmp_path, batch_kind):
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, _ = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    checkpointed = threading.Event()
    payload = {'results': []}
    # Isolate batch cancellation; construction-stage permissions have separate coverage.
    monkeypatch.setattr(interactive_shell, 'construction_tool_failure', lambda *args: None)

    def search(searches, equipment, client, messages, progress=None, on_result=None):
        if batch_kind == 'combined_search':
            on_result('finished', payload)
            assert checkpointed.is_set()
            raise KeyboardInterrupt
        return {'finished': payload}

    def cancelled_metadata(*args):
        assert checkpointed.wait(3), 'A finished lookup must be persisted while the batch is still running.'
        raise KeyboardInterrupt

    target = interactive_shell if batch_kind == 'combined_search' else 'workout_generator_pkg.lookup_batch'
    if isinstance(target, str):
        monkeypatch.setattr(target + '.execute_library_searches', search)
    else:
        monkeypatch.setattr(target, 'execute_library_searches', search)
    monkeypatch.setattr('workout_generator_pkg.lookup_batch.get_exercise_candidates', cancelled_metadata)
    first = FakeToolCall('finished', 'function', FakeFunction('search_exercise_library', json.dumps({'queries': ['push']})))
    second_name = 'search_exercise_library' if batch_kind == 'combined_search' else 'get_exercise_candidates'
    second_args = {'queries': ['pull']} if batch_kind == 'combined_search' else {'definition_ids': ['LIBRARY_0']}
    second = FakeToolCall('unfinished', 'function', FakeFunction(second_name, json.dumps(second_args)))
    initial = FakeToolCall('requirements', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements)))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [initial]), (None, [first, second])],
                           generation_results=[], generation_calls=[])
    save = deps.save_conversation

    def save_and_check(messages, *args, **kwargs):
        result = save(messages, *args, **kwargs)
        if any(m.get('tool_call_id') == 'finished' and m.get('content') == json.dumps(payload)
               for m in messages):
            checkpointed.set()
        return result

    deps.save_conversation = save_and_check
    inputs = iter(['Plan a workout', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    saved = load_active_conversation_record(str(tmp_path))['messages']
    finished = [m for m in saved if m.get('tool_call_id') == 'finished']
    unfinished = [m for m in saved if m.get('tool_call_id') == 'unfinished']
    assert len(finished) == len(unfinished) == 1
    assert json.loads(finished[0]['content']) == payload
    assert 'cancelled by the user' in unfinished[0]['content']
    assert [m['tool_call_id'] for m in saved if m.get('tool_call_id') in ('finished', 'unfinished')] == ['finished', 'unfinished']


def test_tool_results_are_checkpointed_before_the_next_tool_without_mutating_pending_calls(monkeypatch, tmp_path):
    tools = [FakeToolCall(key, 'function', FakeFunction('get_training_evidence', '{}')) for key in ('first', 'second')]
    deps = make_shell_deps(tmp_path, chat_results=[(None, tools), ('Done', None)], generation_results=[], generation_calls=[])
    calls = []
    def complete(client, messages, name, arguments, *args, **kwargs):
        key = tools[len(calls)].id
        if key == 'second':
            saved = load_active_conversation_record(str(tmp_path))['messages']
            assert json.loads(next(m['content'] for m in saved if m.get('tool_call_id') == 'first')) == {'completed': 'first'}
            assert sum(m.get('tool_call_id') == 'second' for m in messages) == 1
            assert next(m['content'] for m in messages if m.get('tool_call_id') == 'second').startswith('Tool call started')
        calls.append(key)
        return {'result': json.dumps({'completed': key}), 'should_exit': False, 'generation_result': None}
    deps.handle_function_call = complete
    run_shell(monkeypatch, deps, ['Retrieve history', '/exit'])
    saved = load_active_conversation_record(str(tmp_path))['messages']
    for key in calls:
        responses = [m for m in saved if m.get('tool_call_id') == key]
        assert len(responses) == 1 and json.loads(responses[0]['content']) == {'completed': key}


def test_internal_failure_receipt_keeps_completed_audit_checkpoint_without_approving_it():
    from workout_generator_pkg.planning_tools import planning_tool_failure
    checkpoint = {'passed': False, 'reviewPending': True,
        'submittedDraft': {'requirementsId': 'REQ_1', 'workouts': [{'name': 'Saved session'}]},
        'currentDraftId': 'REVISION_50', 'libraryFingerprint': 'library-hash',
        'recipeQualification': {'inputHash': 'qualified', 'contracts': [{'definition_id': 'LIBRARY_1'}]},
        'coordinatedCandidatePending': True, 'preview': 'Must not be shown.', 'planIndex': {'hidden': True},
        'errors': [{'code': 'independent_review_pending'}]}

    failure = interactive_shell._merge_completed_tool_checkpoint(
        planning_tool_failure('audit_workout_plan', RuntimeError('solver receipt UnboundLocalError')),
        checkpoint)

    assert failure['submittedDraft'] == checkpoint['submittedDraft']
    assert failure['recipeQualification'] == checkpoint['recipeQualification']
    assert failure['coordinatedCandidatePending'] and failure['checkpointPreserved']
    assert failure['passed'] is False and failure['errors'][0]['code'] == 'tool_execution_failed'
    assert failure['errors'][0]['owner'] == 'generator'
    assert 'preview' not in failure and 'planIndex' not in failure


def test_draft_bound_tool_schemas_advertise_only_the_exact_current_revision():
    from workout_generator_pkg.planning_tools import AUDIT_WORKOUT_PLAN_TOOL, PREPARE_WORKOUT_SESSION_TOOL, REPAIR_WORKOUT_PLAN_TOOL
    from workout_generator_pkg.session_drafting import PREPARE_WORKOUT_SESSIONS_TOOL

    for original in (AUDIT_WORKOUT_PLAN_TOOL, PREPARE_WORKOUT_SESSION_TOOL,
                    PREPARE_WORKOUT_SESSIONS_TOOL, REPAIR_WORKOUT_PLAN_TOOL):
        bound = interactive_shell._bind_current_draft_id(original, 'REVISION_1')
        def find_base(schema):
            if isinstance(schema, dict):
                for name, value in schema.get('properties', {}).items():
                    if name == 'baseDraftId':
                        return value
                    result = find_base(value)
                    if result:
                        return result
                for key in ('oneOf', 'anyOf', 'allOf'):
                    for value in schema.get(key, []):
                        result = find_base(value)
                        if result:
                            return result
                if isinstance(schema.get('items'), dict):
                    return find_base(schema['items'])
            return None
        base_schema = find_base(bound['function']['parameters'])
        assert base_schema and base_schema['enum'] == ['REVISION_1']
        assert 'exactly REVISION_1' in bound['function']['description']

    initial = interactive_shell._bind_current_draft_id(PREPARE_WORKOUT_SESSIONS_TOOL, None)
    assert initial['function']['parameters']['properties']['baseDraftId']['enum'] == [None]
    assert 'use null exactly' in initial['function']['parameters']['properties']['baseDraftId']['description']


def test_candidate_menu_expansion_receipt_requires_materialized_audited_candidate():
    task = {'sourceBaseDraftId': 'REVISION_4', 'sourceProblemFingerprint': 'source-problem',
        'sourceMenuFingerprint': 'source-menu', 'requirementsId': 'REQ', 'libraryFingerprint': 'LIB',
        'historyFingerprint': 'HIST', 'resolvedDecisions': {}, 'blockers': [{'coverageKey': 'horizontal_pull_weekly'}]}
    rejected = {'passed': False, 'currentDraftId': 'REVISION_4',
        'errors': [{'code': 'invalid_arguments'}]}
    assert interactive_shell._candidate_menu_expansion_audit_marker(task, rejected) is None
    terminal_without_candidate = interactive_shell._candidate_menu_expansion_attempt(task)
    assert terminal_without_candidate['attempted'] and not terminal_without_candidate['auditedCandidate']
    assert terminal_without_candidate['blockers'] == task['blockers']
    assert 'resultingProblemFingerprint' not in terminal_without_candidate

    candidate = {'requirementsId': 'REQ', 'workouts': [{'exercises': [{'definition_id': 'row'}]}]}
    audited = {'passed': False, 'currentDraftId': 'REVISION_5', 'submittedDraft': candidate,
        'coordinatedJointPlanning': {'status': 'infeasible', 'problemFingerprint': 'result-problem'}}
    assert interactive_shell._candidate_menu_expansion_audit_marker(
        task, audited, {'patch': []}) is None
    marker = interactive_shell._candidate_menu_expansion_audit_marker(task, audited)
    assert marker['attempted'] and marker['auditedCandidate']
    assert marker['sourceProblemFingerprint'] == 'source-problem'
    assert marker['blockers'] == task['blockers']
    assert marker['resultingProblemFingerprint'] == 'result-problem'

    unproven = {**audited, 'coordinatedJointPlanning': {'status': 'infeasible'}}
    marker = interactive_shell._candidate_menu_expansion_audit_marker(task, unproven)
    assert marker['auditedCandidate'] and marker['resultingProblemFingerprint'] is None


def test_candidate_menu_expansion_defers_user_tradeoff_and_alternative_tools():
    tools = [{'function': {'name': name}} for name in (
        'ask_user', 'propose_workout_alternatives', 'accept_workout_alternative',
        'search_exercise_library', 'audit_workout_plan')]
    selected = interactive_shell._candidate_menu_expansion_tools(tools, {'sourceProblemFingerprint': 'p'})
    assert [tool['function']['name'] for tool in selected] == [
        'search_exercise_library', 'audit_workout_plan']
    assert interactive_shell._candidate_menu_expansion_tools(tools, None) == tools


def test_messages_for_api_preserves_compact_candidate_menu_expansion_proof():
    from workout_generator_pkg.joint_planning import candidate_menu_fingerprint

    workouts = [{'day': 'Day 1', 'exercises': [{'definition_id': 'row'}]}]
    marker = {'attempted': True, 'auditedCandidate': True, 'sourceMenuFingerprint': 'source-menu'}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-1', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-1', 'content': json.dumps({
            'passed': False, 'currentDraftId': 'REVISION_2', 'submittedDraft': {'workouts': workouts},
            'candidateMenuExpansion': marker, 'coordinatedJointPlanning': {'problemFingerprint': 'result-problem'},
            'audit': {'targets': {}, 'workouts': []}, 'review': {'findings': []}})},
    ]

    compacted = interactive_shell._messages_for_api(messages)
    receipt = json.loads(compacted[1]['content'])
    assert receipt['candidateMenuExpansion'] == marker
    assert receipt['candidateMenuFingerprint'] == candidate_menu_fingerprint(workouts)
    assert 'submittedDraft' not in receipt


def test_internal_lookup_failure_pauses_once_and_keeps_completed_parallel_search(monkeypatch, tmp_path, capsys):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import planning_tool_failure
    requirements = planning_case()[1]
    failure = planning_tool_failure('get_training_evidence', RuntimeError('Invalid backend similarity score'))
    success = {'results': [{'query': 'quad isolation', 'exercises': []}], 'errors': []}
    batch = [FakeToolCall('history', 'function', FakeFunction('get_training_evidence', '{"definition_ids":["LIBRARY_0"]}')),
             FakeToolCall('search', 'function', FakeFunction('search_exercise_library', '{"queries":["quad isolation"]}'))]
    initial = FakeToolCall('requirements', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements)))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [initial]), (None, batch)],
                           generation_results=[], generation_calls=[])
    requests = []
    chat = deps.chat_call_with_loading

    def track_chat(*args, **kwargs):
        requests.append(1)
        return chat(*args, **kwargs)

    def completed_batch(*args, on_result=None, **kwargs):
        on_result('history', failure)
        on_result('search', success)
        return {'history': failure, 'search': success}

    deps.chat_call_with_loading = track_chat
    monkeypatch.setattr(interactive_shell, 'execute_lookup_batch', completed_batch)
    run_shell(monkeypatch, deps, ['Plan a workout', 'CONFIRM REQUIREMENTS', '/exit'])
    output = capsys.readouterr().out
    assert len(requests) == 2
    assert 'get_training_evidence failed internally: Invalid backend similarity score' in output
    assert 'Skipped search_exercise_library' not in output
    messages = load_active_conversation_record(str(tmp_path))['messages']
    results = [m for m in messages if m.get('tool_call_id') == 'search']
    assert len(results) == 1 and json.loads(results[0]['content']) == success
    assert failure['executionFailure'] and failure['errors'][0]['code'] == 'tool_execution_failed'
    assert 'Do not edit the workout' in failure['instruction']


@pytest.mark.parametrize('failure', ['serialization', 'replace'])
def test_failed_checkpoint_preserves_previous_conversation_file(monkeypatch, tmp_path, failure):
    from workout_generator_pkg import json_io
    identifier = save_conversation([{'role': 'user', 'content': 'Keep this checkpoint'}], script_dir=str(tmp_path))
    path = tmp_path / 'workouts' / 'conversation_sessions' / identifier / 'messages.json'
    before = path.read_bytes()
    if failure == 'replace':
        def fail_replace(*args):
            raise OSError('Simulated interrupted publish')
        monkeypatch.setattr(json_io.os, 'replace', fail_replace)
        value = [{'role': 'user', 'content': 'New checkpoint'}]
        expected_error = OSError
    else:
        value = [{'role': 'user', 'content': object()}]
        expected_error = TypeError
    with pytest.raises(expected_error):
        save_conversation(value, conversation_id=identifier, script_dir=str(tmp_path))
    assert path.read_bytes() == before
    assert not list(path.parent.glob('.messages.json.*.tmp'))


def test_checkpoint_retries_transient_permission_failure_without_rewriting_model_work(monkeypatch, tmp_path):
    from workout_generator_pkg import json_io
    path = tmp_path / 'messages.json'
    json_io.write_json_atomic(path, ['old'])
    replace = json_io.os.replace
    attempts = []
    def locked_once(source, destination):
        attempts.append(source)
        if len(attempts) == 1:
            raise PermissionError('Reader briefly holds destination')
        return replace(source, destination)
    monkeypatch.setattr(json_io.os, 'replace', locked_once)
    monkeypatch.setattr(json_io.time, 'sleep', lambda seconds: None)
    json_io.write_json_atomic(path, ['completed response'])
    assert json.loads(path.read_text()) == ['completed response']
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    monkeypatch.setattr(json_io.os, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('Persistent denial')))
    with pytest.raises(PermissionError):
        json_io.write_json_atomic(path, ['unsaved'])
    assert json.loads(path.read_text()) == ['completed response']


@pytest.mark.parametrize('first_tool, code', [
    ('audit_workout_plan', 'review_execution_failed'),
    ('record_planning_decisions', 'decision_review_failed'),
    ('record_planning_decisions', 'decision_source_finding'),
])
def test_review_output_failure_pauses_immediately_and_preserves_feedback(monkeypatch, tmp_path, capsys, first_tool, code):
    failure = {'passed': False, 'errors': [{'code': code,
               'message': 'Reviewer returned a schema instead of findings.'}]}
    tool = FakeToolCall('first', 'function', FakeFunction(first_tool, '{}'))
    remaining = [FakeToolCall(key, 'function', FakeFunction(name, '{}')) for key, name in (
        ('requirements', 'set_workout_requirements'), ('search1', 'search_exercise_library'), ('search2', 'search_exercise_library'))]
    deps = make_shell_deps(tmp_path, chat_results=[(None, [tool, *remaining]), ('The choice needs repair.', None)],
                           generation_results=[], generation_calls=[])
    executed = []
    def handle(*args, **kwargs):
        executed.append(args[2])
        return {'result': json.dumps(failure), 'should_exit': False, 'generation_result': None}
    deps.handle_function_call = handle
    monkeypatch.setattr(interactive_shell, 'execute_library_searches', lambda *a, **k: pytest.fail('Dependent searches must not start'))
    original_chat = deps.chat_call_with_loading
    calls = []
    def chat(*args, **kwargs):
        calls.append(1)
        return original_chat(*args, **kwargs)
    deps.chat_call_with_loading = chat
    run_shell(monkeypatch, deps, ['Repair the draft', '/exit'])
    execution_failure = code != 'decision_source_finding'
    assert len(calls) == (1 if execution_failure else 2) and executed == [first_tool]
    output = capsys.readouterr().out
    label = 'Independent review' if first_tool == 'audit_workout_plan' else 'Planning choice review'
    assert (f'Planning paused: {label} failed:' in output) is execution_failure
    assert 'Skipped set_workout_requirements' in output
    saved = load_active_conversation_record(str(tmp_path))['messages']
    assert json.loads(next(m['content'] for m in saved if m.get('tool_call_id') == 'first')) == failure
    skipped = [json.loads(m['content']) for m in saved if m.get('tool_call_id') in ('requirements', 'search1', 'search2')]
    assert len(skipped) == 3 and all(result['skipped'] and not result['passed'] for result in skipped)
    from workout_generator_pkg.planning_tools import _latest_result
    assert _latest_result(saved, 'set_workout_requirements') == (-1, {})


@pytest.mark.parametrize('attempt_full_rewrite', [False, True])
def test_shell_repairs_one_rep_with_patch_then_previews_and_exports(monkeypatch, tmp_path, capsys, attempt_full_rewrite):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import confirmed_draft
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [
        {'workSetIndex': i, 'reps': reps, 'additionalWeight': 0} for i, reps in enumerate([10, 9, 8, 8, 7])]
    prescriptions = copy.deepcopy(draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'])
    prescriptions[4]['reps'] = 8
    patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'targetSetPrescriptions': prescriptions}}]}}
    def tool(name, arguments, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(arguments)))])
    generated = []
    responses = [tool('set_workout_requirements', requirements, 'requirements'),
                 tool('audit_workout_plan', draft, 'initial')]
    if attempt_full_rewrite:
        replacement = copy.deepcopy(draft)
        replacement['name'] = 'UNREQUESTED REWRITE'
        responses.append(tool('audit_workout_plan', replacement, 'rewrite'))
    responses.extend([tool('audit_workout_plan', patch, 'repair'), tool('generate_workout', {}, 'export')])
    deps = make_shell_deps(tmp_path, chat_results=responses,
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    original_chat = deps.chat_call_with_loading
    requests = []
    def capture(client, messages, tools, logger, **options):
        requests.append((copy.deepcopy(tools), options))
        return original_chat(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = capture
    inputs = iter(['Plan 5-6 chest sets', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    snapshot = confirmed_draft(messages, equipment)
    assert snapshot['currentDraftId'] == 'REVISION_1' and len(generated) == 1
    assert snapshot['submittedDraft']['name'] == draft['name']
    assert [s['reps'] for s in snapshot['planIndex']['exercises'][0]['targetSetPrescriptions']] == [10, 9, 8, 8, 8]
    assert sum(bool(m.get('canonicalDraftPreview')) for m in messages) == 1
    stored_patch = next(c['function'] for m in messages for c in m.get('tool_calls', []) if c['id'] == 'repair')
    assert 'workouts' not in json.loads(stored_patch['arguments'])
    repair_tools, repair_options = requests[2]
    assert repair_options == {'reasoning_effort': 'low', 'activity': 'Repairing draft', 'max_tokens': 16384, 'timeout': None}
    schema = next(t['function']['parameters'] for t in repair_tools if t.get('function', {}).get('name') == 'audit_workout_plan')
    assert 'edits' in schema['required'] and 'workouts' not in schema['properties']
    assert requests[1][1] == {'reasoning_effort': 'low', 'activity': 'Drafting session', 'max_tokens': 16384, 'timeout': None}
    assert requests[-1][1] == {'reasoning_effort': 'low', 'activity': 'Repairing draft', 'max_tokens': 16384, 'timeout': None}
    if attempt_full_rewrite:
        failure = next(json.loads(m['content']) for m in messages if m.get('tool_call_id') == 'rewrite')
        assert failure['errors'][0]['code'] == 'repair_edit_contract_required'
        assert 'submittedDraft' not in failure
    output = capsys.readouterr().out
    assert 'outside minReps' not in output


@pytest.mark.parametrize('stale_review', [False, True])
@pytest.mark.parametrize('numbered_choice', [False, True])
def test_exact_confirmation_routes_directly_to_guarded_export(monkeypatch, tmp_path, stale_review, numbered_choice):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    calls = [FakeToolCall('requirements', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements))),
             FakeToolCall('draft', 'function', FakeFunction('audit_workout_plan', json.dumps(draft)))]
    generated, model_calls = [], []
    deps = make_shell_deps(tmp_path, chat_results=[(None, [calls[0]]), (None, [calls[1]]), ('The saved review needs refreshing.', None)],
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    chat, handle = deps.chat_call_with_loading, deps.handle_function_call

    def count_chat(*args, **kwargs):
        model_calls.append(1)
        return chat(*args, **kwargs)

    def handle_with_review_change(client, messages, name, *args, **kwargs):
        if stale_review and name == 'generate_workout':
            result = next(m for m in reversed(messages) if m.get('tool_call_id') == 'draft')
            snapshot = json.loads(result['content'])
            snapshot['review']['version'] = REVIEW_VERSION - 1
            result['content'] = json.dumps(snapshot)
        return handle(client, messages, name, *args, **kwargs)

    deps.chat_call_with_loading, deps.handle_function_call = count_chat, handle_with_review_change
    inputs = iter(['Plan 5-6 chest sets', '1' if numbered_choice else 'CONFIRM REQUIREMENTS',
                   '1' if numbered_choice else 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    assert len(generated) == (0 if stale_review else 1)
    assert len(model_calls) == 2
    saved = load_active_conversation_record(str(tmp_path))['messages']
    confirmations = [c for m in saved for c in m.get('tool_calls', []) if c['id'].startswith('confirm_')]
    assert len(confirmations) == 1 and confirmations[0]['function']['name'] == 'generate_workout'
    if stale_review:
        assert any(c['id'].startswith('reaudit_') for m in saved for c in m.get('tool_calls', []))
        assert sum(bool(m.get('canonicalDraftPreview')) for m in saved) == 2


def test_generate_with_instructions_enters_planning_instead_of_exporting(monkeypatch, tmp_path):
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, arguments, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(arguments)))])
    calls = []
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'requirements'),
        tool('audit_workout_plan', draft, 'draft'),
        ('I need to revise the draft to avoid push-ups.', None)], generation_results=[], generation_calls=calls)
    inputs = iter(['Plan 5-6 chest sets', 'CONFIRM REQUIREMENTS', '/generate Avoid push-ups', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert not calls
    assert any(m.get('role') == 'user' and m.get('content') == 'Avoid push-ups' for m in messages)


def test_passing_automatic_review_returns_to_pending_followup_before_preview(monkeypatch, tmp_path, capsys):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from test_workout_generator_planner_context import _tool
    from workout_generator_pkg.planning_tools import audit_workout_plan, confirmed_draft
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.planning_tools import _latest_result
    equipment, requirements, stored, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    messages = requirement_messages(stored)
    initial_audit = audit_workout_plan(draft, equipment, messages)
    initial_audit['reviewVersion'] = REVIEW_VERSION
    initial_audit['review'] = {'version': REVIEW_VERSION, 'findings': []}
    _tool(messages, 'audit_workout_plan', draft, initial_audit, 'initial')
    messages.extend([
        {'role': 'assistant', 'content': initial_audit['preview'],
         'canonicalDraftPreview': initial_audit['draftId']},
        {'role': 'user', 'content': 'CONFIRM GENERATE'},
        {'role': 'user', 'content': 'Review the saved draft and explain whether repairs are needed.'},
    ])
    conversation_id = save_conversation(messages, script_dir=str(tmp_path), migrate=False)
    deps = make_shell_deps(tmp_path, chat_results=[
        ('The saved review passed; the prescriptions need no correction.', None)],
        generation_results=[], generation_calls=[])
    original_chat = deps.chat_call_with_loading
    requests = []
    def capture(client, messages, tools, logger, **options):
        requests.append(copy.deepcopy(messages))
        return original_chat(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = capture
    original_pending = interactive_shell.pending_reaudit
    forced = False
    def pending_reaudit(state, user_input):
        nonlocal forced
        if user_input == '/continue' and not forced:
            forced = True
            return {'requirementsId': state['requirementsId'], 'baseDraftId': state['currentDraftId'], 'patch': []}
        return original_pending(state, user_input)
    monkeypatch.setattr(interactive_shell, 'pending_reaudit', pending_reaudit)
    rendered = []
    monkeypatch.setattr(interactive_shell, 'print_markdown', lambda text, logger, paged=False: rendered.append(text))
    inputs = iter([f'/resume-conversation {conversation_id}', '/continue', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert len(requests) == 1
    assert any(c['id'].startswith('reaudit_') for m in messages for c in m.get('tool_calls', []))
    assert sum(bool(m.get('canonicalDraftPreview')) for m in messages) == 2
    latest_audit = _latest_result(messages, 'audit_workout_plan')[1]
    assert latest_audit['passed'] is True
    assert messages[-1].get('canonicalDraftPreview') == latest_audit['draftId']
    assert messages[-1]['content'] == latest_audit['preview']
    assert rendered[-1] == latest_audit['preview']
    with pytest.raises(ValueError, match='fresh CONFIRM GENERATE'):
        confirmed_draft(messages, equipment, require_confirmation=True)
    messages.append({'role': 'user', 'content': 'CONFIRM GENERATE'})
    assert confirmed_draft(messages, equipment, require_confirmation=True)['draftId'] == latest_audit['draftId']
    assert 'returning to your pending request' in capsys.readouterr().out


def test_continue_retries_only_saved_requirements_source_review_without_reextracting(monkeypatch, tmp_path):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.planning_tools import requirements_approved, set_workout_requirements

    equipment, arguments, _, _ = planning_case()
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]
    candidate = set_workout_requirements(arguments, messages, equipment)
    failure = 'TruncatedResponseError: source review exhausted its reasoning budget before emitting a result.'
    candidate.update(sourceReview={'version': plan_review.REQUIREMENTS_REVIEW_VERSION,
                                   'inputHash': 'saved-failed-review', 'passed': False,
                                   'findings': [], 'failure': failure, 'instructionBoundary': 0},
                     passed=False,
                     errors=[{'code': 'requirements_review_failed', 'message': failure,
                              'repair': 'Retry the saved source review explicitly.'}],
                     instruction='The source review failed; requirements remain unchanged.')
    tool_arguments = copy.deepcopy(arguments)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'failed-requirements', 'type': 'function',
            'function': {'name': 'set_workout_requirements', 'arguments': json.dumps(tool_arguments)}}]},
        {'role': 'tool', 'tool_call_id': 'failed-requirements', 'content': json.dumps(candidate)},
        {'role': 'assistant', 'content': 'The source review failed. Type /continue to retry explicitly.'},
        {'role': 'user', 'content': '/continue'},
        {'role': 'assistant', 'content': 'Updating requirements. The prior review can be tried again with /continue.'},
    ])
    conversation_id = save_conversation(messages, script_dir=str(tmp_path), migrate=False)
    calls = []

    def review_again(_client, request, **options):
        calls.append((copy.deepcopy(request), options))
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, '_review_call', review_again)
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    deps.load_equipment_from_file = lambda _path: equipment
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library)])
    rendered = []
    monkeypatch.setattr(interactive_shell, 'print_markdown', lambda text, logger, paged=False: rendered.append(text))
    inputs = iter([f'/resume-conversation {conversation_id}', '/continue', '/exit'])

    interactive_shell.main(deps=deps)

    saved = load_active_conversation_record(str(tmp_path))['messages']
    requirement_calls = [call for message in saved for call in message.get('tool_calls', [])
                         if call.get('function', {}).get('name') == 'set_workout_requirements']
    requirement_results = [json.loads(message['content']) for message in saved
                           if message.get('role') == 'tool' and message.get('tool_call_id') in
                           {call['id'] for message in saved for call in message.get('tool_calls', [])
                            if call.get('function', {}).get('name') == 'set_workout_requirements'}]
    assert len(calls) == 1  # The planner LLM was not asked to interpret /continue.
    assert len(requirement_calls) == 2
    assert json.loads(requirement_calls[-1]['function']['arguments']) == tool_arguments
    assert len(requirement_results) == 2
    assert requirement_results[-1]['requirementsId'] == candidate['requirementsId']
    assert requirement_results[-1]['requirements'] == candidate['requirements']
    assert requirement_results[-1].get('resolvedDecisions', {}) == candidate.get('resolvedDecisions', {})
    assert requirement_results[-1]['passed'] is True
    assert not requirements_approved(saved)
    assert rendered[-1] == requirement_results[-1]['requirementsPreview']
    assert any(message.get('canonicalRequirementsPreview') == candidate['requirementsId']
               for message in saved)


def test_continue_does_not_retry_semantic_requirements_findings(monkeypatch, tmp_path):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, arguments, _, _ = planning_case()
    candidate = set_workout_requirements(arguments, [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}], equipment)
    candidate.update(sourceReview={'version': plan_review.REQUIREMENTS_REVIEW_VERSION,
                                   'passed': False, 'findings': [{'severity': 'blocking'}]},
                     passed=False,
                     errors=[{'code': 'requirement_source_finding', 'message': 'Clarify a genuine ambiguity.'}])
    messages = [
        {'role': 'user', 'content': 'Plan 5-6 chest sets.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'semantic-requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': 'semantic-requirements', 'content': json.dumps(candidate)},
        {'role': 'user', 'content': '/continue'},
    ]
    assert interactive_shell._requirements_review_retry_arguments(messages, '/continue') is None


def test_requirements_reapproval_repairs_saved_draft_against_current_revision(monkeypatch, tmp_path, capsys):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import confirmed_draft
    monkeypatch.setattr(interactive_shell, 'auto_allocate_workout', lambda result, *args, **kwargs: result)
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    def tool(name, arguments, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(arguments)))])
    repair = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'numWorkSets': 5}}]}}
    generated = []
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'initial-requirements'),
        tool('audit_workout_plan', draft, 'initial-draft'), ('The draft is saved.', None),
        tool('set_workout_requirements', requirements, 'refreshed-requirements'),
        tool('audit_workout_plan', repair, 'repair'), tool('generate_workout', {}, 'export')],
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    original_chat = deps.chat_call_with_loading
    calls = []
    def capture(client, messages, tools, logger, **options):
        calls.append((copy.deepcopy(messages), options))
        return original_chat(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = capture
    inputs = iter(['Plan 5-6 chest sets', 'CONFIRM REQUIREMENTS', 'Refresh the unchanged requirements',
                   'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    repair_call = next(c for m in messages for c in m.get('tool_calls', [])
                       if c['function']['name'] == 'audit_workout_plan'
                       and json.loads(c['function']['arguments']).get('edits'))
    repair_args = json.loads(repair_call['function']['arguments'])
    assert repair_args['baseDraftId'] == 'REVISION_0' and 'patch' not in repair_args
    assert not any(c['id'].startswith('reaudit_') for m in messages for c in m.get('tool_calls', []))
    assert confirmed_draft(messages, equipment)['currentDraftId'] == 'REVISION_1' and len(generated) == 1
    assert 'stale_draft_patch' not in json.dumps(messages)
    capsys.readouterr()


@pytest.mark.parametrize('metadata_retry', [False, True])
def test_cli_routes_assessed_model_patch_through_coordinated_repair(monkeypatch, tmp_path, metadata_retry):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import library_fingerprint
    from workout_generator_pkg.review_assessment import VERSION as ASSESSMENT_VERSION

    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, arguments, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(arguments)))])

    assessment = {'version': ASSESSMENT_VERSION, 'inputHash': 'fixture-review-hash',
        'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                    'repairDimensions': ['guidance'],
                    'reason': 'Correct the assessed progression instruction.',
                    'errorKind': 'none', 'evidencePaths': []}],
        'repairPlan': 'Repair the assessed issue in the owning structured field.'}
    finding = {'code': 'independent_review_finding', 'severity': 'warning', 'basis': 'uncertainty',
        'path': '/workouts/0/exercises/0/placementNotes',
        'draftPath': '/workouts/0/exercises/0/placementNotes', 'reviewScope': 'evidence',
        'message': 'The progression route needs a clearer instruction.',
        'repair': 'Update the exercise guidance.', 'action': 'repair', 'evidencePaths': []}
    initial_result = {'passed': False, 'requirementsId': draft['requirementsId'],
        'currentDraftId': 'REVISION_0', 'submittedDraft': copy.deepcopy(draft),
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'audit': {'errors': []}, 'errors': [finding],
        'review': {'findings': [finding], 'assessment': assessment}, 'findingsAssessment': assessment}
    patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0',
        'addressedFindingIndexes': [0], 'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Controlled execution and progression cue.'}}]}}
    metadata_patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0',
        'patch': [{'op': 'replace', 'path': finding['draftPath'], 'value': 'Controlled execution and progression cue.'}]}
    metadata_edits = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
            'setFields': {'placementNotes': 'Controlled execution and progression cue.'}}]}}
    if metadata_retry:
        initial_result['errors'] = [{'code': 'invalid_arguments', 'validator': 'maxLength', 'expected': 500,
            'path': finding['draftPath'], 'actual': 'x' * 501, 'message': 'The local cue is too long.'}]
        initial_result['rejectedSubmission'] = {**metadata_patch, 'patch': [
            {**metadata_patch['patch'][0], 'value': 'x' * 501}]}
        patch = metadata_edits
    responses = [tool('set_workout_requirements', requirements, 'requirements'),
                 tool('audit_workout_plan', draft, 'initial-audit'),
                 tool('audit_workout_plan', patch, 'coordinated-patch')]
    deps = make_shell_deps(tmp_path, chat_results=responses, generation_results=[], generation_calls=[])
    # This test isolates routing of the model's assessed repair; explicit saved-draft
    # re-audit behavior is covered separately and must not consume this fixture's repair response.
    monkeypatch.setattr(interactive_shell, 'pending_reaudit', lambda _state, _input: None)
    deps.load_equipment_from_file = lambda _path: equipment
    original_chat = deps.chat_call_with_loading
    planning_snapshots = []
    def capture_chat(client, api_messages, tools, logger, **options):
        snapshot = next((message['content'].split('\n', 1)[1] for message in api_messages
                         if (message.get('content') or '').startswith('Current planning state')), None)
        if snapshot:
            planning_snapshots.append(json.loads(snapshot))
        return original_chat(client, api_messages, tools, logger, **options)
    deps.chat_call_with_loading = capture_chat
    calls = []
    def handle(*args, **kwargs):
        name = args[2]
        calls.append({'name': name, 'arguments': copy.deepcopy(args[3]),
                      'coordinated_repair': kwargs.get('coordinated_repair', False)})
        if name == 'audit_workout_plan' and len([call for call in calls if call['name'] == name]) == 1:
            submitted = copy.deepcopy(draft)
            submitted['requirementsId'] = args[3]['requirementsId']
            result = {**initial_result, 'requirementsId': args[3]['requirementsId'],
                      'submittedDraft': submitted}
            return {'result': json.dumps(result), 'should_exit': False,
                    'generation_result': None}
        if name == 'audit_workout_plan':
            submitted = copy.deepcopy(draft)
            submitted['requirementsId'] = args[3]['requirementsId']
            return {'result': json.dumps({'passed': True, 'requirementsId': args[3]['requirementsId'],
                'currentDraftId': 'REVISION_1', 'submittedDraft': submitted, 'audit': {},
                'review': {'findings': [], 'assessment': {'version': ASSESSMENT_VERSION,
                    'inputHash': 'repaired-fixture', 'groups': [], 'repairPlan': ''}}}),
                'should_exit': False, 'generation_result': None,
                'draft_preview': 'Reviewed workout preview', 'draft_id': 'REVISION_1'}
        return deps._original_handle(*args, **kwargs)

    deps._original_handle = deps.handle_function_call
    deps.handle_function_call = handle
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    inputs = iter(['Plan a workout', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    interactive_shell.main(deps=deps)

    audit_calls = [call for call in calls if call['name'] == 'audit_workout_plan']
    assert len(audit_calls) == 2
    assert audit_calls[0]['coordinated_repair'] is False
    assert audit_calls[1]['coordinated_repair'] is False
    record = load_active_conversation_record(str(tmp_path))
    model_repair = next(call for message in record['messages'] for call in message.get('tool_calls', [])
                        if call['id'] == 'coordinated-patch')
    model_repair_args = json.loads(model_repair['function']['arguments'])
    assert 'edits' in model_repair_args and 'patch' not in model_repair_args


@pytest.mark.parametrize("first_sets", [5, 3, "invalid"])
def test_canonical_draft_repairs_and_displays_before_confirmation(monkeypatch, tmp_path, capsys, first_sets):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import confirmed_draft
    monkeypatch.setattr(interactive_shell, 'auto_allocate_workout', lambda result, *args, **kwargs: result)

    loading_events = []
    class RecordingLoading:
        def __init__(self, label):
            self.label = label
        def start(self):
            loading_events.append((self.label, "start"))
        def stop(self):
            loading_events.append((self.label, "stop"))
        def update(self, label):
            loading_events.append((label, 'update'))
    monkeypatch.setattr(interactive_shell, "LoadingIndicator", RecordingLoading)
    equipment, requirements, stored, draft = planning_case()
    path = tmp_path / "library.json"
    path.write_text(json.dumps(equipment), encoding="utf-8")

    def tool(name, arguments, call_id):
        return (None, [FakeToolCall(call_id, "function", FakeFunction(name, json.dumps(arguments)))])

    results = [tool("set_workout_requirements", requirements, "requirements")]
    if first_sets != 5:
        failing = copy.deepcopy(draft)
        failing["workouts"][0]["exercises"][0]["numWorkSets"] = first_sets
        results.append(tool("audit_workout_plan", failing, "failed"))
    repair = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'numWorkSets': 5}}]}} if first_sets == 3 else draft
    results.append(tool("audit_workout_plan", repair, "draft"))
    if first_sets == 5:
        results.append(("RIR means reps in reserve.", None))
    results.append(tool("generate_workout", {}, "generate"))
    calls = []
    deps = make_shell_deps(tmp_path, chat_results=results,
        generation_results=[{"success": True, "filepath": "generated.json", "error": None}], generation_calls=calls)
    inputs = iter(["Plan 5-6 effective chest sets", "CONFIRM REQUIREMENTS", *(["What is RIR?"] if first_sets == 5 else []),
                   '1' if first_sets == 5 else EXACT_GENERATION_CONFIRMATION, "/exit"])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("sys.argv", ["workout_generator.py", "--exercise-library-file", str(path)])
    interactive_shell.main(deps=deps)
    output = capsys.readouterr().out
    assert "| 1 | Push-Up | 5 | 8–10 |" in output
    assert "| 1 | Push-Up | 3 |" not in output
    assert "Estimated duration: 13.5 min" in output
    assert len(calls) == 1
    record = load_active_conversation_record(str(tmp_path))
    assert sum(bool(message.get("canonicalDraftPreview")) for message in record["messages"]) == 1
    tool_turns = [message for message in record["messages"] if message.get("tool_calls")
                  and not message['tool_calls'][0]['id'].startswith('confirm_')]
    assert tool_turns and all(message["reasoning_content"] == "test reasoning" for message in tool_turns)
    assert all(message["reasoning_content"] == "test reasoning"
               for message in interactive_shell._messages_for_api(record["messages"])
               if message.get("tool_calls") and not message['tool_calls'][0]['id'].startswith('confirm_'))
    snapshot = confirmed_draft(record["messages"], equipment)
    assert snapshot["planIndex"]["exercises"][0]["numWorkSets"] == 5
    if first_sets != 5:
        failure = next(json.loads(m["content"]) for m in record["messages"] if m.get("role") == "tool" and m.get("tool_call_id") == "failed")
        assert not failure["passed"]
        if first_sets == 3:
            assert "3 effective sets" in failure["audit"]["issues"][0]
        else:
            error = failure["errors"][0]
            assert error["code"] == "invalid_arguments"
            assert error["path"] == "/workouts/0/exercises/0/numWorkSets"
            assert "preserve agreed requirements" in error["repair"]


def test_missing_draft_returns_repair_feedback_then_requires_fresh_confirmation(monkeypatch, tmp_path, capsys):
    from test_workout_generator_planning_tools import planning_case

    equipment, requirements, _, draft = planning_case()
    path = tmp_path / "library.json"
    path.write_text(json.dumps(equipment), encoding="utf-8")

    def tool(name, arguments, call_id):
        return (None, [FakeToolCall(call_id, "function", FakeFunction(name, json.dumps(arguments)))])

    calls = []
    deps = make_shell_deps(tmp_path, chat_results=[
        ("I will validate the plan before generation.", None),
        tool("set_workout_requirements", requirements, "requirements"),
        tool("audit_workout_plan", draft, "draft"),
    ], generation_results=[{"success": True, "filepath": "generated.json", "error": None}], generation_calls=calls)
    inputs = iter(["Plan 5-6 chest sets", EXACT_GENERATION_CONFIRMATION, "CONFIRM REQUIREMENTS", EXACT_GENERATION_CONFIRMATION, "/exit"])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("sys.argv", ["workout_generator.py", "--exercise-library-file", str(path)])
    interactive_shell.main(deps=deps)
    assert len(calls) == 1
    messages = load_active_conversation_record(str(tmp_path))["messages"]
    failed = next(json.loads(m["content"]) for m in messages if m.get("role") == 'tool'
                  and m.get("tool_call_id", '').startswith('confirm_'))
    assert failed["requires_plan_revision"] and failed["errors"][0]["repair"]
    assert "Returning to planning" in capsys.readouterr().out


def test_failed_audit_revises_in_chat_and_requires_fresh_confirmation(monkeypatch, tmp_path, capsys):
    generate = (None, [FakeToolCall("generate", "function", FakeFunction("generate_workout", "{}"))])
    calls = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[generate, generate, ("Revised plan: four sets. Reply CONFIRM GENERATE.", None), generate],
        generation_results=[
            {"success": False, "filepath": None, "error": "Programming audit requires a revised plan.",
             "requires_plan_revision": True, "programming_audit": {"issues": ["Weekly chest: 3; required 4"]}},
            {"success": True, "filepath": "generated.json", "error": None},
        ],
        generation_calls=calls,
    )
    captured = []
    original_chat = deps.chat_call_with_loading

    def chat(client, messages, tools, logger, **options):
        captured.append((copy.deepcopy(messages), tools))
        return original_chat(client, messages, tools, logger, **options)

    deps.chat_call_with_loading = chat
    run_shell(monkeypatch, deps, [EXACT_GENERATION_CONFIRMATION, EXACT_GENERATION_CONFIRMATION, "/exit"])
    assert len(calls) == 2
    assert captured[1][1] == [interactive_shell.ASK_USER_TOOL]
    assert any("Weekly chest: 3; required 4" in str(message.get("content")) for message in captured[1][0])
    assert any("fresh CONFIRM GENERATE" in str(message.get("content")) for message in captured[2][0])
    assert "Revised plan: four sets" in capsys.readouterr().out


def test_revision_failure_without_programming_audit_preserves_error_without_keyerror():
    deps = SimpleNamespace(execute_workout_generation=lambda *_args, **_kwargs: {
        "success": False,
        "filepath": None,
        "error": "The approved draft's load-calibration flags do not match current evidence.",
        "requires_plan_revision": True,
    })

    result = interactive_shell.handle_function_call(
        None,
        [{"role": "user", "content": EXACT_GENERATION_CONFIRMATION}],
        "generate_workout",
        {},
        deps=deps,
    )

    assert "load-calibration flags do not match current evidence" in result["result"]
    assert "No programming audit was produced" in result["result"]
    assert '"audit"' not in result["result"]


def test_legacy_history_migrates_into_archived_session(tmp_path: Path) -> None:
    (tmp_path / "conversation_history.json").write_text(
        json.dumps(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "conversation_meta.json").write_text(
        json.dumps({"conversation_id": "legacy-conversation-id"}),
        encoding="utf-8",
    )

    record = load_active_conversation_record(str(tmp_path))

    assert record is not None
    assert record["conversation_id"] == "legacy-conversation-id"
    assert [message["role"] for message in record["messages"]] == ["system", "user"]
    assert get_active_conversation_id(str(tmp_path)) == "legacy-conversation-id"
    conversations = list_conversations(str(tmp_path))
    assert len(conversations) == 1
    assert conversations[0]["status"] == "active"


def test_save_load_and_list_conversations_by_recency(tmp_path: Path) -> None:
    save_conversation(
        [{"role": "system", "content": "old"}],
        conversation_id="conversation-old",
        script_dir=str(tmp_path),
        metadata={"created_at": "2026-05-10T10:00:00", "updated_at": "2026-05-10T10:00:00"},
    )
    save_conversation(
        [{"role": "system", "content": "new"}],
        conversation_id="conversation-new",
        script_dir=str(tmp_path),
        metadata={
            "created_at": "2026-05-11T10:00:00",
            "updated_at": "2026-05-11T10:00:00",
            "last_generation_result": {"success": True},
        },
    )

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert active_record["conversation_id"] == "conversation-new"
    assert active_record["messages"][0]["content"] == "new"

    conversations = list_conversations(str(tmp_path))
    assert [item["conversation_id"] for item in conversations] == ["conversation-new", "conversation-old"]
    assert conversations[0]["status"] == "active"
    assert conversations[1]["status"] == "open"


def test_reopen_completed_conversation_preserves_turns(tmp_path: Path) -> None:
    completed_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "done"},
        {"role": "emitter", "step": "emit", "item_id": "item-1", "request_messages": [], "response_content": "ok"},
    ]
    save_conversation(
        completed_messages,
        conversation_id="completed-conversation",
        script_dir=str(tmp_path),
        metadata={
            "last_generation_result": {"success": True, "filepath": "workouts/generated.json"},
            "updated_at": "2026-05-11T08:00:00",
        },
    )
    save_conversation(
        [{"role": "system", "content": "active"}],
        conversation_id="active-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-10T08:00:00"},
    )

    assert set_active_conversation("completed-conversation", str(tmp_path)) is True

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert active_record["conversation_id"] == "completed-conversation"
    assert active_record["messages"] == completed_messages


def test_successful_generation_keeps_shell_alive_and_preserves_active_conversation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[("You can keep refining this conversation.", None)],
        generation_results=[
            {
                "success": True,
                "filepath": str(tmp_path / "workouts" / "generated.json"),
                "error": None,
                "emitter_conversations": [
                    {
                        "step": "exercise_definitions",
                        "item_id": "exercise-1",
                        "request_messages": [{"role": "user", "content": "emit"}],
                        "response_content": "{\"id\":\"exercise-1\"}",
                    }
                ],
            }
        ],
        generation_calls=generation_calls,
    )

    run_shell(
        monkeypatch,
        deps,
        [EXACT_GENERATION_CONFIRMATION, "another question", "/exit"],
    )

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert any(message.get("content") == "another question" for message in active_record["messages"])
    assert any(message.get("role") == "emitter" for message in active_record["messages"])
    assert generation_calls[0]["resume_session_id"] is None
    captured = capsys.readouterr().out
    assert "Assistant> You can keep refining this conversation." in captured


def test_clear_starts_new_conversation_without_deleting_archived_ones(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_conversation(
        [{"role": "system", "content": "original"}],
        conversation_id="existing-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-10T09:00:00"},
    )
    original_active_id = get_active_conversation_id(str(tmp_path))
    assert original_active_id == "existing-conversation"

    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=generation_calls,
    )

    run_shell(monkeypatch, deps, ["/clear", "/exit"])

    conversations = list_conversations(str(tmp_path))
    assert len(conversations) == 1
    assert any(item["conversation_id"] == "existing-conversation" for item in conversations)


def test_clear_keep_requirements_starts_fresh_conversation_with_only_revalidated_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, draft = planning_case()
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    messages = requirement_messages(stored)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prior-audit', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'prior-audit', 'content': json.dumps({
            'currentDraftId': 'REVISION_0', 'submittedDraft': draft, 'review': {'passed': True}})},
        {'role': 'assistant', 'content': 'Prior workout menu', 'canonicalDraftPreview': 'REVISION_0'},
    ])
    save_conversation(messages, conversation_id='approved-source', script_dir=str(tmp_path))
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])

    run_shell(monkeypatch, deps, ['/resume-conversation approved-source', '/clear keep-requirements', '/exit'])

    active = load_active_conversation_record(str(tmp_path))
    assert active is not None and active['conversation_id'] != 'approved-source'
    carried = active['messages']
    assert any(message.get('content') == stored['sourceMessages'][0]['content'] for message in carried)
    assert not any(message.get('canonicalDraftPreview') or message.get('canonicalAlternativePreview')
        for message in carried)
    assert not any(message.get('tool_call_id') == 'prior-audit' for message in carried)
    assert json.loads(carried[-2]['content'])['sourceReview'] == {}
    assert carried[-1]['role'] == 'system' and 'library changed' in carried[-1]['content']


def test_resume_can_reopen_completed_conversation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_conversation(
        [{"role": "system", "content": "completed"}],
        conversation_id="completed-conversation",
        script_dir=str(tmp_path),
        metadata={
            "updated_at": "2026-05-12T10:00:00",
            "last_generation_result": {"success": True},
        },
    )
    save_conversation(
        [{"role": "system", "content": "active"}],
        conversation_id="active-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-10T10:00:00"},
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/resume", "1", "/exit"])

    assert get_active_conversation_id(str(tmp_path)) == "completed-conversation"
    output = capsys.readouterr().out
    assert "Resumed conversation complete" in output
    assert "Conversation Turns" in output
    assert "completed" in output


def test_resume_progress_targets_generation_progress_not_archived_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_conversation(
        [{"role": "system", "content": "active"}],
        conversation_id="active-conversation",
        script_dir=str(tmp_path),
    )
    save_conversation(
        [{"role": "system", "content": "completed"}],
        conversation_id="completed-conversation",
        script_dir=str(tmp_path),
        metadata={"last_generation_result": {"success": True}},
    )
    write_progress_file(tmp_path, "progress-session-1234", step=4)

    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[
            {
                "success": True,
                "filepath": str(tmp_path / "workouts" / "resumed.json"),
                "error": None,
                "emitter_conversations": [],
            }
        ],
        generation_calls=generation_calls,
    )

    run_shell(monkeypatch, deps, ["/resume-progress", "1", "/exit"])

    assert generation_calls == [
        {
            "custom_prompt": "",
            "resume_session_id": "progress-session-1234",
            "message_count": 1,
        }
    ]


def test_show_turns_hides_tool_and_emitter_payloads_but_keeps_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_conversation(
        [
            {"role": "system", "content": "system", "timestamp": "2026-05-12T09:00:00"},
            {"role": "user", "content": "user", "timestamp": "2026-05-12T09:01:00"},
            {
                "role": "assistant",
                "content": "assistant",
                "timestamp": "2026-05-12T09:02:00",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tool-1",
                "content": "tool result",
                "timestamp": "2026-05-12T09:03:00",
            },
            {
                "role": "emitter",
                "step": "exercise_definitions",
                "item_id": "exercise-1",
                "request_messages": [{"role": "user", "content": "emit this"}],
                "response_content": "{\"ok\":true}",
                "timestamp": "2026-05-12T09:04:00",
            },
        ],
        conversation_id="turns-conversation",
        script_dir=str(tmp_path),
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/show-turns turns-conversation", "/exit"])

    output = capsys.readouterr().out
    assert "[1] system | 2026-05-12 09:00:00" in output
    assert "[2] user | 2026-05-12 09:01:00" in output
    assert "[3] assistant | 2026-05-12 09:02:00" in output
    assert "[Tool call triggered]" in output
    assert "tool_name: generate_workout" not in output
    assert "request_messages:" not in output
    assert "tool result" not in output
    assert "[5] tool | 2026-05-12 09:03:00" not in output
    assert "[5] emitter | 2026-05-12 09:04:00" not in output


def test_resume_repairs_orphaned_tool_call_before_next_api_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    save_conversation(
        [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "The generation hit a validation snag — let me try again!"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-orphan",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
        ],
        conversation_id="orphaned-tool-conversation",
        script_dir=str(tmp_path),
        metadata={"updated_at": "2026-05-12T17:25:30"},
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[("Recovered after resume.", None)],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/resume", "1", "continue", "/exit"])

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert any(
        message.get("role") == "tool" and message.get("tool_call_id") == "tool-orphan"
        for message in active_record["messages"]
    )


def test_fresh_resume_dispatches_saved_draft_reaudit_before_model_tool_bookkeeping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    from workout_generator_pkg.planning_tools import audit_workout_plan
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    audit['review'] = {'version': REVIEW_VERSION - 1, 'findings': []}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{
            'id': 'stale-audit', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)},
        }]},
        {'role': 'tool', 'tool_call_id': 'stale-audit', 'content': json.dumps(audit)},
        {'role': 'user', 'content': '/continue'},
    ])
    conversation_id = 'saved-reaudit-dispatch'
    save_conversation(messages, conversation_id=conversation_id, script_dir=str(tmp_path))

    library_path = tmp_path / 'library.json'
    library_path.write_text(json.dumps(equipment), encoding='utf-8')
    dispatched: list[str] = []
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])

    def stop_after_audit(client, messages, function_name, *args, **kwargs):
        dispatched.append(function_name)
        return {
            'result': json.dumps({'passed': False, 'executionFailure': True,
                'errors': [{'code': 'tool_execution_failed', 'message': 'test stop'}]}),
            'should_exit': False,
            'generation_result': None,
        }

    deps.handle_function_call = stop_after_audit
    inputs = iter([f'/resume-conversation {conversation_id}', '/continue', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(library_path)])

    interactive_shell.main(deps=deps)

    assert dispatched == ['audit_workout_plan']


def test_messages_for_api_repairs_multiple_orphaned_tool_calls_and_drops_stray_tools() -> None:
    repaired = interactive_shell._messages_for_api(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": EXACT_GENERATION_CONFIRMATION},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {"role": "user", "content": EXACT_GENERATION_CONFIRMATION},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-2",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tool-stray", "content": "orphan"},
            {"role": "user", "content": "continue"},
        ]
    )

    assert [(message["role"], message.get("tool_call_id")) for message in repaired] == [
        ("system", None),
        ("user", None),
        ("assistant", None),
        ("tool", "tool-1"),
        ("user", None),
        ("assistant", None),
        ("tool", "tool-2"),
        ("user", None),
    ]


def test_save_conversation_repairs_orphaned_tool_calls_at_persistence_boundary(tmp_path: Path) -> None:
    save_conversation(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": EXACT_GENERATION_CONFIRMATION},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "generate_workout", "arguments": "{\"custom_prompt\":\"\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "stray-tool", "content": "orphan"},
            {"role": "assistant", "content": "next"},
        ],
        conversation_id="persisted-conversation",
        script_dir=str(tmp_path),
    )

    record = load_conversation_record("persisted-conversation", str(tmp_path))
    assert record is not None
    assert [(message["role"], message.get("tool_call_id")) for message in record["messages"]] == [
        ("system", None),
        ("user", None),
        ("assistant", None),
        ("tool", "tool-1"),
        ("assistant", None),
    ]


def test_interrupted_tool_call_still_persists_matching_tool_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deps = make_shell_deps(
        tmp_path,
        chat_results=[
            (
                None,
                [
                    FakeToolCall(
                        id="tool-1",
                        type="function",
                        function=FakeFunction("generate_workout", json.dumps({"custom_prompt": ""})),
                    )
                ],
            ),
        ],
        generation_results=[],
        generation_calls=[],
    )

    def interrupted_handle_function_call(*args, **kwargs):
        raise KeyboardInterrupt()

    deps.handle_function_call = interrupted_handle_function_call

    run_shell(monkeypatch, deps, [EXACT_GENERATION_CONFIRMATION, "/exit"])

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    assert any(
        message.get("role") == "tool" and message.get("tool_call_id", '').startswith('confirm_')
        for message in active_record["messages"]
    )


def test_failed_generation_still_records_tool_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generation_calls: list[dict[str, object]] = []
    deps = make_shell_deps(
        tmp_path,
        chat_results=[
            (
                None,
                [
                    FakeToolCall(
                        id="tool-1",
                        type="function",
                        function=FakeFunction("generate_workout", json.dumps({"custom_prompt": ""})),
                    )
                ],
            ),
        ],
        generation_results=[
            {
                "success": False,
                "filepath": None,
                "error": "first failure",
                "emitter_conversations": [],
            },
        ],
        generation_calls=generation_calls,
    )

    run_shell(monkeypatch, deps, [EXACT_GENERATION_CONFIRMATION, "/exit"])

    active_record = load_active_conversation_record(str(tmp_path))
    assert active_record is not None
    tool_messages = [message for message in active_record["messages"] if message.get("role") == "tool"]
    assert len(tool_messages) == 1 and tool_messages[0]['tool_call_id'].startswith('confirm_')
    assert len(generation_calls) == 1
    output = capsys.readouterr().out
    assert "Workout generation failed: first failure" in output


def test_shell_does_not_resume_previous_conversation_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_conversation(
        [
            {"role": "system", "content": "previous system"},
            {"role": "user", "content": "previous user"},
        ],
        conversation_id="previous-conversation",
        script_dir=str(tmp_path),
    )

    deps = make_shell_deps(
        tmp_path,
        chat_results=[],
        generation_results=[],
        generation_calls=[],
    )

    run_shell(monkeypatch, deps, ["/show-turns", "/exit"])

    output = capsys.readouterr().out
    assert "✓ Resumed active conversation" not in output
    assert "previous user" not in output
    assert "base system prompt" in output


@pytest.mark.parametrize('interrupt', [False, True])
def test_shell_blocked_submission_never_becomes_a_saved_draft(monkeypatch, tmp_path, interrupt):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import set_workout_requirements, latest_draft_submission
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions with 5-6 chest sets each.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, arguments, identifier):
        return (None, [FakeToolCall(identifier, 'function', FakeFunction(name, json.dumps(arguments)))])
    responses = [tool('set_workout_requirements', requirements, 'requirements'), tool('audit_workout_plan', draft, 'first')]
    responses.append(('The week still needs shared preparation.', None))
    generated, requests = [], []
    deps = make_shell_deps(tmp_path, chat_results=responses,
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    original = deps.chat_call_with_loading
    def capture(client, messages, tools, logger, **options):
        requests.append((copy.deepcopy(tools), options))
        if interrupt and len(requests) == 3:
            from workout_generator_pkg.api_client import TruncatedResponseError
            raise TruncatedResponseError(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=None, reasoning_content='rejected unfinished reasoning', tool_calls=None))]), 65536, 'low')
        from workout_generator_pkg.planner_context import request_planning_state
        state = request_planning_state(messages)
        omitted = any(day.get('detailsOmitted') for day in (state.get('currentDraft') or {}).get('workouts', []))
        if not omitted:
            assert 'get_workout_draft' not in [tool['function']['name'] for tool in tools]
        return original(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = capture
    inputs = iter(['Three sessions with 5-6 chest sets each.', 'CONFIRM REQUIREMENTS',
                   *(['/continue'] if interrupt else []), '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert not generated and latest_draft_submission(messages, equipment) == (None, None)
    results = {m['tool_call_id']: json.loads(m['content']) for m in messages if m.get('tool_call_id') == 'first'}
    assert results['first']['errors'][0]['code'] == 'construction_stage_required'
    assert not any(m.get('canonicalDraftPreview') for m in messages)
    for _, options in requests[1:-1]:
        assert options['reasoning_effort'] is None and options['max_tokens'] == 16384 and options['timeout'] is None
        assert options['activity'] == 'Selecting weekly movements'


def test_combined_search_failure_keeps_tool_responses_and_preserves_approved_requirements(monkeypatch, tmp_path):
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, _ = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    calls = [FakeToolCall(identifier, 'function', FakeFunction(name, json.dumps(arguments)))
             for identifier, name, arguments in [
                 ('one', 'search_exercise_library', {'queries': ['push']}),
                 ('two', 'search_exercise_library', {'queries': ['pull']}),
                 ('requirements', 'set_workout_requirements', requirements)]]
    deps = make_shell_deps(tmp_path, chat_results=[(None, [FakeToolCall('requirements-initial', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements)))]), (None, calls), ('The library lookup failed; your requirements are saved.', None)],
                           generation_results=[], generation_calls=[])
    def fail(*args, **kwargs):
        raise ValueError('Semantic ranking response truncated')
    monkeypatch.setattr(interactive_shell, 'execute_library_searches', fail)
    inputs = iter(['Plan a workout', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    results = {message['tool_call_id']: json.loads(message['content']) for message in messages if message.get('role') == 'tool'}
    assert set(results) == {'one', 'two', 'requirements', 'requirements-initial'}
    assert results['requirements-initial']['requirementsId']
    assert results['requirements']['errors'][0]['code'] == 'construction_stage_required'
    from workout_generator_pkg.planning_tools import _latest_result
    assert _latest_result(messages, 'set_workout_requirements')[1] == results['requirements-initial']
    for identifier in ('one', 'two'):
        assert results[identifier]['errors'][0]['code'] == 'library_search_failed'
        assert 'truncated' in results[identifier]['errors'][0]['message']
        assert 'Do not automatically repeat' in results[identifier]['instruction']
def test_unvalidated_assistant_proposal_does_not_become_requirement_authority():
    from workout_generator_pkg.planning_tools import requirement_sources
    messages = [
        {'role': 'user', 'content': 'Keep the approved volume targets.'},
        {'role': 'assistant', 'content': 'Malformed attempted repair', 'unvalidatedProposal': True},
        {'role': 'user', 'content': 'Use three sessions.', 'unvalidatedProposal': True},
    ]
    sources = requirement_sources(messages)
    assert [item['content'] for item in sources] == ['Keep the approved volume targets.', 'Use three sessions.']
