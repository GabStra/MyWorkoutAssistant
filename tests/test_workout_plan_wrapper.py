from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


def test_motion_launchers_allow_automatic_vram_fitting():
    repo = Path(__file__).resolve().parents[1]
    command = r'''
    $ErrorActionPreference = 'Stop'
    $tokens = $null; $errors = $null
    $root = $env:MOTION_FIT_TEST_ROOT
    $wrapper = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw $errors[0] }
    $body = $wrapper.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Start-SharedLlamaServer'}, $true)[0].Body.Extent.Text
    $from = $body.IndexOf('    $parallel =')
    $to = $body.IndexOf('    $launchId =')
    $build = [scriptblock]::Create($body.Substring($from, $to - $from))
    $LlamaCppCtxSize = 16384; $LlamaCppFitCtx = 12345; $LlamaCppFitTarget = 3072
    foreach ($fit in @('on', 'off')) {
        $LlamaCppFit = $fit
        . $build
        $expected = if ($fit -eq 'on') { 'auto' } else { 'all' }
        if ($serverArgs[[array]::IndexOf($serverArgs, '--gpu-layers') + 1] -ne $expected) { throw 'Shared worker defeats auto-fit' }
        if ($serverArgs[[array]::IndexOf($serverArgs, '--fit-ctx') + 1] -ne '12345') { throw 'Fit context not forwarded' }
        if ($serverArgs[[array]::IndexOf($serverArgs, '--fit-target') + 1] -ne '3072') { throw 'VRAM reserve not forwarded' }
    }
    $segment = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $root 'scripts/run_exercise_segment_detection.ps1'), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw $errors[0] }
    $definition = $segment.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-LlamaCppServerProcess'}, $true)[0]
    . ([scriptblock]::Create($definition.Extent.Text))
    function Start-Process { param($FilePath, $ArgumentList, [switch]$PassThru, $WindowStyle) $script:launchArgs = @($ArgumentList) }
    foreach ($fit in @('on', 'off')) {
        Resolve-LlamaCppServerProcess -Command 'unused.exe' -ModelPath 'model' -MmprojPath 'projector' -Backend 'gpu' -Fit $fit
        $expected = if ($fit -eq 'on') { 'auto' } else { 'all' }
        if ($launchArgs[[array]::IndexOf($launchArgs, '--gpu-layers') + 1] -ne $expected) { throw 'Segment worker defeats auto-fit' }
    }
    '''
    result = subprocess.run(['pwsh', '-NoProfile', '-Command', command],
        env={**os.environ, 'MOTION_FIT_TEST_ROOT': str(repo)}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_motion_cancellation_reaches_piped_child_wrapper(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = str(repo_root / "scripts/motion_run_interrupt.ps1").replace("'", "''")
    marker = str(tmp_path / "cancel").replace("'", "''")
    child = tmp_path / "child.ps1"
    child.write_text(
        f". '{helper}'\nWrite-Output 'ready'\n"
        "$deadline = [DateTime]::UtcNow.AddSeconds(10)\n"
        "while (-not (Test-MotionRunCancelRequested)) {\n"
        "    if ([DateTime]::UtcNow -ge $deadline) { exit 1 }\n"
        "    Start-Sleep -Milliseconds 50\n"
        "}\nexit 130\n",
        encoding="utf-8",
    )
    child_path = str(child).replace("'", "''")
    command = f"""
    $ErrorActionPreference = 'Stop'
    $env:EXERCISE_MOTION_CANCEL_PATH = '{marker}'
    . '{helper}'
    if (Test-MotionRunCancelRequested) {{ throw 'Cancellation was already set' }}
    & pwsh -NoProfile -File '{child_path}' 2>&1 | ForEach-Object {{
        if ("$_" -eq 'ready') {{ [MotionRunInterrupt]::RequestCancellation() }}
    }}
    if ($LASTEXITCODE -ne 130) {{ throw "Child did not receive cancellation: $LASTEXITCODE" }}
    exit 0
    """
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree shutdown")
def test_cancellation_stops_idle_staged_worker(tmp_path: Path) -> None:
    wrapper = Path(__file__).resolve().parents[1] / "scripts/run_exercise_motion_workout_plan.ps1"
    command = r"""
    $ErrorActionPreference = 'Stop'
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$errors)
    foreach ($function in $ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @('Get-StagedBakeQueueServiceState', 'Stop-StagedBakeQueueServiceProcessTree', 'Stop-StagedBakeQueueService')
    }, $true)) { Invoke-Expression $function.Extent.Text }
    function ConvertFrom-ReconstructionJson { process { $_ | ConvertFrom-Json } }
    function Test-MotionRunCancelRequested { return $true }
    $script:StagedWaveServiceQueueRoot = $env:MOTION_TEST_ROOT
    $movementRunId = 'cancel-idle-test'
    $worker = Start-Process -FilePath $env:MOTION_TEST_PYTHON -ArgumentList @('-c', '"import time; time.sleep(30)"') -WindowStyle Hidden -PassThru
    try {
        @{schemaVersion=1; queueRoot=$script:StagedWaveServiceQueueRoot; pid=$worker.Id; processIdentity=$worker.StartTime.ToUniversalTime().ToFileTimeUtc();
          currentWaveId=$null; status='idle'; updatedAtEpoch=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0} |
            ConvertTo-Json | Set-Content (Join-Path $script:StagedWaveServiceQueueRoot 'worker_state.json')
        $confirmed = Stop-StagedBakeQueueService -Cancel
        if (-not $confirmed -or -not $worker.WaitForExit(1000)) { throw 'Cancellation left the idle worker alive' }
    } finally {
        if (-not $worker.HasExited) { $worker.Kill() }
        $worker.Dispose()
    }
    """
    environment = dict(os.environ, MOTION_WRAPPER_PATH=str(wrapper), MOTION_TEST_ROOT=str(tmp_path), MOTION_TEST_PYTHON=sys.executable)
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="Windows PowerShell file sharing")
def test_staged_wave_waiter_survives_locked_worker_heartbeat(tmp_path: Path) -> None:
    wrapper = Path(__file__).resolve().parents[1] / "scripts/run_exercise_motion_workout_plan.ps1"
    command = r"""
    $ErrorActionPreference = 'Stop'
    $tokens = $null; $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
    $function = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-StagedBakeWaveJob'
    }, $true)
    $startJob = $function.Find({ param($node)
        $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Start-Job'
    }, $true)
    $waiterText = ($startJob.CommandElements | Where-Object {
        $_ -is [System.Management.Automation.Language.ScriptBlockExpressionAst]
    } | Select-Object -First 1).ScriptBlock.Extent.Text
    if (-not $waiterText) { throw 'Could not find the staged-wave waiter.' }
    $waiterText = $waiterText.Trim()
    $waiter = [scriptblock]::Create($waiterText.Substring(1, $waiterText.Length - 2))
    $StagedWaveAmbiguousRecoveryStatus = 'ambiguous_recovery'
    $StagedWaveAmbiguousRecoveryExitCode = 76
    $queueRoot = $env:MOTION_TEST_ROOT
    $waveWorkspace = Join-Path $queueRoot 'wave'
    New-Item -ItemType Directory -Force -Path $waveWorkspace, (Join-Path $queueRoot 'results') | Out-Null
    $statePath = Join-Path $queueRoot 'worker_state.json'
    '{}' | Set-Content -LiteralPath $statePath
    $lockedState = [IO.File]::Open($statePath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $job = Start-Job -ScriptBlock $waiter -ArgumentList '', $waveWorkspace, 'test-wave', 'test-request', $queueRoot
        Start-Sleep -Milliseconds 1500
        @{requestId='test-request'; waveId='test-wave'; exitCode=0; status='completed'} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $queueRoot 'results/test-request.json')
        @{waveId='test-wave'} | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $waveWorkspace 'staged_wave_report.json')
        if (-not (Wait-Job -Job $job -Timeout 15)) { throw 'Staged-wave waiter did not finish.' }
        $result = Receive-Job -Job $job -Wait -ErrorAction Stop
        if ($result.exitCode -ne 0 -or $result.serviceStatus -ne 'completed') {
            throw "Waiter lost the completed result: $($result | ConvertTo-Json -Compress)"
        }
    } finally {
        $lockedState.Dispose()
        if ($job) { Remove-Job -Job $job -Force }
    }
    """
    environment = dict(os.environ, MOTION_WRAPPER_PATH=str(wrapper), MOTION_TEST_ROOT=str(tmp_path))
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], env=environment, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell wrapper test")
def test_staged_wave_recovers_response_already_acknowledged_by_waiter(tmp_path: Path) -> None:
    wrapper = Path(__file__).resolve().parents[1] / "scripts/run_exercise_motion_workout_plan.ps1"
    command = r"""
    $ErrorActionPreference = 'Stop'
    $tokens = $null; $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
    $recovery = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text -eq '-not $waveResult' -and
        $node.Extent.Text.Contains('Staged-wave waiter ended without a terminal response')
    }, $true)
    if (-not $recovery) { throw 'Could not find the staged-wave response recovery.' }
    function Get-ObjectProperty { param($Object, $Name) $Object.$Name }
    function ConvertFrom-ReconstructionJson { process { $_ | ConvertFrom-Json } }
    $StagedWaveAmbiguousRecoveryStatus = 'ambiguous_recovery'
    $StagedWaveAmbiguousRecoveryExitCode = 76
    $script:StagedWaveServiceQueueRoot = $env:MOTION_TEST_ROOT
    $waveWorkspace = Join-Path $env:MOTION_TEST_ROOT 'wave'
    $consumedDirectory = Join-Path $env:MOTION_TEST_ROOT 'consumed'
    New-Item -ItemType Directory -Force -Path $waveWorkspace, $consumedDirectory | Out-Null
    $job = [pscustomobject]@{RequestId='test-request'; WaveId='test-wave'; WaveWorkspace=$waveWorkspace}
    $waveResult = $null
    @{requestId='test-request'; waveId='test-wave'; exitCode=0; status='completed'} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $consumedDirectory 'test-request.json')
    @{waveId='test-wave'; items=@()} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $waveWorkspace 'staged_wave_report.json')
    Invoke-Expression $recovery.Extent.Text
    if ($waveResult.exitCode -ne 0 -or $waveResult.serviceStatus -ne 'completed' -or
        $waveResult.report.waveId -ne 'test-wave' -or
        -not (Test-Path -LiteralPath (Join-Path $consumedDirectory 'test-request.json'))) {
        throw "Acknowledged response was not recovered: $($waveResult | ConvertTo-Json -Compress)"
    }
    """
    environment = dict(os.environ, MOTION_WRAPPER_PATH=str(wrapper), MOTION_TEST_ROOT=str(tmp_path))
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_workout_plan_bake_flags_are_supported_by_cli() -> None:
    from exercise_motion_pkg.cli import build_parser

    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    bake_arguments = script.split("$bakeArgs = @(", 1)[1].split("\n    $workItems +=", 1)[0]
    # Check argument declarations, including optional flags, without running models.
    flags = set(re.findall(r'"(--[a-z][a-z0-9-]*)"', bake_arguments))
    parser = build_parser()
    subcommands = next(action for action in parser._actions if action.dest == "command")
    accepted = set(subcommands.choices["bake-and-rank"]._option_string_actions)
    assert flags <= accepted, f"Unsupported bake flags: {sorted(flags - accepted)}"


