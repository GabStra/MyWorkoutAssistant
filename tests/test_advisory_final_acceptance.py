import json
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.acceptance import decide_acceptance
from exercise_motion_pkg.visual_evidence import parse_visual_observations


def request(**kw):
    return SimpleNamespace(final_output_validation=True, two_scale_source_validation=False, **kw)


def setup_render(tmp_path, monkeypatch):
    image = tmp_path / "render.jpg"
    image.write_bytes(b"fixture")
    monkeypatch.setattr(bake, "final_output_preview_contact_sheets", lambda *a, **k: [image])
    monkeypatch.setattr(bake, "final_output_validation_artifact_slug", lambda _: "fixture")
    return SimpleNamespace(candidate_workspace=tmp_path)


@pytest.mark.parametrize("observer", [
    {"advisoryOnly": True, "status": "unavailable", "findings": []},
    {"advisoryOnly": True, "status": "observed", "findings": [{"kind": "recognizability", "observation": "Looks wrong"}],
     "passed": False, "reject": ["wrong_exercise"], "retry": True, "score": 0.},
])
def test_optional_model_cannot_veto_or_score_required_evidence(tmp_path, monkeypatch, observer):
    item = setup_render(tmp_path, monkeypatch)
    monkeypatch.setattr(bake, "validate_final_output_with_caption_images", lambda *a, **k: observer)
    metrics = {"passed": True}
    final = bake.final_output_validation_metrics(item, None, request=request(),
        deterministic_metrics=metrics, caption_images=lambda: None)
    assert final["passed"] and "score" not in final
    assert bake.final_output_hard_rejection_reasons(final) == []
    decision = decide_acceptance(metrics, final, deterministic_rejections=[], review_rejections=[])
    assert decision.status == "valid" and not decision.can_regenerate_motion


def test_model_service_failure_is_optional_after_required_evidence(tmp_path, monkeypatch):
    item = setup_render(tmp_path, monkeypatch)
    def fail(*a, **k):
        raise TimeoutError("optional observer")
    monkeypatch.setattr(bake, "validate_final_output_with_caption_images", fail)
    final = bake.final_output_validation_metrics(item, None, request=request(),
        deterministic_metrics={"passed": True}, caption_images=lambda: None)
    assert final["passed"] and final["visualReview"]["status"] == "unavailable"


def test_missing_render_is_not_approval_or_geometry_regeneration(tmp_path, monkeypatch):
    item = setup_render(tmp_path, monkeypatch)
    monkeypatch.setattr(bake, "final_output_preview_contact_sheets", lambda *a, **k: [])
    final = bake.final_output_validation_metrics(item, None, request=request(),
        deterministic_metrics={"passed": True}, caption_images=None)
    decision = decide_acceptance({"passed": True}, final, deterministic_rejections=[],
        review_rejections=bake.final_output_hard_rejection_reasons(final))
    assert decision.status == "needs_manual_review" and decision.failure_owner == "rendering"
    assert not decision.can_regenerate_motion


def test_required_source_review_failure_is_preserved(tmp_path, monkeypatch):
    item = setup_render(tmp_path, monkeypatch)
    monkeypatch.setattr(bake, "validate_final_output_with_caption_images", lambda *a, **k: {
        "passed": False, "backend": "llama_cpp_vision_two_scale_source", "hardRejectionReasons": ["source_identity_mismatch"]})
    req = request(); req.two_scale_source_validation = True
    final = bake.final_output_validation_metrics(item, None, request=req,
        deterministic_metrics={"passed": True}, caption_images=lambda: None)
    decision = decide_acceptance({"passed": True}, final, deterministic_rejections=[],
        review_rejections=bake.final_output_hard_rejection_reasons(final))
    assert decision.status == "invalid" and decision.failure_owner == "source"
    assert not decision.can_regenerate_motion


