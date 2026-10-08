from scripts.replay_controlled_motion_fit import _prepare_payload


def test_repeat_captured_cycle_restores_source_preflight_for_fit_budgeting():
    selection = {'startFrame': 1, 'stopFrameExclusive': 8, 'score': 1.}
    source_preflight = [{'passed': True, 'selection': selection}]
    payload = {
        'frames': [{'timeSec': index / 30.} for index in range(8)],
        'fps': 30.,
        'controlledMotionFit': {
            'cycleSelectionAttempts': [{'selection': selection}],
            'sourceCyclePreflight': source_preflight,
        },
    }

    replay_payload, captured = _prepare_payload(payload, captured_cycle=True)

    assert captured == selection
    assert replay_payload['sourceCyclePreflight'] == source_preflight
