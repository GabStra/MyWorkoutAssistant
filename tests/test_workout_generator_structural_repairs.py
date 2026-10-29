import copy

import pytest

from workout_generator_pkg import allocation, session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure
from test_workout_generator_parallel_planning import store_tool
from test_workout_generator_week_structure import prepared_case


def failed_preparation(arguments, messages, equipment, legacy_layout=False):
    with pytest.raises(PlanningInputError) as caught:
        if legacy_layout:
            allocation.allocate_prepared_sets(arguments['sessions'], {}, {'auditTargets': {}})
        else:
            session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments,
               planning_tool_failure('prepare_workout_sessions', caught.value, arguments))
    return session_drafting.preparation_repair_task(messages)


def test_group_repair_preserves_duplicate_occurrences_and_rejects_lost_or_reused_members():
    equipment, _, messages, arguments, _ = prepared_case()
    items = arguments['sessions'][0]['exercises']
    items.extend([copy.deepcopy(items[0]), copy.deepcopy(items[0])])
    for i, item in enumerate(items):
        item['superset'] = 'broken' if i != 1 else None
        item['numWorkSets'] = i + 3
        item['satisfiesCoverage'] = []
    task = failed_preparation(arguments, messages, equipment, legacy_layout=True)
    refs = list(task['blockRepair']['sessions']['SESSION_0']['occurrences'])
    update = {'sessionReference': 'SESSION_0', 'blocks': [
        {'exercises': [refs[2], refs[0]]}, {'exercises': [refs[1]]}]}
    request = {'basePreparationId': task['basePreparationId'], 'sessionBlocks': [update]}
    repaired = session_drafting.resolve_preparation_patch(request, messages)
    expected = [copy.deepcopy(items[i]) for i in (2, 0, 1)]
    for item, group in zip(expected, ['GROUP_0', 'GROUP_0', None]):
        item['superset'] = group
    assert repaired['sessions'][0]['exercises'] == expected
    assert repaired['sessions'][1:] == arguments['sessions'][1:]
    assert arguments['sessions'][0]['exercises'] == items
    for invalid in ([refs[0]], [refs[0], refs[0], refs[1]], ['/sessions/1/exercises/0']):
        update['blocks'] = [{'exercises': invalid}]
        with pytest.raises(PlanningInputError):
            session_drafting.resolve_preparation_patch(request, messages)


def test_selection_replacement_requires_explicit_roles_and_preserves_bounds():
    equipment, _, messages, arguments, _ = prepared_case()
    arguments['sessions'][0]['exercises'][0].update(
        definition_id='LIBRARY_999', allocationBounds={'minimum': 2, 'maximum': 2}, numWorkSets=2)
    task = failed_preparation(arguments, messages, equipment)
    member = {'replaces': '/sessions/0/exercises/0', 'definition_id': 'LIBRARY_0'}
    request = {'basePreparationId': task['basePreparationId'], 'sessionBlocks': [
        {'sessionReference': 'SESSION_0', 'replacements': [member]}]}
    schema = session_drafting.preparation_patch_tool(task)['function']['parameters']
    selection_fields = schema['properties']['sessionBlocks']['items']['oneOf']
    selection = next(item for item in selection_fields
                     if 'replacements' in item.get('properties', {}))
    replacement_schema = selection['properties']['replacements']['items']
    assert replacement_schema['properties']['replaces']['enum'] == ['/sessions/0/exercises/0']
    assert 'blocks' not in selection['properties']
    with pytest.raises(PlanningInputError):
        session_drafting.resolve_preparation_patch(request, messages)
    member['satisfiesCoverage'] = []
    repaired = session_drafting.resolve_preparation_patch(request, messages)
    assert repaired['sessions'][0]['exercises'][0]['allocationBounds'] == {'minimum': 2, 'maximum': 2}
    assert repaired['sessions'][0]['exercises'][0]['numWorkSets'] == 2
    assert repaired['sessions'][0]['exercises'][1:] == arguments['sessions'][0]['exercises'][1:]
    assert repaired['sessions'][1:] == arguments['sessions'][1:]
    no_op = copy.deepcopy(request)
    no_op['sessionBlocks'][0]['replacements'][0].update(definition_id='LIBRARY_999', satisfiesCoverage=[])
    with pytest.raises(PlanningInputError):
        session_drafting.resolve_preparation_patch(no_op, messages)
    with pytest.raises(PlanningInputError):
        session_drafting.resolve_preparation_patch({'basePreparationId': task['basePreparationId'],
            'sessionBlocks': [{'sessionReference': 'SESSION_0', 'replacements': []}]}, messages)
    with pytest.raises(PlanningInputError):
        session_drafting.resolve_preparation_patch({'basePreparationId': task['basePreparationId'],
            'patch': [{'op': 'replace', 'path': '/sessions/0/exercises', 'value': []}]}, messages)
