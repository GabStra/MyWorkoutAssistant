from __future__ import annotations

import os
import os.path as osp
from collections import defaultdict

import cv2
import numpy as np
import torch
from progress.bar import Bar

from configs import constants as _C
from .backbone.hmr2 import hmr2
from .backbone.utils import process_image
from ...utils.imutils import flip_kp, flip_bbox


ROOT_DIR = osp.abspath(f"{__file__}/../../../../")
DEFAULT_FEATURE_BATCH_SIZE = max(1, int(os.environ.get("WHAM_FEATURE_BATCH_SIZE", "32")))

if torch.cuda.is_available():
    torch.set_float32_matmul_precision("high")
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True


class FeatureExtractor(object):
    def __init__(self, device, flip_eval=False, max_batch_size=DEFAULT_FEATURE_BATCH_SIZE):
        self.device = device
        self.flip_eval = flip_eval
        self.max_batch_size = max(1, int(max_batch_size))

        ckpt = osp.join(ROOT_DIR, "checkpoints", "hmr2a.ckpt")
        self.model = hmr2(ckpt).to(device).eval()

    def run(self, video, tracking_results, patch_h=256, patch_w=256):
        if osp.isfile(video):
            cap = cv2.VideoCapture(video)
            is_video = True
            length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        else:
            cap = video
            is_video = False
            length = len(video)
            height, width = cv2.imread(video[0]).shape[:2]

        pending = []
        frame_id = 0
        bar = Bar("Feature extraction ...", fill="#", max=length)
        while True:
            if is_video:
                flag, img = cap.read()
                if not flag:
                    break
            else:
                if frame_id >= len(cap):
                    break
                img = cv2.imread(cap[frame_id])

            for subject_id, values in tracking_results.items():
                matching_frames = np.where(values["frame_id"] == frame_id)[0]
                if len(matching_frames) == 0:
                    continue
                subject_frame_id = int(matching_frames[0])
                bbox = values["bbox"][subject_frame_id]
                cx, cy, scale = bbox
                norm_img, _crop_img = process_image(
                    img[..., ::-1],
                    [cx, cy],
                    scale,
                    patch_h,
                    patch_w,
                )
                norm_tensor = torch.from_numpy(norm_img).unsqueeze(0)
                pending.append((subject_id, subject_frame_id, bbox, norm_tensor))

                if subject_frame_id == 0:
                    self.predict_init(norm_tensor.to(self.device), tracking_results, subject_id, flip_eval=False)
                    if self.flip_eval:
                        self.predict_init(
                            torch.flip(norm_tensor, (3,)).to(self.device),
                            tracking_results,
                            subject_id,
                            flip_eval=True,
                        )

                if len(pending) >= self.max_batch_size:
                    self._extract_pending(pending, tracking_results, width, height)
                    pending.clear()

            bar.next()
            frame_id += 1

        if pending:
            self._extract_pending(pending, tracking_results, width, height)
        if is_video:
            cap.release()
        return self.process(tracking_results)

    def _extract_pending(self, pending, tracking_results, width, height):
        batch = None
        try:
            batch = torch.cat([item[3] for item in pending], dim=0).to(self.device)
            features = self.model(batch, encode=True).cpu()
            flipped_features = None
            if self.flip_eval:
                flipped_features = self.model(torch.flip(batch, (3,)), encode=True).cpu()
        except torch.cuda.OutOfMemoryError:
            if len(pending) == 1:
                raise
            if batch is not None:
                del batch
            torch.cuda.empty_cache()
            midpoint = len(pending) // 2
            self._extract_pending(pending[:midpoint], tracking_results, width, height)
            self._extract_pending(pending[midpoint:], tracking_results, width, height)
            return

        for batch_index, (subject_id, _subject_frame_id, bbox, _tensor) in enumerate(pending):
            tracking_results[subject_id]["features"].append(features[batch_index : batch_index + 1])
            if flipped_features is not None:
                tracking_results[subject_id]["flipped_bbox"].append(flip_bbox(bbox, width, height))
                tracking_results[subject_id]["flipped_keypoints"].append(
                    flip_kp(
                        tracking_results[subject_id]["keypoints"][_subject_frame_id],
                        width,
                    )
                )
                tracking_results[subject_id]["flipped_features"].append(
                    flipped_features[batch_index : batch_index + 1]
                )

    def predict_init(self, norm_img, tracking_results, subject_id, flip_eval=False):
        prefix = "flipped_" if flip_eval else ""
        pred_global_orient, pred_body_pose, pred_betas, _ = self.model(norm_img, encode=False)
        tracking_results[subject_id][prefix + "init_global_orient"] = pred_global_orient.cpu()
        tracking_results[subject_id][prefix + "init_body_pose"] = pred_body_pose.cpu()
        tracking_results[subject_id][prefix + "init_betas"] = pred_betas.cpu()
        return tracking_results

    def process(self, tracking_results):
        output = defaultdict(dict)
        for subject_id, results in tracking_results.items():
            for key, value in results.items():
                if isinstance(value, list):
                    if isinstance(value[0], torch.Tensor):
                        value = torch.cat(value)
                    elif isinstance(value[0], np.ndarray):
                        value = np.array(value)
                output[subject_id][key] = value
        return output
