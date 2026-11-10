import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg.generation_audit import (available_muscle_targets, muscle_credits_per_set,
    muscle_credit_coupling_evidence, muscle_metadata_policy, render_optimization_disclosure)
from workout_generator_pkg.planning_tools import workout_requirements_tool, set_workout_requirements, audit_workout_plan, PlanningInputError
from workout_generator_pkg.plan_contract import hydrate_plan_index_from_exercise_library
from test_workout_generator_planning_tools import planning_case, capability_requirement_messages


@pytest.mark.parametrize('category', ['ISOLATION', 'HEAVY_COMPOUND', None])
def test_accounting_uses_only_existing_primary_and_secondary_muscles(category):
    definition = {'exerciseType': 'WEIGHT', 'exerciseCategory': category,
        'muscleGroups': ['FRONT_CHEST', 'FRONT_CHEST'],
        'secondaryMuscleGroups': ['FRONT_CHEST', 'FRONT_TRICEPS', 'BACK_TRICEPS'],
        'trainingMuscles': {'primary': ['lateralDelts'], 'secondary': ['rearDelts']}}
    expected = {'chest': {'direct': 1, 'indirect': 0}, 'triceps': {'direct': 0, 'indirect': 0.5}}
    assert muscle_credits_per_set(definition) == expected
    definition['trainingMuscles'] = 'unused legacy metadata'
    assert muscle_credits_per_set(definition) == expected


def test_discovery_and_supported_targets_ignore_alternative_muscle_annotations():
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    from workout_generator_pkg.semantic_retrieval import _entry_text
    gear, _, _, _ = planning_case()
    definition = gear['exerciseDefinitions'][0]
    definition['secondaryMuscleGroups'] = ['FRONT_TRICEPS']
    definition['exerciseCategory'] = 'ISOLATION'
    definition['trainingMuscles'] = {'primary': ['lateralDelts'], 'secondary': []}
    candidate = get_exercise_candidates({'definition_ids': ['LIBRARY_0']}, gear)['exercises'][0]
    assert 'trainingMuscles' not in candidate
    assert candidate['creditsPerWorkingSet'] == muscle_credits_per_set(definition)
    assert set(available_muscle_targets(gear)) == {'chest', 'triceps'}
    assert 'lateralDelts' not in _entry_text(definition)
    policy = muscle_metadata_policy(available_muscle_targets(gear))
    assert 'muscleGroups' in policy['interpretation']
    assert 'derived view' in policy['interpretation']


def test_alternative_annotations_cannot_enable_unrepresented_targets():
    gear, arguments, _, _ = planning_case()
    gear['exerciseDefinitions'][0]['trainingMuscles'] = {'primary': ['lats'], 'secondary': ['upperBack']}
    arguments['auditTargets']['weeklyEffectiveSets'] = {'lats': {'minimum': 5, 'maximum': 6}}
    arguments['auditTargets']['perSessionEffectiveSets'] = {}
    with pytest.raises((PlanningInputError, ValidationError)):
        set_workout_requirements(arguments, [], gear)
    schema = workout_requirements_tool(gear)['function']['parameters']['properties']['auditTargets']
    assert 'lats' not in schema['properties']['weeklyEffectiveSets']['properties']


def test_final_audit_and_export_project_the_same_authoritative_roles():
    from workout_generator_pkg.domain_ops import apply_exercise_library_schema_v2
    gear, _, stored, draft = planning_case()
    definition = gear['exerciseDefinitions'][0]
    definition['trainingMuscles'] = {'primary': ['lateralDelts'], 'secondary': []}
    result = audit_workout_plan(draft, gear, capability_requirement_messages(stored, gear))
    assert result['passed']
    assert result['audit']['weeklyVolume']['chest']['effective'] == 5
    assert 'lateralDelts' not in result['audit']['weeklyVolume']
    assert not any(e['code'] == 'missing_training_muscle_roles' for e in result['errors'])
    plan = result['planIndex']
    hydrate_plan_index_from_exercise_library(plan, gear['exerciseDefinitions'])
    package = {'workouts': [{'workoutComponents': [dict(plan['exercises'][0], type='Exercise', sets=[])]}]}
    apply_exercise_library_schema_v2(package, gear['exerciseDefinitions'])
    expected = {'primary': ['chest'], 'secondary': ['triceps']}
    assert plan['exercises'][0]['trainingMuscles'] == expected
    assert package['exerciseDefinitions'][0]['trainingMuscles'] == expected
    assert package['workouts'][0]['workoutComponents'][0]['trainingMuscles'] == expected
    assert definition['trainingMuscles'] == {'primary': ['lateralDelts'], 'secondary': []}


