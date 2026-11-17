"""Sample contact patches on native rendered body-surface meshes.

The primitive formulas and triangle order mirror ``wear_exact_mesh.js``. This
module covers wearSegment/wearSphere, the renderer hand-segment variant, the
existing native head-material helper, and material shoes. The torso shell is
intentionally not covered or represented by a proxy.
"""
from __future__ import annotations

import numpy as np

from .body_surface_contacts import normalize_body_surface_contact


_LIMBS = (
    ("left_hip", "left_knee", .27, .215, .46, 1.38, .34),
    ("left_knee", "left_ankle", .225, .165, .44, 1.18, .46),
    ("right_hip", "right_knee", .27, .215, .46, 1.38, .34),
    ("right_knee", "right_ankle", .225, .165, .44, 1.18, .46),
    ("left_shoulder", "left_elbow", .30, .225, .44, 1.42, .30),
    ("left_elbow", "left_wrist", .235, .175, .42, 1.16, .40),
    ("right_shoulder", "right_elbow", .30, .225, .44, 1.42, .30),
    ("right_elbow", "right_wrist", .235, .175, .42, 1.16, .40),
)
_CAP_JOINTS = ("left_hip", "right_hip", "left_shoulder", "right_shoulder",
               "left_elbow", "right_elbow", "left_wrist", "right_wrist",
               "left_knee", "right_knee", "left_ankle", "right_ankle")
_RING8 = np.asarray([[.94, .34], [.15, .99], [-.15, .99], [-.94, .34],
                     [-.94, -.34], [-.15, -.99], [.15, -.99], [.94, -.34]])


def _unit(value, fallback):
    value = np.asarray(value, dtype=float)
    norm = np.linalg.norm(value, axis=-1, keepdims=True)
    return np.where(norm > 1e-8, value / np.maximum(norm, 1e-30), fallback)


def _strip_triangles(a, b):
    return [[a[i], b[i], b[(i + 1) % len(a)], a[(i + 1) % len(a)]]
            for i in range(len(a))]


def _triangulate(faces):
    return np.asarray([tri for face in faces for tri in
                       ([face[0], face[i], face[i + 1]] for i in range(1, len(face) - 1))], dtype=np.int64)


def _body_axes(points, names, binding):
    supplied = binding.get("bodyAxes")
    if supplied is not None:
        axes = np.asarray(supplied, dtype=float)
        if axes.shape == (3, 3):
            axes = np.broadcast_to(axes, (len(points), 3, 3))
        if axes.shape != (len(points), 3, 3) or not np.isfinite(axes).all():
            raise ValueError("bodyAxes must be finite frames x 3 x 3")
        return axes
    required = ("left_hip", "right_hip", "pelvis", "neck")
    if not all(name in names for name in required):
        raise ValueError("native limb geometry requires body-axis joints or binding")
    from .render_geometry import material_body_axes
    return material_body_axes(points, names)


def _stable_lengths(points, names, binding):
    result = dict(binding.get("segmentLengths") or {})
    required = ("left_hip", "right_hip", "left_shoulder", "right_shoulder")
    if not all(name in names for name in required):
        return result
    for i, row in enumerate(points):
        if np.linalg.norm(row[names.index("left_hip")] - row[names.index("right_hip")]) <= .0001:
            continue
        if np.linalg.norm(row[names.index("left_shoulder")] - row[names.index("right_shoulder")]) <= .0001:
            continue
        for start, end, *_ in (*_LIMBS, ("left_wrist", "left_hand"),
                               ("right_wrist", "right_hand")):
            key = f"{start}->{end}"
            if key not in result and start in names and end in names:
                length = float(np.linalg.norm(row[names.index(end)] - row[names.index(start)]))
                if length > .0001:
                    result[key] = length
        break
    return result


def _torso_cap_axes(points, names, axes, shoulder_width, arm_lengths):
    """The native pelvis and aligned upper-chest frames used by cap spheres."""
    output_pelvis, output_shoulder = [], []
    def norm(v, fallback):
        return _unit(v, fallback)
    def aligned(reference, candidate):
        side, up, forward = candidate
        if np.dot(side, reference[0]) < 0:
            side = -side
        return side, up, norm(np.cross(side, up), forward)
    def spine_axes(previous, before, center, after, reference):
        tangent = norm(after - before, norm(after - center, reference[1]))
        side = norm(reference[0] - tangent * np.dot(reference[0], tangent), reference[0])
        return side, tangent, norm(np.cross(side, tangent), reference[2])
    for row, body in zip(points, axes):
        at = lambda name: row[names.index(name)]
        side, up, forward = body
        hip = (at("left_hip") + at("right_hip")) * .5
        torso = at("neck") - hip
        torso_up = norm(torso, up)
        waist_source = at("spine1") if "spine1" in names else hip + torso * .40
        chest_source = at("spine2") if "spine2" in names else waist_source * .55 + at("neck") * .45
        upper_source = at("spine3") if "spine3" in names else chest_source * .65 + at("neck") * .35
        waist = waist_source * .5 + (hip + chest_source) * .25
        chest = chest_source * .5 + (waist_source + upper_source) * .25
        upper = upper_source * .5 + (chest_source + at("neck")) * .25
        pelvis_up = norm(waist - hip, torso_up)
        hip_side = at("left_hip") - at("right_hip")
        pelvis_side = norm(hip_side - pelvis_up * np.dot(hip_side, pelvis_up), -side)
        pelvis = (pelvis_side, pelvis_up, norm(np.cross(pelvis_side, pelvis_up), -forward))
        waist_frame = aligned(pelvis, spine_axes(pelvis, hip, waist, chest, pelvis))
        chest_frame = aligned(waist_frame, spine_axes(waist_frame, waist, chest, upper, waist_frame))
        upper_frame = aligned(chest_frame, spine_axes(chest_frame, chest, upper,
                                                       (at("left_shoulder") + at("right_shoulder")) * .5,
                                                       chest_frame))
        shoulder_side = norm(at("left_shoulder") - at("right_shoulder"), -side)
        shoulder_vector = at("neck") - upper_source
        shoulder_up = norm(shoulder_vector - shoulder_side * np.dot(shoulder_vector, shoulder_side), torso_up)
        shoulder_axes = (shoulder_side, shoulder_up, norm(np.cross(shoulder_side, shoulder_up), -forward))
        output_pelvis.append(pelvis)
        output_shoulder.append(aligned(upper_frame, shoulder_axes))
    return np.asarray(output_pelvis), np.asarray(output_shoulder)


