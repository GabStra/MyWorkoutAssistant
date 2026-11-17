import numpy as np

from exercise_motion_pkg.material_region_support import (
    finite_patch_shoe_errors, support_surface_for_region,
)


def test_finite_material_support_keeps_overhang_free_and_checks_triangle_intersection():
    vertices = np.zeros((1, 26, 3))
    vertices[:, :, 1] = 1.
    vertices[:, :, 0] = 2.
    vertices[0, [1, 2, 9, 10]] = [[0., 0., 0.], [.2, .1, 0.],
                                         [0., .1, .2], [.2, .1, .2]]
    contact = {'region': 'foot_dorsum', 'planeOffsetMeters': 0.,
               'boundsXZ': [-.1, .3, -.1, .3], 'thicknessMeters': .4}
    # A hanging toe outside the finite equipment footprint is not floor contact.
    vertices[0, 25] = [2., -.5, 2.]
    np.testing.assert_allclose(finite_patch_shoe_errors(vertices, contact), 0.)
    # Native strip triangle (0,8,9) crosses the patch despite outside vertices.
    vertices[0, 0] = [-1., -.2, 0.]
    vertices[0, 8] = [1., -.2, 0.]
    errors = finite_patch_shoe_errors(vertices, contact)
    assert errors[0, 0] == 0.
    assert errors[0, 1] <= -.2
    surface = support_surface_for_region(contact)
    assert surface['topY'] == contact['planeOffsetMeters']
    np.testing.assert_allclose(surface['center'], [.1, 0., .1])
    assert surface['size'] == surface['depth'] == .4
    from exercise_motion_pkg.material_region_support import source_surface_projection_errors
    region = {'polygonNormalizedXY': [[.3, .4], [.9, .4], [.9, .6], [.3, .6]]}
    camera = {'projection': np.asarray([[1., 0., 0.], [0., 1., 0.]]),
              'offset': np.asarray([.5, .5])}
    np.testing.assert_allclose(source_surface_projection_errors(contact, region, camera, 1.), 0.)
    assert np.max(abs(source_surface_projection_errors(
        {**contact, 'planeOffsetMeters': .5}, region, camera, 1.))) > 0.
    # Leaving the patch cannot erase a genuine vertical contact gap.
    above = np.ones((1, 26, 3))
    above[0, [1, 2, 9, 10, 17, 18]] = [[0., .1, 0.], [.2, .1, 0.],
                                       [0., .1, .1], [.2, .1, .1],
                                       [0., .1, .2], [.2, .1, .2]]
    before = finite_patch_shoe_errors(above, {**contact, 'boundsXZ': [.2-1e-6, .4, -.1, .3]})[0, 0]
    after = finite_patch_shoe_errors(above, {**contact, 'boundsXZ': [.2+1e-6, .4, -.1, .3]})[0, 0]
    np.testing.assert_allclose([before, after], [.1, .1], atol=1e-8)


