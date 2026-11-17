"""Whole-native nonpenetration on bound body-surface support planes."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_body_surface_geometry import _poses

from exercise_motion_pkg.body_surface_geometry import (
    bind_body_surface_contact_to_plane,
    body_surface_primitive_meshes,
    evaluate_contact_patch,
    native_min_signed_distance,
)
from exercise_motion_pkg.support_geometry import TOLERANCE_METERS, geometry_errors


_SHA = "a" * 64
_PRIMITIVES = (
    "wearSphere:left_knee",
    "wearSegment:left_knee->left_ankle",
    "wearSphere:left_shoulder",
)


def _single_frame():
    names, points = _poses()
    return names, points[:1]


def _record(primitive_id, mode, triangle_index, barycentric, estimate):
    return {
        "schemaVersion": 1,
        "contactId": "native-nonpenetration",
        "bodyRegion": {"name": "knee", "side": "left"},
        "contactMode": mode,
        "sourceEvidence": {
            "sourceVideoSha256": _SHA,
            "sourcePosePayloadSha256": _SHA,
            "sourceFrameClockReceiptSha256": _SHA,
            "observations": [{
                "sampleId": "sample-0",
                "sourceTimeSec": 0.,
                "sourcePoseFrameIndex": 0,
                "sourceFrameIndex": 0,
                "sourceFps": 30.,
                "contactState": "direct_contact",
                "visible": True,
                "surfaceId": "mat",
            }],
        },
        "patchBinding": {
            "primitiveId": primitive_id,
            "points": [{"triangleIndex": int(triangle_index),
                        "barycentric": list(barycentric)}],
        },
        "surfaceEstimate": estimate,
        "geometryProvenance": {"kind": "inferred"},
    }


def _nonparallel_support(vertices, triangles):
    """Deterministic native support-facing, nonparallel plane and facet."""
    best = None
    for index, triangle in enumerate(triangles):
        corners = vertices[triangle]
        face = np.cross(corners[1] - corners[0], corners[2] - corners[0])
        length = float(np.linalg.norm(face))
        if length <= 1e-9:
            continue
        outward = face / length
        axis = np.eye(3)[int(np.argmin(np.abs(outward)))]
        tangent = np.cross(outward, axis)
        tangent /= np.linalg.norm(tangent)
        normal = -outward + 2. * tangent
        normal /= np.linalg.norm(normal)
        signed = corners @ normal
        spread = float(signed.mean() - signed.min())
        if best is None or spread > best[0]:
            best = (spread, index, normal, float(signed.mean()))
    assert best is not None and best[0] > TOLERANCE_METERS
    return best[1], best[2], best[3], best[0]


def _tangent_frame(normal):
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    first = np.cross(normal, axis)
    first /= np.linalg.norm(first)
    return first, np.cross(normal, first)


def _plane_polygon(normal, offset, first, second, low, high):
    corners = [(low[0], low[1]), (high[0], low[1]),
               (high[0], high[1]), (low[0], high[1])]
    origin = offset * normal
    return np.asarray([origin + u * first + v * second for u, v in corners])


def _projected_triangle(vertices, triangle, normal, first, second):
    projected = np.stack((vertices[triangle] @ first, vertices[triangle] @ second), axis=1)
    return projected.min(axis=0), projected.max(axis=0)


@pytest.mark.parametrize("primitive_id", _PRIMITIVES)
@pytest.mark.parametrize("mode", ["stationary", "sliding"])
def test_centroid_binding_penetration_is_rejected(primitive_id, mode):
    names, points = _single_frame()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes[primitive_id]
    triangle, normal, offset, spread = _nonparallel_support(
        mesh["vertices"][0], mesh["triangles"])
    # Control: the provided plane is not world-up and the centroid binding is
    # nonparallel, so its lower native vertices must penetrate after the bind.
    assert abs(normal[1]) < .99
    estimate = {"normal": normal.tolist(), "offsetMeters": offset}
    record = _record(primitive_id, mode, triangle, [1. / 3.] * 3, estimate)
    sampled = evaluate_contact_patch(meshes, record["patchBinding"])
    assert abs(float(sampled[0, 0] @ normal) - offset) < 1e-9

    residuals = geometry_errors(points, names, {"bodySurfaceContacts": [record]})
    assert np.min(residuals) < -TOLERANCE_METERS


@pytest.mark.parametrize("primitive_id", _PRIMITIVES)
def test_extremal_binding_fit_leaves_no_native_penetration(primitive_id):
    names, points = _single_frame()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes[primitive_id]
    _, normal, offset, _ = _nonparallel_support(mesh["vertices"][0], mesh["triangles"])
    estimate = {"normal": normal.tolist(), "offsetMeters": offset}

    bound = bind_body_surface_contact_to_plane(
        _record(primitive_id, "stationary", 0, [1. / 3.] * 3, estimate),
        meshes, primitive_id, estimate,
        frame_map={0: 0})
    sampled = evaluate_contact_patch(meshes, bound["patchBinding"])
    shift = offset - float(sampled[0, 0] @ normal)
    # A whole-body translation keeps every native primitive rigid while the
    # fit places the bound material point on the plane.
    shifted_points = points + shift * normal
    shifted = body_surface_primitive_meshes(shifted_points, names)[primitive_id]
    assert float(np.min(shifted["vertices"][0] @ normal) - offset) >= -1e-9

    residuals = geometry_errors(
        shifted_points, names, {"bodySurfaceContacts": [bound]})
    np.testing.assert_allclose(residuals, 0., atol=1e-9)


def test_finite_support_ignores_legitimate_bench_overhang():
    names, points = _single_frame()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes["wearSegment:left_knee->left_ankle"]
    vertices, triangles = mesh["vertices"][0], mesh["triangles"]
    _, normal, _, _ = _nonparallel_support(vertices, triangles)
    signed = vertices @ normal
    offset = float(signed.min() + .3 * (signed.max() - signed.min()))
    first, second = _tangent_frame(normal)
    # A small bench footprint on the high side of the knee; the low side hangs
    # beyond the bench and may legitimately pass below the unbounded plane.
    center = vertices[int(np.argmax(signed))]
    center_uv = np.asarray([center @ first, center @ second])
    polygon = _plane_polygon(
        normal, offset, first, second,
        center_uv - .002, center_uv + .002)
    estimate = {"normal": normal.tolist(), "offsetMeters": offset,
                "polygonWorld": polygon.tolist()}

    finite = native_min_signed_distance(
        vertices[None], triangles, normal, offset, polygon)
    unbounded = native_min_signed_distance(
        vertices[None], triangles, normal, offset, None)
    assert finite[0] >= -1e-9
    assert unbounded[0] < -TOLERANCE_METERS

    record = _record(
        "wearSegment:left_knee->left_ankle", "stationary", 0,
        [1. / 3.] * 3, estimate)
    bound = bind_body_surface_contact_to_plane(
        record, meshes, "wearSegment:left_knee->left_ankle", estimate,
        frame_map={0: 0})
    sampled = evaluate_contact_patch(meshes, bound["patchBinding"])
    shifted_points = points + (offset - float(sampled[0, 0] @ normal)) * normal
    residuals = geometry_errors(
        shifted_points, names, {"bodySurfaceContacts": [bound]})
    np.testing.assert_allclose(residuals, 0., atol=1e-9)


def test_finite_support_rejects_penetration_inside_footprint():
    names, points = _single_frame()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes["wearSegment:left_knee->left_ankle"]
    vertices, triangles = mesh["vertices"][0], mesh["triangles"]
    triangle, normal, offset, _ = _nonparallel_support(vertices, triangles)
    first, second = _tangent_frame(normal)
    low, high = _projected_triangle(vertices, triangles[triangle], normal, first, second)
    polygon = _plane_polygon(normal, offset, first, second, low - .005, high + .005)
    estimate = {"normal": normal.tolist(), "offsetMeters": offset,
                "polygonWorld": polygon.tolist()}
    # The whole triangle sits inside the finite footprint, so clipping must
    # find the same centroid-on-plane penetration as the unbounded plane.
    assert native_min_signed_distance(
        vertices[None], triangles, normal, offset, polygon)[0] < -TOLERANCE_METERS

    record = _record(
        "wearSegment:left_knee->left_ankle", "sliding", triangle,
        [1. / 3.] * 3, estimate)
    residuals = geometry_errors(points, names, {"bodySurfaceContacts": [record]})
    assert np.min(residuals) < -TOLERANCE_METERS


def test_finite_clipping_catches_triangle_crossing_with_all_vertices_outside():
    normal = np.asarray([0., 1., 0.])
    vertices = np.asarray([[[-1., -.1, -1.], [1., -.1, -1.], [0., .05, 1.]]])
    triangle = np.asarray([[0, 1, 2]])
    polygon = np.asarray([[-.1, 0., -.1], [.1, 0., -.1],
                          [.1, 0., .1], [-.1, 0., .1]])
    inside = np.stack((vertices[0] @ np.asarray([1., 0., 0.]),
                       vertices[0] @ np.asarray([0., 0., 1.])), axis=1)
    assert np.all(np.max(np.abs(inside), axis=1) > .1)
    assert native_min_signed_distance(
        vertices, triangle, normal, 0., polygon)[0] < -.01
