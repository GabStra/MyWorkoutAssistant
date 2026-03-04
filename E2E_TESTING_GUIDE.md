# E2E Testing Guide

This document describes how to run Wear and cross-device E2E tests in this repository.

## Prerequisites

- Android SDK tools installed and on `PATH` (`adb`, `emulator`).
- At least one Wear emulator/device connected for Wear E2E.
- For cross-device E2E: one Wear emulator/device **and** one phone emulator/device connected.

Check devices:

```powershell
adb devices
```

## Wear E2E

Use this script (PowerShell):

```powershell
pwsh ./scripts/run_wear_e2e.ps1
```

### Common runs

Run all Wear E2E (excluding cross-device Wear classes by default):

```powershell
pwsh ./scripts/run_wear_e2e.ps1
```

Run smoke only:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -SmokeOnly
```

Run one class (class name from `com.gabstra.myworkoutassistant.e2e` package):

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearExerciseHistoryE2ETest
```

Run one method:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearExerciseHistoryE2ETest -TestMethod exerciseHistory_storedCorrectlyAfterWorkoutCompletion
```

Run multiple classes (comma-separated):

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearSmokeE2ETest,WearWorkoutFlowE2ETest
```

Include cross-device Wear classes in full run:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -IncludeCrossDeviceTests
```

### Device targeting

Use a specific connected Wear emulator/device:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -WearEmulatorSerial emulator-5554
```

Disable auto-starting emulator if none is connected:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -StartEmulatorIfNeeded:$false
```

Choose an AVD when auto-start is enabled:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -WearAvdName Wear_OS_XL_Round
```

### Performance flags (new)

Fast profile (reduced timeouts in instrumentation code):

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearSmokeE2ETest -FastTimeoutProfile
```

Skip build/install (for reruns when APKs are already assembled/installed):

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearSmokeE2ETest -SkipAssemble -SkipInstall
```

Disable logcat capture:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearSmokeE2ETest -NoLogcat
```

Write timing JSON to a specific path:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearSmokeE2ETest -TimingOutputPath wearos/build/e2e-logs/wear_smoke_timing.json
```

## Cross-Device Sync E2E

Use this script:

```powershell
pwsh ./scripts/run_cross_device_sync_e2e.ps1
```

Default flow:

1. Resolve watch + phone emulators/devices.
2. Build/install Wear debug app.
3. Build/install mobile debug + mobile androidTest APKs.
4. Run mobile prep instrumentation.
5. Run Wear VS LAST verification class (`PhoneToWearVsLastComparisonE2ETest`).
6. Run Wear producer class.
7. Run mobile verification instrumentation.

### Common runs

Default cross-device sync run:

```powershell
pwsh ./scripts/run_cross_device_sync_e2e.ps1
```

Pin watch/phone serials:

```powershell
pwsh ./scripts/run_cross_device_sync_e2e.ps1 -WearEmulatorSerial emulator-5554 -PhoneEmulatorSerial emulator-5556
```

Override classes:

```powershell
pwsh ./scripts/run_cross_device_sync_e2e.ps1 -WearTestClass WearCrossDeviceSyncProducerE2ETest -MobileTestClass com.gabstra.myworkoutassistant.e2e.WorkoutSyncVerificationTest
```

Fast profile + timing output:

```powershell
pwsh ./scripts/run_cross_device_sync_e2e.ps1 -FastTimeoutProfile -TimingOutputPath wearos/build/e2e-logs/cross_device_timing.json
```

### Performance flags (new)

Reuse Wear install/build after first Wear class (default enabled):

```powershell
pwsh ./scripts/run_cross_device_sync_e2e.ps1 -SkipWearRebuildAfterFirstRun
```

This runs the first Wear class normally, then runs subsequent Wear classes via `run_wear_e2e.ps1` with `-SkipAssemble -SkipInstall` (currently the VS LAST verifier runs first, then producer).

## Outputs

- Wear logcat logs: `wearos/build/e2e-logs/logcat_*.txt` (unless `-NoLogcat`).
- Wear timing JSON: path from `-TimingOutputPath` or auto-generated under `wearos/build/e2e-logs/`.
- Cross-device timing JSON: path from `-TimingOutputPath` or auto-generated under `wearos/build/e2e-logs/`.

## Troubleshooting

No devices found:

- Start emulator(s) manually in Android Studio or with `emulator -avd <name>`.
- Verify with `adb devices`.

Provided serial rejected:

- Ensure serial is connected and matches target kind (watch vs phone).

Missing APK when using `-SkipAssemble`:

- Build once first, or remove `-SkipAssemble`.

Instrumentation missing when using `-SkipInstall`:

- The Wear script automatically retries once with install fallback if instrumentation package is missing.

Cross-device sync timeout:

- Confirm both emulators are online.
- Confirm package `com.gabstra.myworkoutassistant.debug` is installed on both devices.
- Re-run without `-FastTimeoutProfile` for more conservative waits.

## Recommended fast local workflow

1. First run a class normally:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearWorkoutFlowE2ETest -FastTimeoutProfile
```

2. Re-run quickly after small test-only edits:

```powershell
pwsh ./scripts/run_wear_e2e.ps1 -TestClass WearWorkoutFlowE2ETest -SkipAssemble -SkipInstall -FastTimeoutProfile -NoLogcat
```

3. Use timing JSON to compare runs over time.

## Note for automation/agents

When invoking these scripts from tooling that has command timeouts, use the maximum available timeout to avoid killing long-running E2E runs prematurely.
