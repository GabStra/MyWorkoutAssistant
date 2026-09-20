"""Material heel anchors shared by trajectory fitting and rig playback."""
from dataclasses import dataclass

import numpy as np

from .contact_constraints import (
    contact_frame_bounds, is_observed_ground_contact, is_stationary_contact,
    motion_support_contacts, stationary_target_track,
)
from .foot_kinematics import HEEL_BEHIND_ANKLE_RATIO


@dataclass
class HeelContacts:
    pairs: list[tuple[int, int]]
    active: np.ndarray
    targets: np.ndarray

    def positions(self, points):
        return np.stack([
            points[:, ankle] - HEEL_BEHIND_ANKLE_RATIO * (points[:, toe] - points[:, ankle])
            for ankle, toe in self.pairs
        ], axis=1) if self.pairs else np.empty((len(points), 0, 3))

    def residual(self, points, first=None, last=None):
        if first is None:
            targets, active = self.targets, self.active
        else:
            targets = self.targets[first]
            active = self.active[first] & self.active[last]
        return (self.positions(points) - targets) * active[:, :, None]


def heel_contact_tracks(points, names, evidence, *, floor=None, fps=30.):
    """Anchor the shoe's heel, preserving free rotation of its raised toe."""
    count = len(points)
    pairs, masks, targets = [], [], []
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
        heels = points[:, pair[0]] - HEEL_BEHIND_ANKLE_RATIO * (points[:, pair[1]] - points[:, pair[0]])
        track, _ = stationary_target_track(heels, mask, fps=fps, anchor_ids=identities)
        if floor is not None:
            track[ground, 1] = float(floor)
        pairs.append(pair)
        masks.append(mask)
        targets.append(track)
    return HeelContacts(pairs,
                        np.stack(masks, axis=1) if pairs else np.zeros((count, 0), dtype=bool),
                        np.stack(targets, axis=1) if pairs else np.empty((count, 0, 3)))
