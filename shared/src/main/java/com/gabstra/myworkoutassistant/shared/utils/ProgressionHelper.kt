package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.pow
import kotlin.math.roundToInt
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
        val volume: Double,
        val percentLoad: Double,
    )

    data class ExerciseData(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averagePercentLoad: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
        val isDeloading : Boolean
    )

    data class WeightExerciseParameters(
        val originalVolume: Double,
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val minimumVolume: Double,
        val minSets: Int,
        val maxSets: Int,
        val isDeload : Boolean
    )

    private suspend fun distributeVolume(
        params: WeightExerciseParameters,
    ): ExerciseData? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        val validSetCombination = findBestCombinationVariant(
            possibleSets,
            params.targetTotalVolume,
            params.minimumVolume,
            params.minSets,
            params.maxSets
        )
        if (validSetCombination.isEmpty()) return null

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseData(
            sets = validSetCombination,
            totalVolume = totalVolume,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            progressIncrease = ((totalVolume - params.originalVolume) / params.originalVolume) * 100,
            averagePercentLoad = validSetCombination.sumOf { it.percentLoad } / validSetCombination.size,
            originalVolume = params.originalVolume,
            isDeloading = params.isDeload
        )
    }

    data class Solution(
        val combination: List<ExerciseSet>,
        val volumeVariation: Double,
        val maxWeight: Double,
        val maxReps: Double,
        val maxSetVolume: Double,
        val maxAverageWeight: Double
    )

    private suspend fun findBestCombinationVariant(
        sets: List<ExerciseSet>,
        targetVolume: Double,
        minimumVolume: Double,
        minSets: Int,
        maxSets: Int,
        maxSolutions: Int = 10
    ) = coroutineScope {
        require(minSets > 0)
        require(minSets <= maxSets)
        require(maxSolutions > 0)

        val solutions = Collections.synchronizedList(ArrayList<Solution>(maxSolutions))

        val maxUsefulVolumePerSet = targetVolume / minSets  // Max useful volume per set

        val sortedSets = sets
            .asSequence()
            .filter { set ->
                set.volume < targetVolume &&
                set.volume <= maxUsefulVolumePerSet
            }
            .sortedByDescending { it.volume }
            .toList()

        if (sortedSets.size < minSets) {
            return@coroutineScope emptyList()
        }

        suspend fun searchChunk(startIdx: Int, endIdx: Int) = coroutineScope {
            flow {
                for (firstSetIdx in startIdx until endIdx) {
                    if (solutions.size >= maxSolutions) break

                    suspend fun buildCombination(
                        currentCombo: List<ExerciseSet>,
                        currentVolume: Double,
                        startFrom: Int,
                        depth: Int = 1
                    ) {
                        if (depth >= maxSets) return

                        val lastSet = currentCombo.last()
                        for (nextIdx in startFrom until sortedSets.size) {
                            if (solutions.size >= maxSolutions) return

                            val nextSet = sortedSets[nextIdx]

                            val isValidSequence = (lastSet.weight > nextSet.weight ||
                                    (lastSet.weight == nextSet.weight && lastSet.reps >= nextSet.reps))

                            if (isValidSequence) {
                                val newVolume = currentVolume + nextSet.volume

                                val newCombo = currentCombo + nextSet
                                if (newCombo.size >= minSets &&
                                    newVolume >= minimumVolume &&
                                    newVolume <= targetVolume) {
                                    emit(Pair(newVolume, newCombo))
                                }
                                buildCombination(newCombo, newVolume, nextIdx, depth + 1)
                            }
                        }
                    }

                    buildCombination(
                        listOf(sortedSets[firstSetIdx]),
                        sortedSets[firstSetIdx].volume,
                        firstSetIdx
                    )
                }
            }
                .buffer(100)
                .flowOn(Dispatchers.Default)
                .collect { (totalVolume, combo) ->
                    solutions.add(
                        Solution(
                            combination = combo,
                            maxWeight = combo.maxOf { it.weight },
                            maxReps = combo.maxOf { it.reps }.toDouble(),
                            maxSetVolume = combo.maxOf { it.volume },
                            volumeVariation = combo.maxOf { it.volume } - combo.minOf { it.volume },
                            maxAverageWeight = combo.sumOf { it.weight } / combo.size
                        )
                    )
                }
        }

        val numThreads = minOf(
            Runtime.getRuntime().availableProcessors(),
            (sortedSets.size + minSets - 1) / minSets
        )

        val chunkSize = (sortedSets.size + numThreads - 1) / numThreads

        (0 until numThreads)
            .map { threadIdx ->
                async(Dispatchers.Default) {
                    val startIdx = threadIdx * chunkSize
                    val endIdx = minOf(startIdx + chunkSize, sortedSets.size)
                    if (startIdx < endIdx) searchChunk(startIdx, endIdx)
                    else emptyList<ExerciseSet>() to Double.NEGATIVE_INFINITY
                }
            }
            .awaitAll()
        /*
        fun calculateCombinedScore(solutions: List<Solution>): List<Double> {
            // Z-score normalization for better statistical properties
            fun List<Double>.normalizeZScore(): List<Double> {
                val mean = average()
                val stdDev = sqrt(map { (it - mean) * (it - mean) }.average())
                return if (stdDev == 0.0) map { 0.0 } else map { (it - mean) / stdDev }
            }

            // Extract and normalize metrics
            val fatigueNorm = solutions.map { it.totalFatigue }.normalizeZScore()
            val variationNorm = solutions.map { it.volumeVariation }.normalizeZScore()

            // Return combined scores with emphasis on volume distribution
            return List(solutions.size) { index ->
                fatigueNorm[index] + variationNorm[index]
            }
        }
        */

        fun calculateCombinedScore(solutions: List<Solution>): List<Double> {
            fun List<Double>.normalize(): List<Double> {
                val min = minOrNull() ?: 0.0
                val max = maxOrNull() ?: 1.0
                val range = max - min
                return if (range == 0.0) map { 0.0 } else map { (it - min) / range }
            }

            fun List<Double>.normalizeZScore(): List<Double> {
                val mean = average()
                val stdDev = sqrt(map { (it - mean) * (it - mean) }.average())
                return if (stdDev == 0.0) map { 0.0 } else map { (it - mean) / stdDev }
            }

            // Extract and normalize metrics
            val maxWeightNorm = solutions.map { it.maxWeight }.normalize()
            val maxSetVolume = solutions.map { it.maxSetVolume }.normalize()

            val volumeVariationNorm = solutions.map { it.volumeVariation }.normalizeZScore()

            return List(solutions.size) { index ->
                maxWeightNorm[index] + maxSetVolume[index] + abs(volumeVariationNorm[index])
            }
        }

        if(solutions.isEmpty()) return@coroutineScope emptyList()

        val combinationScores = calculateCombinedScore(solutions)

        solutions.minByOrNull {
            combinationScores[solutions.indexOf(it)]
        }?.combination ?: emptyList()
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val minWeight = params.oneRepMax * (params.percentLoadRange.first / 100)
            val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)

            val weightRange =  params.availableWeights.filter { it in minWeight..maxWeight }

            val setsDeferred = weightRange.map { weight ->
                async(Dispatchers.Default) {
                    val loadPercentage = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - loadPercentage) / 0.0278).roundToInt()

                    params.repsRange
                        .filter { reps ->
                            reps <= expectedReps
                        }
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                                oneRepMax = params.oneRepMax,
                            )
                        }
                }
            }

            setsDeferred.awaitAll().flatten()
        }

    private fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
    ): ExerciseSet {
        val volume = weight * reps
        val relativeIntensity = weight / oneRepMax
        val percentLoad = relativeIntensity * 100

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            percentLoad = percentLoad,
        )
    }

    fun calculateTargetVolume(
        totalVolume: Double,
        desiredIncreasePercent: Float
    ): Double {
        val baseRate = (desiredIncreasePercent / 100).toDouble()

        // Volume factor using natural log to create progressive resistance
        val volumeFactor = (1.0 / (1.0 + ln(totalVolume))).coerceIn(0.3, 1.0)

        // Combined progression rate
        val progressionRate = (baseRate * volumeFactor)
            .coerceAtLeast(0.01)
            .coerceAtMost(baseRate)

        return totalVolume * (1 + progressionRate)
    }


    suspend fun generateExerciseProgression(
        totalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        desiredIncreasePercent: Float,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
    ): ExerciseData? {
        if (desiredIncreasePercent < 1) {
            throw IllegalArgumentException("Percentage increase must be higher or equal to 1")
        }

        /*val minimumRequiredVolume = calculateTargetVolume(
            totalVolume = totalVolume,
            desiredIncreasePercent = desiredIncreasePercent,
        )*/

        val params = WeightExerciseParameters(
            targetTotalVolume = totalVolume * 1.02,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            minimumVolume = totalVolume * 1.01,
            originalVolume = totalVolume,
            minSets = 3,
            maxSets = 4,
            isDeload = false
        )

        val result = distributeVolume(params)
        return result ?: distributeVolume(params.copy(minSets = 5, maxSets = 5))
    }

    suspend fun redistributeExerciseSets(
        totalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        upperVolumeRange: Double,
        lowerVolumeRange: Double,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        isDeload: Boolean,
        minSets: Int = 3,
        maxSets: Int = 4
    ): ExerciseData? {
        val params = WeightExerciseParameters(
            targetTotalVolume = upperVolumeRange,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            minimumVolume = lowerVolumeRange,
            originalVolume = totalVolume,
            minSets = minSets,
            maxSets = maxSets,
            isDeload = isDeload
        )

        val exerciseData = distributeVolume(params) ?: return null
        return exerciseData.copy(progressIncrease = 0.0)
    }
}
