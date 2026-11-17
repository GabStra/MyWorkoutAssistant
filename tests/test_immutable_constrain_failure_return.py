def payload():
    return {
        'fps': 30.,
        'frames': [
            {'timeSec': i / 30., 'joints': {'pelvis': [0., 1., 0.]},
             'sourceJoints': {'pelvis': [0., 1., 0.]}}
            for i in range(2)
        ],
        'jointNames': ['pelvis'],
        'controlledMotionFit': {'applied': True, 'checks': {'old': True}},
        'sourcePoseReference': {'sourceVideoSha256': 'candidate-source'},
    }


def test_immutable_constrain_preflight_returns_candidate_and_current_failure(monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg import source_evidence

    context = payload()
    context['frames'][0]['joints']['pelvis'][1] = 9.
    candidate = payload()
    candidate['sourcePoseReference'] = {'sourceVideoSha256': 'candidate-source-current'}
    monkeypatch.setattr(source_evidence, 'verified_source_pair_execution_unit', lambda _payload: None)
    context['preReconstructionSourceIntervalAuthority'] = {
        'sourcePairExecutionUnit': {'declared': True}}

    result, report = bake.constrain_baked_payload_to_source_articulation(
        context, validation_candidate=candidate)

    assert result['frames'] == candidate['frames']
    assert result['sourcePoseReference'] == candidate['sourcePoseReference']
    assert report['applied'] is False
    assert report['reason'] == 'selected_source_execution_unit_unbound'
    from exercise_motion_pkg.controlled_motion import pose_digest
    assert report['outputPoseDigest'] == pose_digest(candidate)
    assert result['controlledMotionFit']['applied'] is False
    assert result['controlledMotionFit']['reason'] == report['reason']


def test_outer_validation_failure_returns_candidate_but_generation_keeps_context(monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import physical_validation

    context = payload()
    candidate = payload()
    candidate['frames'][0]['joints']['pelvis'][1] = 2.
    context['frames'][0]['joints']['pelvis'][1] = 3.
    failed_result = payload()
    failed_result['frames'][0]['joints']['pelvis'][1] = 9.
    report = {
        'applied': False, 'validationOnly': True,
        'reason': 'fit_validation_failed',
        'checks': {'sourceSupportAuthority': False},
        'fitSourceEvidenceDigest': 'current-context-evidence',
    }
    monkeypatch.setattr(bake, 'source_knee_angle_bounds', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(physical_validation, 'source_hinge_angle_bounds', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(motion, 'validate_controlled_motion_candidate',
                        lambda *_args, **_kwargs: (failed_result, report))

    validated, _ = bake.constrain_baked_payload_to_source_articulation(
        context, validation_candidate=candidate)
    generated = bake.finalize_controlled_motion_result(
        context, failed_result, report, fit_input_pose_digest='current-pose',
        fit_input_source_evidence_digest='current-context-evidence')

    assert validated['frames'] == candidate['frames']
    assert validated['controlledMotionFit']['applied'] is False
    assert validated['controlledMotionFit']['validationOnly'] is True
    assert validated['controlledMotionFit']['fitSourceEvidenceDigest'] == 'current-context-evidence'
    assert validated['controlledMotionFit']['checks'] == {'sourceSupportAuthority': False}
    assert generated['frames'] == context['frames']
    assert generated['controlledMotionFit']['applied'] is False
