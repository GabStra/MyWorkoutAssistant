"""Exact coordinate-space projection for requested canonical execution policies."""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


_REFLECTION = np.diag([-1.0, 1.0, 1.0])
_FORWARD = np.array([0.0, 1.0, 0.0])


def _layout(fixed_rig):
    names = list(fixed_rig["jointNames"])
    parents = np.asarray(fixed_rig["parents"], dtype=int)
    offsets = np.asarray(fixed_rig["offsets"], dtype=float)
    rotation_names = list(fixed_rig["rotationJointNames"])
    values = np.asarray(fixed_rig["coordinates"], dtype=float)
    if (parents.shape != (len(names),) or offsets.shape != (len(names), 3)
            or values.ndim != 2 or values.shape[1] != 3 + 3 * len(rotation_names)
            or not np.isfinite(offsets).all() or not np.isfinite(values).all()):
        raise ValueError("Canonical projection received an invalid fixed-rig layout")
    index = {name: i for i, name in enumerate(names)}
    slots = {index[name]: slice(3 + 3 * i, 6 + 3 * i)
             for i, name in enumerate(rotation_names) if name in index}
    if len(index) != len(names) or any(name not in index for name in rotation_names):
        raise ValueError("Canonical projection received duplicate or unknown rig joints")
    order = fixed_rig.get("order")
    order = list(range(len(names))) if order is None else [int(value) for value in order]
    if sorted(order) != list(range(len(names))):
        raise ValueError("Canonical projection requires a complete rig order")
    roots = [joint for joint, parent in enumerate(parents) if parent < 0]
    if len(roots) != 1:
        raise ValueError("Canonical projection requires one fixed-rig root")
    root = roots[0]
    return names, index, parents, offsets, slots, order, root, values


def _forward_kinematics(values, parents, offsets, slots, order, root):
    frames = len(values)
    local = {}
    identity = np.broadcast_to(np.eye(3), (frames, 3, 3))
    for joint, slot in slots.items():
        local[joint] = Rotation.from_rotvec(values[:, slot]).as_matrix()
    world = {}
    points = np.empty((frames, len(parents), 3), dtype=float)
    points[:, root] = values[:, :3]
    for joint in order:
        parent = parents[joint]
        matrix = local.get(joint, identity)
        world[joint] = matrix if parent < 0 else world[parent] @ matrix
        if parent >= 0:
            points[:, joint] = points[:, parent] + np.einsum(
                "fij,j->fi", world[joint], offsets[joint])
    return points, world, local


def _minimal_rotation(source, target):
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    source = source / np.linalg.norm(source, axis=1, keepdims=True)
    target = target / np.linalg.norm(target, axis=1, keepdims=True)
    cross = np.cross(source, target)
    sine = np.linalg.norm(cross, axis=1)
    cosine = np.clip(np.sum(source * target, axis=1), -1.0, 1.0)
    if np.any((sine <= 1e-10) & (cosine < 0.0)):
        raise ValueError("Canonical projection cannot choose an axis for an antiparallel direction")
    axis = cross / np.maximum(sine[:, None], 1e-15)
    angle = np.arctan2(sine, cosine)
    return Rotation.from_rotvec(axis * angle[:, None]).as_matrix()


def _policy_modes(execution):
    execution = execution or {}
    if "torso" in execution and execution["torso"] not in {
        "sagittal", "support_aligned", "unconstrained", None,
    }:
        raise ValueError("Unsupported canonical torso execution mode")
    for group in ("legs", "arms"):
        if group in execution and execution[group] not in {"mirrored", "unconstrained", None}:
            raise ValueError("Unsupported canonical bilateral execution mode")
    torso = execution.get("torso") == "sagittal"
    legs = execution.get("legs") == "mirrored"
    arms = execution.get("arms") == "mirrored"
    return torso, legs, arms


