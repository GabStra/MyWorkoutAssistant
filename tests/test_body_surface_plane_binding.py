from copy import deepcopy

import numpy as np
import pytest

from exercise_motion_pkg.body_surface_geometry import (
    bind_body_surface_contact_to_plane,
    body_surface_primitive_meshes,
    evaluate_contact_patch,
    native_shoe_region_candidates,
    select_native_shoe_material_point,
)
from test_body_surface_geometry import _poses


_SHA = "a" * 64


def _three_frame_poses():
    names, two = _poses()
    return names, np.stack((two[0], two[1], (two[0] + two[1]) * .5))


def _record(mode="stationary", states=("direct_contact",) * 3, visible=True):
    observations = [{
        "sampleId": f"sample-{index}",
        "sourceTimeSec": index / 30.,
        "sourcePoseFrameIndex": index,
        "sourceFrameIndex": index,
        "sourceFps": 30.,
        "contactState": state,
        "visible": visible,
        "surfaceId": "mat",
    } for index, state in enumerate(states)]
    return {
        "schemaVersion": 1,
        "contactId": "native-material-contact",
        "bodyRegion": {"name": "knee", "side": "left"},
        "contactMode": mode,
        "sourceEvidence": {
            "sourceVideoSha256": _SHA,
            "sourcePosePayloadSha256": _SHA,
            "sourceFrameClockReceiptSha256": _SHA,
            "observations": observations,
        },
        "patchBinding": None,
        "surfaceEstimate": None,
        "geometryProvenance": None,
    }


def _provided_plane(vertices, normal):
    normal = np.asarray(normal, dtype=float)
    normal /= np.linalg.norm(normal)
    support_vertex = vertices[0][int(np.argmin(vertices[0] @ normal))]
    offset = float(support_vertex @ normal)
    point = support_vertex - (support_vertex @ normal - offset) * normal
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    first = np.cross(normal, axis)
    first /= np.linalg.norm(first)
    second = np.cross(normal, first)
    polygon = np.asarray([
        point + u * first + v * second
        for u, v in ((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5))
    ])
    return normal, offset, polygon


@pytest.mark.parametrize("primitive_id,joint_name,normal", [
    ("wearSphere:left_knee", "left_knee", (0.25, 0.92, 0.30)),
    ("wearSegment:left_knee->left_ankle", "left_knee", (0.18, 0.96, 0.21)),
    ("wearSphere:left_shoulder", "left_shoulder", (0.30, 0.22, 0.93)),
])
def test_binding_selects_native_material_triangle_on_known_plane(
        primitive_id, joint_name, normal):
    names, points = _three_frame_poses()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes[primitive_id]
    plane_normal, offset, polygon = _provided_plane(mesh["vertices"], normal)
    estimate = {
        "normal": plane_normal.tolist(),
        "offsetMeters": offset,
        "polygonWorld": polygon.tolist(),
    }
    record = _record()
    original = deepcopy(record)

    bound = bind_body_surface_contact_to_plane(
        record, meshes, primitive_id, estimate,
        frame_map={0: 0, 1: 1, 2: 2},
    )

    assert record == original
    assert bound["sourceEvidence"] == original["sourceEvidence"]
    assert bound["schemaVersion"] == 1
    assert bound["patchBinding"]["primitiveId"] == primitive_id
    assert bound["geometryProvenance"]["kind"] == "inferred"
    np.testing.assert_allclose(bound["surfaceEstimate"]["normal"], plane_normal)
    assert bound["surfaceEstimate"]["offsetMeters"] == pytest.approx(offset)
    np.testing.assert_allclose(bound["surfaceEstimate"]["polygonWorld"], polygon)

    point = bound["patchBinding"]["points"][0]
    triangle_index = point["triangleIndex"]
    weights = np.asarray(point["barycentric"], dtype=float)
    sampled = evaluate_contact_patch(meshes, bound["patchBinding"])
    corners = mesh["vertices"][:, mesh["triangles"][triangle_index]]
    np.testing.assert_allclose(sampled[:, 0], np.einsum("v,fvc->fc", weights, corners))
    # An extremal support point, not the triangle centroid: the bound material
    # point is a native vertex (the supplied polygon contains the whole facet).
    np.testing.assert_allclose(np.sort(weights), [0., 0., 1.], atol=1e-9)
    assert np.linalg.norm(sampled[0, 0] - points[0, names.index(joint_name)]) > 1e-3

    face = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    face /= np.linalg.norm(face, axis=-1, keepdims=True)
    assert np.all(np.einsum("fc,c->f", face, plane_normal) < -1e-6)
    # The supplied world plane is honored as-is rather than snapped to world up.
    assert abs(abs(plane_normal[1]) - 1.) > 1e-6
    assert abs(offset - float(np.min(mesh["vertices"][0] @ plane_normal))) < 1e-12
    # The bound point attains the primitive's lowest signed distance in the
    # source frame, so a fit that places it on the plane cannot cross it.
    assert abs(float(sampled[0, 0] @ plane_normal) - offset) < 1e-9


