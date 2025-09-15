package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlin.math.abs


object ProgressionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val previousVolume: Double
    )

    data class ProgressionParameters(
        var previousSets:  List<ProgressionHelper.ExerciseSet>,
        val availableWeights: Set<Double>,
        val repsRange: IntRange,
        val progressionIncrease: Double
    )

    data class DeloadParameters(
        var previousSets:  List<ProgressionHelper.ExerciseSet>,
        val availableWeights: Set<Double>,
        val repsRange: IntRange,
        val targetVolume: Double
    )

    private fun toWeightRepsMultiset(
        sets: List<ExerciseSet>,
        decimals: Int = 2
    ): Map<Pair<Double, Int>, Int> =
        sets.groupingBy { it.weight.round(decimals) to it.reps }.eachCount()

    private fun sameMultisetByWeightReps(
        a: List<ExerciseSet>,
        b: List<ExerciseSet>,
        decimals: Int = 2
    ): Boolean =
        toWeightRepsMultiset(a, decimals) == toWeightRepsMultiset(b, decimals)

    private fun calculateScore(combo: List<ExerciseSet>, targetVolume :Double, previousAvgIntensity: Double, previousMaxSetVolume: Double, previousMaxWeight: Double): Double {
        val eps = 1e-9
        val totalVol = combo.sumOf { it.volume }
        val totalReps = combo.sumOf { it.reps }
        val avgInt = totalVol / totalReps.coerceAtLeast(1)

        // Normalized deviations (0 = perfect, ~1 = poor fit)
        val volDiff = abs((totalVol - targetVolume) / targetVolume.coerceAtLeast(eps))
        val intDiff = abs(avgInt - previousAvgIntensity) / previousAvgIntensity.coerceAtLeast(eps)

        // Volume variance across sets (lower is better)
        val setCount = combo.size.coerceAtLeast(1)
        val meanVolPerSet = totalVol / setCount
        val variance = if (combo.isEmpty()) 0.0
        else combo.sumOf { val d = it.volume - meanVolPerSet; d * d } / setCount
        val stdDev = kotlin.math.sqrt(variance)
        val cv = stdDev / meanVolPerSet.coerceAtLeast(eps) // 0 = perfectly even volumes

        // Convert to "fit scores" ≥ 1 (1 is best)
        val volFit = 1 + volDiff.coerceAtMost(1.0)
        val intFit = 1 + intDiff.coerceAtMost(1.0)
        val varFit = 1 + cv.coerceAtMost(1.0)

        val fits = listOf(volFit, intFit, varFit)

        // Weighted geometric mean
        val weights = listOf(0.5, 0.25, 0.25)
        val logSum = weights.zip(fits).sumOf { (w, f) -> w * kotlin.math.ln(f) }
        val baseScore = kotlin.math.exp(logSum)

        // Penalties
        val penaltyFactor = 100.0

        val totalExcessVolume = combo.filter { it.volume >= previousMaxSetVolume }
            .sumOf {  1.0 + (it.volume - previousMaxSetVolume) }
        val volumePenalty = totalExcessVolume * penaltyFactor

        val weightPenaltyUnits = combo
            .filter { it.weight > previousMaxWeight }
            .sumOf { 1.0 + (it.weight - previousMaxWeight)}
        val weightPenalty = weightPenaltyUnits * penaltyFactor

        /* val lowerWeightPenalty = combo
             .filter { it.weight < previousMaxWeight }
             .sumOf { 1.0 + (previousMaxWeight - it.weight) }
         val lowerWeightPenaltyWeight = lowerWeightPenalty * penaltyFactor*/

        return baseScore + volumePenalty + weightPenalty
    }


    private  suspend fun findValidProgression(
        params: ProgressionParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        val previousTotalVolume = params.previousSets.sumOf { it.volume }
        val targetVolume = previousTotalVolume * params.progressionIncrease

        val previousMinWeight = params.previousSets.minOf { it.weight }
        val previousMaxWeight = params.previousSets.maxOf { it.weight }

        val previousMaxSetVolume = params.previousSets.maxOf { it.volume }

        val previousAvgIntensity = previousTotalVolume / params.previousSets.sumOf { it.reps }

        val weightLowerThanPrevious = params.availableWeights
            .filter { it < previousMaxWeight }
            .minByOrNull { abs(it - (previousMaxWeight * 0.95)) }
            ?: Double.NEGATIVE_INFINITY

        val nextWeightUp =  params.availableWeights
            .filter { it > previousMaxWeight }
            .minByOrNull { abs( it - (previousMaxWeight * 1.05)) }
            ?: Double.MAX_VALUE

        val usableSets = possibleSets.filter { it.weight in weightLowerThanPrevious..nextWeightUp }

        var result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo -> calculateScore(combo, targetVolume, previousAvgIntensity, previousMaxSetVolume, previousMaxWeight) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)
                val isVolumeLowerOrEqualToTarget = currentTotalVolume.round(2) <= targetVolume.round(2)
                val oneSetUsesPreviousMaxWeightOrHigher = combo.any { it.weight >= previousMaxWeight }

                isNotPrevious && isVolumeHigherThanPrevious && isVolumeLowerOrEqualToTarget && oneSetUsesPreviousMaxWeightOrHigher
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo ->  calculateScore(combo, targetVolume, previousAvgIntensity, previousMaxSetVolume, previousMaxWeight) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)
                val oneSetUsesPreviousMaxWeightOrHigher = combo.any { it.weight >= previousMaxWeight }

                isNotPrevious && isVolumeHigherThanPrevious && oneSetUsesPreviousMaxWeightOrHigher
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets,
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo -> calculateScore(combo, targetVolume, previousAvgIntensity, previousMaxSetVolume, previousMaxWeight) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)
                val oneSetUsesPreviousMaxWeightOrHigher = combo.any { it.weight >= previousMaxWeight }

                isNotPrevious && isVolumeHigherThanPrevious && oneSetUsesPreviousMaxWeightOrHigher
            }
        )

        return result
    }

    private suspend fun findDeload(
        params: DeloadParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        val previousTotalVolume = params.previousSets.sumOf { it.volume }
        val targetVolume = params.targetVolume

        val previousMaxWeight = params.previousSets.maxOf { it.weight }

        val previousMaxSetVolume = params.previousSets.maxOf { it.volume }

        val previousAvgIntensity = previousTotalVolume / params.previousSets.sumOf { it.reps }

        val usableSets = possibleSets.filter { it.weight <= previousMaxWeight }

        val result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo -> calculateScore(combo, targetVolume, previousAvgIntensity, previousMaxSetVolume, previousMaxWeight) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeLowerThanPrevious = currentTotalVolume.round(2) < previousTotalVolume.round(2)

                isNotPrevious && isVolumeLowerThanPrevious
            }
        )

        return result
    }

    private suspend fun findBestProgressions(
        sets: List<ExerciseSet>,
        minSets: Int,
        maxSets: Int,
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

                        val maxVolume = currentCombo[0].volume

                        val lastSet = currentCombo.last()
                        val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && candidate.volume.round(2) in (maxVolume * 0.8).round(2)..(maxVolume * 1.2).round(2) }

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

    private suspend fun generatePossibleSets(availableWeights: Set<Double>, repsRange: IntRange): List<ExerciseSet> =
        coroutineScope {
            val sortedWeights = availableWeights.sorted()
            sortedWeights.map { weight ->
                async(Dispatchers.Default) {
                    repsRange
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                            )
                        }
                }
            }.awaitAll().flatten()
        }

    fun createSet(
        weight: Double,
        reps: Int,
    ): ExerciseSet {
        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = weight * reps
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        progressionIncrease: Double
    ): ExerciseProgression? {
        val baseParams = ProgressionParameters(
            previousSets = previousSets,
            availableWeights = availableWeights,
            repsRange = repsRange,
            progressionIncrease = progressionIncrease
        )

        val possibleSets = generatePossibleSets(availableWeights,repsRange)

        val validSetCombination = findValidProgression(baseParams, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume = validSetCombination.sumOf { it.volume },
            previousVolume = previousSets.sumOf { it.volume }
        )
    }

    suspend fun generateDeload(
        previousSets:  List<ExerciseSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        targetVolume: Double,
    ): ExerciseProgression? {
        val baseParams = DeloadParameters(
            previousSets = previousSets,
            availableWeights = availableWeights,
            repsRange = repsRange,
            targetVolume = targetVolume
        )

        val possibleSets = generatePossibleSets(availableWeights,repsRange)

        val validSetCombination = findDeload(baseParams, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume = validSetCombination.sumOf { it.volume },
            previousVolume = previousSets.sumOf { it.volume }
        )
    }
}
