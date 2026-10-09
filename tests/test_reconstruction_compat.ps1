$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/reconstruction_compat.ps1')

$payload = '{"whamResultsPkl":"raw/wham/wham_output.pkl","wham":{"whamCacheStatus":"reused","WHAMFrame":1,"WhamReady":true},"whamRunSeconds":3,"reconstructionRunSeconds":4,"items":[{"whamPath":"cache/wham/item.json"}]}' |
    ConvertFrom-Json |
    Convert-ReconstructionMetadata

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

Write-Host 'Reconstruction metadata compatibility test passed.'
