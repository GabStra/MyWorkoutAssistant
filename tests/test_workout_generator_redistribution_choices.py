import copy
import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg import api_client, review_assessment
from workout_generator_pkg.json_patching import apply_json_patch
from workout_generator_pkg.planning_tools import compile_coordinated_repair
from workout_generator_pkg.repair_contract import (
    build_repair_contract,
    redistribution_objective_choices,
    repair_contract_errors,
    target_content,
)


def _saved_shape_case():
    from test_workout_generator_planning_tools import planning_case

    _, _, stored, draft = planning_case()
    source = draft['workouts'][0]
    exercises = source['exercises']
    recipes = []
    for minimum, maximum in ((6, 8), (8, 10), (10, 12), (12, 14)):
        item = copy.deepcopy(exercises[0])
        item.pop('placementNotes', None)
        item.update(minReps=minimum, maxReps=maximum,
            allocationBounds={'minimum': 2, 'maximum': 20})
        recipes.append(item)

    workouts = []
    for name in ('Day A', 'Day B', 'Day C'):
        workouts.append({**copy.deepcopy(source), 'name': name, 'exercises': []})
    for workout_index, recipe_index, sets in (
            (0, 0, 7), (1, 0, 7), (0, 1, 7), (1, 1, 7), (0, 2, 2), (2, 3, 2)):
        item = copy.deepcopy(recipes[recipe_index])
        item['numWorkSets'] = sets
        workouts[workout_index]['exercises'].append(item)
    draft['workouts'] = workouts

    requirements = {'sessionsPerWeek': 3, 'executionRules': [{
        'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 20,
    }]}
    definitions = {'LIBRARY_0': {'exerciseCategory': 'MODERATE_COMPOUND'}}
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
        'currentDraft': draft, 'requirements': requirements, 'recipeDefinitions': definitions}
    choices = redistribution_objective_choices(draft, requirements, definitions)
    return draft, task, requirements, definitions, choices


def test_saved_mixed_recipe_objective_is_enumerated_as_only_feasible_recipe_spreads():
    draft, _, _, _, choices = _saved_shape_case()

    assert sum(item['numWorkSets'] for day in draft['workouts'] for item in day['exercises']) == 32
    assert len([item for day in draft['workouts'] for item in day['exercises']]) == 6
    assert sorted(sum(item['numWorkSets'] for day in draft['workouts'] for item in day['exercises']
                      if (item['minReps'], item['maxReps']) == reps)
                  for reps in ((6, 8), (8, 10), (10, 12), (12, 14))) == [2, 2, 14, 14]

    assert {(tuple(choice['exerciseRefs']), choice['minimumSessions']) for choice in choices} == {
        (('EXERCISE_0', 'EXERCISE_3'), 2), (('EXERCISE_0', 'EXERCISE_3'), 3),
        (('EXERCISE_1', 'EXERCISE_4'), 2), (('EXERCISE_1', 'EXERCISE_4'), 3),
    }


def test_wire_choices_omit_satisfied_session_spreads_but_keep_canonical_carried_objective():
    draft, _, requirements, definitions, choices = _saved_shape_case()
    recipe_refs = ['EXERCISE_0', 'EXERCISE_3']
    already_satisfied = next(choice for choice in choices
        if choice['exerciseRefs'] == recipe_refs and choice['minimumSessions'] == 2)
    improving = review_assessment.improving_repair_objective_choices(choices, draft)
    assert not any(choice['exerciseRefs'] == recipe_refs and choice['minimumSessions'] == 2
        for choice in improving)
    assert any(choice['exerciseRefs'] == recipe_refs and choice['minimumSessions'] == 3
        for choice in improving)

    exercise_refs, workouts = [], []
    for workout in draft['workouts']:
        workout_ids = []
        for item in workout['exercises']:
            reference = f'EXERCISE_{len(exercise_refs)}'
            exercise_refs.append({'id': reference, 'libraryDefinitionId': item['definition_id']})
            workout_ids.append(reference)
        workouts.append({'exerciseIds': workout_ids, 'supersetGroups': []})
    context = {'draft': {'exercises': exercise_refs, 'libraryDefinitions': definitions,
        'workouts': workouts}, 'requirements': requirements, 'redistributionObjectiveChoices': choices}
    finding = {'severity': 'blocking', 'action': 'repair', 'message': 'Spread this recipe further.',
        'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0']}
    review = {'inputHash': 'current-draft', 'findings': [finding]}
    review['assessment'] = {'version': review_assessment.VERSION,
        'inputHash': review_assessment.assessment_hash(review), 'groups': [{
            'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['prescription'],
            'repairObjectives': [already_satisfied], 'reason': 'Preserve the current recipe distribution.',
            'evidencePaths': [], 'errorKind': 'none'}],
        'repairPlan': 'Preserve and verify the assessed redistribution.'}
    assert review_assessment.validate_assessment(review, context)['groups'][0]['repairObjectives'] == [already_satisfied]


