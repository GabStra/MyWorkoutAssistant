from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exercise_motion_pkg.llama_defaults import (
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET,
    DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE,
    DEFAULT_LLAMA_CPP_SERVER_COMMAND,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
)


DEFAULT_IMAGE = (
    Path("build")
    / "exercise_motion"
    / "barbell-calves-generic-contract-e2e-20260627_205141"
    / "barbell-calves"
    / "selected"
    / "barbell_calves_selected_input_contact.jpg"
)


@dataclass(frozen=True)
class Profile:
    name: str
    ctx_size: int
    image_max_tokens: int | None
    mtmd_batch_max_tokens: int | None
    parallel: int
    fit_target: int


def parse_profile(value: str) -> Profile:
    parts = {}
    for chunk in value.split(","):
        if "=" not in chunk:
            raise argparse.ArgumentTypeError(f"Invalid profile chunk: {chunk!r}")
        key, raw = chunk.split("=", 1)
        parts[key.strip()] = raw.strip()
    try:
        return Profile(
            name=parts["name"],
            ctx_size=int(parts["ctx"]),
            image_max_tokens=None if parts.get("image", "").lower() in {"", "none", "default"} else int(parts["image"]),
            mtmd_batch_max_tokens=None if parts.get("mtmd", "").lower() in {"", "none", "default"} else int(parts["mtmd"]),
            parallel=int(parts["parallel"]),
            fit_target=int(parts.get("fit_target", "2048")),
        )
    except KeyError as exc:
        raise argparse.ArgumentTypeError(f"Missing profile key: {exc}") from exc


def default_profiles() -> list[Profile]:
    return [
        Profile("current-safe-p4", 24576, None, None, 4, 2048),
        Profile("fast-12288-img1024-p4", 12288, 1024, 512, 4, 2048),
        Profile("fast-8192-img768-p4", 8192, 768, 512, 4, 2048),
        Profile("parallel-8192-img768-p6", 8192, 768, 512, 6, 2048),
        Profile("parallel-8192-img512-p6", 8192, 512, 512, 6, 2048),
    ]


