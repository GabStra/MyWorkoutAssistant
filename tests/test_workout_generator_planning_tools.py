import copy
import json
from dataclasses import replace

import pytest

from workout_generator_pkg.planning_tools import (
    PlanningInputError, audit_workout_plan, confirmed_draft, set_workout_requirements, planning_tool_failure,
)


def planning_case():
    equipment = {"equipments": [], "accessoryEquipments": [], "exerciseDefinitions": [{
        "id": "press", "name": "Push-Up", "exerciseType": "BODY_WEIGHT", "equipmentId": None,
        "bodyWeightPercentage": 65, "requiredAccessoryEquipmentIds": [],
        "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": ["BACK_TRICEPS"],
        "exerciseCategory": "MODERATE_COMPOUND",
    }]}
    requirements = {"auditTargets": {"weeklyEffectiveSets": {"chest": {"minimum": 5, "maximum": 6}},
                    "perSessionEffectiveSets": {"chest": {"minimum": 5, "maximum": 6}},
                    "maximumSessionSeconds": 1000}, "sessionsPerWeek": 1, "notes": "Working sets at 1–2 RIR."}
    stored = set_workout_requirements(requirements, [{"role": "user", "content": "Plan 5-6 chest sets"}])
    draft = {"name": "Program", "requirementsId": stored["requirementsId"], "workouts": [{
        "name": "Day A", "description": "Full body", "timesCompletedInAWeek": 1,
        "exercises": [{"definition_id": "LIBRARY_0", "numWorkSets": 5, "minReps": 8, "maxReps": 10,
                       "durationSeconds": None, "restBetweenSetsSeconds": 90, "restAfterExerciseSeconds": 0,
                       "superset": None, "restAfterSupersetExerciseSeconds": 0,
                       "intraSetRestInSeconds": None, "generateWarmUpSets": False, "setupSeconds": 60,
                       "placementNotes": "Controlled reps.", "effortAcceptance": {
                           "kind": "technical_criteria", "minimumRIR": None, "maximumRIR": None,
                           "acceptanceCriterion": "Each repetition reaches the same controlled range of motion.",
                           "terminationCriterion": "Stop when range shortens or the trunk loses position."}}],
    }]}
    return equipment, requirements, stored, draft


def test_reordering_promotes_code_default_setup_for_new_transition():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    equipment, requirements, stored, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first.pop('setupSeconds')
    second = copy.deepcopy(first)
    first['numWorkSets'] = 4
    second['numWorkSets'] = 2
    second['setupSeconds'] = 30
    draft['workouts'][0]['exercises'].append(second)
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1',
            'currentDraft': draft, 'requirements': requirements}
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1', 'edits': {
        'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_1', 'EXERCISE_0']}],
    }}

    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    candidate = apply_json_patch(draft, compiled['patch'])
    audited = audit_workout_plan(candidate, equipment, requirement_messages(stored))

    assert audited['passed']
    assert audited['submittedDraft']['workouts'][0]['exercises'][1]['setupSeconds'] == 60
    assert audited['audit']['workouts'][0]['timing']['transitionSeconds'] == 60


def requirement_messages(stored):
    # These unit fixtures represent an already source-reviewed requirement set.
    from workout_generator_pkg.plan_review import REQUIREMENTS_REVIEW_VERSION, _requirements_context, _hash
    stored = copy.deepcopy(stored)
    from workout_generator_pkg.generation_audit import ASSUMPTIONS
    stored['sourceReview'] = {'version': REQUIREMENTS_REVIEW_VERSION, 'passed': True, 'findings': [], 'auditPolicy': copy.deepcopy(ASSUMPTIONS),
                            'inputHash': _hash(_requirements_context(stored))}
    return [{key: m[key] for key in ('role', 'content')} for m in stored.get('sourceMessages', [])] + [
            {"role": "assistant", "tool_calls": [{"id": "requirements", "function": {"name": "set_workout_requirements"}}]},
            {"role": "tool", "tool_call_id": "requirements", "content": json.dumps(stored)},
            {"role": "assistant", "content": stored["requirementsPreview"], "canonicalRequirementsPreview": stored["requirementsId"]},
            {"role": "user", "content": "CONFIRM REQUIREMENTS"}]


def test_requirements_approval_uses_its_reviewed_snapshot_after_new_decision():
    from workout_generator_pkg.planning_tools import requirements_approved

    _, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    assert requirements_approved(messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'new-decision', 'function': {'name': 'record_planning_decisions'}}]},
        {'role': 'tool', 'tool_call_id': 'new-decision', 'content': json.dumps({
            'passed': True, 'decisionReview': {'passed': True}, 'decisions': {
                'DECISION_0': {'topic': 'Numerical objective order',
                    'choice': 'Distribution then soft movement balance.', 'sourceReferences': ['SOURCE_0']}}})}])
    assert requirements_approved(messages)