def _validate_sagittal_rig(names, index, parents, offsets, slots, root):
    required = ("pelvis", "left_hip", "right_hip", "spine1", "spine2", "spine3", "neck", "head")
    if any(name not in index for name in required):
        raise ValueError("Sagittal projection requires pelvis, hips, spine, neck and head joints")
    pelvis = index["pelvis"]
    if pelvis != root or pelvis not in slots:
        raise ValueError("Sagittal projection currently requires pelvis as the fixed-rig root")
    left_hip, right_hip = index["left_hip"], index["right_hip"]
    span = offsets[right_hip] - offsets[left_hip]
    if (parents[left_hip] != root or parents[right_hip] != root
            or left_hip in slots or right_hip in slots
            or np.linalg.norm(span) <= 1e-8
            or np.linalg.norm(span[[1, 2]]) > 1e-7 * np.linalg.norm(span)):
        raise ValueError("Sagittal projection requires fixed hips on the local lateral axis")
    spine = ("spine1", "spine2", "spine3", "neck")
    for joint_name in spine:
        joint = index[joint_name]
        if joint not in slots or np.linalg.norm(offsets[joint, [0, 2]]) > 1e-7 * max(1e-8, np.linalg.norm(offsets[joint])):
            raise ValueError("Sagittal projection requires rotatable centerline spine offsets")
    if index["head"] not in slots:
        raise ValueError("Sagittal projection requires a rotatable head")
    return span


def _mirror_legs(values, names, index, parents, offsets, slots, order, root, authority):
    for part in ("hip", "knee", "ankle", "foot"):
        if f"left_{part}" not in index or f"right_{part}" not in index:
            raise ValueError("Leg mirroring requires complete left and right leg chains")
    left_hip, right_hip = index["left_hip"], index["right_hip"]
    if parents[left_hip] != parents[right_hip] or left_hip in slots or right_hip in slots:
        raise ValueError("Leg mirroring requires fixed bilateral hip anchors")
    anchor_axis = offsets[right_hip] - offsets[left_hip]
    anchor_length = np.linalg.norm(anchor_axis)
    if anchor_length <= 1e-9:
        raise ValueError("Leg mirroring requires distinct hip anchors")
    anchor_axis /= anchor_length
    anchor_reflection = np.eye(3) - 2.0 * np.outer(anchor_axis, anchor_axis)
    for part in ("knee", "ankle", "foot"):
        left, right = index[f"left_{part}"], index[f"right_{part}"]
        if left not in slots or right not in slots:
            raise ValueError("Leg mirroring requires local rotations for both " + part + " joints")
        if np.linalg.norm(offsets[left] - offsets[right]) > 1e-8:
            raise ValueError("Leg mirroring requires equal paired downstream offsets")
    left_knee, right_knee = index["left_knee"], index["right_knee"]
    if np.linalg.norm(offsets[left_knee, [0, 2]]) > 1e-8:
        raise ValueError("Leg mirroring requires knee offsets on the sagittal axis")
    _, source_world, local = _forward_kinematics(values, parents, offsets, slots, order, root)
    for part in ("knee", "ankle"):
        left, right = index[f"left_{part}"], index[f"right_{part}"]
        left_local, right_local = local[left], local[right]
        parent_reflection = anchor_reflection if part == "knee" else _REFLECTION
        reflected_right = parent_reflection @ right_local @ _REFLECTION
        if authority == "right":
            shared_left = reflected_right
        elif authority == "left":
            shared_left = left_local
        else:
            relative = np.swapaxes(left_local, 1, 2) @ reflected_right
            shared_left = left_local @ Rotation.from_rotvec(
                Rotation.from_matrix(relative).as_rotvec() * 0.5).as_matrix()
        shared_right = parent_reflection @ shared_left @ _REFLECTION
        values[:, slots[index[f"left_{part}"]]] = Rotation.from_matrix(shared_left).as_rotvec()
        values[:, slots[index[f"right_{part}"]]] = Rotation.from_matrix(shared_right).as_rotvec()

    # Preserve each foot's free axial material twist while setting only its
    # mirrored bone direction. Average directions, never full foot matrices.
    left_foot, right_foot = index["left_foot"], index["right_foot"]
    left_ankle, right_ankle = index["left_ankle"], index["right_ankle"]
    source_left_foot_world = source_world[left_foot]
    source_right_foot_world = source_world[right_foot]
    source_left_forward = source_left_foot_world @ _FORWARD
    source_right_forward = source_right_foot_world @ _FORWARD
    source_left_parent = np.einsum(
        "fij,fj->fi", np.swapaxes(source_world[left_ankle], 1, 2), source_left_forward)
    source_right_parent = np.einsum(
        "fij,fj->fi", np.swapaxes(source_world[right_ankle], 1, 2), source_right_forward)
    _, world, _ = _forward_kinematics(values, parents, offsets, slots, order, root)
    if authority == "right":
        shared_left = (_REFLECTION @ source_right_parent.T).T
    elif authority == "left":
        shared_left = source_left_parent
    else:
        shared_left = source_left_parent + (_REFLECTION @ source_right_parent.T).T
    lengths = np.linalg.norm(shared_left, axis=1, keepdims=True)
    if np.any(lengths <= 1e-9):
        raise ValueError("Leg mirroring requires identifiable foot bone directions")
    shared_left /= lengths
    shared_right = (_REFLECTION @ shared_left.T).T
    desired_left = np.einsum("fij,fj->fi", world[left_ankle], shared_left)
    desired_right = np.einsum("fij,fj->fi", world[right_ankle], shared_right)
    for foot, ankle, desired in (
        (left_foot, left_ankle, desired_left), (right_foot, right_ankle, desired_right),
    ):
        old_foot_world = source_left_foot_world if foot == left_foot else source_right_foot_world
        old_forward = old_foot_world @ _FORWARD
        swing = _minimal_rotation(old_forward, desired)
        transported = swing @ old_foot_world
        local_foot = np.swapaxes(world[ankle], 1, 2) @ transported
        values[:, slots[foot]] = (
            Rotation.from_matrix(local_foot).as_rotvec())


