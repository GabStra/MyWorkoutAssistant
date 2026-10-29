import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from exercise_motion_pkg.process_lock import (
    InterProcessFileLock,
    WorkspaceLease,
    interprocess_lock_is_stale,
    process_identity,
)


def _powershell_function(source: str, name: str) -> str:
    marker = f"function {name} {{"
    start = source.index(marker)
    next_function = source.find("\nfunction ", start + len(marker))
    return source[start:] if next_function < 0 else source[start:next_function]


def test_power_shell_workspace_lease_creates_child_directory_and_keeps_exclusion(tmp_path: Path):
    pwsh = shutil.which('pwsh')
    if pwsh is None:
        pytest.skip('PowerShell required')
    source = (Path(__file__).resolve().parents[1] / 'scripts/run_exercise_motion_workout_plan.ps1').read_text(encoding='utf-8-sig')
    acquire = _powershell_function(source, 'Acquire-MotionWorkspaceLease')
    old = acquire.replace('    [System.IO.Directory]::CreateDirectory($WorkspaceRoot) | Out-Null\n', '')
    command = f'''
$ErrorActionPreference = 'Stop'
function Assert-StagedWaveWorkspaceIsQuiescent {{ param($WorkspaceRoot) }}
function Get-ObjectProperty {{ param($Object, $Name); return $null }}
{old}
$reproduced = $false
try {{ $null = Acquire-MotionWorkspaceLease -WorkspaceRoot (Join-Path $env:MOTION_TEST_WORKSPACE 'old/predict') }}
catch {{ $reproduced = $_.Exception.Message.Contains('already owned') }}
if (-not $reproduced) {{ throw 'Missing-directory failure was not reproduced' }}
{acquire}
$child = Join-Path $env:MOTION_TEST_WORKSPACE 'new/predict'
$lease = Acquire-MotionWorkspaceLease -WorkspaceRoot $child
try {{
    if (-not (Test-Path -LiteralPath $lease.ownerPath)) {{ throw 'Owner receipt missing' }}
    $excluded = $false
    try {{ $null = Acquire-MotionWorkspaceLease -WorkspaceRoot $child }}
    catch {{ $excluded = $_.Exception.Message.Contains('already owned') }}
    if (-not $excluded) {{ throw 'Concurrent owner was admitted' }}
}} finally {{ $lease.stream.Dispose() }}
$next = Acquire-MotionWorkspaceLease -WorkspaceRoot $child
$next.stream.Dispose()
'''
    completed = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-Command', command],
        env={**os.environ, 'MOTION_TEST_WORKSPACE': str(tmp_path)}, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_successful_wave_retains_worker_handle_for_confirmed_shutdown():
    pwsh = shutil.which('pwsh')
    if pwsh is None:
        pytest.skip('PowerShell required')
    source = (Path(__file__).resolve().parents[1] / 'scripts/run_exercise_motion_workout_plan.ps1').read_text(encoding='utf-8-sig')
    start = source.index('                        $siblingStagedWaveRunning =')
    end = source.index('                        if ($waveResult -and $waveResult.exitCode -eq 75)', start)
    cleanup = _powershell_function(source, 'Stop-MotionModelServicesAfterStagedWorker')
    command = f'''
$ErrorActionPreference = 'Stop'
$bakeRunningJobs = @()
$job = [pscustomobject]@{{ Id = 1 }}
$waveResult = [pscustomobject]@{{ exitCode = 0 }}
$waveAmbiguousRecovery = $false
$warmGvhmrWorkerInstance = [pscustomobject]@{{ workers = @('preprocess', 'predict') }}
$script:Stopped = $false
function Stop-GvhmrWarmWorker {{ param($Worker); if ($null -ne $Worker) {{ $script:Stopped = $true }} }}
function Stop-SharedLlamaServer {{ param($Server) }}
{source[start:end]}
if ($null -eq $warmGvhmrWorkerInstance) {{ throw 'Successful wave discarded the live worker owner' }}
{cleanup}
$null = Stop-MotionModelServicesAfterStagedWorker -StagedWaveShutdownConfirmed $true -WarmGvhmrWorker $warmGvhmrWorkerInstance
if (-not $script:Stopped) {{ throw 'Final cleanup lost the worker handle' }}
'''
    completed = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_workspace_lease_refuses_to_replace_a_live_service_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    owner = {
        "schemaVersion": 1,
        "pid": os.getpid(),
        "ownerToken": "prior-service-owner",
        "runtimeOwner": {
            "kind": "process",
            "service": "llama-server",
            "pid": os.getpid(),
            "processIdentity": process_identity(os.getpid()),
        },
        "serviceState": "shutdown_unconfirmed",
    }
    owner_path = tmp_path / ".motion_workspace.owner.json"
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    for stage in ("replacement_one", "replacement_two"):
        with pytest.raises(TimeoutError, match="previous motion service owner"):
            with WorkspaceLease(tmp_path, stage=stage):
                pytest.fail("A new owner must not replace evidence for a live child service")
        assert json.loads(owner_path.read_text(encoding="utf-8")) == owner

    monkeypatch.setattr("exercise_motion_pkg.process_lock.process_identity", lambda _pid: None)
    with pytest.raises(TimeoutError, match="runtime state is unknown"):
        with WorkspaceLease(tmp_path, stage="identity_unavailable"):
            pytest.fail("An unqueryable live process must not release service ownership")
    assert json.loads(owner_path.read_text(encoding="utf-8")) == owner


