from exercise_motion_pkg.llama_defaults import (
    DEFAULT_EXERCISE_CONTRACT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_MODEL,
)
from exercise_motion_pkg.pipeline import GenerateRequest


def test_contract_and_visual_review_use_the_same_qwen_model():
    assert DEFAULT_EXERCISE_CONTRACT_LLAMA_CPP_MODEL == DEFAULT_LLAMA_CPP_MODEL


def test_generation_defaults_to_gvhmr(tmp_path):
    request = GenerateRequest(exercise_slug="sample", workspace=tmp_path)
    assert request.motion_reconstruction_backend == "gvhmr"


def test_direct_generation_rejects_removed_backend(tmp_path):
    with pytest.raises(ValueError, match="Only the GVHMR"):
        GenerateRequest(
            exercise_slug="sample", workspace=tmp_path,
            motion_reconstruction_backend="removed_backend",
        )


def test_gvhmr_spinepose_rejects_camera_pose_merge(tmp_path):
    with pytest.raises(ValueError, match="motion merge mode"):
        GenerateRequest(
            exercise_slug="sample", workspace=tmp_path,
            spinepose_enabled=True, spinepose_merge_mode="legacy_pkl",
        )
import pytest
