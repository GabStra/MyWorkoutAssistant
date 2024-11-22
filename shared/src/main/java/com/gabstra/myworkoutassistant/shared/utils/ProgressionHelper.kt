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
        val percentLoad: Double,
    )

    data class DistributedWorkout(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val totalFatigue: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageFatiguePerSet: Double
    )

    data class WeightExerciseParameters(
        val numberOfSets: Int,
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
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

    private suspend fun distributeVolume(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float
    ): DistributedWorkout? {

        // Create base parameters
        val baseParams = WeightExerciseParameters(
            numberOfSets = numberOfSets,
            targetTotalVolume = targetTotalVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        // Try with original parameters first
        findSolution(baseParams)?.let { return it }
        return null
    }

    private suspend fun findSolution(params: WeightExerciseParameters): DistributedWorkout? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        val possibleNumberOfSets = generatePossibleNumberOfSets(params)
        if (possibleNumberOfSets.isEmpty()) return null

        val solutions = coroutineScope {
            possibleNumberOfSets.map { numberOfSets ->
                async(Dispatchers.IO) {
                    val validSetCombination = findValidSetCombination(
                        possibleSets = possibleSets,
                        targetSets = numberOfSets,
                        targetVolume = params.targetTotalVolume,
                    ) ?: return@async null

                    DistributedWorkout(
                        sets = validSetCombination.sets,
                        totalVolume = validSetCombination.sets.sumOf { it.volume },
                        totalFatigue = validSetCombination.totalFatigue,
                        usedOneRepMax = params.oneRepMax,
                        maxRepsUsed = validSetCombination.sets.maxOf { it.reps },
                        averageFatiguePerSet = validSetCombination.averageFatiguePerSet
                    )
                }
            }.awaitAll().filterNotNull()
        }

        if (solutions.isEmpty()) return null

        // Calculate the ranges for normalization
        val minSets = solutions.minOf { it.sets.size }
        val maxSets = solutions.maxOf { it.sets.size }
        val minAvgFatigue = solutions.minOf { it.averageFatiguePerSet }
        val maxAvgFatigue = solutions.maxOf { it.averageFatiguePerSet }

        // Find solution with best balance between number of sets and average fatigue
        return solutions.minByOrNull { solution ->
            // Normalize both metrics to 0-1 range
            val normalizedSets = if (maxSets == minSets) {
                0.0
            } else {
                (solution.sets.size - minSets).toDouble() / (maxSets - minSets)
            }

            val normalizedFatigue = if (maxAvgFatigue == minAvgFatigue) {
                0.0
            } else {
                (solution.averageFatiguePerSet - minAvgFatigue) / (maxAvgFatigue - minAvgFatigue)
            }

            // Calculate combined score (lower is better)
            // Equal weight to both metrics
            normalizedSets * 0.5 + normalizedFatigue * 0.5
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val minWeight = params.oneRepMax * (params.percentLoadRange.first / 100)
            val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)

            val weightRange = params.availableWeights.filter { it in minWeight..maxWeight }

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

            //for sets with the same volume, keep the one with the lowest fatigue
            val setsByVolume = filteredSets.groupBy { it.volume }
            setsByVolume.map { it.value.minByOrNull { it.fatigue }!! }
        }

    private fun generatePossibleNumberOfSets(params: WeightExerciseParameters): Set<Int> {
        val minWeight = params.oneRepMax * (params.percentLoadRange.first / 100.0)
        val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100.0)

        val possibleSets = mutableSetOf<Int>()
        val weights = mutableSetOf<Double>()

        weights.add(minWeight)
        weights.add(maxWeight)

        val reps = mutableSetOf<Int>()
        reps.add(params.repsRange.first)
        reps.add(params.repsRange.last)

        weights.forEach { weight ->
            reps.forEach { rep ->
                val volume = weight * rep
                val numberOfSets = (params.targetTotalVolume / volume).toInt()
                if(numberOfSets > 0) {
                    possibleSets.add(numberOfSets)
                }
            }
        }

        if(possibleSets.isEmpty()) return emptySet()

        //get the min an max number of sets and return all the number in between
        val minNumberOfSets = possibleSets.minOrNull() ?: 0
        val maxNumberOfSets = possibleSets.maxOrNull() ?: 0

        return (minNumberOfSets..maxNumberOfSets).toSet()
    }

    data class SetCombination(
        val sets: List<ExerciseSet>,
        val totalFatigue: Double,
        val totalVolume: Double,
        val averageFatiguePerSet: Double
    )

    private fun findValidSetCombination(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double
    ): SetCombination? {
        if (possibleSets.isEmpty()) return null

        // Pre-filter and sort possible sets by weight and then reps
        val filteredSets = possibleSets
            .sortedWith(compareByDescending<ExerciseSet> { it.weight }
                .thenByDescending { it.reps })
            .filter { it.volume <= targetVolume / targetSets * 1.2 }
            .take(10)

        data class SearchState(
            val remainingSets: Int,
            val remainingVolume: Double,
            val currentSets: List<ExerciseSet>,
            val currentFatigue: Double,
            val lastWeight: Double? = null
        )

        val queue = ArrayDeque<SearchState>()
        var bestCombination: SetCombination? = null
        var closestVolumeGap = Double.MAX_VALUE
        var bestFatigue = Double.MAX_VALUE

        queue.add(SearchState(
            remainingSets = targetSets,
            remainingVolume = targetVolume,
            currentSets = emptyList(),
            currentFatigue = 0.0
        ))

        while (queue.isNotEmpty()) {
            val state = queue.removeFirst()

            // Complete combination found
            if (state.currentSets.size == targetSets) {
                val totalVolume = state.currentSets.sumOf { it.volume }
                val volumeGap = targetVolume - totalVolume

                // Only consider solutions that don't exceed target volume and have proper weight progression
                if (volumeGap >= 0 && isWeightProgressionValid(state.currentSets)) {
                    // Update best combination if:
                    // 1. This combination is closer to target volume, or
                    // 2. Equal volume distance but has less fatigue
                    if (volumeGap < closestVolumeGap ||
                        (volumeGap == closestVolumeGap && state.currentFatigue < bestFatigue)) {
                        closestVolumeGap = volumeGap
                        bestFatigue = state.currentFatigue
                        bestCombination = SetCombination(
                            sets = state.currentSets,
                            totalFatigue = state.currentFatigue,
                            totalVolume = totalVolume,
                            averageFatiguePerSet = state.currentFatigue / targetSets
                        )
                    }
                }
                continue
            }

            val currentVolume = state.currentSets.sumOf { it.volume }
            val volumeGap = targetVolume - currentVolume

            // Skip if we've exceeded target volume
            if (volumeGap < 0) {
                continue
            }

            // Get valid next sets that maintain weight progression
            val validNextSets = filteredSets
                .filter { set ->
                    // Weight must be equal or less than previous set
                    val isWeightValid = if (state.lastWeight != null) {
                        set.weight <= state.lastWeight
                    } else true

                    // Total volume must not exceed target
                    val isVolumeValid = (currentVolume + set.volume) <= targetVolume

                    isWeightValid && isVolumeValid
                }

            // Add new states to queue
            for (set in validNextSets) {
                // Calculate if this path could possibly get close enough to target
                val remainingSets = state.remainingSets - 1
                val remainingVolumeNeeded = targetVolume - (currentVolume + set.volume)
                val isPathViable = if (remainingSets > 0) {
                    // Check if we can possibly reach target with remaining sets
                    val maxVolumePerRemainingSet = validNextSets
                        .filter { it.weight <= set.weight }
                        .maxOfOrNull { it.volume } ?: 0.0
                    remainingVolumeNeeded <= (remainingSets * maxVolumePerRemainingSet)
                } else true

                if (isPathViable) {
                    queue.add(SearchState(
                        remainingSets = remainingSets,
                        remainingVolume = state.remainingVolume - set.volume,
                        currentSets = state.currentSets + set,
                        currentFatigue = state.currentFatigue + set.fatigue,
                        lastWeight = set.weight
                    ))
                }
            }

            // Manage queue size
            if (queue.size > 1000) {
                val sortedQueue = queue.sortedWith(compareBy(
                    // Sort by how close they could get to target volume
                    { state ->
                        val currentStateVolume = state.currentSets.sumOf { it.volume }
                        kotlin.math.abs(targetVolume - currentStateVolume)
                    },
                    { it.currentFatigue }
                ))
                queue.clear()
                queue.addAll(sortedQueue.take(500))
            }
        }

        return bestCombination
    }

    // Helper function to verify weight progression
    private fun isWeightProgressionValid(sets: List<ExerciseSet>): Boolean {
        for (i in 1 until sets.size) {
            if (sets[i].weight > sets[i-1].weight) {
                return false
            }
        }
        return true
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
            percentLoad = percentLoad,
        )
    }

    suspend fun distributeVolumeWithMinimumIncrease(
        numberOfSets: Int,
        targetTotalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        percentageIncrease: Float,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float
    ): Pair<DistributedWorkout?, Boolean> {
        if (percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease / 100))

        val solution = distributeVolume(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        if(solution == null) {
            return Pair(null, true)
        }else{
            return Pair(solution, false)
        }

        /*if(numberOfSets >= 6) {

        }

        val increasedSetSolution = distributeVolume(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        if(solution == null && increasedSetSolution == null) {
            return Pair(null, true)
        }

        if (solution != null && increasedSetSolution == null) {
            return Pair(solution, false)
        }

        if(solution == null && increasedSetSolution != null) {
            return Pair(increasedSetSolution, false)
        }

        return if(solution!!.averageFatiguePerSet<=increasedSetSolution!!.averageFatiguePerSet){
            Pair(solution, false)
        }else{
            Pair(increasedSetSolution, false)
        }*/
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
            percentLoad = 100.0, // Constant since it's always bodyweight
        )
    }

    private suspend fun findBodyWeightSolution(params: BodyWeightExerciseParameters): DistributedWorkout? {
        var possibleSets = generatePossibleBodyWeightSets(params)

        if (possibleSets.isEmpty()) return null

        // Find valid combination of sets
        val validSetCombinations = findAllValidBodyWeightSetCombinations(
            possibleSets = possibleSets,
            targetSets = params.numberOfSets,
            targetVolume = params.targetTotalVolume,
        )

        val validSetCombination =
            validSetCombinations.sortedBy { it.totalFatigue }.minByOrNull { it.totalFatigue }
                ?: return null

        return DistributedWorkout(
            sets = validSetCombination.sets,
            totalVolume = validSetCombination.sets.sumOf { it.volume },
            totalFatigue = validSetCombination.sets.sumOf { it.fatigue },
            usedOneRepMax = 1.0, // Not applicable for bodyweight
            maxRepsUsed = validSetCombination.sets.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.averageFatiguePerSet
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
        }
    }

    private fun findAllValidBodyWeightSetCombinations(
        possibleSets: List<ExerciseSet>,
        targetSets: Int,
        targetVolume: Double,
        maxResults: Int = 10
    ): List<SetCombination> {
        val validSets = possibleSets

        if (validSets.isEmpty()) return emptyList()



        fun getValidSetsForRemaining(
            remainingSets: Int,
            remainingVolume: Double,
            previousFatigue: Double
        ): List<ExerciseSet> {
            val targetVolumePerSet = remainingVolume / remainingSets
            val minVolumePerSet = targetVolumePerSet * 0.8
            val maxVolumePerSet = targetVolumePerSet * 1.2

            val filteredSets = validSets.filter {
                it.volume in minVolumePerSet..maxVolumePerSet &&
                        it.fatigue <= previousFatigue
            }

            return filteredSets.sortedWith(
                compareBy(
                    { kotlin.math.abs(it.volume - targetVolumePerSet) },
                    { it.fatigue })
            )
        }

        val results = mutableListOf<SetCombination>()
        val uniqueCombinations = mutableSetOf<List<ExerciseSet>>()

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
                    if (uniqueCombinations.add(currentSets)) {
                        results.add(
                            SetCombination(
                                sets = currentSets,
                                totalFatigue = currentFatigue,
                                totalVolume = totalVolume,
                                averageFatiguePerSet = currentFatigue / targetSets
                            )
                        )
                    }
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
    ): Pair<DistributedWorkout?, Boolean> {
        if (percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val minimumRequiredVolume = targetTotalVolume * (1 + (percentageIncrease / 100))
        val maximumRequiredVolume = minimumRequiredVolume * 1.05

        val baseParams = BodyWeightExerciseParameters(
            numberOfSets = numberOfSets,
            targetTotalVolume = minimumRequiredVolume,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        val solution = findBodyWeightSolution(baseParams)
        if (solution != null && solution.totalVolume >= minimumRequiredVolume && solution.totalVolume <= maximumRequiredVolume) {
            return Pair(solution, false)
        }

        val increasedSetSolution =
            findBodyWeightSolution(baseParams.copy(numberOfSets = numberOfSets + 1))

        if (increasedSetSolution != null && increasedSetSolution.totalVolume >= minimumRequiredVolume && increasedSetSolution.totalVolume <= maximumRequiredVolume) {
            return Pair(increasedSetSolution, false)
        }

        return Pair(null, true)
    }
}
