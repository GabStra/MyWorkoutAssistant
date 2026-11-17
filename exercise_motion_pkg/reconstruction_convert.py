from __future__ import annotations

from pathlib import Path
import math

from exercise_motion_pkg.legacy_smpl_compat import ensure_legacy_smpl_runtime_compat
from exercise_motion_pkg.models import MotionClip, MotionFrame
from exercise_motion_pkg.smpl_joint_names import SMPL_JOINT_NAMES
from exercise_motion_pkg.reconstruction_results import load_reconstruction_results, resolve_reconstruction_coordinate_keys, select_reconstruction_subject, validate_reconstruction_frame_rate

NATIVE_FOOT_SIDE_AXIS_PROVENANCE = "gvhmr_ankle_global_smpl_rotation"


def convert_reconstruction_results_to_motion_clip(
    *,
    reconstruction_results_pkl: Path,
    body_model_root: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
    output_rotation_degrees: float = 0.0,
    fps: float = 30.0,
    extractor: str = "RECONSTRUCTION",
    source_frame_clock: dict[str, object] | None = None,
) -> MotionClip:
    fps = validate_reconstruction_frame_rate(fps)
    ensure_legacy_smpl_runtime_compat()
    try:
        import torch  # type: ignore
        import smplx  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "RECONSTRUCTION conversion requires torch and smplx in the active environment. "
            "Run this stage with the RECONSTRUCTION Python environment or install those packages there."
        ) from exc

    raw_results = load_reconstruction_results(reconstruction_results_pkl)
    resolved_subject_id, payload = select_reconstruction_subject(raw_results, subject_id=subject_id)
    pose_key, translation_key = resolve_reconstruction_coordinate_keys(coordinate_space)

    pose = torch.as_tensor(payload.get(pose_key), dtype=torch.float32)
    translation = torch.as_tensor(payload.get(translation_key), dtype=torch.float32)
    betas = torch.as_tensor(payload.get("betas"), dtype=torch.float32)
    frame_ids = payload.get("frame_ids")

    if pose.ndim != 2 or pose.shape[1] != 72:
        raise ValueError(f"RECONSTRUCTION '{pose_key}' must be shaped like [frames, 72].")
    if translation.ndim != 2 or translation.shape[1] != 3:
        raise ValueError(f"RECONSTRUCTION '{translation_key}' must be shaped like [frames, 3].")
    frame_count = int(pose.shape[0])
    if frame_count <= 0:
        raise ValueError(f"RECONSTRUCTION '{pose_key}' must contain at least one frame.")
    if translation.shape[0] != frame_count:
        raise ValueError(
            f"RECONSTRUCTION '{translation_key}' frame count {translation.shape[0]} does not match pose frame count {frame_count}."
        )
    betas = _prepare_betas(torch, betas, frame_count=frame_count)

    model = smplx.create(
        model_path=str(body_model_root),
        model_type="smpl",
        gender="neutral",
        batch_size=frame_count,
    )
    with torch.no_grad():
        output = model(
            global_orient=pose[:, :3],
            body_pose=pose[:, 3:],
            betas=betas,
            transl=translation,
        )
    foot_marker_prior = _named_foot_marker_prior(
        model, betas[:1], reconstruction_results_pkl, body_model_root, source_frame_clock)

    joints = output.joints[:, : len(SMPL_JOINT_NAMES), :].detach().cpu().tolist()
    if abs(output_rotation_degrees) > 1e-6:
        radians = math.radians(output_rotation_degrees)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        joints = [
            [
                [
                    cosine * float(coords[0]) - sine * float(coords[1]),
                    sine * float(coords[0]) + cosine * float(coords[1]),
                    float(coords[2]),
                ]
                for coords in joint_row
            ]
            for joint_row in joints
        ]
    normalized_frame_ids = _normalize_frame_ids(frame_ids, frame_count=frame_count)
    native_foot_bone_sides = _native_foot_bone_sides(
        pose=pose.detach().cpu().numpy(),
        joints=joints,
        parents=_model_parents(model),
        foot_marker_prior=foot_marker_prior,
        output_rotation_degrees=output_rotation_degrees,
    )
    camera_registration = reconstruction_camera_registration(payload, pose, coordinate_space)
    source_references = None
    if source_frame_clock is not None:
        from .source_frame_clock import source_references_for_frame_ids

        source_references = source_references_for_frame_ids(source_frame_clock, normalized_frame_ids)
    frames: list[MotionFrame] = []
    for index, joint_row in enumerate(joints):
        frame_joints = {
            SMPL_JOINT_NAMES[joint_index]: (
                float(coords[0]),
                float(coords[1]),
                float(coords[2]),
            )
            for joint_index, coords in enumerate(joint_row)
        }
        frames.append(
            MotionFrame(
                time_sec=float(normalized_frame_ids[index]) / fps,
                joints=frame_joints,
                source_time_sec=(float(source_references[index]["sourceTimeSec"]) if source_references is not None else None),
                source_frame_index=(int(source_references[index]["sourceFrameIndex"]) if source_references is not None else None),
                inference_frame_index=(normalized_frame_ids[index] if source_references is not None else None),
                bone_sides=(native_foot_bone_sides[index] if native_foot_bone_sides else None),
                bone_side_provenance=(
                    {key: NATIVE_FOOT_SIDE_AXIS_PROVENANCE
                     for key in native_foot_bone_sides[index]}
                    if native_foot_bone_sides else None
                ),
            )
        )

    return MotionClip(
        fps=fps,
        joint_names=list(SMPL_JOINT_NAMES),
        frames=frames,
        source={
            "extractor": extractor,
            "reconstructionResultsPkl": str(reconstruction_results_pkl),
            "coordinateSpace": coordinate_space,
            "subjectId": str(resolved_subject_id),
            "outputRotationDegrees": output_rotation_degrees,
        },
        metadata={
            "upstream": extractor.lower(),
            "reconstruction": {
                "coordinateSpace": coordinate_space,
                "subjectId": str(resolved_subject_id),
                "frameIds": normalized_frame_ids,
                "sourceFps": fps,
                **({"footMarkerPrior": foot_marker_prior} if foot_marker_prior else {}),
                **({"cameraRegistration": camera_registration} if camera_registration is not None else {}),
                **({"sourceFrameClock": {
                    "sourceVideoPath": source_frame_clock.get("sourceVideoPath"),
                    "sourceVideoSha256": source_frame_clock.get("sourceVideoSha256"),
                    "outputVideoPath": source_frame_clock.get("outputVideoPath"),
                    "outputVideoSha256": source_frame_clock.get("outputVideoSha256"),
                }} if source_frame_clock is not None else {}),
            },
        },
    )


