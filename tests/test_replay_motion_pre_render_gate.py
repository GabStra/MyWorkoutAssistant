import json
from pathlib import Path

import pytest

from scripts.replay_motion_pre_render_gate import validate_motion_payload


def test_pre_render_replay_rejects_report_wrapper_as_motion(tmp_path):
    report_path = tmp_path / "previous-replay.json"
    report_path.write_text(json.dumps({"payload": "motion.json", "gate": {"passed": True}}))

    with pytest.raises(ValueError, match="at least two frames"):
        validate_motion_payload(json.loads(report_path.read_text()), report_path)


def test_pre_render_replay_accepts_saved_motion_payload():
    fixture_path = Path(__file__).parent / "fixtures/dumbbell-thruster-renderer.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    validate_motion_payload(payload, fixture_path)
