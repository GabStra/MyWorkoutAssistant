$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Get-SharedLlamaBakeRestartCounts', 'Test-SharedLlamaServerRestartAdmission')) {
    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
$job = [pscustomobject]@{ WorkItem = [pscustomobject]@{ bakeArgs = @('--shared-llama-server') } }
$counts = Get-SharedLlamaBakeRestartCounts -RunningJobs @($job)
foreach ($handoff in @($false, $true)) {
    $admitted = Test-SharedLlamaServerRestartAdmission -RestartRequired $true -StartRequested $true -ReadyMarkerExists $false -LiveExclusiveHandoffActive $handoff -SafeBakeRunningJobCount $counts.safeBakeRunningJobCount -UnsafeBakeRunningJobCount $counts.unsafeBakeRunningJobCount -PrefetchRunningJobCount 0 -PendingPrefetchCount 0 -DiscoveryRunningJobCount 0 -PendingDiscoveryCount 0 -PendingLegacyBakeCount 0
    if ($admitted -eq $handoff) { throw 'Individual shared job must permit restart only outside an exclusive handoff' }
}
$job.WorkItem.bakeArgs = @()
$counts = Get-SharedLlamaBakeRestartCounts -RunningJobs @($job)
if ($counts.unsafeBakeRunningJobCount -ne 1) { throw 'Uncoordinated individual job must remain blocked' }
Write-Host 'Individual restart admission checks passed.'
