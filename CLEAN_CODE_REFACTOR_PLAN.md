# Clean Code Refactor Plan

## Objective
Improve maintainability and readability by applying single-responsibility, DRY, and Kotlin style conventions, with the highest-impact refactors first.

## Prioritization Criteria
- Large files with mixed responsibilities (hard to test and reason about).
- Duplicated logic across modules (risk of inconsistent behavior).
- UI files that combine state management + rendering (harder to evolve).
- Cross-cutting infrastructure code (sync, persistence) that affects multiple features.

## High-Priority Refactor Areas (in order)

### 1) Decompose WorkoutViewModel (core session logic)
- Files: `shared/src/main/java/com/gabstra/myworkoutassistant/shared/viewmodels/WorkoutViewModel.kt`
- Why: Very large file with multiple responsibilities (session state, persistence, progression, UI side-effects).
- Plan:
  - Extract session state management into a `WorkoutSessionController` (pure state + transitions).
  - Extract progression logic into a `ProgressionService` (set progression, warmups, plate calculation).
  - Extract persistence and data access into a `WorkoutPersistenceCoordinator` (DAOs, repo updates).
  - Keep ViewModel thin: wiring, state exposure, and lifecycle.
  - Add unit tests for extracted services (start with critical flows).

### 2) Split mobile Utils into focused modules
- Files: `mobile/src/main/java/com/gabstra/myworkoutassistant/Utils.kt`
- Why: Single file hosts UI helpers, data layer sync, Health Connect, serialization, and export logic.
- Plan:
  - Create domain-focused files: `SyncHandshake.kt`, `HealthConnectUtils.kt`,
    `ExportUtils.kt`, `DateTimeUtils.kt`, and `ComposeUiUtils.kt`.
  - Move Data Layer sync helpers into shared module if also used on Wear.
  - Keep top-level `Utils.kt` as thin re-exports or remove once references update.

### 3) Consolidate DataLayerListenerService duplication
- Files:
  - `mobile/src/main/java/com/gabstra/myworkoutassistant/DataLayerListenerService.kt`
  - `wearos/src/main/java/com/gabstra/myworkoutassistant/DataLayerListenerService.kt`
- Why: Similar chunking/serialization and sync logic duplicated with platform-specific details.
- Plan:
  - Extract shared chunk storage + (de)serialization into `shared` module.
  - Create a small, platform-specific service that delegates to shared helpers.
  - Centralize DataLayer path handling in one shared utility.

### 4) Break down large Compose screens
- Files:
  - `mobile/src/main/java/com/gabstra/myworkoutassistant/screens/WorkoutDetailScreen.kt`
  - `mobile/src/main/java/com/gabstra/myworkoutassistant/screens/WorkoutHistoryScreen.kt`
  - `mobile/src/main/java/com/gabstra/myworkoutassistant/MainActivity.kt`
- Why: Large UI files tend to mix rendering, event wiring, and state transformations.
- Plan:
  - Extract smaller composables per responsibility (header, list, filters, dialogs).
  - Move state transformation logic into viewmodels or UI state mappers.
  - Reduce parameter lists using UI state data classes.

### 5) Reduce cross-platform UI duplication (where feasible)
- Files:
  - `mobile/src/main/java/com/gabstra/myworkoutassistant/workout/*`
  - `wearos/src/main/java/com/gabstra/myworkoutassistant/composables/*`
- Why: Similar component names and behavior across platforms suggest duplication.
- Plan:
  - Identify shared primitives (e.g., time/weight formatting, state labels).
  - Extract common non-UI helpers to `shared` module.
  - Keep platform-specific UI, but reuse shared models and logic.

## Execution Notes
- Refactor in small, testable steps; avoid large, single-PR rewrites.
- Add or update tests as logic is extracted (prioritize the session flow).
- Re-run unit tests and build after each refactor batch.

## Definition of Done (per refactor item)
- New modules/classes are single-purpose and named clearly.
- Behavior remains the same (validated by tests or manual verification).
- Duplicate logic is removed or centralized.