def exact_canonical_coordinates(fixed_rig, execution, authoritative_sides=None):
    """Project fixed-rig coordinates onto requested canonical pose policies."""
    execution = execution or {}
    coordinates = np.asarray(fixed_rig["coordinates"], dtype=float).copy()
    if coordinates.ndim != 2 or not np.isfinite(coordinates).all():
        raise ValueError("Canonical projection requires finite frame-by-coordinate values")
    torso, legs, arms = _policy_modes(execution)
    if not (torso or legs or arms):
        return coordinates
    names, index, parents, offsets, slots, order, root, _ = _layout(fixed_rig)
    authority = (authoritative_sides or {}).get("legs")
    if authority not in (None, "left", "right"):
        raise ValueError("Invalid authoritative mirrored leg side")
    if torso:
        span = _validate_sagittal_rig(names, index, parents, offsets, slots, root)
        original = coordinates.copy()
        _, old_world, _ = _forward_kinematics(original, parents, offsets, slots, order, root)
        lateral = np.einsum("fij,j->fi", old_world[root], span)
        desired = lateral.copy()
        desired[:, 1] = 0.0
        lengths = np.linalg.norm(desired, axis=1)
        if np.any(lengths <= 1e-9):
            raise ValueError("Sagittal projection cannot identify horizontal heading")
        desired /= lengths[:, None]
        root_delta = _minimal_rotation(lateral, desired)
        new_root = root_delta @ old_world[root]
        coordinates[:, slots[index["pelvis"]]] = Rotation.from_matrix(new_root).as_rotvec()
        _, levelled_world, _ = _forward_kinematics(coordinates, parents, offsets, slots, order, root)
        if legs and authority in ("left", "right"):
            driver_hip = index[f"{authority}_hip"]
            before_points, _, _ = _forward_kinematics(original, parents, offsets, slots, order, root)
            after_points, _, _ = _forward_kinematics(coordinates, parents, offsets, slots, order, root)
            coordinates[:, :3] += before_points[:, driver_hip] - after_points[:, driver_hip]
        # Rebase both lower chains against the new pelvis frame. This keeps
        # each original bone direction under torso leveling; the leg policy
        # subsequently replaces only its non-authoritative chain.
        for side in ("left", "right"):
            for part in ("knee", "ankle", "foot"):
                joint = index[f"{side}_{part}"]
                parent = parents[joint]
                desired_world = old_world[joint]
                local_matrix = (desired_world if parent < 0 else
                                np.swapaxes(levelled_world[parent], 1, 2) @ desired_world)
                coordinates[:, slots[index[f"{side}_{part}"]]] = Rotation.from_matrix(local_matrix).as_rotvec()
                _, levelled_world, _ = _forward_kinematics(
                    coordinates, parents, offsets, slots, order, root)
        # Carry source spine bone directions through the pelvis-leveling
        # rotation. Raw local rotations are gauge-dependent: an arbitrary
        # twist shared between a parent and child can change them without
        # changing any source point or downstream world pose.
        root_lateral = desired
        for name in ("spine1", "spine2", "spine3", "neck"):
            joint = index[name]
            parent = parents[joint]
            world_direction = np.einsum("fij,fj->fi", root_delta, old_world[joint] @ _FORWARD)
            world_direction -= np.sum(
                world_direction * root_lateral, axis=1, keepdims=True) * root_lateral
            direction_length = np.linalg.norm(world_direction, axis=1, keepdims=True)
            if np.any(direction_length <= 1e-9):
                raise ValueError("Sagittal projection cannot identify source torso flexion")
            world_direction /= direction_length
            _, current_world, _ = _forward_kinematics(
                coordinates, parents, offsets, slots, order, root)
            parent_direction = np.einsum(
                "fij,fj->fi", np.swapaxes(current_world[parent], 1, 2), world_direction)
            if np.max(np.abs(parent_direction[:, 0])) > 1e-6:
                raise ValueError("Sagittal torso direction is outside the projected parent plane")
            pitch = np.arctan2(parent_direction[:, 2], parent_direction[:, 1])
            local_matrix = Rotation.from_rotvec(
                np.column_stack((pitch, np.zeros_like(pitch), np.zeros_like(pitch)))).as_matrix()
            coordinates[:, slots[index[name]]] = Rotation.from_matrix(local_matrix).as_rotvec()
        _, torso_world, _ = _forward_kinematics(coordinates, parents, offsets, slots, order, root)
        head = index["head"]
        parent = parents[head]
        head_local = np.swapaxes(torso_world[parent], 1, 2) @ old_world[head]
        coordinates[:, slots[index["head"]]] = Rotation.from_matrix(head_local).as_rotvec()
        # Ancestor gauge removal changes collar parent frames. Preserve each
        # shoulder's original world orientation before the arm policy is
        # applied so valid distal articulation is not rotated with the torso.
        _, torso_world, _ = _forward_kinematics(coordinates, parents, offsets, slots, order, root)
        for side in ("left", "right"):
            shoulder = index[f"{side}_shoulder"]
            if shoulder not in slots:
                raise ValueError("Sagittal projection requires rotatable shoulders")
            parent = parents[shoulder]
            shoulder_local = np.swapaxes(torso_world[parent], 1, 2) @ old_world[shoulder]
            coordinates[:, slots[shoulder]] = Rotation.from_matrix(shoulder_local).as_rotvec()
    if legs:
        _mirror_legs(coordinates, names, index, parents, offsets, slots, order, root, authority)
    if arms:
        from .controlled_motion import exact_mirrored_arm_coordinates

        coordinates = exact_mirrored_arm_coordinates(
            {**fixed_rig, "coordinates": coordinates}, execution)
    return coordinates


