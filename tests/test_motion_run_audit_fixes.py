import json
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import source_review_preflight as preflight
from exercise_motion_pkg import wave_pipeline as wave


def test_manual_review_fallback_is_exportable_from_a_staged_wave():
    assert wave.wave_manifest_is_exportable({"selected": {"selectedWearSkeletonPath": "x"}})
    assert wave.wave_manifest_is_exportable({
        "selected": None,
        "selectionStatus": "needs_manual_review",
        "manualReviewFallback": {"selectedWearSkeletonPath": "x"},
    })
    assert not wave.wave_manifest_is_exportable({
        "selected": None,
        "selectionStatus": "needs_manual_review",
    })
    assert not wave.wave_manifest_is_exportable({
        "selected": None,
        "selectionStatus": "failed",
        "manualReviewFallback": {"selectedWearSkeletonPath": "x"},
    })
    assert wave.wave_retry_disposition({"status": "completed"}) == "export_selected"


@pytest.mark.parametrize("reason,expected", [
    ("no_approved_discovery_candidates", "next_source"),
    ("no_reconstruction_ready_source", "next_source"),
    ("source_processing_failed", "retry_infrastructure"),
    ("source_review_incomplete", "retry_review"),
])
def test_source_exhaustion_does_not_trigger_individual_infrastructure_retry(reason, expected):
    state = {"status": "retry_required", "source": {
        "status": "failed", "failureReason": reason, "attempts": [],
    }}
    assert wave.wave_retry_disposition(state) == expected


@pytest.mark.parametrize("rotation,camera,passed", [
    (180, -45, True), (179.62562857778346, -45.37437142221654, True),
    (179.94259943482632, -45.05740056517368, True),
    (0, 135, True), (180, 135, False), (0, -45, False),
])
def test_export_camera_compensation(rotation, camera, passed):
    payload = {"wearDisplay": {"viewYawDegrees": camera},
        "bakedPreviewConfiguration": {"bakedSagittalPlaneAlignment": {
            "applied": True, "yawDegrees": rotation}}}
    assert bake.materialized_camera_is_canonical(payload) is passed


@pytest.mark.parametrize("reference,events", [(None, ["handoff", "compute"]),
                                            ({"frames": []}, ["compute"])])
def test_materialized_metrics_only_handoff_for_missing_pose(monkeypatch, reference, events):
    calls = []
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "materialized_output_acceptance_metrics",
        lambda *args, **kwargs: calls.append("compute") or {"passed": True})
    monkeypatch.setattr(bake, "run_with_caption_gpu_exclusive",
        lambda caption, operation: calls.append("handoff") or operation())
    bake.materialized_metrics_with_gpu_handoff(SimpleNamespace(loop_index=-1), None,
        caption_images=None, source_pose_reference=reference)
    assert calls == events


@pytest.mark.parametrize("status,attempts", [("needs_source_review", 2), ("ready_for_selection", 1), ("failed", 1)])
def test_review_retry_is_bounded_and_owner_specific(status, attempts):
    calls = []
    def run():
        calls.append(1)
        return {"selected": None, "selectionStatus": "needs_manual_review",
            "candidateResults": [{"status": status}]}
    result = wave.finalize_with_bounded_review_retry(run)
    assert len(calls) == result["reviewAttemptCount"] == attempts
    disposition = wave.wave_retry_disposition({"finalValidation": {
        "status": "no_selection", **wave.final_processing_diagnostics(result)}})
    assert disposition == {"needs_source_review": "retry_review", "ready_for_selection": "next_source",
                           "failed": "retry_infrastructure"}[status]


def test_review_retry_stops_when_second_review_succeeds():
    manifests = iter([
        {"selected": None, "candidateResults": [{"status": "needs_source_review"}]},
        {"selected": {"artifact": "approved"}, "candidateResults": []},
    ])
    result = wave.finalize_with_bounded_review_retry(lambda: next(manifests))
    assert result["selected"] == {"artifact": "approved"}
    assert result["reviewAttemptCount"] == 2


@pytest.mark.parametrize("entry_key", ["rejectedBest", "manualReviewFallback"])
def test_outer_retry_does_not_multiply_completed_candidate_review_budget(entry_key):
    calls = []
    def run():
        calls.append(1)
        return {"selected": None, "candidateResults": [{"status": "needs_manual_review"}],
                entry_key: {"ranking": {"payload": {"finalOutputValidation": {
                    "passed": False, "failureOwner": "review", "underlyingMotionRejected": False,
                    "boundedReview": {"additionalReviewCount": 1},
                    "rejectionReasons": ["visual_review_unresolved"]}}}}}
    result = wave.finalize_with_bounded_review_retry(run)
    assert len(calls) == 1
    assert result["selected"] is None
    assert result["reviewRetrySkippedReason"] == "candidate_review_budget_exhausted"


