import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest


def test_marker_pair_origin_is_a_measurement_invariant_and_rejects_impossible_span():
    from exercise_motion_pkg.contact_heel_pitch import marker_pair_region_translation

    heel, toe = np.asarray([.2, -.1, .3]), np.asarray([.7, .2, .8])
    low, high = np.zeros(3), np.ones(3)
    vector = heel - toe
    projection = np.asarray([[.4, .1, .2], [0., -.5, .1]])
    translation = marker_pair_region_translation(heel, toe, low, high)
    np.testing.assert_array_equal(translation, [0., .1, 0.])
    np.testing.assert_allclose((heel + translation) - (toe + translation), vector, atol=1e-15)
    np.testing.assert_allclose(projection @ ((heel + translation) - (toe + translation)),
                               projection @ vector, atol=1e-15)
    assert np.all(heel + translation >= low) and np.all(toe + translation <= high)
    np.testing.assert_array_equal(marker_pair_region_translation(heel + translation, toe + translation, low, high),
                                  np.zeros(3))
    assert marker_pair_region_translation([-.5, 0., 0.], [.7, .1, .1], low, high) is None


def test_anatomical_inverse_clearance_is_virtual_and_never_translates_an_anchor():
    from exercise_motion_pkg.contact_heel_pitch import anatomical_marker_foot_geometry

    ankle, toe = np.asarray([0., .02, -.15]), np.asarray([0., -.01, 0.])
    direction = (toe - ankle) / np.linalg.norm(toe - ankle)
    rest = float(np.arcsin(direction[1]))
    marker = np.asarray([-.2, .01, -.03])
    before = anatomical_marker_foot_geometry(ankle, toe, direction, marker, rest, .2, None)
    free = anatomical_marker_foot_geometry(ankle, toe, direction, marker, rest, .2, 0.)
    np.testing.assert_array_equal(free['vector'], before['vector'])
    np.testing.assert_allclose(free['virtualClearance'], [0., -before['vertices'][:, 1].min(), 0.], atol=1e-15)
    assert free['vertices'][:, 1].min() >= -1e-15
    for ownership in ({'toe_anchor': toe}, {'ankle_anchor': ankle},
                      {'ankle_anchor': ankle, 'toe_anchor': toe}):
        pinned = anatomical_marker_foot_geometry(
            ankle, toe, direction, marker, rest, .2, 0., **ownership)
        np.testing.assert_array_equal(pinned['virtualClearance'], np.zeros(3))
        for field in ('ankle', 'toe'):
            if field + '_anchor' in ownership:
                np.testing.assert_array_equal(pinned[field], ownership[field + '_anchor'])
        assert -pinned['vertices'][:, 1].min() > .002


