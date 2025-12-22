Param(
    [switch]$SmokeOnly
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

if ($SmokeOnly) {
    $cmd = ".\gradlew :wearos:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.gabstra.myworkoutassistant.e2e.SmokeE2ETest"
} else {
    $cmd = ".\gradlew :wearos:connectedDebugAndroidTest"
}

Write-Host "Executing: $cmd" -ForegroundColor Yellow
iex $cmd
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Error "Wear OS E2E tests failed with exit code $exitCode. Check JUnit XML under wearos/build/outputs/androidTest-results or wearos/build/test-results/connected."
    exit $exitCode
}

Write-Host "Wear OS E2E tests completed successfully." -ForegroundColor Green


