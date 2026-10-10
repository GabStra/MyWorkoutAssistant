from types import SimpleNamespace
import json
from pathlib import Path
import re
import subprocess

import numpy as np
import pytest

import exercise_motion_pkg.bake_and_rank as motion
from exercise_motion_pkg import preview
from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_CTX_SIZE, DEFAULT_LLAMA_CPP_PARALLEL


def test_horizontal_torso_does_not_infer_inversion_from_head_foot_height():
    frames = [{"joints": {
        "pelvis": [0., 0.2, 0.], "neck": [0.8, 0.2, 0.],
        "head": [1., 0.2, 0.], "left_foot": [0., 0.8, 0.],
        "right_foot": [0., 0.8, 0.],
    }} for _ in range(5)]
    normalized, metadata = preview._normalize_wear_skeleton_export_coordinates(
        frames, remove_scene_inversion=False)
    assert normalized == frames
    assert metadata["transform"] == "none"


def test_auto_alignment_preserves_an_explicit_ground_plane():
    from exercise_motion_pkg.models import MotionFrame
    frames = [MotionFrame(time_sec=index / 30., joints={
        'pelvis': (0., 0.4, 0.), 'neck': (0.8, 0.6, 0.),
        'left_hip': (0., 0.4, -0.1), 'right_hip': (0., 0.4, 0.1),
        'left_shoulder': (0.8, 0.6, -0.2), 'right_shoulder': (0.8, 0.6, 0.2),
        'left_foot': (0., 0., -0.1), 'right_foot': (0., 0., 0.1),
    }) for index in range(5)]
    rotations = preview._compute_preview_auto_alignment(frames, preserve_world_up=True)
    assert all(abs(axis[1]) > 0.999 for axis, angle in rotations)


def test_python_export_retains_explicit_floor_without_detected_contacts():
    from exercise_motion_pkg.models import MotionClip, MotionFrame
    joints = {'head': (0., 1.8, 0.), 'neck': (0., 1.6, 0.),
              'pelvis': (0., 1., 0.), 'left_foot': (-0.1, 0.8, 0.),
              'right_foot': (0.1, 0.8, 0.)}
    clip = MotionClip(fps=30., joint_names=list(joints),
                      frames=[MotionFrame(time_sec=index / 30., joints=dict(joints)) for index in range(5)],
                      metadata={'motionTuning': {'enabled': False}, 'ground': {
                          'renderGroundPlane': {'normal': [0., 1., 0.], 'offset': -0.2}}})
    exported = preview.build_wear_skeleton_payload(clip, title='Ground evidence', selected_loop_index=-1)
    assert exported['renderFloorY'] is not None
    assert exported['frames'][0]['joints']['left_foot'][1] - exported['renderFloorY'] == pytest.approx(0.6)


def test_anchor_relocation_distinguishes_sliding_from_relocated_contact_episodes(monkeypatch):
    frames = [{"joints": {
        "head": [0., 1.8, 0.], "pelvis": [0., 1., 0.],
        "left_foot": [0.14 * np.sin(np.pi * index / 20), 0., 0.],
    }} for index in range(21)]
    contact = {"jointName": "left_foot", "supportKind": "observed_foot_patch",
               "contactMotion": "stationary", "contactState": "full_sole",
               "anchorGroupId": "same-plant", "startFrame": 0, "endFrame": 20}
    monkeypatch.setattr(motion, 'source_contact_intervals_from_evidence', lambda *a, **k: [contact])
    metrics = motion.source_confirmed_support_stationarity_metrics({"frames": frames}, {})
    assert not metrics["sides"]["left"]["intervals"][0]["stationary"]
    assert metrics["rejectionReasons"] == ['left_source_confirmed_support_slides']
    # Distinct episodes with the same observed anchor still cannot relocate.
    contacts = [dict(contact, startFrame=0, endFrame=5), dict(contact, startFrame=15, endFrame=20)]
    for index, frame in enumerate(frames):
        frame["joints"]["left_foot"][0] = 0. if index < 10 else 0.3
    monkeypatch.setattr(motion, 'source_contact_intervals_from_evidence', lambda *a, **k: contacts)
    rejected = motion.source_confirmed_support_stationarity_metrics({"frames": frames}, {})
    assert 'left_source_confirmed_anchor_relocated' in rejected["rejectionReasons"]


@pytest.mark.parametrize('fails', [False, True])
def test_shared_discovery_prefilter_coordinates_gpu_handoff(monkeypatch, tmp_path, fails):
    from exercise_motion_pkg import youtube
    events = []

    class Session:
        def __init__(self, request):
            assert request.shared_llama_server
            events.append('attach')

        def run_without_llama_overlap(self, operation, **kwargs):
            assert kwargs['small_stage'] == 'yolo_pose_prefilter'
            events.append('admit')
            return operation()

        def close(self):
            events.append('close')

    def prefilter(**kwargs):
        events.append('pose')
        if fails:
            raise RuntimeError('pose failed')
        return SimpleNamespace(score=0.8, reasons=[], payload={})

    monkeypatch.setattr(motion, 'LazyLlamaCppVisionSession', Session)
    monkeypatch.setattr(youtube, 'download_youtube_preview', lambda *a, **k: tmp_path / 'input.mp4')
    monkeypatch.setattr(youtube, 'run_yolo_pose_prefilter', prefilter)
    monkeypatch.setattr(youtube, 'release_yolo_pose_cuda_memory', lambda: events.append('release'))
    settings = youtube.YouTubeRankingSettings(llama_cpp_shared_server=True)
    call = lambda: youtube.rank_candidate_with_yolo_pose(
        SimpleNamespace(name='Movement'), SimpleNamespace(url='source'), settings)
    if fails:
        with pytest.raises(RuntimeError, match='pose failed'):
            call()
    else:
        assert call()[0] == 0.8
    assert events == ['attach', 'admit', 'pose', 'release', 'close']


