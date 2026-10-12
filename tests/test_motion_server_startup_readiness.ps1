$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$owner = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Start-SharedLlamaServer' }, $true)
$loop = $owner.Find({ param($n) $n -is [System.Management.Automation.Language.WhileStatementAst] -and $n.Condition.Extent.Text -match 'deadline' }, $true)
function Test-MotionRunCancelRequested { return $false }
function Test-SharedLlamaExclusiveHandoffActive { throw 'Startup waited for a queued holder while owning its transition lock' }
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    $script:ProbeUri = $Uri
}
function Set-Content { param($LiteralPath, $Encoding); $script:ReadyPublished = $LiteralPath }
function Update-SharedLlamaServerHeartbeat { param($SessionDir) }
function Start-Sleep { param($Seconds, $Milliseconds); throw 'Ready server was not admitted' }
$SessionDir = $PSScriptRoot
$sessionLeaseKey = 'test-lease'
$runtimeOwner = @{}
$process = [pscustomobject]@{ HasExited = $false; Id = 123 }
$baseUrl = 'http://127.0.0.1:8090'
$LlamaCppModel = 'test-model'
$parallel = 3
$logPath = 'test-log'
$result = & ([scriptblock]::Create($loop.Body.Extent.Text.Trim().Substring(1).TrimEnd().TrimEnd('}')))
if ($result.processId -ne 123 -or -not $script:ReadyPublished) { throw 'Startup did not publish its ready owner' }
if ($script:ProbeUri -ne "$baseUrl/health") { throw 'Startup must probe inference readiness, not model metadata' }
# Existing holders must still prevent launch before the readiness loop.
$guard = $owner.Find({ param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('if (Test-SharedLlamaExclusiveHandoffActive') }, $true)
if ($null -eq $guard -or $guard.Extent.StartOffset -gt $loop.Extent.StartOffset) { throw 'Startup lost its pre-launch GPU admission guard' }
Write-Host 'Server startup readiness checks passed.'
