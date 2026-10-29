import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_action_evidence import action_pose_grounding, overhead_reach_samples


def test_articulation_intervals_preserve_timing_and_do_not_bridge_occlusion():
    import math
    from exercise_motion_pkg.source_action_evidence import articulation_event_intervals
    source = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 640, 'imageHeight': 640, 'frames': []}
    for i, degrees in enumerate([170, 150, 100, 60, 100, 150, 170]):
        angle = math.radians(degrees)
        joints = {'left_shoulder': [.5, .4], 'left_elbow': [.5, .5],
                  'left_wrist': [.5 + .1 * math.sin(angle), .5 - .1 * math.cos(angle)]}
        source['frames'].append({'sourceTimeSec': i / 10, 'joints': joints,
                                 'jointConfidence': {name: .99 for name in joints}})
    intervals = articulation_event_intervals(source)
    assert any(row['times'] == [0., .3, .6] for row in intervals)
    assert any(row['times'][0] == 0. and row['times'][-1] == .3 for row in intervals)
    assert any(row['times'][0] == .3 and row['times'][-1] == .6 for row in intervals)
    assert next(row for row in intervals if row['times'] == [0., .3, .6])['sampleTimes'] == [i / 10 for i in range(7)]
    for frame in source['frames']:
        frame['joints'] = {name: [1 - point[1], point[0]] for name, point in frame['joints'].items()}
    assert articulation_event_intervals(source) == intervals
    source['frames'][3]['jointConfidence']['left_elbow'] = .1
    assert not any(row['times'][0] < .3 < row['times'][-1] for row in articulation_event_intervals(source))
    assert articulation_event_intervals(None) == []


def test_event_labels_cannot_invent_sequence_order_or_reuse_a_compound_interval():
    from exercise_motion_pkg.source_action_evidence import ordered_event_coverage
    phases = [{'description': 'first'}, {'description': 'second'}]
    events = [{'id': 'a', 'times': [0., .5, 1.]}, {'id': 'b', 'times': [1., 1.5, 2.]}]
    assert ordered_event_coverage(phases, events, {'a': ['first'], 'b': ['second']}) == events
    assert ordered_event_coverage(phases, events, {'a': ['second'], 'b': ['first']}) == []
    assert ordered_event_coverage(phases, events, {'a': ['second'], 'b': ['first']},
                                  allow_cyclic_order=True) == events[::-1]
    assert ordered_event_coverage(phases, events, {'a': ['first', 'second']}) == []
    events[1]['times'][0] = .5
    assert ordered_event_coverage(phases, events, {'a': ['first'], 'b': ['second']}) == []


def test_generated_sequence_proposal_cannot_add_obligations_to_reviewed_definition():
    from exercise_motion_pkg.source_evidence import source_requirements
    contract = {'definingAction': 'Perform the reviewed action', 'completionMode': 'distinct_end_state',
                'requiredPhases': ['Invented entry', 'Invented action', 'Invented exit'],
                'motionContext': {'exerciseDefinition': {'definingAction': 'Perform the reviewed action'}}}
    assert not any(row['id'].startswith('phase_') for row in source_requirements(contract, []))
    contract['requiredPhasesAuthority'] = 'trusted'
    assert len([row for row in source_requirements(contract, []) if row['id'].startswith('phase_')]) == 3


def pose(overhead=True):
    joints = {'nose': [.5, .25, 0.], 'left_hip': [.45, .8, 0.], 'right_hip': [.55, .8, 0.]}
    for side, x in [('left', .4), ('right', .6)]:
        joints.update({f'{side}_shoulder': [x, .4, 0.],
                       f'{side}_elbow': [x, .2 if overhead else .6, 0.],
                       f'{side}_wrist': [x, .1 if overhead else .4, 0.]})
    return {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 640, 'imageHeight': 360,
            'frames': [{'sourceTimeSec': float(i), 'joints': joints,
                        'jointConfidence': {name: .99 for name in joints}} for i in range(3)]}


