from types import SimpleNamespace
import hashlib
import json

import pytest

from exercise_motion_pkg import source_review_authority as authority
from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_turn_budget import _SourceTurnBudget


def test_new_validated_review_identity_reopens_once_without_erasing_history():
    key = "exercise:candidate"
    prior_keys = [key]
    current = {key: "a" * 64}

    # Legacy cursor has no acknowledged review identity. A canonical validated
    # identity allows one retry while the historical key remains untouched.
    reopened = authority.retained_source_attempt_keys(
        prior_keys, {}, current_validated_review_identities=current,
        acknowledged_review_identities={},
    )
    assert reopened == []
    assert prior_keys == [key]

    # Persisting the acknowledged identity closes that exact transition.
    acknowledged = {key: current[key]}
    assert authority.retained_source_attempt_keys(
        prior_keys, {}, current_validated_review_identities=current,
        acknowledged_review_identities=acknowledged,
    ) == [key]
    assert authority.source_review_evidence_blocks_attempt(key, current, acknowledged)
    assert authority.source_review_evidence_blocks_attempt(key, {}, acknowledged)

    # A genuinely different validated decision can reopen it once again.
    newer = {key: "b" * 64}
    assert authority.retained_source_attempt_keys(
        prior_keys, {}, current_validated_review_identities=newer,
        acknowledged_review_identities=acknowledged,
    ) == []
    assert not authority.source_review_evidence_blocks_attempt(key, newer, acknowledged)


def test_missing_or_malformed_evidence_does_not_reopen_attempt():
    key = "exercise:candidate"
    prior_keys = [key]
    for current in (None, {}, {key: "passed"}, {key: "a" * 63}):
        assert authority.retained_source_attempt_keys(
            prior_keys, {}, current_validated_review_identities=current,
            acknowledged_review_identities={},
        ) == [key]
    assert not authority.source_review_evidence_reopens_attempt(key, {key: "a" * 64}, {key: "bad"})


def test_legacy_unresolved_selection_reopens_once_by_semantic_identity(tmp_path):
    key = "exercise:candidate"
    path = tmp_path / "segment_detection" / "segment_selection.json"
    path.parent.mkdir()
    payload = {
        "selectedSpan": None,
        "updatedAt": "before",
        "sourceVideoPath": "C:/old/workspace/source.mp4",
        "sourceVideoSha256": "a" * 64,
        "sourceCutRanking": {
            "reasons": ["source_cut_review_required"],
            "payload": {
                "sourceReviewStatus": "needs_review",
                "sourceReviewAuthorityVersion": authority.SOURCE_REVIEW_AUTHORITY_VERSION,
                "rejectionReasons": ["old model wording"],
                "citations": ["old citation"],
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    identity = authority.candidate_source_review_replay_identity(tmp_path)
    assert identity and len(identity) == 64
    assert authority.retained_source_attempt_keys([key], {key: tmp_path}) == []
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path}, legacy_replay_reservations={key: identity},
    ) == [key]

    # Whitespace, timestamps and relocated path metadata do not mint a new turn.
    payload["updatedAt"] = "after"
    payload["sourceVideoPath"] = "D:/new/location/source.mp4"
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    assert authority.candidate_source_review_replay_identity(tmp_path) == identity

    # Rejection wording and citations are prior outputs, not changed inputs.
    payload["sourceCutRanking"]["payload"]["rejectionReasons"] = ["different reviewer prose"]
    payload["sourceCutRanking"]["payload"]["citations"] = ["new citation text"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert authority.candidate_source_review_replay_identity(tmp_path) == identity
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path}, legacy_replay_reservations={key: identity},
    ) == [key]

    # A changed source byte identity is a genuine changed review input.
    payload["sourceVideoSha256"] = "b" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path}, legacy_replay_reservations={key: identity},
    ) == []


