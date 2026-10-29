import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from workout_generator_pkg import generation_audit, joint_planning, planning_tools, session_drafting
from test_workout_generator_development_emphasis import development_case


def credit(**values):
    return {muscle: {'direct': value, 'indirect': 0} for muscle, value in values.items()}


def test_menu_ceiling_includes_required_work_and_exposes_unadmitted_relief():
    selected = [
        {'id': 'C', 'name': 'Press', 'creditsPerWorkingSet': credit(chest=1, shoulders=.5)},
        {'id': 'B', 'name': 'Pull', 'creditsPerWorkingSet': credit(back=1, shoulders=.5)},
        {'id': 'V', 'name': 'Vertical', 'creditsPerWorkingSet': credit(shoulders=1)},
        {'id': 'R', 'name': 'Rear', 'creditsPerWorkingSet': credit(shoulders=1)},
        {'id': 'L', 'name': 'Lateral', 'creditsPerWorkingSet': credit(shoulders=1)},
    ]
    candidates = selected + [{'id': 'X', 'name': 'Alternative',
        'creditsPerWorkingSet': credit(chest=1, back=1)}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 15, 'maximum': 18}, 'back': {'minimum': 15, 'maximum': 18},
        'shoulders': {'minimum': 15, 'maximum': 22}}},
        'requiredCoverage': [{'key': key, 'scope': 'weekly', 'intent': intent}
            for key, intent in [('vertical', 'inclusion'), ('rear', 'inclusion'), ('lateral', 'development')]]}
    coverage = {'C': [], 'B': [], 'V': ['vertical'], 'R': ['rear'], 'L': ['lateral']}

    limits = generation_audit.development_menu_limits(candidates, requirements, coverage,
        source_set_cap=50, training_occurrences=3, minimum_work_sets=2)

    assert limits['status'] == 'proven_upper_bounds'
    assert limits['roleUpperBounds']['lateral'] == pytest.approx(3)
    assert limits['volumeCreditCoupling']['menuRelief']['improvements']
    assert 'X' not in coverage  # Credit-only relief is never a qualified recipe.
    blocked = generation_audit.development_menu_limits(candidates, requirements, coverage,
        source_set_cap=30, training_occurrences=3, minimum_work_sets=2)
    assert blocked['status'] == 'infeasible_relaxation'


def test_infeasible_preparation_exposes_eligible_single_add_volume_witness(monkeypatch):
    selected = [
        {'id': 'PRESS', 'creditsPerWorkingSet': credit(chest=1, shoulders=1)},
        {'id': 'PULL', 'creditsPerWorkingSet': credit(back=1, shoulders=1)},
    ]
    catalog = selected + [{'id': 'PULLOVER', 'name': 'Dumbbell Pullover', 'exerciseType': 'WEIGHT',
        'equipmentName': 'Dumbbell', 'creditsPerWorkingSet': credit(chest=1, back=1)}]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.search_catalog',
        lambda equipment, restrictions: (copy.deepcopy(catalog), 'catalog-fingerprint'))
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 15, 'maximum': 18}, 'back': {'minimum': 15, 'maximum': 18},
        'shoulders': {'minimum': 15, 'maximum': 21}}}}
    result = session_drafting._infeasible_menu_credit_diagnostic(
        [{'exercises': [{'definition_id': item['id']} for item in selected]}],
        {item['id']: item for item in selected},
        {'requirements': requirements, 'restrictionPolicy': {}}, {}, None)

    assert result['selectedMenuVolumeStatus'] == 'infeasible_relaxation'
    assert result['eligibleLibraryVolumeStatus'] == 'proven'
    assert result['scope'] == 'eligible_library_single_add_continuous_weekly_volume_only'
    assert [item['definition_id'] for item in result['alternatives']] == ['PULLOVER']
    assert result['alternatives'][0]['creditProfileStatus'] == 'continuous_volume_feasible_when_added_to_selected_menu'
    assert 'does not establish movement-role qualification' in result['interpretation']


