package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import org.junit.Before

abstract class WearBaseE2ETest {

    protected lateinit var device: UiDevice
    protected lateinit var context: Context
    protected val defaultTimeoutMs: Long = E2ETestTimings.DEFAULT_TIMEOUT_MS
    private val interactionDriver: WearWorkoutDriver by lazy {
        WearWorkoutDriver(device) { desc, timeout -> longPressByDesc(desc, timeout) }
    }

    @Before
    open fun baseSetUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        context = ApplicationProvider.getApplicationContext()

        // Grant all required runtime permissions before launching the app.
        // This prevents permission dialogs from appearing during tests.
        // Keep this list in sync with runtime permissions declared in AndroidManifest.xml.
        grantPermissions(
            android.Manifest.permission.BODY_SENSORS,
            android.Manifest.permission.ACTIVITY_RECOGNITION,
            android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.BLUETOOTH_SCAN,
            android.Manifest.permission.BLUETOOTH_CONNECT
        )

        clearPersistedE2eState()
        markTutorialsAsSeenForE2E()
        seedWorkoutStore()
        launchAppFromHome()
    }

    /**
     * Grants runtime permissions to the target app package using UiAutomation API.
     * This is the most reliable way to grant permissions in E2E tests, avoiding
     * brittle UI-based permission dialog interactions.
     */
    protected fun grantPermissions(vararg perms: String) {
        val inst = InstrumentationRegistry.getInstrumentation()
        val pkg = inst.targetContext.packageName
        val ua = inst.uiAutomation
        perms.forEach { perm ->
            ua.grantRuntimePermission(pkg, perm)
        }
    }

    protected fun seedWorkoutStore() {
        TestWorkoutStoreSeeder.seedWorkoutStore(context)
    }

    private fun clearPersistedE2eState() {
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("workout_recovery_checkpoint", Context.MODE_PRIVATE).edit().clear().commit()
    }

    private fun markTutorialsAsSeenForE2E() {
        context.getSharedPreferences("tutorial_prefs", Context.MODE_PRIVATE).edit()
            .putBoolean("has_seen_workout_selection_tutorial", true)
            .putBoolean("has_seen_workout_heart_rate_tutorial", true)
            .putBoolean("has_seen_set_screen_tutorial", true)
            .putBoolean("has_seen_rest_screen_tutorial", true)
            .commit()
    }

    /**
     * Launches the app from home and waits until the main screen is ready.
     * Uses (1) retry if the window doesn't appear, and (2) a readiness condition (selection screen
     * visible) so we don't proceed on a raw window timeout.
     */
    protected fun launchAppFromHome() {
        val pkg = context.packageName
        val launchIntent = context.packageManager.getLaunchIntentForPackage(pkg)
            ?: error("Launch intent for package $pkg not found")
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)

        val windowSelector = By.pkg(pkg).depth(0)
        var windowAppeared = false
        repeat(2) { attempt ->
            device.pressHome()
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            context.startActivity(launchIntent)
            windowAppeared = device.wait(
                Until.hasObject(windowSelector),
                E2ETestTimings.APP_LAUNCH_WINDOW_TIMEOUT_MS
            )
            if (windowAppeared) return@repeat
        }
        require(windowAppeared) { "Timed out waiting for app ($pkg) to appear on screen after 2 launch attempts" }

        // Wait for app to settle and optionally show tutorial
        device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION)

        // Readiness: proceed when either selection screen or recovery dialog is visible (relaunch may show recovery first)
        val deadline = System.currentTimeMillis() + E2ETestTimings.APP_LAUNCH_CONTENT_READY_MS
        var ready = false
        while (System.currentTimeMillis() < deadline) {
            dismissAnyTutorialOverlayIfPresent()
            if (device.hasObject(By.text("My Workout Assistant")) ||
                isRecoveryDialogVisible() ||
                device.hasObject(By.textContains("Resuming workout")) ||
                device.hasObject(By.textContains("Reloading workout")) ||
                isActiveWorkoutVisible()
            ) {
                ready = true
                break
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        if (!ready) {
            // Process-death/resume scenarios can transiently show intermediate frames where
            // selectors are not yet stable. Allow callers to continue with their own recovery waits.
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    private fun dismissAnyTutorialOverlayIfPresent() {
        val gotIt = device.findObject(By.text("Got it")) ?: return
        runCatching { gotIt.click() }
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
    }

    private fun isActiveWorkoutVisible(): Boolean {
        return device.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)) ||
            device.hasObject(By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)) ||
            device.hasObject(By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)) ||
            device.hasObject(By.descContains(SetValueSemantics.EnduranceSetTypeDescription)) ||
            device.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)) ||
            device.hasObject(By.textContains("Set load for")) ||
            device.hasObject(By.text("0 = Form Breaks")) ||
            device.hasObject(By.text("Start")) ||
            device.hasObject(By.text("Stop"))
    }

    private fun isRecoveryDialogVisible(): Boolean {
        return device.hasObject(By.desc("Recovery resume action")) ||
            device.hasObject(By.desc("Recovery discard action")) ||
            device.hasObject(By.text("Resume or discard this interrupted workout."))
    }

    protected fun createWorkoutDriver(): WearWorkoutDriver = interactionDriver

    /**
     * Performs a long press on a UI element identified by its content description.
     * This is used for dialogs that require long press confirmation (e.g., CustomDialogYesOnLongPress).
     * 
     * @param contentDescription The content description of the element to long press
     * @param timeoutMs Timeout in milliseconds to wait for the element to appear
     */
    private fun longPressByDesc(contentDescription: String, timeoutMs: Long = defaultTimeoutMs) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var attempts = 0
        var lastError: Throwable? = null

        while (System.currentTimeMillis() < deadline && attempts < 5) {
            attempts++
            val remaining = (deadline - System.currentTimeMillis()).coerceAtLeast(1L)
            val obj = device.wait(Until.findObject(By.desc(contentDescription)), remaining)
            if (obj == null) {
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                continue
            }

            val pressed = runCatching {
                val bounds = obj.visibleBounds
                val centerX = bounds.centerX()
                val centerY = bounds.centerY()
                // Hold press via swipe gesture at a fixed point to trigger long-press handlers.
                device.swipe(centerX, centerY, centerX, centerY, 200)
                true
            }.recoverCatching {
                if (it is StaleObjectException) {
                    val refreshed = device.wait(Until.findObject(By.desc(contentDescription)), 500)
                    if (refreshed != null) {
                        val bounds = refreshed.visibleBounds
                        device.swipe(bounds.centerX(), bounds.centerY(), bounds.centerX(), bounds.centerY(), 200)
                        true
                    } else {
                        false
                    }
                } else {
                    throw it
                }
            }.getOrElse {
                lastError = it
                false
            }

            if (pressed) {
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                return
            }

            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        if (lastError != null) {
            throw IllegalArgumentException(
                "Failed to long-press UI object with content description '$contentDescription'",
                lastError
            )
        }
        throw IllegalArgumentException(
            "Timed out waiting for UI object with content description '$contentDescription' to appear"
        )
    }

    /**
     * Enum representing different tutorial contexts in the app flow.
     * Each context corresponds to a specific screen where a tutorial may appear.
     */
    protected enum class TutorialContext {
        WORKOUT_SELECTION,  // WorkoutSelectionScreen
        HEART_RATE,         // WorkoutScreen when workout starts (before Set/Rest states)
        SET_SCREEN,         // WorkoutScreen when in Set state
        REST_SCREEN         // WorkoutScreen when in Rest state
    }

    /**
     * Dismisses the resume workout dialog if present when reopening the app after leaving
     * a workout incomplete. This ensures tests can start fresh without dealing with resume options.
     * 
     * Behavior:
     * 1) Check if "Resume" button is visible (indicates paused workout dialog/screen is present)
     * 2) If found, press back to dismiss and return to workout selection screen
     * 3) This allows tests to start workouts fresh rather than resuming
     */
    protected fun dismissResumeDialogIfPresent() {
        interactionDriver.dismissResumeDialogIfPresent(timeoutMs = 2_000)
    }

    /**
     * Best-effort dismissal of any tutorial overlay that might be covering
     * the workout UI, checking only the relevant preference for the current screen context.
     *
     * Behavior:
     * 1) Check the specific tutorial preference for the given context.
     * 2) If already seen, skip UI interaction to avoid random scrolling.
     * 3) Use scrollUntilFound to find the "Got it" button (checks if visible first, then scrolls if needed).
     * 4) If found, click it.
     *
     * @param tutorialContext The tutorial context indicating which screen we're on
     * @param maxWaitMs Maximum time to wait for the tutorial button to appear
     */
    protected fun dismissTutorialIfPresent(
        tutorialContext: TutorialContext,
        maxWaitMs: Long = 1_000
    ) {
        val prefs = context.getSharedPreferences("tutorial_prefs", Context.MODE_PRIVATE)

        val hasSeenTutorial = when (tutorialContext) {
            TutorialContext.WORKOUT_SELECTION ->
                prefs.getBoolean("has_seen_workout_selection_tutorial", false)
            TutorialContext.HEART_RATE ->
                prefs.getBoolean("has_seen_workout_heart_rate_tutorial", false)
            TutorialContext.SET_SCREEN ->
                prefs.getBoolean("has_seen_set_screen_tutorial", false)
            TutorialContext.REST_SCREEN ->
                prefs.getBoolean("has_seen_rest_screen_tutorial", false)
        }

        if (hasSeenTutorial) return

        val deadline = System.currentTimeMillis() + maxWaitMs
        while (System.currentTimeMillis() < deadline) {
            val gotIt = device.findObject(By.text("Got it")) ?: device.findObject(By.desc("Got it"))
            if (gotIt != null) {
                runCatching { interactionDriver.clickObjectOrAncestor(gotIt) }
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                return
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
    }

    /**
     * Starts a workout by selecting it by name and waiting for the preparing step to complete.
     * 
     * @param workoutName The name of the workout to select and start
     */
    protected fun startWorkout(workoutName: String) {
        // Dismiss workout selection tutorial if present (we're still on WorkoutSelectionScreen)
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)

        val headerAppeared = interactionDriver.waitForText("My Workout Assistant", defaultTimeoutMs)
        require(headerAppeared) { "Selection header not visible" }

        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        interactionDriver.openWorkoutDetailAndStartOrResume(
            workoutName = workoutName,
            timeoutMs = defaultTimeoutMs
        )

        // Dismiss heart rate tutorial if it appears (shown when workout starts, before Set/Rest states)
        // Use longer timeout to catch tutorial that appears after a delay
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        
        var enteredWorkoutFlow = waitForPostStartWorkoutState(timeoutMs = 10_000)
        if (!enteredWorkoutFlow) {
            val recoveryResume = device.findObject(By.desc("Recovery resume action"))
                ?: device.findObject(By.text("Resume"))
            if (recoveryResume != null) {
                runCatching { interactionDriver.clickObjectOrAncestor(recoveryResume) }
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            } else {
                val startAgain = device.findObject(By.desc("Start"))
                    ?: device.findObject(By.text("Start"))
                    ?: device.findObject(By.desc("Resume"))
                    ?: device.findObject(By.text("Resume"))
                if (startAgain != null) {
                    runCatching { interactionDriver.clickObjectOrAncestor(startAgain) }
                    device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                }
            }
            dismissAnyTutorialOverlayIfPresent()
            enteredWorkoutFlow = waitForPostStartWorkoutState(timeoutMs = 8_000)
        }
        require(enteredWorkoutFlow) {
            "Workout did not reach a known post-start state (preparing, calibration, set/rest, or completion)"
        }

        val preparingVisible = device.hasObject(By.textContains("Preparing"))
        if (preparingVisible) {
            val preparingGone = device.wait(Until.gone(By.textContains("Preparing")), 8_000)
            require(preparingGone) { "Preparing step did not complete" }
        }

        if (isActiveWorkoutVisible()) {
            dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
        }
    }

    private fun waitForPostStartWorkoutState(timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            dismissAnyTutorialOverlayIfPresent()
            if (device.hasObject(By.textContains("Preparing")) ||
                device.hasObject(By.textContains("Set load for")) ||
                device.hasObject(By.text("0 = Form Breaks")) ||
                device.hasObject(By.textContains("Resuming workout")) ||
                device.hasObject(By.textContains("Reloading workout")) ||
                isActiveWorkoutVisible() ||
                device.hasObject(By.text("Go Home"))
            ) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }
}
