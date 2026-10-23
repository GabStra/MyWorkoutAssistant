$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/reconstruction_compat.ps1')

$payload = '{"whamResultsPkl":"raw/wham/wham_output.pkl","wham":{"whamCacheStatus":"reused","WHAMFrame":1,"WhamReady":true},"whamRunSeconds":3,"reconstructionRunSeconds":4,"items":[{"whamPath":"cache/wham/item.json"}]}' |
    ConvertFrom-ReconstructionJson

if ($payload.reconstructionResultsPkl -ne 'raw/wham/wham_output.pkl') {
    throw 'Normalization changed a filesystem path value.'
}
if ($payload.reconstruction.reconstructionCacheStatus -ne 'reused' -or
    $payload.reconstruction.RECONSTRUCTIONFrame -ne 1 -or
    -not $payload.reconstruction.ReconstructionReady) {
    throw 'Nested legacy metadata keys were not normalized.'
}
if ($payload.reconstructionRunSeconds -ne 4) {
    throw 'The legacy alias overwrote an explicitly current field.'
}
if ($payload.items[0].reconstructionPath -ne 'cache/wham/item.json') {
    throw 'Normalization changed a nested path value or missed its key.'
}

$approvedAtUtc = '2026-10-22T11:27:56.244742+00:00'
$approvedPlan = ('{"motionContext":{"exerciseDefinition":{"review":{"approvedAtUtc":"' +
    $approvedAtUtc + '"}}}}') | ConvertFrom-ReconstructionJson
$approvedTimestamp = $approvedPlan.motionContext.exerciseDefinition.review.approvedAtUtc
if ($approvedTimestamp -isnot [string] -or $approvedTimestamp -cne $approvedAtUtc) {
    throw 'ISO timestamp strings must retain their exact JSON type and text.'
}
$serializedApprovedPlan = $approvedPlan | ConvertTo-Json -Depth 16 -Compress
if (-not $serializedApprovedPlan.Contains('"approvedAtUtc":"' + $approvedAtUtc + '"')) {
    throw 'Plan serialization changed the approved timestamp used for cache identity.'
}

$escaped = '{"\u0077ham":{"\u0057HAMFrame":1}}' | ConvertFrom-ReconstructionJson
if ($escaped.reconstruction.RECONSTRUCTIONFrame -ne 1) {
    throw 'Escaped legacy keys were not normalized.'
}

# Current metadata must not invoke the recursive legacy converter.
function Convert-ReconstructionMetadata { throw 'Current metadata entered legacy conversion.' }
$current = '{"reconstruction":{"frames":[[1,2,3],[4,5,6]],"caption":"\u2019"}}' |
    ConvertFrom-ReconstructionJson
if ($current.reconstruction.frames.Count -ne 2 -or $current.reconstruction.frames[1][2] -ne 6) {
    throw 'Current metadata lost nested movement data.'
}
$invalidRejected = $false
try { '{invalid' | ConvertFrom-ReconstructionJson -ErrorAction Stop } catch { $invalidRejected = $true }
if (-not $invalidRejected) { throw 'Invalid JSON was accepted.' }

Write-Host 'Reconstruction metadata compatibility test passed.'