def test_workspace_lease_refuses_incomplete_prior_owner_metadata(tmp_path: Path):
    owner_path = tmp_path / ".motion_workspace.owner.json"
    malformed_owner = {"runtimeOwner": "unparseable-service-state"}
    owner_path.write_text(json.dumps(malformed_owner), encoding="utf-8")

    with pytest.raises(TimeoutError, match="incomplete previous owner record"):
        with WorkspaceLease(tmp_path, stage="replacement"):
            pytest.fail("Incomplete prior ownership metadata must fail closed")
    assert json.loads(owner_path.read_text(encoding="utf-8")) == malformed_owner


def test_old_lock_metadata_does_not_revoke_a_live_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    lock_path = tmp_path / "shared.lock"
    lock_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")
    monkeypatch.setattr("exercise_motion_pkg.process_lock.process_is_running", lambda _pid: True)

    assert not interprocess_lock_is_stale(lock_path, stale_after_seconds=0)


def test_interprocess_lock_serializes_even_when_owner_metadata_is_old(tmp_path: Path):
    lock_path = tmp_path / "shared.lock"
    owner = InterProcessFileLock(
        lock_path,
        stage="first",
        timeout_seconds=0.1,
        stale_after_seconds=0,
        poll_interval_seconds=0.01,
    )
    waiter = InterProcessFileLock(
        lock_path,
        stage="second",
        timeout_seconds=0.05,
        stale_after_seconds=0,
        poll_interval_seconds=0.01,
    )

    owner.__enter__()
    try:
        os.utime(lock_path, (1, 1))
        with pytest.raises(TimeoutError, match="Timed out waiting for process lock"):
            waiter.__enter__()
    finally:
        owner.__exit__(None, None, None)

    assert json.loads(lock_path.read_text(encoding="utf-8"))["stage"] == "first"
    waiter.__enter__()
    waiter.__exit__(None, None, None)
    assert json.loads(lock_path.read_text(encoding="utf-8"))["stage"] == "second"


def test_power_shell_services_preserve_leases_until_runtime_exit():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    ).read_text(encoding="utf-8-sig")
    acquire = _powershell_function(script, "Acquire-MotionWorkspaceLease")
    release = _powershell_function(script, "Release-MotionServiceSessionLease")
    llama_stop = _powershell_function(script, "Stop-SharedLlamaServer")
    worker_stop = _powershell_function(script, "Stop-GvhmrWarmWorker")

    assert "Get-MotionServiceRuntimeState -RuntimeOwner $previousRuntime" in acquire
    assert '$runtimeState -ne "stopped"' in acquire
    assert '"shutdown_unconfirmed"' in release
    assert "Release-MotionWorkspaceLease -Lease $lease -PreserveOwner" in release
    assert '$runtimeState -eq "stopped"' in llama_stop
    assert '"ready.json"' in llama_stop
    assert "Release-MotionServiceSessionLease -SessionDirectory $Worker.sessionLeaseKey" in worker_stop
    assert '$runtimeState -eq "stopped"' in worker_stop
    assert 'shutdown could not be confirmed; preserving its session owner evidence.' in worker_stop