def test_development_role_relief_lp_finds_low_shoulder_credit_profile_without_assigning_it_a_role():
    candidates = [
        {'id': 'PRESS', 'name': 'Press', 'creditsPerWorkingSet': credit(chest=1, shoulders=.5)},
        {'id': 'PULL', 'name': 'Pull', 'creditsPerWorkingSet': credit(back=1, shoulders=.5)},
        {'id': 'LATERAL', 'name': 'Lateral Raise', 'creditsPerWorkingSet': credit(shoulders=1)},
        {'id': 'PULLOVER', 'name': 'Dumbbell Pullover',
            'creditsPerWorkingSet': credit(chest=1, back=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 15, 'maximum': 15}, 'back': {'minimum': 15, 'maximum': 15},
        'shoulders': {'minimum': 0, 'maximum': 18}}},
        'requiredCoverage': [{'key': 'lateral', 'scope': 'weekly', 'intent': 'development'}]}

    limits = generation_audit.development_menu_limits(candidates, requirements,
        {'PRESS': [], 'PULL': [], 'LATERAL': ['lateral']},
        source_set_cap=60, training_occurrences=3, minimum_work_sets=2)

    assert limits['status'] == 'proven_upper_bounds'
    assert limits['roleUpperBounds']['lateral'] == pytest.approx(3)
    relief = limits['developmentRoleRelief']['improvements'][0]
    assert relief['role'] == 'lateral'
    assert relief['creditOnlyRelaxedUpperBound'] == pytest.approx(18)
    witness = relief['outsideMenuWitnessProfiles'][0]
    assert witness['creditsPerWorkingSet'] == {'chest': 1, 'back': 1}
    assert witness['profileRelaxedUpperBound'] == pytest.approx(18)
    assert witness['definitionChoices'] == [{'id': 'PULLOVER', 'name': 'Dumbbell Pullover'}]
    assert witness['qualifiedRoleContribution'] == 0
    assert witness['qualificationStatus'] == 'unqualified'


def test_saved_msg144_keeps_hard_cap_and_surfaces_uncapped_lateral_delt_diagnostic():
    receipt_path = (Path(__file__).resolve().parents[1] / 'build' /
        'workout_quality_policy_20261027' / 'fresh_e2e' / 'workouts' /
        'conversation_sessions' / 'aca503d2-2204-4091-959a-64cc950960f4' / 'messages.json')
    if not receipt_path.exists():
        pytest.skip('The retained msg144 acceptance receipt is not present in this checkout.')
    messages = json.loads(receipt_path.read_text(encoding='utf-8'))
    review = json.loads(messages[144]['content'])
    prepared = next(json.loads(message['content']) for message in messages
        if message.get('role') == 'tool' and '"preparationId": "' + review['preparationId'] + '"' in message.get('content', '')
        and '"sourceWorkingSetBudget"' in message.get('content', ''))
    requirements = next(json.loads(message['content'])['requirements'] for message in messages
        if message.get('role') == 'tool' and '"requirementsId": "' + review['requirementsId'] + '"' in message.get('content', '')
        and '"auditTargets"' in message.get('content', ''))
    coverage = {item['definition_id']: set(item.get('satisfiesCoverage', []))
        for item in review['recipeQualification']['contracts']}
    minimum_work_sets = next(rule['minimumSets'] for rule in requirements['executionRules']
        if rule.get('kind') == 'workSets')

    result = generation_audit.development_menu_limits(list(prepared['candidates'].values()),
        requirements, coverage,
        source_set_cap=prepared['sourceWorkingSetBudget']['variableWeeklyWorkingSets'],
        training_occurrences=requirements['sessionsPerWeek'], minimum_work_sets=minimum_work_sets)

    assert result['status'] == 'infeasible_relaxation'
    assert result['hardFeasibilityStatus'] == 'infeasible_relaxation'
    assert result['roleUpperBounds'] == {}
    assert result['diagnosticRoleUpperBounds']['lateral_delt'] == {
        'weeklySets': pytest.approx(4.5), 'sourceSetCap': 69,
        'sourceSetCapExcluded': True, 'diagnosticOnly': True}
    assert result['diagnosticMinimumConflicts'][0]['role'] == 'lateral_delt'
    assert result['diagnosticMinimumConflicts'][0]['required'] == 6
    assert result['diagnosticMinimumConflicts'][0]['diagnosticOnly'] is True


def test_proven_hard_infeasibility_survives_optional_role_bound_timeout(monkeypatch):
    candidates = [{'id': 'PRESS', 'creditsPerWorkingSet': credit(chest=1)}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 2, 'maximum': 2}}},
        'requiredCoverage': [{'key': 'lateral', 'scope': 'weekly', 'intent': 'development',
            'minimumWeeklySets': 2}]}
    monkeypatch.setattr(generation_audit, 'muscle_credit_coupling_evidence',
        lambda *args, **kwargs: {'status': 'proven'})
    calls = iter([
        SimpleNamespace(success=False, status=2, fun=None, x=None),
        SimpleNamespace(success=False, status=1, fun=None, x=None),
    ])
    monkeypatch.setattr('scipy.optimize.linprog', lambda *args, **kwargs: next(calls))

    result = generation_audit.development_menu_limits(candidates, requirements,
        {'PRESS': ['lateral']}, source_set_cap=None, training_occurrences=1, minimum_work_sets=2)

    assert result['hardFeasibilityStatus'] == 'infeasible_relaxation'
    assert result['status'] == 'infeasible_relaxation'


