# MyWorkoutAssistant (Wear OS) - Agent Reference

This document gives future agents the context they need to work on the Wear OS app: what the app does, how the flows fit together, where state lives, how data moves between phone and watch, and how to test E2E scenarios. It is intentionally detailed to reduce guesswork.

## Purpose and high-level behavior
- Wear OS companion app that lets users pick a workout synced from the phone, start or resume it, progress through exercises/sets/rests, and finish with progression info. Heart rate can come from the watch sensor or a Polar device. Scheduled alarms can launch workouts.
- Core states follow `WorkoutState`: `Preparing` -> `Set` -> `Rest` -> `Completed`. A paused workout can be resumed from where it stopped. Notifications and alarms keep the user aware if the app isn't foregrounded.

## App lifecycle and entry points
- **MainActivity.kt** bootstraps everything:
  - Loads WorkoutStore JSON from watch storage, initializes DAOs, sets nav start destination (normally `WorkoutSelection`; can switch to `Workout` if resuming/notification).
  - Registers receivers:
    - `MyReceiver` (DataLayer broadcast) updates store, handles backups, reschedules alarms.
    - `errorLogReceiver` to sync errors to the phone.
  - Handles notification intents via `handleNotificationIntent`: if a workout is already in progress (flag in `SharedPreferences("workout_state").isWorkoutInProgress`), it refuses to start another; otherwise sets `executeStartWorkout` to kick off that workout.
  - Wires data layer (`WearDataLayerAppHelper`, `DataClient`), haptics, HR/Polar view models.
- **WearApp composable** sets up:
  - Nav graph: `WorkoutSelection`, `WorkoutDetail`, `Workout`, `Loading`.
  - Tutorial flags (selection, HR, set screen, rest screen) from `TutorialPreferences`.
  - Resume flow: queries incomplete workouts and shows `ResumeWorkoutDialog` if present.
  - Background dimming via `KeepOn`.
  - HR/Polar view models; connects to phone nodes for sync.

## Screens and user flows
- **WorkoutSelectionScreen.kt**
  - Lists workouts sorted by `order`.
  - Back exits the app (finish Activity).
  - Header interactions: long-press -> version toast; double-tap -> data tools (clear data dialog).
  - Permission helpers: notification permission status; exact-alarm prompt if not allowed.
  - "Open mobile app" triggers phone settings via data layer.
  - If `userAge` matches current year, prompts user to fill age on phone.
- **WorkoutDetailScreen.kt**
  - Shows selected workout, Start/Resume/Delete paused workout/Send history/Back.
  - Runtime permissions (BODY_SENSORS, BLUETOOTH_SCAN/CONNECT, location, POST_NOTIFICATIONS) gate Start/Resume.
  - If a paused workout exists, Start may first show a confirmation dialog to delete the paused record.
  - Start sets `isWorkoutInProgress` flag, navigates to `Workout`.
- **WorkoutScreen.kt** (state machine host)
  - Uses `WorkoutState` to render:
    - **PreparingStandardScreen:** waits for data + minimum 3s before moving into sets; stops back nav.
    - **PreparingPolarScreen:** connects to Polar; if no device, shows skip after 5s; transitions after connection or skip. Respects `hasWorkoutRecord` to resume last state.
    - **Set state:** via `ExerciseScreen` with a pager for detail/plates/progression/muscles/notes/exercises/buttons. Supports intra-set sides, warmups, progression comparison, plate math. Back double-press opens "Workout in progress" dialog; dialogs for completing set appear via `CustomDialogYesOnLongPress`.
    - **Rest state:** `RestScreen` timer auto-advances to next state. User can long-press to edit timer (+/-5s), skip via dialog, see current/next exercise, plates/progression when applicable.
    - **Completed state:** `WorkoutCompleteScreen` stops sensors/Polar, clears notification and in-progress flag, shows progression section, auto-close countdown (5s if no data, 30s otherwise), and dialog to return to main menu.
  - Tutorials: overlays may appear for HR, set screen, rest screen; they dimming-inhibit and need dismissal.
  - Notifications: `showWorkoutInProgressNotification` when workout starts; `cancelWorkoutInProgressNotification` on end or Go Home.
  - Back handling: custom back handler opens "Workout in progress" dialog; double-press pauses/opens dialog unless already completed.
- **WorkoutAlarmActivity.kt**
  - Full-screen, over lockscreen, launched by scheduler (phone-backed schedules).
  - If `isWorkoutInProgress` flag is true, it immediately exits and cancels notification.
  - Shows long-press dialog: Yes starts MainActivity with WORKOUT_ID/SCHEDULE_ID; No stops alarm. Auto-stops after 10s.