def test_background_jobs_load_reconstruction_metadata_helper() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    setup = re.search(
        r"(?m)^\$reconstructionCompatPath = .*\n\$script:ReconstructionJobInitialization = .*",
        script,
    )
    assert setup is not None
    scripts_path = str(repo_root / "scripts").replace("'", "''")
    command = setup.group().replace("$PSScriptRoot", f"'{scripts_path}'") + """
    $ErrorActionPreference = 'Stop'
    $job = Start-Job -InitializationScript $script:ReconstructionJobInitialization -ScriptBlock {
        '{"wham":{"value":1}}' | ConvertFrom-Json | Convert-ReconstructionMetadata | ConvertTo-Json -Compress
    }
    try {
        $result = Receive-Job $job -Wait -ErrorAction Stop
        if (($result | ConvertFrom-Json).reconstruction.value -ne 1) { throw 'Metadata conversion failed' }
    } finally { Remove-Job $job -Force }
    """
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def write_fake_motion_cli(tmp_path: Path) -> tuple[Path, Path]:
    fake_cli = tmp_path / "fake_motion_cli.py"
    validator_source = (
        Path(__file__).resolve().parents[1] / "exercise_motion_pkg" / "bake_and_rank.py"
    ).read_text(encoding="utf-8")
    selection_policy_line = next(
        line for line in validator_source.splitlines()
        if line.startswith("SELECTION_VALIDATION_POLICY_VERSION =")
    )
    selection_policy_version = int(selection_policy_line.partition("=")[2].strip())
    fake_cli.write_text(
        textwrap.dedent(
            r"""
            import hashlib
            import json
            import os
            import sys
            import time
            from pathlib import Path

            sys.path.insert(0, __EXERCISE_MOTION_REPO_ROOT__)


            def arg_value(args, name, default=None):
                try:
                    return args[args.index(name) + 1]
                except ValueError:
                    return default


            def slugify(value):
                result = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
                while "--" in result:
                    result = result.replace("--", "-")
                return result or "exercise"


            def full_clip_artifact_state(payload):
                identity_fields = (
                    "kind", "source", "fps", "frameCount", "jointNames", "rootJoint", "loop",
                    "selectedPreviewSettings", "bakedPreviewConfiguration", "wearDisplay",
                    "renderFloorY", "groundContactMode", "elevatedSupportSurfaces", "bounds", "frames",
                )
                identity_payload = {name: payload.get(name) for name in identity_fields}
                encoded = json.dumps(
                    identity_payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
                full_clip_identity = {
                    "algorithm": "sha256",
                    "identityVersion": 2,
                    "contentSha256": hashlib.sha256(encoded).hexdigest(),
                    "frameCount": len(payload["frames"]),
                    "fps": payload["fps"],
                }
                return {
                    "schemaVersion": 1,
                    "artifactClass": "full_clip_bake",
                    "requiredClass": None,
                    "terminal": True,
                    "lineageComplete": True,
                    "history": ["full_clip_bake"],
                    "selectionEvidence": {"fullClipBake": full_clip_identity},
                }


            def append_log(command):
                log_path = os.environ.get("FAKE_MOTION_CLI_LOG")
                if log_path:
                    with open(log_path, "a", encoding="utf-8") as handle:
                        handle.write(command + "\n")


            def process_start_identity(pid):
                import ctypes
                from ctypes import wintypes

                class FileTime(ctypes.Structure):
                    _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.GetProcessTimes.argtypes = (
                    wintypes.HANDLE,
                    ctypes.POINTER(FileTime),
                    ctypes.POINTER(FileTime),
                    ctypes.POINTER(FileTime),
                    ctypes.POINTER(FileTime),
                )
                kernel32.GetProcessTimes.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
                kernel32.CloseHandle.restype = wintypes.BOOL
                process = kernel32.OpenProcess(0x1000, False, pid)
                if not process:
                    return None
                try:
                    created = FileTime()
                    exited = FileTime()
                    kernel = FileTime()
                    user = FileTime()
                    if not kernel32.GetProcessTimes(
                        process,
                        ctypes.byref(created),
                        ctypes.byref(exited),
                        ctypes.byref(kernel),
                        ctypes.byref(user),
                    ):
                        return None
                    return (int(created.high) << 32) | int(created.low)
                finally:
                    kernel32.CloseHandle(process)


            def run_staged_wave(args):
                staged_wave_manifest = arg_value(args, "--staged-wave-manifest")
                wave = json.loads(Path(staged_wave_manifest).read_text(encoding="utf-8-sig"))
                wave_workspace = Path(wave["workspace"])
                wave_workspace.mkdir(parents=True, exist_ok=True)
                item_states = [
                    {
                        "exerciseId": item["exerciseId"],
                        "exerciseName": item["exerciseName"],
                        "status": "pending",
                        "source": {"status": "prepared", "attempts": []},
                        "reconstruction": {"status": "pending"},
                        "finalValidation": {"status": "pending"},
                    }
                    for item in wave["items"]
                ]
                checkpoint = {
                    "schemaVersion": 1,
                    "waveId": wave["waveId"],
                    "stage": "reconstruction_generation",
                    "elapsedSeconds": 0.1,
                    "items": item_states,
                }
                (wave_workspace / "staged_wave_checkpoint.json").write_text(
                    json.dumps(checkpoint), encoding="utf-8"
                )
                time.sleep(2.5)
                for state in item_states:
                    state["status"] = "retry_required"
                    state["reconstruction"] = {"status": "failed", "error": "fake staged retry"}
                report = {
                    **checkpoint,
                    "stage": "completed",
                    "items": item_states,
                    "completedExerciseCount": 0,
                    "retryExerciseCount": len(item_states),
                    "retryExerciseIds": [state["exerciseId"] for state in item_states],
                }
                report_path = wave_workspace / "staged_wave_report.json"
                report_path.write_text(json.dumps(report), encoding="utf-8")
                return str(report_path)


            def run_staged_wave_service(args):
                queue_root = Path(arg_value(args, "--queue-root"))
                source_identity_fingerprint = arg_value(args, "--source-identity-fingerprint", "")
                service_configuration_fingerprint = arg_value(args, "--service-configuration-fingerprint", "")
                requests = queue_root / "requests"
                processing = queue_root / "processing"
                results = queue_root / "results"
                for directory in (requests, processing, results):
                    directory.mkdir(parents=True, exist_ok=True)
                state_path = queue_root / "worker_state.json"
                state = {
                    "schemaVersion": 1,
                    "queueRoot": str(queue_root.resolve()),
                    "sourceIdentityFingerprint": source_identity_fingerprint,
                    "serviceConfigurationFingerprint": service_configuration_fingerprint,
                    "pid": os.getpid(),
                    "processIdentity": process_start_identity(os.getpid()),
                    "status": "idle",
                    "updatedAtEpoch": time.time(),
                }
                state_path.write_text(json.dumps(state), encoding="utf-8")
                stop_path = queue_root / "stop.request"
                stop_path.unlink(missing_ok=True)
                idle_since = time.monotonic()
                while True:
                    request_paths = sorted(requests.glob("*.json"))
                    if not request_paths:
                        if stop_path.exists():
                            break
                        idle_timeout = float(os.environ.get("FAKE_STAGED_IDLE_SECONDS", "1.0"))
                        if time.monotonic() - idle_since >= idle_timeout:
                            break
                        time.sleep(0.02)
                        continue
                    for request_path in request_paths:
                        claimed_path = processing / request_path.name
                        try:
                            os.replace(request_path, claimed_path)
                        except FileNotFoundError:
                            continue
                        request = json.loads(claimed_path.read_text(encoding="utf-8"))
                        wave_id = request["waveId"]
                        request_id = request.get("requestId", wave_id)
                        state.update({"status": "running", "currentWaveId": wave_id, "updatedAtEpoch": time.time()})
                        state_path.write_text(json.dumps(state), encoding="utf-8")
                        command_args = request["arguments"]
                        command = command_args[0]
                        append_log(command)
                        if os.environ.get("FAKE_STAGED_AMBIGUOUS_RECOVERY") == "1":
                            exit_code, report_path, error = (
                                76,
                                None,
                                "The previous staged-wave service stopped while this request was running. Completion is ambiguous.",
                            )
                            status = "ambiguous_recovery"
                        elif request.get("sourceIdentityFingerprint") != source_identity_fingerprint:
                            exit_code, report_path, error = 1, None, "source identity mismatch"
                            status = "failed"
                        elif command != "bake-and-rank":
                            exit_code, report_path, error = 1, None, "unexpected staged service command"
                            status = "failed"
                        else:
                            report_path = run_staged_wave(command_args)
                            exit_code, error = 0, None
                            status = "completed"
                        result = {
                            "schemaVersion": 1,
                            "requestId": request_id,
                            "waveId": wave_id,
                            "exitCode": exit_code,
                            "status": status,
                            "reportPath": report_path,
                            "error": error,
                        }
                        (results / f"{request_id}.json").write_text(json.dumps(result), encoding="utf-8")
                        claimed_path.unlink(missing_ok=True)
                        idle_since = time.monotonic()
                        state.update({"status": "idle", "currentWaveId": None, "updatedAtEpoch": time.time()})
                        state_path.write_text(json.dumps(state), encoding="utf-8")
                state.update({"status": "stopped", "updatedAtEpoch": time.time()})
                state_path.write_text(json.dumps(state), encoding="utf-8")


            args = sys.argv[1:]
            if len(args) >= 2 and args[0] == "-c":
                # The production wrapper uses Python -c for both artifact-state
                # validation and packaged-state construction. PowerShell's test
                # .cmd adapter loses JSON quotes at the cmd.exe boundary, so
                # restore the state emitted by this fake bake before executing
                # the real project helper.
                sys.argv = ["-c", *args[2:]]
                if "json.loads(sys.argv[1])" in args[1]:
                    state_path = Path(__file__).with_name("fake_artifact_state.json")
                    sys.argv[1] = state_path.read_text(encoding="utf-8")
                exec(compile(args[1], "<fake-python -c>", "exec"), {"__name__": "__main__"})
                raise SystemExit(0)
            module_name = args[1] if len(args) >= 2 and args[0] == "-m" else None
            command = args[2] if len(args) >= 3 and module_name == "exercise_motion_pkg.cli" else None
            if module_name == "exercise_motion_pkg.staged_wave_service":
                run_staged_wave_service(args[2:])
                raise SystemExit(0)
            append_log(command or "unknown")
            if command == "bake-and-rank":
                argument_log = os.environ.get("FAKE_MOTION_CLI_ARGS_LOG")
                if argument_log:
                    with open(argument_log, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(args) + "\n")
                direct_bake_log = os.environ.get("FAKE_MOTION_DIRECT_BAKE_LOG")
                if direct_bake_log:
                    with open(direct_bake_log, "a", encoding="utf-8") as handle:
                        handle.write("direct bake-and-rank\n")

            if command == "list-workout-plan-exercises":
                out_json = Path(arg_value(args, "--out-json"))
                plan = json.loads(Path(arg_value(args, "--workout-plan-json")).read_text(encoding="utf-8"))
                readiness_status = os.environ.get("FAKE_MOTION_DEFINITION_STATUS", "ready")
                source_budget_status = os.environ.get("FAKE_MOTION_SOURCE_BUDGET_STATUS", "ready")
                exercises = []
                for item in plan["exercises"]:
                    name = item["name"]
                    exercise_id = item["id"]
                    exercises.append(
                        {
                            "exerciseId": exercise_id,
                            "exerciseName": name,
                            "slug": slugify(exercise_id),
                            "sourceExerciseName": name,
                            "equipmentQualifiedExerciseName": name,
                            "definitionReadiness": {
                                "status": readiness_status,
                                "reason": "fake_definition_unresolved" if readiness_status != "ready" else None,
                            },
                            "sourceReviewBudgetReadiness": {
                                "ready": source_budget_status == "ready",
                                "status": source_budget_status,
                                "stopReason": "source_turn_attempt_budget" if source_budget_status != "ready" else None,
                            },
                            **({"motionContext": item["motionContext"]} if "motionContext" in item else {}),
                        }
                    )
                readiness = {
                    "readyCount": sum(item["definitionReadiness"]["status"] == "ready" for item in exercises),
                    "unresolvedCount": sum(item["definitionReadiness"]["status"] != "ready" for item in exercises),
                    "approvedDefinitionsReused": 0,
                    "unresolvedReviewQueue": [
                        {"exerciseId": item["exerciseId"], "exerciseName": item["exerciseName"], **item["definitionReadiness"]}
                        for item in exercises if item["definitionReadiness"]["status"] != "ready"
                    ],
                    "readinessByExerciseId": {item["exerciseId"]: item["definitionReadiness"] for item in exercises},
                    "sourceReviewBudgetReadiness": {
                        "readyCount": sum(item["sourceReviewBudgetReadiness"]["ready"] for item in exercises),
                        "needsReviewCount": sum(not item["sourceReviewBudgetReadiness"]["ready"] for item in exercises),
                    },
                }
                effective_plan_path = arg_value(args, "--definition-effective-plan-json")
                if effective_plan_path:
                    Path(effective_plan_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(effective_plan_path).write_text(json.dumps(plan), encoding="utf-8")
                    readiness["effectivePlanPath"] = effective_plan_path
                    readiness["effectivePlanSha256"] = hashlib.sha256(Path(effective_plan_path).read_bytes()).hexdigest()
                readiness_report_path = arg_value(args, "--definition-readiness-report-json")
                if readiness_report_path:
                    Path(readiness_report_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(readiness_report_path).write_text(json.dumps(readiness), encoding="utf-8")
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps({"definitionReadiness": readiness, "exercises": exercises}), encoding="utf-8")
                raise SystemExit(0)

            if command == "find-youtube-videos":
                out_json = Path(arg_value(args, "--out-json"))
                plan = json.loads(Path(arg_value(args, "--workout-plan-json")).read_text(encoding="utf-8"))
                exercise = plan["exercises"][0]
                name = exercise["name"]
                exercise_id = exercise["id"]
                slug = slugify(exercise_id)
                candidate = {
                    "title": f"{name} tutorial",
                    "url": f"https://www.youtube.com/watch?v={slug[:11].ljust(11, 'x')}",
                    "webpageUrl": f"https://www.youtube.com/watch?v={slug[:11].ljust(11, 'x')}",
                    "videoId": slug[:11].ljust(11, "x"),
                    "status": "recommended",
                    "finalScore": 0.95,
                    "visionPayload": {
                        "bestChunkScore": 0.95,
                        "source_score": 0.95,
                        "validChunkCount": 1,
                        "scoredChunkCount": 1,
                    },
                }
                manifest = {
                    "schemaVersion": 1,
                    "ranking": {"searchElapsedSeconds": 0.01, "posePrefilterEnabled": False},
                    "exercises": [
                        {
                            "exerciseId": exercise_id,
                            "exerciseName": name,
                            "slug": slug,
                            "candidates": [candidate],
                        }
                    ],
                }
                if "--prefetch-only" in args:
                    source_plan_path = Path(arg_value(args, "--workout-plan-json"))
                    manifest.update(
                        {
                            "kind": "youtube_candidate_prefetch",
                            "sourcePlanPath": str(source_plan_path),
                            "sourcePlanSha256": hashlib.sha256(source_plan_path.read_bytes()).hexdigest(),
                            "equipmentJsonPath": None,
                            "equipmentSha256": None,
                        }
                    )
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps(manifest), encoding="utf-8")
                raise SystemExit(0)

            if command == "prefetch-youtube-sources":
                candidates_json = Path(arg_value(args, "--candidates-json"))
                out_json = Path(arg_value(args, "--out-json"))
                source_cache = Path(arg_value(args, "--youtube-source-cache-dir"))
                payload = json.loads(candidates_json.read_text(encoding="utf-8"))
                candidate = payload["exercises"][0]["candidates"][0]
                source_cache.mkdir(parents=True, exist_ok=True)
                source_path = source_cache / f"{candidate['videoId']}.mp4"
                source_path.write_bytes(b"source")
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "results": [
                                {
                                    "videoId": candidate["videoId"],
                                    "status": "downloaded",
                                    "path": str(source_path),
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                raise SystemExit(0)

            if command == "bake-and-rank":
                staged_wave_manifest = arg_value(args, "--staged-wave-manifest")
                if staged_wave_manifest:
                    wave = json.loads(Path(staged_wave_manifest).read_text(encoding="utf-8-sig"))
                    wave_workspace = Path(wave["workspace"])
                    wave_workspace.mkdir(parents=True, exist_ok=True)
                    item_states = [
                        {
                            "exerciseId": item["exerciseId"],
                            "exerciseName": item["exerciseName"],
                            "status": "pending",
                            "source": {"status": "prepared", "attempts": []},
                            "reconstruction": {"status": "pending"},
                            "finalValidation": {"status": "pending"},
                        }
                        for item in wave["items"]
                    ]
                    checkpoint = {
                        "schemaVersion": 1,
                        "waveId": wave["waveId"],
                        "stage": "reconstruction_generation",
                        "elapsedSeconds": 0.1,
                        "items": item_states,
                    }
                    (wave_workspace / "staged_wave_checkpoint.json").write_text(
                        json.dumps(checkpoint), encoding="utf-8"
                    )
                    time.sleep(2.5)
                    for state in item_states:
                        state["status"] = "retry_required"
                        state["reconstruction"] = {"status": "failed", "error": "fake staged retry"}
                    report = {
                        **checkpoint,
                        "stage": "completed",
                        "items": item_states,
                        "completedExerciseCount": 0,
                        "retryExerciseCount": len(item_states),
                        "retryExerciseIds": [state["exerciseId"] for state in item_states],
                    }
                    (wave_workspace / "staged_wave_report.json").write_text(
                        json.dumps(report), encoding="utf-8"
                    )
                    raise SystemExit(0)

                candidates_json = Path(arg_value(args, "--candidates-json"))
                workspace = Path(arg_value(args, "--workspace"))
                payload = json.loads(candidates_json.read_text(encoding="utf-8"))
                exercise = payload["exercises"][0]
                selected_dir = workspace / "fake_selected"
                selected_dir.mkdir(parents=True, exist_ok=True)
                skeleton_path = selected_dir / "wear_skeleton.json"
                review_video_path = selected_dir / "review.webm"
                input_video_path = selected_dir / "input.mp4"
                preview_html_path = selected_dir / "preview.html"
                source_preview_html_path = selected_dir / "motion_preview.html"
                three_module_path = selected_dir / "three.module.0.169.0.js"
                segment_detection_dir = selected_dir / "segment_detection"
                segment_detection_dir.mkdir(parents=True, exist_ok=True)
                source_pose_reference_path = segment_detection_dir / "exact_source_pose_reference.json"
                exact_source_validation_path = segment_detection_dir / "exact_source_phase_validation.json"
                segment_selection_path = segment_detection_dir / "segment_selection.json"
                skeleton_payload = {
                    "fps": 30.0,
                    "frameCount": 2,
                    "jointNames": ["pelvis"],
                    "rootJoint": "pelvis",
                    "loop": {"enabled": False},
                    "frames": [
                        {"joints": {"pelvis": [0.0, 0.0, 0.0]}},
                        {"joints": {"pelvis": [0.0, 0.0, 0.0]}},
                    ],
                    "selectedPreviewSettings": {
                        "cameraYawDegrees": 90.0,
                        "cameraPitchDegrees": 35.264389682754654,
                    },
                    "wearDisplay": {
                        "viewYawDegrees": 135.0,
                        "viewPitchDegrees": 35.264389682754654,
                    },
                }
                skeleton_payload["artifactState"] = full_clip_artifact_state(skeleton_payload)
                manifest_artifact_state = json.loads(json.dumps(skeleton_payload["artifactState"]))
                artifact_state_case = os.environ.get("FAKE_MOTION_ARTIFACT_STATE_CASE")
                if artifact_state_case == "missing_full_clip_lineage":
                    manifest_artifact_state.pop("lineageComplete")
                    manifest_artifact_state["selectionEvidence"] = {}
                    skeleton_payload["artifactState"] = json.loads(json.dumps(manifest_artifact_state))
                elif artifact_state_case == "embedded_state_mismatch":
                    embedded_state = json.loads(json.dumps(manifest_artifact_state))
                    embedded_state["requiredClass"] = "cyclic_rebake"
                    embedded_state["terminal"] = False
                    skeleton_payload["artifactState"] = embedded_state
                elif artifact_state_case == "embedded_state_corrupt":
                    embedded_state = json.loads(json.dumps(manifest_artifact_state))
                    embedded_state["history"] = ["full_clip_bake", "cyclic_rebake"]
                    skeleton_payload["artifactState"] = embedded_state
                elif artifact_state_case == "embedded_state_reordered":
                    skeleton_payload["artifactState"] = {
                        key: manifest_artifact_state[key]
                        for key in reversed(list(manifest_artifact_state))
                    }
                elif artifact_state_case == "missing_embedded_state":
                    skeleton_payload.pop("artifactState")
                Path(__file__).with_name("fake_artifact_state.json").write_text(
                    json.dumps(manifest_artifact_state), encoding="utf-8"
                )
                skeleton_path.write_text(json.dumps(skeleton_payload), encoding="utf-8")
                skeleton_identity = {
                    "sha256": hashlib.sha256(skeleton_path.read_bytes()).hexdigest(),
                    "frameCount": len(skeleton_payload["frames"]),
                }
                full_clip_review_window = {
                    "schemaVersion": 1,
                    "frameCount": 2,
                    "frameIndices": [1],
                    "frameTimesSec": [1.0 / 30.0],
                    "sampling": {"policy": "evenly_spaced_v1", "requestedFrameCount": 1},
                    "selection": {
                        "artifactClass": "full_clip_bake",
                        "selectionId": None,
                        "interval": {
                            "type": "full_clip_bake",
                            "startFrame": 0,
                            "endFrame": 1,
                            "startTimeSec": 0.0,
                            "endTimeSec": 1.0 / 30.0,
                            "durationSec": 1.0 / 30.0,
                        },
                    },
                }
                review_video_path.write_bytes(b"webm")
                input_video_path.write_bytes(b"mp4")
                preview_html_path.write_text("<html></html>", encoding="utf-8")
                source_preview_html_path.write_text("<html>interactive</html>", encoding="utf-8")
                three_module_path.write_text("export const WebGLRenderer = class {};", encoding="utf-8")
                source_pose_reference_path.write_text(
                    json.dumps({"schemaVersion": 1, "pose": {"frames": []}}), encoding="utf-8"
                )
                exact_source_validation = {
                    "validationPolicyVersion": 1,
                    "passed": True,
                    "metrics": {"sourcePoseReferencePath": str(source_pose_reference_path)},
                }
                exact_source_validation_path.write_text(
                    json.dumps(exact_source_validation), encoding="utf-8"
                )
                segment_selection_path.write_text(
                    json.dumps({"exactSourcePhaseValidation": exact_source_validation}), encoding="utf-8"
                )
                selected = {
                    "exerciseName": exercise["exerciseName"],
                    "candidateTitle": exercise["candidates"][0]["title"],
                    "artifactClass": "full_clip_bake",
                    "artifactState": manifest_artifact_state,
                    "ranking": {
                        "payload": {
                            "finalOutputValidation": {
                                "passed": True,
                                "artifactClassGate": {
                                    "passed": True,
                                    "artifactClass": "full_clip_bake",
                                },
                                "renderEvidence": {
                                    "available": True,
                                    "passed": True,
                                    "skeletonIdentity": skeleton_identity,
                                    "reviewWindow": full_clip_review_window,
                                },
                            },
                        },
                    },
                    "selectedWearSkeletonPath": str(skeleton_path),
                    "selectedReviewVideoPath": str(review_video_path),
                    "selectedInputVideoPath": str(input_video_path),
                    "selectedPreviewHtmlPath": str(preview_html_path),
                    "sourcePreviewHtmlPath": str(source_preview_html_path),
                    "candidateWorkspace": str(selected_dir),
                    "selectedSectionStartSeconds": 1.25,
                    "selectedSectionEndSeconds": 4.75,
                    "settingsOptions": {
                        "autoWorldAlignment": True,
                        "sceneInverted": True,
                        "lockPlantedFeet": True,
                        "lockPlantedHands": False,
                    },
                    "wearSkeletonSettingsBaked": True,
                    "selectionScore": 0.9,
                }
                if os.environ.get("FAKE_MOTION_SOURCE_CLEARANCE") == "1":
                    selected["sourceSelectionClearance"] = {
                        "status": "not_required",
                        "sourceSelectionPolicyVersion": 67,
                        "sourceSelectionClearancePolicyVersion": 2,
                        "sourcePrepReason": "test explicitly skipped pre-reconstruction review",
                        "sourceManifestPath": str(candidates_json),
                        "sourceManifestSha256": hashlib.sha256(candidates_json.read_bytes()).hexdigest(),
                        "selectedSegmentPath": str(input_video_path),
                        "selectedSegmentSha256": hashlib.sha256(input_video_path.read_bytes()).hexdigest(),
                    }
                manual_review = os.environ.get("FAKE_MOTION_MANUAL_REVIEW") == "1"
                selection = {
                    "schemaVersion": 1,
                    "selectionValidationPolicyVersion": __SELECTION_VALIDATION_POLICY_VERSION__,
                    "sourceSelectionPolicyVersion": 67,
                    "preReconstructionSourceValidationEnabled": False,
                    "preReconstructionSourceValidationExplicitlyDisabled": True,
                    "selectionStatus": "needs_manual_review" if manual_review else "selected",
                    "sourceCandidatesJson": str(candidates_json),
                    "timings": {
                        "totalSeconds": 0.2,
                        "candidateProcessingSeconds": 0.1,
                        "processedCandidateCount": 1,
                        "readyCandidateCount": 1,
                        "reviewRankingSeconds": 0.01,
                        "selectionMaterializationSeconds": 0.01,
                    },
                    "candidateResults": [
                        {
                            "status": "ready_for_selection",
                            "reconstructionCacheStatus": "generated",
                            "generationTimings": {
                                "sourcePreparationSeconds": 0.01,
                                "reconstruction": {"elapsedSeconds": 0.02, "dockerLockWaitSeconds": 0.0},
                            },
                            "timings": {"previewBakeSeconds": 0.03},
                        }
                    ],
                    "selectedResultCount": 0 if manual_review else 1,
                    "selectedResults": [] if manual_review else [selected],
                    "selected": None if manual_review else selected,
                    "manualReviewFallback": (
                        {
                            **selected,
                            "selectionStatus": "needs_manual_review",
                            "rejectionReason": "automatic_acceptance_gate_failed",
                        }
                        if manual_review
                        else None
                    ),
                }
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "selection_manifest.json").write_text(json.dumps(selection), encoding="utf-8")
                raise SystemExit(0)

            raise SystemExit(f"unexpected command: {command}")
            """
        ).lstrip().replace(
            "__SELECTION_VALIDATION_POLICY_VERSION__",
            str(selection_policy_version),
        ).replace(
            "__EXERCISE_MOTION_REPO_ROOT__",
            repr(str(Path(__file__).resolve().parents[1])),
        ),
        encoding="utf-8",
    )

    fake_cmd = tmp_path / "fake_python.cmd"
    fake_cmd.write_text(
        f'@echo off\r\n'
        f'"{sys.executable}" "{fake_cli}" %*\r\n',
        encoding="utf-8",
    )
    return fake_cli, fake_cmd


