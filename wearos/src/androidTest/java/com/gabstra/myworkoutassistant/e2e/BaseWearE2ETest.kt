package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
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
    protected val permissionDialogPackages: Set<String> by lazy { resolvePermissionDialogPackages() }

    @Before
    fun baseSetUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        context = ApplicationProvider.getApplicationContext()
        seedWorkoutStore()
        launchAppFromHome()
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

        // On cold starts a permission dialog may cover the UI. Drain it before moving on.
        drainPermissionDialogs()

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
     * Checks if a permission dialog is currently visible on screen.
     * Uses multiple heuristics to detect system permission dialogs.
     */
    protected fun isPermissionDialogPresent(): Boolean {
        // Check for resolved permission controller packages from the device/emulator
        permissionDialogPackages.forEach { pkg ->
            val dialog = device.findObject(By.pkg(pkg))
            if (dialog != null) {
                Log.d(
                    TAG,
                    "Permission dialog detected via package $pkg (class=${dialog.className})"
                )
                return true
            }
        }

        // Check for common permission dialog button resource IDs
        val positiveButtonIds = listOf(
            "android:id/button1",
            "com.android.permissioncontroller:id/permission_allow_button",
            "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
            "com.android.permissioncontroller:id/permission_allow_one_time_button",
            "com.android.permissioncontroller:id/permission_allow_always_button"
        )

        positiveButtonIds.forEach { resId ->
            val button = device.findObject(By.res(resId))
            if (button != null) {
                Log.d(TAG, "Permission dialog detected via resource id $resId")
                return true
            }
        }

        // Check for permission-related text buttons
        val allowByText = device.findObject(
            UiSelector().textMatches(POSITIVE_PERMISSION_REGEX)
        )
        if (allowByText.exists()) {
            Log.d(TAG, "Permission dialog detected via text ${allowByText.text}")
            return true
        }

        // Some Wear OS permission dialogs render chips instead of classic buttons.
        PERMISSION_DIALOG_TEXT_CUES.forEach { cue ->
            val chip = device.findObject(By.textContains(cue))
            if (chip != null) {
                Log.d(TAG, "Permission dialog detected via chip text containing '$cue'")
                return true
            }
        }

        return false
    }

    /**
     * Waits for a permission dialog to appear, then clicks the allow button.
     * Returns true if a dialog was found and dismissed, false if no dialog appeared.
     */
    protected fun waitForAndDismissPermissionDialog(timeoutMs: Long = 5_000): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        
        // Poll for dialog appearance (checking multiple conditions)
        while (SystemClock.elapsedRealtime() < deadline) {
            if (isPermissionDialogPresent()) {
                // Dialog appeared, now try to click the allow button
                return maybeClickPermissionAllow(3_000)
            }
            SystemClock.sleep(250)
        }

        // No dialog appeared within timeout
        return false
    }

    protected fun maybeClickPermissionAllow(timeoutMs: Long = defaultTimeoutMs): Boolean {
        val allowDeadline = SystemClock.elapsedRealtime() + timeoutMs
        val positiveButtonIds = listOf(
            "android:id/button1",
            "com.android.permissioncontroller:id/permission_allow_button",
            "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
            "com.android.permissioncontroller:id/permission_allow_one_time_button",
            "com.android.permissioncontroller:id/permission_allow_always_button"
        )

        while (SystemClock.elapsedRealtime() < allowDeadline) {
            positiveButtonIds.forEach { resId ->
                val allowButton = device.findObject(By.res(resId))
                if (allowButton != null) {
                    try {
                        allowButton.click()
                        Log.d(TAG, "Clicked permission allow button with resource id $resId")
                        device.waitForIdle(500)
                        return true
                    } catch (_: Exception) {
                        Log.d(TAG, "Permission allow button $resId not clickable yet, retrying")
                        // Button exists but not clickable yet; continue trying
                    }
                }
            }

            val allowByText = device.findObject(
                UiSelector().textMatches(POSITIVE_PERMISSION_REGEX)
            )
            if (allowByText.exists()) {
                try {
                    allowByText.click()
                    Log.d(TAG, "Clicked permission allow button via visible text")
                    device.waitForIdle(500)
                    return true
                } catch (_: Exception) {
                    Log.d(TAG, "Permission allow button text present but not clickable, retrying")
                    // Button is present but not clickable yet; retry after a short delay.
                }
            } else {
                val scrollable = UiScrollable(UiSelector().scrollable(true))
                if (scrollable.exists()) {
                    try {
                        scrollable.scrollForward()
                    } catch (_: Exception) {
                        // Ignore scrolling failures; we'll retry until timeout.
                    }
                }
            }

            SystemClock.sleep(250)
        }

        return false
    }

    /**
     * Drains all permission dialogs that may appear.
     * Waits for each dialog to appear before attempting to dismiss it.
     * Continues until no more dialogs appear or maxLoops is reached.
     */
    protected fun drainPermissionDialogs(maxLoops: Int = 5, waitTimeoutMs: Long = 5_000) {
        repeat(maxLoops) {
            val dismissed = waitForAndDismissPermissionDialog(waitTimeoutMs)
            if (!dismissed) {
                // No dialog appeared, we're done
                return
            }
            // Dialog was dismissed, wait a moment before checking for another
            SystemClock.sleep(500)
        }
    }

    /**
     * Waits for permission dialogs to be cleared and/or expected content to appear.
     * This is useful when you want to proceed as soon as either:
     * 1. All permission dialogs are cleared, OR
     * 2. The expected content appears (which may happen even if dialogs are still present)
     * 
     * @param expectedContentSelector The selector for the expected content
     * @param timeoutMs Maximum time to wait
     * @return true if expected content appeared, false if timeout
     */
    protected fun waitForDialogsClearedOrContentAppears(
        expectedContentSelector: BySelector,
        timeoutMs: Long = defaultTimeoutMs
    ): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        
        while (SystemClock.elapsedRealtime() < deadline) {
            // First check if expected content is already visible
            val contentObject = device.findObject(expectedContentSelector)
            if (contentObject != null) {
                return true
            }

            // Check if a permission dialog is present
            if (isPermissionDialogPresent()) {
                Log.d(TAG, "Permission dialog detected while waiting for content; attempting dismissal")
                // Dialog is present, try to dismiss it
                val dismissed = maybeClickPermissionAllow(1_000)
                if (dismissed) {
                    Log.d(TAG, "Permission dialog dismissed while waiting for content")
                    device.waitForIdle(500)
                    // After dismissing, check again for content
                    val contentAfterDismiss = device.findObject(expectedContentSelector)
                    if (contentAfterDismiss != null) {
                        return true
                    }
                }
            } else {
                // No dialog present, check if content appeared
                val contentObject = device.findObject(expectedContentSelector)
                if (contentObject != null) {
                    return true
                }
            }

            SystemClock.sleep(250)
        }

        // Timeout reached, check one final time for content
        val finalContent = device.findObject(expectedContentSelector)
        return finalContent != null
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
    protected fun dismissTutorialIfPresent(maxWaitMs: Long = 8_000) {
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

    private fun resolvePermissionDialogPackages(): Set<String> {
        val resolved = LinkedHashSet<String>()
        val runtimePackage = try {
            val method = context.packageManager::class.java
                .getMethod("getPermissionControllerPackageName")
            method.invoke(context.packageManager) as? String
        } catch (_: Exception) {
            null
        }
        if (!runtimePackage.isNullOrEmpty()) {
            resolved += runtimePackage
            Log.d(TAG, "Detected platform permission controller package $runtimePackage")
        }
        resolved += PERMISSION_DIALOG_PACKAGES
        return resolved
    }
}

private const val POSITIVE_PERMISSION_REGEX =
    "(?i)^(allow|allow only this time|allow while using app|allow while using the app|while using the app|while app in use|while in use|only this time|yes)$"
private val PERMISSION_DIALOG_PACKAGES = listOf(
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller"
)
private val PERMISSION_DIALOG_TEXT_CUES = listOf(
    "Allow",
    "While using app",
    "Only this time",
    "Precise location",
    "Approximate location"
)

private const val TAG = "BaseWearE2ETest"


