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
    protected val defaultTimeoutMs: Long = 15_000

    @Before
    fun baseSetUp() {
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
        
        // Dismiss tutorial overlay if present (shown after app launch before WorkoutSelectionScreen)
        dismissTutorialIfPresent()
        
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
     * Best-effort dismissal of any tutorial overlay that might be covering
     * the workout UI.
     *
     * In the app, tutorial overlays always have a "Got it" button at the
     * bottom of a scrollable column. The algorithm here is:
     * 1) Look for a "Got it" button; if found, click it and return.
     * 2) If not found, check if there's any scrollable container.
     * 3) If scrollable, scroll to the bottom once (to reveal the button),
     *    then try again to find and click "Got it".
     * 4) Repeat this loop until the timeout is reached.
     */
    protected fun dismissTutorialIfPresent(maxWaitMs: Long = 2_000) {
        // Wait for "Got it" button to appear (tutorial overlay may take time to render)
        val button = device.wait(Until.findObject(By.text("Got it")), maxWaitMs)
        if (button != null) {
            try {
                button.click()
                device.waitForIdle(1_000)
                return
            } catch (_: Exception) {
                // Button found but not clickable, try scrolling
            }
        }

        // If button not found or not clickable, try scrolling to reveal it
        val scrollable = UiScrollable(UiSelector().scrollable(true))
        if (scrollable.exists()) {
            try {
                scrollable.scrollToEnd(5)
                device.waitForIdle(500)
                // Try again after scrolling
                val buttonAfterScroll = device.wait(Until.findObject(By.text("Got it")), 2_000)
                if (buttonAfterScroll != null) {
                    try {
                        buttonAfterScroll.click()
                        device.waitForIdle(1_000)
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
}


