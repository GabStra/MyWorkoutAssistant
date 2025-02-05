package com.gabstra.myworkoutassistant.shared.utils

import kotlinx.coroutines.*
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.log10
import kotlin.math.roundToInt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val percentLoad: Double,
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageLoad: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
    )

    data class WeightExerciseParameters(
        val exerciseVolume: Double,
        val averageLoad: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val repsRange: IntRange,
        val minSets: Int,
        val maxSets: Int,
    )

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()){
            //Log.d("WorkoutViewModel", "No sets available")
            return null
        }
        possibleSets = possibleSets.filter { it.volume >= params.exerciseVolume / params.maxSets }

        val defaultValidation = { volume: Double, intensity: Double ->
            ValidationResult(
                shouldReturn = volume < params.exerciseVolume || intensity <= params.averageLoad || intensity > params.averageLoad  * 1.025
            )
        }

        var validSetCombination = findBestProgressions(
            possibleSets,
            params.minSets,
            params.maxSets,
            params.exerciseVolume,
            defaultValidation
        )
        if (validSetCombination.isEmpty()){
            val justIncreaseVolumeValidation = { volume: Double, intensity: Double ->
                ValidationResult(
                    shouldReturn = volume <= params.exerciseVolume || intensity < params.averageLoad
                )
            }

            validSetCombination = findBestProgressions(
                possibleSets,
                params.minSets,
                params.maxSets,
                params.exerciseVolume,
                justIncreaseVolumeValidation
            )
        }

        if (validSetCombination.isEmpty()){
            return null
        }

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseProgression(
            sets = validSetCombination,
            totalVolume = totalVolume,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            progressIncrease = ((totalVolume - params.exerciseVolume) / params.exerciseVolume) * 100,
            averageLoad = validSetCombination.map { it.weight }.average(),
            originalVolume = params.exerciseVolume,
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
        minVolume: Double,
        validationRules: (Double, Double) -> ValidationResult
    ) = coroutineScope {
        require(minSets > 0)
        require(minSets <= maxSets)

        val bestComboRef = AtomicReference<List<ExerciseSet>>(emptyList())
        val bestScore = AtomicReference(Double.MAX_VALUE)

        val sortedSets = sets
            .sortedWith(
                compareByDescending<ExerciseSet> { it.weight }
                    .thenByDescending { it.reps }
            )
            .toList()

        if (sortedSets.size < minSets || sortedSets.isEmpty()) {
            return@coroutineScope emptyList()
        }

        fun calculateScore(
            currentCombo: List<ExerciseSet>,
        ): Double {
            val currentTotalVolume = currentCombo.sumOf { it.volume }
            val currentAverageIntensity = currentCombo.map { it.weight }.average()
            val intensityVariation = ((currentCombo.maxOf { it.weight } - currentCombo.minOf { it.weight }) + 1)
            val repsVariation = ((currentCombo.maxOf { it.reps } - currentCombo.minOf { it.reps }) + 1).toDouble()

            val validationResult = validationRules(currentTotalVolume, currentAverageIntensity)
            if (validationResult.shouldReturn) {
                return validationResult.returnValue
            }

            return currentTotalVolume * currentAverageIntensity * (1 + log10(intensityVariation + 1) * 0.1) * (1 + log10(repsVariation + 1) * 0.1) * currentCombo.size
        }

        suspend fun searchChunk(startIdx: Int, endIdx: Int) = coroutineScope {
            for (firstSetIdx in startIdx until endIdx) {
                fun buildCombination(
                    currentCombo: List<ExerciseSet>,
                    currentVolume: Double,
                    depth: Int = 1
                ) {
                    if (depth >= maxSets) return

                    val currentScore = calculateScore(currentCombo)
                    if(currentScore != Double.MAX_VALUE && bestScore.get() < Double.MAX_VALUE){
                        if(currentScore > bestScore.get()) return
                    }

                    val lastSet = currentCombo.last()

                    val validSets = sortedSets.filter { (lastSet.weight > it.weight) ||
                            (lastSet.weight == it.weight && lastSet.reps >= it.reps)}

                    val maxVolume = validSets.maxOf { it.volume }
                    val maxPossibleVolume = currentVolume +
                            (maxSets - currentCombo.size) * maxVolume
                    if (maxPossibleVolume < minVolume) return

                    for (nextSet in validSets) {
                        if(currentScore != Double.MAX_VALUE && bestScore.get() < Double.MAX_VALUE){
                            if(currentScore > bestScore.get()) return
                        }

                        val newVolume = currentVolume + nextSet.volume
                        val newCombo = currentCombo + nextSet

                        if (newCombo.size >= minSets) {
                            val newScore = calculateScore(newCombo)

                            if (newScore < bestScore.get()) {
                                bestScore.set(newScore)
                                bestComboRef.set(newCombo)
                            }
                        }

                        if (newCombo.size < maxSets) {
                            buildCombination(
                                newCombo,
                                newVolume,
                                depth + 1
                            )
                        }
                    }
                }

                buildCombination(
                    listOf(sortedSets[firstSetIdx]),
                    sortedSets[firstSetIdx].volume,
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
                }
            }
            .awaitAll()

        bestComboRef.get()
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val maxWeightFromOneRepMax = params.oneRepMax * (params.maxLoadPercent / 100)
            val sortedWeights = params.availableWeights.sorted()

            val closestWeightIndex = sortedWeights.binarySearch {
                it.compareTo(params.averageLoad)
            }.let { if (it < 0) -(it + 1) else it }

            val nearAverageWeights = sortedWeights
                .filterIndexed { index, _ ->
                    index in (closestWeightIndex-1)..(closestWeightIndex)
                }
                .filter { it <= maxWeightFromOneRepMax }

            nearAverageWeights.map { weight ->
                async(Dispatchers.Default) {
                    val loadPercentage = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - loadPercentage) / 0.0278).roundToInt() + 1

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

    suspend fun generateExerciseProgression(
        exerciseVolume: Double,
        averageLoad: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        minSets: Int = 3,
        maxSets: Int = 5,
    ): ExerciseProgression? {
        val baseParams = WeightExerciseParameters(
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            exerciseVolume = exerciseVolume,
            minSets = minSets,
            maxSets = maxSets,
            averageLoad = averageLoad
        )

        return getProgression(baseParams)
    }
}
