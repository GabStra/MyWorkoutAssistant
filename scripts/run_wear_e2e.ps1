Param(
    [switch]$SmokeOnly,
    [string]$TestClass,
    [string]$TestMethod,
    [string]$WearEmulatorSerial,
    [switch]$StartEmulatorIfNeeded = $true,
    [string]$WearAvdName
)

$adb = "adb"

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

Write-Host "Checking connected Android devices..." -ForegroundColor Cyan
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

Write-Host "Using Wear emulator: $targetWearSerial" -ForegroundColor Green
Write-Host "Running Wear OS E2E tests..." -ForegroundColor Cyan

# Setup logcat capture
$logsDir = "wearos/build/e2e-logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logsDir "logcat_$timestamp.txt"
Write-Host "Capturing device logs to: $logFile" -ForegroundColor Cyan
New-Item -ItemType File -Path $logFile -Force | Out-Null

# Clear logcat buffer and start capturing logs in background
Write-Host "Starting logcat capture..." -ForegroundColor Cyan
& $adb -s $targetWearSerial logcat -c | Out-Null
# Use a job to capture raw logcat output
$logcatJob = Start-Job -ScriptBlock {
    param($adbPath, $serial, $logFilePath)
    & $adbPath -s $serial logcat -v threadtime *:V *>&1 |
        Out-File -FilePath $logFilePath -Encoding utf8 -Append
} -ArgumentList $adb, $targetWearSerial, $logFile

# Wait a moment for logcat to start
Start-Sleep -Milliseconds 500

$gradleArgs = @(":wearos:assembleDebug", ":wearos:assembleDebugAndroidTest")
$classArgument = $null

if ($TestMethod) {
    if (-not $TestClass) {
        Write-Error "TestMethod requires TestClass to be specified. Use: -TestClass <ClassName> -TestMethod <MethodName>"
        if ($logcatJob) {
            Stop-Job -Job $logcatJob -ErrorAction SilentlyContinue
            Remove-Job -Job $logcatJob -Force -ErrorAction SilentlyContinue
        }
        exit 1
    }
    # Format: ClassName#methodName
    $fullClassName = if ($TestClass -notmatch "^com\.") { "com.gabstra.myworkoutassistant.e2e.$TestClass" } else { $TestClass }
    $classArgument = "$fullClassName#$TestMethod"
} elseif ($TestClass) {
    # Support comma-separated list of classes
    $classes = $TestClass -split "," | ForEach-Object {
        $class = $_.Trim()
        if ($class -notmatch "^com\.") { "com.gabstra.myworkoutassistant.e2e.$class" } else { $class }
    }
    $classArgument = $classes -join ","
} elseif ($SmokeOnly) {
    $classArgument = "com.gabstra.myworkoutassistant.e2e.SmokeE2ETest"
}

$cmdDisplay = ".\gradlew " + ($gradleArgs -join " ")
Write-Host "Executing: $cmdDisplay" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to cancel the test execution" -ForegroundColor Gray

$exitCode = 0

# Function to clean up resources
function Stop-TestExecution {
    param([string]$reason = "interrupted")
    Write-Host "`n$reason - Stopping test execution..." -ForegroundColor Yellow
    
    # Try to stop any gradle processes (the main process should already be stopped by Ctrl+C)
    # This is a best-effort cleanup for any child processes
    Write-Host "Cleaning up any remaining processes..." -ForegroundColor Yellow
    try {
        # Stop gradle daemon if it was started (optional - usually not needed)
        & .\gradlew --stop 2>&1 | Out-Null
    } catch {
        # Ignore errors - gradle might not be running
    }
    
    Write-Host "Stopping logcat capture..." -ForegroundColor Cyan
    if ($logcatJob) {
        Stop-Job -Job $logcatJob -ErrorAction SilentlyContinue
        Remove-Job -Job $logcatJob -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }
}

# Trap Ctrl+C (SIGINT) - this will catch when user presses Ctrl+C
trap {
    if ($_.Exception -is [System.Management.Automation.PipelineStoppedException]) {
        Stop-TestExecution -reason "Test execution cancelled by user (Ctrl+C)"
        exit 130  # Standard exit code for Ctrl+C
    }
    throw
}

try {
    # Build debug and androidTest APKs.
    & .\gradlew $gradleArgs 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Gradle assemble failed with exit code $exitCode"
    }

    $appApk = "wearos/build/outputs/apk/debug/wearos-debug.apk"
    $testApk = "wearos/build/outputs/apk/androidTest/debug/wearos-debug-androidTest.apk"
    if (-not (Test-Path $appApk)) {
        throw "Missing app APK: $appApk"
    }
    if (-not (Test-Path $testApk)) {
        throw "Missing androidTest APK: $testApk"
    }

    Write-Host "Installing APKs on $targetWearSerial..." -ForegroundColor Cyan
    & $adb -s $targetWearSerial install -r $appApk 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Failed to install app APK on $targetWearSerial" }

    & $adb -s $targetWearSerial install -r $testApk 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Failed to install test APK on $targetWearSerial" }

    $runner = "com.gabstra.myworkoutassistant.debug.test/androidx.test.runner.AndroidJUnitRunner"
    $instrumentArgs = @("-s", $targetWearSerial, "shell", "am", "instrument", "-w", "-r")
    if ($classArgument) {
        $instrumentArgs += @("-e", "class", $classArgument)
    }
    $instrumentArgs += $runner

    Write-Host "Executing instrumentation on $targetWearSerial..." -ForegroundColor Yellow
    Write-Host ("adb " + ($instrumentArgs -join " ")) -ForegroundColor Gray
    $instrumentOutput = & $adb $instrumentArgs 2>&1
    $instrumentOutput | Out-Host

    $exitCode = $LASTEXITCODE
    $outputText = $instrumentOutput -join "`n"
    $hasOkSummary = $outputText -match "(?m)^OK \("
    $hasFailureMarker = $outputText -match "FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed"
    if ($exitCode -ne 0 -or $hasFailureMarker -or -not $hasOkSummary) {
        $exitCode = if ($exitCode -eq 0) { 1 } else { $exitCode }
    }
} catch {
    # Handle other errors (Ctrl+C is handled by trap above)
    Write-Error "Error running Gradle: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    # Stop logcat capture (always run, even on error or Ctrl+C)
    Write-Host "Stopping logcat capture..." -ForegroundColor Cyan
    if ($logcatJob) {
        Stop-Job -Job $logcatJob -ErrorAction SilentlyContinue
        Remove-Job -Job $logcatJob -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }
}

if (Test-Path $logFile) {
    $logSize = (Get-Item $logFile).Length
    Write-Host "Device logs saved to: $logFile ($([math]::Round($logSize / 1KB, 2)) KB)" -ForegroundColor Green
} else {
    Write-Warning "Log file was not created: $logFile"
}

if ($exitCode -ne 0) {
    Write-Error "Wear OS E2E tests failed with exit code $exitCode."
    Write-Host "Device logs available at: $logFile" -ForegroundColor Yellow
    exit $exitCode
}

Write-Host "Wear OS E2E tests completed successfully." -ForegroundColor Green


