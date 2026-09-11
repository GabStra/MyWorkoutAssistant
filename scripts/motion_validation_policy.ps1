function Get-MotionSelectionValidationPolicyVersion {
    # Read the validator's authoritative version without importing its heavy
    # Python dependencies or keeping another manually synchronized constant.
    $validatorPath = Join-Path $PSScriptRoot '..\exercise_motion_pkg\bake_and_rank.py'
    $validatorSource = Get-Content -LiteralPath $validatorPath -Raw -ErrorAction Stop
    $versionMatches = [regex]::Matches(
        $validatorSource,
        '(?m)^SELECTION_VALIDATION_POLICY_VERSION\s*=\s*(\d+)\s*$'
    )
    if ($versionMatches.Count -ne 1) {
        throw "Cannot determine the motion selection validation policy from $validatorPath."
    }
    return [int]$versionMatches[0].Groups[1].Value
}