def test_empty_requirement_refresh_after_consumed_decision_keeps_approved_base():
    from workout_generator_pkg.planning_tools import active_requirement_result

    _, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    stored = json.loads(messages[-3]['content'])
    draft = {'requirementsId': stored['requirementsId'], 'workouts': []}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps({
            'passed': False, 'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
            'currentDraft': draft, 'submittedDraft': draft, 'libraryFingerprint': 'LIB',
            'historyFingerprint': None, 'review': {'findings': []}})},
        {'role': 'user', 'content': 'Accept the disclosed soft preference for this exact candidate.'},
    ])
    boundary = len(messages) - 1
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'decision', 'function': {
            'name': 'record_planning_decisions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'decision', 'content': json.dumps({
            'passed': True, 'decisionReview': {'passed': True, 'instructionBoundary': boundary}})},
        {'role': 'assistant', 'tool_calls': [{'id': 'refresh', 'function': {
            'name': 'set_workout_requirements', 'arguments': json.dumps({
                'baseRequirementsId': 'REQUIREMENTS_REJECTED', 'updates': {}})}}]},
    ])
    refreshed = copy.deepcopy(stored)
    refreshed.update(requirementsId='REQUIREMENTS_NOOP', baseRequirementsId='REQUIREMENTS_REJECTED',
        passed=False, sourceReview={**stored['sourceReview'], 'passed': False})
    messages.append({'role': 'tool', 'tool_call_id': 'refresh', 'content': json.dumps(refreshed)})

    recovered_index, recovered = active_requirement_result(messages)
    assert recovered_index < len(messages) - 2
    assert recovered['requirementsId'] == stored['requirementsId']

    changed = copy.deepcopy(refreshed)
    changed['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] += 1
    messages[-1]['content'] = json.dumps(changed)
    candidate_index, candidate = active_requirement_result(messages)
    assert candidate_index == len(messages) - 1
    assert candidate['requirementsId'] == 'REQUIREMENTS_NOOP'
def test_duration_balance_tolerance_is_optional_approved_requirement_and_respects_hard_cap():
    from workout_generator_pkg.planning_tools import workout_requirements_tool

    equipment, arguments, _, _ = planning_case()
    properties = workout_requirements_tool(equipment)['function']['parameters']['properties']
    schema = properties['durationBalanceToleranceSeconds']
    assert schema['type'] == 'integer' and schema['minimum'] == 0
    assert 'explicit numeric tolerance' in schema['description']

    arguments['objectiveOrder'] = ['duration_balance', 'distribution']
    arguments['durationBalanceToleranceSeconds'] = 300
    stored = set_workout_requirements(arguments, [{'role': 'user', 'content':
        'Prefer similar session durations, allowing up to a 5-minute difference.'}], equipment)
    assert stored['requirements']['durationBalanceToleranceSeconds'] == 300
    assert 'spreads up to **5 minutes** count as equally balanced' in stored['requirementsPreview']
    assert 'this is not a hard session limit' in stored['requirementsPreview']

    update_schema = workout_requirements_tool(equipment, source_checked_unconfirmed_messages(stored))
    update_properties = update_schema['function']['parameters']['properties']['updates']['properties']
    assert update_properties['durationBalanceToleranceSeconds']['minimum'] == 0
    assert 'durationBalanceToleranceSeconds' not in set_workout_requirements(
        {key: value for key, value in planning_case()[1].items()},
        [{'role': 'user', 'content': 'Plan chest sets.'}], equipment)['requirements']

    over_limit = copy.deepcopy(arguments)
    over_limit['durationBalanceToleranceSeconds'] = 1001
    with pytest.raises(PlanningInputError) as error:
        set_workout_requirements(over_limit, [{'role': 'user', 'content': 'Plan chest sets.'}], equipment)
    assert error.value.code == 'duration_balance_tolerance_exceeds_session_limit'

    orphaned = copy.deepcopy(arguments)
    orphaned['objectiveOrder'] = ['distribution']
    with pytest.raises(PlanningInputError) as error:
        set_workout_requirements(orphaned, [{'role': 'user', 'content': 'Plan chest sets.'}], equipment)
    assert error.value.code == 'duration_balance_tolerance_without_objective'


def test_exercise_distribution_is_explicit_ordered_priority_and_rendered_for_approval():
    from workout_generator_pkg.planning_tools import workout_requirements_tool

    equipment, requirements, _, _ = planning_case()
    requirements['objectiveOrder'] = [
        'demand_distribution', 'duration_balance', 'source_balance', 'exercise_distribution',
        'workload_economy', 'distribution']
    source = ('Prioritize demand reduction, similar session durations, movement balance, qualified exercise-family '
        'distribution, lower total weekly working sets, then session muscle-set distribution.')
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': source}], equipment)

    objective_schema = workout_requirements_tool(equipment)['function']['parameters']['properties']['objectiveOrder']
    assert 'exercise_distribution' in objective_schema['items']['enum']
    assert 'workload_economy' in objective_schema['items']['enum']
    assert 'unknown pools are omitted rather than treated as diverse' in objective_schema['description']
    assert 'objectiveOrder is authoritative' in objective_schema['description']
    assert 'The approved policy order is' not in objective_schema['description']
    assert 'Development intent never inserts extra-exposure objectives' in objective_schema['description']
    assert 'app owns progression and load calibration' in objective_schema['description']
    assert stored['requirements']['objectiveOrder'] == requirements['objectiveOrder']
    assert ('Approved optimization order: reduce known per-session demand peaks, then balance estimated '
            'session durations, then reduce source-backed movement set-count differences, then spread exposure '
            'across qualified exercises, then minimize physical working sets across the week, then reduce '
            'muscle-set concentration across sessions.') in stored['requirementsPreview']


def approved_messages(stored, result):
    return requirement_messages(stored) + [
        {"role": "assistant", "tool_calls": [{"id": "draft", "function": {"name": "audit_workout_plan"}}]},
        {"role": "tool", "tool_call_id": "draft", "content": json.dumps(result)},
        {"role": "assistant", "content": result["preview"], "canonicalDraftPreview": result["draftId"]},
        {"role": "user", "content": "CONFIRM GENERATE"},
    ]


def source_checked_unconfirmed_messages(stored, clarification='Change the weekly chest ceiling to 8.'):
    messages = requirement_messages(stored)[:-1]
    messages.append({'role': 'user', 'content': clarification})
    return messages


def test_requirements_tool_uses_structured_initial_extraction_and_sparse_updates():
    from workout_generator_pkg.planning_tools import workout_requirements_tool, requirements_approved

    equipment, requirements, stored, _ = planning_case()
    requirements['workingSetRIR'] = {'minimum': 1, 'maximum': 2}
    requirements['requiredCoverage'] = [{'key': 'upper_push', 'description': 'Upper push each session', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': '5-6 chest sets, upper push each session at 1-2 RIR.'}], equipment)
    initial_schema = workout_requirements_tool(equipment)['function']['parameters']
    assert 'requirementAccounting' not in initial_schema['properties']
    assert 'relaxationPermissions' in initial_schema['properties']
    initial_permission_paths = initial_schema['properties']['relaxationPermissions']['items']['properties']['path']['enum']
    assert '/auditTargets/weeklyEffectiveSets/chest/minimum' in initial_permission_paths
    assert '/auditTargets/perSessionEffectiveSets/triceps/maximum' in initial_permission_paths
    assert not any('/calves/' in path for path in initial_permission_paths)
    assert stored['requirements']['relaxationPermissions'] == []
    assert 'No target changes are authorized for relaxation.' in stored['requirementsPreview']
    from workout_generator_pkg.planning_tools import render_requirements
    preview = render_requirements({**stored['requirements'], 'relaxationPermissions': [
        {'path': '/auditTargets/weeklyEffectiveSets/chest/minimum', 'direction': 'lower_minimum', 'rank': 2}]})
    assert 'Weekly Chest minimum (currently 5): may propose reducing the minimum; compromise rank 2.' in preview
    assert 'any proposed change still needs review and your approval' in preview

    messages = source_checked_unconfirmed_messages(stored)
    update_schema = workout_requirements_tool(equipment, messages)['function']['parameters']
    assert update_schema['required'] == ['baseRequirementsId', 'updates']
    assert update_schema['properties']['baseRequirementsId']['enum'] == [stored['requirementsId']]
    assert 'requirementAccounting' not in update_schema['properties']['updates']['properties']
    update_permission_paths = update_schema['properties']['updates']['properties']['relaxationPermissions']['items']['properties']['path']['enum']
    assert update_permission_paths == initial_permission_paths

    updated = set_workout_requirements({
        'baseRequirementsId': stored['requirementsId'],
        'updates': {'auditTargets': {'weeklyEffectiveSets': {'chest': {'maximum': 8}},
                                    'maximumSessionSeconds': None},
                    'workingSetRIR': None,
                    'requiredCoverage': []},
    }, messages, equipment)
    assert updated['baseRequirementsId'] == stored['requirementsId']
    assert updated['requirements']['auditTargets']['weeklyEffectiveSets']['chest'] == {'minimum': 5, 'maximum': 8}
    assert updated['requirements']['auditTargets']['perSessionEffectiveSets']['chest'] == {'minimum': 5, 'maximum': 6}
    assert updated['requirements']['auditTargets']['maximumSessionSeconds'] is None
    assert 'workingSetRIR' not in updated['requirements']
    assert updated['requirements']['requiredCoverage'] == []
    assert not requirements_approved(messages, updated)
    assert '`/auditTargets/weeklyEffectiveSets/chest/maximum`' in updated['requirementsPreview']
    assert '`/workingSetRIR`' in updated['requirementsPreview']


def test_open_ended_volume_targets_render_without_a_ceiling_or_raise_permission():
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    from workout_generator_pkg.requirement_accounting import validate_relaxation_permissions

    equipment, requirements, _, _ = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] = None
    requirements['auditTargets']['perSessionEffectiveSets']['chest']['maximum'] = None
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'At least 5 chest sets.'}], equipment)
    assert '≥ 5' in stored['requirementsPreview']

    messages = requirement_messages(stored)
    update_schema = workout_requirements_tool(equipment, messages)['function']['parameters']
    permission_paths = update_schema['properties']['updates']['properties']['relaxationPermissions']['items']['properties']['path']['enum']
    assert '/auditTargets/weeklyEffectiveSets/chest/maximum' not in permission_paths
    assert '/auditTargets/weeklyEffectiveSets/chest/minimum' in permission_paths
    with pytest.raises(ValueError, match='does not match a supported numeric target'):
        validate_relaxation_permissions({**stored['requirements'], 'relaxationPermissions': [
            {'path': '/auditTargets/weeklyEffectiveSets/chest/maximum', 'direction': 'raise_maximum'}]})

    from workout_generator_pkg.planning_tools import audit_workout_plan
    _, _, _, draft = planning_case()
    draft['requirementsId'] = stored['requirementsId']
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    assert '≥ 5' in result['preview']


def test_fresh_requirements_include_the_code_owned_two_set_floor_and_updates_preserve_it():
    from workout_generator_pkg.programming_guidelines import MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE

    equipment, requirements, stored, _ = planning_case()
    rules = stored['requirements']['executionRules']
    assert rules == [MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE]
    assert 'All applicable exercises: 2–20 working sets per occurrence.' in stored['requirementsPreview']

    messages = requirement_messages(stored)
    updated = set_workout_requirements({'baseRequirementsId': stored['requirementsId'],
        'updates': {'executionRules': []}}, messages, equipment)
    assert updated['requirements']['executionRules'] == [MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE]
    assert stored['requirements']['executionRules'] == [MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE]


def test_fresh_requirements_reject_a_structured_single_set_cap():
    equipment, requirements, _, _ = planning_case()
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 1, 'maximumSets': 1}]
    with pytest.raises(PlanningInputError, match='no compatible set count') as error:
        set_workout_requirements(requirements, [{'role': 'user', 'content': 'Create a plan.'}], equipment)
    assert error.value.code == 'conflicting_execution_rules'

    requirements['requiredCoverage'] = [{'key': 'priority', 'description': 'Priority movement', 'scope': 'weekly'}]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': 'priority',
        'minimumSets': 1, 'maximumSets': 1}]
    with pytest.raises(PlanningInputError, match='no compatible set count') as scoped_error:
        set_workout_requirements(requirements, [{'role': 'user', 'content': 'Create a plan.'}], equipment)
    assert scoped_error.value.code == 'conflicting_execution_rules'


