import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from workout_generator_pkg import api_client, image_attachments, interactive_shell as shell, plan_review
from workout_generator_pkg.image_attachments import save_image, prepare_image_messages, image_message
from workout_generator_pkg.planning_tools import requirement_sources, source_message_context, set_workout_requirements, requirements_approved
from workout_generator_pkg.conversation_store import load_active_conversation_record
from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
from test_workout_generator_planning_tools import planning_case, requirement_messages


def fixture_image(tmp_path, name='source.png', image_format='PNG'):
    path = tmp_path / name
    Image.new('RGB', (80, 40), 'red').save(path, format=image_format)
    return path


@pytest.mark.parametrize('image_format,mime', [('PNG', 'image/png'), ('JPEG', 'image/jpeg'), ('GIF', 'image/gif'), ('WEBP', 'image/webp')])
def test_images_are_detected_from_bytes_copied_and_encoded_only_for_api(tmp_path, image_format, mime):
    original = fixture_image(tmp_path, 'misnamed.bin', image_format)
    expected = original.read_bytes()
    attachment = save_image(original, tmp_path)
    original.unlink()
    sources = [{'role': 'user', 'content': 'Describe this image.', 'imageAttachments': [attachment]}]
    before = copy.deepcopy(sources)
    request = prepare_image_messages(image_message(sources))
    url = request[0]['content'][1]['image_url']['url']
    assert url.startswith(f'data:{mime};base64,')
    assert base64.b64decode(url.split(',', 1)[1]) == expected
    assert sources == before and 'data:image' not in json.dumps(sources)
    assert 'imageAttachments' not in request[0]
    assert source_message_context(sources)['SOURCE_0']['images'] == [{'name': 'misnamed.bin', 'sha256': attachment['sha256']}]


@pytest.mark.parametrize('change', ['delete', 'tamper'])
def test_missing_or_modified_saved_images_fail_before_model_request(tmp_path, change):
    attachment = save_image(fixture_image(tmp_path), tmp_path)
    path = Path(attachment['path'])
    if change == 'delete':
        path.unlink()
    else:
        path.write_bytes(b'changed')
    calls = []
    client = SimpleNamespace(with_options=lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError, match='Attach it again'):
        api_client.chat_call(client, [{'role': 'user', 'content': 'Describe it.', 'imageAttachments': [attachment]}])
    assert not calls


def test_invalid_images_and_size_limits_are_rejected(tmp_path, monkeypatch):
    invalid = tmp_path / 'bad.png'
    invalid.write_bytes(b'not an image')
    with pytest.raises(ValueError, match='decoded'):
        save_image(invalid, tmp_path)
    valid = fixture_image(tmp_path)
    monkeypatch.setattr(image_attachments, 'MAX_IMAGE_BYTES', 10)
    with pytest.raises(ValueError, match='32 MiB'):
        save_image(valid, tmp_path)


def test_full_image_request_limit_includes_non_image_fields(tmp_path, monkeypatch):
    attachment = save_image(fixture_image(tmp_path), tmp_path)
    messages = [{'role': 'user', 'content': 'Describe it.', 'imageAttachments': [attachment]}]
    encoded = prepare_image_messages(messages)
    monkeypatch.setattr(image_attachments, 'MAX_REQUEST_BYTES', len(json.dumps({'messages': encoded}).encode()) + 1)
    with pytest.raises(ValueError, match='request size limit'):
        image_attachments.validate_image_request({'messages': encoded, 'tools': [{'description': 'long extra schema' * 50}]})


def test_many_images_use_the_lower_dimension_limit(tmp_path):
    path = tmp_path / 'wide.png'
    Image.new('RGB', (4097, 1), 'red').save(path)
    attachment = save_image(path, tmp_path)
    with pytest.raises(ValueError, match='4096 pixels'):
        prepare_image_messages([{'role': 'user', 'content': 'Inspect them.', 'imageAttachments': [attachment] * 15}])


def test_chat_call_sends_native_image_parts_and_preserves_original_messages(tmp_path):
    attachment = save_image(fixture_image(tmp_path), tmp_path)
    messages = [{'role': 'user', 'content': 'Describe it.', 'imageAttachments': [attachment]}]
    before, requests = copy.deepcopy(messages), []
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
        content='A red image.', tool_calls=None, reasoning_content=None))])
    def create(**kwargs):
        requests.append(kwargs)
        return response
    client = SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    assert api_client.chat_call(client, messages)[0] == 'A red image.'
    assert requests[0]['messages'][0]['content'][1]['type'] == 'image_url'
    assert messages == before


