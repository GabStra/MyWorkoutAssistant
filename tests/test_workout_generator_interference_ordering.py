import pytest

from workout_generator_pkg import joint_planning, programming_guidelines as rules


def test_request_policy_separates_overlapping_compounds_without_changing_selected_work():
    import copy
    import json
    from pathlib import Path

    requirements = json.loads((Path(__file__).resolve().parents[1]
        / 'docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    definitions = [
        {'id': 'A', 'exerciseCategory': 'HEAVY_COMPOUND', 'muscleGroups': ['BACK_UPPER_BACK']},
        {'id': 'B', 'exerciseCategory': 'HEAVY_COMPOUND', 'muscleGroups': ['FRONT_CHEST']},
        {'id': 'C', 'exerciseCategory': 'MODERATE_COMPOUND', 'muscleGroups': ['FRONT_QUADRICEPS']},
        {'id': 'D', 'exerciseCategory': 'MODERATE_COMPOUND', 'muscleGroups': ['FRONT_QUADRICEPS']},
        {'id': 'E', 'exerciseCategory': 'ISOLATION', 'muscleGroups': ['FRONT_BICEPS']},
        {'id': 'F', 'exerciseCategory': 'ISOLATION', 'muscleGroups': ['FRONT_ABS']},
    ]
    items = [{'definition_id': f'LIBRARY_{index}', 'numWorkSets': 2, 'superset': None,
        'satisfiesCoverage': ['knee_dominant'] if index in (2, 3) else [],
        'restBetweenSetsSeconds': 120 if index < 2 else 90 if index < 4 else 60,
        'restAfterExerciseSeconds': 0, 'restAfterSupersetExerciseSeconds': 0}
        for index in range(len(definitions))]
    draft = {'workouts': [{'name': 'Day', 'exercises': copy.deepcopy(items)}]}
    equipment = {'exerciseDefinitions': definitions}
    roles = [set(item['satisfiesCoverage']) for item in items]
    profiles = [rules.execution_interference_profile([definition], [2], role, requirements)
        for definition, role in zip(definitions, roles, strict=True)]
    keys = [rules.execution_block_order_key([definition], [2]) for definition in definitions]

    strict = copy.deepcopy(requirements)
    strict['orderingPreferences']['phaseOrder'] = [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]
    blocked = rules.canonical_execution_order_draft(draft, strict, equipment)
    ordered = rules.canonical_execution_order_draft(draft, requirements, equipment)
    indexes = lambda value: [int(item['definition_id'].removeprefix('LIBRARY_'))
        for item in value['workouts'][0]['exercises']]
    before, after = indexes(blocked), indexes(ordered)
    assert abs(before.index(2) - before.index(3)) == 1
    assert abs(after.index(2) - after.index(3)) > 1
    assert rules.execution_order_is_admissible(after, roles, keys, requirements)
    assert not rules.execution_order_is_admissible(after, roles, keys, strict)
    assert max(after.index(index) for index in range(4)) < after.index(4) < after.index(5)
    before_score = rules.execution_interference_score(before, profiles)
    after_score = rules.execution_interference_score(after, profiles)
    assert after_score[:6] == before_score[:6]
    assert after_score[6] < before_score[6]
    assert sorted(ordered['workouts'][0]['exercises'], key=lambda item: item['definition_id']) == items
    assert draft['workouts'][0]['exercises'] == items


@pytest.mark.parametrize('phases', [
    [['HEAVY_COMPOUND', 'MODERATE_COMPOUND']],
    [['HEAVY_COMPOUND'], ['MODERATE_COMPOUND']]])
def test_order_search_can_change_opener_to_protect_heavy_work_but_preserves_explicit_priority(phases):
    requirements = {'objectiveOrder': ['execution_order'], 'executionRules': [],
        'orderingPreferences': {'phaseOrder': phases, 'protectionOrder': ['heavy_direct']}}
    definitions = [
        {'id': 'A', 'exerciseCategory': 'MODERATE_COMPOUND', 'muscleGroups': ['FRONT_CHEST']},
        {'id': 'B', 'exerciseCategory': 'HEAVY_COMPOUND', 'muscleGroups': ['FRONT_CHEST']},
        {'id': 'C', 'exerciseCategory': 'HEAVY_COMPOUND', 'muscleGroups': ['FRONT_QUADRICEPS']}]
    roles = [{'technique'}, {'main'}, {'squat'}]
    profiles = [rules.execution_interference_profile([definition], [3], role, requirements)
        for definition, role in zip(definitions, roles, strict=True)]
    keys = [rules.execution_block_order_key([definition], [3]) for definition in definitions]
    order = rules.execution_order_indices(roles, keys, requirements, interference_profiles=profiles)
    assert order.index(1) < order.index(0)
    assert rules.execution_interference_score(order, profiles, requirements) == (0, 0)
    assert rules.execution_order_is_admissible(order, roles, keys, requirements)
    requirements['executionRules'] = [{'kind': 'order', 'before': 'technique', 'after': 'main'},
                                      {'kind': 'order', 'before': 'technique', 'after': 'squat'}]
    ordered_priority = rules.execution_order_indices(roles, keys, requirements, interference_profiles=profiles)
    assert ordered_priority[0] == 0
    assert rules.execution_order_is_admissible(ordered_priority, roles, keys, requirements)


@pytest.mark.parametrize('metric', ['heavy_direct', 'heavy_support', 'main_direct', 'main_support'])
def test_protected_exposure_uses_total_only_after_preserving_peak(metric):
    requirements = {'orderingPreferences': {'protectionOrder': [metric]}}
    category = 'HEAVY_COMPOUND' if metric.startswith('heavy_') else 'MODERATE_COMPOUND'
    anatomy = [('FRONT_CHEST', 'BACK_TRICEPS'), ('FRONT_QUADRICEPS', 'BACK_GLUTEAL'),
               ('BACK_UPPER_BACK', 'FRONT_BICEPS')]
    profiles = [rules.execution_interference_profile([{'exerciseCategory': category,
        'muscleGroups': [anatomy[index // 2][0]],
        'secondaryMuscleGroups': [anatomy[index // 2][1]] if metric.endswith('_support') else []}],
        [count], [], requirements) for index, count in enumerate([3, 2, 1, 2, 1, 2])]
    score = lambda order: rules.execution_interference_score(order, profiles, requirements)
    assert rules.execution_interference_metric_names(requirements) == (metric, metric + '_total')
    assert score([1, 0, 3, 2, 5, 4]) == (2, 6)
    assert score([0, 1, 2, 3, 4, 5]) == (3, 5)
    assert score([1, 0, 3, 2, 5, 4]) < score([0, 1, 2, 3, 4, 5])
    assert score([1, 0, 2, 3, 5, 4]) == (2, 5)
    assert score([1, 0, 2, 3, 5, 4]) < score([1, 0, 3, 2, 5, 4])


def test_heavy_exposure_tie_refinement_precedes_main_work_without_changing_admission():
    # Category/anatomy/counts from the retained Nov 6 Wednesday main blocks.
    data = [
        [('H', ['BACK_UPPER_BACK'], ['BACK_TRAPEZIUS', 'BACK_DELTOIDS', 'FRONT_BICEPS'], 2)],
        [('H', ['BACK_UPPER_BACK', 'BACK_TRAPEZIUS'], ['BACK_DELTOIDS', 'FRONT_BICEPS'], 3)],
        [('M', ['FRONT_CHEST'], ['BACK_DELTOIDS', 'BACK_TRICEPS'], 3)],
        [('M', ['BACK_HAMSTRING', 'BACK_GLUTEAL'], ['BACK_ADDUCTORS', 'BACK_LOWER_BACK'], 2),
         ('I', ['FRONT_DELTOIDS'], ['BACK_TRAPEZIUS'], 2)],
        [('H', ['BACK_GLUTEAL', 'FRONT_QUADRICEPS'], ['FRONT_ABS', 'BACK_ADDUCTORS', 'BACK_LOWER_BACK'], 3)],
    ]
    requirements = {'objectiveOrder': ['execution_order'], 'executionRules': [],
        'orderingPreferences': {'protectionOrder': list(rules.INTERFERENCE_METRICS), 'phaseOrder': [
            ['HEAVY_COMPOUND', 'MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]}}
    definitions = [[{'id': f'{index}_{member}', 'exerciseCategory': {
        'H': 'HEAVY_COMPOUND', 'M': 'MODERATE_COMPOUND', 'I': 'ISOLATION'}[category],
        'muscleGroups': direct, 'secondaryMuscleGroups': supporting}
        for member, (category, direct, supporting, count) in enumerate(block)]
        for index, block in enumerate(data)]
    profiles = [rules.execution_interference_profile(block, [row[3] for row in data[index]], [], requirements)
        for index, block in enumerate(definitions)]
    roles = [{'pull'}, {'row'}, {'press'}, {'hinge'}, {'squat'}]
    keys = [rules.execution_block_order_key(block, [row[3] for row in data[index]])
        for index, block in enumerate(definitions)]
    late, early = [0, 1, 2, 3, 4], [0, 4, 1, 2, 3]
    old_late, old_early = [rules.execution_interference_score(order, profiles) for order in (late, early)]
    assert old_late[2:4] == old_early[2:4] == (2, 6)
    assert old_late[4] == 2 and old_early[4] == 3
    assert old_late < old_early
    names = rules.execution_interference_metric_names(requirements)
    facts = [dict(zip(names, rules.execution_interference_score(order, profiles, requirements), strict=True))
        for order in (late, early)]
    assert [row['heavy_direct_total'] for row in facts] == [4, 2]
    assert [row['heavy_support_total'] for row in facts] == [10, 6]
    assert rules.execution_interference_score(early, profiles, requirements) < rules.execution_interference_score(
        late, profiles, requirements)
    selected = rules.execution_order_indices(roles, keys, requirements, interference_profiles=profiles)
    assert selected.index(4) < selected.index(3)
    assert rules.execution_order_is_admissible(selected, roles, keys, requirements)

    from workout_generator_pkg import cp_solver
    from workout_generator_pkg.generation_audit import setup_resource_profile
    variables, constraints, blocks = [], [], []
    def variable(upper=1, lower=0, integer=True, domain_identity=None):
        variables.append({'upper': upper, 'lower': lower, 'integer': integer,
            'domainIdentity': domain_identity, 'objectiveCost': 0})
        return len(variables) - 1
    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((label, lower, upper, intercept, coefficients))
    for index, block in enumerate(definitions):
        option = variable(lower=1)
        blocks.append({'first': variable(), 'options': [option],
            'optionValues': {option: {'count': data[index][0][3],
                'setupProfiles': [setup_resource_profile(definition) for definition in block]}},
            'recipe': {'roles': roles[index], 'orderPriority': keys[index][0],
                'interferencePerRound': rules.execution_interference_profile(
                    block, [1] * len(block), [], requirements)}})
    costs, _ = joint_planning._add_execution_sequence(blocks, requirements, variable, constraint, 0, 2)
    objective_variables = [{**item, 'objectiveCost': sum(cost.get(index, 0) for cost in costs.values())}
        for index, item in enumerate(variables)]
    arcs = blocks[0]['sequenceArcs']
    for order in (late, early):
        path = [(0, order[0] + 1), *[(a + 1, b + 1) for a, b in zip(order, order[1:])],
            (order[-1] + 1, 0)]
        pinned = [(('path', *edge), 1, 1, 0, {arcs[edge]: 1}) for edge in path]
        status, chosen = cp_solver.solve(objective_variables, [*constraints, *pinned])
        assert status == 'optimal'
        cp_score = tuple(sum(chosen[index] * value for index, value in costs['ordering_' + name].items())
            for name in names)
        assert cp_score == tuple(2 * value for value in rules.execution_interference_score(
            order, profiles, requirements))

    requirements['executionRules'] = [{'kind': 'order', 'before': 'hinge', 'after': 'squat'}]
    constrained = rules.execution_order_indices(roles, keys, requirements, interference_profiles=profiles)
    assert constrained.index(3) < constrained.index(4)
    assert rules.execution_order_is_admissible(constrained, roles, keys, requirements)


def retained_order_case():
    # Exact category/anatomy/count profiles from the Nov 3 exported Session A.
    data = [
        [('H', ['BACK_UPPER_BACK'], ['FRONT_BICEPS', 'BACK_DELTOIDS', 'BACK_TRAPEZIUS'], 2)],
        [('M', ['BACK_HAMSTRING', 'BACK_GLUTEAL'], ['BACK_ADDUCTORS'], 2)],
        [('H', ['BACK_UPPER_BACK', 'BACK_TRAPEZIUS'], ['BACK_DELTOIDS', 'FRONT_BICEPS'], 2)],
        [('H', ['FRONT_QUADRICEPS', 'BACK_GLUTEAL'], ['BACK_ADDUCTORS'], 3)],
        [('H', ['FRONT_DELTOIDS'], ['BACK_TRICEPS', 'BACK_TRAPEZIUS', 'FRONT_CHEST'], 2)],
        [('M', ['FRONT_CHEST', 'BACK_UPPER_BACK'], [], 2)],
        [('M', ['FRONT_QUADRICEPS', 'BACK_GLUTEAL'], ['BACK_ADDUCTORS'], 2),
         ('I', ['FRONT_DELTOIDS'], ['BACK_TRAPEZIUS'], 2)],
        [('M', ['FRONT_CHEST'], ['BACK_TRICEPS', 'FRONT_DELTOIDS'], 2)],
        [('I', ['FRONT_BICEPS'], ['FRONT_FOREARM'], 3)],
        [('I', ['BACK_TRICEPS'], [], 3)],
        [('I', ['BACK_CALVES'], [], 3)],
        [('I', ['BACK_HAMSTRING'], [], 3)],
        [('I', ['FRONT_ABS'], [], 3)],
    ]
    definitions, blocks = [], []
    for block_index, members in enumerate(data):
        block = []
        for category, primary, supporting, count in members:
            index = len(definitions)
            definitions.append({'id': f'D{index:02}', 'muscleGroups': primary,
                'secondaryMuscleGroups': supporting, 'exerciseCategory': {
                    'H': 'HEAVY_COMPOUND', 'M': 'MODERATE_COMPOUND', 'I': 'ISOLATION'}[category]})
            block.append({'definition_id': f'LIBRARY_{index}', 'numWorkSets': count,
                'superset': 'PAIR' if len(members) > 1 else None,
                'satisfiesCoverage': [f'block{block_index}'],
                'restAfterSupersetExerciseSeconds': 15 if category == 'M' else 90,
                'restAfterExerciseSeconds': 0})
        blocks.append(block)
    return definitions, blocks


def test_retained_order_escapes_pair_swap_minimum_and_admission_does_not_call_optimizer(monkeypatch):
    definitions, blocks = retained_order_case()
    requirements = {'objectiveOrder': ['movement_overlap'], 'executionRules': []}
    lookup = {f'LIBRARY_{index}': definition for index, definition in enumerate(definitions)}
    roles = [{f'block{index}'} for index in range(len(blocks))]
    profiles = [rules.execution_interference_profile([lookup[item['definition_id']] for item in block],
        [item['numWorkSets'] for item in block], role, requirements)
        for block, role in zip(blocks, roles, strict=True)]
    keys = [rules.execution_block_order_key([lookup[item['definition_id']] for item in block],
        [item['numWorkSets'] for item in block]) for block in blocks]
    original = list(range(len(blocks)))
    assert rules.execution_interference_score(original, profiles) == (0, 0, 2, 8, 10, 15, 0, 4)
    selected = rules.execution_order_indices(roles, keys, requirements, interference_profiles=profiles)
    assert rules.execution_interference_score(selected, profiles) == (0, 0, 2, 8, 8, 13, 0, 8)
    assert selected[0] == 0
    draft = {'workouts': [{'name': 'Day', 'exercises': [item for index in selected for item in blocks[index]]}]}
    equipment = {'exerciseDefinitions': definitions}
    assert rules.canonical_execution_order_draft(draft, requirements, equipment) == draft

    # A distinct admissible same-phase sequence need not match the optimizer's choice.
    alternative = original.copy()
    alternative[1], alternative[3] = alternative[3], alternative[1]
    for order in (selected, alternative):
        ordered_items = [item for index in order for item in blocks[index]]
        plan = {'exercises': [dict(definition, id=f'E{index}') for index, definition in enumerate(definitions)],
            'workouts': [{'exerciseIds': ['E' + item['definition_id'].removeprefix('LIBRARY_') for item in ordered_items]}]}
        report = {'errors': [], 'issues': []}
        monkeypatch.setattr(rules, 'execution_order_indices', lambda *a, **k: pytest.fail('audit invoked optimizer'))
        rules.audit_execution_rules({'workouts': [{'name': 'Day', 'exercises': ordered_items}]}, requirements, report, plan)
        assert not report['errors']


def test_order_admissibility_preserves_explicit_edges_and_accessory_core_phases():
    roles = [{'main'}, {'accessory'}, {'core'}]
    keys = [(0, 'main'), (2, 'accessory'), (3, 'core')]
    requirements = {'objectiveOrder': ['movement_overlap'], 'executionRules': []}
    assert rules.execution_order_is_admissible([0, 1, 2], roles, keys, requirements)
    assert not rules.execution_order_is_admissible([1, 0, 2], roles, keys, requirements)
    assert not rules.execution_order_is_admissible([0, 2, 1], roles, keys, requirements)
    requirements['executionRules'] = [{'kind': 'order', 'before': 'core', 'after': 'main'}]
    assert rules.execution_order_is_admissible([1, 2, 0], roles, keys, requirements)
    assert not rules.execution_order_is_admissible([0, 1, 2], roles, keys, requirements)

    definitions, blocks = retained_order_case()
    blocks[0], blocks[8] = blocks[8], blocks[0]
    items = [item for block in blocks for item in block]
    plan = {'exercises': [dict(definition, id=f'E{index}') for index, definition in enumerate(definitions)],
        'workouts': [{'exerciseIds': ['E' + item['definition_id'].removeprefix('LIBRARY_') for item in items]}]}
    report = {'errors': [], 'issues': []}
    rules.audit_execution_rules({'workouts': [{'name': 'Day', 'exercises': items}]},
        {'objectiveOrder': ['movement_overlap'], 'executionRules': []}, report, plan)
    assert [error['code'] for error in report['errors']] == ['execution_order']
    report = {'errors': [], 'issues': []}
    rules.audit_execution_rules({'workouts': [{'name': 'Day', 'exercises': items}]},
        {'objectiveOrder': ['movement_overlap'], 'executionRules': [
            {'kind': 'order', 'before': 'block0', 'after': 'block8'}]}, report, plan)
    assert any(error.get('rulePath') == '/executionRules/0' for error in report['errors'])


def test_order_search_keeps_larger_main_phases_bounded(monkeypatch):
    monkeypatch.setattr(rules, 'permutations', lambda *a: pytest.fail('unbounded exact search'))
    requirements = {'objectiveOrder': ['movement_overlap']}
    profile = rules.execution_interference_profile([
        {'muscleGroups': ['FRONT_CHEST'], 'exerciseCategory': 'HEAVY_COMPOUND'}], [2], [], requirements)
    order = rules.execution_order_indices([set()] * 9, [(0, index) for index in range(9)],
        requirements, interference_profiles=[profile] * 9)
    assert sorted(order) == list(range(9)) and order[0] == 0


def test_training_dose_lock_allows_equivalent_exercise_substitution():
    options = [(index, 0, index, {'items': [{'definition_id': reference}], 'count': 2,
        'coverage': {'upper_pull': 2}, 'volume': {'back': {'effective': 2}}})
        for index, reference in enumerate(('ROW_A', 'ROW_B'))]
    features = []
    joint_planning._lock_weekly_training_doses(features, [1, 0], options,
        [{'timesCompletedInAWeek': 1}], ['upper_pull'], ['back'])
    for _, minimum, maximum, intercept, coefficients in features:
        value = intercept + sum(coefficient * [0, 1][index] for index, coefficient in coefficients.items())
        assert minimum == value == maximum
    assert {label[1] for label, *_ in features} == {'physical_sets', 'coverage', 'muscle'}


def test_shared_muscle_does_not_make_distinct_movements_redundant():
    items = [{'definition_id': 'SQUAT', 'satisfiesCoverage': ['quads', 'glutes', 'knee_dominant']},
             {'definition_id': 'HINGE', 'satisfiesCoverage': ['glutes', 'hamstrings', 'hip_dominant']}]
    assert joint_planning.overlapping_movement_pairs(items) == []
    items.append({'definition_id': 'SECOND_SQUAT', 'satisfiesCoverage': ['glutes', 'knee_dominant']})
    assert joint_planning.overlapping_movement_pairs(items) == [('SECOND_SQUAT', 'SQUAT')]


def test_interference_counts_supporting_work_beyond_the_previous_exercise():
    profiles = [
        rules.execution_interference_profile([{'muscleGroups': ['FRONT_CHEST'],
            'secondaryMuscleGroups': ['BACK_TRICEPS']}], [3], [], {}),
        rules.execution_interference_profile([{'muscleGroups': ['FRONT_QUADRICEPS']}], [3], [], {}),
        rules.execution_interference_profile([{'muscleGroups': ['BACK_TRICEPS']}], [2], ['elbow_extension'],
            {'executionRules': [{'kind': 'order', 'before': 'elbow_extension', 'after': 'other'}]})]
    score = rules.execution_interference_score([0, 1, 2], profiles)
    assert score[:2] == (0, 3)
    assert score[2:] == (0, 0, 0, 0, 0, 0)
    assert rules.execution_interference_score([2, 1, 0], profiles)[:2] == (0, 0)


def test_main_compound_order_minimizes_worst_cumulative_primary_exposure():
    requirements = {'objectiveOrder': ['movement_overlap']}
    definitions = [
        {'muscleGroups': ['FRONT_CHEST'], 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'muscleGroups': ['FRONT_QUADRICEPS'], 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'muscleGroups': ['FRONT_QUADRICEPS'], 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'muscleGroups': ['FRONT_QUADRICEPS'], 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'muscleGroups': ['BACK_UPPER_BACK'], 'exerciseCategory': 'MODERATE_COMPOUND'},
    ]
    counts = [2, 5, 1, 1, 2]
    roles = [set()] * len(definitions)
    profiles = [rules.execution_interference_profile([definition], [count], role, requirements)
        for definition, count, role in zip(definitions, counts, roles, strict=True)]
    source_order = list(range(len(definitions)))
    order = rules.execution_order_indices(roles, [(1, index) for index in source_order], requirements,
        interference_profiles=profiles)

    assert order[0] == 0  # The first block remains pinned for solver setup constraints.
    assert rules.execution_interference_score(order, profiles)[4] == 2
    assert rules.execution_interference_score(order, profiles) < rules.execution_interference_score(source_order, profiles)


@pytest.mark.parametrize('moderate_primary,moderate_supporting', [
    (['FRONT_QUADRICEPS'], []), (['BACK_HAMSTRING'], ['FRONT_QUADRICEPS'])])
def test_heavy_work_precedes_overlapping_moderate_work_with_noncompeting_interleaving(
        moderate_primary, moderate_supporting):
    requirements = {'objectiveOrder': ['movement_overlap', 'setup_economy']}
    definitions = [
        {'muscleGroups': ['BACK_UPPER_BACK'], 'exerciseCategory': 'HEAVY_COMPOUND'},
        {'muscleGroups': moderate_primary, 'secondaryMuscleGroups': moderate_supporting,
            'exerciseCategory': 'MODERATE_COMPOUND'},
        {'muscleGroups': ['FRONT_CHEST'], 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'muscleGroups': ['FRONT_QUADRICEPS'], 'exerciseCategory': 'HEAVY_COMPOUND'},
    ]
    counts = [2, 2, 2, 3]
    roles = [set() for _ in definitions]
    profiles = [rules.execution_interference_profile([definition], [count], role, requirements)
        for definition, count, role in zip(definitions, counts, roles, strict=True)]
    resources = [frozenset({gear}) for gear in ('a', 'a', 'b', 'a')]
    keys = [rules.execution_block_order_key([dict(definition, id=str(index))], [counts[index]])
        for index, definition in enumerate(definitions)]
    order = rules.execution_order_indices(roles, keys, requirements, resources, profiles)

    assert order == [0, 3, 2, 1]
    assert rules.execution_interference_score(order, profiles)[2:4] == (0, 0)
    requirements['executionRules'] = [{'kind': 'order', 'before': 'priority', 'after': 'absent'}]
    roles[1].add('priority')
    profiles[1] = rules.execution_interference_profile([definitions[1]], [counts[1]], roles[1], requirements)
    priority_order = rules.execution_order_indices(roles, keys, requirements, resources, profiles)
    assert priority_order.index(1) < priority_order.index(3)


def test_accessory_superset_partner_does_not_gain_heavy_work_protection():
    profiles = [rules.execution_interference_profile(definitions, [2] * len(definitions), [], {})
        for definitions in ([{'muscleGroups': ['FRONT_CHEST'], 'exerciseCategory': 'HEAVY_COMPOUND'},
            {'muscleGroups': ['FRONT_QUADRICEPS'], 'exerciseCategory': 'ISOLATION'}],
            [{'muscleGroups': ['FRONT_QUADRICEPS'], 'exerciseCategory': 'MODERATE_COMPOUND'}])]
    assert profiles[0]['primary'] == {'chest': 2, 'quads': 2}
    assert profiles[0]['heavy_primary'] == ['chest']
    assert rules.execution_interference_score([1, 0], profiles)[2:4] == (0, 0)


def test_accessory_superset_partner_does_not_gain_main_work_protection():
    prior = {'muscleGroups': ['FRONT_DELTOIDS'], 'secondaryMuscleGroups': ['BACK_TRAPEZIUS'],
             'exerciseCategory': 'ISOLATION'}
    main = {'muscleGroups': ['BACK_HAMSTRING', 'BACK_GLUTEAL'],
            'secondaryMuscleGroups': ['BACK_ADDUCTORS'], 'exerciseCategory': 'MODERATE_COMPOUND'}
    accessory = {'muscleGroups': ['FRONT_DELTOIDS'], 'secondaryMuscleGroups': ['BACK_TRAPEZIUS'],
                 'exerciseCategory': 'ISOLATION'}
    profiles = [rules.execution_interference_profile(definitions, counts, [], {})
        for definitions, counts in (([prior], [3]), ([main, accessory], [2, 2]), ([accessory], [2]))]

    assert profiles[1]['main_primary'] == ['glutes', 'hamstrings']
    assert profiles[1]['main_supporting'] == ['adductors']
    assert rules.execution_interference_score([0, 1], profiles)[4:6] == (0, 0)
    # The isolation still contributes actual source exposure and adjacent overlap.
    assert profiles[1]['primary']['shoulders'] == 2
    assert profiles[1]['supporting']['traps'] == 2
    assert rules.execution_interference_score([0, 1, 2], profiles)[6:] == (5, 5)
    singleton = rules.execution_interference_profile([main], [2], [], {})
    assert singleton['main_primary'] == sorted(singleton['primary'])
    assert singleton['main_supporting'] == sorted(singleton['supporting'])

    from workout_generator_pkg import cp_solver
    from workout_generator_pkg.generation_audit import setup_resource_profile
    variables, constraints, blocks = [], [], []
    def variable(upper=1, lower=0, integer=True, domain_identity=None):
        variables.append({'upper': upper, 'lower': lower, 'integer': integer,
                          'domainIdentity': domain_identity, 'objectiveCost': 0})
        return len(variables) - 1
    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((label, lower, upper, intercept, coefficients))
    requirements = {'objectiveOrder': ['execution_order'],
        'orderingPreferences': {'protectionOrder': ['main_direct', 'main_support']}}
    for index, (definitions, count) in enumerate((([prior], 3), ([main, accessory], 2))):
        option = variable(lower=1)
        blocks.append({'first': variable(lower=int(index == 0), upper=int(index == 0)),
            'options': [option], 'optionValues': {option: {'count': count,
                'setupProfiles': [setup_resource_profile(definition) for definition in definitions]}},
            'recipe': {'roles': set(), 'orderPriority': 0,
                'interferencePerRound': rules.execution_interference_profile(
                    definitions, [1] * len(definitions), [], requirements)}})
    costs, _ = joint_planning._add_execution_sequence(blocks, requirements, variable, constraint, 0, 1)
    metric_names = rules.execution_interference_metric_names(requirements)
    objective = {index: cost for name in metric_names
        for index, cost in costs['ordering_' + name].items()}
    status, chosen = cp_solver.solve([{**item, 'objectiveCost': objective.get(index, 0)}
        for index, item in enumerate(variables)], constraints)
    assert status == 'optimal'
    cp_score = tuple(sum(chosen[index] * value for index, value in costs['ordering_' + name].items())
                     for name in metric_names)
    assert cp_score == rules.execution_interference_score([0, 1], profiles, requirements) == (0, 0, 0, 0)


def test_reviewed_execution_support_changes_sequence_exposure_without_volume_credit():
    import copy
    from workout_generator_pkg.exercise_contracts import execution_supporting_muscles
    from workout_generator_pkg.generation_audit import muscle_credits_per_set

    opener = {'id': 'opener', 'muscleGroups': ['FRONT_QUADRICEPS'],
              'exerciseCategory': 'HEAVY_COMPOUND'}
    hinge = {'id': 'hinge', 'muscleGroups': ['BACK_HAMSTRING', 'BACK_GLUTEAL'],
             'secondaryMuscleGroups': ['BACK_ADDUCTORS'], 'exerciseCategory': 'MODERATE_COMPOUND'}
    row = {'id': 'row', 'muscleGroups': ['BACK_UPPER_BACK'],
           'secondaryMuscleGroups': ['FRONT_BICEPS'], 'exerciseCategory': 'HEAVY_COMPOUND'}
    accessory = {'id': 'accessory', 'muscleGroups': ['FRONT_DELTOIDS'],
                 'secondaryMuscleGroups': ['BACK_TRAPEZIUS'], 'exerciseCategory': 'ISOLATION'}
    definitions = [opener, hinge, row, accessory]
    original = copy.deepcopy(definitions)
    credits = [muscle_credits_per_set(definition) for definition in definitions]
    facts = {'supportingMuscles': ['lowerBack', 'abs'], 'source': 'https://example.com/reviewed-execution',
             'basis': 'The reviewed execution uses spinal support and abdominal bracing.'}
    hinge['reviewedExecution'] = {**facts, 'supportingMuscles': ['lowerBack', 'abs', 'adductors', 'glutes']}
    row['reviewedExecution'] = copy.deepcopy(facts)
    accessory['reviewedExecution'] = {**facts, 'supportingMuscles': ['neck']}

    assert execution_supporting_muscles(opener) is None
    assert [muscle_credits_per_set(definition) for definition in definitions] == credits
    requirements = {'objectiveOrder': ['execution_order'],
        'executionRules': [{'kind': 'order', 'before': 'opener', 'after': 'work'}], 'orderingPreferences': {
        'protectionOrder': list(rules.INTERFERENCE_METRICS),
        'phaseOrder': [['HEAVY_COMPOUND', 'MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]}}
    roles = [{'opener'}, {'work'}, {'work'}, {'work'}]
    profiles = [rules.execution_interference_profile([definition], [2], role, requirements)
                for definition, role in zip(definitions, roles, strict=True)]
    assert profiles[1]['supporting'] == {'adductors': 2, 'abs': 2, 'lowerBack': 2}
    assert profiles[1]['main_supporting'] == ['abs', 'adductors', 'lowerBack']
    mixed = rules.execution_interference_profile([hinge, accessory], [2, 2], [], requirements)
    assert 'neck' in mixed['supporting'] and 'neck' not in mixed['main_supporting']
    assert mixed['heavy_supporting'] == []
    old_profiles = [rules.execution_interference_profile([definition], [2], [], requirements)
                    for definition in original]
    support_index = rules.execution_interference_metric_names(requirements).index('heavy_support')
    assert rules.execution_interference_score([0, 1, 2, 3], old_profiles, requirements)[support_index] == 0
    assert rules.execution_interference_score([0, 1, 2, 3], profiles, requirements)[support_index] == 4
    keys = [rules.execution_block_order_key([definition], [2]) for definition in definitions]
    order = rules.execution_order_indices(roles, keys, requirements, interference_profiles=profiles)
    assert order[0] == 0 and order.index(2) < order.index(1)
    assert rules.execution_interference_score(order, profiles, requirements) < rules.execution_interference_score(
        [0, 1, 2, 3], profiles, requirements)
    assert 'demand_distribution' not in requirements['objectiveOrder']


def test_whole_sequence_comparison_improves_on_source_order_and_respects_explicit_edges():
    requirements = {'objectiveOrder': ['movement_overlap'],
        'executionRules': [{'kind': 'order', 'before': 'opener', 'after': 'vertical_pull'}],
        'requiredCoverage': [{'key': 'vertical_pull', 'intent': 'development'}]}
    roles = [{'opener'}, {'vertical_pull'}, {'vertical_pull'}]
    profiles = [rules.execution_interference_profile([{'muscleGroups': [tag]}], [count], role, requirements)
        for tag, count, role in zip(['FRONT_QUADRICEPS', 'BACK_UPPER_BACK', 'BACK_UPPER_BACK'],
            [3, 3, 2], roles, strict=True)]
    order = rules.execution_order_indices(roles, [(0, index) for index in range(3)],
        requirements, interference_profiles=profiles)
    assert order == [0, 2, 1]
    assert rules.execution_interference_score(order, profiles) < rules.execution_interference_score([0, 1, 2], profiles)
    requirements['executionRules'].append({'kind': 'order', 'before': 'first', 'after': 'second'})
    roles[1].add('first'); roles[2].add('second')
    assert rules.execution_order_indices(roles, [(0, index) for index in range(3)], requirements,
        interference_profiles=profiles) == [0, 1, 2]


def test_core_containing_accessory_superset_stays_after_other_accessories():
    calf = {'muscleGroups': ['BACK_CALVES'], 'exerciseCategory': 'ISOLATION'}
    core = {'muscleGroups': ['FRONT_ABS'], 'exerciseCategory': 'ISOLATION'}
    assert rules.execution_block_priority([calf, core]) == 3
    assert rules.execution_block_priority([calf]) == 2
    assert rules.execution_order_indices([{'calves', 'abs'}, {'elbow_flexion'}], [(3, 0), (2, 1)],
        {'objectiveOrder': ['movement_overlap']}) == [1, 0]


def test_core_and_main_work_superset_uses_existing_split_gate():
    items = [{'definition_id': reference, 'numWorkSets': 2, 'superset': 'PAIR',
              'satisfiesCoverage': []} for reference in ('MAIN', 'CORE')]
    plan = {'exercises': [
        {'id': 'E0', 'exerciseCategory': 'HEAVY_COMPOUND', 'muscleGroups': ['FRONT_CHEST']},
        {'id': 'E1', 'exerciseCategory': 'ISOLATION', 'muscleGroups': ['FRONT_ABS']}],
        'workouts': [{'exerciseIds': ['E0', 'E1']}]}
    report = {'issues': [], 'errors': []}
    rules.audit_execution_rules({'workouts': [{'name': 'Day', 'exercises': items}]},
        {'objectiveOrder': ['movement_overlap']}, report, plan)
    assert any(error['code'] == 'execution_superset_order_conflict' for error in report['errors'])


def test_solver_first_setup_and_priority_order_use_the_same_owner():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'movement_overlap']
    requirements['requiredCoverage'][1]['intent'] = 'development'
    requirements['executionRules'] = [{'kind': 'order', 'before': 'second', 'after': 'first'}]
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert result['sessions'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    assert not result['audit']['errors']


def test_joint_solver_splits_main_core_group_instead_of_delaying_main_work():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'movement_overlap']
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'chest': {'minimum': 2, 'maximum': 2}, 'abs': {'minimum': 2, 'maximum': 2}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 2}]
    equipment['exerciseDefinitions'][0]['exerciseCategory'] = 'HEAVY_COMPOUND'
    equipment['exerciseDefinitions'][1].update(muscleGroups=['FRONT_ABS'],
        secondaryMuscleGroups=[], exerciseCategory='ISOLATION')
    for index, item in enumerate(sessions[0]['exercises']):
        item.update(numWorkSets=2, superset='PAIR', restBetweenSetsSeconds=0,
            restAfterSupersetExerciseSeconds=30 if index == 0 else 90)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert all(item['superset'] is None for item in result['sessions'][0]['exercises'])
    assert any(error['code'] == 'execution_superset_order_conflict' for error in result['rejectedOptions'])
    assert not result['audit']['errors']


def test_development_dose_does_not_promote_a_compound_superset_partner():
    requirements = {'requiredCoverage': [{'key': 'lateral_delt', 'intent': 'development'}]}
    assert rules.execution_priority_rank({'knee_dominant', 'lateral_delt'}, requirements) == 1
    requirements['executionRules'] = [{'kind': 'order', 'before': 'lateral_delt', 'after': 'press'}]
    assert rules.execution_priority_rank({'knee_dominant', 'lateral_delt'}, requirements) == 0


def test_lower_body_pair_exposure_is_round_aware_without_penalizing_upper_lower_pairings():
    squat = {'muscleGroups': ['FRONT_QUADRICEPS', 'BACK_GLUTEAL']}
    knee_flexion = {'muscleGroups': ['BACK_HAMSTRING']}
    press = {'muscleGroups': ['FRONT_CHEST']}
    assert rules.superset_lower_body_pair_sets([squat, knee_flexion], [3, 3]) == 3
    assert rules.superset_lower_body_pair_sets([squat, knee_flexion], [2, 3]) == 2
    assert rules.superset_lower_body_pair_sets([press, knee_flexion], [3, 3]) == 0
    assert joint_planning._ordered_joint_objective_names({'objectiveOrder': ['movement_overlap', 'duration_economy']},
        {'movement_overlap': True, 'superset_lower_body_overlap': True, 'duration_economy': True}) == [
            'movement_overlap', 'superset_lower_body_overlap', 'duration_economy']



def test_execution_order_compares_known_load_changes_not_only_equipment_ids():
    from workout_generator_pkg.generation_audit import setup_resource_profile
    requirements = {'objectiveOrder': ['movement_overlap', 'setup_economy']}
    definitions = [{'id': str(index), 'equipmentId': 'bar', 'exerciseType': 'WEIGHT',
        'muscleGroups': [tag], 'secondaryMuscleGroups': [], 'exerciseCategory': 'HEAVY_COMPOUND'}
        for index, tag in enumerate(('FRONT_CHEST', 'FRONT_QUADRICEPS', 'BACK_UPPER_BACK'))]
    profiles = [rules.execution_interference_profile([d], [2], [], requirements) for d in definitions]
    setups = [[setup_resource_profile(d, {'workSetTemplate': {'weight': load}})]
        for d, load in zip(definitions, (10, 20, 10))]
    order = rules.execution_order_indices([set()] * 3, [(0, index) for index in range(3)],
        requirements, [frozenset({'bar'})] * 3, profiles, setups)
    assert abs(order.index(0) - order.index(2)) == 1


def test_setup_order_keeps_known_physical_changes_when_loads_need_calibration():
    from workout_generator_pkg.generation_audit import executable_setup_evidence, setup_resource_profile
    definitions = [{'id': str(index), 'equipmentId': 'bar', 'exerciseType': 'WEIGHT',
        'requiredAccessoryEquipmentIds': ['bench'], 'reviewedExecution': {'setupConfiguration': [{
            'resourceId': 'bench', 'state': {'angle': angle}, 'source': 'https://example.test/setup',
            'basis': 'Controlled required-state fixture.'}]}}
        for index, angle in enumerate((0, 45, 0))]
    sources = [{'definition_id': definition['id'], 'numWorkSets': 2,
        'requiresLoadCalibration': True, 'workSetTemplate': {'weight': 0}}
        for definition in definitions]
    setups = [[setup_resource_profile(definition, source)]
        for definition, source in zip(definitions, sources, strict=True)]
    lookup = {definition['id']: definition for definition in definitions}
    order = rules.execution_order_indices([set()] * 3, [(0, index) for index in range(3)],
        {'objectiveOrder': ['setup_economy']}, setup_profiles=setups, setup_rounds=[2] * 3)
    original = executable_setup_evidence({'exercises': sources}, lookup)
    reordered = executable_setup_evidence({'exercises': [sources[index] for index in order]}, lookup)
    assert original['physicalRequiredChanges'] == 2 and reordered['physicalRequiredChanges'] == 1
    assert original['physicalPreparationCount'] == 4 and reordered['physicalPreparationCount'] == 3
    assert reordered['unknownPhysicalPreparationCount'] > 0


@pytest.mark.parametrize('setup_priority', ['after', 'before', 'goal'])
def test_local_setup_order_respects_approved_priority_relative_to_interference(setup_priority):
    from workout_generator_pkg.generation_audit import executable_setup_evidence, setup_resource_profile
    requirements = {'objectiveOrder': ['execution_order', 'setup_economy'],
        'orderingPreferences': {'protectionOrder': ['heavy_direct']}}
    if setup_priority == 'before':
        requirements['objectiveOrder'].reverse()
    if setup_priority == 'goal':
        requirements['objectiveTiers'] = [[{'metric': 'setup_economy', 'target': 0, 'scale': 1}]]
    definitions = [{'id': str(index), 'equipmentId': 'bar', 'exerciseType': 'WEIGHT',
        'exerciseCategory': 'HEAVY_COMPOUND' if index < 2 else 'MODERATE_COMPOUND',
        'muscleGroups': [muscle]} for index, muscle in enumerate([
            'FRONT_CHEST', 'FRONT_QUADRICEPS', 'FRONT_QUADRICEPS', 'FRONT_CHEST'])]
    sources = [{'definition_id': definition['id'], 'numWorkSets': 1, 'workSetTemplate': {'weight': load}}
        for definition, load in zip(definitions, (10, 20, 10, 20), strict=True)]
    profiles = [rules.execution_interference_profile([definition], [1], [], requirements)
        for definition in definitions]
    setups = [[setup_resource_profile(definition, source)]
        for definition, source in zip(definitions, sources, strict=True)]
    order = rules.execution_order_indices([set()] * 4, [(0, index) for index in range(4)],
        requirements, interference_profiles=profiles, setup_profiles=setups)
    evidence = executable_setup_evidence({'exercises': [sources[index] for index in order]},
        {definition['id']: definition for definition in definitions})
    assert evidence['physicalPreparationCount'] == (3 if setup_priority == 'after' else 2)
    assert rules.execution_interference_score(order, profiles, requirements)[0] == (
        0 if setup_priority == 'after' else 1)


def test_setup_sequence_uses_final_prescribed_load_and_preserves_unknowns():
    from workout_generator_pkg.generation_audit import setup_resource_profile
    definitions = [{'id': str(index), 'equipmentId': 'bar', 'exerciseType': 'WEIGHT'}
        for index in range(4)]
    sources = [{'numWorkSets': len(loads),
        'targetSetPrescriptions': [{'weight': load} for load in loads]}
        for loads in ([10], [20, 10], [20], [10])]
    setups = [[setup_resource_profile(definition, source)]
        for definition, source in zip(definitions, sources, strict=True)]
    arguments = ([set()] * 4, [(0, index) for index in range(4)], {'objectiveOrder': ['setup_economy']})

    assert rules.execution_order_indices(*arguments, setup_profiles=setups, setup_rounds=[1, 2, 1, 1]) == [2, 1, 0, 3]
    arguments[2]['orderingPreferences'] = {'phaseOrder': [
        ['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION'], ['CORE']]}
    assert rules.execution_order_indices([set()] * 4, [(0, 0), (0, 1), (1, 2), (0, 3)],
        arguments[2], setup_profiles=setups, setup_rounds=[1, 2, 1, 1])[-1] == 2
    sources[1]['requiresLoadCalibration'] = True
    setups[1] = [setup_resource_profile(definitions[1], sources[1])]
    assert not setups[1][0]['loadConfigurationKnown']
    assert rules.execution_order_indices(*arguments, setup_profiles=setups, setup_rounds=[1, 2, 1, 1]) == [2, 1, 0, 3]


def test_setup_order_counts_known_physical_changes_despite_unknown_configuration_dimensions():
    from workout_generator_pkg.generation_audit import executable_setup_evidence, setup_resource_profile
    definitions = [{'id': str(index), 'equipmentId': gear, 'exerciseType': 'WEIGHT'}
        for index, gear in enumerate(('bar', 'dumbbells', 'bar', 'bar'))]
    sources = [{'definition_id': definition['id'], 'numWorkSets': 1, 'workSetTemplate': {'weight': load}}
        for definition, load in zip(definitions, (20, 20, 40, 20), strict=True)]
    setups = [[setup_resource_profile(definition, source)]
        for definition, source in zip(definitions, sources, strict=True)]
    arguments = ([set()] * 4, [(0, index) for index in range(4)], {'objectiveOrder': ['setup_economy']})
    lookup = {definition['id']: definition for definition in definitions}

    order = rules.execution_order_indices(*arguments, setup_profiles=setups)
    original = executable_setup_evidence({'exercises': sources}, lookup)
    reordered = executable_setup_evidence({'exercises': [sources[index] for index in order]}, lookup)

    assert original['physicalPreparationCount'] == 4
    assert reordered['physicalPreparationCount'] == 3
    assert reordered['unknownConfigurationTransitions'] > 0
    assert reordered['unknownTransitions'] == 0
    for index in (1, 2):
        definitions[index]['equipmentId'] = None
        setups[index] = [setup_resource_profile(definitions[index], sources[index])]
    assert all(profile['loadConfigurationKnown'] for block in setups for profile in block)
    assert sorted(rules.execution_order_indices(*arguments, setup_profiles=setups)) == [0, 1, 2, 3]


def test_calibrated_loads_do_not_rank_ready_resource_accesses_as_preparations():
    from workout_generator_pkg.generation_audit import executable_setup_evidence, setup_resource_profile
    definitions = [{'id': str(index), 'equipmentId': gear, 'exerciseType': 'WEIGHT'}
        for index, gear in enumerate(('bar', 'dumbbells', 'bar', 'bar'))]
    sources = [{'definition_id': definition['id'], 'numWorkSets': 1,
        'requiresLoadCalibration': True, 'workSetTemplate': {'weight': 20}}
        for definition in definitions]
    setups = [[setup_resource_profile(definition, source)]
        for definition, source in zip(definitions, sources, strict=True)]
    lookup = {definition['id']: definition for definition in definitions}

    order = rules.execution_order_indices([set()] * 4, [(0, index) for index in range(4)],
        {'objectiveOrder': ['setup_economy']}, setup_profiles=setups)
    original = executable_setup_evidence({'exercises': sources}, lookup)
    reordered = executable_setup_evidence({'exercises': [sources[index] for index in order]}, lookup)

    assert order[0] == 0
    assert original['declaredResourceSwitches'] == 2
    assert original['resourceIdentityComplete'] is True
    assert reordered['declaredResourceSwitches'] == 2
    assert original['physicalPreparationCount'] == reordered['physicalPreparationCount'] == 2
    assert reordered['unknownConfigurationTransitions'] == 3
    assert reordered['unknownTransitions'] == 1
    assert all(item['configurationRelation'] == 'unknown_configuration' for item in reordered['transitions'])
    definitions[1]['equipmentId'] = None
    assert executable_setup_evidence({'exercises': sources}, lookup)['resourceIdentityComplete'] is False


def test_solver_prefers_splitting_lower_body_pair_at_the_same_approved_dose():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['workload_economy', 'movement_overlap', 'duration_economy']
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'quads': {'minimum': 2, 'maximum': 2}, 'hamstrings': {'minimum': 2, 'maximum': 2}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 2}]
    for definition, muscle in zip(equipment['exerciseDefinitions'], ('FRONT_QUADRICEPS', 'BACK_HAMSTRING')):
        definition.update(muscleGroups=[muscle], secondaryMuscleGroups=[])
    for index, item in enumerate(sessions[0]['exercises']):
        item.update(numWorkSets=2, superset='PAIR', restBetweenSetsSeconds=0,
            restAfterSupersetExerciseSeconds=15 if index == 0 else 90)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert all(item['superset'] is None and item['numWorkSets'] == 2
        for item in result['sessions'][0]['exercises'])
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'superset_lower_body_overlap')
    assert stage['value'] == 0
    assert not result['audit']['errors']
    from workout_generator_pkg.generation_audit import render_optimization_disclosure
    disclosure = render_optimization_disclosure(result['priorityExecution'])
    assert '0 weekly paired sets' in disclosure
    assert 'globally optimal sequence is not established' in disclosure


def test_primary_anatomy_does_not_establish_complete_execution_support():
    from workout_generator_pkg.generation_audit import session_interference_evidence
    base = {'id': 'row', 'exerciseCategory': 'HEAVY_COMPOUND',
        'muscleGroups': ['BACK_UPPER_BACK']}
    unknown = rules.execution_interference_profile([base], [2], [], {})
    assert unknown['primaryKnown'] is True
    assert 'known' not in unknown
    assert unknown['executionSupportEvidence'] == [
        {'definitionId': 'row', 'status': 'unknown', 'supportingMuscles': None}]
    documented = {**base, 'reviewedExecution': {'supportingMuscles': ['lowerBack'],
        'source': 'https://example.test/row', 'basis': 'Positive trunk-support evidence only.'}}
    known = rules.execution_interference_profile([documented], [2], [], {})
    assert known['supporting'] == {'lowerBack': 2}
    assert known['executionSupportEvidence'][0]['status'] == 'documented_non_exhaustive'
    assert unknown['primary'] == known['primary']
    assert 'lower bounds' in known['supportingCountsMeaning']
    source = {'numWorkSets': 2, 'satisfiesCoverage': []}
    summary = session_interference_evidence({'components': [{**base, 'type': 'Exercise', 'id': 'e',
        'name': 'Row', 'sets': []}]}, {'e': (source, base, {}, {'libraryDefinitionId': 'row'})},
        {'row': base}, {}, {}, {})
    assert summary['status'] == 'partial_execution_support_evidence'
    assert summary['blocks'][0]['libraryMuscleEvidence'] == 'primary_tags_available'
    assert summary['blocks'][0]['executionSupportEvidence'][0]['supportingMuscles'] is None
