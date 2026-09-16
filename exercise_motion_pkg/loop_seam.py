"""Shared geometric seam quantities for cyclic fitting and playback checks."""
import numpy as np


# ~0.4% of leg length (~3–4 mm). Tighter 0.1% rejected otherwise-valid wraps
# with sub-centimeter hitch that boundary nudging or mild residual still fix.
MAX_STEP_EXCESS_BODY_RATIO = .004
MAX_VELOCITY_MISMATCH_BODY_RATIO = .25


def seam_errors(points):
    """The last and first poses are adjacent samples, not duplicate endpoints."""
    step = points[0] - points[-1]
    incoming, outgoing = points[-1] - points[-2], points[1] - points[0]
    neighboring = np.maximum(np.linalg.norm(incoming, axis=-1), np.linalg.norm(outgoing, axis=-1))
    excess = np.maximum(np.linalg.norm(step, axis=-1) - 1.25 * neighboring, 0.)
    return step, excess, np.stack((step - incoming, outgoing - step))