def _model_parents(model) -> list[int]:
    parents = getattr(model, "parents", None)
    if parents is None:
        return []
    if hasattr(parents, "detach"):
        parents = parents.detach().cpu().tolist()
    return [int(value) for value in parents]


def _native_foot_bone_sides(
    *,
    pose,
    joints,
    parents: list[int],
    foot_marker_prior,
    output_rotation_degrees: float,
):
    """Produce the ankle->foot bone side from the posed ankle global rotation.

    The leg/ankle rotation owns the bone direction; the ball/foot joint rotation
    only adds toe articulation and must not be used here. Arrays are model-pose
    estimates, so downstream approved corrections may still change them.
    """
    import numpy as np
    from scipy.spatial.transform import Rotation

    if not isinstance(foot_marker_prior, dict) or not parents:
        return None
    prior_sides = foot_marker_prior.get("sides")
    if not isinstance(prior_sides, dict):
        return None
    pose_array = np.asarray(pose, dtype=np.float64)
    joints_array = np.asarray(joints, dtype=np.float64)
    if pose_array.ndim != 2 or pose_array.shape[1] != 72:
        return None
    frame_count = int(pose_array.shape[0])
    if (joints_array.shape != (frame_count, len(SMPL_JOINT_NAMES), 3)
            or len(parents) < len(SMPL_JOINT_NAMES)):
        return None
    rotations = Rotation.from_rotvec(
        pose_array.reshape(-1, 3)).as_matrix().reshape(frame_count, len(SMPL_JOINT_NAMES), 3, 3)
    rotation_z = None
    if abs(output_rotation_degrees) > 1e-6:
        rotation_z = Rotation.from_euler(
            "z", output_rotation_degrees, degrees=True).as_matrix()
    sides = {}
    for side in ("left", "right"):
        try:
            side_prior = prior_sides[side]
            model_frame = np.asarray(side_prior["modelFootFrame"], dtype=np.float64)
        except (KeyError, TypeError, ValueError):
            return None
        if (model_frame.shape != (3, 3) or not np.isfinite(model_frame).all()
                or not np.allclose(np.linalg.norm(model_frame, axis=0), 1.0, atol=1e-4)
                or not np.allclose(model_frame.T @ model_frame, np.eye(3), atol=1e-4)):
            return None
        ankle_name, foot_name = f"{side}_ankle", f"{side}_foot"
        ankle_index, foot_index = SMPL_JOINT_NAMES.index(ankle_name), SMPL_JOINT_NAMES.index(foot_name)
        global_rotation = np.broadcast_to(np.eye(3), (frame_count, 3, 3)).copy()
        joint_index = ankle_index
        chain = []
        while joint_index >= 0:
            chain.append(joint_index)
            joint_index = int(parents[joint_index])
        for joint_index in reversed(chain):
            global_rotation = np.matmul(global_rotation, rotations[:, joint_index])
        side_axis = np.einsum("fij,j->fi", global_rotation, model_frame[:, 1])
        if rotation_z is not None:
            side_axis = side_axis @ rotation_z.T
        forward = joints_array[:, foot_index] - joints_array[:, ankle_index]
        forward_length = np.linalg.norm(forward, axis=1, keepdims=True)
        if np.any(forward_length <= 1e-9):
            return None
        forward = forward / forward_length
        side_axis = side_axis - forward * np.sum(side_axis * forward, axis=1, keepdims=True)
        side_length = np.linalg.norm(side_axis, axis=1, keepdims=True)
        if np.any(side_length <= 1e-9) or not np.isfinite(side_axis).all():
            return None
        sides[side] = (side_axis / side_length)
    return [
        {
            f"{side}_ankle->{side}_foot": sides[side][frame_index].tolist()
            for side in ("left", "right")
        }
        for frame_index in range(frame_count)
    ]


