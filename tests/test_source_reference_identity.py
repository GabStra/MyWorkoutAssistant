import hashlib
import json

import pytest

from exercise_motion_pkg import bake_and_rank as bake


@pytest.mark.parametrize('hash_kind,expected', [('matching', True), ('stale', False), ('missing', False)])
def test_pose_reference_requires_exact_video_identity(tmp_path, hash_kind, expected):
    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact selected video bytes')
    pose = {'frames': [{'sourceTimeSec': 0, 'joints': {}}]}
    data = {'pose': pose}
    if hash_kind != 'missing':
        data['sourceVideoSha256'] = hashlib.sha256(video.read_bytes() if hash_kind == 'matching' else b'another window').hexdigest()
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps(data))
    loaded = bake.load_verified_source_pose_reference(reference, video)
    assert (loaded is not None) is expected
    if expected:
        assert loaded['frames'] == pose['frames']
    metrics = {'sourcePoseReferencePath': str(reference), 'sourceVideoPath': str(video)}
    metric_pose = bake.source_pose_reference_from_phase_metrics(metrics)
    assert (metric_pose is not None) is expected
    if expected:
        assert metric_pose['frames'] == pose['frames']


def test_reference_without_source_file_is_unusable(tmp_path):
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({'pose': {'frames': []}, 'sourceVideoSha256': 'abc'}))
    assert bake.load_verified_source_pose_reference(reference, tmp_path / 'missing.mp4') is None


def test_retained_camera_without_verified_frame_clock_is_unavailable(tmp_path):
    workspace = tmp_path / 'candidate'
    segment = workspace / 'segment_detection'
    source = workspace / 'source'
    cleaned = workspace / 'cleaned'
    segment.mkdir(parents=True)
    source.mkdir()
    cleaned.mkdir()

    bounded_cut = source / 'bounded-cut.mp4'
    bounded_cut.write_bytes(b'exact bounded cut bytes')
    (source / 'source.mp4').write_bytes(b'different parent source bytes')
    pose = {'frames': [{'sourceTimeSec': 1.25, 'joints': {'left_ankle': [0.3, 0.8, 0.0]}}]}
    reference = segment / 'exact_source_pose_reference.json'
    reference.write_text(json.dumps({
        'sourceVideoSha256': hashlib.sha256(bounded_cut.read_bytes()).hexdigest(),
        'pose': pose,
    }))
    (segment / 'exact_source_phase_validation.json').write_text(json.dumps({
        'metrics': {
            'sourcePoseReferencePath': str(reference),
            'sourceVideoPath': str(bounded_cut),
            'sourceVideoSha256': hashlib.sha256(bounded_cut.read_bytes()).hexdigest(),
        },
    }))
    (cleaned / 'motion.cleaned.json').write_text(json.dumps({
        'frames': [{'sourceTimeSec': 1.25, 'joints': {'pelvis': [0.0, 0.0, 0.0]}}],
        'metadata': {'structuralRefinement': {'sourceGuidedArticulation': {
            'cameraRegistration': {
                'available': True,
                'cameraImageTransform': [1, 0, 0, 0, 1, 0],
                'bilateralAssignment': 'identity',
            },
        }}},
    }))

    loaded = bake.load_verified_source_pose_reference(
        reference, workspace / 'input' / 'selected_segment.mp4',
    )
    camera = bake.load_baked_source_camera_reference(workspace, loaded)

    assert loaded is not None and loaded['frames'] == pose['frames']
    # The exact pose and source video identity alone do not prove which parent
    # exposures the reconstruction used. A legacy camera without that lineage
    # must be recalibrated rather than silently reused.
    assert camera is None


def test_missing_selected_segment_rejects_mismatched_provenance_video(tmp_path):
    workspace = tmp_path / 'candidate'
    segment = workspace / 'segment_detection'
    segment.mkdir(parents=True)
    expected_cut = tmp_path / 'expected-cut.mp4'
    wrong_source = tmp_path / 'wrong-source.mp4'
    expected_cut.write_bytes(b'exact bounded cut bytes')
    wrong_source.write_bytes(b'different full source bytes')
    reference = segment / 'exact_source_pose_reference.json'
    reference.write_text(json.dumps({
        'sourceVideoSha256': hashlib.sha256(expected_cut.read_bytes()).hexdigest(),
        'pose': {'frames': []},
    }))
    (segment / 'exact_source_phase_validation.json').write_text(json.dumps({
        'metrics': {
            'sourcePoseReferencePath': str(reference),
            'sourceVideoPath': str(wrong_source),
            'sourceVideoSha256': hashlib.sha256(expected_cut.read_bytes()).hexdigest(),
        },
    }))

    assert bake.load_verified_source_pose_reference(
        reference, workspace / 'input' / 'selected_segment.mp4',
    ) is None


@pytest.mark.parametrize(('video_bytes', 'expected'), [
    (b'exact source bytes', True),
    (b'replaced source bytes', False),
])
def test_embedded_pose_reference_is_bound_to_current_video_identity(tmp_path, video_bytes, expected):
    video = tmp_path / 'selected.mp4'
    video.write_bytes(video_bytes)
    pose = {'frames': []}
    metrics = {
        '_sourcePoseReference': pose,
        'sourceVideoPath': str(video),
        'sourceVideoSha256': hashlib.sha256(b'exact source bytes').hexdigest(),
    }

    loaded = bake.source_pose_reference_from_phase_metrics(metrics)

    assert (loaded is not None) is expected
    if expected:
        assert loaded['frames'] == pose['frames']


def test_embedded_pose_prefers_exact_reference_file_when_available(tmp_path):
    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact source bytes')
    pose = {'frames': [{'sourceTimeSec': 0, 'joints': {}}]}
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({
        'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
        'pose': pose,
    }))
    metrics = {
        '_sourcePoseReference': {'frames': [{'sourceTimeSec': 9, 'joints': {}}]},
        'sourcePoseReferencePath': str(reference),
        'sourceVideoPath': str(video),
        'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
    }

    loaded = bake.source_pose_reference_from_phase_metrics(metrics)

    assert loaded is not None
    assert loaded['frames'] == pose['frames']


def test_embedded_pose_rejects_mismatch_with_callers_current_video(tmp_path):
    retained_video = tmp_path / 'retained.mp4'
    current_video = tmp_path / 'current.mp4'
    retained_video.write_bytes(b'retained source bytes')
    current_video.write_bytes(b'new source bytes')
    pose = {'frames': []}
    metrics = {
        '_sourcePoseReference': pose,
        'sourceVideoPath': str(retained_video),
        'sourceVideoSha256': hashlib.sha256(retained_video.read_bytes()).hexdigest(),
    }

    assert bake.source_pose_reference_from_phase_metrics(
        metrics, source_video_path=current_video,
    ) is None


def test_retention_preserves_selected_processing_evidence_only(tmp_path):
    chosen = tmp_path / 'chosen'
    other = tmp_path / 'other'
    for candidate in (chosen, other):
        (candidate / 'raw').mkdir(parents=True)
        (candidate / 'cleaned').mkdir()
        for relative in ('raw/motion.raw.json', 'cleaned/motion.cleaned.json', 'manifest.json'):
            (candidate / relative).write_text('{}')
    protected = bake.collect_artifact_retention_protected_paths(tmp_path, {'selected': {'candidateWorkspace': str(chosen)}})
    assert (chosen / 'raw/motion.raw.json').resolve() in protected
    assert (chosen / 'cleaned/motion.cleaned.json').resolve() in protected
    assert (other / 'raw/motion.raw.json').resolve() not in protected
