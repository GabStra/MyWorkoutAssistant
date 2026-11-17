from time import monotonic

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.contact_heel_repair import propose_contact_heel_repair


class _FreeFootRig:
    names = ['pelvis', 'left_hip', 'right_hip', 'left_knee', 'left_ankle',
             'left_foot', 'right_knee', 'right_ankle', 'right_foot']
    parents = np.asarray([-1, 0, 0, 1, 3, 4, 2, 6, 7])
    order = list(range(len(names)))
    root = 0
    active = [0, 3, 4, 5, 6, 7, 8]
    slots = {joint: 3 + 3 * offset for offset, joint in enumerate(active)}
    width = 3 + 3 * len(active)
    offsets = np.asarray([
        [0., 0., 0.], [-.25, 0., 0.], [.25, 0., 0.],
        [.12, -.35, 0.], [-.12, -.35, 0.], [0., -.02, .1],
        [-.12, -.35, 0.], [.12, -.35, 0.], [0., -.02, .1],
    ])

    def decode(self, coordinates):
        coordinates = np.asarray(coordinates, dtype=float)
        rotations = Rotation.from_rotvec(
            coordinates[:, 3:].reshape(-1, len(self.active), 3)
        ).as_matrix()
        points = np.empty((len(coordinates), len(self.names), 3))
        points[:, self.root] = coordinates[:, :3]
        world = {}
        active_index = {joint: i for i, joint in enumerate(self.active)}
        for joint in self.order:
            parent = self.parents[joint]
            local = (rotations[:, active_index[joint]] if joint in active_index
                     else np.broadcast_to(np.eye(3), (len(coordinates), 3, 3)))
            world[joint] = local if parent < 0 else world[parent] @ local
            if parent >= 0:
                points[:, joint] = points[:, parent] + np.einsum(
                    'fij,j->fi', world[joint], self.offsets[joint])
        return points


def _fixture(*, pinned_joint=None, full_sole=False, patch_available=True):
    rig = _FreeFootRig()
    coordinates = np.zeros((8, rig.width), dtype=float)
    points = rig.decode(coordinates)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    if pinned_joint:
        pinned[:, rig.names.index(pinned_joint)] = True
    projection = np.asarray([[1., 0., 0.], [0., 0., 1.]])
    reflection = np.diag([-1., 1., 1.])
    knee, ankle, foot = (rig.names.index(f'left_{part}')
                         for part in ('knee', 'ankle', 'foot'))
    shin = points[0, ankle] - points[0, knee]
    shin /= np.linalg.norm(shin)
    vector = points[0, foot] - points[0, ankle]
    lateral = np.cross(shin, vector)
    lateral /= np.linalg.norm(lateral)
    expected = (Rotation.from_rotvec(shin * np.deg2rad(38.))
                * Rotation.from_rotvec(lateral * np.deg2rad(10.)))
    left_ray = projection @ expected.apply(vector)
    right_vector = points[0, rig.names.index('right_foot')] - points[0, rig.names.index('right_ankle')]
    right_ray = projection @ (reflection @ expected.as_matrix() @ reflection @ right_vector)
    rows = []
    for side, ray in (('left', left_ray), ('right', right_ray)):
        ankle_i = rig.names.index(f'{side}_ankle')
        foot_i = rig.names.index(f'{side}_foot')
        for frame in range(len(coordinates)):
            rows.append({
                'sourceSide': side, 'ankleJointIndex': ankle_i,
                'footJointIndex': foot_i, 'leftFrame': frame,
                'rightFrame': frame, 'alpha': 0., 'targetRay': ray.tolist(),
                'confidenceWeight': 1., 'headingOffsetRadians': 0.,
            })
    constraint = {
        'available': True, 'projection': projection.tolist(),
        'sourceFootRayObservations': rows,
        'sourceFootRaySideMapping': {'left': 'left', 'right': 'right'},
    }
    patch = {
        'available': patch_available,
        'feet': {side: {'states': ['full_sole' if full_sole else 'unknown']}
                 for side in ('left', 'right')},
    }
    payload = {
        'canonicalExecution': {'legs': 'mirrored'},
        'sourceFootSupportEvidence': {
            'footPatchEvidence': patch, 'contacts': [], 'supportContacts': [],
        },
    }
    return rig, coordinates, points, pinned, constraint, payload


def _propose(fixture):
    rig, coordinates, points, pinned, constraint, payload = fixture
    return propose_contact_heel_repair(
        rig, coordinates, payload=payload,
        source_projection_constraint=constraint,
        anatomical_reference=points, pinned=pinned,
        fps=30., cyclic=True, deadline=monotonic() + 10.,
        jerk_reference=points, shake_reference=points,
        jerk_limit=1., body_scale=1., contact_targets=None,
    )


def test_free_mirrored_feet_fit_bounded_yaw_pitch_and_change_only_foot_dofs():
    fixture = _fixture()
    proposal = _propose(fixture)
    assert proposal is not None
    encoded, tracks, details = proposal
    rig, coordinates, points, pinned, _constraint, _payload = fixture
    decoded = rig.decode(encoded)

    assert details['strategy'] == 'source_camera_ray_mirrored_free_foot_yaw_pitch_v1'
    assert details['cameraHeadingAfter']['passed'] is True
    assert abs(details['derivedMirroredYawDegrees']) > 1.
    assert abs(details['derivedMirroredPitchDegrees']) > 1.
    assert abs(details['derivedMirroredPitchDegrees']) < 14.5
    np.testing.assert_allclose(decoded[:, [4, 7]], points[:, [4, 7]], atol=1e-10, rtol=0.)
    np.testing.assert_allclose(decoded[:, [0, 1, 2, 3, 6]], points[:, [0, 1, 2, 3, 6]], atol=1e-10, rtol=0.)
    np.testing.assert_allclose(
        np.linalg.norm(decoded[:, [5, 8]] - decoded[:, [4, 7]], axis=2),
        np.linalg.norm(points[:, [5, 8]] - points[:, [4, 7]], axis=2),
        atol=1e-10, rtol=0.)
    assert np.array_equal(encoded[:, :3], coordinates[:, :3])
    assert tracks['version'] == 1
    assert not np.any(pinned)


def test_free_mirrored_feet_decline_without_free_authority_or_with_a_foot_pin():
    assert _propose(_fixture(patch_available=False)) is None
    assert _propose(_fixture(full_sole=True)) is None
    assert _propose(_fixture(pinned_joint='left_foot')) is None
