package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.isEqualTo
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.exp
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
        val setVolumes: List<Double>,
        val setWorkloads: List<Double>,
        val setWeights: List<Double>,
        val totalReps: Int,
        val averageLoadPerRep: Double,
        val averageWorkloadPerRep: Double,
        val averageWorkloadPerSet: Double,
        val totalWorkload: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val workloadProgressionRange: FloatRange,
        val sets: Int,
    )

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        val minWorkload = params.totalWorkload * (1 + params.workloadProgressionRange.from / 100)
        val maxWorkload = params.totalWorkload * (1 + params.workloadProgressionRange.to / 100)

        var result = emptyList<ExerciseSet>()

        var currentSets = params.sets

        while(currentSets <=5){
            var result = findBestProgressions(
                possibleSets,
                currentSets,
                currentSets,
                params,
                { combo ->
                    val currentTotalWorkload = combo.sumOf { it.workload }

                    ValidationResult(
                        shouldReturn = currentTotalWorkload.isEqualTo(params.totalWorkload)
                                || currentTotalWorkload < minWorkload
                                || currentTotalWorkload > maxWorkload
                    )
                }
            )
            if (result.isNotEmpty()) return result
            currentSets++
        }

        currentSets = params.sets

        while(currentSets <=5){
            var result = findBestProgressions(
                possibleSets,
                currentSets,
                currentSets,
                params,
                { combo ->
                    val currentTotalWorkload = combo.sumOf { it.workload }

                    ValidationResult(
                        shouldReturn = currentTotalWorkload.isEqualTo(params.totalWorkload)
                                || currentTotalWorkload < minWorkload
                    )
                }
            )
            if (result.isNotEmpty()) return result
            currentSets++
        }

        return result
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()){
            return null
        }

        val validSetCombination = findValidProgression(params, possibleSets)

        if(validSetCombination.isEmpty()){
            return null
        }

        val currentTotalWorkload = validSetCombination.sumOf { it.workload }

        return ExerciseProgression(
            sets = validSetCombination,
            workload = currentTotalWorkload,
            usedOneRepMax = params.oneRepMax,
            progressIncrease = ((currentTotalWorkload - params.totalWorkload) / params.totalWorkload) * 100,
            originalWorkload = params.totalWorkload,
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

            val currentWorkload = combo.sumOf { it.workload }
            val workloadDifferenceScore = 1 + (combo.maxOf { it.workload } - combo.minOf { it.workload })

            return currentWorkload * workloadDifferenceScore
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

    private fun getNearAverageWeights(params: WeightExerciseParameters): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        if (sortedWeights.size < 2) {
            return sortedWeights  // Return all available weights if less than 2
        }

        val closestWeightIndex = when {
            params.averageLoadPerRep.isNaN() || params.averageLoadPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(params.averageLoadPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - 1)..(closestWeightIndex + 1)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            var nearAverageWeights = getNearAverageWeights(params)

            val maxIntensity = params.setWeights.max() / params.oneRepMax
            val maxWeight = (maxIntensity * 1.01) * params.oneRepMax

            // Filter out weights that are too high
            nearAverageWeights = nearAverageWeights.filter { it <= maxWeight }

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
        val effortMultiplier = exp(2.0 * intensity)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            intensity = intensity,
            workload = volume * effortMultiplier
        )
    }

    suspend fun generateExerciseProgression(
        setVolumes: List<Double>,
        setWorkloads: List<Double>,
        setWeights: List<Double>,
        totalReps: Int,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        workloadProgressionRange: FloatRange,
        sets: Int
    ): ExerciseProgression? {
        val exerciseVolume = setVolumes.sum()
        val exerciseWorkload = setWorkloads.sum()
        val averageLoadPerRep = exerciseVolume / totalReps
        val averateWorkloadPerRep = exerciseWorkload / totalReps
        val averageWorkloadPerSet = exerciseWorkload / setWorkloads.size

        val baseParams = WeightExerciseParameters(
            setVolumes = setVolumes,
            setWorkloads = setWorkloads,
            setWeights = setWeights,
            totalReps = totalReps,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            totalWorkload = exerciseWorkload,
            sets = sets,
            averageLoadPerRep =  averageLoadPerRep,
            averageWorkloadPerRep = averateWorkloadPerRep,
            workloadProgressionRange = workloadProgressionRange,
            averageWorkloadPerSet = averageWorkloadPerSet
        )

        return getProgression(baseParams)
    }
}
