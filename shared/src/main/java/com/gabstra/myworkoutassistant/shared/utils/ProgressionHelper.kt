package com.gabstra.myworkoutassistant.shared.utils

import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.isEqualTo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.pow


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val fatigue: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val newVolume: Double,
        val usedOneRepMax: Double,
        val previousVolume: Double,
    )

    data class WeightExerciseParameters(
        val previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        val previousTotalVolume : Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val volumeProgressionRange: FloatRange,
    )

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        if(possibleSets.isEmpty()){
            return emptyList()
        }

        var previousTotalFatigue = params.previousSets.sumOf { it.fatigue }
        var nearAverageWeights = getNearAverageWeights(params,1)

        val previousMaxFatigue = params.previousSets.maxOf { it.fatigue }
        val previousMinFatigue = params.previousSets.minOf { it.fatigue }

        val fatigues = possibleSets.filter { set -> set.weight in nearAverageWeights }.map { it.fatigue }.sorted()

        val minFatigue = fatigues
            .filter { it < previousMinFatigue}
            .minByOrNull { abs(it - (previousMinFatigue * 0.975)) }
            ?: previousMinFatigue

        val maxFatigue = fatigues
            .filter { it > previousMaxFatigue}
            .minByOrNull { abs(it - (previousMaxFatigue * 1.025)) }
            ?: previousMaxFatigue

        var usableSets = possibleSets
            .filter { set -> set.weight in nearAverageWeights }
            .filter { set -> set.fatigue in minFatigue..maxFatigue }

        val minTotalFatigue = previousTotalFatigue * (1 + params.volumeProgressionRange.from / 100)

        if(!previousMaxFatigue.isEqualTo(previousMinFatigue)){
            var result = findBestProgressions(
                usableSets,
                params.previousSets.size,
                params.previousSets.size,
                params,
                { combo ->
                    val currentTotalFatigue = combo.sumOf { it.fatigue }
                    val currentMaxFatigue = combo.maxOf { it.fatigue }
                    ValidationResult(
                        shouldReturn = currentTotalFatigue < previousTotalFatigue
                                || currentTotalFatigue.isEqualTo(previousTotalFatigue, epsilon = 1e-1)
                                || currentMaxFatigue > previousMaxFatigue
                                || currentTotalFatigue < minTotalFatigue
                    )
                }
            )

            if(result.isNotEmpty()){
                return result
            }
        }

        var result = findBestProgressions(
            usableSets,
            params.previousSets.size,
            params.previousSets.size,
            params,
            { combo ->
                val currentTotalFatigue = combo.sumOf { it.fatigue }
                ValidationResult(
                    shouldReturn = currentTotalFatigue < previousTotalFatigue
                            || currentTotalFatigue.isEqualTo(previousTotalFatigue, epsilon = 1e-1)
                            || currentTotalFatigue < minTotalFatigue
                )
            }
        )

        if(result.isEmpty()){
             result = findBestProgressions(
                usableSets,
                params.previousSets.size,
                params.previousSets.size,
                params,
                { combo ->
                    val currentTotalFatigue = combo.sumOf { it.fatigue }
                    ValidationResult(
                        shouldReturn = currentTotalFatigue < previousTotalFatigue
                                || currentTotalFatigue.isEqualTo(previousTotalFatigue, epsilon = 1e-1)
                    )
                }
            )
        }

        return result
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params)
        var validSetCombination = findValidProgression(params, possibleSets)

        if (validSetCombination.isEmpty()) {
            return null
        }

        return ExerciseProgression(
            sets = validSetCombination,
            newVolume =  validSetCombination.sumOf { it.volume },
            usedOneRepMax = params.oneRepMax,
            previousVolume = params.previousSets.sumOf { it.volume },
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

            val currentTotalFatigue = combo.sumOf { it.fatigue }
            val maxFatigue = combo.maxOf { it.fatigue }

            return currentTotalFatigue * maxFatigue
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

            val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.volume >= candidate.volume }

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

    private fun getNearAverageWeights(params: WeightExerciseParameters, offset: Int = 1): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        if (sortedWeights.size < 2) {
            return sortedWeights
        }

        var averageWeightPerRep = params.previousTotalVolume / params.previousSets.sumOf { it.reps }

        val closestWeightIndex = when {
            averageWeightPerRep.isNaN() || averageWeightPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(averageWeightPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - offset)..(closestWeightIndex + offset)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            var sortedWeights = params.availableWeights.sorted()
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

        val fatigue = reps * intensity.pow(2)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            fatigue = fatigue,
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        volumeProgressionRange: FloatRange,
    ): ExerciseProgression? {
        val exerciseVolume = previousSets.sumOf { it.volume }

        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            previousTotalVolume = exerciseVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            volumeProgressionRange = volumeProgressionRange,
        )

        var currentExerciseProgression = getProgression(baseParams)
        if(currentExerciseProgression == null){
            return null
        }

        return currentExerciseProgression
    }
}
