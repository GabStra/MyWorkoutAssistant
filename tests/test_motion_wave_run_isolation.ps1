$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Start-StagedBakeWaveJob' }, $true)
. ([scriptblock]::Create($node.Extent.Text))
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-StagedBakeServiceConfigurationFingerprint' }, $true)
. ([scriptblock]::Create($node.Extent.Text))
function Start-Job {
    param($Name, $ScriptBlock, $ArgumentList)
    [pscustomobject]@{
        Name = $Name
        ScriptBlock = $ScriptBlock
        Arguments = $ArgumentList
    }
}
function Wait-Job {
    param($Job)
    return $Job
}
function Receive-Job {
    param($Job)
    $waiter = [scriptblock]::Create(
        $Job.ScriptBlock.ToString().Replace('$using:StagedWaveAmbiguousRecoveryStatus', '$StagedWaveAmbiguousRecoveryStatus').Replace('$using:StagedWaveAmbiguousRecoveryExitCode', '$StagedWaveAmbiguousRecoveryExitCode')
    )
    $argumentList = $Job.Arguments
    return (& $waiter @argumentList)
}
function Publish-StagedBakeQueueRequest {
    param($QueueRoot, $MaxWaveItems, $RequestTemporaryPath, $RequestPath)
    $requestDirectory = Split-Path -Parent $RequestPath
    New-Item -ItemType Directory -Force -Path $requestDirectory | Out-Null
    $request = Get-Content -LiteralPath $RequestTemporaryPath -Raw | ConvertFrom-Json
    $manifestArgumentIndex = [Array]::IndexOf([object[]]$request.arguments, '--staged-wave-manifest')
    $waveManifestPath = [string]$request.arguments[$manifestArgumentIndex + 1]
    $waveWorkspace = Split-Path -Parent $waveManifestPath
    $reportedWaveId = if ($script:PublishedWaveCount -eq 0) { 'stale-run-wave-0001' } else { $request.waveId }
    $script:PublishedWaveCount += 1
    @{ waveId=$reportedWaveId; items=@() } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $waveWorkspace 'staged_wave_report.json')
    Move-Item -LiteralPath $RequestTemporaryPath -Destination $RequestPath -Force
    $resultDirectory = Join-Path $QueueRoot 'results'
    New-Item -ItemType Directory -Force -Path $resultDirectory | Out-Null
    @{
        requestId = $request.requestId
        waveId = $request.waveId
        exitCode = 0
        status = 'completed'
        error = $null
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resultDirectory "$($request.requestId).json")
}
$resolvedWorkspaceRoot = Join-Path ([IO.Path]::GetTempPath()) ('motion-wave-test-' + [guid]::NewGuid().ToString('N'))
$effectiveWarmGvhmrWorker = $false
$resolvedGvhmrWorkerSessionDir = $null
$StagedWaveSize = 2
$StagedWaveAmbiguousRecoveryStatus = 'ambiguous_recovery'
$StagedWaveAmbiguousRecoveryExitCode = 81
$script:StagedWaveServiceQueueRoot = Join-Path $resolvedWorkspaceRoot 'staged-wave-services/v1'
$script:MotionSourceIdentityFingerprint = 'test-source-fingerprint'
$script:PublishedWaveCount = 0
$PythonCommand = 'unused'
$item = [pscustomobject]@{ exerciseId='curl'; exerciseName='Curl'; exerciseCandidatesPath='candidates.json'; bakeWorkspace='durable-exercise-cache'; bakeArgs=@() }
$movementRunId = 'run-one'
$first = Start-StagedBakeWaveJob -WorkItems @($item) -WaveIndex 1
$movementRunId = 'run-two'
$second = Start-StagedBakeWaveJob -WorkItems @($item) -WaveIndex 1
if ($first.WaveWorkspace -eq $second.WaveWorkspace) { throw 'Runs share a wave workspace' }
$manifest = Get-Content (Join-Path $second.WaveWorkspace 'wave_manifest.json') -Raw | ConvertFrom-Json
if ($manifest.items[0].workspace -ne $item.bakeWorkspace) { throw 'Durable exercise cache changed' }
foreach ($job in @($first, $second)) {
    Wait-Job -Job $job | Out-Null
    $result = Receive-Job -Job $job
    if ($job -eq $first) {
        if ($result.report -or $result.exitCode -eq 0) { throw 'Stale report accepted' }
    } elseif (-not $result.report -or $result.exitCode -ne 0) {
        throw 'Current report rejected'
    }
}
$requests = @(Get-ChildItem -LiteralPath (Join-Path $script:StagedWaveServiceQueueRoot 'requests') -Filter '*.json')
if ($requests.Count -ne 2) { throw 'Expected one durable service request for each isolated wave' }
$requestWaveIds = @($requests | ForEach-Object { (Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json).waveId })
if ($requestWaveIds -notcontains $first.WaveId -or $requestWaveIds -notcontains $second.WaveId) {
    throw 'Service requests do not retain their owning wave IDs'
}
if ($first.WaveWorkspace -notlike "$resolvedWorkspaceRoot*") { throw 'First wave escaped its test workspace' }
if ($second.WaveWorkspace -notlike "$resolvedWorkspaceRoot*") { throw 'Second wave escaped its test workspace' }
Remove-Item -LiteralPath $resolvedWorkspaceRoot -Recurse -Force
Write-Host 'Wave run isolation tests passed.'
