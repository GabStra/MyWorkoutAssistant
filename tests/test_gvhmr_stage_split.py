import json
from types import SimpleNamespace

from exercise_motion_pkg import gvhmr_warm_worker as worker


def _fixture(tmp_path):
    output_dir = tmp_path / "demo" / "pull"
    preprocess_dir = output_dir / "preprocess"
    preprocess_dir.mkdir(parents=True)
    source = tmp_path / "selected.mp4"
    source.write_bytes(b"source-video-a")
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"model")
    bridge = tmp_path / "gvhmr_inference.py"
    bridge.write_text("bridge", encoding="utf-8")
    paths = SimpleNamespace(
        bbx=preprocess_dir / "bbx.pt",
        vitpose=preprocess_dir / "vitpose.pt",
        vit_features=preprocess_dir / "vit_features.pt",
        slam=preprocess_dir / "slam_results.pt",
    )
    for path in (paths.bbx, paths.vitpose, paths.vit_features):
        path.write_bytes(path.name.encode())
    cfg = SimpleNamespace(
        output_dir=output_dir,
        preprocess_dir=preprocess_dir,
        ckpt_path=checkpoint,
        f_mm=None,
        use_dpvo=False,
        static_cam=True,
        paths=paths,
    )
    return cfg, source, bridge, paths.vit_features


def test_preprocess_handoff_binds_source_config_image_and_artifact_bytes(tmp_path):
    cfg, source, bridge, artifact = _fixture(tmp_path)
    manifest = worker._preprocess_manifest_path(cfg)
    worker.write_json(manifest, {
        "version": 1,
        "identity": worker._preprocess_identity(
            cfg=cfg, video_path=source, static_cam=True,
            image_identity="sha256:image-a", inference_script=bridge,
        ),
        "artifacts": worker._tree_file_manifest(cfg.preprocess_dir),
    })

    assert worker._verify_preprocess_manifest(
        cfg=cfg, video_path=source, static_cam=True,
        image_identity="sha256:image-a", inference_script=bridge,
    )
    assert not worker._verify_preprocess_manifest(
        cfg=cfg, video_path=source, static_cam=True,
        image_identity="sha256:image-b", inference_script=bridge,
    )
    source.write_bytes(b"source-video-b")
    assert not worker._verify_preprocess_manifest(
        cfg=cfg, video_path=source, static_cam=True,
        image_identity="sha256:image-a", inference_script=bridge,
    )
    source.write_bytes(b"source-video-a")
    artifact.write_bytes(b"modified features")
    assert not worker._verify_preprocess_manifest(
        cfg=cfg, video_path=source, static_cam=True,
        image_identity="sha256:image-a", inference_script=bridge,
    )
    artifact.unlink()
    assert not worker._verify_preprocess_manifest(
        cfg=cfg, video_path=source, static_cam=True,
        image_identity="sha256:image-a", inference_script=bridge,
    )


def test_same_frame_count_new_source_bytes_force_copy_refresh(tmp_path):
    source, copied = tmp_path / "source.mp4", tmp_path / "copied.mp4"
    receipt = tmp_path / "copied.mp4.source.json"
    source.write_bytes(b"frames-A")
    copied.write_bytes(b"encoded")
    receipt.write_text(json.dumps({
        "sha256": worker._sha256_file(source),
        "copiedSha256": worker._sha256_file(copied),
    }), encoding="utf-8")

    assert not worker._source_copy_needs_refresh(
        source_video=source, copied_video=copied, source_receipt=receipt,
        source_frame_count=84, copied_frame_count=84,
    )
    source.write_bytes(b"frames-B")
    assert worker._source_copy_needs_refresh(
        source_video=source, copied_video=copied, source_receipt=receipt,
        source_frame_count=84, copied_frame_count=84,
    )
