package com.gabstra.myworkoutassistant.shared.utils

import kotlinx.coroutines.*
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.roundToInt
import kotlin.math.sqrt


object VolumeDistributionHelper {
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
    )

    data class ExerciseProgression(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageIntensity: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
    )

    data class WeightExerciseParameters(
        val exerciseVolume: Double,
        val averageLoad: Double,
        val baselineReps: Int,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val maxLoadPercent: Double,
        val maxWeightFromOneRepMax: Double,
        val repsRange: IntRange,
        val minSets: Int,
        val maxSets: Int,
    )

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseProgression? {
        var possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()){
            return null
        }

        possibleSets = possibleSets.filter { it.volume >= (params.exerciseVolume / params.maxSets) * 0.75 }

        val maxSetVolume = possibleSets.maxOf { it.volume }
        val maxPossibleVolume = maxSetVolume * params.maxSets

        var validSetCombination = emptyList<ExerciseSet>()

        //Log.d("WorkoutViewModel", "Max possible volume: $maxPossibleVolume Exercise volume: ${params.exerciseVolume}")

        if(maxPossibleVolume < params.exerciseVolume) {
            val maxSet = possibleSets.maxByOrNull { it.volume }!!
            validSetCombination = List(params.maxSets) { maxSet }
        }

        //Log.d("WorkoutViewModel", "Possible sets: ${possibleSets.joinToString { "${it.weight} kg x ${it.reps}" }}")

        val maxWeight = possibleSets.maxOf { it.weight }
        val intensityLimit = if(params.averageLoad > maxWeight) maxWeight else params.averageLoad

        if(validSetCombination.isEmpty()){
            validSetCombination = findBestProgressions(
                possibleSets,
                params.minSets,
                params.maxSets,
                params.exerciseVolume,
                params.averageLoad,
                params.baselineReps,
                { volume: Double, intensity: Double ->
                    ValidationResult(
                        shouldReturn = volume < params.exerciseVolume || intensity <= intensityLimit || intensity > intensityLimit  * 1.025
                    )
                }
            )
            if (validSetCombination.isEmpty()){
                validSetCombination = findBestProgressions(
                    possibleSets,
                    params.minSets,
                    params.maxSets,
                    params.exerciseVolume,
                    params.averageLoad,
                    params.baselineReps,
                    { volume: Double, intensity: Double ->
                        ValidationResult(
                            shouldReturn = volume <= params.exerciseVolume || intensity < intensityLimit
                        )
                    }
                )
            }

            if (validSetCombination.isEmpty()){
                return null
            }
        }

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseProgression(
            sets = validSetCombination,
            totalVolume = totalVolume,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            progressIncrease = ((totalVolume - params.exerciseVolume) / params.exerciseVolume) * 100,
            averageIntensity = validSetCombination.map { it.weight }.average(),
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
        previousVolume: Double,
        previousAverageLoad: Double,
        baselineReps: Int,
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

        if (sortedSets.isEmpty()) {
            return@coroutineScope emptyList()
        }

        fun calculateScore(currentCombo: List<ExerciseSet>): Double {
            val currentTotalVolume = currentCombo.sumOf { it.volume }
            val currentTotalReps = currentCombo.sumOf { it.reps }
            val currentAverageLoad = currentTotalVolume / currentTotalReps

            val validationResult = validationRules(currentTotalVolume, currentAverageLoad)
            if (validationResult.shouldReturn) {
                return validationResult.returnValue
            }

            val deltaVPercent = (currentTotalVolume / previousVolume)
            val deltaLPercent =  (currentAverageLoad / previousAverageLoad)

            val stdDevWeight = sqrt(currentCombo.map { (it.weight - currentAverageLoad) * (it.weight - currentAverageLoad) }.average())
            val cvWeights = if (currentAverageLoad != 0.0) stdDevWeight / currentAverageLoad else 0.0

            val repsList = currentCombo.map { it.reps.toDouble() }
            val meanReps = repsList.average()
            val stdDevReps = sqrt(repsList.map { (it - meanReps) * (it - meanReps) }.average())
            val cvReps = if (meanReps != 0.0) stdDevReps / meanReps else 0.0

            val repsPenalty = currentCombo.sumOf {
                if (it.reps > baselineReps) (it.reps - baselineReps).toDouble() else 0.0
            }

            val w1 = 1.0
            val w2 = 1.0
            val w3 = 1.0
            val w4 = 1.0
            val w5 = 1.0
            val w6 = 10.0

            return w1 * (deltaVPercent * deltaVPercent) +
                   w2 * (deltaLPercent * deltaLPercent) +
                   w3 * (cvWeights * cvWeights) +
                   w4 * (cvReps * cvReps) +
                   w5 * repsPenalty +
                   w6 * currentCombo.size
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
                    if (maxPossibleVolume < previousVolume) return

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
            val sortedWeights = params.availableWeights.filter { it <= params.maxWeightFromOneRepMax }.sorted()

            val closestWeightIndex = sortedWeights.binarySearch {
                it.compareTo(params.averageLoad)
            }.let { if (it < 0) -(it + 1) else it }.coerceAtMost(sortedWeights.size - 1).coerceAtLeast(0)

            val nearAverageWeights = sortedWeights
                .filterIndexed { index, _ ->
                    index in (closestWeightIndex)..(closestWeightIndex+1)
                }


            //Log.d("WorkoutViewModel", "Closest Weight Index: $closestWeightIndex Intensity: ${params.averageIntensity} Near average weights: $nearAverageWeights")

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
                            )
                        }
                }
            }.awaitAll().flatten()
        }

    private fun createSet(
        weight: Double,
        reps: Int,
    ): ExerciseSet {
        val volume = weight * reps

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
        )
    }

    suspend fun generateExerciseProgression(
        exerciseVolume: Double,
        averageLoad: Double,
        baselineReps: Int,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        maxLoadPercent: Double,
        repsRange: IntRange,
        minSets: Int = 3,
        maxSets: Int = 5,
    ): ExerciseProgression? {
        val maxWeightFromOneRepMax = oneRepMax * (maxLoadPercent / 100)

        val baseParams = WeightExerciseParameters(
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            maxWeightFromOneRepMax = maxWeightFromOneRepMax,
            maxLoadPercent = maxLoadPercent,
            repsRange = repsRange,
            exerciseVolume = exerciseVolume,
            minSets = minSets,
            maxSets = maxSets,
            averageLoad =  if(averageLoad > maxWeightFromOneRepMax) maxWeightFromOneRepMax else averageLoad,
            baselineReps = baselineReps,
        )

        return getProgression(baseParams)
    }
}
