from copy import deepcopy
import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.support_alignment import validate_alignment


def supported_torso():
    joints = {'pelvis': [0, 0, 0], 'left_hip': [-.15, 0, 0], 'right_hip': [.15, 0, 0],
              'left_shoulder': [-.2, 0, .5], 'right_shoulder': [.2, 0, .5],
              'spine1': [.02, .02, .15], 'spine2': [.01, .03, .3], 'spine3': [0, .02, .4]}
    evidence = {'required': True, 'status': 'confirmed', 'coplanarGroups': [
        {'joints': ['pelvis', 'left_shoulder', 'right_shoulder'], 'normal': [0, 1, 0]}]}
    return list(joints), np.tile(list(joints.values()), (8, 1, 1)), evidence


def test_preserves_valid_bending_and_allows_support_height_repair_in_any_orientation():
    names, original, evidence = supported_torso()
    corrected = original.copy()
    corrected[:, names.index('spine1'), 1] += .03
    corrected += [3, 2, 1]
    assert validate_alignment(corrected, original, names, evidence)['passed']
    rotation = Rotation.from_euler('xyz', [31, -42, 68], degrees=True)
    transformed = deepcopy(evidence)
    transformed['coplanarGroups'][0]['normal'] = rotation.apply([0, 1, 0]).tolist()
    rotate = lambda points: rotation.apply(points.reshape(-1, 3)).reshape(points.shape)
    assert validate_alignment(rotate(corrected), rotate(original), names, transformed)['passed']


def test_rejects_introduced_pelvic_rotation_and_sideways_waist_bend():
    names, original, evidence = supported_torso()
    for defect in ('pelvis', 'roll', 'waist', 'pelvis_offset'):
        corrected = original.copy()
        if defect in ('pelvis', 'roll'):
            indices = [names.index('left_hip'), names.index('right_hip')]
            rotation = Rotation.from_euler('y' if defect == 'pelvis' else 'z', 13, degrees=True)
            corrected[:, indices] = rotation.apply(original[:, indices].reshape(-1, 3)).reshape(8, 2, 3)
        elif defect == 'pelvis_offset':
            corrected[:, names.index('pelvis'), 0] += .01
        else:
            corrected[:, names.index('spine1'), 0] += .03
        assert not validate_alignment(corrected, original, names, evidence)['passed']
    assert not validate_alignment(original, None, names, evidence)['passed']
    # A stationary supported torso must not reproduce noisy per-frame roll.
    evidence['stationaryJoints'] = ['pelvis', 'left_shoulder', 'right_shoulder']
    noisy = original.copy()
    indices = [names.index('left_hip'), names.index('right_hip')]
    for frame, angle in enumerate(np.linspace(-4., 4., len(noisy))):
        noisy[frame, indices] = Rotation.from_euler('z', angle, degrees=True).apply(original[frame, indices])
    assert validate_alignment(original, noisy, names, evidence)['passed']
    assert not validate_alignment(noisy, noisy, names, evidence)['passed']