def _current_mapped_request_inputs():
    context = {
        "schemaVersion": 1,
        "sourceExerciseId": "source-id",
        "sourceExerciseName": "Nordic Curl",
        "targetExerciseId": "target-id",
        "targetExerciseName": "Weighted Vest Nordic Curl",
        "allowedDifference": "external_load_not_shown",
        "approvalAuthority": "explicit_user_approval",
        "approvalSha256": "a" * 64,
        "mappingSha256": "b" * 64,
        "targetContractSha256": "c" * 64,
        "targetContractPolicyVersion": 39,
    }
    model_identity = {"modelSha256": "f" * 64}
    context_sha256 = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    model_sha256 = hashlib.sha256(
        json.dumps(model_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "sourceVideoSha256": "d" * 64,
        "currentContractSha256": context["targetContractSha256"],
        "contractPolicyVersion": 39,
        "sourceSelectionPolicyVersion": 62,
        "sourceReviewPolicyVersion": 2,
        "modelIdentity": model_identity,
        "modelIdentitySha256": model_sha256,
        "requestedWindow": {"startSeconds": 0.0, "endSeconds": 4.4667},
        "sourceReferenceReviewContext": context,
        "sourceReferenceReviewContextSha256": context_sha256,
        "sourceReferenceVisualReviewSpecPolicyVersion": 1,
        "sourceReferenceVisualReviewSpecSha256": "e" * 64,
        "targetExerciseId": "target-id",
        "phaseInputIdentity": None,
    }


def test_changed_current_approved_request_resumes_absent_legacy_selection_once(tmp_path):
    key = "source-id:nordic-curl-001-ycozlcqu7qu"
    inputs = _current_mapped_request_inputs()
    identity = authority.source_review_input_identity(inputs)
    assert identity and len(identity) == 64
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path},
        current_source_review_input_identities={key: identity},
        source_review_input_reservations={},
        eligible_legacy_input_keys={key},
    ) == []

    # Reserve before the charged review call. The same semantic request is
    # blocked on the next resume even if old response wording changes.
    reserved = {key: identity}
    changed_response_only = {**inputs, "diagnostic": {"response": "different reviewer prose"}}
    assert authority.source_review_input_identity(changed_response_only) == identity
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path},
        current_source_review_input_identities={key: identity},
        source_review_input_reservations=reserved,
        eligible_legacy_input_keys={key},
    ) == [key]

    # A changed source/target contract produces a distinct request identity,
    # but the single legacy migration is still spent.
    changed_mapping = dict(inputs)
    changed_mapping["sourceReferenceReviewContext"] = {
        **inputs["sourceReferenceReviewContext"], "mappingSha256": "3" * 64,
    }
    changed_mapping["sourceReferenceReviewContextSha256"] = hashlib.sha256(
        json.dumps(
            changed_mapping["sourceReferenceReviewContext"],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    changed_identity = authority.source_review_input_identity(changed_mapping)
    assert changed_identity != identity
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path},
        current_source_review_input_identities={key: changed_identity},
        source_review_input_reservations=reserved,
        eligible_legacy_input_keys={key},
    ) == [key]


def test_current_input_readmission_fails_closed_without_complete_approved_context():
    inputs = _current_mapped_request_inputs()
    assert authority.source_review_input_identity(None) is None
    assert authority.source_review_input_identity({**inputs, "sourceVideoSha256": None}) is None
    bad_context = {**inputs["sourceReferenceReviewContext"], "approvalAuthority": "inferred"}
    assert authority.source_review_input_identity({
        **inputs, "sourceReferenceReviewContext": bad_context,
    }) is None
    assert authority.source_review_input_identity({
        key: value for key, value in inputs.items()
        if key != "sourceReferenceVisualReviewSpecSha256"
    }) is None
    assert authority.source_review_input_identity({
        **inputs, "sourceReferenceVisualReviewSpecPolicyVersion": 2,
    }) is None


