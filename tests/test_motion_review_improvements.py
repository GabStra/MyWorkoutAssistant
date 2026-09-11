import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import segment_detection as segment
from exercise_motion_pkg import youtube
from exercise_motion_pkg.contact_sheet_crop import persistent_border_crop


def exercise(name="Standing Cable Press"):
    return youtube.ExerciseEntry(exercise_id="test", name=name, slug="test")


def contract_for(entry, support="standing"):
    return youtube.normalize_exercise_motion_contract(
        {"movementType": "repetition", "groundContactMode": "continuous", "completionMode": "return_to_start",
         "startPoseConstraints": {"supportMode": support, "handHeight": "shoulder_chest", "torsoOrientation": "upright", "kneeState": "extended", "stance": "shoulder_width"},
         "endPoseConstraints": {"supportMode": support, "handHeight": "shoulder_chest", "torsoOrientation": "upright", "kneeState": "extended", "stance": "shoulder_width"},
         "validStartState": f"{support} with hands at chest height", "validEndState": f"{support} with hands at chest height",
         "requiredPhases": ["extend the arms forward", "return the hands to the chest"],
         "primaryMovingRegions": ["upper_limb"], "referenceRegions": ["torso"],
         "primaryAxis": "horizontal", "motionPattern": "joint_flex_extend", "youtubeQueryAliases": [entry.name]},
        exercise=entry, source="llm",
    )


def approved_response(candidate_id="A"):
    return json.dumps({"candidates": [{"id": candidate_id, "approved": True, "confidence": 0.95,
        "completeMovement": True, "startBoundaryClean": True, "finishBoundaryClean": True,
        "setupOrFiller": False, "namedEquipmentEngagedStatus": "not_applicable", "reject": [],
        "note": "Full action and return visible.", "startStateMatch": "match", "endStateMatch": "match",
        "phaseEvidence": [{"phaseId": "phase_01", "position": 0.3}, {"phaseId": "phase_02", "position": 0.8}]}]})


def candidate_at(tmp_path, candidate_id="A", phase=None):
    directory = tmp_path / candidate_id
    directory.mkdir()
    sheets = [directory / f"{kind}.jpg" for kind in ("chronological", "start", "finish")]
    for sheet in sheets:
        sheet.write_bytes(b"fixture")
    return bake.SourceCutCandidate(candidate_id=candidate_id,
        window=segment.DetectionWindow(index=0, start_seconds=0, end_seconds=4),
        frame_paths=sheets[:1], boundary_audit_frame_paths=sheets[1:], sample_frame_paths=sheets[1:],
        motion_coverage={} if phase is None else {"candidateFullRepetitionPhaseCompletenessMetrics": phase})


def parse_review(raw, candidate):
    return bake.parse_source_cut_candidate_choice(raw, [candidate], exercise_motion_contract=contract_for(exercise()))


def test_contract_identity_conflict_cannot_bypass_quality_with_aliases():
    entry = exercise("Ab Wheel Standing Rollout")
    contract = contract_for(entry, support="kneeling")
    contract["youtubeQueryAliases"] = [entry.name]
    assert contract["youtubeQueryAliases"]
    assert "requires standing" in " ".join(youtube.exercise_motion_contract_quality_issues(contract))
    assert not youtube.exercise_motion_contract_is_usable(contract)


@pytest.mark.parametrize("name,support", [("Standing Cable Press", "standing"), ("Kneeling Cable Press", "kneeling"), ("Kneeling to Standing", "kneeling")])
def test_consistent_identity_and_support_transitions_remain_usable(name, support):
    assert youtube.exercise_motion_contract_is_usable(contract_for(exercise(name), support))


def test_explicit_wrong_implement_is_rejected_without_requiring_textual_mentions():
    entry = exercise("Barbell Curl")
    contract = contract_for(entry)
    assert youtube.exercise_motion_contract_identity_issues(contract) == []
    contract["requiredPhases"] = ["raise the dumbbells", "return the dumbbells"]
    assert "requires barbell" in " ".join(youtube.exercise_motion_contract_identity_issues(contract))


def test_cached_contract_is_validated_against_requested_exercise(tmp_path):
    entry = exercise("Standing Cable Press")
    settings = youtube.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path)
    good = contract_for(entry)
    path = youtube.cache_exercise_motion_contract(entry, settings, good)
    assert path is not None
    assert youtube.load_cached_exercise_motion_contract(entry, settings) is not None
    payload = json.loads(path.read_text())
    payload["contract"] = contract_for(exercise("Kneeling Cable Press"), "kneeling")
    path.write_text(json.dumps(payload))
    assert youtube.load_cached_exercise_motion_contract(entry, settings) is None
    assert youtube.cache_exercise_motion_contract(entry, settings, payload["contract"]) is None


