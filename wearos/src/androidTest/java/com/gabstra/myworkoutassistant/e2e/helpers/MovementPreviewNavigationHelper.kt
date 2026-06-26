package com.gabstra.myworkoutassistant.e2e.helpers

import android.graphics.Rect
import android.os.SystemClock
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver

class MovementPreviewNavigationHelper(
    private val device: UiDevice,
    private val workoutDriver: WearWorkoutDriver,
) {
    private val movementPreviewSelector = By.desc(MovementPreviewContentDescription)

    fun waitForMovementPreview(maxSwipes: Int = MaxAnimationPageSwipes): Boolean {
        if (device.wait(Until.hasObject(movementPreviewSelector), E2ETestTimings.DEFAULT_TIMEOUT_MS)) {
            return true
        }

        repeat(maxSwipes) {
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            if (device.wait(Until.hasObject(movementPreviewSelector), E2ETestTimings.DEFAULT_TIMEOUT_MS)) {
                return true
            }
        }

        repeat(maxSwipes) {
            workoutDriver.navigateToPagerPage(Direction.RIGHT)
            if (device.wait(Until.hasObject(movementPreviewSelector), E2ETestTimings.DEFAULT_TIMEOUT_MS)) {
                return true
            }
        }

        return false
    }

    fun requireMovementPreviewVisibleAndStable(renderSettleMs: Long = MovementPreviewRenderSettleMs) {
        require(waitForMovementPreview()) {
            "Exercise movement preview did not appear from the workout flow"
        }

        SystemClock.sleep(renderSettleMs)

        val preview = device.findObject(movementPreviewSelector)
        require(preview != null) {
            "Exercise movement preview disappeared while rendering"
        }
        require(preview.visibleBounds.hasVisibleArea()) {
            "Exercise movement preview exists but is not visibly laid out. bounds=${preview.visibleBounds}"
        }
    }

    private fun Rect.hasVisibleArea(): Boolean = width() > 0 && height() > 0

    private companion object {
        const val MovementPreviewContentDescription = "Exercise movement preview"
        const val MaxAnimationPageSwipes = 4
        const val MovementPreviewRenderSettleMs = 4_000L
    }
}
