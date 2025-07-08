package com.gabstra.myworkoutassistant.shared.utils

import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.calculateRIR
import com.gabstra.myworkoutassistant.shared.standardDeviation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.pow


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val intensity: Double,
        val reps: Int,
        val volume: Double,
        val fatigue: Double,
        val rir: Int = 0
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val usedOneRepMax: Double,
        val previousVolume: Double,
    )

    data class WeightExerciseParameters(
        var previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        val previousTotalVolume : Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val repsRange: IntRange,
        val volumeProgressionRange: FloatRange,
    )

    fun recalculateExerciseFatigue(
        existingSets: List<ExerciseSet>,
        fatigueFactor: Double = 0.005      // you’ll likely need a smaller factor here
    ): List<ExerciseSet> {
        val adjustedSets = mutableListOf<ExerciseSet>()
        var cumulativeFatigue = 0.0

        existingSets.forEach { original ->
            val baseFatigue = original.fatigue
            val adjustedFatigue = baseFatigue * (1.0 + fatigueFactor * cumulativeFatigue)
            adjustedSets.add(original.copy(fatigue = adjustedFatigue))
            cumulativeFatigue += adjustedFatigue
        }

        return adjustedSets
    }

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        val previousTotalFatigue = params.previousSets.sumOf { it.fatigue }
        var nearAverageWeights = getNearAverageWeights(params)

        val previousAverageWeightPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }
        val previousMaxWeight = params.previousSets.maxOf { it.weight }

        val previousMaxVolume = params.previousSets.maxOf { it.volume }
        val previousMinVolume = params.previousSets.minOf { it.volume }

        val maxRir = params.previousSets.maxOf { it.rir }