def test_fresh_requirements_report_when_rule_capacity_cannot_hold_the_floor():
    from jsonschema import ValidationError

    equipment, requirements, _, _ = planning_case()
    requirements['executionRules'] = [{'kind': 'rest', 'coverageKey': None, 'context': 'straightSets',
        'minimumSeconds': 0, 'maximumSeconds': 1800} for _ in range(30)]
    with pytest.raises(PlanningInputError, match='leaves no room') as error:
        set_workout_requirements(requirements, [{'role': 'user', 'content': 'Create a plan.'}], equipment)
    assert error.value.code == 'execution_rule_limit'

    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': '1', 'maximumSets': 20}]
    with pytest.raises(ValidationError):
        set_workout_requirements(requirements, [{'role': 'user', 'content': 'Create a plan.'}], equipment)


def test_sparse_update_materializes_policy_without_mutating_preexisting_candidate():
    from workout_generator_pkg.programming_guidelines import MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE

    equipment, requirements, stored, _ = planning_case()
    old_candidate = copy.deepcopy(stored)
    old_candidate['requirements'].pop('executionRules')
    messages = source_checked_unconfirmed_messages(old_candidate, 'Update the session count.')

    updated = set_workout_requirements({'baseRequirementsId': old_candidate['requirementsId'],
        'updates': {'sessionsPerWeek': 2}}, messages, equipment)
    assert updated['requirements']['executionRules'] == [MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE]
    assert '`/executionRules`' in updated['requirementsPreview']
    assert 'executionRules' not in old_candidate['requirements']


def test_requirements_distinguish_development_from_inclusion_without_inventing_a_floor():
    equipment, requirements, _, _ = planning_case()
    requirements['requiredCoverage'] = [
        {'key': 'lateral', 'description': 'Lateral shoulder work', 'scope': 'weekly', 'intent': 'development'},
        {'key': 'horizontal', 'description': 'Horizontal pushing', 'scope': 'weekly'},
    ]
    requirements['executionRules'] = [{'kind': 'coverageBalance', 'first': 'lateral', 'second': 'horizontal',
        'scope': 'weekly', 'relationship': 'first_not_less_than_second'}]

    stored = set_workout_requirements(requirements, [{'role': 'user',
        'content': 'Develop lateral shoulder work at least as much as horizontal pushing.'}], equipment)

    coverage = stored['requirements']['requiredCoverage']
    assert coverage[0]['intent'] == 'development'
    assert 'intent' not in coverage[1]  # Existing callers retain inclusion semantics.
    preview = stored['requirementsPreview']
    assert 'development emphasis' in preview and 'qualitative emphasis, not an added numeric minimum' in preview
    assert 'inclusion' in preview
    assert 'at least as much exposure' in preview and 'not a fixed ratio or hard minimum' in preview
    assert 'objectiveOrder' not in stored['requirements']


def test_development_floors_are_explicit_and_policy_does_not_infer_extra_dose():
    from workout_generator_pkg.programming_guidelines import GUIDELINE_POLICY
    from workout_generator_pkg.requirement_accounting import ACCOUNTING_SCHEMA

    equipment, requirements, _, _ = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['requiredCoverage'] = [{'key': 'lateral_delt', 'description': 'Lateral delts',
        'scope': 'weekly', 'intent': 'development', 'minimumWeeklySets': 6, 'minimumSessions': 2}]
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Program at least six qualified lateral-delt sets over two sessions.'}], equipment)

    preview = stored['requirementsPreview']
    assert 'at least 6 qualified working sets weekly' in preview
    assert 'at least 2 weekly training sessions' in preview
    assert 'relative allocation of the approved weekly set budget' not in GUIDELINE_POLICY['goalAuthority']
    assert 'extra-set bonus' in GUIDELINE_POLICY['goalAuthority']
    assert 'only when explicitly listed in the authoritative `objectiveOrder`' in GUIDELINE_POLICY['goalAuthority']
    assert 'workload_economy preference minimizes physical weekly working sets' in ACCOUNTING_SCHEMA['description']


def test_scoped_requirement_update_can_clear_nested_optional_target_and_rejects_stale_base():
    equipment, requirements, stored, _ = planning_case()
    messages = source_checked_unconfirmed_messages(stored, 'Remove the weekly chest target.')
    cleared = set_workout_requirements({'baseRequirementsId': stored['requirementsId'],
        'updates': {'auditTargets': {'weeklyEffectiveSets': {'chest': None}}}}, messages, equipment)
    assert 'chest' not in cleared['requirements']['auditTargets']['weeklyEffectiveSets']
    assert cleared['requirements']['auditTargets']['perSessionEffectiveSets']['chest'] == {'minimum': 5, 'maximum': 6}
    with pytest.raises(ValueError, match='latest source-checked'):
        set_workout_requirements({'baseRequirementsId': 'REQUIREMENTS_stale', 'updates': {}}, messages, equipment)


def test_scoped_requirement_update_reuses_unchanged_restriction_resolution(monkeypatch):
    from workout_generator_pkg import restriction_policy
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, _, _ = planning_case()
    requirements['exerciseRestrictions'] = {'excludeNameTerms': ['Burpee'], 'exceptNameTerms': []}
    calls = []

    def resolve(restrictions, current_equipment, *_args):
        calls.append(copy.deepcopy(restrictions))
        return {'resolutionVersion': restriction_policy.RESTRICTION_POLICY_VERSION,
                'libraryFingerprint': library_fingerprint(current_equipment), 'matches': [],
                'excludedDefinitionIds': [], 'exceptDefinitionIds': [],
                'excludedExerciseNames': [], 'exceptExerciseNames': []}

    monkeypatch.setattr(restriction_policy, 'resolve_restrictions', resolve)
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Exclude burpees and plan 5-6 chest sets.'}], equipment)
    assert len(calls) == 1

    updated = set_workout_requirements({'baseRequirementsId': stored['requirementsId'],
        'updates': {'auditTargets': {'weeklyEffectiveSets': {'chest': {'maximum': 7}}}}},
        source_checked_unconfirmed_messages(stored, 'Raise the chest ceiling to 7.'), equipment)
    assert len(calls) == 1
    assert updated['restrictionPolicy'] == stored['restrictionPolicy']

    changed = set_workout_requirements({'baseRequirementsId': updated['requirementsId'],
        'updates': {'exerciseRestrictions': {'excludeNameTerms': ['Burpee', 'Mountain climber']}}},
        source_checked_unconfirmed_messages(updated, 'Also exclude mountain climbers.'), equipment)
    assert len(calls) == 2
    assert calls[-1]['excludeNameTerms'] == ['Burpee', 'Mountain climber']
    assert changed['restrictionPolicy']['libraryFingerprint'] == library_fingerprint(equipment)


def test_requirements_are_separate_and_frozen_during_repair():
    _, requirements, stored, _ = planning_case()
    changed = copy.deepcopy(requirements)
    changed["auditTargets"]["weeklyEffectiveSets"] = {}
    messages = requirement_messages(stored)
    with pytest.raises(ValueError, match="frozen"):
        set_workout_requirements(changed, messages)
    messages.append({"role": "user", "content": "Remove weekly volume target"})
    updated = set_workout_requirements(changed, messages)
    assert updated["requirementsId"] != stored["requirementsId"]
    assert '| Chest | — | 5–6 |' in updated['requirementsPreview']


@pytest.mark.parametrize('scope, claims, code', [
    ('weekly', [], 'required_coverage_missing'),
    ('weekly', ['unknown'], 'unknown_coverage_key'),
    ('weekly', ['requested'], None),
])
def test_coverage_scope_and_unknown_assignments(scope, claims, code):
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{'key': 'requested', 'description': 'Requested work', 'scope': scope}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Include requested work weekly.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = claims
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed'] is (code is None)
    if code:
        assert result['errors'][0]['code'] == code
    assert 'Requested work' in stored['requirementsPreview']
    assert 'satisfiesCoverage' not in result['planIndex']['exercises'][0]


