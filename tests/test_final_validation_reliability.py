import copy
import json
import shutil
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake, pose_fidelity as pose
from exercise_motion_pkg.acceptance import decide_acceptance
from exercise_motion_pkg.review_consensus import corroborate_rejection
from exercise_motion_pkg.visual_evidence import localize_review_evidence, diagnostic_frame_indices


def evidence(defect="torso_twist", region="torso", indices=None):
    return {"passed": False, "reject": ["gross_pose_reconstruction_error"],
            "failureOwner": "motion_output", "modelPayload": {"rejectionEvidence": [{
                "tag": "gross_pose_reconstruction_error", "basis": "body_motion",
                "defectType": defect, "bodyRegion": region,
                "frameIndices": indices if indices is not None else [4],
                "bodyRelation": {"subject": "torso", "reference": "pelvis", "relation": "rotated_relative_to"},
                "observation": "A concrete visible defect."}]}}


def torso_export():
    return {"frames": [{"joints": {"left_shoulder": [-.2, 1., 0.],
        "right_shoulder": [.2, 1., 0.], "left_hip": [-.2, .5, 0.],
        "right_hip": [.2, .5, 0.]}} for _ in range(20)]}


def test_matching_tag_different_defects_do_not_corroborate():
    export = torso_export()
    a = localize_review_evidence(evidence("limb_geometry", "left_arm"), export, [4])
    b = localize_review_evidence(evidence("limb_geometry", "left_leg"), export, [4])
    result = corroborate_rejection(a, lambda: b)
    assert not result["boundedReview"]["corroborated"]
    assert result["failureOwner"] == "review"
    assert not result["needsRetry"]


def test_same_defect_different_frames_is_not_agreement():
    export = torso_export()
    a = localize_review_evidence(evidence("limb_geometry", "left_arm", [4]), export, [4, 10])
    b = localize_review_evidence(evidence("limb_geometry", "left_arm", [10]), export, [4, 10])
    assert not corroborate_rejection(a, lambda: b)["boundedReview"]["corroborated"]


def test_localized_matching_claim_can_remain_rejected():
    export = torso_export()
    a = localize_review_evidence(evidence("limb_geometry", "left_arm"), export, [4])
    result = corroborate_rejection(a, lambda: copy.deepcopy(a))
    assert result["boundedReview"]["corroborated"]
    assert result["hardRejectionReasons"] == ["gross_pose_reconstruction_error"]


@pytest.mark.parametrize("indices", [[-1], [99], [True], [3], []])
def test_invented_or_unshown_samples_cannot_support_rejection(indices):
    result = localize_review_evidence(evidence(indices=indices), torso_export(), [4])
    assert not result["localizedClaims"]


def test_skeletal_twist_contradiction_does_not_approve_or_regenerate():
    review = localize_review_evidence(evidence(), torso_export(), [4])
    assert review["localizedClaims"][0]["status"] == "contradicted"
    result = corroborate_rejection(review, lambda: review)
    assert result["reviewStatus"] == "needs_manual_review"
    assert not result["passed"] and not result["underlyingMotionRejected"]


def test_mesh_defect_not_cleared_by_straight_skeleton():
    review = localize_review_evidence(evidence("render_corruption"), torso_export(), [4])
    assert review["localizedClaims"][0]["status"] == "observed"
    assert review["failureOwner"] == "rendering"


def test_diagnostic_samples_are_bounded_and_include_neighbors():
    review = localize_review_evidence(evidence("limb_geometry", "left_arm", [4, 18]), torso_export(), [4, 18])
    assert diagnostic_frame_indices(review, 20) == [2, 3, 4, 5, 6, 16, 17, 18, 19]


def test_whole_sequence_claim_still_gets_dense_diagnostic_evidence():
    review = {"localizedClaims": [{"frameIndices": list(range(0, 124, 8))}]}
    indices = diagnostic_frame_indices(review, 124)
    assert len(indices) <= 16 and any(b-a == 1 for a, b in zip(indices, indices[1:]))
    assert 0 in indices and 120 in indices