def _native_side(direction, axes):
    side, up, forward = axes
    projected = side - direction * np.dot(side, direction)
    if np.linalg.norm(projected) > .18:
        return projected / np.linalg.norm(projected)
    projected = forward - direction * np.dot(forward, direction)
    if np.linalg.norm(projected) > .18:
        return projected / np.linalg.norm(projected)
    return _unit(up - direction * np.dot(up, direction), forward)


def _native_side_rows(directions, axes):
    return np.asarray([_native_side(_unit(direction, np.zeros(3)), frame)
                       for direction, frame in zip(directions, axes)])


def _limb_side_tracks(points, names, axes, binding, frames):
    supplied = binding.get("limbSides")
    result = {}
    for start, end, *_ in _LIMBS:
        key = f"{start}->{end}"
        if start not in names or end not in names:
            continue
        raw = None
        if isinstance(supplied, dict) and key in supplied:
            raw = np.asarray(supplied[key], dtype=float)
            if raw.shape == (3,):
                raw = np.broadcast_to(raw, (len(points), 3))
            if raw.shape != (len(points), 3) or not np.isfinite(raw).all():
                raise ValueError(f"limbSides[{key}] must be finite frames x 3")
        track = []
        previous = None
        for i in range(len(points)):
            direction = _unit(points[i, names.index(end)] - points[i, names.index(start)], np.zeros(3))
            if np.linalg.norm(direction) <= 1e-8:
                track.append(np.zeros(3)); continue
            preferred = raw[i] if raw is not None else None
            if preferred is None and frames is not None and i < len(frames):
                preferred = (frames[i].get("boneSides") or {}).get(key)
            if preferred is not None:
                side = np.asarray(preferred, dtype=float)
                side = side - direction * np.dot(side, direction)
                side = _unit(side, _native_side(direction, axes[i]))
            elif previous is not None:
                side = _unit(previous - direction * np.dot(previous, direction), _native_side(direction, axes[i]))
                if np.dot(side, previous) < 0:
                    side = -side
            else:
                side = _native_side(direction, axes[i])
            track.append(side)
            previous = side
        result[key] = np.asarray(track)
    # Native renderer shares the knee hinge frame between thigh and shin.
    for side in ("left", "right"):
        thigh, shin, foot = (f"{side}_{x}" for x in ("hip", "knee", "ankle"))
        foot_name = f"{side}_foot"
        if all(n in names for n in (thigh, shin, foot, foot_name)):
            try:
                from .temporal_quality import rendered_leg_sides
                leg_frames = frames or [{"joints": {n: points[i, names.index(n)].tolist() for n in
                                  (thigh, shin, foot, foot_name)}} for i in range(len(points))]
                native = rendered_leg_sides(leg_frames)
                for key in (f"{side}_hip->{side}_knee", f"{side}_knee->{side}_ankle"):
                    for i, row in enumerate(native):
                        if key in row and key not in (binding.get("limbSides") or {}):
                            result[key][i] = row[key]
            except (KeyError, ValueError, TypeError):
                pass
    return result


def _segment_mesh(points, start, end, widths, depths, sides, start_insets, end_insets,
                  bulge, position, *, round_end=False):
    frame_vertices = []
    triangle_faces = None
    for i, (a, b) in enumerate(zip(start, end)):
        direction = _unit(b - a, np.zeros(3))
        length = np.linalg.norm(b - a)
        if length <= .0001:
            raise ValueError("wearSegment cannot render a zero-length bone")
        safe_a = a + direction * min(start_insets[i], length * .15)
        safe_b = b - direction * min(end_insets[i], length * .15)
        if np.linalg.norm(safe_b - safe_a) <= 1e-4:
            raise ValueError("wearSegment insets collapse the native segment")
        axis = sides[i] - direction * np.dot(sides[i], direction)
        axis = _unit(axis, _native_side(direction, np.eye(3)))
        depth = _unit(np.cross(axis, direction), np.asarray([0., 0., 1.]))

        def ring(center, width):
            half_width = width * .5
            front_depth = width * depths[i]
            back_depth = width * depths[i]
            corners = [
                center + axis * half_width + depth * front_depth,
                center - axis * half_width + depth * front_depth,
                center - axis * half_width - depth * back_depth,
                center + axis * half_width - depth * back_depth,
            ]
            bevel = .30
            return np.asarray([
                corners[index] * (1. - bevel) + corners[(index + offset) % 4] * bevel
                for index in range(4) for offset in (-1, 1)
            ])

        lower = ring(safe_a, widths[i, 0])
        upper = ring(safe_b, widths[i, 1])
        rings = [lower, upper]
        if bulge[i, 0] > 1:
            t = float(np.clip(position[i], .2, .8))
            center = safe_a * (1 - t) + safe_b * t
            interpolated_width = widths[i, 0] + (widths[i, 1] - widths[i, 0]) * t
            width = max(widths[i, 0], widths[i, 1], interpolated_width) * bulge[i, 0]
            rings.append(ring(center, width))
        tip = (safe_b + direction * widths[i, 1] * .25) if round_end else None
        frame_vertices.append(np.concatenate([*rings, tip[None]] if round_end else rings, axis=0))
        if triangle_faces is None:
            ring_indexes = [list(range(j * 8, (j + 1) * 8)) for j in range(len(rings))]
            if bulge[i, 0] > 1:
                # Native keeps vertex order lower, upper, bulge, while it
                # emits the two walls lower→bulge→upper.
                triangle_faces = [face for lo, hi in ((ring_indexes[0], ring_indexes[2]),
                                                        (ring_indexes[2], ring_indexes[1]))
                                  for face in _strip_triangles(lo, hi)]
            else:
                triangle_faces = [face for face in _strip_triangles(ring_indexes[0], ring_indexes[1])]
            triangle_faces.append(ring_indexes[0])
            end_ring = ring_indexes[1]
            if round_end:
                tip_index = len(rings) * 8
                reversed_end = list(reversed(end_ring))
                triangle_faces.extend([[tip_index, reversed_end[j], reversed_end[(j + 1) % 8]]
                                       for j in range(8)])
            else:
                triangle_faces.append(list(reversed(end_ring)))
    return np.asarray(frame_vertices, dtype=float), _triangulate(triangle_faces)