def test_legacy_requirements_can_extract_coverage_without_unfreezing_targets():
    from workout_generator_pkg.planning_tools import REQUIREMENTS_VERSION, requirements_approved
    equipment, requirements, stored, _ = planning_case()
    stored['requirementsVersion'] = REQUIREMENTS_VERSION - 1
    messages = requirement_messages(stored)
    messages.append({'role': 'user', 'content': '/continue'})
    extracted = copy.deepcopy(requirements)
    extracted['requiredCoverage'] = [{'key': 'requested', 'description': 'Original requested work', 'scope': 'eachSession'}]
    result = set_workout_requirements(extracted, messages, equipment)
    assert result['requirementsVersion'] == REQUIREMENTS_VERSION and result['requirementsId'] != stored['requirementsId']
    assert not requirements_approved(messages, result)
    extracted['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] = 1
    with pytest.raises(ValueError, match='frozen'):
        set_workout_requirements(extracted, messages, equipment)


def test_single_draft_audits_real_reps_rests_and_roles_then_renders():
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"]
    assert result["audit"]["workouts"][0]["estimatedSeconds"] == 810
    assert result["audit"]["weeklyVolume"]["triceps"]["effective"] == 2.5
    assert "| 1 | Push-Up | 5 | 8–10 | Technical criteria (plan choice) | Chest | Triceps | 90s |" in result["preview"]
    assert 'Working-set acceptance (plan-selected technical criteria)' in result['planIndex']['exercises'][0]['notes']
    assert "Estimated duration: 13.5 min" in result["preview"]
    approved = confirmed_draft(approved_messages(stored, result), equipment)
    assert approved["planIndex"] == result["planIndex"]
    approved["planIndex"]["exercises"][0]["numWorkSets"] = 1
    assert result["planIndex"]["exercises"][0]["numWorkSets"] == 5


def test_volume_and_time_failures_return_feedback_without_a_preview():
    equipment, requirements, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not failed["passed"] and "preview" not in failed
    assert any("chest: 3 effective sets" in issue for issue in failed["audit"]["issues"])
    requirements["auditTargets"]["maximumSessionSeconds"] = 500
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 5
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not failed["passed"] and any("810s exceeds 500s" in issue for issue in failed["audit"]["issues"])


def test_confirmation_requires_display_current_library_settings_and_successful_replacement():
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    with pytest.raises(ValueError, match="displayed"):
        confirmed_draft(messages[:5], equipment)
    changed = copy.deepcopy(equipment)
    changed["exerciseDefinitions"][0]["muscleGroups"] = ["FRONT_DELTOIDS"]
    with pytest.raises(ValueError, match="library or equipment changed"):
        confirmed_draft(messages, changed)
    with pytest.raises(ValueError, match="Calibration settings"):
        confirmed_draft(messages, equipment, False)
    messages.append({"role": "user", "content": "Change the plan"})
    # Conversation text alone does not mutate the structured plan.
    assert confirmed_draft(messages, equipment)["planIndex"] == result["planIndex"]
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "replacement", "function": {"name": "audit_workout_plan"}}]},
        {"role": "tool", "tool_call_id": "replacement", "content": '{"passed":false,"errors":[]}'},
    ])
    with pytest.raises(ValueError, match="passing"):
        confirmed_draft(messages, equipment)


def test_prescriptions_have_unique_occurrence_ids_and_superset_rounds():
    equipment, requirements, stored, draft = planning_case()
    requirements["auditTargets"]["weeklyEffectiveSets"] = {}
    requirements["auditTargets"]["perSessionEffectiveSets"] = {}
    requirements["auditTargets"]["maximumSessionSeconds"] = 4500
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    first = draft["workouts"][0]["exercises"][0]
    first.update(superset="A", restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=40)
    second = copy.deepcopy(first)
    second["restAfterSupersetExerciseSeconds"] = 75
    draft["workouts"][0]["exercises"].append(second)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"]
    assert [e["id"] for e in result["planIndex"]["exercises"]] == ["EXERCISE_0", "EXERCISE_1"]
    assert result["audit"]["workouts"][0]["timing"]["restSeconds"] == 5 * (40 + 75) - 75
    second["numWorkSets"] = 3
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not failed["passed"] and "shortest member" in failed["audit"]["issues"][0]


def test_pipeline_uses_approved_draft_without_summarizing_or_replanning(tmp_path, monkeypatch):
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation

    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    from workout_generator_pkg.plan_review import review_draft
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    result = review_draft(None, result, requirement_messages(stored), equipment)
    messages = approved_messages(stored, result)
    emitted = []

    def no_planning(*_args, **_kwargs):
        pytest.fail("The approved draft must not be summarized or replanned")

    def emission(items, *_args, **_kwargs):
        plan = items[0][1]["plan_index"]
        emitted.append(plan)
        assert plan["exercises"][0]["numWorkSets"] == 5
        assert plan["exercises"][0]["maxReps"] == 10
        assert plan["auditTargets"] == stored["requirements"]["auditTargets"]
        raise RuntimeError("Stopped at emission checkpoint")

    deps = replace(resolve_pipeline_deps(), test_connection=no_planning,
                   hash_conversation=lambda *_: "hash", summarize_conversation=no_planning, generate_index=no_planning,
                   save_generation_progress=lambda *_a, **_k: ("progress.json", 0), parallel_emit_items=emission)
    exported = execute_workout_generation(None, messages, provided_equipment=equipment,
                                         script_dir=str(tmp_path), deps=deps, force_use_reasoner=False)
    assert emitted and "emission checkpoint" in exported["error"]


def test_uuid_equipment_validation_keeps_original_identity_and_exact_total_loads():
    equipment, _, stored, draft = planning_case()
    equipment_id = "11111111-1111-4111-8111-111111111111"
    equipment["equipments"] = [{"id": equipment_id, "name": "Barbell", "type": "BARBELL", "barWeight": 10.0, "plates": []}]
    definition = equipment["exerciseDefinitions"][0]
    definition.update(exerciseType="WEIGHT", equipmentId=equipment_id, bodyWeightPercentage=None)
    item = draft["workouts"][0]["exercises"][0]
    item["targetSetPrescriptions"] = [{"workSetIndex": i, "reps": 10, "weight": 10.0} for i in range(5)]
    original = copy.deepcopy(equipment)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"] and equipment == original
    assert result["planIndex"]["exercises"][0]["equipmentId"] == equipment_id
    assert result["planIndex"]["exercises"][0]["targetSetPrescriptions"] == item["targetSetPrescriptions"]
    assert "Exact work-set targets" in result["preview"]


def test_plan_validation_skips_motion_payload_copy_and_keeps_definition_checks():
    from workout_generator_pkg.planning_tools import _validate_draft_plan
    from workout_generator_pkg.plan_contract import ContractValidationError
    equipment, _, stored, draft = planning_case()
    plan = audit_workout_plan(draft, equipment, requirement_messages(stored))['planIndex']
    class PlaybackData(list):
        def __deepcopy__(self, memo):
            pytest.fail('Plan validation must not copy playback data')
    equipment['exerciseMovements'] = PlaybackData([{'large': 'motion data'}])
    _validate_draft_plan(plan, equipment)
    plan['exercises'][0]['libraryDefinitionId'] = 'unknown'
    with pytest.raises(ContractValidationError):
        _validate_draft_plan(plan, equipment)


def test_timed_draft_uses_real_interval_duration():
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=1, auditTargets={"weeklyEffectiveSets": {}, "perSessionEffectiveSets": {}, "maximumSessionSeconds": 1000})
    stored = set_workout_requirements(requirements, [])
    draft["requirementsId"] = stored["requirementsId"]
    equipment["exerciseDefinitions"][0].update(exerciseType="COUNTDOWN", muscleGroups=[], secondaryMuscleGroups=[],
                                               exerciseCategory=None, bodyWeightPercentage=None)
    item = draft["workouts"][0]["exercises"][0]
    item.update(numWorkSets=2, minReps=None, maxReps=None, durationSeconds=30, restBetweenSetsSeconds=60)
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result["passed"]
    assert result["audit"]["workouts"][0]["estimatedSeconds"] == 420
    assert "| 2 | 30s | Technical criteria (plan choice) | — | — | 60s |" in result["preview"]