def test_omitted_prop_in_approval_note_is_not_a_contradiction():
    assert bake.final_output_validator_note_conflict_reasons(
        {"approved": True, "note": "The action matches; the implement is not visible."}) == []
    assert bake.final_output_validator_note_conflict_reasons(
        {"approved": True, "note": "This is a different exercise."})


@pytest.mark.parametrize("reason", ["materialized_kinematic_metrics_unavailable",
                                    "materialized_paired_hands_metrics_unavailable"])
def test_required_metric_exception_never_approves_or_regenerates(reason):
    result = decide_acceptance({"passed": True, "skippedReasons": [reason]}, {"passed": True},
                               deterministic_rejections=[], review_rejections=[])
    assert result.status == "needs_manual_review" and not result.can_regenerate_motion


def test_missing_required_check_skips_expensive_visual_review():
    def forbidden(*args, **kwargs):
        pytest.fail("Missing numerical evidence must not invoke the VLM")
    result = bake.final_output_validation_metrics(None, None,
        request=SimpleNamespace(final_output_validation=True),
        deterministic_metrics={"passed": True, "kinematicPlausibilityMetrics": bake.empty_kinematic_plausibility_metrics()},
        caption_images=forbidden)
    assert result["reviewStatus"] == "needs_manual_review"


def test_full_fidelity_gate_ignores_end_on_angle_noise():
    joints = {}
    for side, sign in (("left", -1), ("right", 1)):
        joints.update({f"{side}_shoulder": (sign*.25, 1.5, 0),
                       f"{side}_hip": (sign*.2, .9, 0), f"{side}_knee": (sign*.2, .45, 0),
                       f"{side}_ankle": (sign*.2, 0, 0),
                       f"{side}_elbow": (sign*.25+.005, 1.5, .3),
                       f"{side}_wrist": (sign*.25+.3, 1.4, .3)})
    observed = {name: (point[0], -point[1]) for name, point in joints.items()}
    for side in ("left", "right"):
        x, y = observed[f"{side}_shoulder"]
        observed[f"{side}_elbow"] = (x, y+.005)
    source = {"frames": [{"sourceTimeSec": i/30, "joints": observed} for i in range(10)]}
    output = {"frames": [{"timeSec": i/30, "joints": joints} for i in range(10)]}
    result = bake.materialized_source_pose_fidelity_metrics(
        source_pose_payload=source, output_motion_payload=output, required=True)
    assert result["passed"], result["rejectionReasons"]
    assert result["p90JointErrorBodyRatio"] < .005


def test_angle_rejection_needs_spatial_support_and_independent_limbs():
    metrics = {"p90JointAngleErrorDegrees": 90., "perAngleMedianErrorDegrees": {
        "left_shoulder": 90., "left_elbow": 90.},
        "perJointMedianErrorBodyRatio": {"left_elbow": .3}}
    assert not bake.source_pose_angle_mismatch_is_corroborated(metrics, threshold_degrees=75)
    metrics["perAngleMedianErrorDegrees"]["right_elbow"] = 90.
    assert not bake.source_pose_angle_mismatch_is_corroborated(metrics, threshold_degrees=75)
    metrics["perJointMedianErrorBodyRatio"]["right_elbow"] = .3
    assert bake.source_pose_angle_mismatch_is_corroborated(metrics, threshold_degrees=75)


def test_explicit_low_confidence_is_excluded_from_camera_and_pose_evidence():
    source = {"frames": [{"sourceTimeSec": 0, "joints": {
        "left_elbow": [2, 2], "left_hip": [0, 1]}, "jointConfidence": {"left_elbow": .1}}]}
    frames = pose._pose_frames(source, source=True)
    assert "left_elbow" not in frames[0]["joints"]
    assert "left_hip" in frames[0]["joints"]


