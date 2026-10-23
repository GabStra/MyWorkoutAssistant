from __future__ import annotations

import json
from pathlib import Path

import pytest

from exercise_motion_pkg import bake_and_rank, youtube


def test_two_scale_uses_structured_required_accessory_and_marks_generated_contract_advisory():
    contract = {
        "status": "generated",
        "source": "llm",
        "motionContext": {
            "requiredAccessories": [{"name": "Rings", "type": "ACCESSORY"}],
        },
    }
    equipment = bake_and_rank.two_scale_named_equipment("Ring Fallout", contract)
    assert equipment == "rings"
    assert bake_and_rank.two_scale_required_equipment_observed(
        {"visibleEquipment": ["gymnastic rings"]}, equipment=equipment
    )
    multi_equipment_contract = {
        "motionContext": {
            "primaryEquipment": {"name": "Barbell", "type": "BARBELL"},
            "requiredAccessories": [{"name": "Bench", "type": "ACCESSORY"}],
        },
    }
    required = bake_and_rank.two_scale_required_equipment_names(
        "Supported Press", multi_equipment_contract
    )
    assert required == ["barbell", "bench"]
    assert bake_and_rank.two_scale_required_equipment_observed(
        {"visibleEquipment": ["barbell", "bench"]}, equipment=", ".join(required)
    )
    assert not bake_and_rank.two_scale_required_equipment_observed(
        {"visibleEquipment": ["barbell"]}, equipment=", ".join(required)
    )
    box_jump_requirements = bake_and_rank.two_scale_required_equipment_names(
        "Box Jump",
        {"motionContext": {"requiredAccessories": [{"name": "Adjustable Bench"}]}},
    )
    assert box_jump_requirements == ["box", "bench"]
    assert bake_and_rank.two_scale_required_equipment_observed(
        {"visibleEquipment": ["box"]}, equipment=", ".join(box_jump_requirements)
    )
    guidance = bake_and_rank.two_scale_contract_authority_guidance(contract)
    assert "model-generated advisory" in guidance
    assert "do not reject based only on generated posture" in guidance
    explicit_guidance = bake_and_rank.two_scale_contract_authority_guidance(
        {"status": "explicit", "source": "exercise_definition"}
    )
    assert "explicit exercise definition" in explicit_guidance


def test_contract_generation_does_not_infer_suspension_from_accessory_name():
    exercise = youtube.ExerciseEntry(
        exercise_id="ring-fallout",
        slug="ring-fallout",
        name="Ring Fallout",
        motion_context={
            "requiredAccessories": [{"name": "Rings", "type": "ACCESSORY"}],
        },
    )
    prompt = youtube.build_exercise_motion_contract_prompt(exercise)
    assert "Do not infer suspension, hanging, or a body-support posture from the accessory name alone" in prompt
    assert "use supportMode any" in prompt


@pytest.mark.parametrize("visible,evidence,expected", [
    (["none"], "standing upright with arms extended straight up holding a bar", False),
    ([], "The hands are raised, not holding a bar across the shoulders.", False),
    (None, "possibly holding a bar", False),
    (["barbell"], "both hands grip the implement", True),
])
def test_required_equipment_is_not_inferred_from_ambiguous_narrative(visible, evidence, expected):
    assert bake_and_rank.two_scale_required_equipment_observed(
        {"visibleEquipment": visible, "evidence": evidence}, equipment="barbell") is expected


