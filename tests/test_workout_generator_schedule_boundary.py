import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import joint_planning, session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError
from workout_generator_pkg.programming_guidelines import complete_training_schedule, audit_training_schedule
from test_workout_generator_joint_prescriptions import prescription_case
from test_workout_generator_planning_tools import planning_case


def week():
    return [{'name': name, 'timesCompletedInAWeek': 1} for name in ('A', 'B', 'C')]


def schedule_errors(workouts, spacing=1):
    report = {'issues': [], 'errors': []}
    audit_training_schedule(workouts, {'minimumRestDaysBetweenSessions': spacing}, report)
    return report['errors']


def test_code_assigns_a_repeating_calendar_when_days_are_omitted():
    source = week()
    result = complete_training_schedule(source, {'minimumRestDaysBetweenSessions': 1})
    assert [day['trainingDays'] for day in result] == [[0], [2], [4]]
    assert not schedule_errors(result)
    assert all('trainingDays' not in day for day in source)


def test_approved_weekdays_survive_code_scheduling_and_native_audit():
    requirements = {'sessionsPerWeek': 3, 'trainingDays': [1, 3, 5],
                    'minimumRestDaysBetweenSessions': 1}
    fixed = [{**week()[0], 'trainingDays': [3]}]
    result = complete_training_schedule(week()[1:], requirements, fixed)
    assert [day['trainingDays'] for day in result] == [[1], [5]]
    report = {'issues': [], 'errors': []}
    audit_training_schedule([*fixed, *result], requirements, report)
    assert not report['errors']
    result[0]['trainingDays'] = [0]
    audit_training_schedule([*fixed, *result], requirements, report)
    assert any(error['code'] == 'schedule_approved_days_mismatch' for error in report['errors'])


def test_explicit_weekdays_must_match_approved_frequency_without_changing_defaults():
    from workout_generator_pkg.planning_tools import _REQUIREMENTS, render_requirements
    from workout_generator_pkg.programming_policy import programming_policy_errors
    from jsonschema import validate

    _, requirements, _, _ = planning_case()
    original = copy.deepcopy(requirements)
    requirements.update(sessionsPerWeek=3, trainingDays=[1, 3, 5])
    validate(requirements, _REQUIREMENTS)
    assert not programming_policy_errors(requirements)
    assert 'Tuesday' in render_requirements(requirements)
    requirements['trainingDays'] = [1, 3]
    assert any(error['path'] == '/trainingDays' for error in programming_policy_errors(requirements))
    assert 'trainingDays' not in original


def test_calendar_respects_existing_sessions_and_explicit_weekdays():
    fixed = [{'name': 'Fixed', 'timesCompletedInAWeek': 1, 'trainingDays': [3]}]
    sessions = week()[:2]
    sessions[1]['trainingDays'] = [5]
    before = copy.deepcopy((fixed, sessions))
    result = complete_training_schedule(sessions, {'minimumRestDaysBetweenSessions': 1}, fixed)
    assert result[1]['trainingDays'] == [5]
    assert not schedule_errors([*fixed, *result])
    assert (fixed, sessions) == before


def test_calendar_handles_a_session_performed_more_than_once_weekly():
    sessions = week()[:2]
    sessions[0]['timesCompletedInAWeek'] = 2
    result = complete_training_schedule(sessions, {'minimumRestDaysBetweenSessions': 1})
    assert [len(day['trainingDays']) for day in result] == [2, 1]
    assert not schedule_errors(result)


def test_explicit_conflicting_calendar_is_not_silently_rewritten():
    sessions = week()
    for day in sessions:
        day['trainingDays'] = [0, 2, 4]
    assert complete_training_schedule(sessions, {'minimumRestDaysBetweenSessions': 1}) == sessions
    assert any(error['code'] == 'schedule_frequency_mismatch' for error in schedule_errors(sessions))


def test_calendar_conflict_does_not_relax_recovery_spacing():
    requirements = {'minimumRestDaysBetweenSessions': 2}
    sessions = complete_training_schedule(week(), requirements)
    assert all('trainingDays' not in day for day in sessions)
    assert requirements['minimumRestDaysBetweenSessions'] == 2
    assert schedule_errors(sessions, spacing=2)


