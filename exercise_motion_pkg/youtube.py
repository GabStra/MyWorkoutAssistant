from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


def download_youtube(url: str, output_dir: Path) -> Path:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for YouTube downloads. Install with: pip install .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "source.%(ext)s")
    options = {
        "format": "best[ext=mp4]/bestvideo[ext=mp4]/bestvideo/best",
        "outtmpl": template,
        "quiet": False,
        "noprogress": False,
        "noplaylist": True,
        "retries": 3,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = Path(ydl.prepare_filename(info))
    if downloaded.exists():
        return downloaded
    for extension in (".mp4", ".mkv", ".webm", ".mov"):
        candidate = Path(os.path.splitext(str(downloaded))[0] + extension)
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Download finished but no video file was found in {output_dir}.")


@dataclass(frozen=True)
class ExerciseEntry:
    exercise_id: str
    name: str
    slug: str


@dataclass(frozen=True)
class YouTubeCandidate:
    url: str
    video_id: str | None
    title: str
    channel: str | None
    duration_seconds: int | None
    view_count: int | None
    upload_date: str | None
    description_snippet: str | None
    thumbnail: str | None
    metadata_score: float = 0.0
    vision_score: float | None = None
    final_score: float = 0.0
    status: str = "candidate"
    score_reasons: list[str] = field(default_factory=list)

    def key(self) -> str:
        if self.video_id:
            return self.video_id
        return self.url

    def to_manifest_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": self.url,
            "videoId": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "durationSeconds": self.duration_seconds,
            "viewCount": self.view_count,
            "uploadDate": self.upload_date,
            "descriptionSnippet": self.description_snippet,
            "thumbnail": self.thumbnail,
            "metadataScore": round(self.metadata_score, 4),
            "visionScore": None if self.vision_score is None else round(self.vision_score, 4),
            "finalScore": round(self.final_score, 4),
            "status": self.status,
            "scoreReasons": self.score_reasons,
        }
        return payload


@dataclass(frozen=True)
class YouTubeRankingSettings:
    results_per_query: int = 10
    max_candidates: int = 6
    min_duration_seconds: int = 20
    max_duration_seconds: int = 120
    rank_with_litert: bool = False
    vision_candidates_per_exercise: int = 3
    vision_frames_per_candidate: int = 4
    vision_download_workers: int = 3
    vision_llm_workers: int = 1
    litert_command: str | None = None
    litert_backend: str = "gpu"
    vision_model: str = "gemma-4-E4B-it"
    include_disabled: bool = False
    use_litert_server: bool = True
    litert_server_url: str = "http://127.0.0.1:9379"
    litert_server_port: int = 9379
    keep_litert_server: bool = False
    vision_early_stop_score: float = 0.95


@dataclass
class PreparedVisionReview:
    candidate: YouTubeCandidate
    temp_dir: tempfile.TemporaryDirectory[str]
    frame_paths: list[Path]
    prompt: str

    def close(self) -> None:
        self.temp_dir.cleanup()


SearchFn = Callable[[str, int], list[YouTubeCandidate]]
VisionRankerFn = Callable[[ExerciseEntry, YouTubeCandidate, YouTubeRankingSettings], tuple[float, list[str]]]


DEMO_KEYWORDS = (
    "demo",
    "demonstration",
    "form",
    "proper",
    "technique",
    "full body",
    "execution",
    "same angle",
    "single camera",
)
PENALTY_KEYWORDS = (
    "shorts",
    "#shorts",
    "music",
    "challenge",
    "vlog",
    "reaction",
    "compilation",
    "fail",
    "funny",
    "motivation",
    "title card",
    "tutorial",
    "how to",
    "explained",
    "mistakes",
    "guide",
    "workout",
    "elite",
    "record",
    "combine",
    "crowd",
    "watches",
)
REST_COMPONENT_TYPES = {"rest", "recovery", "break"}
NON_MOTION_EXERCISE_TYPES = {"countdown"}


def load_workout_plan_exercises(plan_path: Path, *, include_disabled: bool = False) -> list[ExerciseEntry]:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    return extract_workout_plan_exercises(payload, include_disabled=include_disabled)