def test_assessment_schema_accepts_only_enumerated_recipe_and_spread(monkeypatch):
    draft, _, requirements, definitions, choices = _saved_shape_case()
    context = {'draft': {'exercises': [
        {'id': f'EXERCISE_{index}', 'libraryDefinitionId': 'LIBRARY_0'} for index in range(6)],
        'libraryDefinitions': {'LIBRARY_0': {}}, 'workouts': draft['workouts']}, 'requirements': requirements,
        'recipeDefinitions': definitions, 'redistributionObjectiveChoices': choices}
    review = {'inputHash': 'saved-candidate', 'findings': [{
        'severity': 'blocking', 'action': 'repair', 'message': 'Distribute the existing work.',
        'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0']}]}
    selected = next(choice for choice in choices if choice['minimumSessions'] == 3
        and choice['exerciseRefs'] == ['EXERCISE_0', 'EXERCISE_3'])
    captured = {}

    def respond(_client, _request, **options):
        captured['schema'] = options['output_schema']
        captured['request'] = _request
        return json.dumps({'findingAssessments': {'FINDING_0': {
            'disposition': 'repair', 'repairDimensions': ['prescription'],
            'repairObjectives': [selected], 'reason': 'Spread this exact recipe.'}},
            'repairPlan': 'Distribute the selected existing recipe.'}), None, None

    monkeypatch.setattr(review_assessment, '_review_call', respond)
    result = review_assessment.assess_findings(None, context, review, single_attempt=True)

    assert result['groups'][0]['repairObjectives'] == [selected]
    finding_schema = captured['schema']['properties']['findingAssessments']['properties']['FINDING_0']
    repair_variant = next(variant for variant in finding_schema['anyOf']
        if variant['properties']['disposition']['enum'] == ['repair'])
    for variant in finding_schema['anyOf']:
        if variant['properties']['disposition']['enum'] != ['repair']:
            assert variant['properties']['repairObjectives']['type'] == 'array'
    objective_items = repair_variant['properties']['repairObjectives']['items']['anyOf']
    assert len(objective_items) == 2
    bounded_refs = {reference for option in objective_items
        for reference in option['properties']['exerciseRefs']['items']['enum']}
    assert bounded_refs == {'EXERCISE_0', 'EXERCISE_3'}
    assert 'EXERCISE_1' not in bounded_refs
    assert {option['properties']['minimumSessions']['enum'][0] for option in objective_items} == {2, 3}
    findings_payload = json.loads(captured['request'][-1]['content'])['findings']['FINDING_0']
    assert findings_payload['supportedRedistributionObjectives'] == [
        choice for choice in choices if choice['exerciseRefs'] == ['EXERCISE_0', 'EXERCISE_3']]


