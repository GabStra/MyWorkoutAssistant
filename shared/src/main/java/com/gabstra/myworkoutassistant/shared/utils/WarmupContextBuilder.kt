package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

object WarmupContextBuilder {
    fun build(
        exercise: Exercise,
        priorExercises: List<Exercise>,
        isSupersetFollowUp: Boolean
    ): WarmupContext {
        val isFirstExercise = priorExercises.isEmpty()
        val currentMuscles = getExerciseMuscles(exercise)
        val priorMuscles = priorExercises.flatMap { getExerciseMuscles(it) }.toSet()

        val overlapRatio = if (currentMuscles.isEmpty() || priorMuscles.isEmpty()) {
            0.0
        } else {
            currentMuscles.intersect(priorMuscles).size.toDouble() / currentMuscles.size.toDouble()
        }

        val previousExercise = priorExercises.lastOrNull()
        val previousExerciseSameEquipment = previousExercise != null &&
            previousExercise.exerciseType == exercise.exerciseType &&
            previousExercise.equipmentId != null &&
            previousExercise.equipmentId == exercise.equipmentId

        return WarmupContext(
            isFirstExerciseInWorkout = isFirstExercise,
            muscleOverlapRatio = overlapRatio,
            previousExerciseSameEquipment = previousExerciseSameEquipment,
            isSupersetFollowUp = isSupersetFollowUp
        )
    }

    private fun getExerciseMuscles(exercise: Exercise): Set<MuscleGroup> {
        val primary = exercise.muscleGroups ?: emptySet()
        val secondary = exercise.secondaryMuscleGroups ?: emptySet()
        if (primary.isEmpty() && secondary.isEmpty()) return emptySet()
        return primary + secondary
    }
}