def test_primary_equipment_context_validates_generic_exercise_name():
    entry = youtube.ExerciseEntry(exercise_id="curl", name="Curl", slug="curl",
        motion_context={"primaryEquipment": {"name": "Barbell", "type": "BARBELL"}})
    contract = contract_for(entry)
    contract["requiredPhases"] = ["raise the dumbbells", "return the dumbbells"]
    assert "requires barbell" in " ".join(
        youtube.exercise_motion_contract_identity_issues(contract, exercise=entry))


def test_seeded_contract_cannot_hide_conflict_in_nested_recommendation(tmp_path):
    entry = exercise("Standing Cable Press")
    bad = contract_for(exercise("Kneeling Cable Press"), "kneeling")
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"exercises": [{"exerciseName": entry.name,
        "exerciseMotionContract": bad, "candidates": [{"status": "recommended", "exerciseMotionContract": bad}]}]}))
    assert youtube.load_seed_exercise_motion_contract_from_candidates_json(path, entry) is None


def test_contract_identity_failure_uses_existing_bounded_repair():
    entry = exercise("Standing Cable Press")
    prompts = []
    def caption_images(**kwargs):
        prompts.append(kwargs["prompt"])
        return json.dumps(contract_for(entry, "kneeling" if len(prompts) < 3 else "standing"))
    result = youtube.generate_exercise_motion_contract_with_ranker(
        exercise=entry, settings=youtube.YouTubeRankingSettings(), ranker=SimpleNamespace(client=SimpleNamespace(caption_images=caption_images)))
    assert result["generationMode"] == "direct_repair"
    assert len(prompts) == 3
    assert "requires standing" in prompts[-1]


@pytest.mark.parametrize("strategy", ["ordinary", bake.KINEMATIC_CUT_STRATEGY])
def test_resolved_partial_cycle_cannot_enter_confirmation(strategy):
    assert not bake.source_cut_confirmation_candidate_is_eligible({"chunking": {"strategy": strategy},
        "motionCoverage": {"candidateFullRepetitionPhaseCompletenessMetrics": {
            "required": True, "passed": False, "reason": "partial_cycle", "finishAtExtreme": True,
            "phaseSignalEvidence": {"resolved": True}}}})


def test_unavailable_pose_does_not_become_hard_partial_rejection():
    assert bake.source_cut_confirmation_candidate_is_eligible({"chunking": {"strategy": bake.KINEMATIC_CUT_STRATEGY},
        "motionCoverage": {"candidateFullRepetitionPhaseCompletenessMetrics": {
            "required": True, "passed": False, "reason": "pose_unavailable", "finishAtExtreme": True}}})


def test_pose_partial_vetoes_positive_model_scorecard(tmp_path):
    candidate = candidate_at(tmp_path, phase={"required": True, "passed": False, "reason": "partial_cycle", "phaseSignalEvidence": {"resolved": True}})
    ranking = parse_review(approved_response(), candidate)
    assert ranking.score == 0
    assert not bake.source_cut_ranking_has_vlm_approval(ranking)
    assert "source_cut_pose_confirmed_partial_movement" in ranking.payload["sourceCutScorecardCandidates"][0]["rejectionReasons"]


def observation(knee="extended"):
    return json.dumps({"supportMode": "standing", "kneeState": knee,
        "torsoOrientation": "upright", "handHeight": "shoulder_chest", "stance": "shoulder_width"})


def review_prompt(_):
    return "Structured movement contract: " + json.dumps(contract_for(exercise()))


@pytest.mark.parametrize("end,expected", [("extended", True), ("flexed", True), ("unknown", True)])
def test_production_review_requires_focused_boundary_evidence(tmp_path, end, expected):
    candidate = candidate_at(tmp_path)
    responses = iter([approved_response(), observation(), observation(end)])
    calls = []
    def caption_images(**kwargs):
        calls.append(kwargs)
        return next(responses)
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate, caption_images=caption_images,
        prompt_builder=review_prompt, parser=parse_review)
    assert len(calls) == 3
    assert calls[1]["frame_paths"] == candidate.sample_frame_paths[:1]
    assert calls[2]["frame_paths"] == candidate.sample_frame_paths[-1:]
    assert "Standing Cable Press" not in calls[1]["prompt"]
    assert bake.source_cut_ranking_has_vlm_approval(result.rankings[0]) is expected


