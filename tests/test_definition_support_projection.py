import json

import pytest

from exercise_motion_pkg import youtube


APPROVED_ACTION = "Kneel on both knees and curl the cable toward the head."
MODEL_KNEE_PROJECTION = {
    "required": [{"region": "knee", "side": "both", "surface": "ground"}],
    "prohibited": [],
}


def _exercise(definition):
    return youtube.ExerciseEntry(
        exercise_id="cable-crunch",
        name="Cable Crunch",
        slug="cable-crunch",
        motion_context={
            "exerciseDefinition": {
                "definingAction": definition,
                "completionMode": "return_to_start",
                "review": {"status": "approved"},
            },
            "requiredAccessories": [{"id": "cable-station"}],
        },
    )


def _definition_contract_payload():
    return {
        "movementType": "repetition",
        "completionMode": "return_to_start",
        "bodySupportRequirements": MODEL_KNEE_PROJECTION,
        "primaryMovingRegions": ["torso"],
        "referenceRegions": ["upper_limb"],
        "primaryAxis": "vertical",
        "motionPattern": "joint_flex_extend",
    }


def test_pre_video_definition_projection_survives_normalization_and_reconcile():
    exercise = _exercise(APPROVED_ACTION)

    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _definition_contract_payload(), exercise=exercise, source="llm",
    )

    # A model projection is never a hard obligation; it survives only as a
    # discovery hint asking source inspection to confirm the contact.
    assert contract["bodySupportRequirements"] == {"required": [], "prohibited": []}
    assert contract["bodySupportDiscoveryHints"] == MODEL_KNEE_PROJECTION
    assert contract["bodySupportDiscoveryHintsAuthority"] == "definition_projection"
    assert contract["bodySupportDiscoveryHintsDefinitionDigest"]
    prompt_contract = youtube.exercise_motion_contract_for_prompt(contract)
    assert prompt_contract["bodySupportRequirements"] == {"required": [], "prohibited": []}
    assert "bodySupportDiscoveryHints" not in prompt_contract
    assert "bodySupportDiscoveryHintsAuthority" not in prompt_contract
    assert "bodySupportDiscoveryHintsDefinitionDigest" not in prompt_contract

    stored = json.loads(json.dumps(contract))
    renormalized = youtube.normalize_exercise_motion_contract(
        stored, exercise=exercise, source="cache",
    )
    assert renormalized["bodySupportRequirements"] == {"required": [], "prohibited": []}
    assert renormalized["bodySupportDiscoveryHints"] == MODEL_KNEE_PROJECTION
    reconciled = youtube.reconcile_exercise_motion_contract_definition(stored, exercise)
    assert reconciled["bodySupportRequirements"] == {"required": [], "prohibited": []}
    assert reconciled["bodySupportDiscoveryHints"] == MODEL_KNEE_PROJECTION
    assert reconciled["bodySupportDiscoveryHintsAuthority"] == "definition_projection"


def test_general_contract_proposals_cannot_establish_requested_support():
    exercise = _exercise(APPROVED_ACTION)
    projection = {
        "required": [{"region": "pelvis", "side": "center", "surface": "ground"}],
        "prohibited": [],
    }

    contract = youtube.normalize_exercise_motion_contract(
        {
            "advisoryText": "Hinge the torso and pull the implement toward it.",
            "movementType": "repetition",
            "completionMode": "return_to_start",
            "bodySupportRequirements": projection,
            "bodySupportDiscoveryHints": projection,
            "bodySupportDiscoveryHintsAuthority": "definition_projection",
            "bodySupportDiscoveryHintsDefinitionDigest": (
                youtube.exercise_motion_definition_support_projection_digest(exercise)
            ),
        },
        exercise=exercise,
        source="llm",
    )

    assert "bodySupportRequirements" not in contract
    assert "bodySupportDiscoveryHints" not in contract
    assert "bodySupportDiscoveryHintsAuthority" not in contract
    assert "bodySupportDiscoveryHintsDefinitionDigest" not in contract


def test_definition_projection_requires_a_current_structured_action():
    exercise = youtube.ExerciseEntry(
        exercise_id="cable-crunch", name="Cable Crunch", slug="cable-crunch",
    )

    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _definition_contract_payload(), exercise=exercise, source="llm",
    )

    assert "bodySupportRequirements" not in contract
    assert "bodySupportDiscoveryHints" not in contract
    assert "bodySupportDiscoveryHintsAuthority" not in contract


@pytest.mark.parametrize("definition_support", [
    {"required": [], "prohibited": []},
    {"required": [{"region": "foot", "side": "both", "surface": "ground"}], "prohibited": []},
])
def test_explicit_definition_support_overrides_the_model_projection(definition_support):
    exercise = _exercise(APPROVED_ACTION)
    context = exercise.motion_context
    exercise = youtube.ExerciseEntry(
        exercise_id=exercise.exercise_id,
        name=exercise.name,
        slug=exercise.slug,
        motion_context={
            **context,
            "exerciseDefinition": {
                **context["exerciseDefinition"],
                "bodySupportRequirements": definition_support,
            },
        },
    )

    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _definition_contract_payload(), exercise=exercise, source="llm",
    )

    assert contract["bodySupportRequirements"] == definition_support
    assert "bodySupportDiscoveryHints" not in contract
    assert "bodySupportDiscoveryHintsAuthority" not in contract


def test_stale_definition_projection_is_discarded():
    original = _exercise(APPROVED_ACTION)
    contract = youtube.normalize_definition_exercise_motion_contract_response(
        _definition_contract_payload(), exercise=original, source="llm",
    )
    stale_contract = {
        key: value for key, value in contract.items() if key != "motionContext"
    }
    edited = _exercise("Stand and curl the cable toward the head.")

    reconciled = youtube.reconcile_exercise_motion_contract_definition(
        dict(stale_contract), edited,
    )

    assert reconciled["bodySupportRequirements"] == {"required": [], "prohibited": []}
    assert "bodySupportDiscoveryHints" not in reconciled
    assert "bodySupportDiscoveryHintsAuthority" not in reconciled


def test_normalizer_keeps_explicit_empty_distinct_from_missing():
    fields = youtube.normalized_exercise_motion_contract_fields(
        {"bodySupportRequirements": {"required": [], "prohibited": []}},
    )

    assert fields["bodySupportRequirements"] == {"required": [], "prohibited": []}
    assert "bodySupportRequirements" not in youtube.normalized_exercise_motion_contract_fields({})
