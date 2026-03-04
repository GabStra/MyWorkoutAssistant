Param(
    [string]$WearTestClass = "WearCrossDeviceSyncProducerE2ETest",
    [string]$WearPhoneToWatchHistoryTestClass = "PhoneToWearWorkoutHistorySyncVerificationE2ETest",
    [string]$WearVsLastComparisonTestClass = "PhoneToWearVsLastComparisonE2ETest",
    [string]$MobilePrepTestClass = "com.gabstra.myworkoutassistant.e2e.PhoneSyncPreparationTest",
    [string]$MobileResetTestClass = "com.gabstra.myworkoutassistant.e2e.PhoneSyncResetStateTest",
    [string]$MobileTestClass = "com.gabstra.myworkoutassistant.e2e.WorkoutSyncVerificationTest",
    [string]$ExpectedWorkoutName = "Cross Device Sync Workout",
    [string]$AppPackage = "com.gabstra.myworkoutassistant.debug",
    [string]$WearEmulatorSerial,
    [string]$PhoneEmulatorSerial,
    [switch]$StartEmulatorIfNeeded = $true,
    [string]$WearAvdName,
    [string]$PhoneAvdName,
    [switch]$SkipWearRebuildAfterFirstRun = $true,
    [switch]$FastTimeoutProfile = $false,
    [string]$TimingOutputPath
)

$ErrorActionPreference = "Stop"
$runStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$timings = [ordered]@{}
$timings["startedAtUtc"] = (Get-Date).ToUniversalTime().ToString("o")
$timings["skipWearRebuildAfterFirstRun"] = $SkipWearRebuildAfterFirstRun.IsPresent
$timings["fastTimeoutProfile"] = $FastTimeoutProfile.IsPresent