def test_source_repair_stops_on_clear_target_blind_equipment_mismatch() -> None:
    validation = {
        "passed": False,
        "rejectionReasons": [
            "two_scale_source_identity_failed",
            "two_scale_source_required_equipment_not_observed",
            "two_scale_source_topology_not_verified",
        ],
        "exerciseMotionContract": {
            "status": "generated",
            "exerciseName": "Single Dumbbell Woodchopper",
            "motionContext": {
                "primaryEquipment": {"name": "Dumbbell", "type": "DUMBBELL"},
            },
        },
        "gates": {
            "identity": {
                "passed": False,
                "response": {"verdict": "mismatch", "visibleEquipment": ["kettlebell"]},
            },
            "targetBlindEquipmentDetail": {
                "clear": True,
                "requiredEquipmentObserved": False,
                "response": {
                    "heldEquipment": ["kettlebell"],
                    "objectCount": 1,
                    "visibleShape": "bell-shaped weight with a handle",
                    "holdingPattern": "held with both hands",
                    "uncertain": False,
                },
            },
            "topology": {
                "passed": False,
                "response": {"complete": False, "requiredEquipmentMatch": "mismatch"},
            },
        },
    }

    assert not bake_and_rank.two_scale_source_validation_needs_repair(validation)

    # Without a clear equipment contradiction, a separate positive topology
    # observation can still enter the existing bounded disagreement repair.
    validation["gates"]["targetBlindEquipmentDetail"]["response"]["uncertain"] = True
    validation["gates"]["topology"]["response"]["complete"] = True
    assert bake_and_rank.two_scale_source_validation_needs_repair(validation)

    cable_validation = {
        "passed": False,
        "rejectionReasons": [
            "two_scale_source_identity_failed",
            "two_scale_source_required_equipment_not_observed",
        ],
        "exerciseMotionContract": {
            "status": "generated",
            "exerciseName": "Cable Crunch",
            "motionContext": {"primaryEquipment": {"name": "Cable", "type": "PLATELOADEDCABLE"}},
        },
        "gates": {
            "identity": {
                "passed": False,
                "response": {
                    "verdict": "match",
                    "visibleEquipment": ["cable machine handle"],
                },
            },
            "targetBlindEquipmentDetail": {
                "clear": True,
                "response": {
                    "heldEquipment": ["cable machine handle"],
                    "objectCount": 1,
                    "visibleShape": "long handle with a cable attached",
                    "holdingPattern": "held with both hands",
                    "uncertain": False,
                },
            },
        },
    }
    assert bake_and_rank.two_scale_source_validation_needs_repair(cable_validation)


def make_review_item(tmp_path: Path, exercise_name: str = "Dumbbell Shrug") -> bake_and_rank.ReviewItem:
    placeholder = tmp_path / "placeholder"
    contract = {
        "status": "generated",
        "contractPolicyVersion": youtube.EXERCISE_MOTION_CONTRACT_POLICY_VERSION,
        "exerciseName": exercise_name,
        "advisoryText": "Source: exercise-specific start. Complete: phase one; phase two.",
        "movementType": "repetition",
        "groundContactMode": "continuous",
        "completionMode": "return_to_start",
        "requiresReturnToStart": True,
        "actionDefinitionStatus": "defined",
        "actionDefinitionAuthority": "trusted",
        "requiredPhases": ["perform the outward phase", "return to the starting posture"],
        "observableMotionSpec": {
            "schemaVersion": 1,
            "primaryMovingRegions": ["hands"],
            "referenceRegions": ["torso"],
            "primaryAxis": "vertical",
            "motionPattern": "joint_travel",
            "requiresReturnToStart": True,
            "oneWayPartialIsInvalid": True,
            "mustShowFullCycle": True,
            "mustBeVisibleRegions": ["hands", "torso"],
        },
        "startPoseConstraints": {
            "supportMode": "standing",
            "handHeight": "hip",
            "torsoOrientation": "upright",
            "kneeState": "extended",
            "stance": "shoulder_width",
        },
        "endPoseConstraints": {
            "supportMode": "standing",
            "handHeight": "hip",
            "torsoOrientation": "upright",
            "kneeState": "extended",
            "stance": "shoulder_width",
        },
        "movementTopology": {
            "schemaVersion": 1,
            "completionMode": "return_to_start",
            "startState": {"id": "start_state", "label": "exercise-specific start posture"},
            "phases": [
                {"id": "phase_01", "label": "exercise-specific outward phase"},
                {"id": "phase_02", "label": "exercise-specific return phase"},
            ],
            "endState": {"id": "end_state", "label": "exercise-specific start posture"},
        },
    }
    if "Lying" in exercise_name:
        for endpoint in ("startPoseConstraints", "endPoseConstraints"):
            contract[endpoint]["supportMode"] = "lying"
    return bake_and_rank.ReviewItem(
        exercise_index=0,
        candidate_rank=0,
        loop_index=-1,
        exercise_name=exercise_name,
        candidate_title=exercise_name,
        candidate_workspace=tmp_path,
        preview_html_path=placeholder,
        skeleton_path=placeholder,
        review_video_path=placeholder,
        duration_sec=4.0,
        loop_start_seconds=0.0,
        loop_end_seconds=4.0,
        candidate={"exerciseMotionContract": contract},
    )


