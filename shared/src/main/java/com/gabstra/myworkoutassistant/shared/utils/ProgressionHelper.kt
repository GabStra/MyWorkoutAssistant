package com.gabstra.myworkoutassistant.shared.utils

import androidx.annotation.FloatRange
import com.gabstra.myworkoutassistant.shared.calculateRIR
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.maxRepsForWeight
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.roundToInt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val intensity: Double,
        val workload: Double,
        val rir: Double
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val workload: Double,
        val usedOneRepMax: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
        val averageRIR: Double
    )

    data class WeightExerciseParameters(
        val previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        val previousVolume : Double,
        val averageLoadPerRep: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val workloadProgressionRange: FloatRange,
        val sets: Int,
    )

    private  suspend fun findValidProgression(
        params: WeightExerciseParameters,
        possibleSets: List<ExerciseSet>,
    ): List<ExerciseSet> {
        val minVolume = params.previousVolume * (1 + params.workloadProgressionRange.from / 100)
        val maxVolume = params.previousVolume * (1 + params.workloadProgressionRange.to / 100)



        var result = emptyList<ExerciseSet>()

        var currentSets = params.sets

        while(currentSets <= 5){
            var result = findBestProgressions(
                possibleSets,
                currentSets,
                currentSets,
                params,
                { combo ->
                    val currentVolume = combo.sumOf { it.volume }

                    ValidationResult(
                        shouldReturn = currentVolume.isEqualTo(params.previousVolume)
                                || currentVolume < minVolume
                                || currentVolume > maxVolume
                    )
                }
            )
            if (result.isNotEmpty()) return result
            currentSets++
        }

        /*
        currentSets = params.sets

        while(currentSets <= 5){
            var result = findBestProgressions(
                possibleSets,
                currentSets,
                currentSets,
                params,
                { combo ->
                    val currentTotalVolume = combo.sumOf { it.volume }

                    ValidationResult(
                        shouldReturn = currentTotalVolume.isEqualTo(params.totalVolume)
                                || currentTotalVolume < minVolume
                    )
                }
            )
            if (result.isNotEmpty()) return result
            currentSets++
        }
        */

        return result
    }

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params,1)
        if (possibleSets.isEmpty()){
            return null
        }

        var validSetCombination = findValidProgression(params, possibleSets)

        if(validSetCombination.isEmpty()){
            possibleSets = generatePossibleSets(params,3)
            validSetCombination = findValidProgression(params, possibleSets)

            if(validSetCombination.isEmpty()){
                return null
            }
        }

        val newVolume = validSetCombination.sumOf { it.volume }

        val averageRIR = validSetCombination.map { it.rir }.average()

        return ExerciseProgression(
            sets = validSetCombination,
            workload = newVolume,
            usedOneRepMax = params.oneRepMax,
            progressIncrease = ((newVolume - params.previousVolume) / params.previousVolume) * 100,
            originalVolume = params.previousVolume,
            averageRIR = averageRIR
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

        val previousAverageLoadPerRep = params.previousSets.sumOf { it.volume } / params.previousSets.sumOf { it.reps }

        fun evaluateGeneralScore(combo: List<ExerciseSet>): Double {
            val validationResult = validationRules(combo)
            if (validationResult.shouldReturn)  return validationResult.returnValue

            val currentVolume = combo.sumOf { it.volume }
            val volumeDifferenceScore = 1 + (combo.maxOf { it.volume } - combo.minOf { it.volume })

            val averageRIR = combo.map { it.rir }.average()

            val currentAverageLoadPerRep = combo.sumOf { it.volume } / combo.sumOf { it.reps }
            val loadPerRepDifferenceScore = 1 + (abs(currentAverageLoadPerRep - previousAverageLoadPerRep))

            return currentVolume * volumeDifferenceScore * (1 + averageRIR) * loadPerRepDifferenceScore
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
            val validSets = sortedSets.filter { candidate -> lastSet.weight >= candidate.weight && lastSet.workload >= candidate.workload }

            /*
            val maxRemainingVolume = validSets.maxOfOrNull { it.volume } ?: 0.0
            val maxPossibleVolume = currentVolume + (maxSets - currentCombo.size) * maxRemainingVolume
            if (maxPossibleVolume < Volume) return
            */

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

    private fun getNearAverageWeights(params: WeightExerciseParameters, offset: Int ): List<Double> {
        val sortedWeights = params.availableWeights.sorted()

        require(offset >= 0) { "Offset must be non-negative" }

        if (sortedWeights.size < 2) {
            return sortedWeights  // Return all available weights if less than 2
        }

        val closestWeightIndex = when {
            params.averageLoadPerRep.isNaN() || params.averageLoadPerRep.isInfinite() -> 0
            else -> sortedWeights.binarySearch {
                it.compareTo(params.averageLoadPerRep)
            }.let { if (it < 0) -(it + 1) else it }
                .coerceIn(0, sortedWeights.lastIndex)
        }

        return sortedWeights.filterIndexed { index, _ ->
            index in (closestWeightIndex - offset)..(closestWeightIndex + offset)
        }
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters,offset: Int): List<ExerciseSet> =
        coroutineScope {
            var nearAverageWeights = getNearAverageWeights(params,offset)

            nearAverageWeights.map { weight ->
                async(Dispatchers.Default) {
                    val expectedReps = maxRepsForWeight(weight,params.oneRepMax).roundToInt()

                    params.repsRange
                        .filter { reps -> reps <= expectedReps }
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
        val volume = weight * reps
        val effortMultiplier = exp(2.0 * intensity)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            intensity = intensity,
            workload = volume * effortMultiplier,
            rir = calculateRIR(
                weight = weight,
                reps = reps,
                oneRepMax = oneRepMax
            )
        )
    }

    suspend fun generateExerciseProgression(
        previousSets:  List<VolumeDistributionHelper.ExerciseSet>,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        workloadProgressionRange: FloatRange,
        sets: Int,
    ): ExerciseProgression? {
        val exerciseVolume = previousSets.sumOf { it.volume }

        val totalReps = previousSets.sumOf { it.reps }
        val averageLoadPerRep = exerciseVolume / totalReps

        val baseParams = WeightExerciseParameters(
            previousSets = previousSets,
            previousVolume = exerciseVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            sets = sets,
            averageLoadPerRep =  averageLoadPerRep,
            workloadProgressionRange = workloadProgressionRange,
        )

        return getProgression(baseParams)
    }
}
