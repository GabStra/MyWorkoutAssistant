from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from exercise_motion_pkg.segment_detection import build_frame_contact_sheets
from exercise_motion_pkg.youtube import LlamaCppVisionRanker, YouTubeRankingSettings


GATE_PROMPTS = {
    "identity": """You verify only exercise identity in chronological contact sheets.
Target exercise: {exercise_name}
Inspect every visible frame. Ignore video quality and repetition completeness.
Judge visible body action and visibly used equipment, not titles or captions.
Use \"uncertain\" when the frames do not visibly prove the answer.
Return JSON only with exactly:
{{"verdict":"match|mismatch|uncertain","observedAction":"short visible description","evidence":"short frame evidence"}}
""",
    "uniform_observation": """You inspect one uniformly sampled chronological contact sheet.
Target exercise: {exercise_name}
Named equipment to check: {named_equipment}
Inspect every numbered tile. Report only direct visible observations. Unrelated action means
talking, pointing, instruction gestures, setup, cleanup, waiting, equipment handling, or a
different exercise. A normal phase or transition within a repetition is not unrelated.
Return JSON only with exactly:
{{"unrelatedActionVisible":false,"unrelatedTileNumbers":[],"evidence":"short visible evidence"}}
""",
    "motion_observation": """You inspect one motion-focused chronological contact sheet.
Target exercise: {exercise_name}
Named equipment to check: {named_equipment}
Inspect every numbered tile. Report only direct visible observations; do not infer equipment
or motion from the exercise name. Target-exercise action means its defining body action is
visibly changing across tiles, not merely a static pose.
Named equipment counts as engaged only when it is visibly held, worn, loaded, pulled,
pressed, or otherwise used by the performer. Equipment merely visible on a floor,
rack, or elsewhere in the background is absent. Use not_applicable only when named
equipment is \"none\".
Return JSON only with exactly:
{{"targetExerciseActionVisible":false,"namedEquipmentEngagedStatus":"engaged|absent|unclear|not_applicable","evidence":"short visible evidence"}}
""",
    "completeness": """You verify only movement-phase completeness in chronological contact sheets.
Do not decide exercise identity or clip purity. A complete execution must visibly show
an initial state, an action phase, a turning point, and a return or stable finish.
Inspect every frame. Return JSON only with exactly:
{{"startStateVisible":false,"actionPhaseVisible":false,"turningPointVisible":false,"returnOrFinishVisible":false,"complete":false,"evidence":"short frame evidence"}}
""",
}


