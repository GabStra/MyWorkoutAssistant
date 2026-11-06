import json

from workout_user_memory import create_profile, facts_for, record_fact
from workout_generator_pkg import interactive_shell
from workout_generator_pkg.conversation_store import load_active_conversation_record, save_conversation
from test_workout_generator_conversation_sessions import make_shell_deps, run_shell


def test_shell_reuses_profile_across_fresh_conversations_and_can_forget(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('MYWORKOUT_USER_MEMORY_DIR', str(tmp_path / 'memory'))
    profile = create_profile('First user')
    other = create_profile('Other user')
    fact = record_fact(profile['profileId'], kind='standing_preference', value='Prefer trackable exercises.',
                       source={'role': 'user', 'statement': 'Prefer trackable exercises.'})
    record_fact(other['profileId'], kind='standing_preference', value='OTHER_USER_PRIVATE_FACT',
                source={'role': 'user', 'statement': 'OTHER_USER_PRIVATE_FACT'})
    monkeypatch.setenv('MYWORKOUT_PROFILE_ID', profile['profileId'])
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    requests = []

    def respond(client, messages, *args, **kwargs):
        requests.append(json.dumps(messages))
        assert all('userMemory' not in message for message in messages)
        return 'Ready to discuss the program.', None, None

    deps.chat_call_with_loading = respond
    run_shell(monkeypatch, deps, ['Plan a workout', '/clear', 'Plan another workout', '/memory',
                                  '/memory forget ' + fact['factId'], '/exit'])
    assert len(requests) == 2
    assert all('Prefer trackable exercises.' in request for request in requests)
    assert all('OTHER_USER_PRIVATE_FACT' not in request for request in requests)
    assert not facts_for(profile['profileId'])['facts']
    assert facts_for(other['profileId'])['facts']
    record = load_active_conversation_record(str(tmp_path))
    assert record['metadata']['userProfileId'] == profile['profileId']
    assert 'Removed the fact from active user memory' in capsys.readouterr().out


def test_shell_rejects_resuming_another_profile(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('MYWORKOUT_USER_MEMORY_DIR', str(tmp_path / 'memory'))
    current, other = create_profile('Current'), create_profile('Other')
    monkeypatch.setenv('MYWORKOUT_PROFILE_ID', current['profileId'])
    save_conversation([{'role': 'user', 'content': 'OTHER_USER_PRIVATE_FACT'}],
                      conversation_id='other-conversation', script_dir=str(tmp_path),
                      metadata={'userProfileId': other['profileId']})
    deps = make_shell_deps(tmp_path, chat_results=[('Hello', None)], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ['Hello', '/resume-conversation other-conversation', '/exit'])
    output = capsys.readouterr().out
    assert 'Cannot resume conversation' in output
    assert 'OTHER_USER_PRIVATE_FACT' not in output
    record = load_active_conversation_record(str(tmp_path))
    assert record['conversation_id'] != 'other-conversation'
    assert record['metadata']['userProfileId'] == current['profileId']


def test_review_does_not_treat_historical_fact_positions_as_transcript_indexes(tmp_path):
    from workout_generator_pkg.plan_review import _review_sources
    from workout_generator_pkg.planning_tools import requirement_sources, source_message_context
    from workout_generator_pkg.user_memory_context import bind_user_memory

    profile = create_profile('User', root=tmp_path)
    for value in ('First standing preference', 'Second standing preference', 'Third standing preference'):
        record_fact(profile['profileId'], kind='standing_preference', value=value,
                    source={'role': 'user', 'statement': value}, root=tmp_path)
    messages = []
    bind_user_memory(messages, profile['profileId'], root=tmp_path)
    messages.extend([{'role': 'assistant', 'content': 'Prior candidate', 'canonicalAlternativePreview': True},
                     {'role': 'user', 'content': 'Review the current plan.'}])
    sources = source_message_context(requirement_sources(messages))
    reviewed = _review_sources({'sourceMessages': sources}, messages, len(messages) - 1)
    assert all(f'SOURCE_{index}' in reviewed for index in range(3))
    assert 'SOURCE_3' not in reviewed and reviewed['SOURCE_4']['content'] == 'Review the current plan.'


def _approved_profile_case(tmp_path):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg.planning_tools import set_workout_requirements, requirements_approved
    from workout_generator_pkg.user_memory_context import bind_user_memory

    equipment, requirements, _, _ = planning_case()
    profile = create_profile('User', root=tmp_path)['profileId']
    record_fact(profile, kind='standing_preference', value='Prefer trackable exercises.',
                source={'role': 'user', 'statement': 'Prefer trackable exercises.'}, root=tmp_path)
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets'}]
    bind_user_memory(messages, profile, equipment, root=tmp_path)
    stored = set_workout_requirements(requirements, messages, equipment)
    messages = requirement_messages(stored)[1:]  # The fixture copies source rows as transcript turns.
    bind_user_memory(messages, profile, equipment, root=tmp_path)
    assert requirements_approved(messages)
    return profile, equipment, messages


def test_keep_requirements_preserves_memory_origin_without_fabricating_user_turns(tmp_path):
    from workout_generator_pkg.planning_decisions import seed_approved_policy_context
    from workout_generator_pkg.planning_tools import requirement_sources
    from workout_generator_pkg.user_memory_context import bind_user_memory

    profile, equipment, messages = _approved_profile_case(tmp_path)
    initial = [{'role': 'system', 'content': 'Planner'}]
    bind_user_memory(initial, profile, equipment, root=tmp_path)
    carried = seed_approved_policy_context(messages, initial, equipment)
    assert carried is not None and not carried.get('blockedReason')
    assert not any(message['role'] == 'user' and 'Previously confirmed' in message.get('content', '')
                   for message in carried['messages'])
    assert len(requirement_sources(carried['messages'])) == 2


def test_reloaded_standing_memory_requires_current_requirements_approval(tmp_path):
    from workout_generator_pkg.planning_tools import requirements_approved
    from workout_generator_pkg.user_memory_context import bind_user_memory

    profile, equipment, messages = _approved_profile_case(tmp_path)
    record_fact(profile, kind='standing_restriction', value='Exclude push-ups.',
                source={'role': 'user', 'statement': 'Exclude push-ups.'}, root=tmp_path)
    bind_user_memory(messages, profile, equipment, root=tmp_path)
    assert not requirements_approved(messages)
