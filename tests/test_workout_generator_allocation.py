import copy
import json
import pytest

from workout_generator_pkg.allocation import allocate_workout_sets, allocation_slots
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def test_selection_preflight_rejects_only_proven_relaxed_volume_conflicts():
    from workout_generator_pkg.allocation import selection_volume_conflicts
    days = [{'definition_ids':['LIBRARY_0'],'timesCompletedInAWeek':1} for _ in range(3)]
    candidates = {'LIBRARY_0':{'creditsPerWorkingSet':{'chest':{'direct':1,'indirect':0},'shoulders':{'direct':0,'indirect':0.5}}},
                  'LIBRARY_1':{'creditsPerWorkingSet':{'chest':{'direct':1,'indirect':0}}}}
    targets = {'weeklyEffectiveSets':{'chest':{'minimum':15,'maximum':18},'shoulders':{'minimum':0,'maximum':6}}}
    conflicts = selection_volume_conflicts(days,candidates,targets)
    assert {c['target'] for c in conflicts} == {'weekly:chest','weekly:shoulders'}
    shoulder = next(item for item in conflicts if item['target']=='weekly:shoulders')
    assert shoulder['rangeWithOtherConflictingTargets'] == pytest.approx([7.5,9])
    assert shoulder['rangeWithOtherConflictingTargets'][0] > shoulder['maximum']
    for day in days:
        day['definition_ids'].append('LIBRARY_1')
    assert not selection_volume_conflicts(days,candidates,targets)


def test_allocation_problem_identity_ignores_soft_counts_and_presentation_only_edits():
    from workout_generator_pkg.allocation import allocation_input_fingerprint
    equipment, _, stored, draft = planning_case()
    identity = lambda value: allocation_input_fingerprint(value, stored['requirementsId'], equipment)
    original = identity(draft)
    cosmetic = copy.deepcopy(draft)
    cosmetic['workouts'][0].update(name='Renamed', description='Short label')
    exercise = cosmetic['workouts'][0]['exercises'][0]
    exercise.update(numWorkSets=2, placementNotes='Different cue')
    assert identity(cosmetic) == original
    changed = copy.deepcopy(cosmetic)
    changed['workouts'][0]['exercises'][0]['setupSeconds'] += 10
    assert identity(changed) != original
    changed = copy.deepcopy(draft)
    changed['workouts'][0]['exercises'][0]['definition_id'] = 'LIBRARY_1'
    assert identity(changed) != original


def test_infeasible_count_problem_blocks_repeat_with_different_soft_preferences(monkeypatch):
    from workout_generator_pkg import allocation
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 500
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    messages, audit = _audited_messages(equipment, stored, draft)
    request = {'requirementsId': stored['requirementsId'], 'baseDraftId': audit['currentDraftId'],
        'boundsBySlot': {'SLOT_0': {'minimum': 5, 'maximum': 6}}, 'preferredSetsBySlot': {'SLOT_0': 5}}
    first = allocate_workout_sets(request, equipment, messages)
    assert first['status'] == 'infeasible'
    conflict = first['allocationConflict']
    assert conflict['requirementsId'] == stored['requirementsId']
    assert conflict['baseDraftId'] == audit['currentDraftId']
    assert conflict['conflictFingerprint']
    call = {'id': 'allocation', 'type': 'function', 'function': {
        'name': 'allocate_workout_sets', 'arguments': json.dumps(request)}}
    messages.extend([{'role': 'assistant', 'tool_calls': [call]},
        {'role': 'tool', 'tool_call_id': 'allocation', 'content': json.dumps(first)}])
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'bad-allocation', 'type': 'function',
        'function': {'name': 'allocate_workout_sets', 'arguments': '{"preferredSetsBySlot": "invalid"}'}}]},
        {'role': 'tool', 'tool_call_id': 'bad-allocation', 'content': json.dumps({'passed': False,
            'errors': [{'code': 'invalid_arguments'}]})}])
    def fail_if_solver_runs(*args, **kwargs):
        pytest.fail('Same proven infeasible problem must be blocked before resolving with new soft preferences')
    monkeypatch.setattr(allocation, '_milp_solve', fail_if_solver_runs)
    repeated = allocate_workout_sets({**request, 'preferredSetsBySlot': {'SLOT_0': 12}}, equipment, messages)
    assert repeated['status'] == 'infeasible'
    assert repeated['allocationConflict'] == conflict
    assert 'soft set preferences cannot change feasibility' in repeated['reason']


