package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiScrollable
import androidx.test.uiautomator.UiSelector
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
     * Grants runtime permissions to the target app package via shell command.
     * This is the most reliable way to grant permissions in E2E tests, avoiding
     * brittle UI-based permission dialog interactions.
     */
    protected fun grantPermissions(vararg perms: String) {
        val inst = InstrumentationRegistry.getInstrumentation()
        val pkg = inst.targetContext.packageName
        val ua = inst.uiAutomation
        perms.forEach { perm ->
            ua.executeShellCommand("pm grant $pkg $perm").close()
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
        obj.click()
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
        // Long press requires holding for at least the system long press timeout (typically 500ms)
        // UIAutomator's longClick() handles this automatically
        obj.longClick()
        device.waitForIdle(1_000)
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
     * Best-effort dismissal of any tutorial overlay that might be covering
     * the workout UI, checking only the relevant preference for the current screen context.
     *
     * Original working behavior:
     * 1) Check the specific tutorial preference for the given context.
     * 2) If already seen, skip UI interaction to avoid random scrolling.
     * 3) Look for a "Got it" button; if found, click it and return.
     * 4) If not found, check if there's any scrollable container.
     * 5) If scrollable, scroll to the bottom once (to reveal the button),
     *    then try again to find and click "Got it".
     *
     * @param tutorialContext The tutorial context indicating which screen we're on
     * @param maxWaitMs Maximum time to wait for the tutorial button to appear
     */
    protected fun dismissTutorialIfPresent(tutorialContext: TutorialContext, maxWaitMs: Long = 1_000) {
        val prefs = context.getSharedPreferences("tutorial_prefs", Context.MODE_PRIVATE)
        
        // Check only the relevant preference for this screen context
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

        // If this specific tutorial was already seen, there's no overlay to dismiss.
        if (hasSeenTutorial) {
            return
        }

        // Wait for "Got it" button to appear (tutorial overlay may take time to render)
        val button = device.wait(Until.findObject(By.text("Got it")), maxWaitMs)
        if (button != null) {
            try {
                button.click()
                return
            } catch (_: Exception) {
                // Button found but not clickable, try scrolling
            }
        }

        // If button not found or not clickable, try scrolling to reveal it
        val scrollable = UiScrollable(UiSelector().scrollable(true))
        if (scrollable.exists()) {
            try {
                // Hint UiAutomator this is a vertical list and use a faster fling
                scrollable.setAsVerticalList()
                scrollable.flingToEnd(3)  // usually much faster than scrollToEnd(10)
                device.waitForIdle(300)

                // Try again after scrolling
                val buttonAfterScroll = device.wait(Until.findObject(By.text("Got it")), 1_000)
                if (buttonAfterScroll != null) {
                    try {
                        buttonAfterScroll.click()
                        return
                    } catch (_: Exception) {
                        // Could not click even after scrolling
                    }
                }
            } catch (_: Exception) {
                // Scroll failed, tutorial might not be present or not scrollable
            }
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
        dismissTutorialIfPresent(TutorialContext.HEART_RATE, 2_000)
        
        // Wait for "Preparing HR Sensor" or "Preparing Polar Sensor" text to appear
        // The screen shows "Preparing HR Sensor" not just "Preparing"
        // Note: Tutorial overlay is full-screen and blocks "Preparing" text when visible
        // If "Preparing" is visible, tutorial is definitely dismissed
        val preparingVisible = device.wait(Until.hasObject(By.textContains("Preparing")), 10_000)
        require(preparingVisible) { "WorkoutScreen 'Preparing' state not visible" }

        // Wait for preparing step to complete (preparing text disappears)
        // This indicates we've moved past the preparing state
        val preparingGone = device.wait(Until.gone(By.textContains("Preparing")), 15_000)
        require(preparingGone) { "Preparing step did not complete" }

        // After preparing step completes, we transition to the first exercise screen (Set state).
        // Dismiss set screen tutorial if it appears when transitioning to the first exercise screen.
        // The "Got it" button might only become visible after scrolling, so we do not gate
        // this on detecting the button first.
        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
    }
}


