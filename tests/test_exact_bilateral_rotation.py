import copy
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from exercise_motion_pkg.controlled_motion import (
    REQUIRED_FIT_CHECKS, CONTROLLED_MOTION_STRATEGY, can_reuse_controlled_motion,
    exact_mirrored_arm_coordinates, canonical_bilateral_reference, pose_digest,
    controlled_motion_fit_source_evidence_digest,
)
from exercise_motion_pkg.rig_playback import sample_rig, mirrored_arm_policy_evidence
from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump


def test_support_chain_gauge_preserves_keys_and_branch_orientation_but_repairs_native_quarters():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.controlled_motion import transported_support_gauge_coordinates
    from exercise_motion_pkg.support_geometry import TOLERANCE_METERS
    data = json.loads((Path(__file__).parent /
        'fixtures/support_chain_gauge_native_quarters.json').read_text())
    original = data['fixedRig']
    proposal = copy.deepcopy(original)
    proposal['coordinates'] = transported_support_gauge_coordinates(
        original, data['stationaryJoints']).tolist()
    count = len(original['coordinates'])
    before = sample_rig(original, np.arange(count))
    after = sample_rig(proposal, np.arange(count))
    np.testing.assert_allclose(after, before, atol=1e-14, rtol=0)
    names = original['jointNames']
    boundary = original['parents'][names.index('left_collar')]
    def global_frames(rig):
        coordinates = np.asarray(rig['coordinates'])
        slots = {names.index(name): 3 + 3*i for i, name in enumerate(rig['rotationJointNames'])}
        result = {}
        for joint in rig['order']:
            local = (Rotation.from_rotvec(coordinates[:, slots[joint]:slots[joint]+3]).as_matrix()
                     if joint in slots else np.tile(np.eye(3), (count, 1, 1)))
            parent = rig['parents'][joint]
            result[joint] = local if parent < 0 else result[parent] @ local
        return result
    np.testing.assert_allclose(global_frames(proposal)[boundary], global_frames(original)[boundary],
                               atol=1e-14, rtol=0)
    cursors = np.arange((count-1)*4+1)/4
    shoulders = [names.index(name) for name in data['stationaryJoints']]
    drift_before = np.linalg.norm(np.ptp(sample_rig(original, cursors)[:, shoulders], axis=0), axis=-1)
    drift_after = np.linalg.norm(np.ptp(sample_rig(proposal, cursors)[:, shoulders], axis=0), axis=-1)
    assert max(drift_before) > TOLERANCE_METERS
    assert max(drift_after) < TOLERANCE_METERS
    np.testing.assert_array_equal(transported_support_gauge_coordinates(original, []),
                                  original['coordinates'])