def test_coarse_pose_pass_cannot_skip_endpoint_observation(tmp_path):
    candidate = candidate_at(tmp_path, phase={"required": True, "passed": True})
    candidate.motion_coverage["sourcePoseEndpointContractValidation"] = {"available": True, "passed": True}
    responses = iter([approved_response(), observation(), observation("flexed")])
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate,
        caption_images=lambda **_: next(responses), prompt_builder=review_prompt, parser=parse_review)
    assert bake.source_cut_ranking_has_vlm_approval(result.rankings[0])


def test_unparseable_boundary_review_preserves_sequence_approval_with_warning(tmp_path):
    responses = iter([approved_response(), "not JSON", "not JSON"])
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate_at(tmp_path),
        caption_images=lambda **_: next(responses), prompt_builder=review_prompt, parser=parse_review)
    assert bake.source_cut_ranking_has_vlm_approval(result.rankings[0])
    assert "selectedCandidateId" in result.rankings[0].payload


def test_missing_boundary_images_preserves_sequence_approval_with_warning(tmp_path):
    candidate = candidate_at(tmp_path)
    candidate.sample_frame_paths.clear()
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate,
        caption_images=lambda **_: approved_response(), prompt_builder=review_prompt, parser=parse_review)
    assert bake.source_cut_ranking_has_vlm_approval(result.rankings[0])


def test_rejected_boundary_candidate_does_not_discard_next_candidate(tmp_path):
    candidates = [candidate_at(tmp_path, candidate_id=key) for key in ("A", "B")]
    candidates[0].motion_coverage["sourceSupportRelativeReturn"] = {"available": True, "passed": False}
    candidates[0].visual_integrity["passed"] = True
    responses = iter([approved_response("A"), observation(), observation("flexed"),
                      approved_response("B"), observation(), observation()])
    result = bake.rank_cut_candidates_with_caption_images(candidates=candidates,
        caption_images=lambda **_: next(responses), prompt_builder=review_prompt, parser=parse_review)
    assert [bake.source_cut_ranking_has_vlm_approval(r) for r in result.rankings] == [False, True]


@pytest.mark.parametrize("truncated", [False, True])
@pytest.mark.parametrize("camera_motion", [False, True])
def test_support_relative_return_with_camera_translation_and_zoom(truncated, camera_motion):
    values = [0, .1, .3, .6, 1, .8, .5, .25, .1, 0]
    if truncated:
        values = values[:8]
    frames = []
    for index, value in enumerate(values):
        scale = 1 + index * .02 if camera_motion else 1
        shift = index * .03 if camera_motion else 0
        joints = {"left_ankle": [.3, .9, 0], "right_ankle": [.6, .9, 0],
                  "pelvis": [.45, .5 + value * .3, 0]}
        frames.append({"joints": {key: [x * scale + shift, y * scale + shift, z]
            for key, (x, y, z) in joints.items()}})
    contract = contract_for(exercise())
    contract["primaryMovingRegions"] = ["hips"]
    result = bake.source_support_relative_return_evidence({"frames": frames}, contract)
    assert result["available"]
    assert result["passed"] is not truncated


def border_frames(tmp_path, *, moving_border=False, edge_object=False):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    paths = []
    for index in range(8):
        frame = np.zeros((160, 320, 3), dtype=np.uint8)
        left = 80 if not moving_border or index < 4 else 40
        frame[:, left:320-left] = 180
        if edge_object and index == 7:
            frame[50:60, 5:20] = 200
        path = tmp_path / f"frame_{index}.png"
        assert cv2.imwrite(str(path), frame)
        paths.append(path)
    return paths


def test_border_crop_is_shared_across_sheets_and_preserves_content(tmp_path):
    cv2 = pytest.importorskip("cv2")
    paths = border_frames(tmp_path)
    crop = persistent_border_crop(paths)
    assert crop is not None and crop[0] < 80 and crop[2] > 240
    output = tmp_path / "sheets"
    sheets = segment.build_frame_contact_sheets(frame_paths=paths, timestamps=list(range(8)), output_dir=output,
        columns=2, tile_width=160, frames_per_sheet=4, jpeg_quality=90, sequence_labels=True, crop_empty_borders=True)
    metadata = json.loads((output / "contact_sheet_crop.json").read_text())
    assert metadata["cropBox"] == list(crop)
    assert len(sheets) == 2
    assert cv2.imread(str(sheets[0])).shape == cv2.imread(str(sheets[1])).shape
    assert cv2.imread(str(sheets[0])).shape[0] > 160


