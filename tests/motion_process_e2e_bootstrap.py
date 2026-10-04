"""Test-only import hooks for the staged movement process E2E."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys
from typing import Any


CONFIG_ENV = "EXERCISE_MOTION_PROCESS_E2E_CONFIG"
_GENERATED_RESULTS: dict[tuple[str, str], Any] = {}


def _config() -> dict[str, Any]:
    config_path = Path(os.environ[CONFIG_ENV])
    return json.loads(config_path.read_text(encoding="utf-8"))


def _record(config: dict[str, Any], event: str, **details: Any) -> None:
    record_path = Path(config["callsPath"])
    record_path.parent.mkdir(parents=True, exist_ok=True)
    with record_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": event, **details}, sort_keys=True) + "\n")


def _patch_module(fullname: str, module: Any) -> None:
    config = _config()

    def generate_from_normalized_fixture(
        candidate: Any,
        *,
        request: Any,
        prepared_video_path: str | Path,
        **_kwargs: Any,
    ) -> Any:
        from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline

        _record(
            config,
            "generation",
            owner=fullname,
            candidateSlug=candidate.workspace_slug,
            preparedVideoPath=str(prepared_video_path),
        )
        cache_key = (
            str(candidate.workspace_slug),
            str(Path(request.workspace).resolve()),
        )
        cached_result = _GENERATED_RESULTS.get(cache_key)
        if cached_result is not None:
            _record(
                config,
                "generation_cache_hit",
                owner=fullname,
                candidateSlug=candidate.workspace_slug,
                workspace=cache_key[1],
            )
            return cached_result
        result = run_generation_pipeline(
            GenerateRequest(
                exercise_slug=candidate.workspace_slug,
                workspace=request.workspace,
                video_path=Path(prepared_video_path),
                normalized_motion_json=Path(config["normalizedMotionPath"]),
                motion_reconstruction_backend="wham",
                ground_contact_mode="intermittent",
                support_mode_hint="standing",
                source_pose_reference_path=Path(config["sourcePoseReferencePath"]),
                reuse_wham_cache=False,
                structural_refinement_enabled=True,
            )
        )
        _record(
            config,
            "generation_complete",
            owner=fullname,
            manifestPath=str(result.manifest_path),
        )
        _GENERATED_RESULTS[cache_key] = result
        return result

    if fullname == "exercise_motion_pkg.bake_and_rank":
        module.generate_candidate_motion = generate_from_normalized_fixture

        def validate_exact_source(**kwargs: Any) -> dict[str, Any]:
            _record(
                config,
                "source_validation",
                sourceVideoPath=str(kwargs["source_video_path"]),
            )
            result = json.loads(
                Path(config["sourceValidationPath"]).read_text(encoding="utf-8")
            )
            result["sourceVideoPath"] = str(Path(kwargs["source_video_path"]).resolve())
            return result

        module.validate_exact_source_with_cached_gpu_handoff = validate_exact_source

        def validate_rendered_fixture(item: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            _record(config, "final_visual_review", skeletonPath=str(item.skeleton_path))
            return {"advisoryOnly": True, "status": "observed", "findings": []}

        module.validate_final_output_with_caption_images = validate_rendered_fixture

    elif fullname == "exercise_motion_pkg.wave_pipeline":
        module.generate_candidate_motion = generate_from_normalized_fixture

    elif fullname == "exercise_motion_pkg.body_support_observation":

        def observe_fixture_support(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "status": "observed",
                "source": "process_e2e_test_model_boundary",
                "policyVersion": module.POLICY_VERSION,
                "observation": {
                    "torsoSurface": "vertical",
                    "pelvisAndUpperBackSameSurface": False,
                    "pelvis": "moving",
                    "upperBack": "moving",
                    "head": "moving",
                    "leftFoot": "stationary_full_sole",
                    "rightFoot": "stationary_full_sole",
                    "leftFootSurface": "ground",
                    "rightFootSurface": "ground",
                    "leftHand": "moving",
                    "rightHand": "moving",
                    "handsSameHorizontalSurface": False,
                    "observations": "Synthetic squat with both feet planted.",
                },
            }

        module.observe_body_support = observe_fixture_support


class _PatchLoader(importlib.abc.Loader):
    def __init__(self, inner: Any, fullname: str) -> None:
        self._inner = inner
        self._fullname = fullname

    def create_module(self, spec: Any) -> Any:
        create_module = getattr(self._inner, "create_module", None)
        return create_module(spec) if create_module is not None else None

    def exec_module(self, module: Any) -> None:
        self._inner.exec_module(module)
        _patch_module(self._fullname, module)


class _PatchFinder(importlib.abc.MetaPathFinder):
    _TARGETS = {
        "exercise_motion_pkg.bake_and_rank",
        "exercise_motion_pkg.wave_pipeline",
        "exercise_motion_pkg.body_support_observation",
    }

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname not in self._TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and spec.loader is not None:
            spec.loader = _PatchLoader(spec.loader, fullname)
        return spec


def install_import_patches() -> None:
    if CONFIG_ENV in os.environ:
        sys.meta_path.insert(0, _PatchFinder())