def test_proven_role_minimum_conflict_survives_later_optional_lp_timeout(monkeypatch):
    candidates = [{'id': 'LATERAL', 'creditsPerWorkingSet': credit(chest=1)}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 1, 'maximum': 2}}},
        'requiredCoverage': [
            {'key': 'lateral', 'scope': 'weekly', 'intent': 'development', 'minimumWeeklySets': 2},
            {'key': 'vertical', 'scope': 'weekly', 'intent': 'development', 'minimumWeeklySets': 2},
        ]}
    monkeypatch.setattr(generation_audit, 'muscle_credit_coupling_evidence',
        lambda *args, **kwargs: {'status': 'proven'})
    calls = iter([
        SimpleNamespace(success=False, status=1, fun=None, x=None),
        SimpleNamespace(success=True, status=0, fun=-1.0, x=[1.0]),
        SimpleNamespace(success=False, status=1, fun=None, x=None),
        SimpleNamespace(success=False, status=1, fun=None, x=None),
    ])
    monkeypatch.setattr('scipy.optimize.linprog', lambda *args, **kwargs: next(calls))

    result = generation_audit.development_menu_limits(candidates, requirements,
        {'LATERAL': ['lateral']}, source_set_cap=None, training_occurrences=1, minimum_work_sets=1)

    assert result['hardFeasibilityStatus'] == 'unproven'
    assert result['approvedMinimumConflicts'][0]['role'] == 'lateral'
    assert result['status'] == 'infeasible_relaxation'


def test_diagnostic_upper_bound_conflict_blocks_when_global_lp_is_unproven(monkeypatch):
    candidates = [{'id': 'LATERAL', 'creditsPerWorkingSet': credit(chest=1)}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 1, 'maximum': 10}}},
        'requiredCoverage': [{'key': 'lateral', 'scope': 'weekly', 'intent': 'development',
            'minimumWeeklySets': 6}]}
    monkeypatch.setattr(generation_audit, 'muscle_credit_coupling_evidence',
        lambda *args, **kwargs: {'status': 'proven'})
    calls = iter([
        SimpleNamespace(success=False, status=1, fun=None, x=None),
        SimpleNamespace(success=False, status=2, fun=None, x=None),
        SimpleNamespace(success=True, status=0, fun=-4.5, x=[4.5]),
        SimpleNamespace(success=False, status=1, fun=None, x=None),
    ])
    monkeypatch.setattr('scipy.optimize.linprog', lambda *args, **kwargs: next(calls))

    result = generation_audit.development_menu_limits(candidates, requirements,
        {'LATERAL': ['lateral']}, source_set_cap=4, training_occurrences=1, minimum_work_sets=2)

    assert result['hardFeasibilityStatus'] == 'unproven'
    assert result['diagnosticMinimumConflicts'][0]['qualifiedMenuUpperBound'] == 4.5
    assert result['diagnosticMinimumConflicts'][0]['diagnosticOnly'] is True
    assert result['status'] == 'infeasible_relaxation'


def test_no_cap_role_bound_reports_other_role_minimum_as_coverage_achieved():
    candidates = [
        {'id': 'LATERAL', 'creditsPerWorkingSet': credit(chest=1)},
        {'id': 'VERTICAL', 'creditsPerWorkingSet': credit(back=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 1, 'maximum': 6}, 'back': {'minimum': 2, 'maximum': 2}}},
        'requiredCoverage': [
            {'key': 'lateral', 'scope': 'weekly', 'intent': 'development', 'minimumWeeklySets': 2},
            {'key': 'vertical', 'scope': 'weekly', 'intent': 'development', 'minimumWeeklySets': 2},
        ]}

    result = generation_audit.development_menu_limits(candidates, requirements,
        {'LATERAL': ['lateral'], 'VERTICAL': ['vertical']}, source_set_cap=None,
        training_occurrences=1, minimum_work_sets=2)

    assert result['status'] == 'proven_upper_bounds'
    lateral_constraints = result['roleUpperBoundConstraints']['lateral']
    vertical_minimum = next(item for item in lateral_constraints
        if item['kind'] == 'approved_weekly_sets_minimum' and item['key'] == 'vertical')
    assert vertical_minimum['achieved'] == pytest.approx(2)
    assert 'slack' not in vertical_minimum