def test_planner_and_requirement_reviewer_both_receive_original_source_image(tmp_path, monkeypatch):
    attachment = save_image(fixture_image(tmp_path), tmp_path)
    equipment, requirements, _, _ = planning_case()
    sources = [{'role': 'user', 'content': 'Use the requirements in this screenshot.', 'imageAttachments': [attachment]}]
    stored = set_workout_requirements(requirements, sources, equipment)
    requests = []
    def review_call(client, messages, **kwargs):
        requests.append(messages)
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', review_call)
    reviewed = plan_review.review_requirements(None, stored, sources)
    assert reviewed['passed']
    assert requests[0][1]['imageAttachments'] == [attachment]
    messages = requirement_messages(reviewed)
    messages[0]['imageAttachments'] = [attachment]
    api_messages = shell._messages_for_api(messages, True, provided_equipment=equipment)
    assert sum(len(m.get('imageAttachments', [])) for m in api_messages) == 1
    assert api_messages[-1]['imageAttachments'] == [attachment]
    state = next(json.loads(m['content'].split('\n', 1)[1]) for m in api_messages if m['content'].startswith('Current planning state'))
    assert state['sourceMessages']['SOURCE_0']['images'][0]['sha256'] == attachment['sha256']
    assert 'path' not in state['sourceMessages']['SOURCE_0']['images'][0]
    altered_sources = copy.deepcopy(sources)
    altered_sources[0]['imageAttachments'][0]['sha256'] = 'different'
    assert set_workout_requirements(requirements, altered_sources, equipment)['requirementsId'] != stored['requirementsId']

    from workout_generator_pkg.planning_tools import audit_workout_plan
    from test_workout_generator_planning_tools import approved_messages
    _, _, _, draft = planning_case()
    draft['requirementsId'] = reviewed['requirementsId']
    numeric = audit_workout_plan(draft, equipment, messages)
    result = plan_review.review_draft(None, numeric, messages, equipment)
    assert result['passed']
    assert requests[-1][1]['imageAttachments'] == [attachment]
    approved = approved_messages(reviewed, result)
    approved[0]['imageAttachments'] = [attachment]
    approved.append({'role': 'user', 'content': 'Does this change the plan?', 'imageAttachments': [attachment]})

    def classify(client, request, **kwargs):
        requests.append(request)
        return '{"readOnly":false,"reason":"New image needs review."}', None, None

    monkeypatch.setattr(plan_review, 'chat_call', classify)
    with pytest.raises(ValueError, match='New conversation instructions'):
        plan_review.review_followup_instructions(None, result, approved, equipment)
    assert requests[-1][1]['imageAttachments'] == [attachment]


@pytest.mark.parametrize('cancelled', [False, True])
def test_shell_attaches_to_next_message_and_keeps_copy_in_saved_conversation(tmp_path, monkeypatch, cancelled):
    original = fixture_image(tmp_path, 'image with spaces.png')
    captured = []
    deps = make_shell_deps(tmp_path, chat_results=[(None, None) if cancelled else ('A red image.', None)],
                           generation_results=[], generation_calls=[])
    call = deps.chat_call_with_loading
    def capture(client, messages, *args, **kwargs):
        captured.append(copy.deepcopy(messages))
        return call(client, messages, *args, **kwargs)
    deps.chat_call_with_loading = capture
    run_shell(monkeypatch, deps, [f'/image "{original}"', 'Describe it.', '/exit'])
    original.unlink()
    saved = load_active_conversation_record(str(tmp_path))['messages']
    assert saved[-1]['role'] == ('user' if cancelled else 'assistant')
    assert any(m.get('imageAttachments') for m in saved)
    assert 'data:image' not in json.dumps(saved)
    assert captured[0][-1]['imageAttachments']
    resumed = shell._messages_for_api(saved)
    assert prepare_image_messages(resumed)[-1]['content'][1]['type'] == 'image_url'


@pytest.mark.parametrize('clear_command', ['/image clear', '/clear'])
def test_clearing_does_not_send_queued_images(tmp_path, monkeypatch, clear_command):
    original = fixture_image(tmp_path)
    deps = make_shell_deps(tmp_path, chat_results=[('Hello.', None)], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, [f'/image "{original}"', clear_command, 'Hello', '/exit'])
    assert not any(m.get('imageAttachments') for m in load_active_conversation_record(str(tmp_path))['messages'])