def _named_foot_marker_prior(model, betas, reconstruction_path, model_root, clock):
    """Retain numeric rest geometry; fitting never imports the body model."""
    import hashlib
    import numpy as np
    import torch
    from smplx.vertex_ids import vertex_ids

    asset = Path(model_root) / 'smpl' / 'SMPL_NEUTRAL.pkl'
    if not asset.is_file() or not isinstance(clock, dict):
        return None
    with torch.no_grad():
        neutral = model(
            global_orient=torch.zeros(1, 3), body_pose=torch.zeros(1, 69),
            betas=betas, transl=torch.zeros(1, 3), return_verts=True)
    vertices, joints = neutral.vertices[0].cpu().numpy(), neutral.joints[0].cpu().numpy()
    owners = model.lbs_weights.argmax(dim=1).cpu().numpy()
    sides = {}
    for side, prefix, ankle, foot in (('left', 'L', 7, 10), ('right', 'R', 8, 11)):
        forward = joints[foot] - joints[ankle]
        bone_length = float(np.linalg.norm(forward))
        forward /= np.linalg.norm(forward)
        lateral = np.cross(forward, [0., 1., 0.])
        lateral /= np.linalg.norm(lateral)
        basis = np.stack([forward, lateral, np.cross(lateral, forward)], axis=1)
        heel = int(vertex_ids['smplh'][prefix + 'Heel'])
        toes = [int(vertex_ids['smplh'][prefix + name]) for name in ('BigToe', 'SmallToe')]
        toe = vertices[toes].mean(axis=0)
        region = vertices[np.isin(owners, [ankle, foot])] - joints[ankle]
        sides[side] = {
            'heelVertex': heel, 'toeVertices': toes,
            'ankleToFootJointLengthMeters': bone_length,
            'heelToToeLocalMeters': ((vertices[heel] - toe) @ basis).tolist(),
            'toeFromAnkleLocalMeters': ((toe - joints[ankle]) @ basis).tolist(),
            'modelFootFrame': basis.tolist(),
            'regionMinimumModelMeters': region.min(axis=0).tolist(),
            'regionMaximumModelMeters': region.max(axis=0).tolist(),
        }
    return {
        'source': 'named_smpl_rest_heel_and_toe_vertices', 'modelType': 'smpl',
        'modelVertexCount': int(len(vertices)),
        'modelSha256': hashlib.sha256(asset.read_bytes()).hexdigest(),
        'reconstructionSha256': hashlib.sha256(Path(reconstruction_path).read_bytes()).hexdigest(),
        'sourceVideoSha256': clock.get('sourceVideoSha256'),
        'modelInputVideoSha256': clock.get('outputVideoSha256'),
        'sides': sides,
    }


