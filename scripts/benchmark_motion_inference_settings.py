"""Benchmark fixed local review requests; keep model and image quality constant."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exercise_motion_pkg.boundary_evidence import ENDPOINT_OBSERVATION_PROMPT
from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_MODEL, DEFAULT_LLAMA_CPP_MMPROJ, DEFAULT_LLAMA_CPP_SERVER_COMMAND,
)
from exercise_motion_pkg.bake_and_rank import extract_json_object_with_trailing_repair
from exercise_motion_pkg.gpu_lock import GlobalGpuLock


def fixed_requests(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    requests = []
    for index in (0, 2, 3, 6):
        debug = cases[index]["debug"]
        requests.append({"id": f"sequence-{index}", "prompt": debug["prompt"],
            "images": debug["framePaths"], "max_tokens": debug["requestKwargs"].get("max_tokens", 512)})
    for index in (0, 3):
        for endpoint, position in (("start", 0), ("end", -1)):
            requests.append({"id": f"endpoint-{index}-{endpoint}", "prompt": ENDPOINT_OBSERVATION_PROMPT,
                "images": [cases[index]["debug"]["sampleFramePaths"][position]], "max_tokens": 200})
    for request in requests:
        request["imageHashes"] = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in request["images"]]
        request["content"] = [{"type": "text", "text": request["prompt"]}] + [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                base64.b64encode(Path(p).read_bytes()).decode("ascii")}} for p in request["images"]]
    return requests


def benchmark(config: str, requests: list[dict], output: Path, port: int) -> dict:
    slots, batch, ubatch = map(int, config.split(":"))
    name = config.replace(":", "-")
    command = [DEFAULT_LLAMA_CPP_SERVER_COMMAND, "-m", DEFAULT_LLAMA_CPP_MODEL,
        "--mmproj", DEFAULT_LLAMA_CPP_MMPROJ, "--host", "127.0.0.1", "--port", str(port),
        "--parallel", str(slots), "--ctx-size", str(slots * 8192), "--batch-size", str(batch),
        "--ubatch-size", str(ubatch), "--flash-attn", "on", "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0", "--fit", "on", "--fit-ctx", str(slots * 8192),
        "--fit-target", "2048", "--gpu-layers", "all", "--reasoning", "off",
        "--reasoning-format", "none", "--reasoning-budget", "0", "--image-min-tokens", "1024",
        "--image-max-tokens", "2048", "--mtmd-batch-max-tokens", "768", "--cont-batching"]
    samples = []
    stopped = threading.Event()
    def sample_gpu():
        while not stopped.is_set():
            try:
                raw = subprocess.check_output(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,power.draw",
                    "--format=csv,noheader,nounits"], text=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                samples.append([float(value.strip()) for value in raw.strip().split(",")])
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            stopped.wait(1)
    result = {"config": config, "command": command}
    with (output / f"{name}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        monitor = threading.Thread(target=sample_gpu, daemon=True)
        monitor.start()
        started = time.perf_counter()
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) as client:
                while time.perf_counter() - started < 180:
                    if process.poll() is not None:
                        raise RuntimeError(f"Server exited; see {name}.log")
                    try:
                        if client.get("/health", timeout=2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.5)
                else:
                    raise TimeoutError("Server startup")
                result["startupSeconds"] = time.perf_counter() - started
                def run(request):
                    began = time.perf_counter()
                    payload = {"model": DEFAULT_LLAMA_CPP_MODEL,
                        "messages": [{"role": "user", "content": request["content"]}],
                        "temperature": 0, "top_p": 1, "top_k": 0, "cache_prompt": False,
                        "max_tokens": request["max_tokens"], "response_format": {"type": "json_object"},
                        "reasoning_format": "none", "chat_template_kwargs": {"enable_thinking": False}}
                    response = client.post("/v1/chat/completions", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    raw = data["choices"][0]["message"]["content"]
                    return {"id": request["id"], "seconds": time.perf_counter() - began,
                        "parsed": extract_json_object_with_trailing_repair(raw), "raw": raw,
                        "timings": data.get("timings"), "usage": data.get("usage"),
                        "finishReason": data["choices"][0].get("finish_reason")}
                # Identical visual warmup in each server, excluded from throughput.
                run(requests[-1])
                sample_start = len(samples)
                began = time.perf_counter()
                with ThreadPoolExecutor(max_workers=slots) as executor:
                    result["rows"] = list(executor.map(run, requests))
                result["workloadSeconds"] = time.perf_counter() - began
                result["requestsPerMinute"] = len(requests) * 60 / result["workloadSeconds"]
                result["gpuSamples"] = samples[sample_start:]
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            stopped.set()
            monitor.join(timeout=6)
    (output / f"{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configs", nargs="+", default=["4:256:512", "2:256:512", "1:256:512", "2:512:256", "4:512:256", "2:1024:512", "4:1024:512"])
    parser.add_argument("--port", type=int, default=8097)
    args = parser.parse_args()
    # Never connect the benchmark to a server owned by another task.
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    args.output.mkdir(parents=True, exist_ok=True)
    requests = fixed_requests(args.cases)
    (args.output / "requests.json").write_text(json.dumps(
        [{k: v for k, v in row.items() if k != "content"} for row in requests], indent=2), encoding="utf-8")
    for config in args.configs:
        with GlobalGpuLock(stage="motion_inference_benchmark"):
            result = benchmark(config, requests, args.output, args.port)
        print(json.dumps({k: result.get(k) for k in ("config", "workloadSeconds", "requestsPerMinute", "error")}), flush=True)


if __name__ == "__main__":
    main()