def test_material_region_uses_native_global_context_and_same_finite_render_patch():
    import json
    from pathlib import Path
    from exercise_motion_pkg import controlled_motion as c
    from exercise_motion_pkg.body_support_observation import POLICY_VERSION
    from exercise_motion_pkg.material_region_support import (
        SHOE_DORSUM_VERTICES, estimated_patch_from_contact_vertices, native_region_geometry,
    )
    from exercise_motion_pkg.shoe_floor import ShoeFloorConstraint
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rig = c.FixedRig(np.tile([fixture['joints'][name] for name in names], (5, 1, 1)), names)
    points = rig.decode(rig.initial)
    mapping = {'selectedSegmentSha256': 'source', 'selectedFrameClockReceiptSha256': 'clock',
               'sourcePosePayloadSha256': 'pose'}
    payload = {'jointNames': names, 'frames': [{'joints': dict(zip(names, row.tolist()))} for row in points],
               'renderFloorY': -10., 'sourcePoseCameraReference': {
                   'sourcePose': {'sourceVideoSha256': 'source'}, 'sourceTimelineMapping': mapping,
                   'camera': {'bilateralAssignment': 'identity'}},
               'sourceFootSupportEvidence': {'bodySupportObservation': {
                   'status': 'observed', 'source': 'exact_source_visual_support_observation',
                   'policyVersion': POLICY_VERSION, 'sourceVideoSha256': 'source',
                   'observation': {'rightFoot': 'supported_dorsum', 'rightFootSurface': 'raised_surface',
                                   'rightFootSurfaceMotion': 'stationary',
                                   'rightFootSurfaceOrientation': 'horizontal',
                                   'rightFootContactContinuity': 'continuous',
                                   'rightFootSurfaceImageRegion': {
                                       'polygonNormalizedXY': [[0., 0.], [1., 0.], [1., 1.], [0., 1.]],
                                       'sourceVideoSha256': 'source', 'sourceClock': 'video_frame_zero_seconds',
                                       'nativeVideoFrameIndex': 0}}}}}
    for frame in payload['frames']:
        frame['boneSides'] = {'right_ankle->right_foot': [-1., 0., 0.]}
    shoes = ShoeFloorConstraint(rig, payload)
    shoes.heights(rig.initial.ravel())
    # A contact FACE annotation cannot rotate the shoe independently of FK.
    from copy import deepcopy
    ordinary = deepcopy(payload)
    ordinary.pop('sourceFootSupportEvidence')
    plain = ShoeFloorConstraint(rig, ordinary)
    plain.heights(rig.initial.ravel())
    np.testing.assert_allclose(shoes.material_vertices(shoes.points, shoes.resolved, shoes.scale)['right'],
                               plain.material_vertices(plain.points, plain.resolved, plain.scale)['right'])

    vertices = shoes.material_vertices(shoes.points, shoes.resolved, shoes.scale)['right']
    contact = {**estimated_patch_from_contact_vertices(
        vertices, vertices[:, SHOE_DORSUM_VERTICES, 1].min(), foot_scale=shoes.scale),
        'side': 'right', 'sourceVideoSha256': 'source',
        'calibrationCamera': {'cameraRotation': None, 'cameraImageTransform': None,
                              'bilateralAssignment': 'identity'},
        'sourceImageRegion': payload['sourceFootSupportEvidence']['bodySupportObservation'][
            'observation']['rightFootSurfaceImageRegion'],
        'calibrationSourceTimelineMappingIdentity': mapping}
    payload['sourceFootSupportEvidence']['bodySupport'] = {'materialRegionContacts': [contact]}
    shoes = ShoeFloorConstraint(rig, payload)
    rows = shoes.residual(rig.initial.ravel())
    native = native_region_geometry(payload)
    fitted = rows[shoes.floor_row_count:].reshape(5, shoes.region_row_count)
    np.testing.assert_allclose(native['maximumSurfaceErrorMeters'], np.max(np.abs(fitted[:, 0])))
    actual_vertices = shoes.material_vertices(shoes.points, shoes.resolved, shoes.scale)['right']
    physical_rows = finite_patch_shoe_errors(actual_vertices, contact)
    np.testing.assert_allclose(native['maximumMaterialPenetrationMeters'], np.max(-physical_rows[:, 1]))
    # Native quarter-frame samples use the full stored context, not five
    # independently reconstructed material frames.
    from exercise_motion_pkg.rig_playback import sample_rig
    cursors = np.arange(17) / 4.
    dense = sample_rig(c._sampling_payload(rig, rig.initial), cursors, wrap=False)
    np.testing.assert_allclose(native_region_geometry(payload, dense, cursors)[
        'maximumSurfaceErrorMeters'], native['maximumSurfaceErrorMeters'], atol=1e-12)
    surface = support_surface_for_region(contact)
    assert surface['topY'] == contact['planeOffsetMeters']
    np.testing.assert_allclose(surface['size'], contact['boundsXZ'][1]-contact['boundsXZ'][0])
    # The extended structured tail retains the same derivative ownership.
    # Evaluate off the contact/penetration hinge, whose derivative is set-valued.
    contact['planeOffsetMeters'] -= .01
    column = rig.slots[names.index('right_foot')]
    plus, minus = rig.initial.copy(), rig.initial.copy()
    plus[2, column] += 1e-6
    minus[2, column] -= 1e-6
    expected = (shoes.residual(plus.ravel())-shoes.residual(minus.ravel()))/2e-6
    np.testing.assert_allclose(shoes.jacobian(rig.initial.ravel()).toarray()[:, 2*rig.width+column],
                               expected, atol=1e-5)
    from exercise_motion_pkg.material_region_support import observed_region_sides
    from copy import deepcopy
    from exercise_motion_pkg.temporal_quality import transport_corrected_bone_sides
    delivered = deepcopy(payload)
    transport_corrected_bone_sides(payload['frames'], delivered)
    np.testing.assert_allclose(native_region_geometry(delivered)['maximumSurfaceErrorMeters'],
                               native_region_geometry(payload)['maximumSurfaceErrorMeters'])
    payload['sourcePoseCameraReference']['sourceTimelineMapping']['selectedSegmentSha256'] = 'different-bytes'
    assert observed_region_sides(payload) == []


