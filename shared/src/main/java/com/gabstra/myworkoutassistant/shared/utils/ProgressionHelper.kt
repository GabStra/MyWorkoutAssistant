package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.isEqualTo
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.pow
import kotlin.math.roundToInt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val intensity: Double,
        val workload: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val workload: Double,
        val usedOneRepMax: Double,
        val progressIncrease: Double,
        val originalWorkload: Double,
    )

    data class WeightExerciseParameters(
        val previousAverageLoadPerRep: Double,
        val previousAverageWorkloadPerSet: Double,
        val previousSessionWorkload: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val workloadProgressionRange: FloatRange,
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

        //val maxSetVolume = possibleSets.maxOf { it.volume }


        var validSetCombination = emptyList<ExerciseSet>()

        //Log.d("WorkoutViewModel", "Max possible volume: $maxPossibleVolume Exercise volume: ${params.exerciseVolume}")

/*
        val maxPossibleVolume = maxSetVolume * params.maxSets
        if(maxPossibleVolume < params.previousSessionWorkload) {
            val maxSet = possibleSets.maxByOrNull { it.volume }!!
            validSetCombination = List(params.maxSets) { maxSet }
        }*/

        //Log.d("WorkoutViewModel", "Possible sets: ${possibleSets.joinToString { "${it.weight} kg x ${it.reps}" }}")

        //Log.d("WorkoutViewModel", "Volume progression range: ${params.volumeProgressionRange}")
        //Log.d("WorkoutViewModel", "Average load per rep progression range: ${params.averageLoadPerRepProgressionRange}")

        validSetCombination = findBestProgressions(
            possibleSets,
            params.minSets,
            params.maxSets,
            params.previousAverageWorkloadPerSet,
            params.previousAverageLoadPerRep,
            { combo: List<ExerciseSet> ->
                val currentSessionWorkload = combo.sumOf { it.workload }
                val currentAverageLoadPerRep = combo.sumOf { it.volume } / combo.sumOf { it.reps }

                ValidationResult(
                    shouldReturn = currentAverageLoadPerRep < params.previousAverageLoadPerRep
                            ||currentSessionWorkload.isEqualTo(params.previousSessionWorkload)
                            || currentSessionWorkload < params.previousSessionWorkload * (1+params.workloadProgressionRange.from/100)
                            || currentSessionWorkload > params.previousSessionWorkload * (1+params.workloadProgressionRange.to/100)
                )
            }
        )

        if(validSetCombination.isEmpty() && params.maxSets < 5){
            validSetCombination = findBestProgressions(
                possibleSets,
                params.maxSets,
                5,
                params.previousAverageWorkloadPerSet,
                params.previousAverageLoadPerRep,
                { combo: List<ExerciseSet> ->
                    val currentSessionWorkload = combo.sumOf { it.workload }
                    val currentAverageLoadPerRep = combo.sumOf { it.volume } / combo.sumOf { it.reps }

                    ValidationResult(
                        shouldReturn = currentAverageLoadPerRep < params.previousAverageLoadPerRep
                                || currentSessionWorkload.isEqualTo(params.previousSessionWorkload)
                                || currentSessionWorkload < params.previousSessionWorkload * (1+params.workloadProgressionRange.from/100)
                                || currentSessionWorkload > params.previousSessionWorkload * (1+params.workloadProgressionRange.to/100)
                    )
                }
            )
        }

        if(validSetCombination.isEmpty()){
            return null
        }

        val currentWorkload = validSetCombination.sumOf { it.workload }

        return ExerciseProgression(
            sets = validSetCombination,
            workload = currentWorkload,
            usedOneRepMax = params.oneRepMax,
            progressIncrease = ((currentWorkload - params.previousSessionWorkload) / params.previousSessionWorkload) * 100,
            originalWorkload = params.previousSessionWorkload,
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
        previousAverageWorkloadPerSet: Double,
        previousAverageLoadPerRep: Double,
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

            val currentWorkload = combo.sumOf { it.workload }
            //val currentAverageWorkloadPerSet = currentWorkload / combo.size
            val currentAverageLoadPerRep = combo.sumOf { it.volume } / combo.sumOf { it.reps }

            //val progressScore = 1 + abs(currentWorkload - previousSessionWorkload)
            val workloadDifferenceScore = 1 + (combo.maxOf { it.workload } - combo.minOf { it.workload })
            //val workloadPerSetScore = 1 + abs(currentAverageWorkloadPerSet - previousAverageWorkloadPerSet)

            val loadChangeScore =  1 + abs(currentAverageLoadPerRep - previousAverageLoadPerRep)
            return currentWorkload * loadChangeScore * workloadDifferenceScore * 10.0.pow(combo.size)
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
            val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.workload >= candidate.workload }

            /*
            val maxRemainingVolume = validSets.maxOfOrNull { it.volume } ?: 0.0
            val maxPossibleVolume = currentVolume + (maxSets - currentCombo.size) * maxRemainingVolume
            if (maxPossibleVolume < previousVolume) return
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

    private fun getNearAverageWeights(params: WeightExerciseParameters): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        if (sortedWeights.size < 2) {
            return sortedWeights  // Return all available weights if less than 2
        }

        val closestWeightIndex = when {
            params.previousAverageLoadPerRep.isNaN() || params.previousAverageLoadPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(params.previousAverageLoadPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - 1)..(closestWeightIndex + 1)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            //val sortedWeights = params.availableWeights.sorted()

            val nearAverageWeights = getNearAverageWeights(params)

            //Log.d("WorkoutViewModel", "Closest Weight Index: $closestWeightIndex Intensity: ${params.averageLoad} Near average weights: $nearAverageWeights")

            nearAverageWeights.map { weight ->
                async(Dispatchers.Default) {
                    val intensity = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - intensity) / 0.0278).roundToInt() + 1

                    params.repsRange
                        .filter { reps -> reps <= expectedReps }
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                                intensity = intensity
                            )
                        }
                }
            }.awaitAll().flatten()
        }

    private fun createSet(
        weight: Double,
        reps: Int,
        intensity: Double
    ): ExerciseSet {
        val volume = weight * reps
        val param = (1 + intensity) * (1 + intensity)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            intensity = intensity,
            workload = volume * param
        )
    }

    suspend fun generateExerciseProgression(
        exerciseWorkload: Double,
        averageLoadPerRep: Double,
        averageWorkloadPerSet: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        workloadProgressionRange: FloatRange,
        minSets: Int = 3,
        maxSets: Int = 5,
    ): ExerciseProgression? {

        val baseParams = WeightExerciseParameters(
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            previousSessionWorkload = exerciseWorkload,
            minSets = minSets,
            maxSets = maxSets,
            previousAverageLoadPerRep =  averageLoadPerRep,
            workloadProgressionRange = workloadProgressionRange,
            previousAverageWorkloadPerSet = averageWorkloadPerSet
        )

        return getProgression(baseParams)
    }
}
