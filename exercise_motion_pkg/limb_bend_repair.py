"""Repair short isolated hinge-plane flips while preserving limb endpoints."""
from __future__ import annotations

from dataclasses import replace
import math

import numpy as np

from .models import MotionClip, MotionFrame


def repair_limb_bend_bursts(clip: MotionClip, *, maximum_burst_seconds: float = .12) -> tuple[MotionClip, dict]:
    from .structural_refinement import _body_local_frame, _fixed_endpoint_bend

    if not math.isfinite(maximum_burst_seconds) or maximum_burst_seconds <= 0:
        raise ValueError("Maximum burst duration must be positive and finite")
    if (clip.frame_count < 7 or not math.isfinite(clip.fps) or clip.fps <= 0
            or any(not math.isfinite(frame.time_sec) for frame in clip.frames)
            or any(after.time_sec <= before.time_sec for before, after in zip(clip.frames, clip.frames[1:]))):
        return clip, {"applied": False, "events": []}
    frames = [MotionFrame(frame.time_sec, dict(frame.joints)) for frame in clip.frames]
    bases = []
    for frame in clip.frames:
        body = _body_local_frame(frame)
        bases.append(np.column_stack((body.right, body.up, body.forward)) if body is not None else np.eye(3))
    events = []
    max_frames = max(1, math.floor(clip.fps * maximum_burst_seconds))

    def angle(left, right):
        return math.degrees(math.acos(float(np.clip(np.dot(left, right), -1., 1.))))

    for side in ("left", "right"):
        for suffixes in (("shoulder", "elbow", "wrist"), ("hip", "knee", "ankle")):
            root, mid, end = [f"{side}_{name}" for name in suffixes]
            if any(name not in frame.joints for frame in clip.frames for name in (root, mid, end)):
                continue
            directions = []
            for index, frame in enumerate(clip.frames):
                start, hinge, finish = [np.asarray(frame.joints[name], dtype=float) for name in (root, mid, end)]
                axis = finish - start
                reach = np.linalg.norm(axis)
                if reach < 1e-8:
                    directions.append(None)
                    continue
                axis /= reach
                bend = hinge - start
                bend -= axis * np.dot(bend, axis)
                height = np.linalg.norm(bend)
                upper = np.linalg.norm(hinge - start)
                # Near extension the bend plane is unobservable. Do not bridge it.
                directions.append(bases[index].T @ (bend / height) if height > .08 * upper and height > 1e-8 else None)
            index = 2
            while index < len(frames) - 3:
                repaired = False
                for length in range(1, max_frames + 1):
                    finish_index = index + length
                    if finish_index + 1 >= len(frames):
                        break
                    window = directions[index - 2:finish_index + 2]
                    if any(value is None for value in window):
                        continue
                    times = [frame.time_sec for frame in clip.frames[index - 2:finish_index + 2]]
                    if any(after - before > 2. / clip.fps for before, after in zip(times, times[1:])):
                        continue
                    left, right = directions[index - 1], directions[finish_index]
                    if (angle(left, right) > 20. or angle(directions[index - 2], left) > 20.
                            or angle(right, directions[finish_index + 1]) > 20.):
                        continue
                    duration = clip.frames[finish_index].time_sec - clip.frames[index].time_sec
                    if duration <= 0 or duration > maximum_burst_seconds + 1e-9:
                        continue
                    if any(angle(left, value) < 70. or angle(right, value) < 70.
                           for value in directions[index:finish_index]):
                        continue
                    candidates = []
                    total_time = clip.frames[finish_index].time_sec - clip.frames[index - 1].time_sec
                    for position in range(index, finish_index):
                        frame = clip.frames[position]
                        alpha = (frame.time_sec - clip.frames[index - 1].time_sec) / total_time
                        direction = bases[position] @ ((1. - alpha) * left + alpha * right)
                        start = np.asarray(frame.joints[root])
                        hinge = np.asarray(frame.joints[mid])
                        endpoint = np.asarray(frame.joints[end])
                        candidate = _fixed_endpoint_bend(
                            tuple(start), tuple(endpoint), tuple(start + direction),
                            upper=float(np.linalg.norm(hinge - start)), lower=float(np.linalg.norm(endpoint - hinge)),
                        )
                        if candidate is None:
                            break
                        candidates.append(candidate)
                    if len(candidates) != length:
                        continue
                    for position, candidate in zip(range(index, finish_index), candidates):
                        frames[position].joints[mid] = candidate
                    events.append({"joint": mid, "startFrame": index, "endFrame": finish_index - 1,
                                   "durationSeconds": duration, "maximumDeviationDegrees": max(
                                       angle(left, value) for value in directions[index:finish_index])})
                    index = finish_index + 2
                    repaired = True
                    break
                if not repaired:
                    index += 1
    return (replace(clip, frames=frames) if events else clip), {
        "applied": bool(events), "strategy": "isolated_bend_plane_interpolation_with_fixed_endpoints",
        "events": events, "maximumBurstSeconds": maximum_burst_seconds,
    }