@pytest.mark.parametrize('objective', [
    {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2',
        'EXERCISE_3', 'EXERCISE_4', 'EXERCISE_5'], 'minimumSessions': 3},
    {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_2'], 'minimumSessions': 3},
    {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_999'], 'minimumSessions': 2},
])
def test_assessment_rejects_mixed_small_or_unknown_recipe_selection(objective):
    draft, _, requirements, definitions, choices = _saved_shape_case()
    context = {'draft': {'exercises': [
        {'id': f'EXERCISE_{index}'} for index in range(6)], 'workouts': draft['workouts']},
        'requirements': requirements, 'recipeDefinitions': definitions,
        'redistributionObjectiveChoices': choices}
    with pytest.raises(ValueError, match='code-enumerated redistribution objective'):
        review_assessment.validate_group_resolution({'disposition': 'repair',
            'repairDimensions': ['prescription'], 'repairObjectives': [objective]}, context)


def test_assessment_binds_objectives_to_recipe_identity_in_finding_evidence():
    draft, _, requirements, _, _ = _saved_shape_case()
    for workout_index, exercise_index, definition in (
            (0, 0, 'LIBRARY_A'), (1, 0, 'LIBRARY_A'), (0, 1, 'LIBRARY_B'), (1, 1, 'LIBRARY_B'),
            (0, 2, 'LIBRARY_C'), (2, 0, 'LIBRARY_D')):
        draft['workouts'][workout_index]['exercises'][exercise_index]['definition_id'] = definition
    next_exercise = 0
    for workout in draft['workouts']:
        workout['exerciseIds'] = [f'EXERCISE_{index}' for index in range(
            next_exercise, next_exercise + len(workout['exercises']))]
        next_exercise += len(workout['exercises'])
    definitions = {key: {'exerciseCategory': 'MODERATE_COMPOUND'}
        for key in ('LIBRARY_A', 'LIBRARY_B', 'LIBRARY_C', 'LIBRARY_D')}
    choices = redistribution_objective_choices(draft, requirements, definitions)
    context = {'draft': {'exercises': [
        {'id': f'EXERCISE_{index}', 'libraryDefinitionId': definition}
        for index, definition in enumerate(('LIBRARY_A', 'LIBRARY_B', 'LIBRARY_C',
            'LIBRARY_A', 'LIBRARY_B', 'LIBRARY_D'))],
        'libraryDefinitions': definitions, 'workouts': draft['workouts']},
        'requirements': requirements, 'recipeDefinitions': definitions,
        'redistributionObjectiveChoices': choices}
    clean = {'severity': 'blocking', 'action': 'repair', 'message': 'Redistribute this cited exercise.',
        'path': '/draft/libraryDefinitions/LIBRARY_A', 'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_A']}
    allowed = review_assessment.finding_redistribution_objective_choices(clean, context)
    assert allowed and all(set(choice['exerciseRefs']) <= {'EXERCISE_0', 'EXERCISE_3'} for choice in allowed)
    assert not any(set(choice['exerciseRefs']) & {'EXERCISE_1', 'EXERCISE_4'} for choice in allowed)

    wrong = next(choice for choice in choices if choice['exerciseRefs'] == ['EXERCISE_1', 'EXERCISE_4']
        and choice['minimumSessions'] == 2)
    session_evidence = {**clean, 'path': '/draft/workouts/0', 'evidencePaths': ['/draft/workouts/0']}
    session_choices = review_assessment.finding_redistribution_objective_choices(session_evidence, context)
    assert wrong in session_choices

    unrelated = {**clean, 'path': '/draft/workouts/2', 'evidencePaths': ['/draft/workouts/2']}
    unrelated_session_choices = review_assessment.finding_redistribution_objective_choices(unrelated, context)
    assert unrelated_session_choices == []
    assert wrong not in unrelated_session_choices

    review = {'inputHash': 'candidate', 'findings': [clean]}
    review['assessment'] = {'version': review_assessment.VERSION,
        'inputHash': review_assessment.assessment_hash(review), 'groups': [{
            'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['prescription'],
            'repairObjectives': [wrong], 'reason': 'Choose an unrelated source family.',
            'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_A'], 'errorKind': 'none'}],
        'repairPlan': 'Redistribute work.'}
    with pytest.raises(ValueError, match='identified by this finding group'):
        review_assessment.validate_assessment(review, context)