def _audited_messages(equipment, stored, draft):
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "audit", "function": {
            "name": "audit_workout_plan", "arguments": json.dumps(draft)}}]},
        {"role": "tool", "tool_call_id": "audit", "content": json.dumps(result)},
    ])
    return messages, result


def test_allocation_returns_minimal_patch_and_exact_numeric_summary():
    equipment, _, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 6}},
    }, equipment, messages)

    assert allocated["feasible"]
    assert allocated["patch"] == [{"op": "replace", "path": "/workouts/0/exercises/0/numWorkSets", "value": 5}]
    assert allocated["summary"]["weeklyEffectiveSets"]["chest"] == 5
    assert allocated["summary"]["sessions"][0]["estimatedSeconds"] == 810
    assert result["submittedDraft"]["workouts"][0]["exercises"][0]["numWorkSets"] == 3


def test_soft_count_preferences_steer_design_without_requiring_a_numeric_failure():
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [
        {'key': key, 'description': key, 'scope': 'weekly'} for key in ('role_a', 'role_b')]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 1, 'maximumSets': 4}]
    stored = set_workout_requirements(requirements, [])
    draft['requirementsId'] = stored['requirementsId']
    template = draft['workouts'][0]['exercises'][0]
    draft['workouts'][0]['exercises'] = [
        {**copy.deepcopy(template), 'numWorkSets': 3, 'allocationBounds': {'minimum': 1, 'maximum': 4},
         'satisfiesCoverage': [key]} for key in ('role_a', 'role_b')]
    messages, current = _audited_messages(equipment, stored, draft)
    assert current['passed']
    request = {'requirementsId': stored['requirementsId'], 'baseDraftId': current['currentDraftId'],
        'boundsBySlot': {slot: {'minimum': 1, 'maximum': 4} for slot in ('SLOT_0', 'SLOT_1')},
        'preferredSetsBySlot': {'SLOT_0': 1, 'SLOT_1': 4}}
    proposed = allocate_workout_sets(request, equipment, messages)
    assert proposed['feasible']
    assert proposed['patch'] == [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 1},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/numWorkSets', 'value': 4}]
    assert proposed['summary']['weeklyCoverageSets'] == {'role_a': 1, 'role_b': 4}
    assert not proposed['summary']['preferenceDifferences']
    request['preferredSetsBySlot'] = {'SLOT_0': 20, 'SLOT_1': 20}
    constrained = allocate_workout_sets(request, equipment, messages)
    assert constrained['feasible']
    assert not constrained['preferencesSatisfied'] and 'NOT achieved' in constrained['nextStep']
    assert constrained['summary']['weeklyEffectiveSets']['chest'] == 6
    assert all(1 <= item['allocated'] <= 4 for item in constrained['summary']['preferenceDifferences'].values())
    assert [e['numWorkSets'] for e in draft['workouts'][0]['exercises']] == [3, 3]


@pytest.mark.parametrize('preferences', [[], {'SLOT_99': 3}, {'SLOT_0': True}, {'SLOT_0': 0}, {'SLOT_0': 21}])
def test_soft_preferences_reject_invalid_references_and_counts(preferences):
    equipment, _, stored, draft = planning_case()
    messages, current = _audited_messages(equipment, stored, draft)
    result = allocate_workout_sets({'requirementsId': stored['requirementsId'], 'baseDraftId': current['currentDraftId'],
        'boundsBySlot': {}, 'preferredSetsBySlot': preferences}, equipment, messages)
    assert not result['feasible'] and 'preferredSetsBySlot' in result['reason']
    assert 'patch' not in result