function Save-TimingOutput {
    param(
        [hashtable]$timingMap,
        [string]$outputPath
    )

    if ([string]::IsNullOrWhiteSpace($outputPath)) {
        return
    }

    $parent = Split-Path -Parent $outputPath
    if (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $timingMap["endedAtUtc"] = (Get-Date).ToUniversalTime().ToString("o")
    ($timingMap | ConvertTo-Json -Depth 10) | Out-File -FilePath $outputPath -Encoding utf8
    Write-Host "Timing output saved to: $outputPath" -ForegroundColor Green
}

function Get-ConnectedDevices {
    $lines = & adb devices
    $devices = @()
    $lines | Select-Object -Skip 1 | ForEach-Object {
        $line = $_.Trim()
        if ($line -match "^(\S+)\s+(\S+)$") {
            $devices += [PSCustomObject]@{
                Serial = $Matches[1]
                State = $Matches[2]
            }
        }
    }
    return $devices
}

function Get-DeviceCharacteristics([string]$serial) {
    return (& adb -s $serial shell getprop ro.build.characteristics 2>$null).Trim()
}

function Is-Emulator([string]$serial) {
    return $serial -like "emulator-*"
}

function Get-DeviceKind([string]$serial) {
    $characteristics = Get-DeviceCharacteristics $serial
    if ($characteristics -match "watch") {
        return "watch"
    }
    return "phone"
}

function Resolve-EmulatorPath {
    $candidates = @(
        "$env:ANDROID_SDK_ROOT\emulator\emulator.exe",
        "$env:ANDROID_HOME\emulator\emulator.exe",
        "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }

    $cmd = Get-Command emulator -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function Wait-ForEmulatorBoot([string]$serial, [int]$timeoutSeconds = 240) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $bootCompleted = (& adb -s $serial shell getprop sys.boot_completed 2>$null).Trim()
        if ($bootCompleted -eq "1") {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Start-Emulator([string]$deviceKind, [string]$forcedAvdName = $null) {
    $emulatorPath = Resolve-EmulatorPath
    if (-not $emulatorPath) {
        throw "Could not find emulator binary. Set ANDROID_SDK_ROOT/ANDROID_HOME or add emulator to PATH."
    }

    $avds = & $emulatorPath -list-avds
    $avdNameToUse = $forcedAvdName
    if (-not $avdNameToUse) {
        if ($deviceKind -eq "watch") {
            $avdNameToUse = ($avds | Where-Object { $_ -match "wear|watch" } | Select-Object -First 1)
        } else {
            $avdNameToUse = ($avds | Where-Object { $_ -notmatch "wear|watch" } | Select-Object -First 1)
        }
    }

    if (-not $avdNameToUse) {
        throw "No suitable AVD found for kind '$deviceKind'. Create one or pass explicit AVD name."
    }

    Write-Host "Starting $deviceKind emulator AVD: $avdNameToUse" -ForegroundColor Yellow
    $before = (Get-ConnectedDevices | Where-Object { Is-Emulator $_.Serial }).Serial
    Start-Process -FilePath $emulatorPath -ArgumentList @("-avd", $avdNameToUse) | Out-Null

    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        $connected = Get-ConnectedDevices | Where-Object { $_.State -eq "device" -and (Is-Emulator $_.Serial) }
        $newDevice = $connected | Where-Object { $_.Serial -notin $before } | Select-Object -First 1
        if (-not $newDevice) { continue }
        if (Get-DeviceKind $newDevice.Serial -ne $deviceKind) { continue }
        if (Wait-ForEmulatorBoot $newDevice.Serial) {
            return $newDevice.Serial
        }
    }

    throw "Timed out waiting for $deviceKind emulator to boot."
}

function Resolve-EmulatorSerial([string]$preferredSerial, [string]$kind, [string]$avdName) {
    if ($preferredSerial) {
        $devices = Get-ConnectedDevices
        $match = $devices | Where-Object {
            $_.State -eq "device" -and $_.Serial -eq $preferredSerial -and
            (Is-Emulator $_.Serial) -and (Get-DeviceKind $_.Serial) -eq $kind
        } | Select-Object -First 1
        if (-not $match) {
            throw "Provided serial '$preferredSerial' is not a connected $kind emulator."
        }
        return $match.Serial
    }

    $devices = Get-ConnectedDevices
    $running = $devices | Where-Object {
        $_.State -eq "device" -and (Is-Emulator $_.Serial) -and (Get-DeviceKind $_.Serial) -eq $kind
    } | Select-Object -First 1
    if ($running) {
        return $running.Serial
    }

    if ($StartEmulatorIfNeeded) {
        return Start-Emulator -deviceKind $kind -forcedAvdName $avdName
    }

    return $null
}

function Install-WearDebugApp([string]$watchSerial) {
    Write-Host "Building and installing Wear debug app on watch emulator..." -ForegroundColor Cyan
    & .\gradlew :wearos:assembleDebug
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to assemble wear debug app."
    }

    $wearApk = "wearos/build/outputs/apk/debug/wearos-debug.apk"
    if (-not (Test-Path $wearApk)) {
        throw "Wear APK not found at $wearApk"
    }

    & adb -s $watchSerial install -r $wearApk | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install wear debug app on $watchSerial"
    }
}

function Install-MobileDebugAndTestApks([string]$phoneSerial) {
    Write-Host "Building and installing mobile debug + androidTest APKs on phone emulator..." -ForegroundColor Cyan
    & .\gradlew :mobile:assembleDebug :mobile:assembleDebugAndroidTest
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to assemble mobile debug/test APKs."
    }

    $mobileApk = "mobile/build/outputs/apk/debug/mobile-debug.apk"
    $mobileTestApk = "mobile/build/outputs/apk/androidTest/debug/mobile-debug-androidTest.apk"
    if (-not (Test-Path $mobileApk)) {
        throw "Mobile APK not found at $mobileApk"
    }
    if (-not (Test-Path $mobileTestApk)) {
        throw "Mobile test APK not found at $mobileTestApk"
    }

    & adb -s $phoneSerial install -r $mobileApk | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install mobile debug app on $phoneSerial"
    }

    & adb -s $phoneSerial install -r $mobileTestApk | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install mobile androidTest APK on $phoneSerial"
    }
}

