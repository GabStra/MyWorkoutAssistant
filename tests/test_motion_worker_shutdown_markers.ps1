$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Stop-GvhmrWarmWorker' }, $true)
. ([scriptblock]::Create($node.Extent.Text))
function Set-MotionServiceSessionState { param($SessionDirectory, $RuntimeOwner, $ServiceState) }
function docker { }
function Release-MotionServiceSessionLease { param($SessionDirectory); return $script:RuntimeState }
$session = Join-Path ([IO.Path]::GetTempPath()) ('motion-stop-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $session | Out-Null
$worker = [pscustomobject]@{ sessionDir=$session; sessionLeaseKey=$session; containerName='test'; runtimeOwner=@{service='test'} }
try {
    foreach ($state in @('unknown', 'stopped')) {
        $script:RuntimeState = $state
        '{}' | Set-Content (Join-Path $session 'ready.json')
        '{}' | Set-Content (Join-Path $session 'heartbeat.json')
        Stop-GvhmrWarmWorker -Worker $worker
        $ready = Test-Path (Join-Path $session 'ready.json')
        $heartbeat = Test-Path (Join-Path $session 'heartbeat.json')
        $stopped = Test-Path (Join-Path $session 'stopped.json')
        if ($state -eq 'stopped') {
            if ($ready -or $heartbeat -or -not $stopped) { throw 'Confirmed shutdown left stale readiness markers' }
        } elseif (-not $ready -or -not $heartbeat -or $stopped) {
            throw 'Unconfirmed shutdown discarded owner evidence'
        }
    }
    $startup = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if ($effectiveWarmGvhmrWorker)') -and $n.Extent.Text.Contains('$activeGvhmrWorkerSessionDir =') }, $true)
    $effectiveWarmGvhmrWorker = $true
    $gvhmrWarmWorkerScriptPath = $runner
    $GvhmrWorkerSessionDir = $session
    function Acquire-MotionServiceSessionLease {
        param($SessionDirectory, $Stage)
        if ($script:RuntimeState -ne 'stopped') { throw 'owner unconfirmed' }
        return $SessionDirectory
    }
    foreach ($state in @('unknown', 'stopped')) {
        $script:RuntimeState = $state
        '{}' | Set-Content (Join-Path $session 'ready.json')
        Remove-Item (Join-Path $session 'stopped.json') -ErrorAction SilentlyContinue
        try { . ([scriptblock]::Create($startup.Extent.Text)) } catch {
            if ($state -ne 'unknown' -or $_.Exception.Message -ne 'owner unconfirmed') { throw }
        }
        if ((Test-Path (Join-Path $session 'ready.json')) -ne ($state -eq 'unknown')) {
            throw 'Startup recovery did not respect service ownership'
        }
        if ((Test-Path (Join-Path $session 'stopped.json')) -ne ($state -eq 'stopped')) {
            throw 'Startup recovery published incorrect stopped state'
        }
    }
} finally {
    Remove-Item -LiteralPath $session -Recurse -Force
}
Write-Host 'Worker shutdown marker checks passed.'
