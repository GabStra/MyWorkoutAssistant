from copy import deepcopy

import pytest

from exercise_motion_pkg import bake_and_rank as bake


def parent_motion():
    return {'fps': 30., 'jointNames': ['root'], 'rootJoint': 'root', 'frames': [
        {'timeSec': i / 30., 'sourceFrameIndex': 270 + i, 'sourceTimeSec': 9. + i / 30.,
         'joints': {'root': [0., 1., 0.]}} for i in range(10)]}


def skipped_cycle_report():
    return {'sourceCyclePreflight': [
        {'passed': True, 'selection': {'startFrame': 2, 'stopFrameExclusive': 8}}]}


def test_queued_source_cycle_keeps_local_and_source_clocks_separate():
    parent = parent_motion()
    queued = bake.enqueue_unattempted_preflight_source_cycle([], skipped_cycle_report(), parent['frames'])
    assert queued.loop['startTimeSec'] == pytest.approx(2 / 30.)
    assert queued.loop['endTimeSec'] == pytest.approx(7 / 30.)
    evidence = bake.cycle_selection_evidence(parent, queued.loop)
    assert evidence['cycleSelection']['sourceInterval']['startTimeSec'] == pytest.approx(9. + 2 / 30.)
    selected = deepcopy(parent)
    selected['frames'] = selected['frames'][2:8]
    for i, frame in enumerate(selected['frames']):
        frame['timeSec'] = i / 30.
    selected['loop'] = {'enabled': True, 'sourceStartFrame': 272, 'sourceEndFrame': 277,
                        'sourceStartTimeSec': 9. + 2 / 30., 'sourceEndTimeSec': 9. + 7 / 30.}
    state = bake.artifact_state_for_baked_payload(
        selected, contract=None, selection_class=bake.CYCLE_SELECTION, selection_evidence=evidence)
    assert state['lineageComplete']


def test_queued_source_cycle_does_not_substitute_source_time_for_missing_local_time():
    frames = parent_motion()['frames']
    frames[2].pop('timeSec')
    assert bake.enqueue_unattempted_preflight_source_cycle([], skipped_cycle_report(), frames) is None