def extract_workout_plan_exercises(payload: Any, *, include_disabled: bool = False) -> list[ExerciseEntry]:
    raw_entries: list[tuple[str | None, str]] = []

    def is_disabled(node: dict[str, Any]) -> bool:
        if include_disabled:
            return False
        if node.get("disabled") is True:
            return True
        if node.get("isDisabled") is True:
            return True
        if node.get("enabled") is False:
            return True
        if node.get("isEnabled") is False:
            return True
        return False

    def is_rest(node: dict[str, Any]) -> bool:
        component_type = str(
            node.get("type")
            or node.get("componentType")
            or node.get("kind")
            or node.get("exerciseType")
            or ""
        ).strip().lower()
        name = str(node.get("exerciseName") or node.get("name") or "").strip().lower()
        exercise_type = str(node.get("exerciseType") or "").strip().lower()
        return (
            component_type in REST_COMPONENT_TYPES
            or name in REST_COMPONENT_TYPES
            or exercise_type in NON_MOTION_EXERCISE_TYPES
        )

    def is_group_container(node: dict[str, Any]) -> bool:
        component_type = str(
            node.get("type")
            or node.get("componentType")
            or node.get("kind")
            or ""
        ).strip().lower()
        if component_type in {"superset", "circuit", "group", "round"}:
            return True
        return any(
            isinstance(node.get(key), list)
            for key in ("workoutComponents", "components", "children", "items", "supersetExercises")
        ) and "exerciseName" not in node and "exercise" not in node

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        if is_disabled(node) or is_rest(node):
            return

        name = None if is_group_container(node) else extract_exercise_name(node)
        if name:
            raw_entries.append((extract_exercise_id(node), name))

        for key in (
            "workoutComponents",
            "components",
            "children",
            "items",
            "supersetExercises",
            "exercises",
            "exerciseComponents",
        ):
            if key in node:
                visit(node[key])

    if isinstance(payload, dict) and isinstance(payload.get("WorkoutStore"), dict):
        visit(payload["WorkoutStore"].get("workouts", []))
    elif isinstance(payload, dict) and isinstance(payload.get("workouts"), list):
        for workout in payload["workouts"]:
            if isinstance(workout, dict):
                visit(workout.get("workoutComponents", []))
    elif isinstance(payload, dict) and isinstance(payload.get("exercises"), list):
        visit(payload["exercises"])
    else:
        visit(payload)

    entries: list[ExerciseEntry] = []
    seen: set[str] = set()
    for source_id, name in raw_entries:
        normalized = normalize_exercise_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        entries.append(
            ExerciseEntry(
                exercise_id=source_id or f"EXERCISE_{len(entries)}",
                name=name.strip(),
                slug=slugify(name),
            )
        )
    return entries


