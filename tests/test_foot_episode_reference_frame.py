import numpy as np

from exercise_motion_pkg.foot_contact_observation import _materialize_foot_patch_contacts


def _materialize(states, toe_points, *, foot_size=0.15, uncalibrated_toe=True):
    count = len(states)
    return _materialize_foot_patch_contacts(
        side='right', states=states, valid=np.ones(count, dtype=bool),
        toe_valid=np.ones(count, dtype=bool), heel_points=np.zeros((count, 2)),
        toe_points=np.asarray(toe_points, dtype=float),
        foot_sizes=np.full(count, foot_size), image_pitch=np.zeros(count),
        world_pitch=np.zeros(count), image_only_toe=np.zeros(count, dtype=bool),
        unresolved_heel_recontact=np.zeros(count, dtype=bool),
        references=[0., 0.], tolerances=[.1, .1],
        uncalibrated_toe=uncalibrated_toe, uncalibrated_surface_kind='ground',
        support_contacts=[],
    )


def test_global_reference_drift_cannot_erase_grounded_static_forefoot():
    """Raw per-frame extrema include jitter; the visible toe stays planted."""
    count = 60
    ramp = np.linspace(0., .008, count)
    jitter = .008 * np.where(np.arange(count) % 2, 1., -1.)
    toe_points = np.column_stack((.30 + ramp + jitter, .70 + .5 * ramp - jitter))
    scale = .15
    assert np.linalg.norm(np.ptp(toe_points, axis=0)) > max(.005, scale * .15)

    states = ['toe_only'] * count
    contacts = _materialize(states, toe_points, foot_size=scale)

    assert states == ['toe_only'] * count
    assert len(contacts) == 1
    assert contacts[0]['contactState'] == 'toe_only'
    assert contacts[0]['contactMotion'] == 'stationary'


def test_genuine_uncalibrated_toe_displacement_is_still_rejected():
    count = 60
    toe_points = np.column_stack((.30 + np.linspace(0., .12, count), np.full(count, .70)))
    states = ['toe_only'] * count

    contacts = _materialize(states, toe_points)

    assert contacts == []
    assert states == ['unknown'] * count


def test_genuine_release_between_static_forefoot_phases_is_not_bridged():
    count = 40
    toe_points = np.tile([.30, .70], (count, 1))
    states = ['toe_only'] * 15 + ['airborne'] * 10 + ['toe_only'] * 15

    contacts = _materialize(states, toe_points)

    assert [contact['contactState'] for contact in contacts] == ['toe_only', 'toe_only']
    assert [contact['startRatio'] for contact in contacts] == [
        0., 25 / (count - 1)]
