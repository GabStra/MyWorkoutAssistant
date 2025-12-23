# Agent Instructions

- Always run `pwsh ./scripts/run_wear_e2e.ps1` with the maximum available timeout so the run can complete and be tracked to the end (do not rely on default tool timeouts).
- Always run E2E tests via the PowerShell script (e.g., `pwsh ./scripts/run_wear_e2e.ps1`) rather than invoking Gradle directly.
- When targeting a specific test class, call `pwsh ./scripts/run_wear_e2e.ps1 -TestClass <ClassName>` using a class from the `com.gabstra.myworkoutassistant.e2e` package (do not pass a fully qualified name).
- When targeting a specific test method, provide both `-TestClass <ClassName>` (from the `com.gabstra.myworkoutassistant.e2e` package) and `-TestMethod <MethodName>`.
