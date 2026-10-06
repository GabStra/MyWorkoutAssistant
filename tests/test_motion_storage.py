import errno
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import storage
from exercise_motion_pkg.bake_and_rank import apply_artifact_retention_policy


def test_storage_guard_checks_existing_volume_before_creating_outputs(tmp_path, monkeypatch):
    seen = []
    def usage(path):
        seen.append(path)
        return SimpleNamespace(free=99)
    monkeypatch.setattr(storage.shutil, 'disk_usage', usage)
    missing = tmp_path/'not-created'/'candidate'
    with pytest.raises(storage.InsufficientStorageError, match='resume'):
        storage.require_storage_reserve(missing, reserve_bytes=100)
    assert seen == [tmp_path.resolve()]
    assert not missing.parent.exists()
    storage.require_storage_reserve(missing, reserve_bytes=99)


def test_actual_disk_exhaustion_has_same_stop_semantics():
    assert storage.is_storage_failure(OSError(errno.ENOSPC, 'full'))
    assert not storage.is_storage_failure(PermissionError(errno.EACCES, 'denied'))


@pytest.mark.parametrize('error', [storage.InsufficientStorageError('reserve'), OSError(errno.ENOSPC, 'full')])
def test_cli_storage_exit_is_distinct_from_retryable_failure(error):
    from exercise_motion_pkg import cli
    entrypoint = Path(cli.__file__).read_text().split('if __name__ == "__main__":', 1)[1]
    def fail():
        raise error
    with pytest.raises(SystemExit) as stopped:
        exec('if True:' + entrypoint, {'main': fail})
    assert stopped.value.code == storage.INSUFFICIENT_STORAGE_EXIT_CODE


@pytest.mark.parametrize('script_name,function_name', [
    ('run_exercise_motion_library.ps1', 'Invoke-MovementPass'),
    ('run_exercise_motion_workout_plan.ps1', 'Complete-BakeJob'),
])
def test_launchers_stop_on_storage_failure_without_retry(tmp_path, script_name, function_name):
    shell = shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell required')
    harness = tmp_path/'storage-stop.ps1'
    harness.write_text('''param($SourceFile, $FunctionName)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($SourceFile, [ref]$null, [ref]$null)
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $FunctionName }, $true)
. ([scriptblock]::Create($node.Extent.Text))
function Invoke-MotionLibraryLoggedCommand { Write-Host 'ATTEMPT'; return 75 }
function Exit-IfMotionRunInterrupted {}
function Write-MotionLibraryMessage { param($Message); Write-Host $Message }
function Receive-Job { Write-Host 'ATTEMPT'; [pscustomobject]@{exitCode=75} }
function Remove-Job {}
function Start-Sleep { throw 'Storage failures must not restart' }
$PassRestartAttempts = 3
if ($FunctionName -eq 'Invoke-MovementPass') { Invoke-MovementPass }
else { Complete-BakeJob -Job ([pscustomobject]@{WorkItem=[pscustomobject]@{}}) }
throw 'Storage failure did not stop the launcher'
''')
    source = Path(__file__).resolve().parents[1]/'scripts'/script_name
    result = subprocess.run([shell, '-NoProfile', '-File', str(harness), str(source), function_name],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 75, result.stdout + result.stderr
    assert result.stdout.count('ATTEMPT') == 1


def test_failed_candidate_pruning_preserves_resume_and_diagnostics(tmp_path):
    candidate = tmp_path/'candidate'
    files = ['raw/motion.raw.json', 'cleaned/motion.cleaned.json', 'input/selected_segment.mp4',
             'raw/wham/unused.npy', 'raw/wham/resume.pkl', 'review/frame_001.png',
             'review/contact_sheet.jpg', 'review/rejection.json']
    for relative in files:
        p = candidate/relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'evidence')
    (candidate/'generation_checkpoint.json').write_text(json.dumps({
        'outputs': [{'path': str(candidate/'raw/wham/resume.pkl')}]}))
    report = apply_artifact_retention_policy(tmp_path, {'candidateResults': [{
        'candidateWorkspace': str(candidate), 'status': 'needs_motion_processing',
        'inputVideoPath': str(candidate/'input/selected_segment.mp4')}]})
    assert not report['errors']
    assert not (candidate/'raw/wham/unused.npy').exists()
    assert not (candidate/'review/frame_001.png').exists()
    for relative in set(files)-{'raw/wham/unused.npy', 'review/frame_001.png'}:
        assert (candidate/relative).exists(), relative


def test_failure_retention_does_not_follow_outside_manifest_paths(tmp_path):
    workspace = tmp_path/'work'; workspace.mkdir()
    external = tmp_path/'external'; (external/'raw').mkdir(parents=True)
    protected = external/'raw/motion.raw.json'; protected.write_text('keep')
    apply_artifact_retention_policy(workspace, {'candidateResults': [{'candidateWorkspace': str(external)}]})
    assert protected.read_text() == 'keep'
