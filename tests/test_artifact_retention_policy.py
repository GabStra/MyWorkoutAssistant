from __future__ import annotations

import json
from pathlib import Path


from exercise_motion_pkg.bake_and_rank import (
    ARTIFACT_RETENTION_DEBUG,
    ARTIFACT_RETENTION_FULL,
    apply_artifact_retention_policy,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_workspace(root: Path) -> dict[str, Path]:
    cache_key = "2460aa2b261409588703f820debceac6e8cfc2a0e2c9eded68b727a8f8c94c4a"
    shared_dir = root / "reconstruction-cache" / cache_key
    shared_pkl = shared_dir / "reconstruction_output.pkl"
    nested_shared_pkl = shared_dir / "features" / "preprocessed.pkl"
    cache_manifest = shared_dir / "cache_manifest.json"
    local_pkl = (
        root
        / "dumbbell-woodchopper-001"
        / "raw"
        / "reconstruction"
        / cache_key
        / "reconstruction_output.pkl"
    )
    local_motion = root / "dumbbell-woodchopper-001" / "raw" / "motion.raw.json"
    disposable_pkl = root / "candidate-debug" / "scratch.pkl"
    sibling_pkl = root / "reconstruction-cache-sibling" / "other.pkl"

    shared_pkl.parent.mkdir(parents=True, exist_ok=True)
    shared_pkl.write_bytes(b"shared-reconstruction")
    nested_shared_pkl.parent.mkdir(parents=True, exist_ok=True)
    nested_shared_pkl.write_bytes(b"nested-shared-reconstruction")
    cache_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "cacheKey": cache_key,
                "sourceResultsPkl": str(local_pkl),
                "canonicalPklPath": str(shared_pkl),
            }
        ),
        encoding="utf-8",
    )
    local_pkl.parent.mkdir(parents=True, exist_ok=True)
    local_pkl.write_bytes(b"candidate-local-reconstruction")
    _write(local_motion, json.dumps({"schemaVersion": 1, "frames": []}))
    disposable_pkl.parent.mkdir(parents=True, exist_ok=True)
    disposable_pkl.write_bytes(b"disposable-debug")
    sibling_pkl.parent.mkdir(parents=True, exist_ok=True)
    sibling_pkl.write_bytes(b"unrelated-cache-content")

    manifest = {
        "schemaVersion": 1,
        "selected": {"candidateWorkspace": "dumbbell-woodchopper-001"},
        "selectedResults": [],
        "candidateResults": [],
        "timings": {"reconstruction": {"globalCachePath": str(shared_pkl)}},
    }
    return {
        "manifest": manifest,  # type: ignore[dict-item]
        "shared_pkl": shared_pkl,
        "nested_shared_pkl": nested_shared_pkl,
        "cache_manifest": cache_manifest,
        "local_pkl": local_pkl,
        "disposable_pkl": disposable_pkl,
        "sibling_pkl": sibling_pkl,
    }


def test_debug_retention_preserves_shared_cache_root_and_descendants(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = _build_workspace(workspace)

    summary = apply_artifact_retention_policy(
        workspace,
        paths["manifest"],  # type: ignore[arg-type]
        mode=ARTIFACT_RETENTION_DEBUG,
    )

    assert summary["mode"] == ARTIFACT_RETENTION_DEBUG
    assert summary["errors"] == []
    assert paths["shared_pkl"].is_file()
    assert paths["nested_shared_pkl"].is_file()
    assert paths["cache_manifest"].is_file()
    assert not paths["disposable_pkl"].exists()
    assert not paths["sibling_pkl"].exists()
    assert Path("candidate-debug/scratch.pkl") in {
        Path(sample) for sample in summary["removedPathSamples"]
    }


def test_full_retention_still_keeps_every_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = _build_workspace(workspace)

    summary = apply_artifact_retention_policy(
        workspace,
        paths["manifest"],  # type: ignore[arg-type]
        mode=ARTIFACT_RETENTION_FULL,
    )

    assert summary["pruned"] is False
    assert paths["shared_pkl"].is_file()
    assert paths["disposable_pkl"].is_file()
    assert paths["sibling_pkl"].is_file()