def _sphere_mesh(points, centers, axes, radii):
    frame_vertices, faces = [], None
    for center, frame, radius in zip(centers, axes, radii):
        if radius <= 0 or not np.isfinite(radius):
            raise ValueError("wearSphere radius must be finite and positive")
        side, up, forward = frame
        vertices = [center - up * radius, center + up * radius]
        for h in (-.5, .5):
            ring_center = center + up * (h * radius)
            vertices.extend([ring_center + side * (np.cos(j * np.pi / 4) * radius * .866)
                             + forward * (np.sin(j * np.pi / 4) * radius * .866) for j in range(8)])
        frame_vertices.append(vertices)
        if faces is None:
            bottom, top = 0, 1
            lower, upper = list(range(2, 10)), list(range(10, 18))
            faces = [[bottom, lower[j], lower[(j + 1) % 8]] for j in range(8)]
            faces.extend(_strip_triangles(lower, upper))
            reversed_upper = list(reversed(upper))
            faces.extend([[top, reversed_upper[j], reversed_upper[(j + 1) % 8]]
                          for j in range(8)])
    return np.asarray(frame_vertices, dtype=float), _triangulate(faces)


def body_surface_primitive_meshes(points, names, frames=None, binding=None):
    """Return native wearSegment/wearSphere meshes in renderer-local coordinates.

    ``binding`` may provide renderer-bound ``segmentLengths``, per-frame
    ``bodyAxes``, ``limbSides``, ``headMaterial`` dimensions, ``footScale``,
    ``footRestPitchRadians``, and ``shoeOrientation``. Frames may supply native
    ``boneSides`` and ``shoeOrientation``. IDs identify native mesh families.
    """
    points = np.asarray(points, dtype=float)
    names = list(names)
    if points.ndim != 3 or points.shape[0] == 0 or points.shape[1:] != (len(names), 3) or not np.isfinite(points).all():
        raise ValueError("points must be nonempty finite frames x jointNames x 3")
    if len(set(names)) != len(names):
        raise ValueError("joint names must be unique")
    binding = dict(binding or {})
    from .native_foot_geometry import validated_native_foot_geometry
    native_foot_geometry = validated_native_foot_geometry(
        binding.get("nativeFootGeometry"))
    if frames is not None and len(frames) != len(points):
        raise ValueError("frames length must match points")
    axes = _body_axes(points, names, binding)
    lengths = _stable_lengths(points, names, binding)
    sides = _limb_side_tracks(points, names, axes, binding, frames)
    meshes = {}
    display_points = points.copy()
    if all(name in names for name in ("left_shoulder", "right_shoulder")):
        shoulder_width = float(binding.get("shoulderWidth", np.linalg.norm(
            points[0, names.index("left_shoulder")] - points[0, names.index("right_shoulder")])))
        if shoulder_width <= .0001:
            raise ValueError("native arm display offset requires shoulder width")
        shoulder_offset = _unit(points[:, names.index("left_shoulder")] - points[:, names.index("right_shoulder")],
                                -axes[:, 0]) * shoulder_width * .075
        for name in ("left_shoulder", "left_elbow", "left_wrist", "left_hand"):
            if name in names:
                display_points[:, names.index(name)] += shoulder_offset
        for name in ("right_shoulder", "right_elbow", "right_wrist", "right_hand"):
            if name in names:
                display_points[:, names.index(name)] -= shoulder_offset
    for start, end, sw, ew, depth_scale, bulge_scale, bulge_position in _LIMBS:
        key = f"{start}->{end}"
        if start not in names or end not in names or key not in lengths or key not in sides:
            continue
        length = float(lengths[key])
        if not np.isfinite(length) or length <= .0001:
            raise ValueError(f"invalid bound native segment length for {key}")
        start_width, end_width = length * sw, length * ew
        capnames = ("hip", "shoulder", "elbow", "wrist", "knee", "ankle")
        def inset(name, width):
            if name.endswith("_ankle"):
                return width * .44 * .90 * .85
            if name.endswith("_hip") or name.endswith("_shoulder"):
                return width * .12
            return width * .08 if any(name.endswith("_" + part) for part in capnames) else 0.
        si = inset(start, start_width)
        ei = inset(end, end_width)
        verts, tris = _segment_mesh(points,
            display_points[:, names.index(start)], display_points[:, names.index(end)],
            np.broadcast_to([start_width, end_width], (len(points), 2)),
            np.full(len(points), depth_scale), sides[key], np.full(len(points), si),
            np.full(len(points), ei), np.full((len(points), 1), bulge_scale),
            np.full(len(points), bulge_position))
        meshes[f"wearSegment:{key}"] = {"vertices": verts.reshape(len(points), -1, 3), "triangles": tris}

    # The renderer's palms use wearSegment with a rounded tip and clip-bound
    # widths distinct from its eight ordinary limb segments.
    for side in ("left", "right"):
        wrist, hand, elbow = (f"{side}_{part}" for part in ("wrist", "hand", "elbow"))
        hand_key, arm_key = f"{wrist}->{hand}", f"{elbow}->{wrist}"
        if not all(name in names for name in (wrist, hand, elbow)) or hand_key not in lengths:
            continue
        hand_length = float(lengths[hand_key])
        wrist_width = max(float(lengths.get(arm_key, 0.)) * .17 * .90, hand_length * .42)
        end_width = max(wrist_width * 1.10, hand_length * .50) * .65
        directions = display_points[:, names.index(hand)] - display_points[:, names.index(wrist)]
        preferred = _native_side_rows(directions, axes)
        verts, tris = _segment_mesh(points, display_points[:, names.index(wrist)],
            display_points[:, names.index(hand)], np.broadcast_to([wrist_width, end_width], (len(points), 2)),
            np.full(len(points), .36), preferred, np.full(len(points), wrist_width * .08),
            np.zeros(len(points)), np.full((len(points), 1), 1.12), np.full(len(points), .58), round_end=True)
        meshes[f"wearSegment:{hand_key}"] = {"vertices": verts.reshape(len(points), -1, 3), "triangles": tris}

    # Native sphere radii depend on clip-bound limb dimensions. Shoulder and
    # hip caps use their actual torso frames; other caps use renderer body axes.
    shoulder_width = float(binding.get("shoulderWidth", np.linalg.norm(
        points[0, names.index("left_shoulder")] - points[0, names.index("right_shoulder")])
        if "left_shoulder" in names and "right_shoulder" in names else 0.))
    arm_lengths = [lengths.get(f"{side}_shoulder->{side}_elbow", 0.) for side in ("left", "right")]
    if all(name in names for name in ("pelvis", "neck", "left_hip", "right_hip",
                                      "left_shoulder", "right_shoulder")) and shoulder_width > .0001:
        pelvis_axes, shoulder_axes = _torso_cap_axes(display_points, names, axes, shoulder_width, arm_lengths)
    else:
        pelvis_axes, shoulder_axes = axes, axes
    for joint in _CAP_JOINTS:
        if joint not in names:
            continue
        side_name, part = joint.split("_", 1)
        if part == "shoulder":
            arm = f"{side_name}_shoulder->{side_name}_elbow"
            if arm not in lengths:
                continue
            radius = lengths[arm] * .30 * .44 * .90
            if shoulder_width <= .0001:
                raise ValueError("native shoulder cap requires shoulder width")
            sphere_axes = shoulder_axes
        elif part in ("hip",):
            radius = lengths.get(f"{joint}->{side_name}_knee", 0.) * .27 * .46 * .90
            sphere_axes = pelvis_axes
        elif part == "knee":
            radius = max(lengths.get(f"{side_name}_hip->{joint}", 0.) * .215,
                         lengths.get(f"{joint}->{side_name}_ankle", 0.) * .225) * .40
            sphere_axes = axes
        elif part == "ankle":
            radius = lengths.get(f"{side_name}_knee->{joint}", 0.) * .165 * .44 * .90
            sphere_axes = axes
        elif part == "elbow":
            radius = max(lengths.get(f"{side_name}_shoulder->{joint}", 0.) * .225,
                         lengths.get(f"{joint}->{side_name}_wrist", 0.) * .235) * .40
            sphere_axes = axes
        else:  # wrist
            radius = lengths.get(f"{side_name}_elbow->{joint}", 0.) * .17 * .30
            sphere_axes = axes
        if radius <= .0001:
            continue
        centers = points[:, names.index(joint)].copy()
        if part == "shoulder":
            # Renderer shifts both shoulder/arm chains outward before meshing.
            offset = _unit(points[:, names.index("left_shoulder")] - points[:, names.index("right_shoulder")], -axes[:, 0]) * shoulder_width * .075
            centers += offset if side_name == "left" else -offset
        verts, tris = _sphere_mesh(points, centers, sphere_axes, np.full(len(points), radius))
        meshes[f"wearSphere:{joint}"] = {"vertices": verts.reshape(len(points), -1, 3), "triangles": tris}
    # Keep the native rounded head material mesh and its renderer strip/fan topology.
    if all(name in names for name in ("neck", "head", "pelvis", "left_hip", "right_hip",
                                      "left_shoulder", "right_shoulder")):
        from .render_geometry import head_material_vertices
        head_binding = binding.get("headMaterial")
        if head_binding is None and {"headLength", "shoulderWidth"} <= set(binding):
            head_binding = {key: binding[key] for key in ("headLength", "shoulderWidth")}
        head_vertices = head_material_vertices(points, names, binding=head_binding)
        head_faces = [face for lo, hi in zip([list(range(i * 8, (i + 1) * 8)) for i in range(3)],
                                               [list(range((i + 1) * 8, (i + 2) * 8)) for i in range(3)])
                      for face in _strip_triangles(lo, hi)]
        head_faces.extend((list(reversed(list(range(24, 32)))),))
        meshes["wearHeadMaterial:head"] = {"vertices": head_vertices,
                                             "triangles": _triangulate(head_faces)}

    # The material-shoe builder and its native topology own footwear geometry.
    if all(name in names for side in ("left", "right")
           for name in (f"{side}_ankle", f"{side}_foot", f"{side}_knee")):
        from .foot_geometry import foot_scale_from_pose, shoe_vertices
        from .material_region_support import shoe_triangles
        from .render_geometry import material_leg_sides
        render_frames = (list(frames) if frames is not None else [
            {"joints": {name: row[index].tolist() for index, name in enumerate(names)}}
            for row in points])
        rendered_sides = material_leg_sides(render_frames)
        foot_scale = binding.get("footScale")
        if foot_scale is None:
            first = next((i for i, row in enumerate(points)
                          if all(name in names for name in ("left_hip", "right_hip",
                                                            "left_shoulder", "right_shoulder"))
                          and np.linalg.norm(row[names.index("left_hip")] - row[names.index("right_hip")]) > .0001
                          and np.linalg.norm(row[names.index("left_shoulder")] - row[names.index("right_shoulder")]) > .0001), None)
            if first is None:
                raise ValueError("native shoe geometry requires bound hip and shoulder widths")
            row = points[first]
            hip_width = np.linalg.norm(row[names.index("left_hip")] - row[names.index("right_hip")])
            shoulder_width_bound = np.linalg.norm(row[names.index("left_shoulder")] - row[names.index("right_shoulder")])
            foot_scale = max(hip_width * .98, shoulder_width_bound * .58)
        foot_scale = float(foot_scale)
        if not np.isfinite(foot_scale) or foot_scale <= 0:
            raise ValueError("footScale must be finite and positive")
        pitch_binding = binding.get("footRestPitchRadians") or {}
        orientation_binding = binding.get("shoeOrientation") or {}
        for side in ("left", "right"):
            ankle_name, toe_name, knee_name = f"{side}_ankle", f"{side}_foot", f"{side}_knee"
            key = f"{ankle_name}->{toe_name}"
            preferred = (binding.get("limbSides") or {}).get(key)
            if preferred is not None:
                lateral_rows = np.asarray(preferred, dtype=float)
                if lateral_rows.shape == (3,):
                    lateral_rows = np.broadcast_to(lateral_rows, (len(points), 3))
                if lateral_rows.shape != (len(points), 3) or not np.isfinite(lateral_rows).all():
                    raise ValueError(f"limbSides[{key}] must be finite frames x 3")
            else:
                lateral_rows = np.asarray([
                    (frame.get("boneSides") or {}).get(key, rendered_sides[index].get(key))
                    for index, frame in enumerate(render_frames)], dtype=float)
                if lateral_rows.shape != (len(points), 3) or not np.isfinite(lateral_rows).all():
                    raise ValueError(f"native shoe side axis unavailable for {side}")
            rest_pitch = pitch_binding.get(side)
            if rest_pitch is not None and (isinstance(rest_pitch, bool) or not np.isfinite(float(rest_pitch))):
                raise ValueError(f"footRestPitchRadians[{side}] must be finite")
            vertices = []
            for index, row in enumerate(points):
                orientation = orientation_binding.get(side)
                if isinstance(orientation, dict):
                    forward, orientation_side = orientation.get("forward"), orientation.get("side")
                    if forward is not None and np.asarray(forward).shape == (len(points), 3):
                        orientation = {"forward": np.asarray(forward)[index],
                                       "side": np.asarray(orientation_side)[index]}
                if orientation is None and index < len(render_frames):
                    orientation = (render_frames[index].get("shoeOrientation") or {}).get(side)
                ankle = row[names.index(ankle_name)]
                toe = row[names.index(toe_name)]
                if np.linalg.norm(toe - ankle) <= .0001:
                    raise ValueError(f"native shoe geometry requires a nonzero {side} ankle-foot vector")
                vertices.append(shoe_vertices(ankle, toe, lateral_rows[index], rest_pitch,
                                              foot_scale, orientation=orientation,
                                              native_geometry=(native_foot_geometry['sides'][side]
                                                               if native_foot_geometry else None)))
            meshes[f"wearShoe:{key}"] = {"vertices": np.asarray(vertices), "triangles": shoe_triangles()}

    # Full native thorax, abdomen, pelvis and neck shell. The historical
    # upper-back quads are returned from the same ring construction for parity.
    from .render_geometry import native_torso_shell_geometry
    torso_binding = binding.get("torsoMaterial")
    if torso_binding is None and {"shoulderWidth", "upperArmLengths"} <= set(binding):
        torso_binding = {key: binding[key] for key in
                         ("shoulderWidth", "upperArmLengths", "hipWidth", "thighLengths") if key in binding}
    torso = native_torso_shell_geometry(points, names, binding=torso_binding, body_axes=axes)
    meshes["wearTorsoShell:body"] = {
        "vertices": torso["vertices"], "triangles": torso["triangles"],
        "ringNames": torso["ringNames"], "upperBackQuads": torso["upperBackQuads"],
    }
    return meshes


