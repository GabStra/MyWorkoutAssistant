package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sqrt


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
        val exerciseVolume: Double,
        val averageLoad: Double,
        val baselineReps: Int,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        //val maxWeightFromOneRepMax: Double,
        val repsRange: IntRange,
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

        if(maxPossibleVolume < params.exerciseVolume) {
            val maxSet = possibleSets.maxByOrNull { it.volume }!!
            validSetCombination = List(params.maxSets) { maxSet }
        }

        //Log.d("WorkoutViewModel", "Possible sets: ${possibleSets.joinToString { "${it.weight} kg x ${it.reps}" }}")

        if(validSetCombination.isEmpty()){
            validSetCombination = findBestProgressions(
                possibleSets,
                params.minSets,
                params.maxSets,
                params.exerciseVolume,
                params.averageLoad,
                params.baselineReps,
                { totalVolume: Double, averageLoad: Double ->
                    ValidationResult(
                        shouldReturn = totalVolume < params.exerciseVolume * 1.005 || totalVolume > params.exerciseVolume * 1.01 || averageLoad < params.averageLoad * .95
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
            progressIncrease = ((totalVolume - params.exerciseVolume) / params.exerciseVolume) * 100,
            averageIntensity = validSetCombination.map { it.weight }.average(),
            originalVolume = params.exerciseVolume,
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
        previousVolume: Double,
        previousAverageLoad: Double,
        baselineReps: Int,
        validationRules: (Double, Double) -> ValidationResult,
        scoreThreshold: Double = 1.001,
        weightCoefficientVariation: Double = 10.0,
        weightRepsPenalty: Double = 10.0
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
        var bestComboScore = Double.MAX_VALUE

        fun evaluateVolumeScore(combo: List<ExerciseSet>): Double {
            val totalVolume = combo.sumOf { it.volume }
            val averageLoad = if (combo.sumOf { it.reps } > 0) {
                totalVolume / combo.sumOf { it.reps }
            } else 0.0

            val validationResult = validationRules(totalVolume, averageLoad)
            if (validationResult.shouldReturn) {
                return validationResult.returnValue
            }

            return totalVolume * combo.size
        }

        fun evaluateHomogeneityScore(combo: List<ExerciseSet>): Double {
            val volumes = combo.map { it.volume }
            val meanVolume = volumes.average()

            val stdDevVolume = if (volumes.size > 1) {
                sqrt(volumes.sumOf { (it - meanVolume).pow(2.0) } / volumes.size)
            } else 0.0
            val cvVolumes = if (meanVolume > 0.0) stdDevVolume / meanVolume else 0.0

            val repsPenalty = combo.sumOf {
                if (it.reps > baselineReps) (it.reps - baselineReps).toDouble() else 0.0
            }

            return weightCoefficientVariation * cvVolumes.pow(2.0) + weightRepsPenalty * repsPenalty
        }

        suspend fun exploreCombinations(
            currentCombo: List<ExerciseSet>,
            currentVolume: Double,
            depth: Int = 1
        ) {
            if (depth >= maxSets) return

            val currentScore = evaluateVolumeScore(currentCombo)
            if (currentScore != Double.MAX_VALUE && bestScore != Double.MAX_VALUE) {
                if (currentScore > bestScore * scoreThreshold) return
            }

            val lastSet = currentCombo.last()

            val validSets = sortedSets.filter { candidate ->
                (lastSet.weight > candidate.weight && lastSet.volume >= candidate.volume) ||
                        (lastSet.weight == candidate.weight && lastSet.reps >= candidate.reps)
            }

            val maxRemainingVolume = validSets.maxOfOrNull { it.volume } ?: 0.0
            val maxPossibleVolume = currentVolume + (maxSets - currentCombo.size) * maxRemainingVolume
            if (maxPossibleVolume < previousVolume) return

            for (nextSet in validSets) {
                val newCombo = currentCombo + nextSet
                val newVolume = currentVolume + nextSet.volume

                if (newCombo.size >= minSets) {
                    val newScore = evaluateVolumeScore(newCombo)
                    val newComboScore = evaluateHomogeneityScore(newCombo)

                    mutex.withLock {
                        if (bestScore != Double.MAX_VALUE && newScore <= bestScore * scoreThreshold) {
                            if (newComboScore < bestComboScore) {
                                bestScore = newScore
                                bestCombination = newCombo
                                bestComboScore = newComboScore
                            }
                        } else if (newScore < bestScore) {
                            bestScore = newScore
                            bestCombination = newCombo
                            bestComboScore = newComboScore
                        }
                    }
                }

                if (newCombo.size < maxSets) {
                    exploreCombinations(newCombo, newVolume, depth + 1)
                }
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
            params.averageLoad.isNaN() || params.averageLoad.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(params.averageLoad)
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
        averageLoad: Double,
        baselineReps: Int,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        minSets: Int = 3,
        maxSets: Int = 5,
    ): ExerciseProgression? {
        //val maxWeightFromOneRepMax = oneRepMax * (maxLoadPercent / 100)

        val baseParams = WeightExerciseParameters(
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            //maxWeightFromOneRepMax = maxWeightFromOneRepMax,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            exerciseVolume = exerciseVolume,
            minSets = minSets,
            maxSets = maxSets,
            averageLoad =  averageLoad,
            baselineReps = baselineReps,
        )

        return getProgression(baseParams)
    }
}
