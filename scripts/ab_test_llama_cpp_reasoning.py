from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exercise_motion_pkg.llama_defaults import (  # noqa: E402
    DEFAULT_LLAMA_CPP_MMPROJ,
    DEFAULT_LLAMA_CPP_MODEL,
    DEFAULT_LLAMA_CPP_SERVER_COMMAND,
    DEFAULT_LLAMA_CPP_TEMPERATURE,
    DEFAULT_LLAMA_CPP_TOP_K,
    DEFAULT_LLAMA_CPP_TOP_P,
)
from exercise_motion_pkg.segment_detection import extract_json_object  # noqa: E402
from exercise_motion_pkg.youtube import (  # noqa: E402
    ExerciseEntry,
    build_exercise_motion_contract_prompt,
    build_exercise_name_rewrite_prompt,
    build_youtube_query_planner_prompt,
    slugify,
)


@dataclass(frozen=True)
class RequestMode:
    name: str
    reasoning_format: str | None
    enable_thinking: bool | None


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    max_tokens: int
    exercise_name: str | None = None


REQUEST_MODES = [
    RequestMode("no_request_reasoning_keys", None, None),
    RequestMode("reasoning_off_template_false", "none", False),
    RequestMode("deepseek_format_only", "deepseek", None),
    RequestMode("deepseek_template_true", "deepseek", True),
]


