"""Matplotlib renderings for session analysis (Agg backend, files only)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Line3DCollection

PHASE_COLORS = {
    "concentric": "tab:blue",
    "eccentric": "tab:orange",
    "pause": "0.75",
}


def plot_trajectory_phases(
    position: np.ndarray,
    phase_per_sample: np.ndarray,
    out_path: Path,
    title: str,
) -> Path:
    """3D wrist path with line segments colored by exercise phase."""
    fig = plt.figure(figsize=(7, 6))
    axis = fig.add_subplot(projection="3d")
    if position.shape[0] > 1:
        segments = np.stack([position[:-1], position[1:]], axis=1)
        colors = [PHASE_COLORS.get(label, PHASE_COLORS["pause"]) for label in phase_per_sample[:-1]]
        axis.add_collection3d(Line3DCollection(segments, colors=colors, linewidths=1.5))
        _set_3d_limits(axis, position)
    axis.set_xlabel("X east (m)")
    axis.set_ylabel("Y north (m)")
    axis.set_zlabel("Z up (m)")
    axis.set_title(title)
    handles = [plt.Line2D([0], [0], color=color, lw=2, label=label) for label, color in PHASE_COLORS.items()]
    axis.legend(handles=handles, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_signal_overlays(
    times_s: np.ndarray,
    raw: np.ndarray,
    filtered: np.ndarray,
    rep_boundary_s: np.ndarray,
    out_path: Path,
    title: str,
) -> Path:
    """Raw vs bandpassed signal overlay with rep boundaries marked."""
    fig, axis = plt.subplots(figsize=(10, 4))
    axis.plot(times_s, raw, color="0.6", linewidth=0.8, label="raw")
    axis.plot(times_s, filtered, color="tab:blue", linewidth=1.2, label="bandpassed")
    for boundary in rep_boundary_s:
        axis.axvline(boundary, color="tab:red", linestyle=":", linewidth=0.8)
    axis.set_xlabel("time since set start (s)")
    axis.set_ylabel("signal")
    axis.set_title(title)
    axis.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def _set_3d_limits(axis: plt.Axes, position: np.ndarray) -> None:
    center = position.mean(axis=0)
    spread = max(float(np.abs(position - center).max()), 0.05)
    axis.set_xlim(center[0] - spread, center[0] + spread)
    axis.set_ylim(center[1] - spread, center[1] + spread)
    axis.set_zlim(center[2] - spread, center[2] + spread)