def reconstruction_camera_registration(payload, pose, coordinate_space):
    """Fit one camera orientation from paired reconstruction roots, never fitted limbs."""
    if coordinate_space != "world" or "camera_global_orient" not in payload:
        return None
    import numpy as np
    from scipy.spatial.transform import Rotation

    world = np.asarray(pose)[:, :3]
    camera = np.asarray(payload["camera_global_orient"])
    if camera.shape != world.shape or not np.isfinite(camera).all():
        raise ValueError("Reconstruction camera roots must match finite world roots.")
    rotations = Rotation.from_rotvec(camera).as_matrix() @ Rotation.from_rotvec(world).as_matrix().transpose(0, 2, 1)
    fitted = Rotation.from_matrix(rotations).mean()
    residual = (fitted.inv() * Rotation.from_matrix(rotations)).magnitude()
    return {"rotationWorldToCamera": fitted.as_matrix().tolist(),
            "policy": "paired_reconstruction_roots_fixed_camera_fit",
            "p95AngularResidualDegrees": float(np.degrees(np.percentile(residual, 95)))}


def normalize_reconstruction_output(
    *,
    reconstruction_results_pkl: Path,
    body_model_root: Path,
    output_json: Path,
    coordinate_space: str = "world",
    subject_id: int | str | None = None,
    output_rotation_degrees: float = 0.0,
    fps: float = 30.0,
    extractor: str = "RECONSTRUCTION",
    source_frame_clock_path: Path | None = None,
) -> Path:
    from exercise_motion_pkg.motion_io import save_motion_json

    source_frame_clock = None
    if source_frame_clock_path is not None:
        from .source_frame_clock import load_verified_source_frame_clock

        source_frame_clock = load_verified_source_frame_clock(source_frame_clock_path)
    clip = convert_reconstruction_results_to_motion_clip(
        reconstruction_results_pkl=reconstruction_results_pkl,
        body_model_root=body_model_root,
        coordinate_space=coordinate_space,
        subject_id=subject_id,
        output_rotation_degrees=output_rotation_degrees,
        fps=fps,
        extractor=extractor,
        source_frame_clock=source_frame_clock,
    )
    save_motion_json(output_json, clip)
    return output_json


def _prepare_betas(torch_module: object, betas, *, frame_count: int):
    if betas.ndim == 1:
        return betas.unsqueeze(0).repeat(frame_count, 1)
    if betas.ndim != 2:
        raise ValueError("RECONSTRUCTION betas must be shaped like [10] or [frames, 10].")
    if betas.shape[0] == frame_count:
        return betas
    if betas.shape[0] == 1:
        return betas.repeat(frame_count, 1)
    raise ValueError(
        f"RECONSTRUCTION betas shape {tuple(betas.shape)} is incompatible with frame count {frame_count}."
    )


def _normalize_frame_ids(frame_ids: object, *, frame_count: int) -> list[int]:
    if frame_ids is None:
        return list(range(frame_count))
    if not hasattr(frame_ids, "__len__"):
        raise ValueError("RECONSTRUCTION frame_ids must be a sequence when provided.")
    normalized = [int(value) for value in frame_ids]  # type: ignore[arg-type]
    if len(normalized) != frame_count:
        raise ValueError(
            f"RECONSTRUCTION frame_ids length {len(normalized)} does not match frame count {frame_count}."
        )
    return normalized
