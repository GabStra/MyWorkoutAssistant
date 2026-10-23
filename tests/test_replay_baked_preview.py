import hashlib
import json

from exercise_motion_pkg.body_support_observation import POLICY_VERSION
from scripts.replay_baked_preview import _copy_retained_inputs


def test_retained_replay_copies_the_active_clip_support_cache(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    video = source / "input" / "selected_segment.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"retained selected clip")
    source_pose = source / "segment_detection" / "exact_source_pose_reference.json"
    source_pose.parent.mkdir(parents=True)
    source_pose.write_text("{}", encoding="utf-8")
    cleaned_motion = source / "cleaned" / "motion.cleaned.json"
    cleaned_motion.parent.mkdir(parents=True)
    cleaned_motion.write_text("{}", encoding="utf-8")

    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    cache_dir = source / "segment_detection" / "body_support"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"body-support-{digest}-v3.json").write_text("stale", encoding="utf-8")
    active_cache = cache_dir / f"body-support-{digest}-v{POLICY_VERSION}.json"
    active_cache.write_text(json.dumps({"status": "observed"}), encoding="utf-8")

    _copy_retained_inputs(source, output)

    copied_cache = output / active_cache.relative_to(source)
    assert json.loads(copied_cache.read_text(encoding="utf-8")) == {"status": "observed"}
