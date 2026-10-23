import copy
import json

import pytest

from workout_generator_pkg import plan_review
from workout_generator_pkg.planning_tools import (
    PlanningInputError, audit_workout_plan, confirmed_draft, set_workout_requirements,
)
from workout_generator_pkg.programming_guidelines import GUIDELINE_POLICY, approved_work_set_bounds
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


def test_fresh_two_set_policy_bounds_solver_domain_and_rejects_raw_single_set():
    equipment, _, stored, draft = case([])
    item = draft['workouts'][0]['exercises'][0]
    definition = {'exerciseCategory': 'MODERATE_COMPOUND'}
    assert approved_work_set_bounds(item, definition, stored['requirements']) == {'minimum': 2, 'maximum': 20}

    item['numWorkSets'] = 1
    with pytest.raises(PlanningInputError) as error:
        audit_workout_plan({'requirementsId': stored['requirementsId'], 'name': 'Week',
            'workouts': draft['workouts']}, equipment, requirement_messages(stored))
    assert error.value.code == 'set_count_outside_allocation_bounds'

    from workout_generator_pkg.programming_guidelines import audit_execution_rules
    report = {'issues': [], 'errors': []}
    audit_execution_rules(draft, stored['requirements'], report)
    assert any(issue['code'] == 'execution_workSets' and issue['path'].endswith('/numWorkSets')
               for issue in report['errors'])


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


def test_unexecuted_one_set_rest_is_not_normalized_or_described_as_applicable():
    from workout_generator_pkg.joint_planning import _rest_options
    from workout_generator_pkg.programming_guidelines import render_execution_rule

    equipment, _, stored, draft = case([
        {'kind': 'rest', 'coverageKey': None, 'context': 'straightSets', 'minimumSeconds': 120, 'maximumSeconds': 180}])
    item = draft['workouts'][0]['exercises'][0]
    item.update(numWorkSets=1, restBetweenSetsSeconds=105)
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda value: value['id']))}
    rule = stored['requirements']['executionRules'][0]
    variants = list(_rest_options([item], stored['requirements'], definitions, 1))
    assert variants == [[item]]
    variants = list(_rest_options([item], stored['requirements'], definitions, 2))
    assert len(variants) == 2 and variants[-1][0]['restBetweenSetsSeconds'] == 120
    assert 'only when at least two working sets are prescribed' in render_execution_rule(rule)


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
        return json.dumps({'findings': []}), None, None

    monkeypatch.setattr(plan_review, 'chat_call', respond)
    result = plan_review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    assert len(calls) == 1 and result['passed']
    request = _messages_for_api(store_audit(messages, result), True, provided_equipment=equipment)
    state = next(json.loads(m['content'].split('\n', 1)[1]) for m in request if m['content'].startswith('Current planning state'))
    assert state['programmingGuidelines'] == GUIDELINE_POLICY


def test_export_preserves_local_notes_without_adding_calibration_protocol():
    from workout_generator_pkg.planning_tools import build_draft_plan, placement_notes_limit
    from workout_generator_pkg.cli import _materialize_exercise_definition
    equipment, requirements, _, draft = case([])
    item = draft['workouts'][0]['exercises'][0]
    item.update(placementNotes='x' * placement_notes_limit({}))
    plan = build_draft_plan(draft, equipment, requirements)
    emitted = _materialize_exercise_definition(plan['exercises'][0])
    assert emitted['placementNotes'].startswith(item['placementNotes'])
    assert 'calibration' not in emitted['placementNotes'].lower()
    assert 'trial' not in emitted['placementNotes'].lower()


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


def test_no_reconfiguration_rule_requires_a_verified_common_load():
    from workout_generator_pkg.programming_guidelines import audit_execution_rules
    equipment, requirements, _, draft = case([{'kind': 'supersetNoReconfiguration', 'coverageKey': None}])
    entries = draft['workouts'][0]['exercises']
    plan = {'exercises': [{'id': str(i), 'equipmentId': 'shared'} for i in range(2)],
            'workouts': [{'exerciseIds': ['0', '1']}]}
    def check():
        report = {'issues': [], 'errors': []}
        audit_execution_rules(draft, requirements, report, plan)
        return report
    for item in entries:
        item.update(superset='pair')
    for item, load in zip(plan['exercises'], (10, 14)):
        item['targetSetPrescriptions'] = [{'workSetIndex': 0, 'reps': 10, 'weight': load}]
    assert check()['errors'][0]['code'] == 'execution_supersetNoReconfiguration'
    plan['exercises'][1]['targetSetPrescriptions'][0]['weight'] = 10
    assert not check()['errors']
    plan['exercises'][0]['requiresLoadCalibration'] = True
    assert check()['errors']  # Equal targets cannot establish independently calibrated loads.
    plan['exercises'][0]['requiresLoadCalibration'] = False
    assert not check()['errors']
    for item in plan['exercises']:
        del item['targetSetPrescriptions']
    assert check()['errors']
    for item in plan['exercises']:
        item['requiresLoadCalibration'] = True
    assert check()['errors']  # Native calibration chooses each exercise's load independently.


