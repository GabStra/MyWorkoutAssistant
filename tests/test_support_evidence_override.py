import numpy as np

from exercise_motion_pkg import support_geometry


def test_support_validator_uses_explicit_native_tracks_and_keeps_default(monkeypatch):
    stale_tracks = {"owner": "payload-fixedRig"}
    rebuilt_tracks = {"owner": "solver-rebuilt"}
    stale = {
        "required": True,
        "status": "confirmed",
        "stationaryJoints": [],
        "soleContacts": [],
        "coplanarGroups": [],
        "nonPenetrationChains": [],
        "_nativeFootMaterialTracks": stale_tracks,
    }
    override = {
        **stale,
        "_nativeFootMaterialTracks": rebuilt_tracks,
        "_nativeFootScale": 0.18,
    }
    payload = {
        "jointNames": ["right_knee"],
        "frames": [{"sourceTimeSec": 0.0, "joints": {"right_knee": [0.0, 0.0, 0.0]}}],
    }
    seen = []

    monkeypatch.setattr(
        "exercise_motion_pkg.material_region_support.native_region_geometry",
        lambda *args, **kwargs: {"required": False, "passed": True},
    )
    monkeypatch.setattr(support_geometry, "support_evidence", lambda _payload: stale)
    monkeypatch.setattr(
        "exercise_motion_pkg.body_support_observation.materialize_stationary_sole_support",
        lambda _payload: {},
    )
    monkeypatch.setattr(
        support_geometry, "support_contact_readiness",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(support_geometry, "evidence_is_complete", lambda *args: True)
    monkeypatch.setattr(
        support_geometry, "support_contact_masks",
        lambda _evidence, _names, count, **kwargs: (
            np.zeros((count, 1), dtype=bool), np.full((count, 1), None, dtype=object)),
    )
    monkeypatch.setattr(
        support_geometry, "_stationary_geometry_contact_masks",
        lambda _evidence, _names, active, anchor_ids, *_args, **_kwargs: (active, anchor_ids),
    )
    monkeypatch.setattr(
        support_geometry, "full_sole_contact_masks",
        lambda _evidence, _names, count, **kwargs: np.zeros((count, 1), dtype=bool),
    )
    monkeypatch.setattr(support_geometry, "_missing_material_sole_pitch_sides", lambda _evidence: set())

    def capture_geometry_errors(_points, _names, evidence, **kwargs):
        seen.append(evidence["_nativeFootMaterialTracks"])
        return np.zeros((1, 0))

    monkeypatch.setattr(support_geometry, "geometry_errors", capture_geometry_errors)
    points = np.zeros((1, 1, 3), dtype=float)

    result = support_geometry.validate_support_geometry(
        payload, points, ["right_knee"], evidence_override=override)
    assert result["passed"] is True
    assert seen[-1] is rebuilt_tracks

    legacy_result = support_geometry.validate_support_geometry(
        payload, points, ["right_knee"])
    assert legacy_result["passed"] is True
    assert seen[-1] is stale_tracks
