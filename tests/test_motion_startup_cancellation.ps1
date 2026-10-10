$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
function Test-MotionRunCancelRequested { return $true }
function Exit-IfMotionRunInterrupted { throw 'cancelled' }
function Stop-GvhmrWarmWorker { param($Worker); $script:StoppedOwner = $Worker }
function Stop-SharedLlamaServer { param($Server); $script:StoppedOwner = $Server }
function Test-Path { throw 'startup continued after cancellation' }
$SessionDir = 'retained-session'
$sessionLeaseKey = 'owned-lease'
$runtimeOwner = @{ service = 'test-service' }
$containerName = 'owned-container'
$containerId = 'owned-container-id'
$process = [pscustomobject]@{ Id = 123; HasExited = $false }
foreach ($name in @('Start-GvhmrWarmWorker', 'Start-SharedLlamaServer')) {
    $function = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    $loop = $function.Find({ param($n) $n -is [System.Management.Automation.Language.WhileStatementAst] -and $n.Condition.Extent.Text -match 'deadline' }, $true)
    $script:StoppedOwner = $null
    try {
        & ([scriptblock]::Create($loop.Body.Extent.Text.Trim().Substring(1).TrimEnd().TrimEnd('}')))
        throw 'startup did not cancel'
    } catch {
        if ($_.Exception.Message -ne 'cancelled') { throw }
    }
    if ($null -eq $script:StoppedOwner -or $script:StoppedOwner.sessionLeaseKey -ne $sessionLeaseKey -or $script:StoppedOwner.runtimeOwner -ne $runtimeOwner) {
        throw "$name did not clean up its owned service before exiting"
    }
}
Write-Host 'Startup cancellation checks passed.'
