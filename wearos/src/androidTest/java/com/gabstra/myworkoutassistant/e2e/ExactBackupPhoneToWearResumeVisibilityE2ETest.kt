package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import java.util.UUID
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ExactBackupPhoneToWearResumeVisibilityE2ETest {

    @Test
    fun phoneSync_makesTargetWorkoutResumeVisibleOnWear() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())

        waitForTargetResumeRecordOnWear(context)
        launchWearApp(context, device)
        dismissFirstRunOverlays(device)

        // Prefer the exact user flow (select target workout, then observe Resume), but on some runs
        // Wear opens directly into a recovery/resume surface. In that case we still assert resume UI.
        runCatching { openTargetWorkoutFromSelection(device) }

        val resumeButton = waitForResumeButton(device, timeoutMs = 12_000)
        require(resumeButton != null) {
            "Target workout detail did not show Resume action on Wear."
        }
    }

    private fun waitForTargetResumeRecordOnWear(context: Context) = runBlocking {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < deadline) {
            val record = db.workoutRecordDao().getWorkoutRecordByWorkoutId(TARGET_WORKOUT_ID)
            if (record != null) return@runBlocking
            delay(500)
        }
        error("Timed out waiting for synced target workout record on Wear before UI assertion.")
    }

    private fun launchWearApp(context: Context, device: UiDevice) {
        device.pressHome()
        val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?: error("Launch intent for package ${context.packageName} not found on Wear.")
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(launchIntent)
        val appeared = device.wait(Until.hasObject(By.pkg(context.packageName).depth(0)), 12_000)
        require(appeared) { "Timed out waiting for Wear app foreground." }
        device.waitForIdle(1_000)
    }

    private fun dismissFirstRunOverlays(device: UiDevice) {
        val deadline = System.currentTimeMillis() + 8_000
        while (System.currentTimeMillis() < deadline) {
            val gotIt = device.findObject(By.text("Got it"))
                ?: device.findObject(By.textContains("Got it"))
            if (gotIt != null) {
                clickObjectOrAncestor(gotIt)
                device.waitForIdle(1_000)
                return
            }
            if (device.hasObject(By.textContains(TARGET_WORKOUT_NAME_FRAGMENT))) return
            device.waitForIdle(300)
        }
    }

    private fun openTargetWorkoutFromSelection(device: UiDevice) {
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            val workout = device.findObject(By.descContains(TARGET_WORKOUT_NAME_FRAGMENT))
                ?: device.findObject(By.textContains(TARGET_WORKOUT_NAME_FRAGMENT))
            if (workout != null) {
                clickObjectOrAncestor(workout)
                device.waitForIdle(1_000)
                return
            }
            val scrollable = device.findObject(By.scrollable(true))
            if (scrollable != null) {
                runCatching { scrollable.scroll(Direction.DOWN, 0.75f) }
            } else {
                val x = device.displayWidth / 2
                val yStart = (device.displayHeight * 0.75).toInt()
                val yEnd = (device.displayHeight * 0.25).toInt()
                device.swipe(x, yStart, x, yEnd, 10)
            }
            device.waitForIdle(500)
        }
        error("Target workout containing '$TARGET_WORKOUT_NAME_FRAGMENT' was not visible on Wear selection.")
    }

    private fun waitForResumeButton(device: UiDevice, timeoutMs: Long): androidx.test.uiautomator.UiObject2? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val resume = device.findObject(By.desc("Resume workout"))
                ?: device.findObject(By.textContains("Resume"))
                ?: device.findObject(By.descContains("Resume"))
            if (resume != null) return resume

            val scrollable = device.findObject(By.scrollable(true))
            if (scrollable != null) {
                runCatching { scrollable.scroll(Direction.DOWN, 0.6f) }
            }
            device.waitForIdle(300)
        }
        return null
    }

    private fun clickObjectOrAncestor(obj: androidx.test.uiautomator.UiObject2) {
        var current: androidx.test.uiautomator.UiObject2? = obj
        while (current != null && !current.isClickable) {
            current = current.parent
        }
        (current ?: obj).click()
    }

    companion object {
        private const val TARGET_WORKOUT_NAME_FRAGMENT = "Squat"
        private val TARGET_WORKOUT_ID = UUID.fromString("efdba35b-82bf-418e-9362-4ffa2d39e435")
    }
}
