from __future__ import annotations

import base64
import html
import json
import math
import shutil
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from exercise_motion_pkg.motion_io import load_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, GenerateResult, run_generation_pipeline
from exercise_motion_pkg.segment_detection import (
    DetectionSettings,
    DetectionWindow,
    detect_exercise_segment,
    extract_json_object,
    extract_window_frames,
    save_detection_result,
)
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video
from exercise_motion_pkg.youtube import LiteRtServerVisionRanker, YouTubeRankingSettings, download_youtube, find_default_litert_command, slugify


DEFAULT_MAX_LOOP_SECONDS = 10.0
DEFAULT_REVIEW_FRAMES = 12
DEFAULT_RANK_FRAME_WIDTH = 640
DEFAULT_MIN_SELECTED_SCORE = 0.55
LOOP_MODEL_SCORE_WEIGHT = 0.5
LOOP_CONTINUITY_SCORE_WEIGHT = 0.5


@dataclass(frozen=True)
class RankedCandidate:
    exercise_index: int
    candidate_rank: int
    exercise_id: str
    exercise_name: str
    exercise_slug: str
    candidate: dict[str, Any]

    @property
    def url(self) -> str | None:
        value = self.candidate.get("url") or self.candidate.get("videoUrl") or self.candidate.get("webpageUrl")
        return str(value).strip() if value else None

    @property
    def video_path(self) -> Path | None:
        value = self.candidate.get("videoPath") or self.candidate.get("sourceVideoPath")
        return Path(str(value)) if value else None

    @property
    def video_id(self) -> str | None:
        value = self.candidate.get("videoId") or self.candidate.get("id")
        return str(value).strip() if value else None

    @property
    def title(self) -> str:
        value = self.candidate.get("title")
        return str(value).strip() if value else f"candidate-{self.candidate_rank + 1}"

    @property
    def workspace_slug(self) -> str:
        identity = self.video_id or self.title or str(self.candidate_rank + 1)
        return slugify(f"{self.exercise_slug}-{self.candidate_rank + 1:03d}-{identity}")[:120]


@dataclass(frozen=True)
class EligibleLoop:
    loop_index: int
    loop: dict[str, Any]
    duration_sec: float


@dataclass(frozen=True)
class RejectedLoop:
    loop_index: int
    loop: dict[str, Any]
    duration_sec: float
    reason: str


@dataclass(frozen=True)
class BakedLoopArtifact:
    loop_index: int
    skeleton_path: Path
    review_video_path: Path
    export_payload: dict[str, Any]


@dataclass(frozen=True)
class LoopRanking:
    score: float
    reasons: list[str]
    raw_response: str | None = None
    payload: dict[str, Any] | None = None
    model_score: float | None = None
    continuity_score: float | None = None
    continuity_metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReviewItem:
    exercise_index: int
    candidate_rank: int
    loop_index: int
    exercise_name: str
    candidate_title: str
    candidate_workspace: Path
    skeleton_path: Path
    review_video_path: Path
    duration_sec: float
    candidate: dict[str, Any]


@dataclass(frozen=True)
class BakeAndRankRequest:
    candidates_json: Path
    workspace: Path
    wham_repo_path: Path | None
    body_model_root: Path | None
    wham_python_command: str = "python"
    use_wham_docker: bool = False
    wham_docker_image: str = "yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest"
    wham_docker_gpus: str = "all"
    wham_docker_shm_size: str = "8g"
    wham_estimate_local_only: bool = False
    wham_run_smplify: bool = False
    wham_coordinate_space: str = "camera"
    max_loop_seconds: float = DEFAULT_MAX_LOOP_SECONDS
    litert_command: str | None = None
    litert_backend: str = "gpu"
    vision_model: str = "gemma-4-E4B-it"
    use_litert_server: bool = True
    litert_server_url: str = "http://127.0.0.1:9379"
    litert_server_port: int = 9379
    keep_litert_server: bool = False
    review_frames: int = DEFAULT_REVIEW_FRAMES
    min_selected_score: float = DEFAULT_MIN_SELECTED_SCORE
    detect_source_segment: bool = True
    segment_base_url: str | None = None
    segment_model: str | None = None
    segment_window_seconds: float = 5.0
    segment_overlap_seconds: float = 2.5
    segment_frames_per_window: int = 20
    segment_confidence_threshold: float = 0.45
    segment_padding_seconds: float = 0.35
    segment_end_padding_seconds: float = 0.35
    segment_min_seconds: float = 2.0
    segment_max_seconds: float = 20.0


