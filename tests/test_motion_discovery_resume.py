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
    exercisePlanSha256 = 'plan'; equipmentSha256 = 'equipment'
    bakeWorkspace = $env:MOTION_RESUME_TEST_ROOT
}
$discoveryStagePolicyVersion = 37
if (-not (Test-DiscoveryStageReady -WorkItem $workItem -Payload $payload)) {
    throw 'Current-policy rejection evidence should remain reusable.'
}
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