def test_timed_search_and_audit_share_the_same_volume_policy():
    from workout_generator_pkg.exercise_library_tools import execute_library_tool
    equipment, requirements, _, draft = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    definition.update(name='Wall Sit', exerciseType='COUNTDOWN', muscleGroups=['FRONT_QUADRICEPS'],
                      secondaryMuscleGroups=[], exerciseCategory=None, bodyWeightPercentage=None)
    requirements['auditTargets'].update(weeklyEffectiveSets={'quads': {'minimum': 2, 'maximum': 3}},
        perSessionEffectiveSets={'quads': {'minimum': 2, 'maximum': 3}})
    stored = set_workout_requirements(requirements, [])
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0].update(numWorkSets=2, minReps=None, maxReps=None,
        durationSeconds=45, restBetweenSetsSeconds=30)
    search = execute_library_tool('search_exercise_library', {'queries': ['Wall Sit']}, equipment)
    entry = search['results'][0]['exercises'][0]
    assert entry['creditsPerWorkingSet'] == {} and 'volumeAuditNote' in entry
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not result['passed'] and result['audit']['weeklyVolume']['quads']['effective'] == 0
    assert result['audit']['workouts'][0]['timing']['workSeconds'] == 90


def test_status_question_and_identical_submission_reuse_audited_draft(monkeypatch):
    from workout_generator_pkg import planning_tools

    equipment, requirements, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    unchanged = set_workout_requirements(requirements, messages)
    assert unchanged["cached"] and unchanged["requirementsId"] == stored["requirementsId"]
    messages.append({"role": "user", "content": "What does RIR mean?"})
    assert confirmed_draft(messages, equipment)["draftId"] == result["draftId"]
    monkeypatch.setattr(planning_tools, "audit_workout_package", lambda *_: pytest.fail("Identical draft should not be re-audited"))
    cached = audit_workout_plan(draft, equipment, messages)
    assert cached["cached"] and cached["draftId"] == result["draftId"]
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "cached", "function": {"name": "audit_workout_plan"}}]},
        {"role": "tool", "tool_call_id": "cached", "content": json.dumps(cached)},
    ])
    assert confirmed_draft(messages, equipment)["draftId"] == result["draftId"]


def test_changed_requirements_invalidate_previous_successful_draft():
    equipment, requirements, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    messages = approved_messages(stored, result)
    messages.append({"role": "user", "content": "Limit sessions to 10 minutes"})
    requirements["auditTargets"]["maximumSessionSeconds"] = 600
    updated = set_workout_requirements(requirements, messages)
    messages.extend([
        {"role": "assistant", "tool_calls": [{"id": "new-goals", "function": {"name": "set_workout_requirements"}}]},
        {"role": "tool", "tool_call_id": "new-goals", "content": json.dumps(updated)},
    ])
    with pytest.raises(ValueError, match="requirements need user approval"):
        confirmed_draft(messages, equipment)


def test_audit_feedback_has_codes_actuals_paths_and_repair_instructions():
    equipment, _, stored, draft = planning_case()
    draft["workouts"][0]["exercises"][0]["numWorkSets"] = 3
    failed = audit_workout_plan(draft, equipment, requirement_messages(stored))
    error = next(e for e in failed["errors"] if e["scope"] == "per_session")
    assert error["code"] == "volume_below_target" and error["actual"] == 3
    assert error["minimum"] == 5 and error["difference"] == 2
    assert error["path"] == "/workouts/0/exercises"
    assert "preserve" in error["repair"] and "re-audit" in error["repair"]
    draft["workouts"][0]["exercises"][0]["definition_id"] = "LIBRARY_999"
    with pytest.raises(ValueError) as captured:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    response = planning_tool_failure("audit_workout_plan", captured.value, draft)
    assert response["errors"][0]["code"] == "unknown_library_reference"
    assert response["errors"][0]["path"] == "/workouts/0/exercises/0/definition_id"
    assert "search_exercise_library" in response["errors"][0]["repair"]


def test_contract_errors_carry_identity_for_repeated_exercise_names():
    from workout_generator_pkg.planning_tools import build_draft_plan, PlanningInputError

    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'][0]['name'] = 'Single-Arm Push-Up'
    second = copy.deepcopy(draft['workouts'][0])
    draft['workouts'].append(second)
    draft['workouts'][0]['exercises'][0]['intraSetRestInSeconds'] = 30
    with pytest.raises(PlanningInputError) as caught:
        build_draft_plan(draft, equipment, requirements)
    errors = [item for item in caught.value.errors if item['code'] == 'missing_unilateral_intra_set_rest']
    assert len(errors) == 1
    assert errors[0]['exerciseId'] == 'EXERCISE_1'
    assert errors[0]['path'] == '/workouts/1/exercises/0/intraSetRestInSeconds'


def test_contract_and_execution_failures_use_same_error_envelope():
    from workout_generator_pkg.plan_contract import ContractIssue, ContractValidationError

    _, _, _, arguments = planning_case()
    failure = planning_tool_failure("audit_workout_plan", ContractValidationError("invalid contract", [
        ContractIssue("invalid_example", "An invalid prescription (misleading text: EXERCISE_99).",
                      exercise_id="EXERCISE_0")
    ]), arguments)
    assert not failure["passed"]
    error = failure["errors"][0]
    assert error["code"] == "invalid_example" and error["exerciseId"] == "EXERCISE_0"
    assert error["path"] == "/workouts/0/exercises/0" and error["repair"]
    unbound = planning_tool_failure('audit_workout_plan', ContractValidationError('invalid', [
        ContractIssue('invalid_example', "Exercise 'EXERCISE_0' has an invalid prescription.")]), arguments)
    assert unbound['errors'][0]['path'] == '/workouts'
    assert unbound['errors'][0]['exerciseId'] is None
    execution = planning_tool_failure("audit_workout_plan", RuntimeError("unexpected failure"), arguments)
    assert execution["errors"][0]["code"] == "tool_execution_failed"
    assert execution["errors"][0]["owner"] == "generator"
    assert execution["executionFailure"] is True
    assert "do not change the draft" in execution["errors"][0]["repair"]


def test_conflicting_superset_rests_and_unilateral_contract_errors_are_returned_together():
    equipment, _, stored, draft = planning_case()
    equipment['exerciseDefinitions'][0]['name'] = 'Single-Arm Push-Up'
    first = draft['workouts'][0]['exercises'][0]
    first.update(superset='A', restBetweenSetsSeconds=40, restAfterSupersetExerciseSeconds=0, restAfterExerciseSeconds=60)
    second = copy.deepcopy(first)
    second.update(restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=75, restAfterExerciseSeconds=0)
    draft['workouts'][0]['exercises'].append(second)
    with pytest.raises(ValueError) as error:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    feedback = planning_tool_failure('audit_workout_plan', error.value, draft)
    codes = {e['code'] for e in feedback['errors']}
    assert {'conflicting_superset_rest', 'superset_outer_rest', 'missing_unilateral_intra_set_rest'} <= codes
    assert not feedback['passed'] and 'preview' not in feedback


def test_saved_audit_from_previous_validator_cannot_be_confirmed():
    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    result.pop('auditVersion')
    with pytest.raises(ValueError, match='validation changed'):
        confirmed_draft(approved_messages(stored, result), equipment)


@pytest.mark.parametrize('reps,expected_code', [(11, 'target_set_prescription_outside_rep_range'),
    (16, 'target_set_prescription_outside_rep_range'), (0, 'invalid_target_set_prescription_reps'),
    (True, 'invalid_target_set_prescription_reps')])
def test_shared_contract_rejects_exact_targets_outside_rep_range(reps, expected_code):
    from workout_generator_pkg.plan_contract import validate_plan_index_contract, ContractValidationError
    equipment, _, stored, draft = planning_case()
    plan = audit_workout_plan(draft, equipment, requirement_messages(stored))['planIndex']
    exercise = plan['exercises'][0]
    exercise.update(minReps=12, maxReps=15, targetSetPrescriptions=[
        {'workSetIndex': i, 'reps': reps if i == 1 else 12, 'additionalWeight': 0} for i in range(5)])
    with pytest.raises(ContractValidationError) as error:
        validate_plan_index_contract(plan, equipment)
    assert expected_code in {issue.code for issue in error.value.issues}


def test_shared_contract_accepts_exact_rep_range_boundaries():
    equipment, _, stored, draft = planning_case()
    plan = audit_workout_plan(draft, equipment, requirement_messages(stored))['planIndex']
    plan['exercises'][0].update(minReps=12, maxReps=15, targetSetPrescriptions=[
        {'workSetIndex': i, 'reps': 12 if i % 2 else 15, 'additionalWeight': 0} for i in range(5)])
    validate_plan_index_contract(plan, equipment)


