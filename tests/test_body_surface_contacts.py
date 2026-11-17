"""Focused regressions for the shared version-1 body-surface contact normalizer."""

from copy import deepcopy
import json

import pytest

from exercise_motion_pkg.body_surface_contacts import (
    normalize_body_surface_contact,
)

_VIDEO_SHA256 = "a" * 64
_POSE_SHA256 = "b" * 64
_CLOCK_SHA256 = "c" * 64


def _record(name="posterior_shin", side="left", mode="sliding"):
    return {
        "schemaVersion": 1,
        "contactId": f"contact-{name}-{side}",
        "bodyRegion": {"name": name, "side": side},
        "contactMode": mode,
        "sourceEvidence": {
            "sourceVideoSha256": _VIDEO_SHA256,
            "sourcePosePayloadSha256": _POSE_SHA256,
            "sourceFrameClockReceiptSha256": _CLOCK_SHA256,
            "observations": [
                {
                    "sampleId": "sample-0001",
                    "sourceTimeSec": 0.0,
                    "sourcePoseFrameIndex": 0,
                    "sourceFrameIndex": 0,
                    "sourceFps": 30.0,
                    "contactState": "direct_contact",
                    "visible": True,
                    "surfaceId": "bench-pad-top",
                },
                {
                    "sampleId": "sample-0002",
                    "sourceTimeSec": 0.5,
                    "sourcePoseFrameIndex": 15,
                    "sourceFrameIndex": 15,
                    "sourceFps": 30.0,
                    "contactState": "unknown",
                    "visible": False,
                    "surfaceId": "bench-pad-top",
                },
            ],
        },
        "patchBinding": {
            "primitiveId": "wear_exact_material_primitive",
            "points": [
                {"triangleIndex": 12, "barycentric": [0.25, 0.25, 0.5]},
            ],
        },
        "surfaceEstimate": {
            "normal": [0.0, 1.0, 0.0],
            "offsetMeters": 0.45,
            "polygonWorld": [
                [0.0, 0.45, 0.0],
                [1.0, 0.45, 0.0],
                [1.0, 0.45, 1.0],
                [0.0, 0.45, 1.0],
            ],
        },
        "geometryProvenance": {
            "kind": "calibrated",
            "solver": "surface-fit-v1",
            "sampleCount": 2,
        },
        "uncertainty": {"positionMeters": 0.012, "normalRadians": 0.03},
    }


def test_unrepresentable_coordinate_is_a_validation_error():
    record = _record()
    record['surfaceEstimate']['offsetMeters'] = 10 ** 400
    with pytest.raises(ValueError, match='finite'):
        normalize_body_surface_contact(record)


def _uncalibrated_record():
    record = _record(name="anterior_shoulder_region", side="right", mode="stationary")
    record["patchBinding"] = None
    record["surfaceEstimate"] = None
    record["geometryProvenance"] = None
    record.pop("uncertainty")
    return record


def _modified(mutator):
    def build():
        record = _record()
        mutator(record)
        return record

    return build


