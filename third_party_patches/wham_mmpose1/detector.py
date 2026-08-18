from __future__ import annotations

import os
import os.path as osp
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import scipy.signal as signal
import torch
from mmengine.dataset import Compose, pseudo_collate
from mmengine.registry import init_default_scope

from ultralytics import YOLO
from mmpose.apis import init_model


ROOT_DIR = osp.abspath(f"{__file__}/../../../../")

VIS_THRESH = float(os.environ.get("WHAM_KEYPOINT_VIS_THRESH", "0.3"))
BBOX_CONF = float(os.environ.get("WHAM_BBOX_CONF", "0.5"))
TRACKING_THR = float(os.environ.get("WHAM_TRACKING_THR", "0.1"))
MINIMUM_FRAMES = int(os.environ.get("WHAM_MINIMUM_TRACK_FRAMES", "30"))
MINIMUM_JOINTS = int(os.environ.get("WHAM_MINIMUM_JOINTS", "6"))
MAX_TRACK_GAP_FRAMES = max(0, int(os.environ.get("WHAM_MAX_TRACK_GAP_FRAMES", "3")))
POSE_BATCH_SIZE = max(1, int(os.environ.get("WHAM_POSE_BATCH_SIZE", "16")))
DUPLICATE_BBOX_IOU_THRESHOLD = float(
    os.environ.get("WHAM_DUPLICATE_BBOX_IOU_THRESHOLD", "0.9")
)
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
DEFAULT_YOLO_POSE_MODEL = osp.join(ROOT_DIR, "checkpoints", "yolo26x-pose.pt")
DEFAULT_POSE_BACKEND = "vitpose"


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
    pose_backend = os.environ.get("WHAM_POSE_BACKEND", DEFAULT_POSE_BACKEND).strip().lower()
    if pose_backend not in {"vitpose", "yolo_pose"}:
        raise ValueError(
            "WHAM_POSE_BACKEND must be either 'vitpose' or 'yolo_pose'."
        )
    return SimpleNamespace(
        pose_backend=pose_backend,
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
        yolo_pose_model=os.environ.get(
            "WHAM_YOLO_POSE_MODEL",
            DEFAULT_YOLO_POSE_MODEL,
        ),
        bbox_conf=float(_cfg_value(mmpose_cfg, "BBOX_CONF", BBOX_CONF)),
        tracking_thr=float(_cfg_value(mmpose_cfg, "TRACKING_THR", TRACKING_THR)),
        min_frames=int(_cfg_value(mmpose_cfg, "MINIMUM_FRAMES", MINIMUM_FRAMES)),
        max_track_gap_frames=MAX_TRACK_GAP_FRAMES,
        pose_batch_size=POSE_BATCH_SIZE,
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


def _deduplicate_overlapping_bboxes(bboxes, scores, iou_threshold):
    """Keep the highest-confidence box for effectively identical detections."""
    bboxes = np.asarray(bboxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    if len(bboxes) <= 1:
        return bboxes

    kept_indices = []
    for index in np.argsort(-scores):
        if all(
            _bbox_iou(bboxes[index], bboxes[kept_index]) < iou_threshold
            for kept_index in kept_indices
        ):
            kept_indices.append(int(index))
    return bboxes[kept_indices]


def _deduplicate_overlapping_detection_indices(bboxes, scores, iou_threshold):
    bboxes = np.asarray(bboxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    kept_indices = []
    for index in np.argsort(-scores):
        if all(
            _bbox_iou(bboxes[index], bboxes[kept_index]) < iou_threshold
            for kept_index in kept_indices
        ):
            kept_indices.append(int(index))
    return kept_indices


def _interpolate_short_track_gaps(track, max_gap_frames):
    frame_ids = np.asarray(track["frame_id"], dtype=np.int64)
    if len(frame_ids) <= 1 or max_gap_frames <= 0:
        return track

    bboxes = np.asarray(track["bbox"], dtype=np.float32)
    keypoints = np.asarray(track["keypoints"], dtype=np.float32)
    output_frame_ids = []
    output_bboxes = []
    output_keypoints = []
    for index in range(len(frame_ids) - 1):
        output_frame_ids.append(frame_ids[index])
        output_bboxes.append(bboxes[index])
        output_keypoints.append(keypoints[index])
        missing_count = int(frame_ids[index + 1] - frame_ids[index] - 1)
        if missing_count <= 0 or missing_count > max_gap_frames:
            continue
        for offset in range(1, missing_count + 1):
            alpha = offset / float(missing_count + 1)
            output_frame_ids.append(frame_ids[index] + offset)
            output_bboxes.append((1.0 - alpha) * bboxes[index] + alpha * bboxes[index + 1])
            output_keypoints.append(
                (1.0 - alpha) * keypoints[index] + alpha * keypoints[index + 1]
            )

    output_frame_ids.append(frame_ids[-1])
    output_bboxes.append(bboxes[-1])
    output_keypoints.append(keypoints[-1])
    track["frame_id"] = np.asarray(output_frame_ids, dtype=np.int64)
    track["bbox"] = np.asarray(output_bboxes, dtype=np.float32)
    track["keypoints"] = np.asarray(output_keypoints, dtype=np.float32)
    return track


class DetectionModel(object):
    def __init__(self, device, mmpose_cfg=None):
        self.cfg = _runtime_cfg(mmpose_cfg)
        if self.cfg.pose_backend == "yolo_pose":
            self.pose_model = YOLO(self.cfg.yolo_pose_model)
            self.bbox_model = None
            self.pose_pipeline = None
        else:
            self.pose_model = _init_trusted_mmpose_model(
                self.cfg.pose_config,
                self.cfg.pose_checkpoint,
                device=device.lower(),
            )
            self.bbox_model = YOLO(self.cfg.bbox_model)
            scope = self.pose_model.cfg.get("default_scope", "mmpose")
            if scope is not None:
                init_default_scope(scope)
            self.pose_pipeline = Compose(
                self.pose_model.cfg.test_dataloader.dataset.pipeline
            )
        self.device = device
        self.initialize_tracking()

    def initialize_tracking(self):
        self.next_id = 0
        self.frame_id = 0
        self.pose_results_last = []
        self.missed_tracking_frames = 0
        self.pending_vitpose_frames = []
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

    def _record_missing_tracking_frame(self):
        self.missed_tracking_frames += 1
        if self.missed_tracking_frames > self.cfg.max_track_gap_frames:
            self.pose_results_last = []

    def _record_current_tracking_results(self, current_results):
        if current_results:
            self.pose_results_last = current_results
            self.missed_tracking_frames = 0
        else:
            self._record_missing_tracking_frame()

    def track(self, img, fps, length):
        del fps, length

        if self.cfg.pose_backend == "yolo_pose":
            self._track_with_yolo_pose(img)
            return

        detected = self.bbox_model.predict(
            img,
            device=self.device,
            classes=0,
            conf=self.cfg.bbox_conf,
            save=False,
            verbose=False,
        )[0]
        bboxes = detected.boxes.xyxy.detach().cpu().numpy().astype(np.float32)
        scores = detected.boxes.conf.detach().cpu().numpy().astype(np.float32)
        bboxes = _deduplicate_overlapping_bboxes(
            bboxes,
            scores,
            DUPLICATE_BBOX_IOU_THRESHOLD,
        )
        self.pending_vitpose_frames.append(
            {
                "frame_id": self.frame_id,
                "image": img.copy() if len(bboxes) > 0 else None,
                "bboxes": bboxes,
            }
        )
        self.frame_id += 1

    def _materialize_pending_vitpose_frames(self):
        if not self.pending_vitpose_frames:
            return

        pose_inputs = []
        pose_input_locations = []
        results_by_frame = defaultdict(list)
        for frame_index, pending_frame in enumerate(self.pending_vitpose_frames):
            image = pending_frame["image"]
            for bbox in pending_frame["bboxes"]:
                data_info = {
                    "img": image,
                    "bbox": np.asarray(bbox, dtype=np.float32)[None],
                    "bbox_score": np.ones(1, dtype=np.float32),
                }
                data_info.update(self.pose_model.dataset_meta)
                pose_inputs.append(self.pose_pipeline(data_info))
                pose_input_locations.append((frame_index, bbox))

        pose_results = self._run_vitpose_batches(pose_inputs)
        for (frame_index, fallback_bbox), pose_result in zip(
            pose_input_locations,
            pose_results,
        ):
            pred = pose_result.pred_instances
            bbox = _normalize_bbox(
                pred.bboxes if hasattr(pred, "bboxes") else fallback_bbox
            )
            keypoints = _normalize_keypoints(pred.keypoints, pred.keypoint_scores)
            if (keypoints[:, -1] > VIS_THRESH).sum() < MINIMUM_JOINTS:
                continue
            results_by_frame[frame_index].append((bbox, keypoints))

        for frame_index, pending_frame in enumerate(self.pending_vitpose_frames):
            current_results = []
            used_last_ids = set()
            for bbox, keypoints in results_by_frame[frame_index]:
                track_id = self._assign_track_id(bbox, used_last_ids)
                self.tracking_results["id"].append(track_id)
                self.tracking_results["frame_id"].append(pending_frame["frame_id"])
                self.tracking_results["bbox"].append(self.xyxy_to_cxcys(bbox)[0])
                self.tracking_results["keypoints"].append(keypoints)
                current_results.append({"id": track_id, "bbox": bbox})
            self._record_current_tracking_results(current_results)

        self.pending_vitpose_frames = []

    def _run_vitpose_batches(self, data_list):
        if not data_list:
            return []
        results = []
        batch_size = min(self.cfg.pose_batch_size, len(data_list))
        offset = 0
        while offset < len(data_list):
            current_batch_size = min(batch_size, len(data_list) - offset)
            batch_data = data_list[offset : offset + current_batch_size]
            try:
                with torch.inference_mode():
                    batch_results = self.pose_model.test_step(
                        pseudo_collate(batch_data)
                    )
            except torch.cuda.OutOfMemoryError:
                if current_batch_size <= 1:
                    raise
                torch.cuda.empty_cache()
                batch_size = max(1, current_batch_size // 2)
                continue
            results.extend(batch_results)
            offset += current_batch_size
        return results

    def _track_with_yolo_pose(self, img):
        detected = self.pose_model.predict(
            img,
            device=self.device,
            classes=0,
            conf=self.cfg.bbox_conf,
            save=False,
            verbose=False,
        )[0]
        if detected.boxes is None or detected.keypoints is None:
            self.frame_id += 1
            self._record_missing_tracking_frame()
            return

        bboxes = detected.boxes.xyxy.detach().cpu().numpy().astype(np.float32)
        scores = detected.boxes.conf.detach().cpu().numpy().astype(np.float32)
        keypoint_xy = detected.keypoints.xy.detach().cpu().numpy().astype(np.float32)
        keypoint_conf_tensor = detected.keypoints.conf
        keypoint_confidence = (
            keypoint_conf_tensor.detach().cpu().numpy().astype(np.float32)
            if keypoint_conf_tensor is not None
            else np.ones(keypoint_xy.shape[:2], dtype=np.float32)
        )
        if len(bboxes) == 0:
            self.frame_id += 1
            self._record_missing_tracking_frame()
            return

        kept_indices = _deduplicate_overlapping_detection_indices(
            bboxes,
            scores,
            DUPLICATE_BBOX_IOU_THRESHOLD,
        )
        current_results = []
        used_last_ids = set()
        for detection_index in kept_indices:
            bbox = bboxes[detection_index]
            keypoints = _normalize_keypoints(
                keypoint_xy[detection_index],
                keypoint_confidence[detection_index],
            )
            if (keypoints[:, -1] > VIS_THRESH).sum() < MINIMUM_JOINTS:
                continue

            track_id = self._assign_track_id(bbox, used_last_ids)
            self.tracking_results["id"].append(track_id)
            self.tracking_results["frame_id"].append(self.frame_id)
            self.tracking_results["bbox"].append(self.xyxy_to_cxcys(bbox)[0])
            self.tracking_results["keypoints"].append(keypoints)
            current_results.append({"id": track_id, "bbox": bbox})

        self.frame_id += 1
        self._record_current_tracking_results(current_results)

    def process(self, fps):
        if self.cfg.pose_backend == "vitpose":
            self._materialize_pending_vitpose_frames()
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
            output[track_id] = _interpolate_short_track_gaps(
                output[track_id],
                self.cfg.max_track_gap_frames,
            )
            if len(output[track_id]["bbox"]) < self.cfg.min_frames:
                del output[track_id]
                continue

            kernel = int(int(fps / 2) / 2) * 2 + 1
            smoothed_bbox = np.array(
                [signal.medfilt(param, kernel) for param in output[track_id]["bbox"].T]
            ).T
            output[track_id]["bbox"] = smoothed_bbox

        return output