def test_rigid_root_pair_registration_preserves_internal_pose_and_clears_retained_pins():
    from exercise_motion_pkg.controlled_motion import project_contact_root_pose_coordinates
    data = json.loads((Path(__file__).parent /
        'fixtures/rigid_pair_root_registration.json').read_text())
    fixed = data['fixedRig']
    names = fixed['jointNames']
    values = np.asarray(fixed['coordinates'])
    root = fixed['parents'].index(-1)
    slots = {names.index(name): 3 + 3*i for i, name in enumerate(fixed['rotationJointNames'])}
    def decode(coordinates):
        return sample_rig({**fixed, 'coordinates': coordinates}, np.arange(len(coordinates)))
    rig = SimpleNamespace(root=root, slots=slots, decode=decode)
    original = decode(values)
    targets = original.copy()
    pins = np.zeros(original.shape[:2], dtype=bool)
    indexes = [names.index(name) for name in data['pinNames']]
    pins[:, indexes] = True
    targets[:, indexes] = data['targets']
    proposal = project_contact_root_pose_coordinates(values, rig, pins, targets)
    internal = np.ones(values.shape[1], dtype=bool)
    internal[:3] = False
    internal[slots[root]:slots[root]+3] = False
    np.testing.assert_array_equal(proposal[:, internal], values[:, internal])
    points = decode(proposal)
    assert np.max(np.linalg.norm((points-targets)[pins], axis=-1)) < .0005
    before = np.linalg.norm(original[:, :, None]-original[:, None, :], axis=-1)
    after = np.linalg.norm(points[:, :, None]-points[:, None, :], axis=-1)
    np.testing.assert_allclose(after, before, atol=1e-14, rtol=0)
    source = np.asarray(data['sourceReference'])
    identities = np.full(pins.shape, None, dtype=object)
    for joint in indexes:
        identities[:, joint] = names[joint]
    source_registered = project_contact_root_pose_coordinates(
        values, rig, pins, targets, source_reference=source, stationary_anchor_ids=identities)
    registered_points = decode(source_registered)
    np.testing.assert_array_equal(source_registered[:, internal], values[:, internal])
    assert np.max(np.linalg.norm((registered_points-targets)[pins], axis=-1)) < .0005
    assert np.mean((registered_points-source)**2) < np.mean((points-source)**2)
    from scipy.spatial.transform import Rotation
    center = targets[0, indexes].mean(axis=0)
    axis = targets[0, indexes[1]]-targets[0, indexes[0]]
    rotation = Rotation.from_rotvec(axis/np.linalg.norm(axis)*.03)
    rotated_source = rotation.apply((source-center).reshape(-1, 3)).reshape(source.shape)+center
    rotated = project_contact_root_pose_coordinates(
        values, rig, pins, targets, source_reference=rotated_source, stationary_anchor_ids=identities)
    expected = rotation.apply((registered_points-center).reshape(-1, 3)).reshape(source.shape)+center
    np.testing.assert_allclose(decode(rotated), expected, atol=1e-14, rtol=0)
    np.testing.assert_allclose(np.linalg.norm(np.diff(decode(rotated), n=3, axis=0), axis=(1, 2)),
                               np.linalg.norm(np.diff(registered_points, n=3, axis=0), axis=(1, 2)),
                               atol=1e-14, rtol=0)
    identities[-1, indexes[0]] = 'different-observed-anchor'
    fallback = project_contact_root_pose_coordinates(
        values, rig, pins, targets, source_reference=source, stationary_anchor_ids=identities)
    np.testing.assert_array_equal(fallback, proposal)
    pins[:, indexes[1]] = False
    singleton = project_contact_root_pose_coordinates(values, rig, pins, targets)
    np.testing.assert_array_equal(singleton[:, 3:], values[:, 3:])
    rotation = Rotation.from_rotvec([.02, -.03, .01])
    targets = rotation.apply(original.reshape(-1, 3)).reshape(original.shape) + [.01, .02, -.01]
    pins[:, indexes] = True
    pins[:, root] = True
    registered = project_contact_root_pose_coordinates(values, rig, pins, targets)
    np.testing.assert_allclose(decode(registered), targets, atol=1e-14, rtol=0)


def test_contact_retraction_corrects_nonlinear_tangent_drift_without_mutating_proposal():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.controlled_motion import (
        retract_contact_root_pose_coordinates, KEYFRAME_CONTACT_LIMIT_METERS,
        RIG_NUMERICAL_CONSISTENCY_METERS)
    def decode(values):
        points = np.zeros((len(values), 2, 3))
        points[:, 0] = values[:, :3]
        points[:, 1] = points[:, 0] + Rotation.from_rotvec(values[:, 3:6]).apply(
            np.tile([1., 0., 0.], (len(values), 1)))
        return points
    rig = SimpleNamespace(root=0, slots={0: 3}, decode=decode)
    values = np.zeros((1, 6))
    values[:, 1] = KEYFRAME_CONTACT_LIMIT_METERS - RIG_NUMERICAL_CONSISTENCY_METERS
    values[:, 5] = .003
    values[:, 1] -= .003  # First-order pin tangent; FK has second-order drift.
    targets = np.array([[[0., 0., 0.], [1., 0., 0.]]])
    pins = np.array([[False, True]])
    original = values.copy()
    assert np.linalg.norm((decode(values)-targets)[pins]) > KEYFRAME_CONTACT_LIMIT_METERS
    retained = retract_contact_root_pose_coordinates(values, rig, pins, targets,
                                                    proposal_constructor=lambda q: q.copy())
    validated = retained.copy()
    assert np.linalg.norm((decode(validated)-targets)[pins]) < (
        KEYFRAME_CONTACT_LIMIT_METERS - RIG_NUMERICAL_CONSISTENCY_METERS)
    np.testing.assert_array_equal(retained, validated)
    np.testing.assert_array_equal(values, original)
    np.testing.assert_array_equal(
        retract_contact_root_pose_coordinates(retained, rig, pins, targets), retained)