def test_library_loader_does_not_validate_unused_annotations(tmp_path):
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload
    gear, _, _, _ = planning_case()
    gear['exerciseDefinitions'][0]['trainingMuscles'] = 'obsolete annotation'
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(gear), encoding='utf-8')
    loaded = _load_exercise_library_payload(str(path))
    assert muscle_credits_per_set(loaded['exerciseDefinitions'][0]) == {
        'chest': {'direct': 1, 'indirect': 0}, 'triceps': {'direct': 0, 'indirect': 0.5}}


def test_reviewed_positive_regions_upgrade_the_parent_once_without_erasing_legacy_roles():
    from copy import deepcopy
    from workout_generator_pkg.muscle_roles import project_training_muscles

    definition = {'id': 'unreviewed', 'exerciseType': 'WEIGHT',
        'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': ['BACK_UPPER_BACK', 'FRONT_BICEPS'],
        'anatomy': {'primarySubregions': ['latissimus_dorsi', 'upper_back'],
            'secondarySubregions': ['deltoid_posterior'],
            'source': 'https://example.org/reviewed', 'basis': 'Controlled reviewed role fixture.'},
        'trainingMuscles': {'primary': ['lateralDelts'], 'secondary': ['lats']}}
    credits = muscle_credits_per_set(definition)
    assert credits['back'] == {'direct': 1, 'indirect': 0}
    assert credits['chest'] == {'direct': 1, 'indirect': 0}
    assert credits['biceps'] == {'direct': 0, 'indirect': 0.5}
    assert credits['shoulders'] == {'direct': 0, 'indirect': 0.5}
    projected = project_training_muscles(deepcopy(definition))
    assert 'BACK_UPPER_BACK' in projected['muscleGroups']
    assert 'BACK_UPPER_BACK' not in projected['secondaryMuscleGroups']
    assert muscle_credits_per_set(projected) == credits
    assert projected['trainingMuscles'] == {
        'primary': ['back', 'chest', 'latissimus_dorsi', 'upper_back'],
        'secondary': ['biceps', 'deltoid_posterior', 'shoulders']}
    assert project_training_muscles(deepcopy(projected)) == projected


def test_overhead_press_materialization_retains_chest_assistance_and_reviewed_lateral_role():
    from copy import deepcopy
    from workout_generator_pkg.domain_ops import _materialize_exercise_definition, apply_exercise_library_schema_v2

    definition = {'id': '8b6b9813-39b1-5c86-89bf-22ab6828556e', 'name': 'Barbell Overhead Press',
        'exerciseType': 'WEIGHT', 'equipmentId': None, 'bodyWeightPercentage': None,
        'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['FRONT_DELTOIDS'],
        'secondaryMuscleGroups': ['BACK_TRICEPS', 'BACK_TRAPEZIUS', 'FRONT_CHEST'],
        'exerciseCategory': 'HEAVY_COMPOUND',
        'trainingMuscles': {'primary': ['anteriorDelts', 'lateralDelts'], 'secondary': ['upperBack']}}
    original = deepcopy(definition)
    plan = {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': definition['id'],
        'numWorkSets': 2, 'minReps': 5, 'maxReps': 10, 'restBetweenSetsSeconds': 60,
        'generateWarmUpSets': False, 'intraSetRestInSeconds': None}], 'workouts': []}
    hydrate_plan_index_from_exercise_library(plan, [definition])
    entry = plan['exercises'][0]
    expected = {'primary': ['deltoid_anterior', 'shoulders'],
        'secondary': ['chest', 'deltoid_lateral', 'traps', 'triceps']}
    assert entry['trainingMuscles'] == expected
    assert entry['muscleGroups'] == definition['muscleGroups']
    assert entry['secondaryMuscleGroups'] == definition['secondaryMuscleGroups']
    component = _materialize_exercise_definition(entry)
    assert component['trainingMuscles'] == expected
    package = {'workouts': [{'workoutComponents': [component]}]}
    apply_exercise_library_schema_v2(package, [definition])
    exported = package['exerciseDefinitions'][0]
    assert exported['trainingMuscles'] == component['trainingMuscles'] == expected
    assert exported['id'] == definition['id']
    assert muscle_credits_per_set(exported)['chest'] == {'direct': 0, 'indirect': 0.5}
    assert muscle_credits_per_set(exported)['deltoid_lateral'] == {'direct': 0, 'indirect': 0.5}
    assert definition == original


