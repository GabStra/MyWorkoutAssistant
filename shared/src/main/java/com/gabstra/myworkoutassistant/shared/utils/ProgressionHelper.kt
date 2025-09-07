package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.OneRM.calculateRIR
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.standardDeviation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope


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
        val progressionIncrease: Double
    )

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        val previousTotalVolume = params.previousSets.sumOf { it.relativeVolume }
        val targetVolume = previousTotalVolume * params.progressionIncrease

        val minAvailableRir = possibleSets.minOf { it.rir }
        val maxAvailableRir = possibleSets.maxOf { it.rir }

        val desiredAverageRir = 1 //params.previousSets.map { it.rir }.average()

        val previousMinWeight = params.previousSets.minOf { it.weight }
        val previousMaxWeight = params.previousSets.maxOf { it.weight }

        val previousMinRir = params.previousSets.minOf { it.rir }
        val previousMaxRir = params.previousSets.maxOf { it.rir }

        val minRir = maxOf(minAvailableRir, 0.0)
        val maxRir = minOf(maxAvailableRir, 3.0)

        val previousAvgIntensity = previousTotalVolume / params.previousSets.sumOf { it.reps }

        val nextWeight = params.availableWeights.filter { it > previousMaxWeight }.minOrNull() ?: previousMaxWeight
        val usableSets = possibleSets.filter { set ->  set.rir in minRir..maxRir }

        //Log.d("WorkoutViewModel","Usable sets: ${usableSets.filter { it.weight <= previousMaxWeight }.joinToString { "${it.weight} x ${it.reps} ${it.rir}" }}")

        fun calculateScore(combo: List<ExerciseSet>): Double {
            val eps = 1e-9
            val totalVol = combo.sumOf { it.relativeVolume }
            val avgRir = combo.map { it.rir }.average()
            val avgInt = totalVol / combo.sumOf { it.reps }.coerceAtLeast(1)

            // Normalized deviations (0 = perfect, ~1 = poor fit)
            val volDiff = kotlin.math.abs((totalVol - targetVolume) / targetVolume.coerceAtLeast(eps))
            val rirDiff = kotlin.math.abs(avgRir - desiredAverageRir) / 2.0            // 2 RIR ~ "large miss"
            val intDiff = kotlin.math.abs(avgInt - previousAvgIntensity) / previousAvgIntensity.coerceAtLeast(eps)

            val rirVar = combo.map { it.rir }.standardDeviation() / 1.0                 // 1 RIR stdev ~ big spread
            val relVols = combo.map { it.relativeVolume }
            val meanRelVol = relVols.average().coerceAtLeast(eps)
            val volSpread = (relVols.maxOrNull()!! - relVols.minOrNull()!!) / meanRelVol

            // Convert to "fit scores" ≥1
            val volFit = 1 + volDiff.coerceAtMost(1.0)
            val rirFit = 1 + rirDiff.coerceAtMost(1.0)
            val intFit = 1 + intDiff.coerceAtMost(1.0)
            val rirVarFit = 1 + rirVar.coerceAtMost(1.0)
            val volSpreadFit = 1 + volSpread.coerceAtMost(1.0)

            val weights = listOf(
                0.35, // RIR fit
                0.30, // Volume fit
                0.20, // Intensity fit
                0.10, // RIR variability
                0.05  // Volume spread
            )

            val fits = listOf(rirFit, volFit, intFit, rirVarFit, volSpreadFit)

            // Weighted geometric mean
            val logSum = weights.zip(fits).sumOf { (w, f) -> w * kotlin.math.ln(f) }
            val score = kotlin.math.exp(logSum)
            return score
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
                val isVolumeHigherThanPrevious = currentTotalVolume.round(2) > previousTotalVolume.round(2)

                isNotPrevious && isVolumeHigherThanPrevious
            }
        )

        if(result.isNotEmpty()) return result

        if(nextWeight != previousMaxWeight) {
            //Log.d("WorkoutViewModel","Fallback sets: ${possibleSets.filter { it.weight == nextWeight }.joinToString { "${it.weight} x ${it.reps} ${it.rir}" }}")

            result = findBestProgressions(
                possibleSets.filter { it.weight == nextWeight },
                params.previousSets.size,
                params.previousSets.size,
                params,
                calculateScore = { combo -> calculateScore(combo) },
                isComboValid = { combo ->
                    val repsSpread = combo.maxOf { it.reps } - combo.minOf { it.reps }
                    val currentTotalVolume = combo.sumOf { it.relativeVolume }
                    repsSpread <= 1 && currentTotalVolume < previousTotalVolume
                }
            )

            if(result.isNotEmpty()){
                //Log.d("WorkoutViewModel", "Fallback load increase")
                return result
            }
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
            newVolume = validSetCombination.sumOf { it.relativeVolume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = previousSets.sumOf { it.relativeVolume }
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