def test_reviewed_observation_veto_preserves_raw_point_and_other_exposures():
    from copy import deepcopy
    import pytest
    from exercise_motion_pkg.pose_fidelity import apply_source_observation_vetoes, _pose_frames
    source = {'sourceVideoSha256': 'source', 'coordinateSpace': 'normalized_image_xy',
              'imageWidth': 100, 'imageHeight': 50, 'frames': [
                  {'sourceTimeSec': 0., 'joints': {'right_ankle': [.5, .8, 0.]},
                   'jointConfidence': {'right_ankle': .75}},
                  {'sourceTimeSec': 2., 'joints': {'right_ankle': [.6, .6, 0.]},
                   'jointConfidence': {'right_ankle': .96}}]}
    original = deepcopy(source)
    veto = {'sourceVideoSha256': 'source', 'sourcePoseSampleIndex': 0,
            'sourceTimeSec': 0., 'jointName': 'right_ankle',
            'reviewAuthority': 'agent_visual_review/root'}
    corrected = apply_source_observation_vetoes(source, source_video_sha256='source', vetoes=[veto])
    assert source == original
    assert corrected['frames'][0]['joints'] == source['frames'][0]['joints']
    frames = _pose_frames(corrected, source=True)
    assert 'right_ankle' not in frames[0]['joints']
    assert 'right_ankle' in frames[1]['joints']
    with pytest.raises(ValueError):
        apply_source_observation_vetoes(source, source_video_sha256='changed-bytes', vetoes=[veto])


def test_native_triangle_escape_keeps_gradient_when_final_overlap_is_capped():
    import json
    from copy import deepcopy
    from pathlib import Path
    from exercise_motion_pkg.material_region_support import (
        triangle_slab_signed_separation, finite_slab_triangle_overlap,
    )
    contact = {'boundsXZ': [-.2, .2, -.2, .2], 'planeOffsetMeters': .1, 'thicknessMeters': .2}
    triangle = np.asarray([[[-1., -1., .05], [1., -1., .05], [0., 1., .05]]])
    np.testing.assert_allclose(triangle_slab_signed_separation(triangle, contact), [-.15])
    for translation in ([0., -3., 0.], [3., 0., 0.], [0., 3., 0.]):
        assert np.all(np.minimum(triangle_slab_signed_separation(triangle+translation, contact), 0.) == 0.)
    fixture = json.loads((Path(__file__).parent/'fixtures/material_region_collision_crossing.json').read_text())
    triangle = np.asarray([fixture['triangleVerticesMeters']])
    contact = fixture['contact']
    np.testing.assert_allclose(finite_slab_triangle_overlap(triangle[0], contact), contact['thicknessMeters'])
    old_gradient, escape_gradient = [], []
    for axis in range(3):
        plus, minus = deepcopy(contact), deepcopy(contact)
        if axis == 1:
            plus['planeOffsetMeters'] += 1e-6
            minus['planeOffsetMeters'] -= 1e-6
        else:
            start = 0 if axis == 0 else 2
            for bound in (start, start+1):
                plus['boundsXZ'][bound] += 1e-6
                minus['boundsXZ'][bound] -= 1e-6
        old_gradient.append((finite_slab_triangle_overlap(triangle[0], plus)
                             - finite_slab_triangle_overlap(triangle[0], minus))/2e-6)
        escape_gradient.append(float((triangle_slab_signed_separation(triangle, plus)
                                      - triangle_slab_signed_separation(triangle, minus))[0]/2e-6))
    np.testing.assert_allclose(old_gradient, 0.)
    np.testing.assert_allclose(np.linalg.norm(escape_gradient), 1., atol=1e-7)

