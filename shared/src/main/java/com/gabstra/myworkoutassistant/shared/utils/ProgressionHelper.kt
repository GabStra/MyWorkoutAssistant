package com.gabstra.myworkoutassistant.shared.utils

import kotlin.math.ceil
import kotlin.math.ln

/**
 * Helper class that contains all the logic for suggesting progression options
 * in a strength training program based on exercise parameters.
 */
object ProgressionHelper {

    // Enum for Exercise Types
    enum class ExerciseCategory {
        STRENGTH,
        HYPERTROPHY,
        ENDURANCE;

        companion object {
            fun fromString(type: String): ExerciseCategory? {
                return values().find { it.name.equals(type, ignoreCase = true) }
            }
        }
    }

    // Enum for Actions
    enum class Action {
        INCREASE_REPETITIONS,
        INCREASE_WEIGHT,
        ADJUST_WEIGHT_AND_REPETITIONS
    }

    data class ExerciseParameters(
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val setsRange: IntRange,
        val fatigueFactor: Double
    )

    data class FatigueResult(
        val fatigue: Double,
        val volume: Double,
        val percentLoad: Double
    )

    data class ProgressionOption(
        val action: Action,
        val weight: Double,
        val reps: Int,
        val fatigue: Double,
        val percentLoad: Double
    )

    /**
     * Retrieves the exercise parameters based on the exercise type.
     */
    private fun getParametersByExerciseType(exerciseCategory: ExerciseCategory): ExerciseParameters {
        return when (exerciseCategory) {
            ExerciseCategory.STRENGTH -> ExerciseParameters(
                percentLoadRange = 85.0 to 100.0,
                repsRange = 1..5,
                setsRange = 3..6,
                fatigueFactor = 0.2
            )
            ExerciseCategory.HYPERTROPHY -> ExerciseParameters(
                percentLoadRange = 65.0 to 85.0,
                repsRange = 6..12,
                setsRange = 3..5,
                fatigueFactor = 0.1
            )
            ExerciseCategory.ENDURANCE -> ExerciseParameters(
                percentLoadRange = 50.0 to 65.0,
                repsRange = 12..20,
                setsRange = 2..4,
                fatigueFactor = 0.05
            )
        }
    }

    /**
     * Calculates the fatigue based on weight, repetitions, one-rep max, and fatigue factor.
     */
    private fun calculateFatigue(weight: Double, reps: Int, oneRepMax: Double, fatigueFactor: Double): FatigueResult {
        val volume = weight * reps
        val percentLoad = (weight / oneRepMax) * 100
        val fatigue = volume * (1 + fatigueFactor * ln(1 + (percentLoad * reps / 100)))
        return FatigueResult(fatigue, volume, percentLoad)
    }

    /**
     * Suggests the best progression option based on the current performance and exercise parameters.
     */
    fun suggestProgression(
        currentWeight: Double,
        currentReps: Int,
        oneRepMax: Double,
        weightIncrement: Double,
        exerciseCategory: ExerciseCategory
    ): ProgressionOption? {
        val params = getParametersByExerciseType(exerciseCategory)
        val (percentLoadRange, repsRange, _, fatigueFactor) = params

        // Calculate current fatigue and volume
        val currentFatigueResult = calculateFatigue(currentWeight, currentReps, oneRepMax, fatigueFactor)
        val currentVolume = currentFatigueResult.volume

        // Attempt to increase repetitions
        val increasedReps = currentReps + 1
        if (increasedReps in repsRange) {
            val fatigueResult = calculateFatigue(currentWeight, increasedReps, oneRepMax, fatigueFactor)

            val (minLoad, maxLoad) = percentLoadRange
            if (fatigueResult.volume > currentVolume && fatigueResult.percentLoad in minLoad..maxLoad) {
                return ProgressionOption(
                    action = Action.INCREASE_REPETITIONS,
                    weight = currentWeight,
                    reps = increasedReps,
                    fatigue = fatigueResult.fatigue,
                    percentLoad = fatigueResult.percentLoad
                )
            }
        }

        // If increasing repetitions is invalid, adjust weight and repetitions
        if (increasedReps > repsRange.last) {
            val adjustedOption = adjustWeightAndReps(
                currentVolume,
                oneRepMax,
                weightIncrement,
                repsRange,
                fatigueFactor,
                percentLoadRange
            )
            if (adjustedOption != null) {
                return adjustedOption
            } else {
                // Suggest increasing weight anyway
                val increasedWeight = currentWeight + weightIncrement
                val fatigueResult = calculateFatigue(increasedWeight, currentReps, oneRepMax, fatigueFactor)
                if (fatigueResult.volume > currentVolume) {
                    return ProgressionOption(
                        action = Action.INCREASE_WEIGHT,
                        weight = increasedWeight,
                        reps = currentReps,
                        fatigue = fatigueResult.fatigue,
                        percentLoad = fatigueResult.percentLoad
                    )
                }
            }
        }

        // Attempt to increase weight
        val increasedWeight = currentWeight + weightIncrement
        val fatigueResult = calculateFatigue(increasedWeight, currentReps, oneRepMax, fatigueFactor)
        if (fatigueResult.volume > currentVolume) {
            return ProgressionOption(
                action = Action.INCREASE_WEIGHT,
                weight = increasedWeight,
                reps = currentReps,
                fatigue = fatigueResult.fatigue,
                percentLoad = fatigueResult.percentLoad
            )
        }

        // If all else fails, return null
        return null
    }

    /**
     * Adjusts both weight and repetitions to find a progression that increases volume
     * while staying within recommended ranges.
     */
    private fun adjustWeightAndReps(
        currentVolume: Double,
        oneRepMax: Double,
        weightIncrement: Double,
        repsRange: IntRange,
        fatigueFactor: Double,
        percentLoadRange: Pair<Double, Double>
    ): ProgressionOption? {
        for (reps in repsRange) {
            val minimalWeight = ceil((currentVolume + weightIncrement) / reps / weightIncrement) * weightIncrement
            if (minimalWeight <= 0) continue

            val percentLoad = (minimalWeight / oneRepMax) * 100
            val (minLoad, maxLoad) = percentLoadRange
            if (percentLoad in minLoad..maxLoad) {
                val fatigueResult = calculateFatigue(minimalWeight, reps, oneRepMax, fatigueFactor)
                if (fatigueResult.volume > currentVolume) {
                    return ProgressionOption(
                        action = Action.ADJUST_WEIGHT_AND_REPETITIONS,
                        weight = minimalWeight,
                        reps = reps,
                        fatigue = fatigueResult.fatigue,
                        percentLoad = percentLoad
                    )
                }
            }
        }
        // No suitable option found
        return null
    }
}
