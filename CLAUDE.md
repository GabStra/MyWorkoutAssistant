# MyWorkoutAssistant Development Guide

## Build, Test & Lint Commands
- Build mobile app: `./gradlew :mobile:assembleDebug`
- Build wear OS app: `./gradlew :wearos:assembleDebug`
- Run all tests: `./gradlew test`
- Run specific test: `./gradlew :module:testDebugUnitTest --tests "com.gabstra.myworkoutassistant.TestClass.testMethod"`
- Check for lint issues: `./gradlew lint`

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