def wait_for_server(base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/v1/models", timeout=5.0)
            if response.status_code < 500:
                response.raise_for_status()
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except Exception as exc:  # noqa: BLE001 - diagnostic loop
            last_error = str(exc)
        time.sleep(1.0)
    raise RuntimeError(f"server did not become ready: {last_error}")


def start_server(
    *,
    profile: Profile,
    port: int,
    server_command: str,
    model: str,
    mmproj: str,
    startup_timeout_seconds: float,
    log_path: Path,
    reasoning: bool,
    mtp_model: str | None,
    spec_draft_n_max: int,
) -> tuple[subprocess.Popen[str], float]:
    command = [
        server_command,
        "-m",
        model,
        "--mmproj",
        mmproj,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--parallel",
        str(profile.parallel),
        "--ctx-size",
        str(profile.ctx_size),
        "--fit",
        "on",
        "--fit-ctx",
        str(profile.ctx_size),
        "--fit-target",
        str(profile.fit_target),
        "--batch-size",
        "256",
        "--ubatch-size",
        "512",
        "--flash-attn",
        "on",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--mmproj-offload",
        "--cont-batching",
        "--gpu-layers",
        "all",
        "--no-mmap",
        "--mlock",
    ]
    if profile.image_max_tokens is not None:
        command.extend(["--image-max-tokens", str(profile.image_max_tokens)])
    if profile.mtmd_batch_max_tokens is not None:
        command.extend(["--mtmd-batch-max-tokens", str(profile.mtmd_batch_max_tokens)])
    if mtp_model:
        command.extend(
            [
                "--model-draft",
                mtp_model,
                "--spec-type",
                "draft-mtp",
                "--spec-draft-n-max",
                str(max(1, spec_draft_n_max)),
                "--gpu-layers-draft",
                "all",
            ]
        )
    if reasoning:
        command.extend(
            [
                "--reasoning",
                "on",
                "--reasoning-format",
                "deepseek",
                "--reasoning-budget",
                str(DEFAULT_LLAMA_CPP_REASONING_BUDGET),
                "--reasoning-budget-message",
                DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE,
            ]
        )
    else:
        command.extend(["--reasoning", "off", "--reasoning-format", "none", "--reasoning-budget", "0"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    log_handle.write(" ".join(command) + "\n\n")
    log_handle.flush()
    env = os.environ.copy()
    env.setdefault("GGML_CUDA_GRAPH_OPT", "0")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    started_at = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
        env=env,
    )
    try:
        wait_for_server(f"http://127.0.0.1:{port}", startup_timeout_seconds)
    except Exception:
        stop_server(process)
        log_handle.close()
        raise
    startup_seconds = time.perf_counter() - started_at
    process._mwa_log_handle = log_handle  # type: ignore[attr-defined]
    return process, startup_seconds


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10.0)
    log_handle = getattr(process, "_mwa_log_handle", None)
    if log_handle is not None:
        log_handle.close()


def build_payload(*, image_b64: str, model: str, prompt: str, reasoning: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
        "temperature": DEFAULT_LLAMA_CPP_TEMPERATURE,
        "top_p": DEFAULT_LLAMA_CPP_TOP_P,
        "top_k": DEFAULT_LLAMA_CPP_TOP_K,
        "max_tokens": 192,
        "response_format": {"type": "json_object"},
        "reasoning_format": "deepseek" if reasoning else "none",
        "chat_template_kwargs": {"enable_thinking": reasoning},
    }
    return payload


def parse_json_response(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def send_request(base_url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(f"{base_url}/v1/chat/completions", json=payload)
        elapsed = time.perf_counter() - started_at
        body = response.text
        if response.status_code >= 400:
            return {"ok": False, "elapsedSeconds": elapsed, "status": response.status_code, "error": body[:500]}
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        parsed = parse_json_response(content)
        expected_positive = False
        if isinstance(parsed, dict):
            expected_positive = bool(parsed.get("contains_target_movement")) and bool(parsed.get("valid_sequence"))
        return {
            "ok": parsed is not None,
            "elapsedSeconds": elapsed,
            "status": response.status_code,
            "jsonValid": parsed is not None,
            "expectedPositive": expected_positive,
            "content": content[:500],
        }
    except Exception as exc:  # noqa: BLE001 - benchmark result
        return {"ok": False, "elapsedSeconds": time.perf_counter() - started_at, "status": None, "error": str(exc)}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def run_profile(
    *,
    profile: Profile,
    index: int,
    args: argparse.Namespace,
    image_b64: str,
    prompt: str,
) -> dict[str, Any]:
    port = args.port_base + index
    log_path = args.output_dir / f"{profile.name}.server.log"
    base_url = f"http://127.0.0.1:{port}"
    process: subprocess.Popen[str] | None = None
    started_at = time.perf_counter()
    result: dict[str, Any] = {
        "profile": profile.__dict__,
        "baseUrl": base_url,
        "serverLogPath": str(log_path),
    }
    try:
        process, startup_seconds = start_server(
            profile=profile,
            port=port,
            server_command=args.server_command,
            model=args.model,
            mmproj=args.mmproj,
            startup_timeout_seconds=args.startup_timeout_seconds,
            log_path=log_path,
            reasoning=not args.disable_reasoning,
            mtp_model=args.mtp_model,
            spec_draft_n_max=args.spec_draft_n_max,
        )
        result["startupSeconds"] = round(startup_seconds, 3)
        payload = build_payload(
            image_b64=image_b64,
            model=args.model,
            prompt=prompt,
            reasoning=not args.disable_reasoning,
        )
        single = send_request(base_url, payload, args.request_timeout_seconds)
        result["warmupRequest"] = single
        request_results: list[dict[str, Any]] = []
        batch_started_at = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.request_concurrency) as executor:
            futures = [
                executor.submit(send_request, base_url, payload, args.request_timeout_seconds)
                for _ in range(args.requests)
            ]
            for future in as_completed(futures):
                request_results.append(future.result())
        batch_seconds = time.perf_counter() - batch_started_at
        latencies = [float(item["elapsedSeconds"]) for item in request_results if item.get("elapsedSeconds") is not None]
        ok_count = sum(1 for item in request_results if item.get("ok"))
        json_valid_count = sum(1 for item in request_results if item.get("jsonValid"))
        positive_count = sum(1 for item in request_results if item.get("expectedPositive"))
        result["batch"] = {
            "requests": args.requests,
            "requestConcurrency": args.request_concurrency,
            "elapsedSeconds": round(batch_seconds, 3),
            "requestsPerSecond": round(args.requests / batch_seconds, 4) if batch_seconds > 0 else None,
            "okCount": ok_count,
            "jsonValidCount": json_valid_count,
            "expectedPositiveCount": positive_count,
            "failureCount": args.requests - ok_count,
            "latencySeconds": {
                "min": round(min(latencies), 3) if latencies else None,
                "mean": round(statistics.fmean(latencies), 3) if latencies else None,
                "p50": round(percentile(latencies, 0.50), 3) if latencies else None,
                "p90": round(percentile(latencies, 0.90), 3) if latencies else None,
                "max": round(max(latencies), 3) if latencies else None,
            },
        }
        result["requests"] = request_results
    except Exception as exc:  # noqa: BLE001 - benchmark result
        result["error"] = str(exc)
    finally:
        if process is not None:
            stop_server(process)
        result["totalSeconds"] = round(time.perf_counter() - started_at, 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark isolated llama.cpp vision runtime settings.")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--output-dir", type=Path, default=Path("build") / "llama_cpp_vision_bench")
    parser.add_argument("--server-command", default=DEFAULT_LLAMA_CPP_SERVER_COMMAND)
    parser.add_argument("--model", default=DEFAULT_LLAMA_CPP_MODEL)
    parser.add_argument("--mmproj", default=DEFAULT_LLAMA_CPP_MMPROJ)
    parser.add_argument("--mtp-model")
    parser.add_argument("--spec-draft-n-max", type=int, default=3)
    parser.add_argument("--port-base", type=int, default=8190)
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--request-concurrency", type=int, default=4)
    parser.add_argument("--startup-timeout-seconds", type=float, default=240.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--disable-reasoning", action="store_true")
    parser.add_argument(
        "--profile",
        action="append",
        type=parse_profile,
        help="Profile: name=...,ctx=...,image=768|none,mtmd=512|none,parallel=4,fit_target=2048",
    )
    parser.add_argument(
        "--prompt",
        default=(
            "Read the contact sheet left-to-right, top row first, then bottom row. "
            "Return JSON only with keys contains_target_movement, valid_sequence, exercise, confidence, reason. "
            "The target is a standing barbell calf raise: a person holds a barbell across the upper back and rises onto the toes, then lowers. "
            "Set contains_target_movement true only if the frames visibly show that movement sequence."
        ),
    )
    args = parser.parse_args()
    profiles = args.profile or default_profiles()
    image_path = args.image.resolve()
    if not image_path.exists():
        raise FileNotFoundError(image_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    results = []
    for index, profile in enumerate(profiles):
        print(f"[{index + 1}/{len(profiles)}] {profile.name}", flush=True)
        result = run_profile(profile=profile, index=index, args=args, image_b64=image_b64, prompt=args.prompt)
        results.append(result)
        batch = result.get("batch")
        if isinstance(batch, dict):
            print(
                f"  startup={result.get('startupSeconds')}s batch={batch.get('elapsedSeconds')}s "
                f"rps={batch.get('requestsPerSecond')} ok={batch.get('okCount')}/{batch.get('requests')} "
                f"positive={batch.get('expectedPositiveCount')}/{batch.get('requests')}",
                flush=True,
            )
        else:
            print(f"  failed: {result.get('error')}", flush=True)
    output = {
        "image": str(image_path),
        "requests": args.requests,
        "requestConcurrency": args.request_concurrency,
        "reasoning": not args.disable_reasoning,
        "results": results,
    }
    output_path = args.output_dir / "benchmark_results.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}", flush=True)
    return 0 if all("batch" in result for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