def evaluate_contact_patch(meshes, binding):
    """Evaluate triangle/barycentric points on one actual primitive mesh."""
    try:
        primitive = binding["primitiveId"]
        points = binding["points"]
        mesh = meshes[primitive]
        vertices = np.asarray(mesh["vertices"], dtype=float)
        triangles = np.asarray(mesh["triangles"], dtype=np.int64)
    except (KeyError, TypeError) as exc:
        raise ValueError("patch binding references an unavailable primitive") from exc
    if vertices.ndim != 3 or vertices.shape[-1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("primitive vertices must be finite frames x V x 3")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or np.any(triangles < 0) or np.any(triangles >= vertices.shape[1]):
        raise ValueError("primitive triangles are malformed")
    if not isinstance(points, list) or not points:
        raise ValueError("patch points must be a nonempty list")
    result = []
    for point in points:
        try:
            raw_index = point["triangleIndex"]
            if isinstance(raw_index, bool) or not isinstance(raw_index, (int, np.integer)):
                raise ValueError("triangleIndex must be an integer")
            index = int(raw_index)
            weights = np.asarray(point["barycentric"], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("patch point requires triangleIndex and barycentric") from exc
        if index < 0 or index >= len(triangles) or weights.shape != (3,) or not np.isfinite(weights).all() or np.any(weights < 0) or not np.isclose(weights.sum(), 1., atol=1e-8):
            raise ValueError("patch point has invalid triangle or barycentric coordinates")
        result.append(np.einsum("v,fvd->fd", weights, vertices[:, triangles[index], :]))
    return np.stack(result, axis=1)


def _plane_frame(normal):
    """Return an orthonormal tangent basis for a unit plane normal."""
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    first = np.cross(normal, axis)
    first /= max(np.linalg.norm(first), 1e-12)
    return first, np.cross(normal, first)


def _oriented_polygon_2d(polygon, normal):
    """Project a planar polygon into its plane frame, oriented counter-clockwise."""
    first, second = _plane_frame(normal)
    projected = np.stack((polygon @ first, polygon @ second), axis=1)
    area = .5 * float(np.sum(
        projected[:, 0] * np.roll(projected[:, 1], -1)
        - np.roll(projected[:, 0], -1) * projected[:, 1]))
    scale = max(float(np.ptp(projected[:, 0])), float(np.ptp(projected[:, 1])), 1e-9)
    if abs(area) <= 1e-12 * scale * scale:
        raise ValueError("support plane polygon is degenerate")
    if area < 0.:
        projected = projected[::-1]
    edges = np.roll(projected, -1, axis=0) - projected
    following = np.roll(edges, -1, axis=0)
    turns = edges[:, 0] * following[:, 1] - edges[:, 1] * following[:, 0]
    if np.any(turns < -1e-12 * scale * scale):
        raise ValueError("support plane polygon must be convex")
    return first, second, projected, scale


def _clip_convex_points(subject, clip, tolerance):
    """Sutherland-Hodgman against a counter-clockwise convex polygon.

    Each subject row is ``(point_2d, barycentric)``. Boundary points are
    retained so a material point exactly on a support edge is never dropped.
    """
    result = list(subject)
    for index, start in enumerate(clip):
        if not result:
            break
        end = clip[(index + 1) % len(clip)]
        edge = end - start

        def distance(point):
            return edge[0] * (point[1] - start[1]) - edge[1] * (point[0] - start[0])

        clipped = []
        previous = result[-1]
        previous_distance = distance(previous[0])
        for current in result:
            current_distance = distance(current[0])
            previous_inside = previous_distance >= -tolerance
            current_inside = current_distance >= -tolerance
            if previous_inside != current_inside:
                alpha = previous_distance / (previous_distance - current_distance)
                clipped.append((
                    previous[0] + alpha * (current[0] - previous[0]),
                    previous[1] + alpha * (current[1] - previous[1]),
                ))
            if current_inside:
                clipped.append(current)
            previous, previous_distance = current, current_distance
        result = clipped
    return result


def _triangle_polygon_weights(corners, polygon_2d, first, second, tolerance):
    """Barycentric weights of a native triangle clipped to a convex support."""
    projected = np.stack((corners @ first, corners @ second), axis=1)
    subject = [(projected[index], np.eye(3)[index]) for index in range(3)]
    return [np.asarray(weights, dtype=float)
            for _, weights in _clip_convex_points(subject, polygon_2d, tolerance)]


def _point_inside_polygon_2d(point, polygon_2d, tolerance):
    for start, end in zip(polygon_2d, np.roll(polygon_2d, -1, axis=0)):
        edge = end - start
        if edge[0] * (point[1] - start[1]) - edge[1] * (point[0] - start[0]) < -tolerance:
            return False
    return True


def _normalized_material_weights(weights):
    weights = np.clip(np.asarray(weights, dtype=float), 0., None)
    total = float(weights.sum())
    if not np.isfinite(total) or total <= 0.:
        raise ValueError("body surface material weights are degenerate")
    return weights / total


def _material_point_drift(material_points, normal):
    displacement = material_points - material_points[0]
    tangential = displacement - (displacement @ normal)[:, None] * normal
    return float(np.linalg.norm(tangential, axis=1).max())


def native_min_signed_distance(vertices, triangles, normal, offset, polygon=None):
    """Minimum signed plane distance over native material geometry.

    On an unbounded plane the minimum of a linear signed distance over each
    triangle is a vertex. With a finite convex support polygon every triangle
    is clipped in the plane frame so intersections without an inside vertex are
    still measured; material beyond the footprint is ignored. Frames whose
    geometry does not meet the footprint return ``inf`` (no contact).
    """
    vertices = np.asarray(vertices, dtype=float)
    triangles = np.asarray(triangles, dtype=np.int64)
    normal = np.asarray(normal, dtype=float)
    if (vertices.ndim != 3 or vertices.shape[-1] != 3 or not np.isfinite(vertices).all()
            or triangles.ndim != 2 or triangles.shape[1] != 3
            or np.any(triangles < 0) or np.any(triangles >= vertices.shape[1])
            or normal.shape != (3,) or not np.isfinite(normal).all()
            or abs(np.linalg.norm(normal) - 1.) > 1e-6
            or not np.isfinite(float(offset))):
        raise ValueError("native material geometry is malformed")
    signed = np.einsum("fvc,c->fv", vertices, normal) - float(offset)
    if polygon is None:
        return np.min(signed[:, triangles], axis=(1, 2))
    polygon = np.asarray(polygon, dtype=float)
    if (polygon.ndim != 2 or polygon.shape[1] != 3 or len(polygon) < 3
            or not np.isfinite(polygon).all()):
        raise ValueError("support plane polygon is malformed")
    first, second, polygon_2d, scale = _oriented_polygon_2d(polygon, normal)
    tolerance = 1e-9 * scale * scale
    minimum = np.full(len(vertices), np.inf)
    for frame, frame_vertices in enumerate(vertices):
        frame_minimum = np.inf
        for triangle in triangles:
            for weight in _triangle_polygon_weights(
                    frame_vertices[triangle], polygon_2d, first, second, tolerance):
                frame_minimum = min(
                    frame_minimum, float(weight @ signed[frame, triangle]))
        minimum[frame] = frame_minimum
    return minimum


def bind_body_surface_contact_to_plane(record, meshes, primitive_id, surface_estimate,
                                       *, frame_map=None, geometry_provenance=None):
    """Bind verified contact facts to an extremal material point on a world plane.

    The caller owns the verified source facts and the plane. This helper selects
    one support-facing native-material triangle and binds its lowest material
    point, not the triangle centroid. Binding an extremal point means a fit that
    puts the bound point on the plane cannot leave the same primitive below it.
    The helper does not infer a plane or certify the initial pose; an initial
    float below or above the plane is repaired by the fit.
    """
    try:
        mesh = meshes[primitive_id]
        vertices = np.asarray(mesh["vertices"], dtype=float)
        triangles = np.asarray(mesh["triangles"], dtype=np.int64)
    except (KeyError, TypeError) as exc:
        raise ValueError("body surface primitive is unavailable") from exc
    if (vertices.ndim != 3 or vertices.shape[-1] != 3 or not np.isfinite(vertices).all()
            or triangles.ndim != 2 or triangles.shape[1] != 3
            or np.any(triangles < 0) or np.any(triangles >= vertices.shape[1])
            or len(triangles) == 0):
        raise ValueError("body surface primitive geometry is malformed")
    try:
        normal = np.asarray(surface_estimate["normal"], dtype=float)
        offset = float(surface_estimate["offsetMeters"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("support plane is malformed") from exc
    if (normal.shape != (3,) or not np.isfinite(normal).all()
            or abs(np.linalg.norm(normal) - 1.) > 1e-6
            or not np.isfinite(offset)):
        raise ValueError("support plane must provide a finite unit normal and offset")
    polygon = surface_estimate.get("polygonWorld")
    if polygon is not None:
        polygon = np.asarray(polygon, dtype=float)
        tolerance = 1e-4 * max(1., abs(offset))
        if (polygon.ndim != 2 or polygon.shape[1] != 3 or len(polygon) < 3
                or not np.isfinite(polygon).all()
                or not np.allclose(polygon @ normal, offset, atol=tolerance, rtol=0.)):
            raise ValueError("support plane polygon is malformed")
    mode = record.get("contactMode")
    if mode not in ("stationary", "sliding", "rolling"):
        raise ValueError("body surface contact mode is unsupported")
    if mode == "rolling" and polygon is not None:
        raise ValueError("rolling contact on a finite support polygon is unsupported")
    observations = (record.get("sourceEvidence") or {}).get("observations") or []
    active = [row for row in observations
              if row.get("contactState") == "direct_contact" and row.get("visible") is True]
    if not active:
        raise ValueError("body surface contact has no positive visible contact rows")
    if frame_map is not None and not isinstance(frame_map, dict):
        raise ValueError("body surface contact frame mapping is malformed")
    frames = []
    for row in active:
        source_frame = row.get("sourcePoseFrameIndex")
        mapped = frame_map.get(source_frame) if isinstance(frame_map, dict) else source_frame
        if (isinstance(mapped, bool) or not isinstance(mapped, (int, np.integer))
                or not 0 <= int(mapped) < len(vertices)):
            raise ValueError("body surface contact frame mapping is unavailable")
        frames.append(int(mapped))
    frames = np.asarray(sorted(set(frames)), dtype=np.int64)
    corners = vertices[frames][:, triangles]
    faces = np.cross(corners[:, :, 1] - corners[:, :, 0],
                     corners[:, :, 2] - corners[:, :, 0])
    lengths = np.linalg.norm(faces, axis=-1)
    unit_faces = faces / np.maximum(lengths[..., None], 1e-30)
    candidates = np.all(lengths > 1e-12, axis=0) & np.all(
        np.einsum("ftc,c->ft", unit_faces, normal) < -1e-6, axis=0)
    indices = np.flatnonzero(candidates)
    if not len(indices):
        raise ValueError("no support-facing native material triangle satisfies the plane")
    depths = np.asarray([
        (float(np.mean(values[np.isfinite(values)]))
         if np.isfinite(values).any() else np.inf)
        for values in (
            native_min_signed_distance(
                vertices[frames], triangles[index][None, :], normal, offset, polygon)
            for index in indices)
    ])
    if not np.isfinite(depths).any():
        raise ValueError("no support-facing native material triangle satisfies the plane")
    # Support depth is primary: the lowest material extremum is the first
    # contact, even when the initial body lies below the plane. Stationary
    # drift only breaks exact depth ties, so it cannot spend support depth.
    triangle_index = int(indices[np.lexsort((indices, depths))[0]])
    chosen_corners = vertices[frames][:, triangles[triangle_index]]
    if polygon is None:
        weight_pool = [np.eye(3)[index] for index in range(3)]
    else:
        first, second, polygon_2d, scale = _oriented_polygon_2d(polygon, normal)
        tolerance = 1e-9 * scale * scale
        weight_pool = []
        for frame_corners in chosen_corners:
            weight_pool.extend(_triangle_polygon_weights(
                frame_corners, polygon_2d, first, second, tolerance))
    unique_weights = {}
    for weights in weight_pool:
        weights = _normalized_material_weights(weights)
        unique_weights.setdefault(tuple(np.round(weights, 10)), weights)
    feasible = []
    for weights in unique_weights.values():
        material_points = np.einsum("v,fvc->fc", weights, chosen_corners)
        if polygon is not None:
            inside = all(
                _point_inside_polygon_2d(
                    np.asarray([point @ first, point @ second]),
                    polygon_2d, tolerance)
                for point in material_points)
            if not inside:
                continue
        signed = material_points @ normal - offset
        feasible.append((weights, signed))
    if not feasible:
        raise ValueError("no extremal material support point lies inside the support polygon")
    depths = np.asarray([float(np.mean(signed)) for _, signed in feasible])
    if mode == "stationary":
        drift = np.asarray([
            _material_point_drift(
                np.einsum("v,fvc->fc", weights, chosen_corners), normal)
            for weights, _ in feasible
        ])
    else:
        drift = np.zeros(len(feasible))
    selected = int(np.lexsort((np.arange(len(feasible)), drift, depths))[0])
    weights = feasible[selected][0]
    estimate = {"normal": normal.tolist(), "offsetMeters": offset}
    if polygon is not None:
        estimate["polygonWorld"] = polygon.tolist()
    provenance = geometry_provenance or {
        "kind": "inferred",
        "cue": "provided_surface_estimate_with_native_mesh_binding",
    }
    bound = dict(record)
    bound["patchBinding"] = {
        "primitiveId": primitive_id,
        "points": [{"triangleIndex": triangle_index,
                    "barycentric": weights.tolist()}],
    }
    bound["surfaceEstimate"] = estimate
    bound["geometryProvenance"] = provenance
    return normalize_body_surface_contact(bound)


def native_shoe_region_candidates(vertices, triangles, ankles, balls, side_axes,
                                  frame_indices, region_role):
    """Clip shoe triangles to the canonical forefoot/heel region and return weights.

    Region membership is tested on the actual clipped triangle portion in the
    pose-aware ankle/ball frame. The returned material point is still inferred
    placement; this helper does not create source evidence.
    """
    vertices = np.asarray(vertices, dtype=float)
    triangles = np.asarray(triangles, dtype=np.int64)
    ankles, balls, side_axes = (np.asarray(value, dtype=float)
                                for value in (ankles, balls, side_axes))
    frame_indices = np.asarray(frame_indices, dtype=int)
    if (region_role not in {'forefoot', 'heel', 'full_sole'}
            or vertices.ndim != 3 or vertices.shape[-1] != 3
            or triangles.ndim != 2 or triangles.shape[1] != 3
            or np.any(triangles < 0) or np.any(triangles >= vertices.shape[1])
            or ankles.shape != (len(vertices), 3) or balls.shape != ankles.shape
            or side_axes.shape != ankles.shape or not np.isfinite(vertices).all()
            or not np.isfinite(ankles).all() or not np.isfinite(balls).all()
            or not np.isfinite(side_axes).all() or not len(frame_indices)
            or np.any(frame_indices < 0) or np.any(frame_indices >= len(vertices))):
        raise ValueError('native shoe region geometry is malformed')
    first = int(frame_indices[0])
    forward = balls[first] - ankles[first]
    bone_length = float(np.linalg.norm(forward))
    if bone_length <= 1e-9:
        raise ValueError('native shoe region has a zero-length ankle-foot bone')
    forward /= bone_length
    lateral = side_axes[first] - forward * np.dot(side_axes[first], forward)
    lateral_length = float(np.linalg.norm(lateral))
    if lateral_length <= 1e-9:
        raise ValueError('native shoe region side axis is collinear with the foot')
    lateral /= lateral_length
    projected = np.stack(((vertices[first] - ankles[first]) @ forward,
                          (vertices[first] - ankles[first]) @ lateral), axis=1)
    longitudinal = projected[:, 0]
    lateral_min, lateral_max = float(longitudinal.min()), float(longitudinal.max())
    side_min, side_max = float(projected[:, 1].min()), float(projected[:, 1].max())
    eps = max(bone_length, side_max - side_min, 1.) * 1e-9
    if region_role == 'forefoot':
        lo, hi = bone_length, lateral_max + eps
    elif region_role == 'heel':
        lo, hi = lateral_min - eps, 0.
    else:
        lo, hi = lateral_min - eps, lateral_max + eps
    clip = np.asarray([[lo, side_min-eps], [hi, side_min-eps],
                       [hi, side_max+eps], [lo, side_max+eps]], dtype=float)
    eligible = []
    for index, triangle in enumerate(triangles):
        if region_role == 'full_sole':
            weights = [np.eye(3)[i] for i in range(3)]
        else:
            corners = vertices[first, triangle]
            coords = np.stack(((corners - ankles[first]) @ forward,
                               (corners - ankles[first]) @ lateral), axis=1)
            subject = [(coords[i], np.eye(3)[i]) for i in range(3)]
            clipped = _clip_convex_points(subject, clip, 1e-10)
            weights = [np.asarray(row[1], dtype=float) for row in clipped]
        for barycentric in weights:
            barycentric = _normalized_material_weights(barycentric)
            points = np.einsum('v,fvc->fc', barycentric,
                               vertices[frame_indices][:, triangle])
            if region_role != 'full_sole':
                for frame, point in zip(frame_indices, points):
                    vector = balls[frame] - ankles[frame]
                    length = np.linalg.norm(vector)
                    if length <= 1e-9:
                        break
                    axis = vector / length
                    coordinate = float(np.dot(point - ankles[frame], axis))
                    if region_role == 'forefoot' and coordinate < length - 1e-8:
                        break
                    if region_role == 'heel' and coordinate > 1e-8:
                        break
                else:
                    eligible.append((index, barycentric))
            else:
                eligible.append((index, barycentric))
    if not eligible:
        raise ValueError(f'no actual shoe triangle portion lies in the {region_role} region')
    return eligible


def select_native_shoe_material_point(vertices, triangles, eligible_points,
                                     frame_indices, normal, offset):
    """Select one stationary support-facing barycentric point from clipped candidates."""
    vertices = np.asarray(vertices, dtype=float)
    triangles = np.asarray(triangles, dtype=np.int64)
    frames = np.asarray(frame_indices, dtype=int)
    normal = np.asarray(normal, dtype=float)
    if (vertices.ndim != 3 or vertices.shape[-1] != 3 or not np.isfinite(vertices).all()
            or triangles.ndim != 2 or triangles.shape[1] != 3
            or not len(frames) or np.any(frames < 0) or np.any(frames >= len(vertices))
            or normal.shape != (3,) or not np.isfinite(normal).all()
            or abs(np.linalg.norm(normal) - 1.) > 1e-6 or not np.isfinite(offset)):
        raise ValueError('native shoe material plane inputs are malformed')
    candidates = []
    for triangle_index, barycentric in eligible_points:
        triangle = triangles[int(triangle_index)]
        corners = vertices[frames][:, triangle]
        faces = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        lengths = np.linalg.norm(faces, axis=1)
        if np.any(lengths <= 1e-12) or np.any((faces @ normal) >= -1e-8):
            continue
        point = np.einsum('v,fvc->fc', barycentric, corners)
        signed = point @ normal - float(offset)
        tangent = point - np.outer(point @ normal, normal)
        drift = _material_point_drift(tangent, normal)
        candidates.append((float(np.mean(signed)), drift, int(triangle_index),
                           np.asarray(barycentric, dtype=float), point))
    if not candidates:
        raise ValueError('no clipped native shoe material point faces the support plane')
    _, _, triangle_index, barycentric, points = min(
        candidates, key=lambda row: (row[0], row[1], row[2], tuple(row[3])))
    target = points[0] + (float(offset) - float(np.dot(normal, points[0]))) * normal
    return {'triangleIndex': triangle_index,
            'barycentric': barycentric.tolist(),
            'targetWorld': target.tolist()}
