from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

from exercise_motion_pkg.wham_runner import DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY
from exercise_motion_pkg.video_utils import read_basic_video_metadata, trim_video
from exercise_motion_pkg.youtube import download_youtube_preview, sanitize_video_for_processing

MIN_TRIM_DURATION_SECONDS = 0.25


@dataclass(frozen=True)
class TrimSelectorRequest:
    exercise_slug: str
    workspace: Path
    youtube_url: str | None = None
    video_path: Path | None = None
    youtube_cookies: Path | None = None
    run_wham_on_write: bool = False
    generation_workspace: Path = Path("build/exercise_motion")
    wham_repo_path: Path = Path("C:\\Users\\gabri\\Downloads\\WHAM")
    body_model_root: Path = Path("C:\\Users\\gabri\\Downloads\\WHAM\\dataset\\body_models")
    wham_python_command: str = "python"
    wham_estimate_local_only: bool = DEFAULT_WHAM_ESTIMATE_LOCAL_ONLY
    wham_run_smplify: bool = True
    motion_tuning_enabled: bool = True
    dominant_chain_ratio: float = 0.65
    non_dominant_damping: float = 1.0
    non_dominant_radius_scale: float = 1.0
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass(frozen=True)
class TrimSelectorSession:
    root_dir: Path
    source_video_path: Path
    selected_video_path: Path
    selection_json_path: Path
    exercise_slug: str
    youtube_url: str | None
    run_wham_on_write: bool
    generation_workspace: Path
    wham_repo_path: Path
    body_model_root: Path
    wham_python_command: str
    wham_estimate_local_only: bool
    wham_run_smplify: bool
    motion_tuning_enabled: bool
    dominant_chain_ratio: float
    non_dominant_damping: float
    non_dominant_radius_scale: float


def run_trim_selector(request: TrimSelectorRequest) -> None:
    session = prepare_trim_selector_session(request)
    handler = build_trim_selector_handler(session)
    server = ThreadingHTTPServer((request.host, request.port), handler)
    url = f"http://{request.host}:{request.port}/"
    print(f"Trim selector: {url}")
    print(f"Source video: {session.source_video_path.resolve()}")
    print(f"Selected output: {session.selected_video_path.resolve()}")
    print("Press Ctrl+C to stop the trim selector server.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Trim selector stopped.")
    finally:
        server.server_close()


def prepare_trim_selector_session(request: TrimSelectorRequest) -> TrimSelectorSession:
    root_dir = request.workspace.expanduser().resolve() / request.exercise_slug
    input_dir = root_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    if request.youtube_url:
        source_video_path = download_youtube_preview(
            request.youtube_url,
            input_dir,
        )
    elif request.video_path is not None:
        source = request.video_path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input video not found: {source}")
        copied_path = input_dir / source.name
        if copied_path.resolve() != source:
            shutil.copy2(source, copied_path)
        source_video_path = sanitize_video_for_processing(copied_path)
    else:
        raise ValueError("Either youtube_url or video_path must be provided.")

    return TrimSelectorSession(
        root_dir=root_dir,
        source_video_path=source_video_path,
        selected_video_path=input_dir / "selected_segment.mp4",
        selection_json_path=root_dir / "trim_selection.json",
        exercise_slug=request.exercise_slug,
        youtube_url=request.youtube_url,
        run_wham_on_write=request.run_wham_on_write,
        generation_workspace=request.generation_workspace.expanduser().resolve(),
        wham_repo_path=request.wham_repo_path.expanduser().resolve(),
        body_model_root=request.body_model_root.expanduser().resolve(),
        wham_python_command=request.wham_python_command,
        wham_estimate_local_only=request.wham_estimate_local_only,
        wham_run_smplify=request.wham_run_smplify,
        motion_tuning_enabled=request.motion_tuning_enabled,
        dominant_chain_ratio=request.dominant_chain_ratio,
        non_dominant_damping=request.non_dominant_damping,
        non_dominant_radius_scale=request.non_dominant_radius_scale,
    )


