from __future__ import annotations

import importlib.util
from pathlib import Path

import joblib
import numpy as np
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gvhmr_image_parity.py"
SPEC = importlib.util.spec_from_file_location("gvhmr_image_parity", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gvhmr_image_parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gvhmr_image_parity)


def _write_motion(path: Path, translation: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({0: {
        "pose_world": np.zeros((3, 72), dtype=np.float32),
        "trans_world": translation.astype(np.float32),
        "betas": np.zeros(10, dtype=np.float32),
        "frame_ids": [0, 1, 2],
        "betasSource": "neutral_smpl",
    }}, path)


@pytest.mark.parametrize("run_id", ("../outside", "..", "C:\\outside", ""))
def test_run_id_cannot_escape_parity_root(run_id: str) -> None:
    with pytest.raises(ValueError, match="run id"):
        gvhmr_image_parity.validate_run_id(run_id)


def test_pkl_parity_checks_motion_arrays_and_schema(tmp_path: Path) -> None:
    reference = tmp_path / "reference.pkl"
    identical = tmp_path / "identical.pkl"
    changed = tmp_path / "changed.pkl"
    translation = np.zeros((3, 3), dtype=np.float32)
    _write_motion(reference, translation)
    _write_motion(identical, translation.copy())
    changed_translation = translation.copy()
    changed_translation[1, 0] = 0.01
    _write_motion(changed, changed_translation)

    assert gvhmr_image_parity.compare_motion_outputs(reference, identical)["identical"]
    comparison = gvhmr_image_parity.compare_motion_outputs(reference, changed)
    assert not comparison["identical"]
    assert not comparison["fields"]["trans_world"]["equal"]
