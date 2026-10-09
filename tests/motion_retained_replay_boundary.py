"""Pinned source IO with retained or fresh reconstruction; reviews stay real.

Used only by the opt-in process replay bootstrap. This does not fabricate model
verdicts. Every source input is pinned by bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


def verified_file(fixture: dict[str, Any], field: str) -> Path:
    path = Path(fixture[field]).resolve()
    expected = fixture[field + "Sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise AssertionError(f"Retained replay input changed: {field}: {path}")
    return path


def patch_module(fullname: str, module: Any, config: dict[str, Any], record: Any) -> None:
    fixtures = config["exerciseFixtures"]

    def fixture_for_url(url: str) -> dict[str, Any]:
        matches = [item for item in fixtures.values() if item["videoId"] in url]
        if len(matches) != 1:
            raise AssertionError(f"Unpinned source request: {url}")
        return matches[0]

    def download(url: str, destination_dir: str | Path, *_args: Any, **_kwargs: Any) -> Path:
        fixture = fixture_for_url(url)
        source = verified_file(fixture, "sourceVideoPath")
        target = Path(destination_dir) / (fixture["videoId"] + ".mp4")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        record(config, "retained_source_io", videoId=fixture["videoId"],
               sha256=fixture["sourceVideoPathSha256"], destination=str(target))
        return target

    if fullname == "exercise_motion_pkg.youtube":
        def search(query: str, results_per_query: int, **_kwargs: Any) -> list[Any]:
            matches = [item for item in fixtures.values()
                       if item["exerciseName"].casefold() in query.casefold()]
            if len(matches) != 1:
                raise AssertionError(f"Unpinned discovery query: {query}")
            fixture = matches[0]
            record(config, "retained_discovery_io", query=query, videoId=fixture["videoId"])
            return module.parse_yt_dlp_search_results({"entries": [{
                "id": fixture["videoId"], "title": fixture["candidateTitle"],
                "channel": fixture["channel"], "duration": fixture["durationSeconds"],
                "view_count": 1000,
            }]})[:results_per_query]

        module.search_youtube = search
        module.download_youtube_preview = download
        return

    if fullname not in {"exercise_motion_pkg.bake_and_rank", "exercise_motion_pkg.wave_pipeline"}:
        return

    if fullname == "exercise_motion_pkg.bake_and_rank":
        module.download_youtube = download
    production_generate_candidate_motion = module.generate_candidate_motion

    def generate(candidate: Any, *, request: Any, prepared_video_path: Path | None = None,
                 stage_identity: dict[str, Any] | None = None, **generation_kwargs: Any) -> Any:
        from exercise_motion_pkg import bake_and_rank as bake
        from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline

        fixture = fixtures[candidate.exercise_id]
        selected = verified_file(fixture, "sourceVideoPath")
        selection_path = (
            request.workspace
            / candidate.workspace_slug
            / "segment_detection/segment_selection.json"
        )
        if not selection_path.is_file():
            raise AssertionError("Production source interval evidence is missing before reconstruction replay")
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selected_source = Path(selection["sourceVideoPath"]).resolve()
        selected_source_hash = hashlib.sha256(selected_source.read_bytes()).hexdigest()
        if selected_source_hash != fixture["sourceVideoPathSha256"]:
            raise AssertionError("Production source selection does not use the pinned retained clip")
        selected_segment = Path(selection["selectedSegmentPath"]).resolve()
        if not selected_segment.is_file():
            raise AssertionError("Production-reviewed selected segment is missing before reconstruction replay")
        span = selection.get("selectedSpanInOriginalSource") or {}
        from exercise_motion_pkg.video_utils import read_basic_video_metadata
        metadata = read_basic_video_metadata(selected)
        source_duration = metadata.frame_count / metadata.fps
        frame_tolerance = 1.0 / metadata.fps
        if (
            float(span.get("startSeconds", -1)) > frame_tolerance
            or abs(float(span.get("endSeconds", -1)) - source_duration) > frame_tolerance
        ):
            raise AssertionError("Production source review selected an interval that differs from retained reconstruction")
        if prepared_video_path is not None:
            prepared_path = Path(prepared_video_path).resolve()
            if prepared_path != selected_segment:
                raise AssertionError("Staged source differs from the production-reviewed selected segment")
            prepared_metadata = read_basic_video_metadata(prepared_path)
            if (prepared_metadata.frame_count != metadata.frame_count
                    or abs(prepared_metadata.fps - metadata.fps) > 0.001):
                raise AssertionError("Staged source timeline differs from retained reconstruction")
        retained_reconstruction = (
            config.get("mode") == "retained_reconstruction_real_review"
        )
        raw = verified_file(fixture, "normalizedMotionPath") if retained_reconstruction else None
        contract = bake.exercise_motion_contract_from_candidate(candidate.candidate)
        pose = request.workspace / candidate.workspace_slug / "segment_detection/exact_source_pose_reference.json"
        if not pose.is_file():
            raise AssertionError("Production exact-source pose evidence is missing before reconstruction replay")
        record(config,
               "retained_reconstruction_boundary" if retained_reconstruction else "fresh_reconstruction_boundary",
               exerciseId=candidate.exercise_id,
               sourceSha256=fixture["sourceVideoPathSha256"],
               rawSha256=fixture.get("normalizedMotionPathSha256") if retained_reconstruction else None,
               upstreamIdentity=fixture.get("upstreamIdentity") if retained_reconstruction else None,
               inferenceCacheReuse=False if not retained_reconstruction else None,
               owner=fullname,
               selectedSourcePath=str(selected), stagedSourcePath=(
                   str(Path(prepared_video_path).resolve()) if prepared_video_path is not None else None
               ), selectedSpan=span)
        if not retained_reconstruction:
            from dataclasses import replace

            fresh_request = replace(
                request,
                reuse_reconstruction_cache=False,
                require_reconstruction_cache=False,
            )
            return production_generate_candidate_motion(
                candidate,
                request=fresh_request,
                prepared_video_path=prepared_video_path,
                stage_identity=stage_identity,
                **generation_kwargs,
            )
        return run_generation_pipeline(GenerateRequest(
            exercise_slug=candidate.workspace_slug, workspace=request.workspace,
            video_path=selected, normalized_motion_json=raw,
            motion_reconstruction_backend=request.motion_reconstruction_backend,
            ground_contact_mode=str((contract or {}).get("groundContactMode") or "unknown"),
            support_mode_hint=bake.exercise_support_mode_hint(
                exercise_name=candidate.exercise_name, exercise_motion_contract=contract),
            rigid_paired_hands_required=bake.exercise_motion_contract_requires_rigid_paired_hands(
                contract, exercise_name=candidate.exercise_name),
            source_pose_reference_path=pose, stage_identity=stage_identity,
            structural_refinement_enabled=request.structural_refinement_enabled,
            motion_tuning_enabled=request.motion_tuning_enabled,
            reuse_reconstruction_cache=retained_reconstruction,
            require_reconstruction_cache=retained_reconstruction,
        ))

    module.generate_candidate_motion = generate
