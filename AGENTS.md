# Agent Instructions

## E2E Testing

- Always run `pwsh ./scripts/run_wear_e2e.ps1` with the maximum available timeout so the run can complete and be tracked to the end (do not rely on default tool timeouts).
- Always run E2E tests via the PowerShell script (e.g., `pwsh ./scripts/run_wear_e2e.ps1`) rather than invoking Gradle directly.
- When targeting a specific test class, call `pwsh ./scripts/run_wear_e2e.ps1 -TestClass <ClassName>` using a class from the `com.gabstra.myworkoutassistant.e2e` package (do not pass a fully qualified name).
- When targeting a specific test method, provide both `-TestClass <ClassName>` (from the `com.gabstra.myworkoutassistant.e2e` package) and `-TestMethod <MethodName>`.
- For cross-device sync E2E (Wear + phone emulator), run `pwsh ./scripts/run_cross_device_sync_e2e.ps1`.
- The cross-device script requires at least one connected Wear emulator/device and one connected phone emulator/device via `adb`.
- The cross-device script installs the mobile debug app, runs Wear producer E2E (`WearCrossDeviceSyncProducerE2ETest`) via `run_wear_e2e.ps1`, then runs mobile verification (`com.gabstra.myworkoutassistant.e2e.WorkoutSyncVerificationTest`).
- To override classes, use:
  - `pwsh ./scripts/run_cross_device_sync_e2e.ps1 -WearTestClass WearCrossDeviceSyncProducerE2ETest`
  - `pwsh ./scripts/run_cross_device_sync_e2e.ps1 -MobileTestClass com.gabstra.myworkoutassistant.e2e.WorkoutSyncVerificationTest`

## Coding Conventions

- Always follow good coding conventions and best practices when writing code.
- Follow DRY (Don't Repeat Yourself) principles - extract repeated code into reusable functions, classes, or utilities.
- Use meaningful variable and function names that clearly express their purpose and intent.
- Keep functions focused and single-purpose - avoid functions that do multiple unrelated things.
- Follow Kotlin coding conventions as defined in the official Kotlin style guide (https://kotlinlang.org/docs/coding-conventions.html).
- Use appropriate design patterns and architectural principles (e.g., MVVM, Repository pattern) consistently throughout the codebase.
- Write clean, readable code with appropriate comments where necessary, but prefer self-documenting code over excessive comments.
- Handle errors appropriately - use try-catch blocks, nullable types, and Result types where appropriate.
- Maintain consistency with existing codebase patterns and conventions.

## Build and Compilation

- Run a build when changes can affect app binaries or compilation outputs, including:
  - Kotlin/Java source files
  - Android resources (`res/`), manifests, or Gradle build scripts
  - Dependency/version/configuration changes
  - Generated code inputs (e.g., Room entities/DAOs, KSP-related sources)
- A build is NOT required for non-runtime/non-compilation changes only, such as:
  - Documentation (`*.md`), comments-only edits, or planning notes
  - Pure formatting/text changes that do not alter code/resource semantics
- Prefer the fastest sufficient verification command first (to keep iteration fast):
  - Kotlin/Java-only changes in mobile/shared code: `./gradlew :mobile:compileDebugKotlin :shared:compileDebugKotlin --parallel --build-cache`
  - Kotlin/Java-only changes in wear/shared code: `./gradlew :wearos:compileDebugKotlin :shared:compileDebugKotlin --parallel --build-cache`
  - Kotlin/Java changes affecting both apps (mobile + wear + shared): `./gradlew :mobile:compileDebugKotlin :wearos:compileDebugKotlin :shared:compileDebugKotlin --parallel --build-cache`
  - Mobile app changes affecting resources/manifests/packaging: `./gradlew :mobile:assembleDebug --parallel --build-cache`
  - Wear app changes affecting resources/manifests/packaging: `./gradlew :wearos:assembleDebug --parallel --build-cache`
  - Changes affecting both apps' resources/manifests/packaging: `./gradlew :mobile:assembleDebug :wearos:assembleDebug --parallel --build-cache`
- Use full builds (`./gradlew :mobile:build` or `./gradlew build`) only when explicitly requested, for release-critical validation, or when changes span multiple modules with potential integration impact.
- For specific modules, prefer debug variants before full build:
  - `./gradlew :module:compileDebugKotlin` (code-only)
  - `./gradlew :module:assembleDebug` (code + resources/manifest)
- If a fast-path command fails or is inconclusive, escalate to the next level (compile -> assemble -> full build).
- If compilation errors are found, fix them immediately before proceeding with other tasks or reporting completion.
- Do not leave code in a broken or uncompilable state. All code changes must result in a successfully compiling project.
- Check for both Kotlin and Java compilation errors, as well as resource and manifest errors.
- If build errors persist after attempts to fix them, clearly report the specific errors and their locations to the user rather than leaving the code in a broken state.
- If Gradle fails with `gradle-*.zip.lck (Access is denied)`, rerun the same Gradle command with escalated permissions so wrapper lock access is available.
- Use `read_lints` tool to check for linter errors after code changes and address any issues found.