def test_pure_validation_does_not_construct_a_different_arm_trajectory():
    from exercise_motion_pkg import controlled_motion as motion
    tree = ast.parse(Path(motion.__file__).read_text(encoding='utf-8'))
    validator = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                     and node.name == '_validate_solution_impl')
    guard = next(node for node in ast.walk(validator) if isinstance(node, ast.If)
                 and isinstance(node.test, ast.Name) and node.test.id == 'allow_repairs'
                 and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                         and call.func.id == 'exact_mirrored_arm_coordinates'
                         for call in ast.walk(node)))
    function = ast.parse('def guarded(allow_repairs):\n    pass').body[0]
    function.body = [guard]
    rig = _rig_fixture()
    original = np.asarray(rig['coordinates'])
    current = SimpleNamespace(initial=original.copy())
    namespace = {**motion.__dict__, 'rig': current, 'fixed_rig_payload': rig,
                 'support_gauge_anchors': [],
                 'payload': {'canonicalExecution': {'arms': 'mirrored'}}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<production-immutable-arm-validation>', 'exec'), namespace)
    namespace['guarded'](False)
    np.testing.assert_array_equal(current.initial, original)
    namespace['guarded'](True)
    assert not np.array_equal(current.initial, original)


def test_temporal_restoration_validates_and_retains_the_constructed_proposal():
    from exercise_motion_pkg import controlled_motion as motion
    tree = ast.parse(Path(motion.__file__).read_text(encoding='utf-8'))
    restorer = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                    and node.name == 'restore_temporal_gates_in_key_pin_tangent_space')
    loop = next(node for node in ast.walk(restorer) if isinstance(node, ast.For)
                and isinstance(node.target, ast.Name) and node.target.id == 'alpha')
    constructed = np.array([[1., .25], [1., .25]])
    observed = []

    def validate(solved, **kwargs):
        assert kwargs['allow_repairs'] is False
        observed.append(solved.x.copy())
        return {'coordinates': solved.x.copy()}, {
            'checks': {'jerk': True}, 'applied': True,
            'jerkAfter': .5, 'playback': {'passed': True}}

    namespace = {**motion.__dict__, 'accepted_coordinates': np.zeros((2, 2)),
                 'proposal': np.ones((2, 2)), 'proposal_constructor': lambda value: constructed.copy(),
                 'restoration_deadline': motion.monotonic() + 30., 'rig': SimpleNamespace(
                     decode=lambda value: np.zeros((2, 1, 3)), offsets=np.zeros((1, 3))),
                 'contact_targets': np.zeros((2, 1, 3)), 'pinned': np.zeros((2, 1), dtype=bool),
                 'temporal_gate_metrics_and_jacobian': lambda *a, **k: ([], np.array([0.]), None),
                 'metric_options': {}, 'positive_violations': np.array([1.]), 'merit_before': 1.,
                 'accepted_solved': SimpleNamespace(nfev=0, status=1),
                 'accepted_report': {'checks': {'jerk': False}}, 'accepted_step': None,
                 'validate_solution': validate, 'validation_seconds': 0., 'validation_calls': 0,
                 'rejected_trials': []}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])),
                 '<production-constructed-temporal-step>', 'exec'), namespace)
    retained_solved, retained_candidate, *_ = namespace['accepted_step']
    np.testing.assert_array_equal(observed[0], constructed.ravel())
    np.testing.assert_array_equal(retained_solved.x, constructed.ravel())
    np.testing.assert_array_equal(retained_candidate['coordinates'], constructed.ravel())


