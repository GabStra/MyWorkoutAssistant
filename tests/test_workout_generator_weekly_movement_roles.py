from jsonschema import validate

from workout_generator_pkg import planning_tools, recipe_contracts
from workout_generator_pkg.muscle_roles import MOVEMENT_COVERAGE_ROLES


def test_weekly_movement_roles_survive_public_intake_without_invented_dose_or_qualification():
    roles = {
        'sagittal_plane', 'frontal_plane', 'transverse_plane',
        'unilateral', 'lateral_movement', 'rotational_core',
    }
    equipment = {'equipments': [], 'accessoryEquipments': [], 'exerciseDefinitions': []}
    arguments = {'sessionsPerWeek': 3, 'requiredCoverage': [
        {'key': role, 'scope': 'weekly', 'intent': 'inclusion'} for role in sorted(roles)]}
    schema = planning_tools.workout_requirements_tool(equipment)['function']['parameters']
    validate(arguments, schema)

    result = planning_tools.set_workout_requirements(arguments, [{
        'role': 'user', 'content': 'Three full-body sessions with weekly plane coverage, '
        'unilateral work, lower-body lateral movement and rotational or anti-rotational core.'}], equipment)

    assert result['requirements']['requiredCoverage'] == [
        {**rule, 'description': MOVEMENT_COVERAGE_ROLES[rule['key']]}
        for rule in arguments['requiredCoverage']]
    assert result['requirements']['auditTargets'] == {
        'weeklyEffectiveSets': {}, 'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}
    assert not roles & recipe_contracts.CODE_OWNED_COVERAGE_ROLES
    definition = {'name': 'Unilateral lateral rotational movement', 'muscleGroups': []}
    assert recipe_contracts.canonical_qualified_roles(definition, roles, roles) == sorted(roles)
    assert recipe_contracts.canonical_qualified_roles(definition, [], roles) == []
