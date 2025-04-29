package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.calculateRIR
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.maxRepsForWeight
import com.gabstra.myworkoutassistant.shared.median
import com.gabstra.myworkoutassistant.shared.standardDeviation
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.pow
import kotlin.math.roundToInt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val usedOneRepMax: Double,
        val previousVolume: Double,
    )

    data class WeightExerciseParameters(
        val previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        val previousTotalVolume : Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val volumeProgressionRange: FloatRange,
    )

    private fun calculateTotalInol(sets: List<ExerciseSet>, oneRepMax: Double): Double {
        // Calculate INOL for each set and sum them up
        return sets.sumOf { set ->
            val percentageOfOneRepMax = set.weight / oneRepMax
            val inol = set.reps / (1.0 - percentageOfOneRepMax)
            inol
        }
    }

    private fun calculateMedianWeight(sets: List<ExerciseSet>): Double {
        if (sets.isEmpty()) {
            throw IllegalArgumentException("Cannot calculate median of empty list")
        }

        return sets.sumOf { it.volume } / sets.sumOf { it.reps }
/*        // Create a list of all weights, repeated by their rep count
        val allWeights = mutableListOf<Double>()
        for (set in sets) {
            repeat(set.reps) {
                allWeights.add(set.weight)
            }
        }

        // Sort the expanded list
        val sortedWeights = allWeights.sorted()

        return if (sortedWeights.size % 2 == 0) {
            // Even number of elements, average the middle two
            val midIndex = sortedWeights.size / 2
            (sortedWeights[midIndex - 1] + sortedWeights[midIndex]) / 2.0
        } else {
            // Odd number of elements, return the middle one
            sortedWeights[sortedWeights.size / 2]
        }*/
    }

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            Log.d("WorkoutViewModel", "No possible sets found")
            return emptyList()
        }

        val minTotalVolume = params.previousTotalVolume * (1 + params.volumeProgressionRange.from / 100)
        val maxTotalVolume = params.previousTotalVolume * (1 + params.volumeProgressionRange.to / 100)

        val previousInol = calculateTotalInol(params.previousSets,params.oneRepMax)

        var result = findBestProgressions(
            possibleSets,
            params.previousSets.size,
            params.previousSets.size,
            params,
            { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val averageVolume = currentTotalVolume / combo.size
                val volumeStdDev = combo.map { it.volume }.standardDeviation()
                val deviationPercentage =  (volumeStdDev / averageVolume) * 100

                val currentInol = calculateTotalInol(combo,params.oneRepMax)

                ValidationResult(
                    shouldReturn = currentTotalVolume.isEqualTo(params.previousTotalVolume)
                            || currentTotalVolume < minTotalVolume
                            || currentTotalVolume > maxTotalVolume
                            || deviationPercentage > 10
                            || currentInol < previousInol
                )
            }
        )

        if (result.isEmpty()) {
            result = findBestProgressions(
                possibleSets,
                params.previousSets.size,
                params.previousSets.size,
                params,
                { combo ->
                    val currentTotalVolume = combo.sumOf { it.volume }

                    val averageVolume = currentTotalVolume / combo.size
                    val volumeStdDev = combo.map { it.volume }.standardDeviation()
                    val deviationPercentage =  (volumeStdDev / averageVolume) * 100

                    val currentInol = calculateTotalInol(combo,params.oneRepMax)

                    ValidationResult(
                        shouldReturn = currentTotalVolume.isEqualTo(params.previousTotalVolume)
                                || currentTotalVolume < minTotalVolume
                                || deviationPercentage > 10
                                || currentInol < previousInol
                    )
                }
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
            previousVolume = params.previousTotalVolume,
        )
    }

    data class ValidationResult(
        val shouldReturn: Boolean,
        val returnValue: Double = Double.MAX_VALUE

    )
    private suspend fun findBestProgressions(
        sets: List<ExerciseSet>,
        minSets: Int,
        maxSets: Int,
        params: WeightExerciseParameters,
        validationRules: (List<ExerciseSet>) -> ValidationResult,
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
            val validationResult = validationRules(combo)
            if (validationResult.shouldReturn)  return validationResult.returnValue

            val currentVolume = combo.sumOf { it.volume }
            val volumeDifference = combo.maxOf { it.volume } - combo.minOf { it.volume }

            return currentVolume.pow(2) * (1 + volumeDifference)
        }

        suspend fun exploreCombinations(
            currentCombo: List<ExerciseSet>,
            depth: Int = 1
        ) {

            if (currentCombo.size >= minSets) {
                mutex.withLock {
                    val currentScore = evaluateGeneralScore(currentCombo)
                    if (currentScore != Double.MAX_VALUE && bestScore != Double.MAX_VALUE) {
                        if (currentScore > bestScore) return
                    }

                    if (currentScore < bestScore) {
                        bestScore = currentScore
                        bestCombination = currentCombo
                    }
                }
            }

            if (depth >= maxSets) return

            val lastSet = currentCombo.last()

            val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.volume >= candidate.volume }

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

    private fun getNearAverageWeights(params: WeightExerciseParameters, offset: Int = 1): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        if (sortedWeights.size < 2) {
            return sortedWeights
        }

        var averageWeightPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }

        val closestWeightIndex = when {
            averageWeightPerRep.isNaN() || averageWeightPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(averageWeightPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - offset)..(closestWeightIndex + offset)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            var nearAverageWeights = getNearAverageWeights(params)

            nearAverageWeights.map { weight ->
                async(Dispatchers.Default) {
                    val expectedReps = maxRepsForWeight(weight,params.oneRepMax).roundToInt() + 2

                    params.repsRange
                        .filter { reps -> reps <= expectedReps }
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

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        volumeProgressionRange: FloatRange,
    ): ExerciseProgression? {
        val exerciseVolume = previousSets.sumOf { it.volume }

        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            previousTotalVolume = exerciseVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            volumeProgressionRange = volumeProgressionRange,
        )

        var currentExerciseProgression = getProgression(baseParams)
        if(currentExerciseProgression == null){
            return null
        }

        return currentExerciseProgression.copy(previousVolume = exerciseVolume)
    }
}
