$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$source = Get-Content -LiteralPath $runner -Raw
$start = $source.IndexOf('            $finishedJobs = @(')
$end = $source.IndexOf('            if (Test-MotionRunCancelRequested)', $start)
if ($start -lt 0 -or $end -le $start) { throw 'Completion harvest not found' }
$harvest = [scriptblock]::Create($source.Substring($start, $end - $start))
$runningJobs = @()
try {
    foreach ($name in @('prefetch', 'discovery', 'wave')) {
        $runningJobs += Start-Job -Name $name -ScriptBlock { 'finished' }
    }
    Wait-Job -Job $runningJobs | Out-Null
    $jobWaitSeconds = 0
    . $harvest
    if ($finishedJobs.Count -ne 3) { throw 'Completed wave starved behind completed upstream jobs' }
    $expectedIds = @($runningJobs.Id | Sort-Object)
    $actualIds = @($finishedJobs.Id | Sort-Object)
    if (Compare-Object $expectedIds $actualIds) { throw 'Completion harvest lost or duplicated jobs' }
} finally {
    $runningJobs | Remove-Job -Force
}
Write-Host 'Completed job harvest checks passed.'
