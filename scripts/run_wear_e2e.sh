#!/usr/bin/env bash
set -euo pipefail

SMOKE_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --smoke-only)
      SMOKE_ONLY=true
      ;;
  esac
done

echo "Checking connected Android devices..."
adb devices

if ! adb devices | grep -E "device$" >/dev/null 2>&1; then
  echo "ERROR: No connected Android devices/emulators detected by adb. Start a Wear OS emulator or connect a watch, then retry." >&2
  exit 1
fi

echo "Running Wear OS E2E tests..."
if [ "$SMOKE_ONLY" = true ]; then
  CMD=(./gradlew :wearos:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.gabstra.myworkoutassistant.e2e.SmokeE2ETest)
else
  CMD=(./gradlew :wearos:connectedDebugAndroidTest)
fi

echo "Executing: ${CMD[*]}"
"${CMD[@]}"

echo "Wear OS E2E tests completed successfully."


