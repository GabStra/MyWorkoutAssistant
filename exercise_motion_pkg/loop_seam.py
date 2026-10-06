"""Shared geometric seam quantities for cyclic fitting and playback checks."""
import numpy as np


# ~0.4% of leg length (~3–4 mm). Tighter 0.1% rejected otherwise-valid wraps
# with sub-centimeter hitch that boundary nudging or mild residual still fix.
MAX_STEP_EXCESS_BODY_RATIO = .004
MAX_VELOCITY_MISMATCH_BODY_RATIO = .25
# Reject source wraps that cannot become a continuous loop even with Stage-B.
# Stage-B's near-miss bound (~2×) is tighter and only decides whether to polish
# vs try another cycle after a fit; ranking must still surface complete returns
# whose raw support wrap is a few× over limit (often closed by boundary repair).
MAX_RANKED_SOURCE_WRAP_RATIO = 8.0


def seam_errors(points):
    """The last and first poses are adjacent samples, not duplicate endpoints."""
    step = points[0] - points[-1]
    incoming, outgoing = points[-1] - points[-2], points[1] - points[0]
    neighboring = np.maximum(np.linalg.norm(incoming, axis=-1), np.linalg.norm(outgoing, axis=-1))
    excess = np.maximum(np.linalg.norm(step, axis=-1) - 1.25 * neighboring, 0.)
    return step, excess, np.stack((step - incoming, outgoing - step))


def seam_quality_metrics(points, *, fps, scale):
    """Shared stored-sample restart limits for fitting and final playback."""
    step, excess, increments = seam_errors(points)
    step_excess = float(np.max(excess))
    velocity = float(np.max(np.linalg.norm(increments, axis=-1))) * fps
    step_limit = MAX_STEP_EXCESS_BODY_RATIO * scale
    velocity_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * scale
    return {
        'seamPositionJumpMeters': float(np.max(np.linalg.norm(step, axis=-1))),
        'seamStepExcessMeters': step_excess,
        'seamStepExcessLimitMeters': float(step_limit),
        'seamVelocityMismatchMetersPerSecond': velocity,
        'seamVelocityMismatchLimitMetersPerSecond': float(velocity_limit),
        'seamContinuous': bool(step_excess < step_limit and velocity < velocity_limit),
    }