@pytest.mark.parametrize('fault', ['shoulder_height', 'cropped', 'unconfident', 'missing_confidence', 'nan'])
def test_uncertain_or_non_overhead_landmarks_cannot_corroborate_press(fault):
    source = pose(fault != 'shoulder_height')
    for frame in source['frames']:
        if fault == 'cropped': frame['joints']['nose'] = [.5, 0., 0.]
        if fault == 'unconfident': frame['jointConfidence']['nose'] = .1
        if fault == 'missing_confidence': frame.pop('jointConfidence')
        if fault == 'nan': frame['jointConfidence']['nose'] = float('nan')
    assert overhead_reach_samples(source)['status'] == 'unresolved'


def test_observed_overhead_reach_is_camera_roll_invariant_and_not_a_press_approval():
    source = pose()
    assert overhead_reach_samples(source)['status'] == 'corroborated'
    for frame in source['frames']:
        frame['joints'] = {name: [1 - point[1], point[0], 0.] for name, point in frame['joints'].items()}
    source['imageWidth'] = source['imageHeight'] = 640
    assert overhead_reach_samples(source)['status'] == 'corroborated'
    assert action_pose_grounding([{'id': 'phase_1', 'description': 'Finish with an overhead press'}], source)[
        'authority'] == 'necessary_observations_only_not_semantic_approval'


def test_an_overhead_event_elsewhere_cannot_support_wrong_citations():
    source = pose(False)
    source['frames'][-1] = pose()['frames'][-1]
    requirements = [{'id': 'phase_1', 'description': 'Finish with an overhead press'}]
    frames = [{'id': str(i), 'timestampSeconds': float(i)} for i in range(3)]
    claims = [{'requirementId': 'phase_1', 'verdict': 'supported', 'evidenceFrameIds': ['0', '1']}]
    assert not action_pose_grounding(requirements, source, frames=frames, observations=claims)['passed']
    claims[0]['evidenceFrameIds'] = ['1', '2']
    assert action_pose_grounding(requirements, source, frames=frames, observations=claims)['passed']


def sheet(tmp_path, name):
    directory = tmp_path / name
    directory.mkdir()
    image = directory / 'contact_sheet_01.jpg'
    image.write_bytes(b'fixture')
    import hashlib
    (directory / 'contact_sheet_evidence.json').write_text(json.dumps({'sheets': {image.name: {
        'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
        'frames': [{'number': i + 1, 'timestampSeconds': float(i)} for i in range(6)]}}}))
    return image


