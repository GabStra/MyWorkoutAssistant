"""Focused transport regression for atomic non-foot support pairs."""
import hashlib
import json

import cv2
import numpy as np

from exercise_motion_pkg import body_support_observation as module


def _serve_source(tmp_path, monkeypatch, payload=b'exact source for pair transport'):
    video = tmp_path / 'source.mp4'
    video.write_bytes(payload)

    class Capture:
        def get(self, prop):
            return 5 if prop == cv2.CAP_PROP_FRAME_COUNT else 1.

        def set(self, *_args):
            pass

        def read(self):
            return True, np.zeros((16, 16, 3), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, 'VideoCapture', lambda _path: Capture())
    return video, hashlib.sha256(video.read_bytes()).hexdigest()


def test_atomic_pair_tokens_round_trip_and_require_knee_reuse(tmp_path, monkeypatch):
    video, _digest = _serve_source(tmp_path, monkeypatch)
    calls = []

    def caption(**kwargs):
        calls.append(kwargs)
        properties = kwargs['response_schema']['properties']
        assert 'leftKneeContactSurface' not in properties
        assert 'leftAnkleContactSurface' not in properties
        knee = set(properties['leftKnee']['enum'])
        assert 'stationary_support:floor' in knee
        assert 'stationary_support:none' not in knee
        assert {'unsupported:none', 'moving:none', 'unknown:unknown'} <= knee
        hand = set(properties['leftHand']['enum'])
        assert 'moving:moving_implement' in hand
        assert 'stationary_support:moving_implement' not in hand
        ankle = set(properties['leftAnkle']['enum'])
        assert 'stationary_support:fixed_bar' in ankle
        assert 'stationary_support:none' not in ankle
        return json.dumps({
            'torsoSurface': 'horizontal',
            'pelvis': 'unsupported:none',
            'upperBack': 'unknown:unknown',
            'head': 'moving:none',
            'leftKnee': 'stationary_support:floor',
            'rightKnee': 'unknown:unknown',
            'leftAnkle': 'stationary_support:fixed_bar',
            'rightAnkle': 'moving:none',
            'leftHand': 'moving:moving_implement',
            'rightHand': 'unsupported:none',
            'leftFoot': 'stationary_full_sole',
            'leftFootSurface': 'ground',
        })

    result = module.observe_body_support(video, caption, tmp_path)
    assert result['status'] == 'observed'
    assert len(calls) == 1
    observation = result['observation']
    assert (observation['pelvis'], observation['pelvisContactSurface']) == ('unsupported', 'none')
    assert (observation['upperBack'], observation['upperBackContactSurface']) == ('unknown', 'unknown')
    assert (observation['head'], observation['headContactSurface']) == ('moving', 'none')
    assert (observation['leftKnee'], observation['leftKneeContactSurface']) == ('stationary_support', 'floor')
    assert (observation['rightKnee'], observation['rightKneeContactSurface']) == ('unknown', 'unknown')
    assert (observation['leftAnkle'], observation['leftAnkleContactSurface']) == ('stationary_support', 'fixed_bar')
    assert (observation['rightAnkle'], observation['rightAnkleContactSurface']) == ('moving', 'none')
    assert (observation['leftHand'], observation['leftHandContactSurface']) == ('moving', 'moving_implement')
    assert (observation['rightHand'], observation['rightHandContactSurface']) == ('unsupported', 'none')
    assert 'stationary_support:none' not in json.dumps(result)

    reused = module.observe_body_support(video, caption, tmp_path, require_knee_observation=True)
    assert len(calls) == 1
    assert reused['observation']['leftKnee'] == 'stationary_support'
    assert reused['observation']['leftKneeContactSurface'] == 'floor'
    assert reused['observation']['rightKneeContactSurface'] == 'unknown'


def test_illegal_stationary_pair_is_rejected_without_coercion(tmp_path, monkeypatch):
    video, _digest = _serve_source(tmp_path, monkeypatch, b'contradictory observer source')

    def caption(**_kwargs):
        return json.dumps({'leftKnee': 'stationary_support:none',
                           'rightKnee': 'unknown:unknown'})

    result = module.observe_body_support(video, caption, tmp_path)
    assert result['status'] == 'unknown'
    assert result['reason'] == 'support_observation_schema_invalid'
    assert result['observation']['leftKnee'] == 'stationary_support:none'
    assert 'leftKneeContactSurface' not in result['observation']


def test_valid_flat_v7_cache_is_reused_unchanged(tmp_path, monkeypatch):
    video, digest = _serve_source(tmp_path, monkeypatch, b'retained flat v7 support cache')
    observation = {
        'leftKnee': 'stationary_support', 'leftKneeContactSurface': 'floor',
        'rightKnee': 'unknown', 'rightKneeContactSurface': 'unknown',
        'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
        'pelvis': 'moving', 'pelvisContactSurface': 'bench',
    }
    cached = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'policyVersion': module.POLICY_VERSION,
        'observation': observation,
    }
    cache_path = tmp_path / f'body-support-{digest}-v{module.POLICY_VERSION}.json'
    cache_path.write_text(json.dumps(cached))
    original = cache_path.read_bytes()

    result = module.observe_body_support(
        video, None, tmp_path, require_knee_observation=True)

    assert result['observation'] == observation
    assert result['policyVersion'] == 7
    assert cache_path.read_bytes() == original


def test_incomplete_flat_cache_requires_knees_and_retains_valid_fields(tmp_path, monkeypatch):
    video, digest = _serve_source(tmp_path, monkeypatch, b'incomplete knee support cache')
    calls = []

    def caption(**_kwargs):
        calls.append(True)
        return json.dumps({'leftKnee': 'stationary_support:floor',
                           'rightKnee': 'unknown:unknown'})

    cached = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'policyVersion': module.POLICY_VERSION,
        'reviewIdentity': module._review_model_identity(caption),
        'observation': {
            'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
            'pelvis': 'moving', 'pelvisContactSurface': 'bench',
        },
    }
    (tmp_path / f'body-support-{digest}-v{module.POLICY_VERSION}.json').write_text(
        json.dumps(cached))

    result = module.observe_body_support(
        video, caption, tmp_path, require_knee_observation=True)

    assert len(calls) == 1
    assert result['observation']['leftFoot'] == 'stationary_full_sole'
    assert result['observation']['leftFootSurface'] == 'ground'
    assert result['observation']['pelvisContactSurface'] == 'bench'
    assert (result['observation']['leftKnee'], result['observation']['leftKneeContactSurface']) == (
        'stationary_support', 'floor')