def test_visual_spec_change_reopens_old_reservation_once_and_keeps_history(tmp_path):
    key = "source-id:nordic-curl-001-ycozlcqu7qu"
    inputs = _current_mapped_request_inputs()
    current_identity = authority.source_review_input_identity(inputs)
    legacy_identity = authority.source_review_input_identity_before_visual_spec(inputs)
    assert current_identity and legacy_identity and current_identity != legacy_identity

    prior_reservations = {key: legacy_identity}
    prior_history = {key: [legacy_identity]}
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path},
        current_source_review_input_identities={key: current_identity},
        source_review_input_reservations=prior_reservations,
        source_review_input_reservation_history=prior_history,
        eligible_legacy_input_keys={key},
        allow_visual_spec_upgrade_keys={key},
    ) == []

    # The same corrected spec is blocked after its identity is reserved; the
    # previous reservation remains in the audit history.
    upgraded_reservations = {key: current_identity}
    upgraded_history = {key: [legacy_identity, current_identity]}
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path},
        current_source_review_input_identities={key: current_identity},
        source_review_input_reservations=upgraded_reservations,
        source_review_input_reservation_history=upgraded_history,
        eligible_legacy_input_keys={key},
        allow_visual_spec_upgrade_keys={key},
    ) == [key]

    # A different mapping hash without the explicit old-spec transition is
    # still blocked, even though it changes the ordinary request identity.
    changed = dict(inputs)
    changed["sourceReferenceReviewContext"] = {
        **inputs["sourceReferenceReviewContext"], "mappingSha256": "3" * 64,
    }
    changed["sourceReferenceReviewContextSha256"] = hashlib.sha256(
        json.dumps(changed["sourceReferenceReviewContext"], sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    changed_identity = authority.source_review_input_identity(changed)
    assert changed_identity and changed_identity != current_identity
    assert authority.retained_source_attempt_keys(
        [key], {key: tmp_path},
        current_source_review_input_identities={key: changed_identity},
        source_review_input_reservations=upgraded_reservations,
        source_review_input_reservation_history=upgraded_history,
        eligible_legacy_input_keys={key},
    ) == [key]


def test_source_turn_cursor_preserves_input_reservations(tmp_path):
    from exercise_motion_pkg.source_turn_budget import (
        _source_turn_exercise_identity,
        write_source_turn_cursor_from_wave_state,
    )

    cursor_path = tmp_path / "source_turn_resume.json"
    plan_path = tmp_path / "plan.json"
    prior_key = "source-id:candidate"
    reservation = "a" * 64
    plan_path.write_text(json.dumps({"exercises": [{
        "id": "source-id", "name": "Nordic", "motionContext": {},
    }]}), encoding="utf-8")
    exercise_identity = _source_turn_exercise_identity("source-id", "Nordic", {})
    cursor_path.write_text(json.dumps({
        "sourceSelectionPolicyVersion": 62,
        "sourceTurnExerciseIdentity": exercise_identity,
        "sourceReviewTurnId": "turn-1",
        "attemptedCandidateKeys": [prior_key],
        "attemptedVideoIds": ["video"],
        "sourceReviewInputReservationsByCandidateKey": {prior_key: reservation},
        "sourceReviewInputReservationDetailsByCandidateKey": {
            prior_key: {"inputIdentitySha256": reservation, "sourceReferenceVisualReviewSpecPolicyVersion": 1},
        },
        "sourceReviewInputReservationHistoryByCandidateKey": {prior_key: [reservation]},
        "sourceReviewReplayReservationsByCandidateKey": {prior_key: "b" * 64},
    }), encoding="utf-8")
    result = write_source_turn_cursor_from_wave_state(
        cursor_path,
        wave_state={
            "exerciseId": "source-id",
            "exerciseName": "Nordic",
            "source": {
                "sourceSelectionPolicyVersion": 62,
                "attempts": [],
                "priorAttemptedCandidateKeys": [prior_key],
                "priorAttemptedVideoIds": ["video"],
                "nextCandidateKey": prior_key,
            },
        },
        exercise_plan_path=plan_path,
        source_review_turn_id="turn-1",
        transition="next_source_candidate",
    )
    assert result["attemptedCandidateKeys"] == [prior_key]
    assert result["sourceReviewInputReservationsByCandidateKey"] == {prior_key: reservation}
    assert result["sourceReviewInputReservationDetailsByCandidateKey"][prior_key]["inputIdentitySha256"] == reservation
    assert result["sourceReviewInputReservationHistoryByCandidateKey"] == {prior_key: [reservation]}
    assert result["sourceReviewReplayReservationsByCandidateKey"] == {prior_key: "b" * 64}


def test_evidence_reopen_spends_existing_remaining_attempt_budget():
    budget = _SourceTurnBudget(
        SimpleNamespace(
            exercise_timeout_seconds=300.0,
            source_review_timeout_seconds=240.0,
            max_source_window_attempts=2,
        ),
        {"sourceTurnBudgetPolicyVersion": 3, "sourceTurnAttemptsUsed": 1},
    )
    assert budget.stop_reason() is None
    budget.begin_attempt()
    assert budget.attempts_used == 2
    assert budget.stop_reason() == "source_turn_attempt_budget"


def test_visual_spec_upgrade_uses_one_explicit_remaining_turn_without_reset():
    budget = _SourceTurnBudget(
        SimpleNamespace(
            exercise_timeout_seconds=300.0,
            source_review_timeout_seconds=300.0,
            max_source_window_attempts=3,
        ),
        {
            "sourceTurnBudgetPolicyVersion": 3,
            "sourceTurnElapsedSeconds": 225.523,
            "sourceTurnAttemptsUsed": 2,
            "sourceTurnAttemptLimit": 2,
            "sourceTurnTimeoutSeconds": None,
            "sourceTurnWaitTimeoutSeconds": 240.0,
        },
    )
    assert budget.attempts_used == 2
    assert budget.attempt_limit == 3
    assert budget.elapsed() >= 225.523
    assert budget.timeout_seconds == 300.0
    assert budget.wait_timeout_seconds == 300.0
    assert budget.budget_extended_by_configuration is True
    assert budget.stop_reason() is None
    budget.begin_attempt()
    assert budget.attempts_used == 3
    assert budget.stop_reason() == "source_turn_attempt_budget"


def test_explicit_visual_spec_supersession_is_pinned_audited_and_one_shot():
    from exercise_motion_pkg.wave_pipeline import (
        _EXPLICIT_VISUAL_SPEC_SUPERSESSION_REASON,
        _validated_source_review_input_supersession,
    )

    key = "source-id:nordic-curl-001-ycozlcqu7qu"
    inputs = _current_mapped_request_inputs()
    current = authority.source_review_input_identity(inputs)
    context = inputs["sourceReferenceReviewContext"]
    context_sha = inputs["sourceReferenceReviewContextSha256"]
    visual_sha = inputs["sourceReferenceVisualReviewSpecSha256"]
    prior = "9" * 64
    explicit = {
        key: {
            "priorInputIdentitySha256": prior,
            "currentInputIdentitySha256": current,
            "sourceReferenceReviewContextSha256": context_sha,
            "sourceReferenceVisualReviewSpecPolicyVersion": 1,
            "sourceReferenceVisualReviewSpecSha256": visual_sha,
            "targetExerciseId": context["targetExerciseId"],
            "reason": _EXPLICIT_VISUAL_SPEC_SUPERSESSION_REASON,
        },
    }

    audit = _validated_source_review_input_supersession(
        key, explicit, prior_identity=prior, current_identity=current,
        current_context_sha256=context_sha, visual_spec_policy_version=1,
        visual_spec_sha256=visual_sha, target_exercise_id=context["targetExerciseId"],
        historical_attempt=True, acknowledged=False, current_validated_pass=False,
        prior_details_present=False, input_history=[],
    )
    assert audit == {
        "priorInputIdentitySha256": prior,
        "currentInputIdentitySha256": current,
        "reason": _EXPLICIT_VISUAL_SPEC_SUPERSESSION_REASON,
        "sourceReferenceReviewContextSha256": context_sha,
        "sourceReferenceVisualReviewSpecPolicyVersion": 1,
        "sourceReferenceVisualReviewSpecSha256": visual_sha,
        "targetExerciseId": context["targetExerciseId"],
        "sourceApprovalGranted": False,
    }

    prior_details = {
        "inputIdentitySha256": prior,
        "sourceReferenceReviewContextSha256": context_sha,
        "sourceReferenceVisualReviewSpecPolicyVersion": 1,
        "sourceReferenceVisualReviewSpecSha256": visual_sha,
        "supersession": {
            "priorInputIdentitySha256": "0" * 64,
            "currentInputIdentitySha256": prior,
            "sourceReferenceReviewContextSha256": context_sha,
            "sourceReferenceVisualReviewSpecPolicyVersion": 1,
            "sourceReferenceVisualReviewSpecSha256": visual_sha,
            "targetExerciseId": context["targetExerciseId"],
            "sourceApprovalGranted": False,
        },
    }
    chained_audit = _validated_source_review_input_supersession(
        key, explicit, prior_identity=prior, current_identity=current,
        current_context_sha256=context_sha, visual_spec_policy_version=1,
        visual_spec_sha256=visual_sha, target_exercise_id=context["targetExerciseId"],
        historical_attempt=True, acknowledged=False, current_validated_pass=False,
        prior_details_present=True, prior_reservation_details=prior_details,
        input_history=["0" * 64, prior],
    )
    assert chained_audit == audit

    assert _validated_source_review_input_supersession(
        key, None, prior_identity=prior, current_identity=current,
        current_context_sha256=context_sha, visual_spec_policy_version=1,
        visual_spec_sha256=visual_sha, target_exercise_id=context["targetExerciseId"],
        historical_attempt=True, acknowledged=False, current_validated_pass=False,
        prior_details_present=False, input_history=[],
    ) is None
    assert authority.retained_source_attempt_keys(
        [key], {}, current_source_review_input_identities={key: current},
        source_review_input_reservations={key: prior},
        source_review_input_reservation_history={key: []},
        eligible_legacy_input_keys={key},
    ) == [key]

    # The normal attempt filter opens this key only with the validated owner
    # record. Persisting both identities closes the same request on a retry.
    assert authority.retained_source_attempt_keys(
        [key], {}, current_source_review_input_identities={key: current},
        source_review_input_reservations={key: prior},
        source_review_input_reservation_history={key: []},
        eligible_legacy_input_keys={key}, allow_visual_spec_upgrade_keys={key},
    ) == []
    history = {key: [prior, current]}
    assert authority.retained_source_attempt_keys(
        [key], {}, current_source_review_input_identities={key: current},
        source_review_input_reservations={key: current},
        source_review_input_reservation_history=history,
        eligible_legacy_input_keys={key},
    ) == [key]

    # Stale owner pins, an already-recorded current identity, or a completed
    # review are not supersession authority.
    for changes in (
        {"prior_identity": "8" * 64},
        {"current_identity": "7" * 64},
        {"visual_spec_sha256": "6" * 64},
        {"prior_details_present": True},
        {"prior_details_present": True,
         "prior_reservation_details": {**prior_details, "inputIdentitySha256": "8" * 64}},
        {"prior_details_present": True,
         "prior_reservation_details": prior_details,
         "input_history": ["0" * 64]},
        {"current_validated_pass": True},
        {"input_history": [current]},
    ):
        values = {
            "prior_identity": prior,
            "current_identity": current,
            "visual_spec_sha256": visual_sha,
            "prior_details_present": False,
            "prior_reservation_details": None,
            "current_validated_pass": False,
            "input_history": [],
        }
        values.update(changes)
        assert _validated_source_review_input_supersession(
            key, explicit, prior_identity=values["prior_identity"],
            current_identity=values["current_identity"], current_context_sha256=context_sha,
            visual_spec_policy_version=1, visual_spec_sha256=values["visual_spec_sha256"],
            target_exercise_id=context["targetExerciseId"], historical_attempt=True,
            acknowledged=False, current_validated_pass=values["current_validated_pass"],
            prior_details_present=values["prior_details_present"],
            prior_reservation_details=values["prior_reservation_details"],
            input_history=values["input_history"],
        ) is None

    budget = _SourceTurnBudget(
        SimpleNamespace(exercise_timeout_seconds=300.0, source_review_timeout_seconds=300.0,
                        max_source_window_attempts=3),
        {"sourceTurnBudgetPolicyVersion": 3, "sourceTurnAttemptsUsed": 2,
         "sourceTurnElapsedSeconds": 225.523, "sourceTurnAttemptLimit": 2},
    )
    assert budget.attempts_used == 2 and budget.attempt_limit == 3
    assert budget.deadline - budget.started_at == pytest.approx(74.477, abs=0.01)
    assert budget.stop_reason() is None
    budget.begin_attempt()
    assert budget.attempts_used == 3
    assert budget.stop_reason() == "source_turn_attempt_budget"


def test_cache_only_source_review_miss_never_calls_caption(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source bytes")
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    item = bake.ReviewItem(
        exercise_index=0, candidate_rank=0, loop_index=-1,
        exercise_name="Cable Crunch", candidate_title="source",
        candidate_workspace=workspace, preview_html_path=workspace / "preview.html",
        skeleton_path=workspace / "wear" / "skeleton.json",
        review_video_path=workspace / "review.webm", duration_sec=1.0,
        loop_start_seconds=0.0, loop_end_seconds=1.0, candidate={},
        source_review_video_path=video,
    )
    monkeypatch.setattr(bake, "final_output_source_video_window", lambda _item: (video, bake.DetectionWindow(0, 0.0, 1.0)))
    monkeypatch.setattr(bake, "source_review_model_identity", lambda _settings: {"model": "current"})

    def forbidden_caption(**_kwargs):
        pytest.fail("cache-only misses must not call the caption provider")

    with pytest.raises(bake.SourceReviewCacheMiss):
        bake.validate_two_scale_source_with_caption_images(
            item, uniform_sheet_paths=[], output_dir=workspace / "review",
            caption_images=forbidden_caption, cache_only=True,
        )


def test_resume_identity_ignores_path_and_timestamp_bookkeeping(tmp_path):
    source_a = tmp_path / "a" / "source.mp4"
    source_b = tmp_path / "b" / "source.mp4"
    image_a = tmp_path / "a" / "sheet.jpg"
    image_b = tmp_path / "b" / "sheet.jpg"
    source_a.parent.mkdir()
    source_b.parent.mkdir()
    source_a.write_bytes(b"same source")
    source_b.write_bytes(b"same source")
    image_a.write_bytes(b"same image")
    image_b.write_bytes(b"same image")
    contract = {"exerciseName": "Cable Crunch", "definingAction": "raise and lower torso"}
    result_a = {
        "sourceIntervalSeconds": [0, 1], "frameInventory": [{"frameId": "A:1", "time": 0.0}],
        "uniformContactSheetPaths": [str(image_a)], "motionContactSheetPaths": [],
        "sourceReviewCache": {"checkpoint": "C:/old/cache/checkpoint.json", "cacheHit": False},
        "updatedAt": "before",
    }
    result_b = {
        **result_a, "uniformContactSheetPaths": [str(image_b)],
        "sourceReviewCache": {"checkpoint": "D:/new/cache/checkpoint.json", "cacheHit": True},
        "updatedAt": "after",
    }
    model_a = {"llama_cpp_model": {"path": "C:/models/current.gguf", "sha256": "model-digest"},
               "server": "8090"}
    model_b = {"llama_cpp_model": {"path": "D:/models/current.gguf", "sha256": "model-digest"},
               "server": "8090"}
    mapping_a = {"approvalArtifactPath": "C:/old/approval.json", "approvalArtifactSha256": "approved"}
    mapping_b = {"approvalArtifactPath": "D:/new/approval.json", "approvalArtifactSha256": "approved"}

    identity_a = bake._source_review_resume_content_identity(
        result=result_a, source_video=source_a, effective_contract=contract,
        model_identity=model_a, source_mapping=mapping_a,
    )
    identity_b = bake._source_review_resume_content_identity(
        result=result_b, source_video=source_b, effective_contract=contract,
        model_identity=model_b, source_mapping=mapping_b,
    )
    assert identity_a == identity_b
