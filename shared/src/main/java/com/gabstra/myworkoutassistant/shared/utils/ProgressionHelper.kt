package com.gabstra.myworkoutassistant.shared.utils

import kotlinx.coroutines.*
import kotlin.math.ceil
import kotlin.math.ln

object ProgressionHelper {
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

    data class ExerciseParameters(
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val setsRange: IntRange,
        val fatigueFactor: Double
    )
}

object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val fatigue: Double,
        val volume: Double,
        val percentLoad: Double
    )

    data class DistributedWorkout(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val totalFatigue: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int
    )

    data class WorkoutParameters(
        val numberOfSets: Int,
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val weightIncrement: Double,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val fatigueFactor: Double
    )

    suspend fun distributeVolume(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        exerciseCategory: ProgressionHelper.ExerciseCategory,
        weightIncrement: Double
    ): DistributedWorkout {
        val params = getParametersByExerciseType(exerciseCategory)

        // Create base parameters
        val baseParams = WorkoutParameters(
            numberOfSets = numberOfSets,
            targetTotalVolume = targetTotalVolume,
            oneRepMax = oneRepMax,
            weightIncrement = weightIncrement,
            percentLoadRange = params.percentLoadRange,
            repsRange = params.repsRange,
            fatigueFactor = params.fatigueFactor
        )

        // Try with original parameters first
        findSolution(baseParams)?.let { return it }

        // If no solution found, try with increased reps only
        val increasedRepsSolution = findSolutionWithIncreasedReps(baseParams)
        return increasedRepsSolution ?: throw IllegalStateException("No solution found with any parameter adjustment")
    }

    private suspend fun findSolutionWithIncreasedReps(baseParams: WorkoutParameters): DistributedWorkout? {
        var currentMaxReps = baseParams.repsRange.last + 1
        val maxPossibleReps = 30 // Upper limit for reps

        while (currentMaxReps <= maxPossibleReps) {
            val newRepsRange = baseParams.repsRange.first..currentMaxReps
            findSolution(baseParams.copy(repsRange = newRepsRange))?.let { return it }
            currentMaxReps++
        }
        return null
    }

    private suspend fun findSolution(params: WorkoutParameters): DistributedWorkout? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        // Find valid combination of sets
        val validSets = findValidSetCombination(
            possibleSets = possibleSets,
            remainingSets = params.numberOfSets,
            remainingVolume = params.targetTotalVolume,
            currentSets = emptyList(),
            maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)
        ) ?: return null

        return DistributedWorkout(
            sets = validSets,
            totalVolume = validSets.sumOf { it.volume },
            totalFatigue = validSets.sumOf { it.fatigue },
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSets.maxOf { it.reps }
        )
    }

    private suspend fun generatePossibleSets(params: WorkoutParameters): List<ExerciseSet> = coroutineScope {
        val minWeight = ceil((params.oneRepMax * (params.percentLoadRange.first / 100)) / params.weightIncrement) * params.weightIncrement
        val maxWeight = (params.oneRepMax * (params.percentLoadRange.second / 100)) / params.weightIncrement * params.weightIncrement

        val weightRange = generateSequence(minWeight) { it + params.weightIncrement }
            .takeWhile { it <= maxWeight }
            .toList()

        val setsDeferred = weightRange.map { weight ->
            async(Dispatchers.Default) {
                params.repsRange.map { reps ->
                    createSet(
                        weight = weight,
                        reps = reps,
                        oneRepMax = params.oneRepMax,
                        fatigueFactor = params.fatigueFactor
                    )
                }
            }
        }

        val sets = setsDeferred.awaitAll().flatten()

        // Filter out sets that exceed the percentage load range
        val filteredSets = sets.filter {
            it.percentLoad >= params.percentLoadRange.first &&
                    it.percentLoad <= params.percentLoadRange.second
        }

        // Sort sets by weight and then by fatigue
        filteredSets.sortedWith(compareBy<ExerciseSet> { it.weight }.thenBy { it.fatigue })
    }

    private fun findValidSetCombination(
        possibleSets: List<ExerciseSet>,
        remainingSets: Int,
        remainingVolume: Double,
        currentSets: List<ExerciseSet>,
        previousFatigue: Double = Double.MAX_VALUE,
        maxWeight: Double
    ): List<ExerciseSet>? {
        if (remainingSets == 0) {
            return if (currentSets.sumOf { it.volume } >= remainingVolume) currentSets else null
        }

        val targetVolumePerSet = remainingVolume / remainingSets

        for (set in possibleSets) {
            if (set.weight <= maxWeight &&
                set.volume >= targetVolumePerSet * 0.95 &&
                set.fatigue <= previousFatigue) {

                val result = findValidSetCombination(
                    possibleSets = possibleSets,
                    remainingSets = remainingSets - 1,
                    remainingVolume = remainingVolume - set.volume,
                    currentSets = currentSets + set,
                    previousFatigue = set.fatigue,
                    maxWeight = set.weight  // Ensure next sets use equal or lower weight
                )
                if (result != null) {
                    return result
                }
            }
        }
        return null
    }

    private fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
        fatigueFactor: Double
    ): ExerciseSet {
        val volume = weight * reps
        val percentLoad = (weight / oneRepMax) * 100
        val fatigue = volume * (1 + fatigueFactor * ln(1 + (percentLoad * reps / 100)))

        return ExerciseSet(
            weight = weight,
            reps = reps,
            fatigue = fatigue,
            volume = volume,
            percentLoad = percentLoad
        )
    }

    private fun getParametersByExerciseType(
        exerciseCategory: ProgressionHelper.ExerciseCategory
    ): ProgressionHelper.ExerciseParameters {
        return when (exerciseCategory) {
            ProgressionHelper.ExerciseCategory.STRENGTH -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 85.0 to 100.0,
                repsRange = 1..5,
                setsRange = 3..6,
                fatigueFactor = 0.2
            )
            ProgressionHelper.ExerciseCategory.HYPERTROPHY -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 65.0 to 85.0,
                repsRange = 6..12,
                setsRange = 3..5,
                fatigueFactor = 0.1
            )
            ProgressionHelper.ExerciseCategory.ENDURANCE -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 50.0 to 65.0,
                repsRange = 12..20,
                setsRange = 2..4,
                fatigueFactor = 0.05
            )
        }
    }

    suspend fun distributeVolumeWithMinimumIncrease(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        exerciseCategory: ProgressionHelper.ExerciseCategory,
        weightIncrement: Double,
        percentageIncrease: Double
    ): DistributedWorkout? {
        if(percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease/100))
        var currentTargetVolume = targetTotalVolume
        var bestSolution: DistributedWorkout? = null
        var smallestIncrease = Double.MAX_VALUE

        // Try solutions with smaller incremental steps
        while (currentTargetVolume <= minimumRequiredVolume * 1.05) { // Limit to 5% above minimum
            try {
                val solution = distributeVolume(
                    numberOfSets = numberOfSets,
                    targetTotalVolume = currentTargetVolume,
                    oneRepMax = oneRepMax,
                    exerciseCategory = exerciseCategory,
                    weightIncrement = weightIncrement
                )

                if (solution.totalVolume >= minimumRequiredVolume) {
                    val increase = (solution.totalVolume / targetTotalVolume) - 1
                    // Keep the solution closest to 2% increase
                    if (increase < smallestIncrease) {
                        smallestIncrease = increase
                        bestSolution = solution
                        // If we're very close to target increase (within 0.5%), we can stop
                        if (increase <= 0.025) { // 2.5%
                            break
                        }
                    }
                }
            } catch (e: IllegalStateException) {
                // Continue if no solution found for current target volume
            }

            // Use smaller increments (0.5% instead of 1%)
            currentTargetVolume *= 1.005
        }

        return bestSolution
    }
}
