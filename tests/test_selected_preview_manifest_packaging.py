from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_exercise_motion_workout_plan.ps1"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is required")
def test_packaged_selection_manifest_points_to_retained_top_level_preview(
    tmp_path: Path,
) -> None:
    selected_preview = tmp_path / "selected" / "movement_selected_preview.html"
    selected_preview.parent.mkdir(parents=True)
    selected_preview.write_text("<html></html>", encoding="utf-8")
    manifest_path = tmp_path / "selected" / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "selectedPreviewHtmlPath": str(tmp_path / "bake" / "selected_section_preview.html"),
                "selected": {"selectedPreviewHtmlPath": "old-preview.html"},
                "selectedResults": [
                    {
                        "selectedResultIndex": 0,
                        "candidateWorkspace": "old-candidate",
                        "selectedPreviewHtmlPath": "old-preview.html",
                        "previewHtmlPath": "old-preview.html",
                        "ranking": {
                            "payload": {
                                "finalOutputValidation": {
                                    "renderEvidence": {"contactSheetPaths": []}
                                }
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    powershell = r"""
$tokens = $null
$parseErrors = $null
$scriptAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WRAPPER_PATH, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { throw ($parseErrors | Out-String) }
$functionAst = $scriptAst.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Update-PackagedSelectionArtifactReferences'
}, $true)
if ($null -eq $functionAst) { throw 'Packaging manifest writer was not found.' }
function ConvertFrom-ReconstructionJson {
    param([Parameter(ValueFromPipeline)][string]$Json)
    process { ConvertFrom-Json -InputObject $Json }
}
function Get-ObjectProperty {
    param([object]$Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}
function Write-AtomicJsonDocument {
    param([string]$Path, [object]$InputObject, [int]$Depth)
    ConvertTo-Json -InputObject $InputObject -Depth $Depth |
        Set-Content -LiteralPath $Path -Encoding utf8
}
Invoke-Expression $functionAst.Extent.Text
Update-PackagedSelectionArtifactReferences `
    -SelectionManifestPath $env:MANIFEST_PATH `
    -OptionIndex 1 `
    -SelectedOutputDirectory (Split-Path -Parent $env:MANIFEST_PATH) `
    -AuditOutputDirectory (Join-Path (Split-Path -Parent $env:MANIFEST_PATH) 'audit') `
    -PackagedSkeletonPath 'selected-skeleton.json' `
    -ReviewVideoPath 'selected-preview.webm' `
    -InputVideoPath 'selected-input.mp4' `
    -InputSourceVideoPath 'source-input.mp4' `
    -PreviewHtmlPath $env:PREVIEW_PATH `
    -InteractivePreviewHtmlPath 'selected-interactive.html' `
    -ContactSheetPaths @()
"""
    env = os.environ.copy()
    env.update(
        WRAPPER_PATH=str(WRAPPER),
        MANIFEST_PATH=str(manifest_path),
        PREVIEW_PATH=str(selected_preview),
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", powershell],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    packaged = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert packaged["selectedPreviewHtmlPath"] == str(selected_preview)
    assert packaged["selected"]["selectedPreviewHtmlPath"] == str(selected_preview)