def test_explicit_source_veto_qualifies_only_joined_hinge_direction(monkeypatch):
    import json
    from pathlib import Path
    from copy import deepcopy
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg import physical_validation as pv, controlled_motion as c
    from exercise_motion_pkg.pose_fidelity import apply_source_observation_vetoes
    from exercise_motion_pkg import contact_constraints as cc
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    reference = np.tile([fixture['joints'][name] for name in names], (5, 1, 1))
    source = {'sourceVideoSha256': 'source', 'frames': [
        {'sourceTimeSec': float(i), 'joints': {'right_ankle': [0., 0., 0.]},
         'jointConfidence': {'right_ankle': 1.}} for i in range(5)]}
    veto = {'sourceVideoSha256': 'source', 'sourcePoseSampleIndex': 0, 'sourceTimeSec': 0.,
            'jointName': 'right_ankle', 'reviewAuthority': 'agent_visual_review/root'}
    source = apply_source_observation_vetoes(source, source_video_sha256='source', vetoes=[veto])
    payload = {'frames': [{'sourceTimeSec': float(i)} for i in range(5)],
               'sourcePoseCameraReference': {'sourcePose': source, 'camera': {'bilateralAssignment': 'identity'}}}
    monkeypatch.setattr(cc, '_source_timeline_mapping_for_payload', lambda p: {'verified': True})
    monkeypatch.setattr(cc, '_foot_patch_times_in_parent_clock', lambda e, m, times: np.asarray(times))
    from exercise_motion_pkg import pose_fidelity as pf
    monkeypatch.setattr(pf, 'source_pose_reference_for_motion', lambda source, motion, **kwargs: {
        'frames': [frame for frame in source['frames'] if motion['frames'][0]['sourceTimeSec']
                   <= frame['sourceTimeSec'] <= motion['frames'][-1]['sourceTimeSec']]})
    authority = pv.source_hinge_direction_authority(payload, names)
    assert np.argwhere(~authority).tolist() == [[0, names.index('right_ankle')]]
    crop = deepcopy(payload)
    crop['frames'] = crop['frames'][2:]
    assert pv.source_hinge_direction_authority(crop, names).all()
    candidate = reference.copy()
    hip, knee, ankle, foot = [names.index('right_'+part) for part in ('hip', 'knee', 'ankle', 'foot')]
    axis = reference[0, hip]-reference[0, knee]
    perpendicular = np.cross(axis, [1., 0., 0.])
    reference[:, ankle] = reference[:, knee]+perpendicular/np.linalg.norm(perpendicular)*.4
    reference[:, foot] = reference[:, ankle]+[0., 0., .12]
    candidate = reference.copy()
    rotation = Rotation.from_rotvec(axis/np.linalg.norm(axis)*np.deg2rad(40.)).as_matrix()
    for frame in (0, 2):
        candidate[frame, [ankle, foot]] = ((reference[frame, [ankle, foot]]-reference[frame, knee])
                                         @ rotation.T+reference[frame, knee])
    ordinary = pv.hinge_direction_events(candidate, names, reference)
    qualified = pv.hinge_direction_events(candidate, names, reference, direction_authority=authority)
    assert any(event['frameIndex'] == 0 for event in ordinary)
    assert not any(event['frameIndex'] == 0 for event in qualified)
    assert any(event['frameIndex'] == 2 for event in qualified)
    # Qualifying direction does not erase scalar-angle fidelity.
    candidate[0, ankle] = reference[0, knee]+(reference[0, hip]-reference[0, knee])*.7
    events = c.support_initialization_articulation_regressions(
        reference, candidate, names, direction_authority=authority)
    assert any(event['feature'] == 'right_knee' for event in events)
    direction_candidate = reference.copy()
    vector = reference[0, foot]-reference[0, ankle]
    direction_candidate[0, foot] = reference[0, ankle]+Rotation.from_euler('y', 90., degrees=True).apply(vector)
    unqualified = c.support_initialization_articulation_regressions(reference, direction_candidate, names)
    qualified = c.support_initialization_articulation_regressions(
        reference, direction_candidate, names, direction_authority=authority)
    assert not any(e['feature'].endswith('_foot_heading') for e in unqualified)
    assert not any(e['feature'].endswith('_foot_heading') for e in qualified)
    direction_candidate[2, foot] = reference[2, ankle]+Rotation.from_euler('y', 90., degrees=True).apply(vector)
    valid_direction = c.support_initialization_articulation_regressions(
        reference, direction_candidate, names, direction_authority=authority)
    assert not any(e['feature'].endswith('_foot_heading') for e in valid_direction)
    bad = deepcopy(payload)
    bad['sourcePoseCameraReference']['sourcePose']['sourceVideoSha256'] = 'other'
    import pytest
    with pytest.raises(ValueError):
        pv.source_hinge_direction_authority(bad, names)