def build_trim_selector_handler(session: TrimSelectorSession) -> type[BaseHTTPRequestHandler]:
    wham_state: dict[str, object] = {
        "session": session,
        "process": None,
        "pid": None,
        "logPath": None,
        "started": False,
        "returnCode": None,
    }

    class TrimSelectorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request_path = self.path.split("?", 1)[0]
            if request_path in ("/", "/index.html"):
                self._send_html(build_trim_selector_html(session))
                return
            if request_path == "/video":
                self._send_file(session.source_video_path)
                return
            if request_path == "/selection.json":
                if session.selection_json_path.exists():
                    self._send_json(json.loads(session.selection_json_path.read_text(encoding="utf-8")))
                else:
                    self._send_json({})
                return
            if request_path == "/wham-status":
                self._send_json(read_wham_status(wham_state))
                return
            if request_path.startswith("/generated/"):
                generated_path = resolve_generated_artifact_path(session, request_path)
                if generated_path is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(generated_path)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path != "/trim":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            start_seconds = float(payload["startSeconds"])
            end_seconds = float(payload["endSeconds"])
            if start_seconds < 0:
                raise ValueError("startSeconds must be >= 0.")
            if end_seconds <= start_seconds:
                raise ValueError("endSeconds must be greater than startSeconds.")
            if end_seconds - start_seconds < MIN_TRIM_DURATION_SECONDS:
                raise ValueError(f"Selection must be at least {MIN_TRIM_DURATION_SECONDS:.2f} seconds long.")
            run_wham = bool(payload.get("runWham", False))
            run_smplify = bool(payload.get("runSmplify", session.wham_run_smplify))
            motion_tuning_enabled = bool(payload.get("motionTuningEnabled", session.motion_tuning_enabled))
            dominant_chain_ratio = float(payload.get("dominantChainRatio", session.dominant_chain_ratio))
            non_dominant_damping = float(payload.get("nonDominantDamping", session.non_dominant_damping))
            non_dominant_radius_scale = float(payload.get("nonDominantRadiusScale", session.non_dominant_radius_scale))

            output_path = trim_video(
                source_path=session.source_video_path,
                output_path=session.selected_video_path,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
            generate_args = build_generate_command(
                session,
                output_path,
                run_smplify=run_smplify,
                motion_tuning_enabled=motion_tuning_enabled,
                dominant_chain_ratio=dominant_chain_ratio,
                non_dominant_damping=non_dominant_damping,
                non_dominant_radius_scale=non_dominant_radius_scale,
            )
            wham_process = None
            if run_wham:
                wham_process = start_wham_generation(
                    session,
                    output_path,
                    run_smplify=run_smplify,
                    motion_tuning_enabled=motion_tuning_enabled,
                    dominant_chain_ratio=dominant_chain_ratio,
                    non_dominant_damping=non_dominant_damping,
                    non_dominant_radius_scale=non_dominant_radius_scale,
                )
                wham_state.update(
                    {
                        "session": session,
                        "process": wham_process["process"],
                        "pid": wham_process["pid"],
                        "logPath": wham_process["logPath"],
                        "started": True,
                        "returnCode": None,
                        "runSmplify": run_smplify,
                        "motionTuningEnabled": motion_tuning_enabled,
                    }
                )

            selection = {
                "exerciseSlug": session.exercise_slug,
                "youtubeUrl": session.youtube_url,
                "sourceVideoPath": str(session.source_video_path.resolve()),
                "selectedVideoPath": str(output_path.resolve()),
                "startSeconds": start_seconds,
                "endSeconds": end_seconds,
                "durationSeconds": end_seconds - start_seconds,
                "dominantChainRatio": dominant_chain_ratio,
                "nonDominantDamping": non_dominant_damping,
                "nonDominantRadiusScale": non_dominant_radius_scale,
                "generateArgs": generate_args,
                "whamStarted": wham_process is not None,
                "whamRunSmplify": run_smplify if wham_process is not None else None,
                "motionTuningEnabled": motion_tuning_enabled if wham_process is not None else None,
                "whamPid": wham_process["pid"] if wham_process else None,
                "whamLogPath": wham_process["logPath"] if wham_process else None,
                "artifactLinks": build_generated_artifact_links(session),
            }
            session.selection_json_path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
            self._send_json(selection)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: object) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            file_size = path.stat().st_size
            range_header = self.headers.get("Range")
            start = 0
            end = file_size - 1
            status = HTTPStatus.OK
            if range_header and range_header.startswith("bytes="):
                status = HTTPStatus.PARTIAL_CONTENT
                range_value = range_header.removeprefix("bytes=").split(",", 1)[0]
                start_text, _, end_text = range_value.partition("-")
                if start_text:
                    start = int(start_text)
                if end_text:
                    end = min(file_size - 1, int(end_text))
            content_length = max(0, end - start + 1)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(content_length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.end_headers()
            with path.open("rb") as video_file:
                video_file.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = video_file.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    return TrimSelectorHandler


def build_generate_command(
    session: TrimSelectorSession,
    selected_video_path: Path,
    *,
    run_smplify: bool | None = None,
    motion_tuning_enabled: bool | None = None,
    dominant_chain_ratio: float | None = None,
    non_dominant_damping: float | None = None,
    non_dominant_radius_scale: float | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "exercise_motion_pkg.cli",
        "generate",
        "--exercise-slug",
        session.exercise_slug,
        "--workspace",
        str(session.generation_workspace),
        "--video-path",
        str(selected_video_path.resolve()),
        "--wham-repo-path",
        str(session.wham_repo_path),
        "--body-model-root",
        str(session.body_model_root),
        "--wham-python-command",
        session.wham_python_command,
        "--use-wham-docker",
        "--dominant-chain-ratio",
        str(session.dominant_chain_ratio if dominant_chain_ratio is None else dominant_chain_ratio),
        "--non-dominant-damping",
        str(session.non_dominant_damping if non_dominant_damping is None else non_dominant_damping),
        "--non-dominant-radius-scale",
        str(session.non_dominant_radius_scale if non_dominant_radius_scale is None else non_dominant_radius_scale),
    ]
    if session.wham_estimate_local_only:
        command.append("--wham-estimate-local-only")
    should_run_smplify = session.wham_run_smplify if run_smplify is None else run_smplify
    if not should_run_smplify:
        command.append("--skip-wham-smplify")
    should_tune_motion = session.motion_tuning_enabled if motion_tuning_enabled is None else motion_tuning_enabled
    if not should_tune_motion:
        command.append("--skip-motion-tuning")
    return command


def start_wham_generation(
    session: TrimSelectorSession,
    selected_video_path: Path,
    *,
    run_smplify: bool,
    motion_tuning_enabled: bool,
    dominant_chain_ratio: float,
    non_dominant_damping: float,
    non_dominant_radius_scale: float,
) -> dict[str, object]:
    if not session.wham_repo_path.exists():
        raise FileNotFoundError(f"WHAM repo path not found: {session.wham_repo_path}")
    if not session.body_model_root.exists():
        raise FileNotFoundError(f"Body model root not found: {session.body_model_root}")

    logs_dir = session.root_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = logs_dir / f"wham-generate-{timestamp}.log"
    command = build_generate_command(
        session,
        selected_video_path,
        run_smplify=run_smplify,
        motion_tuning_enabled=motion_tuning_enabled,
        dominant_chain_ratio=dominant_chain_ratio,
        non_dominant_damping=non_dominant_damping,
        non_dominant_radius_scale=non_dominant_radius_scale,
    )
    log_file = log_path.open("w", encoding="utf-8")
    log_file.write("Command:\n")
    log_file.write(" ".join(command))
    log_file.write("\n\n")
    log_file.flush()
    process = subprocess.Popen(
        command,
        cwd=session.root_dir.parents[2],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return {
        "process": process,
        "pid": process.pid,
        "logPath": str(log_path.resolve()),
    }


def read_wham_status(wham_state: dict[str, object]) -> dict[str, object]:
    process = wham_state.get("process")
    return_code = None
    if isinstance(process, subprocess.Popen):
        return_code = process.poll()
        wham_state["returnCode"] = return_code
    elif wham_state.get("returnCode") is not None:
        return_code = int(wham_state["returnCode"])

    log_path_value = wham_state.get("logPath")
    log_tail = ""
    if isinstance(log_path_value, str):
        log_tail = read_text_tail(Path(log_path_value), max_chars=12000)

    if not wham_state.get("started"):
        status = "not_started"
    elif return_code is None:
        status = "running"
    elif return_code == 0:
        status = "completed"
    else:
        status = "failed"

    return {
        "status": status,
        "pid": wham_state.get("pid"),
        "returnCode": return_code,
        "logPath": log_path_value,
        "logTail": log_tail,
        "runSmplify": wham_state.get("runSmplify"),
        "motionTuningEnabled": wham_state.get("motionTuningEnabled"),
        "artifactLinks": build_generated_artifact_links_for_state(wham_state),
    }


def read_text_tail(path: Path, *, max_chars: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def build_generated_artifact_links_for_state(wham_state: dict[str, object]) -> dict[str, str]:
    session = wham_state.get("session")
    if isinstance(session, TrimSelectorSession):
        return build_generated_artifact_links(session)
    return {}


def build_generated_artifact_links(session: TrimSelectorSession) -> dict[str, str]:
    return {
        "Preview HTML": "/generated/preview/motion_preview.html",
        "Raw preview HTML": "/generated/preview/motion_preview.raw.html",
        "Cleaned motion JSON": "/generated/cleaned/motion.cleaned.json",
        "Raw motion JSON": "/generated/raw/motion.raw.json",
        "Manifest JSON": "/generated/manifest.json",
        "Wear skeleton JSON": "/generated/wear/skeleton.preview.json",
    }


def resolve_generated_artifact_path(session: TrimSelectorSession, request_path: str) -> Path | None:
    relative_text = unquote(request_path.removeprefix("/generated/"))
    if not relative_text:
        return None
    root = (session.generation_workspace / session.exercise_slug).resolve()
    candidate = (root / relative_text).resolve()
    if root != candidate and root not in candidate.parents:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def build_trim_selector_html(session: TrimSelectorSession) -> str:
    metadata = read_basic_video_metadata(session.source_video_path)
    source_name = session.source_video_path.name
    source_path = str(session.source_video_path.resolve())
    escaped_source_name = json.dumps(source_name)
    escaped_source_path = json.dumps(source_path)
    duration = metadata.duration_seconds
    video_url = f"/video?name={quote(source_name)}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WHAM trim selector - {source_name}</title>
  <style>
    :root {{
      --bg: #f6f4ef;
      --panel: #ffffff;
      --ink: #1e1d1a;
      --muted: #666056;
      --accent: #2457d6;
      --accent-dark: #17398d;
      --line: #d8d3c8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background: var(--bg);
      font-family: "Segoe UI", sans-serif;
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 20px 0;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(1.6rem, 3vw, 2.4rem);
      letter-spacing: -0.03em;
      line-height: 1.05;
    }}
    .subhead {{
      max-width: 760px;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.5;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 18px;
      margin-top: 24px;
    }}
    .video-card, .controls {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
      overflow: hidden;
    }}
    video {{
      display: block;
      width: 100%;
      max-height: 72vh;
      background: #000;
    }}
    .timeline {{
      padding: 16px;
      background: rgba(0, 0, 0, 0.2);
    }}
    .bar {{
      position: relative;
      height: 18px;
      border-radius: 999px;
      background: rgba(244, 239, 226, 0.18);
      overflow: hidden;
    }}
    .range {{
      position: absolute;
      top: 0;
      bottom: 0;
      border-radius: 999px;
      background: linear-gradient(90deg, #f4b05c, var(--accent));
    }}
    .controls {{
      padding: 18px;
      background: var(--panel);
    }}
    .field {{
      display: grid;
      gap: 6px;
      margin: 14px 0;
    }}
    label {{
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    input {{
      width: 100%;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      color: var(--ink);
      background: #fffaf0;
      font: 700 1.05rem ui-monospace, SFMono-Regular, Consolas, monospace;
    }}
    button {{
      width: 100%;
      margin-top: 10px;
      padding: 13px 14px;
      border: 0;
      border-radius: 999px;
      color: #fff9ee;
      background: var(--accent);
      font-weight: 800;
      cursor: pointer;
    }}
    button.secondary {{
      color: var(--accent-dark);
      background: #ead9bd;
    }}
    button:disabled {{
      cursor: wait;
      opacity: 0.62;
    }}
    .button-row {{
      display: grid;
      gap: 8px;
      grid-template-columns: 1fr;
      margin-top: 10px;
    }}
    .readout {{
      margin-top: 14px;
      padding: 12px;
      border-radius: 16px;
      color: var(--ink);
      background: #f7f7f7;
      font: 0.86rem ui-monospace, SFMono-Regular, Consolas, monospace;
      max-height: min(42vh, 520px);
      overflow: auto;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}
    .readout pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .readout details {{
      margin-top: 10px;
    }}
    .readout summary {{
      cursor: pointer;
      font-weight: 800;
    }}
    .log-tail {{
      margin-top: 8px;
      padding: 10px;
      max-height: min(32vh, 420px);
      overflow: auto;
      border-radius: 12px;
      color: #f6f1e7;
      background: #17120d;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .source {{
      margin-top: 12px;
      color: var(--muted);
      font: 0.82rem ui-monospace, SFMono-Regular, Consolas, monospace;
      overflow-wrap: anywhere;
    }}
    @media (max-width: 880px) {{
      .layout {{ grid-template-columns: 1fr; }}
      main {{ width: min(100vw - 18px, 1180px); padding-top: 18px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Pick segment</h1>
    <div class="subhead">Set start/end, preview the loop, then generate.</div>
    <div class="source" id="source"></div>
    <section class="layout">
      <div class="video-card">
        <video id="player" controls preload="metadata" src="{video_url}"></video>
        <div class="timeline"><div class="bar"><div class="range" id="range"></div></div></div>
      </div>
      <aside class="controls">
        <div class="field">
          <label for="current">Current time</label>
          <input id="current" type="number" step="0.001" min="0" value="0.000">
        </div>
        <div class="field">
          <label for="start">Start seconds</label>
          <input id="start" type="number" step="0.001" min="0" value="0.000">
        </div>
        <button class="secondary" id="setStart">Set start from current time</button>
        <div class="field">
          <label for="end">End seconds</label>
          <input id="end" type="number" step="0.001" min="0" value="{duration:.3f}">
        </div>
        <button class="secondary" id="setEnd">Set end from current time</button>
        <button class="secondary" id="jumpStart">Jump to start</button>
        <button class="secondary" id="previewLoop">Preview selected loop</button>
        <div class="button-row">
          <button class="secondary action" data-run-wham="false" data-motion-tuning="false">Write trim only</button>
          <button class="action" data-run-wham="true" data-motion-tuning="false">Generate raw WHAM</button>
          <button class="action" data-run-wham="true" data-motion-tuning="true">Generate tuned motion</button>
        </div>
        <div class="readout" id="status">No trim written yet.</div>
      </aside>
    </section>
  </main>
  <script>
    const player = document.getElementById("player");
    const current = document.getElementById("current");
    const start = document.getElementById("start");
    const end = document.getElementById("end");
    const range = document.getElementById("range");
    const status = document.getElementById("status");
    const sourceName = {escaped_source_name};
    const sourcePath = {escaped_source_path};
    const fallbackDuration = {duration:.6f};
    let loopPreview = false;
    let whamPollTimer = null;

    document.getElementById("source").textContent = `${{sourceName}} | ${{sourcePath}}`;

    function duration() {{
      return Number.isFinite(player.duration) && player.duration > 0 ? player.duration : fallbackDuration;
    }}

    function numberValue(input) {{
      return Number.parseFloat(input.value || "0");
    }}

    function formatSeconds(value) {{
      return Number(value).toFixed(3);
    }}

    function syncRange() {{
      const total = Math.max(duration(), 0.001);
      const left = Math.max(0, Math.min(100, numberValue(start) / total * 100));
      const right = Math.max(left, Math.min(100, numberValue(end) / total * 100));
      range.style.left = `${{left}}%`;
      range.style.width = `${{right - left}}%`;
    }}

    function validateSelection() {{
      const startSeconds = numberValue(start);
      const endSeconds = numberValue(end);
      if (startSeconds < 0 || endSeconds <= startSeconds) {{
        throw new Error("End must be greater than start, and start must be >= 0.");
      }}
      if (endSeconds - startSeconds < {MIN_TRIM_DURATION_SECONDS:.3f}) {{
        throw new Error("Selection is too short. Pick at least {MIN_TRIM_DURATION_SECONDS:.2f} seconds.");
      }}
      return {{ startSeconds, endSeconds }};
    }}

    player.addEventListener("timeupdate", () => {{
      current.value = formatSeconds(player.currentTime);
      if (loopPreview && player.currentTime >= numberValue(end)) {{
        player.currentTime = numberValue(start);
        player.play();
      }}
    }});
    player.addEventListener("loadedmetadata", syncRange);
    current.addEventListener("change", () => {{
      const targetTime = Math.max(0, Math.min(duration(), numberValue(current)));
      player.currentTime = targetTime;
      current.value = formatSeconds(targetTime);
    }});
    start.addEventListener("input", syncRange);
    end.addEventListener("input", syncRange);

    document.getElementById("setStart").addEventListener("click", () => {{
      start.value = formatSeconds(player.currentTime);
      syncRange();
    }});
    document.getElementById("setEnd").addEventListener("click", () => {{
      end.value = formatSeconds(player.currentTime);
      syncRange();
    }});
    document.getElementById("jumpStart").addEventListener("click", () => {{
      player.currentTime = numberValue(start);
    }});
    document.getElementById("previewLoop").addEventListener("click", async () => {{
      validateSelection();
      loopPreview = !loopPreview;
      if (loopPreview) {{
        player.currentTime = numberValue(start);
        await player.play();
      }}
      status.textContent = loopPreview ? "Loop preview enabled." : "Loop preview disabled.";
    }});
    document.querySelectorAll(".action").forEach((button) => {{
      button.addEventListener("click", () => {{
        writeSelection({{
          button,
          runWham: button.dataset.runWham === "true",
          motionTuningEnabled: button.dataset.motionTuning === "true",
        }});
      }});
    }});

    async function writeSelection({{ button, runWham, motionTuningEnabled }}) {{
      try {{
        const selection = validateSelection();
        setActionButtonsDisabled(true);
        button.textContent = "Writing...";
        status.textContent = "Writing trimmed video...";
        const response = await fetch("/trim", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ ...selection, runWham, motionTuningEnabled }}),
        }});
        if (!response.ok) {{
          throw new Error(await response.text());
        }}
        const payload = await response.json();
        const whamText = payload.whamStarted
          ? `\\n\\nWHAM started.\\nPID: ${{payload.whamPid}}\\nLog: ${{payload.whamLogPath}}`
          : "\\n\\nWHAM was not started for this selector session.";
        status.textContent = `Trim written.\\n\\nSelected video:\\n${{payload.selectedVideoPath}}\\n\\nStart: ${{payload.startSeconds.toFixed(3)}}s\\nEnd: ${{payload.endSeconds.toFixed(3)}}s\\nDuration: ${{payload.durationSeconds.toFixed(3)}}s${{whamText}}`;
        if (payload.whamStarted) {{
          requestBrowserNotifications();
          startWhamPolling();
        }}
      }} catch (error) {{
        status.textContent = `Error: ${{error.message || error}}`;
      }} finally {{
        setActionButtonsDisabled(false);
        button.textContent = button.dataset.runWham === "true"
          ? button.dataset.motionTuning === "true"
            ? "Generate tuned motion"
            : "Generate raw WHAM"
          : "Write trim only";
      }}
    }}

    async function refreshWhamStatus() {{
      const response = await fetch("/wham-status");
      const payload = await response.json();
      if (payload.status === "not_started") {{
        return;
      }}
      const header = [
        `WHAM status: ${{payload.status}}`,
        `PID: ${{payload.pid ?? ""}}`,
        `SMPLify: ${{payload.runSmplify ? "yes" : "no"}}`,
        `Motion tuning: ${{payload.motionTuningEnabled ? "on" : "off"}}`,
        `Return code: ${{payload.returnCode ?? ""}}`,
        `Log: ${{payload.logPath ?? ""}}`,
      ].join("\\n");
      status.innerHTML = `<pre>${{escapeHtml(header)}}</pre>${{artifactLinksHtml(payload.artifactLinks, payload.status)}}${{logDetailsHtml(payload.logTail)}}`;
      if (payload.status === "completed" || payload.status === "failed") {{
        notifyWhamFinished(payload.status);
        stopWhamPolling();
      }}
    }}

    function startWhamPolling() {{
      stopWhamPolling();
      refreshWhamStatus().catch((error) => {{
        status.textContent = `Error reading WHAM status: ${{error.message || error}}`;
      }});
      whamPollTimer = window.setInterval(() => {{
        refreshWhamStatus().catch((error) => {{
          status.textContent = `Error reading WHAM status: ${{error.message || error}}`;
          stopWhamPolling();
        }});
      }}, 3000);
    }}

    function stopWhamPolling() {{
      if (whamPollTimer !== null) {{
        window.clearInterval(whamPollTimer);
        whamPollTimer = null;
      }}
    }}

    function setActionButtonsDisabled(disabled) {{
      document.querySelectorAll(".action").forEach((button) => {{
        button.disabled = disabled;
      }});
    }}

    function artifactLinksHtml(links, statusValue) {{
      if (statusValue !== "completed" || !links || typeof links !== "object") {{
        return "";
      }}
      const entries = Object.entries(links);
      if (entries.length === 0) {{
        return "";
      }}
      return `<div><strong>Generated artifacts</strong><br>${{entries.map(([label, href]) => `<a href="${{escapeHtml(href)}}" target="_blank" rel="noreferrer">${{escapeHtml(label)}}</a>`).join("<br>")}}</div>`;
    }}

    function logDetailsHtml(logTail) {{
      if (!logTail) {{
        return "";
      }}
      return `<details open><summary>Log tail</summary><pre class="log-tail">${{escapeHtml(logTail)}}</pre></details>`;
    }}

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}

    function requestBrowserNotifications() {{
      if (!("Notification" in window) || Notification.permission !== "default") {{
        return;
      }}
      Notification.requestPermission().catch(() => {{}});
    }}

    function notifyWhamFinished(statusValue) {{
      if (!("Notification" in window) || Notification.permission !== "granted") {{
        return;
      }}
      new Notification(`WHAM generation ${{statusValue}}`, {{
        body: statusValue === "completed" ? "Preview and JSON artifacts are ready." : "Check the log tail on the selector page.",
      }});
    }}

    startWhamPolling();
    syncRange();
  </script>
</body>
</html>
"""
