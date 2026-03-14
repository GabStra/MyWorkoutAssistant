Param(
    [switch]$SmokeOnly,
    [string]$TestClass,
    [string]$TestMethod,
    [string]$WearEmulatorSerial,
    [switch]$StartEmulatorIfNeeded = $true,
    [string]$WearAvdName,
    [switch]$IncludeCrossDeviceTests = $false,
    [switch]$SkipAssemble = $false,
    [switch]$SkipInstall = $false,
    [switch]$NoLogcat = $false,
    [string]$TimingOutputPath,
    [switch]$FastTimeoutProfile = $false
)

$adb = "adb"
$runStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$timings = [ordered]@{}
$timings["startedAtUtc"] = (Get-Date).ToUniversalTime().ToString("o")
$timings["fastTimeoutProfile"] = $FastTimeoutProfile.IsPresent
$timings["skipAssemble"] = $SkipAssemble.IsPresent
$timings["skipInstall"] = $SkipInstall.IsPresent
$timings["logcatEnabled"] = (-not $NoLogcat)
$timings["installFallbackUsed"] = $false

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
    $lines = & $adb devices
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
    return (& $adb -s $serial shell getprop ro.build.characteristics 2>$null).Trim()
}

function Is-WearEmulator([string]$serial) {
    if ($serial -notlike "emulator-*") {
        return $false
    }
    $characteristics = Get-DeviceCharacteristics $serial
    return $characteristics -match "watch"
}

function Wait-ForEmulatorBoot([string]$serial, [int]$timeoutSeconds = 240) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $bootCompleted = (& $adb -s $serial shell getprop sys.boot_completed 2>$null).Trim()
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
        return $candidates[0]
    }

    $cmd = Get-Command emulator -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function Start-WearEmulator {
    $emulatorPath = Resolve-EmulatorPath
    if (-not $emulatorPath) {
        Write-Error "Could not find emulator binary. Set ANDROID_SDK_ROOT/ANDROID_HOME or add emulator to PATH."
        exit 1
    }

    $avdNameToUse = $WearAvdName
    if (-not $avdNameToUse) {
        $avds = & $emulatorPath -list-avds
        $avdNameToUse = ($avds | Where-Object { $_ -match "wear|watch" } | Select-Object -First 1)
        if (-not $avdNameToUse) {
            $avdNameToUse = ($avds | Select-Object -First 1)
        }
    }

    if (-not $avdNameToUse) {
        Write-Error "No AVD found. Create a Wear OS AVD or pass -WearAvdName."
        exit 1
    }

    Write-Host "Starting emulator AVD: $avdNameToUse" -ForegroundColor Yellow
    $before = (Get-ConnectedDevices | Where-Object { $_.Serial -like "emulator-*" }).Serial
    Start-Process -FilePath $emulatorPath -ArgumentList @("-avd", $avdNameToUse) | Out-Null

    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        $after = Get-ConnectedDevices | Where-Object { $_.Serial -like "emulator-*" -and $_.State -eq "device" }
        $candidate = $after | Where-Object { $_.Serial -notin $before } | Select-Object -First 1
        if ($candidate -and (Is-WearEmulator $candidate.Serial)) {
            if (Wait-ForEmulatorBoot $candidate.Serial) {
                return $candidate.Serial
            }
        }
    }

    Write-Error "Timed out waiting for Wear emulator to boot."
    exit 1
}

function Install-WearApks {
    param(
        [string]$serial,
        [string]$appApk,
        [string]$testApk
    )

    Write-Host "Installing APKs on $serial..." -ForegroundColor Cyan
    & $adb -s $serial install -r $appApk 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Failed to install app APK on $serial" }

    & $adb -s $serial install -r $testApk 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Failed to install test APK on $serial" }
}

function Invoke-Instrumentation {
    param(
        [string]$serial,
        [string]$classArgument,
        [string]$notClassArgument,
        [bool]$fastProfile
    )

    $runner = "com.gabstra.myworkoutassistant.debug.test/androidx.test.runner.AndroidJUnitRunner"
    $instrumentArgs = @("-s", $serial, "shell", "am", "instrument", "-w", "-r")
    if ($classArgument) {
        $instrumentArgs += @("-e", "class", $classArgument)
    } elseif ($notClassArgument) {
        $instrumentArgs += @("-e", "notClass", $notClassArgument)
    }
    if ($fastProfile) {
        $instrumentArgs += @("-e", "e2e_profile", "fast")
    }
    $instrumentArgs += $runner

    Write-Host "Executing instrumentation on $serial..." -ForegroundColor Yellow
    Write-Host ("adb " + ($instrumentArgs -join " ")) -ForegroundColor Gray

    $instrumentOutput = & $adb $instrumentArgs 2>&1
    $instrumentOutput | Out-Host

    $exitCode = $LASTEXITCODE
    $outputText = $instrumentOutput -join "`n"
    $hasOkSummary = $outputText -match "(?m)^OK \("
    $hasFailureMarker = $outputText -match "FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed"
    $missingInstrumentation = $outputText -match "Unable to find instrumentation info|INSTRUMENTATION_FAILED: .* does not exist"

    return [PSCustomObject]@{
        ExitCode = if ($exitCode -ne 0 -or $hasFailureMarker -or -not $hasOkSummary) { if ($exitCode -eq 0) { 1 } else { $exitCode } } else { 0 }
        MissingInstrumentation = $missingInstrumentation
    }
}

