from exercise_motion_pkg.controlled_motion import bounded_anatomy_projection_eligible


def test_bounded_anatomy_projection_allows_independent_foot_articulation_failure():
    checks = {
        name: True for name in (
            'contacts', 'heightOnlyContacts', 'sourceArticulation', 'trajectoryFit',
            'rootTravel', 'jointRange', 'fixedRig', 'bodySupport', 'supportAlignment',
            'rootContinuity', 'equipment', 'bodyRotation',
        )
    }
    checks.update({'anatomy': False, 'sourceFootContactArticulation': False})

    assert bounded_anatomy_projection_eligible(
        {'anatomy', 'sourceFootContactArticulation'},
        checks,
        repairable_anatomy=True,
        cyclic=False,
    )
    assert not bounded_anatomy_projection_eligible(
        {'anatomy', 'sourceFootContactArticulation'},
        {**checks, 'bodySupport': False},
        repairable_anatomy=True,
        cyclic=False,
    )
