import copy
import json
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.controlled_motion import controlled_fit_processing_incomplete
from exercise_motion_pkg.source_outcomes import update_source_outcome_index
from exercise_motion_pkg.wave_pipeline import final_processing_diagnostics, wave_retry_disposition


@pytest.mark.parametrize("report,incomplete", [
    ({"applied": False, "reason": "fit_timeout"}, True),
    ({"applied": False, "reason": "no_validated_loop_cycle", "cycleSelectionAttempts": [
        {"fitReport": {"reason": "fit_timeout"}}]}, True),
    ({"applied": False, "reason": "fit_validation_failed"}, False),
    ({"applied": True, "reason": "validated_controlled_motion"}, False),
])
def test_fitting_deadline_is_distinct_from_completed_validation(report, incomplete):
    assert controlled_fit_processing_incomplete(report) is incomplete


def test_timeout_blocks_export_without_calling_unchanged_pose_a_kinematic_defect():
    joints = json.loads((Path(__file__).parent / "fixtures/sequence_stabilization_stance.json").read_text())["joints"]
    payload = {"fps": 30, "jointNames": list(joints), "frames": [
        {"timeSec": i / 30, "joints": copy.deepcopy(joints)} for i in range(12)]}
    before = bake.pre_render_deterministic_gate(payload, None)
    payload["controlledMotionFit"] = {"applied": False, "reason": "fit_timeout"}
    after = bake.pre_render_deterministic_gate(payload, None)
    assert after["kinematics"]["artifactReasons"] == before["kinematics"]["artifactReasons"]
    assert not after["passed"]
    assert "controlled_motion_processing_incomplete" in after["rejectionReasons"]
    assert "controlled_motion_processing_incomplete" in bake.blocking_materialized_kinematic_reasons(
        after["kinematics"], source_corroborated_joint_angle_step=False)


def test_incomplete_processing_preserves_source_and_resumes_processing(tmp_path):
    candidate = {"status": "needs_motion_processing", "candidate": {"videoId": "good-source"},
                 "reconstructionAttempted": True,
                 "failures": [{"reason": "controlled_motion_processing_incomplete"}]}
    bake.mark_parallel_candidate_final_selection_statuses(
        [candidate], [], selected=None, selected_results=[], rejected_best=None)
    assert candidate["finalSelectionStatus"] == "processing_incomplete"
    assert not bake.candidate_result_has_terminal_quality_decision(candidate)
    diagnostics = final_processing_diagnostics({"candidateResults": [candidate]})
    assert wave_retry_disposition({"finalValidation": {"status": "no_selection", **diagnostics}}) == "retry_processing"
    assert wave_retry_disposition(
        {"finalValidation": {"status": "incomplete_processing", **diagnostics}}
    ) == "retry_processing"
    from exercise_motion_pkg.wave_pipeline import final_validation_outcome_status
    assert final_validation_outcome_status({"candidateResults": [candidate]}) == "incomplete_processing"
    assert final_validation_outcome_status({"selected": {"candidate": {"videoId": "x"}}}) == "selected"
    assert final_validation_outcome_status({
        "candidateResults": [{"status": "rejected_baked_motion_validation",
                              "failures": [{"reason": "baked_motion_validation_failed"}]}]
    }) == "no_selection"
    index = tmp_path / "outcomes.json"
    assert update_source_outcome_index(index, [candidate]) is None
    assert not index.exists()


def test_sibling_variant_timeout_does_not_mask_applied_controlled_motion():
    applied = bake.BakedLoopArtifact(
        0, Path("a.json"), Path("a.webm"),
        {"controlledMotionFit": {"applied": True, "reason": "validated_controlled_motion"}},
    )
    timed_out = bake.BakedLoopArtifact(
        0, Path("b.json"), Path("b.webm"),
        {"controlledMotionFit": {"applied": False, "reason": "fit_timeout"}},
    )
    only_timeout = [timed_out]
    mixed = [applied, timed_out]

    def classify(artifacts):
        has_applied = any(
            isinstance(a.export_payload.get("controlledMotionFit"), dict)
            and a.export_payload["controlledMotionFit"].get("applied")
            for a in artifacts
        )
        return (not has_applied) and any(
            controlled_fit_processing_incomplete(a.export_payload.get("controlledMotionFit"))
            for a in artifacts
        )

    assert classify(only_timeout) is True
    assert classify(mixed) is False