@pytest.mark.parametrize('clear', [False, True])
def test_multiline_image_commands_preserve_text_and_send_remaining_images(tmp_path, monkeypatch, clear):
    first = fixture_image(tmp_path, 'first image.png')
    second = tmp_path / 'second.png'
    Image.new('RGB', (80, 40), 'blue').save(second)
    captured = []
    deps = make_shell_deps(tmp_path, chat_results=[('Seen.', None)], generation_results=[], generation_calls=[])
    call = deps.chat_call_with_loading

    def capture(client, messages, *args, **kwargs):
        captured.append(copy.deepcopy(messages))
        return call(client, messages, *args, **kwargs)

    deps.chat_call_with_loading = capture
    run_shell(monkeypatch, deps, [
        '/ml', 'Compare these setups:', f'/image "{first}"',
        *(['/image clear'] if clear else []),
        f'/image "{tmp_path / "missing.png"}"', '', '  Keep this indentation.',
        f'/IMAGE "{second}"', '/end', '/exit',
    ])
    saved = load_active_conversation_record(str(tmp_path))['messages']
    user = next(m for m in saved if m['role'] == 'user')
    assert user['content'] == 'Compare these setups:\n\n  Keep this indentation.'
    assert [a['name'] for a in user['imageAttachments']] == (['second.png'] if clear else ['first image.png', 'second.png'])
    assert len(captured) == 1
    outgoing = prepare_image_messages(captured[0])[-1]['content']
    assert sum(part['type'] == 'image_url' for part in outgoing) == (1 if clear else 2)


def test_cancelled_multiline_restores_previously_queued_images(tmp_path, monkeypatch):
    first = fixture_image(tmp_path, 'first.png')
    second = tmp_path / 'second.png'
    Image.new('RGB', (80, 40), 'blue').save(second)
    deps = make_shell_deps(tmp_path, chat_results=[('Seen.', None)], generation_results=[], generation_calls=[])
    inputs = iter([f'/image "{first}"', '/ml', 'Discard this text.', '/image clear',
                   f'/image "{second}"', KeyboardInterrupt(), 'Describe the original.', '/exit'])

    def input_value(prompt=''):
        value = next(inputs)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', input_value)
    monkeypatch.setattr('sys.argv', ['workout_generator.py'])
    shell.main(deps=deps)
    user = next(m for m in load_active_conversation_record(str(tmp_path))['messages'] if m['role'] == 'user')
    assert user['content'] == 'Describe the original.'
    assert [a['name'] for a in user['imageAttachments']] == ['first.png']


def test_image_messages_cannot_approve_requirements(tmp_path):
    _, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    messages[-1]['imageAttachments'] = [save_image(fixture_image(tmp_path), tmp_path)]
    assert not requirements_approved(messages)
    assert requirement_sources(messages)[-1]['imageAttachments']


def test_multiline_image_positions_survive_save_resume_and_compaction(tmp_path, monkeypatch):
    first = fixture_image(tmp_path, 'rack.png')
    second = tmp_path / 'floor.png'
    Image.new('RGB', (80, 40), 'blue').save(second)
    deps = make_shell_deps(tmp_path, chat_results=[('Seen.', None)], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, [
        '/ml', f'/image "{first}"', 'The rack above is fixed.', f'/image "{second}"',
        'This floor space is available.', f'/image "{first}"', '/end', '/exit',
    ])
    # A repeated image retains its second position. Saved copies work after the originals disappear.
    first.unlink()
    second.unlink()
    saved = load_active_conversation_record(str(tmp_path))['messages']
    user = next(m for m in saved if m.get('imageAttachments'))
    assert [a['textOffset'] for a in user['imageAttachments']] == [0, len('The rack above is fixed.\n'), len(user['content'])]
    assert 'data:image' not in json.dumps(saved)
    for planning in (False, True):
        request = prepare_image_messages(shell._messages_for_api(saved, planning, provided_equipment=planning_case()[0]))
        parts = request[-1]['content']
        assert [p['type'] for p in parts] == ['text', 'image_url', 'text', 'image_url', 'text', 'image_url']
        assert parts[2]['text'] == 'The rack above is fixed.\n'
        assert parts[4]['text'] == 'This floor space is available.'
        assert parts[1]['image_url'] == parts[5]['image_url'] != parts[3]['image_url']
    sources = requirement_sources(saved)
    assert source_message_context(sources)['SOURCE_0']['images'][1]['textOffset'] == user['imageAttachments'][1]['textOffset']


@pytest.mark.parametrize('offset', [-1, 9999, True, '0'])
def test_invalid_saved_image_position_fails_before_request(tmp_path, offset):
    attachment = {**save_image(fixture_image(tmp_path), tmp_path), 'textOffset': offset}
    source = [{'role': 'user', 'content': 'Text.', 'imageAttachments': [attachment]}]
    for wrap in (lambda messages: messages, image_message):
        with pytest.raises(ValueError, match='Invalid saved image position'):
            prepare_image_messages(wrap(source))
