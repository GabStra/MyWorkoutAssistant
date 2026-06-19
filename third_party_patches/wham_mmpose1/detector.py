from __future__ import annotations

import os
import os.path as osp
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import scipy.signal as signal
import torch

from ultralytics import YOLO
from mmpose.apis import init_model, inference_topdown


ROOT_DIR = osp.abspath(f"{__file__}/../../../../")

VIS_THRESH = float(os.environ.get("WHAM_KEYPOINT_VIS_THRESH", "0.3"))
BBOX_CONF = float(os.environ.get("WHAM_BBOX_CONF", "0.5"))
TRACKING_THR = float(os.environ.get("WHAM_TRACKING_THR", "0.1"))
MINIMUM_FRAMES = int(os.environ.get("WHAM_MINIMUM_TRACK_FRAMES", "30"))
MINIMUM_JOINTS = int(os.environ.get("WHAM_MINIMUM_JOINTS", "6"))
COCO_KEYPOINTS = 17

DEFAULT_POSE_CONFIG = osp.join(
    ROOT_DIR,
    "configs",
    "VIT",
    "td-hm_ViTPose-huge_8xb64-210e_coco-256x192.py",
)
DEFAULT_POSE_CHECKPOINT = osp.join(
    ROOT_DIR,
    "checkpoints",
    "td-hm_ViTPose-huge_8xb64-210e_coco-256x192-e32adcd4_20230314.pth",
)
DEFAULT_BBOX_MODEL = osp.join(ROOT_DIR, "checkpoints", "yolo26x.pt")


def _init_trusted_mmpose_model(config, checkpoint, device):
    original_load = torch.load

    def load_with_legacy_checkpoint_support(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    try:
        torch.load = load_with_legacy_checkpoint_support
        return init_model(config, checkpoint, device=device)
    finally:
        torch.load = original_load


def _cfg_value(cfg, name, default):
    if cfg is None:
        return default
    if hasattr(cfg, name):
        value = getattr(cfg, name)
        return value if value not in (None, "") else default
    if isinstance(cfg, dict):
        value = cfg.get(name)
        return value if value not in (None, "") else default
    return default


def _runtime_cfg(mmpose_cfg=None):
    return SimpleNamespace(
        pose_config=os.environ.get(
            "WHAM_MMPOSE_CONFIG",
            _cfg_value(mmpose_cfg, "POSE_CONFIG", DEFAULT_POSE_CONFIG),
        ),
        pose_checkpoint=os.environ.get(
            "WHAM_MMPOSE_CHECKPOINT",
            _cfg_value(mmpose_cfg, "POSE_CHECKPOINT", DEFAULT_POSE_CHECKPOINT),
        ),
        bbox_model=os.environ.get(
            "WHAM_YOLO_BBOX_MODEL",
            _cfg_value(mmpose_cfg, "DET_CHECKPOINT", DEFAULT_BBOX_MODEL),
        ),
        bbox_conf=float(_cfg_value(mmpose_cfg, "BBOX_CONF", BBOX_CONF)),
        tracking_thr=float(_cfg_value(mmpose_cfg, "TRACKING_THR", TRACKING_THR)),
        min_frames=int(_cfg_value(mmpose_cfg, "MINIMUM_FRAMES", MINIMUM_FRAMES)),
    )


def _as_numpy(value):
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def _normalize_keypoints(keypoints, scores):
    keypoints = _as_numpy(keypoints)
    scores = _as_numpy(scores)
    if keypoints.ndim == 3:
        keypoints = keypoints[0]
    if scores.ndim == 2:
        scores = scores[0]

    output = np.zeros((COCO_KEYPOINTS, 3), dtype=np.float32)
    count = min(COCO_KEYPOINTS, keypoints.shape[0], scores.shape[0])
    output[:count, :2] = keypoints[:count, :2]
    output[:count, 2] = scores[:count]
    return output


def _normalize_bbox(bbox):
    bbox = _as_numpy(bbox).astype(np.float32)
    if bbox.ndim == 2:
        bbox = bbox[0]
    return bbox[:4]


def _bbox_iou(a, b):
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, float(a[2] - a[0])) * max(0.0, float(a[3] - a[1]))
    area_b = max(0.0, float(b[2] - b[0])) * max(0.0, float(b[3] - b[1]))
    denom = area_a + area_b - inter
    return 0.0 if denom <= 0.0 else inter / denom


