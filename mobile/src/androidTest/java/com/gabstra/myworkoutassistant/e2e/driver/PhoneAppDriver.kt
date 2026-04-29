package com.gabstra.myworkoutassistant.e2e.driver

import android.content.Context
import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
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

    fun waitForAppForeground(timeoutMs: Long = defaultTimeoutMs): Boolean {
        return device.wait(Until.hasObject(By.pkg(context.packageName).depth(0)), timeoutMs)
    }

    fun waitForForegroundText(text: String, timeoutMs: Long = defaultTimeoutMs): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (device.hasObject(By.pkg(context.packageName).depth(0)) && device.hasObject(By.text(text))) {
                return true
            }
            device.waitForIdle(250)
        }
        return false
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
            workManager.getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME)
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

    fun restoreBackupThroughFilePicker(
        backupFileName: String,
        backupFileNamePrefix: String,
        appPackageForBackupPath: String = context.packageName
    ) {
        val chooseFile = device.wait(Until.findObject(By.text("Choose file")), 10_000)
            ?: device.wait(Until.findObject(By.textContains("Choose file")), 5_000)
            ?: error("Restore backup dialog with 'Choose file' action did not appear.")
        chooseFile.click()
        device.waitForIdle(1_000)

        clickIfPresent("Allow", "ALLOW", "While using the app")
        clickIfPresent("Allow access", "Continue")

        openPickerRootsIfAvailable()
        // Deterministic fallback for this emulator image: Downloads row in roots drawer.
        // Row bounds observed from picker XML: [0,357][735,504].
        device.click(367, 430)
        device.waitForIdle(500)
        openPickerLocationIfPresent("sdk_gphone64_x86_64")
        openPickerLocationIfPresent("SDCARD")
        openPickerLocationIfPresent("Recent")
        openPickerLocationIfPresent("Downloads")
        openPickerLocationIfPresent("Internal storage")
        openPickerLocationIfPresent("Download")
        openPickerPathIfPresent("Android", "data", appPackageForBackupPath, "files")
        device.waitForIdle(700)

        val backupFile = findBackupFileInPicker(
            backupFileName = backupFileName,
            backupFileNamePrefix = backupFileNamePrefix,
            timeoutMs = 20_000
        ) ?: searchBackupFileInPicker(
            backupFileName = backupFileName,
            backupFileNamePrefix = backupFileNamePrefix
        ) ?: error("Could not locate '$backupFileName' in restore file picker.")
        backupFile.click()
        device.waitForIdle(1_500)

        device.findObject(By.text("Open"))?.click()
        device.findObject(By.text("Allow"))?.click()
        device.waitForIdle(1_000)
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
                val ownerPackage = obj.applicationPackage.orEmpty()
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

    private fun openPickerRootsIfAvailable() {
        device.findObject(By.descContains("Show roots"))?.click()
        device.findObject(By.descContains("Navigation"))?.click()
        device.waitForIdle(400)
    }

    private fun openPickerLocationIfPresent(label: String) {
        val entry = device.findObject(By.text(label))
            ?: device.findObject(By.textContains(label))
            ?: return
        clickObjectOrAncestor(entry)
        device.waitForIdle(400)
    }

    private fun openPickerPathIfPresent(vararg segments: String) {
        segments.forEach { segment ->
            val node = findNodeWithScroll(label = segment, timeoutMs = 2_500) ?: return
            clickObjectOrAncestor(node)
            device.waitForIdle(350)
        }
    }

    private fun findNodeWithScroll(label: String, timeoutMs: Long): UiObject2? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val node = device.findObject(By.text(label))
                ?: device.findObject(By.textContains(label))
            if (node != null) return node

            val scrollable = device.findObject(By.scrollable(true))
            if (scrollable != null) {
                runCatching { scrollable.scroll(androidx.test.uiautomator.Direction.DOWN, 0.8f) }
            } else {
                val x = device.displayWidth / 2
                val startY = (device.displayHeight * 0.75).toInt()
                val endY = (device.displayHeight * 0.25).toInt()
                device.swipe(x, startY, x, endY, 10)
            }
            device.waitForIdle(250)
        }
        return null
    }

    private fun findBackupFileInPicker(
        backupFileName: String,
        backupFileNamePrefix: String,
        timeoutMs: Long
    ): UiObject2? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val file = device.findObject(By.text(backupFileName))
                ?: device.findObject(By.textContains(backupFileNamePrefix))
            if (file != null) return file

            val scrollable = device.findObject(By.scrollable(true))
            if (scrollable != null) {
                runCatching { scrollable.scroll(androidx.test.uiautomator.Direction.DOWN, 0.8f) }
            } else {
                val x = device.displayWidth / 2
                val startY = (device.displayHeight * 0.75).toInt()
                val endY = (device.displayHeight * 0.25).toInt()
                device.swipe(x, startY, x, endY, 12)
            }
            device.waitForIdle(300)
        }
        return null
    }

    private fun searchBackupFileInPicker(
        backupFileName: String,
        backupFileNamePrefix: String
    ): UiObject2? {
        val searchButton = device.findObject(By.descContains("Search"))
            ?: device.findObject(By.text("Search"))
            ?: device.findObject(By.textContains("Search"))
            ?: return null
        searchButton.click()
        device.waitForIdle(500)

        val searchField = device.findObject(By.clazz("android.widget.EditText"))
            ?: device.findObject(By.textContains("Search"))
            ?: return null
        searchField.click()
        searchField.text = backupFileName
        device.waitForIdle(1_000)

        return device.wait(Until.findObject(By.text(backupFileName)), 6_000)
            ?: device.wait(Until.findObject(By.textContains(backupFileNamePrefix)), 6_000)
    }

    private fun clickObjectOrAncestor(obj: UiObject2) {
        var current: UiObject2? = obj
        while (current != null && !current.isClickable) {
            current = current.parent
        }
        (current ?: obj).click()
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
                workManager.getWorkInfosForUniqueWorkFlow(MobileSyncToWatchWorker.UNIQUE_WORK_NAME).first()
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

}
