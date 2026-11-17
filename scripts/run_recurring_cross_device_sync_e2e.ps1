param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^emulator-\d+$')]
    [string]$PhoneEmulatorSerial,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^emulator-\d+$')]
    [string]$WearEmulatorSerial,
    [string]$ExpectedPhoneAvdName = 'Medium_Phone',
    [string]$ExpectedWearAvdName = 'codex_recurring_sync_20261115',
    [string]$AppPackage = 'com.gabstra.myworkoutassistant.debug',
    [ValidatePattern('^[A-Za-z0-9_-]{1,48}$')]
    [string]$RunId
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$mobileTestClass = 'com.gabstra.myworkoutassistant.e2e.RecurringCrossDevicePhoneSyncE2ETest'
$wearStoreClass = 'RecurringCrossDeviceStoreVerificationE2ETest'
$wearHistoryClass = 'WearRecurringCrossDeviceHistoryProducerE2ETest'

function Assert-IsolatedReadOnlyEmulator {
    param(
        [string]$Serial,
        [string]$ExpectedAvdName,
        [ValidateSet('phone', 'watch')]
        [string]$Kind
    )

    $deviceLine = (& adb devices) | Where-Object {
        $_ -match "^$([regex]::Escape($Serial))\s+device$"
    } | Select-Object -First 1
    if (-not $deviceLine) { throw "Required emulator '$Serial' is not connected and ready." }

    $qemu = (& adb -s $Serial shell getprop ro.kernel.qemu 2>$null).Trim()
    $boot = (& adb -s $Serial shell getprop sys.boot_completed 2>$null).Trim()
    $avdName = (& adb -s $Serial shell getprop ro.boot.qemu.avd_name 2>$null).Trim()
    $characteristics = (& adb -s $Serial shell getprop ro.build.characteristics 2>$null).Trim()
    if ($qemu -ne '1' -or $boot -ne '1' -or $avdName -ne $ExpectedAvdName) {
        throw "Refusing '$Serial': expected booted emulator AVD '$ExpectedAvdName', got qemu='$qemu', boot='$boot', avd='$avdName'."
    }
    if ($Kind -eq 'watch' -and $characteristics -notmatch 'watch') {
        throw "Refusing '$Serial': expected a Wear emulator, got characteristics '$characteristics'."
    }
    if ($Kind -eq 'phone' -and $characteristics -match 'watch') {
        throw "Refusing '$Serial': expected a phone emulator, got characteristics '$characteristics'."
    }

    $consolePort = [int]($Serial -replace '^emulator-', '')
    $adbPort = $consolePort + 1
    $escapedAvdName = [regex]::Escape($ExpectedAvdName)
    $portPattern = "(?:-port\s+$consolePort(?:\s|$)|-ports\s+$consolePort,$adbPort(?:\s|$))"
    $qemuProcesses = Get-CimInstance Win32_Process `
        -Filter "Name='qemu-system-x86_64-headless.exe'" `
        -Property ProcessId, CommandLine
    $ownedQemu = @($qemuProcesses | Where-Object {
        $_.CommandLine -match "-avd\s+$escapedAvdName(?:\s|$)" -and
            $_.CommandLine -match $portPattern
    })
    if ($ownedQemu.Count -ne 1 -or
        $ownedQemu[0].CommandLine -notmatch '(?:^|\s)-read-only(?:\s|$)' -or
        $ownedQemu[0].CommandLine -notmatch '(?:^|\s)-no-snapshot(?:\s|$)') {
        throw "Refusing '$Serial': process arguments do not prove one read-only/no-snapshot qemu for '$ExpectedAvdName' on port $consolePort."
    }

    [pscustomobject]@{
        Serial = $Serial
        AvdName = $avdName
        Characteristics = $characteristics
        ConsolePort = $consolePort
        QemuProcessId = $ownedQemu[0].ProcessId
    }
}

function Assert-ActualWearPairing {
    $phoneOutput = & adb -s $PhoneEmulatorSerial shell am broadcast `
        -a com.google.android.gms.wearable.EMULATOR `
        --es operation get-pairing-status 2>&1
    $phoneStatus = $phoneOutput -join "`n"
    if ($phoneStatus -notmatch 'result=1') {
        throw "Phone emulator pairing endpoint is unavailable or not paired. Status: $phoneStatus"
    }

    $wearOutput = & adb -s $WearEmulatorSerial shell am broadcast `
        -a com.google.android.gms.wearable.EMULATOR `
        --es operation get-pairing-status 2>&1
    $wearStatus = $wearOutput -join "`n"
    if ($wearStatus -notmatch 'result=1' -or $wearStatus -notmatch 'Peer:\[[^\]]+,true,true\]') {
        throw "Wear emulator is not paired to an online phone emulator. Status: $wearStatus"
    }
    Write-Host "Verified Google Play Services Wear pairing on both target emulators."
}