@pytest.mark.parametrize('shown_preview', [False, True])
def test_automatic_allocation_balances_only_before_a_preview_is_shown(monkeypatch, shown_preview):
    from workout_generator_pkg import allocation, joint_planning
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0].update(numWorkSets=7, allocationBounds={'minimum': 1, 'maximum': 7})
    messages, result = _audited_messages(equipment, stored, draft)
    if shown_preview:
        messages.append({'role': 'assistant', 'content': 'Reviewed plan', 'canonicalDraftPreview': 'previous'})
    calls = []
    solve = allocation._milp_solve
    def record(variables, features, **options):
        calls.append(options.get('balance', False))
        return solve(variables, features, **options)
    monkeypatch.setattr(joint_planning, '_milp_solve', record)
    repaired = allocation.auto_allocate_workout(result, equipment, messages)
    assert repaired['passed'] is not shown_preview
    assert calls and not any(calls)
    assert repaired['automaticAllocation']['objective'] == 'joint_prescriptions'
    assert repaired['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] == (7 if shown_preview else 6)
    if shown_preview:
        assert repaired['automaticAllocation']['application'] == 'proposal'
        assert any(patch['path'].endswith('/numWorkSets') and patch['value'] == 6
                   for patch in repaired['automaticAllocation']['patch'])
    assert draft['workouts'][0]['exercises'][0]['numWorkSets'] == 7


def test_cached_joint_allocation_is_recomputed_when_solver_inputs_change(monkeypatch):
    from workout_generator_pkg import allocation, joint_planning
    from workout_generator_pkg.planning_tools import set_workout_requirements, library_fingerprint
    from workout_generator_pkg.restriction_policy import effective_restrictions

    equipment, requirements, _, draft = planning_case()
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Plan a 3-day full-body hypertrophy program.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 7
    messages, result = _audited_messages(equipment, stored, draft)
    assert any(error['code'] == 'volume_above_target' for error in result['errors'])

    restrictions = effective_restrictions(stored, equipment)
    original_problem = joint_planning.joint_problem_fingerprint(draft['workouts'], stored['requirements'], equipment,
        messages=messages, restriction_policy=restrictions, preserve_source_selection=True)
    cached = {'inputDraftId': result['draftId'], 'objective': 'joint_prescriptions',
        'application': 'automatic', 'selectionPolicyVersion': joint_planning.SELECTION_POLICY_VERSION,
        'preserveSourceSelection': True, 'problemFingerprint': original_problem,
        'feasible': False, 'status': 'infeasible', 'instruction': 'Old infeasibility.'}
    messages[-1]['content'] = json.dumps({**result, 'automaticAllocation': cached})

    changed_equipment = copy.deepcopy(equipment)
    changed_equipment['exerciseDefinitions'][0]['name'] += ' revised'
    assert library_fingerprint(changed_equipment) != library_fingerprint(equipment)
    calls = []

    def solve(*args, **kwargs):
        calls.append(kwargs)
        return {'feasible': False, 'status': 'unproven', 'problemFingerprint': 'fresh',
            'instruction': 'Recomputed with current inputs.'}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    repaired = allocation.auto_allocate_workout(result, changed_equipment, messages)

    assert calls
    assert repaired['automaticAllocation']['instruction'] == 'Recomputed with current inputs.'


def test_cached_joint_allocation_is_recomputed_when_solver_policy_changes(monkeypatch):
    from workout_generator_pkg import allocation, joint_planning
    from workout_generator_pkg.planning_tools import set_workout_requirements
    from workout_generator_pkg.restriction_policy import effective_restrictions

    equipment, requirements, _, draft = planning_case()
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Plan a 3-day full-body hypertrophy program.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 7
    messages, result = _audited_messages(equipment, stored, draft)
    assert any(error['code'] == 'volume_above_target' for error in result['errors'])

    current_problem = joint_planning.joint_problem_fingerprint(draft['workouts'], stored['requirements'], equipment,
        messages=messages, restriction_policy=effective_restrictions(stored, equipment),
        preserve_source_selection=True)
    old_policy = {'inputDraftId': result['draftId'], 'objective': 'joint_prescriptions',
        'application': 'automatic', 'selectionPolicyVersion': joint_planning.SELECTION_POLICY_VERSION - 1,
        'preserveSourceSelection': True, 'problemFingerprint': current_problem,
        'feasible': False, 'status': 'invalid_options', 'instruction': 'Stale source occurrence result.'}
    messages[-1]['content'] = json.dumps({**result, 'automaticAllocation': old_policy})
    calls = []

    def solve(*args, **kwargs):
        calls.append(kwargs)
        return {'feasible': False, 'status': 'infeasible', 'problemFingerprint': 'fresh',
            'instruction': 'Recomputed under the current solver policy.'}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    repaired = allocation.auto_allocate_workout(result, equipment, messages)

    assert calls
    assert repaired['automaticAllocation']['problemFingerprint'] == 'fresh'


def test_automatic_allocation_repairs_numeric_counts_without_waiving_setup_findings():
    from workout_generator_pkg.allocation import auto_allocate_workout
    equipment, _, stored, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first.update(numWorkSets=1, allocationBounds={'minimum': 1, 'maximum': 5})
    second = copy.deepcopy(first)
    second.update(numWorkSets=2)
    second.pop('allocationBounds')
    second.pop('setupSeconds')
    draft['workouts'][0]['exercises'].append(second)
    messages, result = _audited_messages(equipment, stored, draft)
    assert {error['code'] for error in result['errors']} >= {'volume_below_target', 'setup_time_required'}
    repaired = auto_allocate_workout(result, equipment, messages)
    assert repaired['automaticAllocation']['feasible']
    assert repaired['audit']['weeklyVolume']['chest']['effective'] == 5
    assert repaired['passed']  # The redundant occurrence can be omitted rather than inventing its setup.
    assert all('setupSeconds' in item for item in repaired['submittedDraft']['workouts'][0]['exercises'][1:])
    assert [item['numWorkSets'] for item in result['submittedDraft']['workouts'][0]['exercises']] == [1, 2]


def test_legacy_allocator_bounds_cannot_widen_approved_count_limits():
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 3, 'maximumSets': 5}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use 3-5 sets per exercise.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['allocationBounds'] = {'minimum': 3, 'maximum': 5}
    messages, result = _audited_messages(equipment, stored, draft)
    request = {'requirementsId': stored['requirementsId'], 'baseDraftId': result['currentDraftId'],
               'boundsBySlot': {'SLOT_0': {'minimum': 20, 'maximum': 20}}, 'preferredSetsBySlot': {'SLOT_0': 20}}
    allocated = allocate_workout_sets(request, equipment, messages)
    assert allocated['feasible'] and not allocated['patch']
    assert allocated['summary']['weeklyEffectiveSets']['chest'] == 5
    assert draft['workouts'][0]['exercises'][0]['numWorkSets'] == 5


