$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$helper = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Assert-ExistingSharedLlamaServer'
}, $true)
if ($null -eq $helper) { throw 'Attach validator function is missing' }
$helperText = $helper.Extent.Text
Invoke-Expression $helperText
$directoryHelper = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Resolve-SharedLlamaSessionDirectory'
}, $true)
if ($null -eq $directoryHelper) { throw 'Shared-session directory resolver is missing' }
Invoke-Expression $directoryHelper.Extent.Text
foreach ($forbidden in @(
    'Acquire-MotionWorkspaceLease', 'Release-MotionWorkspaceLease',
    'Start-SharedLlamaServer', 'Stop-SharedLlamaServer', 'Update-SharedLlamaServerHeartbeat'
)) {
    if ($helperText.Contains($forbidden)) { throw "Attach validation must not mutate service ownership ($forbidden)" }
}
if (-not $helperText.Contains('/health') -or -not $helperText.Contains('/v1/models') -or
    -not $helperText.Contains('--ctx-size') -or -not $helperText.Contains('--parallel')) {
    throw 'Attach validation must check endpoint, model listing, and the context/parallel profile'
}
if (-not $runner -or -not (Select-String -LiteralPath $runner -Pattern '-not \$AttachExistingSharedLlamaServer' -Quiet)) {
    throw 'Attached runs must suppress local shared-server restart admission'
}

function ConvertFrom-ReconstructionJson {
    process { ConvertFrom-Json -InputObject $_ }
}
function Get-ObjectProperty {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    return $Object.$Name
}
function Get-MotionServiceRuntimeState { param($RuntimeOwner); return 'running' }
function Get-Process { param([int]$Id, $ErrorAction); return [pscustomobject]@{ Id = $Id } }
function Get-CimInstance {
    param($Class, $Filter, $ErrorAction)
    if ($Filter -match '111') {
        return [pscustomobject]@{ CommandLine = 'pwsh -File scripts/run_exercise_motion_workout_plan.ps1 -SharedLlamaServerOnly -SharedLlamaServer' }
    }
    return [pscustomobject]@{ CommandLine = $script:MockServerCommandLine }
}
function Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    if ($Uri.EndsWith('/health')) { return [pscustomobject]@{ status = 'ok' } }
    return [pscustomobject]@{ models = @([pscustomobject]@{ id = 'test-model'; name = 'test-model'; model = 'test-model' }) }
}

$testSession = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testSession | Out-Null
try {
    $missingSession = Join-Path $testSession 'missing'
    $missingRejected = $false
    try { $null = Resolve-SharedLlamaSessionDirectory -Path $missingSession -AttachExisting }
    catch { $missingRejected = $_.Exception.Message -match 'does not exist' }
    if (-not $missingRejected -or (Test-Path -LiteralPath $missingSession)) {
        throw 'Attach mode must reject a missing session without creating it'
    }

    $ownerPath = Join-Path $testSession '.motion_workspace.owner.json'
    $readyPath = Join-Path $testSession 'ready.json'
    $heartbeatPath = Join-Path $testSession 'heartbeat.json'
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    [ordered]@{
        schemaVersion = 1; pid = 111; stage = 'run_exercise_motion_workout_plan'
        workspaceRoot = $testSession; ownerToken = 'external-owner-token'; serviceState = 'running'
        runtimeOwner = @{ kind = 'process'; service = 'llama-server'; pid = 222; processIdentity = 333; baseUrl = 'http://127.0.0.1:8090' }
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ownerPath
    @{ pid = 222; baseUrl = 'http://127.0.0.1:8090'; model = 'test-model'; parallel = 3 } |
        ConvertTo-Json | Set-Content -LiteralPath $readyPath
    @{ updatedAtUnixSeconds = $now } | ConvertTo-Json | Set-Content -LiteralPath $heartbeatPath
    $evidencePaths = @($ownerPath, $readyPath, $heartbeatPath)
    $before = @($evidencePaths | ForEach-Object { (Get-FileHash -LiteralPath $_).Hash })
    $script:MockServerCommandLine = 'llama-server --parallel 3 --ctx-size 49152 --batch-size 1024 --ubatch-size 512'
    $result = Assert-ExistingSharedLlamaServer `
        -SessionDir $testSession -BaseUrl 'http://127.0.0.1:8090' -Model 'test-model' -Parallel 3 `
        -ContextSize 49152 -BatchSize 1024 -UBatchSize 512
    if ($result.supervisorPid -ne 111 -or $result.serverPid -ne 222) { throw 'Attached owner identity was not returned' }
    $after = @($evidencePaths | ForEach-Object { (Get-FileHash -LiteralPath $_).Hash })
    if (($before -join ',') -ne ($after -join ',')) { throw 'Attach validation modified owner/session evidence' }

    $script:MockServerCommandLine = 'llama-server --parallel 30 --ctx-size 49152 --batch-size 1024 --ubatch-size 512'
    $prefixRejected = $false
    try {
        $null = Assert-ExistingSharedLlamaServer `
            -SessionDir $testSession -BaseUrl 'http://127.0.0.1:8090' -Model 'test-model' -Parallel 3 `
            -ContextSize 49152 -BatchSize 1024 -UBatchSize 512
    } catch { $prefixRejected = $_.Exception.Message -match 'command line does not match' }
    if (-not $prefixRejected) { throw 'Attach validation must reject numeric argument prefix mismatches' }

    $ready = Get-Content -LiteralPath $readyPath -Raw | ConvertFrom-Json
    $ready.model = 'different-model'
    $ready | ConvertTo-Json | Set-Content -LiteralPath $readyPath
    $rejected = $false
    try {
        $null = Assert-ExistingSharedLlamaServer `
            -SessionDir $testSession -BaseUrl 'http://127.0.0.1:8090' -Model 'test-model' -Parallel 3 `
            -ContextSize 49152 -BatchSize 1024 -UBatchSize 512
    } catch { $rejected = $_.Exception.Message -match 'profile differs' }
    if (-not $rejected) { throw 'Attach validation must fail closed on a profile mismatch' }
} finally {
    Remove-Item -LiteralPath $testSession -Recurse -Force
}
Write-Host 'Shared Llama attach-mode checks passed.'
