"""Replay fixed review requests through the production llama.cpp launcher and client."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exercise_motion_pkg.boundary_evidence import ENDPOINT_OBSERVATION_PROMPT
from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_CTX_SIZE, DEFAULT_LLAMA_CPP_PARALLEL
from exercise_motion_pkg.bake_and_rank import (
    SourceCutCandidate, parse_source_cut_candidate_choice, extract_json_object_with_trailing_repair,
)
from exercise_motion_pkg.segment_detection import DetectionWindow
from exercise_motion_pkg.youtube import LlamaCppVisionRanker, YouTubeRankingSettings


def fixed_requests(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        requests = data["requests"]
    else:
        requests = []
        for index, case in enumerate(data):
            debug = case.get("debug", case)
            requests.append({"id": f"sequence-{index}", "prompt": debug["prompt"],
                "images": debug["framePaths"], "kwargs": debug["requestKwargs"]})
            samples = debug.get("sampleFramePaths", [])
            for endpoint, position in (("start", 0), ("end", -1)) if samples else ():
                requests.append({"id": f"endpoint-{index}-{endpoint}", "prompt": ENDPOINT_OBSERVATION_PROMPT,
                    "images": [samples[position]], "kwargs": {
                        "max_tokens": 200, "disable_reasoning": True, "json_response": True}})
    if not requests:
        raise ValueError("At least one fixed review request is required")
    ids = [row["id"] for row in requests]
    if len(ids) != len(set(ids)):
        raise ValueError("Review request ids must be unique")
    for request in requests:
        request["kwargs"] = {key: value for key, value in request.get("kwargs", {}).items()
                             if not key.startswith("clef_visual_decision_")}
        request["images"] = [str((path.parent / p).resolve()) for p in request["images"]]
        request["imageHashes"] = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in request["images"]]
    return requests


def parse_gpu_samples(raw: str) -> list[dict]:
    rows = []
    for line in raw.splitlines():
        index, utilization, memory, power = (value.strip() for value in line.split(","))
        rows.append({"index": int(index), "utilizationPercent": float(utilization),
                     "memoryMiB": float(memory), "powerWatts": None if "N/A" in power else float(power)})
    return rows


def review_decision(request: dict, parsed: dict, raw: str) -> dict:
    spec = request.get("sourceCandidate")
    if spec is None:
        return {key: value for key, value in parsed.items() if key != "description"}
    candidate = SourceCutCandidate(spec["id"], DetectionWindow(0, spec["start"], spec["end"]),
                                   [Path(p) for p in request["images"]])
    ranking = parse_source_cut_candidate_choice(raw, [candidate], has_contract=False,
        require_identity_evidence=True,
        required_equipment=spec["requiredEquipment"],
        equipment_timing_requirement_ids=spec.get("equipmentRequirementIds"))
    if ranking is None:
        raise ValueError("Source review failed the production parser")
    rows = ranking.payload["sourceCutScorecardCandidates"]
    if len(rows) != 1 or rows[0]["id"] != candidate.candidate_id:
        raise ValueError("Source review did not return the requested candidate")
    return {key: rows[0].get(key) for key in ("id", "passed", "rejectionReasons", "identityMatch",
        "completeMovement", "startBoundaryClean", "finishBoundaryClean", "setupOrFiller",
        "namedEquipmentEngagedStatus")}


def benchmark(config: str, requests: list[dict], output: Path, port: int, *,
              context_per_slot: int, workers: int, repeats: int, kv_type: str, kv_unified: bool) -> dict:
    slots, batch, ubatch = map(int, config.split(":"))
    if min(slots, batch, ubatch, context_per_slot, workers, repeats) < 1:
        raise ValueError("Benchmark dimensions must be positive")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    output.mkdir(parents=True, exist_ok=False)
    settings = YouTubeRankingSettings(llama_cpp_base_url=f"http://127.0.0.1:{port}",
        llama_cpp_parallel=slots, llama_cpp_ctx_size=slots * context_per_slot,
        llama_cpp_fit_ctx=slots * context_per_slot, llama_cpp_batch_size=batch,
        llama_cpp_ubatch_size=ubatch, llama_cpp_cache_type_k=kv_type, llama_cpp_cache_type_v=kv_type,
        llama_cpp_kv_unified=kv_unified, llama_cpp_threads_http=8)
    result = {"config": config, "contextPerSlot": context_per_slot, "workers": workers,
              "kvType": kv_type, "kvUnified": kv_unified, "waves": []}
    samples, sample_errors = [], []
    stopped = threading.Event()
    local = threading.local()
    ranker = None

    def sample_gpu():
        while not stopped.is_set():
            try:
                raw = subprocess.check_output(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,power.draw",
                    "--format=csv,noheader,nounits"], text=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                samples.append({"seconds": time.perf_counter() - started, "gpus": parse_gpu_samples(raw)})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                sample_errors.append(str(exc))
            stopped.wait(1)

    def capture_response(response):
        response.read()
        data = response.json()
        local.responses.append({"status": response.status_code, "timings": data.get("timings"),
            "usage": data.get("usage"), "finishReason": (data.get("choices") or [{}])[0].get("finish_reason")})

    def run(request):
        began = time.perf_counter()
        local.responses = []
        row = {"id": request["id"]}
        try:
            raw = ranker.client.caption_images(frame_paths=[Path(p) for p in request["images"]],
                                               prompt=request["prompt"], **request["kwargs"])
            row.update(raw=raw)
            parsed = extract_json_object_with_trailing_repair(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Response is not a JSON object")
            row.update(parsed=parsed, decision=review_decision(request, parsed, raw))
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row.update(seconds=time.perf_counter() - began, responses=local.responses)
        return row

    started = time.perf_counter()
    monitor = threading.Thread(target=sample_gpu, daemon=True)
    monitor.start()
    try:
        # The real launcher owns its GPU lock, process cleanup, fit and reasoning policy.
        ranker = LlamaCppVisionRanker(settings)
        if ranker.process is None:
            raise RuntimeError("Benchmark did not start its own isolated server")
        result.update(command=ranker.process.args, startupSeconds=time.perf_counter() - started)
        result["serverProps"] = ranker._server_props_payload()
        ranker.client.client.event_hooks["response"].append(capture_response)
        for repeat in range(repeats):
            sample_start = len(samples)
            began = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as executor:
                rows = list(executor.map(run, requests))
            elapsed = time.perf_counter() - began
            result["waves"].append({"repeat": repeat, "seconds": elapsed, "rows": rows,
                "jsonReviewsPerMinute": sum("error" not in row for row in rows) * 60 / elapsed,
                "gpuSamples": samples[sample_start:]})
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if ranker is not None:
                log_path = ranker.server_log_path
                ranker.close(force_stop_server=True)
                if log_path is not None and log_path.exists():
                    shutil.copyfile(log_path, output / "server.log")
        finally:
            stopped.set()
            monitor.join(timeout=6)
            result["gpuSamplingErrors"] = sample_errors
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configs", nargs="+", default=["3:1024:512", "1:1024:512", "2:1024:512",
                                                        "3:2048:512", "3:1024:256", "3:1024:512"])
    parser.add_argument("--context-per-slot", type=int,
                        default=DEFAULT_LLAMA_CPP_CTX_SIZE // DEFAULT_LLAMA_CPP_PARALLEL)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--kv-type", choices=["q8_0", "f16"], default="q8_0")
    parser.add_argument("--kv-unified", action="store_true")
    parser.add_argument("--port", type=int, default=18181)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    requests = fixed_requests(args.cases)
    (args.output / "requests.json").write_text(json.dumps(requests, indent=2), encoding="utf-8")
    for index, config in enumerate(args.configs):
        for request in requests:
            if [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in request["images"]] != request["imageHashes"]:
                raise ValueError(f"Fixture images changed: {request['id']}")
        result = benchmark(config, requests, args.output / f"{index:02}-{config.replace(':', '-')}",
            args.port, context_per_slot=args.context_per_slot, workers=args.workers, repeats=args.repeats,
            kv_type=args.kv_type, kv_unified=args.kv_unified)
        print(json.dumps({"config": config, "error": result.get("error"),
            "waves": [{k: wave[k] for k in ("repeat", "seconds", "jsonReviewsPerMinute")}
                      for wave in result["waves"]]}), flush=True)


if __name__ == "__main__":
    main()
