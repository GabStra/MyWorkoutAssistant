from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
)
from exercise_motion_pkg.youtube import (
    ExerciseEntry,
    normalize_body_support_requirements,
    normalize_definition_exercise_motion_contract_response,
)


def _requirements():
    return {
        "required": [{"region": "ankle", "side": "both", "surface": "external_anchor"}],
        "prohibited": [{"region": "hand", "side": "both"}],
    }


def _evidence(observation, digest="selected-video"):
    return {
        "sourceVideoSha256": digest,
        "bodySupportObservation": {
            "status": "observed",
            "source": "exact_source_visual_support_observation",
            "sourceVideoSha256": digest,
            "policyVersion": POLICY_VERSION,
            "observation": observation,
        },
    }


def _add_timed_contacts(evidence, contacts, digest="selected-video"):
    evidence["bodySupportObservation"]["contactTimeline"] = {
        "schemaVersion": 1,
        "policyVersion": CONTACT_TIMELINE_POLICY_VERSION,
        "source": "exact_source_visual_contact_timeline",
        "sourceClock": "video_frame_zero_seconds",
        "sourceVideoSha256": digest,
        "status": "observed",
        "samples": [
            {
                "sampleId": f"{joint}-{frame}",
                "sourceTimeSec": frame / 30,
                "side": side,
                "landmark": landmark,
                "jointName": joint,
                "contactState": state,
                "surface": surface,
                "visible": True,
                "sourceTrackStationary": True,
                "sourcePoseFrameIndex": frame,
                "sourceFrameIndex": frame,
                "sourceFps": 30,
            }
            for joint, side, landmark, state, surface, frame in contacts
        ],
    }
    return evidence


def _timed_pair(joint, side, landmark, state, surface):
    return [(joint, side, landmark, state, surface, frame) for frame in (30, 60)]


def test_body_support_normalizer_canonicalizes_common_model_forms():
    assert normalize_body_support_requirements({
        "required": [
            {"region": "feet", "surface": "ground"},
            {"region": "upper_back", "surface": "bench"},
        ],
        "prohibited": [],
    }) == {
        "required": [
            {"region": "foot", "side": "both", "surface": "ground"},
            {"region": "upper_back", "side": "center", "surface": "bench"},
        ],
        "prohibited": [],
    }


def test_body_support_normalizer_preserves_generic_region_and_optional_contact_mode():
    assert normalize_body_support_requirements({
        "required": [
            {"region": "shin", "side": "left", "surface": "bench", "contactMode": "sliding"},
            {"region": "shoulder", "side": "right", "surface": "wall", "contactMode": "stationary"},
            {"region": "upper_back", "side": "center", "surface": "bench"},
        ],
        "prohibited": [],
    }) == {
        "required": [
            {"region": "shin", "side": "left", "surface": "bench", "contactMode": "sliding"},
            {"region": "shoulder", "side": "right", "surface": "wall", "contactMode": "stationary"},
            {"region": "upper_back", "side": "center", "surface": "bench"},
        ],
        "prohibited": [],
    }
    assert normalize_body_support_requirements({
        "required": [{"region": "shoulder", "side": "left"}], "prohibited": [],
    }) == {"required": [{"region": "shoulder", "side": "left"}], "prohibited": []}


@pytest.mark.parametrize("entry", [
    {"region": "", "side": "left"},
    {"region": "shin!", "side": "left"},
    {"region": {"name": "shin"}, "side": "left"},
    {"region": "shin", "side": "left", "surface": "unknown_surface"},
    {"region": "shin", "side": "left", "contactMode": "bouncing"},
    {"region": "shin", "side": "left", "contactMode": 4},
    {"region": "ankle", "side": "center"},
    {"region": "upper_back", "side": "left"},
])
def test_body_support_normalizer_rejects_malformed_generic_region_or_mode(entry):
    assert normalize_body_support_requirements({
        "required": [entry], "prohibited": [],
    }) is None