def test_power_shell_workspace_admission_rejects_queued_motion_work(tmp_path: Path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required to exercise staged-wave workspace admission")
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    ).read_text(encoding="utf-8-sig")
    admission = _powershell_function(script, "Assert-StagedWaveWorkspaceIsQuiescent")
    acquire = _powershell_function(script, "Acquire-MotionWorkspaceLease")
    assert "Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $WorkspaceRoot" in acquire
    command = fr"""
function Invoke-WithStagedWaveAdmissionLock {{
    param([string]$QueueRoot, [scriptblock]$Operation)
    return & $Operation
}}
function Get-StagedBakeQueueServiceState {{
    param([string]$QueueRoot)
    return $script:MockStagedWaveServiceState
}}
$workspaceRoot = $env:MOTION_TEST_WORKSPACE
$queueRoot = Join-Path (Join-Path $workspaceRoot "staged-wave-services") "v1"
New-Item -ItemType Directory -Force -Path $queueRoot, `
    (Join-Path $queueRoot "requests"), `
    (Join-Path $queueRoot "processing"), `
    (Join-Path $queueRoot "ambiguous") | Out-Null
{admission}

$script:MockStagedWaveServiceState = [pscustomobject]@{{
    healthy = $true
    matchingProcess = $true
    state = [pscustomobject]@{{ status = "idle"; currentRequestId = ""; currentWaveId = ""; pid = 123 }}
}}
Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $workspaceRoot

$script:MockStagedWaveServiceState.state.status = "running"
$activeRejected = $false
try {{ Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $workspaceRoot }} catch {{
    $activeRejected = $_.Exception.Message.Contains("active") -or $_.Exception.Message.Contains("unverifiable")
}}
if (-not $activeRejected) {{ throw "A live staged-wave worker was not rejected." }}

$script:MockStagedWaveServiceState.matchingProcess = $false
$script:MockStagedWaveServiceState.state.status = "stopped"
Set-Content -LiteralPath (Join-Path $queueRoot "requests\pending.json") -Value "{{}}"
$pendingRejected = $false
try {{ Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $workspaceRoot }} catch {{
    $pendingRejected = $_.Exception.Message.Contains("pending")
}}
if (-not $pendingRejected) {{ throw "An unclaimed staged-wave request was not rejected." }}
Remove-Item -LiteralPath (Join-Path $queueRoot "requests\pending.json") -Force

Set-Content -LiteralPath (Join-Path $queueRoot "processing\claimed.json") -Value "{{}}"
$processingRejected = $false
try {{ Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $workspaceRoot }} catch {{
    $processingRejected = $_.Exception.Message.Contains("processing") -or $_.Exception.Message.Contains("pending")
}}
if (-not $processingRejected) {{ throw "A claimed staged-wave request was not rejected." }}
Remove-Item -LiteralPath (Join-Path $queueRoot "processing\claimed.json") -Force

Set-Content -LiteralPath (Join-Path $queueRoot "ambiguous\uncertain.json") -Value "{{}}"
$ambiguousRejected = $false
try {{ Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $workspaceRoot }} catch {{
    $ambiguousRejected = $_.Exception.Message.Contains("ambiguous")
}}
if (-not $ambiguousRejected) {{ throw "An ambiguous staged-wave request was not rejected." }}
"""
    environment = dict(os.environ)
    environment["MOTION_TEST_WORKSPACE"] = str(tmp_path)
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_shared_llama_restart_reuses_held_lease_only_after_runtime_stops():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    ).read_text(encoding="utf-8-sig")
    acquire = _powershell_function(script, "Acquire-MotionServiceSessionLease")

    assert '$script:MotionServiceSessionLeases.ContainsKey($normalizedSession)' in acquire
    assert 'Get-MotionServiceRuntimeState -RuntimeOwner $existingLease.runtimeOwner' in acquire
    assert '$existingRuntimeState -ne "stopped"' in acquire
    assert 'return $normalizedSession' in acquire

    runtime_monitor = script.index(
        '$serverRuntimeState = Get-MotionServiceRuntimeState `\n                        -RuntimeOwner $sharedLlamaServerInstance.runtimeOwner'
    )
    runtime_transition = script[runtime_monitor : runtime_monitor + 1800]
    assert 'if ($serverRuntimeState -eq "stopped")' in runtime_transition
    assert 'elseif ($serverRuntimeState -eq "running")' in runtime_transition
    assert 'process identity is unverified' in runtime_transition


