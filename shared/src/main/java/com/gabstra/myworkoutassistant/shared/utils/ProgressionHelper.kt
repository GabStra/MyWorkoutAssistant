package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.isEqualTo
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.roundToInt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageIntensity: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
    )

    data class WeightExerciseParameters(
        val currentVolume: Double,
        val minVolumePerSet: Double,
        val currentAverageLoadPerRep: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val volumeProgressionRange: FloatRange,
        val averageLoadPerRepProgressionRange: FloatRange,
        val minSets: Int,
        val maxSets: Int,
    )

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()){
            Log.d("WorkoutViewModel", "No possible sets found")
            return null
        }

        //Log.d("WorkoutViewModel", "Possible sets: ${possibleSets.joinToString { "${it.weight} kg x ${it.reps}" }}")

        val maxSetVolume = possibleSets.maxOf { it.volume }
        val maxPossibleVolume = maxSetVolume * params.maxSets

        var validSetCombination = emptyList<ExerciseSet>()

        //Log.d("WorkoutViewModel", "Max possible volume: $maxPossibleVolume Exercise volume: ${params.exerciseVolume}")

        if(maxPossibleVolume < params.currentVolume) {
            val maxSet = possibleSets.maxByOrNull { it.volume }!!
            validSetCombination = List(params.maxSets) { maxSet }
        }

        //Log.d("WorkoutViewModel", "Possible sets: ${possibleSets.joinToString { "${it.weight} kg x ${it.reps}" }}")

        //Log.d("WorkoutViewModel", "Volume progression range: ${params.volumeProgressionRange}")
        //Log.d("WorkoutViewModel", "Average load per rep progression range: ${params.averageLoadPerRepProgressionRange}")

        if(validSetCombination.isEmpty()){
            validSetCombination = findBestProgressions(
                possibleSets,
                params.minSets,
                params.maxSets,
                params.currentAverageLoadPerRep,
                { totalVolume: Double, averageLoadPerRep: Double, minVolumePerSet: Double ->
                    ValidationResult(
                        shouldReturn = totalVolume.isEqualTo(params.currentVolume) && averageLoadPerRep.isEqualTo(params.currentAverageLoadPerRep)
                                || totalVolume < params.currentVolume * (1+params.volumeProgressionRange.from/100)
                                || totalVolume > params.currentVolume * (1+params.volumeProgressionRange.to/100)
                                || averageLoadPerRep < params.currentAverageLoadPerRep * (1+params.averageLoadPerRepProgressionRange.from/100)
                                || averageLoadPerRep > params.currentAverageLoadPerRep * (1+params.averageLoadPerRepProgressionRange.to/100)
                                // || minVolumePerSet < params.minVolumePerSet * 0.8,
                    )
                }
            )
        }

        if(validSetCombination.isEmpty()){
            return null
        }

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseProgression(
            sets = validSetCombination,
            totalVolume = totalVolume,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            progressIncrease = ((totalVolume - params.currentVolume) / params.currentVolume) * 100,
            averageIntensity = validSetCombination.map { it.weight }.average(),
            originalVolume = params.currentVolume,
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
        previousAverageLoadPerSet: Double,
        validationRules: (Double, Double,Double) -> ValidationResult,
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
            val totalVolume = combo.sumOf { it.volume }
            val averageLoadPerRep = if (combo.sumOf { it.reps } > 0) {
                totalVolume / combo.sumOf { it.reps }
            } else 0.0

            val volumes = combo.map { it.volume }
            val loadDifference = averageLoadPerRep - previousAverageLoadPerSet

            val validationResult = validationRules(totalVolume, averageLoadPerRep,volumes.min())
            if (validationResult.shouldReturn) {
                return validationResult.returnValue
            }

            val differences = mutableListOf<Double>()

            for (i in 0 until volumes.size - 1) {
                for (j in i + 1 until volumes.size) {
                    differences.add(abs(volumes[i] - volumes[j]))
                }
            }

            val volumeDifference = if (differences.isNotEmpty()) differences.max() else 0.0

            val loadDifferenceParam = 1 + loadDifference
            val volumeDifferenceParam = 1 + volumeDifference

            return totalVolume * (loadDifferenceParam * 10) * (volumeDifferenceParam * 10) * (combo.size * 10)
        }

        suspend fun exploreCombinations(
            currentCombo: List<ExerciseSet>,
            currentVolume: Double,
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

            /*
            val maxRemainingVolume = validSets.maxOfOrNull { it.volume } ?: 0.0
            val maxPossibleVolume = currentVolume + (maxSets - currentCombo.size) * maxRemainingVolume
            if (maxPossibleVolume < previousVolume) return
            */

            for (nextSet in validSets) {
                val newCombo = currentCombo + nextSet
                val newVolume = currentVolume + nextSet.volume
                exploreCombinations(newCombo, newVolume, depth + 1)
            }
        }

        suspend fun processSetRange(startIdx: Int, endIdx: Int) {
            for (firstSetIdx in startIdx until endIdx) {
                val firstSet = sortedSets[firstSetIdx]
                exploreCombinations(listOf(firstSet), firstSet.volume)
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

    private fun getNearAverageWeights(params: WeightExerciseParameters): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        if (sortedWeights.size < 2) {
            return sortedWeights  // Return all available weights if less than 2
        }

        val closestWeightIndex = when {
            params.currentAverageLoadPerRep.isNaN() || params.currentAverageLoadPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(params.currentAverageLoadPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - 1)..(closestWeightIndex + 1)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val nearAverageWeights = getNearAverageWeights(params)

            //Log.d("WorkoutViewModel", "Closest Weight Index: $closestWeightIndex Intensity: ${params.averageLoad} Near average weights: $nearAverageWeights")

            nearAverageWeights.map { weight ->
                async(Dispatchers.Default) {
                    val loadPercentage = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - loadPercentage) / 0.0278).roundToInt() + 1

                    params.repsRange
                        .filter { reps -> reps <= expectedReps }
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                            )
                        }
                }
            }.awaitAll().flatten()
        }

    private fun createSet(
        weight: Double,
        reps: Int,
    ): ExerciseSet {
        val volume = weight * reps

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
        )
    }

    suspend fun generateExerciseProgression(
        exerciseVolume: Double,
        minVolumePerSet: Double,
        averageLoadPerRep: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        volumeProgressionRange: FloatRange,
        averageLoadPerRepProgressionRange: FloatRange,
        minSets: Int = 3,
        maxSets: Int = 5,
    ): ExerciseProgression? {

        val baseParams = WeightExerciseParameters(
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            minVolumePerSet = minVolumePerSet,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            currentVolume = exerciseVolume,
            minSets = minSets,
            maxSets = maxSets,
            currentAverageLoadPerRep =  averageLoadPerRep,
            volumeProgressionRange = volumeProgressionRange,
            averageLoadPerRepProgressionRange = averageLoadPerRepProgressionRange,
        )

        return getProgression(baseParams)
    }
}