def build_tasks(exercise_names: list[str] | None = None) -> list[Task]:
    if not exercise_names:
        exercise_names = ["Weighted Pull-Ups"]
    exercises = [
        ExerciseEntry(
            exercise_id=slugify(name),
            name=name,
            slug=slugify(name),
            source_name=name,
            equipment_qualified_name=name,
        )
        for name in exercise_names
        if name.strip()
    ]
    weighted_pullups = exercises[0] if len(exercises) == 1 else ExerciseEntry(
        exercise_id="weighted-pull-ups",
        name="Weighted Pull-Ups",
        slug="weighted-pull-ups",
        source_name="Pull-Ups",
        equipment_qualified_name="Weighted Pull-Ups",
    )
    base_queries = [
        '"Weighted Pull-Ups" exercise demonstration',
        '"Weighted Pull-Ups" exercise demo full rep',
        '"Weighted Pull-Ups" proper form',
    ]
    tasks = [
        Task(
            "strict_json_64",
            'Return JSON only: {"ok": true, "label": "strict"}',
            64,
        ),
        Task(
            "strict_json_256",
            'Return JSON only: {"ok": true, "label": "strict"}',
            256,
        ),
        Task(
            "strict_json_1024",
            'Return JSON only: {"ok": true, "label": "strict"}',
            1024,
        ),
        Task(
            "name_rewrite_weighted_pullups_192",
            build_exercise_name_rewrite_prompt(weighted_pullups),
            192,
            weighted_pullups.name,
        ),
        Task(
            "name_rewrite_weighted_pullups_768",
            build_exercise_name_rewrite_prompt(weighted_pullups),
            768,
            weighted_pullups.name,
        ),
        Task(
            "query_planner_weighted_pullups_256",
            build_youtube_query_planner_prompt(
                exercise_name=weighted_pullups.name,
                base_queries=base_queries,
                max_queries=5,
            ),
            256,
            weighted_pullups.name,
        ),
        Task(
            "query_planner_weighted_pullups_768",
            build_youtube_query_planner_prompt(
                exercise_name=weighted_pullups.name,
                base_queries=base_queries,
                max_queries=5,
            ),
            768,
            weighted_pullups.name,
        ),
        Task(
            "motion_contract_weighted_pullups_512",
            build_exercise_motion_contract_prompt(weighted_pullups),
            512,
            weighted_pullups.name,
        ),
        Task(
            "motion_contract_weighted_pullups_1024",
            build_exercise_motion_contract_prompt(weighted_pullups),
            1024,
            weighted_pullups.name,
        ),
        Task(
            "motion_contract_weighted_pullups_1536",
            build_exercise_motion_contract_prompt(weighted_pullups),
            1536,
            weighted_pullups.name,
        ),
    ]
    if len(exercises) == 1 and exercises[0].slug == weighted_pullups.slug:
        return tasks
    for exercise in exercises:
        exercise_base_queries = [
            f'"{exercise.name}" exercise demonstration',
            f'"{exercise.name}" exercise demo full rep',
            f'"{exercise.name}" proper form',
        ]
        tasks.extend(
            [
                Task(
                    f"name_rewrite_{exercise.slug}_768",
                    build_exercise_name_rewrite_prompt(exercise),
                    768,
                    exercise.name,
                ),
                Task(
                    f"query_planner_{exercise.slug}_768",
                    build_youtube_query_planner_prompt(
                        exercise_name=exercise.name,
                        base_queries=exercise_base_queries,
                        max_queries=5,
                    ),
                    768,
                    exercise.name,
                ),
                Task(
                    f"motion_contract_{exercise.slug}_1536",
                    build_exercise_motion_contract_prompt(exercise),
                    1536,
                    exercise.name,
                ),
            ]
        )
    return tasks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A/B test llama.cpp reasoning server/request settings on strict JSON pipeline prompts."
    )
    parser.add_argument("--out-json", type=Path, default=REPO_ROOT / "build" / "exercise_motion" / "llama_reasoning_ab.json")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--server-mode", choices=["on", "off"], action="append")
    parser.add_argument(
        "--server-reasoning-budget",
        type=int,
        action="append",
        help=(
            "Server-side thinking budget to test when --server-mode on is used. "
            "Use -1 for unrestricted. Defaults to -1 for reasoning=on."
        ),
    )
    parser.add_argument(
        "--server-reasoning-budget-message",
        default="Now stop thinking and return the JSON object.",
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--ctx-size", type=int, default=24576)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=DEFAULT_LLAMA_CPP_TEMPERATURE)
    parser.add_argument("--top-p", type=float, default=DEFAULT_LLAMA_CPP_TOP_P)
    parser.add_argument("--top-k", type=int, default=DEFAULT_LLAMA_CPP_TOP_K)
    parser.add_argument(
        "--task",
        action="append",
        help="Task name(s) to run. Defaults to all generated text-only control-plane tasks.",
    )
    parser.add_argument(
        "--exercise-name",
        action="append",
        help="Exercise name to generate name-rewrite, query-planner, and motion-contract prompts for.",
    )
    parser.add_argument(
        "--request-mode",
        action="append",
        choices=[mode.name for mode in REQUEST_MODES],
        help="Request reasoning mode(s) to run. Defaults to all modes.",
    )
    return parser.parse_args()


def wait_for_server(base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/v1/models", timeout=5.0)
            if response.status_code < 500:
                response.raise_for_status()
                return
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            last_error = str(exc)
        time.sleep(1.0)
    raise RuntimeError(f"llama-server did not become ready at {base_url}: {last_error}")


def start_server(
    *,
    server_mode: str,
    reasoning_budget: int | None,
    reasoning_budget_message: str,
    port: int,
    ctx_size: int,
    parallel: int,
    startup_timeout: float,
) -> subprocess.Popen[str]:
    command = [
        DEFAULT_LLAMA_CPP_SERVER_COMMAND,
        "-m",
        DEFAULT_LLAMA_CPP_MODEL,
        "--mmproj",
        DEFAULT_LLAMA_CPP_MMPROJ,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--parallel",
        str(max(1, parallel)),
        "--ctx-size",
        str(max(1024, ctx_size)),
        "--reasoning",
        server_mode,
        "--reasoning-format",
        "deepseek" if server_mode == "on" else "none",
        "--mmproj-offload",
        "--cont-batching",
        "--gpu-layers",
        "all",
    ]
    if server_mode == "off":
        command.extend(["--reasoning-budget", "0"])
    elif reasoning_budget is not None:
        command.extend(["--reasoning-budget", str(reasoning_budget)])
        if reasoning_budget >= 0 and reasoning_budget_message:
            command.extend(["--reasoning-budget-message", reasoning_budget_message])
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=creationflags,
    )
    try:
        wait_for_server(f"http://127.0.0.1:{port}", startup_timeout)
    except Exception:
        stop_server(process)
        raise
    return process


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10.0)


def build_payload(task: Task, mode: RequestMode, *, temperature: float, top_p: float, top_k: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": DEFAULT_LLAMA_CPP_MODEL,
        "messages": [{"role": "user", "content": [{"type": "text", "text": task.prompt}]}],
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "max_tokens": task.max_tokens,
        "response_format": {"type": "json_object"},
    }
    if mode.reasoning_format is not None:
        payload["reasoning_format"] = mode.reasoning_format
    if mode.enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": mode.enable_thinking}
    return payload


def exercise_identity_tokens(exercise_name: str | None) -> list[str]:
    if not exercise_name:
        return []
    normalized = exercise_name.casefold().replace("-", " ")
    stopwords = {"the", "and", "with", "from", "raise", "raises", "press", "curl", "crunch"}
    tokens = []
    for token in normalized.split():
        token = "".join(ch for ch in token if ch.isalnum())
        if len(token) <= 2 or token in stopwords:
            continue
        tokens.append(token)
    return tokens


def identity_token_match_score(text: str, exercise_name: str | None) -> float:
    tokens = exercise_identity_tokens(exercise_name)
    if not tokens:
        return 1.0
    normalized_text = text.casefold().replace("-", " ")
    matches = sum(1 for token in tokens if token in normalized_text)
    return matches / len(tokens)


