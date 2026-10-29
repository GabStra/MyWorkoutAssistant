from workout_generator_pkg.joint_planning import (
    _constrain_first_block_order,
    _execution_order,
    _is_isolated_arm_calf_core,
)


def _definitions():
    return {
        'LIBRARY_ROW': {'exerciseCategory': 'HEAVY_COMPOUND',
                        'muscleGroups': ['BACK', 'FRONT_BICEPS']},
        'LIBRARY_CURL': {'exerciseCategory': 'ISOLATION',
                         'muscleGroups': ['FRONT_BICEPS']},
        'LIBRARY_CALF': {'exerciseCategory': 'ISOLATION',
                         'muscleGroups': ['FRONT_CALVES']},
    }


def _block(index, role, source_rank, isolated, definitions):
    definition_id = ('LIBRARY_CURL' if isolated else 'LIBRARY_ROW')
    return {
        'options': [index], 'first': 100 + index, 'sourceRank': source_rank,
        'recipe': {'roles': {role}, 'sourcePositions': [[0, index]],
                   'identity': [definition_id], 'isolatedArmCalfCore': isolated},
        'items': [{'definition_id': definition_id}],
    }


def _assert_milp_first_block_matches(blocks, requirements, expected_order):
    variables = []
    constraints = []

    def variable(upper=1, cost=0, domain_identity=None, lower=0, integer=True):
        index = 1000 + len(variables)
        variables.append({'index': index, 'domainIdentity': domain_identity})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((lower, upper, intercept, coefficients))

    selected_coefficients = [{block['options'][0]: 1} for block in blocks]
    _constrain_first_block_order(blocks, selected_coefficients, requirements,
                                 variable, constraint, 0)

    selected = {block['options'][0] for block in blocks}
    predecessors = {index: set() for index in range(len(blocks))}
    for before in range(len(blocks)):
        for after in range(len(blocks)):
            if before != after and any(
                    rule['kind'] == 'order'
                    and rule['before'] in blocks[before]['recipe']['roles']
                    and rule['after'] in blocks[after]['recipe']['roles']
                    for rule in requirements.get('executionRules', [])):
                predecessors[after].add(before)
    ready = {index: int(index in selected and not (predecessors[index] & selected))
             for index in range(len(blocks))}
    values = {index: int(index in selected) for index in selected}
    ready_variables = [entry['index'] for entry in variables
                       if entry['domainIdentity']['kind'] == 'first_block_ready']
    values.update({var: ready[index] for index, var in enumerate(ready_variables)})

    prefix = 0
    prefix_variables = [entry['index'] for entry in variables
                        if entry['domainIdentity']['kind'] == 'first_block_prefix']
    prefix_order = sorted(range(len(blocks)), key=lambda index: (
        blocks[index]['recipe']['isolatedArmCalfCore'], blocks[index]['sourceRank'], index))
    for var, index in zip(prefix_variables, prefix_order[:-1]):
        prefix = int(bool(prefix or ready[index]))
        values[var] = prefix
    first_index = expected_order[0]
    values.update({block['first']: int(index == first_index)
                   for index, block in enumerate(blocks)})

    for lower, upper, intercept, coefficients in constraints:
        actual = intercept + sum(coefficient * values.get(index, 0)
                                 for index, coefficient in coefficients.items())
        assert lower - 1e-9 <= actual <= upper + 1e-9


def test_only_isolated_arm_calf_or_core_definitions_are_accessories():
    definitions = _definitions()
    assert _is_isolated_arm_calf_core(
        [{'definition_id': 'LIBRARY_CURL'}], definitions)
    assert not _is_isolated_arm_calf_core(
        [{'definition_id': 'LIBRARY_ROW'}], definitions)
    # A mixed superset stays a movement block when any member is not an accessory.
    assert not _is_isolated_arm_calf_core([
        {'definition_id': 'LIBRARY_CURL'}, {'definition_id': 'LIBRARY_ROW'}], definitions)


def test_ready_main_blocks_precede_accessories_but_keep_source_order_within_class():
    blocks = [
        _block(0, 'elbow_flexion', 0, True, _definitions()),
        _block(1, 'horizontal_pull', 2, False, _definitions()),
        _block(2, 'horizontal_push', 1, False, _definitions()),
    ]
    assert _execution_order(blocks, [1, 1, 1], {}) == [2, 1, 0]


def test_explicit_source_edge_overrides_default_in_topological_and_milp_order():
    blocks = [
        _block(0, 'elbow_flexion', 0, True, _definitions()),
        _block(1, 'horizontal_pull', 1, False, _definitions()),
    ]
    requirements = {'executionRules': [
        {'kind': 'order', 'before': 'elbow_flexion', 'after': 'horizontal_pull'}]}
    expected = _execution_order(blocks, [1, 1], requirements)
    assert expected == [0, 1]
    _assert_milp_first_block_matches(blocks, requirements, expected)


def test_milp_first_block_default_prefers_movement_before_isolated_accessory():
    blocks = [
        _block(0, 'elbow_flexion', 0, True, _definitions()),
        _block(1, 'horizontal_pull', 1, False, _definitions()),
    ]
    expected = _execution_order(blocks, [1, 1], {})
    assert expected == [1, 0]
    _assert_milp_first_block_matches(blocks, {'executionRules': []}, expected)
