package com.gabstra.myworkoutassistant.shared.utils

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
        val fatigue: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val usedOneRepMax: Double,
        val previousVolume: Double,
        val newFatigue : Double,
        val previousFatigue : Double
    )

    data class WeightExerciseParameters(
        var previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val repsRange: IntRange,
        val targetFatigue: Double,
        val maxWeight: Double,
        val progressionIncrease: Double
    )

    fun recalculateExerciseFatigue(
        existingSets: List<ExerciseSet>,
        fatigueFactor: Double = 0.005      // you’ll likely need a smaller factor here
    ): List<ExerciseSet> {
        //return existingSets

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
        val previousTotalVolume = params.previousSets.sumOf { it.volume }
        val previousTotalIntensity = params.previousSets.sumOf { it.intensity * it.reps  }

        val previousAverageWeightPerRep = previousTotalVolume / params.previousSets.sumOf { it.reps }

        val previousMaxWeight = params.previousSets.maxOf { it.weight }
        val previousMinWeight = params.previousSets.minOf { it.weight }

        val previousMaxVolume = params.previousSets.maxOf { it.volume }
        val previousMaxFatigue = params.previousSets.maxOf { it.fatigue }
        val previousMinFatigue = params.previousSets.minOf { it.fatigue }
        val previousMinVolume = params.previousSets.minOf { it.volume }

        val nearAverageWeights = params.previousSets.minOf { it.weight }   .. params.maxWeight
        val usableSets = possibleSets.filter { set -> set.weight in nearAverageWeights }

        fun calculateScore (combo: List<ExerciseSet>): Double {
            val currentTotalFatigue = combo.sumOf { it.fatigue }
            val currentAverageWeightPerRep = combo.sumOf { it.volume } / combo.sumOf { it.reps }

            val targetFatigueDifference = 1 + (abs(currentTotalFatigue - params.targetFatigue) / params.targetFatigue)
            val averageWeightPerRepDifference = 1 + (abs(currentAverageWeightPerRep - previousAverageWeightPerRep) / previousAverageWeightPerRep)
            val volumeCOV = 1 + combo.map { it.fatigue }.coefficientOfVariation()

            val maxVolumeDifference = combo.map {
                if(it.volume > previousMaxVolume) {
                    1 + ((it.volume - previousMaxVolume) / previousMaxVolume)
                } else {
                    1.0
                }
            }.reduce { acc, d -> acc * d }

            val differences = listOf(
                targetFatigueDifference,
                averageWeightPerRepDifference,
                volumeCOV,
                maxVolumeDifference
            )

            val geometricMean = differences.reduce { acc, d -> acc * d }.pow(1.0 / differences.size)

            return geometricMean
        }

        fun isValidProgression(combo: List<ExerciseSet>): Boolean{
            val prevF = params.previousSets.map { it.fatigue }
            val candF = combo.map { it.fatigue }

            for (i in combo.indices) {
                val wi = prevF[i] / previousTotalFatigue
                if (wi <= 0.0) continue
                val di = ((candF[i] - prevF[i]) / prevF[i]).round(2)
                val cap = (params.progressionIncrease / wi).round(2)
                if (di > cap) return false
            }
            return true
        }

        var result = findBestProgressions(
            usableSets.filter { it.volume >= previousMinVolume },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalFatigue = combo.sumOf { it.fatigue }
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = combo != params.previousSets && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isFatigueConditionMet = currentTotalFatigue.round(1) > previousTotalFatigue.round(1)
                val isFatigueLowerOrEqualToTarget = currentTotalFatigue < params.targetFatigue || currentTotalFatigue.isEqualTo(params.targetFatigue)

                isNotPrevious && isFatigueConditionMet && isFatigueLowerOrEqualToTarget && isValidProgression(combo)
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets.filter{ it.weight >= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }
                val isVolumeReducedEnough = currentTotalVolume in previousTotalVolume * 0.8 .. previousTotalVolume * 0.85

                val hasAtLeastOneSetWithHigherWeight = combo.any { it.weight > previousMaxWeight }

                isVolumeReducedEnough && hasAtLeastOneSetWithHigherWeight
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets.filter {  it.volume >= previousMinVolume },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalFatigue = combo.sumOf { it.fatigue }
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = combo != params.previousSets && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isFatigueConditionMet = currentTotalFatigue.round(1) > previousTotalFatigue.round(1)

                isNotPrevious && isFatigueConditionMet
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
            previousVolume = params.previousSets.sumOf { it.volume },
            newFatigue = validSetCombination.sumOf { it.fatigue },
            previousFatigue = params.previousSets.sumOf { it.fatigue }
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
                        val adjustedCombo = recalculateExerciseFatigue(currentCombo)

                        if (currentCombo.size >= minSets && isComboValid(adjustedCombo)) {
                            val currentScore = calculateScore(adjustedCombo)
                            if (currentScore < localBestScore) {
                                localBestScore = currentScore
                                localBestCombination = adjustedCombo
                            }
                        }

                        if (depth >= maxSets) return

                        val lastSet = currentCombo.last()
                        val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.fatigue >= candidate.fatigue }

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

        val fatigue = (reps * intensity).pow(1.5)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            fatigue = fatigue,
            intensity = intensity
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        targetFatigue: Double,
        progressionIncrease: Double
    ): ExerciseProgression? {
        val currentMaxWeight = previousSets.maxOf { it.weight }
        val maxWeight = availableWeights.filter { it > currentMaxWeight }.minOrNull() ?: currentMaxWeight

        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            repsRange = repsRange,
            targetFatigue = targetFatigue,
            maxWeight = maxWeight,
            progressionIncrease = progressionIncrease
        )

        val currentExerciseProgression = getProgression(baseParams)
        if(currentExerciseProgression == null){
            return null
        }

        return currentExerciseProgression
    }
}