def test_body_support_requirements_require_exact_matching_evidence():
    contract = {"advisoryText": "Nordic curl", "bodySupportRequirements": _requirements()}
    passing = _evidence({
        "leftAnkle": "stationary_support", "rightAnkle": "stationary_support",
        "leftAnkleContactSurface": "fixed_bar", "rightAnkleContactSurface": "fixed_bar",
        "leftHand": "moving", "rightHand": "moving",
    })
    _add_timed_contacts(passing, [
        *_timed_pair("left_ankle", "left", "joint", "direct_contact", "fixed_bar"),
        *_timed_pair("right_ankle", "right", "joint", "direct_contact", "fixed_bar"),
    ])
    contradicted = _evidence({
        "leftAnkle": "moving", "rightAnkle": "moving",
        "leftHand": "stationary_support", "rightHand": "stationary_support",
        "leftHandContactSurface": "floor", "rightHandContactSurface": "floor",
    })
    _add_timed_contacts(contradicted, [
        *_timed_pair("left_wrist", "left", "joint", "direct_contact", "floor"),
        *_timed_pair("right_wrist", "right", "joint", "direct_contact", "floor"),
    ])
    unknown = _evidence({"leftAnkle": "unknown", "rightAnkle": "unknown"})
    stale = _evidence({
        "leftAnkle": "stationary_support", "rightAnkle": "stationary_support",
        "leftAnkleContactSurface": "fixed_bar", "rightAnkleContactSurface": "fixed_bar",
    }, digest="other-video")

    assert bake.body_support_contract_evidence_status(contract, passing)["status"] == "passed"
    assert bake.body_support_contract_evidence_status(contract, contradicted)["status"] == "contradicted"
    assert bake.body_support_contract_evidence_status(contract, unknown)["status"] == "insufficient_evidence"
    assert bake.body_support_contract_evidence_status(contract, stale)["status"] == "insufficient_evidence"


def test_nonfoot_positive_without_timed_contact_is_insufficient():
    contract = {"bodySupportRequirements": _requirements()}
    evidence = _evidence({
        "leftAnkle": "stationary_support", "rightAnkle": "stationary_support",
        "leftAnkleContactSurface": "fixed_bar", "rightAnkleContactSurface": "fixed_bar",
        "leftHand": "moving", "rightHand": "moving",
    })
    assert bake.body_support_contract_evidence_status(contract, evidence)["status"] == "insufficient_evidence"


def test_nonfoot_positive_with_negative_timeline_is_insufficient():
    contract = {"bodySupportRequirements": _requirements()}
    evidence = _evidence({
        "leftAnkle": "stationary_support", "rightAnkle": "stationary_support",
        "leftAnkleContactSurface": "fixed_bar", "rightAnkleContactSurface": "fixed_bar",
        "leftHand": "moving", "rightHand": "moving",
    })
    _add_timed_contacts(evidence, [
        *_timed_pair("left_ankle", "left", "joint", "no_contact", "none"),
        *_timed_pair("right_ankle", "right", "joint", "no_contact", "none"),
    ])
    assert bake.body_support_contract_evidence_status(contract, evidence)["status"] == "insufficient_evidence"


def test_nonfoot_mixed_fine_surfaces_do_not_corroborate_coarse_surface():
    contract = {"bodySupportRequirements": _requirements()}
    evidence = _evidence({
        "leftAnkle": "stationary_support", "rightAnkle": "stationary_support",
        "leftAnkleContactSurface": "fixed_bar", "rightAnkleContactSurface": "fixed_bar",
        "leftHand": "moving", "rightHand": "moving",
    })
    _add_timed_contacts(evidence, [
        *_timed_pair("left_ankle", "left", "joint", "direct_contact", "fixed_bar"),
        *_timed_pair("right_ankle", "right", "joint", "direct_contact", "other"),
    ])
    assert bake.body_support_contract_evidence_status(contract, evidence)["status"] == "insufficient_evidence"


def test_prohibited_coarse_negative_conflicting_with_fine_contact_is_unknown():
    contract = {"bodySupportRequirements": {
        "required": [],
        "prohibited": [{"region": "hand", "side": "both"}],
    }}
    evidence = _evidence({
        "leftHand": "unsupported", "rightHand": "unsupported",
        "leftHandContactSurface": "none", "rightHandContactSurface": "none",
    })
    _add_timed_contacts(evidence, _timed_pair(
        "left_wrist", "left", "joint", "direct_contact", "fixed_bar",
    ))
    assert bake.body_support_contract_evidence_status(contract, evidence)["status"] == "insufficient_evidence"


