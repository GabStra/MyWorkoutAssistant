import numpy as np


def test_raised_full_sole_timeline_sets_articulation_without_ground_calibration(monkeypatch):
    from exercise_motion_pkg import body_support_observation
    from exercise_motion_pkg.foot_contact_observation import _reviewed_sole_mode_masks

    digest = 'a' * 64
    observations = {
        'sourceVideoSha256': digest,
        'frames': [{'timeSeconds': 0.0}, {'timeSeconds': 1.0 / 30.0}],
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySupportObservation': {'sourceVideoSha256': digest},
    }
    timeline = [
        {
            'side': 'right', 'sourceFrameIndex': 0, 'sourceTimeSec': 0.0,
            'contactState': 'full_sole', 'surface': 'raised_surface',
            'visible': True, 'sourceTrackStationary': True,
        },
        {
            'side': 'right', 'sourceFrameIndex': 1, 'sourceTimeSec': 1.0 / 30.0,
            'contactState': 'full_sole', 'surface': 'ground',
            'visible': True, 'sourceTrackStationary': True,
        },
    ]
    monkeypatch.setattr(
        body_support_observation, 'validated_body_support_contact_timeline',
        lambda *_args, **_kwargs: timeline,
    )

    neutral, contact, forefoot, heel_only, stationary, exact_fullsole = (
        _reviewed_sole_mode_masks(evidence, observations, 'right'))

    # Raised-surface contact remains provenance for a visible full-sole state;
    # it does not become ground contact or a calibration reference.
    assert not neutral[0]
    assert not contact[0]
    assert not forefoot[0]
    assert not heel_only[0]
    assert not stationary[0]
    assert exact_fullsole[0]

    # Ground full-sole rows continue to populate the calibration/contact masks.
    assert neutral[1]
    assert contact[1]
    assert not forefoot[1]
    assert not heel_only[1]
    assert stationary[1]
    assert exact_fullsole[1]
    assert neutral.dtype == np.bool_