function Run-MobileInstrumentationClass([string]$phoneSerial, [string]$className, [string]$appPackage, [switch]$fastTimeoutProfile) {
    Write-Host "Running mobile instrumentation class: $className" -ForegroundColor Cyan
    $runner = "$appPackage.test/androidx.test.runner.AndroidJUnitRunner"
    $instrumentArgs = @("-s", $phoneSerial, "shell", "am", "instrument", "-w", "-r", "-e", "class", $className)
    if ($fastTimeoutProfile) {
        $instrumentArgs += @("-e", "e2e_profile", "fast")
    }
    $instrumentArgs += $runner
    Write-Host ("adb " + ($instrumentArgs -join " ")) -ForegroundColor Gray
    $instrumentOutput = & adb $instrumentArgs 2>&1
    $instrumentOutput | Out-Host

    $exitCode = $LASTEXITCODE
    $outputText = $instrumentOutput -join "`n"
    $hasOkSummary = $outputText -match "(?m)^OK \("
    $hasFailureMarker = $outputText -match "FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed"
    if ($exitCode -ne 0 -or $hasFailureMarker -or -not $hasOkSummary) {
        throw "Mobile instrumentation failed for class '$className'."
    }
}

function Test-DeviceOnline([string]$serial) {
    return ((& adb -s $serial get-state 2>$null).Trim() -eq "device")
}

function Test-PackageInstalled([string]$serial, [string]$packageName) {
    $lines = (& adb -s $serial shell pm list packages $packageName 2>$null) -join "`n"
    return $lines -match ("package:{0}(\r?\n|$)" -f [regex]::Escape($packageName))
}

function Assert-DeviceAndPackage([string]$serial, [string]$deviceLabel, [string]$packageName) {
    if (-not (Test-DeviceOnline $serial)) {
        throw "$deviceLabel emulator is not online (serial: $serial)."
    }
    if (-not (Test-PackageInstalled $serial $packageName)) {
        throw "$deviceLabel emulator does not have package '$packageName' installed (serial: $serial)."
    }
}

function Assert-CrossDevicePackageParity([string]$watchSerial, [string]$phoneSerial, [string]$packageName) {
    Assert-DeviceAndPackage -serial $watchSerial -deviceLabel "Wear" -packageName $packageName
    Assert-DeviceAndPackage -serial $phoneSerial -deviceLabel "Phone" -packageName $packageName
}

