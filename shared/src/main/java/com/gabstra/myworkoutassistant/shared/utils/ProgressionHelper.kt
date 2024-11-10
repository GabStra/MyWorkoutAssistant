package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.ceil
import kotlin.math.ln
import kotlin.time.Duration.Companion.milliseconds

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
        val fatigueFactor: Double
    )

    fun getParametersByExerciseType(
        exerciseCategory: ProgressionHelper.ExerciseCategory
    ): ProgressionHelper.ExerciseParameters {
        return when (exerciseCategory) {
            ProgressionHelper.ExerciseCategory.STRENGTH -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 85.0 to 100.0,
                repsRange = 1..5,
                fatigueFactor = 0.2
            )
            ProgressionHelper.ExerciseCategory.HYPERTROPHY -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 65.0 to 85.0,
                repsRange = 6..12,
                fatigueFactor = 0.1
            )
            ProgressionHelper.ExerciseCategory.ENDURANCE -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 50.0 to 65.0,
                repsRange = 12..20,
                fatigueFactor = 0.05
            )
        }
    }
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
        val fatigueFactor: Float
    )

    data class BodyWeightExerciseParameters(
        val numberOfSets: Int,
        val targetTotalVolume: Double,
        val repsRange: IntRange,
        val fatigueFactor: Float
    )

    suspend fun distributeVolume(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        weightIncrement: Double,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float
    ): DistributedWorkout? {

        // Create base parameters
        val baseParams = WeightExerciseParameters(
            numberOfSets = numberOfSets,
            targetTotalVolume = targetTotalVolume,
            oneRepMax = oneRepMax,
            weightIncrement = weightIncrement,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
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
        val validSetCombinations = findAllValidSetCombinations(
            possibleSets = possibleSets,
            targetSets = params.numberOfSets,
            targetVolume = params.targetTotalVolume,
            maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)
        )

        val validSetCombination = validSetCombinations.sortedBy { it.totalFatigue }.minByOrNull { it.totalFatigue } ?: return null

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

    private fun findAllValidSetCombinations(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double,
        maxWeight: Double,
        maxResults: Int = 10
    ): List<SetCombination> {
         val validSets = possibleSets
            .filter { it.weight <= maxWeight }
            .sortedWith(compareBy({ it.weight }, { it.volume }))

        if (validSets.isEmpty()) return emptyList()

        val result = mutableListOf<SetCombination>()

        fun getValidSetsForRemaining(
            remainingSets: Int,
            remainingVolume: Double,
            currentMaxWeight: Double,
            lastFatigue: Double?
        ): List<ExerciseSet> {
            val targetVolumePerSet = remainingVolume / remainingSets
            // Increased tolerance range for volume per set
            val minVolumePerSet = targetVolumePerSet * 0.7  // More lenient minimum
            val maxVolumePerSet = targetVolumePerSet * 1.3  // More lenient maximum

            val filteredSets = validSets.filter { set ->
                set.weight <= currentMaxWeight &&
                        set.volume >= minVolumePerSet &&
                        set.volume <= maxVolumePerSet &&
                        (lastFatigue == null || set.fatigue <= lastFatigue)
            }.sortedWith(compareBy({ it.weight }, { it.volume }))

            return filteredSets
        }

        fun search(
            remainingSets: Int,
            currentMaxWeight: Double,
            remainingVolume: Double,
            currentSets: List<ExerciseSet>,
            currentFatigue: Double
        ): Boolean {
            if (result.size >= maxResults) return true

            if (currentSets.size == targetSets) {
                val totalVolume = currentSets.sumOf { it.volume }
                if (totalVolume >= targetVolume && totalVolume <= targetVolume * 1.1) {
                    result.add(
                        SetCombination(
                            sets = currentSets,
                            totalFatigue = currentFatigue,
                            totalVolume = totalVolume
                        )
                    )
                    return result.size >= maxResults
                }
                return false
            }

            val lastFatigue = currentSets.lastOrNull()?.fatigue
            val validSetsForRemaining = getValidSetsForRemaining(
                remainingSets = remainingSets,
                remainingVolume = remainingVolume,
                currentMaxWeight = currentMaxWeight,
                lastFatigue = lastFatigue
            )

            for (set in validSetsForRemaining) {
                val newRemainingVolume = remainingVolume - set.volume

                // Removed overly restrictive volume check
                val shouldStop = search(
                    remainingSets = remainingSets - 1,
                    currentMaxWeight = set.weight,
                    remainingVolume = newRemainingVolume,
                    currentSets = currentSets + set,
                    currentFatigue = currentFatigue + set.fatigue
                )

                if (shouldStop) return true
            }

            return false
        }

        search(
            remainingSets = targetSets,
            currentMaxWeight = maxWeight,
            remainingVolume = targetVolume,
            currentSets = emptyList(),
            currentFatigue = 0.0
        )

        return result
    }

    private fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
        fatigueFactor: Float
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

    suspend fun distributeVolumeWithMinimumIncrease(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        weightIncrement: Double,
        percentageIncrease: Float,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float
    ): Pair<DistributedWorkout?,Boolean> {
        if(percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease/100))
        val maximumRequiredVolume = minimumRequiredVolume * 1.05

        val solution = distributeVolume(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            oneRepMax = oneRepMax,
            weightIncrement = weightIncrement,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )


        if (solution != null && solution.totalVolume >= minimumRequiredVolume && solution.totalVolume <= maximumRequiredVolume) {
            return Pair(solution,false)
        }

        val increasedSetSolution = distributeVolume(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            oneRepMax = oneRepMax,
            weightIncrement = weightIncrement,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        if (increasedSetSolution != null && increasedSetSolution.totalVolume >= minimumRequiredVolume && increasedSetSolution.totalVolume <= maximumRequiredVolume) {
            return Pair(increasedSetSolution,false)
        }

        return Pair(null,true)
    }

    private fun createBodyWeightSet(
        reps: Int,
        fatigueFactor: Float
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
        val validSetCombinations = findAllValidBodyWeightSetCombinations(
            possibleSets = possibleSets,
            targetSets = params.numberOfSets,
            targetVolume = params.targetTotalVolume,
        )

        val validSetCombination = validSetCombinations.sortedBy { it.totalFatigue }.minByOrNull { it.totalFatigue } ?: return null

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

    private fun findAllValidBodyWeightSetCombinations(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double,
        maxResults: Int = 10
    ): List<SetCombination> {
        val validSets = possibleSets.sortedBy { it.fatigue }

        if (validSets.isEmpty()) return emptyList()

        fun getValidSetsForRemaining(
            remainingSets: Int,
            remainingVolume: Double,
            previousFatigue: Double
        ): List<ExerciseSet> {
            val targetVolumePerSet = remainingVolume / remainingSets
            val minVolumePerSet = targetVolumePerSet * 0.8
            val maxVolumePerSet = targetVolumePerSet * 1.2

            return validSets.filter { set ->
                set.fatigue <= previousFatigue &&
                        set.volume >= minVolumePerSet &&
                        set.volume <= maxVolumePerSet
            }
        }

        val results = mutableListOf<SetCombination>()

        fun search(
            remainingSets: Int,
            remainingVolume: Double,
            currentSets: List<ExerciseSet>,
            previousFatigue: Double = Double.MAX_VALUE,
            currentFatigue: Double = currentSets.sumOf { it.fatigue }
        ): Boolean {  // Return true if we should stop searching
            if (results.size >= maxResults) return true

            if (currentSets.size == targetSets) {
                val totalVolume = targetVolume - remainingVolume
                if (totalVolume >= targetVolume && totalVolume <= targetVolume * 1.1) {
                    results.add(
                        SetCombination(
                            sets = currentSets,
                            totalFatigue = currentFatigue,
                            totalVolume = totalVolume
                        )
                    )
                    return results.size >= maxResults
                }
                return false
            }

            // Early pruning: check if minimum possible volume is achievable
            val validSetsForRemaining = getValidSetsForRemaining(
                remainingSets = remainingSets,
                remainingVolume = remainingVolume,
                previousFatigue = previousFatigue
            )

            if (validSetsForRemaining.isEmpty()) return false

            val minPossibleVolumePerSet = validSetsForRemaining.minOf { it.volume }
            if (minPossibleVolumePerSet * remainingSets < remainingVolume * 0.5) {
                return false
            }

            // Try each valid set
            for (set in validSetsForRemaining) {
                val newRemainingVolume = remainingVolume - set.volume

                // Skip if total volume would be too high
                if (targetVolume - newRemainingVolume > targetVolume * 1.1) continue
                if (newRemainingVolume < 0) continue

                val shouldStop = search(
                    remainingSets = remainingSets - 1,
                    remainingVolume = newRemainingVolume,
                    currentSets = currentSets + set,
                    previousFatigue = set.fatigue,
                    currentFatigue = currentFatigue + set.fatigue
                )

                if (shouldStop) return true
            }

            return false
        }

        search(
            remainingSets = targetSets,
            remainingVolume = targetVolume,
            currentSets = emptyList()
        )

        return results
    }

    suspend fun distributeBodyWeightVolumeWithMinimumIncrease(
        numberOfSets: Int,
        targetTotalVolume: Double,
        percentageIncrease: Float,
        repsRange: IntRange,
        fatigueFactor: Float
    ): Pair<DistributedWorkout?,Boolean> {
        if(percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease/100))
        val maximumRequiredVolume = minimumRequiredVolume * 1.05

        val baseParams = BodyWeightExerciseParameters(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        val solution = findBodyWeightSolution(baseParams)
        if (solution!=null && solution.totalVolume >= minimumRequiredVolume && solution.totalVolume <= maximumRequiredVolume) {
            return Pair(solution,false)
        }

        val increasedSetSolution = findBodyWeightSolution(baseParams.copy(numberOfSets = numberOfSets + 1))

        if (increasedSetSolution!=null && increasedSetSolution.totalVolume >= minimumRequiredVolume && increasedSetSolution.totalVolume <= maximumRequiredVolume) {
            return Pair(increasedSetSolution,false)
        }

        return Pair(null,true)
    }
}
