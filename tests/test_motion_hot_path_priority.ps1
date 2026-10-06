$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }

function Get-FunctionText([string]$Name) {
    $node = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $Name
    }.GetNewClosure(), $true)
    if (-not $node) { throw "Missing function $Name" }
    return $node.Extent.Text
}

foreach ($name in @(
    'Test-BakeStageReady',
    'Test-SelectionHasNeedsMotionProcessing',
    'Test-MotionProcessingResumeReady',
    'Test-SourceTurnResumePresent',
    'Get-BakeQueuePriority',
    'Optimize-PendingBakeQueue'
)) {
    Invoke-Expression (Get-FunctionText $name)
}

function Test-MovementSkeletonIntegrity {
    param([string]$Path)
    return (Test-Path -LiteralPath $Path)
}

$SelectionValidationPolicyVersion = 70
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('motion-hot-path-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
try {
    $coldBake = Join-Path $fixture 'cold\bake'
    $resumeBake = Join-Path $fixture 'resume\bake'
    $cursorBake = Join-Path $fixture 'cursor\bake'
    New-Item -ItemType Directory -Path $coldBake, $resumeBake, $cursorBake -Force | Out-Null

    $candidatesPath = Join-Path $fixture 'candidates.json'
    '{"candidates":[]}' | Set-Content -LiteralPath $candidatesPath -Encoding UTF8

    $incompleteManifest = @{
        selectionValidationPolicyVersion = 70
        candidateResults = @(
            @{ status = 'needs_motion_processing'; candidateRank = 1 }
        )
    }
    $incompleteManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $resumeBake 'selection_manifest.json') -Encoding UTF8
    '{}' | Set-Content -LiteralPath (Join-Path $cursorBake 'source_turn_resume.json') -Encoding UTF8

    $cold = [pscustomobject]@{
        bakeWorkspace = $coldBake
        exerciseCandidatesPath = $candidatesPath
        exerciseName = 'Cold'
    }
    $resume = [pscustomobject]@{
        bakeWorkspace = $resumeBake
        exerciseCandidatesPath = $candidatesPath
        exerciseName = 'Resume'
        motionProcessingResumed = $true
    }
    $cursor = [pscustomobject]@{
        bakeWorkspace = $cursorBake
        exerciseCandidatesPath = $candidatesPath
        exerciseName = 'Cursor'
    }

    if (Test-MotionProcessingResumeReady -WorkItem $cold) {
        throw 'Cold item must not be motion-processing resume ready.'
    }
    if (-not (Test-MotionProcessingResumeReady -WorkItem $resume)) {
        throw 'Incomplete-fit item must be motion-processing resume ready.'
    }
    if ((Get-BakeQueuePriority -WorkItem $resume) -ne 0) {
        throw 'Incomplete-fit resume must have priority 0.'
    }
    if ((Get-BakeQueuePriority -WorkItem $cursor) -ne 1) {
        throw 'Source-turn cursor must have priority 1.'
    }
    if ((Get-BakeQueuePriority -WorkItem $cold) -ne 2) {
        throw 'Cold item must have priority 2.'
    }

    $queue = [System.Collections.Queue]::new()
    $queue.Enqueue($cold)
    $queue.Enqueue($cursor)
    $queue.Enqueue($resume)
    Optimize-PendingBakeQueue -Queue $queue
    $ordered = @()
    while ($queue.Count -gt 0) { $ordered += $queue.Dequeue() }
    if ($ordered.Count -ne 3) { throw 'Queue lost items during optimize.' }
    if ($ordered[0].exerciseName -ne 'Resume') { throw 'Resume must dequeue first.' }
    if ($ordered[1].exerciseName -ne 'Cursor') { throw 'Source-turn cursor must dequeue second.' }
    if ($ordered[2].exerciseName -ne 'Cold') { throw 'Cold item must dequeue last.' }

    # DisableStageResume must still leave discovery reuse gated in the runner source.
    $enqueueText = $ast.Extent.Text
    if ($enqueueText -notmatch 'Test-MotionProcessingResumeReady') {
        throw 'Enqueue loop must call Test-MotionProcessingResumeReady.'
    }
    if ($enqueueText -notmatch 'Optimize-PendingBakeQueue') {
        throw 'Wave fill must call Optimize-PendingBakeQueue.'
    }
    if ($enqueueText -notmatch 'motionProcessingResumed = \$false') {
        throw 'Work items must declare motionProcessingResumed for sealed PSCustomObject assignment.'
    }
    if ($enqueueText -notmatch 'motionProcessingResumed') {
        throw 'Wave readiness must consider motionProcessingResumed.'
    }
    $disableDiscoveryReuse = [regex]::Matches(
        $enqueueText,
        'if \(-not \$DisableStageResume -and \(Test-DiscoveryStageReady'
    )
    if ($disableDiscoveryReuse.Count -lt 1) {
        throw 'Discovery stage reuse must remain gated by DisableStageResume.'
    }

    Write-Output 'Hot-path keep priority checks passed.'
} finally {
    $resolvedFixture = [IO.Path]::GetFullPath($fixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe fixture cleanup path.'
    }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
