import copy
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import wave_pipeline as wave


@pytest.mark.parametrize("rigid_passes", [True, False])
@pytest.mark.parametrize("loop_required", [True, False])
def test_exact_source_contact_correction_preserves_range_and_baseline(tmp_path, monkeypatch, rigid_passes, loop_required):
    baseline = {"frames": [{"joints": {"left_ankle": [0, 0, 0]}}] * 10,
                "jointNames": ["left_ankle"], "frameCount": 10, "fps": 30}
    calls = []

    class Page:
        def goto(self, *args, **kwargs): pass
        def wait_for_function(self, *args): pass
        def evaluate(self, script, args=None):
            if args is None:
                return {"motionTuningEnabled": True}
            # Synthetic exact-source clips have no corresponding detected loop.
            assert args["explicitTimeRange"] is True
            assert "? window.exerciseMotionAutomation.bakeTimeRange" in script
            assert (args["startSeconds"], args["endSeconds"]) == (2.0, 5.0)
            calls.append(args["options"])
            result = copy.deepcopy(baseline)
            if args["options"].get("contactSequenceCorrection"):
                result["corrected"] = True
            return result

    class Context:
        def __enter__(self): return object()
        def __exit__(self, *args): pass

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Context)
    monkeypatch.setattr(bake, "launch_chromium_browser", lambda _: SimpleNamespace(
        new_page=lambda **kwargs: Page(), close=lambda: None))
    monkeypatch.setattr(bake, "stage_preview_for_browser_if_needed", lambda path: (path, None))
    monkeypatch.setattr(bake, "plan_adaptive_preview_settings_variants", lambda **kwargs: [
        {"id": "adaptive-baseline", "label": "Baseline", "options": {}}])
    monkeypatch.setattr(bake, "select_readable_preview_camera_options",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(bake, "deterministic_post_bake_scene_orientation_correction",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(bake, "constrain_baked_payload_to_source_articulation",
                        lambda payload, **kwargs: (payload, {}))
    monkeypatch.setattr(bake, "render_baked_wear_frames_with_playwright", lambda *args, **kwargs: ["frame"])
    monkeypatch.setattr(bake, "write_validated_review_video_from_data_urls",
                        lambda frames, path, **kwargs: (path, {"passed": True}))
    monkeypatch.setattr(bake, "fuse_reconstructed_support_evidence",
                        lambda payload, evidence: (evidence, {"applied": True}))
    monkeypatch.setattr(bake, "source_contact_intervals_from_evidence",
                        lambda evidence, **kwargs: [{"jointName": "left_ankle"}])
    monkeypatch.setattr(bake, "apply_source_contact_sequence_correction",
                        lambda payload, evidence: ({**copy.deepcopy(payload), "corrected": True}, {"applied": True}))
    monkeypatch.setattr(bake, "source_confirmed_support_stationarity_metrics",
                        lambda *args: {"passed": rigid_passes})
    monkeypatch.setattr(bake, "payload_loop_seam_joint_rms", lambda payload: 2 if payload.get("corrected") else 1)
    monkeypatch.setattr(bake, "exercise_requires_loop_continuity", lambda *args: loop_required)
    artifacts = bake.bake_preview_loops_with_playwright(
        tmp_path / "preview.html", [bake.EligibleLoop(0, {"type": "exact_source_movement_instance"}, 3, 2, 5)],
        tmp_path / "candidate", 6, adaptive_preview_settings=True, source_foot_support_evidence={})
    assert len(calls) == (1 if rigid_passes else 2)
    assert artifacts[0].settings_variant_id == "adaptive-baseline"
    assert len(artifacts) == (1 if loop_required else 2)
    if not rigid_passes:
        assert calls[-1]["contactSequenceCorrection"] is True


@pytest.mark.parametrize("status,failure_stage,expected", [
    ("rejected_raw_wham_validation", None, "raw_reconstruction_validation"),
    ("skipped_no_baked_clip", None, "baked_motion_validation"),
    ("failed", "browser_bake", "browser_bake"),
    ("failed", None, "processing_error"),
])
def test_final_diagnostics_distinguish_quality_from_processing_errors(status, failure_stage, expected):
    manifest = {"candidateResults": [{"status": status, "failureStage": failure_stage,
        "failures": [{"reason": "test_failure"}],
        "timings": {"previewBakeSeconds": 12.5, "nested": {"secret": 1}}}]}
    diagnostics = wave.final_processing_diagnostics(manifest)
    candidate = diagnostics["candidateDiagnostics"][0]
    assert candidate["stage"] == expected
    assert candidate["reasons"] == ["test_failure"]
    assert candidate["timings"] == {"previewBakeSeconds": 12.5}


def test_final_diagnostics_identify_model_rejection():
    diagnostics = wave.final_processing_diagnostics({
        "candidateResults": [{"status": "ready_for_selection"}],
        "timings": {"candidateSelectionAttempts": [{"rejectionReasons": ["final_output_model_rejected"]}],
                    "reviewRankingSeconds": 3.2}})
    assert diagnostics["candidateDiagnostics"][0]["stage"] == "model_review"
    assert diagnostics["reviewTimings"] == {"reviewRankingSeconds": 3.2}
