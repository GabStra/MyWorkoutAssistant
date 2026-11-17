import json

import pytest

from exercise_motion_pkg.definition_review import export_definition_review


@pytest.mark.parametrize(
    ("existing_execution", "expected"),
    [
        ({"arms": "mirrored"}, {"arms": "mirrored"}),
        ({"arms": "unconstrained", "legs": "unconstrained"},
         {"arms": "unconstrained", "legs": "unconstrained"}),
        ({}, {}),
        (None, None),
    ],
)
def test_export_preserves_existing_bilateral_execution_intent(tmp_path, existing_execution, expected):
    motion_context = {}
    if existing_execution is not None:
        motion_context["exerciseDefinition"] = {"bilateralExecution": existing_execution}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"exerciseDefinitions": [
        {"id": "pull", "name": "High Pull", "motionContext": motion_context},
    ]}))

    review = export_definition_review(
        plan_path=plan_path, exercise_id="pull", review_path=tmp_path / "review.json",
    )

    if expected is None:
        assert "bilateralExecution" not in review["definition"]
    else:
        assert review["definition"]["bilateralExecution"] == expected


def test_export_rejects_invalid_existing_bilateral_execution(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"exerciseDefinitions": [
        {"id": "pull", "name": "High Pull", "motionContext": {
            "exerciseDefinition": {"bilateralExecution": {"arms": "alternating"}},
        }},
    ]}))

    with pytest.raises(ValueError):
        export_definition_review(
            plan_path=plan_path, exercise_id="pull", review_path=tmp_path / "review.json",
        )