function Install-Preserved {
    param([string]$Serial, [string]$ApkPath)
    if (-not (Test-Path -LiteralPath $ApkPath)) {
        throw "Required prebuilt APK is missing: $ApkPath. This runner does not build APKs."
    }
    Write-Host "Installing with data preservation: $ApkPath -> $Serial"
    & adb -s $Serial install -r $ApkPath | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "install -r failed for '$ApkPath' on '$Serial'; no uninstall/clear retry is used."
    }
}

function Assert-InstrumentationSuccess {
    param([string]$Phase, [string[]]$Output, [int]$ExitCode)
    $text = $Output -join [Environment]::NewLine
    if ($ExitCode -ne 0 -or $text -notmatch '(?m)^\s*OK \(' -or
        $text -match 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed') {
        throw "$Phase instrumentation did not pass. Inspect the captured phase log."
    }
}

function Invoke-MobileTestMethod {
    param([string]$MethodName, [string]$LogPath)
    $classArgument = "$mobileTestClass#$MethodName"
    Write-Host "Running phone instrumentation: $classArgument"
    $output = & adb -s $PhoneEmulatorSerial shell am instrument -w -r `
        -e class $classArgument -e run_id $RunId `
        "$AppPackage.test/androidx.test.runner.AndroidJUnitRunner" 2>&1
    $exitCode = $LASTEXITCODE
    @(
        "Device: $PhoneEmulatorSerial"
        "Test: $classArgument"
        "Run id: $RunId"
        "Command exit code: $exitCode"
        ''
        $output
    ) | Tee-Object -FilePath $LogPath | Out-Host
    Assert-InstrumentationSuccess -Phase $classArgument -Output $output -ExitCode $exitCode
}