@pytest.mark.parametrize('missing_phase', [None, 'Second action', 'extra_identity'])
@pytest.mark.parametrize('measured_phase', [False, True])
def test_complex_source_reviews_each_phase_once_and_code_owns_completion(tmp_path, monkeypatch, missing_phase, measured_phase):
    uniform, motion = sheet(tmp_path, 'uniform'), sheet(tmp_path, 'motion')
    target = {'exerciseName': 'Sequence', 'definingAction': 'Execute the prescribed sequence',
              'completionMode': 'distinct_end_state', 'requiredPhases': ['First action', 'Second action', 'Third action'],
              'actionDefinitionAuthority': 'trusted', 'actionDefinitionStatus': 'defined',
              'requiredPhasesAuthority': 'trusted'}
    item = SimpleNamespace(exercise_name='Sequence', candidate_workspace=tmp_path, candidate={})
    monkeypatch.setattr(bake, 'final_output_source_video_window', lambda *a: None)
    monkeypatch.setattr(bake, 'final_output_motion_contact_sheets', lambda *a, **k: [motion])
    monkeypatch.setattr(bake, 'resolve_two_scale_exercise_motion_contract', lambda *a, **k: (target, None, None))
    monkeypatch.setattr(bake, 'validate_source_pose_endpoints_against_contract', lambda *a, **k: {})
    import exercise_motion_pkg.source_action_evidence as action_evidence
    # This fixture tests question ownership/caching; real geometry is replayed below.
    monkeypatch.setattr(action_evidence, 'event_action_completion', lambda *a: {'passed': True})
    events = [{'id': f'event_{i + 1}', 'times': [float(i * 2), i * 2 + .5, float(i * 2 + 1)],
               'tracks': ['fixture']} for i in range(3)]
    monkeypatch.setattr(action_evidence, 'articulation_event_intervals', lambda source: events)
    if measured_phase:
        target['requiredPhases'][-1] = 'Finish with an overhead press'
        source = pose(False)
        source['frames'] = [{**source['frames'][0], 'sourceTimeSec': float(i)} for i in range(6)]
        source['frames'][-1] = {**pose()['frames'][0], 'sourceTimeSec': 5.0}
        monkeypatch.setattr(bake, 'load_verified_source_pose_reference', lambda *a: source)
    def extract(video, times, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = [output_dir / f'raw-{i}.jpg' for i in range(len(times))]
        for path in paths: path.write_bytes(str(times).encode())
        return paths
    monkeypatch.setattr(bake, 'source_review_sample_frames', extract)
    calls = []
    def caption(**kwargs):
        if 'observedActions' in kwargs['response_schema']['properties']:
            index = int(kwargs['frame_paths'][0].parent.name.removeprefix('event_')) - 1
            label = target['requiredPhases'][index]
            calls.append([label])
            if missing_phase == 'extra_identity' and index == 1:
                return json.dumps({'observedActions': [label], 'unresolved': False, 'requirement': label})
            return json.dumps({'observedActions': [] if label == missing_phase else [label],
                               'unresolved': label == missing_phase})
        assert 'requirement' not in kwargs['response_schema']['properties']
        assert 'observations' not in kwargs['response_schema']['properties']
        assert 'Reviewed target action context:' in kwargs['prompt']
        assert target['definingAction'] in kwargs['prompt']
        supplied = json.loads(kwargs['prompt'].split('Requirements: ', 1)[1].split('\nFrame inventory:', 1)[0])
        labels = list(dict.fromkeys(row['description'] for row in supplied))
        calls.append(labels)
        observations = []
        for label in labels:
            if label in target['requiredPhases']:
                index = target['requiredPhases'].index(label)
                ids = [f'uniform:{index * 2 + 1}', f'uniform:{index * 2 + 2}']
            else:
                ids = [f'uniform:{i}' for i in range(1, 7)] if label.startswith('Uniformly') else ['uniform:1', 'uniform:6']
            observations.append({'requirement': label, 'verdict': 'unresolved' if label == missing_phase else 'supported',
                                 'evidenceFrameIds': [] if label == missing_phase else ids})
        assert len(observations) == 1
        answer = {key: value for key, value in observations[0].items() if key != 'requirement'}
        if missing_phase == 'extra_identity' and labels == ['Second action']:
            answer['requirement'] = 'Second action'
        return json.dumps(answer)
    result = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
        output_dir=tmp_path / 'review', caption_images=caption, exercise_motion_contract=target)
    assert calls[1:] == [[phase] for phase in target['requiredPhases']]
    assert target['definingAction'] not in calls[0]
    assert len(calls) == 4
    assert result['passed'] is (missing_phase is None)
    assert result['gates']['structuredEvidence']['correction']['completionAuthority'] == (
        'ordered_measured_intervals_with_observed_actions')
    if missing_phase in (None, 'Second action') and not measured_phase:
        # Losing only the aggregate receipt must reuse the independent decisions.
        video = tmp_path / 'input.mp4'
        video.write_bytes(b'unchanged-source')
        monkeypatch.setattr(bake, 'final_output_source_video_window', lambda *a: (
            video, bake.DetectionWindow(index=0, start_seconds=0., end_seconds=6.)))
        class Reviewer:
            settings = SimpleNamespace(llama_cpp_model='fixture-model')
            def caption_images(self, **kwargs): return caption(**kwargs)
        reviewer = Reviewer()
        first = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
            output_dir=tmp_path / 'cached-review', caption_images=reviewer.caption_images,
            exercise_motion_contract=target)
        assert first['passed'] is (missing_phase is None)
        Path(first['sourceReviewCache']['checkpoint']).unlink(missing_ok=True)
        count = len(calls)
        replayed = bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=[uniform],
            output_dir=tmp_path / 'cached-review', caption_images=reviewer.caption_images,
            exercise_motion_contract=target)
        assert replayed['passed'] is (missing_phase is None)
        assert len(calls) == count