@pytest.mark.parametrize('kind,load_field,load', [('WEIGHT', 'weight', 10.0), ('BODY_WEIGHT', 'additionalWeight', 0)])
@pytest.mark.parametrize('initial,expected', [(3, 5), (7, 5)])
def test_uniform_template_allows_bounded_count_allocation_and_exact_materialization(monkeypatch, kind, load_field, load, initial, expected):
    from workout_generator_pkg.allocation import auto_allocate_workout
    from workout_generator_pkg import cli, plan_review
    equipment, _, stored, draft = planning_case()
    if kind == 'WEIGHT':
        equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 10.0, 'plates': []}]
        equipment['exerciseDefinitions'][0].update(exerciseType=kind, equipmentId='EQUIPMENT_0', bodyWeightPercentage=None)
    item = draft['workouts'][0]['exercises'][0]
    item.update(numWorkSets=initial, allocationBounds={'minimum': 3, 'maximum': 7},
                workSetTemplate={'reps': 9, load_field: load})
    from workout_generator_pkg.planning_tools import set_workout_requirements
    explicit = {**stored['requirements'], 'executionRules': [{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 3, 'maximumSets': 7}]}
    stored = set_workout_requirements(explicit, [{'role': 'user', 'content': 'Use 3-7 working sets per exercise.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages, result = _audited_messages(equipment, stored, draft)
    before = copy.deepcopy(result)
    allocated = auto_allocate_workout(result, equipment, messages)
    assert allocated['passed'] and allocated['automaticAllocation']['feasible']
    source = allocated['submittedDraft']['workouts'][0]['exercises'][0]
    assert source['numWorkSets'] == expected and source['workSetTemplate'] == item['workSetTemplate']
    assert 'targetSetPrescriptions' not in source and result == before
    entry = allocated['planIndex']['exercises'][0]
    assert entry['targetSetPrescriptions'] == [
        {'workSetIndex': index, 'reps': 9, load_field: load} for index in range(expected)]
    monkeypatch.setattr(cli, 'json_call_chat_max_with_loading', lambda *a, **k: pytest.fail('No model for template expansion'))
    emitted, _ = cli.emit_exercise_definition(entry['id'], None, '', allocated['planIndex'],
        equipment_subset=equipment['equipments'], accessory_subset=[], provided_equipment=equipment, deterministic=True)
    assert [(s['reps'], s[load_field]) for s in emitted['sets'] if s['type'] != 'RestSet'] == [(9, load)] * expected
    assert 'workSetTemplate' not in entry and 'workSetTemplate' not in emitted
    assert plan_review._draft_patch_path('/draft/exercises/0/targetSetPrescriptions/1/reps',
        allocated['planIndex'], allocated['submittedDraft']) == '/workouts/0/exercises/0/workSetTemplate'
    context = plan_review._context(allocated, messages, equipment, None, len(messages) - 1)
    assert context['templateExerciseIds'] == ['EXERCISE_0']
    assert result['submittedDraft'] == draft


def test_infeasible_volume_and_duration_reports_conflict_without_patch():
    equipment, requirements, _, draft = planning_case()
    requirements["auditTargets"]["maximumSessionSeconds"] = 500
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 6}},
    }, equipment, messages)

    assert not allocated["feasible"]
    assert "approved count constraints" in allocated["reason"]
    assert "patch" not in allocated