def test_credit_coupling_reports_menu_conditioned_hamstring_only_floor():
    credit = lambda **values: {muscle: {'direct': amount, 'indirect': 0} for muscle, amount in values.items()}
    candidates = [
        {'id': 'squat', 'creditsPerWorkingSet': credit(quads=1, glutes=1)},
        {'id': 'rdl', 'creditsPerWorkingSet': credit(hamstrings=1, glutes=1)},
        {'id': 'nordic', 'creditsPerWorkingSet': credit(hamstrings=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        muscle: {'minimum': 15, 'maximum': maximum}
        for muscle, maximum in {'quads': 18, 'hamstrings': 18, 'glutes': 18}.items()}}}
    result = muscle_credit_coupling_evidence(candidates, requirements)
    nordic = next(item for item in result['profileLowerBounds'] if item['members'][0]['id'] == 'nordic')
    assert result['status'] == 'proven'
    assert nordic['minimumWeeklyWorkingSets'] == pytest.approx(12)
    assert nordic['activeWeeklyVolumeTargets'] == [
        {'muscle': 'quads', 'boundary': 'minimum', 'targetSets': 15, 'achievedSets': 15.0},
        {'muscle': 'hamstrings', 'boundary': 'minimum', 'targetSets': 15, 'achievedSets': 15.0},
        {'muscle': 'glutes', 'boundary': 'maximum', 'targetSets': 18, 'achievedSets': 18.0},
    ]
    assert result['scope'] == 'supplied_candidate_pool_continuous_volume_only_relaxation'
    assert 'menuRelief' not in result

    disclosure = render_optimization_disclosure({'developmentEmphasis': {
        'roleKeys': ['hamstrings'], 'status': 'optimal', 'minimumWeeklyWorkingSets': 12,
        'menuLimits': {'volumeCreditCoupling': result}}})
    assert 'At this witness, active approved weekly target boundaries are quads minimum 15, hamstrings minimum 15, glutes maximum 18.' in disclosure
    assert 'does not prove any single target causes the floor' in disclosure


def test_credit_coupling_exposes_outside_menu_profile_witness_for_reduced_floor():
    credit = lambda **values: {muscle: {'direct': amount, 'indirect': 0} for muscle, amount in values.items()}
    candidates = [
        {'id': 'selected_quad', 'name': 'Squat', 'creditsPerWorkingSet': credit(quads=1)},
        {'id': 'selected_ham', 'name': 'Nordic', 'creditsPerWorkingSet': credit(hamstrings=1)},
        {'id': 'outside_hinge', 'name': 'Hinge option', 'creditsPerWorkingSet': credit(hamstrings=0.5, glutes=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'quads': {'minimum': 4, 'maximum': 4},
        'hamstrings': {'minimum': 4, 'maximum': 4},
    }}}

    result = muscle_credit_coupling_evidence(candidates, requirements,
        selected_definition_ids=['selected_quad', 'selected_ham'])

    assert result['status'] == 'proven'
    selected_profile = next(item for item in result['profileLowerBounds']
        if item['members'][0]['id'] == 'selected_ham')
    assert selected_profile['minimumWeeklyWorkingSets'] == pytest.approx(4)
    relief = result['menuRelief']
    assert relief['status'] == 'proven'
    assert relief['scope'] == 'selected_menu_vs_retrieved_pool_continuous_weekly_volume_relaxation'
    improvement = next(item for item in relief['improvements']
        if item['selectedDefinitions'][0]['id'] == 'selected_ham')
    assert improvement['minimumWeeklyWorkingSetsSelectedPool'] == pytest.approx(4)
    assert improvement['minimumWeeklyWorkingSetsRetrievedPool'] == pytest.approx(0)
    witness = improvement['outsideMenuWitnessProfiles']
    assert witness
    assert any(choice['id'] == 'outside_hinge'
        for profile in witness for choice in profile['definitionChoices'])
    assert 'not an admitted or executable substitution' in relief['interpretation']


def test_credit_coupling_menu_relief_fails_closed_for_infeasible_selected_pool():
    credit = lambda **values: {muscle: {'direct': amount, 'indirect': 0} for muscle, amount in values.items()}
    candidates = [
        {'id': 'selected_quad', 'creditsPerWorkingSet': credit(quads=1)},
        {'id': 'outside_ham', 'creditsPerWorkingSet': credit(hamstrings=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'quads': {'minimum': 4, 'maximum': 4}, 'hamstrings': {'minimum': 4, 'maximum': 4}}}}

    result = muscle_credit_coupling_evidence(candidates, requirements,
        selected_definition_ids=['selected_quad'])

    assert result['status'] == 'infeasible_relaxation'
    assert result['profileLowerBounds'] == []
    assert result['menuRelief'] == {'status': 'unproven', 'improvements': []}


