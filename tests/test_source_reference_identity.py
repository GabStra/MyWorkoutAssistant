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
    assert (loaded == pose) is expected
    metrics = {'sourcePoseReferencePath': str(reference), 'sourceVideoPath': str(video)}
    assert (bake.source_pose_reference_from_phase_metrics(metrics) == pose) is expected


def test_reference_without_source_file_is_unusable(tmp_path):
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({'pose': {'frames': []}, 'sourceVideoSha256': 'abc'}))
    assert bake.load_verified_source_pose_reference(reference, tmp_path / 'missing.mp4') is None


def test_fresh_in_memory_pose_does_not_need_a_disk_roundtrip():
    pose = {'frames': []}
    assert bake.source_pose_reference_from_phase_metrics({'_sourcePoseReference': pose}) is pose


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
