import copy

import numpy as np
import pytest

from exercise_motion_pkg.contact_constraints import stationary_target_track
from exercise_motion_pkg.foot_contact_observation import assign_stationary_anchor_groups


@pytest.mark.parametrize('gap', ['stationary', 'missing', 'moving', 'airborne'])
def test_only_continuously_observed_stationary_toe_links_contact_states(gap):
    contacts = [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary', 'startFrame': 0, 'endFrame': 4},
        {'jointName': 'left_foot', 'contactState': 'toe_only', 'contactMotion': 'stationary', 'startFrame': 8, 'endFrame': 12},
    ]
    original = copy.deepcopy(contacts)
    valid = np.ones(13, dtype=bool)
    points = np.full((13, 2), .5)
    states = ['full_sole'] * 5 + ['unknown'] * 3 + ['toe_only'] * 5
    if gap == 'missing':
        valid[6] = False
    elif gap == 'moving':
        points[6, 0] += .08
    elif gap == 'airborne':
        states[6] = 'airborne'
    assign_stationary_anchor_groups(contacts, side='left', valid=valid,
                                    toe_points=points, foot_sizes=np.full(13, .05), states=states)
    assert (contacts[0]['anchorGroupId'] == contacts[1]['anchorGroupId']) == (gap == 'stationary')
    # Linking endpoint anchors does not label the uncertain gap as contact.
    assert [{k: v for k, v in c.items() if k != 'anchorGroupId'} for c in contacts] == original


def test_shared_anchor_does_not_fix_unobserved_gap_frames():
    points = np.column_stack([np.linspace(0., .2, 30), np.zeros(30), np.zeros(30)])
    points[12:17, 1] = .3
    mask = np.ones(30, dtype=bool)
    mask[12:17] = False
    ids = np.full(30, 'same-observed-toe', dtype=object)
    ids[~mask] = None
    fitted, _ = stationary_target_track(points, mask, fps=30., anchor_ids=ids)
    np.testing.assert_allclose(fitted[0], fitted[-1], atol=1e-12)
    assert not np.allclose(fitted[14], fitted[0])