function Wait-ForWatchWorkoutStoreSync([string]$watchSerial, [string]$appPackage, [string]$expectedWorkoutName, [int]$timeoutSeconds = 60) {
    Write-Host "Waiting for watch workout_store sync (expecting '$expectedWorkoutName')..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $json = (& adb -s $watchSerial shell run-as $appPackage cat files/workout_store.json 2>$null) -join "`n"
        if ($json -and $json.Contains($expectedWorkoutName)) {
            Write-Host "Watch workout store contains expected workout." -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw "Timed out waiting for watch workout_store.json to contain '$expectedWorkoutName'. Ensure manual pairing is active."
}

function Wait-ForPhoneWorkoutStoreSync([string]$phoneSerial, [string]$appPackage, [string]$expectedWorkoutName, [int]$timeoutSeconds = 60) {
    Write-Host "Waiting for phone workout_store sync (expecting '$expectedWorkoutName')..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $json = (& adb -s $phoneSerial shell run-as $appPackage cat files/workout_store.json 2>$null) -join "`n"
        if ($json -and $json.Contains($expectedWorkoutName)) {
            Write-Host "Phone workout store contains expected workout." -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw "Timed out waiting for phone workout_store.json to contain '$expectedWorkoutName'."
}

function Bring-PhoneAppToForeground([string]$phoneSerial, [string]$appPackage) {
    Write-Host "Bringing phone app to foreground before Wear producer run..." -ForegroundColor Cyan
    & adb -s $phoneSerial shell monkey -p $appPackage -c android.intent.category.LAUNCHER 1 | Out-Null
}

function Ensure-PhonePackageState([string]$phoneSerial) {
    Write-Host "Ensuring phone package state is debug-only for Data Layer routing..." -ForegroundColor Cyan
    & adb -s $phoneSerial uninstall com.gabstra.myworkoutassistant | Out-Null
}

function Invoke-WearRunnerClass {
    param(
        [string]$className,
        [string]$watchSerial,
        [string]$timingPath,
        [bool]$skipAssemble,
        [bool]$skipInstall,
        [bool]$fastProfile
    )

    $args = @(
        "-NoProfile",
        "-File",
        "./scripts/run_wear_e2e.ps1",
        "-TestClass",
        $className,
        "-WearEmulatorSerial",
        $watchSerial,
        "-StartEmulatorIfNeeded:`$false",
        "-TimingOutputPath",
        $timingPath
    )

    if ($skipAssemble) {
        $args += "-SkipAssemble"
    }
    if ($skipInstall) {
        $args += "-SkipInstall"
    }
    if ($fastProfile) {
        $args += "-FastTimeoutProfile"
    }

    & pwsh @args
    if ($LASTEXITCODE -ne 0) {
        throw "Wear runner failed for class '$className'."
    }
}

Write-Host "Discovering connected emulators..." -ForegroundColor Cyan

$resolvePhase = [System.Diagnostics.Stopwatch]::StartNew()
$watchSerial = Resolve-EmulatorSerial -preferredSerial $WearEmulatorSerial -kind "watch" -avdName $WearAvdName
$phoneSerial = Resolve-EmulatorSerial -preferredSerial $PhoneEmulatorSerial -kind "phone" -avdName $PhoneAvdName
if (-not $watchSerial -or -not $phoneSerial) {
    throw "Could not find both watch and phone emulators. watch='$watchSerial' phone='$phoneSerial'."
}
$resolvePhase.Stop()
$timings["resolveDeviceSeconds"] = [math]::Round($resolvePhase.Elapsed.TotalSeconds, 3)

Write-Host "Using watch: $watchSerial" -ForegroundColor Green
Write-Host "Using phone: $phoneSerial" -ForegroundColor Green
Write-Host "Required package on both: $AppPackage" -ForegroundColor Green

$logsDir = "wearos/build/e2e-logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $TimingOutputPath) {
    $TimingOutputPath = Join-Path $logsDir "cross_device_timings_$timestamp.json"
}
$timings["timingOutputPath"] = $TimingOutputPath