def test_final_prompt_is_blind_to_selection_score_and_limits_temporal_claims(monkeypatch):
    monkeypatch.setattr(bake, "exercise_motion_contract_for_review_item", lambda *a: {})
    prompt = bake.build_final_output_validation_prompt(item=SimpleNamespace(exercise_name="Movement"),
        ranking=SimpleNamespace(score=.999, payload={}), has_source_context=False, min_score=.9)
    assert "0.999" not in prompt and "Previous selection score" not in prompt
    assert "sparse pose samples" in prompt and "frameIndices" in prompt


@pytest.mark.parametrize("reject", [False, True])
def test_visual_observer_ignores_verdict_fields_and_reuses_exact_artifact_cache(tmp_path, monkeypatch, reject):
    export = torso_export()
    export.update(frameCount=20, fps=30)
    for i, frame in enumerate(export["frames"]):
        frame["timeSec"] = i/30
    skeleton = tmp_path / "skeleton.json"
    skeleton.write_text(json.dumps(export))
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"mock-render")
    item = bake.ReviewItem(exercise_index=0, candidate_rank=0, loop_index=-1,
        exercise_name="Test movement", candidate_title="Unused title", candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html", skeleton_path=skeleton,
        review_video_path=tmp_path / "preview.webm", duration_sec=19/30,
        loop_start_seconds=0., loop_end_seconds=19/30, candidate={})
    item.settings_options["reviewFrameIndices"] = [1, 7, 19]
    monkeypatch.setattr(bake, "exercise_motion_contract_for_review_item", lambda *a: {})
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **kw: pytest.fail("Unused source render"))
    monkeypatch.setattr(bake, "final_output_preview_contact_sheets", lambda *a, **kw: [sheet])
    diagnostic = []
    def render_targeted(item, **kw):
        diagnostic.append(item.settings_options)
        return [sheet]
    monkeypatch.setattr(bake, "final_output_vlm_preview_contact_sheets", render_targeted)
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        # Frame 4 occurs in both the primary and targeted manifest.
        payload = evidence("limb_geometry", "left_arm")["modelPayload"] if reject else {}
        payload.update(findings=[], approved=not reject, confidence=.95, retry=reject,
                       reject=["gross_pose_reconstruction_error"] if reject else [], note="Observed result.")
        return json.dumps(payload)
    request = bake.BakeAndRankRequest(candidates_json=tmp_path / "candidates.json", workspace=tmp_path,
        body_model_root=None, final_output_validation=True, two_scale_source_validation=False)
    result = bake.validate_final_output_with_caption_images(item, bake.LoopRanking(.9, [], {}),
        request=request, caption_images=caption, deterministic_metrics={"passed": True})
    assert len(calls) == 1
    assert result["advisoryOnly"] and result["status"] == "observed"
    assert "passed" not in result and "reject" not in result and not diagnostic
    assert 'Cell-to-frame manifest (same in both views): {"1": 1, "2": 7, "3": 19}' in calls[0]["prompt"]
    cached = bake.validate_final_output_with_caption_images(item, bake.LoopRanking(.9, [], {}),
        request=request, caption_images=caption, deterministic_metrics={"passed": True})
    assert cached["cacheStatus"] == "reused"
    assert len(calls) == 1
    # Equal-looking sheets cannot reuse a verdict for different underlying geometry.
    export["frames"][0]["joints"]["left_shoulder"][0] -= .01
    skeleton.write_text(json.dumps(export))
    bake.validate_final_output_with_caption_images(item, bake.LoopRanking(.9, [], {}),
        request=request, caption_images=caption, deterministic_metrics={"passed": True})
    assert len(calls) == 2