def test_missing_required_source_service_does_not_approve(tmp_path, monkeypatch):
    item = setup_render(tmp_path, monkeypatch)
    req = request()
    req.two_scale_source_validation = True
    final = bake.final_output_validation_metrics(item, None, request=req,
        deterministic_metrics={"passed": True}, caption_images=None)
    decision = decide_acceptance({"passed": True}, final, deterministic_rejections=[],
        review_rejections=bake.final_output_hard_rejection_reasons(final))
    assert decision.status == "needs_manual_review" and decision.failure_owner == "source"
    assert not decision.can_regenerate_motion


def test_bare_observation_cannot_replace_required_render_evidence():
    decision = decide_acceptance({"passed": True}, {"advisoryOnly": True, "status": "observed"},
        deterministic_rejections=[], review_rejections=[])
    assert decision.status == "needs_manual_review" and decision.failure_owner == "rendering"


def test_malformed_optional_observation_is_unavailable():
    assert parse_visual_observations(None, [0])["status"] == "unavailable"


def test_numeric_failure_short_circuits_optional_observer():
    final = bake.final_output_validation_metrics(None, None, request=request(),
        deterministic_metrics={"passed": False, "rejectionReasons": ["postprocess_joint_spike"]},
        caption_images=lambda: pytest.fail("No optional review on broken motion"))
    assert not final["passed"] and final["deterministicGateBlocking"]


def test_observation_parser_discards_invented_verdict_and_frame_fields():
    parsed = parse_visual_observations({"approved": False, "reject": ["wrong_variant"], "retry": True,
        "findings": [{"kind": "mesh", "frameIndices": [4], "observation": "Possible deformation."},
                     {"kind": "mesh", "frameIndices": [999], "observation": "Invented sample"}]}, [4])
    assert parsed["advisoryOnly"] and len(parsed["findings"]) == 1
    assert not {"approved", "passed", "reject", "retry", "score"}.intersection(parsed)


@pytest.mark.parametrize("model_fails", [False, True])
def test_single_observation_call_has_no_corroboration(tmp_path, monkeypatch, model_fails):
    export = {"frameCount": 2, "frames": [{"timeSec": 0, "joints": {}}, {"timeSec": 1, "joints": {}}]}
    skeleton = tmp_path / "skeleton.json"; skeleton.write_text(json.dumps(export))
    item = bake.ReviewItem(exercise_index=0, candidate_rank=0, loop_index=-1,
        exercise_name="Movement", candidate_title="Title", candidate_workspace=tmp_path,
        preview_html_path=tmp_path / "preview.html", skeleton_path=skeleton,
        review_video_path=tmp_path / "unused.webm", duration_sec=1., loop_start_seconds=0., loop_end_seconds=1., candidate={})
    setup_render(tmp_path, monkeypatch)
    monkeypatch.setattr(bake, "exercise_motion_contract_for_review_item", lambda *a: {})
    monkeypatch.setattr(bake, "final_output_source_contact_sheets", lambda *a, **k: [])
    monkeypatch.setattr(bake, "validate_two_scale_source_with_caption_images", lambda *a, **k: {"passed": True})
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        if model_fails:
            raise TimeoutError("Optional observer timeout after source validation")
        return json.dumps({"findings": [{"kind": "mesh", "frameIndices": [0], "observation": "Possible artifact"}]})
    req = bake.BakeAndRankRequest(candidates_json=tmp_path / "unused.json", workspace=tmp_path,
        wham_repo_path=None, body_model_root=None, final_output_validation=True, two_scale_source_validation=True)
    result = bake.final_output_validation_metrics(item, bake.LoopRanking(.9, [], {}),
        request=req, caption_images=caption, deterministic_metrics={"passed": True})
    assert result["passed"] and result["sourceEvidence"]["passed"]
    assert result["visualReview"]["advisoryOnly"] and len(calls) == 1
    assert "boundedReview" not in result["visualReview"]
    assert result["visualReview"]["status"] == ("unavailable" if model_fails else "observed")
