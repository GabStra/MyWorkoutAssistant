package com.gabstra.myworkoutassistant

import android.app.NotificationManager
import android.content.Intent
import android.util.Log
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import java.util.UUID

internal object WearNotificationIntentHandler {
    private const val WORKOUT_ID = "WORKOUT_ID"
    private const val SCHEDULE_ID = "SCHEDULE_ID"

    fun handle(
        intent: Intent,
        notificationManager: NotificationManager,
        isWorkoutInProgress: Boolean,
        workoutStoreRepository: WorkoutStoreRepository,
        appViewModel: AppViewModel
    ) {
        if (!intent.hasExtra(WORKOUT_ID)) {
            return
        }

        val workoutId = intent.getStringExtra(WORKOUT_ID)
        val scheduleId = intent.getStringExtra(SCHEDULE_ID)
        notificationManager.cancel(scheduleId.hashCode())

        if (isWorkoutInProgress || workoutId.isNullOrBlank()) {
            return
        }

        val workoutUuid = runCatching { UUID.fromString(workoutId) }
            .onFailure {
                Log.e("WearNotificationIntentHandler", "Invalid workout id in notification", it)
            }
            .getOrNull()
            ?: return

        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.find { it.globalId == workoutUuid } ?: return
        appViewModel.triggerStartWorkout(workout.globalId)
    }
}