/*        val avgPreviousRir = params.previousSets.map { it.rir }.average()

        val maxRir = (ceil(avgPreviousRir)).toInt().coerceIn(0, 10)*/

        var validSets = possibleSets
            .filter { set -> set.weight in nearAverageWeights }
            .filter { set -> set.rir <= maxRir }

        val atUpperLimit = params.previousSets.all { it.reps >= params.repsRange.last }

        if(atUpperLimit){
            val sortedValidSets = validSets.filter { it.weight > previousAverageWeightPerRep }.sortedWith(
                compareByDescending<ExerciseSet> { it.weight }
                    .thenByDescending { it.reps }
            )

            validSets = when {
                sortedValidSets.isNotEmpty() ->  listOf(sortedValidSets.last())
                else -> emptyList()
            }
        }

        val maxVolume = validSets
            .filter { it.volume > previousMaxVolume }
            .groupBy { it.weight }
            .mapValues { it.value.minOf { set -> set.volume } }
            .values
            .maxOrNull() ?: Double.MAX_VALUE

        val minVolume = validSets
            .filter { it.volume < previousMinVolume }
            .groupBy { it.weight }
            .mapValues { it.value.maxOf { set -> set.volume } }
            .values
            .minOrNull() ?: Double.MIN_VALUE

        var usableSets = validSets
            .filter {  it.volume in minVolume..maxVolume }

        //Log.d("WorkoutViewModel", "usableSets: ${usableSets.map { "${it.weight} x ${it.reps}"}}")

        val previousTotalVolume = params.previousTotalVolume

        fun calculateScore (combo: List<ExerciseSet>): Double {
            val currentTotalFatigue = combo.sumOf { it.fatigue }
            val currentTotalVolume = combo.sumOf { it.volume }
            val currentAverageWeightPerRep = currentTotalVolume / combo.sumOf { it.reps }

            val currentMaxVolume = combo.maxOf { it.volume }
            val currentMaxWeight = combo.maxOf { it.weight }

            val totalFatigueDifference = 1 + (abs(currentTotalFatigue - previousTotalFatigue) / previousTotalFatigue)
            val avgWeightDifference = 1 + (abs(currentAverageWeightPerRep - previousAverageWeightPerRep) / previousAverageWeightPerRep)
            val targetVolumeDifference = 1 + (abs(currentTotalVolume - previousTotalVolume) / previousTotalVolume)

            val overPreviousMaxVolumeCount = combo.count { it.volume > previousMaxVolume }

            val maxVolumeDifference = if(currentMaxVolume > previousMaxVolume) {
                (1 + (currentMaxVolume - previousMaxVolume) / previousMaxVolume) * overPreviousMaxVolumeCount
            } else {
                1.0
            }

            val maxWeightDifference = if(currentMaxWeight > previousMaxWeight) {
                (1 + (currentMaxWeight - previousMaxWeight) / previousMaxWeight)
            } else {
                1.0
            }
            val intensityStdDev = 1 + combo.map { it.intensity }.standardDeviation()

            val differences = listOf(
                totalFatigueDifference,
                avgWeightDifference,
                targetVolumeDifference,
                maxVolumeDifference,
                maxWeightDifference,
                intensityStdDev
            )

            val geometricMean = differences.reduce { acc, d -> acc * d }.pow(1.0 / differences.size)

            return geometricMean
        }

        fun isStrictProgression(originalSets: List<ExerciseSet>, newSets: List<ExerciseSet>): Boolean {
            if (newSets.size < originalSets.size) {
                return false
            }

            var atLeastOneImprovement = false

            for (i in originalSets.indices) {
                val originalSet = originalSets[i]
                val newSet = newSets[i]

                // Check for a downgrade in any set. If found, it's not a progression.
                if (newSet.weight < originalSet.weight || newSet.reps < originalSet.reps) {
                    return false
                }

                // Check for an improvement in any set.
                if (newSet.weight > originalSet.weight || newSet.reps > originalSet.reps) {
                    atLeastOneImprovement = true
                }
            }

            if (newSets.size > originalSets.size) {
                return true
            }

            return atLeastOneImprovement
        }

        var result = findBestProgressions(
            usableSets,
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo -> isStrictProgression(params.previousSets, combo) }
        )

        if(result.isEmpty()){
            result = findBestProgressions(
                usableSets,
                params.previousSets.size,
                params.previousSets.size,
                params,
                calculateScore = { combo -> calculateScore(combo) },
                isComboValid = { combo -> true }
            )
        }

        return result
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params)
        var validSetCombination = findValidProgression(params, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume =  validSetCombination.sumOf { it.volume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = params.previousSets.sumOf { it.volume },
        )
    }

    private suspend fun findBestProgressions(
        sets: List<ExerciseSet>,
        minSets: Int,
        maxSets: Int,
        params: WeightExerciseParameters,
        calculateScore: (List<ExerciseSet>) -> Double,
        isComboValid: (List<ExerciseSet>) -> Boolean,
    ) = coroutineScope {
        require(minSets > 0) { "Minimum sets must be positive" }
        require(minSets <= maxSets) { "Minimum sets cannot exceed maximum sets" }

        if (sets.isEmpty()) return@coroutineScope emptyList()

        val sortedSets = sets.sortedWith(
            compareByDescending<ExerciseSet> { it.weight }
                .thenByDescending { it.reps }
        )

        val mutex = Mutex()
        var bestCombination = emptyList<ExerciseSet>()
        var bestScore = Double.MAX_VALUE

        fun evaluateGeneralScore(combo: List<ExerciseSet>): Double {
            val isValid = isComboValid(combo)
            if (!isValid)  return Double.MAX_VALUE
            return calculateScore(combo)
        }

        suspend fun exploreCombinations(
            currentCombo: List<ExerciseSet>,
            depth: Int = 1
        ) {
            if (currentCombo.size >= minSets) {
                mutex.withLock {
                    val adjustedCombo = recalculateExerciseFatigue(currentCombo)
                    val currentScore = evaluateGeneralScore(adjustedCombo)



                    if (currentScore != Double.MAX_VALUE && bestScore != Double.MAX_VALUE) {
                        if (currentScore > bestScore) return
                    }

                    if (currentScore < bestScore) {
                        bestScore = currentScore
                        bestCombination = adjustedCombo
                    }
                }
            }

            if (depth >= maxSets) return

            val lastSet = currentCombo.last()
            val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.fatigue >= candidate.fatigue }

            for (nextSet in validSets) {
                val newCombo = currentCombo + nextSet
                exploreCombinations(newCombo,depth + 1)
            }
        }

        suspend fun processSetRange(startIdx: Int, endIdx: Int) {
            for (firstSetIdx in startIdx until endIdx) {
                val firstSet = sortedSets[firstSetIdx]
                exploreCombinations(listOf(firstSet))
            }
        }

        val processorCount = Runtime.getRuntime().availableProcessors()
        val effectiveParallelism = minOf(processorCount, sortedSets.size)
        val chunkSize = (sortedSets.size + effectiveParallelism - 1) / effectiveParallelism

        (0 until effectiveParallelism)
            .map { threadIdx ->
                async(Dispatchers.Default) {
                    val startIdx = threadIdx * chunkSize
                    val endIdx = minOf(startIdx + chunkSize, sortedSets.size)
                    if (startIdx < endIdx) processSetRange(startIdx, endIdx)
                }
            }
            .awaitAll()

        return@coroutineScope bestCombination
    }

    private fun getWeightClosestToAvg(params : WeightExerciseParameters): Double {
        val sortedWeights = params.availableWeights.sorted()
        var averageWeightPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }

        val closestWeightIndex = when {
            averageWeightPerRep.isNaN() || averageWeightPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(averageWeightPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights[closestWeightIndex]
    }

    private fun getNearAverageWeights(params: WeightExerciseParameters, offsetPerc: Double = 0.025): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        if (sortedWeights.size < 2) {
            return sortedWeights
        }

        var averageWeightPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }

        val lowerBound = sortedWeights.filter { it <= averageWeightPerRep * (1 - offsetPerc) }.maxOrNull() ?: Double.MIN_VALUE
        val upperBound =  sortedWeights.filter { it >= averageWeightPerRep * (1 + offsetPerc) }.minOrNull() ?: Double.MAX_VALUE

        return sortedWeights.filter{ it in lowerBound..upperBound }

    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            var sortedWeights = params.availableWeights.sorted()
            sortedWeights.map { weight ->
                async(Dispatchers.Default) {
                    params.repsRange
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                                oneRepMax = params.oneRepMax
                            )
                        }
                }
            }.awaitAll().flatten()
        }

    fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
    ): ExerciseSet {
        val volume = weight * reps
        val intensity = weight / oneRepMax

        val fatigue = (reps * intensity).pow(1.5)

        val rir = calculateRIR(weight,reps,oneRepMax)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            fatigue = fatigue,
            rir = rir,
            intensity = intensity
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        volumeProgressionRange: FloatRange,
    ): ExerciseProgression? {
        val exerciseVolume = previousSets.sumOf { it.volume }

        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            previousTotalVolume = exerciseVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            repsRange = repsRange,
            volumeProgressionRange = volumeProgressionRange,
        )

        var currentExerciseProgression = getProgression(baseParams)
        if(currentExerciseProgression == null){
            return null
        }

        return currentExerciseProgression
    }
}