def test_coupled_infeasibility_identifies_conflicting_targets_without_relaxing_them():
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets'] = {'weeklyEffectiveSets': {
        muscle: {'minimum': 5, 'maximum': 6} for muscle in ('quads', 'hamstrings', 'glutes')},
        'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}
    stored = set_workout_requirements(requirements, [])
    draft['requirementsId'] = stored['requirementsId']
    equipment['exerciseDefinitions'][0].update(name='Quad movement', muscleGroups=['FRONT_QUADRICEPS', 'BACK_GLUTEAL'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0], 'id': 'zzz',
        'name': 'Hamstring movement', 'muscleGroups': ['BACK_HAMSTRING', 'BACK_GLUTEAL']})
    first = draft['workouts'][0]['exercises'][0]
    first['numWorkSets'] = 3
    draft['workouts'][0]['exercises'].append({**copy.deepcopy(first), 'definition_id': 'LIBRARY_1'})
    messages, result = _audited_messages(equipment, stored, draft)
    before = copy.deepcopy(draft)
    proposal = allocate_workout_sets({'requirementsId': stored['requirementsId'], 'baseDraftId': result['currentDraftId'],
        'boundsBySlot': {slot: {'minimum': 1, 'maximum': 10} for slot in ('SLOT_0', 'SLOT_1')}}, equipment, messages)
    assert not proposal['feasible'] and 'patch' not in proposal
    assert {item['target'] for item in proposal['conflictingTargets']} == {'weekly:quads', 'weekly:hamstrings', 'weekly:glutes'}
    assert all(item['minimum'] == 5 and item['maximum'] == 6 for item in proposal['conflictingTargets'])
    assert {item['target']: item['rangeWithinSlotBounds'] for item in proposal['conflictingTargets']} == {
        'weekly:quads': [1, 20], 'weekly:hamstrings': [1, 20], 'weekly:glutes': [2, 40]}
    assert draft == before