def test_binding_fails_closed_for_unverified_or_unsupported_inputs():
    names, points = _three_frame_poses()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes["wearSphere:left_knee"]
    normal, offset, polygon = _provided_plane(mesh["vertices"], (0.25, 0.92, 0.30))
    estimate = {"normal": normal.tolist(), "offsetMeters": offset,
                "polygonWorld": polygon.tolist()}

    with pytest.raises(ValueError):
        bind_body_surface_contact_to_plane(
            _record(), meshes, "capsule:shin", estimate)
    with pytest.raises(ValueError):
        bind_body_surface_contact_to_plane(
            _record(), meshes, "wearSphere:left_knee",
            {"normal": [0., 0., 0.], "offsetMeters": offset})
    with pytest.raises(ValueError):
        bind_body_surface_contact_to_plane(
            _record(states=("no_contact",) * 3), meshes,
            "wearSphere:left_knee", estimate)
    with pytest.raises(ValueError):
        bind_body_surface_contact_to_plane(
            _record(), meshes, "wearSphere:left_knee", estimate,
            frame_map={0: 0})
    with pytest.raises(ValueError):
        bind_body_surface_contact_to_plane(
            _record(mode="rolling"), meshes, "wearSphere:left_knee", estimate)
    with pytest.raises(ValueError):
        bind_body_surface_contact_to_plane(
            _record(), meshes, "wearSphere:left_knee", estimate,
            geometry_provenance={"kind": "observed"})


def test_binding_handles_initial_float_and_sliding_without_certifying_fit():
    names, points = _three_frame_poses()
    meshes = body_surface_primitive_meshes(points, names)
    mesh = meshes["wearSphere:left_knee"]
    normal, offset, _ = _provided_plane(mesh["vertices"], (0.25, 0.92, 0.30))
    estimate = {"normal": normal.tolist(), "offsetMeters": offset - .04}

    bound = bind_body_surface_contact_to_plane(
        _record(mode="sliding"), meshes, "wearSphere:left_knee", estimate)

    sampled = evaluate_contact_patch(meshes, bound["patchBinding"])
    gap = np.einsum("fpc,c->fp", sampled, normal) - estimate["offsetMeters"]
    assert np.all(gap > 1e-3)  # initial float is preserved for the fit to repair
    assert bound["contactMode"] == "sliding"


def test_native_forefoot_region_clips_triangle_at_ball_before_binding_material_point():
    ankles = np.zeros((2, 3))
    balls = np.tile([1., 0., 0.], (2, 1))
    axes = np.tile([0., 0., 1.], (2, 1))
    one = np.asarray([[-.2, 0., 0.], [1.2, 0., 0.], [-.2, 0., .2]])
    vertices = np.stack((one, one + [0., .01, 0.]))
    triangles = np.asarray([[0, 1, 2]])
    forefoot = native_shoe_region_candidates(
        vertices, triangles, ankles, balls, axes, np.asarray([0, 1]), 'forefoot')
    heel = native_shoe_region_candidates(
        vertices, triangles, ankles, balls, axes, np.asarray([0, 1]), 'heel')
    assert forefoot and heel
    for index, weights in forefoot:
        point = np.einsum('v,vc->c', weights, one[triangles[index]])
        assert point[0] >= 1. - 1e-8
    for index, weights in heel:
        point = np.einsum('v,vc->c', weights, one[triangles[index]])
        assert point[0] <= 1e-8
    binding = select_native_shoe_material_point(
        vertices, triangles, forefoot, np.asarray([0, 1]), [0., 1., 0.], .01)
    assert binding['triangleIndex'] == 0
    assert sum(binding['barycentric']) == pytest.approx(1.)
