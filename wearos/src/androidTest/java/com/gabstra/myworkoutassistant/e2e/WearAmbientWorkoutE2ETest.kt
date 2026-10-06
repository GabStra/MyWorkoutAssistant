package com.gabstra.myworkoutassistant.e2e

import android.app.NotificationManager
import org.junit.Test

class WearAmbientWorkoutE2ETest : WearBaseE2ETest() {

    @Test
    fun activeWorkout_keepsOngoingNotification() {
        startWorkout("Test Workout")

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