$previousAndroidSerial = $env:ANDROID_SERIAL
try {
    $wearInstallPhase = [System.Diagnostics.Stopwatch]::StartNew()
    Install-WearDebugApp -watchSerial $watchSerial
    $wearInstallPhase.Stop()
    $timings["wearBuildInstallSeconds"] = [math]::Round($wearInstallPhase.Elapsed.TotalSeconds, 3)

    Ensure-PhonePackageState -phoneSerial $phoneSerial

    $mobileInstallPhase = [System.Diagnostics.Stopwatch]::StartNew()
    Install-MobileDebugAndTestApks -phoneSerial $phoneSerial
    $mobileInstallPhase.Stop()
    $timings["mobileBuildInstallSeconds"] = [math]::Round($mobileInstallPhase.Elapsed.TotalSeconds, 3)

    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    $mobilePrepPhase = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "Preparing phone app state (seed workout store + dismiss startup dialogs)..." -ForegroundColor Cyan
    Run-MobileInstrumentationClass -phoneSerial $phoneSerial -className $MobilePrepTestClass -appPackage $AppPackage -fastTimeoutProfile:$FastTimeoutProfile
    $mobilePrepPhase.Stop()
    $timings["mobilePrepInstrumentationSeconds"] = [math]::Round($mobilePrepPhase.Elapsed.TotalSeconds, 3)

    Wait-ForPhoneWorkoutStoreSync -phoneSerial $phoneSerial -appPackage $AppPackage -expectedWorkoutName $ExpectedWorkoutName
    Wait-ForWatchWorkoutStoreSync -watchSerial $watchSerial -appPackage $AppPackage -expectedWorkoutName $ExpectedWorkoutName
    Bring-PhoneAppToForeground -phoneSerial $phoneSerial -appPackage $AppPackage
    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    $wearClassTimings = [ordered]@{}
    $skipAssemble = $false
    $skipInstall = $false

    Write-Host "Running Wear verification for phone->watch workout history sync..." -ForegroundColor Cyan
    $phase = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-WearRunnerClass -className $WearPhoneToWatchHistoryTestClass -watchSerial $watchSerial -timingPath (Join-Path $logsDir "wear_phone_to_watch_$timestamp.json") -skipAssemble:$skipAssemble -skipInstall:$skipInstall -fastProfile:$FastTimeoutProfile
    $phase.Stop()
    $wearClassTimings["phoneToWatchSeconds"] = [math]::Round($phase.Elapsed.TotalSeconds, 3)

    if ($SkipWearRebuildAfterFirstRun) {
        $skipAssemble = $true
        $skipInstall = $true
    }

    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    Write-Host "Running Wear VS LAST comparison verification against synced phone history..." -ForegroundColor Cyan
    $phase = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-WearRunnerClass -className $WearVsLastComparisonTestClass -watchSerial $watchSerial -timingPath (Join-Path $logsDir "wear_vs_last_$timestamp.json") -skipAssemble:$skipAssemble -skipInstall:$skipInstall -fastProfile:$FastTimeoutProfile
    $phase.Stop()
    $wearClassTimings["vsLastSeconds"] = [math]::Round($phase.Elapsed.TotalSeconds, 3)

    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    $mobileResetPhase = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "Resetting phone workout history state before Wear producer run..." -ForegroundColor Cyan
    Run-MobileInstrumentationClass -phoneSerial $phoneSerial -className $MobileResetTestClass -appPackage $AppPackage -fastTimeoutProfile:$FastTimeoutProfile
    $mobileResetPhase.Stop()
    $timings["mobileResetInstrumentationSeconds"] = [math]::Round($mobileResetPhase.Elapsed.TotalSeconds, 3)

    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    Write-Host "Running Wear producer E2E test..." -ForegroundColor Cyan
    $producerPhase = [System.Diagnostics.Stopwatch]::StartNew()
    $wearArgs = @(
        "-NoProfile",
        "-File",
        "./scripts/run_wear_e2e.ps1",
        "-TestClass",
        $WearTestClass,
        "-WearEmulatorSerial",
        $watchSerial,
        "-StartEmulatorIfNeeded:`$false",
        "-TimingOutputPath",
        (Join-Path $logsDir "wear_producer_$timestamp.json")
    )
    if ($skipAssemble) { $wearArgs += "-SkipAssemble" }
    if ($skipInstall) { $wearArgs += "-SkipInstall" }
    if ($FastTimeoutProfile) { $wearArgs += "-FastTimeoutProfile" }

    $wearProcess = Start-Process -FilePath "pwsh" -ArgumentList $wearArgs -NoNewWindow -PassThru
    $lastParityCheck = Get-Date
    while (-not $wearProcess.HasExited) {
        if (((Get-Date) - $lastParityCheck).TotalSeconds -ge 15) {
            Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage
            $lastParityCheck = Get-Date
        }
        Start-Sleep -Milliseconds 750
    }
    if ($wearProcess.ExitCode -ne 0) {
        throw "Wear producer E2E test failed."
    }
    $producerPhase.Stop()
    $wearClassTimings["producerSeconds"] = [math]::Round($producerPhase.Elapsed.TotalSeconds, 3)

    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    Write-Host "Running mobile verification instrumentation test..." -ForegroundColor Cyan
    $mobileVerifyPhase = [System.Diagnostics.Stopwatch]::StartNew()
    Run-MobileInstrumentationClass -phoneSerial $phoneSerial -className $MobileTestClass -appPackage $AppPackage -fastTimeoutProfile:$FastTimeoutProfile
    $mobileVerifyPhase.Stop()
    $timings["mobileVerificationInstrumentationSeconds"] = [math]::Round($mobileVerifyPhase.Elapsed.TotalSeconds, 3)

    $timings["wearClassTimings"] = $wearClassTimings

    Write-Host "Cross-device sync E2E completed successfully." -ForegroundColor Green
} finally {
    $env:ANDROID_SERIAL = $previousAndroidSerial
    $runStopwatch.Stop()
    $timings["totalSeconds"] = [math]::Round($runStopwatch.Elapsed.TotalSeconds, 3)
    Save-TimingOutput -timingMap $timings -outputPath $TimingOutputPath
}