def test_exact_source_contact_timeline_supplies_unknown_foot_fields():
    digest = "selected-video"
    contract = {"bodySupportRequirements": {
        "required": [{"region": "foot", "side": "both", "surface": "ground"}],
        "prohibited": [],
    }}
    evidence = _evidence({"leftFoot": "unknown", "rightFoot": "unknown"}, digest)
    evidence["bodySupportObservation"]["contactTimeline"] = {
        "schemaVersion": 1,
        "policyVersion": CONTACT_TIMELINE_POLICY_VERSION,
        "source": "exact_source_visual_contact_timeline",
        "sourceClock": "video_frame_zero_seconds",
        "sourceVideoSha256": digest,
        "status": "observed",
        "samples": [
            {
                "sampleId": f"{side}-{frame}",
                "sourceTimeSec": frame / 30,
                "side": side,
                "contactState": "full_sole",
                "surface": "ground",
                "visible": True,
                "sourceTrackStationary": True,
                "sourcePoseFrameIndex": frame // 4,
                "sourceFrameIndex": frame,
                "sourceFps": 30,
            }
            for side, frame in (("left", 30), ("right", 30))
        ],
    }

    assert bake.body_support_contract_evidence_status(contract, evidence)["status"] == "passed"
    evidence["bodySupportObservation"]["contactTimeline"]["sourceVideoSha256"] = "other-video"
    assert bake.body_support_contract_evidence_status(contract, evidence)["status"] == "insufficient_evidence"


def test_definition_contract_cannot_omit_typed_support_requirements():
    exercise = ExerciseEntry(exercise_id="nordic", name="Nordic Curl", slug="nordic-curl")
    payload = {
        "movementType": "repetition",
        "completionMode": "return_to_start",
        "groundContactMode": "continuous",
        "primaryMovingRegions": ["knees"],
        "referenceRegions": ["feet"],
        "primaryAxis": "horizontal",
        "motionPattern": "body_away_from_anchor",
    }

    with pytest.raises(ValueError, match="bodySupportRequirements"):
        normalize_definition_exercise_motion_contract_response(payload, exercise=exercise, source="llm")


def test_source_pose_support_cache_tracks_required_and_prohibited_contacts():
    original = {'groundContactMode': 'continuous', 'completionMode': 'return_to_start'}
    required = {**original, 'bodySupportRequirements': _requirements()}
    prohibited = {**original, 'bodySupportRequirements': {
        'required': [], 'prohibited': [{'region': 'hand', 'side': 'both'}]}}
    assert len({bake.source_pose_support_contract_fingerprint(contract)
                for contract in (original, required, prohibited)}) == 3
    assert bake.source_pose_support_contract_fingerprint(required) == (
        bake.source_pose_support_contract_fingerprint({**required, 'generatedAt': 'later'}))
    assert bake.source_pose_support_contract_fingerprint(original) == (
        bake.source_pose_support_contract_fingerprint({**original, 'bodySupportRequirements': {
            'required': [], 'prohibited': []}}))


def test_incompatible_source_support_is_rejected_before_preview_fit(tmp_path, monkeypatch):
    contract = {"advisoryText": "Nordic curl", "bodySupportRequirements": _requirements()}
    evidence = _evidence({
        "leftAnkle": "unknown", "rightAnkle": "unknown",
        "leftHand": "stationary_support", "leftHandContactSurface": "floor",
        "rightHand": "unknown",
    })
    candidate = bake.RankedCandidate(0, 0, "Example", "Channel", "example", {
        "videoId": "retained", "exerciseMotionContract": contract,
    })
    request = bake.BakeAndRankRequest(tmp_path / "candidates.json", tmp_path, None)
    monkeypatch.setattr(bake, "evaluate_source_candidate_gate", lambda *_a, **_k: {"passed": True})
    monkeypatch.setattr(
        bake,
        "generate_candidate_motion",
        lambda *_a, **_k: SimpleNamespace(
            raw_motion_json_path=tmp_path / "raw.json",
            cleaned_motion_json_path=tmp_path / "cleaned.json",
            timings=None,
        ),
    )
    monkeypatch.setattr(bake, "generation_to_manifest", lambda _result: {})
    monkeypatch.setattr(bake, "evaluate_generated_motion_recovery_gate", lambda **_k: {"passed": True})
    monkeypatch.setattr(bake, "load_motion_json", lambda *_a, **_k: {})
    monkeypatch.setattr(bake, "pre_reconstruction_source_interval_authority", lambda **_k: {})
    monkeypatch.setattr(bake, "pre_reconstruction_source_foot_support_evidence", lambda *_a, **_k: evidence)

    result = bake.process_ranked_candidate(
        candidate,
        request=request,
        preview_baker=lambda *_a, **_k: pytest.fail("incompatible support reached controlled fitting"),
        review_items=[],
        review_item_entries=[],
        support_dominance_classifier=None,
    )

    assert result["status"] == "rejected_source_support_contract", result.get("failures", [{}])[0].get("traceback")
    assert result["sourceSupportContractEvidence"]["status"] == "insufficient_evidence"
