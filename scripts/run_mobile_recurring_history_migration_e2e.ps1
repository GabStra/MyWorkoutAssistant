param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^emulator-\d+$')]
    [string]$PhoneEmulatorSerial,
    [string]$AppPackage = 'com.gabstra.myworkoutassistant.debug'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $repoRoot
try {
    $deviceLine = (& adb devices) | Where-Object {
        $_ -match "^$([regex]::Escape($PhoneEmulatorSerial))\s+device$"
    } | Select-Object -First 1
    if (-not $deviceLine) {
        throw "Phone emulator '$PhoneEmulatorSerial' is not connected and ready."
    }

    $qemu = (& adb -s $PhoneEmulatorSerial shell getprop ro.kernel.qemu 2>$null).Trim()
    $boot = (& adb -s $PhoneEmulatorSerial shell getprop sys.boot_completed 2>$null).Trim()
    if ($qemu -ne '1' -or $boot -ne '1') {
        throw "Refusing migration instrumentation: '$PhoneEmulatorSerial' failed emulator/boot validation."
    }

    $appApk = 'mobile/build/outputs/apk/debug/mobile-debug.apk'
    $testApk = 'mobile/build/outputs/apk/androidTest/debug/mobile-debug-androidTest.apk'
    foreach ($apk in @($appApk, $testApk)) {
        if (-not (Test-Path -LiteralPath $apk)) {
            throw "Prebuilt APK is missing: $apk. This runner does not build APKs."
        }
    }

    foreach ($apk in @($appApk, $testApk)) {
        & adb -s $PhoneEmulatorSerial install -r $apk | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Install -r failed for '$apk' on '$PhoneEmulatorSerial'; no uninstall/clear fallback is used."
        }
    }

    $testClass = 'com.gabstra.myworkoutassistant.e2e.RecurringHistoryMigrationTest'
    $runner = "$AppPackage.test/androidx.test.runner.AndroidJUnitRunner"
    $instrumentOutput = & adb -s $PhoneEmulatorSerial shell am instrument -w -r -e class $testClass $runner 2>&1
    $instrumentExitCode = $LASTEXITCODE

    $logDirectory = Join-Path $repoRoot 'build/wod_session'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $logPath = Join-Path $logDirectory ("recurring-history-migration-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    @(
        "Device: $PhoneEmulatorSerial"
        "Test class: $testClass"
        "Command exit code: $instrumentExitCode"
        ''
        $instrumentOutput
    ) | Tee-Object -FilePath $logPath | Out-Host

    $outputText = $instrumentOutput -join [Environment]::NewLine
    if ($instrumentExitCode -ne 0 -or $outputText -notmatch '(?m)^OK \(' -or
        $outputText -match 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed') {
        throw "Recurring history migration instrumentation failed on '$PhoneEmulatorSerial'."
    }
} finally {
    Pop-Location
}
