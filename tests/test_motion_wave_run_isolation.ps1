$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Start-StagedBakeWaveJob' }, $true)
. ([scriptblock]::Create($node.Extent.Text))
function Start-Job {
    param($Name, $ScriptBlock, $ArgumentList)
    [pscustomobject]@{ Name=$Name; Worker=$ScriptBlock; Arguments=$ArgumentList }
}
$resolvedWorkspaceRoot = Join-Path ([IO.Path]::GetTempPath()) ('motion-wave-test-' + [guid]::NewGuid().ToString('N'))
$effectiveWarmWhamWorker = $false
$PythonCommand = 'unused'
$item = [pscustomobject]@{ exerciseId='curl'; exerciseName='Curl'; exerciseCandidatesPath='candidates.json'; bakeWorkspace='durable-exercise-cache'; bakeArgs=@() }
$movementRunId = 'run-one'
$first = Start-StagedBakeWaveJob -WorkItems @($item) -WaveIndex 1
$movementRunId = 'run-two'
$second = Start-StagedBakeWaveJob -WorkItems @($item) -WaveIndex 1
if ($first.WaveWorkspace -eq $second.WaveWorkspace) { throw 'Runs share a wave workspace' }
$manifest = Get-Content (Join-Path $second.WaveWorkspace 'wave_manifest.json') -Raw | ConvertFrom-Json
if ($manifest.items[0].workspace -ne $item.bakeWorkspace) { throw 'Durable exercise cache changed' }
$fake = Join-Path $resolvedWorkspaceRoot 'fake-python.ps1'
'param($ReportPath, $WaveId); @{waveId=$WaveId;items=@()} | ConvertTo-Json | Set-Content -LiteralPath $ReportPath; exit 0' | Set-Content -LiteralPath $fake
$reportPath = Join-Path $second.WaveWorkspace 'staged_wave_report.json'
foreach ($identity in @('old-run', $second.WaveId)) {
    $result = & $second.Worker 'pwsh' @('-NoProfile', '-File', $fake, $reportPath, $identity) (Join-Path $second.WaveWorkspace 'wave.log') $second.WaveWorkspace $second.WaveId
    if ($identity -eq 'old-run') {
        if ($result.report -or $result.exitCode -eq 0) { throw 'Stale report accepted' }
    } elseif (-not $result.report -or $result.exitCode -ne 0) { throw 'Current report rejected' }
}
# Remove only the explicitly created test files and empty directories.
foreach ($job in @($first, $second)) {
    foreach ($name in @('wave_manifest.json', 'wave.log', 'staged_wave_report.json')) {
        Remove-Item -LiteralPath (Join-Path $job.WaveWorkspace $name) -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $job.WaveWorkspace
}
Remove-Item -LiteralPath $fake
Remove-Item -LiteralPath (Join-Path $resolvedWorkspaceRoot 'staged-waves')
Remove-Item -LiteralPath $resolvedWorkspaceRoot
Write-Host 'Wave run isolation tests passed.'