def test_solver_rejects_invalid_calendar_before_recipe_audits(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    requirements['minimumRestDaysBetweenSessions'] = 1
    for day in sessions:
        day['trainingDays'] = [0, 2, 4]
    monkeypatch.setattr(joint_planning, '_audit_raw', lambda *a, **k: pytest.fail('No recipe audit should run'))
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['status'] == 'invalid_schedule' and not result['feasible']
    assert any(error['code'] == 'schedule_frequency_mismatch' for error in result['errors'])


def test_repair_solver_completes_omitted_calendar_with_the_same_problem_identity(monkeypatch):
    equipment, requirements, sessions = prescription_case()
    requirements['minimumRestDaysBetweenSessions'] = 1
    original = copy.deepcopy((requirements, sessions))
    scheduled = complete_training_schedule(sessions, requirements)
    assert not schedule_errors(scheduled)
    assert joint_planning.joint_problem_fingerprint(sessions, requirements, equipment) == (
        joint_planning.joint_problem_fingerprint(scheduled, requirements, equipment))

    class CalendarReached(Exception):
        pass

    def next_stage(workouts, budget):
        assert workouts == scheduled
        raise CalendarReached

    monkeypatch.setattr(joint_planning, '_source_working_set_budget_identity', next_stage)
    with pytest.raises(CalendarReached):
        joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert (requirements, sessions) == original


def retained_preparation():
    root = Path(__file__).resolve().parents[1] / 'build/workout_intake_three_set_fresh_e2e_20261029'
    if not root.exists():
        pytest.skip('The retained live run is not present in this checkout.')
    identifier = json.loads((root / 'conversation_meta.json').read_text(encoding='utf-8'))['active_conversation_id']
    messages = json.loads((root / 'workouts/conversation_sessions' / identifier / 'messages.json').read_text(encoding='utf-8'))
    def is_original_bad_preparation(index, message):
        if not any(call['function']['name'] == 'prepare_workout_sessions'
                   for call in message.get('tool_calls', [])):
            return False
        arguments = json.loads(message['tool_calls'][0]['function']['arguments'])
        if not arguments.get('sessions') or index + 1 >= len(messages):
            return False
        try:
            result = json.loads(messages[index + 1]['content'])
        except ValueError:
            return False
        return bool(result.get('preparationId') and any(
            len(day.get('trainingDays', [])) != day['timesCompletedInAWeek']
            for day in arguments['sessions']))

    index = next(index for index, message in enumerate(messages) if is_original_bad_preparation(index, message))
    arguments = json.loads(messages[index]['tool_calls'][0]['function']['arguments'])
    return arguments, messages[:index]


def test_retained_bad_schedule_stops_at_preparation_before_lookups_or_workers(monkeypatch):
    arguments, messages = retained_preparation()
    monkeypatch.setattr(session_drafting, 'get_exercise_candidates',
        lambda *a, **k: pytest.fail('Calendar errors must precede exercise lookups and workers'))
    with pytest.raises(PlanningInputError) as error:
        session_drafting._prepare_week(session_drafting._expand_preparation_blocks(arguments),
            messages, planning_case()[0])
    assert error.value.code == 'preparation_schedule_invalid'
    assert any(item['code'] == 'schedule_frequency_mismatch' for item in error.value.errors)


def test_retained_selection_can_use_code_calendar_without_changing_exercises(monkeypatch):
    arguments, messages = retained_preparation()
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload
    equipment = _load_exercise_library_payload(Path(__file__).resolve().parents[1] /
        'build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json')
    for day in arguments['sessions']:
        day.pop('trainingDays', None)
    captured = []

    class CalendarReached(Exception):
        pass

    def next_stage(sessions, *args, **kwargs):
        captured.extend(copy.deepcopy(sessions))
        raise CalendarReached

    monkeypatch.setattr(session_drafting, '_history_configuration_concerns', next_stage)
    with pytest.raises(CalendarReached):
        session_drafting._prepare_week(session_drafting._expand_preparation_blocks(arguments), messages, equipment)
    assert not schedule_errors(captured)
    assert [day['trainingDays'] for day in captured] == [[0], [2], [4]]
    assert all('trainingDays' not in day for day in arguments['sessions'])


def test_saved_worker_receipt_routes_bad_calendar_to_preparation_repair(monkeypatch):
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload
    from workout_generator_pkg.planning_tools import _latest_result
    _, messages = retained_preparation()
    root = Path(__file__).resolve().parents[1] / 'build/workout_intake_three_set_fresh_e2e_20261029'
    identifier = json.loads((root / 'conversation_meta.json').read_text(encoding='utf-8'))['active_conversation_id']
    messages = json.loads((root / 'workouts/conversation_sessions' / identifier / 'messages.json').read_text(encoding='utf-8'))
    failed_worker_index = next(index for index, message in enumerate(messages)
        if message.get('role') == 'tool' and 'jointUnresolvedCandidate' in message.get('content', '')
        and 'schedule_frequency_mismatch' in message['content'])
    messages = messages[:failed_worker_index + 1]
    _, prepared = _latest_result(messages, 'prepare_workout_sessions')
    _, previous = _latest_result(messages, 'draft_workout_sessions')
    equipment = _load_exercise_library_payload(root.parents[1] /
        'build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json')

    class History:
        fingerprint = prepared['historyFingerprint']

    monkeypatch.setattr(session_drafting, '_history_configuration_concerns',
        lambda *a, **k: pytest.fail('Saved calendar errors must be caught before qualification or workers'))
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, {'historyFingerprint': History.fingerprint}, training_history=History())
    assert not result['passed'] and result['preparationErrors']
    assert result['workerResults'] == previous['workerResults']
    assert result['workerInputHashes'] == previous['workerInputHashes']
    assert all(error.get('permittedPaths', {}).get('exact') for error in result['preparationErrors'])
    task = session_drafting.preparation_repair_task(messages, equipment)
    assert task and not task['needsAlternatives']
    assert task['permittedPaths'] == [f'/sessions/{i}/trainingDays' for i in range(3)]