def test_reps_only_targets_enable_native_calibration_without_inventing_a_load():
    equipment, _, stored, draft = planning_case()
    equipment_id = '11111111-1111-4111-8111-111111111111'
    equipment['equipments'] = [{'id': equipment_id, 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 20.0, 'plates': []}]
    equipment['exerciseDefinitions'][0].update(exerciseType='WEIGHT', equipmentId=equipment_id, bodyWeightPercentage=None)
    draft['workouts'][0]['exercises'][0]['workSetTemplate'] = {'reps': 9}

    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    plan_exercise = result['planIndex']['exercises'][0]

    assert result['passed'] is True
    assert plan_exercise['requiresLoadCalibration'] is True
    assert plan_exercise['targetSetPrescriptions'] == [
        {'workSetIndex': index, 'reps': 9} for index in range(5)]


@pytest.mark.parametrize(('exercise_type', 'equipment_type'), [
    ('WEIGHT', 'BARBELL'),
    ('BODY_WEIGHT', 'WEIGHTVEST'),
])
def test_loaded_exercises_without_any_targets_enable_native_calibration(exercise_type, equipment_type):
    from workout_generator_pkg.planning_tools import audit_workout_plan, build_draft_plan

    equipment, _, stored, draft = planning_case()
    equipment_id = '11111111-1111-4111-8111-111111111111'
    equipment['equipments'] = [{'id': equipment_id, 'name': equipment_type, 'type': equipment_type,
                                'barWeight': 10.0, 'plates': []}]
    definition = equipment['exerciseDefinitions'][0]
    definition.update(exerciseType=exercise_type, equipmentId=equipment_id,
                      bodyWeightPercentage=65 if exercise_type == 'BODY_WEIGHT' else None,
                      requiresLoadCalibration=False)
    item = draft['workouts'][0]['exercises'][0]
    item.pop('workSetTemplate', None)
    item.pop('targetSetPrescriptions', None)

    plan = build_draft_plan(draft, equipment, stored['requirements'])

    assert plan['exercises'][0]['requiresLoadCalibration'] is True
    assert 'targetSetPrescriptions' not in plan['exercises'][0]
    audited = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert audited['planIndex']['exercises'][0]['requiresLoadCalibration'] is True
    assert audited['audit']['workouts'][0]['timing']['calibrationSeconds'] == 30


@pytest.mark.parametrize('indexed', [False, True])
def test_unloaded_bodyweight_reps_only_targets_use_known_zero_added_load(indexed):
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    if indexed:
        item['targetSetPrescriptions'] = [{'workSetIndex': i, 'reps': 9} for i in range(5)]
    else:
        item['workSetTemplate'] = {'reps': 9}

    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    exercise = result['planIndex']['exercises'][0]
    assert result['passed'] is True
    assert exercise['requiresLoadCalibration'] is False
    assert exercise['targetSetPrescriptions'] == [
        {'workSetIndex': i, 'reps': 9, 'additionalWeight': 0} for i in range(5)]
    assert all('additionalWeight' not in target for target in item.get('targetSetPrescriptions', []))
    assert 'additionalWeight' not in item.get('workSetTemplate', {})


def test_shared_contract_rejects_mixed_fixed_and_unspecified_target_loads():
    equipment, _, stored, draft = planning_case()
    equipment_id = '11111111-1111-4111-8111-111111111111'
    equipment['equipments'] = [{'id': equipment_id, 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 20.0, 'plates': []}]
    equipment['exerciseDefinitions'][0].update(exerciseType='WEIGHT', equipmentId=equipment_id, bodyWeightPercentage=None)
    draft['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [
        {'workSetIndex': 0, 'reps': 9},
        *[{'workSetIndex': index, 'reps': 9, 'weight': 20.0} for index in range(1, 5)],
    ]

    with pytest.raises(ValueError) as failure:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert 'invalid_target_set_prescription_load' in {error['code'] for error in failure.value.errors}


@pytest.mark.parametrize('extra,expected', [
    ({'targetSetPrescriptions': []}, 'conflicting_set_prescriptions'),
    ({'workSetTemplate': {'reps': 11, 'additionalWeight': 0}}, 'target_set_prescription_outside_rep_range'),
    ({'workSetTemplate': {'reps': 9, 'additionalWeight': 5}}, 'missing_plan_bodyweight_equipment_id'),
])
def test_work_set_template_keeps_existing_load_and_rep_guards(extra, expected):
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item.update(workSetTemplate={'reps': 9, 'additionalWeight': 0}, **{k:v for k,v in extra.items() if k != 'workSetTemplate'})
    if 'workSetTemplate' in extra:
        item['workSetTemplate'] = extra['workSetTemplate']
    with pytest.raises(ValueError) as failure:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    errors = planning_tool_failure('audit_workout_plan', failure.value, draft)['errors']
    assert any(expected in error['code'] or expected in error['message'] for error in errors)


@pytest.mark.parametrize('targets,code', [
    ([{'workSetIndex': i, 'reps': 9, 'additionalWeight': 5} for i in range(5)], 'missing_plan_bodyweight_equipment_id'),
    (42, 'invalid_target_set_prescriptions'),
    *[([{'workSetIndex': i, 'reps': 9, 'additionalWeight': load} for i in range(5)], 'invalid_target_set_prescription_load')
      for load in (True, -1, float('nan'), float('inf'), 10 ** 500)],
])
def test_shared_plan_contract_rejects_unrepresented_added_load_and_malformed_targets(targets, code):
    from workout_generator_pkg.plan_contract import validate_plan_index_contract, ContractValidationError
    equipment, _, stored, draft = planning_case()
    plan = audit_workout_plan(draft, equipment, requirement_messages(stored))['planIndex']
    plan['exercises'][0]['targetSetPrescriptions'] = targets
    with pytest.raises(ContractValidationError) as failure:
        validate_plan_index_contract(plan, equipment)
    assert code in {issue.code for issue in failure.value.issues}


def test_planning_and_parallel_session_schemas_share_the_export_description_limit():
    from workout_generator_pkg.constants import JSON_SCHEMA
    from workout_generator_pkg.planning_tools import _DRAFT_SCHEMA
    from workout_generator_pkg.session_drafting import PREPARE_WORKOUT_SESSIONS_TOOL
    export = JSON_SCHEMA['$defs']['Workout']['properties']['description']
    planning = _DRAFT_SCHEMA['properties']['workouts']['items']['properties']['description']
    assert {key: value for key, value in planning.items() if key != 'description'} == export
    assert PREPARE_WORKOUT_SESSIONS_TOOL['function']['parameters']['properties']['sessions']['items']['properties']['description'] == planning


def test_capped_text_rejection_explains_field_purpose_reserve_and_exact_budget():
    from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure
    equipment, _, stored, draft = planning_case()
    day = draft['workouts'][0]
    day.update(description='A long focus label that cannot fit after adding the schedule.', trainingDays=[2])
    with pytest.raises(PlanningInputError) as caught:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    feedback = planning_tool_failure('audit_workout_plan', caught.value, draft)
    contract = feedback['errors'][0]['textFieldContract']
    assert contract['maximumCharacters'] == 29 and contract['exportMaximumCharacters'] == 50
    assert contract['reservedCharacters'] == 21 and contract['charactersToRemove'] == len(day['description']) - 29
    assert 'not an exercise list' in contract['purpose']
    day['description'] = 'Squat and press focus'
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']


@pytest.mark.parametrize('bounds', [{'minimum': 3, 'maximum': 3}, {'minimum': 6, 'maximum': 4}])
def test_model_declared_bounds_cannot_become_working_set_requirements(bounds):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['allocationBounds'] = bounds
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']
    item = result['submittedDraft']['workouts'][0]['exercises'][0]
    assert item['allocationBounds'] == {'minimum': 1, 'maximum': 20}
    assert item['numWorkSets'] == 5
    assert draft['workouts'][0]['exercises'][0]['allocationBounds'] == bounds


