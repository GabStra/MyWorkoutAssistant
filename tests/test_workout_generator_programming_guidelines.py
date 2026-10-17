import copy
import json

import pytest

from workout_generator_pkg import plan_review
from workout_generator_pkg.planning_tools import (
    PlanningInputError, audit_workout_plan, confirmed_draft, set_workout_requirements,
)
from workout_generator_pkg.programming_guidelines import GUIDELINE_POLICY
from test_workout_generator_planning_tools import planning_case, requirement_messages


def case(rules):
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets'] = {'weeklyEffectiveSets': {}, 'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 10000}
    requirements['requiredCoverage'] = [
        {'key': key, 'description': key + ' work', 'scope': 'eachSession'} for key in ('priority', 'accessory')]
    requirements['executionRules'] = rules
    sources = [{'role': 'user', 'content': 'Priority work before accessories, with ramp-ups and straight sets. '
                'Rest 120–180s between priority sets, 30–45s between superset partners, and 60–90s after a round.'}]
    stored = set_workout_requirements(requirements, sources, equipment)
    draft['requirementsId'] = stored['requirementsId']
    priority = draft['workouts'][0]['exercises'][0]
    priority.update(satisfiesCoverage=['priority'], numWorkSets=3, restBetweenSetsSeconds=150, generateWarmUpSets=True)
    accessory = copy.deepcopy(priority)
    accessory.update(satisfiesCoverage=['accessory'], generateWarmUpSets=False)
    draft['workouts'][0]['exercises'].append(accessory)
    return equipment, requirements, stored, draft


def store_audit(messages, result):
    return messages + [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(result)},
    ]


def test_execution_violations_block_preview_and_repair_with_json_patch(monkeypatch):
    from workout_generator_pkg.interactive_shell import handle_function_call
    calls = []

    def review(client, request, **options):
        calls.append(request)
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, 'chat_call', review)
    rules = [
        {'kind': 'order', 'before': 'priority', 'after': 'accessory'},
        {'kind': 'warmup', 'coverageKey': 'priority'},
        {'kind': 'rest', 'coverageKey': 'priority', 'context': 'straightSets', 'minimumSeconds': 120, 'maximumSeconds': 180},
    ]
    equipment, _, stored, draft = case(rules)
    assert '### Execution rules' in stored['requirementsPreview']
    day = draft['workouts'][0]
    day['exercises'].reverse()
    day['exercises'][1].update(generateWarmUpSets=False, restBetweenSetsSeconds=15)
    messages = requirement_messages(stored)
    failed = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)['result'])
    assert not failed['passed'] and 'preview' not in failed
    assert not calls  # Deterministic failures do not spend a reviewer call.
    assert {e['code'] for e in failed['errors']} == {'execution_order', 'execution_warmup', 'execution_rest'}
    assert all(e['rulePath'].startswith('/executionRules/') and e['repair'] for e in failed['errors'])
    messages = store_audit(messages, failed)
    with pytest.raises(ValueError, match='passing'):
        confirmed_draft(messages, equipment)
    patch = {
        'requirementsId': stored['requirementsId'], 'baseDraftId': failed['currentDraftId'], 'patch': [
            {'op': 'replace', 'path': '/workouts/0/exercises/1/generateWarmUpSets', 'value': True},
            {'op': 'replace', 'path': '/workouts/0/exercises/1/restBetweenSetsSeconds', 'value': 150},
            {'op': 'move', 'from': '/workouts/0/exercises/1', 'path': '/workouts/0/exercises/0'},
        ]}
    repaired = json.loads(handle_function_call(None, messages, 'audit_workout_plan', patch, equipment)['result'])
    assert repaired['passed'] and repaired['currentDraftId'] != failed['currentDraftId']
    assert len(calls) == 1
    assert repaired['audit']['executionGuidelines']['findings'] == 0
    assert repaired['requirementsId'] == stored['requirementsId']
    assert [e['numWorkSets'] for e in repaired['submittedDraft']['workouts'][0]['exercises']] == [3, 3]


