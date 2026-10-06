import json
import os
from pathlib import Path
import shutil
import subprocess

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
    worker_stop = _powershell_function(script, "Stop-WhamWarmWorker")

    assert "Get-MotionServiceRuntimeState -RuntimeOwner $previousRuntime" in acquire
    assert '$runtimeState -ne "stopped"' in acquire
    assert '"shutdown_unconfirmed"' in release
    assert "Release-MotionWorkspaceLease -Lease $lease -PreserveOwner" in release
    assert '$runtimeState -eq "stopped"' in llama_stop
    assert '"ready.json"' in llama_stop
    assert "Release-MotionServiceSessionLease -SessionDirectory $Worker.sessionLeaseKey" in worker_stop
    assert '$runtimeState -ne "stopped"' in worker_stop


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


def test_shared_llama_restart_admission_ignores_stale_ready_and_defers_only_for_unsafe_bake():
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
    unsafe_bake_counter = _powershell_function(source, "Get-SharedLlamaUnsafeBakeRunningJobCount")
    command = f"""
$ErrorActionPreference = 'Stop'
{helper}
{unsafe_bake_counter}
$staleReadyRestart = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $false -ReadyMarkerExists $true `
    -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 1 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if (-not $staleReadyRestart) {{ throw 'An observed server exit was hidden by stale ready.json.' }}
$prefetchRestart = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $false -ReadyMarkerExists $true `
    -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 1 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 0 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if (-not $prefetchRestart) {{ throw 'Active prefetch work did not admit a required restart.' }}
$exclusiveBake = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $true -ReadyMarkerExists $false `
    -UnsafeBakeRunningJobCount 1 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 1 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if ($exclusiveBake) {{ throw 'The shared vision server restarted during an exclusive bake.' }}
$safeWave = [pscustomobject]@{{ IsStagedWave = $true; WaveWorkspace = 'safe-wave' }}
$safeCheckpoint = [pscustomobject]@{{ stage = 'source_validation' }}
function Get-Content {{ return $safeCheckpoint | ConvertTo-Json }}
function Test-Path {{ return $true }}
$safeBakeCount = Get-SharedLlamaUnsafeBakeRunningJobCount -RunningJobs @($safeWave)
if ($safeBakeCount -ne 0) {{ throw 'Source validation was treated as GPU-exclusive.' }}
$safeSourceRestart = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $true -StartRequested $true -ReadyMarkerExists $false `
    -UnsafeBakeRunningJobCount $safeBakeCount -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
    -DiscoveryRunningJobCount 1 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
if (-not $safeSourceRestart) {{ throw 'A source-validation wave could not restart its required vision server.' }}
$safeCheckpoint = [pscustomobject]@{{ stage = 'final_validation' }}
$safeFinalCount = Get-SharedLlamaUnsafeBakeRunningJobCount -RunningJobs @($safeWave)
if ($safeFinalCount -ne 0) {{ throw 'Final validation was treated as GPU-exclusive.' }}
$safeCheckpoint = [pscustomobject]@{{ stage = 'wham_generation' }}
$unsafeBakeCount = Get-SharedLlamaUnsafeBakeRunningJobCount -RunningJobs @($safeWave)
if ($unsafeBakeCount -ne 1) {{ throw 'WHAM generation did not block the shared vision server restart.' }}
$unknownWave = [pscustomobject]@{{ IsStagedWave = $true; WaveWorkspace = 'unknown-wave' }}
function Test-Path {{ return $false }}
$unknownBakeCount = Get-SharedLlamaUnsafeBakeRunningJobCount -RunningJobs @($unknownWave)
if ($unknownBakeCount -ne 1) {{ throw 'A missing staged checkpoint did not fail closed.' }}
$staleMarkerOnly = Test-SharedLlamaServerRestartAdmission `
    -RestartRequired $false -StartRequested $false -ReadyMarkerExists $true `
    -UnsafeBakeRunningJobCount 0 -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 `
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