def test_preview_distinguishes_raw_indirect_sets_from_fractional_credit_and_shows_execution_audit():
    equipment, requirements, _, draft = planning_case()
    requirements['workingSetRIR'] = {'minimum': 1, 'maximum': 2}
    requirements['requiredCoverage'] = [{'key': 'upper_push', 'description': 'Upper push each session', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': '5-6 chest sets; upper push each session at 1-2 RIR.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0].pop('effortAcceptance', None)
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['upper_push']
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']
    assert '| Triceps | 0 | 5 | 2.5 | — | Reported |' in result['preview']
    assert '| Chest | 5 | 0 | 5 | 5–6 | Within target |' in result['preview']
    assert 'Primary muscles | Secondary muscles' in result['preview']
    assert 'Timing breakdown:' in result['preview']
    assert 'Total weekly working sets: 5' in result['preview']
    assert '| upper push | 5 |' in result['preview']
    from workout_generator_pkg.plan_review import _context
    context = _context(result, requirement_messages(stored), equipment, None, len(requirement_messages(stored)) - 1)
    assert result['audit']['weeklyWorkingSets'] == context['audit']['weeklyWorkingSets'] == 5
    assert result['audit']['weeklyCoverageSets'] == context['audit']['weeklyCoverageSets'] == {'upper_push': 5}
    assert context['audit']['workouts'][0]['coverageSets'] == {'upper_push': 5}


def test_saved_long_descriptions_can_be_reaudited_and_edited_without_rewriting_exercises():
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['description'] = 'Old detailed description ' * 6
    draft['workouts'].append(copy.deepcopy(draft['workouts'][0]))
    messages = requirement_messages(stored) + [
        {'role': 'assistant', 'tool_calls': [{'id': 'old', 'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'old', 'content': json.dumps({'submittedDraft': draft, 'currentDraftId': 'REVISION_0'})}]
    from workout_generator_pkg.planning_tools import PlanningInputError
    with pytest.raises(PlanningInputError):
        audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': []}, equipment, messages)
    patch = [{'op': 'replace', 'path': f'/workouts/{index}/description', 'value': 'Full body'} for index in range(2)]
    repaired = audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'patch': patch}, equipment, messages)
    assert all(day['description'] == 'Full body' for day in repaired['submittedDraft']['workouts'])
    assert [day['exercises'] for day in repaired['submittedDraft']['workouts']] == [day['exercises'] for day in draft['workouts']]


def test_resuming_an_old_audit_schedules_a_source_draft_reaudit():
    from workout_generator_pkg import interactive_shell as shell
    from workout_generator_pkg.planner_context import request_planning_state, pending_reaudit
    from workout_generator_pkg.planning_tools import AUDIT_VERSION
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    old = audit_workout_plan(draft, equipment, messages)
    old.update(auditVersion=AUDIT_VERSION - 1, review={'version': REVIEW_VERSION, 'findings': []})
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'saved', 'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'saved', 'content': json.dumps(old)},
        {'role': 'user', 'content': '/continue'}])
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['lastAudit']['auditVersion'] == AUDIT_VERSION - 1
    assert pending_reaudit(state, '/continue') == {'requirementsId': stored['requirementsId'], 'baseDraftId': old['currentDraftId'], 'patch': []}


def test_description_only_repair_scope_cannot_change_prescriptions():
    from workout_generator_pkg.planning_tools import validate_repair_scope
    task = {'permittedPatchPaths': ['/workouts/0/description'], 'omittedWorkoutReferences': []}
    validate_repair_scope({'patch': [{'op': 'replace', 'path': '/workouts/0/description', 'value': 'Full body'}]}, task)
    with pytest.raises(ValueError, match='outside allowed'):
        validate_repair_scope({'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 1}]}, task)


@pytest.mark.parametrize('path', ['', '/workouts', '/workouts/0', '/workouts/0/exercises', '/workouts/0/exercises/0'])
def test_numeric_repair_rejects_whole_object_rewrites_but_allows_targeted_changes(path):
    from workout_generator_pkg.planning_tools import PlanningInputError, validate_repair_scope
    task = {'findingCode': 'volume_below_target', 'omittedWorkoutReferences': []}
    arguments = {'patch': [{'op': 'replace', 'path': path, 'value': []}]}
    before = copy.deepcopy(arguments)
    with pytest.raises(PlanningInputError) as caught:
        validate_repair_scope(arguments, task)
    assert caught.value.code == 'numeric_repair_too_broad'
    assert arguments == before
    targeted = {'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3},
        {'op': 'add', 'path': '/workouts/0/exercises/-', 'value': {}},
        {'op': 'remove', 'path': '/workouts/0/exercises/1'}]}
    assert validate_repair_scope(targeted, task) == targeted
    assert validate_repair_scope(arguments, {'findingCode': 'independent_review_finding'}) == arguments


def test_legacy_calibration_fields_are_stripped_and_native_mode_is_history_driven():
    from workout_generator_pkg.planning_tools import _EXERCISE
    equipment, _, stored, draft = planning_case()
    equipment_id = '11111111-1111-4111-8111-111111111111'
    equipment['equipments'] = [{'id': equipment_id, 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 10.0, 'plates': []}]
    equipment['exerciseDefinitions'][0].update(exerciseType='WEIGHT', equipmentId=equipment_id, bodyWeightPercentage=None)
    item = draft['workouts'][0]['exercises'][0]
    item.update(requiresEffortCalibration=True, calibrationAttempts=2)
    assert not {'requiresEffortCalibration', 'calibrationAttempts'} & set(_EXERCISE['properties'])
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']
    assert 'requiresEffortCalibration' not in draft['workouts'][0]['exercises'][0]
    assert 'calibrationAttempts' not in draft['workouts'][0]['exercises'][0]
    exercises = result['planIndex']['exercises']
    assert exercises[0]['requiresLoadCalibration'] is True
    assert all('requiresEffortCalibration' not in exercise and 'calibrationAttempts' not in exercise
        and 'trial budget' not in exercise['placementNotes'].lower()
        and 'Working-set acceptance' in exercise['placementNotes']
        for exercise in exercises)


def test_retained_legacy_draft_is_migrated_without_changing_its_revision():
    from workout_generator_pkg.planning_tools import latest_draft_submission
    _, _, _, draft = planning_case()
    draft['workouts'][0]['exercises'][0].update(requiresEffortCalibration=True, calibrationAttempts=4)
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps({
            'submittedDraft': draft, 'currentDraftId': 'REVISION_8'})},
    ]
    migrated, revision = latest_draft_submission(messages)
    exercise = migrated['workouts'][0]['exercises'][0]
    assert revision == 'REVISION_8'
    assert 'requiresEffortCalibration' not in exercise and 'calibrationAttempts' not in exercise
    assert 'effortAcceptance' in exercise


def test_effort_acceptance_is_required_or_bound_from_approved_global_target():
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    plan = build_draft_plan(draft, equipment, stored['requirements'])
    assert 'Working-set acceptance (plan-selected technical criteria)' in plan['exercises'][0]['placementNotes']
    assert 'accept only when Each repetition reaches' in plan['exercises'][0]['placementNotes']

    missing = copy.deepcopy(draft)
    for workout in missing['workouts']:
        for exercise in workout['exercises']:
            exercise.pop('effortAcceptance')
    no_global_rir = copy.deepcopy(stored['requirements'])
    no_global_rir.pop('workingSetRIR', None)
    build_draft_plan(missing, equipment, no_global_rir)
    assert all(exercise['effortAcceptance']['kind'] == 'rir_range'
               and exercise['effortAcceptance']['minimumRIR'] == 1
               and exercise['effortAcceptance']['maximumRIR'] == 2
               for workout in missing['workouts'] for exercise in workout['exercises'])

    global_rir = {'minimum': 2, 'maximum': 3}
    draft_without_local = copy.deepcopy(draft)
    draft_without_local['workouts'][0]['exercises'][0].pop('effortAcceptance')
    globally_bound = build_draft_plan(draft_without_local, equipment,
        {**stored['requirements'], 'workingSetRIR': global_rir})
    assert globally_bound['workingSetRIR'] == global_rir
    assert '2–3 RIR (approved target)' in globally_bound['exercises'][0]['placementNotes']


def test_effort_acceptance_accepts_minimal_kind_specific_shapes():
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item['effortAcceptance'] = {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2}
    build_draft_plan(draft, equipment, stored['requirements'])
    assert item['effortAcceptance'] == {'kind': 'rir_range', 'minimumRIR': 1, 'maximumRIR': 2,
        'acceptanceCriterion': None, 'terminationCriterion': None}


def test_rep_timing_is_rendered_and_only_rep_based_exercises_accept_it():
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item['repDurationSeconds'] = 6
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['passed']
    assert result['audit']['workouts'][0]['timing']['workSeconds'] == 5 * 10 * 6
    assert '6s/rep' in result['preview'] and 'complete calibration trial budgets' not in result['preview']
    definition = equipment['exerciseDefinitions'][0]
    definition.update(exerciseType='COUNTDOWN', bodyWeightPercentage=None)
    item.update(minReps=None, maxReps=None, durationSeconds=30)
    with pytest.raises(ValueError, match='Per-rep timing applies only'):
        build_draft_plan(draft, equipment, stored['requirements'])