def test_two_scale_peak_selector_captures_single_frame_spike_deterministically() -> None:
    scores = [0.0] * 300
    scores[20] = 10.0
    scores[137] = 100.0
    scores[260] = 8.0

    first = bake_and_rank.select_two_scale_motion_peak_indices(scores, 60.0)
    second = bake_and_rank.select_two_scale_motion_peak_indices(scores, 60.0)

    assert 137 in first
    assert first == second


def test_source_repair_guard_compares_held_item_to_active_implement_only():
    validation = {
        "passed": False,
        "rejectionReasons": [
            "two_scale_source_identity_failed",
            "two_scale_source_required_equipment_not_observed",
            "two_scale_source_topology_not_verified",
        ],
        "exerciseMotionContract": {
            "exerciseName": "Barbell Floor Press",
            "motionContext": {
                "primaryEquipment": {"name": "Barbell", "type": "BARBELL"},
                "requiredAccessories": [{
                    "name": "Squat Rack", "type": "SQUATRACK",
                    "capabilities": ["RACKED_BAR_SUPPORT"],
                }],
            },
        },
        "gates": {
            "identity": {"passed": False, "response": {"verdict": "uncertain"}},
            "targetBlindEquipmentDetail": {
                "response": {
                    "heldEquipment": ["barbell"], "objectCount": 1,
                    "visibleShape": "bar with plates", "holdingPattern": "both hands",
                    "uncertain": False,
                },
            },
            "topology": {"passed": False, "response": {"complete": True}},
        },
    }

    assert bake_and_rank.two_scale_source_validation_needs_repair(validation)


def topology_response(*, equipment_match: str = "match", complete: bool = True) -> dict[str, object]:
    return {
        "startStateMatch": "match" if complete else "mismatch",
        "phaseEvidence": [
            {"phaseId": "phase_01", "visible": complete, "position": 0.25, "evidence": "phase one"},
            {"phaseId": "phase_02", "visible": complete, "position": 0.75, "evidence": "phase two"},
        ],
        "endStateMatch": "match" if complete else "mismatch",
        "requiredEquipmentMatch": equipment_match,
        "complete": complete,
        "evidence": "complete ordered movement" if complete else "required phases are missing",
    }