@pytest.mark.parametrize("chooser_name", ["choose_best_materialized_review_item", "choose_top_materialized_review_items"])
def test_materialized_gate_results_are_retained_for_every_review_item(tmp_path, monkeypatch, chooser_name):
    items = [
        bake.ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=3,
            exercise_name="Press",
            candidate_title="Press demo",
            candidate_workspace=tmp_path,
            preview_html_path=tmp_path / "preview.html",
            skeleton_path=tmp_path / "cyclic.json",
            review_video_path=tmp_path / "cyclic.webm",
            duration_sec=2.,
            loop_start_seconds=0.,
            loop_end_seconds=2.,
            candidate={},
            artifact_class="cyclic_rebake",
        ),
        bake.ReviewItem(
            exercise_index=0,
            candidate_rank=0,
            loop_index=-1,
            exercise_name="Press",
            candidate_title="Press demo",
            candidate_workspace=tmp_path,
            preview_html_path=tmp_path / "preview.html",
            skeleton_path=tmp_path / "full.json",
            review_video_path=tmp_path / "full.webm",
            duration_sec=9.,
            loop_start_seconds=0.,
            loop_end_seconds=9.,
            candidate={},
            artifact_class="full_clip_bake",
        ),
    ]
    rankings = [
        bake.LoopRanking(.923, [], model_score=.923, payload={"item": "cyclic"}),
        bake.LoopRanking(.49, [], model_score=.49, payload={"item": "full"}),
    ]

    def reject_with_persistable_evidence(original, **_kwargs):
        item, ranking = original
        reason = "final_render_evidence_unavailable" if item.loop_index == 3 else "artifact_class_not_accepted"
        updated = bake.LoopRanking(
            score=.49,
            reasons=ranking.reasons,
            payload={
                **(ranking.payload or {}),
                "finalOutputValidation": {"passed": False, "rejectionReasons": [reason]},
            },
            model_score=ranking.model_score,
        )
        return None, (item, updated)

    monkeypatch.setattr(bake, "materialize_selection_candidate", reject_with_persistable_evidence)
    request = SimpleNamespace(min_selected_score=.5, max_selected_results=1)
    chooser = getattr(bake, chooser_name)
    if chooser_name == "choose_best_materialized_review_item":
        chooser(items, rankings, request=request)
    else:
        chooser(items, rankings, request=request, max_results=1)

    assert rankings[0].payload["finalOutputValidation"]["rejectionReasons"] == [
        "final_render_evidence_unavailable"
    ]
    assert rankings[1].payload["finalOutputValidation"]["rejectionReasons"] == [
        "artifact_class_not_accepted"
    ]


