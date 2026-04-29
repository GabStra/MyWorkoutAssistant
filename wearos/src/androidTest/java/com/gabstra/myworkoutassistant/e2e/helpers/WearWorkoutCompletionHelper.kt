package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings

object WearWorkoutCompletionHelper {
    fun completeWorkoutViaStateMutations(
        device: UiDevice,
        context: Context,
        maxSteps: Int,
        completionErrorMessage: String
    ) {
        repeat(maxSteps) {
            if (WearWorkoutStateMutationHelper.isWorkoutCompleted()) return

            if (
                WearWorkoutStateMutationHelper.completeCurrentSet(
                    device = device,
                    context = context,
                    timeoutMs = 20_000
                )
            ) {
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                return@repeat
            }

            if (
                WearWorkoutStateMutationHelper.skipCurrentRest(
                    device = device,
                    timeoutMs = 15_000
                )
            ) {
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                return@repeat
            }

            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        require(WearWorkoutStateMutationHelper.isWorkoutCompleted()) {
            completionErrorMessage
        }
    }
}
