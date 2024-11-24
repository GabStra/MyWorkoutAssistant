package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import java.util.BitSet
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.pow
import kotlin.math.sqrt

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
        targetTotalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float
    ): DistributedWorkout? {

        // Create base parameters
        val baseParams = WeightExerciseParameters(
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

    // Extension function to calculate variance of a list of doubles
    fun List<Double>.variance(): Double {
        val mean = this.average()
        return this.map { (it - mean) * (it - mean) }.average()
    }

    fun List<Int>.standardDeviation(): Double {
        val mean = average()
        return sqrt(map { (it - mean) * (it - mean) }.average())
    }

    fun findBestCombination(
        sets: List<ExerciseSet>,
        targetVolume: Double
    ): List<ExerciseSet> {
        val sortedSets = sets.sortedByDescending { it.volume }
        var bestCombination: List<ExerciseSet> = emptyList()
        var bestVolumeDeviation = Double.MAX_VALUE
        var bestPenaltyScore = Double.MIN_VALUE

        // Early termination checks
        val maxPossibleVolume = sets.sumOf { it.volume }
        if (maxPossibleVolume < targetVolume) return emptyList()

        val twoSmallestSets = sets.asSequence()
            .sortedBy { it.volume }
            .take(2)
            .toList()
        if (twoSmallestSets.size < 2 || twoSmallestSets.sumOf { it.volume } > targetVolume) {
            return emptyList()
        }

        fun getMinVolumeNeeded(startIndex: Int, requiredSets: Int): Double {
            if (startIndex >= sortedSets.size || requiredSets <= 0) return Double.MAX_VALUE

            return sortedSets.asSequence()
                .drop(startIndex)
                .sortedBy { it.volume }
                .take(requiredSets)
                .sumOf { it.volume }
        }

        fun calculateScore(
            numSets: Int,
            currentCombination: List<ExerciseSet>,
            currentVolume: Double
        ): Double {
            if (numSets < 2) return 0.0

            //val volumeDeviation = abs(currentVolume - targetVolume) / targetVolume
            val setPenalty = 0.95.pow(maxOf(0, numSets - 3))
            val totalFatigue = currentCombination.sumOf { it.fatigue }
            val fatiguePenalty = 0.95.pow(totalFatigue) // Reduced impact
            val lowRepPenalty = currentCombination.count { it.reps < 3 } * 0.95

            /* val reps = currentCombination.map { it.reps }
             val repStdDev = reps.standardDeviation()
             val repConsistencyScore = 1.0 / (1.0 + (repStdDev * 0.1))
             val repBalanceScore = 1.0 / (1.0 + (repStdDev * 2))*/

            return setPenalty * fatiguePenalty  * (1.0 - lowRepPenalty)
        }

        fun backtrack(
            start: Int,
            currentCombination: ArrayList<ExerciseSet>,
            currentTotalVolume: Double,
            usedIndices: BitSet,
            remainingMaxVolume: Double
        ): Boolean {
            // Early termination checks
            val remainingSetsNeeded = maxOf(2 - currentCombination.size, 0)
            if (remainingSetsNeeded > 0) {
                val minVolumeForRemainingSets = getMinVolumeNeeded(start, remainingSetsNeeded)
                if (minVolumeForRemainingSets == Double.MAX_VALUE ||
                    currentTotalVolume + minVolumeForRemainingSets > targetVolume) { // Slightly relaxed constraint
                    return false
                }
            }

            if (currentCombination.size < 2 &&
                sortedSets.size - start + currentCombination.size < 2) {
                return false
            }

            val currentVolumeDeviation = abs(currentTotalVolume - targetVolume) / targetVolume
            val penaltyScore = calculateScore(
                currentCombination.size,
                currentCombination,
                currentTotalVolume
            )

            if (currentCombination.size >= 2) {
                val shouldUpdate = currentVolumeDeviation < bestVolumeDeviation ||
                        (currentVolumeDeviation == bestVolumeDeviation && penaltyScore > bestPenaltyScore)

                if (shouldUpdate) {
                    bestVolumeDeviation = currentVolumeDeviation
                    bestPenaltyScore = penaltyScore


                    if(currentVolumeDeviation <= 0.05) {
                        val bestCombinationString = currentCombination.joinToString { "(${it.weight}, ${it.reps})" }
                        Log.d("WorkoutViewModel", "Target: $targetVolume | Valid combination - score: $penaltyScore volume: $currentTotalVolume - $bestCombinationString")
                    }


                    if(currentVolumeDeviation <= 0.01) {
                        bestCombination = ArrayList(currentCombination)
                    }
                }
            }

            if (currentTotalVolume >= targetVolume ||
                start >= sortedSets.size ||
                currentCombination.size >= 10) {
                return false
            }

            for (i in start until sortedSets.size) {
                if (usedIndices[i]) continue

                val nextSet = sortedSets[i]
                val newTotalVolume = currentTotalVolume + nextSet.volume

                if (newTotalVolume > targetVolume) continue // Slightly relaxed constraint

                if (currentCombination.isNotEmpty()) {
                    val lastSetReps = currentCombination.last().reps
                    val repsDifference = abs(nextSet.reps - lastSetReps) / lastSetReps.toDouble()
                    if (repsDifference > 0.3) continue

                    // Weight/rep order check
                    if (nextSet.weight > currentCombination.last().weight ||
                        (nextSet.weight == currentCombination.last().weight &&
                                nextSet.reps > currentCombination.last().reps)
                    ) continue
                }

                val projectedDeviation = abs(newTotalVolume - targetVolume) / targetVolume
                if (currentCombination.size >= 2 && projectedDeviation > bestVolumeDeviation) continue

                currentCombination.add(nextSet)
                usedIndices.set(i)

                if (backtrack(
                        i + 1,
                        currentCombination,
                        newTotalVolume,
                        usedIndices,
                        remainingMaxVolume - nextSet.volume
                    )) {
                    return true
                }

                currentCombination.removeAt(currentCombination.size - 1)
                usedIndices.clear(i)
            }

            return false
        }

        backtrack(
            0,
            ArrayList(),
            0.0,
            BitSet(sortedSets.size),
            maxPossibleVolume
        )

        return bestCombination
    }

    // Simple LRU Cache implementation to limit memory usage
    class LruCache<K, V>(private val maxSize: Int) {
        private val map = LinkedHashMap<K, V>(maxSize, 0.75f, true)

        fun get(key: K, compute: () -> V): V {
            map[key]?.let { return it }

            val value = compute()
            put(key, value)
            return value
        }

        private fun put(key: K, value: V) {
            map[key] = value
            if (map.size > maxSize) {
                map.remove(map.keys.first())
            }
        }
    }

    private suspend fun findSolution(params: WeightExerciseParameters): DistributedWorkout? {
        val possibleSets = generatePossibleSets(params)

       val possibleSetsData = possibleSets.joinToString { "(${it.weight}, ${it.reps}, ${it.volume})" }
        Log.d("WorkoutViewModel", "Possible sets: $possibleSetsData")

        if (possibleSets.isEmpty()) return null

        val validSetCombination = findBestCombination(possibleSets, params.targetTotalVolume)
        if (validSetCombination.isEmpty()) return null

        return DistributedWorkout(
            sets = validSetCombination,
            totalVolume = validSetCombination.sumOf { it.volume },
            totalFatigue = validSetCombination.sumOf { it.fatigue },
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.sumOf { it.fatigue } / validSetCombination.size
        )
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

        queue.add(
            SearchState(
                remainingSets = targetSets,
                remainingVolume = targetVolume,
                currentSets = emptyList(),
                currentFatigue = 0.0
            )
        )

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
                        (volumeGap == closestVolumeGap && state.currentFatigue < bestFatigue)
                    ) {
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
                    queue.add(
                        SearchState(
                            remainingSets = remainingSets,
                            remainingVolume = state.remainingVolume - set.volume,
                            currentSets = state.currentSets + set,
                            currentFatigue = state.currentFatigue + set.fatigue,
                            lastWeight = set.weight
                        )
                    )
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
            if (sets[i].weight > sets[i - 1].weight) {
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

        // Calculate intensity multiplier based on proximity to 1RM
        // Exponential increase as weight gets closer to 1RM
        val intensityMultiplier = kotlin.math.exp(
            1.5 * (percentLoad / 100.0) * (percentLoad / 100.0)
        )

        // Rep multiplier - higher reps are exponentially more fatiguing
        val repMultiplier = 1 + ln(1.0 + reps)

        // Enhanced fatigue calculation that maintains original parameter influence
        // while incorporating intensity and rep effects
        val fatigue = volume * (1 + fatigueFactor * ln(
            1 + (intensityMultiplier * repMultiplier * percentLoad * reps / 10000)
        ))

        return ExerciseSet(
            weight = weight,
            reps = reps,
            fatigue = fatigue,
            volume = volume,
            percentLoad = percentLoad,
        )
    }

    suspend fun distributeVolumeWithMinimumIncrease(
        currentVolume: Double,
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

        val minimumRequiredVolume = currentVolume * (1 + (percentageIncrease / 100))

        val solution = distributeVolume(
            targetTotalVolume = minimumRequiredVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor
        )

        return if (solution == null) {
            Pair(null, true)
        } else {
            Pair(solution, false)
        }
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
