"""Wave-lifecycle bench: the fastest possible config comparison.

Runs ZERO exercises. Instead it drives one real wave's LIFECYCLE sequence per
configuration - real llama.cpp server, real captions, real exclusive handoff
(quiesce vs force-stop+restart) - with the heavy phase compute replaced by
short sleeps. Phase compute is config-independent, so the lifecycle deltas
this measures (server startups, quiesce overhead, restart costs) are exactly
what a config choice changes.

Per config (~2 min): session start -> source captions -> small co-resident op
-> exclusive generation window (server down) -> final captions -> close.

Usage:
  python scripts/motion_wave_bench.py                       # baseline,shared
  python scripts/motion_wave_bench.py --configs shared --items 4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, LazyLlamaCppVisionSession

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER = r"C:\Users\gabri\Documents\llama.cpp\build-master\bin\Release\llama-server.exe"
MODEL = r"C:\Users\gabri\Downloads\Qwen3.5-9B-UD-Q4_K_XL.gguf"
MMPROJ = r"C:\Users\gabri\Downloads\mmproj-BF16(6).gguf"
PORT = 8160
BASE_URL = f"http://127.0.0.1:{PORT}"
BENCH_ROOT = REPO_ROOT / "build/exercise_motion/wave-bench"

SERVER_ARGS = [
    SERVER, "-m", MODEL, "--host", "127.0.0.1", "--port", str(PORT),
    "--mmproj", MMPROJ, "--mmproj-offload",
    "--parallel", "8", "--ctx-size", "49152",
    "--batch-size", "1024", "--ubatch-size", "512",
    "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
    "--fit", "on", "--threads-http", "8",
    "--reasoning", "on", "--reasoning-format", "deepseek", "--reasoning-budget", "64",
    "--cont-batching", "--gpu-layers", "all",
]


def _http_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/v1/models", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class SharedSupervisor:
    """Minimal stand-in for the ps1 drain loop: start, heartbeat, restart."""

    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.stop_event = threading.Event()
        self.starts = 0
        self.process: subprocess.Popen | None = None
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _start_server(self) -> None:
        for marker in ("ready.json", "heartbeat.json", "stop_intent.json",
                       "start_requested.json", "stopped.json", "startup_error.json"):
            path = self.session_dir / marker
            if path.exists():
                path.unlink()
        inflight = self.session_dir / "in-flight"
        if inflight.exists():
            for path in inflight.glob("*.json"):
                path.unlink()
        log = (self.session_dir / "server.log").open("w")
        self.process = subprocess.Popen(SERVER_ARGS, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 180
        while time.time() < deadline:
            if _http_ok():
                _write(self.session_dir / "ready.json", {
                    "pid": self.process.pid, "baseUrl": BASE_URL, "model": MODEL,
                    "parallel": 8, "startedAtUnixSeconds": time.time(),
                })
                self.starts += 1
                return
            if self.process.poll() is not None:
                raise RuntimeError("shared bench server exited during startup")
            time.sleep(1.0)
        raise RuntimeError("shared bench server startup timeout")

    def _loop(self) -> None:
        self._start_server()
        while not self.stop_event.is_set():
            _write(self.session_dir / "heartbeat.json", {"updatedAtUnixSeconds": time.time()})
            if (self.session_dir / "start_requested.json").exists():
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                self._start_server()
            self.stop_event.wait(2.0)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 180
        while time.time() < deadline and not (self.session_dir / "ready.json").exists():
            time.sleep(0.5)
        if not (self.session_dir / "ready.json").exists():
            raise RuntimeError("supervisor never became ready")

    def shutdown(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=15)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _request(session_dir: Path, shared: bool) -> BakeAndRankRequest:
    return BakeAndRankRequest(
        candidates_json=session_dir / "dummy.json",
        workspace=session_dir,
        wham_repo_path=REPO_ROOT / "third_party/WHAM",
        body_model_root=REPO_ROOT / "third_party/WHAM/dataset/body_models",
        llama_cpp_base_url=BASE_URL,
        llama_cpp_model=MODEL,
        llama_cpp_mmproj=MMPROJ,
        llama_cpp_server_command=SERVER,
        llama_cpp_backend="gpu",
        llama_cpp_parallel=8,
        llama_cpp_ctx_size=49152,
        llama_cpp_batch_size=1024,
        llama_cpp_ubatch_size=512,
        llama_cpp_flash_attn="on",
        llama_cpp_cache_type_k="q8_0",
        llama_cpp_cache_type_v="q8_0",
        llama_cpp_fit="on",
        llama_cpp_threads_http=8,
        llama_cpp_mmproj_offload=True,
        llama_cpp_cont_batching=True,
        llama_cpp_disable_reasoning=False,
        llama_cpp_reasoning_budget=64,
        shared_llama_server=shared,
        shared_llama_server_session_dir=session_dir if shared else None,
    )


def _caption_burst(session: LazyLlamaCppVisionSession, frame: Path, count: int) -> list[float]:
    latencies: list[float] = []
    for index in range(count):
        started = time.perf_counter()
        session.caption_images(
            frame_paths=[frame],
            prompt="Reply with the single word: ok",
            disable_reasoning=True,
        )
        latencies.append(round(time.perf_counter() - started, 2))
    return latencies


def run_config(name: str, shared: bool, items: int, captions: int,
               frame: Path, session_dir: Path) -> dict:
    supervisor = SharedSupervisor(session_dir) if shared else None
    result: dict = {"config": name, "captionLatencies": [], "serverStarts": 0}
    started = time.perf_counter()

    # Discovery analog: a second consumer captioning in a loop while the wave
    # session runs its sequence. In owned mode the wave's exclusive handoff
    # force-stops the port server and this consumer's request dies + recovers;
    # in shared mode the quiesce drains it first.
    discovery_state = {"requests": 0, "failures": 0, "recoverSeconds": 0.0}
    discovery_done = threading.Event()

    def discovery_loop() -> None:
        failure_started: float | None = None
        while not discovery_done.is_set():
            try:
                with urllib.request.urlopen(
                    f"{BASE_URL}/v1/models", timeout=3
                ) as response:
                    if response.status != 200:
                        raise RuntimeError("unhealthy")
                payload = json.dumps({
                    "model": MODEL,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": "Reply with the single word: hi"},
                    ]}],
                    "max_tokens": 8, "temperature": 0,
                    "reasoning_format": "none",
                    "chat_template_kwargs": {"enable_thinking": False},
                }).encode("utf-8")
                request = urllib.request.Request(
                    f"{BASE_URL}/v1/chat/completions", data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    json.loads(response.read())
                discovery_state["requests"] += 1
                failure_started = None
            except Exception:
                discovery_state["failures"] += 1
                if failure_started is None:
                    failure_started = time.perf_counter()
            time.sleep(0.25)
        if failure_started is not None:
            discovery_state["recoverSeconds"] = round(time.perf_counter() - failure_started, 2)

    try:
        if supervisor:
            supervisor.start()
            print(f"[bench:{name}] supervisor ready", flush=True)
        discovery_thread = threading.Thread(target=discovery_loop, daemon=True)
        discovery_thread.start()
        session = LazyLlamaCppVisionSession(_request(session_dir, shared))
        try:
            # Source validation: per-item caption bursts.
            for _item in range(items):
                result["captionLatencies"] += _caption_burst(session, frame, captions)
            print(f"[bench:{name}] source captions done {result['captionLatencies']}", flush=True)
            # Small co-resident op (the YOLO-refresh analog; both configs).
            session.run_without_llama_overlap(
                lambda: "small-op",
                small_stage="yolo_pose_prefilter",
                small_min_free_mib=600,
            )
            # Exclusive generation window: server must go down.
            gen_started = time.perf_counter()
            session.run_without_llama_overlap(lambda: time.sleep(2.0) or "gen-done")
            result["exclusiveWindowSeconds"] = round(time.perf_counter() - gen_started, 2)
            print(f"[bench:{name}] exclusive window {result['exclusiveWindowSeconds']}s", flush=True)
            # Final validation: pays the restart in owned mode.
            for _item in range(items):
                result["captionLatencies"] += _caption_burst(session, frame, captions)
        finally:
            session.close(force_stop_server=not shared)
        print(f"[bench:{name}] session closed; discovery={discovery_state}", flush=True)
        manifest = session.timing_manifest()
        result["visionStartups"] = manifest.get("visionRankerStartupCount")
        result["visionStartupSeconds"] = manifest.get("visionRankerStartupSeconds")
        result["coResidentOps"] = manifest.get("coResidentGpuOperationCount")
        shared_metrics = manifest.get("sharedVisionSession") or {}
        result["sharedMetrics"] = {
            key: shared_metrics.get(key)
            for key in (
                "sharedVisionQuiesceCount",
                "sharedVisionQuiesceWaitSeconds",
                "sharedVisionRestartRequestCount",
                "sharedVisionPeakForeignActiveRequests",
            )
        }
        result["discovery"] = dict(discovery_state)
    finally:
        discovery_done.set()
        if supervisor:
            supervisor.shutdown()
            result["serverStarts"] = supervisor.starts
    result["wallSeconds"] = round(time.perf_counter() - started, 2)
    caption_total = sum(result["captionLatencies"])
    result["lifecycleOverheadSeconds"] = round(
        result["wallSeconds"] - caption_total - 2.0, 2
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configs", default="baseline,shared")
    parser.add_argument("--items", type=int, default=2, help="Exercises per wave (caption bursts)")
    parser.add_argument("--captions", type=int, default=3, help="Captions per exercise per phase")
    args = parser.parse_args()

    import cv2
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = BENCH_ROOT / stamp
    root.mkdir(parents=True, exist_ok=True)
    frame = root / "frame.jpg"
    clip = REPO_ROOT / "build/exercise_motion/gvhmr-warm-smoke-20261001/mount/input-a/wham_inference_segment_sanitized.mp4"
    capture = cv2.VideoCapture(str(clip))
    ok, image = capture.read()
    capture.release()
    assert ok, f"bench clip missing: {clip}"
    cv2.imwrite(str(frame), image, [cv2.IMWRITE_JPEG_QUALITY, 85])

    configs = {"baseline": False, "shared": True}
    results = []
    for name in [c.strip() for c in args.configs.split(",") if c.strip()]:
        if name not in configs:
            raise SystemExit(f"unknown config {name}; available: {', '.join(configs)}")
        session_dir = root / name
        session_dir.mkdir(exist_ok=True)
        print(f"[bench] running config '{name}'...", flush=True)
        result = run_config(name, configs[name], args.items, args.captions, frame, session_dir)
        results.append(result)
        print(
            f"[bench] {name}: wall={result['wallSeconds']}s lifecycle={result['lifecycleOverheadSeconds']}s "
            f"startups={result['visionStartups']}/{result['visionStartupSeconds']}s "
            f"exclusive={result.get('exclusiveWindowSeconds')}s "
            f"quiesce={result['sharedMetrics']['sharedVisionQuiesceCount']} "
            f"peakForeign={result['sharedMetrics']['sharedVisionPeakForeignActiveRequests']} "
            f"discovery(req/fail/recover)={result['discovery']['requests']}/"
            f"{result['discovery']['failures']}/{result['discovery']['recoverSeconds']}s "
            f"coRes={result['coResidentOps']} serverStarts={result['serverStarts']}",
            flush=True,
        )
        time.sleep(3)

    results_path = root / "results.json"
    results_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"[bench] results: {results_path}", flush=True)


if __name__ == "__main__":
    main()
