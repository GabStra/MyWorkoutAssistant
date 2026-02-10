# MyWorkoutAssistant Development Guide

## Build, Test & Lint Commands
- Build mobile app: `./gradlew :mobile:assembleDebug`
- Build wear OS app: `./gradlew :wearos:assembleDebug`
- Run all unit tests: `./gradlew test`
- Run specific unit test: `./gradlew :module:testDebugUnitTest --tests "com.gabstra.myworkoutassistant.TestClass.testMethod"`
- Check for lint issues: `./gradlew lint`

### Wear OS E2E (instrumented UIAutomator) tests
- Run full Wear OS E2E suite on all connected devices/emulators (debug):
  - `./gradlew :wearos:connectedDebugAndroidTest`
- Run Wear OS E2E tests against release build (near-production, if needed):
  - `./gradlew :wearos:connectedReleaseAndroidTest`
- Run only the Wear OS smoke E2E suite (fast launch + basic flows):
  - `./gradlew :wearos:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.gabstra.myworkoutassistant.e2e.WearSmokeE2ETest`

### Agent workflow for Wear OS E2E tests
- Ensure at least one Wear OS device/emulator is connected and online:
  - `adb devices` (agent should verify there is at least one `device` entry).
- (Optional) Apply device-selection rules if multiple devices are connected (e.g. prefer Wear device model or a specific serial).
- From the project root, run the debug E2E suite:
  - `./gradlew :wearos:connectedDebugAndroidTest`
- Interpret results:
  - Treat a non-zero Gradle exit code as failure.
  - Parse JUnit XML results under:
    - `wearos/build/outputs/androidTest-results/` **or**
    - `wearos/build/test-results/connected/`
  - Extract number of tests, failures, and failure messages for reporting.
- For a quick health check, agents can run only the smoke E2E suite (see command above) and interpret results the same way.

## Code Style Guidelines
- **Package Structure**: Follow `com.gabstra.myworkoutassistant.shared` for shared code, with module-specific packages
- **Imports**: Group imports by package and organize alphabetically
- **Types**: Use explicit types for public functions, prefer nullable types over lateinit
- **Naming**:
  - Classes: PascalCase (e.g. `WorkoutComponent`)
  - Functions/Properties: camelCase (e.g. `getNewSetFromSetHistory`)
  - Constants: SNAKE_CASE (e.g. `ZONE_RANGES`)
- **Error Handling**: Use try/catch with specific exception types, include logging
- **Nullability**: Prefer safe calls (`?.`) and elvis operator (`?:`) over direct null assertions
- **Extensions**: Use extension functions for utility operations
- **UI Components**: Follow Jetpack Compose patterns with composable prefixes
- **Coroutines**: Use structured concurrency with viewModelScope

When adding new features, follow existing patterns for adapter registration and type conversions.
