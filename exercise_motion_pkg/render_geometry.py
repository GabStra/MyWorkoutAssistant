from __future__ import annotations


UNIFORM_CAPSULE_RADIUS = 0.046


def support_surface_height(joint_height: float) -> float:
    """Return the lowest rendered surface for a support joint on a Y-up plane."""
    return float(joint_height) - UNIFORM_CAPSULE_RADIUS


def support_joint_height_for_surface(surface_height: float) -> float:
    return float(surface_height) + UNIFORM_CAPSULE_RADIUS
