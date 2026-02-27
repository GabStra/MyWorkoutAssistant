package com.gabstra.myworkoutassistant.shared.workout.ui

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.time.LocalDateTime

/**
 * Immutable snapshot of all UI-observable state for workout screens.
 * This aggregates multiple ViewModel properties into a single state object
 * that both mobile and WearOS UIs can consume.
 */
data class WorkoutScreenState(
    val workoutState: WorkoutState,
    val sessionPhase: WorkoutSessionPhase,
    val nextWorkoutState: WorkoutState?,
    val selectedWorkout: Workout,
    val isPaused: Boolean,
    val hasWorkoutRecord: Boolean,
    val isResuming: Boolean,
    val isRefreshing: Boolean,
    val isCustomDialogOpen: Boolean,
    val enableWorkoutNotificationFlow: String?,
    val userAge: Int,
    val measuredMaxHeartRate: Int?,
    val restingHeartRate: Int?,
    val startWorkoutTime: LocalDateTime?,
    val enableDimming: Boolean,
    val keepScreenOn: Boolean,
    val currentScreenDimmingState: Boolean,
    // WearOS-specific display modes (default to 0 for mobile)
    val headerDisplayMode: Int = 0,
    val hrDisplayMode: Int = 0,
    val isRestTimerPageVisible: Boolean = true,
) {
    companion object {
        /**
         * Creates an initial empty state.
         */
        fun initial(): WorkoutScreenState {
            return WorkoutScreenState(
                workoutState = WorkoutState.Preparing(dataLoaded = false),
                sessionPhase = WorkoutSessionPhase.PREPARING,
                nextWorkoutState = null,
                selectedWorkout = Workout(
                    id = java.util.UUID.randomUUID(),
                    name = "",
                    description = "",
                    workoutComponents = emptyList(),
                    order = 0,
                    enabled = true,
                    usePolarDevice = false,
                    creationDate = java.time.LocalDate.now(),
                    type = 0,
                    globalId = java.util.UUID.randomUUID()
                ),
                isPaused = false,
                hasWorkoutRecord = false,
                isResuming = false,
                isRefreshing = false,
                isCustomDialogOpen = false,
                enableWorkoutNotificationFlow = null,
                userAge = 0,
                measuredMaxHeartRate = null,
                restingHeartRate = null,
                startWorkoutTime = null,
                enableDimming = false,
                keepScreenOn = false,
                currentScreenDimmingState = false,
                headerDisplayMode = 0,
                hrDisplayMode = 0,
                isRestTimerPageVisible = true,
            )
        }
    }
}


