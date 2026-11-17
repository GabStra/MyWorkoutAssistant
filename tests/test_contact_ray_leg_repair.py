from time import monotonic

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.contact_heel_repair import propose_contact_heel_repair


class _BilateralToeRig:
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
        active_index = {joint: index for index, joint in enumerate(self.active)}
        for joint in self.order:
            parent = self.parents[joint]
            local = (rotations[:, active_index[joint]] if joint in active_index
                     else np.broadcast_to(np.eye(3), (len(coordinates), 3, 3)))
            world[joint] = local if parent < 0 else world[parent] @ local
            if parent >= 0:
                points[:, joint] = points[:, parent] + np.einsum(
                    'fij,j->fi', world[joint], self.offsets[joint])
        return points


def _fixture(*, full_sole=False, wrong_owner=False):
    rig = _BilateralToeRig()
    coordinates = np.zeros((4, rig.width), dtype=float)
    points = rig.decode(coordinates)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    pinned[:, [rig.names.index('left_foot'), rig.names.index('right_foot')]] = True
    target = points.copy()
    projection = np.asarray([[1., 0., 0.], [0., 1., 0.]])
    null = np.cross(projection[0], projection[1])
    expected = Rotation.from_rotvec(null * np.deg2rad(-25.))
    reflection = np.diag([-1., 1., 1.])
    rows = []
    for side in ('left', 'right'):
        ankle = rig.names.index(f'{side}_ankle')
        foot = rig.names.index(f'{side}_foot')
        vector = points[0, foot] - points[0, ankle]
        if side == 'left':
            vector = reflection @ expected.apply(reflection @ vector)
        else:
            vector = expected.apply(vector)
        ray = projection @ vector
        if wrong_owner:
            ankle += 1
        for frame in range(4):
            rows.append({'sourceSide': side, 'ankleJointIndex': ankle,
                         'footJointIndex': foot, 'leftFrame': frame,
                         'rightFrame': frame, 'alpha': 0.,
                         'targetRay': ray.tolist(), 'confidenceWeight': 1.,
                         'headingOffsetRadians': 0.})
    constraint = {'available': True, 'projection': projection.tolist(),
                  'sourceFootRayObservations': rows,
                  'sourceFootRaySideMapping': {'left': 'left', 'right': 'right'}}
    payload = {'canonicalExecution': {'legs': 'mirrored'}}
    if full_sole:
        payload['sourceFootSupportEvidence'] = {'footPatchEvidence': {
            'available': True, 'feet': {'left': {'states': ['full_sole']}}}}
    return rig, coordinates, points, target, pinned, constraint, payload


def _propose(fixture):
    rig, coordinates, points, targets, pinned, constraint, payload = fixture
    return propose_contact_heel_repair(
        rig, coordinates, payload=payload,
        source_projection_constraint=constraint,
        anatomical_reference=points, pinned=pinned,
        fps=30., cyclic=True, deadline=monotonic() + 10.,
        jerk_reference=points, shake_reference=points,
        jerk_limit=1., body_scale=1., contact_targets=targets)


def test_camera_ray_only_mirrored_toe_repair_keeps_contacts_and_bone_lengths():
    fixture = _fixture()
    proposal = _propose(fixture)
    assert proposal is not None
    coordinates, tracks, details = proposal
    rig, _seed, points, targets, pinned, constraint, _payload = fixture
    updated = rig.decode(coordinates)
    np.testing.assert_allclose(updated[pinned], targets[pinned], atol=1e-8, rtol=0.)
    assert tracks['version'] == 1
    assert details['cameraHeadingIs2DInference'] is True
    assert details['heelOr3DHeadingClaimed'] is False
    assert details['cameraHeadingAfter']['passed'] is True
    assert abs(details['derivedMirroredYawDegrees']) > 0.
    for side in ('left', 'right'):
        hip, knee, ankle, foot = (rig.names.index(f'{side}_{part}')
                                  for part in ('hip', 'knee', 'ankle', 'foot'))
        np.testing.assert_allclose(
            np.linalg.norm(updated[:, knee] - updated[:, hip], axis=1),
            np.linalg.norm(points[:, knee] - points[:, hip], axis=1), atol=1e-10, rtol=0.)
        np.testing.assert_allclose(
            np.linalg.norm(updated[:, ankle] - updated[:, knee], axis=1),
            np.linalg.norm(points[:, ankle] - points[:, knee], axis=1), atol=1e-10, rtol=0.)
        np.testing.assert_allclose(
            np.linalg.norm(updated[:, foot] - updated[:, ankle], axis=1),
            np.linalg.norm(points[:, foot] - points[:, ankle], axis=1), atol=1e-10, rtol=0.)


def test_camera_ray_only_mirrored_toe_repair_rejects_unbound_or_fullsole_authority():
    assert _propose(_fixture(wrong_owner=True)) is None
    assert _propose(_fixture(full_sole=True)) is None