def test_two_scale_source_caches_complete_rejection_for_exact_review_inputs(
    tmp_path: Path, monkeypatch,
) -> None:
    from types import SimpleNamespace

    source = tmp_path / "source.mp4"
    uniform_sheet = tmp_path / "uniform.jpg"
    source.write_bytes(b"source")
    uniform_sheet.write_bytes(b"sheet")
    motion_sheet = tmp_path / "motion.jpg"
    motion_sheet.write_bytes(b"motion")
    item = make_review_item(tmp_path)
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_source_video_window",
        lambda _item: (source, bake_and_rank.DetectionWindow(index=0, start_seconds=1.0, end_seconds=5.0)),
    )
    class Captioner:
        settings = SimpleNamespace(llama_cpp_model="model", llama_cpp_mmproj="project")

        def caption_images(self, **_kwargs: object) -> str:
            return "{}"

    captioner = Captioner()
    calls = 0

    def validate(_item: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "passed": False,
            "reviewStatus": "rejected",
            "missingEvidenceReasons": [],
            "rejectionReasons": ["two_scale_source_identity_failed"],
            "uniformContactSheetPaths": [str(uniform_sheet)],
            "motionContactSheetPaths": [str(motion_sheet)],
        }

    monkeypatch.setattr(bake_and_rank, "_validate_two_scale_source_uncached", validate)
    kwargs = {
        "item": item,
        "uniform_sheet_paths": [uniform_sheet],
        "output_dir": tmp_path / "review",
        "caption_images": captioner.caption_images,
    }

    first = bake_and_rank.validate_two_scale_source_with_caption_images(**kwargs)
    second = bake_and_rank.validate_two_scale_source_with_caption_images(**kwargs)

    assert calls == 1
    assert first["rejectionReasons"] == second["rejectionReasons"]
    assert second["reviewStatus"] == "rejected"
    assert first["sourceReviewCache"]["cacheHit"] is False
    assert second["sourceReviewCache"]["cacheHit"] is True


def test_two_scale_source_does_not_cache_incomplete_reviews(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    source = tmp_path / "source.mp4"
    uniform_sheet = tmp_path / "uniform.jpg"
    source.write_bytes(b"source")
    uniform_sheet.write_bytes(b"sheet")
    item = make_review_item(tmp_path)
    monkeypatch.setattr(
        bake_and_rank,
        "final_output_source_video_window",
        lambda _item: (source, bake_and_rank.DetectionWindow(index=0, start_seconds=1.0, end_seconds=5.0)),
    )
    class Captioner:
        settings = SimpleNamespace(llama_cpp_model="model", llama_cpp_mmproj="project")

        def caption_images(self, **_kwargs: object) -> str:
            return "{}"

    captioner = Captioner()
    calls = 0

    def validate(_item: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "passed": False,
            "reviewStatus": "incomplete",
            "missingEvidenceReasons": ["two_scale_source_identity_review_incomplete"],
            "rejectionReasons": [],
            "uniformContactSheetPaths": [],
            "motionContactSheetPaths": [],
        }

    monkeypatch.setattr(bake_and_rank, "_validate_two_scale_source_uncached", validate)
    kwargs = {
        "item": item,
        "uniform_sheet_paths": [uniform_sheet],
        "output_dir": tmp_path / "review",
        "caption_images": captioner.caption_images,
    }

    bake_and_rank.validate_two_scale_source_with_caption_images(**kwargs)
    bake_and_rank.validate_two_scale_source_with_caption_images(**kwargs)

    assert calls == 2


def test_retained_shape_discrete_contract_stops_before_generic_two_scale_approval(
    tmp_path: Path, monkeypatch,
) -> None:
    sheet = tmp_path / "motion.jpg"
    sheet.write_bytes(b"retained contact sheet")
    item = make_review_item(tmp_path, "Barbell High Pull")
    contract = {
        "status": "generated",
        "source": "reused_candidate_contract",
        "completionMode": "distinct_end_state",
    }
    calls = []
    monkeypatch.setattr(
        bake_and_rank, "final_output_motion_contact_sheets",
        lambda *_args, **_kwargs: [sheet],
    )
    monkeypatch.setattr(
        bake_and_rank, "resolve_two_scale_exercise_motion_contract",
        lambda _item, *, contract, caption_images: (contract, None, None),
    )
    result = bake_and_rank._validate_two_scale_source_uncached(
        item,
        uniform_sheet_paths=[sheet],
        output_dir=tmp_path / "validation",
        caption_images=lambda **kwargs: calls.append(kwargs) or json.dumps({"complete": True}),
        exercise_motion_contract=contract,
    )
    assert result["passed"] is False
    assert result["reviewStatus"] == "incomplete"
    assert result["missingEvidenceReasons"] == ["two_scale_source_action_definition_unresolved"]
    assert result["gates"]["actionDefinition"]["passed"] is False
    assert calls == []
