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
    }

    protected fun waitForText(text: String, timeoutMs: Long = defaultTimeoutMs): Boolean {
        return device.wait(Until.hasObject(By.text(text)), timeoutMs)
    }

    protected fun clickText(text: String) {
        val obj = device.findObject(By.text(text))
        require(obj != null) { "UI object with text '$text' not found" }
        obj.click()
    }

    protected fun maybeClickPermissionAllow(timeoutMs: Long = defaultTimeoutMs): Boolean {
        val allow = device.wait(
            Until.findObject(
                By.textStartsWith("Allow")
            ),
            timeoutMs
        )
        return if (allow != null) {
            allow.click()
            true
        } else {
            false
        }
    }

    protected fun drainPermissionDialogs(maxLoops: Int = 5) {
        repeat(maxLoops) {
            val clicked = maybeClickPermissionAllow(1_000)
            if (!clicked) return
        }
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
        val deadline = System.currentTimeMillis() + maxWaitMs

        while (System.currentTimeMillis() < deadline) {
            // 1) Try to find and click the "Got it" button directly.
            val button = device.findObject(By.text("Got it"))
            if (button != null) {
                button.click()
                device.waitForIdle(1_000)
                return
            }

            // 2) If no button yet, see if we have any scrollable container.
            val scrollable = UiScrollable(UiSelector().scrollable(true))
            if (scrollable.exists()) {
                // 3) Scroll to the bottom once to reveal the button.
                try {
                    scrollable.scrollToEnd(5)
                } catch (_: Exception) {
                    // Ignore scroll failures; we'll just break out on next loop.
                }
            } else {
                // Nothing scrollable and no button – nothing more we can do.
                return
            }
        }
    }
}


