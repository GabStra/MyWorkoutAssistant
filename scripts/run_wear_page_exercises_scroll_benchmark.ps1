Param(
    [string]$WearEmulatorSerial,
    [switch]$StartEmulatorIfNeeded = $true,
    [string]$WearAvdName,
    [switch]$SkipAssemble = $false,
    [switch]$SkipInstall = $false,
    [switch]$NoLogcat = $true,
    [string]$OutputPath,
    [ValidateSet("debug", "release")]
    [string]$BuildType = "debug"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$e2eScript = Join-Path $scriptRoot "run_wear_e2e.ps1"
$benchmarkClass = "com.gabstra.myworkoutassistant.benchmark.PageExercisesScrollBenchmark"

$resultsDir = Join-Path $repoRoot "wearos/build/benchmark-results"
if (-not (Test-Path $resultsDir)) {
    New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $resultsDir "page_exercises_scroll_$timestamp.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $repoRoot $OutputPath
}

$e2eTimingOutputPath = Join-Path $resultsDir "page_exercises_scroll_e2e_timing_$timestamp.json"

$e2eParams = @{
    TestClass = $benchmarkClass
    TimingOutputPath = $e2eTimingOutputPath
    BuildType = $BuildType
    StartEmulatorIfNeeded = $StartEmulatorIfNeeded.IsPresent
}

if ($WearEmulatorSerial) {
    $e2eParams["WearEmulatorSerial"] = $WearEmulatorSerial
}
if ($WearAvdName) {
    $e2eParams["WearAvdName"] = $WearAvdName
}
if ($SkipAssemble) {
    $e2eParams["SkipAssemble"] = $true
}
if ($SkipInstall) {
    $e2eParams["SkipInstall"] = $true
}
if ($NoLogcat) {
    $e2eParams["NoLogcat"] = $true
}

Write-Host "Running Wear PageExercises scroll benchmark..." -ForegroundColor Cyan
Write-Host "pwsh $e2eScript -TestClass $benchmarkClass -TimingOutputPath $e2eTimingOutputPath" -ForegroundColor Gray

$output = & $e2eScript @e2eParams 2>&1
$exitCode = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }

$metricLine = $output |
    ForEach-Object { [string]$_ } |
    Where-Object { $_ -match 'BENCHMARK_METRIC\s+PageExercisesScroll\s+\{.*\}' } |
    Select-Object -Last 1

if (-not $metricLine) {
    if (Test-Path $e2eTimingOutputPath) {
        $e2eTiming = Get-Content -LiteralPath $e2eTimingOutputPath -Raw | ConvertFrom-Json
        if ($e2eTiming.benchmarkMetrics -and $e2eTiming.benchmarkMetrics.PageExercisesScroll) {
            $metric = $e2eTiming.benchmarkMetrics.PageExercisesScroll
        }
    }

    if (-not $metric) {
        Write-Error "Benchmark did not emit a BENCHMARK_METRIC PageExercisesScroll line."
        if ($exitCode -ne 0) {
            exit $exitCode
        }
        exit 1
    }
}

if ($metricLine) {
    $metricJson = [regex]::Match($metricLine, 'BENCHMARK_METRIC\s+PageExercisesScroll\s+(\{.*\})').Groups[1].Value
    $metric = $metricJson | ConvertFrom-Json
}

$result = [ordered]@{
    benchmark = "PageExercisesScroll"
    benchmarkClass = $benchmarkClass
    createdAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    buildType = $BuildType
    metric = $metric
    e2eTimingOutputPath = $e2eTimingOutputPath
}

$result | ConvertTo-Json -Depth 10 | Out-File -FilePath $OutputPath -Encoding utf8

Write-Host "Benchmark result saved to: $OutputPath" -ForegroundColor Green
if ($metric.medianScrollMs) {
    Write-Host ("PageExercisesScroll median scroll: {0} ms; min: {1} ms; max: {2} ms; median total: {3} ms" -f $metric.medianScrollMs, $metric.minScrollMs, $metric.maxScrollMs, $metric.medianTotalMs) -ForegroundColor Green
    if ($metric.medianScrollMsPerSwipe) {
        Write-Host ("PageExercisesScroll median scroll/swipe: {0} ms; median total/swipe: {1} ms" -f $metric.medianScrollMsPerSwipe, $metric.medianTotalMsPerSwipe) -ForegroundColor Green
    }
    if ($metric.frameStats) {
        Write-Host ("PageExercisesScroll frames: total={0}; janky={1}; janky%={2}; p90={3} ms; p95={4} ms; p99={5} ms" -f $metric.frameStats.totalFrames, $metric.frameStats.jankyFrames, $metric.frameStats.jankyFramePercent, $metric.frameStats.percentile90Ms, $metric.frameStats.percentile95Ms, $metric.frameStats.percentile99Ms) -ForegroundColor Green
    }
} else {
    Write-Host ("PageExercisesScroll median: {0} ms; min: {1} ms; max: {2} ms" -f $metric.medianMs, $metric.minMs, $metric.maxMs) -ForegroundColor Green
}

if ($exitCode -ne 0) {
    exit $exitCode
}
