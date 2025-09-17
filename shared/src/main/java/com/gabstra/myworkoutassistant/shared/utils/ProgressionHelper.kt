package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.OneRM.calculateRIR
import com.gabstra.myworkoutassistant.shared.round
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.ln1p
import kotlin.math.max
import kotlin.math.sqrt

object ProgressionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val perc1RM: Double,
        val relativeVolume: Double,
        val rir: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val previousVolume: Double,
        val newRelVolume: Double,
        val previousRelVolume: Double

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
        val targetRelVol: Double
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

    private fun calculateScore(
        combo: List<ExerciseSet>,
        targetRelVol: Double,
        previousAvgIntensity: Double,
        previousMaxSetRelVol: Double,
        previousMaxWeight: Double,
        previousAvgRIR: Double,
        previousMinSetRir: Double
    ): Double {
        if (combo.isEmpty()) return Double.POSITIVE_INFINITY
        val eps = 1e-9
        val setCount = combo.size

        // Totals
        val totalRelVol = combo.sumOf { it.relativeVolume }
        val totalVol = combo.sumOf { it.volume }
        val totalReps = combo.sumOf { it.reps }.coerceAtLeast(1)
        val avgInt = totalVol / totalReps.toDouble()

        // --- Fits (>=1; 1 is perfect) ---
        val volFit = 1.0 + abs((totalRelVol - targetRelVol) / (targetRelVol + eps))
        val intFit = 1.0 + abs((avgInt - previousAvgIntensity) / (previousAvgIntensity + eps))

        // Evenness via CV of per-set relative volume
        val meanRelVolPerSet = totalRelVol / setCount
        val volVar = combo.sumOf { val d = it.relativeVolume - meanRelVolPerSet; d * d } / setCount
        val volCv = if (meanRelVolPerSet <= eps) 0.0 else sqrt(volVar) / meanRelVolPerSet
        val evenFit = 1.0 + volCv

        // --- RIR handling: shift all values positive, preserve distances ---
        val rawRIRs = combo.map { it.rir }
        val rawMinRIR = rawRIRs.minOrNull() ?: 0.0
        // include previousMinSetRir in the shift so negatives are handled consistently
        val minRIR = minOf(rawMinRIR, previousAvgRIR, previousMinSetRir)
        val shift = if (minRIR <= 0.0) -minRIR + eps else 0.0

        val shRIRs = rawRIRs.map { it + shift }
        val shPrevAvgRIR = previousAvgRIR + shift
        val shAvgRIR = shRIRs.average()
        val shPrevMinSetRir = previousMinSetRir + shift

        val RIR_RANGE = 5.0

        val rirFit = 1.0 + abs(shAvgRIR - shPrevAvgRIR) / RIR_RANGE

        // Optional spread penalty on shifted RIR (std is shift-invariant)
        val rirStd = if (shRIRs.isEmpty()) 0.0 else {
            val m = shAvgRIR
            sqrt(shRIRs.sumOf { (it - m) * (it - m) } / shRIRs.size)
        }
        val rirSpreadPenalty = 1.0 + rirStd / RIR_RANGE

        // Weighted geometric mean (via log-sum)
        val weights = doubleArrayOf(0.45, 0.20, 0.20, 0.15) // vol, intensity, evenness, RIR
        val fits = doubleArrayOf(volFit, intFit, evenFit, rirFit)
        val base = exp(weights.indices.sumOf { i -> weights[i] * ln(fits[i]) })

        // --- Smooth multiplicative penalties (only for caps) ---
        fun softHingeFrac(overFrac: Double) = ln1p(max(0.0, overFrac)) + 1.0

        val weightPenalty = combo.fold(1.0) { acc, s ->
            val fracOver = (s.weight - previousMaxWeight) / (previousMaxWeight + eps)
            acc * softHingeFrac(fracOver)
        }

        val perSetRelVolPenalty = combo.fold(1.0) { acc, s ->
            val fracOver = (s.relativeVolume - previousMaxSetRelVol) / (previousMaxSetRelVol + eps)
            acc * softHingeFrac(fracOver)
        }

        // Penalize sets with RIR below previousMinSetRir (using shifted values, works even if negatives)
        val rirBelowMinPenalty = combo.fold(1.0) { acc, s ->
            val shRir = s.rir + shift
            val deficit = (shPrevMinSetRir - shRir) / RIR_RANGE
            acc * softHingeFrac(deficit)
        }

        // Final score (lower is better)
        return base * weightPenalty * perSetRelVolPenalty * rirSpreadPenalty * rirBelowMinPenalty
    }

    private  suspend fun findValidProgression(
        params: ProgressionParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        val previousRelVol = params.previousSets.sumOf { it.relativeVolume }
        val targetRelVol = params.previousSets.sumOf { it.relativeVolume } * params.progressionIncrease

        val previousMaxWeight = params.previousSets.maxOf { it.weight }
        val previousMinSetRIR = params.previousSets.minOf { it.rir }
        val previousMaxSetRelVol = params.previousSets.maxOf { it.relativeVolume }
        val previousAvgIntensity = params.previousSets.sumOf { it.volume } / params.previousSets.sumOf { it.reps }
        val previousAvgRIR = params.previousSets.map {it.rir }.average()

        val weightLowerThanPrevious = params.availableWeights
            .filter { it < previousMaxWeight }
            .minByOrNull { abs(it - (previousMaxWeight * 0.95)) }
            ?: Double.NEGATIVE_INFINITY

        val nextWeightUp =  params.availableWeights
            .filter { it > previousMaxWeight }
            .minByOrNull { abs( it - (previousMaxWeight * 1.05)) }
            ?: Double.MAX_VALUE

        val usableSets = possibleSets.filter { it.weight in weightLowerThanPrevious..nextWeightUp && it.rir <= 2.0 }

        var result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo -> calculateScore(combo, targetRelVol, previousAvgIntensity, previousMaxSetRelVol, previousMaxWeight, previousAvgRIR, previousMinSetRIR) },
            isComboValid = { combo ->
                val currentTotalRelVol = combo.sumOf { it.relativeVolume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets)
                val isVolumeHigherThanPrevious = currentTotalRelVol.round(2) > previousRelVol.round(2)
                val oneSetUsesPreviousMaxWeightOrHigher = combo.any { it.weight >= previousMaxWeight }

                isNotPrevious && isVolumeHigherThanPrevious && oneSetUsesPreviousMaxWeightOrHigher
            }
        )

        if(result.isNotEmpty()) return result

        result = findBestProgressions(
            usableSets,
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo -> calculateScore(combo, targetRelVol, previousAvgIntensity, previousMaxSetRelVol, previousMaxWeight, previousAvgRIR, previousMinSetRIR) },
            isComboValid = { combo ->
                val currentTotalRelVol = combo.sumOf { it.relativeVolume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets)
                val isVolumeHigherThanPrevious = currentTotalRelVol.round(2) > previousRelVol.round(2)
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

        val previousTotalVolume = params.previousSets.sumOf { it.relativeVolume }
        val targetRelVol = params.targetRelVol

        val previousMaxWeight = params.previousSets.maxOf { it.weight }
        val previousMinSetRIR = params.previousSets.minOf { it.rir }
        val previousMaxSetRelVol = params.previousSets.maxOf { it.relativeVolume }
        val previousAvgIntensity = params.previousSets.sumOf { it.volume } / params.previousSets.sumOf { it.reps }
        val previousAvgRIR = params.previousSets.map {it.rir }.average()

        val usableSets = possibleSets.filter { it.weight <= previousMaxWeight }

        val result = findBestProgressions(
            usableSets.filter { it.weight <= previousMaxWeight },
            params.previousSets.size,
            params.previousSets.size,
            calculateScore = { combo -> calculateScore(combo, targetRelVol, previousAvgIntensity, previousMaxSetRelVol, previousMaxWeight, previousAvgRIR, previousMinSetRIR) },
            isComboValid = { combo ->
                val currentTotalVolume = combo.sumOf { it.relativeVolume }

                val isNotPrevious = !sameMultisetByWeightReps(combo, params.previousSets)
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
        isSetValid: (currentSet: ExerciseSet, lastSet:ExerciseSet) -> Boolean = { candidateSet, lastSet -> lastSet.weight >= candidateSet.weight}
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
                        val validSets = sortedSets.filter { candidateSet -> isSetValid(candidateSet,lastSet) }

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

    private suspend fun generatePossibleSets(availableWeights: Set<Double>, repsRange: IntRange, est1RM: Double): List<ExerciseSet> =
        coroutineScope {
            val sortedWeights = availableWeights.sorted()
            sortedWeights.map { weight ->
                async(Dispatchers.Default) {
                    repsRange
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                                est1RM = est1RM
                            )
                        }
                }
            }.awaitAll().flatten()
        }

    fun createSet(
        weight: Double,
        reps: Int,
        est1RM: Double
    ): ExerciseSet {
        val perc1RM = weight / est1RM

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = weight * reps,
            rir = calculateRIR(weight,reps, est1RM),
            perc1RM = perc1RM,
            relativeVolume = perc1RM * reps
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        progressionIncrease: Double,
        est1RM: Double
    ): ExerciseProgression? {
        val baseParams = ProgressionParameters(
            previousSets = previousSets,
            availableWeights = availableWeights,
            repsRange = repsRange,
            progressionIncrease = progressionIncrease
        )

        val possibleSets = generatePossibleSets(availableWeights,repsRange,est1RM)

        val validSetCombination = findValidProgression(baseParams, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume = validSetCombination.sumOf { it.volume },
            previousVolume = previousSets.sumOf { it.volume },
            newRelVolume = validSetCombination.sumOf { it.relativeVolume },
            previousRelVolume = previousSets.sumOf { it.relativeVolume }
        )
    }

    suspend fun generateDeload(
        previousSets:  List<ExerciseSet>,
        availableWeights: Set<Double>,
        repsRange: IntRange,
        targetRelVol: Double,
        est1RM: Double
    ): ExerciseProgression? {
        val baseParams = DeloadParameters(
            previousSets = previousSets,
            availableWeights = availableWeights,
            repsRange = repsRange,
            targetRelVol = targetRelVol
        )

        val possibleSets = generatePossibleSets(availableWeights,repsRange,est1RM)

        val validSetCombination = findDeload(baseParams, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume = validSetCombination.sumOf { it.volume },
            previousVolume = previousSets.sumOf { it.volume },
            newRelVolume = validSetCombination.sumOf { it.relativeVolume },
            previousRelVolume = previousSets.sumOf { it.relativeVolume }
        )
    }
}
