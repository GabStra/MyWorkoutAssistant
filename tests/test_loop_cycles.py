import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg.loop_cycles import rank_loop_cycles, slice_loop_cycle
from exercise_motion_pkg.sequence_stabilization import contact_mask


def repeated_motion():
    stance = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(stance['joints'])
    points = np.tile(np.asarray(list(stance['joints'].values())), (100, 1, 1))
    # More than one period, with different poses at the original endpoints.
    phase = np.arange(100)*2*np.pi/60
    points[:, :, 1] += (.15*np.sin(phase))[:, None]
    return {'fps': 30, 'jointNames': names, 'frameCount': len(points),
            'frames': [{'frameIndex': i, 'sourceFrameIndex': i+200,
                        'sourceTimeSec': (i+200)/30, 'timeSec': i/30,
                        'joints': dict(zip(names, p.tolist()))} for i, p in enumerate(points)]}


def test_cycle_preserves_excursion_and_direction_without_duplicate_endpoint():
    payload = repeated_motion()
    choices = rank_loop_cycles(payload)
    assert choices
    best = choices[0]
    assert best['stopFrameExclusive']-best['startFrame'] == 60
    assert best['minimumRetainedRangeRatio'] > .99
    result = slice_loop_cycle(payload, best)
    assert len(result['frames']) == result['frameCount'] == 60
    assert result['loop']['enabled']
    assert 'restartFadeMillis' not in result['loop']
    assert result['frames'][0]['timeSec'] == 0
    assert result['frames'][-1]['frameIndex'] == 59
    assert result['frames'][0]['sourceFrameIndex'] == best['startFrame']+200
    assert payload['frameCount'] == 100


def test_contact_intervals_are_clipped_rebased_and_not_duplicated():
    payload = repeated_motion()
    payload['sourceFootSupportEvidence'] = {
        'supportContacts': [{'jointName': 'left_foot', 'contactState': 'toe_only',
                             'startFrame': 10, 'endFrame': 30}],
        'contacts': [{'jointName': 'right_foot', 'contactState': 'toe_only',
                      'startRatio': 60/99, 'endRatio': 90/99}],
    }
    original = contact_mask(payload, payload['jointNames'], 100)
    result = slice_loop_cycle(payload, {'startFrame': 20, 'stopFrameExclusive': 80})
    np.testing.assert_array_equal(contact_mask(result, payload['jointNames'], 60), original[20:80])
    assert 'supportContacts' not in result['sourceFootSupportEvidence']


def test_net_travel_and_stationary_holds_are_not_misidentified_as_cycles():
    payload = repeated_motion()
    for i, frame in enumerate(payload['frames']):
        for point in frame['joints'].values():
            point[0] += i*.03
    assert not rank_loop_cycles(payload)
    payload = repeated_motion()
    for frame in payload['frames']:
        frame['joints'] = payload['frames'][0]['joints']
    assert not rank_loop_cycles(payload)


def test_cycle_ranking_is_invariant_to_world_rotation_and_translation():
    payload = repeated_motion()
    expected = rank_loop_cycles(payload, max_candidates=1)[0]
    # Yaw leaves the physical floor normal unchanged.
    angle = .73
    rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
                         [-np.sin(angle), 0, np.cos(angle)]])
    for frame in payload['frames']:
        frame['joints'] = {n: (rotation@p+[2., 0., -3.]).tolist() for n, p in frame['joints'].items()}
    actual = rank_loop_cycles(payload, max_candidates=1)[0]
    assert actual['stopFrameExclusive']-actual['startFrame'] == 60
    assert abs(actual['score']-expected['score']) < 1e-10


def test_failed_cycle_attempts_return_the_entire_original_payload(monkeypatch):
    from exercise_motion_pkg import controlled_motion
    payload = repeated_motion()
    payload['loop'] = {'enabled': True}
    seen = []

    def reject(candidate, **kwargs):
        seen.append(candidate)
        return candidate, {'applied': False, 'reason': 'anatomy_failed'}

    monkeypatch.setattr(controlled_motion, '_fit_controlled_motion', reject)
    result, report = controlled_motion.fit_controlled_motion(payload)
    assert result is payload
    assert not report['applied']
    assert report['reason'] == 'no_validated_loop_cycle'
    assert 1 <= len(seen) <= 3
    assert all(len(p['frames']) < len(payload['frames']) for p in seen)
    assert len(payload['frames']) == 100
