$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
function Get-AssignmentText([string]$Name) {
    $node = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq $Name
    }.GetNewClosure(), $true)
    if (-not $node) { throw "Missing assignment $Name" }
    return $node.Extent.Text
}
$decision = [scriptblock]::Create((@(
    (Get-AssignmentText '$partialWaveDue'), (Get-AssignmentText '$stagedWaveReady'),
    (Get-AssignmentText '$canLaunchDiscovery'), (Get-AssignmentText '$canLaunchBake'),
    (Get-AssignmentText '$discoveryAndDownloadDrained'), (Get-AssignmentText '$canStartStagedWave'),
    '@{ ready=$stagedWaveReady; discover=$canLaunchDiscovery; bake=$canStartStagedWave }'
) -join "`n"))
$stagedWavesEnabled = $true
$stagedWaveIndex = 0
$StagedWaveSize = 32
$StagedWaveMaxWaitSeconds = 300
$avoidGpuDiscoveryBakeOverlap = $true
$pendingBakeItems = @(1)
$pendingLegacyBakeItems = @()
$pendingCompletionItems = @()
$bakeRunningJobs = @()
$pendingDiscoveryItems = @(1)
$discoveryRunningJobs = @()
$pendingSourceDownloadItems = @()
$pendingFallbackSourceDownloadItems = @()
$sourceDownloadRunningJobs = @()
$readyWaveSince = (Get-Date).AddSeconds(-20)
$result = & $decision
if ($result.ready -or $result.bake -or -not $result.discover) { throw 'Small fresh batch should accumulate while discovery proceeds.' }
$readyWaveSince = (Get-Date).AddSeconds(-301)
$result = & $decision
if (-not $result.ready -or -not $result.bake -or $result.discover) { throw 'Expired partial batch must take priority.' }
$discoveryRunningJobs = @(1)
$result = & $decision
if ($result.bake -or $result.discover) { throw 'Must wait for existing GPU discovery to finish without launching more.' }
$discoveryRunningJobs = @()
$readyWaveSince = $null
$pendingBakeItems = @()
$result = & $decision
if ($result.ready -or $result.bake) { throw 'Empty batch must not start.' }
$pendingBakeItems = @(1..32)
$readyWaveSince = Get-Date
$result = & $decision
if (-not $result.ready -or -not $result.bake) { throw 'Full batch should start immediately.' }
$pendingBakeItems = @([pscustomobject]@{ primarySourceDownloadReused = $true })
$result = & $decision
if (-not $result.ready -or -not $result.bake -or $result.discover) { throw 'Resumed reconstruction must start before new discovery even below the batch target.' }
$stagedWaveIndex = 1
$result = & $decision
if ($result.ready -or $result.bake -or -not $result.discover) { throw 'Later cached sources must accumulate into batches.' }
$stagedWaveIndex = 0

# Cached review work must not consume this run's bounded CPU preparation buffer.
$prefetchLoop = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.WhileStatementAst] -and
    $node.Condition.Extent.Text -match 'PrefetchQueueDepth'
}, $true)
$prefetchDecision = [scriptblock]::Create($prefetchLoop.Condition.Extent.Text)
$pendingPrefetchItems = @(1)
$prefetchRunningJobs = @()
$PrefetchWorkers = 2
$PrefetchQueueDepth = 40
$pendingDiscoveryItems = @(1..42 | ForEach-Object { [pscustomobject]@{ prefetchReused = $true } })
if (-not (& $prefetchDecision)) { throw 'Cached source-review backlog blocked CPU preparation.' }
$pendingDiscoveryItems += @(1..40 | ForEach-Object { [pscustomobject]@{ prefetchReused = $false } })
if (& $prefetchDecision) { throw 'CPU preparation buffer is not bounded.' }
Write-Output 'Scheduling checks passed: partial wait, full batch, empty queue, and exclusive GPU ownership.'

# Execute the production yield block without starting any job or GPU work.
$yieldBlock = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '$stagedWaveReady'
}, $true)
if (-not $yieldBlock) { throw 'Missing cooperative discovery yield block.' }
$testDirectory = Join-Path $root ('build/test-discovery-yield/' + [guid]::NewGuid().ToString('N'))
[void][System.IO.Directory]::CreateDirectory($testDirectory)
$discoveryRunningJobs = @([pscustomobject]@{ WorkItem = [pscustomobject]@{
    exerciseCandidatesPath = Join-Path $testDirectory 'youtube_candidates.json'; exerciseName = 'Test movement'
}})
$yieldDecision = [scriptblock]::Create($yieldBlock.Extent.Text)
$stagedWaveReady = $false
& $yieldDecision
if (Test-Path -LiteralPath (Join-Path $testDirectory 'discovery_yield.request')) { throw 'Yield requested without ready reconstruction.' }
$stagedWaveReady = $true
& $yieldDecision
if (-not (Test-Path -LiteralPath (Join-Path $testDirectory 'discovery_yield.request'))) { throw 'Ready reconstruction failed to request discovery yield.' }
Write-Output 'Discovery yield signal checks passed.'
