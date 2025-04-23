package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.calculateOneRepMax
import com.gabstra.myworkoutassistant.shared.calculateRIR
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.maxRepsForWeight
import com.gabstra.myworkoutassistant.shared.median
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.roundToInt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val rir: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val usedOneRepMax: Double,
        val previousVolume: Double,
        val medianRIR: Double
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

        var result = emptyList<ExerciseSet>()

        var currentSets = 3

        while(currentSets <= 5){
            var minVolumePerSet = (minTotalVolume / currentSets) * 0.75
            var maxVolumePerSet = (maxTotalVolume / currentSets) * 1.25

            var currentPossibleSets = possibleSets.filter { set ->
                set.volume in minVolumePerSet..maxVolumePerSet
            }

            //Log.d("WorkoutViewModel", "Current Possible sets: ${possibleSets.joinToString(", ") { "${it.weight}x${it.reps}" }}")

            var result = findBestProgressions(
                currentPossibleSets,
                currentSets,
                currentSets,
                params,
                { combo ->
                    val currentTotalVolume = combo.sumOf { it.volume }

                    ValidationResult(
                        shouldReturn = currentTotalVolume.isEqualTo(params.previousTotalVolume)
                                || currentTotalVolume < minTotalVolume
                                || currentTotalVolume > maxTotalVolume
                    )
                }
            )
            if (result.isNotEmpty()){
                return result
            }
            currentSets++
        }

        return result
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var offset = 1

        var validSetCombination = emptyList<ExerciseSet>()

        while (offset<=5){
            var possibleSets = generatePossibleSets(params,offset)
            validSetCombination = findValidProgression(params, possibleSets)

            if(validSetCombination.isNotEmpty()){
                break
            }
            offset++
        }


        return ExerciseProgression(
            sets = validSetCombination,
            newVolume =  validSetCombination.sumOf { it.volume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = params.previousTotalVolume,
            medianRIR = validSetCombination.map { it.rir }.median()
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

        val previousAverageLoadPerSet = params.previousSets.sumOf { it.volume } / params.previousSets.size
        val previousAverageLoadPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }

        fun evaluateGeneralScore(combo: List<ExerciseSet>): Double {
            val validationResult = validationRules(combo)
            if (validationResult.shouldReturn)  return validationResult.returnValue

            val currentVolume = combo.sumOf { it.volume }
            val volumeDifferenceScore = 1 + (combo.maxOf { it.volume } - combo.minOf { it.volume })

            val totalRIR = combo.sumOf { it.rir }

            val currentAverageLoadPerSet = currentVolume / combo.size
            val currentAverageLoadPerRep = currentVolume/ combo.sumOf { it.reps }

            val loadPerSetDifferenceScore = 1 + (abs(currentAverageLoadPerSet - previousAverageLoadPerSet))
            val loadPerRepDifferenceScore = 1 + (abs(currentAverageLoadPerRep - previousAverageLoadPerRep))

            return currentVolume * volumeDifferenceScore * (1 + totalRIR) * loadPerSetDifferenceScore * loadPerRepDifferenceScore
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

            /*
            val maxRemainingVolume = validSets.maxOfOrNull { it.volume } ?: 0.0
            val maxPossibleVolume = currentVolume + (maxSets - currentCombo.size) * maxRemainingVolume
            if (maxPossibleVolume < Volume) return
            */

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

    private fun getNearAverageWeights(params: WeightExerciseParameters, offset: Int ): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        require(offset >= 0) { "Offset must be non-negative" }

        var averageLoadPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }

        if (sortedWeights.size < 2) {
            return sortedWeights  // Return all available weights if less than 2
        }

        val closestWeightIndex = when {
            averageLoadPerRep.isNaN() || averageLoadPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(averageLoadPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - offset)..(closestWeightIndex + offset)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters,offset: Int): List<ExerciseSet> =
        coroutineScope {
            var nearAverageWeights = getNearAverageWeights(params,offset)

            nearAverageWeights.map { weight ->
                async(Dispatchers.Default) {
                    val expectedReps = maxRepsForWeight(weight,params.oneRepMax).roundToInt()

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
            volume = volume,
            rir = calculateRIR(
                weight = weight,
                reps = reps,
                oneRepMax = oneRepMax
            )
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
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

        while(true) {
            if (currentExerciseProgression!!.medianRIR <= 1.0) {
                break
            }

            var oneRepMax = currentExerciseProgression.sets.maxOf {
                calculateOneRepMax(it.weight, it.reps)
            }

            var newParams = baseParams.copy(
                previousSets = currentExerciseProgression.sets,
                previousTotalVolume = currentExerciseProgression.newVolume,
                oneRepMax = max(oneRepMax, currentExerciseProgression.usedOneRepMax),
            )

            var possibleExerciseProgression = getProgression(newParams)
            if(possibleExerciseProgression == null){
                break
            }else{
                currentExerciseProgression = possibleExerciseProgression
            }
        }

        return currentExerciseProgression.copy(previousVolume = exerciseVolume)
    }
}