@pytest.mark.parametrize('warmups', [False, True])
def test_execution_instructions_follow_final_prescription_and_runtime_warmup_support(warmups):
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, requirements, _, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item.pop('placementNotes', None)
    item['generateWarmUpSets'] = warmups
    plan = build_draft_plan(draft, equipment, requirements)
    notes = plan['exercises'][0]['notes']
    assert '60s estimated changeover' in notes
    assert '5 working sets with 90s between sets' in notes
    assert '0s recovery rest' in notes and 'setup time is additional to this rest' in notes
    assert 'cannot generate lighter loaded ramp-up sets' in notes
    assert 'Personal capability remains unverified.' in notes
    assert item['generateWarmUpSets'] is False and plan['exercises'][0]['generateWarmUpSets'] is False
    other = copy.deepcopy(item)
    item.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterExerciseSeconds=0, restAfterSupersetExerciseSeconds=15)
    other.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterExerciseSeconds=30, restAfterSupersetExerciseSeconds=90)
    draft['workouts'][0]['exercises'].append(other)
    plan = build_draft_plan(draft, equipment, requirements)
    assert 'displayed order for 5 rounds' in plan['exercises'][0]['notes']
    assert 'Rest 15s after this member' in plan['exercises'][0]['notes']
    assert 'Rest 90s after this member' in plan['exercises'][1]['notes']
    assert '30s transition rest' in plan['exercises'][1]['notes']


def test_unilateral_rendering_and_unsupported_warmup_match_audit_semantics():
    from workout_generator_pkg.planning_tools import build_draft_plan
    from workout_generator_pkg.generation_audit import audit_workout_package, plan_audit_package
    equipment, requirements, _, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item.pop('placementNotes', None)
    item.update(intraSetRestInSeconds=20, generateWarmUpSets=True)
    plan = build_draft_plan(draft, equipment, requirements)
    notes = plan['exercises'][0]['notes']
    assert '5 logged working sets' in notes and '20s between sides' in notes
    assert 'Each set includes both sides' in notes and 'Finish both sides before logging that set once' in notes
    assert 'count that paired set once for muscle volume' in notes
    report = audit_workout_package(plan_audit_package(plan, False), requirements['auditTargets'])
    assert report['workouts'][0]['timing']['rampUpSeconds'] == 0
    assert report['weeklyVolume']['chest']['direct'] == 5


def test_latest_draft_audit_uses_materialized_owner_after_rejected_edit():
    from workout_generator_pkg.planning_tools import latest_draft_audit
    draft = {'requirementsId': 'REQ', 'workouts': []}
    owner = {'submittedDraft': draft, 'repairContract': {'redistributions': ['preserved']}}
    rejected = {'passed': False, 'currentDraft': draft, 'errors': [{'code': 'rejected'}]}
    messages = []
    for index, result in enumerate([owner, rejected]):
        messages.extend([{'role': 'assistant', 'tool_calls': [{'id': str(index),
            'function': {'name': 'audit_workout_plan'}}]},
            {'role': 'tool', 'tool_call_id': str(index), 'content': json.dumps(result)}])
    assert latest_draft_audit(messages, draft) == (1, owner)
    assert latest_draft_audit(messages, {**draft, 'name': 'Changed'}) == (-1, {})


def test_legacy_generator_method_does_not_detach_materialized_audit_owner():
    from workout_generator_pkg.planning_tools import latest_draft_audit, latest_draft_submission
    legacy = {'requirementsId': 'REQ', 'workouts': [{'exercises': [
        {'definition_id': 'LIBRARY_0', 'progressionMethod': 'doubleProgression'}]}]}
    owner = {'submittedDraft': legacy, 'currentDraftId': 'REVISION_2'}
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'audit',
        'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(owner)}]
    before = copy.deepcopy(messages)
    canonical, revision = latest_draft_submission(messages)
    assert 'progressionMethod' not in canonical['workouts'][0]['exercises'][0]
    assert revision == 'REVISION_2' and latest_draft_audit(messages, canonical) == (1, owner)
    assert messages == before


def test_legacy_progression_plans_cannot_reintroduce_generator_guidance():
    from workout_generator_pkg.planning_tools import build_draft_plan, _EXERCISE
    equipment, requirements, _, draft = planning_case()
    exercise = draft['workouts'][0]['exercises'][0]
    exercise.update(progressionMethod='doubleProgression', progressionPlan={
        'kind': 'load', 'nextDefinitionId': None, 'nextDefinitionName': None,
        'atCeilingAction': 're_audit_higher_reps'})
    draft['workouts'][0]['exercises'].append(copy.deepcopy(exercise))
    plan = build_draft_plan(draft, equipment, requirements)
    assert 'progressionPlan' not in _EXERCISE['properties']
    assert all('progressionPlan' not in item for item in draft['workouts'][0]['exercises'])
    assert all('maximum selectable load' not in item['notes']
               and 're-audit a higher-rep' not in item['notes']
               and 'do not change load' not in item['notes'] for item in plan['exercises'])

def test_app_owned_progression_needs_no_generator_method_or_algorithm():
    from workout_generator_pkg import domain_ops
    from workout_generator_pkg.planning_tools import _EXERCISE, build_draft_plan
    equipment, requirements, _, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['progressionMethod'] = 'doubleProgression'
    original_reps = (draft['workouts'][0]['exercises'][0]['minReps'], draft['workouts'][0]['exercises'][0]['maxReps'])
    plan = build_draft_plan(draft, equipment, requirements)
    assert 'progressionMethod' not in _EXERCISE['properties']
    assert 'progressionMethod' not in draft['workouts'][0]['exercises'][0]
    actual = domain_ops._materialize_exercise_definition(plan['exercises'][0])
    assert actual['progressionMode'] == 'AUTO_REGULATION'
    assert (actual['minReps'], actual['maxReps']) == original_reps


def test_label_only_repair_schema_cannot_change_exercise_allocation():
    from jsonschema import validate, ValidationError
    from workout_generator_pkg.planning_tools import coordinated_repair_tool, compile_coordinated_repair
    import pytest

    _, requirements, stored, draft = planning_case()
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1',
        'currentDraft': draft, 'requirements': requirements,
        'findingsAssessment': {'groups': [{'disposition': 'repair', 'findingIndexes': [0],
            'repairDimensions': ['session_labels'], 'repairObjectives': []}]}}
    schema = coordinated_repair_tool(task)['function']['parameters']
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'edits': {'workoutUpdates': [
            {'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Workout'}}]}}
    validate(arguments, schema)
    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    assert all(operation['path'].endswith('/description') for operation in compiled['patch'])
    arguments['edits']['exerciseUpdates'] = [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'numWorkSets': 6}}]
    with pytest.raises(ValidationError):
        validate(arguments, schema)
    arguments['edits'].pop('exerciseUpdates')
    arguments['edits']['workoutUpdates'][0]['setFields']['timesCompletedInAWeek'] = 2
    with pytest.raises(ValidationError):
        validate(arguments, schema)


def test_existing_draft_execution_repair_schema_uses_stable_fields_and_order_refs():
    from jsonschema import validate
    from workout_generator_pkg.planning_tools import coordinated_repair_tool

    _, requirements, stored, draft = planning_case()
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1',
        'currentDraft': draft, 'requirements': requirements}
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert 'patch' not in schema['properties']
    edits_schema = schema['properties']['edits']
    assert {'exerciseUpdates', 'exerciseOrders'} <= set(edits_schema['properties'])
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'generateWarmUpSets': False}}],
        'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_1', 'EXERCISE_0']}],
    }}
    validate(arguments, schema)


def test_typed_replacement_schema_stays_compact_for_per_occurrence_allowlists():
    from jsonschema import validate
    from workout_generator_pkg.planning_tools import coordinated_repair_tool

    _, requirements, stored, draft = planning_case()
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1',
        'currentDraft': draft, 'requirements': requirements,
        'replacementDefinitionReferences': ['LIBRARY_90', 'LIBRARY_91'],
        'replacementDefinitionReferencesByExercise': {
            'EXERCISE_0': ['LIBRARY_90'], 'EXERCISE_1': ['LIBRARY_91']}}
    schema = coordinated_repair_tool(task)['function']['parameters']
    update_items = schema['properties']['edits']['properties']['exerciseUpdates']['items']
    assert 'oneOf' not in update_items
    valid = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
            'setFields': {'definition_id': 'LIBRARY_90'}}]}}
    validate(valid, schema)
    invalid = copy.deepcopy(valid)
    invalid['edits']['exerciseUpdates'][0]['setFields']['definition_id'] = 'LIBRARY_91'
    # The compact provider schema exposes the shared replacement catalog. The
    # compiler owns the occurrence-specific allowlist and rejects this before
    # applying any candidate mutation.
    validate(invalid, schema)
