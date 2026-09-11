import json
from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.contact_constraints import InfeasibleContactCorrection, reachable_root_track


def test_near_boundary_trajectory_converges_without_relaxing_reach():
    fixture=json.loads((Path(__file__).parent/'fixtures/contact_reach_near_boundary.json').read_text(encoding='utf-8'))
    constraints=[(np.array(indexes),np.array(offsets),radius) for indexes,offsets,radius in fixture['constraints']]
    result=reachable_root_track(fixture['count'],fixture['fps'],constraints)
    for indexes,offsets,radius in constraints:
        assert np.max(np.linalg.norm(result[indexes]-offsets,axis=1)-radius)<1e-6
    assert np.isfinite(result).all()


def test_disjoint_reach_constraints_still_fail():
    indexes=np.arange(3)
    constraints=[(indexes,np.tile([0.,0.,0.],(3,1)),.1),
                 (indexes,np.tile([1.,0.,0.],(3,1)),.1)]
    with pytest.raises(InfeasibleContactCorrection):
        reachable_root_track(3,30.,constraints)
