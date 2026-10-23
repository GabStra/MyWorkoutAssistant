import pytest

from workout_generator_pkg.planning_tools import (
    PlanningInputError,
    _structured_repair_coverage,
    repair_exercise_domain,
    uses_menu_selection,
)
from workout_generator_pkg.repair_capabilities import (
    repair_group_dimensions,
    repair_objective_dimensions,
)
from test_workout_generator_mixed_repair_composition import mixed_task


def _redistribution_task():
    current = {'workouts': [
        {'exercises': [{'definition_id': 'LIBRARY_0', 'numWorkSets': 4}]},
        {'exercises': [{'definition_id': 'LIBRARY_0', 'numWorkSets': 4}]},
    ]}
    task = {
        'findingsAssessment': {'groups': [{
            'findingIndexes': [0],
            'disposition': 'repair',
            'repairDimensions': [],
            'repairObjectives': [{
                'kind': 'redistribute_work',
                'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'],
                'minimumSessions': 2,
            }],
        }]},
        'reviewFindings': [{'draftPath': '/audit'}],
        'currentDraft': current,
    }
    return current, task


def test_redistribution_objective_derives_only_its_code_owned_operation_scope():
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}
    group = {'repairDimensions': [], 'repairObjectives': [objective]}

    assert repair_objective_dimensions(objective) == {'exercise_selection', 'ordering'}
    assert repair_group_dimensions(group) == {'exercise_selection', 'ordering'}
    assert 'prescription' not in repair_group_dimensions(group)
    assert 'session_timing' not in repair_group_dimensions(group)


def test_redistribution_objective_enables_menu_selection_without_model_authored_dimensions():
    _, task = mixed_task()
    group = task['findingsAssessment']['groups'][0]
    group['repairDimensions'] = []

    domain = repair_exercise_domain(task)

    assert domain['protected'] == ['EXERCISE_0', 'EXERCISE_2']
    assert domain['editable'] == ['EXERCISE_1']
    assert uses_menu_selection(task, domain=domain)


def test_objective_scope_accepts_its_compiled_placement_but_not_arbitrary_edits():
    current, task = _redistribution_task()
    task['_compiledRepairOperationRefs'] = [['EXERCISE_0', 'WORKOUT_0', 'WORKOUT_1']]
    placement = {
        'addressedFindingIndexes': [0],
        'patch': [{'op': 'move', 'from': '/workouts/0/exercises/0', 'path': '/workouts/1/exercises/1'}],
    }

    _structured_repair_coverage(placement, task, current)

    task['_compiledRepairOperationRefs'] = [['EXERCISE_9', 'WORKOUT_0']]
    unrelated = {
        'addressedFindingIndexes': [0],
        'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/definition_id', 'value': 'LIBRARY_1'}],
    }
    with pytest.raises(PlanningInputError, match='matching structured field'):
        _structured_repair_coverage(unrelated, task, current)

    task['_compiledRepairOperationRefs'] = [['EXERCISE_0', 'WORKOUT_0']]
    prescription_edit = {
        'addressedFindingIndexes': [0],
        'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3}],
    }
    with pytest.raises(PlanningInputError, match='matching structured field'):
        _structured_repair_coverage(prescription_edit, task, current)