def test_bounded_processing_retry_refits_after_incomplete_prefetch(monkeypatch):
    from exercise_motion_pkg import stage_cache
    from exercise_motion_pkg.wave_pipeline import finalize_with_bounded_processing_retry

    attempts = []
    initial_attempt = stage_cache.PROCESSING_ATTEMPT_ID

    def operation():
        attempts.append(stage_cache.PROCESSING_ATTEMPT_ID)
        if len(attempts) == 1:
            return {
                "selected": None,
                "candidateResults": [{
                    "status": "needs_motion_processing",
                    "failures": [{"reason": "controlled_motion_processing_incomplete"}],
                    # Prefetch handoff without a fully exhausted session still retries.
                    "candidateFitBudget": {"seconds": 360.0, "remainingSeconds": 120.0, "fitCalls": 1},
                    "controlledMotionFit": {
                        "applied": False,
                        "reason": "fit_timeout",
                        "candidateFitBudget": {"seconds": 360.0, "remainingSeconds": 120.0, "fitCalls": 1},
                    },
                }],
            }
        return {
            "selected": {"candidate": {"videoId": "kept"}},
            "candidateResults": [{"status": "ready_for_selection"}],
        }

    manifest = finalize_with_bounded_processing_retry(operation)
    assert manifest.get("selected")
    assert manifest["processingAttemptCount"] == 2
    assert len(attempts) == 2
    assert attempts[0] == initial_attempt
    assert attempts[1] != initial_attempt
    assert stage_cache.PROCESSING_ATTEMPT_ID == attempts[1]


def test_bounded_processing_retry_skips_exhausted_candidate_session(monkeypatch):
    from exercise_motion_pkg import stage_cache
    from exercise_motion_pkg.wave_pipeline import finalize_with_bounded_processing_retry

    attempts = []
    initial_attempt = stage_cache.PROCESSING_ATTEMPT_ID

    def operation():
        attempts.append(stage_cache.PROCESSING_ATTEMPT_ID)
        return {
            "selected": None,
            "candidateResults": [{
                "status": "needs_motion_processing",
                "failures": [{"reason": "controlled_motion_processing_incomplete"}],
                "candidateFitBudget": {"seconds": 360.0, "remainingSeconds": 0.0, "fitCalls": 1},
                "controlledMotionFit": {
                    "applied": False,
                    "reason": "no_validated_loop_cycle",
                    "candidateFitBudget": {"seconds": 360.0, "remainingSeconds": 0.0, "fitCalls": 1},
                    "cycleSelectionAttempts": [{"fitReport": {"reason": "fit_timeout"}}],
                },
            }],
        }

    manifest = finalize_with_bounded_processing_retry(operation)
    assert manifest.get("selected") is None
    assert manifest["processingAttemptCount"] == 1
    assert manifest["processingRetrySkippedReason"] == "candidate_fit_session_exhausted"
    assert attempts == [initial_attempt]
    assert stage_cache.PROCESSING_ATTEMPT_ID == initial_attempt


def test_bounded_processing_retry_skips_near_exhausted_candidate_session(monkeypatch):
    from exercise_motion_pkg import stage_cache
    from exercise_motion_pkg.wave_pipeline import finalize_with_bounded_processing_retry

    attempts = []
    initial_attempt = stage_cache.PROCESSING_ATTEMPT_ID

    def operation():
        attempts.append(stage_cache.PROCESSING_ATTEMPT_ID)
        return {
            "selected": None,
            "candidateResults": [{
                "status": "needs_motion_processing",
                "failures": [{"reason": "controlled_motion_processing_incomplete"}],
                "candidateFitBudget": {"seconds": 360.0, "remainingSeconds": 4.8, "fitCalls": 1},
                "controlledMotionFit": {
                    "applied": False,
                    "reason": "no_validated_loop_cycle",
                    "candidateFitBudget": {"seconds": 360.0, "remainingSeconds": 4.8, "fitCalls": 1},
                    "cycleSelectionAttempts": [{"fitReport": {"reason": "fit_timeout"}}],
                },
            }],
        }

    manifest = finalize_with_bounded_processing_retry(operation)
    assert manifest.get("selected") is None
    assert manifest["processingAttemptCount"] == 1
    assert manifest["processingRetrySkippedReason"] == "candidate_fit_session_exhausted"
    assert attempts == [initial_attempt]
    assert stage_cache.PROCESSING_ATTEMPT_ID == initial_attempt


