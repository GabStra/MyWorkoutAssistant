from __future__ import annotations

import json
import copy
import io
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
        generate_workout_tool={"name": "generate_workout"},
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
    def search_group(searches, equipment, client, messages, progress=None):
        calls.append(searches)
        progress(0, 2)
        progress(2, 2)
        return {call_id: {"results": []} for call_id, _ in searches}
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
    patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/targetSetPrescriptions/4/reps', 'value': 8}]}
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
    assert repair_options == {'reasoning_effort': 'low', 'activity': 'Repairing draft'}
    schema = next(t['function']['parameters'] for t in repair_tools if t.get('function', {}).get('name') == 'audit_workout_plan')
    assert 'patch' in schema['required'] and 'workouts' not in schema['properties']
    assert requests[1][1] == {'reasoning_effort': 'low', 'activity': 'Drafting session'}
    assert requests[-1][1] == {}
    if attempt_full_rewrite:
        failure = next(json.loads(m['content']) for m in messages if m.get('tool_call_id') == 'rewrite')
        assert failure['errors'][0]['code'] == 'repair_patch_required'
        assert 'submittedDraft' not in failure
    output = capsys.readouterr().out
    assert 'outside minReps' not in output
    assert 'Repair task: REVISION_0' in output


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


def test_requirements_reapproval_reaudits_saved_draft_before_another_planner_call(monkeypatch, tmp_path, capsys):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import confirmed_draft
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    def tool(name, arguments, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(arguments)))])
    repair = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_1', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 5}]}
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
    automatic = next(c for m in messages for c in m.get('tool_calls', []) if c['id'].startswith('reaudit_'))
    assert json.loads(automatic['function']['arguments'])['patch'] == []
    resumed = json.loads(next(m['content'].split('\n', 1)[1] for m in calls[4][0]
                             if m.get('content', '').startswith('Current planning state')))
    assert resumed['currentDraftId'] == 'REVISION_1' and resumed['repairTask']
    assert calls[4][1]['reasoning_effort'] == 'low' and len(calls) == 6
    assert confirmed_draft(messages, equipment)['currentDraftId'] == 'REVISION_2' and len(generated) == 1
    assert 'Re-auditing saved draft' in capsys.readouterr().out


@pytest.mark.parametrize("first_sets", [5, 3, "invalid"])
def test_canonical_draft_repairs_and_displays_before_confirmation(monkeypatch, tmp_path, capsys, first_sets):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import confirmed_draft

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
    repair = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 5}]} if first_sets == 3 else draft
    results.append(tool("audit_workout_plan", repair, "draft"))
    if first_sets == 5:
        results.append(("RIR means reps in reserve.", None))
    results.append(tool("generate_workout", {}, "generate"))
    calls = []
    deps = make_shell_deps(tmp_path, chat_results=results,
        generation_results=[{"success": True, "filepath": "generated.json", "error": None}], generation_calls=calls)
    inputs = iter(["Plan 5-6 effective chest sets", "CONFIRM REQUIREMENTS", *(["What is RIR?"] if first_sets == 5 else []), EXACT_GENERATION_CONFIRMATION, "/exit"])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("sys.argv", ["workout_generator.py", "--exercise-library-file", str(path)])
    interactive_shell.main(deps=deps)
    output = capsys.readouterr().out
    assert "| 1 | Push-Up | 5 | 8–10 | 90s |" in output
    assert "| 1 | Push-Up | 3 |" not in output
    assert "Estimated duration: 13.5 min" in output
    assert len(calls) == 1
    record = load_active_conversation_record(str(tmp_path))
    assert sum(bool(message.get("canonicalDraftPreview")) for message in record["messages"]) == 1
    tool_turns = [message for message in record["messages"] if message.get("tool_calls")]
    assert tool_turns and all(message["reasoning_content"] == "test reasoning" for message in tool_turns)
    assert all(message["reasoning_content"] == "test reasoning"
               for message in interactive_shell._messages_for_api(record["messages"])
               if message.get("tool_calls"))
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
        tool("generate_workout", {}, "premature"),
        tool("set_workout_requirements", requirements, "requirements"),
        tool("audit_workout_plan", draft, "draft"),
        tool("generate_workout", {}, "confirmed"),
    ], generation_results=[{"success": True, "filepath": "generated.json", "error": None}], generation_calls=calls)
    inputs = iter(["Plan 5-6 chest sets", EXACT_GENERATION_CONFIRMATION, "CONFIRM REQUIREMENTS", EXACT_GENERATION_CONFIRMATION, "/exit"])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("sys.argv", ["workout_generator.py", "--exercise-library-file", str(path)])
    interactive_shell.main(deps=deps)
    assert len(calls) == 1
    messages = load_active_conversation_record(str(tmp_path))["messages"]
    failed = next(json.loads(m["content"]) for m in messages if m.get("tool_call_id") == "premature")
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
    assert captured[1][1] == []
    assert any("Weekly chest: 3; required 4" in str(message.get("content")) for message in captured[1][0])
    assert any("fresh CONFIRM GENERATE" in str(message.get("content")) for message in captured[2][0])
    assert "Revised plan: four sets" in capsys.readouterr().out


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
            ("You can keep refining this conversation.", None),
        ],
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
        message.get("role") == "tool" and message.get("tool_call_id") == "tool-1"
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
    assert [message.get("tool_call_id") for message in tool_messages] == ["tool-1"]
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
def test_shell_builds_sessions_incrementally_and_reviews_only_the_complete_program(monkeypatch, tmp_path, interrupt):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import set_workout_requirements, confirmed_draft
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
    for index in (1, 2):
        day = {**copy.deepcopy(draft['workouts'][0]), 'name': f'Day {index + 1}'}
        responses.append(tool('audit_workout_plan', {
            'requirementsId': stored['requirementsId'], 'baseDraftId': f'REVISION_{index-1}',
            'patch': [{'op': 'add', 'path': '/workouts/-', 'value': day}]}, f'append-{index}'))
    responses.append(tool('generate_workout', {}, 'export'))
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
        return original(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = capture
    inputs = iter(['Three sessions with 5-6 chest sets each.', 'CONFIRM REQUIREMENTS',
                   *(['/continue'] if interrupt else []), 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert len(generated) == 1 and len(confirmed_draft(messages, equipment)['planIndex']['workouts']) == 3
    results = {m['tool_call_id']: json.loads(m['content']) for m in messages if m.get('tool_call_id') in ('first', 'append-1', 'append-2')}
    assert results['first']['reviewPending'] and results['append-1']['reviewPending']
    assert results['append-2']['passed'] and results['append-2']['review']['findings'] == []
    assert sum(bool(m.get('canonicalDraftPreview')) for m in messages) == 1
    assert all(options == {'reasoning_effort': 'low', 'activity': 'Drafting session'} for _, options in requests[1:-1])


def test_combined_search_failure_keeps_tool_responses_and_records_requirements(monkeypatch, tmp_path):
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
    assert results['requirements']['requirementsId']
    for identifier in ('one', 'two'):
        assert results[identifier]['errors'][0]['code'] == 'library_search_failed'
        assert 'truncated' in results[identifier]['errors'][0]['message']
        assert 'Do not automatically repeat' in results[identifier]['instruction']
