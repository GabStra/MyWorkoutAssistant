from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
)
from exercise_motion_pkg.youtube import sanitize_video_for_processing
from exercise_motion_pkg.video_utils import read_basic_video_metadata


@dataclass(frozen=True)
class DetectionSettings:
    base_url: str = "http://127.0.0.1:8090"
    model: str = "local-vision"
    litert_command: str | None = None
    litert_backend: str = "gpu"
    llama_cpp_backend: str = "gpu"
    llama_cpp_n_predict: int = 768
    llama_cpp_temperature: float = DEFAULT_LLAMA_CPP_TEMPERATURE
    llama_cpp_top_p: float | None = DEFAULT_LLAMA_CPP_TOP_P
    llama_cpp_top_k: int | None = DEFAULT_LLAMA_CPP_TOP_K
    llama_cpp_disable_reasoning: bool = False
    llama_cpp_image_min_tokens: int | None = None
    llama_cpp_image_max_tokens: int | None = None
    window_seconds: float = 4.0
    overlap_seconds: float = 2.0
    frames_per_window: int = 6
    max_frame_width: int = 640
    contact_sheet_enabled: bool = True
    contact_sheet_columns: int = 4
    contact_sheet_tile_width: int = 320
    refinement_contact_sheet_tile_width: int = 480
    contact_sheet_frames_per_sheet: int = 8
    contact_sheet_jpeg_quality: int = 90
    incomplete_movement_penalty: float = 0.20
    duration_penalty_per_second: float = 0.02
    max_candidate_camera_variation: float = 0.15
    comparative_selection_enabled: bool = False
    comparative_selection_score_tolerance: float = 0.02
    comparative_selection_max_candidates: int = 8
    merge_gap_seconds: float = 2.0
    confidence_threshold: float = 0.45
    min_segment_seconds: float = 2.0
    max_segment_seconds: float = 20.0
    target_segment_seconds: float | None = None
    chunk_retry_multipliers: tuple[float, ...] = (1.0, 1.5, 2.0)
    retry_overlap_ratio: float = 0.5
    use_motion_prefilter: bool = False
    refinement_window_seconds: float = 2.0
    refinement_overlap_seconds: float = 1.0
    refinement_frames_per_window: int = 16
    refinement_padding_seconds: float = 1.0
    enable_final_refinement: bool = False
    enable_boundary_refinement: bool = True
    boundary_refinement_frames_per_window: int = 24
    min_boundary_refinement_duration_ratio: float = 0.45
    classification_workers: int = 3
    motion_sample_fps: float = 2.0
    motion_threshold_ratio: float = 0.35
    motion_padding_seconds: float = 2.0
    motion_min_interval_seconds: float = 1.0
    motion_merge_gap_seconds: float = 2.0
    max_motion_candidates: int = 3
    active_refinement_tolerance_seconds: float = 5.0
    active_refinement_max_rounds: int = 0
    active_refinement_overlap_ratio: float = 0.5
    min_refined_score_ratio: float = 0.85
    min_refinement_duration_ratio: float = 0.65
    health_timeout_seconds: float = 180.0
    request_timeout_seconds: float = 90.0


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    fps: float
    frame_count: int
    width: int
    height: int


@dataclass(frozen=True)
class DetectionWindow:
    index: int
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class MotionInterval:
    start_seconds: float
    end_seconds: float
    score: float


