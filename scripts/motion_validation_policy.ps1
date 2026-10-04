function Get-MotionPythonValidationPolicyConstant {
    param([Parameter(Mandatory = $true)][string]$Name)

    # Read authoritative validator constants without importing its heavy
    # Python dependencies or keeping manually synchronized copies.
    $validatorPath = Join-Path $PSScriptRoot '..\exercise_motion_pkg\bake_and_rank.py'
    $validatorSource = Get-Content -LiteralPath $validatorPath -Raw -ErrorAction Stop
    $versionMatches = [regex]::Matches(
        $validatorSource,
        ('(?m)^{0}\s*=\s*(\d+)\s*$' -f [regex]::Escape($Name))
    )
    if ($versionMatches.Count -ne 1) {
        throw "Cannot determine motion validation policy constant '$Name' from $validatorPath."
    }
    return [int]$versionMatches[0].Groups[1].Value
}

function Get-MotionSelectionValidationPolicyVersion {
    return Get-MotionPythonValidationPolicyConstant -Name 'SELECTION_VALIDATION_POLICY_VERSION'
}

function Get-MotionRetainedSelectedRevalidationVersion {
    return Get-MotionPythonValidationPolicyConstant -Name 'RETAINED_SELECTED_REVALIDATION_VERSION'
}