def evaluate_payload(task: Task, payload: dict[str, Any] | None) -> dict[str, Any]:
    task_name = task.name
    if not isinstance(payload, dict):
        return {"schemaOk": False, "qualityScore": 0.0, "qualityReasons": ["no_json_object"]}
    reasons: list[str] = []
    score = 0.0
    if task_name.startswith("strict_json"):
        ok = payload.get("ok") is True
        return {"schemaOk": ok, "qualityScore": 1.0 if ok else 0.0, "qualityReasons": [] if ok else ["missing_ok_true"]}
    if task_name.startswith("name_rewrite"):
        if isinstance(payload.get("canonicalExerciseName"), str) and payload["canonicalExerciseName"].strip():
            score += 0.35
        else:
            reasons.append("missing_canonicalExerciseName")
        if isinstance(payload.get("rewriteNeeded"), bool):
            score += 0.25
        else:
            reasons.append("missing_rewriteNeeded_boolean")
        if isinstance(payload.get("confidence"), int | float):
            score += 0.20
        else:
            reasons.append("missing_numeric_confidence")
        canonical = str(payload.get("canonicalExerciseName") or "")
        if identity_token_match_score(canonical, task.exercise_name) >= 0.5:
            score += 0.20
        else:
            reasons.append("canonical_does_not_preserve_exercise_identity")
        return {"schemaOk": score >= 0.80, "qualityScore": round(score, 3), "qualityReasons": reasons}
    if task_name.startswith("query_planner"):
        queries = payload.get("queries")
        if isinstance(queries, list) and all(isinstance(item, str) for item in queries):
            score += 0.45
            if queries:
                score += 0.20
        else:
            reasons.append("missing_queries_list")
            queries = []
        joined = " ".join(queries) if isinstance(queries, list) else ""
        if identity_token_match_score(joined, task.exercise_name) >= 0.5:
            score += 0.25
        else:
            reasons.append("queries_do_not_preserve_exercise_identity")
        joined_casefolded = joined.casefold()
        if not any(bad in joined_casefolded for bad in ("chin-up", "chin up", "assisted", "banded", "kipping")):
            score += 0.10
        else:
            reasons.append("queries_include_wrong_variant")
        return {"schemaOk": score >= 0.80, "qualityScore": round(score, 3), "qualityReasons": reasons}
    if task_name.startswith("motion_contract"):
        required_phases = payload.get("requiredPhases")
        reject_if = payload.get("rejectIf")
        observable = payload.get("observableMotionSpec")
        aliases = payload.get("youtubeQueryAliases")
        if isinstance(required_phases, list) and required_phases:
            score += 0.25
        else:
            reasons.append("missing_requiredPhases")
        if isinstance(reject_if, list) and reject_if:
            score += 0.20
        else:
            reasons.append("missing_rejectIf")
        if isinstance(observable, dict):
            score += 0.30
            if observable.get("motionPattern") == "body_toward_anchor":
                score += 0.10
            else:
                reasons.append("observable_motion_not_body_toward_anchor")
        else:
            reasons.append("missing_observableMotionSpec")
        if isinstance(aliases, list) and aliases:
            score += 0.10
        else:
            reasons.append("missing_youtubeQueryAliases")
        text = json.dumps(payload, ensure_ascii=False)
        if identity_token_match_score(text, task.exercise_name) >= 0.5:
            score += 0.05
        else:
            reasons.append("contract_does_not_preserve_exercise_identity")
        return {"schemaOk": score >= 0.80, "qualityScore": round(score, 3), "qualityReasons": reasons}
    return {"schemaOk": True, "qualityScore": 0.0, "qualityReasons": ["unknown_task"]}


