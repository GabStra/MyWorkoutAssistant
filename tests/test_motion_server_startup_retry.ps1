$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$owner = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Start-SharedLlamaServer' }, $true)
$branch = $owner.Find({ param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if ($process.HasExited)') }, $true)
function Test-SharedLlamaServerStoppedByLiveExclusiveHandoff { param($SessionDir); return $false }
function Release-MotionServiceSessionLease { param($SessionDirectory); $script:Released = $true }
function Start-Sleep { param($Seconds) }
function Exit-IfMotionRunInterrupted { }
function Start-SharedLlamaServer {
    param($SessionDir, $StartupAttempt)
    if (-not $script:Released -or -not $script:Disposed) { throw 'Retry retained service or transition lease' }
    return $StartupAttempt
}
$SessionDir = $PSScriptRoot
$sessionLeaseKey = 'test-lease'
$logPath = Join-Path $PSScriptRoot 'nonexistent-startup.log'
$errorLogPath = Join-Path $PSScriptRoot 'nonexistent-startup.err.log'
$process = [pscustomobject]@{ HasExited=$true; ExitCode=1 }
foreach ($StartupAttempt in @(1, 3)) {
    $script:Released = $false
    $script:Disposed = $false
    $transitionLock = [pscustomobject]@{}
    $transitionLock | Add-Member ScriptMethod Dispose { $script:Disposed = $true }
    if ($StartupAttempt -eq 1) {
        $result = & ([scriptblock]::Create($branch.Extent.Text))
        if ($result -ne 2) { throw 'Failed startup did not retry locally' }
    } else {
        try {
            & ([scriptblock]::Create($branch.Extent.Text))
            throw 'Startup retries exceeded the bound'
        } catch {
            if ($_.Exception.Message -notlike 'Shared llama.cpp server exited during startup*Logs:*') { throw }
        }
        if (-not $script:Released) { throw 'Failed final attempt retained its stopped service lease' }
    }
}
Write-Host 'Server startup retry checks passed.'
