import copy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg import pose_fidelity as fidelity
from exercise_motion_pkg import structural_refinement as refinement
from exercise_motion_pkg.models import MotionClip, MotionFrame
from test_bench_pipeline_root_fixes import motion_fixture


def source_fixture(motion, camera_angles=(25., 35., -10.)):
    camera = Rotation.from_euler('xyz', camera_angles, degrees=True)
    return {'frames': [{'sourceTimeSec': f['timeSec'], 'joints': {
        n: (camera.apply(p)[:2] * .4 + [.3, .6]).tolist() for n, p in f['joints'].items()
    }} for f in motion['frames']]}


def test_fixed_camera_keeps_unchanged_joint_errors_unchanged():
    motion = motion_fixture()
    source = source_fixture(motion)
    camera = fidelity.registered_camera_pose_fidelity_metrics(source, motion)
    changed = copy.deepcopy(motion)
    for frame in changed['frames']:
        frame['joints']['left_shoulder'][0] += .2
    metrics = fidelity.registered_camera_pose_fidelity_metrics(source, changed, camera_reference=camera)
    for name in ('left_hip', 'right_hip', 'left_knee', 'right_ankle'):
        assert metrics['perJointMedianErrorBodyRatio'][name] == pytest.approx(
            camera['perJointMedianErrorBodyRatio'][name], abs=1e-12)
    assert metrics['perJointMedianErrorBodyRatio']['left_shoulder'] > .03


def test_partial_camera_reference_is_unavailable():
    motion = motion_fixture()
    metrics = fidelity.registered_camera_pose_fidelity_metrics(source_fixture(motion), motion,
                 camera_reference={'cameraRotation': np.eye(3).tolist()})
    assert not metrics['available']


@pytest.mark.parametrize('trim_start', [0, 5])
@pytest.mark.parametrize('placement_key', ['controlledSourceJoints', 'cameraPlacementReferenceJoints'])
def test_materialized_camera_follows_rigid_placement_without_refitting_output(trim_start, placement_key):
    motion = motion_fixture()
    source = source_fixture(motion)
    camera = fidelity.registered_camera_pose_fidelity_metrics(source, motion)
    rotation = Rotation.from_euler('xyz', [70., -40., 15.], degrees=True)
    placed = copy.deepcopy(motion)
    placed['frames'] = placed['frames'][trim_start:]
    origin = placed['frames'][0]['timeSec']
    for frame in placed['frames']:
        frame['sourceTimeSec'] = frame['timeSec']
        frame['timeSec'] -= origin
        frame['joints'] = {n: (rotation.apply(p) * 1.4 + [3., -2., 1.]).tolist()
                           for n, p in frame['joints'].items()}
        frame[placement_key] = copy.deepcopy(frame['joints'])
        if placement_key == 'cameraPlacementReferenceJoints':
            frame['controlledSourceJoints'] = copy.deepcopy(frame['joints'])
            frame['controlledSourceJoints']['left_wrist'][0] += .2
    placed['sourcePoseCameraReference'] = {'camera': camera, 'sourcePose': source,
                                         'coordinateReference': motion}
    result = fidelity.materialized_camera_pose_fidelity_metrics(source, placed)
    assert result['available']
    assert result['p90JointErrorBodyRatio'] < 1e-6
    selected_source = fidelity.source_pose_reference_for_motion(source, placed)
    selected_result = fidelity.materialized_camera_pose_fidelity_metrics(selected_source, placed)
    assert selected_result['p90JointErrorBodyRatio'] == pytest.approx(result['p90JointErrorBodyRatio'])
    assert result['comparableFrameRatio'] == 1.0
    for frame in placed['frames']:
        frame['joints']['left_wrist'][0] += .4
    damaged = fidelity.materialized_camera_pose_fidelity_metrics(source, placed)
    assert damaged['perJointMedianErrorBodyRatio']['left_wrist'] > .05
    assert damaged['perJointMedianErrorBodyRatio']['left_hip'] == pytest.approx(
        result['perJointMedianErrorBodyRatio']['left_hip'], abs=1e-12)
    for frame in placed['frames']:
        frame[placement_key]['left_hip'][0] += .1
    assert not fidelity.materialized_camera_pose_fidelity_metrics(source, placed)['available']


