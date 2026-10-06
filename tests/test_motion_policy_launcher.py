import ast
from pathlib import Path
import shutil
import subprocess

import pytest


def test_launchers_read_the_python_validation_policy():
    root = Path(__file__).resolve().parents[1]
    shell = shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell is unavailable')
    tree = ast.parse((root/'exercise_motion_pkg/bake_and_rank.py').read_text(encoding='utf-8'))
    expected = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id == 'SELECTION_VALIDATION_POLICY_VERSION' for target in node.targets))
    result = subprocess.run([shell, '-NoProfile', '-Command',
        '. ./scripts/motion_validation_policy.ps1; Get-MotionSelectionValidationPolicyVersion'],
        cwd=root, capture_output=True, text=True, check=True, timeout=30)
    assert int(result.stdout.strip()) == expected
    for script in ['run_exercise_motion_library.ps1', 'run_exercise_motion_workout_plan.ps1']:
        source = (root/'scripts'/script).read_text(encoding='utf-8')
        assert '$SelectionValidationPolicyVersion = Get-MotionSelectionValidationPolicyVersion' in source
