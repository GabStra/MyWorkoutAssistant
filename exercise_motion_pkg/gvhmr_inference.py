"""Run GVHMR prediction without producing unused visualization videos.

This bridge executes inside the GVHMR Docker image. The generation pipeline
consumes ``hmr4d_results.pt`` through the WHAM-schema exporter and renders its
own previews later, so GVHMR's camera/global MP4s are redundant work.
"""

from __future__ import annotations

import json
import sys
from time import perf_counter
from pathlib import Path

GVHMR_ROOT = Path("/opt/gvhmr")
if str(GVHMR_ROOT) not in sys.path:
    sys.path.insert(0, str(GVHMR_ROOT))


def _time_method(owner, method_name: str, timing_name: str, timings: dict[str, float]) -> None:
    original = getattr(owner, method_name)

    def timed(self, *args, **kwargs):
        started = perf_counter()
        try:
            return original(self, *args, **kwargs)
        finally:
            timings[timing_name] = timings.get(timing_name, 0.0) + perf_counter() - started

    setattr(owner, method_name, timed)


def _instrument_preprocessing(demo_module, timings: dict[str, float]) -> None:
    _time_method(demo_module.Tracker, "__init__", "trackerInitializationSeconds", timings)
    _time_method(demo_module.Tracker, "track", "trackerExecutionSeconds", timings)
    _time_method(demo_module.VitPoseExtractor, "__init__", "vitPoseInitializationSeconds", timings)
    _time_method(demo_module.VitPoseExtractor, "extract", "vitPoseExecutionSeconds", timings)
    _time_method(demo_module.Extractor, "__init__", "hmr2InitializationSeconds", timings)
    _time_method(demo_module.Extractor, "extract_video_features", "hmr2FeatureExecutionSeconds", timings)


def main() -> None:
    script_started = perf_counter()
    timings = {}
    phase_started = perf_counter()
    # Reuse GVHMR's configuration and preprocessing contract while bypassing
    # demo.py's unconditional mesh rendering after prediction.
    from tools.demo import demo as demo_module

    load_data_dict = demo_module.load_data_dict
    parse_args_to_cfg = demo_module.parse_args_to_cfg
    run_preprocess = demo_module.run_preprocess
    _instrument_preprocessing(demo_module, timings)
    timings["demoImportsSeconds"] = perf_counter() - phase_started

    phase_started = perf_counter()
    cfg = parse_args_to_cfg()
    paths = cfg.paths
    timings["configSeconds"] = perf_counter() - phase_started

    phase_started = perf_counter()
    import torch
    import hydra
    from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL
    from hmr4d.utils.net_utils import detach_to_cpu
    from hmr4d.utils.pylogger import Log
    timings["modelImportsSeconds"] = perf_counter() - phase_started

    Log.info(f"[GPU]: {torch.cuda.get_device_name()}")
    phase_started = perf_counter()
    run_preprocess(cfg)
    timings["preprocessSeconds"] = perf_counter() - phase_started

    phase_started = perf_counter()
    data = load_data_dict(cfg)
    timings["loadDataSeconds"] = perf_counter() - phase_started

    results_path = Path(paths.hmr4d_results)
    if not results_path.exists():
        Log.info("[HMR4D] Predicting")
        phase_started = perf_counter()
        model: DemoPL = hydra.utils.instantiate(cfg.model, _recursive_=False)
        model.load_pretrained_model(cfg.ckpt_path)
        model = model.eval().cuda()
        timings["modelSetupSeconds"] = perf_counter() - phase_started

        started = Log.sync_time()
        phase_started = perf_counter()
        prediction = detach_to_cpu(model.predict(data, static_cam=cfg.static_cam))
        timings["predictionSeconds"] = perf_counter() - phase_started
        Log.info(
            f"[HMR4D] Elapsed: {Log.sync_time() - started:.2f}s "
            f"for data-length={data['length'] / 30:.1f}s"
        )
        phase_started = perf_counter()
        results_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(prediction, results_path)
        timings["savePredictionSeconds"] = perf_counter() - phase_started
    else:
        Log.info(f"[HMR4D] Results already exist at {results_path}")
        timings["modelSetupSeconds"] = 0.0
        timings["predictionSeconds"] = 0.0
        timings["savePredictionSeconds"] = 0.0

    timings["scriptTotalSeconds"] = perf_counter() - script_started
    print(f"GVHMR_PHASE_TIMINGS_JSON:{json.dumps(timings, sort_keys=True)}", flush=True)


if __name__ == "__main__":
    main()
