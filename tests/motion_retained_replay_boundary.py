"""Local source IO and retained reconstruction boundaries; reviews stay real.

Used only by the opt-in process replay bootstrap. This does not fabricate model
verdicts or prove reconstruction cache lookup. Every input is pinned by bytes.
"""
from __future__ import annotations

import hashlib
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

    def generate(candidate: Any, *, request: Any, prepared_video_path: Path | None = None,
                 stage_identity: dict[str, Any] | None = None, **_kwargs: Any) -> Any:
        from exercise_motion_pkg import bake_and_rank as bake
        from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline

        if prepared_video_path is None:
            raise AssertionError("Retained reconstruction replay requires the staged source-review path")
        fixture = fixtures[candidate.exercise_id]
        selected = Path(prepared_video_path).resolve()
        if hashlib.sha256(selected.read_bytes()).hexdigest() != fixture["sourceVideoPathSha256"]:
            raise AssertionError("Selected source differs from the retained reconstruction timeline")
        raw = verified_file(fixture, "normalizedMotionPath")
        contract = bake.exercise_motion_contract_from_candidate(candidate.candidate)
        pose = request.workspace / candidate.workspace_slug / "segment_detection/exact_source_pose_reference.json"
        if not pose.is_file():
            raise AssertionError("Production exact-source pose evidence is missing before reconstruction replay")
        record(config, "retained_reconstruction_boundary", exerciseId=candidate.exercise_id,
               sourceSha256=fixture["sourceVideoPathSha256"], rawSha256=fixture["normalizedMotionPathSha256"],
               upstreamIdentity=fixture["upstreamIdentity"], owner=fullname)
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
            require_wham_cache=True,
        ))

    module.generate_candidate_motion = generate
