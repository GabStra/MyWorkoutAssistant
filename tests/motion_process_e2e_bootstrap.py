"""Test-only import hooks for the staged movement process E2E."""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys
from typing import Any


CONFIG_ENV = "EXERCISE_MOTION_PROCESS_E2E_CONFIG"


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
                reuse_wham_cache=True,
                structural_refinement_enabled=True,
            )
        )
        result_cache_status = str(result.wham_cache_status)
        _record(
            config,
            "generation_complete",
            owner=fullname,
            manifestPath=str(result.manifest_path),
            cacheStatus=result_cache_status,
            generationCheckpoint=(result.timings or {}).get("generationCheckpoint"),
        )
        if result_cache_status == "reused_processed":
            _record(
                config,
                "generation_cache_hit",
                owner=fullname,
                candidateSlug=candidate.workspace_slug,
                workspace=str(Path(request.workspace).resolve()),
                cacheStatus=result_cache_status,
            )
        return result

    if fullname == "exercise_motion_pkg.bake_and_rank":
        module.generate_candidate_motion = generate_from_normalized_fixture

        production_exact_source_validator = module.validate_exact_source_with_cached_gpu_handoff

        def validate_exact_source_from_seeded_cache(**kwargs: Any) -> dict[str, Any]:
            source_video_path = Path(kwargs["source_video_path"])
            cache_path = Path(kwargs["cache_path"])
            cache_key_payload, cache_key = module.exact_source_phase_validation_cache_key(
                source_video_path=source_video_path,
                exercise_name=str(kwargs["exercise_name"]),
                exercise_motion_contract=kwargs.get("exercise_motion_contract"),
            )
            expected_cache_key = config.get("sourceValidationCacheKey")
            if expected_cache_key and cache_key != expected_cache_key:
                raise AssertionError(
                    "Production exact-source cache identity differs from the seeded fixture"
                )
            candidate_cache_paths = [cache_path]
            shared_cache_dir = kwargs.get("shared_cache_dir")
            if shared_cache_dir is not None:
                candidate_cache_paths.insert(
                    0,
                    Path(shared_cache_dir) / cache_key / cache_path.name,
                )
            cache_hit_path = next(
                (
                    candidate_path
                    for candidate_path in candidate_cache_paths
                    if module.load_cached_exact_source_phase_validation(
                        cache_path=candidate_path,
                        cache_key=cache_key,
                    )
                    is not None
                ),
                None,
            )
            if cache_hit_path is None:
                _record(
                    config,
                    "source_validation_cache_miss",
                    sourceVideoPath=str(source_video_path.resolve()),
                    cacheKey=cache_key,
                    candidateCachePaths=[str(path.resolve()) for path in candidate_cache_paths],
                )
                raise AssertionError(
                    "Process E2E requires a matching exact-source cache entry; "
                    "uncached YOLO/model work is disabled."
                )
            result = production_exact_source_validator(**kwargs)
            _record(
                config,
                "source_validation",
                sourceVideoPath=str(source_video_path.resolve()),
                cachePath=str(cache_hit_path.resolve()),
                cacheKey=cache_key,
                sourceVideoSha256=cache_key_payload["videoSha256"],
                cacheStatus=result.get("cacheStatus"),
                validationPolicyVersion=result.get("validationPolicyVersion"),
                sourcePoseReferencePath=result.get("sourcePoseReferencePath"),
            )
            return result

        module.validate_exact_source_with_cached_gpu_handoff = (
            validate_exact_source_from_seeded_cache
        )

        production_final_output_validator = module.validate_final_output_with_caption_images

        def validate_rendered_fixture(
            item: Any,
            ranking: Any,
            *_args: Any,
            **kwargs: Any,
        ) -> dict[str, Any]:
            def deterministic_visual_response(
                *,
                frame_paths: list[Path],
                prompt: str,
                **_request_options: Any,
            ) -> str:
                response = json.dumps(
                    {
                        "findings": [],
                        "note": "Deterministic process E2E visual-review response.",
                    }
                )
                _record(
                    config,
                    "final_visual_review_request",
                    skeletonPath=str(item.skeleton_path.resolve()),
                    promptCharacters=len(prompt),
                    framePaths=[str(path.resolve()) for path in frame_paths],
                    response=response,
                )
                return response

            validator_kwargs = dict(kwargs)
            validator_kwargs["caption_images"] = deterministic_visual_response
            result = production_final_output_validator(
                item,
                ranking,
                *_args,
                **validator_kwargs,
            )
            _record(
                config,
                "final_visual_review",
                skeletonPath=str(item.skeleton_path.resolve()),
                parserStatus=result.get("status"),
                advisoryOnly=result.get("advisoryOnly"),
                discardedFindingCount=result.get("discardedFindingCount"),
                rawResponse=result.get("rawResponse"),
                parsedResponsePath=result.get("parsedResponsePath"),
                cacheMetadataPath=result.get("cacheMetadataPath"),
            )
            return result

        module.validate_final_output_with_caption_images = validate_rendered_fixture

    elif fullname == "exercise_motion_pkg.wave_pipeline":
        module.generate_candidate_motion = generate_from_normalized_fixture

    elif fullname == "exercise_motion_pkg.body_support_observation":
        production_body_support_observer = module.observe_body_support

        def observe_seeded_body_support_cache(
            video_path: str | Path,
            caption_images: Any,
            cache_dir: str | Path,
        ) -> dict[str, Any]:
            video_path = Path(video_path)
            digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
            cache_path = (
                Path(cache_dir)
                / f"body-support-{digest}-v{module.POLICY_VERSION}.json"
            )
            expected_cache_path = config.get("bodySupportCachePath")
            expected_video_digest = config.get("bodySupportSourceVideoSha256")
            if (
                expected_cache_path
                and cache_path.resolve() != Path(expected_cache_path).resolve()
            ) or (expected_video_digest and digest != expected_video_digest):
                raise AssertionError(
                    "Production body-support cache identity differs from the seeded fixture"
                )
            if not cache_path.is_file():
                _record(
                    config,
                    "body_support_cache_miss",
                    sourceVideoPath=str(video_path.resolve()),
                    cachePath=str(cache_path.resolve()),
                    sourceVideoSha256=digest,
                )
                raise AssertionError(
                    "Process E2E requires a seeded body-support cache entry; "
                    "uncached visual-model work is disabled."
                )

            def reject_uncached_visual_call(**_kwargs: Any) -> str:
                _record(
                    config,
                    "body_support_visual_call_unexpected",
                    sourceVideoPath=str(video_path.resolve()),
                )
                raise AssertionError("Body-support fixture cache unexpectedly missed")

            result = production_body_support_observer(
                video_path,
                reject_uncached_visual_call,
                cache_dir,
            )
            cache_hit = (
                result.get("sourceVideoSha256") == digest
                and result.get("policyVersion") == module.POLICY_VERSION
            )
            _record(
                config,
                "body_support_observation",
                sourceVideoPath=str(video_path.resolve()),
                cachePath=str(cache_path.resolve()),
                sourceVideoSha256=digest,
                policyVersion=result.get("policyVersion"),
                cacheHit=cache_hit,
                status=result.get("status"),
            )
            if not cache_hit:
                raise AssertionError("Body-support observer returned a mismatched cache entry")
            return result

        module.observe_body_support = observe_seeded_body_support_cache


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
