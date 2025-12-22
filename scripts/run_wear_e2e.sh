#!/usr/bin/env bash
set -euo pipefail

SMOKE_ONLY=false
TEST_CLASS=""
TEST_METHOD=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --smoke-only)
      SMOKE_ONLY=true
      shift
      ;;
    --test-class|-c)
      TEST_CLASS="$2"
      shift 2
      ;;
    --test-method|-m)
      TEST_METHOD="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--smoke-only] [--test-class|-c CLASS] [--test-method|-m METHOD]" >&2
      exit 1
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

# Setup logcat capture
LOGS_DIR="wearos/build/e2e-logs"
mkdir -p "$LOGS_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOGS_DIR/logcat_$TIMESTAMP.txt"
echo "Capturing device logs to: $LOG_FILE"

# Clear logcat buffer and start capturing logs in background
echo "Starting logcat capture..."
APP_PACKAGE="com.gabstra.myworkoutassistant"
adb logcat -c >/dev/null 2>&1
adb logcat -v time *:V 2>&1 | grep "$APP_PACKAGE" > "$LOG_FILE" &
LOGCAT_PID=$!

# Wait a moment for logcat to start
sleep 0.5

# Function to cleanup logcat on exit
cleanup_logcat() {
  if [ -n "$LOGCAT_PID" ] && kill -0 "$LOGCAT_PID" 2>/dev/null; then
    echo "Stopping logcat capture..."
    kill "$LOGCAT_PID" 2>/dev/null || true
    wait "$LOGCAT_PID" 2>/dev/null || true
    LOGCAT_PID=""  # Clear PID to prevent double cleanup
  fi
}

# Ensure logcat is stopped on script exit
trap cleanup_logcat EXIT

BASE_CMD=(./gradlew :wearos:connectedDebugAndroidTest)
TEST_ARG=""

if [ -n "$TEST_METHOD" ]; then
  if [ -z "$TEST_CLASS" ]; then
    echo "ERROR: --test-method requires --test-class to be specified." >&2
    cleanup_logcat
    exit 1
  fi
  # Format: ClassName#methodName
  if [[ "$TEST_CLASS" =~ ^com\. ]]; then
    FULL_CLASS_NAME="$TEST_CLASS"
  else
    FULL_CLASS_NAME="com.gabstra.myworkoutassistant.e2e.$TEST_CLASS"
  fi
  TEST_ARG="-Pandroid.testInstrumentationRunnerArguments.class=$FULL_CLASS_NAME#$TEST_METHOD"
elif [ -n "$TEST_CLASS" ]; then
  # Support comma-separated list of classes
  IFS=',' read -ra CLASSES <<< "$TEST_CLASS"
  FULL_CLASSES=()
  for class in "${CLASSES[@]}"; do
    class=$(echo "$class" | xargs)  # trim whitespace
    if [[ "$class" =~ ^com\. ]]; then
      FULL_CLASSES+=("$class")
    else
      FULL_CLASSES+=("com.gabstra.myworkoutassistant.e2e.$class")
    fi
  done
  TEST_ARG="-Pandroid.testInstrumentationRunnerArguments.class=$(IFS=','; echo "${FULL_CLASSES[*]}")"
elif [ "$SMOKE_ONLY" = true ]; then
  TEST_ARG="-Pandroid.testInstrumentationRunnerArguments.class=com.gabstra.myworkoutassistant.e2e.SmokeE2ETest"
fi

if [ -n "$TEST_ARG" ]; then
  CMD=("${BASE_CMD[@]}" "$TEST_ARG")
else
  CMD=("${BASE_CMD[@]}")
fi

echo "Executing: ${CMD[*]}"
"${CMD[@]}"
EXIT_CODE=$?

# Stop logcat capture
cleanup_logcat

if [ -f "$LOG_FILE" ]; then
  LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
  echo "Device logs saved to: $LOG_FILE ($LOG_SIZE)"
else
  echo "WARNING: Log file was not created: $LOG_FILE" >&2
fi

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: Wear OS E2E tests failed with exit code $EXIT_CODE. Check JUnit XML under wearos/build/outputs/androidTest-results or wearos/build/test-results/connected." >&2
  echo "Device logs available at: $LOG_FILE"
  exit $EXIT_CODE
fi

echo "Wear OS E2E tests completed successfully."