def test_shared_llama_restart_admission_defers_for_live_exclusive_handoff(tmp_path: Path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required to exercise the shared llama restart gate")
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    )
    source = script_path.read_text(encoding="utf-8-sig")
    helper = _powershell_function(source, "Test-SharedLlamaServerRestartAdmission")
    handoff_helper = _powershell_function(source, "Test-SharedLlamaExclusiveHandoffActive")
    stopped_handoff_helper = _powershell_function(source, "Test-SharedLlamaServerStoppedByLiveExclusiveHandoff")
    process_identity_helper = _powershell_function(source, "Get-MotionProcessIdentityState")
    bake_restart_counter = _powershell_function(source, "Get-SharedLlamaBakeRestartCounts")
    session_dir = str(tmp_path / "shared-llama").replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
{helper}
{handoff_helper}
{stopped_handoff_helper}
{process_identity_helper}
{bake_restart_counter}
$sessionDir = '{session_dir}'
$inflightDir = Join-Path $sessionDir 'in-flight'
New-Item -ItemType Directory -Path $inflightDir -Force | Out-Null
$ownerProcess = Get-Process -Id $PID
$ownerIdentity = [long]$ownerProcess.StartTime.ToUniversalTime().ToFileTimeUtc()
@{{ pid = $PID; processIdentity = $ownerIdentity }} | ConvertTo-Json | Set-Content (Join-Path $sessionDir 'stop_intent.json')
@{{ pid = $PID; processIdentity = $ownerIdentity; activeRequests = 0 }} | ConvertTo-Json | Set-Content (Join-Path $inflightDir "$PID.json")
if (-not (Test-SharedLlamaExclusiveHandoffActive -SessionDir $sessionDir)) {{ throw 'A live zero-request exclusive owner was not recognized.' }}
@{{ stoppedByPid = $PID }} | ConvertTo-Json | Set-Content (Join-Path $sessionDir 'stopped.json')
if (-not (Test-SharedLlamaServerStoppedByLiveExclusiveHandoff -SessionDir $sessionDir)) {{ throw 'A matching stop record was not recognized.' }}
$staleReadyRestart = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $false -ReadyMarkerExists $true `
    -SafeBakeRunningJobCount 0 -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 1 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if (-not $staleReadyRestart) {{ throw 'An observed server exit was hidden by stale ready.json.' }}
$prefetchRestart = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $false -ReadyMarkerExists $true `
    -SafeBakeRunningJobCount 0 -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 1 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 0 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if (-not $prefetchRestart) {{ throw 'Active prefetch work did not admit a required restart.' }}
$quiescingClient = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $true -ReadyMarkerExists $false `
    -LiveExclusiveHandoffActive $true `
    -SafeBakeRunningJobCount 1 -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 0 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if ($quiescingClient) {{ throw 'A live exclusive GPU handoff did not defer the server restart.' }}
$exclusiveBake = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $true -ReadyMarkerExists $false `
    -SafeBakeRunningJobCount 0 -UnsafeBakeRunningJobCount 1 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 1 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if ($exclusiveBake) {{ throw 'The shared vision server restarted during an exclusive bake.' }}
$safeWave = [pscustomobject]@{{ IsStagedWave = $true; WaveWorkspace = 'safe-wave' }}
$safeCheckpoint = [pscustomobject]@{{ stage = 'source_validation' }}
function Get-Content {{ return $safeCheckpoint | ConvertTo-Json }}
function Test-Path {{ return $true }}
$safeBakeCounts = Get-SharedLlamaBakeRestartCounts -RunningJobs @($safeWave)
if ($safeBakeCounts.safeBakeRunningJobCount -ne 1 -or $safeBakeCounts.unsafeBakeRunningJobCount -ne 0) {{ throw 'Source validation was not classified as restart-safe work.' }}
$safeSourceRestart = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $true -ReadyMarkerExists $false `
    -SafeBakeRunningJobCount $safeBakeCounts.safeBakeRunningJobCount `
    -UnsafeBakeRunningJobCount $safeBakeCounts.unsafeBakeRunningJobCount `
    -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 0 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if (-not $safeSourceRestart) {{ throw 'A source-validation wave could not restart its required vision server.' }}
