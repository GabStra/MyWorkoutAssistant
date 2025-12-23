package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.TestWorkoutStoreSeeder
import org.junit.Before

abstract class BaseWearE2ETest {

    protected lateinit var device: UiDevice
    protected lateinit var context: Context
    protected val defaultTimeoutMs: Long = 5_000

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

    protected fun launchAppFromHome() {
        device.pressHome()

        val pkg = context.packageName
        val launchIntent = context.packageManager.getLaunchIntentForPackage(pkg)
            ?: error("Launch intent for package $pkg not found")

        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(launchIntent)

        val appeared = device.wait(Until.hasObject(By.pkg(pkg).depth(0)), defaultTimeoutMs)
        require(appeared) { "Timed out waiting for app ($pkg) to appear on screen" }

        // Wait a bit for the app to fully initialize and potentially show tutorial
        device.waitForIdle(2_000)
        
        // Dismiss tutorial overlay if present (shown after app launch on WorkoutSelectionScreen)
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION)
        
        // Wait for UI to settle after tutorial dismissal
        device.waitForIdle(1_000)
    }

    protected fun waitForText(text: String, timeoutMs: Long = defaultTimeoutMs): Boolean {
        return device.wait(Until.hasObject(By.text(text)), timeoutMs)
    }

    protected fun clickText(text: String) {
        // Wait for the target text to actually appear in the UI before clicking.
        // Using Until.findObject() avoids the race where hasObject() returns true
        // but a subsequent findObject() still returns null.
        val obj = device.wait(Until.findObject(By.text(text)), defaultTimeoutMs)
        require(obj != null) {
            "Timed out waiting for UI object with text '$text' to appear"
        }
        clickObjectOrAncestor(obj)
        device.waitForIdle(500)
    }

    /**
     * Performs a long press on a UI element identified by its content description.
     * This is used for dialogs that require long press confirmation (e.g., CustomDialogYesOnLongPress).
     * 
     * @param contentDescription The content description of the element to long press
     * @param timeoutMs Timeout in milliseconds to wait for the element to appear
     */
    protected fun longPressByDesc(contentDescription: String, timeoutMs: Long = defaultTimeoutMs) {
        val obj = device.wait(Until.findObject(By.desc(contentDescription)), timeoutMs)
        require(obj != null) {
            "Timed out waiting for UI object with content description '$contentDescription' to appear"
        }
        // Use a swipe-based press to trigger pointerInput long-press handlers reliably.
        val bounds = obj.visibleBounds
        val centerX = bounds.centerX()
        val centerY = bounds.centerY()
        device.swipe(centerX, centerY, centerX, centerY, 100)
        device.waitForIdle(1_000)
    }

    /**
     * Generic helper that scrolls until a selector is found.
     * First checks if the element is already visible (fast path), then attempts to scroll
     * in the specified direction until the element is found.
     * 
     * @param selector The By selector to search for
     * @param direction The direction to scroll (e.g., Direction.DOWN, Direction.UP)
     * @param initialWaitMs Timeout in milliseconds to wait for the element before scrolling (default: 1_000)
     * @return The found UiObject2, or null if not found after scrolling
     */
    protected fun scrollUntilFound(
        selector: BySelector,
        direction: Direction,
        initialWaitMs: Long = 1_000
    ): UiObject2? {
        // Fast path: if already visible, return it immediately
        device.wait(Until.findObject(selector), initialWaitMs)?.let {
            return it
        }

        // Find scrollable container and scroll until the selector is found
        val scrollable = device.findObject(By.scrollable(true))
        if (scrollable != null) {
            return runCatching {
                scrollable.scrollUntil(direction, Until.findObject(selector))
            }.getOrNull()
        }

        // No scrollable container found, return null
        return null
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
     * Enum representing pager navigation directions.
     */
    protected enum class PagerDirection {
        LEFT,   // Swipe left to go to next page
        RIGHT   // Swipe right to go to previous page
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
        // Check if "Resume" button is visible (indicates we're on WorkoutDetailScreen with paused workout)
        val resumeVisible = device.wait(Until.hasObject(By.textContains("Resume")), 2_000)
        
        if (resumeVisible) {
            // Press back to dismiss the resume dialog and return to workout selection
            device.pressBack()
            device.waitForIdle(1_000)
        }
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

        val gotItSelector = By.text("Got it")
        
        // If not immediately visible, scroll until found
        scrollUntilFound(gotItSelector, Direction.DOWN, maxWaitMs)?.let { btn ->
            runCatching { clickObjectOrAncestor(btn) }
        }
    }

    private fun clickObjectOrAncestor(obj: UiObject2) {
        var current: UiObject2? = obj
        while (current != null && !current.isClickable) {
            current = current.parent
        }
        (current ?: obj).click()
    }

    private fun longClickObjectOrAncestor(obj: UiObject2) {
        var current: UiObject2? = obj
        while (current != null && !current.isLongClickable) {
            current = current.parent
        }
        (current ?: obj).longClick()
    }

    /**
     * Navigates to a specific pager page by swiping horizontally.
     * 
     * @param direction The direction to swipe (LEFT for next page, RIGHT for previous page)
     */
    protected fun navigateToPagerPage(direction: PagerDirection) {
        // Get screen dimensions for swipe
        val width = device.displayWidth
        val height = device.displayHeight
        val centerY = height / 2

        when (direction) {
            PagerDirection.LEFT -> {
                // Swipe left to go to next page - swipe from 80% to 20% of screen width for more reliable page change
                val startX = (width * 0.8).toInt().coerceAtMost(width - 1)
                val endX = (width * 0.2).toInt().coerceAtLeast(0)
                device.swipe(startX, centerY, endX, centerY, 5)
            }
            PagerDirection.RIGHT -> {
                // Swipe right to go to previous page - swipe from 20% to 80% of screen width for more reliable page change
                val startX = (width * 0.2).toInt().coerceAtLeast(0)
                val endX = (width * 0.8).toInt().coerceAtMost(width - 1)
                device.swipe(startX, centerY, endX, centerY, 5)
            }
        }
        device.waitForIdle(500)
    }

    /**
     * Starts a workout by selecting it by name and waiting for the preparing step to complete.
     * 
     * @param workoutName The name of the workout to select and start
     */
    protected fun startWorkout(workoutName: String) {
        // Dismiss workout selection tutorial if present (we're still on WorkoutSelectionScreen)
        dismissTutorialIfPresent(TutorialContext.WORKOUT_SELECTION, 2_000)

        val headerAppeared = waitForText("My Workout Assistant")
        require(headerAppeared) { "Selection header not visible" }

        val workoutAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(workoutAppeared) { "Workout '$workoutName' not visible to tap" }

        clickText(workoutName)

        val detailAppeared = device.wait(Until.hasObject(By.text(workoutName)), defaultTimeoutMs)
        require(detailAppeared) { "Workout detail with '$workoutName' not visible" }

        clickText("Start")

        // Dismiss heart rate tutorial if it appears (shown when workout starts, before Set/Rest states)
        // Use longer timeout to catch tutorial that appears after a delay
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 10_000)
        
        // Wait for "Preparing HR Sensor" or "Preparing Polar Sensor" text to appear
        // The screen shows "Preparing HR Sensor" not just "Preparing"
        // Note: Tutorial overlay is full-screen and blocks "Preparing" text when visible
        // If "Preparing" is visible, tutorial is definitely dismissed
        val preparingVisible = device.wait(Until.hasObject(By.textContains("Preparing")), 10_000)
        require(preparingVisible) { "WorkoutScreen 'Preparing' state not visible" }

        // Wait for preparing step to complete (preparing text disappears)
        // This indicates we've moved past the preparing state
        val preparingGone = device.wait(Until.gone(By.textContains("Preparing")), 10_000)
        require(preparingGone) { "Preparing step did not complete" }

        // After preparing step completes, we transition to the first exercise screen (Set state).
        // Dismiss set screen tutorial if it appears when transitioning to the first exercise screen.
        // The "Got it" button might only become visible after scrolling, so we do not gate
        // this on detecting the button first.
        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 10_000)
    }
}