def parse_json_object(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("VLM response must be a JSON object")
    return payload


def gate_passed(gate: str, payload: dict[str, Any]) -> bool:
    if gate == "identity":
        return payload.get("verdict") == "match"
    if gate == "uniform_observation":
        sheets = payload.get("sheets")
        return isinstance(sheets, list) and bool(sheets) and all(
            sheet.get("unrelatedActionVisible") is False
            and sheet.get("unrelatedTileNumbers") == []
            for sheet in sheets
            if isinstance(sheet, dict)
        ) and all(isinstance(sheet, dict) for sheet in sheets)
    if gate == "motion_observation":
        sheets = payload.get("sheets")
        return isinstance(sheets, list) and bool(sheets) and any(
            sheet.get("targetExerciseActionVisible") is True
            and sheet.get("namedEquipmentEngagedStatus") in {"engaged", "not_applicable"}
            for sheet in sheets
            if isinstance(sheet, dict)
        )
    required = (
        "startStateVisible",
        "actionPhaseVisible",
        "turningPointVisible",
        "returnOrFinishVisible",
        "complete",
    )
    return all(payload.get(key) is True for key in required)


def discover_cases(workspace: Path) -> list[dict[str, Any]]:
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    exercise_names = {
        Path(item["selectionManifestPath"]).parent.parent.name: item["exerciseName"]
        for item in summary["exercises"]
        if item.get("selectionManifestPath")
    }
    source_videos = {
        Path(item["selectionManifestPath"]).parent.parent.name: Path(
            item.get("selectedSourceVideoOriginalPath") or item["selectedSourceVideoPath"]
        )
        for item in summary["exercises"]
        if item.get("selectionManifestPath")
        and (item.get("selectedSourceVideoOriginalPath") or item.get("selectedSourceVideoPath"))
    }
    cases: list[dict[str, Any]] = []
    for parsed_path in sorted(workspace.glob("*/bake/**/final_output_validation_parsed.json")):
        exercise_slug = parsed_path.relative_to(workspace).parts[0]
        payload = json.loads(parsed_path.read_text(encoding="utf-8"))
        sheets = [Path(value) for value in payload.get("sourceContactSheetPaths", [])]
        if sheets and all(path.is_file() for path in sheets):
            candidate_source_video = parsed_path.parents[2] / "input" / "selected_segment.mp4"
            cases.append(
                {
                    "exerciseName": exercise_names.get(exercise_slug, exercise_slug.replace("-", " ").title()),
                    "exerciseSlug": exercise_slug,
                    "contactSheets": sheets,
                    "sourceVideo": source_videos.get(exercise_slug, candidate_source_video),
                }
            )
    return cases


def named_equipment(exercise_name: str) -> str:
    lowered = exercise_name.casefold()
    for equipment in ("barbell", "dumbbell", "cable", "kettlebell"):
        if equipment in lowered:
            return equipment
    return "none"


def select_motion_peak_indices(scores: list[float], fps: float) -> list[int]:
    if len(scores) < 2:
        return []
    minimum_peak_distance = max(1, int(round(max(fps, 1.0) * 0.15)))
    selected: list[int] = []

    def add_if_separated(frame_index: int) -> None:
        if all(abs(frame_index - existing) >= minimum_peak_distance for existing in selected):
            selected.append(frame_index)

    for frame_index in sorted(range(1, len(scores)), key=lambda index: (-scores[index], index)):
        add_if_separated(frame_index)
        if len(selected) >= 6:
            break
    temporal_bin_count = min(6, len(scores) - 1)
    for bin_index in range(temporal_bin_count):
        start = 1 + ((len(scores) - 1) * bin_index) // temporal_bin_count
        end = 1 + ((len(scores) - 1) * (bin_index + 1)) // temporal_bin_count
        if start < end:
            add_if_separated(max(range(start, end), key=lambda index: (scores[index], -index)))
    return sorted(selected)


def build_motion_contact_sheets(case: dict[str, Any], output_root: Path) -> list[Path]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Motion-focused sampling requires OpenCV and NumPy") from exc
    video_path = case.get("sourceVideo")
    if not isinstance(video_path, Path) or not video_path.is_file():
        raise FileNotFoundError(f"Source video missing for {case['exerciseName']}: {video_path}")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open source video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[Any] = []
    scores: list[float] = []
    previous_gray: Any | None = None
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
            score = 0.0 if previous_gray is None else float(np.mean(cv2.absdiff(gray, previous_gray)))
            frames.append(frame)
            scores.append(score)
            previous_gray = gray
    finally:
        capture.release()
    if len(frames) < 2:
        raise RuntimeError(f"Not enough readable frames in {video_path}")
    effective_fps = fps if fps > 0.0 else 30.0
    peak_indices = select_motion_peak_indices(scores, effective_fps)
    neighborhood = max(1, int(round(effective_fps * 0.067)))
    selected_indices = sorted(
        {
            min(len(frames) - 1, max(0, peak_index + offset * neighborhood))
            for peak_index in peak_indices
            for offset in (-2, -1, 0, 1, 2)
        }
    )
    frame_dir = output_root / case["exerciseSlug"] / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    timestamps: list[float] = []
    for sequence_index, frame_index in enumerate(selected_indices, start=1):
        frame_path = frame_dir / f"motion_{sequence_index:03d}_{frame_index:06d}.jpg"
        if not cv2.imwrite(str(frame_path), frames[frame_index], [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            raise RuntimeError(f"Could not write motion frame: {frame_path}")
        frame_paths.append(frame_path)
        timestamps.append(frame_index / effective_fps)
    sheets = build_frame_contact_sheets(
        frame_paths=frame_paths,
        timestamps=timestamps,
        output_dir=output_root / case["exerciseSlug"] / "contact_sheets",
        columns=4,
        tile_width=320,
        frames_per_sheet=16,
        jpeg_quality=90,
        sequence_labels=True,
    )
    if not sheets:
        raise RuntimeError(f"Could not build motion contact sheets for {case['exerciseName']}")
    return sheets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    output_path = (args.output or workspace / "source_contact_sheet_gate_experiment.json").resolve()
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    runtime = summary["llamaCppRuntime"]
    settings = YouTubeRankingSettings(
        vision_llm_workers=1,
        llama_cpp_parallel=1,
        llama_cpp_model=runtime["visualModel"],
        llama_cpp_mmproj=runtime["visualMmproj"],
        llama_cpp_mtp_model=None,
        llama_cpp_ctx_size=runtime["ctxSize"],
        llama_cpp_fit_ctx=runtime["fitCtx"],
        llama_cpp_batch_size=runtime["batchSize"],
        llama_cpp_ubatch_size=runtime["ubatchSize"],
        llama_cpp_image_min_tokens=runtime["imageMinTokens"],
        llama_cpp_image_max_tokens=runtime["imageMaxTokens"],
        llama_cpp_mtmd_batch_max_tokens=runtime["mtmdBatchMaxTokens"],
        llama_cpp_temperature=0.0,
        llama_cpp_top_p=1.0,
        llama_cpp_top_k=1,
        llama_cpp_disable_reasoning=True,
        llama_cpp_n_predict=256,
        llama_cpp_request_timeout_seconds=300.0,
    )
    cases = discover_cases(workspace)
    motion_sheet_root = output_path.parent / f"{output_path.stem}_motion_sheets"
    for case in cases:
        case["motionContactSheets"] = build_motion_contact_sheets(case, motion_sheet_root)
    report: dict[str, Any] = {
        "workspace": str(workspace),
        "deterministicSettings": {
            "temperature": 0.0,
            "topP": 1.0,
            "topK": 1,
            "reasoning": False,
            "parallel": 1,
            "mtp": False,
            "repeats": max(1, args.repeats),
        },
        "cases": [],
    }
    ranker = LlamaCppVisionRanker(settings)
    try:
        for case in cases:
            print(f"[evaluate] {case['exerciseName']}", flush=True)
            result = {
                "exerciseName": case["exerciseName"],
                "exerciseSlug": case["exerciseSlug"],
                "contactSheets": [str(path) for path in case["contactSheets"]],
                "motionContactSheets": [str(path) for path in case["motionContactSheets"]],
                "runs": [],
            }
            for repeat_index in range(max(1, args.repeats)):
                gates: dict[str, Any] = {}
                for gate, template in GATE_PROMPTS.items():
                    prompt = template.format(
                        exercise_name=case["exerciseName"],
                        named_equipment=named_equipment(case["exerciseName"]),
                    )
                    if gate in {"uniform_observation", "motion_observation"}:
                        parsed = {"sheets": []}
                        sheet_paths = (
                            case["contactSheets"]
                            if gate == "uniform_observation"
                            else case["motionContactSheets"]
                        )
                        for sheet_path in sheet_paths:
                            raw = ranker.client.caption_images(
                                frame_paths=[sheet_path],
                                prompt=prompt,
                                max_tokens=256,
                                request_timeout_seconds=300.0,
                                disable_reasoning=True,
                                json_response=True,
                                temperature=0.0,
                                top_p=1.0,
                                top_k=1,
                            )
                            parsed["sheets"].append(parse_json_object(raw))
                    else:
                        frame_paths = (
                            case["motionContactSheets"]
                            if gate == "identity"
                            else case["contactSheets"]
                        )
                        raw = ranker.client.caption_images(
                            frame_paths=frame_paths,
                            prompt=prompt,
                            max_tokens=256,
                            request_timeout_seconds=300.0,
                            disable_reasoning=True,
                            json_response=True,
                            temperature=0.0,
                            top_p=1.0,
                            top_k=1,
                        )
                        parsed = parse_json_object(raw)
                    gates[gate] = {"passed": gate_passed(gate, parsed), "response": parsed}
                result["runs"].append(
                    {
                        "repeat": repeat_index + 1,
                        "gates": gates,
                        "passed": all(value["passed"] for value in gates.values()),
                    }
                )
            signatures = [
                json.dumps(run["gates"], sort_keys=True, separators=(",", ":")) for run in result["runs"]
            ]
            result["deterministicAcrossRepeats"] = len(set(signatures)) == 1
            decision_signatures = [
                (
                    run["passed"],
                    tuple((gate, values["passed"]) for gate, values in sorted(run["gates"].items())),
                )
                for run in result["runs"]
            ]
            result["deterministicDecisionAcrossRepeats"] = len(set(decision_signatures)) == 1
            report["cases"].append(result)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        ranker.close(force_stop_server=True)
    print(f"Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
