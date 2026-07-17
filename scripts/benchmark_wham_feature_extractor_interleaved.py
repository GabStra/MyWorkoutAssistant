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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracking-results", required=True)
    parser.add_argument("--batch-sizes", type=int, nargs=2, default=(1, 32))
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    base_tracking = joblib.load(args.tracking_results)
    for subject in base_tracking.values():
        for key in GENERATED_KEYS:
            subject.pop(key, None)

    def fresh_tracking():
        value = copy.deepcopy(base_tracking)
        for subject in value.values():
            subject["features"] = []
            subject["flipped_bbox"] = []
            subject["flipped_keypoints"] = []
            subject["flipped_features"] = []
        return value

    extractor = FeatureExtractor("cuda", True, max_batch_size=max(args.batch_sizes))
    samples = {batch_size: [] for batch_size in args.batch_sizes}
    outputs = {}
    peak_memory = {batch_size: 0 for batch_size in args.batch_sizes}

    for batch_size in args.batch_sizes:
        extractor.max_batch_size = batch_size
        with torch.inference_mode():
            extractor.run(args.video, fresh_tracking())
        torch.cuda.synchronize()

    for round_index in range(max(1, args.rounds)):
        order = args.batch_sizes if round_index % 2 == 0 else tuple(reversed(args.batch_sizes))
        for batch_size in order:
            extractor.max_batch_size = batch_size
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            started = time.perf_counter()
            with torch.inference_mode():
                output = extractor.run(args.video, fresh_tracking())
            torch.cuda.synchronize()
            samples[batch_size].append(time.perf_counter() - started)
            peak_memory[batch_size] = max(peak_memory[batch_size], int(torch.cuda.max_memory_allocated()))
            outputs[batch_size] = {
                f"{subject_id}:{key}": value.detach().cpu().numpy()
                for subject_id, subject in output.items()
                for key in ("features", "flipped_features")
                if (value := subject.get(key)) is not None
            }

    baseline, candidate = args.batch_sizes
    absolute_errors = []
    for key, baseline_value in outputs[baseline].items():
        candidate_value = outputs[candidate][key]
        absolute_errors.append(
            np.abs(baseline_value.astype(np.float64) - candidate_value.astype(np.float64))
        )
    baseline_median = float(np.median(samples[baseline]))
    candidate_median = float(np.median(samples[candidate]))
    payload = {
        "gpu": torch.cuda.get_device_name(0),
        "rounds": args.rounds,
        "results": {
            str(batch_size): {
                "samplesSeconds": [round(value, 6) for value in samples[batch_size]],
                "medianSeconds": round(float(np.median(samples[batch_size])), 6),
                "peakCudaMemoryBytes": peak_memory[batch_size],
            }
            for batch_size in args.batch_sizes
        },
        "candidateSpeedup": round(baseline_median / candidate_median, 6),
        "candidateTimeReductionPercent": round((1.0 - candidate_median / baseline_median) * 100.0, 3),
        "comparison": {
            "maxAbsoluteError": max(float(value.max(initial=0.0)) for value in absolute_errors),
            "meanAbsoluteError": float(np.mean([value.mean() for value in absolute_errors])),
        },
    }
    Path(args.output_json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
