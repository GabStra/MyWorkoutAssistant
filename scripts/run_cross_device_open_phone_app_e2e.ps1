Param(
    [string]$WearTestClass = "WearOpenPhoneAppE2ETest",
    [string]$MobileTestClass = "com.gabstra.myworkoutassistant.e2e.PhoneLaunchFromWearVerificationTest",
    [ValidateSet("debug", "release")]
    [string]$BuildType = "release",
    [string]$AppPackage,
    [string]$WearEmulatorSerial,
    [string]$PhoneEmulatorSerial,
    [switch]$StartEmulatorIfNeeded = $true,
    [string]$WearAvdName,
    [string]$PhoneAvdName,
    [switch]$SkipMobileAssemble = $false,
    [switch]$SkipMobileInstall = $false,
    [switch]$FastTimeoutProfile = $false,
    [string]$TimingOutputPath
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$gradlewPath = Join-Path $repoRoot "gradlew.bat"
$runStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$timings = [ordered]@{}
$timings["startedAtUtc"] = (Get-Date).ToUniversalTime().ToString("o")
$timings["buildType"] = $BuildType
$timings["skipMobileAssemble"] = $SkipMobileAssemble.IsPresent
$timings["skipMobileInstall"] = $SkipMobileInstall.IsPresent
$timings["fastTimeoutProfile"] = $FastTimeoutProfile.IsPresent

function Resolve-RepoPath([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) {
        return $path
    }
    if ([System.IO.Path]::IsPathRooted($path)) {
        return $path
    }
    return Join-Path $repoRoot $path
}

function Get-ExecutablePath([object]$commandPath) {
    $normalizedPath = if ($commandPath -is [System.Array]) {
        $commandPath -join ""
    } else {
        [string]$commandPath
    }

    return (Get-Item -LiteralPath $normalizedPath).FullName
}

function Invoke-ExternalCommand {
    param(
        [string]$commandPath,
        [string[]]$arguments = @()
    )

    & (Get-ExecutablePath $commandPath) @arguments
}

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

function Get-BuildTypePascalCase([string]$buildType) {
    return (Get-Culture).TextInfo.ToTitleCase($buildType)
}

function Get-AppPackageForBuildType([string]$buildType) {
    if ($buildType -eq "release") {
        return "com.gabstra.myworkoutassistant"
    }
    return "com.gabstra.myworkoutassistant.debug"
}

function Get-AndroidTestPackage([string]$appPackage) {
    return "$appPackage.test"
}

function Get-AlternatePackage([string]$packageName) {
    switch ($packageName) {
        "com.gabstra.myworkoutassistant" { return "com.gabstra.myworkoutassistant.debug" }
        "com.gabstra.myworkoutassistant.debug" { return "com.gabstra.myworkoutassistant" }
        "com.gabstra.myworkoutassistant.test" { return "com.gabstra.myworkoutassistant.debug.test" }
        "com.gabstra.myworkoutassistant.debug.test" { return "com.gabstra.myworkoutassistant.test" }
        default { return $null }
    }
}

function Get-AndroidSdkRoot {
    $candidates = @()

    if ($env:ANDROID_SDK_ROOT) {
        $candidates += $env:ANDROID_SDK_ROOT
    }
    if ($env:ANDROID_HOME) {
        $candidates += $env:ANDROID_HOME
    }

    $localPropertiesPath = Join-Path $repoRoot "local.properties"
    if (Test-Path $localPropertiesPath) {
        $sdkDirLine = Get-Content $localPropertiesPath |
            Where-Object { $_ -match '^sdk\.dir=' } |
            Select-Object -First 1
        if ($sdkDirLine) {
            $rawPath = $sdkDirLine.Substring("sdk.dir=".Length)
            $normalizedPath = $rawPath.Replace('\:', ':').Replace('\\', '\')
            if (-not [string]::IsNullOrWhiteSpace($normalizedPath)) {
                $candidates += $normalizedPath
            }
        }
    }

    $defaultLocalSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if ($defaultLocalSdk) {
        $candidates += $defaultLocalSdk
    }

    return $candidates |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique
}

function Resolve-AdbPath {
    $sdkCandidates = Get-AndroidSdkRoot
    foreach ($sdkRoot in $sdkCandidates) {
        $adbCandidate = Join-Path $sdkRoot "platform-tools\adb.exe"
        if (Test-Path $adbCandidate) {
            return $adbCandidate
        }
    }

    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function Get-ConnectedDevices {
    $lines = Invoke-ExternalCommand -commandPath $adb -arguments @("devices")
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
    return (Invoke-ExternalCommand -commandPath $adb -arguments @("-s", $serial, "shell", "getprop", "ro.build.characteristics") 2>$null).Trim()
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

function Wait-ForEmulatorBoot([string]$serial, [int]$timeoutSeconds = 240) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $bootCompleted = (Invoke-ExternalCommand -commandPath $adb -arguments @("-s", $serial, "shell", "getprop", "sys.boot_completed") 2>$null).Trim()
        if ($bootCompleted -eq "1") {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Resolve-EmulatorPath {
    $candidates = @(
        "$env:ANDROID_SDK_ROOT\emulator\emulator.exe",
        "$env:ANDROID_HOME\emulator\emulator.exe",
        "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -gt 0) {
        return $candidates | Select-Object -First 1
    }

    $cmd = Get-Command emulator -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function Start-Emulator([string]$deviceKind, [string]$forcedAvdName = $null) {
    $emulatorPath = Resolve-EmulatorPath
    if (-not $emulatorPath) {
        throw "Could not find emulator binary. Set ANDROID_SDK_ROOT/ANDROID_HOME or add emulator to PATH."
    }

    $avds = Invoke-ExternalCommand -commandPath $emulatorPath -arguments @("-list-avds")
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
    Start-Process -FilePath (Get-ExecutablePath $emulatorPath) -ArgumentList @("-avd", $avdNameToUse) | Out-Null

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

function Remove-PackageIfPresent([string]$serial, [string]$packageName) {
    if ([string]::IsNullOrWhiteSpace($packageName)) {
        return
    }
    Invoke-ExternalCommand -commandPath $adb -arguments @("-s", $serial, "uninstall", $packageName) 2>$null | Out-Null
}

function Ensure-SinglePackageVariant([string]$serial, [string]$appPackage) {
    $alternateAppPackage = Get-AlternatePackage $appPackage
    $testPackage = Get-AndroidTestPackage $appPackage
    $alternateTestPackage = Get-AlternatePackage $testPackage

    Remove-PackageIfPresent -serial $serial -packageName $alternateAppPackage
    Remove-PackageIfPresent -serial $serial -packageName $alternateTestPackage
}

function Test-PackageInstalled([string]$serial, [string]$packageName) {
    $lines = (Invoke-ExternalCommand -commandPath $adb -arguments @("-s", $serial, "shell", "pm", "list", "packages", $packageName) 2>$null) -join "`n"
    return $lines -match ("package:{0}(\r?\n|$)" -f [regex]::Escape($packageName))
}

function Assert-PackageInstalled([string]$serial, [string]$deviceLabel, [string]$packageName) {
    if (-not (Test-PackageInstalled $serial $packageName)) {
        throw "$deviceLabel emulator does not have package '$packageName' installed (serial: $serial)."
    }
}

function Install-MobileAppAndTestApks([string]$phoneSerial, [string]$buildType, [string]$appPackage) {
    $buildTypePascal = Get-BuildTypePascalCase $buildType
    if (-not $SkipMobileAssemble) {
        Write-Host "Building mobile $buildType app + androidTest APKs..." -ForegroundColor Cyan
        & $gradlewPath ":mobile:assemble${buildTypePascal}" ":mobile:assemble${buildTypePascal}AndroidTest" "-Pe2eTestBuildType=$buildType"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to assemble mobile $buildType APKs."
        }
    } else {
        Write-Host "Skipping mobile Gradle assemble due to -SkipMobileAssemble." -ForegroundColor Yellow
    }

    if ($SkipMobileInstall) {
        Write-Host "Skipping mobile APK install due to -SkipMobileInstall." -ForegroundColor Yellow
        return
    }

    $mobileApk = Resolve-RepoPath "mobile/build/outputs/apk/$buildType/mobile-$buildType.apk"
    $mobileTestApk = Resolve-RepoPath "mobile/build/outputs/apk/androidTest/$buildType/mobile-$buildType-androidTest.apk"

    if (-not (Test-Path $mobileApk)) {
        throw "Mobile APK not found at $mobileApk"
    }
    if (-not (Test-Path $mobileTestApk)) {
        throw "Mobile test APK not found at $mobileTestApk"
    }

    Ensure-SinglePackageVariant -serial $phoneSerial -appPackage $appPackage

    Write-Host "Installing mobile APKs on $phoneSerial..." -ForegroundColor Cyan
    Invoke-ExternalCommand -commandPath $adb -arguments @("-s", $phoneSerial, "install", "-r", $mobileApk) 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install mobile app APK on $phoneSerial"
    }

    Invoke-ExternalCommand -commandPath $adb -arguments @("-s", $phoneSerial, "install", "-r", $mobileTestApk) 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install mobile androidTest APK on $phoneSerial"
    }
}

function Get-MobileInstrumentationArguments(
    [string]$phoneSerial,
    [string]$className,
    [string]$appPackage,
    [bool]$fastTimeoutProfile,
    [string[]]$extraInstrumentationArgs = @()
) {
    $runner = "$appPackage.test/androidx.test.runner.AndroidJUnitRunner"
    $instrumentArgs = @("-s", $phoneSerial, "shell", "am", "instrument", "-w", "-r", "-e", "class", $className)
    if ($fastTimeoutProfile) {
        $instrumentArgs += @("-e", "e2e_profile", "fast")
    }
    if ($extraInstrumentationArgs.Count -gt 0) {
        $instrumentArgs += $extraInstrumentationArgs
    }
    $instrumentArgs += $runner
    return $instrumentArgs
}

function Start-MobileInstrumentationClass(
    [string]$phoneSerial,
    [string]$className,
    [string]$appPackage,
    [bool]$fastTimeoutProfile,
    [string]$stdoutPath,
    [string]$stderrPath,
    [string[]]$extraInstrumentationArgs = @()
) {
    $instrumentArgs = Get-MobileInstrumentationArguments -phoneSerial $phoneSerial -className $className -appPackage $appPackage -fastTimeoutProfile $fastTimeoutProfile -extraInstrumentationArgs $extraInstrumentationArgs
    Write-Host "Starting mobile instrumentation class: $className" -ForegroundColor Cyan
    Write-Host ("adb " + ($instrumentArgs -join " ")) -ForegroundColor Gray
    return Start-Process -FilePath (Get-ExecutablePath $adb) -ArgumentList $instrumentArgs -NoNewWindow -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
}

function Read-InstrumentationOutput([string]$stdoutPath, [string]$stderrPath) {
    $lines = @()
    if (Test-Path $stdoutPath) {
        $lines += Get-Content $stdoutPath
    }
    if (Test-Path $stderrPath) {
        $lines += Get-Content $stderrPath
    }
    return $lines
}

function Assert-MobileInstrumentationResult {
    param(
        [string]$className,
        [string[]]$instrumentOutput,
        [int]$exitCode
    )

    $instrumentOutput | Out-Host
    $outputText = $instrumentOutput -join "`n"
    $hasOkSummary = $outputText -match "(?m)^OK \("
    $hasFailureMarker = $outputText -match "FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed"
    if ($exitCode -ne 0 -or $hasFailureMarker -or -not $hasOkSummary) {
        throw "Mobile instrumentation failed for class '$className'."
    }
}

if (-not $AppPackage) {
    $AppPackage = Get-AppPackageForBuildType $BuildType
}
$timings["appPackage"] = $AppPackage

$adb = Resolve-AdbPath
if (-not $adb) {
    throw "Could not find adb. Set ANDROID_SDK_ROOT/ANDROID_HOME, ensure local.properties contains sdk.dir, or add adb to PATH."
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
Write-Host "Using app package: $AppPackage" -ForegroundColor Green

$logsDir = Resolve-RepoPath "wearos/build/e2e-logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $TimingOutputPath) {
    $TimingOutputPath = Join-Path $logsDir "cross_device_open_phone_$timestamp.json"
} else {
    $TimingOutputPath = Resolve-RepoPath $TimingOutputPath
}
$timings["timingOutputPath"] = $TimingOutputPath

$observerProcess = $null
$observerStdoutPath = Join-Path $logsDir "phone_launch_observer_$timestamp.stdout.txt"
$observerStderrPath = Join-Path $logsDir "phone_launch_observer_$timestamp.stderr.txt"

try {
    Ensure-SinglePackageVariant -serial $watchSerial -appPackage $AppPackage

    $mobileInstallPhase = [System.Diagnostics.Stopwatch]::StartNew()
    Install-MobileAppAndTestApks -phoneSerial $phoneSerial -buildType $BuildType -appPackage $AppPackage
    $mobileInstallPhase.Stop()
    $timings["mobileBuildInstallSeconds"] = [math]::Round($mobileInstallPhase.Elapsed.TotalSeconds, 3)

    Assert-PackageInstalled -serial $phoneSerial -deviceLabel "Phone" -packageName $AppPackage
    Assert-PackageInstalled -serial $phoneSerial -deviceLabel "Phone" -packageName (Get-AndroidTestPackage $AppPackage)

    $observerPhase = [System.Diagnostics.Stopwatch]::StartNew()
    $observerProcess = Start-MobileInstrumentationClass `
        -phoneSerial $phoneSerial `
        -className $MobileTestClass `
        -appPackage $AppPackage `
        -fastTimeoutProfile $FastTimeoutProfile.IsPresent `
        -stdoutPath $observerStdoutPath `
        -stderrPath $observerStderrPath `
        -extraInstrumentationArgs @("-e", "phone_launch_from_wear_mode", "observe_live")
    Start-Sleep -Seconds 3

    $wearPhase = [System.Diagnostics.Stopwatch]::StartNew()
    $wearArgs = @(
        "-NoProfile",
        "-File",
        (Join-Path $scriptRoot "run_wear_e2e.ps1"),
        "-TestClass",
        $WearTestClass,
        "-WearEmulatorSerial",
        $watchSerial,
        "-StartEmulatorIfNeeded:`$false",
        "-TimingOutputPath",
        (Join-Path $logsDir "wear_open_phone_$timestamp.json"),
        "-BuildType",
        $BuildType
    )
    if ($FastTimeoutProfile) {
        $wearArgs += "-FastTimeoutProfile"
    }

    & pwsh @wearArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Wear open-phone-app E2E test failed."
    }
    $wearPhase.Stop()
    $timings["wearInstrumentationSeconds"] = [math]::Round($wearPhase.Elapsed.TotalSeconds, 3)

    if (-not $observerProcess.WaitForExit((if ($FastTimeoutProfile) { 60_000 } else { 120_000 }))) {
        throw "Timed out waiting for the phone launch observer to finish."
    }

    $observerOutput = Read-InstrumentationOutput -stdoutPath $observerStdoutPath -stderrPath $observerStderrPath
    Assert-MobileInstrumentationResult -className $MobileTestClass -instrumentOutput $observerOutput -exitCode $observerProcess.ExitCode
    $observerPhase.Stop()
    $timings["mobileObserverInstrumentationSeconds"] = [math]::Round($observerPhase.Elapsed.TotalSeconds, 3)

    Write-Host "Cross-device open-phone-app E2E completed successfully." -ForegroundColor Green
} finally {
    if ($observerProcess -and -not $observerProcess.HasExited) {
        Stop-Process -Id $observerProcess.Id -Force -ErrorAction SilentlyContinue
    }

    $runStopwatch.Stop()
    $timings["totalSeconds"] = [math]::Round($runStopwatch.Elapsed.TotalSeconds, 3)
    Save-TimingOutput -timingMap $timings -outputPath $TimingOutputPath
}
