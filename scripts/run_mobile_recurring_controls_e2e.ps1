param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^emulator-\d+$')]
    [string]$PhoneEmulatorSerial,
    [string]$AppPackage = "com.gabstra.myworkoutassistant.debug",
    [ValidatePattern('^[A-Za-z0-9_]+$')]
    [string]$TestClass = "RecurringControlsAuthoringE2ETest",
    [ValidatePattern('^[A-Za-z0-9_]+$')]
    [string]$TestMethod
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Push-Location $repoRoot
try {
    $devices = & adb devices
    $deviceLine = $devices | Where-Object { $_ -match "^$([regex]::Escape($PhoneEmulatorSerial))\s+device$" } | Select-Object -First 1
    if (-not $deviceLine) {
        throw "Phone emulator '$PhoneEmulatorSerial' is not connected and ready."
    }
    $qemu = (& adb -s $PhoneEmulatorSerial shell getprop ro.kernel.qemu 2>$null).Trim()
    if ($qemu -ne "1") {
        throw "Refusing instrumentation: '$PhoneEmulatorSerial' is not verified as an Android emulator."
    }

    $appApk = "mobile/build/outputs/apk/debug/mobile-debug.apk"
    $testApk = "mobile/build/outputs/apk/androidTest/debug/mobile-debug-androidTest.apk"
    foreach ($apk in @($appApk, $testApk)) {
        if (-not (Test-Path $apk)) {
            throw "Prebuilt APK is missing: $apk. This runner does not build APKs."
        }
    }

    & adb -s $PhoneEmulatorSerial install -r $appApk | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Failed to install app APK on '$PhoneEmulatorSerial'." }
    & adb -s $PhoneEmulatorSerial install -r $testApk | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Failed to install instrumentation APK on '$PhoneEmulatorSerial'." }

    $runner = "$AppPackage.test/androidx.test.runner.AndroidJUnitRunner"
    $testSelector = "com.gabstra.myworkoutassistant.e2e.$TestClass"
    if ($TestMethod) { $testSelector += "#$TestMethod" }
    $output = & adb -s $PhoneEmulatorSerial shell am instrument -w -r -e class $testSelector $runner 2>&1
    $instrumentationExitCode = $LASTEXITCODE
    $logDirectory = Join-Path $repoRoot "build/wod_session"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $testLogName = $TestClass
    if ($TestMethod) { $testLogName += "-$TestMethod" }
    $logPath = Join-Path $logDirectory ("recurring-controls-{0}-{1}.log" -f $testLogName, (Get-Date -Format "yyyyMMdd-HHmmss"))
    @(
        "Device: $PhoneEmulatorSerial"
        "Test selector: $testSelector"
        "Command exit code: $instrumentationExitCode"
        ""
        $output
    ) | Tee-Object -FilePath $logPath | Out-Host
    $outputText = $output -join [Environment]::NewLine
    if ($instrumentationExitCode -ne 0 -or
        $outputText -notmatch "(?m)^OK \([1-9]\d* tests?\)\s*$" -or
        $outputText -match "FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed") {
        throw "Recurring-controls instrumentation failed on '$PhoneEmulatorSerial'."
    }
} finally {
    Pop-Location
}
