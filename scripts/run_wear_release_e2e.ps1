Param(
    [switch]$SmokeOnly,
    [string]$TestClass,
    [string]$TestMethod,
    [string]$WearEmulatorSerial,
    [string]$WearAvdName,
    [switch]$IncludeCrossDeviceTests = $false,
    [switch]$NoLogcat = $false,
    [string]$TimingOutputPath
)

$wearE2eScript = Join-Path $PSScriptRoot "run_wear_e2e.ps1"
$arguments = @{
    BuildType = "release"
    StartEmulatorIfNeeded = $true
}

foreach ($parameterName in @(
    "SmokeOnly",
    "TestClass",
    "TestMethod",
    "WearEmulatorSerial",
    "WearAvdName",
    "IncludeCrossDeviceTests",
    "NoLogcat",
    "TimingOutputPath"
)) {
    if ($PSBoundParameters.ContainsKey($parameterName)) {
        $arguments[$parameterName] = $PSBoundParameters[$parameterName]
    }
}

& $wearE2eScript @arguments
exit $LASTEXITCODE
