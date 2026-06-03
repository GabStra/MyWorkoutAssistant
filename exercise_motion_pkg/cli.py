from __future__ import annotations

import argparse
import json
from pathlib import Path

from exercise_motion_pkg.ground import embed_ground_metadata_in_clip, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline
from exercise_motion_pkg.physics_bundle import PhysicsBundleConfig, write_physics_bundle
from exercise_motion_pkg.physics_sim import PhysicsSimulationConfig, run_physics_simulation
from exercise_motion_pkg.preview import write_preview_debug_json, write_preview_html
from exercise_motion_pkg.video_utils import trim_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exercise-motion",
        description="Generate a cleaned, previewable exercise motion clip from a video and GVHMR output.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Run the video -> GVHMR -> cleanup -> preview pipeline.")
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
        "--gvhmr-repo-path",
        help="Local GVHMR checkout prepared for inference. Required unless --normalized-motion-json is supplied.",
    )
    generate.add_argument(
        "--gvhmr-results-pt",
        help="Existing GVHMR hmr4d_results.pt path inside or outside the GVHMR repo. If supplied, local inference is skipped.",
    )
    generate.add_argument(
        "--body-model-root",
        help="Directory containing the SMPL/SMPLX body model folders used to reconstruct joints from GVHMR output.",
    )
    generate.add_argument(
        "--gvhmr-python-command",
        default="python",
        help="Python interpreter or command to run GVHMR and the GVHMR-backed conversion stage.",
    )
    generate.add_argument(
        "--gvhmr-static-camera",
        action="store_true",
        help="Pass -s to GVHMR to skip visual odometry for static camera clips.",
    )
    generate.add_argument(
        "--gvhmr-coordinate-space",
        choices=("incam", "global"),
        default="incam",
        help="Which GVHMR SMPL parameter set to convert into the repo motion clip. Default: incam",
    )
    generate.add_argument(
        "--normalized-motion-json",
        help="Existing normalized motion JSON. If supplied, GVHMR execution and conversion are skipped.",
    )
    generate.add_argument("--smoothing-window", type=int, default=5)
    generate.add_argument("--motion-threshold", type=float, default=0.015)
    generate.add_argument("--padding-frames", type=int, default=3)

    preview = subparsers.add_parser("preview", help="Build a standalone HTML preview from a normalized motion JSON.")
    preview.add_argument("--motion-json", required=True)
    preview.add_argument("--out-html", required=True)
    preview.add_argument("--title", default="exercise-motion-preview")
    preview.add_argument("--render-debug-json", help="Optional JSON export of the exact joint coordinates used by the preview renderer.")

    detect = subparsers.add_parser("detect-segment", help="Use a local multimodal model to detect the exercise span in a video.")
    detect.add_argument("--video-path", required=True)
    detect.add_argument("--out-json", required=True)
    detect.add_argument("--frames-dir", required=True)
    detect.add_argument("--exercise-name")
    detect.add_argument("--base-url", default="http://127.0.0.1:8090")
    detect.add_argument("--model", default="local-vision")
    detect.add_argument("--litert-command")
    detect.add_argument("--litert-backend", default="gpu")
    detect.add_argument("--window-seconds", type=float, default=8.0)
    detect.add_argument("--overlap-seconds", type=float, default=4.0)
    detect.add_argument("--frames-per-window", type=int, default=6)
    detect.add_argument("--max-frame-width", type=int, default=960)
    detect.add_argument("--merge-gap-seconds", type=float, default=2.0)
    detect.add_argument("--confidence-threshold", type=float, default=0.45)

    trim = subparsers.add_parser("trim-video", help="Trim a local video to an exact time span.")
    trim.add_argument("--video-path", required=True)
    trim.add_argument("--out-video", required=True)
    trim.add_argument("--start-seconds", type=float, required=True)
    trim.add_argument("--end-seconds", type=float, required=True)

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
        result = run_generation_pipeline(
            GenerateRequest(
                exercise_slug=args.exercise_slug,
                workspace=Path(args.workspace),
                youtube_url=args.youtube_url,
                video_path=Path(args.video_path) if args.video_path else None,
                gvhmr_repo_path=Path(args.gvhmr_repo_path) if args.gvhmr_repo_path else None,
                gvhmr_results_pt=Path(args.gvhmr_results_pt) if args.gvhmr_results_pt else None,
                body_model_root=Path(args.body_model_root) if args.body_model_root else None,
                gvhmr_python_command=args.gvhmr_python_command,
                gvhmr_static_camera=args.gvhmr_static_camera,
                gvhmr_coordinate_space=args.gvhmr_coordinate_space,
                normalized_motion_json=Path(args.normalized_motion_json) if args.normalized_motion_json else None,
                smoothing_window=args.smoothing_window,
                motion_threshold=args.motion_threshold,
                padding_frames=args.padding_frames,
            )
        )
        print(f"Manifest: {result.manifest_path}")
        print(f"Preview HTML: {result.preview_html_path}")
        print(f"Raw preview HTML: {result.raw_preview_html_path}")
        print(f"Cleaned motion JSON: {result.cleaned_motion_json_path}")
        print(f"Target rig contract JSON: {result.target_rig_contract_path}")
        if result.gvhmr_retarget_source_path is not None:
            print(f"GVHMR retarget source JSON: {result.gvhmr_retarget_source_path}")
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
        print(f"Preview HTML: {Path(args.out_html).resolve()}")
        return
    if args.command == "detect-segment":
        from exercise_motion_pkg.segment_detection import (
            DetectionSettings,
            detect_exercise_segment,
            save_detection_result,
        )

        result = detect_exercise_segment(
            video_path=Path(args.video_path),
            output_dir=Path(args.frames_dir),
            settings=DetectionSettings(
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
            ),
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
    if args.command == "trim-video":
        output_path = trim_video(
            source_path=Path(args.video_path),
            output_path=Path(args.out_video),
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
        print(f"Trimmed video: {output_path.resolve()}")
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
