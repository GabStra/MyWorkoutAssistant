import json
from pathlib import Path

import numpy as np
import pytest

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
    assert 'sourceWrapOverLimitRatio' in best
    result = slice_loop_cycle(payload, best)
    assert len(result['frames']) == result['frameCount'] == 60
    assert result['loop']['enabled']
    assert 'restartFadeMillis' not in result['loop']
    assert result['frames'][0]['timeSec'] == 0
    assert result['frames'][-1]['frameIndex'] == 59
    assert result['frames'][0]['sourceFrameIndex'] == best['startFrame']+200
    assert payload['frameCount'] == 100


def test_rank_loop_cycles_prefers_lower_source_wrap_ratio():
    payload = repeated_motion()
    # Corrupt one mid-clip wrap so a worse window exists; ranking must still
    # surface a low sourceWrapOverLimitRatio first when both are complete.
    choices = rank_loop_cycles(payload, max_candidates=3)
    assert choices
    wraps = [c['sourceWrapOverLimitRatio'] for c in choices]
    assert wraps == sorted(wraps)


@pytest.mark.parametrize('status,valid_geometry', [('confirmed', True), ('unknown', True), ('confirmed', False)])
def test_cycle_selection_uses_confirmed_support_across_landmark_gaps(status, valid_geometry):
    payload = repeated_motion()
    feet = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    for frame in payload['frames']:
        for name in feet:
            frame['joints'][name] = list(payload['frames'][0]['joints'][name])
    baseline = rank_loop_cycles(payload)
    assert baseline
    payload['sourceFootSupportEvidence'] = {'contacts': [
        {'jointName': name, 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startRatio': 0., 'endRatio': .49} for name in ['left_foot', 'right_foot']]}
    fragmented = rank_loop_cycles(payload)
    assert fragmented != baseline
    payload['sourceFootSupportEvidence']['bodySupport'] = {
        'required': True, 'status': status, 'stationaryJoints': feet,
        'coplanarGroups': [{'joints': ['left_foot', 'right_foot'],
                            'normal': [0, 1, 0] if valid_geometry else [0, 0, 0]}]}
    choices = rank_loop_cycles(payload)
    assert choices == (baseline if status == 'confirmed' and valid_geometry else fragmented)


def test_declared_phase_range_ignores_incidental_drift_but_keeps_endpoint_gate():
    payload = repeated_motion()
    signal = [.15*np.sin(i*2*np.pi/60) for i in range(100)]
    for i, frame in enumerate(payload['frames']):
        frame['joints']['head'][2] += i*.002
    # One-rep range is judged against peer cycles, not whole-clip drift. Mild
    # incidental head travel must not empty geometric proposals.
    assert rank_loop_cycles(payload, endpoint_correction_ratio=.08)
    choices = rank_loop_cycles(payload, endpoint_correction_ratio=.08, phase_values=signal)
    assert choices
    assert choices[0]['minimumRetainedRangeRatio'] >= .9
    for i, frame in enumerate(payload['frames']):
        for point in frame['joints'].values():
            point[0] += i*.03
    assert not rank_loop_cycles(payload, endpoint_correction_ratio=.08, phase_values=signal)


def test_exclusive_seam_frame_is_included_in_phase_completeness():
    """Regression: completeness on [start:stop) missed the return sample at stop.

    Build a track that is low at the seam frames and high only in the open
    interior. Without including the exclusive stop sample, the open slice is
    ['low','high'] and complete_repetition rejects a real one-rep return.
    """
    from exercise_motion_pkg.repetition_phase import complete_repetition, major_phase_sequence

    values = np.full(40, 0.5)
    values[0] = values[30] = 0.0
    values[10:20] = 1.0
    assert major_phase_sequence(values[0:30].tolist()) == ['low', 'high']
    assert not complete_repetition(values[0:30].tolist())[0]
    assert major_phase_sequence(values[0:31].tolist()) == ['low', 'high', 'low']
    assert complete_repetition(values[0:31].tolist())[0]

    payload = repeated_motion()
    diagnostics = {}
    choices = rank_loop_cycles(payload, max_candidates=3, diagnostics=diagnostics)
    assert choices
    assert diagnostics['counts']['completePhase'] > 0
    assert diagnostics['counts']['rangePreserved'] > 0


def test_phase_direction_keeps_apex_return_but_rejects_opposite_phase():
    """Complete returns survive opposite apex velocity; incomplete crossings do not."""
    payload = repeated_motion()
    diagnostics = {}
    choices = rank_loop_cycles(payload, max_candidates=3, diagnostics=diagnostics)
    assert choices
    assert diagnostics['counts']['completePhase'] > 0
    assert diagnostics['counts']['directionCompatible'] > 0

    # Incomplete opposite-velocity crossing: short rise then fall without a
    # full return — must not become a ranked cycle.
    payload = repeated_motion()
    names = payload['jointNames']
    base = {name: list(payload['frames'][0]['joints'][name]) for name in names}
    for i, frame in enumerate(payload['frames']):
        for name in names:
            frame['joints'][name] = list(base[name])
        height = 0.004 * i if i <= 20 else 0.004 * (40 - i) if i <= 40 else 0.0
        frame['joints']['right_wrist'][1] = base['right_wrist'][1] + max(height, 0.0)
        frame['joints']['left_wrist'][1] = base['left_wrist'][1] + max(height, 0.0)
    diag = {}
    crossed = rank_loop_cycles(payload, max_candidates=5, diagnostics=diag)
    for choice in crossed:
        assert not (0 <= choice['startFrame'] <= 10
                    and 25 <= choice['stopFrameExclusive'] <= 45)


def test_rank_loop_cycles_rejects_unpolishable_source_wrap():
    from exercise_motion_pkg.loop_seam import MAX_RANKED_SOURCE_WRAP_RATIO
    payload = repeated_motion()
    # Inject a huge seam hitch into one otherwise-complete window.
    for name, point in payload['frames'][59]['joints'].items():
        payload['frames'][59]['joints'][name] = [point[0] + 0.25, point[1], point[2]]
    diagnostics = {}
    choices = rank_loop_cycles(payload, max_candidates=5, diagnostics=diagnostics)
    assert diagnostics['counts'].get('wrapFeasible', 0) <= diagnostics['counts']['directionCompatible']
    assert all(c['sourceWrapOverLimitRatio'] <= MAX_RANKED_SOURCE_WRAP_RATIO + 1e-9 for c in choices)


def test_contact_intervals_are_clipped_rebased_and_not_duplicated():
    payload = repeated_motion()
    payload['sourceFootSupportEvidence'] = {
        'supportContacts': [{'jointName': 'left_foot', 'contactState': 'toe_only',
                             'startFrame': 10, 'endFrame': 30}],
        'contacts': [{'jointName': 'right_foot', 'contactState': 'toe_only',
                      'startRatio': 60/99, 'endRatio': 90/99}],
        'footContactCandidates': [{'jointName': 'left_ankle', 'startFrame': 10, 'endFrame': 90}],
        'footPatchEvidence': {'feet': {'left': {'states': ['airborne']*20+['unknown']*60+['airborne']*20}}},
    }
    original = contact_mask(payload, payload['jointNames'], 100)
    result = slice_loop_cycle(payload, {'startFrame': 20, 'stopFrameExclusive': 80})
    np.testing.assert_array_equal(contact_mask(result, payload['jointNames'], 60), original[20:80])
    assert 'supportContacts' not in result['sourceFootSupportEvidence']
    candidate = result['sourceFootSupportEvidence']['footContactCandidates'][0]
    assert (candidate['startRatio'], candidate['endRatio']) == (0., 1.)
    assert result['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left']['states'] == ['unknown']*60


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


def test_small_pause_oscillations_cannot_replace_the_observed_excursion():
    payload = repeated_motion()
    base = payload['frames'][0]['joints']
    # A one-way movement followed by tiny tracking oscillations at the hold.
    # The hold supplies matching endpoints and a locally complete phase, but
    # none of those windows represents the movement's actual excursion.
    for i, frame in enumerate(payload['frames']):
        height = .4 * min(i / 40., 1.) + (.003 * np.sin((i - 40) * 2 * np.pi / 20) if i > 40 else 0.)
        frame['joints'] = {name: [p[0], p[1] + height, p[2]] for name, p in base.items()}
    diagnostics = {}
    assert not rank_loop_cycles(payload, diagnostics=diagnostics)
    assert diagnostics['counts']['wrapFeasible'] > 0
    assert diagnostics['counts']['rangePreserved'] == 0


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
    assert 1 <= len(seen)
    assert len(seen[0]['frames']) == len(payload['frames'])
    assert all(len(p['frames']) < len(payload['frames']) for p in seen[1:])
    assert len(payload['frames']) == 100