@pytest.mark.parametrize("options", [{"moving_border": True}, {"edge_object": True}])
def test_uncertain_borders_are_not_cropped(tmp_path, options):
    assert persistent_border_crop(border_frames(tmp_path, **options)) is None


def test_missing_frame_disables_window_crop(tmp_path):
    paths = border_frames(tmp_path)
    paths[-1].unlink()
    assert persistent_border_crop(paths) is None


def test_motion_coverage_exposes_separate_endpoint_comparisons(monkeypatch):
    joints = {"nose": [.5, .1, 0], "left_shoulder": [.4, .25, 0], "right_shoulder": [.6, .25, 0],
        "shoulders": [.5, .25, 0], "pelvis": [.5, .5, 0], "left_hip": [.45, .5, 0],
        "right_hip": [.55, .5, 0], "left_knee": [.45, .7, 0], "right_knee": [.55, .7, 0],
        "left_ankle": [.4, .9, 0], "right_ankle": [.6, .9, 0],
        "left_wrist": [.3, .3, 0], "right_wrist": [.7, .3, 0]}
    pose = {"jointNames": list(joints), "rootJoint": "pelvis",
        "frames": [{"sourceTimeSec": index / 8, "joints": joints} for index in range(8)]}
    monkeypatch.setattr(bake, "source_pose_skeleton_payload_for_window", lambda *args, **kwargs: pose)
    result = bake.source_cut_candidate_motion_coverage_metrics(
        candidate_window=segment.DetectionWindow(index=0, start_seconds=0, end_seconds=1),
        pose_payload={}, exercise_name="Standing Cable Press",
        chunk_estimate=SimpleNamespace(rep_duration_min_sec=1, rep_duration_max_sec=2),
        exercise_motion_contract=contract_for(exercise()))
    comparisons = result["sourcePoseEndpointContractValidation"]["comparisons"]
    assert {row["endpoint"] for row in comparisons} == {"start", "end"}
    assert len(comparisons) == 10


@pytest.mark.parametrize("stable_camera", [False, True])
def test_support_return_conflict_requires_stable_camera(tmp_path, stable_camera):
    candidate = candidate_at(tmp_path)
    candidate.motion_coverage["sourceSupportRelativeReturn"] = {"available": True, "passed": False}
    candidate.visual_integrity["passed"] = stable_camera
    responses = iter([approved_response(), observation(), observation("flexed")])
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate,
        caption_images=lambda **_: next(responses), prompt_builder=review_prompt, parser=parse_review)
    assert bake.source_cut_ranking_has_vlm_approval(result.rankings[0]) is not stable_camera


