from __future__ import annotations

import argparse
import json
from pathlib import Path

from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest, run_bake_and_rank_pipeline
from exercise_motion_pkg.ground import embed_ground_metadata_in_clip, generate_ground_metadata
from exercise_motion_pkg.motion_io import load_motion_json
from exercise_motion_pkg.pipeline import GenerateRequest, run_generation_pipeline
from exercise_motion_pkg.physics_bundle import PhysicsBundleConfig, write_physics_bundle
from exercise_motion_pkg.physics_sim import PhysicsSimulationConfig, run_physics_simulation
from exercise_motion_pkg.preview import write_preview_debug_json, write_preview_html, write_wear_skeleton_json
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
        "--wham-run-smplify",
        action="store_true",
        help="Run WHAM's Temporal SMPLify refinement before conversion.",
    )
    generate.add_argument(
        "--wham-coordinate-space",
        choices=("world", "camera"),
        default="camera",
        help="Which WHAM pose/translation space to convert into the repo motion clip. Default: camera",
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

    preview = subparsers.add_parser("preview", help="Build a standalone HTML preview from a normalized motion JSON.")
    preview.add_argument("--motion-json", required=True)
    preview.add_argument("--out-html", required=True)
    preview.add_argument("--title", default="exercise-motion-preview")
    preview.add_argument("--render-debug-json", help="Optional JSON export of the exact joint coordinates used by the preview renderer.")
    preview.add_argument("--wear-skeleton-json", help="Optional Wear-ready JSON export of the exact baked preview skeleton.")
    preview.add_argument("--wear-skeleton-loop-index", type=int, help="Loop index to bake for --wear-skeleton-json. Use -1 for full clip. Defaults to first detected loop.")
    preview.add_argument("--wear-skeleton-lock-y-drift", action="store_true", help="Also lock root Y drift in the baked Wear skeleton.")

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
    detect.add_argument("--max-frame-width", type=int, default=960)
    detect.add_argument("--merge-gap-seconds", type=float, default=2.0)
    detect.add_argument("--confidence-threshold", type=float, default=0.45)
    detect.add_argument("--min-segment-seconds", type=float, default=2.0)
    detect.add_argument("--max-segment-seconds", type=float, default=20.0)

    youtube_search = subparsers.add_parser(
        "find-youtube-videos",
        help="Find and rank YouTube candidate videos for exercises in a workout plan JSON.",
    )
    youtube_search.add_argument("--workout-plan-json", required=True)
    youtube_search.add_argument("--out-json", required=True)
    youtube_search.add_argument("--results-per-query", type=int, default=10)
    youtube_search.add_argument("--max-candidates", type=int, default=6)
    youtube_search.add_argument("--min-duration-seconds", type=int, default=20)
    youtube_search.add_argument("--max-duration-seconds", type=int, default=120)
    youtube_search.add_argument("--rank-with-litert", action="store_true")
    youtube_search.add_argument("--vision-candidates-per-exercise", type=int, default=3)
    youtube_search.add_argument("--vision-frames-per-candidate", type=int, default=4)
    youtube_search.add_argument("--vision-download-workers", type=int, default=3)
    youtube_search.add_argument("--vision-llm-workers", type=int, default=1)
    youtube_search.add_argument("--litert-command")
    youtube_search.add_argument("--litert-backend", default="gpu")
    youtube_search.add_argument("--vision-model", default="gemma-4-E4B-it")
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
    bake_and_rank.add_argument(
        "--workspace",
        default="build/exercise_motion",
        help="Workspace root for generated artifacts. Default: build/exercise_motion",
    )
    bake_and_rank.add_argument("--wham-repo-path", required=True)
    bake_and_rank.add_argument("--body-model-root", required=True)
    bake_and_rank.add_argument("--max-loop-seconds", type=float, default=10.0)
    bake_and_rank.add_argument("--wham-python", default="python")
    bake_and_rank.add_argument("--use-wham-docker", action="store_true")
    bake_and_rank.add_argument(
        "--wham-docker-image",
        default="yusun9/wham-vitpose-dpvo-cuda11.3-python3.9:latest",
    )
    bake_and_rank.add_argument("--wham-docker-gpus", default="all")
    bake_and_rank.add_argument("--wham-docker-shm-size", default="8g")
    bake_and_rank.add_argument("--estimate-local-only", action="store_true")
    bake_and_rank.add_argument("--run-smplify", action="store_true")
    bake_and_rank.add_argument(
        "--wham-coordinate-space",
        choices=("world", "camera"),
        default="camera",
    )
    bake_and_rank.add_argument("--litert-command")
    bake_and_rank.add_argument("--litert-backend", default="gpu")
    bake_and_rank.add_argument("--vision-model", default="gemma-4-E4B-it")
    bake_and_rank.add_argument("--no-litert-server", action="store_true")
    bake_and_rank.add_argument("--litert-server-url", default="http://127.0.0.1:9379")
    bake_and_rank.add_argument("--litert-server-port", type=int, default=9379)
    bake_and_rank.add_argument("--keep-litert-server", action="store_true")
    bake_and_rank.add_argument("--review-frames", type=int, default=12)
    bake_and_rank.add_argument("--min-selected-score", type=float, default=0.55)
    bake_and_rank.add_argument("--skip-source-segment-detection", action="store_true")
    bake_and_rank.add_argument("--segment-base-url")
    bake_and_rank.add_argument("--segment-model")
    bake_and_rank.add_argument("--segment-window-seconds", type=float, default=5.0)
    bake_and_rank.add_argument("--segment-overlap-seconds", type=float, default=2.5)
    bake_and_rank.add_argument("--segment-frames-per-window", type=int, default=20)
    bake_and_rank.add_argument("--segment-confidence-threshold", type=float, default=0.45)
    bake_and_rank.add_argument("--segment-padding-seconds", type=float, default=0.35)
    bake_and_rank.add_argument("--segment-end-padding-seconds", type=float, default=0.35)
    bake_and_rank.add_argument("--segment-min-seconds", type=float, default=2.0)
    bake_and_rank.add_argument("--segment-max-seconds", type=float, default=20.0)

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
                wham_repo_path=Path(args.wham_repo_path) if args.wham_repo_path else None,
                wham_results_pkl=Path(args.wham_results_pkl) if args.wham_results_pkl else None,
                body_model_root=Path(args.body_model_root) if args.body_model_root else None,
                wham_python_command=args.wham_python_command,
                use_wham_docker=args.use_wham_docker,
                wham_docker_image=args.wham_docker_image,
                wham_docker_gpus=args.wham_docker_gpus,
                wham_docker_shm_size=args.wham_docker_shm_size,
                wham_estimate_local_only=args.wham_estimate_local_only,
                wham_run_smplify=args.wham_run_smplify,
                wham_coordinate_space=args.wham_coordinate_space,
                normalized_motion_json=Path(args.normalized_motion_json) if args.normalized_motion_json else None,
                one_euro_min_cutoff=args.one_euro_min_cutoff,
                one_euro_beta=args.one_euro_beta,
                one_euro_derivative_cutoff=args.one_euro_derivative_cutoff,
                motion_threshold=args.motion_threshold,
                padding_frames=args.padding_frames,
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

        result = detect_exercise_segment(
            video_path=Path(args.video_path),
            output_dir=Path(args.frames_dir),
            settings=DetectionSettings(
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
    if args.command == "find-youtube-videos":
        manifest = discover_and_rank_youtube_candidates(
            workout_plan_json=Path(args.workout_plan_json),
            out_json=Path(args.out_json),
            settings=YouTubeRankingSettings(
                results_per_query=args.results_per_query,
                max_candidates=args.max_candidates,
                min_duration_seconds=args.min_duration_seconds,
                max_duration_seconds=args.max_duration_seconds,
                rank_with_litert=args.rank_with_litert,
                vision_candidates_per_exercise=args.vision_candidates_per_exercise,
                vision_frames_per_candidate=args.vision_frames_per_candidate,
                vision_download_workers=args.vision_download_workers,
                vision_llm_workers=args.vision_llm_workers,
                litert_command=args.litert_command,
                litert_backend=args.litert_backend,
                vision_model=args.vision_model,
                include_disabled=args.include_disabled,
                use_litert_server=not args.no_litert_server,
                litert_server_url=args.litert_server_url,
                litert_server_port=args.litert_server_port,
                keep_litert_server=args.keep_litert_server,
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
                wham_python_command=args.wham_python,
                use_wham_docker=args.use_wham_docker,
                wham_docker_image=args.wham_docker_image,
                wham_docker_gpus=args.wham_docker_gpus,
                wham_docker_shm_size=args.wham_docker_shm_size,
                wham_estimate_local_only=args.estimate_local_only,
                wham_run_smplify=args.run_smplify,
                wham_coordinate_space=args.wham_coordinate_space,
                max_loop_seconds=args.max_loop_seconds,
                litert_command=args.litert_command,
                litert_backend=args.litert_backend,
                vision_model=args.vision_model,
                use_litert_server=not args.no_litert_server,
                litert_server_url=args.litert_server_url,
                litert_server_port=args.litert_server_port,
                keep_litert_server=args.keep_litert_server,
                review_frames=args.review_frames,
                min_selected_score=args.min_selected_score,
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
            )
        )
        selection_path = Path(args.workspace) / "selection_manifest.json"
        print(f"Selection manifest: {selection_path.resolve()}")
        selected = manifest.get("selected")
        if selected:
            print(f"Selected Wear skeleton: {selected['selectedWearSkeletonPath']}")
            preview_html = manifest.get("selectedLoopPreviewHtmlPath")
            if preview_html:
                print(f"Selected loop preview: {Path(preview_html).resolve()}")
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
