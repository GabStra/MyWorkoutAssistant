import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is required")
def test_library_resume_preserves_rejections_and_invalidates_only_stale_discovery(tmp_path):
    script = r'''
$ErrorActionPreference = 'Stop'
function Read-Ast([string]$Path) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    return $ast
}
$library = Read-Ast (Join-Path (Get-Location) 'scripts/run_exercise_motion_library.ps1')
$runner = Read-Ast (Join-Path (Get-Location) 'scripts/run_exercise_motion_workout_plan.ps1')
$startup = $library.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text.Trim() -eq '$readyDefinitionExerciseCount -gt 0'
}, $true)
if (-not $startup) { throw 'Missing ready-target startup branch.' }
$readiness = $runner.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Test-DiscoveryStageReady'
}, $true)
. ([scriptblock]::Create(($runner.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-DiscoverySemanticArgumentArraySha256'
}, $true)).Extent.Text))
. ([scriptblock]::Create($readiness.Extent.Text))
function Get-DefinitionReviewReason { param($Payload); return $null }
function Test-HasIdentityReviewedRecommendedCandidate { param($CandidatesPath, $Payload); return $false }
function ConvertFrom-ReconstructionJson { process { $_ | ConvertFrom-Json } }
function Invoke-PassBoundaryRevalidation { $script:revalidationCalls += 1 }
function Write-MotionLibraryMessage { param($Message) }

$manifestPath = Join-Path $env:MOTION_RESUME_TEST_ROOT 'youtube_candidates.json'
$payload = [pscustomobject]@{
    wrapperDiscoverySignature = [pscustomobject]@{
        schemaVersion = 1; policyVersion = 37; argumentsSha256 = 'args'
        exercisePlanSha256 = 'plan'; equipmentSha256 = 'equipment'
    }
    ranking = @{ sourceRejectionReviewPolicyVersion = 1 }
    exercises = @(@{
        exerciseId = 'carry'; exerciseName = 'Carry'
        candidates = @(
            @{ videoId = 'bad-motion'; status = 'rejected'; visionPayload = @{ target_identity_match = $true } },
            @{ videoId = 'wrong-exercise'; status = 'rejected'; visionPayload = @{ target_identity_match = $false } }
        )
    })
}
$payload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $manifestPath
$originalHash = (Get-FileHash -LiteralPath $manifestPath).Hash
$readyDefinitionExerciseCount = 1
$script:revalidationCalls = 0
& ([scriptblock]::Create($startup.Extent.Text))
& ([scriptblock]::Create($startup.Extent.Text))
if ($script:revalidationCalls -ne 2) { throw 'Resume skipped selected-output revalidation.' }
if ((Get-FileHash -LiteralPath $manifestPath).Hash -ne $originalHash) { throw 'Resume changed discovery verdicts.' }

$workItem = [pscustomobject]@{
    exerciseCandidatesPath = $manifestPath; discoveryArgumentsSha256 = 'args'
    discoverySemanticArgumentsSha256 = ''
    exercisePlanSha256 = 'plan'; equipmentSha256 = 'equipment'
    bakeWorkspace = $env:MOTION_RESUME_TEST_ROOT
}
$discoveryStagePolicyVersion = 37
if (-not (Test-DiscoveryStageReady -WorkItem $workItem -Payload $payload)) {
    throw 'Current-policy rejection evidence should remain reusable.'
}
$workItem.discoveryArgumentsSha256 = 'changed-full-arguments'
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $payload) {
    throw 'Legacy discovery signature ignored a changed full argument hash.'
}
$workItem.discoveryArgumentsSha256 = 'args'
$discoveryStagePolicyVersion = 38
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $payload) {
    throw 'Changed discovery policy must reopen the stage.'
}
$discoveryStagePolicyVersion = 37
$workItem.exercisePlanSha256 = 'changed-plan'
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $payload) {
    throw 'Changed exercise configuration must reopen the stage.'
}
$workItem.exercisePlanSha256 = 'plan'
$baseDiscoveryArgs = @(
    '--workout-plan-json', 'plan.json', '--source-outcome-index', 'outcomes.json',
    '--exclude-youtube-video-id', 'video-A', '--out-json', 'result-a.json',
    '--youtube-preview-cache-dir', 'cache-a', '--vision-llm-workers', '1'
)
$changedOutputArgs = @(
    '--workout-plan-json', 'plan.json', '--source-outcome-index', 'outcomes.json',
    '--exclude-youtube-video-id', 'video-A', '--out-json', 'result-b.json',
    '--youtube-preview-cache-dir', 'cache-a', '--vision-llm-workers', '1'
)
$baseSemanticHash = Get-DiscoverySemanticArgumentArraySha256 -Arguments $baseDiscoveryArgs
if ($baseSemanticHash -ne (Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedOutputArgs)) {
    throw 'Output destination changed semantic discovery identity.'
}
$changedCacheArgs = @($baseDiscoveryArgs)
$changedCacheArgs[9] = 'cache-b'
if ($baseSemanticHash -eq (Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedCacheArgs)) {
    throw 'Preview cache path was removed despite its cached content affecting review inputs.'
}
$changedWorkerArgs = @($baseDiscoveryArgs)
$changedWorkerArgs[11] = '3'
if ($baseSemanticHash -eq (Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedWorkerArgs)) {
    throw 'Vision worker count was removed despite changing which candidate decisions complete.'
}
$changedPlanArgs = @($baseDiscoveryArgs)
$changedPlanArgs[1] = 'other-plan.json'
if ($baseSemanticHash -eq (Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedPlanArgs)) {
    throw 'Changed workout plan was removed from semantic discovery identity.'
}
$changedSourceArgs = @($baseDiscoveryArgs)
$changedSourceArgs[5] = 'video-B'
if ($baseSemanticHash -eq (Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedSourceArgs)) {
    throw 'Changed source-selection exclusion was removed from semantic discovery identity.'
}
$semanticPayload = [pscustomobject]@{
    wrapperDiscoverySignature = [pscustomobject]@{
        schemaVersion = 1; policyVersion = 37; argumentsSha256 = 'legacy-different'
        semanticArgumentsSha256 = $baseSemanticHash
        exercisePlanSha256 = 'plan'; equipmentSha256 = 'equipment'
    }
    ranking = @{ sourceRejectionReviewPolicyVersion = 1 }
    exercises = @(@{ exerciseId = 'carry'; exerciseName = 'Carry'; candidates = @() })
}
$workItem.discoverySemanticArgumentsSha256 = $baseSemanticHash
if (-not (Test-DiscoveryStageReady -WorkItem $workItem -Payload $semanticPayload)) {
    throw 'New semantic discovery signature did not allow an operational-only argument change.'
}
$workItem.exercisePlanSha256 = 'changed-plan'
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $semanticPayload) {
    throw 'New semantic discovery signature reused after the exercise-plan content changed.'
}
$workItem.exercisePlanSha256 = 'plan'
$workItem.discoverySemanticArgumentsSha256 = Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedSourceArgs
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $semanticPayload) {
    throw 'New semantic discovery signature reused after source-selection input changed.'
}
$workItem.discoverySemanticArgumentsSha256 = Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedCacheArgs
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $semanticPayload) {
    throw 'New semantic discovery signature reused after preview-cache input changed.'
}
$workItem.discoverySemanticArgumentsSha256 = Get-DiscoverySemanticArgumentArraySha256 -Arguments $changedWorkerArgs
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $semanticPayload) {
    throw 'New semantic discovery signature reused after vision worker count changed.'
}
$workItem.discoverySemanticArgumentsSha256 = $baseSemanticHash
$workItem.equipmentSha256 = 'changed-equipment'
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $semanticPayload) {
    throw 'New semantic discovery signature reused after equipment changed.'
}
$workItem.equipmentSha256 = 'equipment'
$payload.ranking.sourceRejectionReviewPolicyVersion = 0
if (Test-DiscoveryStageReady -WorkItem $workItem -Payload $payload) {
    throw 'Legacy rejection policy must reopen the stage.'
}
if ((Get-FileHash -LiteralPath $manifestPath).Hash -ne $originalHash) { throw 'Readiness checks changed cached verdicts.' }
'RESUME_REJECTIONS_PRESERVED'
'''
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "MOTION_RESUME_TEST_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESUME_REJECTIONS_PRESERVED" in result.stdout


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is required")
def test_initial_discovery_retries_only_recoverable_vlm_transport_failures():
    script = r'''
$ErrorActionPreference = 'Stop'
$path = Join-Path (Get-Location) 'scripts/run_exercise_motion_workout_plan.ps1'
$tokens = $null; $errors = $null
$runner = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$policy = $runner.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-InitialDiscoveryRetryPolicy'
}, $true)
if (-not $policy) { throw 'Missing initial discovery retry policy.' }
. ([scriptblock]::Create($policy.Extent.Text))
$attemptLogReader = $runner.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-InitialDiscoveryAttemptLog'
}, $true)
if (-not $attemptLogReader) { throw 'Missing current-attempt log reader.' }
. ([scriptblock]::Create($attemptLogReader.Extent.Text))

$recoverableTimeout = Get-InitialDiscoveryRetryPolicy -LogTail 'CriticalVlmInteractionError: Critical VLM timeout during vision chat' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($recoverableTimeout.maximumAttempts -ne 2 -or $recoverableTimeout.reason -ne 'recoverable VLM interaction failure') {
    throw 'Recoverable VLM timeout did not use one bounded outer retry.'
}
$recoverableTransport = Get-InitialDiscoveryRetryPolicy -LogTail 'CriticalVlmInteractionError: Critical VLM transport failure during vision chat' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($recoverableTransport.maximumAttempts -ne 2) { throw 'Recoverable VLM transport failure did not get exactly one outer retry.' }
$recoverableHttp = Get-InitialDiscoveryRetryPolicy -LogTail 'CriticalVlmInteractionError: Critical VLM HTTP failure during vision chat: status=503' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($recoverableHttp.maximumAttempts -ne 2) { throw 'Recoverable VLM HTTP status did not get exactly one outer retry.' }
$serverStartup = Get-InitialDiscoveryRetryPolicy -LogTail 'llama-server did not become healthy' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($serverStartup.maximumAttempts -ne 3) { throw 'Server startup retry allowance changed.' }
$syntaxFailure = Get-InitialDiscoveryRetryPolicy -LogTail 'SyntaxError: invalid syntax' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($syntaxFailure.maximumAttempts -ne 2) { throw 'Syntax-load retry allowance changed.' }
$nonrecoverable = Get-InitialDiscoveryRetryPolicy -LogTail 'CriticalVlmInteractionError: Critical VLM HTTP failure during vision chat: status=400' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($nonrecoverable.maximumAttempts -ne 1) { throw 'Nonrecoverable VLM failure was retried.' }
$noSource = Get-InitialDiscoveryRetryPolicy -LogTail 'No suitable source candidates were found.' -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
if ($noSource.maximumAttempts -ne 1) { throw 'Ordinary no-source outcome was retried.' }

$staleLogPath = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString() + '.log')
try {
    [System.IO.File]::WriteAllText($staleLogPath, 'CriticalVlmInteractionError: Critical VLM timeout from an earlier attempt')
    $attemptStart = [System.IO.File]::ReadAllText($staleLogPath).Length
    [System.IO.File]::AppendAllText($staleLogPath, "`nNo suitable source candidates were found.")
    $currentAttempt = Get-InitialDiscoveryAttemptLog -Path $staleLogPath -StartCharacter $attemptStart
    $staleTimeout = Get-InitialDiscoveryRetryPolicy -LogTail $currentAttempt -MaxTransientAttempts 3 -MaxRecoverableVlmAttempts 2
    if ($staleTimeout.maximumAttempts -ne 1) { throw 'A stale timeout caused the current no-source outcome to retry.' }
} finally {
    Remove-Item -LiteralPath $staleLogPath -Force -ErrorAction SilentlyContinue
}
'INITIAL_DISCOVERY_RETRY_POLICY_OK'
'''
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INITIAL_DISCOVERY_RETRY_POLICY_OK" in result.stdout
