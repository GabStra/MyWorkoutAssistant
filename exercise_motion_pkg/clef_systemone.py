"""Small adapter for Clef-Flash's typed, multimodal SystemOne endpoint."""

from __future__ import annotations

import base64
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from contextvars import ContextVar
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from .gpu_lock import GlobalGpuLock

CLEF_FINAL_REVIEW_POLICY_VERSION = "clef-final-preview-review-v1"
CLEF_FINAL_REVIEW_FINDING_THRESHOLD = 0.80
CLEF_VISUAL_DECISION_POLICY_VERSION = "clef-visual-decisions-v1"
CLEF_WINDOW_SELECTION_CONFIDENCE_THRESHOLD = 0.50
CLEF_SUPPORT_DOMINANCE_CONFIDENCE_THRESHOLD = 0.45
CLEF_ENDPOINT_OBSERVATION_CONFIDENCE_THRESHOLD = 0.20

_MANAGED_SERVER_LOCK = threading.Lock()
_MANAGED_SERVER_STARTUP_TIMEOUT_SECONDS = 180.0
_CLEF_SERVER_BATCH_SIZE = 3072
_CLEF_SERVER_UBATCH_SIZE = 3072
_ACTIVE_MANAGED_CLEF_ENDPOINT: ContextVar[tuple[str, int] | None] = ContextVar(
    "active_managed_clef_endpoint",
    default=None,
)

_FINAL_REVIEW_QUESTIONS: dict[str, dict[str, Any]] = {
    "subject_readable": {
        "type": "noul",
        "instructions": (
            "Is the rendered body subject clearly readable across the supplied preview sheets? "
            "Answer false only for an obvious display problem such as severe clipping, a broken "
            "silhouette, or the subject being too unclear to inspect. Do not judge anatomy, "
            "exercise correctness, or equipment."
        ),
        "criteria": {
            "true": "The body subject is readable enough to inspect in the supplied views.",
            "false": "A clear display or readability problem makes the subject hard to inspect.",
        },
    },
    "movement_recognizable": {
        "type": "noul",
        "instructions": (
            "Is the broad body action visually recognizable as a deliberate movement from the "
            "sampled poses? Do not identify the exercise, judge its correctness, or infer equipment."
        ),
        "criteria": {
            "true": "The broad body action is visually recognizable from the supplied poses.",
            "false": "The sampled poses do not make the broad body action visually recognizable.",
        },
    },
    "obvious_mesh_or_display_defect": {
        "type": "noul",
        "instructions": (
            "Is there an obvious mesh, silhouette, or rendering defect visible in the supplied "
            "preview sheets? Ignore ordinary pose variation, perspective, and uncertain anatomy."
        ),
        "criteria": {
            "true": "A clear mesh, silhouette, or rendering defect is visible.",
            "false": "No clear mesh, silhouette, or rendering defect is visible.",
        },
    },
}


def final_preview_review_contract(sampled_frame_indices: list[int]) -> dict[str, Any]:
    return {
        "state": {
            "reviewPolicyVersion": CLEF_FINAL_REVIEW_POLICY_VERSION,
            "purpose": "Optional advisory review of the rendered movement preview.",
            "limits": [
                "These images show the selected body-only artifact, not source footage.",
                "Do not decide acceptance, rejection, retry, exercise identity, or movement mechanics.",
                "Image sheets may contain multiple numbered sample frames; answers apply to the whole preview.",
            ],
            "sampledFrameIndices": sampled_frame_indices,
            "cellToFrameIndex": {
                str(cell): frame_index
                for cell, frame_index in enumerate(sampled_frame_indices, start=1)
            },
        },
        "questions": _FINAL_REVIEW_QUESTIONS,
    }


def build_final_preview_review_request(
    *,
    model: str,
    frame_paths: list[Path],
    sampled_frame_indices: list[int],
) -> dict[str, Any]:
    """Build one typed review request and encode its image sheets as data URLs."""
    if not frame_paths:
        raise ValueError("Clef final preview review requires at least one rendered image sheet.")

    image_data_urls = _images_as_data_urls(frame_paths)
    image_manifest: list[dict[str, Any]] = []
    for index, path in enumerate(frame_paths):
        image_manifest.append(
            {
                "imageIndex": index,
                "view": path.parent.name,
                "fileName": path.name,
            }
        )

    request_payload = {
        "model": model,
        **final_preview_review_contract(sampled_frame_indices),
        "images": image_data_urls,
    }
    request_payload["state"]["imageManifest"] = image_manifest
    return request_payload


