package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.OneRM.calculateRIR
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlin.math.abs
import kotlin.math.pow


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val intensity: Double,
        val reps: Int,
        val relativeVolume: Double,
        val rir: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val usedOneRepMax: Double,
        val previousVolume: Double
    )

    data class WeightExerciseParameters(
        var previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val repsRange: IntRange,
        val targetVolume: Double,
        val nextWeight: Double,
        val progressionIncrease: Double
    )

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        val needsRebalance = params.previousSets.any { it.rir < 1 }

        if(needsRebalance){
            val nearAverageWeights = possibleSets.minOf { it.weight } * 0.75   ..  possibleSets.maxOf { it.weight }
            val usableSets = possibleSets.filter { set -> set.weight in nearAverageWeights && set.rir in 1.0..3.0 }

            val previousTotalVolume = params.previousSets.sumOf { it.relativeVolume }

            fun calculateScore (combo: List<ExerciseSet>): Double {
                val currentTotalVolume = combo.sumOf { it.relativeVolume }
                val targetVolumeDifference = 1 + abs((currentTotalVolume - previousTotalVolume) / previousTotalVolume)

                val currentAvgRir = combo.map { it.rir }.average()

                val avgRirDifference = 1 + abs((currentAvgRir - 1))

                val currentMinRir = combo.minOf { it.rir}
                val currentMaxRir = combo.maxOf { it.rir }

                val rirSpread = 1 + currentMaxRir - currentMinRir
                val relativeVolumeSpread = 1 + combo.maxOf { it.relativeVolume } - combo.minOf { it.relativeVolume }

                val differences = listOf(
                    targetVolumeDifference,
                    avgRirDifference,
                    rirSpread,
                    relativeVolumeSpread
                )

                val geometricMean = differences.reduce { acc, d -> acc * d }.pow(1.0 / differences.size)

                return geometricMean
            }

            params.previousSets = findBestProgressions(
                usableSets,
                params.previousSets.size,
                params.previousSets.size,
                params,
                calculateScore = { combo -> calculateScore(combo) },
                isComboValid = { combo ->
                    val currentTotalVolume = combo.sumOf { it.relativeVolume }
                    val isVolumeLowerOrEqualToTarget = currentTotalVolume < previousTotalVolume || currentTotalVolume.isEqualTo(previousTotalVolume)

                    isVolumeLowerOrEqualToTarget
                }
            )
        }

        val previousTotalVolume = params.previousSets.sumOf { it.relativeVolume }
        val previousMaxWeight = params.previousSets.maxOf { it.weight }

        val previousMinRir = params.previousSets.minOf { it.rir }
        val previousMaxRir = params.previousSets.maxOf { it.rir }

        val previousAverageRir = params.previousSets.map { it.rir }.average()

        val nearAverageWeights = possibleSets.minOf { it.weight }    .. params.nextWeight

        val usableSets = possibleSets.filter { set -> set.weight in nearAverageWeights && set.rir in 1.0..3.0 }

        fun calculateScore (combo: List<ExerciseSet>): Double {
            val currentTotalVolume = combo.sumOf { it.relativeVolume }
            val targetVolumeDifference = 1 + abs((currentTotalVolume - params.targetVolume)/params.targetVolume)

            val currentAvgRir = combo.map { it.rir }.average()

            val avgRirDifference = 1 + abs((currentAvgRir - previousAverageRir))

            val currentMinRir = combo.minOf { it.rir}
            val currentMaxRir = combo.maxOf { it.rir }

            val underMinPenalty = 1 + abs(currentMinRir - previousMinRir)
            val overMaxPenalty = 1 + abs(currentMaxRir - previousMaxRir)

            val rirSpread = 1 + currentMaxRir - currentMinRir
            val relativeVolumeSpread = 1 + combo.maxOf { it.relativeVolume } - combo.minOf { it.relativeVolume }

            val differences = listOf(
                targetVolumeDifference,
                avgRirDifference,
                underMinPenalty,
                overMaxPenalty,
                rirSpread,
                relativeVolumeSpread
            )

            val geometricMean = differences.reduce { acc, d -> acc * d }.pow(1.0 / differences.size)

            return geometricMean
        }

        fun isVolumeProportionallyIncreased(combo: List<ExerciseSet>): Boolean{
            val prevF = params.previousSets.map { it.relativeVolume }
            val candF = combo.map { it.relativeVolume }

            for (i in combo.indices) {
                val wi = prevF[i] / previousTotalVolume
                if (wi <= 0.0) continue
                val di = ((candF[i] - prevF[i]) / prevF[i]).round(2)
                val cap = (params.progressionIncrease / wi).round(2)
                if (di > cap) return false
            }
            return true
        }

        var result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.relativeVolume }

                val isNotPrevious = combo != params.previousSets && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(1) > previousTotalVolume.round(1)
                val isVolumeLowerOrEqualToTarget = currentTotalVolume < params.targetVolume || currentTotalVolume.isEqualTo(params.targetVolume)

                isNotPrevious  && isVolumeLowerOrEqualToTarget && isVolumeProportionallyIncreased(combo)
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets. filter { it.rir >= previousMinRir },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.relativeVolume }

                val isNotPrevious = combo != params.previousSets && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(1) > previousTotalVolume.round(1)
                val isVolumeLowerOrEqualToTarget = currentTotalVolume < params.targetVolume || currentTotalVolume.isEqualTo(params.targetVolume)

                isNotPrevious && isVolumeHigherThanPrevious && isVolumeLowerOrEqualToTarget && isVolumeProportionallyIncreased(combo)
            }
        )

        if(result.isNotEmpty()) return result

        if(params.nextWeight != previousMaxWeight) {
            result = findBestProgressions(
                usableSets.filter { it.weight >= previousMaxWeight },
                params.previousSets.size,
                params.previousSets.size,
                params,
                calculateScore = { combo -> calculateScore(combo) },
                isComboValid = { combo ->
                    val atLeastOneSetWithHigherWeight = combo.any { it.weight > previousMaxWeight }
                    val repsSpread = combo.maxOf { it.reps } - combo.minOf { it.reps }

                    val currentTotalVolume = combo.sumOf { it.relativeVolume }
                    val currentAverageRir = combo.map { it.rir }.average()

                    atLeastOneSetWithHigherWeight && repsSpread <= 1 && currentTotalVolume < previousTotalVolume && currentAverageRir <= previousAverageRir
                }
            )

            if(result.isNotEmpty()) return result
        }

        result = findBestProgressions(
            usableSets,
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.relativeVolume }

                val isNotPrevious = combo != params.previousSets && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(1) > previousTotalVolume.round(1)

                isNotPrevious && isVolumeHigherThanPrevious && isVolumeProportionallyIncreased(combo)
            }
        )

        return result
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        val possibleSets = generatePossibleSets(params)
        val validSetCombination = findValidProgression(params, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume = validSetCombination.sumOf { it.relativeVolume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = params.previousSets.sumOf { it.relativeVolume }
        )
    }

    private suspend fun findBestProgressions(
        sets: List<ExerciseSet>,
        minSets: Int,
        maxSets: Int,
        params: WeightExerciseParameters,
        calculateScore: (List<ExerciseSet>) -> Double,
        isComboValid: (List<ExerciseSet>) -> Boolean = { true },
    ) = coroutineScope {
        require(minSets > 0) { "Minimum sets must be positive" }
        require(minSets <= maxSets) { "Minimum sets cannot exceed maximum sets" }

        if (sets.isEmpty()) return@coroutineScope emptyList()

        val sortedSets = sets.sortedWith(
            compareByDescending<ExerciseSet> { it.weight }
                .thenByDescending { it.reps }
        )

        val localBestResults = (0 until Runtime.getRuntime().availableProcessors())
            .map { threadIdx ->
                async(Dispatchers.Default) {
                    var localBestCombination: List<ExerciseSet>? = null
                    var localBestScore = Double.MAX_VALUE

                    fun exploreCombinations(
                        currentCombo: List<ExerciseSet>,
                        depth: Int = 1
                    ) {
                        if (currentCombo.size >= minSets && isComboValid(currentCombo)) {
                            val currentScore = calculateScore(currentCombo)
                            if (currentScore < localBestScore) {
                                localBestScore = currentScore
                                localBestCombination = currentCombo
                            }
                        }

                        if (depth >= maxSets) return

                        val lastSet = currentCombo.last()
                        val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.rir <= candidate.rir }

                        for (nextSet in validSets) {
                            exploreCombinations(currentCombo + nextSet, depth + 1)
                        }
                    }

                    val processorCount = Runtime.getRuntime().availableProcessors()
                    val effectiveParallelism = minOf(processorCount, sortedSets.size)
                    val chunkSize = (sortedSets.size + effectiveParallelism - 1) / effectiveParallelism
                    val startIdx = threadIdx * chunkSize
                    val endIdx = minOf(startIdx + chunkSize, sortedSets.size)

                    if (startIdx < endIdx) {
                        for (firstSetIdx in startIdx until endIdx) {
                            exploreCombinations(listOf(sortedSets[firstSetIdx]))
                        }
                    }

                    return@async localBestCombination
                }
            }
            .awaitAll()

        return@coroutineScope localBestResults
            .filterNotNull()
            .minByOrNull { combo -> calculateScore(combo) } ?: emptyList()
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val sortedWeights = params.availableWeights.sorted()
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
        val intensity = weight / oneRepMax
        val rir = calculateRIR(weight,reps,oneRepMax)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            relativeVolume = intensity * reps,
            intensity = intensity,
            rir = rir.round(2)
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        targetVolume: Double,
        progressionIncrease: Double
    ): ExerciseProgression? {
        val previousMaxWeight = previousSets.maxOf { it.weight }
        val nextWeight = availableWeights.filter { it > previousMaxWeight }.minOrNull() ?: previousMaxWeight

        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            repsRange = repsRange,
            targetVolume = targetVolume,
            nextWeight = nextWeight,
            progressionIncrease = progressionIncrease
        )

        val currentExerciseProgression = getProgression(baseParams)
        if(currentExerciseProgression == null){
            return null
        }

        return currentExerciseProgression
    }
}