def test_superset_rules_use_actual_member_rests_and_treat_whole_group_as_one_block():
    rules = [
        {'kind': 'straightSets', 'coverageKey': 'priority'},
        {'kind': 'order', 'before': 'priority', 'after': 'accessory'},
        {'kind': 'rest', 'coverageKey': None, 'context': 'supersetTransition', 'minimumSeconds': 30, 'maximumSeconds': 45},
        {'kind': 'rest', 'coverageKey': None, 'context': 'supersetRound', 'minimumSeconds': 60, 'maximumSeconds': 90},
    ]
    equipment, _, stored, draft = case(rules)
    a, b = draft['workouts'][0]['exercises']
    a.update(superset='pair', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=20)
    b.update(superset='pair', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=50)
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert {e['code'] for e in failed['errors']} == {'execution_straightSets', 'execution_order', 'execution_rest'}
    rest_errors = [e for e in failed['errors'] if e['code'] == 'execution_rest']
    assert [e['actual'] for e in rest_errors] == [20, 50]
    assert all(e['path'].endswith('/restAfterSupersetExerciseSeconds') for e in rest_errors)
    # Once the priority stands alone, approved lower/upper rest boundaries both pass.
    a.update(superset=None, restBetweenSetsSeconds=150, restAfterSupersetExerciseSeconds=0)
    b.update(restAfterSupersetExerciseSeconds=30)
    c = copy.deepcopy(b)
    c.update(restAfterSupersetExerciseSeconds=90)
    draft['workouts'][0]['exercises'].append(c)
    passed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert passed['passed'], passed['errors']


@pytest.mark.parametrize('context,grouped', [('straightSets', False), ('supersetRound', True)])
def test_one_set_does_not_require_an_unexecuted_recovery(context, grouped):
    equipment, _, stored, draft = case([
        {'kind': 'rest', 'coverageKey': None, 'context': context, 'minimumSeconds': 120, 'maximumSeconds': 180}])
    for item in draft['workouts'][0]['exercises']:
        item.update(numWorkSets=1, restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=0,
                    superset='pair' if grouped else None)
    assert audit_workout_plan(draft, equipment, requirement_messages(stored))['passed']


@pytest.mark.parametrize('rule', [
    {'kind': 'straightSets', 'coverageKey': 'invented'},
    {'kind': 'order', 'before': 'priority', 'after': 'priority'},
    {'kind': 'rest', 'coverageKey': None, 'context': 'straightSets', 'minimumSeconds': 90, 'maximumSeconds': 60},
])
def test_invalid_rule_references_and_ranges_rejected_before_approval(rule):
    with pytest.raises(PlanningInputError) as error:
        case([rule])
    assert error.value.code == 'invalid_execution_rule'
    assert error.value.path == '/executionRules/0'


