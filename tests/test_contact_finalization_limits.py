import json
from pathlib import Path

import numpy as np

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.anatomical_repair import repair_residuals


def test_playback_passing_isolated_keyframe_contact_still_gets_strict_projection():
    fixture = json.loads((Path(__file__).parent / 'fixtures' / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    source = np.tile(np.asarray([fixture['joints'][name] for name in names]), (8, 1, 1))
    rig = motion.FixedRig(source, names)
    targets = rig.decode(rig.initial)
    pinned = np.zeros(source.shape[:2], dtype=bool)
    pinned[3, names.index('left_foot')] = True
    coordinates = rig.initial.copy()
    coordinates[3, 0] += .0007

    before = rig.decode(coordinates)
    assert motion._playback_contact_sample_error(coordinates, rig, pinned, targets) < .003
    assert not motion._playback_failing_intervals(coordinates, rig, pinned, targets)
    assert np.max(np.linalg.norm((before - targets)[pinned], axis=-1)) >= .0005

    projected = motion.project_interval_playback_plants(coordinates, rig, pinned, targets)
    result = rig.decode(projected)

    assert np.max(np.linalg.norm((result - targets)[pinned], axis=-1)) < .0005
    assert motion._playback_contact_sample_error(projected, rig, pinned, targets) < .003
    assert np.max(np.abs(np.diff(np.linalg.norm(
        result[:, 1:] - result[:, np.asarray(rig.parents[1:])], axis=-1), axis=0))) < 1e-12
    before_jerk = np.sqrt(np.mean(np.diff(before, n=3, axis=0) ** 2))
    after_jerk = np.sqrt(np.mean(np.diff(result, n=3, axis=0) ** 2))
    assert after_jerk <= before_jerk + 1e-12
    before_anatomy, _ = repair_residuals(before, names, reference=source)
    after_anatomy, _ = repair_residuals(result, names, reference=source)
    assert np.max(after_anatomy) <= np.max(before_anatomy) + 1e-9
    assert motion.source_knee_envelope_metrics(source, result, names)['passed']