def write_workout_plan(tmp_path: Path, exercise_count: int = 3) -> Path:
    exercises = [
        {"id": "bench", "name": "Barbell Bench Press"},
        {"id": "squat", "name": "Barbell Back Squat"},
        {"id": "pullup", "name": "Weighted Pull-Up"},
    ][:exercise_count]
    workout_plan = tmp_path / "workout_plan.json"
    workout_plan.write_text(json.dumps({"exercises": exercises}), encoding="utf-8")
    return workout_plan


def write_prepared_candidates_manifest(
    tmp_path: Path,
    fake_cli: Path,
    workout_plan: Path,
) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    plan_payload = json.loads(workout_plan.read_text(encoding="utf-8"))
    manifest_items = []
    for exercise in plan_payload["exercises"]:
        exercise_id = str(exercise["id"])
        slug = "-".join(
            "".join(character.lower() if character.isalnum() else " " for character in exercise_id).split()
        ) or "exercise"
        single_exercise_plan = tmp_path / f"{slug}_prepared_plan.json"
        candidates_path = tmp_path / f"{slug}_prepared_candidates.json"
        single_exercise_plan.write_text(
            json.dumps({"exercises": [exercise]}),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(fake_cli),
                "-m",
                "exercise_motion_pkg.cli",
                "find-youtube-videos",
                "--workout-plan-json",
                str(single_exercise_plan),
                "--out-json",
                str(candidates_path),
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        candidate_payload = json.loads(candidates_path.read_text(encoding="utf-8"))
        candidate = candidate_payload["exercises"][0]["candidates"][0]
        manifest_items.append(
            {
                "exerciseId": exercise_id,
                "exerciseSlug": slug,
                "candidatesJson": str(candidates_path),
                "expectedVideoId": candidate["videoId"],
            }
        )

    manifest_path = tmp_path / "prepared_candidates_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "prepared_exercise_candidates",
                "items": manifest_items,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_youtube_discovery_wrappers_keep_semantic_gate_budget_independent_of_attempt_max() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    youtube_bake = (repo_root / "scripts/run_exercise_motion_youtube_bake_and_rank.ps1").read_text(encoding="utf-8")
    workout_plan = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    for script in (youtube_bake, workout_plan):
        assert "--semantic-gate-candidates-per-exercise\" -Value \"$attemptMaxCandidates\"" not in script
        assert "--semantic-gate-max-candidates-per-exercise\" -Value \"$attemptMaxCandidates\"" not in script
        assert '"--semantic-gate-max-candidates-per-exercise", "$SemanticGateMaxCandidatesPerExercise"' in script


def test_workout_plan_attempt_exclusions_match_the_active_discovery_signature() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    loader = script.split("function Get-AttemptCandidateSnapshotPaths", 1)[1].split(
        "function Get-CandidateEvidenceIdentities", 1
    )[0]

    assert "[int]$signature.schemaVersion -eq 1" in loader
    assert "[int]$signature.policyVersion -eq $DiscoveryStagePolicyVersion" in loader
    assert "$cachedArgumentsHash -eq $expectedArgumentsHash" in loader
    assert "$cachedPlanHash -eq $expectedPlanHash" in loader
    assert "$cachedEquipmentHash -eq $expectedEquipmentHash" in loader
    assert "-DiscoveryArgumentsSha256 $DiscoveryArgumentsSha256" in script
    assert "-ExercisePlanSha256 $ExercisePlanSha256" in script
    assert "-EquipmentSha256 $EquipmentSha256" in script


def test_youtube_bake_wrapper_passes_exercise_motion_contract_cache_dir() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_youtube_bake_and_rank.ps1").read_text(encoding="utf-8")

    assert "[string]$ExerciseMotionContractCacheDir" in script
    assert '"--exercise-motion-contract-cache-dir", $contractCachePath' in script
    assert 'Join-Path $repoRoot "build\\exercise_motion\\exercise-library\\exercise-motion-contract-cache"' in script
    repo_root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "scripts/run_exercise_motion_workout_plan.ps1",
        "scripts/run_exercise_motion_youtube_bake_and_rank.ps1",
    ):
        script = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "[double]$CandidateTimeoutSeconds = 0.0" in script
        assert "[double]$ExerciseTimeoutSeconds = 0.0" in script
        assert '"--candidate-timeout-seconds", "$CandidateTimeoutSeconds"' in script
        assert '"--exercise-timeout-seconds", "$ExerciseTimeoutSeconds"' in script


