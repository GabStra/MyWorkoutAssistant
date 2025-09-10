package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlin.math.abs


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double
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
        val progressionIncrease: Double
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

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
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
            .minByOrNull { abs(it - previousMaxWeight * 0.95) }
            ?: Double.NEGATIVE_INFINITY
        val nextWeightUp = params.availableWeights.filter { it > previousMaxWeight }.minOrNull() ?: Double.MAX_VALUE
        val usableSets = possibleSets.filter { it.weight in weightLowerThanPrevious..nextWeightUp }

        fun calculateScore(combo: List<ExerciseSet>): Double {
            val eps = 1e-9
            val totalVol = combo.sumOf { it.volume }
            val totalReps = combo.sumOf { it.reps }
            val avgInt = totalVol / totalReps.coerceAtLeast(1)

            // Normalized deviations (0 = perfect, ~1 = poor fit)
            val volDiff = kotlin.math.abs((totalVol - targetVolume) / targetVolume.coerceAtLeast(eps))
            val intDiff = kotlin.math.abs(avgInt - previousAvgIntensity) / previousAvgIntensity.coerceAtLeast(eps)

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
            val weights = listOf(0.5, 0.25, 0.25) //val weights = List(fits.size) { 1.0 / fits.size }
            val logSum = weights.zip(fits).sumOf { (w, f) -> w * kotlin.math.ln(f) }
            val baseScore = kotlin.math.exp(logSum)

            // Add penalty for sets exceeding previous max volume
            val penaltyFactor = 100.0 // A multiplier to make the penalty significant
            val totalExcessVolume = combo.filter { it.volume >= previousMaxSetVolume }
                .sumOf { (it.volume - previousMaxSetVolume).coerceAtLeast(1.0) }
            val penalty = totalExcessVolume * penaltyFactor

            return baseScore + penalty
        }

        val allSetsAtMaxReps = params.previousSets.isNotEmpty() && params.previousSets.all { it.reps == params.repsRange.last }

        if(allSetsAtMaxReps && nextWeightUp != Double.MAX_VALUE){
            val result = findBestProgressions(
                sets = possibleSets.filter { it.weight in previousMinWeight.. nextWeightUp },
                minSets = params.previousSets.size,
                maxSets = params.previousSets.size,
                params = params,
                calculateScore = { combo -> calculateScore(combo) },
                isComboValid = { combo ->
                    val currentTotalVolume = combo.sumOf { it.volume }

                    val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                    val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)

                    isNotPrevious && isVolumeHigherThanPrevious
                }
            )

            if (result.isNotEmpty()) return result
        }

        var result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)
                val isVolumeLowerOrEqualToTarget = currentTotalVolume.round(2) <= targetVolume.round(2)

                isNotPrevious && isVolumeHigherThanPrevious && isVolumeLowerOrEqualToTarget
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            params,
            calculateScore = { combo -> calculateScore(combo) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.volume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets) && !currentTotalVolume.isEqualTo(previousTotalVolume)
                val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)

                isNotPrevious && isVolumeHigherThanPrevious
            }
        )

        if(result.isNotEmpty()) return result

        if(nextWeightUp != Double.MAX_VALUE) {
            result = findBestProgressions(
                possibleSets.filter { it.weight == nextWeightUp },
                params.previousSets.size,
                params.previousSets.size,
                params,
                calculateScore = { combo -> combo.sumOf { it.volume } },
                isComboValid = { combo ->
                    val repsSpread = combo.maxOf { it.reps } - combo.minOf { it.reps }
                    val currentTotalVolume = combo.sumOf { it.volume }
                    repsSpread == 0 && currentTotalVolume.round(2) >= (previousTotalVolume * 0.9).round(2) && currentTotalVolume.round(2) < previousTotalVolume.round(2)
                }
            )

            if(result.isNotEmpty()) return result
        }

        return emptyList()
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        val possibleSets = generatePossibleSets(params)

        val previousSets = params.previousSets

        val validSetCombination = findValidProgression(params, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume = validSetCombination.sumOf { it.volume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = previousSets.sumOf { it.volume }
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

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = weight * reps,
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        progressionIncrease: Double
    ): ExerciseProgression? {
        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            repsRange = repsRange,
            progressionIncrease = progressionIncrease
        )

        val currentExerciseProgression = getProgression(baseParams)
        if(currentExerciseProgression == null){
            return null
        }

        return currentExerciseProgression
    }
}