@pytest.mark.parametrize('kind, field, load, adjustable, passes', [
    ('WEIGHT', 'weight', 10, True, False), ('BODY_WEIGHT', 'additionalWeight', 0, True, False),
    ('WEIGHT', 'weight', 10, False, True),
])
def test_common_load_checks_distinguish_adjustable_calibration_from_fixed_equipment(kind, field, load, adjustable, passes):
    equipment, requirements, _, draft = case([{'kind': 'supersetNoReconfiguration', 'coverageKey': None}])
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 10.0,
                                'sleeveLength': 100,
                                'availablePlates': [{'weight': 5.0, 'thickness': 1.0}] * 2 if adjustable else []}]
    definition = equipment['exerciseDefinitions'][0]
    definition.update(exerciseType=kind, equipmentId='EQUIPMENT_0', bodyWeightPercentage=65 if kind == 'BODY_WEIGHT' else None)
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Superset partners keep the same shared load.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    for index, item in enumerate(draft['workouts'][0]['exercises']):
        item.update(superset='pair', restBetweenSetsSeconds=0, restAfterExerciseSeconds=0, restAfterSupersetExerciseSeconds=90 if index else 30,
                    workSetTemplate={'reps': 9, field: load})
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed'] is passes, result.get('errors')
    if not passes:
        assert any(error['code'] == 'execution_supersetNoReconfiguration' for error in result['errors'])


def test_history_rep_conflict_uses_requested_rir_instead_of_assuming_equal_reps():
    from test_workout_generator_training_history import history_case
    from workout_generator_pkg.training_history import TrainingHistory
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, stored, draft, backup = history_case()
    requirements = stored['requirements']
    requirements['workingSetRIR'] = {'minimum': 1, 'maximum': 2}
    for day in draft['workouts']:
        for exercise in day['exercises']:
            exercise.pop('effortAcceptance', None)
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
    plan['exercises'][0]['requiresLoadCalibration'] = True
    assert concerns()  # This fixture is unequipped bodyweight, which has no native load mode.


