from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg.models import MotionClip


RAW_PREVIEW_CHAINS = [
    ["left_foot", "left_ankle", "left_knee", "left_hip", "pelvis", "right_hip", "right_knee", "right_ankle", "right_foot"],
    ["pelvis", "spine1", "spine2", "spine3", "neck", "head"],
    ["neck", "left_collar", "left_shoulder", "left_elbow", "left_wrist", "left_hand"],
    ["neck", "right_collar", "right_shoulder", "right_elbow", "right_wrist", "right_hand"],
]


def write_raw_motion_preview_html(path: Path, clip: MotionClip, *, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": title,
        "fps": clip.fps,
        "frameCount": clip.frame_count,
        "jointNames": clip.joint_names,
        "source": clip.source,
        "metadata": clip.metadata,
        "chains": RAW_PREVIEW_CHAINS,
        "frames": [
            {
                "frameIndex": index,
                "timeSec": frame.time_sec,
                "joints": frame.joints,
            }
            for index, frame in enumerate(clip.frames)
        ],
    }
    payload_json = json.dumps(payload)
    path.write_text(_build_raw_preview_html(payload_json), encoding="utf-8")


def _build_raw_preview_html(payload_json: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Raw WHAM Preview</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #101114;
      --panel: #191c21;
      --ink: #f3f5f7;
      --muted: #aeb6c2;
      --line: #2f3540;
      --accent: #55c2ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    main {{
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    header {{
      display: flex;
      gap: 14px;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .controls {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
    }}
    button,
    select,
    input {{
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #12151a;
      color: var(--ink);
      font: inherit;
    }}
    button {{
      padding: 0 12px;
      cursor: pointer;
    }}
    select {{
      padding: 0 8px;
    }}
    input[type="range"] {{
      width: 140px;
    }}
    .stage {{
      position: relative;
      min-height: 0;
      overflow: hidden;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 100%;
      background: #0b0c0f;
    }}
    .hud {{
      position: absolute;
      left: 12px;
      bottom: 12px;
      display: grid;
      gap: 4px;
      padding: 8px 10px;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 6px;
      background: rgba(8,10,13,0.72);
      color: var(--muted);
      font: 12px Consolas, monospace;
      pointer-events: none;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1 id="title">Raw WHAM Preview</h1>
      <div class="controls">
        <button id="toggle">Pause</button>
        <label>Projection <select id="projection">
          <option value="xy">X/Y</option>
          <option value="xz">X/Z</option>
          <option value="zy">Z/Y</option>
        </select></label>
        <label>Speed <input id="speed" type="range" min="0.1" max="2.5" step="0.1" value="1"></label>
      </div>
    </header>
    <section class="stage">
      <canvas id="canvas"></canvas>
      <div class="hud" id="hud"></div>
    </section>
  </main>
  <script>
    const payload = {payload_json};
    const canvas = document.getElementById("canvas");
    const ctx = canvas.getContext("2d");
    const title = document.getElementById("title");
    const hud = document.getElementById("hud");
    const toggle = document.getElementById("toggle");
    const projection = document.getElementById("projection");
    const speedInput = document.getElementById("speed");
    const frames = Array.isArray(payload.frames) ? payload.frames : [];
    let paused = false;
    let cursor = 0;
    let lastTimestamp = null;

    title.textContent = payload.title || "Raw WHAM Preview";

    function resize() {{
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }}

    function axes() {{
      switch (projection.value) {{
        case "xz": return [0, 2, false];
        case "zy": return [2, 1, true];
        case "xy":
        default: return [0, 1, true];
      }}
    }}

    function boundsForProjection() {{
      const [axisA, axisB] = axes();
      let minA = Infinity;
      let maxA = -Infinity;
      let minB = Infinity;
      let maxB = -Infinity;
      for (const frame of frames) {{
        for (const point of Object.values(frame.joints || {{}})) {{
          if (!Array.isArray(point) || point.length < 3) {{
            continue;
          }}
          minA = Math.min(minA, Number(point[axisA]));
          maxA = Math.max(maxA, Number(point[axisA]));
          minB = Math.min(minB, Number(point[axisB]));
          maxB = Math.max(maxB, Number(point[axisB]));
        }}
      }}
      if (!Number.isFinite(minA) || !Number.isFinite(maxA) || minA === maxA || minB === maxB) {{
        return {{ minA: -1, maxA: 1, minB: -1, maxB: 1 }};
      }}
      return {{ minA, maxA, minB, maxB }};
    }}

    function project(point, bounds, width, height) {{
      const [axisA, axisB, invertB] = axes();
      const padding = 42;
      const spanA = Math.max(1e-6, bounds.maxA - bounds.minA);
      const spanB = Math.max(1e-6, bounds.maxB - bounds.minB);
      const scale = Math.min((width - padding * 2) / spanA, (height - padding * 2) / spanB);
      const centerA = (bounds.minA + bounds.maxA) * 0.5;
      const centerB = (bounds.minB + bounds.maxB) * 0.5;
      const a = (Number(point[axisA]) - centerA) * scale + width * 0.5;
      const bValue = (Number(point[axisB]) - centerB) * scale;
      const b = height * 0.5 + (invertB ? -bValue : bValue);
      return [a, b];
    }}

    function drawChain(frame, chain, bounds, width, height) {{
      let started = false;
      ctx.beginPath();
      for (const jointName of chain) {{
        const point = frame.joints?.[jointName];
        if (!Array.isArray(point) || point.length < 3) {{
          started = false;
          continue;
        }}
        const [x, y] = project(point, bounds, width, height);
        if (!started) {{
          ctx.moveTo(x, y);
          started = true;
        }} else {{
          ctx.lineTo(x, y);
        }}
      }}
      ctx.stroke();
    }}

    function draw() {{
      const width = canvas.clientWidth || 1;
      const height = canvas.clientHeight || 1;
      ctx.clearRect(0, 0, width, height);
      if (frames.length === 0) {{
        return;
      }}
      const frame = frames[Math.max(0, Math.min(frames.length - 1, Math.floor(cursor)))];
      const bounds = boundsForProjection();
      ctx.lineWidth = 5;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#55c2ff";
      for (const chain of payload.chains || []) {{
        drawChain(frame, chain, bounds, width, height);
      }}
      ctx.fillStyle = "#f4f8ff";
      for (const point of Object.values(frame.joints || {{}})) {{
        if (!Array.isArray(point) || point.length < 3) {{
          continue;
        }}
        const [x, y] = project(point, bounds, width, height);
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
      }}
      hud.textContent = [
        `frame ${{frame.frameIndex + 1}} / ${{frames.length}}`,
        `time ${{Number(frame.timeSec || 0).toFixed(3)}}s`,
        `fps ${{Number(payload.fps || 0).toFixed(3)}}`,
        `space ${{payload.source?.coordinateSpace || payload.metadata?.wham?.coordinateSpace || "unknown"}}`,
      ].join("\\n");
    }}

    function step(timestamp) {{
      if (lastTimestamp == null) {{
        lastTimestamp = timestamp;
      }}
      const elapsed = Math.max(0, timestamp - lastTimestamp) / 1000;
      lastTimestamp = timestamp;
      if (!paused && frames.length > 0) {{
        cursor = (cursor + elapsed * Number(payload.fps || 30) * Number(speedInput.value || 1)) % frames.length;
        draw();
      }}
      window.requestAnimationFrame(step);
    }}

    toggle.addEventListener("click", () => {{
      paused = !paused;
      toggle.textContent = paused ? "Play" : "Pause";
    }});
    projection.addEventListener("change", draw);
    speedInput.addEventListener("input", draw);
    window.addEventListener("resize", resize);
    resize();
    window.requestAnimationFrame(step);
  </script>
</body>
</html>
"""
