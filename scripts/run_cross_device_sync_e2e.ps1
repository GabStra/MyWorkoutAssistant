Param(
    [string]$WearTestClass = "CrossDeviceWorkoutSyncProducerE2ETest",
    [string]$MobilePrepTestClass = "com.gabstra.myworkoutassistant.e2e.PhoneSyncPreparationTest",
    [string]$MobileTestClass = "com.gabstra.myworkoutassistant.e2e.WorkoutSyncVerificationTest",
    [string]$ExpectedWorkoutName = "Cross Device Sync Workout",
    [string]$AppPackage = "com.gabstra.myworkoutassistant.debug",
    [string]$WearEmulatorSerial,
    [string]$PhoneEmulatorSerial,
    [switch]$StartEmulatorIfNeeded = $true,
    [string]$WearAvdName,
    [string]$PhoneAvdName
)

$ErrorActionPreference = "Stop"

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

function Run-MobileInstrumentationClass([string]$phoneSerial, [string]$className, [string]$appPackage) {
    Write-Host "Running mobile instrumentation class: $className" -ForegroundColor Cyan
    $runner = "$appPackage.test/androidx.test.runner.AndroidJUnitRunner"
    $instrumentArgs = @("-s", $phoneSerial, "shell", "am", "instrument", "-w", "-r", "-e", "class", $className, $runner)
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

function Wait-ForWatchWorkoutStoreSync([string]$watchSerial, [string]$appPackage, [string]$expectedWorkoutName, [int]$timeoutSeconds = 120) {
    Write-Host "Waiting for watch workout_store sync (expecting '$expectedWorkoutName')..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $json = (& adb -s $watchSerial shell run-as $appPackage cat files/workout_store.json 2>$null) -join "`n"
        if ($json -and $json.Contains($expectedWorkoutName)) {
            Write-Host "Watch workout store contains expected workout." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "Timed out waiting for watch workout_store.json to contain '$expectedWorkoutName'. Ensure manual pairing is active."
}

function Wait-ForPhoneWorkoutStoreSync([string]$phoneSerial, [string]$appPackage, [string]$expectedWorkoutName, [int]$timeoutSeconds = 120) {
    Write-Host "Waiting for phone workout_store sync (expecting '$expectedWorkoutName')..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $json = (& adb -s $phoneSerial shell run-as $appPackage cat files/workout_store.json 2>$null) -join "`n"
        if ($json -and $json.Contains($expectedWorkoutName)) {
            Write-Host "Phone workout store contains expected workout." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 2
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

Write-Host "Discovering connected emulators..." -ForegroundColor Cyan

$watchSerial = Resolve-EmulatorSerial -preferredSerial $WearEmulatorSerial -kind "watch" -avdName $WearAvdName
$phoneSerial = Resolve-EmulatorSerial -preferredSerial $PhoneEmulatorSerial -kind "phone" -avdName $PhoneAvdName

if (-not $watchSerial -or -not $phoneSerial) {
    throw "Could not find both watch and phone emulators. watch='$watchSerial' phone='$phoneSerial'."
}

Write-Host "Using watch: $watchSerial" -ForegroundColor Green
Write-Host "Using phone: $phoneSerial" -ForegroundColor Green
Write-Host "Required package on both: $AppPackage" -ForegroundColor Green

$previousAndroidSerial = $env:ANDROID_SERIAL
try {
    Install-WearDebugApp -watchSerial $watchSerial

    Ensure-PhonePackageState -phoneSerial $phoneSerial

    Install-MobileDebugAndTestApks -phoneSerial $phoneSerial
    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    Write-Host "Preparing phone app state (seed workout store + dismiss startup dialogs)..." -ForegroundColor Cyan
    Run-MobileInstrumentationClass -phoneSerial $phoneSerial -className $MobilePrepTestClass -appPackage $AppPackage
    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage
    Wait-ForPhoneWorkoutStoreSync -phoneSerial $phoneSerial -appPackage $AppPackage -expectedWorkoutName $ExpectedWorkoutName

    Wait-ForWatchWorkoutStoreSync -watchSerial $watchSerial -appPackage $AppPackage -expectedWorkoutName $ExpectedWorkoutName
    Bring-PhoneAppToForeground -phoneSerial $phoneSerial -appPackage $AppPackage
    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    Write-Host "Running Wear producer E2E test..." -ForegroundColor Cyan
    $wearArgs = @(
        "-NoProfile",
        "-File",
        "./scripts/run_wear_e2e.ps1",
        "-TestClass",
        $WearTestClass,
        "-WearEmulatorSerial",
        $watchSerial,
        "-StartEmulatorIfNeeded:`$false"
    )
    $wearProcess = Start-Process -FilePath "pwsh" -ArgumentList $wearArgs -NoNewWindow -PassThru
    while (-not $wearProcess.HasExited) {
        Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage
        Start-Sleep -Seconds 2
    }
    if ($wearProcess.ExitCode -ne 0) {
        throw "Wear producer E2E test failed."
    }
    Assert-CrossDevicePackageParity -watchSerial $watchSerial -phoneSerial $phoneSerial -packageName $AppPackage

    Write-Host "Running mobile verification instrumentation test..." -ForegroundColor Cyan
    Run-MobileInstrumentationClass -phoneSerial $phoneSerial -className $MobileTestClass -appPackage $AppPackage

    Write-Host "Cross-device sync E2E completed successfully." -ForegroundColor Green
} finally {
    $env:ANDROID_SERIAL = $previousAndroidSerial
}
