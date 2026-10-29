from workout_generator_pkg import generation_audit as audit


def _exercise(occurrence_id, definition_id, name, *, primary=(), secondary=(), sets=2):
    prescriptions = []
    for index in range(sets):
        if index:
            prescriptions.append({'type': 'RestSet', 'timeInSeconds': 90})
        prescriptions.append({'type': 'WeightSet', 'reps': 8, 'subCategory': 'WorkSet'})
    return {'id': occurrence_id, 'type': 'Exercise', 'name': name, 'exerciseType': 'WEIGHT',
        'libraryDefinitionId': definition_id, 'muscleGroups': list(primary),
        'secondaryMuscleGroups': list(secondary), 'sets': prescriptions}


def test_credit_sensitivity_uses_canonical_definition_frequency_and_separate_roles():
    package = {'workouts': [
        {'name': 'A', 'timesCompletedInAWeek': 2,
         'workoutComponents': [_exercise('a1', 'definition-a', 'Same Name', primary=['FRONT_QUADRICEPS'])]},
        {'name': 'B', 'timesCompletedInAWeek': 1,
         'workoutComponents': [_exercise('b1', 'definition-b', 'Same Name', primary=['FRONT_QUADRICEPS'], sets=3)]},
    ]}
    targets = {'weeklyEffectiveSets': {'quads': {'minimum': 6, 'maximum': 8}},
        'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}

    report = audit.audit_workout_package(package, targets)
    sensitivity = report['muscleCreditReliance']
    quads = sensitivity['weeklyTargets'][0]

    assert report['weeklyVolume']['quads']['effective'] == 7
    assert quads['status'] == 'within_target'
    assert quads['identityComplete'] is True
    assert {item['exerciseDefinitionId'] for item in quads['singleDefinitionDependencies']} == {
        'definition-a', 'definition-b'}
    by_id = {item['exerciseDefinitionId']: item for item in quads['singleDefinitionDependencies']}
    assert by_id['definition-a']['weeklyWorkingSets'] == 4
    assert by_id['definition-a']['directCredit'] == 4
    assert by_id['definition-a']['weightedIndirectCredit'] == 0
    assert by_id['definition-a']['effectiveSetsWithoutDefinition'] == 3
    assert by_id['definition-a']['shortfallBelowMinimum'] == 3
    assert by_id['definition-b']['effectiveSetsWithoutDefinition'] == 4
    disclosure = audit.render_plan_disclosures(report)
    assert 'accounting inputs, not measurements of equivalent physiological stimulus' in disclosure
    assert 'Weekly Quadriceps target 6–8 has 7 effective sets' in disclosure


def test_credit_sensitivity_reports_session_minimum_and_unknown_equivalence():
    package = {'workouts': [{'name': 'A', 'timesCompletedInAWeek': 2,
        'workoutComponents': [_exercise('combo', 'definition-combo', 'Combo',
            primary=['FRONT_QUADRICEPS'], secondary=['BACK_HAMSTRING'])]}]}
    targets = {'weeklyEffectiveSets': {
        'quads': {'minimum': 4, 'maximum': 6}, 'hamstrings': {'minimum': 2, 'maximum': 4}},
        'perSessionEffectiveSets': {'quads': {'minimum': 1, 'maximum': None}},
        'maximumSessionSeconds': None}

    report = audit.audit_workout_package(package, targets)
    sensitivity = report['muscleCreditReliance']
    by_muscle = {item['muscle']: item for item in sensitivity['weeklyTargets']}

    assert by_muscle['quads']['auditedEffectiveSets'] == 4
    assert by_muscle['quads']['singleDefinitionDependencies'][0]['directCredit'] == 4
    assert by_muscle['quads']['singleDefinitionDependencies'][0]['weightedIndirectCredit'] == 0
    assert by_muscle['hamstrings']['auditedEffectiveSets'] == 2
    assert by_muscle['hamstrings']['singleDefinitionDependencies'][0]['directCredit'] == 0
    assert by_muscle['hamstrings']['singleDefinitionDependencies'][0]['weightedIndirectCredit'] == 2
    session = sensitivity['perSessionMinimums'][0]
    assert session['status'] == 'meets_minimum'
    assert session['singleDefinitionDependencies'][0]['shortfallBelowMinimum'] == 1
    assert sensitivity['physiologicalEquivalence'] == 'unknown'


def test_credit_sensitivity_does_not_infer_a_definition_from_its_name():
    package = {'workouts': [{'name': 'A', 'workoutComponents': [
        _exercise('unmapped', '', 'Same Name', primary=['FRONT_QUADRICEPS'])]}]}
    targets = {'weeklyEffectiveSets': {'quads': {'minimum': 1, 'maximum': 2}},
        'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}

    report = audit.audit_workout_package(package, targets)
    quads = report['muscleCreditReliance']['weeklyTargets'][0]

    assert quads['identityComplete'] is False
    assert quads['singleDefinitionDependencies'] == []
    assert report['muscleCreditReliance']['unmappedCreditOccurrences'][0]['exerciseName'] == 'Same Name'


def test_session_sensitivity_keeps_duplicate_session_names_distinct():
    package = {'workouts': [
        {'name': 'Repeated', 'workoutComponents': [
            _exercise('first', 'same-definition', 'Same Exercise', primary=['FRONT_QUADRICEPS'])]},
        {'name': 'Repeated', 'workoutComponents': [
            _exercise('second', 'same-definition', 'Same Exercise', primary=['FRONT_QUADRICEPS'])]},
    ]}
    targets = {'weeklyEffectiveSets': {},
        'perSessionEffectiveSets': {'quads': {'minimum': 1, 'maximum': None}},
        'maximumSessionSeconds': None}

    report = audit.audit_workout_package(package, targets)
    sessions = report['muscleCreditReliance']['perSessionMinimums']

    assert [item['sessionIndex'] for item in sessions] == [0, 1]
    assert [item['singleDefinitionDependencies'][0]['effectiveCredit'] for item in sessions] == [2, 2]
    assert [item['singleDefinitionDependencies'][0]['shortfallBelowMinimum'] for item in sessions] == [1, 1]