def test_improving_objectives_checks_reference_coverage_separately_from_session_count():
    choices = [
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2'], 'minimumSessions': 2},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_2', 'EXERCISE_3'], 'minimumSessions': 3},
    ]
    draft = {'workouts': [
        {'exerciseIds': ['EXERCISE_0', 'EXERCISE_1']},
        {'exerciseIds': ['EXERCISE_2', 'EXERCISE_3']},
    ]}

    # Three recipe occurrences occupy two sessions, so a two-session spread is
    # already satisfied even though occurrence count and session count differ.
    # A distinct-session count is not a reference-coverage count.
    assert review_assessment.improving_repair_objective_choices(choices[:1], draft) == []
    assert review_assessment.improving_repair_objective_choices(choices[1:], draft) == choices[1:]

    # Unknown occurrence identity stays available rather than being assumed satisfied.
    unknown = {'workouts': [{'exerciseIds': ['EXERCISE_0']}]}
    assert review_assessment.improving_repair_objective_choices(choices[:1], unknown) == choices[:1]


def test_cached_assessment_reuse_rebuilds_current_source_association_context():
    draft, _, requirements, _, _ = _saved_shape_case()
    for workout_index, exercise_index, definition in (
            (0, 0, 'LIBRARY_A'), (1, 0, 'LIBRARY_A'), (0, 1, 'LIBRARY_B'), (1, 1, 'LIBRARY_B'),
            (0, 2, 'LIBRARY_C'), (2, 0, 'LIBRARY_D')):
        draft['workouts'][workout_index]['exercises'][exercise_index]['definition_id'] = definition
    definitions = {key: {'exerciseCategory': 'MODERATE_COMPOUND'}
        for key in ('LIBRARY_A', 'LIBRARY_B', 'LIBRARY_C', 'LIBRARY_D')}
    context = review_assessment.assessment_validation_context(draft, requirements, definitions)
    choices = context['redistributionObjectiveChoices']
    clean = {'severity': 'blocking', 'action': 'repair', 'message': 'Redistribute the cited movement.',
        'path': '/draft/libraryDefinitions/LIBRARY_A', 'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_A']}
    unrelated = {'severity': 'blocking', 'action': 'repair', 'message': 'Correct the cited movement.',
        'path': '/draft/libraryDefinitions/LIBRARY_C', 'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_C']}
    clean_objective = next(choice for choice in choices
        if set(choice['exerciseRefs']) == {'EXERCISE_0', 'EXERCISE_3'} and choice['minimumSessions'] == 2)
    unrelated_objective = next(choice for choice in choices
        if set(choice['exerciseRefs']) == {'EXERCISE_1', 'EXERCISE_4'} and choice['minimumSessions'] == 2)
    review = {'inputHash': 'saved-candidate', 'findings': [clean, unrelated]}
    review['assessment'] = {'version': review_assessment.VERSION,
        'inputHash': review_assessment.assessment_hash(review), 'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['prescription'],
             'repairObjectives': [clean_objective], 'reason': 'Preserve the cited distribution.',
             'evidencePaths': [clean['path']], 'errorKind': 'none'},
            {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['prescription'],
             'repairObjectives': [unrelated_objective], 'reason': 'Preserve an unrelated distribution.',
             'evidencePaths': [unrelated['path']], 'errorKind': 'none'}],
        'repairPlan': 'Address the findings.'}

    review_assessment.validate_assessment(review)  # A legacy cache admitted this without source context.
    with pytest.raises(ValueError, match='identified by this finding group'):
        review_assessment.validate_redistribution_objective_associations(review, context)
    refreshed = copy.deepcopy(review)
    refreshed['assessment']['groups'][1]['repairObjectives'] = []
    review_assessment.validate_assessment(refreshed)
    review_assessment.validate_redistribution_objective_associations(refreshed, context)
    assert refreshed['assessment']['groups'][0]['repairObjectives'] == [clean_objective]
    assert review_assessment.finding_redistribution_objective_choices(clean, context) == [clean_objective,
        next(choice for choice in choices if set(choice['exerciseRefs']) == {'EXERCISE_0', 'EXERCISE_3'}
             and choice['minimumSessions'] == 3)]


