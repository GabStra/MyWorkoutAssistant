import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg.generation_audit import available_muscle_targets, muscle_credits_per_set, muscle_metadata_policy
from workout_generator_pkg.planning_tools import workout_requirements_tool, set_workout_requirements, audit_workout_plan, PlanningInputError
from workout_generator_pkg.plan_contract import hydrate_plan_index_from_exercise_library
from test_workout_generator_planning_tools import planning_case, requirement_messages


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
    assert 'without explicit agreement' in policy['interpretation']


def test_alternative_annotations_cannot_enable_unrepresented_targets():
    gear, arguments, _, _ = planning_case()
    gear['exerciseDefinitions'][0]['trainingMuscles'] = {'primary': ['lats'], 'secondary': ['upperBack']}
    arguments['auditTargets']['weeklyEffectiveSets'] = {'lats': {'minimum': 5, 'maximum': 6}}
    arguments['auditTargets']['perSessionEffectiveSets'] = {}
    with pytest.raises((PlanningInputError, ValidationError)):
        set_workout_requirements(arguments, [], gear)
    schema = workout_requirements_tool(gear)['function']['parameters']['properties']['auditTargets']
    assert 'lats' not in schema['properties']['weeklyEffectiveSets']['properties']


def test_final_audit_uses_same_fields_while_preserving_legacy_export_data():
    from workout_generator_pkg.domain_ops import apply_exercise_library_schema_v2
    gear, _, stored, draft = planning_case()
    definition = gear['exerciseDefinitions'][0]
    definition['trainingMuscles'] = {'primary': ['lateralDelts'], 'secondary': []}
    result = audit_workout_plan(draft, gear, requirement_messages(stored))
    assert result['passed']
    assert result['audit']['weeklyVolume']['chest']['effective'] == 5
    assert 'lateralDelts' not in result['audit']['weeklyVolume']
    assert not any(e['code'] == 'missing_training_muscle_roles' for e in result['errors'])
    plan = result['planIndex']
    hydrate_plan_index_from_exercise_library(plan, gear['exerciseDefinitions'])
    package = {'workouts': [{'workoutComponents': [dict(plan['exercises'][0], type='Exercise', sets=[])]}]}
    apply_exercise_library_schema_v2(package, gear['exerciseDefinitions'])
    assert package['exerciseDefinitions'][0]['trainingMuscles'] == definition['trainingMuscles']


def test_library_loader_does_not_validate_unused_annotations(tmp_path):
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload
    gear, _, _, _ = planning_case()
    gear['exerciseDefinitions'][0]['trainingMuscles'] = 'obsolete annotation'
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(gear), encoding='utf-8')
    loaded = _load_exercise_library_payload(str(path))
    assert muscle_credits_per_set(loaded['exerciseDefinitions'][0]) == {
        'chest': {'direct': 1, 'indirect': 0}, 'triceps': {'direct': 0, 'indirect': 0.5}}
