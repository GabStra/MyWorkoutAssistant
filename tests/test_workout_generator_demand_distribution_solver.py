import copy

from workout_generator_pkg import joint_planning
from workout_generator_pkg.generation_audit import render_program_guidance
from test_workout_generator_planning_tools import planning_case


def _fully_tagged_definition(definition, *, unsupported_trunk):
    definition['programmingDemands'] = {
        'unsupported_trunk': {'present': unsupported_trunk, 'source': 'Reviewed exercise execution entry.'},
        'axial_loading': {'present': False, 'source': 'Reviewed exercise execution entry.'},
        'eccentric_emphasis': {'present': False, 'source': 'Reviewed exercise execution entry.'},
    }


def _sessions_from_draft(draft, counts):
    sessions = []
    for index, count in enumerate(counts):
        day = copy.deepcopy(draft['workouts'][0])
        day.update(name=f'Day {index + 1}', trainingDays=[index * 2])
        day['exercises'][0]['numWorkSets'] = count
        day['exercises'][0].pop('placementNotes', None)
        sessions.append(day)
    return sessions


def test_approved_demand_distribution_spreads_known_group_before_muscle_distribution():
    equipment, requirements, _, draft = planning_case()
    _fully_tagged_definition(equipment['exerciseDefinitions'][0], unsupported_trunk=True)
    requirements.update(sessionsPerWeek=2,
        objectiveOrder=['demand_distribution', 'distribution', 'preservation'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 10}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 6}
    sessions = _sessions_from_draft(draft, [8, 2])
    before = copy.deepcopy(sessions)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [5, 5]
    assert [stage['goal'] for stage in result['objectiveProgress'][:2]] == [
        'demand_distribution', 'distribution']
    demand = result['demandDistribution']
    assert demand['status'] == 'optimal'
    group, = [item for item in demand['groups'] if item['key'] == 'unsupported_trunk']
    assert [item['sessionExposureSets'] for item in group['sessionExposureSets']] == [5, 5]
    assert group['weeklyExposureSets'] == 10 and group['peakSessionExposureSets'] == 5
    assert 'not a fatigue score' in demand['proofScope']
    assert sessions == before
    assert all(4 <= day['volume']['chest']['effective'] <= 6 for day in result['audit']['workouts'])
    assert result['audit']['weeklyVolume']['chest']['effective'] == 10


def test_unknown_demand_tags_disable_group_optimization_and_are_not_zeroed():
    equipment, requirements, _, draft = planning_case()
    known = equipment['exerciseDefinitions'][0]
    _fully_tagged_definition(known, unsupported_trunk=True)
    unknown = copy.deepcopy(known)
    unknown.update(id='second-exercise', name='Second press')
    unknown.pop('programmingDemands')
    equipment['exerciseDefinitions'].append(unknown)
    references = {definition['id']: f'LIBRARY_{index}' for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda value: value['id']))}
    requirements.update(sessionsPerWeek=2, objectiveOrder=['demand_distribution', 'preservation'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 10}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 6}
    sessions = _sessions_from_draft(draft, [5, 5])
    sessions[0]['exercises'][0]['definition_id'] = references[known['id']]
    sessions[1]['exercises'][0]['definition_id'] = references[unknown['id']]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert not any(stage['goal'] == 'demand_distribution' for stage in result['objectiveProgress'])
    demand = result['demandDistribution']
    assert demand['status'] == 'unavailable'
    assert demand['optimizationStatus'] == 'unavailable_evidence'
    assert demand['unavailableGroups']['unsupported_trunk'] == ['second-exercise']
    assert result['priorityExecution']['approvedPriorities'][0]['status'] == 'unavailable_evidence'


