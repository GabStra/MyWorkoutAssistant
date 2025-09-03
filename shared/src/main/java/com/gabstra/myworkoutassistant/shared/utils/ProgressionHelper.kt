package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.calculateRIR
import com.gabstra.myworkoutassistant.shared.coefficientOfVariation
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
        val volume: Double,
        val rir: Int
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

        val previousTotalVolume = params.previousSets.sumOf { it.volume }
        val previousMaxWeight = params.previousSets.maxOf { it.weight }
        val previousMaxVolume = params.previousSets.maxOf { it.volume }

        val nearAverageWeights = params.previousSets.minOf { it.weight }   .. params.nextWeight
        val maxRir = maxOf(params.previousSets.maxOf { it.rir }, 2)

        val usableSets = possibleSets.filter { set -> set.weight in nearAverageWeights }

        fun calculateScore (combo: List<ExerciseSet>): Double {
            val currentTotalVolume = combo.sumOf { it.volume }

            val targetVolumeDifference = 1 + (abs(currentTotalVolume - params.targetVolume) / params.targetVolume)

            val targetVolumeOvershoot = if(currentTotalVolume > params.targetVolume) {
                1 + ((currentTotalVolume - params.targetVolume) / params.targetVolume)
            }else{
                1.0
            }

            val maxVolumeDifference = combo.map {
                if(it.volume > previousMaxVolume) {
                    1 + ((it.volume - previousMaxVolume) / previousMaxVolume)
                } else {
                    1.0
                }
            }.reduce { acc, d -> acc * d }

            val maxWeightDifference = combo.map {
                if(it.weight > previousMaxWeight) {
                    1 + ((it.weight - previousMaxWeight) / previousMaxWeight)
                } else {
                    1.0
                }
            }.reduce { acc, d -> acc * d }

            val relDeltas = combo.indices.map { i ->
                val pv = params.previousSets[i].volume
                if (pv == 0.0) 0.0 else (combo[i].volume - pv) / pv
            }

            val distributionPenalty = 1 + relDeltas.coefficientOfVariation()

            val differences = listOf(
                targetVolumeDifference,
                targetVolumeOvershoot,
                distributionPenalty,
                maxWeightDifference,
                maxVolumeDifference
            )

            val geometricMean = differences.reduce { acc, d -> acc * d }.pow(1.0 / differences.size)

            return geometricMean
        }

        fun isVolumeProportionallyIncreased(combo: List<ExerciseSet>): Boolean{
            val prevF = params.previousSets.map { it.volume }
            val candF = combo.map { it.volume }

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
            usableSets.filter { it.weight <= previousMaxWeight && it.rir <= maxRir },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = combo != params.previousSets && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(1) > previousTotalVolume.round(1)
                val isVolumeLowerOrEqualToTarget = currentTotalVolume < params.targetVolume || currentTotalVolume.isEqualTo(params.targetVolume)

                isNotPrevious && isVolumeHigherThanPrevious && isVolumeLowerOrEqualToTarget && isVolumeProportionallyIncreased(combo)
            }
        )

        if(result.isNotEmpty()) return result

        if(params.nextWeight == previousMaxWeight) return emptyList()

        result = findBestProgressions(
            usableSets.filter{ it.weight == params.nextWeight },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }
                val targetVolumeDifference = 1 + (abs(currentTotalVolume - previousTotalVolume * 0.8) / previousTotalVolume * 0.8)
                targetVolumeDifference
            },
            isComboValid = { combo ->
                val repsRange = combo.maxOf { it.reps } - combo.minOf { it.reps }
                repsRange == 0
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
            newVolume = validSetCombination.sumOf { it.volume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = params.previousSets.sumOf { it.volume }
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
                        val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight }

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
        val volume = weight * reps
        val intensity = weight / oneRepMax
        val rir = calculateRIR(weight,reps,oneRepMax)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            intensity = intensity,
            rir = rir
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
