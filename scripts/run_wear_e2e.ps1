Param(
    [switch]$SmokeOnly,
    [string]$TestClass,
    [string]$TestMethod
)

Write-Host "Checking connected Android devices..." -ForegroundColor Cyan
$adb = "adb"
$devicesOutput = & $adb devices
Write-Host $devicesOutput

if (-not ($devicesOutput -match "device`r?$")) {
    Write-Error "No connected Android devices/emulators detected by adb. Start a Wear OS emulator or connect a watch, then retry."
    exit 1
}

Write-Host "Running Wear OS E2E tests..." -ForegroundColor Cyan

# Setup logcat capture
$logsDir = "wearos/build/e2e-logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logsDir "logcat_$timestamp.txt"
Write-Host "Capturing device logs to: $logFile" -ForegroundColor Cyan

# Clear logcat buffer and start capturing logs in background
Write-Host "Starting logcat capture..." -ForegroundColor Cyan
& $adb logcat -c | Out-Null
# Use a job to capture logs filtered by app package (same as logcat filtering)
$appPackage = "com.gabstra.myworkoutassistant"
$logcatJob = Start-Job -ScriptBlock {
    param($adbPath, $logFilePath, $packageName)
    & $adbPath logcat -v time *:V *>&1 | 
        Where-Object { $_ -match $packageName } | 
        Out-File -FilePath $logFilePath -Encoding utf8 -Append
} -ArgumentList $adb, $logFile, $appPackage

# Wait a moment for logcat to start
Start-Sleep -Milliseconds 500

$gradleArgs = @(":wearos:connectedDebugAndroidTest")

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
    $gradleArgs += "-Pandroid.testInstrumentationRunnerArguments.class=$fullClassName#$TestMethod"
} elseif ($TestClass) {
    # Support comma-separated list of classes
    $classes = $TestClass -split "," | ForEach-Object {
        $class = $_.Trim()
        if ($class -notmatch "^com\.") { "com.gabstra.myworkoutassistant.e2e.$class" } else { $class }
    }
    $gradleArgs += "-Pandroid.testInstrumentationRunnerArguments.class=$($classes -join ',')"
} elseif ($SmokeOnly) {
    $gradleArgs += "-Pandroid.testInstrumentationRunnerArguments.class=com.gabstra.myworkoutassistant.e2e.SmokeE2ETest"
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
    # Execute Gradle command - Ctrl+C will be caught by the trap above
    & .\gradlew $gradleArgs 2>&1
    # Capture exit code immediately after command execution (before finally block)
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        # If $LASTEXITCODE is not set, check $? as fallback
        $exitCode = if ($?) { 0 } else { 1 }
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
    Write-Error "Wear OS E2E tests failed with exit code $exitCode. Check JUnit XML under wearos/build/outputs/androidTest-results or wearos/build/test-results/connected."
    Write-Host "Device logs available at: $logFile" -ForegroundColor Yellow
    exit $exitCode
}

Write-Host "Wear OS E2E tests completed successfully." -ForegroundColor Green