@pytest.mark.parametrize(('program_guidance', 'emitter_guidance', 'fail_guidance_write', 'final_mutation', 'alias_renumbering'), [
    (None, None, False, None, False),
    ('Use a lighter week after the next hard block.', None, False, None, False),
    ('Use a lighter week after the next hard block.', 'Emitter guess; ignore recovery signals.', False, None, False),
    ('Use a lighter week after the next hard block.', None, True, None, False),
    (None, None, False, 'order', False),
    (None, None, False, 'sets', False),
    (None, None, False, 'guidance', False),
    (None, None, False, None, True),
])
def test_canonical_export_preserves_setup_timing_without_model_repairs(
    tmp_path, monkeypatch, program_guidance, emitter_guidance, fail_guidance_write, final_mutation, alias_renumbering
):
    from dataclasses import replace
    from workout_generator_pkg import cli
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation
    from test_workout_generator_planning_tools import approved_messages
    equipment, requirements, _, draft = case([])
    selected = equipment['exerciseDefinitions'][0]
    if alias_renumbering:
        selected['id'] = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        unselected = copy.deepcopy(selected)
        unselected.update(id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name='Unused Push-Up Variant')
        equipment['exerciseDefinitions'].append(unselected)
        for day in draft['workouts']:
            for exercise in day['exercises']:
                exercise['definition_id'] = 'LIBRARY_1'
    else:
        selected['id'] = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    stored = set_workout_requirements(requirements, [], equipment)
    draft['requirementsId'] = stored['requirementsId']
    if program_guidance:
        draft['programGuidance'] = program_guidance
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
    if final_mutation:
        apply_schema = deps.apply_exercise_library_schema_v2
        def mutate_final(*args, **kwargs):
            final = apply_schema(*args, **kwargs)
            components = final['workouts'][0]['workoutComponents']
            if final_mutation == 'order':
                components.reverse()
            elif final_mutation == 'sets':
                components[0]['sets'][0]['reps'] += 1
            else:
                components[0]['notes'] += ' Unreviewed advice.'
            return final
        deps = replace(deps, apply_exercise_library_schema_v2=mutate_final)
    emit_workout_structure = deps.emit_workout_structure
    if emitter_guidance:
        def emit_with_unapproved_guidance(*args, **kwargs):
            structure, conversation = emit_workout_structure(*args, **kwargs)
            structure['programGuidance'] = emitter_guidance
            return structure, conversation
        deps = replace(deps, emit_workout_structure=emit_with_unapproved_guidance)
    validation_attempts = []
    def validate(*args, **kwargs):
        validation_attempts.append(kwargs['max_attempts'])
        return deps.validate_and_repair_placeholder_json(*args, **kwargs)
    if fail_guidance_write:
        import builtins
        open_file = builtins.open
        def fail_sidecar(path, *args, **kwargs):
            if str(path).endswith('.guidance.md'):
                raise OSError('sidecar write failed')
            return open_file(path, *args, **kwargs)
        monkeypatch.setattr(builtins, 'open', fail_sidecar)
    exported = execute_workout_generation(None, messages, provided_equipment=equipment, script_dir=str(tmp_path),
        force_use_reasoner=False, deps=replace(deps, test_connection=lambda *a, **k: (True, None),
            validate_and_repair_placeholder_json=validate))
    if final_mutation:
        assert not exported['success']
        assert 'differs from the independently reviewed artifact' in exported['error']
        return
    if fail_guidance_write:
        assert not exported['success'] and 'sidecar write failed' in exported['error']
        return
    assert exported['success'], exported['error']
    assert validation_attempts == [1]
    from pathlib import Path
    saved_workout = json.loads(Path(exported['filepath']).read_text(encoding='utf-8'))
    assert 'programGuidance' not in saved_workout
    assert 'placementNotes' not in json.dumps(saved_workout)
    assert 'Working-set acceptance' in json.dumps(saved_workout)
    assert exported['guidance_filepath'] == str(Path(exported['filepath']).with_suffix('.guidance.md'))
    guidance = Path(exported['guidance_filepath']).read_text(encoding='utf-8')
    assert 'Code-computed credit sources:' in guidance
    assert 'request a re-audit before changing set counts' in guidance
    if program_guidance:
        assert program_guidance not in guidance
        if emitter_guidance:
            assert emitter_guidance not in guidance
        assert 'not included in the phone or watch workout data' in guidance
    from workout_generator_pkg.interactive_shell import _metadata_for_generation_result
    metadata = _metadata_for_generation_result(exported, None)
    assert exported['guidance_filepath'] in metadata['generated_output_paths']
    reports = list(Path(tmp_path).rglob('*.audit.json')) + list(Path(tmp_path).rglob('*audit*.json'))
    report = next(json.loads(path.read_text(encoding='utf-8')) for path in reports
                  if 'setupEstimates' in path.read_text(encoding='utf-8'))
    from workout_generator_pkg.generation_audit import render_plan_disclosures
    assert render_plan_disclosures(report, stored['requirements']['auditTargets']['weeklyEffectiveSets'],
        result['submittedDraft'], stored['requirements'].get('requiredCoverage', [])) in guidance
    assert report['workouts'][0]['timing']['transitionSeconds'] == 120
    # Planned time uses upper rep targets; emitted reps may take less work time.
    assert report['workouts'][0]['estimatedSeconds'] <= result['audit']['workouts'][0]['estimatedSeconds']


def test_directional_coverage_comparison_is_rendered_as_soft_source_backed_preference():
    from workout_generator_pkg.programming_guidelines import render_execution_rule

    rendered = render_execution_rule({'kind': 'coverageBalance', 'first': 'lateral',
        'second': 'horizontal', 'scope': 'weekly',
        'relationship': 'first_not_less_than_second'})
    assert 'lateral' in rendered and 'horizontal' in rendered
    assert 'at least as much exposure' in rendered
    assert 'not a fixed ratio or hard minimum' in rendered
