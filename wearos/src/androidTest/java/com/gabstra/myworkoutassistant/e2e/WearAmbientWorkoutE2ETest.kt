package com.gabstra.myworkoutassistant.e2e

import android.app.NotificationManager
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import org.junit.Test

class WearAmbientWorkoutE2ETest : WearBaseE2ETest() {

    override fun prepareAppStateBeforeLaunch() {
        super.prepareAppStateBeforeLaunch()
        E2eRuntimePreferences.setAmbientWorkoutOverlayForced(context, true)
    }

    @Test
    fun activeWorkout_rendersAmbientOverlayAndKeepsOngoingNotification() {
        startWorkout("Test Workout")

        val overlayVisible = device.wait(
            Until.hasObject(By.desc("Ambient workout overlay")),
            defaultTimeoutMs
        )
        require(overlayVisible) { "Forced ambient workout overlay did not render." }

        val phaseVisible = device.wait(
            Until.hasObject(By.desc("Ambient workout phase: Set")),
            defaultTimeoutMs
        )
        require(phaseVisible) { "Ambient overlay did not report the active Set phase." }

        val exerciseVisible = device.wait(
            Until.hasObject(By.desc("Ambient workout exercise: Bench Press")),
            defaultTimeoutMs
        )
        require(exerciseVisible) {
            "Ambient overlay did not show the active exercise from the workout UI."
        }

        val notificationManager = context.getSystemService(NotificationManager::class.java)
        val ongoingWorkoutVisible = notificationManager.activeNotifications.any { statusBarNotification ->
            statusBarNotification.id == 1 &&
                statusBarNotification.notification.channelId == "workout_progress_channel"
        }
        require(ongoingWorkoutVisible) {
            "Workout ongoing activity notification was not active during the workout."
        }
    }
}