def test_model_mismatch_is_pending_not_a_confirmed_rejection(tmp_path):
    candidate = candidate_at(tmp_path)
    responses = iter([approved_response(), observation(), observation("flexed")])
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate,
        caption_images=lambda **_: next(responses), prompt_builder=review_prompt, parser=parse_review)
    ranking = result.rankings[0]
    review = ranking.payload["sourceCutBoundaryReview"]
    assert review["decision"] == "needs_review"
    assert "source_cut_boundary_uncertain" in ranking.reasons
    assert bake.source_cut_ranking_has_vlm_approval(ranking)
    assert Path(review["reviewPath"]).exists()
    assert "First frame" in Path(review["reviewPath"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("support_passed,expected", [(False, "rejected"), (True, "needs_review")])
def test_independent_support_evidence_arbitrates_visible_mismatch(tmp_path, support_passed, expected):
    candidate = candidate_at(tmp_path)
    candidate.motion_coverage["sourceSupportRelativeReturn"] = {"available": True, "passed": support_passed}
    candidate.visual_integrity["passed"] = True
    responses = iter([approved_response(), observation(), observation("flexed")])
    result = bake.rank_cut_candidate_with_caption_images(candidate=candidate,
        caption_images=lambda **_: next(responses), prompt_builder=review_prompt, parser=parse_review)
    assert result.rankings[0].payload["sourceCutBoundaryReview"]["decision"] == expected


def test_repeated_contract_conflict_is_not_repaired_to_fit_frames():
    from exercise_motion_pkg.boundary_evidence import assess_boundary_evidence
    rows = [{"endpoint": endpoint, "field": "torsoOrientation", "expected": "upright",
        "observed": "hinged", "passed": False} for endpoint in ("start", "end")]
    result = assess_boundary_evidence(rows, support_return={"available": True, "passed": False},
        stable_camera=True, completion_mode="return_to_start")
    assert result["decision"] == "needs_review"
    assert result["reason"] == "contract_observation_conflict"
    assert all(row["expected"] == "upright" for row in rows)


@pytest.mark.parametrize("value", [None, [], {}, "unknown"])
def test_malformed_or_unknown_observation_remains_unresolved(value):
    from exercise_motion_pkg.boundary_evidence import assess_boundary_evidence
    result = assess_boundary_evidence([
        {"endpoint": endpoint, "field": "kneeState", "expected": "extended", "observed": value, "passed": False}
        for endpoint in ("start", "end")], support_return={}, stable_camera=True, completion_mode="return_to_start")
    assert result["decision"] == "needs_review"


def test_pending_source_does_not_damage_history_but_resolved_sibling_counts(tmp_path):
    from exercise_motion_pkg.source_outcomes import update_source_outcome_index, load_source_outcome_index
    path = tmp_path / "history.json"
    candidate = {"videoId": "source", "channel": "channel"}
    pending = {"candidate": candidate, "status": "needs_source_review"}
    assert update_source_outcome_index(path, [pending]) is None
    assert not path.exists()
    accepted = {"candidate": candidate, "status": "ready_for_selection", "finalSelectionStatus": "selected"}
    update_source_outcome_index(path, [pending, accepted])
    index = load_source_outcome_index(path)
    assert index["sources"]["video:source"]["attempts"] == 1
    assert index["sources"]["video:source"]["accepts"] == 1


def test_explicit_posture_variant_still_blocks_wrong_source():
    from exercise_motion_pkg.boundary_evidence import assess_boundary_evidence
    rows = [{"endpoint": endpoint, "field": "supportMode", "expected": "standing",
             "observed": "kneeling", "passed": False, "requirementOrigin": "exercise_definition"}
            for endpoint in ("start", "end")]
    result = assess_boundary_evidence(rows, support_return={}, stable_camera=True, completion_mode="return_to_start")
    assert result["blocking"] is True
    assert result["reason"] == "explicit_identity_conflict"


def test_incomplete_return_compares_observations_not_ideal_posture():
    from exercise_motion_pkg.boundary_evidence import assess_boundary_evidence
    rows = [{"endpoint": "start", "field": "kneeState", "expected": "extended", "observed": "flexed", "passed": False},
            {"endpoint": "end", "field": "kneeState", "expected": "extended", "observed": "deep_flexion", "passed": False}]
    result = assess_boundary_evidence(rows, support_return={"available": True, "passed": False},
                                     stable_camera=True, completion_mode="return_to_start")
    assert result["blocking"] is True


def test_deterministic_pose_expectations_are_advisory_but_identity_is_not():
    contract = contract_for(exercise())
    observed = {"supportMode": "standing", "kneeState": "flexed", "torsoOrientation": "hinged",
                "handHeight": "hip", "stance": "wide"}
    features = {"available": True, "start": dict(observed), "end": dict(observed)}
    result = bake.validate_source_pose_endpoints_against_contract(features, contract)
    assert result["passed"] is True
    assert result["diagnosticOnlyMismatches"]
    features["start"]["supportMode"] = "kneeling"
    result = bake.validate_source_pose_endpoints_against_contract(features, contract)
    assert result["passed"] is False
    assert {row["field"] for row in result["blockingMismatches"]} == {"supportMode"}


def test_topology_posture_mismatch_is_advisory_without_relaxing_missing_action():
    topology = bake.movement_topology_from_contract(contract_for(exercise()))
    evidence = {"startStateMatch": "mismatch", "endStateMatch": "uncertain",
                "phaseEvidence": [{"phaseId": phase["id"], "position": (index+1)/3}
                                  for index, phase in enumerate(topology["phases"])]}
    payload, reasons, missing = bake.topology_evidence_rejection_reasons(evidence, topology)
    assert not reasons and not missing
    assert payload["advisoryBoundaryWarnings"]
    # Exact phase requirements, where authoritative, still reject missing action.
    topology["phaseEvidenceHardGate"] = True
    evidence["phaseEvidence"] = []
    _, reasons, _ = bake.topology_evidence_rejection_reasons(evidence, topology)
    assert "source_cut_contract_phase_sequence_mismatch" in reasons
