Param(
    [string]$PhoneEmulatorSerial,
    [string]$AppPackage = "com.gabstra.myworkoutassistant.debug",
    [switch]$SkipAssemble = $false
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot

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

function Resolve-PhoneEmulatorSerial([string]$preferredSerial) {
    $devices = Get-ConnectedDevices | Where-Object { $_.State -eq "device" }
    if ($preferredSerial) {
        $match = $devices | Where-Object { $_.Serial -eq $preferredSerial } | Select-Object -First 1
        if (-not $match) {
            throw "Provided phone emulator serial '$preferredSerial' is not connected."
        }
        return $match.Serial
    }

    $phone = $devices | Where-Object {
        $_.Serial -like "emulator-*" -and (Get-DeviceCharacteristics $_.Serial) -notmatch "watch"
    } | Select-Object -First 1
    if (-not $phone) {
        throw "No connected phone emulator found. Start one or pass -PhoneEmulatorSerial."
    }
    return $phone.Serial
}

function Invoke-Adb {
    param([string[]]$AdbArgs, [string]$FailureMessage)

    & adb @AdbArgs | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Uninstall-PackageIfPresent([string]$serial, [string]$packageName) {
    & adb -s $serial uninstall $packageName | Out-Null
}

function Install-MobileApks([string]$serial, [string]$appPackage) {
    $mobileApk = "mobile/build/outputs/apk/debug/mobile-debug.apk"
    $mobileTestApk = "mobile/build/outputs/apk/androidTest/debug/mobile-debug-androidTest.apk"
    if (-not (Test-Path $mobileApk)) {
        throw "Mobile APK not found at $mobileApk"
    }
    if (-not (Test-Path $mobileTestApk)) {
        throw "Mobile test APK not found at $mobileTestApk"
    }

    Invoke-Adb -AdbArgs @("-s", $serial, "install", "-r", $mobileApk) -FailureMessage "Failed to install mobile APK."
    Invoke-Adb -AdbArgs @("-s", $serial, "install", "-r", $mobileTestApk) -FailureMessage "Failed to install mobile androidTest APK."
}

function Run-MobileInstrumentationClass([string]$serial, [string]$className, [string]$appPackage) {
    $runner = "$appPackage.test/androidx.test.runner.AndroidJUnitRunner"
    $args = @("-s", $serial, "shell", "am", "instrument", "-w", "-r", "-e", "class", $className, $runner)
    Write-Host "Running mobile instrumentation class: $className" -ForegroundColor Cyan
    Write-Host ("adb " + ($args -join " ")) -ForegroundColor Gray
    $output = & adb @args 2>&1
    $output | Out-Host
    $outputText = $output -join "`n"
    $hasOkSummary = $outputText -match "(?m)^OK \("
    $hasFailureMarker = $outputText -match "FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed"
    if ($LASTEXITCODE -ne 0 -or $hasFailureMarker -or -not $hasOkSummary) {
        throw "Mobile instrumentation failed for class '$className'."
    }
}

Push-Location $repoRoot
try {
    $phoneSerial = Resolve-PhoneEmulatorSerial -preferredSerial $PhoneEmulatorSerial
    Write-Host "Using phone emulator: $phoneSerial" -ForegroundColor Green

    if (-not $SkipAssemble) {
        Write-Host "Building mobile debug and androidTest APKs..." -ForegroundColor Cyan
        & .\gradlew :mobile:assembleDebug :mobile:assembleDebugAndroidTest
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to assemble mobile debug/test APKs."
        }
    }

    $testPackage = "$AppPackage.test"

    Write-Host "Installing a fresh app and test APK..." -ForegroundColor Cyan
    Uninstall-PackageIfPresent -serial $phoneSerial -packageName $testPackage
    Uninstall-PackageIfPresent -serial $phoneSerial -packageName $AppPackage
    Install-MobileApks -serial $phoneSerial -appPackage $AppPackage

    # Scoped storage blocks a freshly reinstalled app from discovering non-media JSON files
    # created by a previous UID, so this stages the file after install but before first activity launch.
    Write-Host "Seeding a valid manual backup into Downloads before first activity launch..." -ForegroundColor Cyan
    Run-MobileInstrumentationClass -serial $phoneSerial -className "com.gabstra.myworkoutassistant.e2e.StartupRestoreDownloadsSeederTest" -appPackage $AppPackage

    Write-Host "Launching fresh app before verification..." -ForegroundColor Cyan
    Invoke-Adb -AdbArgs @("-s", $phoneSerial, "shell", "monkey", "-p", $AppPackage, "-c", "android.intent.category.LAUNCHER", "1") -FailureMessage "Failed to launch mobile app."
    Start-Sleep -Seconds 2

    Run-MobileInstrumentationClass -serial $phoneSerial -className "com.gabstra.myworkoutassistant.e2e.StartupRestoreFromDownloadsVerificationTest" -appPackage $AppPackage
    Write-Host "Startup restore Downloads regression passed." -ForegroundColor Green
} finally {
    Pop-Location
}