def test_finding_evidence_resolves_occurrences_from_supersets_and_final_components():
    choices = [
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2'], 'minimumSessions': 2},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_1', 'EXERCISE_3'], 'minimumSessions': 2},
    ]
    context = {'draft': {'exercises': [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': 'LIBRARY_A'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'LIBRARY_B'},
        {'id': 'EXERCISE_2', 'libraryDefinitionId': 'LIBRARY_A'},
        {'id': 'EXERCISE_3', 'libraryDefinitionId': 'LIBRARY_B'}],
        'libraryDefinitions': {'LIBRARY_A': {}, 'LIBRARY_B': {}},
        'workouts': [{'exerciseIds': ['EXERCISE_0', 'EXERCISE_1'],
            'supersetGroups': [{'exerciseIds': ['EXERCISE_0', 'EXERCISE_1']}]},
            {'exerciseIds': ['EXERCISE_2', 'EXERCISE_3'], 'supersetGroups': []}]},
        'finalArtifact': {'workouts': [{'components': [{'type': 'Superset', 'exercises': [{'id': 'EXERCISE_1'}]}]}]},
        'redistributionObjectiveChoices': choices}
    assert review_assessment.finding_redistribution_objective_choices(
        {'path': '/draft/workouts/0/supersetGroups/0', 'evidencePaths': []}, context) == choices
    assert review_assessment.finding_redistribution_objective_choices(
        {'path': '/draft/workouts/0/supersetGroups/0/exerciseIds/0', 'evidencePaths': []}, context) == choices
    assert review_assessment.finding_redistribution_objective_choices(
        {'path': '/finalArtifact/workouts/0/components/0/exercises/0', 'evidencePaths': []}, context) == [choices[1]]
    assert review_assessment.finding_redistribution_objective_choices(
        {'path': '/finalArtifact', 'evidencePaths': []}, context) == []

    from workout_generator_pkg import plan_review
    finding = {'severity': 'blocking', 'action': 'repair',
        'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0']}
    with pytest.raises(ValueError, match='identified by this finding'):
        plan_review._validate_confirmation_resolution({
            'status': 'open', 'disposition': 'repair', 'repairDimensions': ['prescription'],
            'repairObjectives': [choices[1]], 'reason': 'Redistribute unrelated exercise.',
            'evidencePaths': ['/draft/exercises/0']}, finding, context)


def test_programming_summary_order_identity_scopes_live_redistribution_objectives():
    library_indexes = (249, 208, 153, 169, 139, 82, 239, 7, 233, 248, 130, 225,
        47, 208, 160, 153, 96, 249, 47, 98, 301, 14, 239, 7)
    definitions = {f'LIBRARY_{index}': {} for index in set(library_indexes)}
    exercises = [{'id': f'EXERCISE_{index}', 'libraryDefinitionId': f'LIBRARY_{library_index}'}
        for index, library_index in enumerate(library_indexes)]
    choices = [
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_17'], 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_1', 'EXERCISE_13'], 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_6', 'EXERCISE_22'], 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_7', 'EXERCISE_23'], 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_12', 'EXERCISE_18'], 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_14'], 'minimumSessions': 2},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_14'], 'minimumSessions': 3},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_19'], 'minimumSessions': 2},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_21'], 'minimumSessions': 2},
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_21'], 'minimumSessions': 3},
    ]
    session_b_order = [
        {'id': f'EXERCISE_{index}', 'name': f'Exercise {index}'}
        for index in (10, 11, 12, 13, 14)]
    context = {'draft': {'exercises': exercises, 'libraryDefinitions': definitions},
        'programmingSummary': {'sessions': [{}, {'finalExerciseOrder': session_b_order}]},
        'redistributionObjectiveChoices': choices}
    finding = {'path': '/programmingSummary/sessions/1/muscles', 'evidencePaths': [
        '/programmingSummary/sessions/1/finalExerciseOrder/2',
        '/programmingSummary/sessions/1/finalExerciseOrder/3',
        '/programmingSummary/sessions/1/finalExerciseOrder/4']}

    allowed = review_assessment.finding_redistribution_objective_choices(finding, context)
    assert allowed == [choices[index] for index in (1, 4, 5, 6)]
    assert review_assessment.finding_redistribution_objective_choices({
        'path': '/programmingSummary/sessions/1/finalExerciseOrder/2/id', 'evidencePaths': []},
        context) == [choices[4]]

    review = {'findings': [finding], 'assessment': {'groups': [{
        'findingIndexes': [0], 'repairObjectives': allowed}]}}
    review_assessment.validate_redistribution_objective_associations(review, context)
    review['assessment']['groups'][0]['repairObjectives'] = [choices[0]]
    with pytest.raises(ValueError, match='identified by this finding group'):
        review_assessment.validate_redistribution_objective_associations(review, context)