def test_partial_demand_evidence_discloses_known_group_scope_without_changing_solver_status():
    equipment, requirements, _, draft = planning_case()
    for definition in equipment['exerciseDefinitions']:
        definition['programmingDemands'] = {
            'unsupported_trunk': {'present': True, 'source': 'Reviewed execution setup.'}}
    requirements.update(sessionsPerWeek=2,
        objectiveOrder=['demand_distribution', 'distribution', 'preservation'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 10}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 6}

    result = joint_planning.solve_prescribed_week(
        _sessions_from_draft(draft, [8, 2]), requirements, equipment)

    assert result['feasible'], result
    demand = result['demandDistribution']
    assert demand['evidenceStatus'] == 'partial'
    assert demand['unavailableGroups'] == {
        'axial_loading': sorted(definition['id'] for definition in equipment['exerciseDefinitions']),
        'eccentric_emphasis': sorted(definition['id'] for definition in equipment['exerciseDefinitions']),
    }
    demand_stage = next(stage for stage in result['objectiveProgress']
        if stage['goal'] == 'demand_distribution')
    assert demand_stage['status'] in ('optimal', 'optimal_zero_lower_bound')
    assert demand['optimizationStatus'] == demand_stage['status']

    guidance = render_program_guidance(
        {'weeklyVolume': {}, 'weeklyWorkingSets': 0}, muscles=[],
        priority_execution=result['priorityExecution'])
    assert 'optimization includes only fully classified groups' in guidance
    assert 'axial_loading, eccentric_emphasis remain unclassified' in guidance
    assert 'conditional on the known evidence' in guidance

def test_unusable_unknown_recipe_does_not_disable_demand_evidence_for_executable_menu(monkeypatch):
    equipment, requirements, _, draft = planning_case()
    known = equipment['exerciseDefinitions'][0]
    _fully_tagged_definition(known, unsupported_trunk=True)
    unusable = copy.deepcopy(known)
    unusable.update(id='unusable-unknown', name='Unusable unknown')
    unusable.pop('programmingDemands')
    equipment['exerciseDefinitions'].append(unusable)
    references = {definition['id']: f'LIBRARY_{index}' for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda value: value['id']))}
    known_reference, unusable_reference = references[known['id']], references[unusable['id']]
    requirements.update(sessionsPerWeek=2, objectiveOrder=['demand_distribution', 'preservation'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 10}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 6}
    sessions = _sessions_from_draft(draft, [5, 5])
    for day in sessions:
        unusable_item = copy.deepcopy(day['exercises'][0])
        unusable_item['definition_id'] = unusable_reference
        day['exercises'][0]['definition_id'] = known_reference
        day['exercises'].append(unusable_item)
    original_rest_options = joint_planning._rest_options

    def executable_only(block, *args):
        if block[0]['definition_id'] == unusable_reference:
            return iter(())
        return original_rest_options(block, *args)

    monkeypatch.setattr(joint_planning, '_rest_options', executable_only)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert any(stage['goal'] == 'demand_distribution' for stage in result['objectiveProgress'])
    demand = result['demandDistribution']
    assert demand['evidenceStatus'] == 'available'
    assert demand['unavailableGroups'] == {}
    assert demand['fixedUnavailableGroups'] == {}
    assert all(item['definition_id'] != unusable_reference
        for day in result['sessions'] for item in day['exercises'])


def test_known_absent_properties_are_distinct_from_missing_evidence():
    equipment, requirements, _, draft = planning_case()
    _fully_tagged_definition(equipment['exerciseDefinitions'][0], unsupported_trunk=False)
    requirements['objectiveOrder'] = ['demand_distribution', 'preservation']

    result = joint_planning.solve_prescribed_week(_sessions_from_draft(draft, [5]), requirements, equipment)

    assert result['feasible'], result
    assert result['demandDistribution']['evidenceStatus'] == 'available'
    assert result['demandDistribution']['optimizationStatus'] == 'no_positive_exposure'
    assert result['demandDistribution']['unavailableGroups'] == {}
    assert all(group['weeklyExposureSets'] == 0 for group in result['demandDistribution']['groups'])
    assert result['priorityExecution']['approvedPriorities'][0]['status'] == 'no_positive_exposure'