def run_request(
    *,
    base_url: str,
    server_mode: str,
    reasoning_budget: int | None,
    request_mode: RequestMode,
    task: Task,
    timeout_seconds: float,
    temperature: float,
    top_p: float,
    top_k: int,
) -> dict[str, Any]:
    payload = build_payload(task, request_mode, temperature=temperature, top_p=top_p, top_k=top_k)
    started = time.monotonic()
    result: dict[str, Any] = {
        "serverReasoning": server_mode,
        "serverReasoningBudget": reasoning_budget,
        "requestMode": request_mode.name,
        "task": task.name,
        "maxTokens": task.max_tokens,
    }
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(f"{base_url}/v1/chat/completions", json=payload)
        result["httpStatus"] = response.status_code
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        content = str(message.get("content") or "")
        reasoning_content = str(message.get("reasoning_content") or "")
        parsed_payload: dict[str, Any] | None = None
        parse_error: str | None = None
        try:
            extracted = extract_json_object(content)
            if isinstance(extracted, dict):
                parsed_payload = extracted
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            parse_error = str(exc)
        result.update(
            {
                "status": "ok",
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "finishReason": data["choices"][0].get("finish_reason"),
                "contentLength": len(content),
                "reasoningContentLength": len(reasoning_content),
                "contentPreview": content[:300],
                "reasoningPreview": reasoning_content[:300],
                "jsonParseOk": parsed_payload is not None,
                "jsonParseError": parse_error,
                "usage": data.get("usage"),
                **evaluate_payload(task, parsed_payload),
            }
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        result.update(
            {
                "status": "error",
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "error": str(exc),
                "jsonParseOk": False,
                "schemaOk": False,
                "qualityScore": 0.0,
                "qualityReasons": ["request_failed"],
            }
        )
    print(
        f"{server_mode:>3} | {request_mode.name:<31} | {task.name:<39} | "
        f"{result['status']:<5} | json={result.get('jsonParseOk')} | "
        f"schema={result.get('schemaOk')} | q={result.get('qualityScore')} | "
        f"{result['elapsedSeconds']}s",
        flush=True,
    )
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        key = (
            f"server={result['serverReasoning']} budget={result.get('serverReasoningBudget')} "
            f"request={result['requestMode']}"
        )
        group = groups.setdefault(
            key,
            {"count": 0, "jsonOk": 0, "schemaOk": 0, "qualityScoreTotal": 0.0, "elapsedTotal": 0.0},
        )
        group["count"] += 1
        group["jsonOk"] += 1 if result.get("jsonParseOk") else 0
        group["schemaOk"] += 1 if result.get("schemaOk") else 0
        group["qualityScoreTotal"] += float(result.get("qualityScore") or 0.0)
        group["elapsedTotal"] += float(result.get("elapsedSeconds") or 0.0)
    rows = []
    for key, group in sorted(groups.items()):
        count = max(1, group["count"])
        rows.append(
            {
                "setting": key,
                "count": group["count"],
                "jsonOkRate": round(group["jsonOk"] / count, 3),
                "schemaOkRate": round(group["schemaOk"] / count, 3),
                "avgQualityScore": round(group["qualityScoreTotal"] / count, 3),
                "avgElapsedSeconds": round(group["elapsedTotal"] / count, 3),
            }
        )
    return {"bySetting": rows}


def main() -> int:
    args = parse_args()
    selected_task_names = set(args.task or [])
    tasks = [
        task
        for task in build_tasks(args.exercise_name)
        if not selected_task_names or task.name in selected_task_names
    ]
    if selected_task_names and not tasks:
        raise ValueError(f"No generated tasks matched: {sorted(selected_task_names)}")
    selected_request_modes = set(args.request_mode or [])
    request_modes = [
        mode for mode in REQUEST_MODES if not selected_request_modes or mode.name in selected_request_modes
    ]
    server_modes = args.server_mode or ["off", "on"]
    reasoning_budgets = args.server_reasoning_budget or [-1]
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []
    started = time.monotonic()
    for server_mode in server_modes:
        budgets_for_mode: list[int | None] = [None] if server_mode == "off" else reasoning_budgets
        for reasoning_budget in budgets_for_mode:
            print(
                f"Starting llama-server reasoning={server_mode} budget={reasoning_budget} on port {args.port}",
                flush=True,
            )
            process = start_server(
                server_mode=server_mode,
                reasoning_budget=reasoning_budget,
                reasoning_budget_message=args.server_reasoning_budget_message,
                port=args.port,
                ctx_size=args.ctx_size,
                parallel=args.parallel,
                startup_timeout=args.server_startup_timeout_seconds,
            )
            try:
                base_url = f"http://127.0.0.1:{args.port}"
                for request_mode in request_modes:
                    for task in tasks:
                        all_results.append(
                            run_request(
                                base_url=base_url,
                                server_mode=server_mode,
                                reasoning_budget=reasoning_budget,
                                request_mode=request_mode,
                                task=task,
                                timeout_seconds=args.request_timeout_seconds,
                                temperature=args.temperature,
                                top_p=args.top_p,
                                top_k=args.top_k,
                            )
                        )
            finally:
                stop_server(process)
    output = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "model": DEFAULT_LLAMA_CPP_MODEL,
        "mmproj": DEFAULT_LLAMA_CPP_MMPROJ,
        "settings": {
            "requestTimeoutSeconds": args.request_timeout_seconds,
            "serverReasoningBudgets": reasoning_budgets,
            "serverReasoningBudgetMessage": args.server_reasoning_budget_message,
            "ctxSize": args.ctx_size,
            "parallel": args.parallel,
            "temperature": args.temperature,
            "topP": args.top_p,
            "topK": args.top_k,
        },
        "summary": summarize(all_results),
        "results": all_results,
    }
    args.out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
