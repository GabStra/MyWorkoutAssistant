from __future__ import annotations

import argparse
import json
from pathlib import Path

from exercise_motion_pkg.bake_and_rank import (
    DEFAULT_FALLBACK_CANDIDATES,
    DEFAULT_MAX_REVIEW_WINDOWS,
    DEFAULT_REVIEW_FRAMES,
    BakeAndRankRequest,
    run_bake_and_rank_pipeline,
    run_bake_and_rank_reselection,
)
from exercise_motion_pkg.ground import embed_ground_metadata_in_clip, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline
from exercise_motion_pkg.physics_bundle import PhysicsBundleConfig, write_physics_bundle
from exercise_motion_pkg.physics_sim import PhysicsSimulationConfig, run_physics_simulation
from exercise_motion_pkg.preview import write_preview_debug_json, write_preview_html, write_wear_skeleton_json
from exercise_motion_pkg.raw_preview import write_raw_motion_preview_html
from exercise_motion_pkg.spinepose_wham_correction import apply_spinepose_to_wham_pkl
from exercise_motion_pkg.trim_selector import TrimSelectorRequest, run_trim_selector
from exercise_motion_pkg.video_utils import trim_video
from exercise_motion_pkg.youtube import YouTubeRankingSettings, discover_and_rank_youtube_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exercise-motion",
        description="Generate a cleaned, previewable exercise motion clip from a video and WHAM output.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Run the video -> WHAM -> cleanup -> preview pipeline.")
    generate.add_argument("--exercise-slug", required=True, help="Stable slug for the output workspace.")
    generate.add_argument(
        "--workspace",
        default="build/exercise_motion",
        help="Workspace root for generated artifacts. Default: build/exercise_motion",
    )
    source_group = generate.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--youtube-url", help="YouTube URL to download and process.")
    source_group.add_argument("--video-path", help="Existing local video path to process.")
    generate.add_argument(
        "--wham-repo-path",
        help="Local WHAM checkout prepared for inference. Required unless --normalized-motion-json is supplied.",
    )
    generate.add_argument(
        "--wham-results-pkl",
        help="Existing WHAM wham_output.pkl path inside or outside the WHAM repo. If supplied, local inference is skipped.",
    )
    generate.add_argument(
        "--no-reuse-wham-cache",
        action="store_true",
        help="Run WHAM even when raw/wham/<input-video-stem>/wham_output.pkl already exists.",
    )
    generate.add_argument(
        "--body-model-root",
        help="Directory containing the SMPL body model folders used to reconstruct joints from WHAM output.",
    )
    generate.add_argument(
        "--wham-python-command",
        default="python",
        help="Python interpreter or command to run WHAM and the WHAM-backed conversion stage.",
    )
    generate.add_argument(
        "--use-wham-docker",
        action="store_true",
        help="Run WHAM through Docker instead of the local Python environment.",
    )
    generate.add_argument(
        "--wham-docker-image",
        default="yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
        help="Docker image to use when --use-wham-docker is set.",
    )
    generate.add_argument("--wham-docker-gpus", default="all")
    generate.add_argument("--wham-docker-shm-size", default="8g")
    generate.add_argument(
        "--wham-estimate-local-only",
        action="store_true",
        help="Skip SLAM and only produce camera-space motion from WHAM.",
    )
    generate.add_argument(
        "--skip-wham-smplify",
        action="store_true",
        help="Skip WHAM's Temporal SMPLify refinement. SMPLify runs by default.",
    )
    generate.add_argument(
        "--skip-motion-tuning",
        action="store_true",
        help="Pass raw camera-space WHAM motion through as the final artifact without cleanup, grounding, or structural tuning.",
    )
    generate.add_argument(
        "--normalized-motion-json",
        help="Existing normalized motion JSON. If supplied, WHAM execution and conversion are skipped.",
    )
    generate.add_argument("--one-euro-min-cutoff", type=float, default=0.6)
    generate.add_argument("--one-euro-beta", type=float, default=0.05)
    generate.add_argument("--one-euro-derivative-cutoff", type=float, default=1.0)
    generate.add_argument("--motion-threshold", type=float, default=0.015)
    generate.add_argument("--padding-frames", type=int, default=3)
    generate.add_argument(
        "--dominant-chain-ratio",
        type=float,
        default=0.65,
        help="Motion ratio used to decide which body groups are dominant. Lower preserves more torso/limb motion.",
    )
    generate.add_argument(
        "--non-dominant-damping",
        type=float,
        default=1.0,
        help="How strongly low-importance motion is damped, from 0 to 1.",
    )
    generate.add_argument(
        "--non-dominant-radius-scale",
        type=float,
        default=1.0,
        help="Scale for allowed residual motion on non-dominant joints.",
    )
    generate.add_argument(
        "--source-start-seconds",
        "--segment-start-seconds",
        type=float,
        dest="source_start_seconds",
        help="Start second for explicit source trimming. Requires --source-end-seconds (or --segment-end-seconds).",
    )
    generate.add_argument(
        "--source-end-seconds",
        "--segment-end-seconds",
        type=float,
        dest="source_end_seconds",
        help="End second for explicit source trimming. Requires --source-start-seconds (or --segment-start-seconds).",
    )
    generate.add_argument(
        "--youtube-cookies",
        "--youtube-cookies-path",
        type=Path,
        help="Path to a YouTube cookies.txt file (helps with bot-protected videos).",
    )

    preview = subparsers.add_parser("preview", help="Build a standalone HTML preview from a normalized motion JSON.")
    preview.add_argument("--motion-json", required=True)
    preview.add_argument("--out-html", required=True)
    preview.add_argument("--title", default="exercise-motion-preview")
    preview.add_argument("--render-debug-json", help="Optional JSON export of the exact joint coordinates used by the preview renderer.")
    preview.add_argument("--wear-skeleton-json", help="Optional Wear-ready JSON export of the exact baked preview skeleton.")
    preview.add_argument("--wear-skeleton-loop-index", type=int, help="Loop index to bake for --wear-skeleton-json. Use -1 for full clip. Defaults to first detected loop.")
    preview.add_argument("--wear-skeleton-lock-y-drift", action="store_true", help="Also lock root Y drift in the baked Wear skeleton.")

    raw_preview = subparsers.add_parser(
        "raw-preview",
        help="Build a minimal no-tuning HTML viewer directly from a motion JSON.",
    )
    raw_preview.add_argument("--motion-json", required=True)
    raw_preview.add_argument("--out-html", required=True)
    raw_preview.add_argument("--title", default="raw-wham-preview")

    wear_skeleton = subparsers.add_parser(
        "wear-skeleton",
        help="Export the exact baked preview skeleton coordinates as Wear-ready JSON.",
    )
    wear_skeleton.add_argument("--motion-json", required=True)
    wear_skeleton.add_argument("--out-json", required=True)
    wear_skeleton.add_argument("--title", default="exercise-motion-preview")
    wear_skeleton.add_argument("--loop-index", type=int, help="Loop index to bake. Use -1 for full clip. Defaults to first detected loop.")
    wear_skeleton.add_argument("--lock-y-drift", action="store_true", help="Also lock root Y drift in the baked Wear skeleton.")

    detect = subparsers.add_parser("detect-segment", help="Use a local multimodal model to detect the exercise span in a video.")
    detect.add_argument("--video-path", required=True)
    detect.add_argument("--out-json", required=True)
    detect.add_argument("--frames-dir", required=True)
    detect.add_argument("--exercise-name")
    detect.add_argument("--llama-cpp-command")
    detect.add_argument("--llama-cpp-model")
    detect.add_argument("--llama-cpp-mmproj")
    detect.add_argument("--llama-cpp-backend", default="gpu")
    detect.add_argument("--llama-cpp-n-predict", type=int, default=768)
    detect.add_argument("--llama-cpp-image-min-tokens", type=int)
    detect.add_argument("--llama-cpp-image-max-tokens", type=int)
    detect.add_argument("--base-url", default="http://127.0.0.1:8090")
    detect.add_argument("--model", default="local-vision")
    detect.add_argument("--litert-command")
    detect.add_argument("--litert-backend", default="gpu")
    detect.add_argument("--window-seconds", type=float, default=5.0)
    detect.add_argument("--overlap-seconds", type=float, default=2.5)
    detect.add_argument("--frames-per-window", type=int, default=20)
    detect.add_argument("--max-frame-width", type=int, default=640)
    detect.add_argument("--merge-gap-seconds", type=float, default=2.0)
    detect.add_argument("--confidence-threshold", type=float, default=0.45)
    detect.add_argument("--min-segment-seconds", type=float, default=2.0)
    detect.add_argument("--max-segment-seconds", type=float, default=20.0)
    detect.add_argument("--refinement-window-seconds", type=float, default=2.0)
    detect.add_argument("--refinement-overlap-seconds", type=float, default=1.0)
    detect.add_argument("--refinement-frames-per-window", type=int, default=0)
    detect.add_argument("--refinement-padding-seconds", type=float, default=1.0)
    detect.add_argument("--fast-segment-profile", action="store_true", help="Enable a latency-first profile for faster candidate discovery.")
    detect.add_argument("--classification-workers", type=int, default=3)

    youtube_search = subparsers.add_parser(
        "find-youtube-videos",
        help="Find and rank YouTube candidate videos for exercises in a workout plan JSON.",
    )
    youtube_search.add_argument("--workout-plan-json", required=True)
    youtube_search.add_argument("--out-json", required=True)
    youtube_search.add_argument("--results-per-query", type=int, default=10)
    youtube_search.add_argument("--max-candidates", type=int, default=8)
    youtube_search.add_argument("--metadata-candidate-pool-size", type=int)
    youtube_search.add_argument("--min-duration-seconds", type=int, default=20)
    youtube_search.add_argument("--max-duration-seconds", type=int, default=120)
    youtube_search.add_argument(
        "--use-deepseek-query-planner",
        action="store_true",
        help="Ask DeepSeek for extra YouTube search queries before yt-dlp search. Uses DEEPSEEK_API_KEY unless --deepseek-api-key is supplied.",
    )
    youtube_search.add_argument("--deepseek-api-key")
    youtube_search.add_argument("--deepseek-base-url", default="https://api.deepseek.com")
    youtube_search.add_argument("--deepseek-model", default="deepseek-v4-flash")
    youtube_search.add_argument("--deepseek-max-queries", type=int, default=4)
    youtube_search.add_argument("--deepseek-timeout-seconds", type=float, default=60.0)
    youtube_search.add_argument("--rank-with-litert", action="store_true")
    youtube_search.add_argument("--rank-with-vision", dest="rank_with_litert", action="store_true")
    youtube_search.add_argument("--vision-candidates-per-exercise", type=int, default=8)
    youtube_search.add_argument("--vision-frames-per-candidate", type=int, default=6)
    youtube_search.add_argument("--vision-chunk-seconds", type=float)
    youtube_search.add_argument("--vision-chunk-overlap-seconds", type=float)
    youtube_search.add_argument("--vision-max-chunks-per-candidate", type=int, default=5)
    youtube_search.add_argument("--vision-download-workers", type=int, default=3)
    youtube_search.add_argument("--vision-llm-workers", type=int, default=3)
    youtube_search.add_argument("--litert-command")
    youtube_search.add_argument("--litert-backend", default="gpu")
    youtube_search.add_argument("--vision-model", default="gemma-4-E4B-it")
    youtube_search.add_argument("--llama-cpp-base-url", default="http://127.0.0.1:8090")
    youtube_search.add_argument("--no-llama-cpp", action="store_true")
    youtube_search.add_argument("--llama-cpp-model", default="C:\\Users\\gabri\\Downloads\\Qwen3VL-8B-Instruct-Q4_K_M.gguf")
    youtube_search.add_argument("--llama-cpp-command")
    youtube_search.add_argument("--llama-cpp-server-command")
    youtube_search.add_argument("--llama-cpp-mmproj", default="C:\\Users\\gabri\\Downloads\\mmproj-Qwen3VL-8B-Instruct-F16.gguf")
    youtube_search.add_argument("--llama-cpp-backend", default="gpu")
    youtube_search.add_argument("--llama-cpp-n-predict", type=int, default=768)
    youtube_search.add_argument("--llama-cpp-image-min-tokens", type=int)
    youtube_search.add_argument("--llama-cpp-image-max-tokens", type=int)
    youtube_search.add_argument("--no-llama-cpp-auto-start-server", action="store_true")
    youtube_search.add_argument("--llama-cpp-server-startup-timeout-seconds", type=float, default=180.0)
    youtube_search.add_argument("--llama-cpp-request-timeout-seconds", type=float, default=90.0)
    youtube_search.add_argument("--no-litert-server", action="store_true")
    youtube_search.add_argument("--litert-server-url", default="http://127.0.0.1:9379")
    youtube_search.add_argument("--litert-server-port", type=int, default=9379)
    youtube_search.add_argument("--keep-litert-server", action="store_true")
    youtube_search.add_argument("--vision-early-stop-score", type=float, default=0.95)
    youtube_search.add_argument("--include-disabled", action="store_true")

    bake_and_rank = subparsers.add_parser(
        "bake-and-rank",
        help="Run WHAM, bake detected preview loops, rank review videos, and select the best Wear skeleton.",
    )
    bake_and_rank.add_argument("--candidates-json", required=True)
    bake_and_rank.add_argument("--fallback-candidates", type=int, default=DEFAULT_FALLBACK_CANDIDATES)
    bake_and_rank.add_argument(
        "--candidate-workers",
        type=int,
        default=1,
        help="Maximum candidates to process concurrently before final selection.",
    )
    bake_and_rank.add_argument(
        "--workspace",
        default="build/exercise_motion",
        help="Workspace root for generated artifacts. Default: build/exercise_motion",
    )
    bake_and_rank.add_argument("--wham-repo-path", required=True)
    bake_and_rank.add_argument("--body-model-root", required=True)
    bake_and_rank.add_argument("--wham-python", default="python")
    bake_and_rank.add_argument(
        "--no-reuse-wham-cache",
        action="store_true",
        help="Run WHAM even when raw/wham/<input-video-stem>/wham_output.pkl already exists.",
    )
    bake_and_rank.add_argument("--use-wham-docker", action="store_true")
    bake_and_rank.add_argument(
        "--wham-docker-image",
        default="yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    )
    bake_and_rank.add_argument("--wham-docker-gpus", default="all")
    bake_and_rank.add_argument("--wham-docker-shm-size", default="8g")
    bake_and_rank.add_argument("--estimate-local-only", action="store_true")
    bake_and_rank.add_argument(
        "--skip-smplify",
        action="store_true",
        help="Skip WHAM's Temporal SMPLify refinement. SMPLify runs by default.",
    )
    bake_and_rank.add_argument(
        "--skip-motion-tuning",
        action="store_true",
        help="Pass raw camera-space WHAM motion through before preview baking and review ranking.",
    )
    bake_and_rank.add_argument("--skip-source-segment-detection", action="store_true")
    bake_and_rank.add_argument("--segment-base-url")
    bake_and_rank.add_argument("--segment-model")
    bake_and_rank.add_argument("--segment-window-seconds", type=float)
    bake_and_rank.add_argument("--segment-overlap-seconds", type=float)
    bake_and_rank.add_argument("--segment-frames-per-window", type=int)
    bake_and_rank.add_argument("--segment-confidence-threshold", type=float, default=0.45)
    bake_and_rank.add_argument("--segment-padding-seconds", type=float, default=0.35)
    bake_and_rank.add_argument("--segment-end-padding-seconds", type=float, default=0.35)
    bake_and_rank.add_argument("--segment-min-seconds", type=float, default=2.0)
    bake_and_rank.add_argument("--segment-max-seconds", type=float, default=20.0)
    bake_and_rank.add_argument("--segment-refinement-window-seconds", type=float, default=2.0)
    bake_and_rank.add_argument("--segment-refinement-overlap-seconds", type=float, default=1.0)
    bake_and_rank.add_argument("--segment-refinement-frames-per-window", type=int, default=0)
    bake_and_rank.add_argument("--segment-refinement-padding-seconds", type=float, default=1.0)
    bake_and_rank.add_argument("--segment-classification-workers", type=int, default=3)
    bake_and_rank.add_argument("--review-frames", type=int, default=DEFAULT_REVIEW_FRAMES)
    bake_and_rank.add_argument(
        "--review-llm-workers",
        type=int,
        default=3,
        help="Maximum concurrent visual review requests for baked review items.",
    )
    bake_and_rank.add_argument(
        "--max-llm-review-items",
        type=int,
        default=4,
        help="Maximum baked review items to send to the visual ranker after deterministic prefiltering. Use 0 to review all.",
    )
    bake_and_rank.add_argument(
        "--max-review-windows",
        type=int,
        default=DEFAULT_MAX_REVIEW_WINDOWS,
        help="Maximum skeleton-prefiltered preview chunks to send to the visual ranker per baked item. Use 0 to review all chunks.",
    )
    bake_and_rank.add_argument(
        "--rank-preview-variants",
        action="store_true",
        help="Bake preset preview tuning variants and ask llama.cpp to score/select the best loopable preview section.",
    )
    bake_and_rank.add_argument("--min-selected-score", type=float, default=0.55)
    bake_and_rank.add_argument("--no-classify-support-dominance", action="store_true")
    bake_and_rank.add_argument("--llama-cpp-base-url", default="http://127.0.0.1:8090")
    bake_and_rank.add_argument("--llama-cpp-model", default="C:\\Users\\gabri\\Downloads\\Qwen3VL-8B-Instruct-Q4_K_M.gguf")
    bake_and_rank.add_argument("--llama-cpp-command")
    bake_and_rank.add_argument("--llama-cpp-server-command")
    bake_and_rank.add_argument("--llama-cpp-mmproj", default="C:\\Users\\gabri\\Downloads\\mmproj-Qwen3VL-8B-Instruct-F16.gguf")
    bake_and_rank.add_argument("--llama-cpp-backend", default="gpu")
    bake_and_rank.add_argument("--llama-cpp-n-predict", type=int, default=768)
    bake_and_rank.add_argument("--llama-cpp-temperature", type=float, default=0.0)
    bake_and_rank.add_argument("--no-llama-cpp-disable-reasoning", action="store_true")
    bake_and_rank.add_argument("--llama-cpp-ctx-size", type=int)
    bake_and_rank.add_argument("--llama-cpp-batch-size", type=int)
    bake_and_rank.add_argument("--llama-cpp-ubatch-size", type=int)
    bake_and_rank.add_argument("--llama-cpp-flash-attn", choices=["on", "off", "auto"])
    bake_and_rank.add_argument("--llama-cpp-threads-http", type=int)
    bake_and_rank.add_argument("--llama-cpp-cache-reuse", type=int)
    bake_and_rank.add_argument("--no-llama-cpp-mmproj-offload", action="store_true")
    bake_and_rank.add_argument("--no-llama-cpp-cont-batching", action="store_true")
    bake_and_rank.add_argument("--llama-cpp-image-min-tokens", type=int)
    bake_and_rank.add_argument("--llama-cpp-image-max-tokens", type=int)
    bake_and_rank.add_argument("--no-llama-cpp-auto-start-server", action="store_true")
    bake_and_rank.add_argument(
        "--keep-llama-cpp-server",
        action="store_true",
        help="Leave an auto-started llama.cpp server running after the pipeline so later runs skip model startup.",
    )
    bake_and_rank.add_argument("--llama-cpp-server-startup-timeout-seconds", type=float, default=180.0)
    bake_and_rank.add_argument("--llama-cpp-request-timeout-seconds", type=float, default=90.0)

    reselect_baked = subparsers.add_parser(
        "reselect-baked",
        help="Reuse an existing bake-and-rank workspace's review items and rankings to select the best Wear skeleton.",
    )
    reselect_baked.add_argument(
        "--workspace",
        required=True,
        help="Workspace containing selection_manifest.json.",
    )
    reselect_baked.add_argument("--min-selected-score", type=float)
    reselect_baked.add_argument("--review-frames", type=int)
    reselect_baked.add_argument("--max-review-windows", type=int)

    trim = subparsers.add_parser("trim-video", help="Trim a local video to an exact time span.")
    trim.add_argument("--video-path", required=True)
    trim.add_argument("--out-video", required=True)
    trim.add_argument("--start-seconds", type=float, required=True)
    trim.add_argument("--end-seconds", type=float, required=True)

    select_trim = subparsers.add_parser(
        "select-trim",
        help="Open a local browser video player to pick a source-video segment for WHAM.",
    )
    select_trim_source = select_trim.add_mutually_exclusive_group(required=True)
    select_trim_source.add_argument("--youtube-url", help="YouTube URL to download and trim.")
    select_trim_source.add_argument("--video-path", help="Existing local video path to trim.")
    select_trim.add_argument("--exercise-slug", default="manual-trim", help="Stable slug for generated trim artifacts.")
    select_trim.add_argument(
        "--workspace",
        default="build/exercise_motion_trim_selector",
        help="Workspace root for trim selector artifacts. Default: build/exercise_motion_trim_selector",
    )
    select_trim.add_argument(
        "--youtube-cookies",
        "--youtube-cookies-path",
        type=Path,
        help="Path to a YouTube cookies.txt file.",
    )
    select_trim.add_argument(
        "--run-wham-on-write",
        action="store_true",
        help="Start the existing generate pipeline after the browser writes selected_segment.mp4.",
    )
    select_trim.add_argument(
        "--generation-workspace",
        default="build/exercise_motion",
        help="Workspace root for WHAM generation artifacts. Default: build/exercise_motion",
    )
    select_trim.add_argument(
        "--wham-repo-path",
        default="C:\\Users\\gabri\\Downloads\\WHAM",
        help="Local WHAM checkout used when --run-wham-on-write is set.",
    )
    select_trim.add_argument(
        "--body-model-root",
        default="C:\\Users\\gabri\\Downloads\\WHAM\\dataset\\body_models",
        help="SMPL body model root used when --run-wham-on-write is set.",
    )
    select_trim.add_argument("--wham-python-command", default="python")
    select_trim.add_argument("--wham-estimate-local-only", action="store_true")
    select_trim.add_argument("--skip-wham-smplify", action="store_true")
    select_trim.add_argument("--skip-motion-tuning", action="store_true")
    select_trim.add_argument("--dominant-chain-ratio", type=float, default=0.65)
    select_trim.add_argument("--non-dominant-damping", type=float, default=1.0)
    select_trim.add_argument("--non-dominant-radius-scale", type=float, default=1.0)
    select_trim.add_argument("--host", default="127.0.0.1")
    select_trim.add_argument("--port", type=int, default=8765)

    spinepose_wham = subparsers.add_parser(
        "apply-spinepose-wham",
        help="Copy a WHAM result PKL and blend SpinePose-derived spine flexion into SMPL spine joints.",
    )
    spinepose_wham.add_argument("--wham-results-pkl", required=True)
    spinepose_wham.add_argument("--spinepose-json-dir", required=True)
    spinepose_wham.add_argument("--out-pkl", required=True)
    spinepose_wham.add_argument("--subject-id")
    spinepose_wham.add_argument("--gain", type=float, default=1.0)
    spinepose_wham.add_argument("--max-degrees", type=float, default=35.0)
    spinepose_wham.add_argument("--axis", type=int, default=0, choices=(0, 1, 2))
    spinepose_wham.add_argument("--invert", action="store_true")
    spinepose_wham.add_argument("--smoothing-window", type=int, default=9)
    spinepose_wham.add_argument("--arm-counter-rotation", type=float, default=1.0)
    spinepose_wham.add_argument("--experimental-enable", action="store_true")

    ground = subparsers.add_parser("ground-metadata", help="Generate motion/contact-derived render-ground metadata from a cleaned motion clip.")
    ground.add_argument("--video-path", required=True)
    ground.add_argument("--motion-json", required=True)
    ground.add_argument("--out-json", required=True)
    ground.add_argument("--embed-motion-json", help="Optional path to rewrite the motion JSON with embedded ground metadata.")
    ground.add_argument("--manifest-path", help="Optional manifest.json to update with the generated ground metadata.")
    ground.add_argument("--preview-html", help="Optional preview HTML path to rebuild from the updated motion JSON.")
    ground.add_argument("--preview-title", help="Optional title to use when rebuilding the preview HTML.")

    physics = subparsers.add_parser(
        "physics-bundle",
        help="Generate a MuJoCo-ready imitation bundle from a cleaned motion clip.",
    )
    physics.add_argument("--motion-json", required=True)
    physics.add_argument("--out-dir", required=True)
    physics.add_argument("--root-joint", default="pelvis")
    physics.add_argument("--smoothing-window", type=int, default=9)
    physics.add_argument("--root-smoothing-window", type=int, default=13)

    physics_sim = subparsers.add_parser(
        "physics-sim",
        help="Run a constrained kinematic refinement or the legacy prototype pass from a physics bundle and emit simulated motion JSON.",
    )
    physics_sim.add_argument("--bundle-dir", required=True)
    physics_sim.add_argument("--out-motion-json", required=True)
    physics_sim.add_argument("--backend", default="kinematic", choices=("kinematic", "prototype"))
    physics_sim.add_argument("--root-alpha", type=float, default=0.2)
    physics_sim.add_argument("--torso-alpha", type=float, default=0.24)
    physics_sim.add_argument("--leg-alpha", type=float, default=0.22)
    physics_sim.add_argument("--arm-alpha", type=float, default=0.14)
    physics_sim.add_argument("--head-alpha", type=float, default=0.12)
    physics_sim.add_argument("--support-blend-frames", type=int, default=6)
    physics_sim.add_argument("--kinematic-iterations", type=int, default=3)
    physics_sim.add_argument("--preview-html", help="Optional preview HTML path to build from the simulated output.")
    physics_sim.add_argument("--preview-title", help="Optional title to use when generating the simulated preview.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "generate":
        if (args.source_start_seconds is None) != (args.source_end_seconds is None):
            raise ValueError("Provide both --source-start-seconds and --source-end-seconds together.")
        if args.source_start_seconds is not None and args.source_end_seconds is not None:
            if args.source_start_seconds < 0:
                raise ValueError("--source-start-seconds must be >= 0.")
            if args.source_end_seconds <= args.source_start_seconds:
                raise ValueError("--source-end-seconds must be greater than --source-start-seconds.")
        result = run_generation_pipeline(
            GenerateRequest(
                exercise_slug=args.exercise_slug,
                workspace=Path(args.workspace),
                youtube_url=args.youtube_url,
                video_path=Path(args.video_path) if args.video_path else None,
                wham_repo_path=Path(args.wham_repo_path) if args.wham_repo_path else None,
                wham_results_pkl=Path(args.wham_results_pkl) if args.wham_results_pkl else None,
                reuse_wham_cache=not args.no_reuse_wham_cache,
                body_model_root=Path(args.body_model_root) if args.body_model_root else None,
                wham_python_command=args.wham_python_command,
                use_wham_docker=args.use_wham_docker,
                wham_docker_image=args.wham_docker_image,
                wham_docker_gpus=args.wham_docker_gpus,
                wham_docker_shm_size=args.wham_docker_shm_size,
                wham_estimate_local_only=args.wham_estimate_local_only,
                wham_run_smplify=not args.skip_wham_smplify,
                normalized_motion_json=Path(args.normalized_motion_json) if args.normalized_motion_json else None,
                one_euro_min_cutoff=args.one_euro_min_cutoff,
                one_euro_beta=args.one_euro_beta,
                one_euro_derivative_cutoff=args.one_euro_derivative_cutoff,
                motion_threshold=args.motion_threshold,
                padding_frames=args.padding_frames,
                dominant_chain_ratio=args.dominant_chain_ratio,
                non_dominant_damping=args.non_dominant_damping,
                non_dominant_radius_scale=args.non_dominant_radius_scale,
                motion_tuning_enabled=not args.skip_motion_tuning,
                source_start_seconds=args.source_start_seconds,
                source_end_seconds=args.source_end_seconds,
                youtube_cookies=Path(args.youtube_cookies) if args.youtube_cookies else None,
            )
        )
        print(f"Manifest: {result.manifest_path}")
        print(f"Preview HTML: {result.preview_html_path}")
        print(f"Raw preview HTML: {result.raw_preview_html_path}")
        print(f"Wear skeleton JSON: {result.wear_skeleton_json_path}")
        print(f"Cleaned motion JSON: {result.cleaned_motion_json_path}")
        print(f"Target rig contract JSON: {result.target_rig_contract_path}")
        if result.retarget_source_path is not None:
            print(f"WHAM retarget source JSON: {result.retarget_source_path}")
        if result.smpl_preview_json_path is not None:
            print(f"WHAM baked SMPL preview JSON: {result.smpl_preview_json_path}")
        if result.ground_metadata_path is not None:
            print(f"Ground metadata JSON: {result.ground_metadata_path}")
        return
    if args.command == "preview":
        clip = load_motion_json(Path(args.motion_json))
        write_preview_html(
            Path(args.out_html),
            clip,
            title=args.title,
            debug_json_path=Path(args.render_debug_json) if args.render_debug_json else None,
        )
        if args.render_debug_json:
            print(f"Preview render debug JSON: {Path(args.render_debug_json).resolve()}")
        if args.wear_skeleton_json:
            write_wear_skeleton_json(
                Path(args.wear_skeleton_json),
                clip,
                title=args.title,
                selected_loop_index=args.wear_skeleton_loop_index,
                lock_y_drift=args.wear_skeleton_lock_y_drift,
            )
            print(f"Wear skeleton JSON: {Path(args.wear_skeleton_json).resolve()}")
        print(f"Preview HTML: {Path(args.out_html).resolve()}")
        return
    if args.command == "raw-preview":
        clip = load_motion_json(Path(args.motion_json))
        write_raw_motion_preview_html(
            Path(args.out_html),
            clip,
            title=args.title,
        )
        print(f"Raw WHAM preview HTML: {Path(args.out_html).resolve()}")
        return
    if args.command == "wear-skeleton":
        clip = load_motion_json(Path(args.motion_json))
        write_wear_skeleton_json(
            Path(args.out_json),
            clip,
            title=args.title,
            selected_loop_index=args.loop_index,
            lock_y_drift=args.lock_y_drift,
        )
        print(f"Wear skeleton JSON: {Path(args.out_json).resolve()}")
        return
    if args.command == "detect-segment":
        from exercise_motion_pkg.segment_detection import (
            DetectionSettings,
            detect_exercise_segment,
            save_detection_result,
        )
        if args.llama_cpp_n_predict <= 0:
            raise ValueError("--llama-cpp-n-predict must be greater than 0.")
        if args.fast_segment_profile:
            settings = DetectionSettings(
                llama_cpp_command=args.llama_cpp_command,
                llama_cpp_model=args.llama_cpp_model,
                llama_cpp_mmproj=args.llama_cpp_mmproj,
                llama_cpp_backend=args.llama_cpp_backend,
                llama_cpp_n_predict=args.llama_cpp_n_predict,
                llama_cpp_image_min_tokens=args.llama_cpp_image_min_tokens,
                llama_cpp_image_max_tokens=args.llama_cpp_image_max_tokens,
                base_url=args.base_url,
                model=args.model,
                litert_command=args.litert_command,
                litert_backend=args.litert_backend,
                window_seconds=4.5,
                overlap_seconds=2.0,
                frames_per_window=6,
                max_frame_width=args.max_frame_width,
                merge_gap_seconds=args.merge_gap_seconds,
                confidence_threshold=0.60,
                min_segment_seconds=args.min_segment_seconds,
                max_segment_seconds=args.max_segment_seconds,
                refinement_window_seconds=args.refinement_window_seconds,
                refinement_overlap_seconds=args.refinement_overlap_seconds,
                refinement_frames_per_window=args.refinement_frames_per_window or max(24, args.frames_per_window * 2),
                refinement_padding_seconds=args.refinement_padding_seconds,
                classification_workers=4,
                use_motion_prefilter=True,
                motion_sample_fps=2.5,
                motion_threshold_ratio=0.55,
                motion_merge_gap_seconds=1.0,
                motion_min_interval_seconds=1.5,
                max_motion_candidates=3,
                active_refinement_max_rounds=0,
                enable_final_refinement=False,
                enable_boundary_refinement=True,
            )
        else:
            settings = DetectionSettings(
                llama_cpp_command=args.llama_cpp_command,
                llama_cpp_model=args.llama_cpp_model,
                llama_cpp_mmproj=args.llama_cpp_mmproj,
                llama_cpp_backend=args.llama_cpp_backend,
                llama_cpp_n_predict=args.llama_cpp_n_predict,
                llama_cpp_image_min_tokens=args.llama_cpp_image_min_tokens,
                llama_cpp_image_max_tokens=args.llama_cpp_image_max_tokens,
                base_url=args.base_url,
                model=args.model,
                litert_command=args.litert_command,
                litert_backend=args.litert_backend,
                window_seconds=args.window_seconds,
                overlap_seconds=args.overlap_seconds,
                frames_per_window=args.frames_per_window,
                max_frame_width=args.max_frame_width,
                merge_gap_seconds=args.merge_gap_seconds,
                confidence_threshold=args.confidence_threshold,
                min_segment_seconds=args.min_segment_seconds,
                max_segment_seconds=args.max_segment_seconds,
                refinement_window_seconds=args.refinement_window_seconds,
                refinement_overlap_seconds=args.refinement_overlap_seconds,
                refinement_frames_per_window=args.refinement_frames_per_window or max(24, args.frames_per_window * 2),
                refinement_padding_seconds=args.refinement_padding_seconds,
                classification_workers=args.classification_workers,
            )

        result = detect_exercise_segment(
            video_path=Path(args.video_path),
            output_dir=Path(args.frames_dir),
            settings=settings,
            exercise_name=args.exercise_name,
        )
        out_json = Path(args.out_json)
        save_detection_result(out_json, result)
        print(f"Detection JSON: {out_json.resolve()}")
        if result.detected_span is None:
            print("Detected span: none")
        else:
            print(f"Detected span start: {result.detected_span.start_seconds:.3f}")
            print(f"Detected span end: {result.detected_span.end_seconds:.3f}")
        return
    if args.command == "find-youtube-videos":
        manifest = discover_and_rank_youtube_candidates(
            workout_plan_json=Path(args.workout_plan_json),
            out_json=Path(args.out_json),
            settings=YouTubeRankingSettings(
                results_per_query=args.results_per_query,
                max_candidates=args.max_candidates,
                metadata_candidate_pool_size=args.metadata_candidate_pool_size,
                min_duration_seconds=args.min_duration_seconds,
                max_duration_seconds=args.max_duration_seconds,
                use_deepseek_query_planner=args.use_deepseek_query_planner,
                deepseek_api_key=args.deepseek_api_key,
                deepseek_base_url=args.deepseek_base_url,
                deepseek_model=args.deepseek_model,
                deepseek_max_queries=args.deepseek_max_queries,
                deepseek_timeout_seconds=args.deepseek_timeout_seconds,
                rank_with_litert=args.rank_with_litert,
                vision_candidates_per_exercise=args.vision_candidates_per_exercise,
                vision_frames_per_candidate=args.vision_frames_per_candidate,
                vision_chunk_seconds=args.vision_chunk_seconds,
                vision_chunk_overlap_seconds=args.vision_chunk_overlap_seconds,
                vision_max_chunks_per_candidate=args.vision_max_chunks_per_candidate,
                vision_download_workers=args.vision_download_workers,
                vision_llm_workers=args.vision_llm_workers,
                llama_cpp_base_url=None if args.no_llama_cpp else args.llama_cpp_base_url,
                llama_cpp_model=args.llama_cpp_model,
                llama_cpp_command=args.llama_cpp_command,
                llama_cpp_server_command=args.llama_cpp_server_command,
                llama_cpp_mmproj=args.llama_cpp_mmproj,
                llama_cpp_backend=args.llama_cpp_backend,
                llama_cpp_n_predict=args.llama_cpp_n_predict,
                llama_cpp_image_min_tokens=args.llama_cpp_image_min_tokens,
                llama_cpp_image_max_tokens=args.llama_cpp_image_max_tokens,
                llama_cpp_auto_start_server=not args.no_llama_cpp_auto_start_server,
                llama_cpp_server_startup_timeout_seconds=args.llama_cpp_server_startup_timeout_seconds,
                llama_cpp_request_timeout_seconds=args.llama_cpp_request_timeout_seconds,
                include_disabled=args.include_disabled,
                vision_early_stop_score=args.vision_early_stop_score,
            ),
        )
        print(f"YouTube candidates JSON: {Path(args.out_json).resolve()}")
        print(f"Exercises: {len(manifest['exercises'])}")
        return
    if args.command == "bake-and-rank":
        manifest = run_bake_and_rank_pipeline(
            BakeAndRankRequest(
                candidates_json=Path(args.candidates_json),
                workspace=Path(args.workspace),
                wham_repo_path=Path(args.wham_repo_path),
                body_model_root=Path(args.body_model_root),
                fallback_candidates=args.fallback_candidates,
                candidate_workers=args.candidate_workers,
                wham_python_command=args.wham_python,
                reuse_wham_cache=not args.no_reuse_wham_cache,
                use_wham_docker=args.use_wham_docker,
                wham_docker_image=args.wham_docker_image,
                wham_docker_gpus=args.wham_docker_gpus,
                wham_docker_shm_size=args.wham_docker_shm_size,
                wham_estimate_local_only=args.estimate_local_only,
                wham_run_smplify=not args.skip_smplify,
                detect_source_segment=not args.skip_source_segment_detection,
                segment_base_url=args.segment_base_url,
                segment_model=args.segment_model,
                segment_window_seconds=args.segment_window_seconds,
                segment_overlap_seconds=args.segment_overlap_seconds,
                segment_frames_per_window=args.segment_frames_per_window,
                segment_confidence_threshold=args.segment_confidence_threshold,
                segment_padding_seconds=args.segment_padding_seconds,
                segment_end_padding_seconds=args.segment_end_padding_seconds,
                segment_min_seconds=args.segment_min_seconds,
                segment_max_seconds=args.segment_max_seconds,
                segment_refinement_window_seconds=args.segment_refinement_window_seconds,
                segment_refinement_overlap_seconds=args.segment_refinement_overlap_seconds,
                segment_refinement_frames_per_window=args.segment_refinement_frames_per_window,
                segment_refinement_padding_seconds=args.segment_refinement_padding_seconds,
                segment_classification_workers=args.segment_classification_workers,
                review_frames=args.review_frames,
                review_llm_workers=args.review_llm_workers,
                max_llm_review_items=args.max_llm_review_items,
                max_review_windows=args.max_review_windows,
                rank_preview_variants=args.rank_preview_variants,
                min_selected_score=args.min_selected_score,
                motion_tuning_enabled=not args.skip_motion_tuning,
                classify_support_dominance=not args.no_classify_support_dominance,
                llama_cpp_base_url=args.llama_cpp_base_url,
                llama_cpp_model=args.llama_cpp_model,
                llama_cpp_command=args.llama_cpp_command,
                llama_cpp_server_command=args.llama_cpp_server_command,
                llama_cpp_mmproj=args.llama_cpp_mmproj,
                llama_cpp_backend=args.llama_cpp_backend,
                llama_cpp_n_predict=args.llama_cpp_n_predict,
                llama_cpp_temperature=args.llama_cpp_temperature,
                llama_cpp_disable_reasoning=not args.no_llama_cpp_disable_reasoning,
                llama_cpp_ctx_size=args.llama_cpp_ctx_size,
                llama_cpp_batch_size=args.llama_cpp_batch_size,
                llama_cpp_ubatch_size=args.llama_cpp_ubatch_size,
                llama_cpp_flash_attn=args.llama_cpp_flash_attn,
                llama_cpp_threads_http=args.llama_cpp_threads_http,
                llama_cpp_cache_reuse=args.llama_cpp_cache_reuse,
                llama_cpp_mmproj_offload=not args.no_llama_cpp_mmproj_offload,
                llama_cpp_cont_batching=not args.no_llama_cpp_cont_batching,
                llama_cpp_image_min_tokens=args.llama_cpp_image_min_tokens,
                llama_cpp_image_max_tokens=args.llama_cpp_image_max_tokens,
                llama_cpp_auto_start_server=not args.no_llama_cpp_auto_start_server,
                keep_llama_cpp_server=args.keep_llama_cpp_server,
                llama_cpp_server_startup_timeout_seconds=args.llama_cpp_server_startup_timeout_seconds,
                llama_cpp_request_timeout_seconds=args.llama_cpp_request_timeout_seconds,
            )
        )
        selection_path = Path(args.workspace) / "selection_manifest.json"
        print(f"Selection manifest: {selection_path.resolve()}")
        selected = manifest.get("selected")
        if selected:
            print(f"Wear skeleton JSON: {selected['selectedWearSkeletonPath']}")
            selected_preview = manifest.get("selectedPreviewHtmlPath")
            if selected_preview:
                print(f"Preview HTML: {Path(selected_preview).resolve()}")
        else:
            print("Selected Wear skeleton: none")
        return
    if args.command == "reselect-baked":
        manifest = run_bake_and_rank_reselection(
            workspace=Path(args.workspace),
            min_selected_score=args.min_selected_score,
            review_frames=args.review_frames,
            max_review_windows=args.max_review_windows,
        )
        selection_path = Path(args.workspace) / "selection_manifest.json"
        print(f"Selection manifest: {selection_path.resolve()}")
        selected = manifest.get("selected")
        if selected:
            print(f"Wear skeleton JSON: {selected['selectedWearSkeletonPath']}")
            selected_preview = manifest.get("selectedPreviewHtmlPath")
            if selected_preview:
                print(f"Preview HTML: {Path(selected_preview).resolve()}")
        else:
            print("Selected Wear skeleton: none")
        return
    if args.command == "trim-video":
        output_path = trim_video(
            source_path=Path(args.video_path),
            output_path=Path(args.out_video),
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
        print(f"Trimmed video: {output_path.resolve()}")
        return
    if args.command == "select-trim":
        run_trim_selector(
            TrimSelectorRequest(
                exercise_slug=args.exercise_slug,
                workspace=Path(args.workspace),
                youtube_url=args.youtube_url,
                video_path=Path(args.video_path) if args.video_path else None,
                youtube_cookies=Path(args.youtube_cookies) if args.youtube_cookies else None,
                run_wham_on_write=args.run_wham_on_write,
                generation_workspace=Path(args.generation_workspace),
                wham_repo_path=Path(args.wham_repo_path),
                body_model_root=Path(args.body_model_root),
                wham_python_command=args.wham_python_command,
                wham_estimate_local_only=args.wham_estimate_local_only,
                wham_run_smplify=not args.skip_wham_smplify,
                motion_tuning_enabled=not args.skip_motion_tuning,
                dominant_chain_ratio=args.dominant_chain_ratio,
                non_dominant_damping=args.non_dominant_damping,
                non_dominant_radius_scale=args.non_dominant_radius_scale,
                host=args.host,
                port=args.port,
            )
        )
        return
    if args.command == "apply-spinepose-wham":
        if not args.experimental_enable:
            raise SystemExit(
                "SpinePose-to-WHAM correction is disabled because it distorts the SMPL body. "
                "Pass --experimental-enable only for manual experiments."
            )
        stats = apply_spinepose_to_wham_pkl(
            wham_results_pkl=Path(args.wham_results_pkl),
            spinepose_json_dir=Path(args.spinepose_json_dir),
            output_pkl=Path(args.out_pkl),
            subject_id=args.subject_id,
            gain=args.gain,
            max_degrees=args.max_degrees,
            axis=args.axis,
            invert=args.invert,
            smoothing_window=args.smoothing_window,
            arm_counter_rotation=args.arm_counter_rotation,
        )
        print(f"Corrected WHAM PKL: {Path(args.out_pkl).resolve()}")
        print(f"Frames: {stats.applied_frame_count}/{stats.frame_count}")
        print(f"Source SpinePose frames: {stats.source_frame_count}")
        print(f"Pose keys: {', '.join(stats.pose_keys)}")
        print(f"Max delta degrees: {stats.max_delta_degrees:.2f}")
        print(f"Mean abs delta degrees: {stats.mean_abs_delta_degrees:.2f}")
        print(f"Arm counter rotation: {stats.arm_counter_rotation:.2f}")
        return
    if args.command == "ground-metadata":
        clip = load_motion_json(Path(args.motion_json))
        ground_metadata = generate_ground_metadata(
            video_path=Path(args.video_path),
            cleaned_clip=clip,
            output_path=Path(args.out_json),
        )
        if args.embed_motion_json:
            embedded_motion_path = Path(args.embed_motion_json)
            embed_ground_metadata_in_clip(
                clip=clip,
                ground_metadata=ground_metadata,
                output_path=embedded_motion_path,
            )
            clip = load_motion_json(embedded_motion_path)
            print(f"Embedded motion JSON: {embedded_motion_path.resolve()}")
        if args.manifest_path:
            manifest_path = Path(args.manifest_path)
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload["groundMetadataPath"] = str(Path(args.out_json).resolve())
            manifest_payload["groundMetadata"] = ground_metadata.to_dict()
            manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
            print(f"Updated manifest JSON: {manifest_path.resolve()}")
        if args.preview_html:
            preview_title = args.preview_title or Path(args.motion_json).stem
            write_preview_html(Path(args.preview_html), clip, title=preview_title)
            print(f"Updated preview HTML: {Path(args.preview_html).resolve()}")
        print(f"Ground metadata JSON: {Path(args.out_json).resolve()}")
        return
    if args.command == "physics-bundle":
        clip = load_motion_json(Path(args.motion_json))
        result = write_physics_bundle(
            clip=clip,
            out_dir=Path(args.out_dir),
            config=PhysicsBundleConfig(
                root_joint=args.root_joint,
                smoothing_window=args.smoothing_window,
                root_smoothing_window=args.root_smoothing_window,
            ),
        )
        print(f"Physics bundle directory: {result.out_dir.resolve()}")
        print(f"Reference targets JSON: {result.reference_json_path.resolve()}")
        print(f"Controller config JSON: {result.controller_config_path.resolve()}")
        print(f"Summary JSON: {result.summary_json_path.resolve()}")
        return
    if args.command == "physics-sim":
        result = run_physics_simulation(
            bundle_dir=Path(args.bundle_dir),
            output_motion_json=Path(args.out_motion_json),
            config=PhysicsSimulationConfig(
                backend=args.backend,
                root_alpha=args.root_alpha,
                torso_alpha=args.torso_alpha,
                leg_alpha=args.leg_alpha,
                arm_alpha=args.arm_alpha,
                head_alpha=args.head_alpha,
                support_blend_frames=args.support_blend_frames,
                kinematic_iterations=args.kinematic_iterations,
            ),
        )
        print(f"Simulated motion JSON: {result.simulated_motion_json_path.resolve()}")
        print(f"Simulation summary JSON: {result.summary_json_path.resolve()}")
        if args.preview_html:
            simulated_clip = load_motion_json(result.simulated_motion_json_path)
            preview_title = args.preview_title or Path(args.out_motion_json).stem
            write_preview_html(Path(args.preview_html), simulated_clip, title=preview_title)
            print(f"Simulated preview HTML: {Path(args.preview_html).resolve()}")
        return
    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