def test_selected_large_recipe_compiles_with_exact_weekly_set_conservation():
    draft, task, requirements, definitions, choices = _saved_shape_case()
    objective = next(choice for choice in choices if choice['minimumSessions'] == 3
        and choice['exerciseRefs'] == ['EXERCISE_0', 'EXERCISE_3'])
    task['findingsAssessment'] = {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': ['prescription'], 'repairObjectives': [objective]}]}
    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0], 'edits': {'redistributionTargets': {
            'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}}}
    compiled, _, references = compile_coordinated_repair(arguments, task, draft,
        return_reference_map=True)
    repaired = apply_json_patch(draft, compiled['patch'])
    contract = build_repair_contract([objective], draft, requirements,
        references['redistributionManifest'])

    assert not repair_contract_errors(contract, repaired)
    counts = [sum(item['numWorkSets'] for item in day['exercises']
                  if item['minReps'] == 6 and item['maxReps'] == 8) for day in repaired['workouts']]
    assert sum(counts) == 14
    assert all(count >= 2 for count in counts)
    assert draft['workouts'][2]['exercises'][0]['minReps'] == 12


def test_choices_exclude_mixed_exact_target_modes_and_nonweekly_source_workouts():
    draft, _, requirements, definitions, _ = _saved_shape_case()
    first = draft['workouts'][0]['exercises'][0]
    first['targetSetPrescriptions'] = [
        {'reps': 8, 'weight': None, 'additionalWeight': None} for _ in range(first['numWorkSets'])]
    choices = redistribution_objective_choices(draft, requirements, definitions)
    assert not any(choice['exerciseRefs'] == ['EXERCISE_0', 'EXERCISE_3'] for choice in choices)

    draft['workouts'][0]['timesCompletedInAWeek'] = 2
    assert redistribution_objective_choices(draft, requirements, definitions) == []


def test_homogeneous_exact_targets_remain_available_and_are_conserved():
    draft, task, requirements, definitions, _ = _saved_shape_case()
    source_refs = ['EXERCISE_0', 'EXERCISE_3']
    exact_targets = [{'reps': 8 + index % 2} for index in range(14)]
    cursor = 0
    for workout_index, exercise_index in ((0, 0), (1, 0)):
        item = draft['workouts'][workout_index]['exercises'][exercise_index]
        count = item['numWorkSets']
        item['targetSetPrescriptions'] = copy.deepcopy(exact_targets[cursor:cursor + count])
        cursor += count

    choices = redistribution_objective_choices(draft, requirements, definitions)
    objective = next(choice for choice in choices if choice['exerciseRefs'] == source_refs
        and choice['minimumSessions'] == 3)
    task['findingsAssessment'] = {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': ['prescription'], 'repairObjectives': [objective]}]}
    compiled, _, references = compile_coordinated_repair({
        'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0], 'edits': {'redistributionTargets': {
            'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}}}, task, draft,
        return_reference_map=True)
    repaired = apply_json_patch(draft, compiled['patch'])
    contract = build_repair_contract([objective], draft, requirements,
        references['redistributionManifest'])
    actual = [target for day in repaired['workouts'] for item in day['exercises']
        if item['minReps'] == 6 and item['maxReps'] == 8
        for target in item['targetSetPrescriptions']]

    assert not repair_contract_errors(contract, repaired)
    assert sorted((target_content(item) for item in actual), key=lambda item: item['reps']) == sorted(
        exact_targets, key=lambda item: item['reps'])


def test_empty_redistribution_menu_stays_strict_compatible_and_rejects_nonempty_objective(monkeypatch):
    context = {'draft': {'exercises': [{'id': 'EXERCISE_0'}], 'workouts': [{}, {}]},
        'redistributionObjectiveChoices': []}
    review = {'inputHash': 'empty-menu-candidate', 'findings': [{
        'severity': 'blocking', 'action': 'repair', 'message': 'Correct the plan.',
        'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0']}]}

    def respond(_client, _request, **options):
        schema = options['output_schema']
        assert api_client._strict_parameters_compatible(schema)
        finding = schema['properties']['findingAssessments']['properties']['FINDING_0']
        repair = next(variant for variant in finding['anyOf']
            if variant['properties']['disposition']['enum'] == ['repair'])
        assert repair['properties']['repairObjectives']['type'] == 'array'
        payload = {'findingAssessments': {'FINDING_0': {
            'disposition': 'repair', 'repairDimensions': ['prescription'],
            'repairObjectives': [{'kind': 'redistribute_work',
                'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}],
            'reason': 'The proposed typed objective is not in the empty executable menu.'}},
            'repairPlan': 'Repair through another supported dimension.'}
        return json.dumps(payload), None, None

    monkeypatch.setattr(review_assessment, '_review_call', respond)
    with pytest.raises(ValueError, match='code-enumerated redistribution objective'):
        review_assessment.assess_findings(None, context, review, single_attempt=True)


def test_confirmation_route_uses_the_same_strict_redistribution_choices(monkeypatch):
    from workout_generator_pkg import plan_review
    _, _, _, _, choices = _saved_shape_case()
    context = {'draft': {'workouts': [{'id': 'WORKOUT_0', 'name': 'Day A'}],
        'exercises': [{'id': f'EXERCISE_{index}', 'libraryDefinitionId': 'LIBRARY_0'}
            for index in range(6)], 'libraryDefinitions': {'LIBRARY_0': {}}},
        'sourceMessages': {}, 'redistributionObjectiveChoices': choices}
    part = {'confirmationOnly': True, 'previousBlockingFindings': {
        'DISPUTE_0': {'message': 'A carried concentration concern.',
            'path': '/draft/exercises/0', 'evidencePaths': ['/draft/exercises/0']}}}
    monkeypatch.setattr(plan_review, '_with_review_refs',
        lambda value: (copy.deepcopy(value), {'FACT_0': '/draft/exercises/0'}))
    monkeypatch.setattr(plan_review, '_review_views', lambda *args: None)
    class Captured(Exception):
        pass
    def respond(client, request, **options):
        schema = options['output_schema']
        assert api_client._strict_parameters_compatible(schema)
        variants = schema['properties']['blockerResolutions']['properties']['ISSUE_0']['anyOf']
        repair = next(variant for variant in variants
            if variant['properties']['disposition']['enum'] == ['repair'])
        actual = repair['properties']['repairObjectives']
        finding_choices = review_assessment.finding_redistribution_objective_choices(
            part['previousBlockingFindings']['DISPUTE_0'], context)
        expected = review_assessment._provider_assessment_schema({
            'type': 'object', 'properties': {'choices': review_assessment.repair_objective_selection_schema(finding_choices)},
            'required': ['choices'], 'additionalProperties': False})['properties']['choices']
        assert actual == expected
        for variant in variants:
            if variant['properties']['disposition']['enum'] != ['repair']:
                    assert variant['properties']['repairObjectives']['type'] == 'array'
        raise Captured
    monkeypatch.setattr(plan_review, '_review_call', respond)
    with pytest.raises(Captured):
        plan_review._review_part(None, 'evidence', part, context,
            {'planIndex': {}, 'submittedDraft': {}}, [], 0, None)