def test_hard_infeasible_menu_proves_only_relief_profile_that_restores_full_relaxation():
    candidates = [
        {'id': 'LATERAL', 'name': 'Lateral Raise',
            'creditsPerWorkingSet': credit(shoulders=1)},
        {'id': 'PRESS', 'name': 'Press',
            'creditsPerWorkingSet': credit(chest=1, shoulders=1)},
        {'id': 'PULL', 'name': 'Row',
            'creditsPerWorkingSet': credit(back=1, shoulders=1)},
        {'id': 'EXTRA_LATERAL', 'name': 'Other Lateral Raise',
            'creditsPerWorkingSet': credit(shoulders=1)},
        {'id': 'PULLOVER', 'name': 'Dumbbell Pullover',
            'creditsPerWorkingSet': credit(chest=1, back=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 2, 'maximum': 2}, 'back': {'minimum': 2, 'maximum': 2},
        'shoulders': {'minimum': 0, 'maximum': 2}}},
        'requiredCoverage': [{'key': 'lateral', 'scope': 'weekly', 'intent': 'development',
            'minimumWeeklySets': 2}]}

    result = generation_audit.development_menu_limits(candidates, requirements,
        {'LATERAL': ['lateral'], 'PRESS': [], 'PULL': []}, source_set_cap=None,
        training_occurrences=1, minimum_work_sets=2)

    assert result['hardFeasibilityStatus'] == 'infeasible_relaxation'
    proof = result['developmentRoleRelief']['singleAdditionFeasibility']
    assert proof['status'] == 'feasible_relaxation'
    assert proof['sourceSetCapApplied'] is False
    assert [choice['id'] for addition in proof['additions']
        for choice in addition['definitionChoices']] == ['PULLOVER']
    assert proof['additions'][0]['qualificationStatus'] == 'unqualified'
    assert proof['additions'][0]['qualifiedRoleContribution'] == 0


def test_saved_msg153_hard_infeasibility_never_offers_acceptance_question(monkeypatch):
    receipt_path = (Path(__file__).resolve().parents[1] / 'build' /
        'workout_quality_policy_20261027' / 'fresh_e2e' / 'workouts' /
        'conversation_sessions' / 'aca503d2-2204-4091-959a-64cc950960f4' / 'messages.json')
    if not receipt_path.exists():
        pytest.skip('The retained msg153 acceptance receipt is not present in this checkout.')
    messages = json.loads(receipt_path.read_text(encoding='utf-8'))
    saved_gate = json.loads(messages[153]['content'])
    prepared = next(json.loads(message['content']) for message in messages
        if message.get('role') == 'tool'
        and '"preparationId": "' + saved_gate['preparationId'] + '"' in message.get('content', '')
        and '"sourceWorkingSetBudget"' in message.get('content', ''))
    requirements_result = next(json.loads(message['content']) for message in messages
        if message.get('role') == 'tool'
        and '"requirementsId": "' + saved_gate['requirementsId'] + '"' in message.get('content', '')
        and '"auditTargets"' in message.get('content', ''))
    qualifications = {item['definition_id']: item.get('satisfiesCoverage', [])
        for item in saved_gate['recipeQualification']['contracts']}
    selections = copy.deepcopy(prepared['recipeSessions'])
    for day in selections:
        for item in day['exercises']:
            item['satisfiesCoverage'] = copy.deepcopy(qualifications.get(item['definition_id'], []))
    evidence = saved_gate['menuReview']['evidence']
    assert evidence['status'] == 'unproven'
    assert evidence['hardFeasibilityStatus'] == 'infeasible_relaxation'
    assert evidence['approvedMinimumConflicts']

    candidates = prepared['candidates']
    monkeypatch.setattr(session_drafting, 'get_exercise_candidates',
        lambda arguments, *_: {'exercises': [copy.deepcopy(candidates[item_id])
            for item_id in arguments['definition_ids'] if item_id in candidates]})
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.definition_available', lambda *_: True)
    monkeypatch.setattr('workout_generator_pkg.restriction_policy.effective_restrictions',
        lambda *_: {})
    monkeypatch.setattr(generation_audit, 'development_menu_limits',
        lambda *args, **kwargs: copy.deepcopy(evidence))
    equipment = {'exerciseDefinitions': [{'id': f'{index:04d}'} for index in range(len(candidates))]}

    review = session_drafting._development_menu_review(prepared, selections,
        {'requirements': requirements_result['requirements'],
         'restrictionPolicy': requirements_result.get('restrictionPolicy')},
        equipment, [], None)

    assert review['evidence']['status'] == 'unproven'
    assert review['evidence']['hardFeasibilityStatus'] == 'infeasible_relaxation'
    assert review.get('accepted') is None
    assert review.get('question') is None


