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

    data class WeightExerciseParameters(
        val numberOfSets: Int,
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val weightIncrement: Double,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val fatigueFactor: Double
    )

    data class BodyWeightExerciseParameters(
        val numberOfSets: Int,
        val targetTotalVolume: Double,
        val repsRange: IntRange,
        val fatigueFactor: Double
    )

    suspend fun distributeVolume(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        exerciseCategory: ProgressionHelper.ExerciseCategory,
        weightIncrement: Double
    ): DistributedWorkout? {
        val params = getParametersByExerciseType(exerciseCategory)

        // Create base parameters
        val baseParams = WeightExerciseParameters(
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
        return null
    }

    private suspend fun findSolution(params: WeightExerciseParameters): DistributedWorkout? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        // Find valid combination of sets with minimum fatigue
        val validSetCombination = findValidSetCombination(
            possibleSets = possibleSets,
            targetSets = params.numberOfSets,
            targetVolume = params.targetTotalVolume,
            maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)
        ) ?: return null

        return DistributedWorkout(
            sets = validSetCombination.sets,
            totalVolume = validSetCombination.sets.sumOf { it.volume },
            totalFatigue = validSetCombination.totalFatigue,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.sets.maxOf { it.reps }
        )
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> = coroutineScope {
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

    data class SetCombination(
        val sets: List<ExerciseSet>,
        val totalFatigue: Double,
        val totalVolume: Double
    )

    private fun findValidSetCombination(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double,
        maxWeight: Double
    ): SetCombination? {
        // Filter and sort sets once
        val validSets = possibleSets
            .filter { it.weight <= maxWeight }
            .sortedByDescending { it.weight }

        if (validSets.isEmpty()) return null

        fun search(
            remainingSets: Int,
            currentMaxWeight: Double,
            remainingVolume: Double,
            currentSets: List<ExerciseSet>,
            currentFatigue: Double
        ): SetCombination? {
            // Found a valid combination
            if (currentSets.size == targetSets) {
                return if (remainingVolume <= 0) {
                    SetCombination(
                        sets = currentSets,
                        totalFatigue = currentFatigue,
                        totalVolume = targetVolume - remainingVolume
                    )
                } else null
            }

            // Try each valid set
            for (set in validSets) {
                // Skip if weight is too high
                if (set.weight > currentMaxWeight) continue

                // Skip if fatigue isn't decreasing
                if (currentSets.isNotEmpty() && set.fatigue >= currentSets.last().fatigue) continue

                val newSolution = search(
                    remainingSets = remainingSets - 1,
                    currentMaxWeight = set.weight,
                    remainingVolume = remainingVolume - set.volume,
                    currentSets = currentSets + set,
                    currentFatigue = currentFatigue + set.fatigue
                )

                if (newSolution != null) return newSolution
            }

            return null
        }

        return search(
            remainingSets = targetSets,
            currentMaxWeight = maxWeight,
            remainingVolume = targetVolume,
            currentSets = emptyList(),
            currentFatigue = 0.0
        )
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

                if(solution == null) {
                    currentTargetVolume *= 1.005
                    continue
                }

                if (solution.totalVolume >= minimumRequiredVolume) {
                    return solution
                }
            } catch (e: IllegalStateException) {
                // Continue if no solution found for current target volume
            }

            // Use smaller increments (0.5% instead of 1%)
            currentTargetVolume *= 1.005
        }

        //As a last resort, try with increased number of sets

        currentTargetVolume = targetTotalVolume
        while (currentTargetVolume <= minimumRequiredVolume * 1.05) { // Limit to 5% above minimum
            try {
                val solution = distributeVolume(
                    numberOfSets = numberOfSets,
                    targetTotalVolume = currentTargetVolume,
                    oneRepMax = oneRepMax,
                    exerciseCategory = exerciseCategory,
                    weightIncrement = weightIncrement
                )

                if(solution == null) {
                    currentTargetVolume *= 1.005
                    continue
                }

                if (solution.totalVolume >= minimumRequiredVolume) {
                    return solution
                }
            } catch (e: IllegalStateException) {
                // Continue if no solution found for current target volume
            }

            // Use smaller increments (0.5% instead of 1%)
            currentTargetVolume *= 1.005
        }

        return null
    }

    private fun createBodyWeightSet(
        reps: Int,
        fatigueFactor: Double
    ): ExerciseSet {
        val volume = reps.toDouble()
        // For bodyweight exercises, we use a simplified fatigue calculation
        // since we don't have percentage load to factor in
        val fatigue = volume * (1 + fatigueFactor * ln(1.0 + reps))

        return ExerciseSet(
            weight = 1.0, // Use 1.0 as a multiplier for bodyweight
            reps = reps,
            fatigue = fatigue,
            volume = volume,
            percentLoad = 100.0 // Constant since it's always bodyweight
        )
    }

    private suspend fun findBodyWeightSolution(params: BodyWeightExerciseParameters): DistributedWorkout? {
        val possibleSets = generatePossibleBodyWeightSets(params)
        if (possibleSets.isEmpty()) return null

        // Find valid combination of sets
        val validSetCombination = findValidBodyWeightSetCombination(
            possibleSets = possibleSets,
            targetSets = params.numberOfSets,
            targetVolume = params.targetTotalVolume,
        ) ?: return null

        return DistributedWorkout(
            sets = validSetCombination.sets,
            totalVolume = validSetCombination.sets.sumOf { it.volume },
            totalFatigue = validSetCombination.sets.sumOf { it.fatigue },
            usedOneRepMax = 1.0, // Not applicable for bodyweight
            maxRepsUsed = validSetCombination.sets.maxOf { it.reps }
        )
    }

    private suspend fun generatePossibleBodyWeightSets(
        params: BodyWeightExerciseParameters
    ): List<ExerciseSet> = coroutineScope {
        params.repsRange.map { reps ->
            createBodyWeightSet(
                reps = reps,
                fatigueFactor = params.fatigueFactor
            )
        }.sortedWith(compareBy<ExerciseSet> { it.reps }.thenBy { it.fatigue })
    }

    private fun findValidBodyWeightSetCombination(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double
    ): SetCombination? {
        // Filter sets once at the start and sort by fatigue
        val validSets = possibleSets.sortedBy { it.fatigue }

        fun search(
            remainingSets: Int,
            remainingVolume: Double,
            currentSets: List<ExerciseSet>,
            previousFatigue: Double = Double.MAX_VALUE,
            currentFatigue: Double = currentSets.sumOf { it.fatigue }
        ): SetCombination? {
            // Base case: found required number of sets
            if (currentSets.size == targetSets) {
                return if (remainingVolume <= 0) {
                    SetCombination(
                        sets = currentSets,
                        totalFatigue = currentFatigue,
                        totalVolume = targetVolume - remainingVolume
                    )
                } else null
            }

            // Early pruning: check if minimum possible volume is achievable
            val minPossibleVolumePerSet = validSets
                .filter { it.fatigue <= previousFatigue }
                .minOfOrNull { it.volume } ?: return null

            if (minPossibleVolumePerSet * remainingSets < remainingVolume * 0.5) {
                return null
            }

            // Try each valid set
            for (set in validSets) {
                // Skip if fatigue isn't decreasing
                if (set.fatigue >= previousFatigue) continue

                // Skip if volume is too low to be useful
                if (set.volume < (remainingVolume / remainingSets) * 0.5) continue

                val newSolution = search(
                    remainingSets = remainingSets - 1,
                    remainingVolume = remainingVolume - set.volume,
                    currentSets = currentSets + set,
                    previousFatigue = set.fatigue,
                    currentFatigue = currentFatigue + set.fatigue
                )

                if (newSolution != null) return newSolution
            }

            return null
        }

        return search(
            remainingSets = targetSets,
            remainingVolume = targetVolume,
            currentSets = emptyList()
        )
    }

    suspend fun distributeBodyWeightVolumeWithMinimumIncrease(
        numberOfSets: Int,
        targetTotalVolume: Double,
        exerciseCategory: ProgressionHelper.ExerciseCategory,
        percentageIncrease: Double
    ): DistributedWorkout? {
        if(percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val params = getParametersByExerciseType(exerciseCategory)
        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease/100))
        var currentTargetVolume = targetTotalVolume

        // Try solutions with smaller incremental steps
        while (currentTargetVolume <= minimumRequiredVolume * 1.05) { // Limit to 5% above minimum
            try {
                val baseParams = BodyWeightExerciseParameters(
                    numberOfSets = numberOfSets,
                    targetTotalVolume = currentTargetVolume,
                    repsRange = params.repsRange,
                    fatigueFactor = params.fatigueFactor
                )

                val solution = findBodyWeightSolution(baseParams)

                if(solution == null) {
                    currentTargetVolume *= 1.005
                    continue
                }

                if (solution.totalVolume >= minimumRequiredVolume) {
                    return solution
                }
            } catch (e: IllegalStateException) {
                // Continue if no solution found for current target volume
            }

            // Use smaller increments (0.5% instead of 1%)
            currentTargetVolume *= 1.005
        }

        //as a last resort, try with increased number of sets
        currentTargetVolume = targetTotalVolume
        while (currentTargetVolume <= minimumRequiredVolume * 1.05) { // Limit to 5% above minimum
            try {
                val baseParams = BodyWeightExerciseParameters(
                    numberOfSets = numberOfSets + 1,
                    targetTotalVolume = currentTargetVolume,
                    repsRange = params.repsRange,
                    fatigueFactor = params.fatigueFactor
                )

                val solution = findBodyWeightSolution(baseParams)

                if(solution == null) {
                    currentTargetVolume *= 1.005
                    continue
                }

                if (solution.totalVolume >= minimumRequiredVolume) {
                    return solution
                }
            } catch (e: IllegalStateException) {
                // Continue if no solution found for current target volume
            }

            // Use smaller increments (0.5% instead of 1%)
            currentTargetVolume *= 1.005
        }

        return null
    }
}