def test_refinement_does_not_start_a_block_too_short_for_a_measured_update():
    from exercise_motion_pkg.controlled_motion import stage_fit_refinement_budget
    assert stage_fit_refinement_budget(
        10., stage='C', minimum_update_seconds=10.8, prioritize_fit=False) is None
    assert stage_fit_refinement_budget(
        20., stage='B', minimum_update_seconds=10.8, prioritize_fit=True) >= 10.8


def test_default_vision_slots_have_room_for_observed_10104_token_request():
    assert DEFAULT_LLAMA_CPP_CTX_SIZE // DEFAULT_LLAMA_CPP_PARALLEL >= 16384


@pytest.mark.parametrize("name", ["workout_plan", "bake_and_rank", "youtube_bake_and_rank"])
def test_wrappers_preserve_context_headroom_when_parallelism_is_overridden(name):
    path = Path(__file__).resolve().parents[1] / f"scripts/run_exercise_motion_{name}.ps1"
    source = path.read_text(encoding="utf-8")
    assert re.search(r"\$LlamaCppParallel = 3,", source)
    escaped_path = str(path).replace("'", "''")
    command = f"""
    $ErrorActionPreference = 'Stop'
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', [ref]$tokens, [ref]$errors)
    if ($errors.Count) {{ throw ($errors | Out-String) }}
    $function = $ast.Find({{ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Ensure-LlamaCppParallelContext'
    }}, $true)
    . ([scriptblock]::Create($function.Extent.Text))
    function Get-LlamaCppParallelSlots {{ return $LlamaCppParallel }}
    $LlamaCppParallel = 6; $LlamaCppCtxSize = 49152; $LlamaCppFitCtx = 49152
    Ensure-LlamaCppParallelContext
    if ($LlamaCppCtxSize -lt 98304 -or $LlamaCppFitCtx -lt $LlamaCppCtxSize) {{ throw 'Insufficient per-slot context' }}
    """
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_validated_distinct_end_interval_is_bounded_without_optional_trim_metadata():
    loops = motion.build_candidate_review_eligible_loops(
        SimpleNamespace(fps=30.0, frame_count=61),
        source_interval_authority={
            "authoritative": True,
            "reason": "exact_pre_reconstruction_distinct_end_state_validated",
            "movementInstance": {"available": True, "trimmed": False, "reason": "proposed_interval_not_confirmed_complete"},
        },
    )
    assert len(loops) == 1
    assert loops[0].artifact_class == motion.BOUNDED_MOVEMENT_SELECTION
    assert loops[0].start_seconds == 0.0
    assert loops[0].end_seconds == 2.0


def test_nonterminal_artifact_rejection_cannot_keep_high_selection_score(tmp_path):
    item = motion.ReviewItem(
        exercise_index=0, candidate_rank=0, loop_index=-1,
        exercise_name="Bounded movement", candidate_title="Demo",
        candidate_workspace=tmp_path, preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json", review_video_path=tmp_path / "review.webm",
        duration_sec=2.0, loop_start_seconds=0.0, loop_end_seconds=2.0,
        candidate={"exerciseMotionContract": {"completionMode": "distinct_end_state"}},
        artifact_class=motion.FULL_CLIP_BAKE,
    )
    ranking = motion.LoopRanking(score=0.98, model_score=0.98, reasons=[], payload={"modelScore": 0.98})
    selected = motion.apply_materialized_output_acceptance_gate(
        (item, ranking),
        request=motion.BakeAndRankRequest(candidates_json=tmp_path / "candidates.json", workspace=tmp_path, body_model_root=None),
    )
    assert selected[1].payload["artifactClassGate"]["passed"] is False
    assert motion.selected_artifact_score(selected) == 0.0
    assert motion.materialized_output_was_rejected(selected)


def test_fit_exports_original_anatomy_reference_to_playback(monkeypatch):
    from exercise_motion_pkg import anatomical_repair, controlled_motion, rig_playback, scene_placement

    fixture = json.loads((Path(__file__).parent / "fixtures/sequence_stabilization_stance.json").read_text())
    names = list(fixture["joints"])
    source = np.tile(np.asarray(list(fixture["joints"].values())), (7, 1, 1))
    payload = {"fps": 30.0, "jointNames": names, "frames": [
        {"timeSec": index / 30.0, "joints": dict(zip(names, joints.tolist()))}
        for index, joints in enumerate(source)
    ]}
    monkeypatch.setattr(anatomical_repair, "repair_residuals", lambda *_args, **_kwargs: (np.ones((7, 1)), ["anatomy_spine_deviation:spine2"]))
    monkeypatch.setattr(anatomical_repair, "repair_rig_anatomy", lambda _rig, points, **_kwargs: (points + [0.02, 0.0, 0.0], {"passed": True, "applied": True}))
    observed = {}
    monkeypatch.setattr(scene_placement, "normalize_scene_placement", lambda candidate: candidate)

    class ReachedPlayback(Exception):
        pass

    def capture_playback(candidate):
        observed["reference"] = np.asarray([
            [frame["controlledArticulationReferenceJoints"][name] for name in names]
            for frame in candidate["frames"]
        ])
        raise ReachedPlayback

    monkeypatch.setattr(rig_playback, "validate_rig_playback", capture_playback)
    with pytest.raises(ReachedPlayback):
        controlled_motion._fit_controlled_motion_impl(payload, max_evaluations=1, timeout_seconds=30.0)
    np.testing.assert_allclose(observed["reference"], source, atol=1e-10)