def test_final_review_preview_uses_short_content_keyed_runtime_path(tmp_path, monkeypatch):
    from exercise_motion_pkg import preview as preview_module

    candidate_workspace = tmp_path / ("nested-" * 10) / "candidate"
    preview_dir = candidate_workspace / "preview"
    wear_dir = candidate_workspace / "wear"
    preview_dir.mkdir(parents=True)
    wear_dir.mkdir(parents=True)
    original_preview = preview_dir / "original.html"
    original_preview.write_text("<html></html>", encoding="utf-8")
    module = preview_dir / "three.module.0.169.0.js"
    module.write_text("export {};", encoding="utf-8")
    skeleton = wear_dir / "skeleton.json"
    skeleton.write_text(json.dumps({
        "fps": 30,
        "jointNames": ["pelvis"],
        "frames": [{"timeSec": 0., "joints": {"pelvis": [0., 0., 0.]}}],
    }), encoding="utf-8")
    item = bake.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=0,
        exercise_name="Test movement",
        candidate_title="Unused title",
        candidate_workspace=candidate_workspace,
        preview_html_path=original_preview,
        skeleton_path=skeleton,
        review_video_path=preview_dir / "review.webm",
        duration_sec=1.,
        loop_start_seconds=0.,
        loop_end_seconds=1.,
        candidate={},
    )
    temp_root = tmp_path / "short-temp"
    monkeypatch.setattr(bake.tempfile, "gettempdir", lambda: str(temp_root))
    writes = []

    def write_runtime(path, payload, *, three_module_path=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html>current skeleton</html>", encoding="utf-8")
        if three_module_path is not None:
            shutil.copy2(three_module_path, path.parent / three_module_path.name)
        writes.append(path)

    rendered_previews = []

    def render_preview_window(*, item, **_kwargs):
        rendered_previews.append(item.preview_html_path)
        return [tmp_path / "sheet.jpg"]

    monkeypatch.setattr(preview_module, "write_baked_preview_html", write_runtime)
    monkeypatch.setattr(bake, "render_review_window_contact_sheet", render_preview_window)
    bake.final_output_vlm_preview_contact_sheets(item, output_dir=tmp_path / "review-output")

    current_preview = rendered_previews[0]
    assert current_preview.is_file()
    assert current_preview.parent.parent == temp_root / "mwa-motion-preview"
    assert len(str(current_preview.resolve())) < len(str(skeleton.resolve()))
    assert (current_preview.parent / module.name).is_file()
    assert rendered_previews == [current_preview, current_preview]
    assert writes == [current_preview]


def test_baked_reselection_persists_materialized_validation_evidence(tmp_path, monkeypatch):
    item = bake.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=3,
        exercise_name="Press",
        candidate_title="Press demo",
        candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html",
        skeleton_path=tmp_path / "skeleton.json",
        review_video_path=tmp_path / "review.webm",
        duration_sec=2.,
        loop_start_seconds=0.,
        loop_end_seconds=2.,
        candidate={},
        artifact_class="cyclic_rebake",
    )
    item.skeleton_path.write_text("{}", encoding="utf-8")
    original = bake.LoopRanking(.923, [], payload={"origin": "saved-ranking"})
    entry = bake.review_item_to_manifest(item)
    entry["ranking"] = bake.ranking_to_manifest(original)
    selection_path = tmp_path / "selection_manifest.json"
    selection_path.write_text(json.dumps({"reviewItems": [entry], "candidateResults": []}), encoding="utf-8")
    request = SimpleNamespace(min_selected_score=.5, max_selected_results=1, final_output_validation=True)

    monkeypatch.setattr(bake, "bake_and_rank_request_from_selection_manifest", lambda *args, **kwargs: request)
    monkeypatch.setattr(bake, "apply_loop_continuity_adjustment", lambda item, ranking: (item, ranking))

    def validate(artifact, **_kwargs):
        artifact_item, _ranking = artifact
        return artifact_item, bake.LoopRanking(
            .49,
            ["materialized_output_rejected"],
            payload={"finalOutputValidation": {
                "passed": False,
                "failureOwner": "rendering",
                "rejectionReasons": ["final_render_evidence_unavailable"],
            }},
            model_score=.923,
        )

    monkeypatch.setattr(bake, "apply_materialized_output_acceptance_gate", validate)
    monkeypatch.setattr(bake, "choose_top_review_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(bake, "choose_best_review_item", lambda items, rankings, **kwargs: (items[0], rankings[0]))
    monkeypatch.setattr(bake, "write_candidate_ranking_manifests", lambda _entries: None)
    monkeypatch.setattr(bake, "write_selected_result_preview_htmls", lambda *_args: [])
    monkeypatch.setattr(
        bake,
        "build_selection_manifest",
        lambda **kwargs: {"reviewItems": kwargs["review_entries"], "candidateResults": []},
    )
    monkeypatch.setattr(bake, "attach_selected_preview_paths_to_manifest", lambda *_args: None)

    bake.run_bake_and_rank_reselection(workspace=tmp_path)

    saved = json.loads(selection_path.read_text(encoding="utf-8"))
    assert saved["reviewItems"][0]["ranking"]["payload"]["finalOutputValidation"]["rejectionReasons"] == [
        "final_render_evidence_unavailable"
    ]
