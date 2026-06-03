from __future__ import annotations

from pathlib import Path


TARGET_RIG_NAME = "assethunts_mannequin_man_v1"
TARGET_RIG_ASSET = Path(__file__).with_name("assets") / "mannequin" / "Mannequin_Man.glb"

TARGET_RIG_BONE_MAP = {
    "root": "root.x",
    "spineLower": "spine_01.x",
    "spineMid": "spine_02.x",
    "spineUpper": "spine_03.x",
    "neck": "neck.x",
    "head": "head.x",
    "leftClavicle": "shoulder.l",
    "leftUpperArm": "arm_stretch.l",
    "leftLowerArm": "forearm_stretch.l",
    "leftHand": "hand.l",
    "rightClavicle": "shoulder.r",
    "rightUpperArm": "arm_stretch.r",
    "rightLowerArm": "forearm_stretch.r",
    "rightHand": "hand.r",
    "leftUpperLeg": "thigh_stretch.l",
    "leftLowerLeg": "leg_stretch.l",
    "leftFoot": "foot.l",
    "leftToes": "toes_01.l",
    "rightUpperLeg": "thigh_stretch.r",
    "rightLowerLeg": "leg_stretch.r",
    "rightFoot": "foot.r",
    "rightToes": "toes_01.r",
    "trajectory": "c_traj",
}

IGNORED_BONES = (
    "thumb_01.l",
    "thumb_02.l",
    "thumb_03.l",
    "index_01.l",
    "index_02.l",
    "index_03.l",
    "middle_01.l",
    "middle_02.l",
    "middle_03.l",
    "ring_01.l",
    "ring_02.l",
    "ring_03.l",
    "pinky_01.l",
    "pinky_02.l",
    "pinky_03.l",
    "thumb_01.r",
    "thumb_02.r",
    "thumb_03.r",
    "index_01.r",
    "index_02.r",
    "index_03.r",
    "middle_01.r",
    "middle_02.r",
    "middle_03.r",
    "ring_01.r",
    "ring_02.r",
    "ring_03.r",
    "pinky_01.r",
    "pinky_02.r",
    "pinky_03.r",
)


def build_target_rig_contract() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "targetRigName": TARGET_RIG_NAME,
        "assetPath": str(TARGET_RIG_ASSET),
        "assetExists": TARGET_RIG_ASSET.exists(),
        "assetFormat": "glb",
        "coordinateSystem": {
            "units": "meters",
            "upAxis": "Y",
            "forwardAxis": "Z",
        },
        "boneMap": dict(TARGET_RIG_BONE_MAP),
        "ignoredBones": list(IGNORED_BONES),
        "retargetPolicy": {
            "mode": "offline_only",
            "source": "gvhmr_smplx",
            "rootHandling": "solve_offline",
            "fingerPolicy": "neutral_pose",
            "toePolicy": "neutral_pose",
            "twistPolicy": "solve_in_parent_space",
        },
    }
