$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $root 'scripts/reconstruction_compat.ps1')
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts/run_exercise_motion_workout_plan.ps1'), [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @(
    'Write-AtomicJsonDocument',
    'Get-SelectedOutputArtifacts',
    'Test-SourceSelectionClearanceCurrent',
    'Get-ExpectedSourceClearanceContractSha256',
    'Remove-IntermediateArtifactFile',
    'Remove-ExerciseIntermediateArtifacts',
    'Get-ExistingSelectedSummary',
    'Test-SelectionNeedsPolicyReaudit',
    'Test-MovementSkeletonIntegrity',
    'Test-BakeStageReady',
    'Write-PublishedSelectionAcceptanceMarker'
)) {
    $node = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }.GetNewClosure(), $true)
    if ($null -eq $node) { throw "Missing function $name" }
    Invoke-Expression $node.Extent.Text
}
. (Join-Path $root 'scripts/motion_validation_policy.ps1')
$SelectionValidationPolicyVersion = 70
$SourceSelectionPolicyVersion = Get-MotionPythonValidationPolicyConstant -Name 'SOURCE_SELECTION_POLICY_VERSION'
$SourceSelectionClearancePolicyVersion = Get-MotionPythonValidationPolicyConstant -Name 'SOURCE_SELECTION_CLEARANCE_POLICY_VERSION'
$ArtifactRetention = 'debug'
$SkipPreReconstructionSourceValidation = $false
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
    $sourceManifestPath = Join-Path $selected 'source_segment_selection.json'
    $sourceSegmentPath = Join-Path $selected 'source_selected_segment.mp4'
    $reviewImagePath = Join-Path $selected 'source_review_frame.jpg'
    '{"sourcePrepReason":"pre_reconstruction_source_window_choice"}' | Set-Content $sourceManifestPath -NoNewline
    'retained' | Set-Content $sourceSegmentPath
    'reviewed image' | Set-Content $reviewImagePath
    $segmentHash = (Get-FileHash $sourceSegmentPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $imageHash = (Get-FileHash $reviewImagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $frameEvidence = @{ candidateId='A'; extractionProfileSha256=('1' * 64); images=@(@{ path=$reviewImagePath; sha256=$imageHash }) }
    $sourceClearance = @{ status='cleared'; sourceSelectionPolicyVersion=$SourceSelectionPolicyVersion; sourceSelectionClearancePolicyVersion=$SourceSelectionClearancePolicyVersion; sourceManifestSha256=(Get-FileHash $sourceManifestPath -Algorithm SHA256).Hash.ToLowerInvariant(); sourceManifestPath=$sourceManifestPath; selectedSegmentSha256=$segmentHash; selectedSegmentPath=$sourceSegmentPath; sourceCutReviewVideoPath=$sourceSegmentPath; sourceCutReviewVideoSha256=$segmentHash; sourceCutOriginalVideoPath=$sourceSegmentPath; sourceCutOriginalVideoSha256=$segmentHash; sourceCutReviewFrameEvidence=$frameEvidence; sourceCutReviewFrameEvidenceSha256=('2' * 64); authorizedCandidateId='A'; reviewedExerciseName='Squat'; exerciseMotionContractSha256=('0' * 64) }
    @{ selectionValidationPolicyVersion=70; sourceSelectionPolicyVersion=$SourceSelectionPolicyVersion; preReconstructionSourceValidationEnabled=$true; selected=@{ exerciseName='Squat'; selectedWearSkeletonPath=$skeletonPath; sourceSelectionClearance=$sourceClearance } } | ConvertTo-Json -Depth 8 | Set-Content $selectionPath
    $marker = @{ status='valid'; selectionValidationPolicyVersion=70; sourceSelectionPolicyVersion=$SourceSelectionPolicyVersion; retainedSelectedArtifactFallbackVersion=11 }
    $markerPath = Join-Path $selected 'revalidation.json'
    $marker | ConvertTo-Json | Set-Content $markerPath
    $item = [pscustomobject]@{ exerciseWorkspace=$fixture; bakeWorkspace=(Join-Path $fixture 'bake'); exerciseSlug='squat'; exerciseName='Squat'; exerciseId='squat-id'; currentContractSha256=('0' * 64) }
    if (-not (Get-ExistingSelectedSummary $item)) { throw 'Current validation must permit explicitly source-validation-disabled lineage.' }
    $marker.status = 'needs_manual_review'
    $marker.selectionValidationPolicyVersion = 69
    $marker | ConvertTo-Json | Set-Content $markerPath
    if (-not (Test-SelectionNeedsPolicyReaudit $item)) { throw 'An old negative selection-policy verdict must trigger retained-artifact re-audit.' }
    $marker.selectionValidationPolicyVersion = 70
    $marker | ConvertTo-Json | Set-Content $markerPath
    if (Test-SelectionNeedsPolicyReaudit $item) { throw 'A current negative verdict must remain terminal under unchanged policies.' }
    $marker.status = 'valid'
    $marker.sourceSelectionPolicyVersion = $SourceSelectionPolicyVersion - 1
    $marker | ConvertTo-Json | Set-Content $markerPath
    if (Get-ExistingSelectedSummary $item) { throw 'A stale source-policy marker was reused.' }
    if (-not (Test-SelectionNeedsPolicyReaudit $item)) { throw 'A stale source-policy marker must trigger source re-audit.' }
    $marker.sourceSelectionPolicyVersion = $SourceSelectionPolicyVersion
    $marker | ConvertTo-Json | Set-Content $markerPath
    $item.currentContractSha256 = ('3' * 64)
    if (Get-ExistingSelectedSummary $item) { throw 'A same-name selection with a different current contract must not be reused.' }
    if (-not (Test-SelectionNeedsPolicyReaudit $item)) { throw 'A same-name contract change must trigger source re-audit.' }
    $item.currentContractSha256 = ('0' * 64)
    if (-not (Get-ExistingSelectedSummary $item)) { throw 'A current source clearance and marker must be reusable.' }
    'changed reviewed image' | Set-Content $reviewImagePath
    if (Get-ExistingSelectedSummary $item) { throw 'Changed scorecard image bytes must invalidate reuse even when the selection manifest and marker are unchanged.' }
    'reviewed image' | Set-Content $reviewImagePath
    $item.exerciseName = 'Lunge'
    if (Get-ExistingSelectedSummary $item) { throw 'A selected source clearance for another exercise must not be reused.' }
    if (-not (Test-SelectionNeedsPolicyReaudit $item)) { throw 'A mismatched exercise identity must trigger source re-audit.' }
    $item.exerciseName = 'Squat'
    'changed source' | Set-Content $sourceSegmentPath
    if (Get-ExistingSelectedSummary $item) { throw 'Changed source bytes must invalidate reuse even when the selection manifest and marker are unchanged.' }
    'retained' | Set-Content $sourceSegmentPath
    'changed manifest' | Set-Content $sourceManifestPath -NoNewline
    if (Get-ExistingSelectedSummary $item) { throw 'Changed source manifest bytes must invalidate reuse even when the selection manifest and marker are unchanged.' }
    '{"sourcePrepReason":"pre_reconstruction_source_window_choice"}' | Set-Content $sourceManifestPath -NoNewline
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
    @{ selectionValidationPolicyVersion=70; sourceSelectionPolicyVersion=$SourceSelectionPolicyVersion; preReconstructionSourceValidationEnabled=$true; selected=@{ exerciseName='Squat'; selectedWearSkeletonPath=$skeletonPath; sourceSelectionClearance=$sourceClearance } } | ConvertTo-Json -Depth 8 | Set-Content $selectionPath
    @{ status='invalid'; selectionValidationPolicyVersion=70; sourceSelectionPolicyVersion=$SourceSelectionPolicyVersion; reasons=@('stale_library_revalidation') } | ConvertTo-Json | Set-Content $markerPath
    Write-PublishedSelectionAcceptanceMarker -WorkItem $item -SelectedOutputDir $selected.FullName -SelectionManifestPath $selectionPath
    $published = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ($published.status -ne 'valid') { throw 'Published acceptance marker must be valid.' }
    if ([string]::IsNullOrWhiteSpace($published.selectedManifestSha256)) { throw 'Published marker must pin selection hash.' }
    if (-not (Get-ExistingSelectedSummary $item)) { throw 'Freshly published keep must be reusable after marker refresh.' }

    $cleanupBake = Join-Path $fixture 'cleanup_bake'
    $proofRoot = Join-Path $cleanupBake 'candidate_a'
    $proofSegmentDir = Join-Path $proofRoot 'segment_detection'
    $proofInputDir = Join-Path $proofRoot 'input'
    New-Item -ItemType Directory -Force -Path $proofSegmentDir, $proofInputDir | Out-Null
    $proofManifest = Join-Path $proofSegmentDir 'segment_selection.json'
    $proofSegment = Join-Path $proofInputDir 'selected_segment.mp4'
    $proofReview = Join-Path $proofInputDir 'review_source.mp4'
    $proofPoseReference = Join-Path $proofSegmentDir 'exact_source_pose_reference.json'
    $proofImage = Join-Path $proofRoot 'source_candidate_A' 'contact_sheet.jpg'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $proofImage) | Out-Null
    '{"exactSourcePhaseValidation":{"sourcePoseReferencePath":"' + $proofPoseReference.Replace('\', '\\') + '"},"sourcePrepReason":"pre_reconstruction_source_window_choice"}' | Set-Content $proofManifest -NoNewline
    'proof segment' | Set-Content $proofSegment
    'proof source' | Set-Content $proofReview
    'pose reference' | Set-Content $proofPoseReference
    'proof image' | Set-Content $proofImage
    $cleanupClearance = @{
        status='cleared'; sourceManifestPath=$proofManifest; selectedSegmentPath=$proofSegment
        sourceCutReviewVideoPath=$proofReview; sourceCutOriginalVideoPath=$proofReview
        sourceCutReviewFrameEvidence=@{ images=@(@{ path=$proofImage }) }
    }
    @{ selected=@{ sourceSelectionClearance=$cleanupClearance } } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $cleanupBake 'selection_manifest.json')
    $extraIntermediate = Join-Path $cleanupBake 'discard_this_intermediate.bin'
    'temporary' | Set-Content $extraIntermediate
    $lockedCheckpoint = Join-Path $proofRoot 'baked_stage_checkpoint.json'
    'checkpoint' | Set-Content $lockedCheckpoint
    $reader = [IO.File]::Open($lockedCheckpoint, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        Remove-ExerciseIntermediateArtifacts ([pscustomobject]@{ bakeWorkspace=$cleanupBake })
        if (-not (Test-Path -LiteralPath $lockedCheckpoint -PathType Leaf)) {
            throw 'A checkpoint held by a reader must be retained until cleanup can retry it.'
        }
    } finally {
        $reader.Dispose()
    }
    Remove-IntermediateArtifactFile -Path $lockedCheckpoint
    foreach ($proofPath in @($proofManifest, $proofSegment, $proofReview, $proofPoseReference, $proofImage)) {
        if (-not (Test-Path -LiteralPath $proofPath -PathType Leaf)) { throw "Source proof file was not retained: $proofPath" }
    }
    if (Test-Path -LiteralPath $lockedCheckpoint) { throw 'Unlocked checkpoint was not removed after the reader closed.' }
    if (Test-Path -LiteralPath $extraIntermediate) { throw 'Unneeded bake intermediate was not removed.' }
    $rawBake = Join-Path $fixture 'raw_cleanup_bake'
    $rawCandidate = Join-Path $rawBake 'candidate_raw'
    $rawSegmentDir = Join-Path $rawCandidate 'segment_detection'
    $rawInputDir = Join-Path $rawCandidate 'input'
    New-Item -ItemType Directory -Force -Path $rawSegmentDir, $rawInputDir | Out-Null
    $rawManifest = Join-Path $rawSegmentDir 'segment_selection.json'
    $rawSelectedSegment = Join-Path $rawInputDir 'selected_segment.mp4'
    '{"sourcePrepReason":"ranked_best_chunk"}' | Set-Content $rawManifest -NoNewline
    'raw segment' | Set-Content $rawSelectedSegment
    @{ selected=@{ sourceSelectionClearance=@{ status='not_required'; sourceManifestPath=$rawManifest; selectedSegmentPath=$rawSelectedSegment } } } |
        ConvertTo-Json -Depth 6 | Set-Content (Join-Path $rawBake 'selection_manifest.json')
    Remove-ExerciseIntermediateArtifacts ([pscustomobject]@{ bakeWorkspace=$rawBake })
    if (-not (Test-Path -LiteralPath $rawManifest -PathType Leaf) -or
        -not (Test-Path -LiteralPath $rawSelectedSegment -PathType Leaf)) {
        throw 'Explicit raw-source lineage proof files must survive debug cleanup.'
    }
    $emptyBake = Join-Path $fixture 'empty_cleanup_bake'
    New-Item -ItemType Directory -Force -Path $emptyBake | Out-Null
    'temporary' | Set-Content (Join-Path $emptyBake 'intermediate.bin')
    Remove-ExerciseIntermediateArtifacts ([pscustomobject]@{ bakeWorkspace=$emptyBake })
    if (Test-Path -LiteralPath $emptyBake) { throw 'Debug cleanup must still remove an empty proof-free bake root.' }

    Write-Output 'Selected reuse checks passed.'
} finally {
    # The fixture is the exact directory created above under the system temp root.
    $resolvedFixture = [IO.Path]::GetFullPath($fixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedFixture.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup path.' }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
