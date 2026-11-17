import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace


def test_body_support_cache_reuses_only_matching_review_identity(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from exercise_motion_pkg import body_support_observation as module
    from exercise_motion_pkg import review_questions

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source bytes for review identity')

    class Capture:
        def get(self, _property):
            return 5

        def set(self, *_args):
            pass

        def read(self):
            return True, np.zeros((16, 16, 3), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, 'VideoCapture', lambda _path: Capture())

    class Reviewer:
        def __init__(self):
            self.settings = SimpleNamespace(llama_cpp_model='model-a')
            self.calls = 0

        def caption(self, **_kwargs):
            self.calls += 1
            return json.dumps({'leftFoot': 'stationary_full_sole',
                               'leftFootSurface': 'ground'})

    reviewer = Reviewer()
    first = module.observe_body_support(video, reviewer.caption, tmp_path)
    assert first['status'] == 'observed'
    assert first['reviewIdentity']['llama_cpp_model'] == 'model-a'
    assert module.observe_body_support(video, reviewer.caption, tmp_path) == first
    assert reviewer.calls == 1

    reviewer.settings = SimpleNamespace(llama_cpp_model='model-b')
    second = module.observe_body_support(video, reviewer.caption, tmp_path)
    assert reviewer.calls == 2
    assert second['reviewIdentity']['llama_cpp_model'] == 'model-b'

    policy = review_questions.STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION
    monkeypatch.setattr(review_questions, 'STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION',
                        policy + 1)
    third = module.observe_body_support(video, reviewer.caption, tmp_path)
    assert reviewer.calls == 3
    assert third['reviewIdentity']['structuredResponsePromptPolicyVersion'] == policy + 1


def test_contact_timeline_cache_reuses_only_matching_review_identity(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import observe_foot_contact_timeline
    from exercise_motion_pkg import review_questions

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact selected source for timeline identity')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()

    class Capture:
        def __init__(self, _path):
            pass

        def get(self, property_name):
            return {cv2.CAP_PROP_FPS: 30., cv2.CAP_PROP_FRAME_COUNT: 151}.get(property_name, 0.)

        def set(self, *_args):
            pass

        def read(self):
            return True, np.zeros((240, 320, 3), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, 'VideoCapture', Capture)
    pose = {
        'coordinateSpace': 'normalized_image_xy',
        'sourceTimeOriginSec': 0.,
        'frames': [
            {'sourceTimeSec': float(index) * .5,
             'joints': {'left_ankle': [.35, .82],
                        'left_heel': [.33, .84], 'left_toe': [.39, .84]},
             'jointConfidence': {'left_ankle': .95, 'left_heel': .9, 'left_toe': .9}}
            for index in range(9)
        ],
    }
    patch_times = [float(index) * .5 for index in range(9)]
    evidence = {
        'sourceVideoSha256': digest,
        'footPatchEvidence': {
            'sourceVideoSha256': digest,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceTimeOriginSec': 0.,
            'sourceTimesSec': patch_times,
            'feet': {'left': {'states': ['unknown'] * len(patch_times)}},
        },
        'feet': {'left': {'contactIntervals': [
            {'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
             'sourceStartTimeSec': 0., 'sourceEndTimeSec': 1.},
            {'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
             'sourceStartTimeSec': 1.5, 'sourceEndTimeSec': 2.5},
            {'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
             'sourceStartTimeSec': 3., 'sourceEndTimeSec': 4.},
        ]}},
    }
    pose_reference = {'sourceVideoSha256': digest, 'pose': deepcopy(pose)}

    class Reviewer:
        def __init__(self):
            self.settings = SimpleNamespace(llama_cpp_model='model-a')
            self.calls = 0

        def caption(self, *, response_schema, **_kwargs):
            self.calls += 1
            return json.dumps({sample_id: 'full_sole_ground'
                               for sample_id in response_schema['properties']})

    reviewer = Reviewer()
    cache_dir = tmp_path / 'cache'
    first = observe_foot_contact_timeline(
        video, pose_reference, evidence, reviewer.caption, cache_dir)
    assert first['status'] == 'observed'
    assert first['reviewIdentity']['llama_cpp_model'] == 'model-a'
    assert reviewer.calls == 2
    assert observe_foot_contact_timeline(
        video, pose_reference, evidence, reviewer.caption, cache_dir) == first
    assert reviewer.calls == 2

    reviewer.settings = SimpleNamespace(llama_cpp_model='model-b')
    second = observe_foot_contact_timeline(
        video, pose_reference, evidence, reviewer.caption, cache_dir)
    assert reviewer.calls == 4
    assert second['reviewIdentity']['llama_cpp_model'] == 'model-b'

    policy = review_questions.STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION
    monkeypatch.setattr(review_questions, 'STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION',
                        policy + 1)
    third = observe_foot_contact_timeline(
        video, pose_reference, evidence, reviewer.caption, cache_dir)
    assert reviewer.calls == 6
    assert third['reviewIdentity']['structuredResponsePromptPolicyVersion'] == policy + 1
    from exercise_motion_pkg import body_support_observation as module
    monkeypatch.setattr(module, 'CONTACT_TIMELINE_CROP_POLICY', 'new-body-region-crop')
    fourth = observe_foot_contact_timeline(
        video, pose_reference, evidence, reviewer.caption, cache_dir)
    assert reviewer.calls == 8
    assert fourth['requestSha256'] != third['requestSha256']
