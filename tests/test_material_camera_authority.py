import hashlib

from exercise_motion_pkg import foot_contact_observation
from exercise_motion_pkg import source_support_tracking
from exercise_motion_pkg.body_support_observation import _stance_has_conflicting_observations
from exercise_motion_pkg.contact_constraints import is_stationary_contact
from exercise_motion_pkg.source_support_tracking import material_episode_scene_registered


def _material(reference='registered_scene', *, passed=True, digest='source-sha'):
    return {
        'side': 'right',
        'sourceVideoSha256': digest,
        'status': 'verified' if passed else 'failed',
        'passed': passed,
        'heel': {'reference': reference},
        'toe': {'reference': reference},
    }


def test_material_scene_registration_controls_material_contact_authority():
    registered_positive = _material()
    registered_negative = _material(passed=False)
    raw_positive = _material('source_image')
    missing_registration = {'passed': True}

    assert material_episode_scene_registered(registered_positive)
    assert not material_episode_scene_registered(registered_negative | {'toe': {'reference': 'source_image'}})
    assert not material_episode_scene_registered(raw_positive)
    assert not material_episode_scene_registered(missing_registration)

    assert is_stationary_contact({
        'contactMotion': 'stationary', 'materialStationarityEvidence': registered_positive,
    })
    assert not is_stationary_contact({
        'contactMotion': 'stationary', 'materialStationarityEvidence': registered_negative,
    })
    assert not is_stationary_contact({
        'contactMotion': 'stationary', 'materialStationarityEvidence': raw_positive,
    })
    # Other independently observed contact types do not depend on shoe registration.
    assert is_stationary_contact({'contactMotion': 'stationary', 'source': 'visual_hand_contact'})


def test_only_registered_same_source_material_negative_is_a_stance_conflict():
    digest = 'same-source-sha'

    def evidence(material):
        return {
            'sourceVideoSha256': digest,
            'footPatchEvidence': {
                'sourceVideoSha256': digest,
                'feet': {'right': {'states': ['full_sole'] * 4}},
                'materialStationarityEvidence': {
                    'sourceVideoSha256': digest,
                    'episodes': [material],
                },
            },
        }

    assert not _stance_has_conflicting_observations(
        evidence(_material('source_image', passed=False, digest=digest)), 'right',
    )
    assert _stance_has_conflicting_observations(
        evidence(_material(passed=False, digest=digest)), 'right',
    )
    assert not _stance_has_conflicting_observations(
        evidence(_material(passed=False, digest='foreign-source-sha')), 'right',
    )


def test_unregistered_cached_positive_cannot_promote_a_foot_contact(tmp_path, monkeypatch):
    video = tmp_path / 'source.mp4'
    video.write_bytes(b'source bytes')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    states = ['full_sole'] * 4
    contact = {
        'jointName': 'right_foot', 'supportKind': 'observed_foot_patch',
        'contactState': 'full_sole', 'contactMotion': 'unknown',
        'startFrame': 0, 'endFrame': 3,
    }
    patch = {
        'available': True, 'sourceVideoSha256': digest,
        'sourceFrameCount': 4, 'sourceFps': 25.,
        'sourceTimeBasis': 'absolute_source_video', 'sourceTimeOriginSec': 0.,
        'sourceTimesSec': [index / 25. for index in range(4)],
        'feet': {'right': {'states': states}}, 'contacts': [contact],
    }
    observations = {
        'available': True, 'sourceVideoSha256': digest,
        'imageWidth': 640, 'imageHeight': 360,
        'frames': [
            {'joints': {
                'right_heel': {'image': [.5, .8], 'confidence': .95},
                'right_toe': {'image': [.58, .8], 'confidence': .95},
            }} for _ in states
        ],
    }

    def classify(*_args, **_kwargs):
        return patch

    def track(_video_path, _observations, _patch, episodes, *, cache_dir):
        return {
            'available': True,
            'sourceVideoSha256': digest,
            'episodes': [{
                **episodes[0], **_material('source_image', digest=digest),
                'episodeId': episodes[0]['episodeId'],
            }],
        }

    monkeypatch.setattr(foot_contact_observation, 'classify_foot_contacts', classify)
    monkeypatch.setattr(source_support_tracking, 'observe_foot_material_episodes', track)

    result = foot_contact_observation.add_observed_foot_contacts(
        {'contacts': []}, observations, {'frames': []}, source_video_path=video,
    )

    promoted = result['footPatchEvidence']['contacts'][0]
    assert promoted['contactMotion'] == 'unknown'
    assert 'materialStationarityEvidence' not in promoted
    assert 'anchorGroupId' not in promoted
