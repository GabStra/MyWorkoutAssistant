import numpy as np
import pytest

from exercise_motion_pkg.body_support_observation import calibrate_material_sole_floor
from exercise_motion_pkg.foot_geometry import shoe_vertices
from exercise_motion_pkg.ground_contact_plane import (
    PROVENANCE,
    infer_ground_contact_plane,
)


def _forefoot_track():
    # One grounded forefoot material track; the heel is never observed.
    points = np.array([
        [[0.10, 0.12, 0.20], [0.12, 0.121, 0.22], [0.11, np.nan, 0.21]],
        [[0.13, 0.12, 0.24], [0.14, 0.120, 0.25], [0.12, 0.121, 0.23]],
    ])
    masks = np.array([[True, True, False], [True, True, True]])
    return points, masks


def _payload():
    return {'renderFloorY': None, 'frames': [], 'jointNames': []}


def test_forefoot_only_track_yields_finite_inferred_plane():
    points, masks = _forefoot_track()
    plane = infer_ground_contact_plane(points, up=[0, 1, 0], contact_masks=masks)
    assert plane['resolved']
    assert plane['offsetMeters'] == pytest.approx(0.120)
    assert plane['pointCount'] == 5
    assert plane['provenance'] == PROVENANCE
    assert plane['authority'] == 'inferred_scene_placement'
    assert plane['observedFloorHeight'] is False


def test_calibration_labels_inferred_placement_and_keeps_rows():
    points, masks = _forefoot_track()
    payload = _payload()
    result = calibrate_material_sole_floor(
        payload, ground_contact_up=[0, 1, 0], ground_contact_points=points,
        contact_masks=masks)
    assert result is not payload
    assert result['renderFloorY'] == pytest.approx(0.120)
    assert result['renderFloorSource'] == PROVENANCE
    provenance = result['renderFloorProvenance']
    assert provenance['authority'] == 'inferred_scene_placement'
    assert provenance['observedFloorHeight'] is False
    assert result['frames'] == payload['frames']
    assert result['jointNames'] == payload['jointNames']


def test_raised_or_bench_source_never_becomes_horizontal_floor():
    points, masks = _forefoot_track()
    plane = infer_ground_contact_plane(
        points, up=[0, 1, 0], contact_masks=masks, surface_kind='bench')
    assert not plane['resolved']
    assert plane['reason'] == 'ground_contact_surface_is_not_ground'
    payload = _payload()
    result = calibrate_material_sole_floor(
        payload, ground_contact_up=[0, 1, 0], ground_contact_points=points,
        contact_masks=masks, surface_kind='raised_surface')
    assert result['renderFloorY'] is None
    assert 'renderFloorSource' not in result


def test_no_valid_ground_rows_fails_closed_without_zero_fill():
    points, masks = _forefoot_track()
    empty = np.zeros_like(masks)
    plane = infer_ground_contact_plane(points, up=[0, 1, 0], contact_masks=empty)
    assert not plane['resolved']
    assert plane['reason'] == 'no_valid_ground_contact_rows'
    payload = _payload()
    result = calibrate_material_sole_floor(
        payload, ground_contact_up=[0, 1, 0], ground_contact_points=points,
        contact_masks=empty)
    assert result['renderFloorY'] is None
    assert 'renderFloorProvenance' not in result


def test_missing_registered_up_fails_closed():
    points, masks = _forefoot_track()
    plane = infer_ground_contact_plane(points, up=[0, 0, 0], contact_masks=masks)
    assert not plane['resolved']
    result = calibrate_material_sole_floor(
        _payload(), ground_contact_up=None, ground_contact_points=points,
        contact_masks=masks)
    assert result['renderFloorY'] is None


def test_explicit_floor_authority_is_unchanged():
    points, masks = _forefoot_track()
    payload = {'renderFloorY': 0.42, 'renderFloorSource': 'explicit_source_floor',
               'frames': [], 'jointNames': []}
    result = calibrate_material_sole_floor(
        payload, ground_contact_up=[0, 1, 0], ground_contact_points=points,
        contact_masks=masks)
    assert result is payload
    assert result['renderFloorY'] == pytest.approx(0.42)


def test_native_shoe_lowest_point_is_zero_distance_from_gauge():
    ankle, toe = np.array([0.2, 0.9, 0.1]), np.array([0.2, 0.9, 0.28])
    vertices = shoe_vertices(ankle, toe, np.array([1., 0., 0.]), None, 1.0)
    # The production shoe's contact-facing anchors are its lowest vertices.
    contacts = vertices[[int(np.argmin(vertices[:, 1]))]]
    plane = infer_ground_contact_plane(contacts, up=[0, 1, 0])
    assert plane['resolved']
    distance = contacts[..., 1].min() - plane['offsetMeters']
    assert distance == pytest.approx(0.0, abs=1e-12)