def test_immutable_candidate_basis_uses_existing_precision_and_source_identity():
    from exercise_motion_pkg import controlled_motion as motion
    rig = _rig_fixture()
    frames = [{'timeSec': i / 30., 'inferenceFrameIndex': i,
               'sourceFrameIndex': i, 'sourceTimeSec': i / 30., 'joints': {}}
              for i in range(24)]
    reference = {'sourceTimelineMapping': {'selectedSegmentSha256': 'a' * 64,
                 'parentSourceSha256': 'b' * 64}, 'camera': {'cameraRotation': np.eye(3).tolist()},
                 'sourcePose': {'frames': [{'sourceTimeSec': 0., 'joints': {'nose': [0., 0.]}}]},
                 'coordinateReference': {'frames': [{'joints': {'pelvis': [0., 0., 0.]}}]}}
    payload = {'frames': frames, 'sourcePoseCameraReference': reference}
    candidate = {**copy.deepcopy(payload), 'fixedRig': rig}
    context = SimpleNamespace(names=rig['jointNames'], parents=rig['parents'], order=rig['order'],
                              active=[rig['jointNames'].index(n) for n in rig['rotationJointNames']],
                              offsets=np.asarray(rig['offsets']).copy(),
                              initial=np.asarray(rig['coordinates']))
    context.offsets[1, 1] += 5.55e-17
    np.testing.assert_array_equal(motion._immutable_candidate_coordinates(payload, candidate, context),
                                  rig['coordinates'])
    context.offsets[1, 1] += .000134
    with pytest.raises(ValueError, match='basis differs'):
        motion._immutable_candidate_coordinates(payload, candidate, context)
    context.offsets = np.asarray(rig['offsets'])
    candidate['frames'][0]['inferenceFrameIndex'] = 1
    with pytest.raises(ValueError, match='frame identity differs'):
        motion._immutable_candidate_coordinates(payload, candidate, context)