def test_named_marker_prior_roundtrips_preview_bake_and_shared_correspondence(tmp_path, monkeypatch):
    torch = pytest.importorskip('torch')
    pytest.importorskip('smplx')
    from smplx.vertex_ids import vertex_ids
    from exercise_motion_pkg import preview, controlled_motion as motion
    from exercise_motion_pkg.contact_heel_pitch import (
        anatomical_foot_frame, calibrate_anatomical_heel_markers)
    from exercise_motion_pkg.models import MotionClip, MotionFrame
    from exercise_motion_pkg.reconstruction_convert import _named_foot_marker_prior
    from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES

    joints = np.zeros((24, 3), dtype=np.float32)
    for index in (0, 3, 6, 9, 12, 15):
        joints[index, 1] = 1. + index * .04
    vertices = np.zeros((6890, 3), dtype=np.float32)
    weights = torch.zeros(6890, 24)
    weights[:, 0] = 1.
    for side, prefix, ankle, foot, x, first in (
            ('left', 'L', 7, 10, -.15, 0), ('right', 'R', 8, 11, .15, 8)):
        joints[ankle], joints[foot] = [x, .1, 0.], [x, .1, .2]
        selected = [vertex_ids['smplh'][prefix + name] for name in ('Heel', 'BigToe', 'SmallToe')]
        vertices[selected] = [[x, 0., -.05], [x - .02, 0., .2], [x + .02, 0., .2]]
        corners = [[x + dx, y, z] for dx in (-.04, .04) for y in (-.02, .15) for z in (-.07, .25)]
        vertices[first:first + 8] = corners
        for index in selected + list(range(first, first + 8)):
            weights[index] = 0.
            weights[index, ankle] = 1.
    model = SimpleNamespace(
        lbs_weights=weights)
    # The owning converter already has an evaluated model; only its neutral call is needed.
    class NeutralModel:
        lbs_weights = model.lbs_weights

        def __call__(self, **kwargs):
            return SimpleNamespace(vertices=torch.tensor(vertices[None]), joints=torch.tensor(joints[None]))

    asset = tmp_path / 'models' / 'smpl' / 'SMPL_NEUTRAL.pkl'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'controlled model asset')
    reconstruction = tmp_path / 'cached.pkl'
    reconstruction.write_bytes(b'controlled reconstruction identity')
    prior = _named_foot_marker_prior(
        NeutralModel(), torch.zeros(1, 10), reconstruction, asset.parent.parent,
        {'sourceVideoSha256': 'e' * 64, 'outputVideoSha256': 'f' * 64})
    assert prior['sides']['left']['heelVertex'] == vertex_ids['smplh']['LHeel']
    names = list(SMPL_JOINT_NAMES)
    clip = MotionClip(
        fps=30., joint_names=names,
        frames=[MotionFrame(index / 30., dict(zip(names, joints.tolist())),
                            source_time_sec=index / 30.) for index in range(5)],
        metadata={'motionTuning': {'enabled': False}, 'reconstruction': {'footMarkerPrior': prior}})
    captured = []
    monkeypatch.setattr(preview, '_build_html', lambda payload, **kwargs: captured.append(payload) or '')
    module = tmp_path / 'three.js'
    module.write_text('export {};')
    preview.write_preview_html(tmp_path / 'preview.html', clip, title='marker', three_module_path=module)
    baked = {key: captured[-1][key] for key in ('frames', 'fps', 'jointNames', 'rootJoint', 'sourceFootMarkerPrior')}
    baked['footRestPitchRadians'] = {'left': 0., 'right': 0.}
    baked['sourceFootSupportEvidence'] = {'sourceVideoSha256': 'e' * 64}
    baked['sourcePoseCameraReference'] = {'sourceTimelineMapping': {
        'selectedSegmentSha256': 'e' * 64, 'parentClockOutputSha256': 'f' * 64}}
    preview.write_baked_preview_html(tmp_path / 'baked.html', baked, three_module_path=module)
    assert captured[-1]['sourceFootMarkerPrior'] == prior
    points = np.asarray([[frame['joints'][name] for name in names] for frame in baked['frames']])
    projection = np.asarray([[.4, 0., .15], [0., .4, 0.]])
    rows, contexts = [], {}
    for side in ('left', 'right'):
        vector = points[0, names.index(side + '_foot')] - points[0, names.index(side + '_ankle')]
        observed = projection @ anatomical_foot_frame(vector) @ np.asarray(prior['sides'][side]['heelToToeLocalMeters'])
        contexts[side] = []
        for index in range(3):
            row = {'motionSide': side, 'state': 'full_sole', 'sourceFeature': 'anatomical_heel_to_toe',
                   'leftFrame': index, 'rightFrame': index, 'alpha': 0., 'sourceTime': index / 30.,
                   'sourceHeelToToeVector': observed}
            rows.append(row)
            contexts[side].append(row)
    calibrated = calibrate_anatomical_heel_markers(baked, points, names, projection, rows, contexts)
    assert set(calibrated) == {'left', 'right'}
    moved_candidate = points.copy()
    moved_candidate[:, names.index('left_ankle'), 0] += .04
    assert calibrate_anatomical_heel_markers(
        baked, moved_candidate, names, projection, rows, contexts) == calibrated
    for row in rows:
        row['anatomicalMarkerLocalVector'] = calibrated[row['motionSide']]['localVector']
    constraint = {'projection': projection, 'footGeometryPayload': baked}
    np.testing.assert_allclose(motion._source_foot_material_heel_vectors(points, constraint, rows),
                               [row['sourceHeelToToeVector'] for row in rows], atol=1e-10)
    # The anatomical radius must not silently become the procedural outsole radius.
    native_rows = [{key: value for key, value in row.items() if key != 'anatomicalMarkerLocalVector'}
                   for row in rows]
    for row in native_rows:
        row['sourceFeature'] = 'native_outsole_heel_to_toe'
    assert not np.allclose(motion._source_foot_material_heel_vectors(points, constraint, native_rows),
                           [row['sourceHeelToToeVector'] for row in rows])
    changed = copy.deepcopy(baked)
    changed['sourcePoseCameraReference']['sourceTimelineMapping']['parentClockOutputSha256'] = 'a' * 64
    assert not calibrate_anatomical_heel_markers(changed, points, names, projection, rows, contexts)
    assert motion.controlled_motion_fit_source_evidence_digest(baked) != motion.controlled_motion_fit_source_evidence_digest(
        {**baked, 'sourceFootMarkerPrior': {**prior, 'modelSha256': 'a' * 64}})
    # Moving a contact target changes placement, never the FixedRig foot length
    # used to derive the inverse's physical search domain.
    from exercise_motion_pkg import foot_geometry, contact_heel_pitch
    lengths = []
    original_vertices = foot_geometry.shoe_vertices

    def observe_vertices(ankle, toe, *args, **kwargs):
        lengths.append(float(np.linalg.norm(toe - ankle)))
        return original_vertices(ankle, toe, *args, **kwargs)

    monkeypatch.setattr(foot_geometry, 'shoe_vertices', observe_vertices)
    for row in rows:
        row['sourceNoiseImageUnits'] = 1. / 360.
    targets = points.copy()
    targets[:, names.index('left_foot'), 0] += .08
    targets[:, names.index('right_foot'), 0] -= .08
    pins = np.zeros(points.shape[:2], dtype=bool)
    pins[:, [names.index('left_foot'), names.index('right_foot')]] = True
    inverse_payload = {**baked, 'sourcePoseCameraReference': {'sourcePose': {'imageHeight': 360}}}
    _, inverse = contact_heel_pitch._propose_anatomical_heel_pitch(
        points, names, inverse_payload,
        {**constraint, 'sourceTimeOriginSec': 0., 'sourceFootHeelImageObservations': rows},
        30., None, targets, pinned=pins)
    assert inverse['passed']
    np.testing.assert_allclose(lengths, .2, atol=1e-7)
    # An anchored observation cannot improve an isolated image residual. Keep
    # that residual diagnostic; the existing episode consumer owns acceptance.
    anchored_rows = copy.deepcopy(rows)
    anchored_rows[0]['sourceHeelToToeVector'] = (
        np.asarray(anchored_rows[0]['sourceHeelToToeVector']) + [1.3 / 360., 0.])
    _, anchored_inverse = contact_heel_pitch._propose_anatomical_heel_pitch(
        points, names, inverse_payload,
        {**constraint, 'sourceTimeOriginSec': 0., 'sourceFootHeelImageObservations': anchored_rows},
        30., None, points, pinned=np.ones(points.shape[:2], dtype=bool))
    assert anchored_inverse['passed']
    assert anchored_inverse['inversionFailureCount'] == 0
    assert anchored_inverse['sourceImageNoiseExceedances']
    json.dumps(prior)
