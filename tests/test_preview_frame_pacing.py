import json
from pathlib import Path
import shutil
import subprocess

import pytest


def run_schedule(tmp_path, timestamps, cap):
    node = shutil.which('node')
    if not node:
        pytest.skip('JavaScript frame pacing regression requires Node')
    source = (Path(__file__).resolve().parents[1] / 'exercise_motion_pkg/preview.py').read_text(encoding='utf-8')
    kernel = source[source.index('    function previewDrawSchedule('):source.index('    function animate(timestamp)')]
    kernel = kernel.replace('{{', '{').replace('}}', '}')
    script = tmp_path / 'pacing.js'
    script.write_text(kernel + '''
const [timestamps, cap] = JSON.parse(process.argv[2]);
let clock = null;
const draws = [];
for (const timestamp of timestamps) {
  const schedule = previewDrawSchedule(timestamp, clock, 1000 / cap);
  if (schedule.due) { draws.push(timestamp); clock = schedule.clock; }
}
console.log(JSON.stringify(draws));
''', encoding='utf-8')
    return json.loads(subprocess.check_output([node, str(script), json.dumps([timestamps, cap])], text=True, timeout=15))


@pytest.mark.parametrize('cap,stride', [(60, 1), (30, 2)])
def test_rounded_raf_timestamps_keep_even_cadence(tmp_path, cap, stride):
    timestamps = [round(i * 1000 / 60, 1) for i in range(600)]
    draws = run_schedule(tmp_path, timestamps, cap)
    assert draws == timestamps[::stride]


def test_high_refresh_display_respects_cap(tmp_path):
    timestamps = [round(i * 1000 / 120, 1) for i in range(600)]
    assert run_schedule(tmp_path, timestamps, 60) == timestamps[::2]


def test_resume_after_gap_does_not_accumulate_catchup_frames(tmp_path):
    timestamps = [0., 16.7, 33.3, 5040., 5041., 5050., 5066.7]
    assert run_schedule(tmp_path, timestamps, 60) == [0., 16.7, 33.3, 5040., 5050., 5066.7]