def test_demand_peak_includes_fixed_existing_session_exposure():
    equipment, requirements, _, draft = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    _fully_tagged_definition(definition, unsupported_trunk=True)
    row_definition = copy.deepcopy(definition)
    row_definition.update(id='row', name='Row', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    row_definition.pop('programmingDemands')
    equipment['exerciseDefinitions'].append(row_definition)
    requirements.update(sessionsPerWeek=3, objectiveOrder=['demand_distribution', 'preservation'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 8, 'maximum': 8}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 2, 'maximum': 4}
    sessions = _sessions_from_draft(draft, [2, 2])
    fixed = copy.deepcopy(draft['workouts'][0])
    fixed['name'] = 'Fixed day'
    fixed['exercises'][0].update(definition_id='LIBRARY_0', numWorkSets=4)
    fixed['exercises'][0].pop('placementNotes', None)
    fixed_unknown = copy.deepcopy(fixed['exercises'][0])
    fixed_unknown.update(definition_id='LIBRARY_1', name='Row', numWorkSets=2)
    fixed['exercises'].append(fixed_unknown)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        existing={'name': 'Fixed program', 'workouts': [fixed]})

    assert result['feasible'], result
    demand = result['demandDistribution']
    group, = [item for item in demand['groups'] if item['key'] == 'unsupported_trunk']
    assert [item['sessionExposureSets'] for item in group['sessionExposureSets']] == [4, 2, 2]
    assert group['peakSessionExposureSets'] == 4
    assert group['weeklyExposureSets'] == 8
    assert demand['evidenceStatus'] == 'available'
    assert demand['status'] == 'partial_fixed_evidence'
    assert demand['optimizationStatus'] == 'optimal_for_known_fixed_exposure_with_fixed_unknowns'
    assert demand['fixedUnavailableGroups']['unsupported_trunk'] == ['row']
    assert 'not a complete-week optimum' in demand['proofScope']
    assert result['objectiveProgress'][0]['value'] == 4


def test_demand_priority_selects_cross_recipe_mix_while_preserving_roles_and_volume():
    equipment, requirements, _, draft = planning_case()
    press = equipment['exerciseDefinitions'][0]
    definitions = []
    for identifier, role, present in (
            ('press_a_present', 'role_a', True), ('press_a_absent', 'role_a', False),
            ('press_b_present', 'role_b', True), ('press_b_absent', 'role_b', False)):
        definition = copy.deepcopy(press)
        definition.update(id=identifier, name=identifier)
        _fully_tagged_definition(definition, unsupported_trunk=present)
        definitions.append(definition)
    equipment['exerciseDefinitions'] = definitions
    references = {definition['id']: f'LIBRARY_{index}' for index, definition in enumerate(
        sorted(definitions, key=lambda value: value['id']))}
    requirements.update(sessionsPerWeek=2,
        objectiveOrder=['demand_distribution', 'distribution', 'preservation'],
        requiredCoverage=[
            {'key': 'role_a', 'description': 'Role A', 'scope': 'weekly'},
            {'key': 'role_b', 'description': 'Role B', 'scope': 'weekly'},
        ],
        executionRules=[
            {'kind': 'workSets', 'coverageKey': 'role_a', 'minimumSets': 2, 'maximumSets': 2},
            {'kind': 'workSets', 'coverageKey': 'role_b', 'minimumSets': 2, 'maximumSets': 2},
        ])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 8, 'maximum': 8}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    sessions = []
    for index in range(2):
        day = copy.deepcopy(draft['workouts'][0])
        day.update(name=f'Day {index + 1}', trainingDays=[index * 2])
        candidates = []
        for identifier, role, _ in (
                ('press_a_present', 'role_a', True), ('press_a_absent', 'role_a', False),
                ('press_b_present', 'role_b', True), ('press_b_absent', 'role_b', False)):
            item = copy.deepcopy(day['exercises'][0])
            item.update(definition_id=references[identifier], numWorkSets=2,
                satisfiesCoverage=[role] if identifier.endswith('_present') else [])
            item.pop('placementNotes', None)
            candidates.append(item)
        day['exercises'] = candidates
        sessions.append(day)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert [day['volume']['chest']['effective'] for day in result['audit']['workouts']] == [4, 4]
    assert result['audit']['weeklyVolume']['chest']['effective'] == 8
    assert set(result['audit']['weeklyCoverageSets']) == {'role_a', 'role_b'}
    group, = [item for item in result['demandDistribution']['groups']
        if item['key'] == 'unsupported_trunk']
    assert [item['sessionExposureSets'] for item in group['sessionExposureSets']] == [2, 2]
    assert group['peakSessionExposureSets'] == 2
    for day in result['sessions']:
        assert len(day['exercises']) == 2
        assert sum(bool(item['satisfiesCoverage']) for item in day['exercises']) == 1
        assert sum(item['numWorkSets'] for item in day['exercises']) == 4
        assert sum(item['numWorkSets'] for item in day['exercises']
                   if item['definition_id'] in {references['press_a_present'], references['press_b_present']}) == 2
