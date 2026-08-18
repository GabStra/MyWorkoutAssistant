from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import joblib
import numpy as np
import torch

sys.path.insert(0, str(Path.cwd()))

from configs.config import get_cfg_defaults
from lib.models.preproc.detector import DetectionModel
from lib.models.preproc.extractor import FeatureExtractor
try:
    from exercise_motion_pkg.wham_tracking_coverage import (
        MAX_STITCH_GAP_SECONDS,
        best_compatible_chain,
        stitch_track_chain,
        tracking_coverage_report,
    )
except ModuleNotFoundError:
    # The warm Docker worker mounts these two modules side by side under
    # /worker instead of mounting the whole application package.
    from wham_tracking_coverage import (  # type: ignore[no-redef]
        MAX_STITCH_GAP_SECONDS,
        best_compatible_chain,
        stitch_track_chain,
        tracking_coverage_report,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run_tracking_preflight(
    *,
    video_path: Path,
    output_root: Path,
    report_path: Path,
    required_start_seconds: float | None,
    required_end_seconds: float | None,
    cfg: Any | None = None,
    detection_model_factory: Any = DetectionModel,
    feature_extractor_factory: Any = FeatureExtractor,
) -> dict[str, Any]:
    if cfg is None:
        cfg = get_cfg_defaults()
        cfg.merge_from_file("configs/yamls/demo.yaml")
    video_path = video_path.expanduser().resolve()
    sequence_name = video_path.stem
    sequence_dir = output_root.expanduser().resolve() / sequence_name
    sequence_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_path.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    input_sha256 = _sha256(video_path)
    tracking_results_path = sequence_dir / "tracking_results.pth"
    slam_results_path = sequence_dir / "slam_results.pth"
    try:
        cached_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached_report = {}
    if (
        cached_report.get("inputSha256") == input_sha256
        and cached_report.get("requiredStartSeconds") == required_start_seconds
        and cached_report.get("requiredEndSeconds") == required_end_seconds
    ):
        if cached_report.get("passed") is False:
            cached_report["cacheStatus"] = "reused"
            return cached_report
        if (
            cached_report.get("passed") is True
            and tracking_results_path.is_file()
            and slam_results_path.is_file()
        ):
            cached_report["cacheStatus"] = "reused"
            return cached_report

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open preflight video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    detector = detection_model_factory(cfg.DEVICE.lower())
    with torch.no_grad():
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            detector.track(frame, fps, frame_count)
    cap.release()
    tracking_results = detector.process(fps)
    stitch_gap_frames = max(2, int(np.ceil(fps * MAX_STITCH_GAP_SECONDS)))
    stitch_chain = best_compatible_chain(
        tracking_results,
        max_gap_frames=stitch_gap_frames,
    )
    stitched_track_ids = [str(track_id) for track_id, _track in stitch_chain]
    tracking_results, interpolated_frame_count = stitch_track_chain(
        tracking_results,
        stitch_chain,
    )
    report = tracking_coverage_report(
        tracking_results,
        fps=fps,
        frame_count=frame_count,
        required_start_seconds=required_start_seconds,
        required_end_seconds=required_end_seconds,
    )
    report["stitchMaxGapFrames"] = stitch_gap_frames
    report["stitchedTrackIds"] = stitched_track_ids if len(stitched_track_ids) > 1 else []
    report["interpolatedTrackingFrameCount"] = interpolated_frame_count
    report["inputSha256"] = input_sha256
    report["cacheStatus"] = "computed"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        return report

    with torch.no_grad():
        extractor = feature_extractor_factory(cfg.DEVICE.lower(), cfg.FLIP_EVAL)
        tracking_results = extractor.run(str(video_path), tracking_results)
    slam_results = np.zeros((frame_count, 7))
    slam_results[:, 3] = 1.0
    joblib.dump(tracking_results, tracking_results_path)
    joblib.dump(slam_results, slam_results_path)
    report["reusablePreprocessingWritten"] = True
    report["trackingResultsPath"] = str(tracking_results_path)
    report["slamResultsPath"] = str(slam_results_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--output-pth", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--required-start-seconds", type=float)
    parser.add_argument("--required-end-seconds", type=float)
    args = parser.parse_args()
    report = run_tracking_preflight(
        video_path=Path(args.video),
        output_root=Path(args.output_pth),
        report_path=Path(args.report),
        required_start_seconds=args.required_start_seconds,
        required_end_seconds=args.required_end_seconds,
    )
    return 0 if report.get("passed") else 42


if __name__ == "__main__":
    raise SystemExit(main())