## Data, storage, and sync
- **WorkoutStore** lives in `filesDir/workout_store.json` on the watch. Repository: `shared/WorkoutStoreRepository`.
- DAOs (Room) for histories, records, schedules, exercise info, progression: initialized in `WearApp`.
- **In-progress flag:** `SharedPreferences("workout_state").isWorkoutInProgress` ensures only one workout; checked in MainActivity and AlarmActivity.
- **Paused workout record:** stored in Room; Detail screen shows "Resume/Delete paused workout" when present; PageButtons allows "Go Home" which persists the record and clears notification/flag.
- **DataLayerListenerService.kt**
  - Receives WorkoutStore and backup chunks from phone; decompresses and writes.
  - On backup end: wipes schedules, histories, records, progression; reinserts from backup; cleans up old histories (keeps recent ones for plateau detection).
  - Handles `CLEAR_ERROR_LOGS_PATH`; broadcasts progress/failure; guards against mismatched transactions.
- **Error logs:** captured via `MyApplication` on watch; synced to phone on app open and when errors logged (DataClient).

## Sensors and devices
- **Standard HR:** `SensorDataViewModel` start/stop tied to lifecycle; stopped on pause, resumed on resume; stopped on completion.
- **Polar:** `PolarViewModel` connects during PreparingPolar; may be disconnected on completion. `WorkoutScreen` differentiates HR vs Polar for chart rendering.
- **Permissions:** BODY_SENSORS, ACTIVITY_RECOGNITION (if used), BLUETOOTH_SCAN/CONNECT, location (for BT scan), POST_NOTIFICATIONS. UI tests grant via shell.

## Notifications and alarms
- Workout in-progress notification handled in WorkoutScreen (via `WorkoutNotificationHelper`).
- Scheduled alarms: `WorkoutAlarmScheduler` (phone-driven) creates notifications; AlarmActivity displays over lockscreen; MainActivity cancels schedule notifications on handling intents.

## Tutorials and overlays
- Selection tutorial, HR tutorial, set tutorial, rest tutorial: controlled by `TutorialPreferences`. Overlays can block taps; tests should always dismiss them (`dismissTutorialIfPresent()` helper in tests).

## UI composition details (important for tests)
- Many elements are text-based; UIAutomator locators rely on visible text (for example: "Start", "Preparing HR Sensor", "Preparing Polar Sensor", "Workout in progress", "Completed", "Go Home").
- Pager pages in `ExerciseScreen`:
  - Detail (always).
  - Plates (barbell equipment).
  - ProgressionComparison (if progression data available).
  - Muscles (if data).
  - Notes (if present).
  - Exercises list.
  - Buttons.
  Pager auto-recenters to Exercise Detail after inactivity.
- RestScreen pager: Exercises, Plates (if barbell), ProgressionComparison (if data), Buttons. Timer editable via long-press; skip dialog is `CustomDialogYesOnLongPress`.
- Completion screen auto-close countdown shows `Closing in: <seconds>`.

## Testing and E2E guidance
- **Current E2E tests:** `src/androidTest/java/com/gabstra/myworkoutassistant/e2e/`
  - `WearBaseE2ETest` grants permissions via shell, seeds WorkoutStore, launches app, dismisses tutorial.
  - `TestWorkoutStoreSeeder` writes `workout_store.json` (currently one default workout: Bench/Squat with rest set).
  - Tests cover: selection header and tap to detail; start preparing; basic in-progress back dialog; complete flow via dialog; smoke launch.
- **Gaps to be aware of** (worth covering in new tests):
  - Real set/rest progression (edits, skip rest, timers).
  - Supersets, intra-set (side switching), warmups, timed-duration sets.
  - Plates/progression pages navigation.
  - Resume/go-home persistence and record reuse.
  - Polar path (skip after timeout) and success path.
  - Alarm/notification launch path.
- **Running tests:** `./gradlew connectedAndroidTest -Pandroid.testInstrumentationRunnerArguments.package=com.gabstra.myworkoutassistant.e2e`
  - Filter by class: add `-Pandroid.testInstrumentationRunnerArguments.class=com.gabstra.myworkoutassistant.e2e.YourTest`.
- **Flakiness control:**
  - Always call `dismissTutorialIfPresent()` after launch/start.
  - Use `Until.findObject` with generous timeouts.
  - Timers/rest: prefer `textContains` matches (for example, "Preparing") and waits after clicks.
  - Ensure workout records are cleared or accounted for (Resume button alters detail UI).
  - If Polar hardware isn't present, rely on skip-after-5s logic in PreparingPolar.

## Data seeding for tests
- Seed helper: `TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore?)` writes `workout_store.json` using shared JSON adapters.
- Default store (today): one barbell workout with Bench + Squat, simple rest set.
- For richer coverage, extend seeder to include:
  - Standard HR workout with multiple sets/rests and short timers.
  - Polar workout (`usePolarDevice = true`) to hit PreparingPolar path.
  - Superset workout (A/B exercises) with plates page enabled.
  - Timed-duration set with auto-start and countdown.
  - Bodyweight with additional weight and intra-set sides (`intraSetTotal`/`intraSetCounter`).
  - Short rest timers for speed in E2E.