def extract_exercise_name(node: dict[str, Any]) -> str | None:
    for key in ("exerciseName", "name", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_name(exercise)
    return None


def extract_exercise_id(node: dict[str, Any]) -> str | None:
    for key in ("exerciseId", "id", "uuid"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exercise = node.get("exercise")
    if isinstance(exercise, dict):
        return extract_exercise_id(exercise)
    return None


def normalize_exercise_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "exercise"


def build_youtube_queries(exercise_name: str) -> list[str]:
    base = exercise_name.strip()
    return [base]


def search_youtube(query: str, results_per_query: int) -> list[YouTubeCandidate]:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for YouTube search. Install with: pip install .[motion]"
        ) from exc

    options = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "noplaylist": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch{results_per_query}:{query}", download=False)
    return parse_yt_dlp_search_results(info)


def parse_yt_dlp_search_results(info: dict[str, Any]) -> list[YouTubeCandidate]:
    entries = info.get("entries") if isinstance(info, dict) else None
    if not isinstance(entries, list):
        return []
    candidates: list[YouTubeCandidate] = []
    for entry in entries:
        if isinstance(entry, dict):
            candidates.append(candidate_from_yt_dlp_entry(entry))
    return candidates


def candidate_from_yt_dlp_entry(entry: dict[str, Any]) -> YouTubeCandidate:
    video_id = as_optional_string(entry.get("id") or entry.get("display_id"))
    url = as_optional_string(entry.get("webpage_url") or entry.get("url"))
    if url and url.startswith("http"):
        resolved_url = url
    elif video_id:
        resolved_url = f"https://www.youtube.com/watch?v={video_id}"
    else:
        resolved_url = str(url or "")
    thumbnails = entry.get("thumbnails")
    thumbnail = None
    if isinstance(thumbnails, list) and thumbnails:
        last = thumbnails[-1]
        if isinstance(last, dict):
            thumbnail = as_optional_string(last.get("url"))
    return YouTubeCandidate(
        url=resolved_url,
        video_id=video_id,
        title=as_optional_string(entry.get("title")) or "",
        channel=as_optional_string(entry.get("channel") or entry.get("uploader")),
        duration_seconds=as_optional_int(entry.get("duration")),
        view_count=as_optional_int(entry.get("view_count")),
        upload_date=as_optional_string(entry.get("upload_date")),
        description_snippet=truncate_text(as_optional_string(entry.get("description")) or "", 260),
        thumbnail=thumbnail or as_optional_string(entry.get("thumbnail")),
    )


def as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def truncate_text(value: str, limit: int) -> str | None:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def score_candidate_metadata(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    *,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> YouTubeCandidate:
    text = f"{candidate.title} {candidate.description_snippet or ''}".lower()
    normalized_text = normalize_exercise_name(text)
    exercise_tokens = normalize_exercise_name(exercise.name).split()
    score = 0.20
    reasons: list[str] = []

    if exercise_tokens and all(token in normalized_text.split() for token in exercise_tokens):
        score += 0.30
        reasons.append("exercise_name_match")
    elif exercise_tokens and any(token in normalized_text.split() for token in exercise_tokens):
        score += 0.12
        reasons.append("partial_exercise_name_match")

    for keyword in DEMO_KEYWORDS:
        if keyword in text:
            score += 0.05
            reasons.append(f"{slugify(keyword).replace('-', '_')}_keyword")
    for keyword in PENALTY_KEYWORDS:
        if keyword in text:
            score -= 0.12
            reasons.append(f"{slugify(keyword).replace('-', '_')}_penalty")

    duration = candidate.duration_seconds
    if duration is None:
        reasons.append("duration_unknown")
    elif min_duration_seconds <= duration <= max_duration_seconds:
        score += 0.18
        reasons.append("usable_duration")
    elif duration < min_duration_seconds:
        score -= 0.24
        reasons.append("too_short")
    else:
        score -= 0.10
        reasons.append("too_long")

    if candidate.view_count is not None:
        if candidate.view_count >= 100_000:
            score += 0.08
            reasons.append("popular_video")
        elif candidate.view_count < 1_000:
            score -= 0.04
            reasons.append("low_view_count")

    score = clamp_score(score)
    return replace_candidate(
        candidate,
        metadata_score=score,
        final_score=score,
        status=status_for_score(score),
        score_reasons=dedupe_reasons(reasons),
    )


def replace_candidate(candidate: YouTubeCandidate, **changes: Any) -> YouTubeCandidate:
    payload = {
        "url": candidate.url,
        "video_id": candidate.video_id,
        "title": candidate.title,
        "channel": candidate.channel,
        "duration_seconds": candidate.duration_seconds,
        "view_count": candidate.view_count,
        "upload_date": candidate.upload_date,
        "description_snippet": candidate.description_snippet,
        "thumbnail": candidate.thumbnail,
        "metadata_score": candidate.metadata_score,
        "vision_score": candidate.vision_score,
        "final_score": candidate.final_score,
        "status": candidate.status,
        "score_reasons": list(candidate.score_reasons),
    }
    payload.update(changes)
    return YouTubeCandidate(**payload)


def dedupe_reasons(reasons: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            result.append(reason)
    return result


def clamp_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def status_for_score(score: float) -> str:
    if score >= 0.68:
        return "recommended"
    if score >= 0.35:
        return "candidate"
    return "rejected"


def compose_final_score(metadata_score: float, vision_score: float | None) -> float:
    if vision_score is None:
        return clamp_score(metadata_score)
    return clamp_score(metadata_score * 0.55 + vision_score * 0.45)


VISION_HARD_GATE_REASONS = {
    "correct_exercise",
    "usable_for_motion_extraction",
    "continuous_motion",
    "single_camera_angle",
    "no_step_breakdown",
    "no_camera_cuts",
    "unobstructed_motion",
    "key_joints_visible",
    "implement_path_visible",
    "single_primary_subject",
    "clean_scene",
    "no_nearby_people",
}


def candidate_passes_vision_hard_gates(
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> bool:
    if candidate.vision_score is None or candidate.vision_score < settings.vision_early_stop_score:
        return False
    return VISION_HARD_GATE_REASONS.issubset(set(candidate.score_reasons))


def litert_vision_backend(settings: YouTubeRankingSettings) -> str:
    if settings.use_litert_server:
        return "litert-server"
    return "litert-cli"


def settings_litert_serve_command(settings: YouTubeRankingSettings) -> list[str]:
    command = settings.litert_command or find_default_litert_command()
    return [
        command,
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.litert_server_port),
    ]


def discover_and_rank_youtube_candidates(
    *,
    workout_plan_json: Path,
    out_json: Path,
    settings: YouTubeRankingSettings,
    search_fn: SearchFn = search_youtube,
    vision_ranker: VisionRankerFn | None = None,
) -> dict[str, Any]:
    exercises = load_workout_plan_exercises(workout_plan_json, include_disabled=settings.include_disabled)
    vision_enabled = settings.rank_with_litert
    owns_vision_ranker = False
    if vision_enabled and vision_ranker is None:
        if settings.use_litert_server:
            vision_ranker = LiteRtServerVisionRanker(settings)
            owns_vision_ranker = True
        else:
            vision_ranker = rank_candidate_with_litert

    exercise_payloads: list[dict[str, Any]] = []
    try:
        for exercise in exercises:
            queries = build_youtube_queries(exercise.name)
            by_key: dict[str, YouTubeCandidate] = {}
            for query in queries:
                for candidate in search_fn(query, settings.results_per_query):
                    if not candidate.url:
                        continue
                    key = candidate.key()
                    if key not in by_key:
                        by_key[key] = candidate

            ranked = [
                score_candidate_metadata(
                    exercise,
                    candidate,
                    min_duration_seconds=settings.min_duration_seconds,
                    max_duration_seconds=settings.max_duration_seconds,
                )
                for candidate in by_key.values()
            ]
            ranked.sort(key=lambda item: item.metadata_score, reverse=True)
            ranked = ranked[: settings.max_candidates]

            if vision_enabled and vision_ranker is not None:
                if isinstance(vision_ranker, LiteRtServerVisionRanker):
                    reranked = rank_candidates_with_prepared_vision_reviews(
                        exercise=exercise,
                        ranked=ranked,
                        settings=settings,
                        vision_ranker=vision_ranker,
                    )
                else:
                    reranked = rank_candidates_with_vision_ranker(
                        exercise=exercise,
                        ranked=ranked,
                        settings=settings,
                        vision_ranker=vision_ranker,
                    )
                ranked = reranked
                ranked.sort(key=lambda item: item.final_score, reverse=True)

            exercise_payloads.append(
                {
                    "exerciseId": exercise.exercise_id,
                    "exerciseName": exercise.name,
                    "slug": exercise.slug,
                    "queries": queries,
                    "candidates": [candidate.to_manifest_dict() for candidate in ranked],
                }
            )
    finally:
        if owns_vision_ranker and isinstance(vision_ranker, LiteRtServerVisionRanker):
            vision_ranker.close()

    manifest = {
        "sourcePlanPath": str(workout_plan_json),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ranking": {
            "metadataEnabled": True,
            "visionEnabled": vision_enabled,
            "visionBackend": litert_vision_backend(settings) if vision_enabled else None,
        },
        "exercises": exercise_payloads,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


class LiteRtServerVisionRanker:
    def __init__(self, settings: YouTubeRankingSettings) -> None:
        self.settings = settings
        self.base_url = settings.litert_server_url.rstrip("/")
        self.client = httpx.Client(timeout=600.0)
        self.process: subprocess.Popen[str] | None = None
        self._ensure_server()

    def __call__(
        self,
        exercise: ExerciseEntry,
        candidate: YouTubeCandidate,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str]]:
        return rank_candidate_with_vision_client(
            exercise=exercise,
            candidate=candidate,
            settings=settings,
            caption_images=self.caption_images,
        )

    def rank_prepared(
        self,
        prepared: PreparedVisionReview,
        settings: YouTubeRankingSettings,
    ) -> tuple[float, list[str]]:
        return score_prepared_vision_review(
            prepared=prepared,
            settings=settings,
            caption_images=self.caption_images,
        )

    def close(self) -> None:
        self.client.close()
        if self.process is None or self.settings.keep_litert_server:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10.0)

    def caption_images(self, *, frame_paths: list[Path], prompt: str) -> str:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for frame_path in frame_paths:
            encoded = base64.b64encode(frame_path.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        payload = {
            "model": self.settings.vision_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        response = self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if response.status_code >= 400:
            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            response = self.client.post(f"{self.base_url}/v1/chat/completions", json=fallback_payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _ensure_server(self) -> None:
        if self._is_healthy():
            return
        command = settings_litert_serve_command(self.settings)
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline:
            if self._is_healthy():
                return
            if self.process.poll() is not None:
                break
            time.sleep(1.0)
        raise RuntimeError("LiteRT server did not become healthy within 180 seconds.")

    def _is_healthy(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/v1/models", timeout=5.0)
            return response.status_code < 500
        except httpx.HTTPError:
            return False


def rank_candidates_with_vision_ranker(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    vision_ranker: VisionRankerFn,
) -> list[YouTubeCandidate]:
    reranked: list[YouTubeCandidate] = []
    vision_limit = max(0, settings.vision_candidates_per_exercise)
    for index, candidate in enumerate(ranked):
        if index < vision_limit:
            vision_score, vision_reasons = vision_ranker(exercise, candidate, settings)
            reviewed = apply_vision_score(candidate, vision_score, vision_reasons)
            reranked.append(reviewed)
            if candidate_passes_vision_hard_gates(reviewed, settings):
                reranked.extend(ranked[index + 1 :])
                break
        else:
            reranked.append(candidate)
    return reranked


def rank_candidates_with_prepared_vision_reviews(
    *,
    exercise: ExerciseEntry,
    ranked: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
    vision_ranker: LiteRtServerVisionRanker,
) -> list[YouTubeCandidate]:
    vision_limit = max(0, settings.vision_candidates_per_exercise)
    candidates_to_review = ranked[:vision_limit]
    prepared_by_key = prepare_vision_reviews_parallel(
        exercise=exercise,
        candidates=candidates_to_review,
        settings=settings,
    )
    reranked: list[YouTubeCandidate] = []
    try:
        if settings.vision_llm_workers > 1:
            vision_results_by_key = score_prepared_vision_reviews_parallel(
                prepared_reviews=list(prepared_by_key.values()),
                settings=settings,
                vision_ranker=vision_ranker,
            )
            for index, candidate in enumerate(ranked):
                if index < vision_limit:
                    vision_result = vision_results_by_key.get(candidate.key())
                    if vision_result is None:
                        reviewed = apply_vision_score(candidate, 0.0, ["vision_review_failed"])
                    else:
                        vision_score, vision_reasons = vision_result
                        reviewed = apply_vision_score(candidate, vision_score, vision_reasons)
                    reranked.append(reviewed)
                    if candidate_passes_vision_hard_gates(reviewed, settings):
                        reranked.extend(ranked[index + 1 :])
                        break
                else:
                    reranked.append(candidate)
            return reranked

        for index, candidate in enumerate(ranked):
            if index < vision_limit:
                prepared = prepared_by_key.get(candidate.key())
                if prepared is None:
                    reviewed = apply_vision_score(candidate, 0.0, ["vision_review_failed"])
                else:
                    vision_score, vision_reasons = vision_ranker.rank_prepared(prepared, settings)
                    reviewed = apply_vision_score(candidate, vision_score, vision_reasons)
                reranked.append(reviewed)
                if candidate_passes_vision_hard_gates(reviewed, settings):
                    reranked.extend(ranked[index + 1 :])
                    break
            else:
                reranked.append(candidate)
    finally:
        for prepared in prepared_by_key.values():
            prepared.close()
    return reranked


def score_prepared_vision_reviews_parallel(
    *,
    prepared_reviews: list[PreparedVisionReview],
    settings: YouTubeRankingSettings,
    vision_ranker: LiteRtServerVisionRanker,
) -> dict[str, tuple[float, list[str]]]:
    if not prepared_reviews:
        return {}
    workers = max(1, min(settings.vision_llm_workers, len(prepared_reviews)))
    results: dict[str, tuple[float, list[str]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(vision_ranker.rank_prepared, prepared, settings): prepared
            for prepared in prepared_reviews
        }
        for future in as_completed(futures):
            prepared = futures[future]
            try:
                results[prepared.candidate.key()] = future.result()
            except Exception:
                results[prepared.candidate.key()] = (0.0, ["vision_review_failed"])
    return results


def apply_vision_score(
    candidate: YouTubeCandidate,
    vision_score: float,
    vision_reasons: list[str],
) -> YouTubeCandidate:
    final_score = compose_final_score(candidate.metadata_score, vision_score)
    return replace_candidate(
        candidate,
        vision_score=vision_score,
        final_score=final_score,
        status=status_for_score(final_score),
        score_reasons=dedupe_reasons(candidate.score_reasons + vision_reasons),
    )


def prepare_vision_reviews_parallel(
    *,
    exercise: ExerciseEntry,
    candidates: list[YouTubeCandidate],
    settings: YouTubeRankingSettings,
) -> dict[str, PreparedVisionReview]:
    if not candidates:
        return {}
    workers = max(1, min(settings.vision_download_workers, len(candidates)))
    prepared_by_key: dict[str, PreparedVisionReview] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(prepare_vision_review, exercise, candidate, settings): candidate
            for candidate in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                prepared_by_key[candidate.key()] = future.result()
            except Exception:
                continue
    return prepared_by_key


def prepare_vision_review(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> PreparedVisionReview:
    from exercise_motion_pkg.segment_detection import DetectionWindow, extract_window_frames
    from exercise_motion_pkg.video_utils import read_basic_video_metadata

    temp_dir = tempfile.TemporaryDirectory(prefix="exercise-motion-youtube-")
    temp_path = Path(temp_dir.name)
    try:
        video_path = download_youtube_preview(candidate.url, temp_path)
        metadata = read_basic_video_metadata(video_path)
        duration = max(0.5, metadata.duration_seconds)
        window = DetectionWindow(index=0, start_seconds=0.0, end_seconds=min(duration, 30.0))
        frame_paths = extract_window_frames(
            video_path=video_path,
            window=window,
            frames_per_window=max(1, settings.vision_frames_per_candidate),
            max_frame_width=960,
            output_dir=temp_path / "frames",
        )
        return PreparedVisionReview(
            candidate=candidate,
            temp_dir=temp_dir,
            frame_paths=frame_paths,
            prompt=build_candidate_vision_prompt(exercise.name, candidate),
        )
    except Exception:
        temp_dir.cleanup()
        raise


def rank_candidate_with_litert(
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
) -> tuple[float, list[str]]:
    from exercise_motion_pkg.segment_detection import LiteRtCliVisionClient

    command = settings.litert_command or find_default_litert_command()
    client = LiteRtCliVisionClient(
        command=command,
        model=settings.vision_model,
        backend=settings.litert_backend,
    )
    return rank_candidate_with_vision_client(
        exercise=exercise,
        candidate=candidate,
        settings=settings,
        caption_images=client.caption_images,
    )


def rank_candidate_with_vision_client(
    *,
    exercise: ExerciseEntry,
    candidate: YouTubeCandidate,
    settings: YouTubeRankingSettings,
    caption_images: Callable[..., str],
) -> tuple[float, list[str]]:
    try:
        prepared = prepare_vision_review(exercise, candidate, settings)
        try:
            return score_prepared_vision_review(
                prepared=prepared,
                settings=settings,
                caption_images=caption_images,
            )
        finally:
            prepared.close()
    except Exception:
        return 0.0, ["vision_review_failed"]


def score_prepared_vision_review(
    *,
    prepared: PreparedVisionReview,
    settings: YouTubeRankingSettings,
    caption_images: Callable[..., str],
) -> tuple[float, list[str]]:
    from exercise_motion_pkg.segment_detection import extract_json_object

    try:
        raw = caption_images(frame_paths=prepared.frame_paths, prompt=prepared.prompt)
    except Exception:
        return 0.0, ["vision_review_failed"]
    payload = extract_json_object(raw)
    if not isinstance(payload, dict):
        return 0.0, ["vision_invalid_json"]

    correct_exercise = parse_bool_value(payload.get("correct_exercise"), default=False)
    full_body_visible = parse_bool_value(payload.get("full_body_visible"), default=False)
    stable_camera = parse_bool_value(payload.get("stable_camera"), default=False)
    repeated_reps = parse_bool_value(payload.get("repeated_reps"), default=False)
    low_obstruction = parse_bool_value(payload.get("low_obstruction"), default=False)
    usable = parse_bool_value(payload.get("usable_for_motion_extraction"), default=False)
    continuous_motion = parse_bool_value(payload.get("continuous_motion"), default=False)
    single_camera_angle = parse_bool_value(payload.get("single_camera_angle"), default=stable_camera)
    no_step_breakdown = parse_bool_value(payload.get("no_step_breakdown"), default=False)
    no_camera_cuts = parse_bool_value(payload.get("no_camera_cuts"), default=single_camera_angle)
    unobstructed_motion = parse_bool_value(payload.get("unobstructed_motion"), default=low_obstruction)
    key_joints_visible = parse_bool_value(payload.get("key_joints_visible"), default=full_body_visible)
    implement_path_visible = parse_bool_value(payload.get("implement_path_visible"), default=full_body_visible)
    single_primary_subject = parse_bool_value(payload.get("single_primary_subject"), default=False)
    clean_scene = parse_bool_value(payload.get("clean_scene"), default=False)
    no_nearby_people = parse_bool_value(payload.get("no_nearby_people"), default=False)
    confidence = payload.get("confidence")
    confidence_score = confidence if isinstance(confidence, (int, float)) else 0.5

    score = 0.0
    reasons: list[str] = []
    if correct_exercise:
        score += 0.30
        reasons.append("correct_exercise")
    else:
        reasons.append("wrong_exercise_penalty")
    if full_body_visible:
        score += 0.20
        reasons.append("full_body_visible")
    if stable_camera:
        score += 0.08
        reasons.append("stable_camera")
    if repeated_reps:
        score += 0.10
        reasons.append("repeated_reps")
    if low_obstruction:
        score += 0.08
        reasons.append("low_obstruction")
    if usable:
        score += 0.07
        reasons.append("usable_for_motion_extraction")

    if continuous_motion:
        score += 0.17
        reasons.append("continuous_motion")
    else:
        reasons.append("broken_or_noncontinuous_motion_penalty")
    if single_camera_angle:
        score += 0.08
        reasons.append("single_camera_angle")
    else:
        reasons.append("angle_change_or_shaky_camera_penalty")
    if no_step_breakdown:
        score += 0.08
        reasons.append("no_step_breakdown")
    else:
        reasons.append("step_breakdown_penalty")
    if no_camera_cuts:
        score += 0.04
        reasons.append("no_camera_cuts")
    else:
        reasons.append("camera_cuts_penalty")
    if unobstructed_motion:
        score += 0.08
        reasons.append("unobstructed_motion")
    else:
        reasons.append("obstructed_motion_penalty")
    if key_joints_visible:
        score += 0.06
        reasons.append("key_joints_visible")
    else:
        reasons.append("key_joints_obstructed_penalty")
    if implement_path_visible:
        score += 0.04
        reasons.append("implement_path_visible")
    else:
        reasons.append("implement_path_obstructed_penalty")
    if single_primary_subject:
        score += 0.08
        reasons.append("single_primary_subject")
    else:
        reasons.append("multiple_people_penalty")
    if clean_scene:
        score += 0.06
        reasons.append("clean_scene")
    else:
        reasons.append("busy_scene_penalty")
    if no_nearby_people:
        score += 0.04
        reasons.append("no_nearby_people")
    else:
        reasons.append("nearby_people_penalty")

    if not usable or not correct_exercise:
        score *= 0.55
    if not continuous_motion or not no_step_breakdown or not no_camera_cuts:
        score *= 0.45
    if not stable_camera or not single_camera_angle:
        score *= 0.60
    if not unobstructed_motion or not key_joints_visible or not implement_path_visible:
        score *= 0.25
    if not single_primary_subject or not clean_scene or not no_nearby_people:
        score *= 0.20
    score *= max(0.0, min(1.0, float(confidence_score)))
    return clamp_score(score), reasons


def parse_bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
    return default


def find_default_litert_command() -> str:
    local = Path(".venv") / "Scripts" / "litert-lm.exe"
    if local.exists():
        return str(local)
    found = shutil.which("litert-lm")
    return found or "litert-lm"


def download_youtube_preview(url: str, output_dir: Path) -> Path:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for YouTube preview downloads. Install with: pip install .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "candidate.%(ext)s")
    options = {
        "format": "worst[ext=mp4]/worstvideo[ext=mp4]/worst",
        "outtmpl": template,
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 2,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = Path(ydl.prepare_filename(info))
    if downloaded.exists():
        return downloaded
    for extension in (".mp4", ".webm", ".mkv", ".mov"):
        candidate = Path(os.path.splitext(str(downloaded))[0] + extension)
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Preview download finished but no video file was found in {output_dir}.")


def build_candidate_vision_prompt(exercise_name: str, candidate: YouTubeCandidate) -> str:
    return (
        "Rank this YouTube candidate for exercise motion extraction.\n"
        f"Target exercise: {exercise_name}.\n"
        f"Video title: {candidate.title}.\n"
        "Judge the sampled frames together. We need a short demo clip for WHAM-style motion extraction, not a full tutorial.\n"
        "Strongly prefer: the actual target exercise being performed as continuous uninterrupted repetitions, a stable single camera angle, the whole relevant body and implement visible through the rep, clear joint motion, no obstruction, and little or no talking/setup/title-card content.\n"
        "For bench press, the bar path, hands, elbows, shoulders, torso, and bench must remain clearly visible through the press; any angle is acceptable if it stays the same and clearly shows the full pressing motion.\n"
        "The scene should contain one clearly isolated primary athlete. Reject crowded gym/event scenes, spectators, multiple nearby people, spotters/helpers close to the lifter, or other bodies that could confuse person tracking, even if the main lifter is visible.\n"
        "Reject or down-rank wrong exercises, cropped bodies, shaky handheld video, setup-only clips, talking-only/tutorial clips, title cards, excessive camera movement, camera cuts between reps, montage edits, obstructed lifters, crowded gym clips, spotters or equipment blocking the motion, and videos not usable for motion extraction.\n"
        "Reject step-by-step demonstrations where the movement is broken into separate instructional positions, paused stages, freeze frames, or edited fragments instead of a continuous rep.\n"
        "Return JSON only with these keys:\n"
        "{"
        '"correct_exercise": boolean, '
        '"full_body_visible": boolean, '
        '"stable_camera": boolean, '
        '"repeated_reps": boolean, '
        '"low_obstruction": boolean, '
        '"usable_for_motion_extraction": boolean, '
        '"continuous_motion": boolean, '
        '"single_camera_angle": boolean, '
        '"no_step_breakdown": boolean, '
        '"no_camera_cuts": boolean, '
        '"unobstructed_motion": boolean, '
        '"key_joints_visible": boolean, '
        '"implement_path_visible": boolean, '
        '"single_primary_subject": boolean, '
        '"clean_scene": boolean, '
        '"no_nearby_people": boolean, '
        '"confidence": number, '
        '"reason": string'
        "}"
    )