class DetectionModel(object):
    def __init__(self, device, mmpose_cfg=None):
        self.cfg = _runtime_cfg(mmpose_cfg)
        self.pose_model = _init_trusted_mmpose_model(
            self.cfg.pose_config,
            self.cfg.pose_checkpoint,
            device=device.lower(),
        )
        self.bbox_model = YOLO(self.cfg.bbox_model)
        self.device = device
        self.initialize_tracking()

    def initialize_tracking(self):
        self.next_id = 0
        self.frame_id = 0
        self.pose_results_last = []
        self.tracking_results = {
            "id": [],
            "frame_id": [],
            "bbox": [],
            "keypoints": [],
        }

    def xyxy_to_cxcys(self, bbox, s_factor=1.05):
        cx, cy = bbox[[0, 2]].mean(), bbox[[1, 3]].mean()
        scale = max(bbox[2] - bbox[0], bbox[3] - bbox[1]) / 200 * s_factor
        return np.array([[cx, cy, scale]], dtype=np.float32)

    def compute_bboxes_from_keypoints(self, s_factor=1.2):
        X = self.tracking_results["keypoints"].copy()
        mask = X[..., -1] > VIS_THRESH

        bbox = np.zeros((len(X), 3), dtype=np.float32)
        for i, (kp, m) in enumerate(zip(X, mask)):
            if m.sum() < MINIMUM_JOINTS:
                bbox[i] = self.tracking_results["bbox"][i]
                continue
            bb = [
                kp[m, 0].min(),
                kp[m, 1].min(),
                kp[m, 0].max(),
                kp[m, 1].max(),
            ]
            cx, cy = [(bb[2] + bb[0]) / 2, (bb[3] + bb[1]) / 2]
            bb_w = bb[2] - bb[0]
            bb_h = bb[3] - bb[1]
            bbox[i] = np.array((cx, cy, max(bb_w, bb_h)), dtype=np.float32)

        bbox[:, 2] = bbox[:, 2] * s_factor / 200.0
        self.tracking_results["bbox"] = bbox

    def _assign_track_id(self, bbox, used_last_ids):
        best_id = None
        best_iou = 0.0
        for previous in self.pose_results_last:
            if previous["id"] in used_last_ids:
                continue
            iou = _bbox_iou(bbox, previous["bbox"])
            if iou > best_iou:
                best_iou = iou
                best_id = previous["id"]
        if best_id is not None and best_iou >= self.cfg.tracking_thr:
            used_last_ids.add(best_id)
            return best_id

        track_id = self.next_id
        self.next_id += 1
        return track_id

    def track(self, img, fps, length):
        del fps, length

        detected = self.bbox_model.predict(
            img,
            device=self.device,
            classes=0,
            conf=self.cfg.bbox_conf,
            save=False,
            verbose=False,
        )[0]
        bboxes = detected.boxes.xyxy.detach().cpu().numpy().astype(np.float32)
        if len(bboxes) == 0:
            self.frame_id += 1
            self.pose_results_last = []
            return

        pose_results = inference_topdown(
            self.pose_model,
            img,
            bboxes=bboxes,
            bbox_format="xyxy",
        )

        current_results = []
        used_last_ids = set()
        for pose_index, pose_result in enumerate(pose_results):
            pred = pose_result.pred_instances
            bbox = _normalize_bbox(
                pred.bboxes if hasattr(pred, "bboxes") else bboxes[pose_index]
            )
            keypoints = _normalize_keypoints(pred.keypoints, pred.keypoint_scores)
            if (keypoints[:, -1] > VIS_THRESH).sum() < MINIMUM_JOINTS:
                continue

            track_id = self._assign_track_id(bbox, used_last_ids)
            self.tracking_results["id"].append(track_id)
            self.tracking_results["frame_id"].append(self.frame_id)
            self.tracking_results["bbox"].append(self.xyxy_to_cxcys(bbox)[0])
            self.tracking_results["keypoints"].append(keypoints)
            current_results.append({"id": track_id, "bbox": bbox})

        self.frame_id += 1
        self.pose_results_last = current_results

    def process(self, fps):
        if len(self.tracking_results["id"]) == 0:
            return defaultdict(lambda: defaultdict(list))

        for key in ["id", "frame_id", "bbox", "keypoints"]:
            self.tracking_results[key] = np.array(self.tracking_results[key])
        self.compute_bboxes_from_keypoints()

        output = defaultdict(lambda: defaultdict(list))
        ids = np.unique(self.tracking_results["id"])
        for track_id in ids:
            idxs = np.where(self.tracking_results["id"] == track_id)[0]
            for key, val in self.tracking_results.items():
                if key == "id":
                    continue
                output[track_id][key] = val[idxs]

        for track_id in list(output.keys()):
            if len(output[track_id]["bbox"]) < self.cfg.min_frames:
                del output[track_id]
                continue

            kernel = int(int(fps / 2) / 2) * 2 + 1
            smoothed_bbox = np.array(
                [signal.medfilt(param, kernel) for param in output[track_id]["bbox"].T]
            ).T
            output[track_id]["bbox"] = smoothed_bbox

        return output
