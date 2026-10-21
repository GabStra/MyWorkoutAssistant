import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workout_generator_synthetic_architecture_e2e as harness


def test_exported_workout_timing_may_improve_but_not_exceed_reviewed_envelope():
    reviewed = [{'exerciseId': 'EXERCISE_0', 'timing': {'workSeconds': 300, 'restSeconds': 600},
        'estimatedSeconds': 1200, 'workingSets': 4, 'volume': {'chest': 4}}]
    realized = [{'exerciseId': 'uuid-0', 'timing': {'workSeconds': 240, 'restSeconds': 600},
        'estimatedSeconds': 1140, 'workingSets': 4, 'volume': {'chest': 4}}]

    assert harness._workout_audit_within_reviewed_envelope(realized, reviewed)
    realized[0]['timing']['workSeconds'] = 301
    assert not harness._workout_audit_within_reviewed_envelope(realized, reviewed)