def test_retained_event_false_labels_are_filtered_before_sequence_selection():
    from exercise_motion_pkg.source_action_evidence import (
        articulation_event_intervals, event_action_completion, ordered_event_coverage, event_review_sample_times)
    root = Path('build/exercise_motion/diagnostics/source-phase-grounding-20261026/next-validation/complete-man-maker')
    receipt = root / 'live-review-policy11-initial.json'
    if not receipt.is_file(): pytest.skip('retained live failure unavailable')
    retained = json.loads(receipt.read_text())['result']
    source = json.loads((root / 'pose.json').read_text())
    phases = [row for row in retained['requirements'] if row['id'].startswith('phase_')]
    events = articulation_event_intervals(source)
    checks = {event['id']: {phase['description']: event_action_completion(phase['description'], source, event)
                          for phase in phases} for event in events}
    assert not checks['event_1'][phases[0]['description']]['passed']
    assert not checks['event_14'][phases[1]['description']]['passed']
    assert not checks['event_33'][phases[3]['description']]['passed']
    assert not checks['event_25'][phases[3]['description']]['passed']  # Folded jump is not an overhead finish.
    observed = retained['gates']['structuredEvidence']['correction']['eventQuestions']
    labels = {row['id']: [label for label in row['observedActions'] if checks[row['id']][label]['passed']]
              for row in observed}
    assert ordered_event_coverage(phases, events, labels) == []
    # Source-inspected positive intervals, not new model approval.
    positive_ids = ['event_4', 'event_17', 'event_36', 'event_45']
    for phase, event_id in zip(phases, positive_ids):
        assert checks[event_id][phase['description']]['passed']
        event = next(row for row in events if row['id'] == event_id)
        review_times = event_review_sample_times(event, checks[event_id][phase['description']])
        assert review_times[0] == event['times'][0] and review_times[-1] == event['times'][-1]
        assert set(review_times).issubset(event['sampleTimes'])
        assert all(time in review_times for witness in checks[event_id][phase['description']]['witnesses']
                   for time in witness['times'])
        labels[event_id] = [phase['description']]
    assert [event['id'] for event in ordered_event_coverage(phases, events, labels)] == positive_ids
    # A confident upper-arm excursion can survive an uncertain wrist without
    # inventing that wrist or lowering landmark confidence requirements.
    row_witnesses = checks['event_17'][phases[1]['description']]['witnesses']
    assert any(row['side'] == 'left' and row['track'] == 'upper_arm' for row in row_witnesses)
    assert event_action_completion('Unknown action', source, events[0])['reason'] == 'unsupported_action_completion'
    assert not event_action_completion('Push-up then row each side', source, events[-1])['passed']


def test_retained_man_maker_false_approval_is_blocked_before_model_replay(tmp_path, monkeypatch):
    workspace = Path('build/exercise_motion/workout-run-library/dumbbell-man-maker/selected')
    receipt = Path('build/exercise_motion/diagnostics/source-review-generalization-20261026/dumbbell_man_maker-raw-result.json')
    if not receipt.is_file(): pytest.skip('retained failing artifact is not available')
    retained = json.loads(receipt.read_text())
    video = workspace / 'dumbbell_man_maker_selected_input.mp4'
    target = retained['exerciseMotionContract']
    item = SimpleNamespace(exercise_name=target['exerciseName'], candidate_workspace=workspace,
                           candidate={}, source_review_video_path=video)
    monkeypatch.setattr(bake, 'final_output_source_video_window', lambda *a: None)
    monkeypatch.setattr(bake, 'final_output_motion_contact_sheets', lambda *a, **k: [Path(p) for p in retained['motionContactSheetPaths']])
    monkeypatch.setattr(bake, 'resolve_two_scale_exercise_motion_contract', lambda *a, **k: (target, None, None))
    def no_call(**kwargs): raise AssertionError('Missing independent observations must not reask the model')
    result = bake.validate_two_scale_source_with_caption_images(item,
        uniform_sheet_paths=[Path(p) for p in retained['uniformContactSheetPaths']],
        output_dir=tmp_path, caption_images=no_call, exercise_motion_contract=target)
    assert not result['passed']
    assert result['reviewStatus'] == 'incomplete'
    assert 'phase_4' in result['gates']['actionPoseEvidence']['unresolvedRequirementIds']
