from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import torch

sys.path.insert(0, str(Path.cwd()))

from lib.models.preproc.extractor import FeatureExtractor


GENERATED_KEYS = {
    "features",
    "flipped_bbox",
    "flipped_keypoints",
    "flipped_features",
    "init_global_orient",
    "init_body_pose",
    "init_betas",
    "flipped_init_global_orient",
    "flipped_init_body_pose",
    "flipped_init_betas",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracking-results", required=True)
    parser.add_argument("--batch-size", required=True, type=int)
    parser.add_argument("--output-npz", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--reference-npz")
    parser.add_argument("--warmup-runs", type=int, default=0)
    parser.add_argument("--measurement-runs", type=int, default=1)
    parser.add_argument("--flip-eval", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_tracking_results = joblib.load(args.tracking_results)
    for subject in base_tracking_results.values():
        for key in GENERATED_KEYS:
            subject.pop(key, None)

    def fresh_tracking_results():
        tracking_results = copy.deepcopy(base_tracking_results)
        for subject in tracking_results.values():
            subject["features"] = []
            if args.flip_eval:
                subject["flipped_bbox"] = []
                subject["flipped_keypoints"] = []
                subject["flipped_features"] = []
        return tracking_results

    extractor = FeatureExtractor("cuda", args.flip_eval, max_batch_size=args.batch_size)
    for _ in range(max(0, args.warmup_runs)):
        with torch.inference_mode():
            extractor.run(args.video, fresh_tracking_results())
        torch.cuda.synchronize()

    elapsed_samples = []
    output = None
    torch.cuda.reset_peak_memory_stats()
    for _ in range(max(1, args.measurement_runs)):
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            output = extractor.run(args.video, fresh_tracking_results())
        torch.cuda.synchronize()
        elapsed_samples.append(time.perf_counter() - started)
    assert output is not None

    arrays: dict[str, np.ndarray] = {}
    frame_count = 0
    for subject_id, subject in output.items():
        for key in ("features", "flipped_features"):
            value = subject.get(key)
            if value is None:
                continue
            array = value.detach().cpu().numpy() if torch.is_tensor(value) else np.asarray(value)
            arrays[f"{subject_id}:{key}"] = array
            if key == "features":
                frame_count += int(array.shape[0])
    np.savez(args.output_npz, **arrays)

    comparison = None
    if args.reference_npz:
        max_absolute_error = 0.0
        mean_absolute_errors = []
        with np.load(args.reference_npz) as reference:
            if set(reference.files) != set(arrays):
                raise RuntimeError("Reference and benchmark feature keys differ")
            for key, value in arrays.items():
                reference_value = reference[key]
                if reference_value.shape != value.shape:
                    raise RuntimeError(f"Feature shape differs for {key}")
                absolute_error = np.abs(reference_value.astype(np.float64) - value.astype(np.float64))
                max_absolute_error = max(max_absolute_error, float(absolute_error.max(initial=0.0)))
                mean_absolute_errors.append(float(absolute_error.mean()))
        comparison = {
            "maxAbsoluteError": max_absolute_error,
            "meanAbsoluteError": float(np.mean(mean_absolute_errors)) if mean_absolute_errors else 0.0,
        }

    payload = {
        "batchSize": args.batch_size,
        "flipEval": args.flip_eval,
        "elapsedSeconds": round(float(np.median(elapsed_samples)), 6),
        "elapsedSamplesSeconds": [round(value, 6) for value in elapsed_samples],
        "trackedFrameCount": frame_count,
        "featureArrayCount": len(arrays),
        "peakCudaMemoryBytes": int(torch.cuda.max_memory_allocated()),
        "gpu": torch.cuda.get_device_name(0),
        "comparison": comparison,
    }
    Path(args.output_json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