function Invoke-WearTestMethod {
    param([string]$ClassName, [string]$MethodName, [string]$PhaseName)
    $runnerPath = Join-Path $scriptRoot 'run_wear_e2e.ps1'
    $timingPath = Join-Path $runLogDirectory "$PhaseName.timings.json"
    $arguments = @(
        '-NoProfile', '-File', $runnerPath,
        '-TestClass', $ClassName,
        '-TestMethod', $MethodName,
        '-WearEmulatorSerial', $WearEmulatorSerial,
        '-StartEmulatorIfNeeded:$false',
        '-SkipAssemble', '-SkipInstall',
        '-InstrumentationExtras', "run_id=$RunId",
        '-TimingOutputPath', $timingPath
    )
    $stdoutPath = Join-Path $runLogDirectory "$PhaseName.stdout.log"
    $stderrPath = Join-Path $runLogDirectory "$PhaseName.stderr.log"
    Write-Host "Running Wear E2E wrapper: $ClassName#$MethodName"
    $process = Start-Process -FilePath 'pwsh' -ArgumentList $arguments `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $process.WaitForExit()
    $process.Refresh()
    $output = @()
    if (Test-Path -LiteralPath $stdoutPath) { $output += Get-Content -LiteralPath $stdoutPath }
    if (Test-Path -LiteralPath $stderrPath) { $output += Get-Content -LiteralPath $stderrPath }
    $exitCode = $process.ExitCode
    @(
        "Device: $WearEmulatorSerial"
        "Test: $ClassName#$MethodName"
        "Run id: $RunId"
        "Process id: $($process.Id)"
        "Command exit code: $exitCode"
        ''
        $output
    ) | Tee-Object -FilePath (Join-Path $runLogDirectory "$PhaseName.combined.log") | Out-Host
    Assert-InstrumentationSuccess -Phase "$ClassName#$MethodName" -Output $output -ExitCode $exitCode
}

function Save-DeviceLogcat {
    param([string]$Serial, [string]$Name)
    $line = (& adb devices) | Where-Object { $_ -match "^$([regex]::Escape($Serial))\s+device$" } | Select-Object -First 1
    if ($line) {
        & adb -s $Serial logcat -d -t 8000 -v time |
            Set-Content -LiteralPath (Join-Path $runLogDirectory "$Name.logcat.log") -Encoding utf8
    }
}

if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId = [guid]::NewGuid().ToString('N') }
$runLogDirectory = Join-Path $repoRoot "build/wod_session/recurring-cross-device/$RunId"
New-Item -ItemType Directory -Path $runLogDirectory -Force | Out-Null
$transcriptPath = Join-Path $runLogDirectory 'orchestrator.transcript.log'
$transcriptStarted = $false
$phoneInstalled = $false
$scratchMayExist = $false
$primaryFailure = $null
$cleanupFailure = $null
Push-Location $repoRoot
try {
    Start-Transcript -LiteralPath $transcriptPath -Force | Out-Null
    $transcriptStarted = $true
    Write-Host "Run id: $RunId"
    Write-Host "Scoped evidence directory: $runLogDirectory"

    $phoneInfo = Assert-IsolatedReadOnlyEmulator `
        -Serial $PhoneEmulatorSerial -ExpectedAvdName $ExpectedPhoneAvdName -Kind phone
    $wearInfo = Assert-IsolatedReadOnlyEmulator `
        -Serial $WearEmulatorSerial -ExpectedAvdName $ExpectedWearAvdName -Kind watch
    $phoneInfo, $wearInfo | Format-Table -AutoSize | Out-Host
    Assert-ActualWearPairing

    $mobileAppApk = 'mobile/build/outputs/apk/debug/mobile-debug.apk'
    $mobileTestApk = 'mobile/build/outputs/apk/androidTest/debug/mobile-debug-androidTest.apk'
    $wearAppApk = 'wearos/build/outputs/apk/debug/wearos-debug.apk'
    $wearTestApk = 'wearos/build/outputs/apk/androidTest/debug/wearos-debug-androidTest.apk'
    Install-Preserved -Serial $PhoneEmulatorSerial -ApkPath $mobileAppApk
    Install-Preserved -Serial $PhoneEmulatorSerial -ApkPath $mobileTestApk
    Install-Preserved -Serial $WearEmulatorSerial -ApkPath $wearAppApk
    Install-Preserved -Serial $WearEmulatorSerial -ApkPath $wearTestApk
    $phoneInstalled = $true

    # This test adds its run-scoped rows to the shared store and scratch profile only.
    $scratchMayExist = $true
    Invoke-MobileTestMethod `
        -MethodName 'prepareRecurringCrossDeviceProfileAndPushToWear' `
        -LogPath (Join-Path $runLogDirectory 'phone-prep-and-push.log')

    # Reload the Wear app process from persisted files before verifying its received store.
    & adb -s $WearEmulatorSerial shell am force-stop $AppPackage
    if ($LASTEXITCODE -ne 0) { throw 'Could not force-stop the Wear app before store reopen verification.' }
    Invoke-WearTestMethod `
        -ClassName $wearStoreClass `
        -MethodName 'phoneSyncRetainsRecurringFamilyOrderTracksPoliciesAndPlanSuggestionSetting' `
        -PhaseName 'wear-store-verification'

    Invoke-WearTestMethod `
        -ClassName $wearHistoryClass `
        -MethodName 'completedRecurringHistorySnapshotsSendOverDataLayerAndCanBeReplayed' `
        -PhaseName 'wear-history-producer-replay'

    # The Wear sender waits for its production Data Layer send result; stop/reopen the phone app
    # afterward so the final verifier reads persisted Room rows through a fresh process.
    & adb -s $PhoneEmulatorSerial shell am force-stop $AppPackage
    if ($LASTEXITCODE -ne 0) { throw 'Could not force-stop the phone app before history reopen verification.' }
    Invoke-MobileTestMethod `
        -MethodName 'verifyWearRecurringHistorySnapshotsAndCleanScratchProfile' `
        -LogPath (Join-Path $runLogDirectory 'phone-history-verification.log')

    $scratchMayExist = $false
    Write-Host "Recurring cross-device sync E2E completed successfully for run $RunId." -ForegroundColor Green
} catch {
    $primaryFailure = $_
} finally {
    if ($scratchMayExist -and $phoneInstalled) {
        try {
            Invoke-MobileTestMethod `
                -MethodName 'cleanupRecurringCrossDeviceScratchProfile' `
                -LogPath (Join-Path $runLogDirectory 'phone-finally-cleanup.log')
        } catch {
            $cleanupFailure = $_
        }
    }
    Save-DeviceLogcat -Serial $PhoneEmulatorSerial -Name 'phone'
    Save-DeviceLogcat -Serial $WearEmulatorSerial -Name 'wear'
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    Pop-Location
}

if ($primaryFailure) { throw $primaryFailure }
if ($cleanupFailure) { throw $cleanupFailure }