Write-Host "Checking connected Android devices..." -ForegroundColor Cyan
$resolvePhase = [System.Diagnostics.Stopwatch]::StartNew()
$devices = Get-ConnectedDevices
if ($devices.Count -eq 0) {
    Write-Host "No devices currently connected." -ForegroundColor Yellow
}

$targetWearSerial = $null
if ($WearEmulatorSerial) {
    $targetWearSerial = $WearEmulatorSerial
    if (-not (Is-WearEmulator $targetWearSerial)) {
        Write-Error "Provided -WearEmulatorSerial '$targetWearSerial' is not a connected Wear emulator."
        exit 1
    }
} else {
    $connectedWearEmulators = $devices |
        Where-Object { $_.State -eq "device" -and (Is-WearEmulator $_.Serial) }
    $targetWearSerial = ($connectedWearEmulators | Select-Object -First 1).Serial
}

if (-not $targetWearSerial -and $StartEmulatorIfNeeded) {
    Write-Host "No connected Wear emulator found. Attempting to start one..." -ForegroundColor Yellow
    $targetWearSerial = Start-WearEmulator
}

if (-not $targetWearSerial) {
    Write-Error "No connected Wear emulator found. Start one or pass -WearEmulatorSerial."
    exit 1
}
$resolvePhase.Stop()
$timings["resolveDeviceSeconds"] = [math]::Round($resolvePhase.Elapsed.TotalSeconds, 3)

Write-Host "Using Wear emulator: $targetWearSerial" -ForegroundColor Green
Write-Host "Running Wear OS E2E tests..." -ForegroundColor Cyan

$logsDir = "wearos/build/e2e-logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $TimingOutputPath) {
    $TimingOutputPath = Join-Path $logsDir "timings_$timestamp.json"
}
$timings["timingOutputPath"] = $TimingOutputPath

$logFile = $null
$logcatJob = $null
if (-not $NoLogcat) {
    $logFile = Join-Path $logsDir "logcat_$timestamp.txt"
    Write-Host "Capturing device logs to: $logFile" -ForegroundColor Cyan
    New-Item -ItemType File -Path $logFile -Force | Out-Null

    Write-Host "Starting logcat capture..." -ForegroundColor Cyan
    & $adb -s $targetWearSerial logcat -c | Out-Null
    $logcatJob = Start-Job -ScriptBlock {
        param($adbPath, $serial, $logFilePath)
        & $adbPath -s $serial logcat -v threadtime *:V *>&1 |
            Out-File -FilePath $logFilePath -Encoding utf8 -Append
    } -ArgumentList $adb, $targetWearSerial, $logFile

    Start-Sleep -Milliseconds 500
}

$classArgument = $null
$notClassArgument = $null

if ($TestMethod) {
    if (-not $TestClass) {
        Write-Error "TestMethod requires TestClass to be specified. Use: -TestClass <ClassName> -TestMethod <MethodName>"
        exit 1
    }
    $fullClassName = if ($TestClass -notmatch "^com\.") { "com.gabstra.myworkoutassistant.e2e.$TestClass" } else { $TestClass }
    $classArgument = "$fullClassName#$TestMethod"
} elseif ($TestClass) {
    $classes = $TestClass -split "," | ForEach-Object {
        $class = $_.Trim()
        if ($class -notmatch "^com\.") { "com.gabstra.myworkoutassistant.e2e.$class" } else { $class }
    }
    $classArgument = $classes -join ","
} elseif ($SmokeOnly) {
    $classArgument = "com.gabstra.myworkoutassistant.e2e.WearSmokeE2ETest"
} elseif (-not $IncludeCrossDeviceTests) {
    $excludedCrossDeviceClasses = @(
        "com.gabstra.myworkoutassistant.e2e.WearCrossDeviceSyncProducerE2ETest",
        "com.gabstra.myworkoutassistant.e2e.PhoneToWearWorkoutHistorySyncVerificationE2ETest",
        "com.gabstra.myworkoutassistant.e2e.PhoneToWearVsLastComparisonE2ETest"
    )
    $notClassArgument = $excludedCrossDeviceClasses -join ","
    Write-Host "Excluding cross-device Wear E2E classes by default:" -ForegroundColor Yellow
    $excludedCrossDeviceClasses | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    Write-Host "Use -IncludeCrossDeviceTests to include them." -ForegroundColor Yellow
}

$exitCode = 0

function Stop-TestExecution {
    param([string]$reason = "interrupted")
    Write-Host "`n$reason - Stopping test execution..." -ForegroundColor Yellow

    try {
        & .\gradlew --stop 2>&1 | Out-Null
    } catch {
    }

    Write-Host "Stopping logcat capture..." -ForegroundColor Cyan
    if ($logcatJob) {
        Stop-Job -Job $logcatJob -ErrorAction SilentlyContinue
        Remove-Job -Job $logcatJob -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }
}