PreviewBaker = Callable[[Path, list[EligibleLoop], Path, int], list[BakedLoopArtifact]]
LoopRanker = Callable[[list[ReviewItem], BakeAndRankRequest], list[LoopRanking]]
SelectedArtifact = tuple[ReviewItem, LoopRanking | None]


def load_ranked_candidates_manifest(path: Path) -> list[RankedCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_top_ranked_candidates_manifest(payload)


def parse_ranked_candidates_manifest(payload: dict[str, Any]) -> list[RankedCandidate]:
    exercises = payload.get("exercises")
    if not isinstance(exercises, list):
        raise ValueError("Candidate manifest must contain an exercises array.")
    ranked: list[RankedCandidate] = []
    for exercise_index, exercise in enumerate(exercises):
        if not isinstance(exercise, dict):
            continue
        candidates = exercise.get("candidates")
        if not isinstance(candidates, list):
            continue
        exercise_name = str(exercise.get("exerciseName") or exercise.get("name") or f"Exercise {exercise_index + 1}")
        exercise_slug = str(exercise.get("slug") or slugify(exercise_name))
        exercise_id = str(exercise.get("exerciseId") or exercise.get("id") or exercise_slug)
        for candidate_rank, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            ranked.append(
                RankedCandidate(
                    exercise_index=exercise_index,
                    candidate_rank=candidate_rank,
                    exercise_id=exercise_id,
                    exercise_name=exercise_name,
                    exercise_slug=exercise_slug,
                    candidate=candidate,
                )
            )
    return ranked


def parse_top_ranked_candidates_manifest(payload: dict[str, Any]) -> list[RankedCandidate]:
    ranked = parse_ranked_candidates_manifest(payload)
    top_by_exercise: dict[int, RankedCandidate] = {}
    for candidate in ranked:
        existing = top_by_exercise.get(candidate.exercise_index)
        if existing is None or candidate.candidate_rank < existing.candidate_rank:
            top_by_exercise[candidate.exercise_index] = candidate
    return [top_by_exercise[index] for index in sorted(top_by_exercise)]


def split_loops_by_duration(
    loops: Iterable[dict[str, Any]],
    *,
    max_loop_seconds: float,
) -> tuple[list[EligibleLoop], list[RejectedLoop]]:
    eligible: list[EligibleLoop] = []
    rejected: list[RejectedLoop] = []
    for loop_index, loop in enumerate(loops):
        duration_sec = parse_loop_duration(loop)
        if duration_sec <= max_loop_seconds:
            eligible.append(EligibleLoop(loop_index=loop_index, loop=loop, duration_sec=duration_sec))
        else:
            rejected.append(
                RejectedLoop(
                    loop_index=loop_index,
                    loop=loop,
                    duration_sec=duration_sec,
                    reason="loop_too_long",
                )
            )
    return eligible, rejected


def parse_loop_duration(loop: dict[str, Any]) -> float:
    value = loop.get("durationSec")
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return max(0.0, float(value))
    return 0.0


def parse_loop_ranking_response(raw: str) -> LoopRanking:
    payload = extract_json_object(raw)
    if payload is None:
        return LoopRanking(score=0.0, reasons=["ranking_invalid_json"], raw_response=raw)
    score = payload.get("score")
    if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
        return LoopRanking(score=0.0, reasons=["ranking_missing_score"], raw_response=raw, payload=payload)
    reasons_value = payload.get("reasons") or payload.get("reason")
    if isinstance(reasons_value, list):
        reasons = [str(item) for item in reasons_value if str(item).strip()]
    elif isinstance(reasons_value, str) and reasons_value.strip():
        reasons = [reasons_value.strip()]
    else:
        reasons = []
    return LoopRanking(score=max(0.0, min(1.0, float(score))), reasons=reasons, raw_response=raw, payload=payload)


def choose_best_review_item(
    items: list[ReviewItem],
    rankings: list[LoopRanking],
    *,
    min_score: float = 0.0,
) -> tuple[ReviewItem, LoopRanking] | None:
    paired = list(zip(items, rankings))
    if not paired:
        return None
    selected = max(
        paired,
        key=lambda pair: (
            pair[1].score,
            -pair[0].exercise_index,
            -pair[0].candidate_rank,
            -pair[0].loop_index,
        ),
    )
    if selected[1].score < min_score:
        return None
    return selected


def apply_loop_continuity_adjustment(item: ReviewItem, ranking: LoopRanking) -> LoopRanking:
    continuity_metrics = compute_loop_continuity_metrics(item.skeleton_path)
    continuity_score = float(continuity_metrics["continuityScore"])
    adjusted_score = clamp_unit(
        ranking.score * LOOP_MODEL_SCORE_WEIGHT
        + continuity_score * LOOP_CONTINUITY_SCORE_WEIGHT
    )
    reasons = list(ranking.reasons)
    if continuity_score < 0.65:
        reasons.append("loop_restart_discontinuity_penalty")
    payload = dict(ranking.payload or {})
    payload["modelScore"] = ranking.score
    payload["continuityScore"] = continuity_score
    payload["continuityMetrics"] = continuity_metrics
    return LoopRanking(
        score=adjusted_score,
        reasons=reasons,
        raw_response=ranking.raw_response,
        payload=payload,
        model_score=ranking.score,
        continuity_score=continuity_score,
        continuity_metrics=continuity_metrics,
    )


def compute_loop_continuity_metrics(skeleton_path: Path) -> dict[str, Any]:
    payload = json.loads(skeleton_path.read_text(encoding="utf-8"))
    frames = payload.get("frames")
    joint_names = payload.get("jointNames")
    if not isinstance(frames, list) or len(frames) < 2 or not isinstance(joint_names, list):
        return {
            "continuityScore": 0.0,
            "seamAverageDistance": None,
            "seamMaxDistance": None,
            "medianFrameStepDistance": None,
            "seamToMedianStepRatio": None,
        }

    seam_distances = joint_distances_between_frames(frames[-1], frames[0], joint_names)
    frame_step_averages = [
        sum(distances) / len(distances)
        for distances in (
            joint_distances_between_frames(left, right, joint_names)
            for left, right in zip(frames, frames[1:])
        )
        if distances
    ]
    if not seam_distances or not frame_step_averages:
        return {
            "continuityScore": 0.0,
            "seamAverageDistance": None,
            "seamMaxDistance": None,
            "medianFrameStepDistance": None,
            "seamToMedianStepRatio": None,
        }
    seam_average = sum(seam_distances) / len(seam_distances)
    seam_max = max(seam_distances)
    median_step = statistics.median(frame_step_averages)
    seam_ratio = seam_average / max(1e-6, median_step)
    average_score = clamp_unit(1.0 - seam_ratio / 1.2)
    max_score = clamp_unit(1.0 - max(0.0, seam_max - 0.02) / 0.06)
    continuity_score = clamp_unit(max_score * 0.65 + average_score * 0.35)
    return {
        "continuityScore": continuity_score,
        "seamAverageDistance": seam_average,
        "seamMaxDistance": seam_max,
        "medianFrameStepDistance": median_step,
        "seamToMedianStepRatio": seam_ratio,
    }


def joint_distances_between_frames(left: dict[str, Any], right: dict[str, Any], joint_names: list[Any]) -> list[float]:
    left_joints = left.get("joints") if isinstance(left, dict) else None
    right_joints = right.get("joints") if isinstance(right, dict) else None
    if not isinstance(left_joints, dict) or not isinstance(right_joints, dict):
        return []
    distances: list[float] = []
    for joint_name_value in joint_names:
        joint_name = str(joint_name_value)
        left_point = left_joints.get(joint_name)
        right_point = right_joints.get(joint_name)
        if not is_point3(left_point) or not is_point3(right_point):
            continue
        distances.append(math.dist(left_point[:3], right_point[:3]))
    return distances


def is_point3(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3 and all(isinstance(item, (int, float)) for item in value[:3])


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def run_bake_and_rank_pipeline(
    request: BakeAndRankRequest,
    *,
    preview_baker: PreviewBaker | None = None,
    loop_ranker: LoopRanker | None = None,
) -> dict[str, Any]:
    candidates = load_ranked_candidates_manifest(request.candidates_json)
    preview_baker = preview_baker or bake_preview_loops_with_playwright
    request.workspace.mkdir(parents=True, exist_ok=True)

    candidate_results: list[dict[str, Any]] = []
    review_items: list[ReviewItem] = []
    review_item_entries: list[dict[str, Any]] = []

    for ranked_candidate in candidates:
        candidate_result = process_ranked_candidate(
            ranked_candidate,
            request=request,
            preview_baker=preview_baker,
            review_items=review_items,
            review_item_entries=review_item_entries,
        )
        candidate_results.append(candidate_result)

    selected: SelectedArtifact | None = (review_items[0], None) if review_items else None
    selection_manifest = build_selection_manifest(
        request=request,
        candidate_results=candidate_results,
        review_entries=review_item_entries,
        selected=selected,
        rejected_best=None,
    )
    selected_preview_path = write_selected_loop_preview_html(request.workspace, selected)
    if selected_preview_path is not None:
        selection_manifest["selectedLoopPreviewHtmlPath"] = str(selected_preview_path)
    selection_path = request.workspace / "selection_manifest.json"
    selection_path.write_text(json.dumps(selection_manifest, indent=2), encoding="utf-8")
    return selection_manifest


def write_candidate_ranking_manifests(review_item_entries: list[dict[str, Any]]) -> None:
    entries_by_workspace: dict[str, list[dict[str, Any]]] = {}
    for entry in review_item_entries:
        entries_by_workspace.setdefault(str(entry["candidateWorkspace"]), []).append(entry)
    for candidate_workspace, entries in entries_by_workspace.items():
        ranking_path = Path(candidate_workspace) / "review" / "ranking.json"
        ranking_path.write_text(
            json.dumps({"rankings": entries}, indent=2),
            encoding="utf-8",
        )


def write_selected_loop_preview_html(
    workspace: Path,
    selected: SelectedArtifact | None,
) -> Path | None:
    if selected is None:
        return None
    item, _ranking = selected
    loop_label = "Full Clip" if item.loop_index < 0 else f"Loop {item.loop_index + 1}"
    preview_path = workspace / "selected_loop_preview.html"
    video_rel = relative_html_path(item.review_video_path, workspace)
    fallback_mp4 = item.review_video_path.with_suffix(".mp4")
    fallback_rel = relative_html_path(fallback_mp4, workspace) if fallback_mp4 != item.review_video_path else None
    interactive_rel = relative_html_path(item.candidate_workspace / "preview" / "motion_preview.html", workspace)
    skeleton_rel = relative_html_path(item.skeleton_path, workspace)
    title = html.escape(f"{item.exercise_name} - Selected {loop_label}")
    source_elements = [
        f'      <source src="{html.escape(video_rel)}" type="{mime_type_for_video_path(item.review_video_path)}">'
    ]
    if fallback_rel is not None and fallback_mp4.exists():
        source_elements.append(
            f'      <source src="{html.escape(fallback_rel)}" type="{mime_type_for_video_path(fallback_mp4)}">'
        )
    preview_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #111;
      color: #eee;
      display: grid;
      min-height: 100vh;
      place-items: center;
    }}
    main {{
      width: min(960px, calc(100vw - 32px));
    }}
    video {{
      width: 100%;
      background: #000;
      border: 1px solid #333;
    }}
    a {{
      color: #9cc9ff;
    }}
    .links {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-top: 12px;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <video controls autoplay loop muted>
{chr(10).join(source_elements)}
    </video>
    <div class="links">
      <a href="{html.escape(video_rel)}">Open review video</a>
      <a href="{html.escape(interactive_rel)}">Open interactive preview</a>
      <a href="{html.escape(skeleton_rel)}">Open selected skeleton JSON</a>
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return preview_path


def relative_html_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def mime_type_for_video_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mp4":
        return "video/mp4"
    return "video/mp4"


def process_ranked_candidate(
    ranked_candidate: RankedCandidate,
    *,
    request: BakeAndRankRequest,
    preview_baker: PreviewBaker,
    review_items: list[ReviewItem],
    review_item_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_workspace = request.workspace / ranked_candidate.workspace_slug
    result_payload: dict[str, Any] = {
        "exerciseIndex": ranked_candidate.exercise_index,
        "candidateRank": ranked_candidate.candidate_rank,
        "exerciseId": ranked_candidate.exercise_id,
        "exerciseName": ranked_candidate.exercise_name,
        "candidate": ranked_candidate.candidate,
        "candidateWorkspace": str(candidate_workspace),
        "status": "pending",
        "eligibleLoops": [],
        "rejectedLoops": [],
        "failures": [],
    }
    try:
        generate_result = generate_candidate_motion(ranked_candidate, request=request)
        result_payload.update(generation_to_manifest(generate_result))
        cleaned_clip = load_motion_json(generate_result.cleaned_motion_json_path)
        eligible = [build_full_clip_eligible_loop(cleaned_clip)]
        rejected: list[RejectedLoop] = []
        result_payload["eligibleLoops"] = [eligible_loop_to_manifest(item) for item in eligible]
        result_payload["rejectedLoops"] = [rejected_loop_to_manifest(item) for item in rejected]
        result_payload["processedFullClip"] = True
        baked_artifacts = preview_baker(
            generate_result.preview_html_path,
            eligible,
            candidate_workspace,
            request.review_frames,
        )
        artifact_by_loop = {artifact.loop_index: artifact for artifact in baked_artifacts}
        for eligible_loop in eligible:
            artifact = artifact_by_loop.get(eligible_loop.loop_index)
            if artifact is None:
                result_payload["failures"].append(
                    {
                        "loopIndex": eligible_loop.loop_index,
                        "reason": "bake_missing_artifact",
                    }
                )
                continue
            review_item = ReviewItem(
                exercise_index=ranked_candidate.exercise_index,
                candidate_rank=ranked_candidate.candidate_rank,
                loop_index=eligible_loop.loop_index,
                exercise_name=ranked_candidate.exercise_name,
                candidate_title=ranked_candidate.title,
                candidate_workspace=candidate_workspace,
                skeleton_path=artifact.skeleton_path,
                review_video_path=artifact.review_video_path,
                duration_sec=eligible_loop.duration_sec,
                candidate=ranked_candidate.candidate,
            )
            review_items.append(review_item)
            review_item_entries.append(review_item_to_manifest(review_item))
        result_payload["status"] = "ready_for_selection" if any(item.candidate_workspace == candidate_workspace for item in review_items) else "skipped_no_baked_clip"
        write_candidate_bake_manifest(candidate_workspace, result_payload)
        return result_payload
    except Exception as exc:
        result_payload["status"] = "failed"
        result_payload["failures"].append({"reason": "candidate_failed", "message": str(exc)})
        write_candidate_bake_manifest(candidate_workspace, result_payload)
        return result_payload


def generate_candidate_motion(ranked_candidate: RankedCandidate, *, request: BakeAndRankRequest) -> GenerateResult:
    video_path = prepare_candidate_input_video(ranked_candidate, request=request)
    return run_generation_pipeline(
        GenerateRequest(
            exercise_slug=ranked_candidate.workspace_slug,
            workspace=request.workspace,
            video_path=video_path,
            wham_repo_path=request.wham_repo_path,
            body_model_root=request.body_model_root,
            wham_python_command=request.wham_python_command,
            use_wham_docker=request.use_wham_docker,
            wham_docker_image=request.wham_docker_image,
            wham_docker_gpus=request.wham_docker_gpus,
            wham_docker_shm_size=request.wham_docker_shm_size,
            wham_estimate_local_only=request.wham_estimate_local_only,
            wham_run_smplify=request.wham_run_smplify,
            wham_coordinate_space=request.wham_coordinate_space,
        )
    )


def build_full_clip_eligible_loop(cleaned_clip: Any) -> EligibleLoop:
    frame_count = int(getattr(cleaned_clip, "frame_count", 0) or 0)
    fps = float(getattr(cleaned_clip, "fps", 30.0) or 30.0)
    duration_sec = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
    return EligibleLoop(
        loop_index=-1,
        loop={
            "type": "full_clip",
            "startFrame": 0,
            "endFrame": max(0, frame_count - 1),
            "durationSec": duration_sec,
        },
        duration_sec=duration_sec,
    )


def prepare_candidate_input_video(ranked_candidate: RankedCandidate, *, request: BakeAndRankRequest) -> Path:
    candidate_workspace = request.workspace / ranked_candidate.workspace_slug
    source_dir = candidate_workspace / "source"
    source_video_path = copy_or_download_candidate_source(ranked_candidate, source_dir)
    if not request.detect_source_segment:
        return source_video_path
    segment_dir = candidate_workspace / "segment_detection"
    detection_result = detect_exercise_segment(
        video_path=source_video_path,
        output_dir=segment_dir / "frames",
        exercise_name=ranked_candidate.exercise_name,
        settings=DetectionSettings(
            base_url=request.segment_base_url or request.litert_server_url,
            model=request.segment_model or request.vision_model,
            litert_command=None if request.segment_base_url else request.litert_command,
            litert_backend=request.litert_backend,
            window_seconds=request.segment_window_seconds,
            overlap_seconds=request.segment_overlap_seconds,
            frames_per_window=request.segment_frames_per_window,
            confidence_threshold=request.segment_confidence_threshold,
            min_segment_seconds=request.segment_min_seconds,
            max_segment_seconds=request.segment_max_seconds,
        ),
    )
    detection_json_path = segment_dir / "segment_detection.json"
    save_detection_result(detection_json_path, detection_result)
    if detection_result.detected_span is None:
        raise RuntimeError(f"Source segment detection did not find a usable {ranked_candidate.exercise_name} span.")
    selected_segment_path = candidate_workspace / "input" / "selected_segment.mp4"
    trim_video(
        source_path=source_video_path,
        output_path=selected_segment_path,
        start_seconds=max(0.0, detection_result.detected_span.start_seconds - request.segment_padding_seconds),
        end_seconds=detection_result.detected_span.end_seconds + request.segment_end_padding_seconds,
    )
    return selected_segment_path


def bake_preview_loops_with_playwright(
    preview_html_path: Path,
    eligible_loops: list[EligibleLoop],
    candidate_workspace: Path,
    review_frames: int,
) -> list[BakedLoopArtifact]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for bake-and-rank. Install with: pip install playwright && playwright install chromium") from exc

    wear_dir = candidate_workspace / "wear"
    review_dir = candidate_workspace / "review"
    wear_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[BakedLoopArtifact] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
        page.goto(preview_html_path.resolve().as_uri(), wait_until="networkidle")
        page.wait_for_function("() => window.exerciseMotionAutomation != null")
        for eligible_loop in eligible_loops:
            options = {
                "fixedRoot": True,
                "autoWorldAlignment": True,
                "lockPlantedFeet": True,
                "lockYDrift": False,
                "sceneInverted": False,
                "showSmplMesh": False,
                "showBoundsHelper": False,
                "cameraYawDegrees": 45.0,
                "cameraPitchDegrees": 30.0,
            }
            export_payload = page.evaluate(
                """({ loopIndex, options }) => window.exerciseMotionAutomation.bakeLoop(loopIndex, options)""",
                {"loopIndex": eligible_loop.loop_index, "options": options},
            )
            artifact_label = "full-clip" if eligible_loop.loop_index < 0 else f"loop-{eligible_loop.loop_index + 1}"
            skeleton_path = wear_dir / f"skeleton.baked.{artifact_label}.json"
            skeleton_path.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")
            review_video_path = review_dir / f"{artifact_label}.webm"
            frame_indices = sample_review_frame_indices(export_payload, review_frames)
            frame_data_urls = [
                page.evaluate(
                    """({ frameIndex, options }) => window.exerciseMotionAutomation.renderFrame(frameIndex, options)""",
                    {"frameIndex": frame_index, "options": options},
                )
                for frame_index in frame_indices
            ]
            write_review_video_from_data_urls(
                frame_data_urls,
                review_video_path,
                fps=parse_export_fps(export_payload),
            )
            artifacts.append(
                BakedLoopArtifact(
                    loop_index=eligible_loop.loop_index,
                    skeleton_path=skeleton_path,
                    review_video_path=review_video_path,
                    export_payload=export_payload,
                )
            )
        browser.close()
    return artifacts


def sample_review_frame_indices(export_payload: dict[str, Any], count: int) -> list[int]:
    frame_count = int(export_payload.get("frameCount") or 0)
    if frame_count <= 0:
        return [0]
    return list(range(frame_count))


def parse_export_fps(export_payload: dict[str, Any]) -> float:
    value = export_payload.get("fps")
    if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0:
        return float(value)
    return 30.0


def write_review_video_from_data_urls(data_urls: list[str], output_path: Path, *, fps: float) -> None:
    if not data_urls:
        raise ValueError("At least one rendered frame is required to write a review video.")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("opencv-python and numpy are required to write review videos.") from exc

    frames = []
    for data_url in data_urls:
        _, _, encoded = data_url.partition(",")
        image_bytes = base64.b64decode(encoded)
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("Failed to decode rendered preview frame.")
        frames.append(image)
    height, width = frames[0].shape[:2]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    codec = "VP90" if output_path.suffix.lower() == ".webm" else "mp4v"
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {output_path}.")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def rank_review_items_with_litert(items: list[ReviewItem], request: BakeAndRankRequest) -> list[LoopRanking]:
    settings = YouTubeRankingSettings(
        litert_command=request.litert_command,
        litert_backend=request.litert_backend,
        vision_model=request.vision_model,
        use_litert_server=request.use_litert_server,
        litert_server_url=request.litert_server_url,
        litert_server_port=request.litert_server_port,
        keep_litert_server=request.keep_litert_server,
    )
    if request.use_litert_server:
        ranker = LiteRtServerVisionRanker(settings)
        try:
            return [
                apply_loop_continuity_adjustment(item, rank_review_item_with_server(item, request, ranker))
                for item in items
            ]
        finally:
            ranker.close()
    return [
        apply_loop_continuity_adjustment(item, rank_review_item_with_cli(item, request))
        for item in items
    ]


def rank_review_item_with_server(
    item: ReviewItem,
    request: BakeAndRankRequest,
    ranker: LiteRtServerVisionRanker,
) -> LoopRanking:
    artifact_label = "full-clip" if item.loop_index < 0 else f"loop-{item.loop_index + 1}"
    frames_dir = item.candidate_workspace / "review" / f"{artifact_label}-rank-frames"
    metadata = read_basic_video_metadata(item.review_video_path)
    window = DetectionWindow(index=0, start_seconds=0.0, end_seconds=max(0.1, item.duration_sec))
    frame_samples = extract_window_frames(
        video_path=item.review_video_path,
        window=window,
        frames_per_window=max(1, request.review_frames),
        max_frame_width=DEFAULT_RANK_FRAME_WIDTH,
        original_fps=metadata.fps,
        output_dir=frames_dir,
    )
    frame_paths = [sample.path for sample in frame_samples]
    raw = ranker.caption_images(frame_paths=frame_paths, prompt=build_loop_ranking_prompt(item))
    return parse_loop_ranking_response(raw)


def rank_review_item_with_cli(item: ReviewItem, request: BakeAndRankRequest) -> LoopRanking:
    import subprocess

    command = request.litert_command or find_default_litert_command()
    process = subprocess.run(
        [
            command,
            "run",
            request.vision_model,
            "--backend",
            request.litert_backend,
            "--vision-backend",
            request.litert_backend,
            "--prompt",
            build_loop_ranking_prompt(item),
            "--attachment",
            str(item.review_video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        return LoopRanking(score=0.0, reasons=["ranking_cli_failed"], raw_response=process.stderr.strip())
    return parse_loop_ranking_response(process.stdout.strip())


def build_loop_ranking_prompt(item: ReviewItem) -> str:
    return (
        "Rank this baked exercise motion preview loop for use as a Wear OS exercise animation.\n"
        f"Target exercise: {item.exercise_name}.\n"
        f"Candidate video title: {item.candidate_title}.\n"
        "Judge the rendered loop only. Score 0 to 1 using these criteria: correct exercise, recognizability, smoothness, stable planted feet, no impossible joints, clean loop continuity, and readability on a small Wear display.\n"
        "Strongly penalize wrong or unclear movement, jitter, foot sliding, broken limbs, visible popping, bad loop transitions, and poses that would be confusing on a watch.\n"
        "Return JSON only with keys: {\"score\": number, \"correctness\": number, \"recognizability\": number, \"smoothness\": number, \"stable_feet\": number, \"joint_plausibility\": number, \"loop_continuity\": number, \"wear_readability\": number, \"reasons\": [string]}."
    )


def write_candidate_bake_manifest(candidate_workspace: Path, payload: dict[str, Any]) -> None:
    review_dir = candidate_workspace / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "bake_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_selection_manifest(
    *,
    request: BakeAndRankRequest,
    candidate_results: list[dict[str, Any]],
    review_entries: list[dict[str, Any]],
    selected: SelectedArtifact | None,
    rejected_best: SelectedArtifact | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceCandidatesJson": str(request.candidates_json),
        "candidateSelectionPolicy": "top_ranked_per_exercise_then_cropped_full_clip",
        "loopRankingPolicy": "skipped_no_loop_choice_required",
        "maxLoopSeconds": request.max_loop_seconds,
        "minSelectedScore": request.min_selected_score,
        "candidateResults": candidate_results,
        "reviewItems": review_entries,
        "selected": None if selected is None else selected_to_manifest(*selected),
        "rejectedBest": None if rejected_best is None else {
            **selected_to_manifest(*rejected_best),
            "rejectionReason": "best_score_below_minimum",
        },
    }


def selected_to_manifest(item: ReviewItem, ranking: LoopRanking | None) -> dict[str, Any]:
    payload = review_item_to_manifest(item)
    if ranking is None:
        payload["selectionReason"] = "top_ranked_video_cropped_clip"
        payload["rankingSkipped"] = "no_loop_choice_required"
    else:
        payload["ranking"] = ranking_to_manifest(ranking)
    payload["selectedWearSkeletonPath"] = str(item.skeleton_path)
    payload["selectedReviewVideoPath"] = str(item.review_video_path)
    return payload


def generation_to_manifest(result: GenerateResult) -> dict[str, Any]:
    return {
        "manifestPath": str(result.manifest_path),
        "previewHtmlPath": str(result.preview_html_path),
        "rawPreviewHtmlPath": str(result.raw_preview_html_path),
        "wearSkeletonJsonPath": str(result.wear_skeleton_json_path),
        "cleanedMotionJsonPath": str(result.cleaned_motion_json_path),
        "rawMotionJsonPath": str(result.raw_motion_json_path),
        "targetRigContractPath": str(result.target_rig_contract_path),
        "retargetSourcePath": str(result.retarget_source_path) if result.retarget_source_path is not None else None,
        "whamSmplPreviewJsonPath": str(result.smpl_preview_json_path) if result.smpl_preview_json_path is not None else None,
        "inputVideoPath": str(result.copied_input_video_path),
        "groundMetadataPath": str(result.ground_metadata_path) if result.ground_metadata_path is not None else None,
    }


def eligible_loop_to_manifest(item: EligibleLoop) -> dict[str, Any]:
    return {
        "loopIndex": item.loop_index,
        "durationSec": item.duration_sec,
        "loop": item.loop,
    }


def rejected_loop_to_manifest(item: RejectedLoop) -> dict[str, Any]:
    return {
        "loopIndex": item.loop_index,
        "durationSec": item.duration_sec,
        "reason": item.reason,
        "loop": item.loop,
    }


def review_item_to_manifest(item: ReviewItem) -> dict[str, Any]:
    return {
        "exerciseIndex": item.exercise_index,
        "candidateRank": item.candidate_rank,
        "loopIndex": item.loop_index,
        "exerciseName": item.exercise_name,
        "candidateTitle": item.candidate_title,
        "candidateWorkspace": str(item.candidate_workspace),
        "skeletonPath": str(item.skeleton_path),
        "reviewVideoPath": str(item.review_video_path),
        "durationSec": item.duration_sec,
        "candidate": item.candidate,
    }


def ranking_to_manifest(ranking: LoopRanking) -> dict[str, Any]:
    return {
        "score": ranking.score,
        "reasons": ranking.reasons,
        "payload": ranking.payload,
        "rawResponse": ranking.raw_response,
        "modelScore": ranking.model_score,
        "continuityScore": ranking.continuity_score,
        "continuityMetrics": ranking.continuity_metrics,
    }


def copy_or_download_candidate_source(ranked_candidate: RankedCandidate, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    video_path = ranked_candidate.video_path
    if video_path is not None:
        source = video_path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Candidate video not found: {source}")
        destination = destination_dir / source.name
        if source != destination.resolve():
            shutil.copy2(source, destination)
        return destination
    if not ranked_candidate.url:
        raise ValueError("Candidate must provide url or videoPath.")
    return download_youtube(ranked_candidate.url, destination_dir)
