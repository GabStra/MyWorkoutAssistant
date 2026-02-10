package com.gabstra.myworkoutassistant.e2e.driver

import android.content.Context
import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until

/**
 * Reusable phone-side driver for cross-device E2E preparation.
 */
class PhoneAppDriver(
    private val device: UiDevice,
    private val context: Context
) {
    private val defaultTimeoutMs = 8_000L

    fun launchAppFromHome() {
        device.pressHome()
        val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?: error("Launch intent for package ${context.packageName} not found")
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(launchIntent)

        val appeared = device.wait(Until.hasObject(By.pkg(context.packageName).depth(0)), defaultTimeoutMs)
        require(appeared) { "Timed out waiting for app (${context.packageName}) to appear" }
        device.waitForIdle(1_500)
    }

    /**
     * Handles startup permission dialogs that can block app interaction.
     * We prefer allowing Downloads access to avoid blocking sync-related flows.
     */
    fun dismissStartupPermissionDialogs(timeoutMs: Long = 12_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val clicked = clickIfPresent(
                "Not now",
                "NOT NOW",
                "Allow",
                "ALLOW",
                "While using the app",
                "Allow all the time",
                "Only this time"
            ) || clickIfPresent(
                "Continue",
                "CONTINUE",
                "OK"
            )

            // No actionable permission button present; stop trying.
            if (!clicked) {
                break
            }
            device.waitForIdle(500)
        }
    }

    fun syncWithWatchFromMenu(timeoutMs: Long = 12_000) {
        val menuButton = device.wait(Until.findObject(By.desc("Menu")), timeoutMs)
            ?: error("Menu button not found on phone app")
        clickWithRetry { menuButton.click() }
        device.waitForIdle(800)

        val syncMenuItem = device.wait(Until.findObject(By.text("Sync with Watch")), timeoutMs)
            ?: device.wait(Until.findObject(By.textContains("Sync with Watch")), timeoutMs)
            ?: error("'Sync with Watch' menu item not found")
        clickWithRetry { syncMenuItem.click() }
        device.waitForIdle(1_000)

        val syncStarted = device.wait(Until.hasObject(By.text("Syncing...")), timeoutMs)
        require(syncStarted) {
            "Expected Syncing overlay after tapping 'Sync with Watch', but it did not appear."
        }

        val syncSettled = device.wait(Until.gone(By.text("Syncing...")), timeoutMs)
        require(syncSettled) {
            "Syncing overlay did not dismiss within timeout after tapping 'Sync with Watch'."
        }

        device.waitForIdle(1_000)
    }

    fun grantRuntimePermissions(vararg permissions: String) {
        val inst = InstrumentationRegistry.getInstrumentation()
        val pkg = inst.targetContext.packageName
        val ua = inst.uiAutomation
        permissions.forEach { permission ->
            runCatching { ua.grantRuntimePermission(pkg, permission) }
        }
    }

    private fun clickIfPresent(vararg texts: String): Boolean {
        texts.forEach { text ->
            val obj = device.wait(Until.findObject(By.text(text)), 400)
                ?: device.wait(Until.findObject(By.textContains(text)), 400)
            if (obj != null) {
                clickWithRetry { obj.click() }
                return true
            }
        }
        return false
    }

    private fun clickWithRetry(maxAttempts: Int = 3, action: () -> Unit) {
        repeat(maxAttempts) { attempt ->
            try {
                action()
                return
            } catch (e: StaleObjectException) {
                if (attempt == maxAttempts - 1) {
                    throw e
                }
                device.waitForIdle(250)
            }
        }
    }
}
