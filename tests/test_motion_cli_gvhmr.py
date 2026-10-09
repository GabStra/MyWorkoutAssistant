from pathlib import Path

import pytest

from exercise_motion_pkg.cli import build_parser
from exercise_motion_pkg.trim_selector import TrimSelectorSession, build_generate_command


def test_generate_cli_defaults_to_gvhmr_docker_and_rejects_old_backend():
    parser = build_parser()

    args = parser.parse_args(["generate", "--exercise-slug", "press", "--video-path", "press.mp4"])

    assert args.motion_reconstructor == "gvhmr"
    assert args.use_reconstruction_docker is True
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "generate",
                "--exercise-slug",
                "press",
                "--video-path",
                "press.mp4",
                "--motion-reconstructor",
                "reconstruction",
            ]
        )


@pytest.mark.parametrize(
    "command",
    ["generate", "bake-and-rank", "find-youtube-videos", "select-trim", "gvhmr-run"],
)
def test_public_command_help_paths_parse(command):
    with pytest.raises(SystemExit) as result:
        build_parser().parse_args([command, "--help"])

    assert result.value.code == 0


def test_gvhmr_run_accepts_shared_docker_flag_names():
    args = build_parser().parse_args(
        [
            "gvhmr-run",
            "--input-video", "source.mp4",
            "--output-root", "output",
            "--logs-dir", "logs",
            "--reconstruction-docker-image", "custom/gvhmr:latest",
            "--reconstruction-docker-gpus", "0",
            "--reconstruction-docker-shm-size", "16g",
            "--reconstruction-timeout-seconds", "42",
        ]
    )

    assert (args.docker_image, args.gpus, args.shm_size, args.timeout_seconds) == (
        "custom/gvhmr:latest", "0", "16g", 42.0
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["generate", "--exercise-slug", "press", "--video-path", "source.mp4"],
        ["bake-and-rank", "--candidates-json", "candidates.json"],
    ],
)
def test_generator_cli_restricts_spinepose_to_motion_fusion(arguments):
    with pytest.raises(SystemExit):
        build_parser().parse_args([*arguments, "--spinepose-merge-mode", "legacy-pkl"])


@pytest.mark.parametrize(
    "arguments",
    [
        ["generate", "--exercise-slug", "press", "--video-path", "source.mp4"],
        ["bake-and-rank", "--candidates-json", "candidates.json"],
    ],
)
def test_generators_reject_legacy_spinepose_tuning_options(arguments):
    with pytest.raises(SystemExit):
        build_parser().parse_args([*arguments, "--spinepose-axis", "1"])

    with pytest.raises(SystemExit):
        build_parser().parse_args([*arguments, "--spinepose-arm-counter-rotation", "0.5"])


def test_standalone_spinepose_pkl_utility_keeps_axis_and_counter_rotation_options():
    args = build_parser().parse_args(
        [
            "apply-spinepose-reconstruction",
            "--reconstruction-results-pkl", "results.pkl",
            "--spinepose-json-dir", "spinepose",
            "--out-pkl", "corrected.pkl",
            "--axis", "1",
            "--arm-counter-rotation", "0.5",
        ]
    )

    assert (args.axis, args.arm_counter_rotation) == (1, 0.5)


def test_trim_selector_launches_gvhmr_with_docker():
    session = TrimSelectorSession(
        root_dir=Path("trim"),
        source_video_path=Path("source.mp4"),
        selected_video_path=Path("selected.mp4"),
        selection_json_path=Path("selection.json"),
        exercise_slug="press",
        youtube_url=None,
        run_reconstruction_on_write=True,
        generation_workspace=Path("generation"),
        body_model_root=Path("body-models"),
        motion_tuning_enabled=False,
        dominant_chain_ratio=0.65,
        non_dominant_damping=1.0,
        non_dominant_radius_scale=1.0,
    )

    command = build_generate_command(session, Path("selected.mp4"))

    assert command[command.index("--motion-reconstructor") + 1] == "gvhmr"
    assert "--use-reconstruction-docker" in command
    assert "--skip-motion-tuning" in command
    assert not any("repo-path" in arg or "python-command" in arg for arg in command)
