import json
from pathlib import Path

import pytest

from exercise_motion_pkg import stage_cache


def test_cached_paths_rejects_payload_paths_not_covered_by_output_identity(tmp_path: Path) -> None:
    output = tmp_path / "verified.json"
    output.write_text("verified", encoding="utf-8")
    unverified = tmp_path / "unverified.json"
    unverified.write_text("unverified", encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.json"
    stage_cache.save_stage(checkpoint, "key", {"paths": [str(output)]}, [output])

    record = json.loads(checkpoint.read_text(encoding="utf-8"))
    record["payload"]["paths"] = [str(unverified)]
    checkpoint.write_text(json.dumps(record), encoding="utf-8")

    assert stage_cache.load_stage(checkpoint, "key") is None
    computed = []

    def recompute() -> list[Path]:
        computed.append(True)
        return [output]

    assert stage_cache.cached_paths(checkpoint, "key", recompute) == [output]
    assert computed == [True]


def test_cached_paths_treats_a_payload_without_paths_as_a_cache_miss(tmp_path: Path) -> None:
    output = tmp_path / "verified.json"
    output.write_text("verified", encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.json"
    stage_cache.save_stage(checkpoint, "key", {"other": "value"}, [output])
    computed = []

    def recompute() -> list[Path]:
        computed.append(True)
        return [output]

    assert stage_cache.cached_paths(checkpoint, "key", recompute) == [output]
    assert computed == [True]


def test_stage_checkpoint_is_fsynced_before_replacement(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "verified.json"
    output.write_text("verified", encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.json"
    stage_cache.save_stage(checkpoint, "old-key", {"paths": [str(output)]}, [output])
    previous_record = checkpoint.read_text(encoding="utf-8")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("simulated storage flush failure")

    monkeypatch.setattr(stage_cache.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated storage flush failure"):
        stage_cache.save_stage(
            checkpoint, "new-key", {"paths": [str(output)]}, [output]
        )

    assert checkpoint.read_text(encoding="utf-8") == previous_record
    assert not list(tmp_path.glob("checkpoint.json.*.tmp"))