def test_motion_wrappers_default_structured_vlm_calls_to_deterministic_decoding() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "scripts/run_exercise_motion_workout_plan.ps1",
        "scripts/run_exercise_motion_youtube_bake_and_rank.ps1",
        "scripts/run_exercise_motion_bake_and_rank.ps1",
        "scripts/run_exercise_motion_generation.ps1",
        "scripts/run_exercise_segment_detection.ps1",
    ):
        script = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "[double]$LlamaCppTemperature = 0.0" in script
        assert "[Nullable[double]]$LlamaCppTopP = 1.0" in script
        assert "[Nullable[int]]$LlamaCppTopK = 0" in script


def test_workout_plan_wrapper_starts_with_initial_suitable_target() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert script.count('$targetSuitableCount = [Math]::Max(1, $InitialTargetSuitableCount)') == 2
    assert '$targetSuitableCount = [Math]::Max(1, $MaxTargetSuitableCount)' not in script


def test_workout_plan_wrapper_acknowledges_ctrl_c_immediately() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    interrupt = (repo_root / "scripts/motion_run_interrupt.ps1").read_text(encoding="utf-8")

    assert "motion_run_interrupt.ps1" in script
    assert "MotionRunInterrupt" in interrupt
    assert "RegisterOnce" in interrupt
    assert "Register-MotionInterruptHandler -Silent" not in script
    assert "TryAcknowledge" in interrupt
    assert "Ctrl+C received. Stopping the motion run" in interrupt
    assert "Stopping background jobs and the motion extractor..." in script
    assert "Motion run stopped." in script
    assert "if (Test-MotionRunCancelRequested) {" in script
    assert "exit 130" in script


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_scheduler_failure_preserves_model_services_when_staged_worker_state_is_unknown(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"
    command = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
        $functionAsts = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -in @(
                    'Get-StagedBakeQueueServiceState',
                    'Get-StagedWaveAdmissionMutexNames',
                    'Invoke-WithStagedWaveAdmissionLock',
                    'Start-StagedBakeQueueServiceGeneration',
                    'Stop-StagedBakeQueueServiceProcessTree',
                    'Stop-StagedBakeQueueService',
                    'Stop-MotionModelServicesAfterStagedWorker'
                )
        }, $true)
        if ($functionAsts.Count -ne 7) { throw 'A staged-wave service function was not found.' }
        foreach ($functionAst in $functionAsts) { Invoke-Expression $functionAst.Extent.Text }

        function ConvertFrom-ReconstructionJson { process { $_ | ConvertFrom-Json } }
        function Test-MotionRunCancelRequested { return $false }
        function ConvertTo-StagedServiceArgument {
            param([string]$Value)
            return '"' + $Value.Replace('"', '\"') + '"'
        }
        function Get-Process {
            [CmdletBinding()]
            param([int]$Id)
            return $script:mockProcess
        }
        function Start-Process {
            param(
                [string]$FilePath,
                [string[]]$ArgumentList,
                [switch]$PassThru,
                [string]$WindowStyle,
                [string]$WorkingDirectory,
                [string]$RedirectStandardOutput,
                [string]$RedirectStandardError,
                [string]$ErrorAction
            )
            if ($FilePath.EndsWith('taskkill.exe', [StringComparison]::OrdinalIgnoreCase)) {
                $script:treeTerminationCommands += [pscustomobject]@{
                    filePath = $FilePath
                    arguments = @($ArgumentList)
                    windowStyle = $WindowStyle
                }
                if ($script:confirmTreeStop) { $script:mockProcess.HasExited = $true }
                $exitCode = if ($script:confirmTreeStop) { 0 } else { 1 }
                $terminator = [pscustomobject]@{
                    Id = 9001
                    HasExited = $true
                    ExitCode = $exitCode
                }
                $terminator | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
                    param([int]$TimeoutMilliseconds)
                    $script:terminatorWaitTimeouts += $TimeoutMilliseconds
                    return $this.HasExited
                }
                $terminator | Add-Member -MemberType ScriptMethod -Name Dispose -Value {}
                return $terminator
            }
            $stopRequestPath = Join-Path $script:StagedWaveServiceQueueRoot 'stop.request'
            if (Test-Path -LiteralPath $stopRequestPath) {
                throw 'A fresh staged-wave worker was launched while the old stop.request marker remained.'
            }
            $script:serviceLaunchCommands += [pscustomobject]@{
                filePath = $FilePath
                arguments = [string]$ArgumentList
                workingDirectory = $WorkingDirectory
                windowStyle = $WindowStyle
                stdout = $RedirectStandardOutput
                stderr = $RedirectStandardError
            }
            $script:mockProcess = [pscustomobject]@{
                Id = 5432
                HasExited = $false
                StartTime = [DateTime]::UtcNow
            }
            Write-TestWorkerState -WaveId $null `
                -Identity ([long]$script:mockProcess.StartTime.ToUniversalTime().ToFileTimeUtc()) `
                -Status 'idle'
            return $script:mockProcess
        }
        function Stop-Process {
            [CmdletBinding()]
            param([int]$Id, [switch]$Force)
            $script:stoppedProcessIds += $Id
            throw 'Parent-only Stop-Process must not terminate the staged-wave service.'
        }
        function Stop-GvhmrWarmWorker {
            param([object]$Worker)
            $script:stoppedModelServices += 'gvhmr'
        }
        function Stop-SharedLlamaServer {
            param([object]$Server)
            $script:stoppedModelServices += 'llama'
        }

        $script:StagedWaveServiceQueueRoot = Join-Path $env:TEMP ('motion-cancel-test-' + [guid]::NewGuid().ToString('N'))
        $script:stoppedProcessIds = @()
        $script:stoppedModelServices = @()
        $script:treeTerminationCommands = @()
        $script:serviceLaunchCommands = @()
        $script:terminatorWaitTimeouts = @()
        $script:workerWaitTimeouts = @()
        $script:gracefulExitOnStopRequest = $false
        $script:confirmTreeStop = $true
        $movementRunId = 'run-under-test'
        New-Item -ItemType Directory -Force -Path $script:StagedWaveServiceQueueRoot | Out-Null
        $statePath = Join-Path $script:StagedWaveServiceQueueRoot 'worker_state.json'
        $script:mockProcess = [pscustomobject]@{
            Id = 4321
            HasExited = $false
            StartTime = [DateTime]::UtcNow
        }
        $processIdentity = [long]$script:mockProcess.StartTime.ToUniversalTime().ToFileTimeUtc()
        $script:mockProcess | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
            param([int]$TimeoutMilliseconds)
            $script:workerWaitTimeouts += $TimeoutMilliseconds
            $stopRequestPath = Join-Path $script:StagedWaveServiceQueueRoot 'stop.request'
            if ($script:gracefulExitOnStopRequest -and (Test-Path -LiteralPath $stopRequestPath)) {
                $this.HasExited = $true
            }
            return $this.HasExited
        }
        function Write-TestWorkerState {
            param([string]$WaveId, [long]$Identity, [string]$Status = 'running')
            @{
                schemaVersion = 1
                queueRoot = $script:StagedWaveServiceQueueRoot
                pid = if ($null -ne $script:mockProcess) { $script:mockProcess.Id } else { 4321 }
                processIdentity = $Identity
                sourceIdentityFingerprint = 'test-source-fingerprint'
                serviceConfigurationFingerprint = 'test-configuration-fingerprint'
                status = $Status
                currentWaveId = $WaveId
                updatedAtEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
            } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        }

        # No state file is not proof that the worker is gone. A failure cleanup
        # must preserve model dependencies and workspace owner evidence.
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if ($stopped) { throw 'Missing worker state incorrectly confirmed shutdown.' }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 0) {
            throw 'Model dependencies were stopped while staged worker state was unknown.'
        }

        # A valid live worker serving another run remains untouched; the
        # failed run can safely stop its own model services after its marker
        # prevents any queued request from starting.
        Write-TestWorkerState -WaveId 'another-run-wave-0001' -Identity $processIdentity
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if (-not $stopped -or $script:stoppedProcessIds.Count -ne 0) {
            throw 'Failure cleanup stopped a staged wave owned by another run.'
        }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 2) {
            throw 'Confirmed cleanup did not stop both model dependencies.'
        }
        $script:stoppedModelServices = @()

        # Same-run active work receives stop.request first and can exit gracefully.
        $script:mockProcess.HasExited = $false
        $script:gracefulExitOnStopRequest = $true
        Write-TestWorkerState -WaveId 'run-under-test-wave-0001' -Identity $processIdentity
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if (-not $stopped -or $script:treeTerminationCommands.Count -ne 0 -or
            3000 -notin $script:workerWaitTimeouts -or
            -not (Test-Path -LiteralPath (Join-Path $script:StagedWaveServiceQueueRoot 'stop.request'))) {
            throw 'The active staged wave did not receive a bounded graceful-stop request.'
        }
        $marker = Get-Content (Join-Path (Join-Path $script:StagedWaveServiceQueueRoot 'cancelled_runs') 'run-under-test.json') -Raw | ConvertFrom-Json
        if ($marker.reason -ne 'workout-plan scheduler failed') { throw 'The run failure reason was not persisted.' }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 2) {
            throw 'Graceful staged-worker exit did not release both model dependencies.'
        }
        $script:stoppedModelServices = @()

        # A fresh generation clears the old stop marker only after the previous
        # process has exited, while holding the production admission mutex.
        $restart = Start-StagedBakeQueueServiceGeneration `
            -QueueRoot $script:StagedWaveServiceQueueRoot `
            -PythonCommand 'python.exe' `
            -MaxWaveItems 2 `
            -SourceIdentityFingerprint 'test-source-fingerprint' `
            -ConfigurationFingerprint 'test-configuration-fingerprint' `
            -RepositoryRoot $script:StagedWaveServiceQueueRoot
        if (-not $restart.launched -or $restart.process.Id -ne 5432 -or
            $script:serviceLaunchCommands.Count -ne 1 -or
            $script:serviceLaunchCommands[0].filePath -ne 'python.exe' -or
            -not $script:serviceLaunchCommands[0].arguments.Contains('--queue-root') -or
            (Test-Path -LiteralPath (Join-Path $script:StagedWaveServiceQueueRoot 'stop.request'))) {
            throw 'A confirmed stopped generation did not clear its stop marker before starting the replacement.'
        }
        $processIdentity = [long]$script:mockProcess.StartTime.ToUniversalTime().ToFileTimeUtc()

        # A still-running synchronous wave falls back to taskkill /T /F.
        $script:mockProcess.HasExited = $false
        $script:gracefulExitOnStopRequest = $false
        $script:confirmTreeStop = $true
        Write-TestWorkerState -WaveId 'run-under-test-wave-0002' -Identity $processIdentity
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if (-not $stopped -or $script:treeTerminationCommands.Count -ne 1 -or
            [string]::Join(' ', @($script:treeTerminationCommands[0].arguments)) -ne '/PID 5432 /T /F' -or
            5000 -notin $script:terminatorWaitTimeouts -or $script:stoppedProcessIds.Count -ne 0) {
            throw 'A nonresponsive staged wave did not use bounded process-tree termination.'
        }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 2) {
            throw 'Confirmed process-tree shutdown did not release both model dependencies.'
        }
        $script:stoppedModelServices = @()

        # If neither graceful nor tree shutdown can be confirmed, keep models.
        $script:mockProcess.HasExited = $false
        $script:confirmTreeStop = $false
        Write-TestWorkerState -WaveId 'run-under-test-wave-0003' -Identity $processIdentity
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if ($stopped -or $script:treeTerminationCommands.Count -ne 2) {
            throw 'Failure cleanup did not report an unconfirmed worker shutdown.'
        }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 0) {
            throw 'Model dependencies were stopped before staged worker exit was confirmed.'
        }

        # A missing PID and a process start-identity mismatch are both
        # confirmed stopped states, so model shutdown is allowed.
        $script:mockProcess = $null
        Write-TestWorkerState -WaveId 'run-under-test-wave-0004' -Identity $processIdentity
        $serviceState = Get-StagedBakeQueueServiceState -QueueRoot $script:StagedWaveServiceQueueRoot
        if ($serviceState.processState -ne 'stopped') { throw 'A dead staged worker was not recognized as stopped.' }
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if (-not $stopped) { throw 'A confirmed dead staged worker did not confirm shutdown.' }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 2) { throw 'Confirmed dead-worker cleanup did not stop model dependencies.' }
        $script:stoppedModelServices = @()

        $script:mockProcess = [pscustomobject]@{
            Id = 4321
            HasExited = $false
            StartTime = [DateTime]::UtcNow
        }
        $mismatchedIdentity = [long]$script:mockProcess.StartTime.ToUniversalTime().ToFileTimeUtc() + 1
        Write-TestWorkerState -WaveId 'run-under-test-wave-0005' -Identity $mismatchedIdentity
        $serviceState = Get-StagedBakeQueueServiceState -QueueRoot $script:StagedWaveServiceQueueRoot
        if ($serviceState.processState -ne 'stopped') { throw 'A staged worker process identity mismatch was not recognized as stopped.' }
        $stopped = Stop-StagedBakeQueueService -RunFailure
        if (-not $stopped) { throw 'A mismatched staged worker identity did not confirm shutdown.' }
        [void](Stop-MotionModelServicesAfterStagedWorker `
            -StagedWaveShutdownConfirmed $stopped `
            -WarmGvhmrWorker ([pscustomobject]@{}) `
            -SharedLlamaServer ([pscustomobject]@{}))
        if ($script:stoppedModelServices.Count -ne 2) { throw 'Confirmed identity-mismatch cleanup did not stop model dependencies.' }

        Remove-Item -LiteralPath $script:StagedWaveServiceQueueRoot -Recurse -Force
        "STAGED_WORKER_SHUTDOWN_TRI_STATE_OK"
        """
    )
    env = os.environ.copy()
    env["MOTION_WRAPPER_PATH"] = str(wrapper_path)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "STAGED_WORKER_SHUTDOWN_TRI_STATE_OK" in result.stdout


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_docker_runtime_state_retries_transient_container_removal(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"
    fake_docker_dir = tmp_path / "fake-docker"
    fake_docker_dir.mkdir()
    fail_once_marker = tmp_path / "docker-ps-fail-once"
    fail_once_marker.write_text("fail", encoding="utf-8")
    docker_call_log = tmp_path / "docker-calls.log"
    (fake_docker_dir / "docker.cmd").write_text(
        """@echo off
echo %*>>"%FAKE_DOCKER_CALL_LOG%"
if /I "%1"=="inspect" exit /b 1
if /I "%1"=="ps" (
  if exist "%FAKE_DOCKER_PS_FAIL_ONCE%" (
    del "%FAKE_DOCKER_PS_FAIL_ONCE%" >nul
    exit /b 1
  )
  exit /b 0
)
exit /b 1
""",
        encoding="utf-8",
    )
    command = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'Stop'
        $PSNativeCommandUseErrorActionPreference = $true
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
        $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq 'Get-MotionServiceRuntimeState'
        }, $true)
        if ($null -eq $functionAst) { throw 'Get-MotionServiceRuntimeState was not found.' }
        Invoke-Expression $functionAst.Extent.Text
        $owner = [pscustomobject]@{
            kind = 'docker'
            containerId = 'removed-container-id'
            containerName = 'removed-container-name'
        }
        $state = Get-MotionServiceRuntimeState -RuntimeOwner $owner
        if ($state -ne 'stopped') {
            $calls = if (Test-Path $env:FAKE_DOCKER_CALL_LOG) { Get-Content $env:FAKE_DOCKER_CALL_LOG -Raw } else { '<no docker calls>' }
            throw "Expected stopped after a transient Docker query failure, got '$state'. Calls: $calls"
        }
        "TRANSIENT_DOCKER_REMOVAL_RESOLVED=$state"
        """
    )
    env = os.environ.copy()
    env["MOTION_WRAPPER_PATH"] = str(wrapper_path)
    env["FAKE_DOCKER_PS_FAIL_ONCE"] = str(fail_once_marker)
    env["FAKE_DOCKER_CALL_LOG"] = str(docker_call_log)
    env["PATH"] = str(fake_docker_dir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "TRANSIENT_DOCKER_REMOVAL_RESOLVED=stopped" in result.stdout


def test_workout_plan_defer_after_first_attempt_disables_final_rejection_cap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    defer_block = script.split("if ($DeferAfterFirstAttempt)", 1)[1].split("}", 1)[0]

    assert "$MaxFinalOutputRejections = 0" in defer_block
    assert '"--max-final-output-rejections", "$MaxFinalOutputRejections"' in script


def test_workout_plan_defer_keeps_two_reconstruction_attempts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    defer_block = script.split("if ($DeferAfterFirstAttempt)", 1)[1].split("}", 1)[0]
    assert "$MaxReconstructionCandidateAttempts = 2" in defer_block
    assert "$MaxReconstructionCandidateAttempts = 1" not in defer_block
    assert "$FallbackCandidates = 0" in defer_block


def test_workout_plan_hot_path_resume_helpers_are_wired() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    assert "function Test-MotionProcessingResumeReady" in script
    assert "function Optimize-PendingBakeQueue" in script
    assert "Resuming {0} at incomplete motion processing." in script
    assert "Optimize-PendingBakeQueue -Queue $pendingBakeItems" in script
    assert "motionProcessingResumed = $false" in script
    library = (repo_root / "scripts/run_exercise_motion_library.ps1").read_text(encoding="utf-8")
    assert "finish retained processing and advance source cursors" in library


def test_workout_plan_wrapper_mobile_package_output_is_strict_and_completion_gated() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert '[string]$MobilePackageOutputJson = ""' in script
    assert 'Mobile package was not created because these requested exercises are incomplete' in script
    assert '-WorkoutPlanPackageJson $resolvedWorkoutPlanJson' in script
    assert '-MotionSummaryJson $summaryPath' in script
    assert '-OutputJson $resolvedRequestedMobilePackageOutputJson' in script
    assert '-StrictIdMatch' in script


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell policy test requires Windows pwsh")
def test_wrapper_reads_retained_revalidation_version_from_python_authority() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    policy_path = repo_root / "scripts" / "motion_validation_policy.ps1"
    wrapper = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    python_source = (repo_root / "exercise_motion_pkg" / "bake_and_rank.py").read_text(encoding="utf-8")
    version_line = next(
        line for line in python_source.splitlines()
        if line.startswith("RETAINED_SELECTED_REVALIDATION_VERSION =")
    )
    expected_version = int(version_line.partition("=")[2].strip())
    policy_path_literal = str(policy_path).replace("'", "''")
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            f". '{policy_path_literal}'; Get-MotionRetainedSelectedRevalidationVersion",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == expected_version
    assert "$RetainedSelectedRevalidationVersion = Get-MotionRetainedSelectedRevalidationVersion" in wrapper


def test_workout_plan_wrapper_supports_incremental_mobile_packages() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert '[string]$IncrementalMobilePackageOutputJson = ""' in script
    assert 'Update-IncrementalMobilePackage -SuccessfulCount $successfulItems.Count' in script
    assert '-MotionSummaryJson $progressCheckpointPath' in script
    assert '-AllowEmpty' in script


def test_workout_plan_wrapper_defaults_youtube_search_timeout_to_sixty_seconds() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert '[double]$YouTubeSearchTimeoutSeconds = 60.0' in script
    assert '"--youtube-search-timeout-seconds", "$YouTubeSearchTimeoutSeconds"' in script


def test_workout_plan_wrapper_defaults_gvhmr_body_models_to_third_party() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $repoRoot "third_party\\GVHMR\\inputs\\checkpoints\\body_models"' in script
    assert r"C:\Users\gabri\Downloads\GVHMR" not in script


def test_motion_wrappers_always_enable_gvhmr_docker() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for name in (
        "run_exercise_motion_workout_plan.ps1",
        "run_exercise_motion_bake_and_rank.ps1",
        "run_exercise_motion_youtube_bake_and_rank.ps1",
    ):
        script = (repo_root / "scripts" / name).read_text(encoding="utf-8")
        assert '"--use-reconstruction-docker"' in script
        assert '"--reconstruction-docker-image"' in script
        assert '"--reconstruction-docker-gpus"' in script
        assert '"--reconstruction-docker-shm-size"' in script
        assert '[string]$ReconstructionDockerImage = "myworkoutassistant/gvhmr:torch2.3-cu121"' in script
        assert "NoReconstructionDocker" not in script


def test_legacy_warm_worker_retry_requests_supervised_restart() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(encoding="utf-8")
    bake_attempt = script.split("$attemptBakeArguments = @($BakeArguments)", 1)[1].split(
        "$bakeStopwatch.Stop()", 1
    )[0]

    assert '$previousGvhmrLazyStart = $env:EXERCISE_MOTION_GVHMR_LAZY_START' in bake_attempt
    assert 'if ($attemptBakeArguments -contains "--warm-gvhmr-worker")' in bake_attempt
    assert '$env:EXERCISE_MOTION_GVHMR_LAZY_START = "1"' in bake_attempt
    assert '& $PythonCommand @attemptBakeArguments *>> $LogPath' in bake_attempt
    assert "$bakeExitCode = $LASTEXITCODE" in bake_attempt
    assert "finally {" in bake_attempt
    assert "Remove-Item Env:EXERCISE_MOTION_GVHMR_LAZY_START" in bake_attempt
    assert "$env:EXERCISE_MOTION_GVHMR_LAZY_START = $previousGvhmrLazyStart" in bake_attempt


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_builds_mobile_package_directly(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    mobile_package = tmp_path / "workout_plan_with_movements.json"
    incremental_mobile_package = tmp_path / "workout_plan_with_incremental_movements.json"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    plan_payload = json.loads(workout_plan.read_text(encoding="utf-8"))
    plan_payload.update(
        {
            "name": "Generated Plan",
            "workouts": [
                {
                    "workoutComponents": [
                        {
                            "type": "Exercise",
                            "id": "bench",
                            "name": "Barbell Bench Press",
                            "sets": [],
                        }
                    ]
                }
            ],
            "equipments": [],
            "accessoryEquipments": [],
        }
    )
    workout_plan.write_text(json.dumps(plan_payload), encoding="utf-8")
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    env = os.environ.copy()
    env["FAKE_MOTION_ARTIFACT_STATE_CASE"] = "embedded_state_reordered"
    command_arguments_log = tmp_path / "motion_cli_arguments.jsonl"
    env["FAKE_MOTION_CLI_ARGS_LOG"] = str(command_arguments_log)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-MobilePackageOutputJson",
            str(mobile_package),
            "-IncrementalMobilePackageOutputJson",
            str(incremental_mobile_package),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreReconstructionSourceValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    command_arguments = [
        json.loads(line)
        for line in command_arguments_log.read_text(encoding="utf-8").splitlines()
    ]
    assert any("--final-output-validation" in args for args in command_arguments)
    assert all("--skip-final-output-validation" not in args for args in command_arguments)
    assert f"Mobile package updated: 1 approved movement(s) at {incremental_mobile_package}" in result.stdout
    assert f"Mobile workout-plan package: {mobile_package}" in result.stdout
    package = json.loads(mobile_package.read_text(encoding="utf-8"))
    exercise = package["workouts"][0]["workoutComponents"][0]
    assert exercise["movementRef"]["movementId"] == "exercise-motion:bench"
    assert len(package["exerciseMovements"]) == 1
    incremental_package = json.loads(incremental_mobile_package.read_text(encoding="utf-8"))
    incremental_exercise = incremental_package["workouts"][0]["workoutComponents"][0]
    assert incremental_exercise["movementRef"]["movementId"] == "exercise-motion:bench"
    assert len(incremental_package["exerciseMovements"]) == 1


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_pipelines_discovery_and_bake(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-BakeWorkers",
            "1",
            "-DiscoveryWorkers",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "movements ready" in result.stdout
    commands = command_log.read_text(encoding="utf-8").splitlines()
    first_bake_index = commands.index("bake-and-rank")
    assert commands.count("find-youtube-videos") == 3
    assert commands.count("bake-and-rank") == 3
    assert commands.count("prefetch-youtube-sources") == 3
    assert "prefetch-youtube-sources" in commands[:first_bake_index]

    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["processingOrder"] == "pipelined_discovery_source_download_and_bake"
    assert summary["speedProfile"] == "fast"
    assert summary["discoveryWorkers"] == 1
    assert summary["bakeWorkers"] == 1
    assert summary["parallelism"]["llamaCppParallel"] == 6
    assert summary["parallelism"]["llamaCppThreadsHttp"] == 8
    assert summary["parallelism"]["activeDiscoveryWorkerBudget"] == 1
    assert summary["parallelism"]["discoveryVisionLlmWorkers"] == 6
    assert summary["parallelism"]["requestedVisionLlmWorkers"] is None
    assert summary["parallelism"]["reviewLlmWorkers"] == 6
    assert summary["parallelism"]["semanticGateLlmWorkers"] == 6
    assert summary["parallelism"]["segmentClassificationWorkers"] == 6
    assert summary["parallelism"]["visionDownloadWorkers"] == 12
    assert summary["parallelism"]["gpuDiscoveryStages"] == []
    assert summary["parallelism"]["gpuDiscoveryBakeOverlap"] == "allow"
    assert summary["parallelism"]["defaultDiscoveryWorkerCap"] == 4
    assert summary["llamaCppRuntime"]["ctxSize"] == 49152
    assert summary["llamaCppRuntime"]["fitCtx"] == 49152
    assert summary["llamaCppRuntime"]["batchSize"] == 1024
    assert summary["llamaCppRuntime"]["ubatchSize"] == 512
    assert summary["llamaCppRuntime"]["imageMaxTokens"] == 2048
    assert summary["llamaCppRuntime"]["mtmdBatchMaxTokens"] == 768
    assert summary["smplifyEnabled"] is True
    assert summary["effectiveCandidateBudget"]["candidateReviewTargetSuitableCount"] == 2
    assert summary["effectiveCandidateBudget"]["fallbackCandidates"] == 6
    assert [item["status"] for item in summary["exercises"]] == ["completed", "completed", "completed"]
    for exercise in summary["exercises"]:
        exercise_log = Path(exercise["logPath"]).read_text(encoding="utf-8")
        assert "workout-plan movement run started; run id " in exercise_log
        assert "initial discovery attempt 1 finished with exit code 0" in exercise_log
        assert "bake attempt 1 finished with exit code 0; selected 1/1 result(s)" in exercise_log
        assert [attempt["stage"] for attempt in exercise["attempts"]] == [
            "initial_discovery",
            "pre_discovered_candidates",
            "bake",
        ]
        assert exercise["timings"]["discoveryAttempts"] == 1
        assert exercise["timings"]["bakeAttempts"] == 1
        assert exercise["timings"]["selection"]["reconstructionGeneratedCount"] == 1
        assert exercise["timings"]["selection"]["reconstructionRunSeconds"] == pytest.approx(0.02)
        selected = exercise["selectedResults"][0]
        selected_preview_html = Path(selected["selectedPreviewHtmlPath"])
        selected_preview_video = Path(selected["selectedPreviewVideoPath"])
        selected_source_video = Path(selected["selectedSourceVideoPath"])
        selected_interactive_preview_html = Path(selected["selectedInteractivePreviewHtmlPath"])
        selected_skeleton = Path(selected["selectedWearSkeletonPath"])
        html = selected_preview_html.read_text(encoding="utf-8")
        assert selected_interactive_preview_html.exists()
        assert selected_interactive_preview_html.read_text(encoding="utf-8") == "<html>interactive</html>"
        assert (selected_interactive_preview_html.parent / "three.module.0.169.0.js").exists()
        assert selected_interactive_preview_html.name in html
        assert "startSeconds=1.250000" in html
        assert "endSeconds=4.750000" in html
        assert "options=" in html
        assert "%22sceneInverted%22%3Atrue" in html
        assert "%22lockPlantedFeet%22%3Atrue" in html
        assert "%22cameraYawDegrees%22%3A90" in html
        assert "%22cameraPitchDegrees%22%3A35.264389682754654" in html
        assert "%22cameraYawDegrees%22%3A45" not in html
        assert selected_preview_video.name in html
        assert selected_source_video.name in html
        assert selected_skeleton.name in html
        assert "fake_selected" not in html
        retained_audit_dir = Path(selected["selectedSourceAuditDirectory"])
        retained_pose_path = retained_audit_dir / "exact_source_pose_reference.json"
        retained_validation_path = retained_audit_dir / "exact_source_phase_validation.json"
        retained_selection_path = retained_audit_dir / "segment_selection.json"
        assert retained_pose_path.exists()
        assert retained_validation_path.exists()
        assert retained_selection_path.exists()
        retained_validation = json.loads(retained_validation_path.read_text(encoding="utf-8-sig"))
        assert Path(retained_validation["metrics"]["sourcePoseReferencePath"]) == retained_pose_path
        retained_selection = json.loads(retained_selection_path.read_text(encoding="utf-8-sig"))
        assert Path(
            retained_selection["exactSourcePhaseValidation"]["metrics"]["sourcePoseReferencePath"]
        ) == retained_pose_path


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_reports_staged_reconstruction_progress(tmp_path: Path, request) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    env = os.environ.copy()
    env["FAKE_STAGED_IDLE_SECONDS"] = "600"
    command = [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-StagedWaveSize",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
    ]

    queue_root = workspace / "staged-wave-services" / "v1"
    def stop_test_service() -> None:
        state_path = queue_root / "worker_state.json"
        if not state_path.exists():
            return
        (queue_root / "stop.request").write_text("test cleanup", encoding="utf-8")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("status") == "stopped":
                    return
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.05)

    request.addfinalizer(stop_test_service)
    first_stdout_path = tmp_path / "wrapper-first.stdout.log"
    first_stderr_path = tmp_path / "wrapper-first.stderr.log"
    with first_stdout_path.open("w", encoding="utf-8") as stdout, first_stderr_path.open("w", encoding="utf-8") as stderr:
        first_result = subprocess.run(
            command,
            cwd=repo_root,
            env=env,
            text=True,
            stdout=stdout,
            stderr=stderr,
            timeout=60,
            check=False,
        )
    first_stdout = first_stdout_path.read_text(encoding="utf-8")
    first_stderr = first_stderr_path.read_text(encoding="utf-8")
    assert first_result.returncode == 0, first_stdout + first_stderr
    assert "Extracting: 0/1 done" in first_stdout
    assert "1 run" in first_stdout
    first_state = json.loads((queue_root / "worker_state.json").read_text(encoding="utf-8"))
    assert first_state["status"] == "idle"

    second_stdout_path = tmp_path / "wrapper-second.stdout.log"
    second_stderr_path = tmp_path / "wrapper-second.stderr.log"
    with second_stdout_path.open("w", encoding="utf-8") as stdout, second_stderr_path.open("w", encoding="utf-8") as stderr:
        second_result = subprocess.run(
            command,
            cwd=repo_root,
            env=env,
            text=True,
            stdout=stdout,
            stderr=stderr,
            timeout=60,
            check=False,
        )
    assert second_result.returncode == 0, second_stdout_path.read_text(encoding="utf-8") + second_stderr_path.read_text(encoding="utf-8")
    second_state = json.loads((queue_root / "worker_state.json").read_text(encoding="utf-8"))
    assert second_state["pid"] == first_state["pid"]
    assert second_state["processIdentity"] == first_state["processIdentity"]
    assert second_state["status"] == "idle"

    stop_test_service()


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_routes_ambiguous_recovery_to_inspection_without_retry(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    direct_bake_log = tmp_path / "direct_bake_commands.log"
    env = os.environ.copy()
    env["FAKE_STAGED_IDLE_SECONDS"] = "600"
    env["FAKE_STAGED_AMBIGUOUS_RECOVERY"] = "1"
    env["FAKE_MOTION_DIRECT_BAKE_LOG"] = str(direct_bake_log)
    command = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
        "-AllowDirtyWorktree",
        "-WorkoutPlanJson",
        str(workout_plan),
        "-WorkspaceRoot",
        str(workspace),
        "-BodyModelRoot",
        str(body_models),
        "-PythonCommand",
        str(fake_cmd),
        "-StagedWaveSize",
        "1",
        "-ProgressIntervalSeconds",
        "1",
        "-SkipVisionRanking",
        "-SkipSemanticGate",
        "-SkipLlamaCppQueryPlanner",
        "-SkipPosePrefilter",
        "-SkipPreReconstructionSourceValidation",
        "-SkipFinalOutputValidation",
    ]

    queue_root = workspace / "staged-wave-services" / "v1"

    def stop_test_service() -> None:
        state_path = queue_root / "worker_state.json"
        if not state_path.exists():
            return
        (queue_root / "stop.request").write_text("test cleanup", encoding="utf-8")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("status") == "stopped":
                    return
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.05)

    stdout_path = tmp_path / "ambiguous-wrapper.stdout.log"
    stderr_path = tmp_path / "ambiguous-wrapper.stderr.log"
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            result = subprocess.run(
                command,
                cwd=repo_root,
                env=env,
                text=True,
                stdout=stdout,
                stderr=stderr,
                timeout=60,
                check=False,
            )
    finally:
        stop_test_service()

    stdout_text = stdout_path.read_text(encoding="utf-8")
    stderr_text = stderr_path.read_text(encoding="utf-8")
    assert result.returncode == 0, stdout_text + stderr_text
    assert "Needs inspection:" in stdout_text
    assert "insufficient free storage" not in stdout_text.lower()
    assert not direct_bake_log.exists() or direct_bake_log.read_text(encoding="utf-8").strip() == ""

    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    exercise = summary["exercises"][0]
    assert exercise["status"] == "needs_operator_inspection"
    assert exercise["stage"] == "staged_wave_recovery"
    assert exercise["exitCode"] == 76
    assert "not retried automatically" in exercise["error"]
    consumed_results = list((queue_root / "consumed").glob("*.json"))
    assert len(consumed_results) == 1
    assert json.loads(consumed_results[0].read_text(encoding="utf-8"))["status"] == "ambiguous_recovery"
    assert not list((queue_root / "results").glob("*.json"))


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_reuses_exact_unchanged_candidate_prefetch(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)
    command = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
        "-AllowDirtyWorktree",
        "-WorkoutPlanJson",
        str(workout_plan),
        "-WorkspaceRoot",
        str(workspace),
        "-BodyModelRoot",
        str(body_models),
        "-PythonCommand",
        str(fake_cmd),
        "-CpuPrefetchDuringBake",
        "-SkipVisionRanking",
        "-SkipSemanticGate",
        "-SkipLlamaCppQueryPlanner",
        "-SkipPosePrefilter",
        "-SkipPreReconstructionSourceValidation",
        "-SkipFinalOutputValidation",
    ]

    first = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert first_commands.count("find-youtube-videos") == 2

    second = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    all_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert all_commands.count("find-youtube-videos") == 3
    assert "reused unchanged CPU/network candidate prefetch" in (
        workspace / "bench" / "bake.log"
    ).read_text(encoding="utf-8")
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["exercises"][0]["timings"]["prefetchReused"] is True
    assert summary["exercises"][0]["timings"]["prefetchSeconds"] == pytest.approx(0.0)

    changed = subprocess.run(
        [*command, "-ResultsPerQuery", "99"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert changed.returncode == 0, changed.stdout + changed.stderr
    changed_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert changed_commands.count("find-youtube-videos") == 5
    changed_summary = json.loads(
        (workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8")
    )
    assert changed_summary["exercises"][0]["timings"]["prefetchReused"] is False


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_resumes_from_durable_discovery_source_downloads_and_bake(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)
    command = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
        "-AllowDirtyWorktree",
        "-WorkoutPlanJson",
        str(workout_plan),
        "-WorkspaceRoot",
        str(workspace),
        "-BodyModelRoot",
        str(body_models),
        "-PythonCommand",
        str(fake_cmd),
        "-ArtifactRetention",
        "full",
        "-SkipVisionRanking",
        "-SkipSemanticGate",
        "-SkipLlamaCppQueryPlanner",
        "-SkipPosePrefilter",
        "-SkipPreReconstructionSourceValidation",
        "-SkipFinalOutputValidation",
    ]

    first = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert first_commands.count("find-youtube-videos") == 1
    assert first_commands.count("prefetch-youtube-sources") == 1
    assert first_commands.count("bake-and-rank") == 1

    second = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    second_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert second_commands.count("find-youtube-videos") == 1
    assert second_commands.count("prefetch-youtube-sources") == 1
    assert second_commands.count("bake-and-rank") == 1
    second_summary = json.loads(
        (workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8")
    )
    timings = second_summary["exercises"][0]["timings"]
    assert timings["bakeReused"] is True

    source_report = json.loads(
        (workspace / "bench" / "youtube_source_prefetch.json").read_text(encoding="utf-8")
    )
    Path(source_report["results"][0]["path"]).unlink()
    third = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert third.returncode == 0, third.stdout + third.stderr
    third_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert third_commands.count("find-youtube-videos") == 1
    assert third_commands.count("prefetch-youtube-sources") == 1
    assert third_commands.count("bake-and-rank") == 1

    fresh = subprocess.run(
        [*command, "-DisableStageResume"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    fresh_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert fresh_commands.count("find-youtube-videos") == 2
    assert fresh_commands.count("prefetch-youtube-sources") == 2
    assert fresh_commands.count("bake-and-rank") == 2


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_staged_wave_timeline_marks_only_accepted_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"
    command = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
        $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq 'Add-StagedWaveTimelineOutcome'
        }, $true)
        if ($null -eq $functionAst) { throw 'Add-StagedWaveTimelineOutcome was not found.' }
        $productionCall = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
                $node.GetCommandName() -eq 'Add-StagedWaveTimelineOutcome'
        }, $true)
        if ($null -eq $productionCall) { throw 'The staged-wave production path does not record its timeline outcome.' }
        Invoke-Expression $functionAst.Extent.Text

        function Get-ObjectProperty {
            param([object]$Object, [string]$Name)
            if ($null -eq $Object) { return $null }
            if ($Object -is [System.Collections.IDictionary]) { return $Object[$Name] }
            $property = $Object.PSObject.Properties[$Name]
            if ($null -eq $property) { return $null }
            return $property.Value
        }
        function Add-SchedulerTimelineItemEvent {
            param([object]$WorkItem, [switch]$MarkAccepted, [string]$FinalStatus)
            $script:events += [pscustomobject]@{
                slug = $WorkItem.exerciseSlug
                markedAccepted = [bool]$MarkAccepted
                finalStatus = $FinalStatus
            }
        }

        $script:events = @()
        $item = [pscustomobject]@{ exerciseSlug = 'press' }
        Add-StagedWaveTimelineOutcome -WorkItem $item -WaveState ([pscustomobject]@{
            artifactLifecycle = [pscustomobject]@{ state = 'accepted' }
        })
        Add-StagedWaveTimelineOutcome -WorkItem $item -WaveState ([pscustomobject]@{
            artifactLifecycle = [pscustomobject]@{ state = 'manual_review' }
        })
        Add-StagedWaveTimelineOutcome -WorkItem $item -WaveState ([pscustomobject]@{})
        if (-not $script:events[0].markedAccepted -or $script:events[0].finalStatus -ne 'accepted') {
            throw 'An accepted staged artifact was not recorded as accepted.'
        }
        if ($script:events[1].markedAccepted -or $script:events[1].finalStatus -ne 'needs_manual_review') {
            throw 'A manual-review staged artifact was marked as accepted.'
        }
        if ($script:events[2].markedAccepted -or $script:events[2].finalStatus -ne 'unverified_completion') {
            throw 'A staged artifact with missing lifecycle state was marked as accepted.'
        }
        "STAGED_WAVE_TIMELINE_ACCEPTANCE_OK"
        """
    )
    env = os.environ.copy()
    env["MOTION_WRAPPER_PATH"] = str(wrapper_path)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "STAGED_WAVE_TIMELINE_ACCEPTANCE_OK" in result.stdout


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_staged_wave_producer_retries_if_idle_worker_closed_admission(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"
    command = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
        $functionAsts = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -in @('Get-StagedWaveAdmissionMutexNames', 'Invoke-WithStagedWaveAdmissionLock', 'Publish-StagedBakeQueueRequest')
        }, $true)
        if ($functionAsts.Count -ne 3) { throw 'Staged-wave admission functions were not found.' }
        foreach ($functionAst in $functionAsts) { Invoke-Expression $functionAst.Extent.Text }

        $script:ensureCount = 0
        $script:stateReadCount = 0
        $script:serviceState = [pscustomobject]@{
            healthy = $true
            processState = 'running'
            matchingProcess = $true
            state = [pscustomobject]@{ status = 'idle' }
        }
        function Ensure-StagedBakeQueueService {
            param([int]$MaxWaveItems)
            $script:ensureCount += 1
            if ($script:ensureCount -ge 2) {
                $script:serviceState.healthy = $true
                $script:serviceState.processState = 'running'
                $script:serviceState.matchingProcess = $true
                $script:serviceState.state.status = 'idle'
            }
        }
        function Get-StagedBakeQueueServiceState {
            param([string]$QueueRoot)
            $script:stateReadCount += 1
            if ($script:stateReadCount -eq 1) {
                return [pscustomobject]@{
                    healthy = $false
                    processState = 'running'
                    matchingProcess = $true
                    state = [pscustomobject]@{ status = 'stopping' }
                }
            }
            return $script:serviceState
        }

        $queueRoot = Join-Path $env:TEMP ('motion-admission-test-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $queueRoot | Out-Null
        $temporaryPath = Join-Path $queueRoot 'request.json.tmp'
        $requestPath = Join-Path $queueRoot 'request.json'
        '{"requestId":"request-1"}' | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Publish-StagedBakeQueueRequest `
            -QueueRoot $queueRoot `
            -MaxWaveItems 1 `
            -RequestTemporaryPath $temporaryPath `
            -RequestPath $requestPath
        if ($script:ensureCount -ne 2 -or $script:stateReadCount -ne 2) {
            throw 'The producer did not re-ensure the worker after observing the stopping generation.'
        }
        if (-not (Test-Path -LiteralPath $requestPath) -or (Test-Path -LiteralPath $temporaryPath)) {
            throw 'The request was not atomically published after the replacement worker was healthy.'
        }
        Remove-Item -LiteralPath $queueRoot -Recurse -Force
        'STAGED_WAVE_ADMISSION_RETRY_OK'
        """
    )
    env = os.environ.copy()
    env["MOTION_WRAPPER_PATH"] = str(wrapper_path)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "STAGED_WAVE_ADMISSION_RETRY_OK" in result.stdout


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_staged_service_restarts_after_source_identity_worker_exit(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"
    command = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
        $function = $ast.Find({ param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq 'Ensure-StagedBakeQueueService'
        }, $true)
        if ($null -eq $function) { throw 'Ensure-StagedBakeQueueService was not found.' }
        Invoke-Expression $function.Extent.Text

        $script:StagedWaveServiceQueueRoot = $env:MOTION_TEST_ROOT
        $script:MotionSourceIdentityFingerprint = 'new-source'
        $script:PythonCommand = 'python.exe'
        $script:repoRoot = $env:MOTION_REPO_ROOT
        $script:stateReadCount = 0
        $script:startCount = 0
        $oldProcess = [pscustomobject]@{}
        $oldProcess | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param([int]$Milliseconds) return $true }
        function Get-StagedBakeServiceConfigurationFingerprint { return 'same-configuration' }
        function Get-StagedBakeQueueServiceState {
            param([string]$QueueRoot)
            $script:stateReadCount += 1
            if ($script:stateReadCount -eq 1) {
                return [pscustomobject]@{
                    healthy = $true; processState = 'running'; matchingProcess = $true
                    state = [pscustomobject]@{ pid = 79216; status = 'idle'; sourceIdentityFingerprint = 'old-source'; serviceConfigurationFingerprint = 'same-configuration' }
                    process = $oldProcess
                }
            }
            return [pscustomobject]@{
                healthy = $false; processState = 'stopped'; matchingProcess = $false
                state = [pscustomobject]@{ pid = 79216; status = 'stopped' }; process = $null
            }
        }
        function Start-StagedBakeQueueServiceGeneration { $script:startCount += 1 }

        foreach ($directoryName in @('requests', 'processing', 'results', 'ambiguous', 'cancelled_runs')) {
            New-Item -ItemType Directory -Force -Path (Join-Path $script:StagedWaveServiceQueueRoot $directoryName) | Out-Null
        }
        Ensure-StagedBakeQueueService -MaxWaveItems 1
        if ($script:stateReadCount -ne 2 -or $script:startCount -ne 1) {
            throw 'A confirmed worker exit did not start a replacement generation.'
        }
        'STAGED_SERVICE_SOURCE_RESTART_OK'
        """
    )
    env = os.environ.copy()
    env["MOTION_WRAPPER_PATH"] = str(wrapper_path)
    env["MOTION_TEST_ROOT"] = str(tmp_path / "queue")
    env["MOTION_REPO_ROOT"] = str(repo_root)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "STAGED_SERVICE_SOURCE_RESTART_OK" in result.stdout


def test_motion_runner_writes_owned_partial_outcome_and_library_rejects_stale_summary(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    command = r'''
    $ErrorActionPreference = 'Stop'
    $runnerPath = Join-Path $env:MOTION_REPORT_TEST_ROOT 'scripts/run_exercise_motion_workout_plan.ps1'
    $libraryPath = Join-Path $env:MOTION_REPORT_TEST_ROOT 'scripts/run_exercise_motion_library.ps1'
    $tokens = $null; $errors = $null
    $runnerAst = [System.Management.Automation.Language.Parser]::ParseFile($runnerPath, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw $errors[0] }
    $libraryAst = [System.Management.Automation.Language.Parser]::ParseFile($libraryPath, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw $errors[0] }
    foreach ($name in @('Write-JsonAtomically', 'Write-EarlyMotionRunOutcomeSummary', 'Write-RunOutcomeArtifacts')) {
        $functionAst = $runnerAst.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true)
        if (-not $functionAst) { throw "Missing $name" }
        . ([scriptblock]::Create($functionAst.Extent.Text))
    }
    function Write-ProgressCheckpoint { }
    $testRoot = $env:MOTION_REPORT_TEST_ROOT_TEMP
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
    try {
        $script:movementRunId = 'current-run'
        $script:movementRunStartedAtUtc = '2026-10-23T10:00:00Z'
        $script:LibraryRunId = 'library-run'
        $script:inputIdentitySha256 = 'current-input-sha'
        $script:definitionsInputSha256 = 'definitions-sha'
        $script:effectiveWorkoutPlanInputSha256 = 'effective-plan-sha'
        $script:earlyRunTargetCount = 4
        $script:MotionSourceIdentity = @{ schemaVersion = 1 }
        $script:resolvedWorkoutPlanJson = 'input.json'
        $script:resolvedWorkspaceRoot = $testRoot
        $script:workItems = @([pscustomobject]@{}, [pscustomobject]@{}, [pscustomobject]@{})
        $script:summaryByIndex = @{ 0 = [pscustomobject]@{status='needs_definition_review'; exerciseName='A'} }
        $script:summaryPath = Join-Path $testRoot 'workout_motion_generation_summary.json'
        $script:progressCheckpointPath = Join-Path $testRoot 'workout_motion_generation_checkpoint.json'
        $script:MotionRunOutcome = 'running'
        @{ runId='foreign-run'; exercises=@(@{status='completed'}) } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath
        Write-EarlyMotionRunOutcomeSummary -Outcome 'running'
        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        if ($summary.runId -ne 'current-run' -or $summary.outcome -ne 'running' -or $summary.totalExerciseCount -ne 4 -or $summary.pendingExerciseCount -ne 4 -or $summary.terminalExerciseCount -ne 0) { throw 'Early run envelope did not preserve the selected target count as pending' }
        Write-EarlyMotionRunOutcomeSummary -Outcome 'failed'
        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        if ($summary.runId -ne 'current-run' -or $summary.outcome -ne 'failed' -or $summary.pendingExerciseCount -ne 4 -or [string]::IsNullOrWhiteSpace($summary.failedAtUtc)) { throw 'Early startup failure did not update only the current run envelope' }
        $runnerSource = Get-Content -LiteralPath $runnerPath -Raw
        $initialEnvelopeIndex = $runnerSource.IndexOf('Write-EarlyMotionRunOutcomeSummary -Outcome "running"')
        $sharedServerStartIndex = $runnerSource.IndexOf('Start-SharedLlamaServer -SessionDir $resolvedSharedLlamaServerSessionDir')
        if ($initialEnvelopeIndex -lt 0 -or $sharedServerStartIndex -lt 0 -or $initialEnvelopeIndex -ge $sharedServerStartIndex) { throw 'Initial run envelope is written after shared llama server startup' }
        Write-RunOutcomeArtifacts -Outcome 'stopped'
        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        if ($summary.runId -ne 'current-run' -or $summary.outcome -ne 'stopped') { throw 'Partial summary lost run identity/outcome' }
        if ($summary.totalExerciseCount -ne 3 -or $summary.terminalExerciseCount -ne 1 -or $summary.pendingExerciseCount -ne 2) { throw 'Partial summary counts are not checkpoint-derived' }
        if ($summary.completedAtUtc -ne $null -or [string]::IsNullOrWhiteSpace($summary.stoppedAtUtc)) { throw 'Stopped outcome timestamps are mislabeled' }
        if (@(Get-ChildItem $testRoot -Filter '*.previous-*.json').Count -ne 1) { throw 'Foreign summary was not preserved before replacement' }
        $script:summaryByIndex[1] = [pscustomobject]@{status='needs_source_review'; exerciseName='B'}
        Write-RunOutcomeArtifacts -Outcome 'stopped'
        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        if ($summary.terminalExerciseCount -ne 2 -or $summary.pendingExerciseCount -ne 1 -or $summary.exercises.Count -ne 2) { throw 'Same-run stopped summary did not refresh from the latest checkpoint' }
        $librarySource = Get-Content -LiteralPath $libraryPath -Raw
        if ($librarySource -notmatch 'passSummary\.runId -eq \$passRunId' -or $librarySource -notmatch 'passSummary\.inputIdentitySha256 -eq \$libraryInputIdentitySha256' -or $librarySource -notmatch 'passSummary\.effectiveDefinitionPlanSha256 -eq \$definitionEffectivePlanSha256' -or $librarySource -notmatch '"-InputIdentitySha256", \$libraryInputIdentitySha256') { throw 'Library runner does not reject stale pass artifacts or pass the authoritative input identity' }
        if ($librarySource.IndexOf('$existingState.signature') -gt $librarySource.IndexOf('Write-RunState -Phase "initialized"')) { throw 'Library overwrites the prior phase before deciding whether pass one is reusable' }
        $runnerSource = Get-Content -LiteralPath $runnerPath -Raw
        if ($runnerSource -notmatch 'source_support_contact_evidence_unavailable' -or $runnerSource -notmatch 'bakeAttemptCount = \[int\]\$waveItem\.bakeAttemptCount \+ 1' -or $runnerSource -notmatch 'reconstructionGeneratedCount' -or $runnerSource -notmatch 'finalValidationDiagnosticSeconds') { throw 'Staged-wave metrics/failure owner are not preserved' }
    } finally { Remove-Item -LiteralPath $testRoot -Recurse -Force }
    '''
    result = subprocess.run(
        ['pwsh', '-NoProfile', '-Command', command],
        env={**os.environ, 'MOTION_REPORT_TEST_ROOT': str(repo), 'MOTION_REPORT_TEST_ROOT_TEMP': str(tmp_path / 'motion-reporting')},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_publishes_manual_review_fallback(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    env = os.environ.copy()
    env["FAKE_MOTION_MANUAL_REVIEW"] = "1"

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-BakeWorkers",
            "1",
            "-DiscoveryWorkers",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    exercise = summary["exercises"][0]
    assert exercise["status"] == "needs_manual_review"
    assert exercise["timings"]["discoveryAttempts"] <= 2
    manual_review_dir = workspace / "bench" / "manual-review"
    assert Path(exercise["selectionManifestPath"]) == manual_review_dir / "selection_manifest.json"
    assert Path(exercise["selectedWearSkeletonPath"]).exists()
    assert Path(exercise["selectedPreviewVideoPath"]).exists()
    assert Path(exercise["selectedPreviewHtmlPath"]).exists()
    assert Path(exercise["selectedSourceVideoPath"]).exists()
    html = Path(exercise["selectedPreviewHtmlPath"]).read_text(encoding="utf-8")
    timeline = json.loads((workspace / "scheduler_timeline.json").read_text(encoding="utf-8"))
    assert len(timeline["items"]) == 1
    timeline_item = timeline["items"][0]
    assert timeline_item["firstAcceptedAtUtc"] is None
    assert timeline_item["materializedAtUtc"] is None
    assert timeline_item["finalStatus"] == "needs_manual_review"
    assert "Manual review" in html
    assert Path(exercise["selectedPreviewVideoPath"]).name in html
    assert Path(exercise["selectedSourceVideoPath"]).name in html


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
@pytest.mark.parametrize(
    ("artifact_state_case", "manual_review"),
    [
        ("missing_full_clip_lineage", False),
        ("embedded_state_mismatch", False),
        ("embedded_state_corrupt", False),
        ("missing_embedded_state", False),
        ("missing_embedded_state", True),
    ],
)
def test_workout_plan_wrapper_rejects_invalid_packaged_artifact_state(
    tmp_path: Path,
    artifact_state_case: str,
    manual_review: bool,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    prepared_candidates_manifest = write_prepared_candidates_manifest(
        tmp_path,
        fake_cli,
        workout_plan,
    )
    env = os.environ.copy()
    env["FAKE_MOTION_ARTIFACT_STATE_CASE"] = artifact_state_case
    if manual_review:
        env["FAKE_MOTION_MANUAL_REVIEW"] = "1"

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-PreparedCandidatesManifest",
            str(prepared_candidates_manifest),
            "-BakeWorkers",
            "1",
            "-DiscoveryWorkers",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPosePrefilter",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    if manual_review:
        assert result.returncode != 0
        assert "Selected skeleton is missing its persisted artifact state." in result.stdout + result.stderr
        return

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    exercise = summary["exercises"][0]
    assert exercise["status"] == "failed"
    assert exercise["stage"] == "selected_output_parity"
    assert exercise["selectedResults"] == []


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_avoids_cuda_discovery_overlap_with_bake_by_default(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=2)
    fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    prepared_candidates_manifest = write_prepared_candidates_manifest(
        tmp_path,
        fake_cli,
        workout_plan,
    )
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-PreparedCandidatesManifest",
            str(prepared_candidates_manifest),
            "-ProgressIntervalSeconds",
            "1",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["processingOrder"] == "pipelined_discovery_source_download_and_bake"
    assert summary["discoveryWorkers"] == 1
    assert summary["bakeWorkers"] == 1
    assert summary["parallelism"]["gpuDiscoveryStages"] == ["yolo_pose_prefilter"]
    assert summary["parallelism"]["globalGpuLockEnabled"] is True
    assert summary["parallelism"]["gpuDiscoveryBakeOverlap"] == "avoid"
    assert summary["parallelism"]["defaultDiscoveryWorkerCap"] == 1
    for exercise_workspace in workspace.iterdir():
        if not exercise_workspace.is_dir() or not (exercise_workspace / "bake.log").exists():
            continue
        assert "installed prepared candidates; skipping discovery and source download" in (
            exercise_workspace / "bake.log"
        ).read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_prepared_candidates_do_not_fall_back_to_live_discovery_after_rejection(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    plan_payload = json.loads(workout_plan.read_text(encoding="utf-8"))
    current_motion_context = {
        "exerciseType": "Strength",
        "primaryEquipment": {
            "id": "barbell-1",
            "type": "barbell",
            "name": "Barbell",
            "capabilities": ["loadable_plates"],
        },
    }
    plan_payload["exercises"][0]["motionContext"] = current_motion_context
    workout_plan.write_text(json.dumps(plan_payload), encoding="utf-8")
    fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    prepared_candidates_manifest = write_prepared_candidates_manifest(
        tmp_path,
        fake_cli,
        workout_plan,
    )
    command_log = tmp_path / "commands.log"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)
    env["FAKE_MOTION_MANUAL_REVIEW"] = "1"

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-PreparedCandidatesManifest",
            str(prepared_candidates_manifest),
            "-StagedWaveSize",
            "1",
            "-ProgressIntervalSeconds",
            "1",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert "bake-and-rank" in commands
    assert "find-youtube-videos" not in commands
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["exercises"][0]["status"] == "no_selection"
    wave_manifests = list((workspace / "staged-waves").glob("*/wave_manifest.json"))
    assert len(wave_manifests) == 1
    wave_item = json.loads(wave_manifests[0].read_text(encoding="utf-8"))["items"][0]
    exercise_plan_path = Path(wave_item["exercisePlanJson"])
    exercise_plan = json.loads(exercise_plan_path.read_text(encoding="utf-8"))
    assert exercise_plan["exercises"][0]["motionContext"] == current_motion_context


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_wrapper_rejects_non_cuda_pose_prefilter_device(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson",
            str(workout_plan),
            "-WorkspaceRoot",
            str(workspace),
            "-BodyModelRoot",
            str(body_models),
            "-PythonCommand",
            str(fake_cmd),
            "-PosePrefilterDevice",
            "cpu",
            "-SkipVisionRanking",
            "-SkipSemanticGate",
            "-SkipLlamaCppQueryPlanner",
            "-SkipPreReconstructionSourceValidation",
            "-SkipFinalOutputValidation",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "YOLO pose prefilter must use CUDA" in result.stdout + result.stderr


def test_staged_fallback_retries_rotate_between_exercises() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(
        encoding="utf-8"
    )

    assert "YieldAfterUnsuccessfulBake" in script
    assert 'status = "retry_pending"' in script
    assert "$pendingLegacyBakeItems.Enqueue($retryWorkItem)" in script
    assert "individualRetryPassCount" in script


def test_workout_plan_wrapper_preserves_bake_attempt_manifests() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts/run_exercise_motion_workout_plan.ps1").read_text(
        encoding="utf-8"
    )

    assert "Save-AttemptSelectionManifest" in script
    assert "best_no_selection_manifest.json" in script
    assert "Restore-BestNoSelectionManifest" in script


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="Windows PowerShell startup guard")
@pytest.mark.parametrize("owner", ["cancelled", "uncancelled", "live"])
def test_startup_recovers_only_dead_staged_claims(tmp_path: Path, owner: str) -> None:
    root = tmp_path / "workspace"
    queue = root / "staged-wave-services" / "v1"
    (queue / "processing").mkdir(parents=True)
    request = {"requestId": "old-request", "waveId": "old-wave", "runId": "old-run"}
    claim = queue / "processing" / "old-request.json"
    claim.write_text(json.dumps(request), encoding="utf-8")
    if owner != "uncancelled":
        (queue / "cancelled_runs").mkdir()
        (queue / "cancelled_runs" / "old-run.json").write_text("{}")
    wrapper = Path(__file__).resolve().parents[1] / "scripts/run_exercise_motion_workout_plan.ps1"
    command = r"""
    $ErrorActionPreference = 'Stop'
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$null, [ref]$errors)
    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-StagedWaveWorkspaceIsQuiescent' }, $true)
    . ([scriptblock]::Create($node.Extent.Text))
    function Invoke-WithStagedWaveAdmissionLock { param($QueueRoot, $Operation) & $Operation }
    function Get-StagedBakeQueueServiceState {
        param($QueueRoot)
        [pscustomobject]@{ processState = $(if ($env:MOTION_OWNER -eq 'live') {'running'} else {'stopped'});
            matchingProcess = ($env:MOTION_OWNER -eq 'live'); healthy = $true;
            state = [pscustomobject]@{ status = 'running'; currentRequestId='old-request'; currentWaveId='old-wave' } }
    }
    $PythonCommand = $env:MOTION_TEST_PYTHON
    Assert-StagedWaveWorkspaceIsQuiescent -WorkspaceRoot $env:MOTION_TEST_WORKSPACE
    """
    environment = dict(os.environ, MOTION_WRAPPER_PATH=str(wrapper), MOTION_TEST_WORKSPACE=str(root),
                       MOTION_TEST_PYTHON=sys.executable, MOTION_OWNER=owner)
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], env=environment,
                            cwd=wrapper.parents[1], capture_output=True, text=True, timeout=30)
    if owner == "cancelled":
        assert result.returncode == 0, result.stdout + result.stderr
        assert not claim.exists()
        terminal = json.loads((queue / "results" / "old-request.json").read_text())
        assert terminal["status"] == "cancelled"
        assert json.loads((queue / "consumed" / "old-request.request.json").read_text()) == request
    else:
        assert result.returncode != 0
        assert "Resolve this queue" in result.stdout + result.stderr
        assert (claim if owner == "live" else queue / "ambiguous" / claim.name).is_file()


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_definition_preflight_blocks_all_unresolved_before_model_work(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workout_plan = write_workout_plan(tmp_path, exercise_count=2)
    approved_registry = tmp_path / "approved_definitions.json"
    approved_registry.write_text(json.dumps({"schemaVersion": 1, "exercises": []}), encoding="utf-8")
    workspace = tmp_path / "workspace"
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "cli_commands.txt"
    env = os.environ.copy()
    env["FAKE_MOTION_DEFINITION_STATUS"] = "needs_definition_review"
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree",
            "-WorkoutPlanJson", str(workout_plan),
            "-ApprovedExerciseDefinitionsJson", str(approved_registry),
            "-WorkspaceRoot", str(workspace),
            "-PythonCommand", str(fake_cmd),
            "-SharedLlamaServer",
            "-LlamaCppServerCommand", str(fake_cmd),
            "-LlamaCppServerStartupTimeoutSeconds", "1",
            "-SkipVisionRanking", "-SkipSemanticGate", "-SkipLlamaCppQueryPlanner", "-SkipPosePrefilter",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == ["list-workout-plan-exercises"]
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in summary["exercises"]] == [
        "needs_definition_review", "needs_definition_review",
    ]
    readiness_report = json.loads((workspace / "definition_readiness_report.json").read_text(encoding="utf-8"))
    assert readiness_report["readyCount"] == 0
    assert readiness_report["unresolvedCount"] == 2
    effective_plan = Path(readiness_report["effectivePlanPath"])
    assert effective_plan == workspace / "effective_workout_plan.json"
    assert effective_plan.is_file()


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_exhausted_source_budget_stops_before_new_discovery(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "cli_commands.txt"
    env = os.environ.copy()
    env["FAKE_MOTION_SOURCE_BUDGET_STATUS"] = "needs_source_review"
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
            "-AllowDirtyWorktree", "-WorkoutPlanJson", str(workout_plan),
            "-WorkspaceRoot", str(workspace), "-BodyModelRoot", str(body_models),
            "-PythonCommand", str(fake_cmd), "-SharedLlamaServer",
            "-LlamaCppServerCommand", str(fake_cmd), "-LlamaCppServerStartupTimeoutSeconds", "1",
            "-SkipSemanticGate", "-SkipLlamaCppQueryPlanner", "-SkipPosePrefilter",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == ["list-workout-plan-exercises"]
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["exercises"][0]["status"] == "needs_source_review"
    assert "source_turn_attempt_budget" in summary["exercises"][0]["error"]


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_exhausted_source_budget_preserves_approved_selected_cache(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workout_plan = write_workout_plan(tmp_path, exercise_count=1)
    workspace = tmp_path / "workspace"
    body_models = tmp_path / "GVHMR" / "inputs" / "checkpoints" / "body_models"
    body_models.mkdir(parents=True)
    _fake_cli, fake_cmd = write_fake_motion_cli(tmp_path)
    command_log = tmp_path / "cli_commands.txt"
    env = os.environ.copy()
    env["FAKE_MOTION_CLI_LOG"] = str(command_log)
    env["FAKE_MOTION_SOURCE_CLEARANCE"] = "1"

    command = [
        "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"),
        "-AllowDirtyWorktree", "-WorkoutPlanJson", str(workout_plan),
        "-WorkspaceRoot", str(workspace), "-BodyModelRoot", str(body_models),
        "-PythonCommand", str(fake_cmd), "-SkipVisionRanking", "-SkipSemanticGate",
        "-SkipLlamaCppQueryPlanner", "-SkipPosePrefilter", "-SkipPreReconstructionSourceValidation",
        "-SkipFinalOutputValidation", "-NoExerciseMotionContract",
    ]
    first = subprocess.run(command, cwd=repo_root, env=env, text=True, capture_output=True, timeout=60, check=False)
    assert first.returncode == 0, first.stdout + first.stderr

    command_log.write_text("", encoding="utf-8")
    env["FAKE_MOTION_SOURCE_BUDGET_STATUS"] = "needs_source_review"
    second = subprocess.run(
        [*command, "-ReuseExistingSelected"], cwd=repo_root, env=env, text=True,
        capture_output=True, timeout=60, check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == ["list-workout-plan-exercises"]
    summary = json.loads((workspace / "workout_motion_generation_summary.json").read_text(encoding="utf-8"))
    assert summary["exercises"][0]["status"] == "completed"
    assert summary["exercises"][0]["reusedExistingSelected"] is True


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell wrapper test requires Windows pwsh")
def test_workout_plan_discovery_child_receives_effective_definition_context(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = repo_root / "scripts" / "run_exercise_motion_workout_plan.ps1"
    output_path = tmp_path / "exercise_plan.json"
    command = r"""
    $ErrorActionPreference = 'Stop'
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOTION_WRAPPER_PATH, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $function = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'New-OneExercisePlanJson'
    }, $true)
    . ([scriptblock]::Create($function.Extent.Text))
    $resolvedWorkoutPlanJson = $env:MOTION_SOURCE_PLAN
    $exercise = [pscustomobject]@{
        exerciseId = 'bench'; exerciseName = 'Barbell Bench Press'
        motionContext = @{ exerciseDefinition = @{ definingAction = 'Press bar from chest to full elbow extension.' } }
        definitionReadiness = @{ status = 'ready'; definitionSource = 'approved_registry' }
    }
    New-OneExercisePlanJson -Exercise $exercise -OutPath $env:MOTION_CHILD_PLAN
    $child = Get-Content -LiteralPath $env:MOTION_CHILD_PLAN -Raw | ConvertFrom-Json
    if ($child.sourcePlanPath -ne $env:MOTION_SOURCE_PLAN) { throw 'Child plan lost original source provenance.' }
    if ($child.exercises[0].motionContext.exerciseDefinition.definingAction -notlike 'Press bar*') { throw 'Child plan lost approved motion context.' }
    if ($child.exercises[0].definitionReadiness.status -ne 'ready') { throw 'Child plan lost readiness evidence.' }
    'EFFECTIVE_DEFINITION_CHILD_PLAN_OK'
    """
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=repo_root,
        env={**os.environ, "MOTION_WRAPPER_PATH": str(wrapper_path),
             "MOTION_SOURCE_PLAN": str(tmp_path / "source_plan.json"), "MOTION_CHILD_PLAN": str(output_path)},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "EFFECTIVE_DEFINITION_CHILD_PLAN_OK" in result.stdout
    child_plan = json.loads(output_path.read_text(encoding="utf-8"))
    assert child_plan["sourcePlanPath"] == str(tmp_path / "source_plan.json")
    assert child_plan["exercises"][0]["definitionReadiness"]["definitionSource"] == "approved_registry"