def test_infeasible_menu_review_projects_only_diagnostic_unqualified_relief(monkeypatch):
    equipment, _, _ = development_case()
    while len(equipment['exerciseDefinitions']) < 2:
        definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
        definition['id'] = f"test_menu_candidate_{len(equipment['exerciseDefinitions'])}"
        equipment['exerciseDefinitions'].append(definition)
    requirements = {'requirements': {'requiredCoverage': [
        {'key': 'lateral', 'intent': 'development'}]}}
    prepared = {'preparationId': 'P1', 'sourceWorkingSetBudget': {'variableWeeklyWorkingSets': 20}}
    sessions = [{'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['lateral'],
         'allocationBounds': {'minimum': 2}}]}]
    candidates = [
        {'id': 'LIBRARY_0', 'name': 'Selected', 'creditsPerWorkingSet': credit(shoulders=1)},
        {'id': 'LIBRARY_1', 'name': 'Shoulder Relief', 'creditsPerWorkingSet': credit(chest=1, back=1)},
    ]
    monkeypatch.setattr(session_drafting, 'get_exercise_candidates',
        lambda arguments, *_: {'exercises': [item for item in candidates
            if item['id'] in arguments['definition_ids']]})
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.definition_available',
        lambda *_: True)
    monkeypatch.setattr(generation_audit, 'development_menu_limits', lambda *a, **k: {
        'status': 'infeasible_relaxation', 'roleUpperBounds': {},
        'diagnosticRoleUpperBounds': {'lateral': {'weeklySets': 4.5,
            'sourceSetCap': 20, 'sourceSetCapExcluded': True, 'diagnosticOnly': True}},
        'diagnosticMinimumConflicts': [{'role': 'lateral', 'kind': 'minimumWeeklySets',
            'required': 6, 'qualifiedMenuUpperBound': 4.5, 'sourceSetCapExcluded': True,
            'diagnosticOnly': True}],
        'volumeCreditCoupling': {'menuRelief': {'status': 'unproven', 'improvements': []}},
        'developmentRoleRelief': {'status': 'proven', 'improvements': [{
            'role': 'lateral', 'selectedMenuUpperBound': 4.5, 'creditOnlyRelaxedUpperBound': 6,
            'sourceSetCapExcluded': True, 'diagnosticOnly': True,
            'outsideMenuWitnessProfiles': [{'creditsPerWorkingSet': {'chest': 1, 'back': 1},
                'profileRelaxedUpperBound': 6, 'relaxedWeeklyWorkingSets': 15,
                'definitionChoices': [{'id': 'LIBRARY_1', 'name': 'Shoulder Relief'}],
                'qualificationStatus': 'unqualified', 'qualifiedRoleContribution': 0,
                'sourceSetCap': 20, 'sourceSetCapExcluded': True, 'diagnosticOnly': True}]}]}})

    review = session_drafting._development_menu_review(prepared, sessions, requirements,
        equipment, [], None)

    assert review.get('accepted') is None
    assert review.get('question') is None
    evidence = review['evidence']
    assert evidence['diagnosticMinimumConflicts'][0]['qualifiedMenuUpperBound'] == 4.5
    alternative = evidence['selectableCreditProfileAlternatives']['alternatives'][0]
    assert alternative['definition_id'] == 'LIBRARY_1'
    assert alternative['qualificationStatus'] == 'unqualified'
    assert alternative['developmentRoleRelief'][0]['sourceSetCapExcluded'] is True
    assert alternative['developmentRoleRelief'][0]['diagnosticOnly'] is True


def test_explicit_development_priority_order_is_used_once_by_native_solver():
    equipment, requirements, sessions = development_case()
    requirements['objectiveOrder'] = ['development_emphasis', 'development_exposure',
        'exercise_distribution', 'distribution', 'source_balance', 'preservation']
    validate(requirements, planning_tools._REQUIREMENTS)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    goals = [stage['goal'] for stage in result['objectiveProgress']]
    assert goals[:3] == ['development_emphasis', 'development_exposure', 'distribution']
    assert goals.count('development_emphasis') == goals.count('development_exposure') == 1
    assert result['priorityExecution']['approvedPriorities'][1]['owner'] == 'joint_solver'


def test_candidate_comparison_honors_explicit_development_before_session_equality():
    from test_workout_generator_joint_candidate_comparison import _candidate, _context, _requirements
    requirements = _requirements(['development_emphasis', 'development_exposure', 'distribution'])
    requirements['requiredCoverage'] = [{'key': role, 'scope': 'weekly', 'intent': 'development'}
        for role in ('a', 'b')]
    baseline = _candidate([3, 3], definition_ids=['LIBRARY_1', 'LIBRARY_2'])
    candidate = _candidate([3, 5], definition_ids=['LIBRARY_1', 'LIBRARY_2'])
    for item, totals in ((baseline, [3, 3]), (candidate, [3, 5])):
        for index, role in enumerate(('a', 'b')):
            item['workouts'][index]['exercises'][0]['satisfiesCoverage'] = [role]
            item['audit']['workouts'][index]['coverageSets'] = {role: totals[index]}
        item['audit']['weeklyCoverageSets'] = dict(zip(('a', 'b'), totals))
    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_1': ['a'], 'LIBRARY_2': ['b']}

    result = joint_planning.compare_audited_joint_candidates(baseline, candidate,
        requirements=requirements, context=context)

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'development_exposure'