$safeCheckpoint = [pscustomobject]@{{ stage = 'final_validation' }}
$safeFinalCounts = Get-SharedLlamaBakeRestartCounts -RunningJobs @($safeWave)
if ($safeFinalCounts.safeBakeRunningJobCount -ne 1 -or $safeFinalCounts.unsafeBakeRunningJobCount -ne 0) {{ throw 'Final validation was not classified as restart-safe work.' }}
$safeCheckpoint = [pscustomobject]@{{ stage = 'reconstruction_generation' }}
$unsafeBakeCounts = Get-SharedLlamaBakeRestartCounts -RunningJobs @($safeWave)
if ($unsafeBakeCounts.safeBakeRunningJobCount -ne 0 -or $unsafeBakeCounts.unsafeBakeRunningJobCount -ne 1) {{ throw 'RECONSTRUCTION generation did not block the shared vision server restart.' }}
$unknownWave = [pscustomobject]@{{ IsStagedWave = $true; WaveWorkspace = 'unknown-wave' }}
function Test-Path {{ return $false }}
$unknownBakeCounts = Get-SharedLlamaBakeRestartCounts -RunningJobs @($unknownWave)
if ($unknownBakeCounts.safeBakeRunningJobCount -ne 0 -or $unknownBakeCounts.unsafeBakeRunningJobCount -ne 1) {{ throw 'A missing staged checkpoint did not fail closed.' }}
$staleMarkerOnly = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $false -StartRequested $false -ReadyMarkerExists $true `
    -SafeBakeRunningJobCount 0 -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 1 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if ($staleMarkerOnly) {{ throw 'A stale ready marker without an observed exit triggered a restart.' }}
"""
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Test-SharedLlamaServerStoppedByLiveExclusiveHandoff -SessionDir $SessionDir" in source
    assert "stderrTail = (Get-Content -LiteralPath $errorLogPath" in source
    assert '"startup_error.json", "start_requested.json", "stopped.json"' in source
    assert source.count("Test-SharedLlamaExclusiveHandoffActive -SessionDir $SessionDir") >= 2


def test_powershell_shared_llama_start_prunes_only_confirmed_dead_counters(tmp_path: Path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required to exercise shared llama counter cleanup")
    from exercise_motion_pkg.gpu_lock import process_identity

    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    )
    source = script_path.read_text(encoding="utf-8-sig")
    remove_counters = _powershell_function(source, "Remove-StaleSharedLlamaInflightCounters")
    process_identity_helper = _powershell_function(source, "Get-MotionProcessIdentityState")
    session_dir = tmp_path / "shared-llama"
    inflight_dir = session_dir / "in-flight"
    inflight_dir.mkdir(parents=True)

    live_path = inflight_dir / f"{os.getpid()}.json"
    live_path.write_text(
        json.dumps({
            "pid": os.getpid(),
            "processIdentity": process_identity(os.getpid()),
            "activeRequests": 0,
        }),
        encoding="utf-8",
    )
    dead = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    dead_identity = process_identity(dead.pid)
    dead.terminate()
    dead.wait(timeout=10)
    dead_path = inflight_dir / f"{dead.pid}.json"
    dead_path.write_text(
        json.dumps({
            "pid": dead.pid,
            "processIdentity": dead_identity,
            "activeRequests": 0,
        }),
        encoding="utf-8",
    )
    malformed_path = inflight_dir / "unverifiable.json"
    malformed_path.write_text("{not-json", encoding="utf-8")

    command = f"""
$ErrorActionPreference = 'Stop'
{process_identity_helper}
{remove_counters}
Remove-StaleSharedLlamaInflightCounters -SessionDir '{str(session_dir).replace("'", "''")}'
if (-not (Test-Path -LiteralPath '{str(live_path).replace("'", "''")}')) {{ throw 'A live counter was removed.' }}
if (Test-Path -LiteralPath '{str(dead_path).replace("'", "''")}') {{ throw 'A dead counter was not reclaimed.' }}
if (-not (Test-Path -LiteralPath '{str(malformed_path).replace("'", "''")}')) {{ throw 'An unverifiable counter was removed.' }}
"""
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_powershell_shared_llama_counter_ignores_recycled_pid_identity(tmp_path: Path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required to exercise the shared llama supervisor helpers")
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    )
    source = script_path.read_text(encoding="utf-8-sig")
    helpers = "\n".join(
        _powershell_function(source, name)
        for name in (
            "Get-MotionProcessIdentityState",
            "Get-SharedLlamaLiveInflightCounters",
            "Stop-MotionProcessWithIdentity",
        )
    )
    session_dir = str(tmp_path / "shared-llama").replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
{helpers}
$sessionDir = '{session_dir}'
$counterDir = Join-Path $sessionDir 'in-flight'
New-Item -ItemType Directory -Force -Path $counterDir | Out-Null
$owner = Get-Process -Id $PID
$identity = [long]$owner.StartTime.ToUniversalTime().ToFileTimeUtc()
$counterPath = Join-Path $counterDir "$PID.json"
@{{ pid = $PID; processIdentity = ($identity + 1); activeRequests = 2 }} |
    ConvertTo-Json -Compress | Set-Content -LiteralPath $counterPath -Encoding UTF8
if (@(Get-SharedLlamaLiveInflightCounters -SessionDir $sessionDir).Count -ne 0) {{
    throw 'A counter from a recycled PID was treated as a live request.'
}}
if ((Get-MotionProcessIdentityState -ProcessId $PID -ExpectedProcessIdentity ($identity + 1)) -ne 'stopped') {{
    throw 'A mismatched process identity was not classified as stopped.'
}}
@{{ pid = $PID; processIdentity = $identity; activeRequests = 2 }} |
    ConvertTo-Json -Compress | Set-Content -LiteralPath $counterPath -Encoding UTF8
$live = @(Get-SharedLlamaLiveInflightCounters -SessionDir $sessionDir)
if ($live.Count -ne 1 -or $live[0].activeRequests -ne 2 -or $live[0].identityState -ne 'running') {{
    throw 'A live matching in-flight owner was not retained by the drain check.'
}}
if ((Stop-MotionProcessWithIdentity -ProcessId $PID -ExpectedProcessIdentity ($identity + 1)) -ne 'stopped') {{
    throw 'A recycled PID was not rejected by identity-safe process shutdown.'
}}
if ($null -eq (Get-Process -Id $PID -ErrorAction SilentlyContinue)) {{
    throw 'The identity check unexpectedly stopped the current PowerShell process.'
}}
"""
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_powershell_shared_llama_does_not_stop_server_after_drain_timeout(tmp_path: Path):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required to exercise the shared llama supervisor helpers")
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_exercise_motion_workout_plan.ps1"
    )
    source = script_path.read_text(encoding="utf-8-sig")
    helpers = "\n".join(
        _powershell_function(source, name)
        for name in (
            "Get-MotionProcessIdentityState",
            "Get-SharedLlamaLiveInflightCounters",
            "Stop-SharedLlamaServer",
        )
    )
    session_dir = str(tmp_path / "shared-llama").replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
{helpers}
$script:leaseReleased = $false
$script:processStopAttempted = $false
function Set-MotionServiceSessionState {{ param($SessionDirectory, $RuntimeOwner, $ServiceState) }}
function Release-MotionServiceSessionLease {{
    param($SessionDirectory)
    $script:leaseReleased = $true
    return 'running'
}}
function Stop-MotionProcessWithIdentity {{
    param($ProcessId, $ExpectedProcessIdentity, $WaitTimeoutSeconds)
    $script:processStopAttempted = $true
    throw 'The server must remain up while an attached request is in flight.'
}}
$sessionDir = '{session_dir}'
$counterDir = Join-Path $sessionDir 'in-flight'
New-Item -ItemType Directory -Force -Path $counterDir | Out-Null
$owner = Get-Process -Id $PID
$identity = [long]$owner.StartTime.ToUniversalTime().ToFileTimeUtc()
@{{ pid = $PID; processIdentity = $identity; activeRequests = 1 }} |
    ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $counterDir "$PID.json") -Encoding UTF8
$SharedLlamaServerStopDrainTimeoutSeconds = 0.1
$server = [pscustomobject]@{{
    processId = $PID
    sessionDir = $sessionDir
    sessionLeaseKey = $sessionDir
    runtimeOwner = [pscustomobject]@{{ processIdentity = $identity }}
}}
Stop-SharedLlamaServer -Server $server
if (-not $script:leaseReleased) {{ throw 'The live server ownership evidence was not preserved.' }}
if ($script:processStopAttempted) {{ throw 'The server was force-stopped before requests drained.' }}
if (Test-Path -LiteralPath (Join-Path $sessionDir 'stop_intent.json')) {{
    throw 'A failed drain left client admissions permanently blocked.'
}}
"""
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