def request_choice_decisions(
    *,
    base_url: str,
    model: str,
    frame_paths: list[Path],
    state: dict[str, Any] | str,
    questions: dict[str, dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Ask one image-grounded batch of typed choices and validate its answer schema."""
    if not questions:
        raise ValueError("Clef choice request requires at least one typed question.")
    request_payload = {
        "model": model,
        "state": state,
        "questions": questions,
        "images": _images_as_data_urls(frame_paths),
    }
    endpoint = f"{base_url.rstrip('/')}/v1/systemone"
    with httpx.Client(timeout=max(1.0, float(timeout_seconds))) as client:
        response = client.post(endpoint, json=request_payload)
    if response.status_code >= 400:
        body = response.text.strip()
        if len(body) > 1200:
            body = body[:1200] + "...[truncated]"
        raise RuntimeError(
            f"Clef SystemOne request failed ({response.status_code}) at {endpoint}: {body}"
        )
    payload = response.json()
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        raise ValueError("Clef SystemOne response is missing its answers object.")

    decisions: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        answer = answers.get(question_id)
        options = question.get("criteria")
        if not isinstance(answer, dict) or not isinstance(options, dict):
            raise ValueError(f"Clef SystemOne response has an invalid answer for {question_id!r}.")
        choice = answer.get("choice")
        confidence = answer.get("confidence")
        if not isinstance(choice, str) or choice not in options:
            raise ValueError(f"Clef SystemOne answer {question_id!r} selected an unknown choice.")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError(f"Clef SystemOne answer {question_id!r} has invalid confidence.")
        decisions[question_id] = {
            "choice": choice,
            "confidence": float(confidence),
            "probabilities": answer.get("probabilities"),
        }
    return {"decisions": decisions, "rawSystemOneResponse": payload}


def choice_question(
    *, instructions: str, options: dict[str, str | None]
) -> dict[str, Any]:
    if len(options) < 2:
        raise ValueError("A Clef choice question needs at least two options.")
    return {"type": "choice", "instructions": instructions, "criteria": options}


def request_window_selection(
    *,
    base_url: str,
    model: str,
    exercise_name: str | None,
    candidates: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Compare one contact sheet per candidate; return a window index or None."""
    labels = "ABCDEFGH"
    if not 2 <= len(candidates) <= len(labels):
        raise ValueError("Clef window selection supports 2 to 8 candidates.")
    frame_paths: list[Path] = []
    options: dict[str, str] = {}
    candidate_manifest: list[dict[str, Any]] = []
    label_to_index: dict[str, int] = {}
    for label, candidate in zip(labels, candidates):
        paths = candidate.get("frame_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError("Each Clef window candidate requires at least one contact sheet.")
        frame_paths.append(Path(paths[0]))
        window_index = int(candidate["window_index"])
        options[label] = (
            f"Candidate {label}: window index {window_index}, "
            f"{float(candidate['start_seconds']):.2f}s to {float(candidate['end_seconds']):.2f}s."
        )
        label_to_index[label] = window_index
        candidate_manifest.append(
            {
                "choice": label,
                "windowIndex": window_index,
                "startSeconds": float(candidate["start_seconds"]),
                "endSeconds": float(candidate["end_seconds"]),
                "imageIndex": len(frame_paths) - 1,
            }
        )
    options["Z"] = "None of the candidates clearly shows one complete execution of the target exercise."
    result = request_choice_decisions(
        base_url=base_url,
        model=model,
        frame_paths=frame_paths,
        state={
            "purpose": "Choose which source window to keep for downstream motion reconstruction.",
            "targetExercise": exercise_name or "unknown",
            "candidateImageOrder": "Each attached contact sheet corresponds to the candidate with the same imageIndex.",
            "candidateWindows": candidate_manifest,
            "limits": [
                "Use only the visible images; do not infer missing phases from other windows.",
                "Prefer one complete execution with its full action path and controlled return or end posture.",
                "Choose Z if no candidate clearly contains a complete target execution.",
            ],
        },
        questions={
            "window": choice_question(
                instructions=(
                    "Which candidate contact sheet best contains one complete, real execution of the target exercise? "
                    "Reject setup transitions, holds, similar exercises, partial repetitions, and embedded screens. "
                    "Choose Z when no candidate is clearly suitable."
                ),
                options=options,
            )
        },
        timeout_seconds=timeout_seconds,
    )
    decision = result["decisions"]["window"]
    choice = decision["choice"]
    return {
        "windowIndex": label_to_index.get(choice),
        "choice": choice,
        "confidence": decision["confidence"],
        "confidenceAccepted": decision["confidence"] >= CLEF_WINDOW_SELECTION_CONFIDENCE_THRESHOLD,
        "rawSystemOneResponse": result["rawSystemOneResponse"],
    }


def request_support_dominance_decision(
    *,
    base_url: str,
    model: str,
    frame_paths: list[Path],
    exercise_name: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    options = {
        "A": "foot_dominant: the primary support and propulsion come from the feet or legs.",
        "B": "hand_dominant: the primary support and propulsion come from the hands or arms.",
        "C": "mixed_support: both hands and feet are meaningfully used as supports.",
        "D": "uncertain: the visible evidence is split, hidden, or unclear.",
    }
    result = request_choice_decisions(
        base_url=base_url,
        model=model,
        frame_paths=frame_paths,
        state={
            "purpose": "Classify which body region primarily supports and propels the movement.",
            "exerciseName": exercise_name or "unknown",
            "limits": [
                "Judge the supplied movement frames, not the exercise name alone.",
                "Use uncertain when the visible evidence is split, hidden, or unclear.",
            ],
        },
        questions={
            "supportDominance": choice_question(
                instructions=(
                    "Which category best describes the movement's primary support and propulsion "
                    "in the supplied frames?"
                ),
                options=options,
            )
        },
        timeout_seconds=timeout_seconds,
    )
    decision = result["decisions"]["supportDominance"]
    choice = decision["choice"]
    accepted = decision["confidence"] >= CLEF_SUPPORT_DOMINANCE_CONFIDENCE_THRESHOLD and choice != "D"
    label = {"A": "foot_dominant", "B": "hand_dominant", "C": "mixed_support"}.get(choice)
    if not accepted:
        label = "uncertain"
    return {
        "supportDominance": label,
        "confidence": decision["confidence"],
        "uncertain": not accepted,
        "rawSystemOneResponse": result["rawSystemOneResponse"],
    }


def request_endpoint_posture_observation(
    *,
    base_url: str,
    model: str,
    frame_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    option_sets = {
        "supportMode": {
            "A": "standing",
            "B": "kneeling",
            "C": "seated",
            "D": "lying",
            "E": "hanging",
            "F": "unknown because the posture is hidden or ambiguous",
        },
        "kneeState": {
            "A": "extended (straight)",
            "B": "flexed",
            "C": "deep_flexion",
            "D": "unknown because the knees are hidden or ambiguous",
        },
        "torsoOrientation": {
            "A": "upright",
            "B": "hinged",
            "C": "horizontal",
            "D": "unknown because the torso is hidden or ambiguous",
        },
        "handHeight": {
            "A": "above_head",
            "B": "shoulder_chest",
            "C": "hip",
            "D": "below_hips",
            "E": "unknown because the hands are hidden or ambiguous",
        },
        "stance": {
            "A": "narrow",
            "B": "shoulder_width",
            "C": "wide",
            "D": "split",
            "E": "unknown because the stance is hidden or ambiguous",
        },
    }
    questions = {
        field: choice_question(
            instructions=(
                f"Observe only the visible {field} in this single image. Do not infer exercise, movement, "
                "or completion. Choose unknown when hidden or ambiguous."
            ),
            options=options,
        )
        for field, options in option_sets.items()
    }
    result = request_choice_decisions(
        base_url=base_url,
        model=model,
        frame_paths=[frame_path],
        state={
            "purpose": "Observe endpoint posture in a single source image.",
            "limits": [
                "This is one endpoint image only; do not infer movement or completion.",
                "Do not use an exercise target or expected posture.",
                "Choose unknown for every hidden or ambiguous feature.",
            ],
        },
        questions=questions,
        timeout_seconds=timeout_seconds,
    )
    observations: dict[str, Any] = {}
    confidences: dict[str, float] = {}
    for field, options in option_sets.items():
        decision = result["decisions"][field]
        confidences[field] = decision["confidence"]
        answer_label = decision["choice"]
        observation = options[answer_label].split(" because the ", 1)[0].split(" (", 1)[0]
        if decision["confidence"] < CLEF_ENDPOINT_OBSERVATION_CONFIDENCE_THRESHOLD:
            observation = "unknown"
        observations[field] = observation
    return {
        "observations": observations,
        "confidences": confidences,
        "rawSystemOneResponse": result["rawSystemOneResponse"],
    }


def _images_as_data_urls(frame_paths: list[Path]) -> list[str]:
    if not frame_paths:
        raise ValueError("Clef image decisions require at least one image.")
    image_data_urls: list[str] = []
    for path in frame_paths:
        if not path.is_file():
            raise FileNotFoundError(f"Clef review image does not exist: {path}")
        mime_type = "image/png" if path.suffix.casefold() == ".png" else "image/jpeg"
        image_data_urls.append(
            f"data:{mime_type};base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii")
        )
    return image_data_urls


def request_final_preview_review(
    *,
    base_url: str,
    model: str,
    frame_paths: list[Path],
    sampled_frame_indices: list[int],
    timeout_seconds: float,
) -> dict[str, Any]:
    request_payload = build_final_preview_review_request(
        model=model,
        frame_paths=frame_paths,
        sampled_frame_indices=sampled_frame_indices,
    )
    endpoint = f"{base_url.rstrip('/')}/v1/systemone"
    with httpx.Client(timeout=max(1.0, float(timeout_seconds))) as client:
        response = client.post(endpoint, json=request_payload)
    if response.status_code >= 400:
        body = response.text.strip()
        if len(body) > 1200:
            body = body[:1200] + "...[truncated]"
        raise RuntimeError(
            f"Clef SystemOne request failed ({response.status_code}) at {endpoint}: {body}"
        )
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise ValueError("Clef SystemOne response is missing its answers object.")

    decisions: dict[str, dict[str, float]] = {}
    for question_id in _FINAL_REVIEW_QUESTIONS:
        answer = payload["answers"].get(question_id)
        if not isinstance(answer, dict):
            raise ValueError(f"Clef SystemOne response is missing answer {question_id!r}.")
        probability_true = answer.get("noul")
        if (
            isinstance(probability_true, bool)
            or not isinstance(probability_true, (int, float))
            or not math.isfinite(float(probability_true))
            or not 0.0 <= float(probability_true) <= 1.0
        ):
            raise ValueError(f"Clef SystemOne answer {question_id!r} has an invalid probability.")
        probability_true = float(probability_true)
        decisions[question_id] = {
            "probabilityTrue": probability_true,
            "probabilityFalse": 1.0 - probability_true,
        }

    findings = _findings_from_decisions(decisions)
    return {
        "advisoryOnly": True,
        "status": "completed",
        "backend": "clef_flash_systemone",
        "reviewPolicyVersion": CLEF_FINAL_REVIEW_POLICY_VERSION,
        "findingThreshold": CLEF_FINAL_REVIEW_FINDING_THRESHOLD,
        "findings": findings,
        "note": (
            "Typed Clef probabilities summarize the complete preview and do not localize a finding "
            "to individual frames. This review is advisory only."
        ),
        "typedDecisions": decisions,
        "rawSystemOneResponse": payload,
    }


def request_final_preview_review_with_managed_server(
    *,
    base_url: str,
    model: str,
    frame_paths: list[Path],
    sampled_frame_indices: list[int],
    timeout_seconds: float,
    caption_source: Any = None,
    exclusive_runner: Callable[[Callable[[], Any]], Any] | None = None,
    conflicting_base_urls: tuple[str | None, ...] = (),
    startup_timeout_seconds: float = _MANAGED_SERVER_STARTUP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Start Clef only for this review and release its GPU before returning."""
    return run_clef_visual_decision_exclusively(
        base_url=base_url,
        caption_source=caption_source,
        exclusive_runner=exclusive_runner,
        conflicting_base_urls=conflicting_base_urls,
        startup_timeout_seconds=startup_timeout_seconds,
        operation=lambda: request_final_preview_review(
            base_url=base_url,
            model=model,
            frame_paths=frame_paths,
            sampled_frame_indices=sampled_frame_indices,
            timeout_seconds=timeout_seconds,
        ),
    )


def run_clef_visual_decision_exclusively(
    *,
    base_url: str,
    operation: Callable[[], Any],
    caption_source: Any = None,
    exclusive_runner: Callable[[Callable[[], Any]], Any] | None = None,
    conflicting_base_urls: tuple[str | None, ...] = (),
    startup_timeout_seconds: float = _MANAGED_SERVER_STARTUP_TIMEOUT_SECONDS,
) -> Any:
    """Run one or more Clef requests while Qwen is quiesced and Clef owns the GPU."""
    endpoint = _local_server_endpoint(base_url)
    active_endpoint = _ACTIVE_MANAGED_CLEF_ENDPOINT.get()
    if active_endpoint is not None:
        if endpoint != active_endpoint:
            raise RuntimeError(
                "A managed Clef decision cannot switch endpoints while its GPU lease is active."
            )
        return operation()

    resolved_runner = exclusive_runner or _exclusive_runner_from_source(caption_source)

    def managed_operation() -> Any:
        return _run_with_managed_clef_server(
            base_url=base_url,
            operation=operation,
            conflicting_base_urls=(
                *conflicting_base_urls,
                *_local_base_urls_from_source(caption_source),
            ),
            startup_timeout_seconds=startup_timeout_seconds,
        )

    return resolved_runner(managed_operation) if resolved_runner is not None else managed_operation()


def _run_with_managed_clef_server(
    *,
    base_url: str,
    operation: Callable[[], Any],
    conflicting_base_urls: tuple[str | None, ...],
    startup_timeout_seconds: float,
) -> Any:
    endpoint = _local_server_endpoint(base_url)
    with _MANAGED_SERVER_LOCK:
        endpoints_to_check = {endpoint}
        endpoints_to_check.update(
            candidate
            for candidate in (_local_server_endpoint_or_none(url) for url in conflicting_base_urls)
            if candidate is not None
        )

        def require_endpoints_available() -> None:
            for candidate in endpoints_to_check:
                if _endpoint_is_responding(candidate):
                    if candidate == endpoint:
                        raise RuntimeError(
                            f"Clef endpoint {base_url} is already serving. Refusing to reuse an "
                            "unmanaged process because it may remain GPU-resident after this decision."
                        )
                    raise RuntimeError(
                        f"A conflicting local model endpoint is already serving at {candidate}. "
                        "Release it through its owner before starting the Clef decision."
                    )

        require_endpoints_available()
        with GlobalGpuLock(stage="clef_flash_systemone"):
            require_endpoints_available()
            server_exe, model_path, mmproj_path = _managed_runtime_files()
            server_args = [
                str(server_exe),
                "-m", str(model_path),
                "--mmproj", str(mmproj_path),
                "--host", "127.0.0.1",
                "--port", str(endpoint[1]),
                "--ctx-size", "4096",
                "--parallel", "1",
                "--batch-size", str(_CLEF_SERVER_BATCH_SIZE),
                "--ubatch-size", str(_CLEF_SERVER_UBATCH_SIZE),
                "--n-gpu-layers", "99",
                "--image-min-tokens", "1024",
                "--image-max-tokens", "1024",
                "--mtmd-batch-max-tokens", "1024",
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as server_log:
                process = subprocess.Popen(
                    server_args,
                    cwd=str(server_exe.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=server_log,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                try:
                    _wait_for_managed_server(
                        process,
                        base_url=base_url,
                        server_log=server_log,
                        timeout_seconds=startup_timeout_seconds,
                    )
                    active_endpoint_token = _ACTIVE_MANAGED_CLEF_ENDPOINT.set(endpoint)
                    try:
                        return operation()
                    finally:
                        _ACTIVE_MANAGED_CLEF_ENDPOINT.reset(active_endpoint_token)
                finally:
                    _stop_managed_server(process)


def _exclusive_runner_from_source(source: Any) -> Callable[[Callable[[], Any]], Any] | None:
    pending = [source]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))
        owner = getattr(current, "__self__", None)
        for candidate in (current, owner):
            runner = getattr(candidate, "run_without_llama_overlap", None)
            if callable(runner):
                return runner
        for attribute in ("_caption_images", "caption_images", "recovery_callback"):
            nested = getattr(current, attribute, None)
            if (
                nested is not None
                and nested is not current
                and getattr(nested, "__self__", None) is not current
            ):
                pending.append(nested)
        if owner is not None:
            pending.append(owner)
    return None


def _local_base_urls_from_source(source: Any) -> tuple[str, ...]:
    pending = [source]
    visited: set[int] = set()
    base_urls: list[str] = []
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))
        owner = getattr(current, "__self__", None)
        for candidate in (current, owner):
            settings = getattr(candidate, "settings", None)
            url = getattr(settings, "llama_cpp_base_url", None)
            if url:
                base_urls.append(str(url))
            url = getattr(candidate, "base_url", None)
            if url:
                base_urls.append(str(url))
        for attribute in ("_caption_images", "caption_images", "recovery_callback"):
            nested = getattr(current, attribute, None)
            if (
                nested is not None
                and nested is not current
                and getattr(nested, "__self__", None) is not current
            ):
                pending.append(nested)
        if owner is not None:
            pending.append(owner)
    return tuple(dict.fromkeys(base_urls))


def _managed_runtime_files() -> tuple[Path, Path, Path]:
    workspace_root = Path(__file__).resolve().parents[1]
    runtime_root = workspace_root / "build" / "clef_runtime"
    server_exe = runtime_root / "llama.cpp" / "b11433" / "llama-server.exe"
    model_path = runtime_root / "hf-model" / "Clef-Flash-Q4_K_M.gguf"
    mmproj_path = runtime_root / "hf-model" / "mmproj-Clef-Flash-BF16.gguf"
    missing = [path for path in (server_exe, model_path, mmproj_path) if not path.is_file()]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            "Managed Clef decisions require the isolated runtime files. "
            f"Missing: {missing_text}. Run scripts/install_clef_llama_cpp.ps1 first."
        )
    return server_exe, model_path, mmproj_path


def _local_server_endpoint(base_url: str) -> tuple[str, int]:
    endpoint = _local_server_endpoint_or_none(base_url)
    if endpoint is None:
        raise ValueError(
            "Managed Clef review only starts a server on localhost; "
            f"received base URL {base_url!r}."
        )
    return endpoint


def _local_server_endpoint_or_none(base_url: str | None) -> tuple[str, int] | None:
    if not base_url:
        return None
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None
    if (
        parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"Expected a local model base URL without a path: {base_url!r}.")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise ValueError(f"Invalid model endpoint URL: {base_url!r}.") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid model endpoint port in {base_url!r}.")
    return parsed.hostname, port


def _endpoint_is_responding(endpoint: tuple[str, int]) -> bool:
    base_url = f"http://{endpoint[0]}:{endpoint[1]}"
    try:
        with httpx.Client(timeout=0.5) as client:
            client.get(f"{base_url}/health")
        return True
    except httpx.RequestError:
        return False


def _wait_for_managed_server(
    process: subprocess.Popen[str],
    *,
    base_url: str,
    server_log,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    health_url = f"{base_url.rstrip('/')}/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            server_log.flush()
            server_log.seek(0)
            details = server_log.read()[-4000:].strip()
            raise RuntimeError(
                f"Managed Clef server exited with code {process.returncode} before becoming ready."
                + (f" Server output: {details}" if details else "")
            )
        try:
            with httpx.Client(timeout=0.75) as client:
                response = client.get(health_url)
            if response.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.25)
    raise TimeoutError(
        f"Managed Clef server did not become ready at {health_url} "
        f"within {timeout_seconds:.0f} seconds."
    )


def _stop_managed_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            return
        process.wait(timeout=5.0)


def _findings_from_decisions(
    decisions: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    issue_definitions = (
        ("subject_readable", "readability", False, "The complete preview may be difficult to read."),
        (
            "movement_recognizable",
            "recognizability",
            False,
            "The broad movement may not be visually recognizable from the sampled poses.",
        ),
        (
            "obvious_mesh_or_display_defect",
            "mesh",
            True,
            "The complete preview may contain a visible mesh or display defect.",
        ),
    )
    findings: list[dict[str, Any]] = []
    for question_id, kind, issue_is_true, observation in issue_definitions:
        decision = decisions[question_id]
        issue_probability = decision["probabilityTrue" if issue_is_true else "probabilityFalse"]
        if issue_probability < CLEF_FINAL_REVIEW_FINDING_THRESHOLD:
            continue
        findings.append(
            {
                "kind": kind,
                "frameIndices": [],
                "observation": observation,
                "issueProbability": issue_probability,
                "localization": "whole_preview",
            }
        )
    return findings
