import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.foot_kinematics import stabilize_rigid_feet, _knee_angles
from exercise_motion_pkg.models import MotionClip, MotionFrame


def test_fast_rigid_leg_swing_does_not_create_ankle_articulation():
    frames=[]
    for index, angle in enumerate([0.,0.,10.,25.,60.,90.,110.,115.,115.]):
        rotation=Rotation.from_euler('x',angle,degrees=True)
        frames.append(MotionFrame(index/30.,{'left_knee':tuple(rotation.apply([0.,1.,0.])),
            'left_ankle':(0.,0.,0.),'left_foot':tuple(rotation.apply([0.,0.,.2]))}))
    clip=MotionClip(30.,list(frames[0].joints),frames)
    repaired,_=stabilize_rigid_feet(clip)
    for before,after in zip(clip.frames,repaired.frames):
        np.testing.assert_allclose(after.joints['left_foot'],before.joints['left_foot'],atol=1e-10)
        assert _knee_angles(*[np.array(after.joints[k]) for k in ['left_knee','left_ankle','left_foot']])==pytest.approx(np.pi/2)


def test_degenerate_shin_does_not_collapse_the_foot():
    joints={'left_knee':(0.,0.,0.),'left_ankle':(0.,0.,0.),'left_foot':(0.,0.,.2)}
    clip=MotionClip(30.,list(joints),[MotionFrame(i/30.,dict(joints)) for i in range(5)])
    repaired,_=stabilize_rigid_feet(clip)
    for frame in repaired.frames:
        assert np.linalg.norm(frame.joints['left_foot'])==pytest.approx(.2)