@dataclass(frozen=True)
class WindowDetection:
    window: DetectionWindow
    movement_present: bool
    contains_movement_start: bool
    contains_movement_end: bool
    movement_start_seconds: float | None
    movement_end_seconds: float | None
    confidence: float
    summary: str
    reason: str
    camera_variation: float
    frame_paths: list[str]
    executions: tuple["CandidateExecution", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateExecution:
    start_seconds: float
    end_seconds: float
    complete: bool
    single_execution: bool
    normal_speed: bool
    not_broken_into_steps: bool
    fixed_camera: bool
    single_person: bool
    fully_in_frame: bool
    unobstructed: bool
    extra_motion_before: bool
    extra_motion_after: bool
    partial_movement: bool
    full_movement_coverage: float
    start_posture_visible: bool
    full_action_path_visible: bool
    end_posture_visible: bool
    target_exercise_match: float
    wrong_exercise_or_unrelated_movement: bool
    loop_quality: float
    suggested_loop_start_seconds: float | None
    suggested_loop_end_seconds: float | None
    actual_demonstration: bool
    title_or_instruction_screen: bool
    screen_with_embedded_video: bool
    contains_multiple_executions: bool
    contains_idle_or_reset: bool
    confidence: float
    quality: float = 0.0
    reason: str = ""
    source_window_index: int | None = None
    is_model_candidate: bool = True


@dataclass(frozen=True)
class SupportDominanceResult:
    support_dominance: str
    confidence: float
    reason: str
    exercise_name: str | None = None
    uncertain: bool = False
    model_output: dict[str, object] | None = None


@dataclass(frozen=True)
class DetectedSpan:
    start_seconds: float
    end_seconds: float
    confidence: float
    average_camera_variation: float
    contributing_windows: list[int]


@dataclass(frozen=True)
class DetectionResult:
    video_path: str
    exercise_name: str | None
    source_duration_seconds: float
    window_seconds: float
    overlap_seconds: float
    detected_span: DetectedSpan | None
    windows: list[WindowDetection]
    source_fps: float = 0.0
    source_total_frames: int = 0
    source_width: int = 0
    source_height: int = 0


def detect_exercise_segment(
    *,
    video_path: Path,
    output_dir: Path,
    settings: DetectionSettings,
    exercise_name: str | None = None,
) -> DetectionResult:
    sanitized_video_path = sanitize_video_for_processing(video_path)
    metadata = read_video_metadata(sanitized_video_path)
    if settings.litert_command:
        client = LiteRtCliVisionClient(
            command=settings.litert_command,
            model=settings.model,
            backend=settings.litert_backend,
        )
    else:
        client = LlamaCppVisionClient(
            settings.base_url,
            settings.model,
            n_predict=settings.llama_cpp_n_predict,
            temperature=settings.llama_cpp_temperature,
            top_p=settings.llama_cpp_top_p,
            top_k=settings.llama_cpp_top_k,
            disable_reasoning=settings.llama_cpp_disable_reasoning,
            image_min_tokens=settings.llama_cpp_image_min_tokens,
            image_max_tokens=settings.llama_cpp_image_max_tokens,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    def classify_window(window: DetectionWindow, *, tier_dir: Path) -> WindowDetection:
        frame_paths = extract_window_frames(
            video_path=sanitized_video_path,
            window=window,
            frames_per_window=settings.frames_per_window,
            max_frame_width=settings.max_frame_width,
            contact_sheet_enabled=settings.contact_sheet_enabled,
            contact_sheet_columns=settings.contact_sheet_columns,
            contact_sheet_tile_width=settings.contact_sheet_tile_width,
            contact_sheet_frames_per_sheet=settings.contact_sheet_frames_per_sheet,
            contact_sheet_jpeg_quality=settings.contact_sheet_jpeg_quality,
            output_dir=tier_dir / f"window_{window.index:04d}",
        )
        return client.detect_window(
            frame_paths=frame_paths,
            window=window,
            exercise_name=exercise_name,
            require_complete_execution=True,
        )

    motion_intervals = (
        detect_motion_candidate_intervals(
            video_path=sanitized_video_path,
            metadata=metadata,
            settings=settings,
        )
        if settings.use_motion_prefilter
        else [MotionInterval(0.0, metadata.duration_seconds, 1.0)]
    )
    detections: list[WindowDetection] = []
    detected_span: DetectedSpan | None = None
    for tier_index, multiplier in enumerate(_normalized_chunk_retry_multipliers(settings.chunk_retry_multipliers)):
        tier_window_seconds = min(metadata.duration_seconds, max(0.5, settings.window_seconds * multiplier))
        tier_overlap_seconds = max(
            0.0,
            min(
                tier_window_seconds - 0.25,
                max(settings.overlap_seconds, tier_window_seconds * settings.retry_overlap_ratio),
            ),
        )
        windows = iter_detection_windows_for_intervals(
            intervals=motion_intervals,
            duration_seconds=metadata.duration_seconds,
            window_seconds=tier_window_seconds,
            overlap_seconds=tier_overlap_seconds,
        )
        window_index_offset = tier_index * 1_000
        windows = [
            DetectionWindow(
                index=window_index_offset + window.index,
                start_seconds=window.start_seconds,
                end_seconds=window.end_seconds,
            )
            for window in windows
        ]
        tier_dir = output_dir / f"tier_{tier_index:02d}_{tier_window_seconds:.1f}s"
        tier_detections = _classify_detection_windows_parallel(
            windows=windows,
            classify_window=lambda window, current_tier_dir=tier_dir: classify_window(window, tier_dir=current_tier_dir),
            classification_workers=settings.classification_workers,
        )
        detections.extend(tier_detections)
        detected_span = choose_detected_span(
            detections=tier_detections,
            confidence_threshold=settings.confidence_threshold,
            merge_gap_seconds=settings.merge_gap_seconds,
            min_segment_seconds=settings.min_segment_seconds,
            max_segment_seconds=settings.max_segment_seconds,
            settings=settings,
        )
        if detected_span is not None:
            detected_span = refine_span_with_comparative_selection(
                client=client,
                detections=tier_detections,
                selected_span=detected_span,
                confidence_threshold=settings.confidence_threshold,
                min_segment_seconds=settings.min_segment_seconds,
                max_segment_seconds=settings.max_segment_seconds,
                settings=settings,
                exercise_name=exercise_name,
            )
            break
    if detected_span is not None and settings.active_refinement_max_rounds > 0:
        active_span, active_detections = refine_detected_span_with_active_search(
            video_path=sanitized_video_path,
            output_dir=output_dir / "active_refinement",
            client=client,
            metadata=metadata,
            coarse_span=detected_span,
            settings=settings,
            exercise_name=exercise_name,
        )
        detected_span = active_span
        detections.extend(active_detections)
    if detected_span is not None and settings.enable_final_refinement:
        refined_span, refinement_detections = refine_detected_span_with_smaller_windows(
            video_path=sanitized_video_path,
            output_dir=output_dir / "refinement",
            client=client,
            metadata=metadata,
            coarse_span=detected_span,
            settings=settings,
            exercise_name=exercise_name,
        )
        detected_span = refined_span
        detections.extend(refinement_detections)
    if detected_span is not None and settings.enable_boundary_refinement:
        detected_span = refine_selected_chunk_boundaries(
            video_path=sanitized_video_path,
            output_dir=output_dir / "boundary_refinement",
            client=client,
            selected_span=detected_span,
            settings=settings,
            exercise_name=exercise_name,
        )
    return DetectionResult(
        video_path=str(sanitized_video_path),
        exercise_name=exercise_name,
        source_duration_seconds=metadata.duration_seconds,
        window_seconds=settings.window_seconds,
        overlap_seconds=settings.overlap_seconds,
        detected_span=detected_span,
        windows=detections,
        source_fps=metadata.fps,
        source_total_frames=metadata.frame_count,
        source_width=metadata.width,
        source_height=metadata.height,
    )


SUPPORT_DOMINANCE_LABELS = ("foot_dominant", "hand_dominant", "mixed_support", "uncertain")


def build_support_dominance_prompt(*, exercise_name: str | None) -> str:
    exercise_clause = (
        f"Target exercise: {exercise_name}.\n" if exercise_name and exercise_name.strip() else ""
    )
    exercise_value = exercise_name.strip() if exercise_name and exercise_name.strip() else "unknown"
    return (
        "You are classifying support usage in a rendered exercise preview.\n"
        f"{exercise_clause}"
        "Goal: choose the dominant support mode.\n"
        "Use only the visible frames.\n"
        "Rules:\n"
        '- "foot_dominant": primary support and propulsion come from feet/legs.\n'
        '- "hand_dominant": primary support and propulsion come from hands/arms.\n'
        '- "mixed_support": both hands and feet are meaningfully used as supports.\n'
        "If the evidence is split or unclear, return mixed_support and set uncertain=true.\n"
        "Read frames in attachment order.\n"
        "Output valid JSON only.\n"
        "Return this JSON schema exactly:\n"
        "{"
        f'"exercise": "{exercise_value}", '
        '"supportDominance": "foot_dominant|hand_dominant|mixed_support|uncertain", '
        '"confidence": 0.0, '
        '"uncertain": false, '
        '"reason": "short visual reason", '
        '"supportDominanceEvidence": "short visible cue summary"'
        "}\n"
    )


def classify_support_dominance_from_frames(
    *,
    frame_paths: list[Path],
    exercise_name: str | None,
    caption_images: Callable[[list[Path], str], str],
) -> SupportDominanceResult:
    payload = parse_support_dominance_payload(
        caption_images(
            frame_paths=frame_paths,
            prompt=build_support_dominance_prompt(exercise_name=exercise_name),
        ),
        exercise_name=exercise_name,
    )
    return payload


def classify_support_dominance_with_client(
    *,
    frame_paths: list[Path],
    exercise_name: str | None,
    client: object,
) -> SupportDominanceResult:
    caption_images = getattr(client, "caption_images", None)
    if not callable(caption_images):
        raise TypeError("support dominance classifier requires a caption_images() method")
    return classify_support_dominance_from_frames(
        frame_paths=frame_paths,
        exercise_name=exercise_name,
        caption_images=caption_images,
    )


def parse_support_dominance_payload(
    raw: str,
    *,
    exercise_name: str | None = None,
) -> SupportDominanceResult:
    payload = extract_json_object(raw)
    if payload is None:
        payload = extract_support_dominance_payload_loose(raw)
    if payload is None:
        return SupportDominanceResult(
            support_dominance="mixed_support",
            confidence=0.0,
            reason="Could not parse model output.",
            exercise_name=exercise_name,
            uncertain=True,
            model_output={"raw": raw},
        )
    payload = canonicalize_support_dominance_payload(payload)
    label = normalize_support_dominance_label(
        str(payload.get("supportDominance") or payload.get("supportDominanceLabel") or ""),
    )
    confidence = normalize_confidence(payload.get("confidence", 0.0))
    uncertain = bool(payload.get("uncertain", label == "uncertain"))
    reason = str(payload.get("reason", payload.get("supportDominanceEvidence", ""))).strip()
    if not reason:
        reason = "Model provided no clear rationale."
    return SupportDominanceResult(
        support_dominance=label,
        confidence=confidence,
        reason=reason,
        exercise_name=exercise_name,
        uncertain=uncertain,
        model_output=payload,
    )


def canonicalize_support_dominance_payload(payload: dict[str, object]) -> dict[str, object]:
    aliases = {
        "supportdominance": "supportDominance",
        "supportdominancelabel": "supportDominance",
        "dominance": "supportDominance",
        "dominancelabel": "supportDominance",
        "support": "supportDominance",
        "dominanceconfidence": "confidence",
        "supportDominanceevidence": "supportDominanceEvidence",
    }
    canonical = dict(payload)
    for key, value in list(payload.items()):
        normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        target_key = aliases.get(normalized_key)
        if target_key:
            canonical[target_key] = value
    return canonical


def extract_support_dominance_payload_loose(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if not text:
        return None

    label_match = re.search(r'"supportDominance"\s*:\s*"([^"]+)"', text, flags=re.IGNORECASE)
    if label_match is None:
        label_match = re.search(r'"support_dominance"\s*:\s*"([^"]+)"', text, flags=re.IGNORECASE)
    label = label_match.group(1).strip() if label_match is not None else "uncertain"

    confidence = 0.0
    confidence_match = re.search(
        r'"confidence"\s*:\s*(null|-?\d+(?:\.\d+)?)',
        text,
        flags=re.IGNORECASE,
    )
    if confidence_match is not None:
        value = confidence_match.group(1).lower()
        try:
            confidence = float(value if value != "null" else "0.0")
        except ValueError:
            confidence = 0.0

    reason_match = re.search(
        r'"reason"\s*:\s*"([^"]*)"',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    reason = reason_match.group(1).strip() if reason_match is not None else ""

    uncertain = bool(re.search(r'"uncertain"\s*:\s*true', text, flags=re.IGNORECASE))
    return {
        "supportDominance": label,
        "confidence": confidence,
        "uncertain": uncertain,
        "reason": reason,
    }


def normalize_support_dominance_label(value: str) -> str:
    normalized = re.sub(r"[^a-z]+", "", value.lower())
    if normalized in {"foot", "feet", "footsupport", "foot_dominant", "footdominant", "doublefoot", "doublesupport", "bothfeet"}:
        return "foot_dominant"
    if normalized in {"hand", "hands", "handsupport", "hand_dominant", "handdominant", "doublehands", "doublehandsupport", "bothhands"}:
        return "hand_dominant"
    if normalized in {"mixed", "mixedsupport", "uncertain", "both"}:
        return "mixed_support"
    return "mixed_support"


def refine_detected_span_with_smaller_windows(
    *,
    video_path: Path,
    output_dir: Path,
    client: object,
    metadata: VideoMetadata,
    coarse_span: DetectedSpan,
    settings: DetectionSettings,
    exercise_name: str | None,
) -> tuple[DetectedSpan, list[WindowDetection]]:
    if settings.refinement_window_seconds <= 0.0 or settings.refinement_frames_per_window <= 0:
        return coarse_span, []

    refinement_start = max(0.0, coarse_span.start_seconds - max(0.0, settings.refinement_padding_seconds))
    refinement_end = min(
        metadata.duration_seconds,
        coarse_span.end_seconds + max(0.0, settings.refinement_padding_seconds),
    )
    if refinement_end <= refinement_start:
        return coarse_span, []

    refinement_detections: list[WindowDetection] = []
    window = DetectionWindow(
        index=10_000,
        start_seconds=refinement_start,
        end_seconds=refinement_end,
    )
    frame_paths = extract_window_frames(
        video_path=video_path,
        window=window,
        frames_per_window=settings.refinement_frames_per_window,
        max_frame_width=settings.max_frame_width,
        contact_sheet_enabled=settings.contact_sheet_enabled,
        contact_sheet_columns=settings.contact_sheet_columns,
        contact_sheet_tile_width=settings.refinement_contact_sheet_tile_width,
        contact_sheet_frames_per_sheet=settings.contact_sheet_frames_per_sheet,
        contact_sheet_jpeg_quality=settings.contact_sheet_jpeg_quality,
        output_dir=output_dir / "window_0000",
    )
    refinement_detections.append(
        client.detect_window(
            frame_paths=frame_paths,
            window=window,
            exercise_name=exercise_name,
            require_complete_execution=True,
        )
    )

    refined_span = choose_detected_span(
        detections=refinement_detections,
        confidence_threshold=settings.confidence_threshold,
        merge_gap_seconds=min(settings.merge_gap_seconds, settings.refinement_window_seconds),
        min_segment_seconds=settings.min_segment_seconds,
        max_segment_seconds=settings.max_segment_seconds,
        settings=settings,
    )
    if refined_span is None:
        return coarse_span, refinement_detections
    if not refined_span_overlaps_coarse_span(refined_span=refined_span, coarse_span=coarse_span):
        return coarse_span, refinement_detections
    constrained_span = constrain_refined_span_to_coarse_span(
        refined_span=refined_span,
        coarse_span=coarse_span,
        settings=settings,
    )
    if constrained_span is None:
        return coarse_span, refinement_detections
    if not should_accept_refined_span(
        parent_span=coarse_span,
        refined_span=constrained_span,
        settings=settings,
    ):
        return coarse_span, refinement_detections
    return constrained_span, refinement_detections


def refine_detected_span_with_active_search(
    *,
    video_path: Path,
    output_dir: Path,
    client: LlamaCppVisionClient,
    metadata: VideoMetadata,
    coarse_span: DetectedSpan,
    settings: DetectionSettings,
    exercise_name: str | None,
) -> tuple[DetectedSpan, list[WindowDetection]]:
    current_span = coarse_span
    detections: list[WindowDetection] = []
    for round_index in range(max(0, settings.active_refinement_max_rounds)):
        current_duration = current_span.end_seconds - current_span.start_seconds
        if current_duration <= settings.active_refinement_tolerance_seconds:
            break
        subwindows = build_active_refinement_windows(
            span=current_span,
            metadata=metadata,
            round_index=round_index,
            settings=settings,
        )
        if not subwindows:
            break

        def classify_subwindow(window: DetectionWindow) -> WindowDetection:
            frame_paths = extract_window_frames(
                video_path=video_path,
                window=window,
                frames_per_window=settings.refinement_frames_per_window,
                max_frame_width=settings.max_frame_width,
                contact_sheet_enabled=settings.contact_sheet_enabled,
                contact_sheet_columns=settings.contact_sheet_columns,
                contact_sheet_tile_width=settings.refinement_contact_sheet_tile_width,
                contact_sheet_frames_per_sheet=settings.contact_sheet_frames_per_sheet,
                contact_sheet_jpeg_quality=settings.contact_sheet_jpeg_quality,
                output_dir=output_dir / f"round_{round_index:02d}" / f"window_{window.index:04d}",
            )
            return client.detect_window(
                frame_paths=frame_paths,
                window=window,
                exercise_name=exercise_name,
                require_complete_execution=True,
            )

        accepted_span: DetectedSpan | None = None
        for subwindow in order_active_refinement_windows(subwindows=subwindows, parent_span=current_span):
            round_detection = classify_subwindow(subwindow)
            detections.append(round_detection)
            refined_span = choose_detected_span(
                detections=[round_detection],
                confidence_threshold=settings.confidence_threshold,
                merge_gap_seconds=min(settings.merge_gap_seconds, current_duration),
                min_segment_seconds=settings.min_segment_seconds,
                max_segment_seconds=min(settings.max_segment_seconds, current_duration),
                settings=settings,
            )
            if refined_span is None:
                continue
            constrained_span = constrain_refined_span_to_coarse_span(
                refined_span=refined_span,
                coarse_span=current_span,
                settings=settings,
            )
            if constrained_span is None:
                continue
            if not should_accept_refined_span(
                parent_span=current_span,
                refined_span=constrained_span,
                settings=settings,
            ):
                continue
            accepted_span = constrained_span
            break
        if accepted_span is None:
            break
        if (accepted_span.end_seconds - accepted_span.start_seconds) >= current_duration - 0.05:
            break
        current_span = accepted_span
    return current_span, detections


def build_active_refinement_windows(
    *,
    span: DetectedSpan,
    metadata: VideoMetadata,
    round_index: int,
    settings: DetectionSettings,
) -> list[DetectionWindow]:
    span_duration = span.end_seconds - span.start_seconds
    if span_duration <= 0:
        return []
    subwindow_seconds = max(settings.min_segment_seconds, span_duration * 0.65)
    overlap_seconds = max(
        0.0,
        min(subwindow_seconds - 0.25, subwindow_seconds * settings.active_refinement_overlap_ratio),
    )
    relative_windows = iter_detection_windows(
        duration_seconds=span_duration,
        window_seconds=subwindow_seconds,
        overlap_seconds=overlap_seconds,
    )
    windows: list[DetectionWindow] = []
    for relative_window in relative_windows:
        start_seconds = max(0.0, span.start_seconds + relative_window.start_seconds)
        end_seconds = min(metadata.duration_seconds, span.start_seconds + relative_window.end_seconds)
        if end_seconds <= start_seconds:
            continue
        windows.append(
            DetectionWindow(
                index=20_000 + round_index * 1_000 + len(windows),
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        )
    return windows


def order_active_refinement_windows(
    *,
    subwindows: list[DetectionWindow],
    parent_span: DetectedSpan,
) -> list[DetectionWindow]:
    parent_midpoint = (parent_span.start_seconds + parent_span.end_seconds) / 2.0
    return sorted(
        subwindows,
        key=lambda window: (
            abs(((window.start_seconds + window.end_seconds) / 2.0) - parent_midpoint),
            window.end_seconds - window.start_seconds,
        ),
    )


def refined_span_overlaps_coarse_span(*, refined_span: DetectedSpan, coarse_span: DetectedSpan) -> bool:
    overlap_start = max(refined_span.start_seconds, coarse_span.start_seconds)
    overlap_end = min(refined_span.end_seconds, coarse_span.end_seconds)
    if overlap_end <= overlap_start:
        return False
    refined_duration = max(0.001, refined_span.end_seconds - refined_span.start_seconds)
    coarse_duration = max(0.001, coarse_span.end_seconds - coarse_span.start_seconds)
    return (overlap_end - overlap_start) >= min(refined_duration, coarse_duration) * 0.25


def constrain_refined_span_to_coarse_span(
    *,
    refined_span: DetectedSpan,
    coarse_span: DetectedSpan,
    settings: DetectionSettings,
) -> DetectedSpan | None:
    start_seconds = max(refined_span.start_seconds, coarse_span.start_seconds)
    end_seconds = min(refined_span.end_seconds, coarse_span.end_seconds)
    if end_seconds <= start_seconds:
        return None
    constrained = DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=refined_span.confidence,
        average_camera_variation=refined_span.average_camera_variation,
        contributing_windows=list(refined_span.contributing_windows),
    )
    if not _span_has_reasonable_length(
        constrained,
        min_segment_seconds=settings.min_segment_seconds,
        max_segment_seconds=settings.max_segment_seconds,
    ):
        return None
    return constrained


def should_accept_refined_span(
    *,
    parent_span: DetectedSpan,
    refined_span: DetectedSpan,
    settings: DetectionSettings,
) -> bool:
    parent_duration = max(0.001, parent_span.end_seconds - parent_span.start_seconds)
    refined_duration = max(0.001, refined_span.end_seconds - refined_span.start_seconds)
    if refined_duration < parent_duration * max(0.0, settings.min_refinement_duration_ratio):
        return False
    parent_score = max(0.001, parent_span.confidence)
    if refined_span.confidence < parent_score * max(0.0, settings.min_refined_score_ratio):
        return False
    return True


def save_detection_result(path: Path, result: DetectionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "videoPath": result.video_path,
        "exerciseName": result.exercise_name,
        "sourceDurationSeconds": result.source_duration_seconds,
        "sourceFps": result.source_fps,
        "sourceTotalFrames": result.source_total_frames,
        "sourceResolution": {
            "width": result.source_width,
            "height": result.source_height,
        },
        "windowSeconds": result.window_seconds,
        "overlapSeconds": result.overlap_seconds,
        "detectedSpan": None if result.detected_span is None else asdict(result.detected_span),
        "windows": [
            {
                "index": item.window.index,
                "startSeconds": item.window.start_seconds,
                "endSeconds": item.window.end_seconds,
                "movementPresent": item.movement_present,
                "containsMovementStart": item.contains_movement_start,
                "containsMovementEnd": item.contains_movement_end,
                "movementStartSeconds": item.movement_start_seconds,
                "movementEndSeconds": item.movement_end_seconds,
                "confidence": item.confidence,
                "summary": item.summary,
                "reason": item.reason,
                "cameraVariation": item.camera_variation,
                "framePaths": item.frame_paths,
                "executions": [asdict(execution) for execution in item.executions],
            }
            for item in result.windows
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_video_metadata(video_path: Path) -> VideoMetadata:
    basic = read_basic_video_metadata(video_path)
    return VideoMetadata(
        duration_seconds=basic.duration_seconds,
        fps=basic.fps,
        frame_count=basic.frame_count,
        width=basic.width,
        height=basic.height,
    )


def detect_motion_candidate_intervals(
    *,
    video_path: Path,
    metadata: VideoMetadata,
    settings: DetectionSettings,
) -> list[MotionInterval]:
    try:
        import cv2
    except ImportError:
        return [MotionInterval(0.0, metadata.duration_seconds, 1.0)]

    if metadata.duration_seconds <= 0:
        return []
    sample_fps = max(0.25, settings.motion_sample_fps)
    sample_step_seconds = 1.0 / sample_fps
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return [MotionInterval(0.0, metadata.duration_seconds, 1.0)]
    samples: list[tuple[float, float]] = []
    previous_gray = None
    timestamp_seconds = 0.0
    try:
        while timestamp_seconds <= metadata.duration_seconds:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000.0)
            ok, frame = capture.read()
            if not ok:
                timestamp_seconds += sample_step_seconds
                continue
            if settings.max_frame_width > 0 and frame.shape[1] > settings.max_frame_width:
                scale = settings.max_frame_width / float(frame.shape[1])
                target_size = (settings.max_frame_width, max(1, int(round(frame.shape[0] * scale))))
                frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            if previous_gray is not None:
                score = float(cv2.absdiff(gray, previous_gray).mean())
                samples.append((timestamp_seconds, score))
            previous_gray = gray
            timestamp_seconds += sample_step_seconds
    finally:
        capture.release()
    if not samples:
        return [MotionInterval(0.0, metadata.duration_seconds, 1.0)]

    scores = sorted(score for _, score in samples)
    high_score = scores[int((len(scores) - 1) * 0.9)]
    median_score = scores[len(scores) // 2]
    threshold = median_score + (high_score - median_score) * max(0.0, min(1.0, settings.motion_threshold_ratio))
    active_samples = [(timestamp, score) for timestamp, score in samples if score >= threshold]
    if not active_samples:
        return [MotionInterval(0.0, metadata.duration_seconds, 1.0)]

    intervals: list[MotionInterval] = []
    current_start = active_samples[0][0]
    current_end = active_samples[0][0]
    current_scores = [active_samples[0][1]]
    max_gap = max(sample_step_seconds * 2.0, settings.motion_merge_gap_seconds)
    for timestamp, score in active_samples[1:]:
        if timestamp - current_end <= max_gap:
            current_end = timestamp
            current_scores.append(score)
            continue
        intervals.append(
            _build_motion_interval(
                start_seconds=current_start,
                end_seconds=current_end,
                scores=current_scores,
                duration_seconds=metadata.duration_seconds,
                settings=settings,
            )
        )
        current_start = timestamp
        current_end = timestamp
        current_scores = [score]
    intervals.append(
        _build_motion_interval(
            start_seconds=current_start,
            end_seconds=current_end,
            scores=current_scores,
            duration_seconds=metadata.duration_seconds,
            settings=settings,
        )
    )
    intervals = [
        interval
        for interval in merge_motion_intervals(intervals, merge_gap_seconds=settings.motion_merge_gap_seconds)
        if interval.end_seconds - interval.start_seconds >= settings.motion_min_interval_seconds
    ]
    if not intervals:
        return [MotionInterval(0.0, metadata.duration_seconds, 1.0)]
    return sorted(intervals, key=lambda item: item.score, reverse=True)[: max(1, settings.max_motion_candidates)]


def _build_motion_interval(
    *,
    start_seconds: float,
    end_seconds: float,
    scores: list[float],
    duration_seconds: float,
    settings: DetectionSettings,
) -> MotionInterval:
    padding = max(0.0, settings.motion_padding_seconds)
    return MotionInterval(
        start_seconds=max(0.0, start_seconds - padding),
        end_seconds=min(duration_seconds, end_seconds + padding),
        score=sum(scores) / max(1, len(scores)),
    )


def merge_motion_intervals(intervals: list[MotionInterval], *, merge_gap_seconds: float) -> list[MotionInterval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item.start_seconds)
    merged: list[MotionInterval] = [ordered[0]]
    for interval in ordered[1:]:
        previous = merged[-1]
        if interval.start_seconds - previous.end_seconds > merge_gap_seconds:
            merged.append(interval)
            continue
        merged[-1] = MotionInterval(
            start_seconds=previous.start_seconds,
            end_seconds=max(previous.end_seconds, interval.end_seconds),
            score=max(previous.score, interval.score),
        )
    return merged


def _normalized_chunk_retry_multipliers(multipliers: tuple[float, ...]) -> tuple[float, ...]:
    cleaned = sorted({float(value) for value in multipliers if float(value) > 0.0})
    if not cleaned:
        return (1.0,)
    if 1.0 not in cleaned:
        cleaned.insert(0, 1.0)
    return tuple(cleaned)


def _classify_detection_windows_parallel(
    *,
    windows: list[DetectionWindow],
    classify_window: Callable[[DetectionWindow], WindowDetection],
    classification_workers: int,
) -> list[WindowDetection]:
    if not windows:
        return []
    worker_count = max(1, min(classification_workers, len(windows)))
    if worker_count == 1:
        return [classify_window(window) for window in windows]
    detections_by_index: dict[int, WindowDetection] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(classify_window, window): window for window in windows}
        for future in as_completed(futures):
            window = futures[future]
            detections_by_index[window.index] = future.result()
    return [detections_by_index[window.index] for window in windows]


def iter_detection_windows_for_intervals(
    *,
    intervals: list[MotionInterval],
    duration_seconds: float,
    window_seconds: float,
    overlap_seconds: float,
) -> list[DetectionWindow]:
    if not intervals:
        return iter_detection_windows(
            duration_seconds=duration_seconds,
            window_seconds=window_seconds,
            overlap_seconds=overlap_seconds,
        )
    windows: list[DetectionWindow] = []
    seen: set[tuple[float, float]] = set()
    for interval in sorted(intervals, key=lambda item: item.start_seconds):
        interval_duration = max(0.0, interval.end_seconds - interval.start_seconds)
        if interval_duration <= window_seconds:
            start = max(0.0, min(interval.start_seconds, duration_seconds))
            end = min(duration_seconds, max(interval.end_seconds, start + min(window_seconds, duration_seconds - start)))
            start = max(0.0, min(start, max(0.0, end - window_seconds)))
            key = (round(start, 3), round(end, 3))
            if key not in seen and end > start:
                seen.add(key)
                windows.append(DetectionWindow(index=len(windows), start_seconds=start, end_seconds=end))
            continue
        for window in iter_detection_windows(
            duration_seconds=interval_duration,
            window_seconds=window_seconds,
            overlap_seconds=overlap_seconds,
        ):
            start = interval.start_seconds + window.start_seconds
            end = min(duration_seconds, interval.start_seconds + window.end_seconds)
            key = (round(start, 3), round(end, 3))
            if key in seen or end <= start:
                continue
            seen.add(key)
            windows.append(DetectionWindow(index=len(windows), start_seconds=start, end_seconds=end))
    return windows


def iter_detection_windows(
    *,
    duration_seconds: float,
    window_seconds: float,
    overlap_seconds: float,
) -> list[DetectionWindow]:
    if duration_seconds <= 0:
        return []
    window_seconds = max(0.5, window_seconds)
    step_seconds = max(0.25, window_seconds - overlap_seconds)
    windows: list[DetectionWindow] = []
    start = 0.0
    index = 0
    while start < duration_seconds:
        end = min(duration_seconds, start + window_seconds)
        windows.append(DetectionWindow(index=index, start_seconds=start, end_seconds=end))
        index += 1
        if end >= duration_seconds:
            break
        start += step_seconds
    return windows


def extract_window_frames(
    *,
    video_path: Path,
    window: DetectionWindow,
    frames_per_window: int,
    max_frame_width: int,
    contact_sheet_enabled: bool = True,
    contact_sheet_columns: int = 4,
    contact_sheet_tile_width: int = 480,
    contact_sheet_frames_per_sheet: int = 8,
    contact_sheet_jpeg_quality: int = 90,
    output_dir: Path,
) -> list[Path]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for exercise segment detection. Install with: pip install -e .[motion]"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    times = linspace_times(window.start_seconds, window.end_seconds, max(1, frames_per_window))
    ffmpeg_available = shutil.which("ffmpeg") is not None
    frame_paths = extract_window_frames_with_ffmpeg(
        video_path=video_path,
        times=times,
        max_frame_width=max_frame_width,
        output_dir=output_dir,
    )
    if not frame_paths and not ffmpeg_available:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        try:
            for frame_index, timestamp_seconds in enumerate(times, start=1):
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000.0)
                ok, frame = capture.read()
                if not ok:
                    continue
                if max_frame_width > 0 and frame.shape[1] > max_frame_width:
                    scale = max_frame_width / float(frame.shape[1])
                    target_size = (max_frame_width, max(1, int(round(frame.shape[0] * scale))))
                    frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
                frame_path = output_dir / f"frame_{frame_index:02d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                frame_paths.append(frame_path)
        finally:
            capture.release()
    if not frame_paths:
        raise RuntimeError(
            f"No frames could be extracted for window {window.index} ({window.start_seconds:.2f}-{window.end_seconds:.2f}s)."
        )
    if contact_sheet_enabled:
        contact_sheet_paths = build_frame_contact_sheets(
            frame_paths=frame_paths,
            timestamps=times[: len(frame_paths)],
            output_dir=output_dir,
            columns=contact_sheet_columns,
            tile_width=contact_sheet_tile_width,
            frames_per_sheet=contact_sheet_frames_per_sheet,
            jpeg_quality=contact_sheet_jpeg_quality,
        )
        if contact_sheet_paths:
            return contact_sheet_paths
    return frame_paths


def extract_window_frames_with_ffmpeg(
    *,
    video_path: Path,
    times: list[float],
    max_frame_width: int,
    output_dir: Path,
) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []
    frame_paths: list[Path] = []
    scale_filter = []
    if max_frame_width > 0:
        scale_filter = ["-vf", f"scale='min({max_frame_width},iw)':-2"]
    for frame_index, timestamp_seconds in enumerate(times, start=1):
        frame_path = output_dir / f"frame_{frame_index:02d}.jpg"
        command = [
            ffmpeg,
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            *scale_filter,
            "-q:v",
            "5",
            str(frame_path),
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
            frame_paths.append(frame_path)
    return frame_paths


def build_frame_contact_sheets(
    *,
    frame_paths: list[Path],
    timestamps: list[float],
    output_dir: Path,
    columns: int,
    tile_width: int,
    frames_per_sheet: int,
    jpeg_quality: int,
) -> list[Path]:
    frames_per_sheet = max(1, frames_per_sheet)
    contact_sheets: list[Path] = []
    for sheet_index, start_index in enumerate(range(0, len(frame_paths), frames_per_sheet), start=1):
        sheet_frame_paths = frame_paths[start_index : start_index + frames_per_sheet]
        sheet_timestamps = timestamps[start_index : start_index + frames_per_sheet]
        sheet_path = build_frame_contact_sheet(
            frame_paths=sheet_frame_paths,
            timestamps=sheet_timestamps,
            output_path=output_dir / f"contact_sheet_{sheet_index:02d}.jpg",
            columns=columns,
            tile_width=tile_width,
            jpeg_quality=jpeg_quality,
        )
        if sheet_path is not None:
            contact_sheets.append(sheet_path)
    return contact_sheets


def build_frame_contact_sheet(
    *,
    frame_paths: list[Path],
    timestamps: list[float],
    output_path: Path,
    columns: int,
    tile_width: int,
    jpeg_quality: int,
) -> Path | None:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    if not frame_paths:
        return None
    columns = max(1, columns)
    tile_width = max(160, tile_width)
    jpeg_quality = max(1, min(100, jpeg_quality))
    tiles = []
    tile_height = None
    for index, frame_path in enumerate(frame_paths):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            continue
        scale = tile_width / float(frame.shape[1])
        target_height = max(1, int(round(frame.shape[0] * scale)))
        resized = cv2.resize(frame, (tile_width, target_height), interpolation=cv2.INTER_AREA)
        if tile_height is None:
            tile_height = target_height
        elif target_height != tile_height:
            resized = cv2.resize(resized, (tile_width, tile_height), interpolation=cv2.INTER_AREA)
        timestamp = timestamps[index] if index < len(timestamps) else 0.0
        label = f"t={timestamp:.2f}s"
        cv2.rectangle(resized, (0, 0), (150, 34), (0, 0, 0), thickness=-1)
        cv2.putText(
            resized,
            label,
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        tiles.append(resized)
    if not tiles or tile_height is None:
        return None
    rows = (len(tiles) + columns - 1) // columns
    sheet = np.full((rows * tile_height, columns * tile_width, 3), 24, dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row = index // columns
        column = index % columns
        y = row * tile_height
        x = column * tile_width
        sheet[y : y + tile_height, x : x + tile_width] = tile
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(output_path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok or not output_path.exists() or output_path.stat().st_size <= 0:
        return None
    return output_path


def linspace_times(start_seconds: float, end_seconds: float, count: int) -> list[float]:
    if count <= 1:
        return [start_seconds]
    duration = max(0.0, end_seconds - start_seconds)
    if duration <= 0:
        return [start_seconds] * count
    usable_end = max(start_seconds, end_seconds - min(0.05, duration / 2.0))
    step = (usable_end - start_seconds) / float(count - 1)
    return [start_seconds + step * index for index in range(count)]


class LlamaCppVisionClient:
    def __init__(
        self,
        base_url: str | None,
        model: str,
        *,
        backend: str = "gpu",
        n_predict: int = 768,
        temperature: float = 0.2,
        top_p: float | None = None,
        top_k: int | None = None,
        disable_reasoning: bool = True,
        image_min_tokens: int | None = None,
        image_max_tokens: int | None = None,
        request_timeout_seconds: float = 90.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url is not None else None
        self.model = model
        self.backend = backend
        self.n_predict = max(1, n_predict)
        self.temperature = max(0.0, float(temperature))
        self.top_p = None if top_p is None else max(0.0, min(1.0, float(top_p)))
        self.top_k = None if top_k is None else max(0, int(top_k))
        self.disable_reasoning = disable_reasoning
        self.image_min_tokens = image_min_tokens
        self.image_max_tokens = image_max_tokens
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.client = httpx.Client(timeout=self.request_timeout_seconds)

    def detect_window(
        self,
        *,
        frame_paths: list[Path],
        window: DetectionWindow,
        exercise_name: str | None,
        require_complete_execution: bool = True,
    ) -> WindowDetection:
        prompt = build_window_prompt(
            exercise_name=exercise_name,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            require_complete_execution=require_complete_execution,
        )
        raw = self.caption_images(frame_paths=frame_paths, prompt=prompt)
        try:
            payload = parse_detection_payload(raw, window=window)
        except RuntimeError:
            return build_unusable_window_detection(window=window, frame_paths=frame_paths, reason=raw)
        return WindowDetection(
            window=window,
            movement_present=payload["movement_present"],
            contains_movement_start=payload["contains_movement_start"],
            contains_movement_end=payload["contains_movement_end"],
            movement_start_seconds=payload["movement_start_seconds"],
            movement_end_seconds=payload["movement_end_seconds"],
            confidence=payload["confidence"],
            summary=payload["summary"],
            reason=payload["reason"],
            camera_variation=compute_camera_variation(frame_paths),
            executions=payload["executions"],
            frame_paths=[str(path) for path in frame_paths],
        )

    def caption_images(self, *, frame_paths: list[Path], prompt: str, max_tokens: int | None = None) -> str:
        if self.base_url is None:
            raise RuntimeError("llama-cpp vision mode requires a base URL.")
        return self._caption_images_via_server(frame_paths=frame_paths, prompt=prompt, max_tokens=max_tokens)

    def _caption_images_via_server(
        self,
        *,
        frame_paths: list[Path],
        prompt: str,
        max_tokens: int | None = None,
    ) -> str:
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
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": self.temperature,
            "max_tokens": self.n_predict if max_tokens is None else max(1, int(max_tokens)),
            "response_format": {"type": "json_object"},
        }
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        if self.disable_reasoning:
            payload["reasoning_format"] = "none"
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        else:
            payload["reasoning_format"] = "deepseek"
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        if self.base_url is None:
            raise RuntimeError("llama-cpp server mode requires base URL.")
        response = self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if response.status_code >= 400:
            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            fallback_payload.pop("reasoning_format", None)
            fallback_payload.pop("chat_template_kwargs", None)
            response = self.client.post(f"{self.base_url}/v1/chat/completions", json=fallback_payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


class VisionClient:
    def detect_window(
        self,
        *,
        frame_paths: list[Path],
        window: DetectionWindow,
        exercise_name: str | None,
        require_complete_execution: bool = True,
    ) -> WindowDetection:
        raise NotImplementedError


class LiteRtCliVisionClient(VisionClient):
    def __init__(self, *, command: str, model: str, backend: str) -> None:
        self.command = command
        self.model = model
        self.backend = backend

    def detect_window(
        self,
        *,
        frame_paths: list[Path],
        window: DetectionWindow,
        exercise_name: str | None,
        require_complete_execution: bool = True,
    ) -> WindowDetection:
        prompt = build_window_prompt(
            exercise_name=exercise_name,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            require_complete_execution=require_complete_execution,
        )
        raw = self.caption_images(frame_paths=frame_paths, prompt=prompt)
        try:
            payload = parse_detection_payload(raw, window=window)
        except RuntimeError:
            return build_unusable_window_detection(window=window, frame_paths=frame_paths, reason=raw)
        return WindowDetection(
            window=window,
            movement_present=payload["movement_present"],
            contains_movement_start=payload["contains_movement_start"],
            contains_movement_end=payload["contains_movement_end"],
            movement_start_seconds=payload["movement_start_seconds"],
            movement_end_seconds=payload["movement_end_seconds"],
            confidence=payload["confidence"],
            summary=payload["summary"],
            reason=payload["reason"],
            camera_variation=compute_camera_variation(frame_paths),
            executions=payload["executions"],
            frame_paths=[str(path) for path in frame_paths],
        )

    def caption_images(self, *, frame_paths: list[Path], prompt: str) -> str:
        command = [
            self.command,
            "run",
            self.model,
            "--backend",
            self.backend,
            "--vision-backend",
            self.backend,
            "--prompt",
            prompt,
        ]
        for frame_path in frame_paths:
            command.extend(["--attachment", str(frame_path)])
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


def build_window_prompt(
    *,
    exercise_name: str | None,
    start_seconds: float,
    end_seconds: float,
    require_complete_execution: bool = True,
) -> str:
    exercise_clause = (
        f"Optional movement label: {exercise_name}.\n"
        if exercise_name and exercise_name.strip()
        else ""
    )
    exercise_value = exercise_name.strip() if exercise_name and exercise_name.strip() else "unknown"
    movement_presence_rule = (
        "- movement_present is true only when the full execution is visibly complete in this window.\n"
        "- If there are only setup, recovery, or fragmentary frames, movement_present is false.\n"
        if require_complete_execution
        else "- movement_present is true when this shorter refinement window contains active target-exercise movement, even if it is only part of the execution.\n"
        "- If there is only setup, idle, recovery, or a static hold with no active target movement, movement_present is false.\n"
    )
    timing_hint_rule = (
        "- movement_start_seconds and movement_end_seconds are coarse timing hints only (window-local seconds).\n"
        if require_complete_execution
        else "- movement_start_seconds and movement_end_seconds should bracket the active movement visible inside this shorter window, in window-local seconds.\n"
    )
    return (
        "You are classifying a short chunk from an exercise video.\n"
        f"Goal: decide whether this window contains {'at least one complete target movement execution' if require_complete_execution else 'active target movement'}.\n"
        f"Window time range in source video: {start_seconds:.2f}s to {end_seconds:.2f}s.\n"
        f"{exercise_clause}"
        "Primary task:\n"
        f"- Prefer classification. Decide if this is {'a full execution' if require_complete_execution else 'active target movement'}, not an exact frame boundary task.\n"
        "- The system will use the entire source chunk as the selected segment if this candidate wins. Score whether the whole chunk is a good clean source segment; do not reward a chunk only because a small sub-part is good.\n"
        f"{movement_presence_rule}"
        "- movement_present is also false when the camera moves, pans, zooms, reframes, or cuts during the movement.\n"
        "- movement_present is false when the athlete or implement leaves the frame during the movement.\n"
        "- movement_present is false when more than one person is close enough to confuse tracking.\n"
        "- movement_present is false when obstacles, spotters, equipment, text overlays, or other bodies obstruct key joints or the implement path.\n"
        "- movement_present is false when the movement is intentionally slowed down for teaching, broken into steps, paused between phases, or demonstrated as separate positions instead of normal-speed continuous execution.\n"
        "- movement_present is false when the visible action is a different movement, stretch, hold, setup transition, or unrelated exercise instead of the requested target exercise.\n"
        "- movement_present is false for title cards, disclaimers, intro/outro graphics, instruction-only screens, thumbnails, preview panels, or a person shown inside a TV/computer/phone screen rather than as the actual full-frame demonstration.\n"
        "Definitions:\n"
        "- setup: getting ready, walking, positioning, bracing, or idle before the movement.\n"
        "- movement: actively performing the target exercise movement at normal demonstration or training speed.\n"
        "- finish: the execution reaches a stable end position.\n"
        "- recovery: after the execution, lowering, walking away, resetting, or idle.\n"
        "- idle: no meaningful exercise action.\n"
        "- unclear: not enough visual evidence.\n"
        "Rules:\n"
        "- Use only the visible frames.\n"
        "- If frames are packed into strips, read each strip left-to-right, and read strips in attachment order.\n"
        "- read them in frame-number order, left-to-right within each row and then top-to-bottom across rows.\n"
        "- Ignore instructional text, logos, title cards, and still demonstration poses unless movement is visible.\n"
        "- Accept only a fixed-camera, single-subject, unobstructed, fully-in-frame movement as usable.\n"
        "- The usable athlete must be the actual person in the video scene, not an embedded picture/video on a monitor, phone, TV, poster, or thumbnail.\n"
        "- Accept only complete executions done at normal speed. Reject deliberate slow-motion, teaching-speed breakdowns, position-by-position demos, pauses inserted to explain form, or clips where the movement is split into isolated steps.\n"
        f"- The target exercise is {exercise_value}. Score target_exercise_match as 1.0 only when the visible movement clearly matches this exact exercise. Use 0.0 for a different exercise, static hold, reaching variation, stretch, transition, or unrelated movement.\n"
        "- A candidate is complete only if it shows one whole exercise repetition/cycle: the start posture, the full action path, and the end posture or return/control phase.\n"
        "- For cyclical or mobility exercises, complete means the visible segment includes both meaningful endpoint postures plus the transition between them, not just the transition or one endpoint.\n"
        "- For strength exercises, complete means the visible segment includes the setup/start position, the main effort path, and the finish or controlled return.\n"
        "- Do not infer missing start/end postures from context outside this window. If the first or last required posture is outside the window, this is partial.\n"
        "- Mark partial_movement true when the candidate is too short and only shows part of the full movement, even if that part is clear and high quality.\n"
        "- full_movement_coverage estimates how much of one full target exercise cycle is visible inside the candidate: 1.0 means the complete cycle, 0.5 means roughly half.\n"
        "- quality is the overall usefulness of this candidate for trimming one clean exercise segment. Give high quality only when the candidate contains the whole target movement at normal speed with little extra before/after. Give low quality to a short partial movement, even if the visible phase is clear.\n"
        "- loop_quality estimates how well this candidate can be looped: high when there is a complete movement and the suggested loop start/end poses are visually similar enough for a usable loop. It does not need to be perfect.\n"
        "- suggested_loop_start_seconds and suggested_loop_end_seconds are source-video timestamp hints for the best usable loop inside this candidate. They may be approximate.\n"
        "- Prefer a slightly longer complete movement over a shorter partial movement. Do not mark a partial transition as a complete execution.\n"
        "- Output valid JSON only. No prose outside JSON.\n"
        f"{timing_hint_rule}"
        "- Use hints only to mark likely movement boundaries; do not be precise.\n"
        "- execution candidates, if provided, are optional and are hints, not hard boundaries.\n"
        "- quality and confidence must be between 0 and 1.\n"
        "Return this JSON schema exactly:\n"
        "{"
        f'"exercise": "{exercise_value}", '
        '"phase": "setup|movement|finish|recovery|idle|unclear", '
        '"movement_present": true, '
        '"contains_movement_start": true, '
        '"contains_movement_end": true, '
        '"movement_start_seconds": number|null, '
        '"movement_end_seconds": number|null, '
        '"confidence": 0.0, '
        '"reason": "short visual reason", '
        '"summary": "short summary", '
        '"executions": ['
        "{"
        '"start_seconds": 0.0, '
        '"end_seconds": 0.0, '
        '"complete": true, '
        '"single_execution": true, '
        '"normal_speed": true, '
        '"not_broken_into_steps": true, '
        '"fixed_camera": true, '
        '"single_person": true, '
        '"fully_in_frame": true, '
        '"unobstructed": true, '
        '"extra_motion_before": false, '
        '"extra_motion_after": false, '
        '"partial_movement": false, '
        '"full_movement_coverage": 1.0, '
        '"start_posture_visible": true, '
        '"full_action_path_visible": true, '
        '"end_posture_visible": true, '
        '"target_exercise_match": 1.0, '
        '"wrong_exercise_or_unrelated_movement": false, '
        '"loop_quality": 0.0, '
        '"suggested_loop_start_seconds": number|null, '
        '"suggested_loop_end_seconds": number|null, '
        '"actual_demonstration": true, '
        '"title_or_instruction_screen": false, '
        '"screen_with_embedded_video": false, '
        '"contains_multiple_executions": false, '
        '"contains_idle_or_reset": false, '
        '"quality": 0.0, '
        '"confidence": 0.0, '
        '"start_reason": "short visual reason", '
        '"end_reason": "short visual reason"'
        "}]"
        "}\n"
    )


def parse_detection_payload(raw: str, *, window: DetectionWindow) -> dict[str, object]:
    payload = extract_json_object(raw)
    if payload is None:
        payload = extract_detection_payload_loose(raw)
    if payload is None:
        raise RuntimeError(f"Segment detector returned invalid JSON: {raw[:300]!r}")
    payload = canonicalize_detection_payload(payload)
    has_executions_field = "executions" in payload
    movement_present = bool(payload.get("movement_present", False))
    movement_start_seconds = normalize_window_relative_seconds(payload.get("movement_start_seconds"), window=window)
    movement_end_seconds = normalize_window_relative_seconds(payload.get("movement_end_seconds"), window=window)
    confidence = normalize_confidence(payload.get("confidence", 0.0))
    summary = str(payload.get("summary", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    raw_executions = payload.get("executions")
    model_executions = parse_execution_payloads(raw_executions, window=window)
    if not model_executions and movement_present and not has_executions_field:
        model_executions = (
            CandidateExecution(
                start_seconds=(
                    window.start_seconds
                    if movement_start_seconds is None
                    else window.start_seconds + movement_start_seconds
                ),
                end_seconds=(
                    window.end_seconds
                    if movement_end_seconds is None
                    else window.start_seconds + movement_end_seconds
                ),
                complete=movement_start_seconds is not None and movement_end_seconds is not None,
                single_execution=movement_start_seconds is not None and movement_end_seconds is not None,
                normal_speed=True,
                not_broken_into_steps=True,
                fixed_camera=True,
                single_person=True,
                fully_in_frame=True,
                unobstructed=True,
                extra_motion_before=False,
                extra_motion_after=False,
                partial_movement=False,
                full_movement_coverage=1.0,
                start_posture_visible=True,
                full_action_path_visible=True,
                end_posture_visible=True,
                target_exercise_match=1.0,
                wrong_exercise_or_unrelated_movement=False,
                loop_quality=0.0,
                suggested_loop_start_seconds=None,
                suggested_loop_end_seconds=None,
                actual_demonstration=True,
                title_or_instruction_screen=False,
                screen_with_embedded_video=False,
                contains_multiple_executions=False,
                contains_idle_or_reset=False,
                confidence=confidence,
                quality=0.0,
                reason=reason,
                source_window_index=window.index,
                is_model_candidate=False,
            ),
        )
    return {
        "movement_present": movement_present,
        "contains_movement_start": bool(payload.get("contains_movement_start", movement_start_seconds is not None)),
        "contains_movement_end": bool(payload.get("contains_movement_end", movement_end_seconds is not None)),
        "movement_start_seconds": movement_start_seconds if movement_present else None,
        "movement_end_seconds": movement_end_seconds if movement_present else None,
        "confidence": confidence,
        "summary": summary,
        "reason": reason,
        "executions": model_executions,
    }


def build_unusable_window_detection(
    *,
    window: DetectionWindow,
    frame_paths: list[Path],
    reason: str,
) -> WindowDetection:
    return WindowDetection(
        window=window,
        movement_present=False,
        contains_movement_start=False,
        contains_movement_end=False,
        movement_start_seconds=None,
        movement_end_seconds=None,
        confidence=0.0,
        summary="Model response could not be parsed.",
        reason=reason[:300],
        camera_variation=compute_camera_variation(frame_paths),
        executions=(),
        frame_paths=[str(path) for path in frame_paths],
    )


def canonicalize_detection_payload(payload: dict[str, object]) -> dict[str, object]:
    aliases = {
        "movementstartseconds": "movement_start_seconds",
        "movementendseconds": "movement_end_seconds",
        "containsmovementstart": "contains_movement_start",
        "containsmovementend": "contains_movement_end",
    }
    canonical = dict(payload)
    for key, value in list(payload.items()):
        normalized_key = re.sub(r"[^a-z0-9]+", "", key.lower())
        target_key = aliases.get(normalized_key)
        if target_key:
            canonical[target_key] = value
    return canonical


def canonicalize_execution_payload(payload: dict[str, object]) -> dict[str, object]:
    aliases = {
        "startseconds": "start_seconds",
        "endseconds": "end_seconds",
        "containsmultipleexecutions": "contains_multiple_executions",
        "containsidleorreset": "contains_idle_or_reset",
        "singleexecution": "single_execution",
        "normalspeed": "normal_speed",
        "notbrokenintosteps": "not_broken_into_steps",
        "fixedcamera": "fixed_camera",
        "singleperson": "single_person",
        "fullyinframe": "fully_in_frame",
        "unobstructed": "unobstructed",
        "extramotionbefore": "extra_motion_before",
        "extramotionafter": "extra_motion_after",
        "partialmovement": "partial_movement",
        "fullmovementcoverage": "full_movement_coverage",
        "startposturevisible": "start_posture_visible",
        "fullactionpathvisible": "full_action_path_visible",
        "endposturevisible": "end_posture_visible",
        "targetexercisematch": "target_exercise_match",
        "wrongexerciseorunrelatedmovement": "wrong_exercise_or_unrelated_movement",
        "loopquality": "loop_quality",
        "suggestedloopstartseconds": "suggested_loop_start_seconds",
        "suggestedloopendseconds": "suggested_loop_end_seconds",
        "suggestedloopstarttimesec": "suggested_loop_start_seconds",
        "suggestedloopendtimesec": "suggested_loop_end_seconds",
        "actualdemonstration": "actual_demonstration",
        "titleorinstructionscreen": "title_or_instruction_screen",
        "screenwithembeddedvideo": "screen_with_embedded_video",
    }
    canonical = dict(payload)
    for key, value in list(payload.items()):
        normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        target_key = aliases.get(normalized_key)
        if target_key:
            canonical[target_key] = value
    return canonical


def normalize_execution_timestamp(value: object, *, window: DetectionWindow) -> float | None:
    seconds = normalize_optional_seconds(value)
    if seconds is None:
        return None
    window_duration = max(0.0, window.end_seconds - window.start_seconds)
    if window.start_seconds - 1e-6 <= seconds <= window.end_seconds + 1e-6:
        if seconds <= window_duration + 1e-6:
            return window.start_seconds + seconds
        return seconds
    return None


def parse_execution_payloads(
    payload: object,
    *,
    window: DetectionWindow,
) -> tuple[CandidateExecution, ...]:
    if not isinstance(payload, list):
        return ()
    parsed: list[CandidateExecution] = []
    for raw_item in payload:
        if not isinstance(raw_item, dict):
            continue
        item = canonicalize_execution_payload(raw_item)
        start_seconds = normalize_execution_timestamp(item.get("start_seconds"), window=window)
        end_seconds = normalize_execution_timestamp(item.get("end_seconds"), window=window)
        if start_seconds is None or end_seconds is None:
            continue
        if end_seconds <= start_seconds:
            continue
        parsed.append(
            CandidateExecution(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                complete=bool(item.get("complete", False)),
                single_execution=bool(item.get("single_execution", False)),
                normal_speed=bool(item.get("normal_speed", False)),
                not_broken_into_steps=bool(item.get("not_broken_into_steps", False)),
                fixed_camera=bool(item.get("fixed_camera", False)),
                single_person=bool(item.get("single_person", False)),
                fully_in_frame=bool(item.get("fully_in_frame", False)),
                unobstructed=bool(item.get("unobstructed", False)),
                extra_motion_before=bool(item.get("extra_motion_before", False)),
                extra_motion_after=bool(item.get("extra_motion_after", False)),
                partial_movement=bool(item.get("partial_movement", False)),
                full_movement_coverage=normalize_confidence(item.get("full_movement_coverage", 0.0)),
                start_posture_visible=bool(item.get("start_posture_visible", False)),
                full_action_path_visible=bool(item.get("full_action_path_visible", False)),
                end_posture_visible=bool(item.get("end_posture_visible", False)),
                target_exercise_match=normalize_confidence(item.get("target_exercise_match", 0.0)),
                wrong_exercise_or_unrelated_movement=bool(
                    item.get("wrong_exercise_or_unrelated_movement", False)
                ),
                loop_quality=normalize_confidence(item.get("loop_quality", 0.0)),
                suggested_loop_start_seconds=normalize_execution_timestamp(
                    item.get("suggested_loop_start_seconds"),
                    window=window,
                ),
                suggested_loop_end_seconds=normalize_execution_timestamp(
                    item.get("suggested_loop_end_seconds"),
                    window=window,
                ),
                actual_demonstration=bool(item.get("actual_demonstration", False)),
                title_or_instruction_screen=bool(item.get("title_or_instruction_screen", False)),
                screen_with_embedded_video=bool(item.get("screen_with_embedded_video", False)),
                contains_multiple_executions=bool(item.get("contains_multiple_executions", False)),
                contains_idle_or_reset=bool(item.get("contains_idle_or_reset", False)),
                confidence=normalize_confidence(item.get("confidence", None)),
                quality=normalize_confidence(item.get("quality", 0.0)),
                reason=str(item.get("reason", "")).strip(),
                source_window_index=int(item.get("source_window_index", window.index)),
                is_model_candidate=True,
            )
        )
    return tuple(parsed)


def extract_json_object(raw: str) -> dict | None:
    text = normalize_json_like_model_output(raw)
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(normalize_json_like_model_output(text[start : end + 1]))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def normalize_json_like_model_output(raw: str) -> str:
    text = raw.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    return re.sub(r",(\s*[}\]])", r"\1", text)


def extract_detection_payload_loose(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if not text:
        return None

    def extract_bool(keys: tuple[str, ...]) -> bool | None:
        for key in keys:
            match = re.search(rf'"{key}"\s*:\s*(true|false)', text, flags=re.IGNORECASE)
            if match:
                return match.group(1).lower() == "true"
        return None

    def extract_number_or_null(keys: tuple[str, ...]) -> float | None | object:
        for key in keys:
            match = re.search(rf'"{key}"\s*:\s*(null|-?\d+(?:\.\d+)*)', text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).lower()
            if value == "null":
                return None
            if value.count(".") > 1:
                head, *tail = value.split(".")
                value = f"{head}.{''.join(tail)}"
            return float(value)
        return ...

    def extract_string(key: str) -> str | None:
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    movement_present = extract_bool(("movement_present",))
    contains_start = extract_bool(("contains_movement_start", "contains_movementstart"))
    contains_end = extract_bool(("contains_movement_end", "contains_movementend"))
    confidence = extract_number_or_null(("confidence",))
    if (
        movement_present is None
        or confidence is ...
    ):
        return None

    summary = extract_string("summary") or ""
    reason = extract_string("reason") or summary

    start_seconds = extract_number_or_null(("movement_start_seconds", "movement_startseconds"))
    end_seconds = extract_number_or_null(("movement_end_seconds", "movement_endseconds"))

    return {
        "movement_present": movement_present,
        "contains_movement_start": contains_start if contains_start is not None else False,
        "contains_movement_end": contains_end if contains_end is not None else False,
        "movement_start_seconds": start_seconds if movement_present and start_seconds is not ... else None,
        "movement_end_seconds": end_seconds if movement_present and end_seconds is not ... else None,
        "confidence": confidence,
        "summary": summary,
        "reason": reason,
    }


def normalize_optional_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return 0.0
    return seconds


def normalize_window_relative_seconds(value: object, *, window: DetectionWindow) -> float | None:
    seconds = normalize_optional_seconds(value)
    if seconds is None:
        return None
    window_duration = max(0.0, window.end_seconds - window.start_seconds)
    if seconds <= window_duration + 1e-6:
        return min(seconds, window_duration)

    # Some model outputs use global source-video timestamps instead of window-relative ones.
    # If the value sits inside the global window bounds, convert it back to a relative offset.
    if window.start_seconds - 1e-6 <= seconds <= window.end_seconds + 1e-6:
        return min(max(0.0, seconds - window.start_seconds), window_duration)

    return window_duration


def normalize_confidence(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(1.0, score))


def choose_detected_span(
    *,
    detections: list[WindowDetection],
    confidence_threshold: float,
    merge_gap_seconds: float,
    min_segment_seconds: float = 2.0,
    max_segment_seconds: float = 20.0,
    settings: DetectionSettings | None = None,
) -> DetectedSpan | None:
    min_segment_seconds = max(0.0, min_segment_seconds)
    max_segment_seconds = max(min_segment_seconds, max_segment_seconds)
    positive_indices = [
        index
        for index, item in enumerate(detections)
        if item.movement_present and item.confidence >= confidence_threshold
    ]
    if not positive_indices:
        return None

    model_candidates = _collect_model_execution_candidates(
        detections=detections,
        confidence_threshold=confidence_threshold,
        min_segment_seconds=min_segment_seconds,
        max_segment_seconds=max_segment_seconds,
        settings=settings,
    )
    if model_candidates:
        return _select_best_model_execution_span(model_candidates)

    interval_candidates = []
    for index in positive_indices:
        detection_window_interval = detection_to_interval(
            detections[index],
            confidence_threshold=confidence_threshold,
        )
        if detection_window_interval is not None:
            interval_candidates.append(
                _apply_boundary_hints_to_interval(
                    interval=detection_window_interval,
                    detection=detections[index],
                )
            )
    interval_candidates = [
        interval
        for interval in interval_candidates
        if _span_has_reasonable_length(
            interval,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
    ]
    if interval_candidates:
        merged_intervals = merge_detection_intervals(
            interval_candidates,
            merge_gap_seconds=merge_gap_seconds,
        )
        merged_intervals = [
            interval
            for interval in merged_intervals
            if _span_has_reasonable_length(
                interval,
                min_segment_seconds=min_segment_seconds,
                max_segment_seconds=max_segment_seconds,
            )
        ]
        if merged_intervals:
            return _select_best_single_execution_span(merged_intervals)

    interval_candidates = [
        interval
        for interval in _collect_cluster_boundaries_as_intervals(
            detections=detections,
            positive_indices=positive_indices,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
        if interval is not None
    ]
    if interval_candidates:
        return _select_best_single_execution_span(interval_candidates)

    clusters = cluster_positive_detections(detections, positive_indices=positive_indices)
    if not clusters:
        return None
    merged = [
        _collect_best_cluster_span(detections, cluster=cluster)
        for cluster in clusters
    ]
    merged = [
        item
        for item in merged
        if _span_has_reasonable_length(
            item,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
    ]
    if not merged:
        return None
    best = min(
        merged,
        key=lambda item: (
            -len(item.contributing_windows),
            -(item.end_seconds - item.start_seconds),
            -item.confidence,
            item.average_camera_variation,
        ),
    )
    return best


def refine_span_with_comparative_selection(
    *,
    client: LlamaCppVisionClient,
    detections: list[WindowDetection],
    selected_span: DetectedSpan,
    confidence_threshold: float,
    min_segment_seconds: float,
    max_segment_seconds: float,
    settings: DetectionSettings,
    exercise_name: str | None,
) -> DetectedSpan:
    if not settings.comparative_selection_enabled:
        return selected_span
    candidates = _collect_model_execution_candidates(
        detections=detections,
        confidence_threshold=confidence_threshold,
        min_segment_seconds=min_segment_seconds,
        max_segment_seconds=max_segment_seconds,
        settings=settings,
    )
    if len(candidates) <= 1:
        return selected_span
    best_score = max(candidate.confidence for candidate in candidates)
    tied_candidates = [
        candidate
        for candidate in candidates
        if candidate.confidence >= best_score - settings.comparative_selection_score_tolerance
    ]
    tied_candidates = sorted(
        tied_candidates,
        key=lambda item: (
            item.start_seconds,
            item.end_seconds,
        ),
    )[: max(1, settings.comparative_selection_max_candidates)]
    if len(tied_candidates) <= 1:
        return selected_span
    detections_by_window_index = {detection.window.index: detection for detection in detections}
    candidate_detections = [
        detections_by_window_index.get(candidate.contributing_windows[0])
        for candidate in tied_candidates
        if candidate.contributing_windows
    ]
    candidate_detections = [item for item in candidate_detections if item is not None]
    if len(candidate_detections) <= 1:
        return selected_span
    selected_window_index = select_best_candidate_window_with_vlm(
        client=client,
        detections=candidate_detections,
        exercise_name=exercise_name,
    )
    if selected_window_index is None:
        return selected_span
    for candidate in tied_candidates:
        if candidate.contributing_windows and candidate.contributing_windows[0] == selected_window_index:
            return candidate
    return selected_span


def select_best_candidate_window_with_vlm(
    *,
    client: LlamaCppVisionClient,
    detections: list[WindowDetection],
    exercise_name: str | None,
) -> int | None:
    frame_paths: list[Path] = []
    prompt_lines = [
        "You are comparing candidate chunks from the same exercise video.",
        f"Target exercise: {exercise_name.strip() if exercise_name and exercise_name.strip() else 'unknown'}.",
        "Choose the one candidate that best contains one complete, real execution of the target exercise.",
        "A complete execution must show the exercise-specific start posture, the full action path, and the exercise-specific end posture or return/control phase.",
        "Reject a candidate if it is only a similar body position, a different exercise, a hold, a setup transition, a stretch, or only part of the movement.",
        "Reject a candidate if the first part is a title, instruction, embedded-preview, monitor, TV, phone, or thumbnail screen even if later frames contain a real demonstration.",
        "Use only the visible frames in the attached contact sheets. Do not infer missing phases from other chunks.",
        "Attachments are grouped by candidate in the order listed below.",
    ]
    attachment_index = 1
    for detection in detections:
        candidate_paths = [Path(path) for path in detection.frame_paths]
        start_attachment = attachment_index
        frame_paths.extend(candidate_paths)
        attachment_index += len(candidate_paths)
        end_attachment = attachment_index - 1
        prompt_lines.append(
            f"- window_index={detection.window.index}, time={detection.window.start_seconds:.2f}s-{detection.window.end_seconds:.2f}s, attachments={start_attachment}-{end_attachment}"
        )
    prompt_lines.extend(
        [
            "Return valid JSON only:",
            '{"selected_window_index": number|null, "confidence": 0.0, "reason": "short reason"}',
        ]
    )
    raw = client.caption_images(frame_paths=frame_paths, prompt="\n".join(prompt_lines))
    payload = extract_json_object(raw)
    if payload is None:
        return None
    selected = payload.get("selected_window_index")
    if selected is None:
        return None
    try:
        selected_index = int(selected)
    except (TypeError, ValueError):
        return None
    valid_indices = {detection.window.index for detection in detections}
    if selected_index not in valid_indices:
        return None
    if normalize_confidence(payload.get("confidence", 0.0)) < 0.5:
        return None
    return selected_index


def refine_selected_chunk_boundaries(
    *,
    video_path: Path,
    output_dir: Path,
    client: LlamaCppVisionClient,
    selected_span: DetectedSpan,
    settings: DetectionSettings,
    exercise_name: str | None,
) -> DetectedSpan:
    window = DetectionWindow(
        index=20_000,
        start_seconds=selected_span.start_seconds,
        end_seconds=selected_span.end_seconds,
    )
    frame_paths = extract_window_frames(
        video_path=video_path,
        window=window,
        frames_per_window=max(2, settings.boundary_refinement_frames_per_window),
        max_frame_width=settings.max_frame_width,
        contact_sheet_enabled=settings.contact_sheet_enabled,
        contact_sheet_columns=settings.contact_sheet_columns,
        contact_sheet_tile_width=settings.refinement_contact_sheet_tile_width,
        contact_sheet_frames_per_sheet=settings.contact_sheet_frames_per_sheet,
        contact_sheet_jpeg_quality=settings.contact_sheet_jpeg_quality,
        output_dir=output_dir / "window_0000",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = client.caption_images(
        frame_paths=frame_paths,
        prompt=build_boundary_refinement_prompt(
            exercise_name=exercise_name,
            start_seconds=selected_span.start_seconds,
            end_seconds=selected_span.end_seconds,
        ),
    )
    (output_dir / "boundary_refinement_raw.txt").write_text(raw, encoding="utf-8")
    payload = extract_json_object(raw)
    if payload is None:
        (output_dir / "boundary_refinement_decision.json").write_text(
            json.dumps(
                {
                    "accepted": False,
                    "reason": "invalid_json",
                    "selected_span": asdict(selected_span),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return selected_span
    refined = parse_boundary_refinement_payload(payload=payload, selected_span=selected_span)
    if refined is None:
        (output_dir / "boundary_refinement_decision.json").write_text(
            json.dumps(
                {
                    "accepted": False,
                    "reason": "invalid_or_low_confidence_refinement",
                    "payload": payload,
                    "selected_span": asdict(selected_span),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return selected_span
    parent_duration = selected_span.end_seconds - selected_span.start_seconds
    refined_duration = refined.end_seconds - refined.start_seconds
    if parent_duration <= 0.0:
        (output_dir / "boundary_refinement_decision.json").write_text(
            json.dumps(
                {
                    "accepted": False,
                    "reason": "invalid_parent_duration",
                    "payload": payload,
                    "selected_span": asdict(selected_span),
                    "refined_span": asdict(refined),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return selected_span
    if refined_duration < parent_duration * settings.min_boundary_refinement_duration_ratio:
        (output_dir / "boundary_refinement_decision.json").write_text(
            json.dumps(
                {
                    "accepted": False,
                    "reason": "refined_span_too_short",
                    "payload": payload,
                    "selected_span": asdict(selected_span),
                    "refined_span": asdict(refined),
                    "min_duration_ratio": settings.min_boundary_refinement_duration_ratio,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return selected_span
    (output_dir / "boundary_refinement_decision.json").write_text(
        json.dumps(
            {
                "accepted": True,
                "payload": payload,
                "selected_span": asdict(selected_span),
                "refined_span": asdict(refined),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return refined


def build_boundary_refinement_prompt(
    *,
    exercise_name: str | None,
    start_seconds: float,
    end_seconds: float,
) -> str:
    exercise_value = exercise_name.strip() if exercise_name and exercise_name.strip() else "unknown"
    return (
        "You are selecting loop timings inside one already-selected exercise chunk.\n"
        f"Target exercise: {exercise_value}.\n"
        f"Chunk source time range: {start_seconds:.2f}s to {end_seconds:.2f}s.\n"
        "Task: choose source-video start and end timestamps for a clean looping clip.\n"
        "The selected interval must contain one complete target-exercise cycle and should loop smoothly when end is followed by start.\n"
        "Completeness is more important than perfect endpoint similarity: never remove the effort/return phase just to make endpoints match.\n"
        "For lifting movements, include both directions of the rep, such as lowering plus pressing/pulling/standing back up.\n"
        "Pick start and end frames at visually compatible movement phases, preferably the same or very similar posture.\n"
        "For cyclical or mobility exercises, a good loop is usually endpoint A -> endpoint B -> endpoint A, or endpoint B -> endpoint A -> endpoint B.\n"
        "For strength exercises, a good loop is usually start/setup posture -> effort path -> return to the same start/setup posture.\n"
        "Do not choose first visible motion and last visible motion if those poses do not match for looping.\n"
        "Do not choose the full chunk unless its first and last frames already form a clean loop.\n"
        "The interval may start after the chunk begins and end before the chunk ends if that creates a better loop.\n"
        "Do not return a partial transition, static hold, mid-rep to mid-rep shortcut, different exercise, setup-only segment, or recovery-only segment.\n"
        "If there is no clean loop inside the chunk, choose the best approximate loop that includes the complete movement and explain why.\n"
        "Use only the visible contact-sheet frames and their displayed source timestamps.\n"
        "Return valid JSON only:\n"
        '{"start_time_sec": number, "end_time_sec": number, "reason": "short reason"}'
    )


def parse_boundary_refinement_payload(
    *,
    payload: dict[str, object],
    selected_span: DetectedSpan,
) -> DetectedSpan | None:
    canonical = dict(payload)
    aliases = {
        "starttimesec": "start_time_sec",
        "startseconds": "start_time_sec",
        "start": "start_time_sec",
        "endtimesec": "end_time_sec",
        "endseconds": "end_time_sec",
        "end": "end_time_sec",
    }
    for key, value in list(payload.items()):
        normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        target_key = aliases.get(normalized_key)
        if target_key:
            canonical[target_key] = value
    start_seconds = normalize_optional_seconds(canonical.get("start_time_sec"))
    end_seconds = normalize_optional_seconds(canonical.get("end_time_sec"))
    if start_seconds is None or end_seconds is None:
        return None
    selected_duration = selected_span.end_seconds - selected_span.start_seconds
    if start_seconds < selected_span.start_seconds and 0.0 <= start_seconds <= selected_duration:
        start_seconds = selected_span.start_seconds + start_seconds
    if end_seconds < selected_span.start_seconds and 0.0 <= end_seconds <= selected_duration:
        end_seconds = selected_span.start_seconds + end_seconds
    start_seconds = max(selected_span.start_seconds, min(start_seconds, selected_span.end_seconds))
    end_seconds = max(selected_span.start_seconds, min(end_seconds, selected_span.end_seconds))
    if end_seconds <= start_seconds:
        return None
    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=selected_span.confidence,
        average_camera_variation=selected_span.average_camera_variation,
        contributing_windows=list(selected_span.contributing_windows),
    )


def _apply_boundary_hints_to_interval(
    *,
    interval: DetectedSpan,
    detection: WindowDetection,
) -> DetectedSpan:
    if detection.movement_start_seconds is None and detection.movement_end_seconds is None:
        return interval
    hint_start = (
        detection.window.start_seconds + detection.movement_start_seconds
        if detection.movement_start_seconds is not None
        else interval.start_seconds
    )
    hint_end = (
        detection.window.start_seconds + detection.movement_end_seconds
        if detection.movement_end_seconds is not None and detection.movement_end_seconds >= 0.0
        else interval.end_seconds
    )
    hint_start = max(interval.start_seconds, min(hint_start, interval.end_seconds))
    hint_end = max(hint_start, min(hint_end, interval.end_seconds))
    return DetectedSpan(
        start_seconds=hint_start,
        end_seconds=hint_end,
        confidence=interval.confidence,
        average_camera_variation=interval.average_camera_variation,
        contributing_windows=list(interval.contributing_windows),
    )


def _collect_cluster_boundaries_as_intervals(
    *,
    detections: list[WindowDetection],
    positive_indices: list[int],
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> list[DetectedSpan]:
    clusters = cluster_positive_detections(detections, positive_indices=positive_indices)
    if not clusters:
        return []
    interval_candidates: list[DetectedSpan] = []
    for cluster in clusters:
        cluster_intervals = _collect_cluster_boundary_candidates(
            detections=detections,
            cluster=cluster,
            min_segment_seconds=min_segment_seconds,
            max_segment_seconds=max_segment_seconds,
        )
        interval_candidates.extend(cluster_intervals)
    return interval_candidates


def _collect_cluster_boundary_candidates(
    *,
    detections: list[WindowDetection],
    cluster: list[int],
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> list[DetectedSpan]:
    effective_cluster = trim_cluster_to_rep_boundaries(detections, cluster=cluster)
    if not effective_cluster:
        return []
    start_candidates = [
        index
        for index in effective_cluster
        if detections[index].contains_movement_start
        or detections[index].movement_start_seconds is not None
    ]
    end_candidates = [
        index
        for index in effective_cluster
        if detections[index].contains_movement_end
        or detections[index].movement_end_seconds is not None
    ]
    intervals: list[DetectedSpan] = []
    if start_candidates and end_candidates:
        for start_index in start_candidates:
            for end_index in end_candidates:
                if end_index < start_index:
                    continue
                span_indices = [index for index in effective_cluster if start_index <= index <= end_index]
                if not span_indices:
                    continue
                interval = _build_cluster_span_with_optional_hints(
                    detections=detections,
                    cluster=span_indices,
                )
                if interval is None or not _span_has_reasonable_length(
                    interval,
                    min_segment_seconds=min_segment_seconds,
                    max_segment_seconds=max_segment_seconds,
                ):
                    continue
                intervals.append(interval)
    return intervals


def _build_cluster_span_with_optional_hints(
    *,
    detections: list[WindowDetection],
    cluster: list[int],
) -> DetectedSpan | None:
    cluster_detections = [detections[index] for index in cluster]
    first = cluster_detections[0]
    last = cluster_detections[-1]
    start_seconds = first.window.start_seconds
    end_seconds = last.window.end_seconds
    if end_seconds <= start_seconds:
        return None
    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=max(item.confidence for item in cluster_detections),
        average_camera_variation=(
            sum(item.camera_variation for item in cluster_detections) / len(cluster_detections)
        ),
        contributing_windows=[item.window.index for item in cluster_detections],
    )


def _collect_best_cluster_span(
    detections: list[WindowDetection],
    *,
    cluster: list[int],
) -> DetectedSpan:
    interval = _build_cluster_span_with_optional_hints(detections=detections, cluster=cluster)
    if interval is not None:
        return interval
    return build_cluster_span(detections=detections, cluster=cluster)


def _model_execution_candidates_present(detections: list[WindowDetection]) -> bool:
    return any(any(item.is_model_candidate for item in detection.executions) for detection in detections)


def _collect_model_execution_candidates(
    *,
    detections: list[WindowDetection],
    confidence_threshold: float,
    min_segment_seconds: float,
    max_segment_seconds: float,
    settings: DetectionSettings | None,
) -> list[DetectedSpan]:
    candidates: list[DetectedSpan] = []
    for detection in detections:
        for execution in detection.executions:
            if not execution.is_model_candidate:
                continue
            if not execution.single_execution or not execution.complete:
                continue
            if not execution.normal_speed or not execution.not_broken_into_steps:
                continue
            if not execution.fixed_camera or not execution.single_person:
                continue
            if settings is not None and detection.camera_variation > settings.max_candidate_camera_variation:
                continue
            if not execution.fully_in_frame or not execution.unobstructed:
                continue
            if execution.wrong_exercise_or_unrelated_movement or execution.target_exercise_match < 0.65:
                continue
            if not execution.actual_demonstration:
                continue
            if execution.title_or_instruction_screen or execution.screen_with_embedded_video:
                continue
            if execution.contains_multiple_executions or execution.contains_idle_or_reset:
                continue
            if execution.confidence < confidence_threshold:
                continue
            start_seconds = execution.start_seconds
            end_seconds = execution.end_seconds
            if end_seconds <= start_seconds:
                continue
            duration = end_seconds - start_seconds
            if not (min_segment_seconds <= duration <= max_segment_seconds):
                continue
            candidates.append(
                DetectedSpan(
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    confidence=_score_execution_candidate(
                        execution=execution,
                        detection=detection,
                        settings=settings,
                    ),
                    average_camera_variation=detection.camera_variation,
                    contributing_windows=[detection.window.index],
                )
            )
    return candidates


def _span_has_reasonable_length(
    span: DetectedSpan,
    *,
    min_segment_seconds: float,
    max_segment_seconds: float,
) -> bool:
    duration = span.end_seconds - span.start_seconds
    return min_segment_seconds <= duration <= max_segment_seconds


def _score_execution_candidate(
    *,
    execution: CandidateExecution,
    detection: WindowDetection,
    settings: DetectionSettings | None,
) -> float:
    vlm_score = max(execution.confidence, detection.confidence) * max(0.0, execution.quality)
    coverage = max(0.0, min(1.0, execution.full_movement_coverage))
    if execution.partial_movement:
        coverage *= settings.incomplete_movement_penalty if settings is not None else 0.20
    required_component_count = sum(
        1
        for present in (
            execution.start_posture_visible,
            execution.full_action_path_visible,
            execution.end_posture_visible,
        )
        if present
    )
    coverage *= required_component_count / 3.0
    vlm_score *= coverage
    vlm_score *= max(0.0, min(1.0, execution.target_exercise_match)) ** 2
    vlm_score += max(0.0, min(1.0, execution.loop_quality)) * 0.05
    extra_motion_penalty = 0.85
    if execution.extra_motion_before:
        vlm_score *= extra_motion_penalty
    if execution.extra_motion_after:
        vlm_score *= extra_motion_penalty
    if settings is not None and settings.target_segment_seconds is not None:
        duration_seconds = max(0.0, execution.end_seconds - execution.start_seconds)
        duration_error = abs(duration_seconds - settings.target_segment_seconds)
        vlm_score -= duration_error * settings.duration_penalty_per_second
    return max(0.0, min(1.0, vlm_score))


def _select_best_single_execution_span(candidates: list[DetectedSpan]) -> DetectedSpan:
    return max(
        candidates,
        key=lambda item: (
            item.confidence,
            -item.average_camera_variation,
            -item.start_seconds,
        ),
    )


def _select_best_model_execution_span(
    candidates: list[DetectedSpan],
) -> DetectedSpan:
    return max(
        candidates,
        key=lambda item: (
            round(item.confidence, 3),
            _detected_span_duration(item),
            -item.average_camera_variation,
            -item.start_seconds,
        ),
    )


def _detected_span_duration(span: DetectedSpan) -> float:
    return max(0.0, span.end_seconds - span.start_seconds)


def cluster_has_complete_rep(detections: list[WindowDetection], *, cluster: list[int]) -> bool:
    cluster_detections = [detections[index] for index in cluster]
    has_start = any(
        item.contains_movement_start and item.movement_start_seconds is not None
        for item in cluster_detections
    )
    has_end = any(
        item.contains_movement_end and item.movement_end_seconds is not None
        for item in cluster_detections
    )
    return has_start and has_end


def cluster_positive_detections(
    detections: list[WindowDetection],
    *,
    positive_indices: list[int],
) -> list[list[int]]:
    if not detections or not positive_indices:
        return []
    clusters: list[list[int]] = [[positive_indices[0]]]
    for current_index in positive_indices[1:]:
        previous_index = clusters[-1][-1]
        previous_detection = detections[previous_index]
        current_detection = detections[current_index]
        if (
            current_index == previous_index + 1
            and current_detection.window.start_seconds <= previous_detection.window.end_seconds + 1e-6
        ):
            clusters[-1].append(current_index)
        else:
            clusters.append([current_index])
    return clusters


def build_cluster_span(detections: list[WindowDetection], *, cluster: list[int]) -> DetectedSpan:
    effective_cluster = trim_cluster_to_rep_boundaries(detections, cluster=cluster)
    cluster_detections = [detections[index] for index in effective_cluster]
    first = cluster_detections[0]
    last = cluster_detections[-1]
    start_seconds = first.window.start_seconds
    end_seconds = last.window.end_seconds

    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=max(item.confidence for item in cluster_detections),
        average_camera_variation=(
            sum(item.camera_variation for item in cluster_detections) / len(cluster_detections)
        ),
        contributing_windows=[item.window.index for item in cluster_detections],
    )


def trim_cluster_to_rep_boundaries(detections: list[WindowDetection], *, cluster: list[int]) -> list[int]:
    start_position = 0
    for position, index in enumerate(cluster):
        if detection_looks_like_preparation(detections[index]):
            start_position = position + 1
            continue
        break
    end_position = len(cluster) - 1
    for reverse_position, index in enumerate(reversed(cluster)):
        if detection_looks_like_recovery(detections[index]):
            end_position = len(cluster) - reverse_position - 2
            continue
        break
    if end_position < start_position:
        return cluster
    return cluster[start_position : end_position + 1]


def detection_looks_like_preparation(detection: WindowDetection) -> bool:
    combined = f"{detection.summary} {detection.reason}".lower()
    return any(
        token in combined
        for token in (
            "setup",
            "preparation",
            "gets into position",
            "get into position",
            "static",
            "still pose",
            "instructional",
            "holding",
            "idle",
            "not started",
        )
    )


def detection_looks_like_recovery(detection: WindowDetection) -> bool:
    combined = f"{detection.summary} {detection.reason}".lower()
    return any(
        token in combined
        for token in (
            "recovery",
            "rest",
            "between reps",
            "between-rep",
            "idle",
            "standing still",
            "finished",
            "after the rep",
        )
    )


def detection_to_interval(
    detection: WindowDetection,
    *,
    confidence_threshold: float,
) -> DetectedSpan | None:
    if not detection.movement_present or detection.confidence < confidence_threshold:
        return None
    if detection.movement_start_seconds is None or detection.movement_end_seconds is None:
        return None
    start_seconds = detection.window.start_seconds + detection.movement_start_seconds
    relative_end = detection.movement_end_seconds
    if relative_end < detection.movement_start_seconds:
        return None
    end_seconds = detection.window.start_seconds + relative_end
    return DetectedSpan(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=detection.confidence,
        average_camera_variation=detection.camera_variation,
        contributing_windows=[detection.window.index],
    )


def merge_detection_intervals(
    intervals: list[DetectedSpan],
    *,
    merge_gap_seconds: float,
) -> list[DetectedSpan]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item.start_seconds, item.end_seconds))
    merged: list[DetectedSpan] = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start_seconds <= previous.end_seconds + merge_gap_seconds:
            merged[-1] = DetectedSpan(
                start_seconds=min(previous.start_seconds, current.start_seconds),
                end_seconds=max(previous.end_seconds, current.end_seconds),
                confidence=max(previous.confidence, current.confidence),
                average_camera_variation=(
                    (
                        previous.average_camera_variation * len(previous.contributing_windows)
                        + current.average_camera_variation * len(current.contributing_windows)
                    )
                    / (len(previous.contributing_windows) + len(current.contributing_windows))
                ),
                contributing_windows=previous.contributing_windows + current.contributing_windows,
            )
        else:
            merged.append(current)
    return merged


def compute_camera_variation(frame_paths: list[Path]) -> float:
    if len(frame_paths) <= 1:
        return 0.0
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python is required for exercise segment detection. Install with: pip install -e .[motion]"
        ) from exc

    grayscale_frames = []
    for frame_path in frame_paths:
        frame = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            continue
        frame = cv2.resize(frame, (160, 160), interpolation=cv2.INTER_AREA)
        grayscale_frames.append(frame)
    if len(grayscale_frames) <= 1:
        return 0.0

    deltas = []
    for previous, current in zip(grayscale_frames, grayscale_frames[1:]):
        difference = cv2.absdiff(previous, current)
        deltas.append(float(difference.mean()) / 255.0)
    return sum(deltas) / len(deltas)