def test_reviewer_and_planner_share_policy_without_extra_calls(monkeypatch):
    from workout_generator_pkg.interactive_shell import _messages_for_api
    equipment, _, stored, draft = case([])
    messages = requirement_messages(stored)
    calls = []

    def respond(client, request, **options):
        assert options['reasoning_effort'] == 'low'
        context = json.loads(request[-1]['content'])
        calls.append(context)
        assert context['programmingGuidelines']['version'] == GUIDELINE_POLICY['version']
        return json.dumps({'findings': [{
            'severity': 'blocking', 'basis': 'uncertainty', 'muscleTargets': [],
            'path': context['draft']['exercises'][0]['_reviewRef'],
            'message': 'The priority may be affected by the preceding work.',
            'evidencePaths': [context['programmingGuidelines']['_reviewRef']],
            'repair': 'Consider placing the priority first if performance suffers.',
        }]}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    result = plan_review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    assert len(calls) == 1 and result['passed']
    assert result['review']['findings'][0]['severity'] == 'warning'
    assert 'Independent review notes:' in result['preview']
    request = _messages_for_api(store_audit(messages, result), True, provided_equipment=equipment)
    state = next(json.loads(m['content'].split('\n', 1)[1]) for m in request if m['content'].startswith('Current planning state'))
    assert state['programmingGuidelines'] == GUIDELINE_POLICY


def test_export_note_limit_includes_python_calibration_guidance():
    from workout_generator_pkg.planning_tools import build_draft_plan, _NOTES_SCHEMA
    from workout_generator_pkg.cli import _materialize_exercise_definition
    equipment, requirements, _, draft = case([])
    item = draft['workouts'][0]['exercises'][0]
    item.update(requiresEffortCalibration=True, placementNotes='x' * 280)
    plan = build_draft_plan(draft, equipment, requirements)
    emitted = _materialize_exercise_definition(plan['exercises'][0])
    assert len(emitted['placementNotes']) <= _NOTES_SCHEMA['maxLength'] == 500
    assert emitted['placementNotes'].startswith(item['placementNotes'])
    assert 'Calibration attempts are additional to working sets' in emitted['placementNotes']
    item['placementNotes'] = 'x' * 490
    with pytest.raises(PlanningInputError) as error:
        build_draft_plan(draft, equipment, requirements)
    assert error.value.code == 'export_notes_too_long'
    assert error.value.path.endswith('/placementNotes')


def test_explicit_setup_replaces_default_and_reaches_final_uuid_audit():
    from workout_generator_pkg.generation_audit import audit_workout_package, plan_audit_package
    equipment, _, stored, draft = case([])
    second = draft['workouts'][0]['exercises'][1]
    del second['setupSeconds']
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert any(e['code'] == 'setup_time_required' for e in failed['errors'])
    second['setupSeconds'] = 120
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']
    assert result['audit']['workouts'][0]['timing']['transitionSeconds'] == 120
    package = plan_audit_package(result['planIndex'])
    for index, exercise in enumerate(package['workouts'][0]['workoutComponents']):
        exercise.pop('setupSeconds', None)
        exercise['id'] = f'converted-{index}'
    final = audit_workout_package(package, stored['requirements']['auditTargets'], setup_seconds_by_exercise={'converted-1': 120})
    assert final['workouts'][0]['estimatedSeconds'] == result['audit']['workouts'][0]['estimatedSeconds']
    assert final['workouts'][0]['setupEstimates'][0]['basis'] == 'declared_estimate'
    invalid = audit_workout_package(package, stored['requirements']['auditTargets'], setup_seconds_by_exercise={'converted-1': -120})
    assert invalid['errors'][0]['code'] == 'invalid_setup_time'


def test_rest_rules_select_immutable_library_category_without_coverage_labels():
    rule = {'kind': 'rest', 'coverageKey': None, 'exerciseCategory': 'MODERATE_COMPOUND',
            'context': 'straightSets', 'minimumSeconds': 90, 'maximumSeconds': 150}
    equipment, _, stored, draft = case([rule])
    item = draft['workouts'][0]['exercises'][1]
    item['restBetweenSetsSeconds'] = 60
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert any(e['code'] == 'execution_rest' and e['path'].endswith('/1/restBetweenSetsSeconds') for e in failed['errors'])
    item['restBetweenSetsSeconds'] = 90
    assert audit_workout_plan(draft, equipment, requirement_messages(stored))['passed']


def test_weekly_schedule_checks_full_rest_days_including_wraparound():
    equipment, requirements, _, draft = case([])
    requirements.update(sessionsPerWeek=3, minimumRestDaysBetweenSessions=1)
    stored = set_workout_requirements(requirements, [], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'] = [copy.deepcopy(draft['workouts'][0]) for _ in range(3)]
    messages = requirement_messages(stored)
    assert any(e['code'] == 'schedule_days_required' for e in audit_workout_plan(draft, equipment, messages)['errors'])
    for day, weekday in zip(draft['workouts'], (0, 2, 6)):
        day['trainingDays'] = [weekday]
    failed = audit_workout_plan(draft, equipment, messages)
    assert any(e['code'] == 'schedule_recovery_gap' and e['actual'] == 0 for e in failed['errors'])
    draft['workouts'][2]['trainingDays'] = [4]
    passing = audit_workout_plan(draft, equipment, messages)
    assert passing['passed']
    assert 'Schedule: Friday.' in passing['planIndex']['workouts'][2]['description']


def test_no_reconfiguration_rule_checks_common_load_or_explicit_calibration():
    from workout_generator_pkg.programming_guidelines import audit_execution_rules
    equipment, requirements, _, draft = case([{'kind': 'supersetNoReconfiguration', 'coverageKey': None}])
    entries = draft['workouts'][0]['exercises']
    plan = {'exercises': [{'id': str(i), 'equipmentId': 'shared'} for i in range(2)],
            'workouts': [{'exerciseIds': ['0', '1']}]}
    def check():
        report = {'issues': [], 'errors': []}
        audit_execution_rules(draft, requirements, report, plan)
        return report
    for item, load in zip(entries, (10, 14)):
        item.update(superset='pair', targetSetPrescriptions=[{'workSetIndex': 0, 'reps': 10, 'weight': load}])
    assert check()['errors'][0]['code'] == 'execution_supersetNoReconfiguration'
    entries[1]['targetSetPrescriptions'][0]['weight'] = 10
    assert not check()['errors']
    for item in entries:
        del item['targetSetPrescriptions']
    assert check()['errors']
    for item in entries:
        item['requiresEffortCalibration'] = True
    assert not check()['errors']


def test_history_rep_conflict_uses_requested_rir_instead_of_assuming_equal_reps():
    from test_workout_generator_training_history import history_case
    from workout_generator_pkg.training_history import TrainingHistory
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, stored, draft, backup = history_case()
    requirements = stored['requirements']
    requirements['workingSetRIR'] = {'minimum': 1, 'maximum': 2}
    plan = build_draft_plan(draft, equipment, requirements)
    def concerns():
        history = TrainingHistory(backup)
        evidence = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
        messages = [{'role': 'assistant', 'tool_calls': [{'id': 'evidence', 'function': {'name': 'get_training_evidence'}}]},
                    {'role': 'tool', 'tool_call_id': 'evidence', 'content': json.dumps(evidence)}]
        return history.load_suitability_errors(plan, messages, equipment)
    assert concerns() == []  # Historical 12 reps vs 10 prescribed can fit the requested 2 RIR.
    backup['SetHistories'][0]['setData']['actualReps'] = 27
    assert concerns()[0]['concerns'][0]['code'] == 'historical_reps_exceed_prescription'
    plan['exercises'][0]['requiresEffortCalibration'] = True
    assert concerns() == []


def test_canonical_export_preserves_setup_timing_without_model_repairs(tmp_path, monkeypatch):
    from dataclasses import replace
    from workout_generator_pkg import cli
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    from test_workout_generator_planning_tools import approved_messages
    equipment, requirements, _, draft = case([])
    equipment['exerciseDefinitions'][0]['id'] = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    stored = set_workout_requirements(requirements, [], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][1]['setupSeconds'] = 120
    messages = requirement_messages(stored)
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = plan_review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    assert result['passed']
    messages = approved_messages(stored, result)
    def forbidden(*a, **k):
        raise AssertionError('Approved canonical export must not use model repair or emission.')
    monkeypatch.setattr(cli, 'json_call_chat_max_with_loading', forbidden)
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', forbidden)
    deps = resolve_pipeline_deps()
    validation_attempts = []
    def validate(*args, **kwargs):
        validation_attempts.append(kwargs['max_attempts'])
        return deps.validate_and_repair_placeholder_json(*args, **kwargs)
    exported = execute_workout_generation(None, messages, provided_equipment=equipment, script_dir=str(tmp_path),
        force_use_reasoner=False, deps=replace(deps, test_connection=lambda *a, **k: (True, None),
            validate_and_repair_placeholder_json=validate))
    assert exported['success'], exported['error']
    assert validation_attempts == [1]
    from pathlib import Path
    reports = list(Path(tmp_path).rglob('*.audit.json')) + list(Path(tmp_path).rglob('*audit*.json'))
    report = next(json.loads(path.read_text(encoding='utf-8')) for path in reports
                  if 'setupEstimates' in path.read_text(encoding='utf-8'))
    assert report['workouts'][0]['timing']['transitionSeconds'] == 120
    # Planned time uses upper rep targets; emitted reps may take less work time.
    assert report['workouts'][0]['estimatedSeconds'] <= result['audit']['workouts'][0]['estimatedSeconds']