trap {
    if ($_.Exception -is [System.Management.Automation.PipelineStoppedException]) {
        Stop-TestExecution -reason "Test execution cancelled by user (Ctrl+C)"
        exit 130
    }
    throw
}

try {
    $appApk = "wearos/build/outputs/apk/debug/wearos-debug.apk"
    $testApk = "wearos/build/outputs/apk/androidTest/debug/wearos-debug-androidTest.apk"

    if (-not $SkipAssemble) {
        $assemblePhase = [System.Diagnostics.Stopwatch]::StartNew()
        $gradleArgs = @(":wearos:assembleDebug", ":wearos:assembleDebugAndroidTest")
        $cmdDisplay = ".\gradlew " + ($gradleArgs -join " ")
        Write-Host "Executing: $cmdDisplay" -ForegroundColor Yellow
        Write-Host "Press Ctrl+C to cancel the test execution" -ForegroundColor Gray
        & .\gradlew $gradleArgs 2>&1
        $exitCode = $LASTEXITCODE
        $assemblePhase.Stop()
        $timings["assembleSeconds"] = [math]::Round($assemblePhase.Elapsed.TotalSeconds, 3)
        if ($exitCode -ne 0) {
            throw "Gradle assemble failed with exit code $exitCode"
        }
    } else {
        Write-Host "Skipping Gradle assemble due to -SkipAssemble." -ForegroundColor Yellow
        $timings["assembleSeconds"] = 0.0
    }

    if (-not (Test-Path $appApk)) {
        throw "Missing app APK: $appApk"
    }
    if (-not (Test-Path $testApk)) {
        throw "Missing androidTest APK: $testApk"
    }

    if (-not $SkipInstall) {
        $installAppPhase = [System.Diagnostics.Stopwatch]::StartNew()
        Install-WearApks -serial $targetWearSerial -appApk $appApk -testApk $testApk
        $installAppPhase.Stop()
        $timings["installSeconds"] = [math]::Round($installAppPhase.Elapsed.TotalSeconds, 3)
    } else {
        Write-Host "Skipping APK install due to -SkipInstall." -ForegroundColor Yellow
        $timings["installSeconds"] = 0.0
    }

    $instrumentPhase = [System.Diagnostics.Stopwatch]::StartNew()
    $result = Invoke-Instrumentation -serial $targetWearSerial -classArgument $classArgument -notClassArgument $notClassArgument -fastProfile $FastTimeoutProfile
    $instrumentPhase.Stop()
    $timings["instrumentationSeconds"] = [math]::Round($instrumentPhase.Elapsed.TotalSeconds, 3)
    $exitCode = $result.ExitCode

    if ($exitCode -ne 0 -and $SkipInstall -and $result.MissingInstrumentation) {
        Write-Host "Instrumentation target missing; retrying once with APK install fallback..." -ForegroundColor Yellow
        $retryInstallPhase = [System.Diagnostics.Stopwatch]::StartNew()
        Install-WearApks -serial $targetWearSerial -appApk $appApk -testApk $testApk
        $retryInstallPhase.Stop()
        $timings["installFallbackSeconds"] = [math]::Round($retryInstallPhase.Elapsed.TotalSeconds, 3)
        $timings["installFallbackUsed"] = $true

        $retryInstrumentPhase = [System.Diagnostics.Stopwatch]::StartNew()
        $retryResult = Invoke-Instrumentation -serial $targetWearSerial -classArgument $classArgument -notClassArgument $notClassArgument -fastProfile $FastTimeoutProfile
        $retryInstrumentPhase.Stop()
        $timings["retryInstrumentationSeconds"] = [math]::Round($retryInstrumentPhase.Elapsed.TotalSeconds, 3)
        $exitCode = $retryResult.ExitCode
    }
} catch {
    Write-Error "Error running Wear E2E: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    if ($logcatJob) {
        Write-Host "Stopping logcat capture..." -ForegroundColor Cyan
        Stop-Job -Job $logcatJob -ErrorAction SilentlyContinue
        Remove-Job -Job $logcatJob -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }

    $runStopwatch.Stop()
    $timings["totalSeconds"] = [math]::Round($runStopwatch.Elapsed.TotalSeconds, 3)
    if ($logFile) {
        $timings["logFile"] = $logFile
    }
    Save-TimingOutput -timingMap $timings -outputPath $TimingOutputPath
}

if ($logFile -and (Test-Path $logFile)) {
    $logSize = (Get-Item $logFile).Length
    Write-Host "Device logs saved to: $logFile ($([math]::Round($logSize / 1KB, 2)) KB)" -ForegroundColor Green
}

if ($exitCode -ne 0) {
    Write-Error "Wear OS E2E tests failed with exit code $exitCode."
    if ($logFile) {
        Write-Host "Device logs available at: $logFile" -ForegroundColor Yellow
    }
    exit $exitCode
}

Write-Host "Wear OS E2E tests completed successfully." -ForegroundColor Green