def test_menu_limit_acceptance_belongs_to_the_disclosed_menu_and_evidence(monkeypatch):
    equipment, _, _ = development_case()
    requirements = {'requirements': {'requiredCoverage': [{'key': 'role', 'intent': 'development'}],
        'objectiveOrder': ['development_emphasis']}}
    prepared = {'preparationId': 'P1', 'requirementsId': 'R1', 'baseDraftId': None,
        'libraryFingerprint': 'L1', 'historyFingerprint': 'H1', 'draftingVersion': 29,
        'sourceMessages': {}, 'sourceWorkingSetBudget': {
            'variableWeeklyWorkingSets': 6, 'preparationId': 'P1'}}
    prepared['sourceBudgetAuthority'] = {'requirementsId': 'R1', 'baseDraftId': None,
        'libraryFingerprint': 'L1', 'historyFingerprint': 'H1', 'restrictionPolicy': None,
        'resolvedDecisions': {}, 'sourceMessages': {}}
    sessions = [{'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['role'], 'allocationBounds': {'minimum': 2}}]}]
    evidence = {'status': 'proven_upper_bounds', 'roleUpperBounds': {'role': 3},
        'volumeCreditCoupling': {'menuRelief': {'status': 'proven', 'improvements': [{
            'selectedDefinitions': [{'id': 'LIBRARY_0', 'name': 'Selected'}],
            'minimumWeeklyWorkingSetsSelectedPool': 4,
            'minimumWeeklyWorkingSetsRetrievedPool': 2,
            'outsideMenuWitnessProfiles': [{'creditsPerWorkingSet': {'back': 1},
                    'profileRelaxedUpperBound': 12, 'relaxedWeeklyWorkingSets': 2,
                'definitionChoices': [{'id': 'LIBRARY_1', 'name': 'Alternative'}]}]}]}}}
    monkeypatch.setattr(generation_audit, 'development_menu_limits', lambda *a, **k: copy.deepcopy(evidence))
    first = session_drafting._development_menu_review(prepared, sessions, requirements, equipment, [], None)
    assert first['accepted'] is False
    disclosure = {'preparationId': 'P1', 'menuReview': first, 'userQuestion': first['question']}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'prep', 'function': {'name': 'prepare_workout_sessions'}}]},
        {'role': 'tool', 'tool_call_id': 'prep', 'content': json.dumps(prepared)},
        {'role': 'assistant', 'tool_calls': [{'id': 'review', 'function': {'name': 'draft_workout_sessions'}}]},
        {'role': 'tool', 'tool_call_id': 'review', 'content': json.dumps(disclosure)},
        {'role': 'assistant', 'content': first['question']['question']},
        {'role': 'user', 'content': 'My answer: ' + first['question']['options'][1]},
    ]

    accepted = session_drafting._development_menu_review(prepared, sessions, requirements, equipment, messages, None)
    assert accepted['accepted'] is True
    mismatched_latest = copy.deepcopy(messages)
    mismatched_latest[2:2] = [
        {'role': 'assistant', 'tool_calls': [{'id': 'newer-prep', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'newer-prep', 'content': json.dumps({**prepared,
            'preparationId': 'P2', 'sourceWorkingSetBudget': {
                'variableWeeklyWorkingSets': 9, 'preparationId': 'P2'}})},
    ]
    assert planning_tools.accepted_menu_preparation(mismatched_latest, 'R1', None, 'L1', 'H1', 29,
        None, {}) is None
    changed = session_drafting._development_menu_review({**prepared, 'preparationId': 'P2'},
        sessions, requirements, equipment, messages, None)
    assert changed['accepted'] is False
    changed_budget = copy.deepcopy(prepared)
    changed_budget['sourceWorkingSetBudget']['variableWeeklyWorkingSets'] = 7
    assert not session_drafting._development_menu_review(changed_budget, sessions,
        requirements, equipment, messages, None)['accepted']
    evidence['roleUpperBounds']['role'] = 4
    changed_evidence = session_drafting._development_menu_review(prepared, sessions,
        requirements, equipment, messages, None)
    assert changed_evidence['accepted'] is False
    messages[-1]['content'] = '/continue'
    assert not session_drafting._development_menu_review(prepared, sessions,
        requirements, equipment, messages, None)['accepted']


def test_menu_review_exposes_concrete_credit_candidates_without_qualifying_or_admitting_them(monkeypatch):
    equipment, _, _ = development_case()
    while len(equipment['exerciseDefinitions']) < 3:
        definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
        definition['id'] = f"test_menu_candidate_{len(equipment['exerciseDefinitions'])}"
        equipment['exerciseDefinitions'].append(definition)
    requirements = {'requirements': {'requiredCoverage': [{'key': 'role', 'intent': 'development'}]}}
    prepared = {'preparationId': 'P1', 'sourceWorkingSetBudget': {'variableWeeklyWorkingSets': 6}}
    sessions = [{'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['role'], 'allocationBounds': {'minimum': 2}}]}]
    candidates = [
        {'id': 'LIBRARY_0', 'name': 'Selected', 'creditsPerWorkingSet': credit(chest=1)},
        {'id': 'LIBRARY_1', 'name': 'Generic Alternative', 'creditsPerWorkingSet': credit(back=1)},
        {'id': 'LIBRARY_2', 'name': 'Development Alternative', 'creditsPerWorkingSet': credit(back=1)},
    ]
    monkeypatch.setattr(session_drafting, 'get_exercise_candidates',
        lambda arguments, *_: {'exercises': [item for item in candidates if item['id'] in arguments['definition_ids']]})
    monkeypatch.setattr(generation_audit, 'development_menu_limits', lambda *a, **k: {
        'status': 'proven_upper_bounds', 'roleUpperBounds': {'role': 3},
        'developmentRoleRelief': {'status': 'proven', 'improvements': [{
            'role': 'role', 'selectedMenuUpperBound': 3, 'creditOnlyRelaxedUpperBound': 12,
            'outsideMenuWitnessProfiles': [{'creditsPerWorkingSet': {'back': 1},
                'profileRelaxedUpperBound': 12, 'relaxedWeeklyWorkingSets': 2,
                'definitionChoices': [{'id': 'LIBRARY_2', 'name': 'Development Alternative'}]}]}]},
        'volumeCreditCoupling': {'menuRelief': {'status': 'proven', 'improvements': [{
            'selectedDefinitions': [{'id': 'LIBRARY_0', 'name': 'Selected'}],
            'minimumWeeklyWorkingSetsSelectedPool': 4,
            'minimumWeeklyWorkingSetsRetrievedPool': 2,
            'outsideMenuWitnessProfiles': [{'creditsPerWorkingSet': {'back': 1},
                'relaxedWeeklyWorkingSets': 2,
                'definitionChoices': [{'id': 'LIBRARY_1', 'name': 'Alternative'}]}]}]}}})

    review = session_drafting._development_menu_review(prepared, sessions, requirements, equipment, [], None)

    assert review.get('question') is None
    assert review.get('accepted') is None
    alternatives = review['evidence']['selectableCreditProfileAlternatives']['alternatives']
    assert [item['definition_id'] for item in alternatives] == ['LIBRARY_2', 'LIBRARY_1']
    assert alternatives[0]['qualificationStatus'] == 'unqualified'
    assert alternatives[0]['creditsPerWorkingSet'] == {'back': 1}
    assert alternatives[0]['developmentRoleRelief'][0]['creditOnlyRelaxedUpperBound'] == 12
    assert alternatives[0]['developmentRoleRelief'][0]['profileRelaxedUpperBound'] == 12
    assert alternatives[1]['selectionEvidence'][0]['selectedDefinitions'] == [
        {'id': 'LIBRARY_0', 'name': 'Selected'}]
    assert 'not qualified' in review['evidence']['selectableCreditProfileAlternatives']['scope']

    requested = copy.deepcopy(requirements)
    requested['requirements']['objectiveOrder'] = ['development_exposure']
    explicit_review = session_drafting._development_menu_review(
        prepared, sessions, requested, equipment, [], None)
    assert explicit_review.get('question')


def test_selected_menu_suggestion_enters_preparation_and_is_qualified_before_joint_solve(monkeypatch):
    import test_workout_generator_parallel_planning as parallel

    build_case = parallel.planning_case
    def case_with_suggestion():
        equipment, requirements, fixed, draft = build_case()
        equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]),
            'id': 'alternate_press', 'name': 'Alternative Press'})
        return equipment, requirements, fixed, draft
    monkeypatch.setattr(parallel, 'planning_case', case_with_suggestion)
    equipment, messages, original, _ = parallel.week_case()
    alternative = 'LIBRARY_1'
    selected_suggestion = {'definition_id': alternative, 'qualificationStatus': 'unqualified'}
    revised = {'requirementsId': original['requirementsId'], 'baseDraftId': original['baseDraftId'],
        'name': original['name'], 'sessions': []}
    for index, day in enumerate(original['recipeSessions']):
        revised['sessions'].append({key: copy.deepcopy(day[key]) for key in
            ('name', 'description', 'timesCompletedInAWeek', 'trainingDays')} | {'blocks': [{
                'numWorkSets': day['exercises'][0]['numWorkSets'], 'allocationBounds': day['exercises'][0]['allocationBounds'],
                'exercises': [{'definition_id': selected_suggestion['definition_id']}]}]})
    revised_preparation = session_drafting.prepare_workout_sessions(revised, messages, equipment)
    assert alternative in revised_preparation['definition_ids']
    assert revised_preparation['sourceWorkingSetBudget'] == original['sourceWorkingSetBudget']
    parallel.store_tool(messages, 'prepare_workout_sessions', revised, revised_preparation)

    qualified_refs = []
    def qualify(*args, **kwargs):
        prepared = args[1]
        qualified_refs.extend(prepared['definition_ids'])
        return {'contracts': [{'definition_id': reference, 'satisfiesCoverage': []}
            for reference in prepared['definition_ids']]}
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts', qualify)
    monkeypatch.setattr(session_drafting, 'chat_call',
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('stop after qualification')))
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *a, **k: pytest.fail('The joint solver must not receive an unqualified menu.'))
    state = parallel.request_planning_state(parallel.shell._messages_for_api(
        messages, True, provided_equipment=equipment))

    result = session_drafting.draft_workout_sessions(None,
        {'preparationId': revised_preparation['preparationId']}, messages, equipment, state)

    assert qualified_refs == [alternative]
    assert result['errors'][0]['message'] == 'stop after qualification'
    assert 'jointPlanning' not in result


