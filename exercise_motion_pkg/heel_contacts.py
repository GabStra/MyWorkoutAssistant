"""Material heel anchors shared by trajectory fitting and rig playback."""
from dataclasses import dataclass, field

import numpy as np

from .contact_constraints import (
    contact_frame_bounds, is_observed_ground_contact, is_stationary_contact,
    motion_support_contacts, stationary_target_track,
)
from .foot_kinematics import HEEL_BEHIND_ANKLE_RATIO
from .foot_geometry import material_foot_points


@dataclass
class HeelContacts:
    pairs: list[tuple[int, int]]
    active: np.ndarray
    targets: np.ndarray
    rest_pitches: list[float | None] = field(default_factory=list)

    def positions(self, points):
        positions = []
        for index, (ankle, toe) in enumerate(self.pairs):
            pitch = self.rest_pitches[index] if index < len(self.rest_pitches) else None
            vector = points[:, toe] - points[:, ankle]
            if pitch is None:
                positions.append(points[:, ankle] - HEEL_BEHIND_ANKLE_RATIO * vector)
            else:
                lateral = np.cross(vector, [0., 1., 0.])
                positions.append(material_foot_points(points[:, ankle], points[:, toe], lateral, pitch)[0])
        return np.stack(positions, axis=1) if positions else np.empty((len(points), 0, 3))

    def residual(self, points, first=None, last=None):
        if first is None:
            targets, active = self.targets, self.active
        else:
            targets = self.targets[first]
            active = self.active[first] & self.active[last]
        return (self.positions(points) - targets) * active[:, :, None]


def heel_contact_tracks(points, names, evidence, *, floor=None, fps=30., rest_pitches=None):
    """Anchor the shoe's heel, preserving free rotation of its raised toe."""
    count = len(points)
    pairs, masks, targets, pitches = [], [], [], []
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
        temporary = HeelContacts([pair], mask[:, None], np.empty((count, 1, 3)), [pitch])
        heels = temporary.positions(points)[:, 0]
        track, _ = stationary_target_track(heels, mask, fps=fps, anchor_ids=identities)
        if floor is not None:
            track[ground, 1] = float(floor)
        pairs.append(pair)
        pitches.append(pitch)
        masks.append(mask)
        targets.append(track)
    return HeelContacts(pairs,
                        np.stack(masks, axis=1) if pairs else np.zeros((count, 0), dtype=bool),
                        np.stack(targets, axis=1) if pairs else np.empty((count, 0, 3)), pitches)
