$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'), [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @(
    'Get-ExistingSelectedSummary',
    'Test-MovementSkeletonIntegrity',
    'Test-BakeStageReady',
    'Write-PublishedSelectionAcceptanceMarker'
)) {
    $node = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }.GetNewClosure(), $true)
    if ($null -eq $node) { throw "Missing function $name" }
    Invoke-Expression $node.Extent.Text
}
$SelectionValidationPolicyVersion = 70
$RetainedSelectedRevalidationVersion = 3
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('motion-reuse-' + [guid]::NewGuid().ToString('N'))
$selected = New-Item -ItemType Directory -Path (Join-Path $fixture 'selected')
try {
    $skeletonPath = Join-Path $selected 'squat_wear_skeleton.json'
    @{ jointNames=@('pelvis'); frames=@(@{}, @{}); frameCount=2; fps=30 } | ConvertTo-Json -Depth 5 | Set-Content $skeletonPath
    foreach ($suffix in @('selected_preview.webm', 'selected_preview.html', 'selected_input.mp4')) {
        'retained' | Set-Content (Join-Path $selected "squat_$suffix")
    }
    $selectionPath = Join-Path $selected 'selection_manifest.json'
    @{ selectionValidationPolicyVersion=1; selected=@{ selectedWearSkeletonPath=$skeletonPath } } | ConvertTo-Json | Set-Content $selectionPath
    $marker = @{ status='valid'; selectionValidationPolicyVersion=70; retainedSelectedArtifactFallbackVersion=11 }
    $markerPath = Join-Path $selected 'revalidation.json'
    $marker | ConvertTo-Json | Set-Content $markerPath
    $item = [pscustomobject]@{ exerciseWorkspace=$fixture; bakeWorkspace=(Join-Path $fixture 'bake'); exerciseSlug='squat'; exerciseName='Squat'; exerciseId='squat-id' }
    if (-not (Get-ExistingSelectedSummary $item)) { throw 'Current validation must permit a legacy metadata format.' }
    $marker.status='invalid'
    $marker | ConvertTo-Json | Set-Content $markerPath
    if (Get-ExistingSelectedSummary $item) { throw 'Invalid selection reused.' }
    $marker.status='valid'
    $marker.selectedManifestSha256='different'
    $marker | ConvertTo-Json | Set-Content $markerPath
    if (Get-ExistingSelectedSummary $item) { throw 'Changed selection reused under a stale marker.' }
    $marker.Remove('selectedManifestSha256')
    $marker | ConvertTo-Json | Set-Content $markerPath
    '{}' | Set-Content $skeletonPath
    if (Get-ExistingSelectedSummary $item) { throw 'Corrupt skeleton reused.' }

    # Publishing a new keep must replace a stale invalid marker so resume reuses it.
    $RetainedSelectedRevalidationVersion = 12
    @{ jointNames=@('pelvis'); frames=@(@{}, @{}); frameCount=2; fps=30 } | ConvertTo-Json -Depth 5 | Set-Content $skeletonPath
    @{ selectionValidationPolicyVersion=70; selected=@{ selectedWearSkeletonPath=$skeletonPath } } | ConvertTo-Json | Set-Content $selectionPath
    @{ status='invalid'; selectionValidationPolicyVersion=70; reasons=@('stale_library_revalidation') } | ConvertTo-Json | Set-Content $markerPath
    Write-PublishedSelectionAcceptanceMarker -WorkItem $item -SelectedOutputDir $selected.FullName -SelectionManifestPath $selectionPath
    $published = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ($published.status -ne 'valid') { throw 'Published acceptance marker must be valid.' }
    if ([string]::IsNullOrWhiteSpace($published.selectedManifestSha256)) { throw 'Published marker must pin selection hash.' }
    if (-not (Get-ExistingSelectedSummary $item)) { throw 'Freshly published keep must be reusable after marker refresh.' }

    Write-Output 'Selected reuse checks passed.'
} finally {
    # The fixture is the exact directory created above under the system temp root.
    $resolvedFixture = [IO.Path]::GetFullPath($fixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup path.' }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
