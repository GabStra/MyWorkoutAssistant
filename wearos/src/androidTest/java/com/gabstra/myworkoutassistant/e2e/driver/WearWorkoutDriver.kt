package com.gabstra.myworkoutassistant.e2e.driver

import android.content.Context
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until

/**
 * Reusable UI driver for common workout E2E interactions.
 * Keeps interaction patterns in one place so tests remain scenario-focused.
 */
class WearWorkoutDriver(
    private val device: UiDevice,
    private val longPressByDesc: (String, Long) -> Unit
) {
    fun completeCurrentSet(timeoutMs: Long = 5_000) {
        device.pressBack()
        if (tryConfirmLongPressDialog(timeoutMs)) return

        // Some UI layers (e.g., inline editors/overlays) consume the first back press.
        device.pressBack()
        val confirmed = tryConfirmLongPressDialog(timeoutMs)
        require(confirmed) { "Timed out waiting for set confirmation dialog ('Done')" }
    }

    fun confirmLongPressDialog(timeoutMs: Long = 5_000) {
        device.waitForIdle(1_000)
        longPressByDesc("Done", timeoutMs)
        device.waitForIdle(1_000)
    }

    private fun tryConfirmLongPressDialog(timeoutMs: Long): Boolean {
        device.waitForIdle(500)
        val hasDone = device.wait(Until.hasObject(By.desc("Done")), timeoutMs)
        if (!hasDone) return false
        longPressByDesc("Done", timeoutMs)
        device.waitForIdle(500)
        return true
    }

    fun skipRest(timeoutMs: Long = 3_000) {
        device.pressBack()
        device.waitForIdle(200)
        device.pressBack()
        device.waitForIdle(500)

        val dialogAppeared = device.wait(Until.hasObject(By.text("Skip Rest")), timeoutMs)
        require(dialogAppeared) { "Skip Rest dialog did not appear" }
        longPressByDesc("Done", timeoutMs)
    }

    fun waitForWorkoutCompletion(timeoutMs: Long = 10_000) {
        val completedVisible = device.wait(Until.hasObject(By.text("Completed")), timeoutMs)
        require(completedVisible) { "Workout completion screen did not appear" }
    }

    /**
     * Completes a timed/endurance set:
     * - manual sets: Start -> short wait -> Stop
     * - auto-start sets: short passive wait
     * Then completes the set confirmation dialog.
     */
    fun completeTimedSet(timeoutMs: Long = 5_000) {
        val started = clickButtonWithRetry("Start", timeoutMs = 3_000, attempts = 4)
        if (started) {
            device.waitForIdle(2_000)
            device.waitForIdle(3_000)
            clickButtonWithRetry("Stop", timeoutMs = 3_000, attempts = 4)
        } else {
            device.waitForIdle(5_000)
        }

        completeCurrentSet(timeoutMs)
    }

    fun goHomeAndVerifySelection(timeoutMs: Long = 5_000) {
        val goHomeSelector = By.text("Go Home")

        val goHome = device.wait(Until.findObject(goHomeSelector), 1_000)
            ?: run {
                val scrollable = device.findObject(By.scrollable(true))
                if (scrollable != null) {
                    runCatching {
                        scrollable.scrollUntil(Direction.DOWN, Until.findObject(goHomeSelector))
                    }.getOrNull()
                } else {
                    null
                }
            }

        require(goHome != null) { "Go Home button not found after scrolling" }
        goHome.click()
        device.waitForIdle(1_000)

        val headerVisible = device.wait(
            Until.hasObject(By.text("My Workout Assistant")),
            timeoutMs
        )
        require(headerVisible) { "Did not return to WorkoutSelectionScreen after Go Home" }
    }

    fun waitForSyncedIds(
        context: Context,
        timeoutMs: Long,
        prefsName: String = "synced_workout_history_ids",
        key: String = "ids"
    ): Boolean {
        val prefs = context.getSharedPreferences(prefsName, Context.MODE_PRIVATE)
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            if (prefs.getStringSet(key, emptySet()).orEmpty().isNotEmpty()) {
                return true
            }
            device.waitForIdle(1_000)
        }

        return false
    }

    private fun waitForButtonByLabel(label: String, timeoutMs: Long = 2_000): UiObject2? {
        return device.wait(Until.findObject(By.desc(label)), timeoutMs)
            ?: device.wait(Until.findObject(By.text(label)), timeoutMs)
    }

    private fun clickButtonWithRetry(
        label: String,
        timeoutMs: Long = 2_000,
        attempts: Int = 3
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        repeat(attempts) {
            val remaining = deadline - System.currentTimeMillis()
            if (remaining <= 0L) {
                return false
            }

            val stepTimeout = if (remaining > 1_000L) 1_000L else remaining
            val button = waitForButtonByLabel(label, stepTimeout)
            if (button != null && clickBestEffort(button)) {
                device.waitForIdle(200)
                return true
            }
            device.waitForIdle(300)
        }
        return false
    }

    private fun clickBestEffort(target: UiObject2): Boolean {
        return try {
            val bounds = target.visibleBounds
            if (bounds.width() > 0 && bounds.height() > 0) {
                return device.click(bounds.centerX(), bounds.centerY())
            }

            if (target.isClickable) {
                target.click()
                return true
            }

            false
        } catch (_: StaleObjectException) {
            false
        }
    }
}