def test_conflict_explanation_does_not_mislabel_integer_only_failure():
    from workout_generator_pkg.allocation import _conflicting_targets
    assert _conflicting_targets([{'lower': 1, 'upper': 4}], [(('weekly', 'chest'), 3.5, 3.5, 0, [1.0])]) == []


def test_conflicts_report_all_unreachable_bounds_and_remaining_coupled_targets():
    from workout_generator_pkg.allocation import _conflicting_targets
    variables = [{'lower': 1, 'upper': 4, 'members': [{'slotId': f'SLOT_{i}'}]} for i in range(3)]
    features = [(('weekly', 'chest'), 5, 6, 0, [0, 0, 1]),
                (('weekly', 'back'), 6, 7, 5, [0, 0, -1]),
                (('weekly', 'quads'), 3, 4, 0, [1, 0, 0]),
                (('weekly', 'hamstrings'), 3, 4, 0, [0, 1, 0]),
                (('weekly', 'glutes'), 2, 5, 0, [1, 1, 0])]
    before = copy.deepcopy((variables, features))
    conflicts = {item['target']: item for item in _conflicting_targets(variables, features)}
    assert set(conflicts) == {'weekly:chest', 'weekly:back', 'weekly:quads', 'weekly:hamstrings', 'weekly:glutes'}
    for target in ('weekly:chest', 'weekly:back'):
        assert conflicts[target]['individuallyUnreachable']
        assert conflicts[target]['rangeWithinSlotBounds'] == [1, 4]
        assert 'rangeWithOtherConflictingTargets' not in conflicts[target]
    assert conflicts['weekly:glutes']['rangeWithOtherConflictingTargets'][0] == 6
    assert (variables, features) == before


@pytest.mark.parametrize('duration_limit', [None, 500])
@pytest.mark.parametrize('omitted_sets', [1, 2])
def test_legacy_omitted_slots_do_not_create_false_locks(duration_limit, omitted_sets):
    equipment, requirements, stored, draft = planning_case()
    requirements["auditTargets"]["weeklyEffectiveSets"] = {
        "glutes": {"minimum": 0, "maximum": 1},
        "shoulders": {"minimum": 0, "maximum": 1},
    }
    requirements["auditTargets"]["perSessionEffectiveSets"] = {}
    requirements["auditTargets"]["maximumSessionSeconds"] = duration_limit
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    equipment["exerciseDefinitions"][0]["muscleGroups"] = ["FRONT_CHEST", "BACK_GLUTEAL", "FRONT_DELTOIDS"]
    equipment["exerciseDefinitions"][0]["secondaryMuscleGroups"] = []
    equipment["exerciseDefinitions"].append({
        "id": "glute-shoulder", "name": "Glute Shoulder Compound", "exerciseType": "BODY_WEIGHT",
        "equipmentId": None, "bodyWeightPercentage": 65, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["BACK_GLUTEAL", "FRONT_DELTOIDS"], "secondaryMuscleGroups": [],
        "exerciseCategory": "MODERATE_COMPOUND",
    })
    draft["workouts"][0]["exercises"].append({
        **copy.deepcopy(draft["workouts"][0]["exercises"][0]), "definition_id": "LIBRARY_1", "numWorkSets": omitted_sets,
    })
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 5}},
    }, equipment, messages)

    assert not allocated["feasible"]
    assert "does not establish" in allocated["reason"]
    json.dumps(allocated, allow_nan=False)
    assert allocated['allocationDiagnostics'] == []  # No omitted slot is artificially frozen now.
    assert {item['target'] for item in allocated['conflictingTargets']} >= {'weekly:glutes', 'weekly:shoulders'}
    assert draft['workouts'][0]['exercises'][1]['numWorkSets'] == omitted_sets