def test_credit_coupling_menu_relief_fails_closed_on_solver_timeout(monkeypatch):
    from types import SimpleNamespace
    import scipy.optimize

    monkeypatch.setattr(scipy.optimize, 'linprog', lambda *args, **kwargs:
        SimpleNamespace(status=1, success=False))
    candidates = [{'id': 'selected', 'creditsPerWorkingSet': {
        'chest': {'direct': 1, 'indirect': 0}}}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 5, 'maximum': 6}}}}

    result = muscle_credit_coupling_evidence(candidates, requirements,
        selected_definition_ids=['selected'])

    assert result['status'] == 'unproven'
    assert result['profileLowerBounds'] == []
    assert result['menuRelief'] == {'status': 'unproven', 'improvements': []}


def test_credit_coupling_menu_relief_keeps_selected_floor_when_union_solve_times_out(monkeypatch):
    from types import SimpleNamespace
    import scipy.optimize
    original = scipy.optimize.linprog
    calls = []

    def timeout_union(*args, **kwargs):
        calls.append(True)
        if len(calls) == 3:
            return SimpleNamespace(status=1, success=False)
        return original(*args, **kwargs)

    monkeypatch.setattr(scipy.optimize, 'linprog', timeout_union)
    credit = lambda **values: {muscle: {'direct': amount, 'indirect': 0} for muscle, amount in values.items()}
    candidates = [
        {'id': 'selected', 'creditsPerWorkingSet': credit(hamstrings=1)},
        {'id': 'outside', 'creditsPerWorkingSet': credit(hamstrings=0.5, glutes=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'hamstrings': {'minimum': 4, 'maximum': 4}}}}

    result = muscle_credit_coupling_evidence(candidates, requirements,
        selected_definition_ids=['selected'])

    assert result['status'] == 'proven'
    assert result['profileLowerBounds'][0]['minimumWeeklyWorkingSets'] == pytest.approx(4)
    assert result['menuRelief'] == {'status': 'unproven', 'improvements': []}


def test_credit_coupling_menu_relief_rejects_conflicting_duplicate_definition_identity():
    credit = lambda **values: {muscle: {'direct': amount, 'indirect': 0} for muscle, amount in values.items()}
    candidates = [
        {'id': 'same', 'creditsPerWorkingSet': credit(chest=1)},
        {'id': 'same', 'creditsPerWorkingSet': credit(back=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 1, 'maximum': 2}, 'back': {'minimum': 1, 'maximum': 2}}}}

    result = muscle_credit_coupling_evidence(candidates, requirements, selected_definition_ids=['same'])

    assert result['status'] == 'unproven'
    assert result['profileLowerBounds'] == []
    assert result['menuRelief'] == {'status': 'unproven', 'improvements': []}


def test_credit_coupling_does_not_claim_nordic_floor_with_triple_credit_option():
    credit = lambda **values: {muscle: {'direct': amount, 'indirect': 0} for muscle, amount in values.items()}
    candidates = [
        {'id': 'squat', 'creditsPerWorkingSet': credit(quads=1, glutes=1)},
        {'id': 'rdl', 'creditsPerWorkingSet': credit(hamstrings=1, glutes=1)},
        {'id': 'nordic', 'creditsPerWorkingSet': credit(hamstrings=1)},
        {'id': 'triple', 'creditsPerWorkingSet': credit(quads=1, hamstrings=1, glutes=1)},
    ]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        muscle: {'minimum': 15, 'maximum': 18} for muscle in ('quads', 'hamstrings', 'glutes')}}}
    result = muscle_credit_coupling_evidence(candidates, requirements)
    assert result['status'] == 'proven'
    assert all('nordic' not in [member['id'] for member in item['members']]
        for item in result['profileLowerBounds'])


def test_credit_coupling_marks_infeasible_pool_as_relaxation_only():
    candidates = [{'id': 'chest', 'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        'quads': {'minimum': 5, 'maximum': 6}}}}
    result = muscle_credit_coupling_evidence(candidates, requirements)
    assert result['status'] == 'infeasible_relaxation'
    assert result['profileLowerBounds'] == []
    assert 'supplied_candidate_pool' in result['scope']


@pytest.mark.parametrize('credit', ['unknown', True, float('nan')])
def test_credit_coupling_unknown_credit_does_not_produce_a_bound(credit):
    candidates = [{'id': 'example', 'creditsPerWorkingSet': {'chest': {'direct': credit}}}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 5, 'maximum': 6}}}}

    result = muscle_credit_coupling_evidence(candidates, requirements)

    assert result['status'] == 'unproven'
    assert result['profileLowerBounds'] == []
