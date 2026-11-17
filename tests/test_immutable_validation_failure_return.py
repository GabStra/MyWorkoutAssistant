from copy import deepcopy


def candidate_payload():
    return {
        'fps': 30.,
        'jointNames': ['pelvis'],
        'frames': [{'timeSec': 0., 'sourceTimeSec': 0., 'joints': {'pelvis': [0., 1., 0.]}}],
        'fixedRig': {'coordinates': [[0., 1., 0.]], 'jointNames': ['pelvis']},
        'loop': {'enabled': False},
        'sourcePoseReference': {'sourceVideoSha256': 'candidate-source'},
        'sourcePoseCameraReference': {'camera': {'id': 'candidate-camera'}},
        'sourceFootSupportEvidence': {'sourceVideoSha256': 'candidate-source'},
        'controlledMotionFit': {'applied': True, 'validationOnly': True, 'reason': None},
    }


def test_early_source_preflight_failure_returns_candidate_not_context(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    candidate = candidate_payload()
    frozen = deepcopy(candidate)
    context = candidate_payload()
    context['frames'][0]['joints']['pelvis'][1] = 9.
    context['sourcePoseCameraReference'] = {'camera': {'id': 'context-camera'}}
    monkeypatch.setattr(motion, 'fit_controlled_motion', lambda *args, **kwargs: (
        context, {'applied': False, 'reason': 'source_support_contact_readiness',
                  'failureStage': 'source_support_contact_readiness'}))

    result, report = motion.validate_controlled_motion_candidate(context, candidate)

    assert candidate == frozen
    assert result['frames'] == frozen['frames']
    assert result['fixedRig'] == frozen['fixedRig']
    assert result['sourcePoseReference'] == frozen['sourcePoseReference']
    assert result['sourcePoseCameraReference'] == frozen['sourcePoseCameraReference']
    assert report['applied'] is False
    assert 'validationOnly' not in report
    assert result['controlledMotionFit']['applied'] is False
    assert 'validationOnly' not in result['controlledMotionFit']


def test_late_failed_validation_returns_candidate_and_clears_stale_success_flags(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    candidate = candidate_payload()
    context = candidate_payload()
    context['frames'][0]['joints']['pelvis'][1] = 9.
    monkeypatch.setattr(motion, 'fit_controlled_motion', lambda *args, **kwargs: (
        context, {
            'applied': False, 'validationOnly': True,
            'immutableCandidateUnchanged': True,
            'outputPoseDigest': 'context-digest',
            'fitSourceEvidenceDigest': 'current-context-evidence',
            'checks': {'sourceSupportAuthority': False},
            'reason': 'fit_validation_failed',
        }))

    result, report = motion.validate_controlled_motion_candidate(context, candidate)

    assert result['frames'] == candidate['frames']
    assert result['sourcePoseCameraReference'] == candidate['sourcePoseCameraReference']
    assert report['applied'] is False
    assert report['checks'] == {'sourceSupportAuthority': False}
    assert report['validationOnly'] is True
    assert report['immutableCandidateUnchanged'] is True
    assert report['fitSourceEvidenceDigest'] == 'current-context-evidence'
    assert report['outputPoseDigest'] == motion.pose_digest(candidate)
    assert result['controlledMotionFit']['applied'] is False


def test_normal_generation_source_preflight_still_returns_generation_input(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import contact_constraints
    from exercise_motion_pkg import native_foot_geometry

    payload = candidate_payload()
    monkeypatch.setattr(native_foot_geometry, 'promote_native_foot_geometry', lambda _payload: None)
    monkeypatch.setattr(motion, 'source_foot_patch_pose_binding_failure', lambda _payload: None)
    monkeypatch.setattr(motion, 'source_foot_patch_clock_failure', lambda _payload: None)
    monkeypatch.setattr(contact_constraints, 'source_support_mapping_unresolved', lambda _payload: True)

    result, report = motion.fit_controlled_motion(payload, max_evaluations=0)

    assert result is payload
    assert report['applied'] is False
    assert report['reason'] == 'source_support_mapping_unresolved'