def test_materialized_camera_rejects_changed_source_evidence():
    motion = motion_fixture()
    source = source_fixture(motion)
    camera = fidelity.registered_camera_pose_fidelity_metrics(source, motion)
    motion['sourcePoseCameraReference'] = {'camera': camera, 'sourcePose': copy.deepcopy(source),
                                         'coordinateReference': {'frames': copy.deepcopy(motion['frames'])}}
    source['frames'][0]['joints']['left_wrist'][0] += .1
    assert not fidelity.materialized_camera_pose_fidelity_metrics(source, motion)['available']


def test_camera_transport_does_not_remove_contact_registration_root_motion():
    motion = motion_fixture()
    source = source_fixture(motion)
    placed = copy.deepcopy(motion)
    placed['sourcePoseCameraReference'] = {'camera': fidelity.registered_camera_pose_fidelity_metrics(source, motion),
                                         'sourcePose': source, 'coordinateReference': motion}
    for index, frame in enumerate(placed['frames']):
        displacement = [.6 * index / (len(placed['frames'])-1), 0., 0.]
        frame['joints'] = {n: np.add(p, displacement).tolist() for n, p in frame['joints'].items()}
        frame['controlledSourceJoints'] = copy.deepcopy(frame['joints'])
    result = fidelity.materialized_camera_pose_fidelity_metrics(source, placed)
    assert result['available']
    assert result['p90JointErrorBodyRatio'] > .05
    assert max(result['cameraReferenceRootTranslationRange']) > .5


@pytest.mark.parametrize('camera_angles', [(25., 35., -10.), (-30., 80., 40.), (75., -15., -60.)])
def test_joint_body_solve_improves_observed_pose_and_preserves_bones(camera_angles):
    motion = motion_fixture()
    target = copy.deepcopy(motion)
    for frame in target['frames']:
        root = np.asarray(frame['joints']['pelvis'])
        rotation = Rotation.from_euler('z', 8., degrees=True)
        for name in refinement.SOURCE_GUIDED_TORSO_JOINTS:
            frame['joints'][name] = (root + rotation.apply(np.asarray(frame['joints'][name])-root)).tolist()
    source = source_fixture(target, camera_angles)
    clip = MotionClip(motion['fps'], motion['jointNames'], [
        MotionFrame(f['timeSec'], {n: tuple(v) for n, v in f['joints'].items()}) for f in motion['frames']])
    proposed, report = refinement._align_body_to_source_pose(clip, source_pose_payload=source)
    assert report['applied']
    before = fidelity.registered_camera_pose_fidelity_metrics(source, motion)
    after = fidelity.registered_camera_pose_fidelity_metrics(source, refinement._motion_clip_pose_payload(proposed),
                                                            camera_reference=before)
    assert after['p90JointErrorBodyRatio'] < before['p90JointErrorBodyRatio']
    for old, new in zip(clip.frames, proposed.frames):
        for a, b in refinement.STRUCTURAL_BONES:
            if a in old.joints and b in old.joints:
                assert np.linalg.norm(np.subtract(new.joints[a],new.joints[b])) == pytest.approx(
                    np.linalg.norm(np.subtract(old.joints[a],old.joints[b])),abs=1e-10)


def test_support_ancestor_paths_remain_fixed(monkeypatch):
    motion = motion_fixture()
    target = copy.deepcopy(motion)
    for frame in target['frames']:
        frame['joints']['left_ankle'][0] += .25
        frame['joints']['right_elbow'][0] += .12
    source = source_fixture(target)
    clip = MotionClip(motion['fps'], motion['jointNames'], [
        MotionFrame(f['timeSec'], {n: tuple(v) for n, v in f['joints'].items()}) for f in motion['frames']])
    monkeypatch.setattr(refinement, '_locked_support_anchor_names', lambda _: {'left_foot'})
    result, report = refinement._align_body_to_source_pose(clip, source_pose_payload=source)
    assert report['applied']
    assert set(('pelvis','left_hip','left_knee','left_ankle','left_foot')).issubset(report['frozenSupportAncestors'])
    for old, new in zip(clip.frames, result.frames):
        for name in ('pelvis','left_hip','left_knee','left_ankle','left_foot'):
            np.testing.assert_allclose(new.joints[name],old.joints[name],atol=1e-12)
