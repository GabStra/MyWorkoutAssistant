import json

import pytest

from workout_generator_pkg import planning_tools, recipe_contracts
from workout_generator_pkg.interactive_shell import _load_exercise_library_payload
from test_workout_generator_planning_tools import planning_case, requirement_messages


def test_explicit_role_minimum_survives_intake_and_blocks_a_smaller_audited_dose():
    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{
        'key': 'upper_push', 'scope': 'weekly', 'intent': 'development',
        'minimumWeeklySets': 6, 'minimumSessions': 1}]
    stored = planning_tools.set_workout_requirements(requirements, [{
        'role': 'user', 'content': 'At least six upper-push working sets in one weekly session.'}], equipment)
    assert stored['requirements']['requiredCoverage'][0]['minimumWeeklySets'] == 6
    assert 'at least 6 qualified working sets weekly' in stored['requirementsPreview']
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['upper_push']
    result = planning_tools.audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert not result['passed']
    assert 'required_coverage_weekly_sets_below_minimum' in {
        error['code'] for error in result['audit']['errors']}


def test_role_frequency_cannot_silently_exceed_the_approved_schedule():
    equipment, requirements, _, _ = planning_case()
    requirements['requiredCoverage'] = [{
        'key': 'upper_push', 'scope': 'weekly', 'minimumSessions': 2}]
    with pytest.raises(planning_tools.PlanningInputError) as caught:
        planning_tools.set_workout_requirements(requirements, [], equipment)
    assert caught.value.code == 'coverage_frequency_exceeds_schedule'


def test_calf_and_abdominal_development_coverage_requires_direct_library_targets():
    roles = {'abs', 'calves', 'core'}
    for role, tag in (('abs', 'FRONT_ABS'), ('calves', 'BACK_CALVES')):
        direct = {'muscleGroups': [tag]}
        secondary = {'muscleGroups': ['BACK_UPPER_BACK'], 'secondaryMuscleGroups': [tag]}
        assert recipe_contracts.canonical_qualified_roles(direct, [], roles) == [role]
        assert recipe_contracts.canonical_qualified_roles(secondary, ['abs', 'calves'], roles) == []
    abdominal = {'muscleGroups': ['FRONT_ABS']}
    assert recipe_contracts.canonical_qualified_roles(abdominal, ['abs', 'core'], roles) == ['abs', 'core']


def test_library_loader_overlays_reviewed_evidence_without_rewriting_the_source(tmp_path, monkeypatch):
    definition_id = '00000000-0000-0000-0000-000000000001'
    source = {'exerciseDefinitions': [{'id': definition_id, 'name': 'Movement'}]}
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(source), encoding='utf-8')
    evidence = {'programmingDemands': {
        'unsupported_trunk': {'present': False, 'source': 'https://example.org/execution'}}}
    monkeypatch.setattr(recipe_contracts, '_reviewed_exercise_annotations_by_definition',
                        lambda: {definition_id: evidence})
    loaded = _load_exercise_library_payload(str(path))
    assert loaded['exerciseDefinitions'][0]['programmingDemands'] == evidence['programmingDemands']
    assert json.loads(path.read_text(encoding='utf-8')) == source