def test_normal_immutable_validation_preserves_the_owned_input_context(monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake, controlled_motion as motion
    rig = _rig_fixture()
    points = sample_rig(rig, np.arange(24))
    payload = {'fps': 30., 'jointNames': rig['jointNames'],
               'canonicalExecution': {'arms': 'mirrored'},
               'equipmentConstraints': {'handRelationship': 'rigid_pair'}, 'frames': []}
    for index, row in enumerate(points):
        joints = dict(zip(rig['jointNames'], row.tolist()))
        source = copy.deepcopy(joints)
        source['left_elbow'][0] += .025
        payload['frames'].append({'timeSec': index / 30., 'joints': joints,
                                  'sourceJoints': source,
                                  'controlledArticulationReferenceJoints': copy.deepcopy(joints)})
    expected = copy.deepcopy(payload)
    monkeypatch.setattr(bake, 'exercise_motion_contract_requires_rigid_paired_hands', lambda _: True)
    monkeypatch.setattr(bake, 'constrain_to_source_articulation_envelope',
                        lambda *a, **k: pytest.fail('Validation must not recondition the owned input'))
    observed = []

    def validate(value, candidate, **kwargs):
        observed.append(copy.deepcopy(value))
        return value, {'applied': False, 'reason': 'test_validation_result'}

    monkeypatch.setattr(motion, 'validate_controlled_motion_candidate', validate)
    monkeypatch.setattr(bake, 'finalize_controlled_motion_result', lambda original, fitted, *a, **k: fitted)
    bake.constrain_baked_payload_to_source_articulation(
        payload, validation_candidate={'fixedRig': rig}, exercise_motion_contract={
            'bilateralExecutionAuthority': 'structured_definition',
            'bilateralExecution': {'arms': 'mirrored'}})
    assert observed == [expected]
    assert payload == expected


def test_observed_support_policy_does_not_override_declared_torso_style():
    from exercise_motion_pkg.bake_and_rank import controlled_motion_execution_policy
    payload = {'renderFloorSource': 'verified_forefoot_pivots', 'sourceFootSupportEvidence': {
        'bodySupport': {'observation': {'torsoSurface': 'horizontal',
            'upperBack': 'stationary_support', 'pelvisAndUpperBackSameSurface': True}}}}
    contract = {'bilateralExecutionAuthority': 'structured_definition',
                'bilateralExecution': {'arms': 'mirrored'}}
    assert controlled_motion_execution_policy(payload, contract) == {
        'arms': 'mirrored', 'torso': 'support_aligned'}
    contract['bilateralExecution']['torso'] = 'sagittal'
    assert controlled_motion_execution_policy(payload, contract) == {
        'arms': 'mirrored', 'torso': 'sagittal'}


def test_validated_successor_refreshes_geometry_identity_and_preserves_source_cycle(monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake, controlled_motion as motion
    from exercise_motion_pkg.artifact_state import cycle_selection_evidence, validate_artifact_state
    contract = {'completionMode': 'return_to_start'}
    payload = {'kind': 'wearPreviewSkeleton', 'fps': 30., 'frameCount': 24,
               'jointNames': ['pelvis'], 'rootJoint': 'pelvis', 'loop': {
                   'enabled': True, 'sourceStartFrame': 0, 'sourceEndFrame': 23,
                   'sourceStartTimeSec': 0., 'sourceEndTimeSec': 23 / 30.},
               'equipmentConstraints': {'handRelationship': 'rigid_pair'}, 'frames': [
                   {'timeSec': i / 30., 'sourceTimeSec': i / 30., 'sourceFrameIndex': i,
                    'joints': {'pelvis': [0., 1., 0.]},
                    'sourceJoints': {'pelvis': [0., 1., 0.]}} for i in range(24)]}
    parent = copy.deepcopy(payload)
    parent['loop']['enabled'] = False
    evidence = cycle_selection_evidence(parent, {
        'type': 'detected_cycle', 'startFrame': 0, 'endFrame': 23,
        'startTimeSec': 0., 'endTimeSec': 23 / 30., 'durationSec': 23 / 30.})
    bake.artifact_state_for_baked_payload(
        payload, contract=contract, selection_class=bake.CYCLE_SELECTION,
        selection_evidence=evidence, source_parent_payload=parent)
    previous = copy.deepcopy(payload['artifactState'])
    monkeypatch.setattr(bake, 'exercise_motion_contract_requires_rigid_paired_hands', lambda _: True)

    def validate(value, candidate, **kwargs):
        result = copy.deepcopy(value)
        result['frames'][0]['joints']['pelvis'][0] += .001
        return result, {'applied': True, 'validationOnly': True, 'evaluations': 0}

    monkeypatch.setattr(motion, 'validate_controlled_motion_candidate', validate)
    result, _ = bake.constrain_baked_payload_to_source_articulation(
        payload, validation_candidate={}, exercise_motion_contract=contract)
    validate_artifact_state(result['artifactState'], movement_payload=result, source_parent_payload=parent)
    assert result['artifactState']['selectionEvidence']['fullClipBake'] == previous['selectionEvidence']['fullClipBake']
    assert result['artifactState']['selectionEvidence']['cycleSelection'] == previous['selectionEvidence']['cycleSelection']
    assert result['artifactState']['selectionEvidence']['cyclicRebake'] != previous['selectionEvidence']['cyclicRebake']
    assert payload['artifactState'] == previous


def _rig_fixture():
    names = ['pelvis', 'spine3', 'left_collar', 'right_collar', 'left_shoulder',
             'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist',
             'left_hand', 'right_hand']
    active = [name for name in names if not name.endswith('collar')]
    offsets = [[0, 0, 0], [0, .4, 0], [-.08, .1, .02], [.08, .1, .02],
               [0, .1, 0], [0, .1, 0], [0, .25, 0], [0, .25, 0],
               [0, .24, 0], [0, .24, 0], [0, .08, 0], [0, .08, 0]]
    phase = np.arange(24) * (2 * np.pi / 24)
    coordinates = np.zeros((24, 3 + 3 * len(active)))
    coordinates[:, :3] = np.column_stack([.02 * np.sin(phase), np.ones(24), .02 * np.cos(phase)])
    for i, name in enumerate(active):
        coordinates[:, 3 + 3*i:6 + 3*i] = np.column_stack([
            .1 * np.sin(phase + i*.03), .2*np.cos(phase + i*.02), .12*np.sin(phase)])
    rig = {'jointNames': names, 'rotationJointNames': active, 'parents': [-1, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9],
           'order': list(range(len(names))), 'offsets': offsets,
           'interpolation': 'limited_quaternion_hermite_v2', 'coordinates': coordinates.tolist()}
    return rig


def test_exact_arm_projection_jacobian_matches_actual_so3_constructor():
    from exercise_motion_pkg.controlled_motion import exact_mirrored_arm_coordinate_jacobian
    rig = _rig_fixture()
    values = np.asarray(rig['coordinates'])
    execution = {'arms': 'mirrored'}
    jacobian = exact_mirrored_arm_coordinate_jacobian(rig, execution)
    direction = np.random.default_rng(42).normal(size=values.shape)
    step = 1e-6
    plus = exact_mirrored_arm_coordinates({**rig, 'coordinates': values+step*direction}, execution)
    minus = exact_mirrored_arm_coordinates({**rig, 'coordinates': values-step*direction}, execution)
    np.testing.assert_allclose((jacobian @ direction.ravel()).reshape(values.shape),
                               (plus-minus)/(2*step), atol=2e-9, rtol=2e-8)
    # Non-arm/root columns pass through; independent frame/part blocks do not
    # leak into another part even with moving root and nontrivial collar poses.
    np.testing.assert_allclose((jacobian @ direction.ravel()).reshape(values.shape)[:, :9],
                               direction[:, :9], atol=0., rtol=0.)
    points_plus = sample_rig({**rig, 'coordinates': plus}, np.arange(len(values)))
    points_minus = sample_rig({**rig, 'coordinates': minus}, np.arange(len(values)))
    derivative = (points_plus-points_minus)/(2*step)
    # Mirrored construction preserves its exact point relation along every
    # perturbed trajectory, including body motion.
    np.testing.assert_allclose(points_plus, canonical_bilateral_reference(
        points_plus, rig['jointNames'], execution), atol=2e-14)
    assert np.isfinite(derivative).all()


def test_exact_arm_midpoint_preserves_native_mirror_and_body_through_loop():
    rig = _rig_fixture()
    names = rig['jointNames']
    coordinates = np.asarray(rig['coordinates'])
    offsets = rig['offsets']
    original = copy.deepcopy(rig)
    np.testing.assert_array_equal(exact_mirrored_arm_coordinates(rig, {}), coordinates)
    mirrored = exact_mirrored_arm_coordinates(rig, {'arms': 'mirrored'})
    proposed = {**rig, 'coordinates': mirrored.tolist()}
    cursors = np.arange(24 * 4) / 4
    before = sample_rig(rig, cursors, wrap=True)
    after = sample_rig(proposed, cursors, wrap=True)
    target = canonical_bilateral_reference(after, names, {'arms': 'mirrored'})
    np.testing.assert_allclose(after, target, atol=2e-14, rtol=0)
    np.testing.assert_array_equal(after[:, :4], before[:, :4])
    np.testing.assert_array_equal(mirrored[:, :9], coordinates[:, :9])
    for joint, parent in enumerate(rig['parents']):
        if parent >= 0:
            np.testing.assert_allclose(np.linalg.norm(after[:, joint] - after[:, parent], axis=1),
                                       np.linalg.norm(offsets[joint]), atol=2e-15)
    assert frame_boundary_velocity_jump(lambda query: sample_rig(proposed, query, wrap=True), [0], 30) < 1e-6
    assert rig == original


def test_cached_mirrored_fit_checks_actual_native_output_not_old_report():
    rig = _rig_fixture()
    names = rig['jointNames']
    payload = {'fixedRig': rig, 'jointNames': names, 'rootJoint': 'pelvis', 'fps': 30.,
               'loop': {'enabled': True}, 'canonicalExecution': {'arms': 'mirrored'}}

    def retain_report():
        points = sample_rig(payload['fixedRig'], np.arange(24))
        payload['frames'] = [{'timeSec': index / 30., 'joints': dict(zip(names, row.tolist()))}
                             for index, row in enumerate(points)]
        payload['controlledMotionFit'] = {
            'applied': True, 'strategy': CONTROLLED_MOTION_STRATEGY,
            'checks': {**dict.fromkeys(REQUIRED_FIT_CHECKS, True), 'loopSeam': True},
            'canonicalExecution': payload['canonicalExecution'],
            'fitSourceEvidenceDigest': controlled_motion_fit_source_evidence_digest(payload),
            'outputPoseDigest': pose_digest(payload),
        }

    retain_report()
    assert not mirrored_arm_policy_evidence(payload)['passed']
    assert not can_reuse_controlled_motion(payload)
    payload['fixedRig']['coordinates'] = exact_mirrored_arm_coordinates(
        rig, payload['canonicalExecution']).tolist()
    retain_report()
    assert mirrored_arm_policy_evidence(payload)['passed']
    assert can_reuse_controlled_motion(payload)