def exact_canonical_coordinate_jacobian(fixed_rig, execution, authoritative_sides=None):
    """Sparse frame-local Jacobian of :func:`exact_canonical_coordinates`."""
    from scipy.sparse import coo_matrix, eye

    values = np.asarray(fixed_rig["coordinates"], dtype=float)
    if values.ndim != 2:
        raise ValueError("Canonical projection requires frame-by-coordinate values")
    execution = execution or {}
    torso, legs, arms = _policy_modes(execution)
    if not (torso or legs or arms):
        return eye(values.size, format="csr")
    if arms and not torso and not legs:
        from .controlled_motion import exact_mirrored_arm_coordinate_jacobian

        return exact_mirrored_arm_coordinate_jacobian(fixed_rig, execution)
    frames, width = values.shape
    rows = []
    cols = []
    data = []
    step = np.cbrt(np.finfo(float).eps) * np.maximum(1.0, np.abs(values))
    for column in range(width):
        plus = values.copy()
        minus = values.copy()
        plus[:, column] += step[:, column]
        minus[:, column] -= step[:, column]
        positive = exact_canonical_coordinates(
            {**fixed_rig, "coordinates": plus}, execution, authoritative_sides)
        negative = exact_canonical_coordinates(
            {**fixed_rig, "coordinates": minus}, execution, authoritative_sides)
        derivative = (positive - negative) / (2.0 * step[:, column, None])
        for frame in range(frames):
            output_rows = frame * width + np.arange(width)
            input_column = frame * width + column
            valid = np.abs(derivative[frame]) > 1e-12
            rows.extend(output_rows[valid].tolist())
            cols.extend([input_column] * int(np.count_nonzero(valid)))
            data.extend(derivative[frame, valid].tolist())
    return coo_matrix((data, (rows, cols)), shape=(values.size, values.size)).tocsr()