def test_incomplete_source_review_does_not_penalize_source(tmp_path, monkeypatch):
    request = SimpleNamespace(source_outcome_index=tmp_path / "outcomes.json")
    item = wave.StagedWaveItem("curl", "Curl", request)
    monkeypatch.setattr(wave, "_wave_candidates_for_item", lambda item: [])
    monkeypatch.setattr(wave, "update_source_outcome_index",
        lambda *args: pytest.fail("Incomplete evidence must not become a quality outcome"))
    state = {"source": {"failureReason": "source_review_incomplete",
        "attempts": [{"status": "needs_source_review", "videoId": "id"}]}}
    assert wave.wave_retry_disposition(state) == "retry_review"
    assert wave._record_wave_source_rejections([item], {"curl": state}) == []


def test_complete_source_review_cache_tracks_video_contract_model_and_frames(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"first")
    sheet = tmp_path / "frame.jpg"
    sheet.write_bytes(b"frame")
    item = SimpleNamespace(exercise_name="Curl", candidate_workspace=tmp_path, candidate={})
    model = SimpleNamespace(llama_cpp_model="model-one")
    class Session:
        settings = model
        def caption_images(self): pass
    monkeypatch.setattr(bake, "final_output_source_video_window",
        lambda item: (video, bake.DetectionWindow(0, 0, 5)))
    calls = []
    passed = [True]
    def validate(*args, **kwargs):
        calls.append(1)
        return {"passed": passed[0], "uniformContactSheetPaths": [str(path) for path in kwargs['uniform_sheet_paths']],
                "motionContactSheetPaths": []}
    monkeypatch.setattr(bake, "_validate_two_scale_source_uncached", validate)
    def run(contract=None, sheets=None):
        return bake.validate_two_scale_source_with_caption_images(item, uniform_sheet_paths=sheets or [sheet],
            output_dir=tmp_path / "review", caption_images=Session().caption_images,
            exercise_motion_contract=contract)
    run(); run()
    assert len(calls) == 1
    video.write_bytes(b"changed"); run()
    run({"policy": 2}); model.llama_cpp_model = "model-two"; run({"policy": 2})
    sheet.write_bytes(b"changed frame"); run({"policy": 2})
    assert len(calls) == 5
    passed[0] = False
    run({"policy": 3}); run({"policy": 3})
    assert len(calls) == 7  # Incomplete or rejected reviews never become accepted cache hits.
    passed[0] = True
    run(); run()
    assert len(calls) == 8
    item.candidate['exerciseMotionContract'] = {'advisoryText': 'Updated explicit loading requirement'}
    run(); run()
    assert len(calls) == 9  # The implicit candidate contract is the reviewed contract too.
    alternative = tmp_path / 'other-frame.jpg'
    alternative.write_bytes(b'other sampling of the same video')
    run(sheets=[alternative]); run(sheets=[alternative])
    assert len(calls) == 10  # Existing old sheets have not changed; the supplied evidence has.
    detail = tmp_path / 'original.jpg'
    detail.write_bytes(b'full-resolution implement')
    (tmp_path / 'contact_sheet_crop.json').write_text(json.dumps({'framePaths': [str(detail)]}))
    run(sheets=[alternative]); run(sheets=[alternative])
    assert len(calls) == 11
    detail.write_bytes(b'changed original implement')
    run(sheets=[alternative])
    assert len(calls) == 12


@pytest.mark.parametrize("passed,review_status,expected_calls", [(True, "passed", 1), (False, "incomplete", 2), (False, "rejected", 1)])
def test_preflight_review_defers_uncertain_evidence_before_reconstruction(tmp_path, monkeypatch, passed, review_status, expected_calls):
    candidate = bake.RankedCandidate(0, 1, "curl", "Curl", "curl", {"videoId": "id", "title": "Curl"})
    request = SimpleNamespace(two_scale_source_validation=True, workspace=tmp_path)
    monkeypatch.setattr(bake, "read_basic_video_metadata", lambda path: SimpleNamespace(duration_seconds=5))
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **k: [])
    monkeypatch.setattr(bake, "pre_wham_exact_source_phase_reference_metrics", lambda item: {})
    monkeypatch.setattr(bake, "validate_source_pose_endpoints_against_contract", lambda *a, **k: {})
    for name in ("small_motion", "completeness", "identity", "topology"):
        monkeypatch.setattr(bake, f"two_scale_{name}_failure_is_independent_outlier", lambda **k: False)
    monkeypatch.setattr(bake, "two_scale_source_validation_needs_repair", lambda validation: False)
    calls = []
    def validate(*args, **kwargs):
        calls.append(1)
        return {"passed": passed, "reviewStatus": review_status, "rejectionReasons": ["unresolved"]}
    monkeypatch.setattr(bake, "validate_two_scale_source_with_caption_images", validate)
    def run():
        preflight.review_prepared_source(candidate, request=request, selected_video=tmp_path / "source.mp4",
            contract=None, caption_images=lambda: "")
    if passed:
        run()
    else:
        error = preflight.SourceReviewIncomplete if review_status == "incomplete" else bake.SourceCandidateRejected
        with pytest.raises(error): run()
    assert len(calls) == expected_calls