_CASES = [
    pytest.param(_record, True, id="valid-arbitrary-shin-region"),
    pytest.param(
        lambda: _record(
            name="anterior_shoulder_cap", side="right", mode="stationary"
        ),
        True,
        id="valid-arbitrary-shoulder-region",
    ),
    pytest.param(_uncalibrated_record, True, id="valid-uncalibrated-nulls"),
    pytest.param(
        _modified(
            lambda record: record["patchBinding"]["points"][0].__setitem__(
                "barycentric", [0.2, 0.2, 0.8]
            )
        ),
        False,
        id="invalid-barycentric-sum",
    ),
    pytest.param(
        _modified(
            lambda record: record["patchBinding"]["points"][0].__setitem__(
                "barycentric", [-0.1, 0.5, 0.6]
            )
        ),
        False,
        id="invalid-barycentric-negative",
    ),
    pytest.param(
        _modified(
            lambda record: record["patchBinding"]["points"][0].__setitem__(
                "barycentric", [float("nan"), 0.5, 0.5]
            )
        ),
        False,
        id="invalid-barycentric-nonfinite",
    ),
    pytest.param(
        _modified(
            lambda record: record["patchBinding"]["points"][0].__setitem__(
                "barycentric", [0.5, 0.5]
            )
        ),
        False,
        id="invalid-barycentric-length",
    ),
    pytest.param(
        _modified(
            lambda record: record["patchBinding"]["points"][0].__setitem__(
                "triangleIndex", -1
            )
        ),
        False,
        id="invalid-triangle-index",
    ),
    pytest.param(
        _modified(
            lambda record: record["surfaceEstimate"].__setitem__(
                "normal", [0.0, 0.0, 2.0]
            )
        ),
        False,
        id="invalid-surface-normal-not-unit",
    ),
    pytest.param(
        _modified(
            lambda record: record["surfaceEstimate"].__setitem__(
                "offsetMeters", float("inf")
            )
        ),
        False,
        id="invalid-surface-offset-nonfinite",
    ),
    pytest.param(
        _modified(
            lambda record: record["surfaceEstimate"]["polygonWorld"][0].__setitem__(
                1, float("nan")
            )
        ),
        False,
        id="invalid-surface-polygon-nonfinite",
    ),
    pytest.param(
        _modified(
            lambda record: record["geometryProvenance"].__setitem__(
                "kind", "observed"
            )
        ),
        False,
        id="invalid-provenance-observed",
    ),
    pytest.param(
        _modified(
            lambda record: record.__setitem__("geometryProvenance", None)
        ),
        False,
        id="invalid-geometry-without-provenance",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"].__setitem__(
                "sourceVideoSha256", "z" * 64
            )
        ),
        False,
        id="invalid-hash-nonhex",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"].__setitem__(
                "sourcePosePayloadSha256", "b" * 63
            )
        ),
        False,
        id="invalid-hash-short",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"].pop(
                "sourceFrameClockReceiptSha256"
            )
        ),
        False,
        id="invalid-hash-missing",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"]["observations"][0].__setitem__(
                "contactState", "maybe"
            )
        ),
        False,
        id="invalid-contact-state",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"]["observations"][0].__setitem__(
                "visible", 1
            )
        ),
        False,
        id="invalid-visible-type",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"]["observations"][0].__setitem__(
                "sourceTimeSec", float("nan")
            )
        ),
        False,
        id="invalid-observation-time-nonfinite",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"]["observations"][0].pop("sampleId")
        ),
        False,
        id="invalid-missing-sample-identity",
    ),
    pytest.param(
        _modified(
            lambda record: record["sourceEvidence"]["observations"][1].__setitem__(
                "sampleId", "sample-0001"
            )
        ),
        False,
        id="invalid-duplicate-sample-identity",
    ),
    pytest.param(
        _modified(
            lambda record: record["bodyRegion"].__setitem__("name", "   ")
        ),
        False,
        id="invalid-empty-region-name",
    ),
    pytest.param(
        _modified(
            lambda record: record["bodyRegion"].pop("name")
        ),
        False,
        id="invalid-missing-region-name",
    ),
    pytest.param(
        _modified(
            lambda record: record["bodyRegion"].__setitem__("side", "middle")
        ),
        False,
        id="invalid-region-side",
    ),
    pytest.param(
        _modified(
            lambda record: record.__setitem__("contactMode", "rolling_ish")
        ),
        False,
        id="invalid-contact-mode",
    ),
    pytest.param(
        _modified(
            lambda record: record.__setitem__("schemaVersion", 1.0)
        ),
        False,
        id="invalid-schema-version-type",
    ),
    pytest.param(
        _modified(
            lambda record: record["uncertainty"].__setitem__(
                "positionMeters", -0.01
            )
        ),
        False,
        id="invalid-uncertainty-negative",
    ),
]


@pytest.mark.parametrize("build_record,is_valid", _CASES)
def test_normalize_body_surface_contact_regressions(build_record, is_valid):
    record = build_record()
    before = json.dumps(record, sort_keys=True)

    if not is_valid:
        with pytest.raises(ValueError):
            normalize_body_surface_contact(record)
        assert json.dumps(record, sort_keys=True) == before
        return

    normalized = normalize_body_surface_contact(record)
    assert json.dumps(record, sort_keys=True) == before
    assert normalized is not record
    assert normalized["bodyRegion"] == record["bodyRegion"]
    assert normalized["bodyRegion"] is not record["bodyRegion"]
    assert normalized["contactId"] == record["contactId"]
    assert (
        normalized["sourceEvidence"]["sourceVideoSha256"] == _VIDEO_SHA256
    )
    assert (
        normalized["sourceEvidence"]["observations"][0]["sampleId"]
        == "sample-0001"
    )
    assert (
        normalized["sourceEvidence"]["observations"][0]
        is not record["sourceEvidence"]["observations"][0]
    )
    if record["patchBinding"] is not None:
        assert (
            normalized["patchBinding"]["points"][0]["triangleIndex"]
            == record["patchBinding"]["points"][0]["triangleIndex"]
        )
        assert (
            normalized["patchBinding"]["primitiveId"]
            == "wear_exact_material_primitive"
        )
    if "uncertainty" in record:
        assert normalized["uncertainty"] == record["uncertainty"]
    json.dumps(normalized)

    normalized["bodyRegion"]["name"] = "mutated"
    normalized["sourceEvidence"]["observations"][0]["sampleId"] = "mutated"
    if normalized["patchBinding"] is not None:
        normalized["patchBinding"]["points"][0]["barycentric"][0] = 99.0
    assert json.dumps(record, sort_keys=True) == before