def test_incomplete_controlled_fit_skips_adaptive_planner_and_review_encode(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import copy

    baseline = {
        "frames": [{"timeSec": i / 30, "joints": {"left_ankle": [0, 0, 0]},
                    "sourceJoints": {"left_ankle": [0, 0, 0]}} for i in range(6)],
        "jointNames": ["left_ankle"], "fps": 30,
    }

    class Page:
        def goto(self, *args, **kwargs):
            pass

        def wait_for_function(self, *args):
            pass

        def evaluate(self, script, args=None):
            if args is None:
                return {"motionTuningEnabled": True}
            return copy.deepcopy(baseline)

    class Context:
        def __enter__(self):
            return SimpleNamespace(new_page=lambda **kwargs: Page(), close=lambda: None)

        def __exit__(self, *args):
            pass

    planner_calls = []
    render_calls = []

    def fail_planner(**kwargs):
        planner_calls.append(kwargs)
        raise AssertionError("adaptive planner must not run before/after incomplete fit")

    monkeypatch.setattr(bake, "browser_session", lambda launch: Context())
    monkeypatch.setattr(bake, "stage_preview_for_browser_if_needed", lambda path: (path, None))
    monkeypatch.setattr(bake, "plan_adaptive_preview_settings_variants", fail_planner)
    monkeypatch.setattr(bake, "select_readable_preview_camera_options",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(bake, "deterministic_post_bake_scene_orientation_correction",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(
        bake,
        "constrain_baked_payload_to_source_articulation",
        lambda payload, **kwargs: (
            {**payload, "controlledMotionFit": {"applied": False, "reason": "fit_timeout"}},
            {},
        ),
    )
    monkeypatch.setattr(
        bake,
        "render_prechecked_baked_artifacts",
        lambda *args, **kwargs: render_calls.append(True) or (_ for _ in ()).throw(
            AssertionError("review encode must not run for incomplete fit")
        ),
    )
    monkeypatch.setattr(
        bake,
        "pre_render_deterministic_gate",
        lambda payload, reference: {
            "passed": False,
            "rejectionReasons": ["controlled_motion_processing_incomplete"],
        },
    )
    monkeypatch.setattr(bake, "load_verified_source_pose_reference", lambda *args, **kwargs: None)

    (tmp_path / "preview.html").write_text("html")
    artifacts = bake._bake_preview_loops_with_playwright_uncached(
        tmp_path / "preview.html",
        [bake.EligibleLoop(-1, {}, 6, 0, 6), bake.EligibleLoop(0, {}, 3, 0, 3)],
        tmp_path / "candidate",
        6,
        adaptive_preview_settings=True,
    )
    assert planner_calls == []
    assert render_calls == []
    assert len(artifacts) == 1
    assert artifacts[0].settings_variant_id == "adaptive-baseline"
    assert artifacts[0].export_payload["controlledMotionFit"]["reason"] == "fit_timeout"
    assert "preRenderDeterministicGate" in artifacts[0].export_payload


def test_failed_validation_fit_stops_extra_preview_loops(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import copy

    baseline = {
        "frames": [{"timeSec": i / 30, "joints": {"left_ankle": [0, 0, 0]},
                    "sourceJoints": {"left_ankle": [0, 0, 0]}} for i in range(6)],
        "jointNames": ["left_ankle"], "fps": 30,
    }

    class Page:
        def goto(self, *args, **kwargs):
            pass

        def wait_for_function(self, *args):
            pass

        def evaluate(self, script, args=None):
            if args is None:
                return {"motionTuningEnabled": True}
            return copy.deepcopy(baseline)

    class Context:
        def __enter__(self):
            return SimpleNamespace(new_page=lambda **kwargs: Page(), close=lambda: None)

        def __exit__(self, *args):
            pass

    constrain_calls = []
    monkeypatch.setattr(bake, "browser_session", lambda launch: Context())
    monkeypatch.setattr(bake, "stage_preview_for_browser_if_needed", lambda path: (path, None))
    monkeypatch.setattr(bake, "plan_adaptive_preview_settings_variants",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("planner")))
    monkeypatch.setattr(bake, "select_readable_preview_camera_options",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(bake, "deterministic_post_bake_scene_orientation_correction",
                        lambda payload, options: (options, {}, False))

    def constrain(payload, **kwargs):
        constrain_calls.append(True)
        return (
            {**payload, "controlledMotionFit": {
                "applied": False,
                "reason": "fit_validation_failed",
                "checks": {"trajectoryFit": False, "rootTravel": False},
            }},
            {},
        )

    monkeypatch.setattr(bake, "constrain_baked_payload_to_source_articulation", constrain)
    monkeypatch.setattr(
        bake,
        "render_prechecked_baked_artifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("review encode")),
    )
    monkeypatch.setattr(
        bake,
        "pre_render_deterministic_gate",
        lambda payload, reference: {"passed": False, "rejectionReasons": ["fit_validation_failed"]},
    )
    monkeypatch.setattr(bake, "load_verified_source_pose_reference", lambda *args, **kwargs: None)
    (tmp_path / "preview.html").write_text("html")
    artifacts = bake._bake_preview_loops_with_playwright_uncached(
        tmp_path / "preview.html",
        [bake.EligibleLoop(-1, {}, 6, 0, 6), bake.EligibleLoop(0, {}, 3, 0, 3)],
        tmp_path / "candidate",
        6,
        adaptive_preview_settings=True,
    )
    assert len(constrain_calls) == 1
    assert len(artifacts) == 1
    assert artifacts[0].export_payload["controlledMotionFit"]["reason"] == "fit_validation_failed"


def test_timed_out_bake_reuses_prefetch_but_retries_on_next_run(tmp_path, monkeypatch):
    from exercise_motion_pkg import stage_cache
    preview = tmp_path / "preview.html"
    preview.write_text("fixture")
    skeleton = tmp_path / "skeleton.json"
    calls = []
    def render(*args, **kwargs):
        calls.append(True)
        payload = {"frames": [], "controlledMotionFit": {"reason": "fit_timeout", "applied": False},
                   "preRenderDeterministicGate": {"passed": False}}
        skeleton.write_text(json.dumps(payload))
        return [bake.BakedLoopArtifact(0, skeleton, tmp_path / "absent.webm", payload)]
    monkeypatch.setattr(bake, "_bake_preview_loops_with_playwright_uncached", render)
    args = (preview, [bake.EligibleLoop(0, {}, 1, 0, 1)], tmp_path, 6)
    bake.bake_preview_loops_with_playwright(*args)
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 1
    # One-shot incomplete reuse is consumed after the prefetch→final handoff.
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 2
    monkeypatch.setattr(stage_cache, "PROCESSING_ATTEMPT_ID", "next-process")
    bake.bake_preview_loops_with_playwright(*args)
    assert len(calls) == 3


def test_pre_fit_fidelity_skips_when_source_joints_already_fail(monkeypatch):
    payload = {
        "frames": [{
            "timeSec": 0.0,
            "joints": {"left_wrist": [0.0, 0.0, 0.0]},
            "sourceJoints": {"left_wrist": [1.0, 0.0, 0.0]},
        }],
        "jointNames": ["left_wrist"],
    }
    monkeypatch.setattr(
        bake,
        "materialized_source_pose_fidelity_metrics",
        lambda **kwargs: {
            "available": True,
            "passed": False,
            "rejectionReasons": ["materialized_source_endpoint_pose_mismatch"],
        },
    )
    monkeypatch.setattr(bake, "source_pose_reference_for_motion", lambda source, motion: source)
    rejected = bake.pre_fit_source_articulation_fidelity_rejection(
        payload, {"frames": [{"timeSec": 0.0, "joints": {"left_wrist": [0.0, 0.0, 0.0]}}]},
    )
    assert rejected is not None
    assert "materialized_source_endpoint_pose_mismatch" in rejected["rejectionReasons"]


def test_pre_fit_fidelity_does_not_skip_when_only_browser_joints_would_fail(monkeypatch):
    calls = []

    def fidelity(*, output_motion_payload, **kwargs):
        joints = output_motion_payload["frames"][0]["joints"]
        calls.append(joints)
        # Fail only if the probe still has the bad browser IK joints.
        if joints.get("left_wrist") == [9.0, 9.0, 9.0]:
            return {
                "available": True,
                "passed": False,
                "rejectionReasons": ["materialized_source_endpoint_pose_mismatch"],
            }
        return {"available": True, "passed": True, "rejectionReasons": []}

    monkeypatch.setattr(bake, "materialized_source_pose_fidelity_metrics", fidelity)
    monkeypatch.setattr(bake, "source_pose_reference_for_motion", lambda source, motion: source)
    payload = {
        "frames": [{
            "timeSec": 0.0,
            "joints": {"left_wrist": [9.0, 9.0, 9.0]},
            "sourceJoints": {"left_wrist": [0.0, 0.0, 0.0]},
        }],
        "jointNames": ["left_wrist"],
    }
    assert bake.pre_fit_source_articulation_fidelity_rejection(
        payload, {"frames": [{"timeSec": 0.0, "joints": {"left_wrist": [0.0, 0.0, 0.0]}}]},
    ) is None
    assert calls and calls[0]["left_wrist"] == [0.0, 0.0, 0.0]


def test_pre_fit_fidelity_unavailable_does_not_skip_fit(monkeypatch):
    monkeypatch.setattr(
        bake,
        "materialized_source_pose_fidelity_metrics",
        lambda **kwargs: {
            "available": False,
            "passed": False,
            "rejectionReasons": ["materialized_source_pose_fidelity_unavailable"],
        },
    )
    monkeypatch.setattr(bake, "source_pose_reference_for_motion", lambda source, motion: source)
    payload = {
        "frames": [{
            "timeSec": 0.0,
            "joints": {"left_wrist": [0.0, 0.0, 0.0]},
            "sourceJoints": {"left_wrist": [0.0, 0.0, 0.0]},
        }],
    }
    assert bake.pre_fit_source_articulation_fidelity_rejection(payload, {"frames": []}) is None


def test_bake_skips_constrain_when_pre_fit_fidelity_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import copy

    baseline = {
        "frames": [{
            "timeSec": i / 30,
            "joints": {"left_ankle": [0, 0, 0]},
            "sourceJoints": {"left_ankle": [1, 0, 0]},
        } for i in range(6)],
        "jointNames": ["left_ankle"],
        "fps": 30,
    }

    class Page:
        def goto(self, *args, **kwargs):
            pass

        def wait_for_function(self, *args):
            pass

        def evaluate(self, script, args=None):
            if args is None:
                return {"motionTuningEnabled": True}
            return copy.deepcopy(baseline)

    class Context:
        def __enter__(self):
            return SimpleNamespace(new_page=lambda **kwargs: Page(), close=lambda: None)

        def __exit__(self, *args):
            pass

    constrain_calls = []
    pre_fit_camera_references = []
    camera = {'available': True, 'cameraImageTransform': [1, 0, 0, 0, 0, 0]}
    cleaned_dir = tmp_path / 'candidate' / 'cleaned'
    cleaned_dir.mkdir(parents=True)
    (cleaned_dir / 'motion.cleaned.json').write_text(json.dumps({
        'frames': baseline['frames'], 'metadata': {'structuralRefinement': {
            'sourceGuidedArticulation': {'cameraRegistration': camera}}}}))
    monkeypatch.setattr(bake, "browser_session", lambda launch: Context())
    monkeypatch.setattr(bake, "stage_preview_for_browser_if_needed", lambda path: (path, None))
    monkeypatch.setattr(bake, "plan_adaptive_preview_settings_variants",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("planner")))
    monkeypatch.setattr(bake, "select_readable_preview_camera_options",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(bake, "deterministic_post_bake_scene_orientation_correction",
                        lambda payload, options: (options, {}, False))
    monkeypatch.setattr(
        bake,
        "pre_fit_source_articulation_fidelity_rejection",
        lambda payload, reference: pre_fit_camera_references.append(payload.get('sourcePoseCameraReference')) or {
            "available": True,
            "passed": False,
            "rejectionReasons": ["materialized_source_endpoint_pose_mismatch"],
        },
    )
    monkeypatch.setattr(
        bake,
        "constrain_baked_payload_to_source_articulation",
        lambda *args, **kwargs: constrain_calls.append(True) or (_ for _ in ()).throw(
            AssertionError("fit must be skipped")
        ),
    )
    monkeypatch.setattr(
        bake,
        "render_prechecked_baked_artifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("review encode")),
    )
    monkeypatch.setattr(bake, "load_verified_source_pose_reference", lambda *args, **kwargs: {"frames": []})
    (tmp_path / "preview.html").write_text("html")
    artifacts = bake._bake_preview_loops_with_playwright_uncached(
        tmp_path / "preview.html",
        [bake.EligibleLoop(-1, {}, 6, 0, 6)],
        tmp_path / "candidate",
        6,
        adaptive_preview_settings=True,
    )
    assert constrain_calls == []
    assert pre_fit_camera_references[0]['camera'] == camera
    assert len(artifacts) == 1
    assert artifacts[0].export_payload["controlledMotionFit"]["reason"] == (
        "pre_fit_source_articulation_fidelity_failed"
    )
