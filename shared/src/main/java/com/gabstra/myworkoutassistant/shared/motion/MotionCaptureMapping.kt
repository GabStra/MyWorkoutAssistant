package com.gabstra.myworkoutassistant.shared.motion

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.util.UUID

object MotionCaptureWorkoutCatalog {
    fun buildCandidates(workout: Workout): List<MotionCaptureExerciseCandidate> {
        val candidates = mutableListOf<MotionCaptureExerciseCandidate>()
        var order = 0
        workout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> {
                    candidates += MotionCaptureExerciseCandidate(
                        exerciseId = component.id,
                        exerciseName = component.name,
                        exerciseType = component.exerciseType,
                        supersetId = null,
                        executionOrder = order++
                    )
                }
                is Superset -> {
                    component.exercises.forEach { exercise ->
                        candidates += MotionCaptureExerciseCandidate(
                            exerciseId = exercise.id,
                            exerciseName = exercise.name,
                            exerciseType = exercise.exerciseType,
                            supersetId = component.id,
                            executionOrder = order++
                        )
                    }
                }
                else -> Unit
            }
        }
        return candidates
    }

    fun findCandidateByExerciseId(
        workout: Workout,
        exerciseId: UUID
    ): MotionCaptureExerciseCandidate? = buildCandidates(workout).firstOrNull { it.exerciseId == exerciseId }
}

object MotionCaptureLabelMapper {
    fun map(
        workoutState: WorkoutState,
        workout: Workout
    ): MotionCaptureLabel? = when (workoutState) {
        is WorkoutState.Preparing -> null
        is WorkoutState.Completed -> null
        is WorkoutState.Set -> {
            val candidate = MotionCaptureWorkoutCatalog.findCandidateByExerciseId(workout, workoutState.exerciseId)
            MotionCaptureLabel(
                kind = MotionCaptureLabelKind.EXERCISE,
                stateName = WorkoutState.Set::class.simpleName ?: "Set",
                exerciseId = workoutState.exerciseId,
                exerciseName = candidate?.exerciseName,
                setId = workoutState.set.id,
                setIndex = workoutState.setIndex,
                exerciseType = candidate?.exerciseType,
                supersetId = candidate?.supersetId,
                noRepExpected = candidate?.noRepExpected ?: false,
                isWarmupSet = workoutState.isWarmupSet,
                isCalibrationSet = workoutState.isCalibrationSet,
                isAutoRegulationSet = workoutState.isAutoRegulationWorkSet
            )
        }
        is WorkoutState.Rest -> {
            val candidate = workoutState.exerciseId?.let { MotionCaptureWorkoutCatalog.findCandidateByExerciseId(workout, it) }
            MotionCaptureLabel(
                kind = MotionCaptureLabelKind.REST,
                stateName = WorkoutState.Rest::class.simpleName ?: "Rest",
                exerciseId = workoutState.exerciseId,
                exerciseName = candidate?.exerciseName,
                setId = workoutState.set.id,
                exerciseType = candidate?.exerciseType,
                supersetId = candidate?.supersetId,
                noRepExpected = candidate?.noRepExpected ?: false,
                isIntraSetRest = workoutState.isIntraSetRest
            )
        }
        is WorkoutState.CalibrationLoadSelection -> null
        is WorkoutState.CalibrationRIRSelection -> null
        is WorkoutState.AutoRegulationRIRSelection -> null
    }
}
