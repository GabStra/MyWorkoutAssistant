package com.gabstra.myworkoutassistant.e2e.driver

import android.content.Context
import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import androidx.work.WorkInfo
import androidx.work.WorkManager
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking

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
                "ALLOW",
                "While using the app",
                "Allow all the time",
                "Only this time"
            ) || clickIfPresent(
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
        val workManager = WorkManager.getInstance(context)
        val existingWorkIds = runBlocking {
            workManager.getWorkInfosForUniqueWorkFlow(MOBILE_SYNC_UNIQUE_WORK_NAME)
                .first()
                .map { it.id }
                .toSet()
        }

        val menuButton = device.wait(Until.findObject(By.desc("Menu")), timeoutMs)
            ?: error("Menu button not found on phone app")
        clickWithRetry { menuButton.click() }
        device.waitForIdle(800)

        val syncMenuItem = device.wait(Until.findObject(By.text("Sync with Watch")), timeoutMs)
            ?: device.wait(Until.findObject(By.textContains("Sync with Watch")), timeoutMs)
            ?: error("'Sync with Watch' menu item not found")
        clickWithRetry { syncMenuItem.click() }
        device.waitForIdle(1_000)

        waitForMobileSyncWorkerCompletion(
            workManager = workManager,
            existingWorkIds = existingWorkIds,
            timeoutMs = timeoutMs
        )
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
                // Avoid tapping non-clickable labels (can trigger unintended navigations in Settings)
                // and limit generic "Allow/ALLOW" taps to permission controller dialogs.
                if (!obj.isClickable) {
                    return@forEach
                }
                val ownerPackage = obj.applicationPackage?.toString().orEmpty()
                if (
                    (text == "Allow" || text == "ALLOW") &&
                    ownerPackage != "com.android.permissioncontroller" &&
                    ownerPackage != "com.google.android.permissioncontroller"
                ) {
                    return@forEach
                }
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

    private fun waitForMobileSyncWorkerCompletion(
        workManager: WorkManager,
        existingWorkIds: Set<java.util.UUID>,
        timeoutMs: Long
    ) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var trackedWorkInfo: WorkInfo? = null

        while (System.currentTimeMillis() < deadline) {
            val workInfos = runBlocking {
                workManager.getWorkInfosForUniqueWorkFlow(MOBILE_SYNC_UNIQUE_WORK_NAME).first()
            }
            val candidate = trackedWorkInfo?.let { tracked ->
                workInfos.firstOrNull { it.id == tracked.id }
            } ?: workInfos.firstOrNull { it.id !in existingWorkIds }
                ?: workInfos.firstOrNull { !it.state.isFinished }

            if (candidate != null) {
                trackedWorkInfo = candidate
                when (candidate.state) {
                    WorkInfo.State.SUCCEEDED -> return
                    WorkInfo.State.FAILED -> error("Mobile sync worker failed after tapping 'Sync with Watch'.")
                    WorkInfo.State.CANCELLED -> error("Mobile sync worker was cancelled after tapping 'Sync with Watch'.")
                    else -> Unit
                }
            }

            device.waitForIdle(250)
        }

        error(
            "Timed out waiting for mobile sync worker completion after tapping 'Sync with Watch'. " +
                "Last state=${trackedWorkInfo?.state ?: "not-started"}"
        )
    }

    companion object {
        private const val MOBILE_SYNC_UNIQUE_WORK_NAME = "mobile_sync_to_watch"
    }
}