## Persistence flags and pitfalls
- `isWorkoutInProgress` flag controls: refusal to start from notification/AlarmActivity if already true; cleared on WorkoutCompleteScreen and PageButtons "Go Home".
- Paused workout record alters Detail screen: shows Resume/Delete buttons and Start confirmation dialog.
- Back handling differences: Selection exits app; Detail pops back; Workout shows dialog; AlarmActivity disables back.
- Tutorials and overlays can hide buttons; always check for "Got it" or call dismissal helper.

## Key classes to know
- `data/AppViewModel` (extends shared `WorkoutViewModel`): orchestrates state transitions, notification triggers, data send to phone, dimming, timers; exposes `screenState`.
- `screens/*`: concrete UI flows.
- `composables/*`: UI building blocks (set/rest/timed set, dialogs, plates, progression, indicators).
- `notifications/WorkoutNotificationHelper.kt`: notification channel handling.
- `scheduling/WorkoutAlarmScheduler.kt`: alarm scheduler.
- `DataLayerListenerService.kt`: sync in/out, backup handling, cleanup.

## How to add/adjust E2E tests (suggested patterns)
- Use `WearBaseE2ETest` helpers: `launchAppFromHome`, `waitForText`, `clickText`, `dismissTutorialIfPresent`.
- Add helper to start a specific workout by name, optionally resume vs start fresh.
- For set/rest interactions:
  - Complete set via "Complete Set" dialog (`CustomDialogYesOnLongPress`).
  - Edit rest: long-press timer, use +/- (plus/minus are UI buttons in RestScreen), exit edit by inactivity.
  - Skip rest: trigger dialog and confirm.
  - Navigate pager to Plates/ProgressionComparison by swiping horizontally (if needed, use UiScrollable or by text).
- For completion: assert "Completed" text and name; handle auto-close countdown (test both wait and dialog "Workout completed" yes/no).
- For go-home/resume: tap "Go Home" (PageButtons) to persist record; relaunch app -> detail should show "Resume"; resume and verify state restored.
- For Polar path: start Polar workout; wait for "Preparing Polar Sensor"; if no device, after 5s skip button appears (double-arrow); assert transition to sets.

## Build/run commands (local)
- Assemble: `./gradlew assembleDebug`
- Install and test: `./gradlew connectedDebugAndroidTest`
- Target E2E package: `./gradlew connectedAndroidTest -Pandroid.testInstrumentationRunnerArguments.package=com.gabstra.myworkoutassistant.e2e`

## Common failure modes to watch for
- Permission dialogs appearing (should be pre-granted in tests; add permission grants if new permissions appear).
- Tutorials masking taps (call dismissal helper).
- Polar connection unavailable on device (tests must allow skip path).
- Shared state from previous run (paused record) changing UI; consider clearing with PageButtons "Go Home" or deleting records in setup.
- Animations/timers: add waits after navigation; prefer `textContains` for "Preparing" vs exact text if HR vs Polar changes wording.

## File map (Wear module)
- `src/main/java/com/gabstra/myworkoutassistant/MainActivity.kt`: app bootstrap, nav host, receivers, intents, error sync.
- `src/main/java/com/gabstra/myworkoutassistant/DataLayerListenerService.kt`: phone-watch sync, backups, cleanup.
- `src/main/java/com/gabstra/myworkoutassistant/screens/*`: UI screens.
- `src/main/java/com/gabstra/myworkoutassistant/composables/*`: reusable UI blocks (set/rest/timed set, dialogs, plates, progression, indicators).
- `src/main/java/com/gabstra/myworkoutassistant/data/*`: view models, state, notification helpers.
- `src/main/java/com/gabstra/myworkoutassistant/notifications/*`: notification helpers.
- `src/main/java/com/gabstra/myworkoutassistant/scheduling/*`: alarm scheduler.
- `src/main/java/com/gabstra/myworkoutassistant/receivers/*`: alarm/boot receivers.
- `src/androidTest/java/com/gabstra/myworkoutassistant/e2e/*`: E2E tests and seeding helpers.

## Quick reference: texts used in UI (for locators)
- Selection header: "My Workout Assistant"
- Detail buttons: "Start", "Resume", "Delete paused workout", "Send history", "Back"
- Preparing: "Preparing HR Sensor" (standard) or "Preparing Polar Sensor" (Polar); sometimes matching `textContains("Preparing")` is safer.
- Back dialog: "Workout in progress" with icons "Done" (yes) / "Close" (no)
- Rest skip dialog: "Skip Rest"
- Completion: "Completed", dialog title "Workout completed", countdown text "Closing in:"
- Go home: "Go Home" (PageButtons)
- Alarm dialog: shows workout name or app name; yes/no are long-press icons.