def test_menu_review_stops_before_session_model_calls(monkeypatch):
    from test_workout_generator_parallel_planning import week_case
    from workout_generator_pkg.planner_context import request_planning_state
    from workout_generator_pkg import interactive_shell
    equipment, messages, prepared, _ = week_case()
    question = {'kind': 'clarification', 'question': 'Review the supplied menu limits?',
        'options': ['Revise menu', 'Accept limits']}
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *a, **k: {'contracts': []})
    monkeypatch.setattr(session_drafting, '_development_menu_review',
        lambda *a, **k: {'question': question, 'accepted': False,
                         'evidence': {'status': 'proven_upper_bounds'}})
    monkeypatch.setattr(session_drafting, 'chat_call',
        lambda *a, **k: pytest.fail('Session prescriptions must wait for menu adjudication.'))
    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))

    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, state)

    assert result['passed'] is False
    assert result['userQuestion'] == question
    assert 'workerResults' not in result


def test_menu_gate_reopens_selection_after_the_ordinary_reconsideration():
    from test_workout_generator_parallel_planning import week_case, store_tool
    from workout_generator_pkg.planner_context import request_planning_state, construction_tool_failure
    from workout_generator_pkg import interactive_shell
    equipment, messages, prepared, _ = week_case()
    store_tool(messages, 'prepare_workout_sessions', {}, prepared)
    review = {'accepted': False, 'question': {'question': 'Menu limits?', 'options': ['Revise', 'Accept']},
        'evidence': {'selectableCreditProfileAlternatives': {'alternatives': [
            {'definition_id': 'LIBRARY_1', 'qualificationStatus': 'unqualified'}]}}}
    store_tool(messages, 'draft_workout_sessions', {}, {'preparationId': prepared['preparationId'],
        'passed': False, 'errors': [], 'menuReview': review, 'userQuestion': review['question']})

    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert state['constructionTask']['reviewAllocationBeforeDrafting']
    assert state['constructionTask']['menuReview'] == review
    assert 'qualificationStatus=unqualified' in state['constructionTask']['instruction']
    assert construction_tool_failure('prepare_workout_sessions', {}, state) is None


def test_disclosure_keeps_menu_ceiling_separate_from_attained_dose():
    evidence = {'developmentEmphasis': {'roleKeys': ['lateral_delt'], 'status': 'feasible',
        'minimumWeeklyWorkingSets': 2, 'menuLimits': {'status': 'proven_upper_bounds',
            'roleUpperBounds': {'lateral_delt': 3}, 'accepted': True}}}

    text = generation_audit.render_optimization_disclosure(evidence)

    assert 'attained minimum 2' in text
    assert 'lateral delt: 3' in text
    assert 'not target doses' in text
    assert 'explicitly accepted' in text
