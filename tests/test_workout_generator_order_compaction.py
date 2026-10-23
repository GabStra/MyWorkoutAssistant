from workout_generator_pkg.joint_planning import _constrain_first_block_order, _execution_order
import pytest


def _ordering_model(blocks, rules=()):
    variables = []
    constraints = []

    def variable(upper=1, cost=0, domain_identity=None, lower=0, integer=True):
        index = 1000 + len(variables)
        variables.append({'index': index, 'upper': upper, 'lower': lower,
                          'integer': integer, 'domainIdentity': domain_identity})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((label, lower, upper, intercept, coefficients))

    selected_coefficients = [{block['options'][0]: 1} for block in blocks]
    _constrain_first_block_order(blocks, selected_coefficients,
        {'executionRules': list(rules)}, variable, constraint, 0)
    return variables, constraints


def _assert_model_accepts_order(blocks, variables, constraints, selected, first_order, rules=()):
    values = {index: int(index in selected) for block in blocks for index in block['options']}
    rank_order = sorted(range(len(blocks)), key=lambda index: (blocks[index]['sourceRank'], index))
    ready = {index: int(index in selected and all(
        predecessor not in selected for predecessor in _predecessors(blocks, index, rules)))
        for index in range(len(blocks))}
    prefix = 0
    prefix_values = []
    for index in rank_order[:-1]:
        prefix = int(bool(prefix or ready[index]))
        prefix_values.append(prefix)
    prefix_variables = [item['index'] for item in variables if item['domainIdentity']['kind'] == 'first_block_prefix']
    for variable_index, prefix_value in zip(prefix_variables, prefix_values):
        values[variable_index] = prefix_value
    ready_variables = [item['index'] for item in variables if item['domainIdentity']['kind'] == 'first_block_ready']
    for variable_index, block_index in zip(ready_variables, range(len(blocks))):
        values[variable_index] = ready[block_index]
    for block_index, block in enumerate(blocks):
        values[block['first']] = int(block_index == first_order[0])
    for _, lower, upper, intercept, coefficients in constraints:
        actual = intercept + sum(coefficient * values.get(index, 0) for index, coefficient in coefficients.items())
        assert lower - 1e-9 <= actual <= upper + 1e-9, (lower, upper, actual, coefficients, values)


def _predecessors(blocks, index, rules):
    return {before for before, block in enumerate(blocks) if before != index
            and any(rule['kind'] == 'order'
                    and rule['before'] in block['recipe']['roles']
                    and rule['after'] in blocks[index]['recipe']['roles']
                    for rule in rules)}


def _blocks(count):
    return [{'options': [index], 'first': 2 * count + index, 'sourceRank': count - index,
             'recipe': {'roles': {f'role-{index}'}, 'sourcePositions': [[0, index]],
                        'identity': [f'LIBRARY_{index}']}}
            for index in range(count)]


def test_source_order_encoding_grows_linearly_and_selects_earliest_ready_block():
    blocks = _blocks(40)
    variables, constraints = _ordering_model(blocks)
    source_rows = [row for row in constraints if row[0][0] == 'first_respects_source_order']
    assert len(source_rows) == 2 * len(blocks) - 1
    assert len(constraints) == 7 * len(blocks) - 5
    assert len(variables) == 2 * len(blocks) - 1
    assert len(source_rows) < len(blocks) * (len(blocks) - 1) // 2

    selected = {0, 7, 13, 39}
    _assert_model_accepts_order(blocks, variables, constraints, selected, [39, 13, 7, 0])


def test_approved_order_readiness_preserves_stable_topological_first_block():
    blocks = _blocks(4)
    blocks[0]['recipe']['roles'] = {'after'}
    blocks[1]['recipe']['roles'] = {'free'}
    blocks[2]['recipe']['roles'] = {'before'}
    blocks[3]['recipe']['roles'] = {'after'}
    rules = [{'kind': 'order', 'before': 'before', 'after': 'after'}]
    variables, constraints = _ordering_model(blocks, rules)
    selected = {0, 1, 2, 3}
    chosen = [0] * (2 * len(blocks))
    for index in selected:
        chosen[index] = 1
    expected = _execution_order(blocks, chosen, {'executionRules': rules})
    _assert_model_accepts_order(blocks, variables, constraints, selected, expected, rules)


def test_compact_ordering_matches_constructor_for_every_small_selection():
    blocks = _blocks(4)
    blocks[0]['recipe']['roles'] = {'after'}
    blocks[2]['recipe']['roles'] = {'before'}
    for rules in ([], [{'kind': 'order', 'before': 'before', 'after': 'after'}]):
        variables, constraints = _ordering_model(blocks, rules)
        for mask in range(1, 1 << len(blocks)):
            selected = {index for index in range(len(blocks)) if mask & (1 << index)}
            chosen = [int(index in selected) for index in range(2 * len(blocks))]
            expected = _execution_order(blocks, chosen, {'executionRules': rules})
            _assert_model_accepts_order(blocks, variables, constraints, selected, expected, rules)
            for wrong in selected - {expected[0]}:
                with pytest.raises(AssertionError):
                    _assert_model_accepts_order(blocks, variables, constraints, selected, [wrong], rules)


def test_compact_ordering_keeps_first_block_setup_deduction_exact():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from workout_generator_pkg import joint_planning

    results = []
    for rules in ([], [{'kind': 'order', 'before': 'second', 'after': 'first'}]):
        equipment, requirements, sessions = two_recipe_order_case()
        for day in sessions:
            for item in day['exercises']:
                item.pop('placementNotes', None)
        requirements['auditTargets']['maximumSessionSeconds'] = 1700
        requirements['executionRules'] = rules
        result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
        assert result['feasible'], result
        results.append(result)

    source_order, approved_order = results
    assert [item['definition_id'] for item in source_order['sessions'][0]['exercises']] == [
        'LIBRARY_0', 'LIBRARY_1']
    assert [item['definition_id'] for item in approved_order['sessions'][0]['exercises']] == [
        'LIBRARY_1', 'LIBRARY_0']
    assert source_order['audit']['workouts'][0]['estimatedSeconds'] == 1620
    assert approved_order['audit']['workouts'][0]['estimatedSeconds'] == 1320
    assert source_order['audit']['workouts'][0]['estimatedSeconds'] - approved_order[
        'audit']['workouts'][0]['estimatedSeconds'] == 300
