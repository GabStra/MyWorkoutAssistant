"""Material heel anchors shared by trajectory fitting and rig playback."""
from dataclasses import dataclass, field

import numpy as np

from .contact_constraints import (
    contact_frame_bounds, is_observed_ground_contact, is_stationary_contact,
    motion_support_contacts, stationary_target_track,
)
from .foot_kinematics import HEEL_BEHIND_ANKLE_RATIO
from .foot_geometry import material_foot_points


def resolved_foot_side_axes(points, names, frames=None):
    """Resolve current renderer bone sides without inventing a global-up frame."""
    from .temporal_quality import rendered_leg_sides
    points = np.asarray(points, dtype=float)
    names = list(names)
    if frames is None:
        frames = [{'joints': dict(zip(names, row.tolist()))} for row in points]
    if len(frames) != len(points):
        raise ValueError('foot side-axis frames must match current points')
    rendered = rendered_leg_sides(frames)
    axes = {}
    for side in ('left', 'right'):
        key = f'{side}_ankle->{side}_foot'
        rows = []
        for index, frame in enumerate(frames):
            axis = (frame.get('boneSides') or {}).get(key)
            if axis is None:
                axis = rendered[index].get(key)
            if axis is None:
                raise ValueError(f'{side} pose-aware foot side axis is unavailable')
            rows.append(axis)
        value = np.asarray(rows, dtype=float)
        if value.shape != (len(points), 3) or not np.isfinite(value).all():
            raise ValueError(f'{side} pose-aware foot side axis is malformed')
        axes[side] = value
    return axes


@dataclass
class HeelContacts:
    pairs: list[tuple[int, int]]
    active: np.ndarray
    targets: np.ndarray
    rest_pitches: list[float | None] = field(default_factory=list)
    native_geometry: list[dict | None] = field(default_factory=list)
    side_axes: list[np.ndarray | None] = field(default_factory=list)

    def positions(self, points, side_axes=None):
        positions = []
        for index, (ankle, toe) in enumerate(self.pairs):
            pitch = self.rest_pitches[index] if index < len(self.rest_pitches) else None
            native = (self.native_geometry[index]
                      if index < len(self.native_geometry) else None)
            vector = points[:, toe] - points[:, ankle]
            if native is not None:
                source_axes = self.side_axes if side_axes is None else side_axes
                side_axis = (source_axes[index] if index < len(source_axes) else None)
                if side_axis is None:
                    raise ValueError('native heel contacts require pose-aware foot side axes')
                positions.append(material_foot_points(
                    points[:, ankle], points[:, toe], side_axis,
                    pitch, native_geometry=native)[0])
            elif pitch is None:
                positions.append(points[:, ankle] - HEEL_BEHIND_ANKLE_RATIO * vector)
            else:
                lateral = np.cross(vector, [0., 1., 0.])
                positions.append(material_foot_points(points[:, ankle], points[:, toe], lateral, pitch)[0])
        return np.stack(positions, axis=1) if positions else np.empty((len(points), 0, 3))

    def residual(self, points, first=None, last=None, *, side_axes=None):
        if first is None:
            targets, active = self.targets, self.active
        else:
            targets = self.targets[first]
            active = self.active[first] & self.active[last]
        return (self.positions(points, side_axes) - targets) * active[:, :, None]


def heel_contact_tracks(points, names, evidence, *, floor=None, fps=30., rest_pitches=None,
                        native_geometry=None, side_axes=None):
    """Anchor the shoe's heel, preserving free rotation of its raised toe."""
    count = len(points)
    pairs, masks, targets, pitches, native_sides, pose_axes = [], [], [], [], [], []
    from .native_foot_geometry import validated_native_foot_geometry
    native_value = (native_geometry.get('nativeFootGeometry')
                    if isinstance(native_geometry, dict)
                    and 'nativeFootGeometry' in native_geometry else native_geometry)
    native = validated_native_foot_geometry(native_value)
    contacts = motion_support_contacts(evidence)
    for side in ('left', 'right'):
        ankle, toe = f'{side}_ankle', f'{side}_foot'
        records = [c for c in contacts if c.get('jointName') in {ankle, toe}
                   and c.get('contactState') == 'heel_only' and is_stationary_contact(c)]
        if not records or ankle not in names or toe not in names:
            continue
        pair = names.index(ankle), names.index(toe)
        mask, ground = np.zeros(count, dtype=bool), np.zeros(count, dtype=bool)
        identities = np.full(count, None, dtype=object)
        for record in records:
            start, end = contact_frame_bounds(record, count)
            mask[start:end+1] = True
            identities[start:end+1] = record.get('anchorGroupId')
            if is_observed_ground_contact(record, evidence):
                ground[start:end+1] = True
        pitch = (rest_pitches or {}).get(side)
        native_side = native['sides'][side] if native is not None else None
        lateral = (side_axes or {}).get(side) if isinstance(side_axes, dict) else None
        if native_side is not None:
            lateral = np.asarray(lateral, dtype=float) if lateral is not None else None
            if lateral is None or lateral.shape != (count, 3) or not np.isfinite(lateral).all():
                raise ValueError(f'{side} native heel contact needs finite pose-aware side axes')
        temporary = HeelContacts([pair], mask[:, None], np.empty((count, 1, 3)), [pitch],
                                 [native_side], [lateral])
        heels = temporary.positions(points)[:, 0]
        track, _ = stationary_target_track(heels, mask, fps=fps, anchor_ids=identities)
        if floor is not None:
            track[ground, 1] = float(floor)
        pairs.append(pair)
        pitches.append(pitch)
        native_sides.append(native_side)
        pose_axes.append(lateral)
        masks.append(mask)
        targets.append(track)
    return HeelContacts(pairs,
                        np.stack(masks, axis=1) if pairs else np.zeros((count, 0), dtype=bool),
                        np.stack(targets, axis=1) if pairs else np.empty((count, 0, 3)), pitches,
                        native_sides, pose_axes)
