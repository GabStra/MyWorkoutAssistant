import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("reason,remaining,expected", [
    ("scheduler_yield", 270, True),
    ("time_budget_exhausted", 0, False),
    ("scheduler_yield", 0, False),
    ("candidate_budget_exhausted", 270, False),
])
def test_scheduler_resumes_only_yielded_work_with_remaining_allowance(tmp_path, reason, remaining, expected):
    shell = shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell required")
    source = (Path(__file__).resolve().parents[1] / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8-sig")
    function = source.split("function Resume-YieldedDiscovery {", 1)[1].split("function Start-InitialDiscoveryJob", 1)[0]
    (tmp_path / "candidates.json").write_text(json.dumps({"exercises": [{"candidateExpansion": {
        "discoveryTurn": {"stopReason": reason, "candidateBudget": 24,
            "reviewedThisTurn": 4, "timeBudgetSeconds": 300, "remainingTimeSeconds": remaining}}}]}))
    script = tmp_path / "check.ps1"
    script.write_text("function Resume-YieldedDiscovery {" + function + '''
$ErrorActionPreference = 'Stop'
$item = [pscustomobject]@{ exerciseCandidatesPath = (Join-Path $PSScriptRoot 'candidates.json');
 discoveryArgs = @('--discovery-candidate-budget', '24', '--discovery-time-budget-seconds', '300') }
$queue = [System.Collections.Generic.Queue[object]]::new()
$resumed = Resume-YieldedDiscovery -WorkItem $item -PendingQueue $queue
@{ resumed = $resumed; queued = $queue.Count; arguments = $item.discoveryArgs } | ConvertTo-Json -Compress
''')
    result = subprocess.run([shell, "-NoProfile", "-File", str(script)], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["resumed"] is expected
    assert payload["queued"] == int(expected)
    assert payload["arguments"][1::2] == (["20", "270"] if expected else ["24", "300"])
