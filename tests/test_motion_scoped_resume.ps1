$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if ($priorRunStateExists -and -not $script:MotionSourceIdentityMatchesPriorRun)') }, $true)
if ($null -eq $node) { throw 'Source identity guard not found' }
$priorRunStateExists = $true
$script:MotionSourceIdentityMatchesPriorRun = $false
foreach ($explicitDisable in @($false, $true)) {
    $DisableStageResume = $explicitDisable
    $DisableMotionProcessingResume = $false
    . ([scriptblock]::Create($node.Extent.Text))
    if ($DisableStageResume -ne $explicitDisable -or -not $DisableMotionProcessingResume) {
        throw 'Code changes must invalidate motion processing while retaining signed source stages and explicit disable overrides'
    }
}
Write-Host 'Scoped resume checks passed.'