def test_allocation_uses_actual_non_unit_weekly_frequency():
    equipment, requirements, _, draft = planning_case()
    requirements["sessionsPerWeek"] = 2
    requirements["auditTargets"]["weeklyEffectiveSets"]["chest"] = {"minimum": 10, "maximum": 12}
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    draft["workouts"][0]["timesCompletedInAWeek"] = 2
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 5, "maximum": 6}},
    }, equipment, messages)

    assert allocated["feasible"]
    assert allocated["summary"]["weeklyEffectiveSets"]["chest"] == 10
    assert allocated["summary"]["completeWeek"] is True


def test_allocation_probes_downward_when_current_count_is_at_maximum():
    equipment, _, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 20
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 1, "maximum": 20}},
    }, equipment, messages)

    assert allocated["feasible"]
    assert allocated["patch"] == [{"op": "replace", "path": "/workouts/0/exercises/0/numWorkSets", "value": 6}]


def test_superset_occurrences_are_allocated_as_one_equal_count_group():
    equipment, requirements, stored, draft = planning_case()
    requirements["auditTargets"]["weeklyEffectiveSets"] = {}
    requirements["auditTargets"]["perSessionEffectiveSets"] = {}
    from workout_generator_pkg.planning_tools import set_workout_requirements
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    first = draft["workouts"][0]["exercises"][0]
    first.update(superset="A", restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=40)
    second = copy.deepcopy(first)
    second["numWorkSets"] = 3
    second["restAfterSupersetExerciseSeconds"] = 75
    draft["workouts"][0]["exercises"].append(second)
    messages, result = _audited_messages(equipment, stored, draft)

    allocated = allocate_workout_sets({
        "requirementsId": stored["requirementsId"],
        "baseDraftId": result["currentDraftId"],
        "boundsBySlot": {"SLOT_0": {"minimum": 2, "maximum": 3}},
    }, equipment, messages)

    assert allocated["feasible"]
    updated = copy.deepcopy(draft)
    for op in allocated["patch"]:
        index = int(op["path"].split("/")[4])
        updated["workouts"][0]["exercises"][index]["numWorkSets"] = op["value"]
    assert [item["numWorkSets"] for item in updated["workouts"][0]["exercises"]] == [3, 3]
    assert {op["path"] for op in allocated["patch"]} == {
        "/workouts/0/exercises/0/numWorkSets"}


def test_exact_prescriptions_and_stale_slot_or_base_are_rejected():
    equipment, _, stored, draft = planning_case()
    exercise = draft["workouts"][0]["exercises"][0]
    exercise["targetSetPrescriptions"] = [
        {"workSetIndex": index, "reps": 9, "additionalWeight": 0} for index in range(5)]
    exercise["numWorkSets"] = 5
    messages, result = _audited_messages(equipment, stored, draft)

    allocation = {"requirementsId": stored["requirementsId"], "baseDraftId": result["currentDraftId"],
                  "boundsBySlot": {"SLOT_0": {"minimum": 4, "maximum": 4}}}
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert rejected["feasible"] and not rejected['patch']
    assert rejected['summary']['weeklyEffectiveSets']['chest'] == 5

    allocation["boundsBySlot"] = {"SLOT_9": {"minimum": 1, "maximum": 2}}
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "Unknown slot" in rejected["reason"]

    allocation["boundsBySlot"] = {}
    allocation["baseDraftId"] = "REVISION_stale"
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "stale" in rejected["reason"]

    allocation["baseDraftId"] = result["currentDraftId"]
    payload = json.loads(messages[-1]["content"])
    payload["submittedDraft"]["requirementsId"] = "REQUIREMENTS_OLD"
    messages[-1]["content"] = json.dumps(payload)
    rejected = allocate_workout_sets(allocation, equipment, messages)
    assert not rejected["feasible"]
    assert "different requirements" in rejected["reason"]


def test_slot_references_are_deterministic_occurrence_ids():
    _, _, _, draft = planning_case()
    draft["workouts"].append(copy.deepcopy(draft["workouts"][0]))
    slots = allocation_slots(draft)
    assert list(slots) == ["SLOT_0", "SLOT_1"]
    assert slots["SLOT_1"]["path"] == "/workouts/1/exercises/0"