def test_raised_unknown_contact_keeps_observed_ray_and_calibration_exposure_identity():
    from exercise_motion_pkg.foot_contact_observation import classify_foot_contacts
    from exercise_motion_pkg.material_region_support import calibration_source_slice
    frames = [{'timeSeconds': .2+i/100., 'joints': {
        'right_ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
        'right_heel': {'image': [.49, .51], 'world': [0., 0., 0.], 'confidence': .5},
        'right_toe': {'image': [.54, .54], 'world': [.1, 0., 0.], 'confidence': .99},
    }} for i in range(12)]
    observations = {'available': True, 'source': 'cached_mediapipe', 'fps': 100., 'sourceVideoSha256': 'same-source',
                    'imageWidth': 640, 'imageHeight': 480, 'frames': frames}
    source = {'imageWidth': 640, 'imageHeight': 480, 'frames': [
        {'sourceTimeSec': f['timeSeconds'], 'joints': {'right_ankle': [.5, .5]}} for f in frames]}
    result = classify_foot_contacts(observations, {'contacts': []}, source)
    foot = result['feet']['right']
    assert foot['states'] == ['unknown']*12
    assert not result['contacts']
    assert len(foot['rayObservations']) == 12
    # Unknown raised contact has image direction, without a neutral sole or pin.
    ray = foot['rayObservations'][6]
    row = {'sourceTime': ray['sourceTimeSec'], 'sourceSide': 'right',
           'sourceRay': ray['ankleToToeImageRay'], 'state': 'unknown',
           'leftFrame': 7, 'rightFrame': 8, 'alpha': .25}
    constraint = {'observations': [{'sourceTime': float(i), 'leftFrame': i,
                                   'rightFrame': i, 'alpha': 0.} for i in range(5)],
                  'sourceFootRayObservations': [row]}
    times, joins, sliced = calibration_source_slice(constraint)
    assert ray['sourceTimeSec'] in times
    phase = times.index(ray['sourceTimeSec'])
    assert joins[phase] == (7, 8, .25)
    actual = sliced['sourceFootRayObservations'][0]
    assert actual == {**row, 'leftFrame': phase, 'rightFrame': phase, 'alpha': 0.}
    assert constraint['sourceFootRayObservations'][0] is row
