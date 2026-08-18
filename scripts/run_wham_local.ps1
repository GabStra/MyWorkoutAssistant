param(
    [Parameter(Mandatory = $true)]
    [string]$WhamRepoPath,

    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$PythonCommand = "python",
    [switch]$EstimateLocalOnly,
    [switch]$RunSmplify,
    [switch]$UseDocker,
    [string]$DockerImage = "myworkoutassistant/wham-ada:torch2.9-cu128-mmpose1",
    [string]$DockerGpus = "all",
    [string]$DockerShmSize = "16g",
    [double]$TimeoutSeconds = 200.0
)

$ErrorActionPreference = "Stop"

function Resolve-StrictPath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Assert-PathExists {
    param([string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        throw "Required path not found: $PathValue"
    }
}

function Invoke-WhamProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory = $true)]
        [string]$LogPath,

        [double]$TimeoutSeconds,
        [string]$DockerContainerName
    )

    $effectiveTimeoutSeconds = if ($TimeoutSeconds -gt 0.0) {
        [Math]::Max(1.0, $TimeoutSeconds)
    }
    else {
        $null
    }
    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = $FilePath
    $processInfo.WorkingDirectory = $WorkingDirectory
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.UseShellExecute = $false
    foreach ($argument in $ArgumentList) {
        [void]$processInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $processInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $completed = if ($null -eq $effectiveTimeoutSeconds) {
        $process.WaitForExit()
        $true
    }
    else {
        $timeoutMilliseconds = [int][Math]::Min(
            [int]::MaxValue,
            [Math]::Ceiling($effectiveTimeoutSeconds * 1000.0)
        )
        $process.WaitForExit($timeoutMilliseconds)
    }
    if (-not $completed) {
        if (-not [string]::IsNullOrWhiteSpace($DockerContainerName)) {
            & docker rm -f $DockerContainerName *> $null
        }
        try {
            $process.Kill($true)
        }
        catch {
            try {
                $process.Kill()
            }
            catch {
            }
        }
        $process.WaitForExit()
        $logContent = @(
            $stdoutTask.GetAwaiter().GetResult(),
            $stderrTask.GetAwaiter().GetResult(),
            "WHAM timed out after $effectiveTimeoutSeconds seconds."
        ) -join "`n"
        Set-Content -LiteralPath $LogPath -Value $logContent -Encoding UTF8
        throw "WHAM timed out after $effectiveTimeoutSeconds seconds. See '$LogPath'."
    }

    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    Set-Content -LiteralPath $LogPath -Value (@($stdout, $stderr) -join "`n") -Encoding UTF8
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        Write-Host $stdout
    }
    if (-not [string]::IsNullOrWhiteSpace($stderr)) {
        Write-Host $stderr
    }
    return $process.ExitCode
}

Assert-PathExists $WhamRepoPath
Assert-PathExists $InputVideo

$resolvedRepo = Resolve-StrictPath $WhamRepoPath
$resolvedInputVideo = Resolve-StrictPath $InputVideo
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $resolvedOutputRoot | Out-Null

$requiredPaths = @(
    (Join-Path $resolvedRepo "demo.py"),
    (Join-Path $resolvedRepo "requirements.txt"),
    (Join-Path $resolvedRepo "checkpoints\wham_vit_w_3dpw.pth.tar"),
    (Join-Path $resolvedRepo "checkpoints\hmr2a.ckpt"),
    (Join-Path $resolvedRepo "checkpoints\vitpose-h-multi-coco.pth"),
    (Join-Path $resolvedRepo "checkpoints\yolo26x.pt"),
    (Join-Path $resolvedRepo "dataset\body_models\smpl\SMPL_NEUTRAL.pkl")
)
if (-not $EstimateLocalOnly) {
    $requiredPaths += Join-Path $resolvedRepo "checkpoints\dpvo.pth"
}

$missing = $requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing.Count -gt 0) {
    throw "WHAM repo is missing required files:`n$($missing -join "`n")"
}

$argsList = @(
    "demo.py",
    "--video",
    $resolvedInputVideo,
    "--output_pth",
    $resolvedOutputRoot,
    "--save_pkl"
)
if ($EstimateLocalOnly) {
    $argsList += "--estimate_local_only"
}
if ($RunSmplify) {
    $argsList += "--run_smplify"
}

if ($UseDocker) {
    $inputDir = Split-Path -Parent $resolvedInputVideo
    $inputName = [System.IO.Path]::GetFileName($resolvedInputVideo)
    $dockerLog = Join-Path $resolvedOutputRoot "wham_docker.log"
    $dockerContainerName = "mwa-wham-job-$([guid]::NewGuid().ToString('N'))"
    $dockerArgs = @(
        "run",
        "--rm",
        "--name", $dockerContainerName
    )
    if (-not [string]::IsNullOrWhiteSpace($DockerGpus)) {
        $dockerArgs += @("--gpus", $DockerGpus)
    }
    if (-not [string]::IsNullOrWhiteSpace($DockerShmSize)) {
        $dockerArgs += @("--shm-size", $DockerShmSize)
    }
    $dockerArgs += @(
        "-e", "WHAM_POSE_BACKEND=vitpose",
        "-e", "WHAM_POSE_BATCH_SIZE=16",
        "-e", "WHAM_FEATURE_BATCH_SIZE=32",
        "-e", "WHAM_MAX_TRACK_GAP_FRAMES=3"
    )
    $dockerArgs += @(
        "-v", "${resolvedRepo}:/code",
        "-v", "${inputDir}:/input",
        "-v", "${resolvedOutputRoot}:/output",
        "-w", "/code",
        $DockerImage,
        "python",
        "-u",
        "demo.py",
        "--video",
        "/input/$inputName",
        "--output_pth",
        "/output",
        "--save_pkl"
    )
    if ($EstimateLocalOnly) {
        $dockerArgs += "--estimate_local_only"
    }
    if ($RunSmplify) {
        $dockerArgs += "--run_smplify"
    }
    $dockerExitCode = Invoke-WhamProcess `
        -FilePath "docker" `
        -ArgumentList $dockerArgs `
        -WorkingDirectory $resolvedRepo `
        -LogPath $dockerLog `
        -TimeoutSeconds $TimeoutSeconds `
        -DockerContainerName $dockerContainerName
    if ($dockerExitCode -ne 0) {
        throw "WHAM Docker run failed with exit code $dockerExitCode. See '$dockerLog'."
    }
    return
}

Push-Location $resolvedRepo
try {
    $localLog = Join-Path $resolvedOutputRoot "wham_local.log"
    $exitCode = Invoke-WhamProcess `
        -FilePath $PythonCommand `
        -ArgumentList $argsList `
        -WorkingDirectory $resolvedRepo `
        -LogPath $localLog `
        -TimeoutSeconds $TimeoutSeconds
    if ($exitCode -ne 0) {
        throw "WHAM run failed with exit code $exitCode. See '$localLog'."
    }
}
finally {
    Pop-Location
}
