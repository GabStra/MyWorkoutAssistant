package com.gabstra.myworkoutassistant.shared.utils

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.log10
import kotlin.math.roundToInt

object ProgressionHelper {
    enum class ExerciseCategory {
        STRENGTH,
        HYPERTROPHY,
        ENDURANCE;

        companion object {
            fun fromString(type: String): ExerciseCategory? {
                return values().find { it.name.equals(type, ignoreCase = true) }
            }
        }
    }

    data class ExerciseParameters(
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val fatigueFactor: Double
    )

    fun getParametersByExerciseType(
        exerciseCategory: ProgressionHelper.ExerciseCategory
    ): ProgressionHelper.ExerciseParameters {
        return when (exerciseCategory) {
            ProgressionHelper.ExerciseCategory.STRENGTH -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 85.0 to 100.0,
                repsRange = 1..5,
                fatigueFactor = 0.2
            )

            ProgressionHelper.ExerciseCategory.HYPERTROPHY -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 65.0 to 85.0,
                repsRange = 6..12,
                fatigueFactor = 0.1
            )

            ProgressionHelper.ExerciseCategory.ENDURANCE -> ProgressionHelper.ExerciseParameters(
                percentLoadRange = 50.0 to 65.0,
                repsRange = 12..20,
                fatigueFactor = 0.05
            )
        }
    }
}

object VolumeDistributionHelper {
    data class GenericSet(
        val weight: Double,
        val reps: Int,
    )

    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val volume: Double,
        val percentLoad: Double,
        val fatigue: Double
    )

    data class ExerciseData(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val minIntensity: Double,
        val progressIncrease: Double,
        val originalVolume: Double,
        val isDeloading : Boolean
    )

    data class WeightExerciseParameters(
        val originalVolume: Double,
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val minimumVolume: Double,
        val minSets: Int,
        val maxSets: Int,
        val isDeload : Boolean,
        val currentSets : List<GenericSet>
    )

    private suspend fun getProgression(
        params: WeightExerciseParameters,
    ): ExerciseData? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        val validSetCombination = findBestProgressions(
            possibleSets,
            params.minSets,
            params.maxSets,
            params.currentSets,
        )
        if (validSetCombination.isEmpty()) return null

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseData(
            sets = validSetCombination,
            totalVolume = totalVolume,
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            progressIncrease = ((totalVolume - params.originalVolume) / params.originalVolume) * 100,
            minIntensity = validSetCombination.minOf { it.percentLoad },
            originalVolume = params.originalVolume,
            isDeloading = params.isDeload
        )
    }

    private suspend fun findBestProgressions(
        sets: List<ExerciseSet>,
        minSets: Int,
        maxSets: Int,
        currentSets : List<GenericSet>,
    ) = coroutineScope {
        require(minSets > 0)
        require(minSets <= maxSets)

        val prevVolume = currentSets.sumOf { it.weight * it.reps }

        // Thread-safe variables using atomic references and mutex
        val bestComboRef = AtomicReference<List<ExerciseSet>>(emptyList())
        val bestScore = AtomicReference(Double.MAX_VALUE)

        val sortedSets = sets
            .sortedWith(
                compareBy(
                    { it.volume },
                    { -it.reps },
                    { it.weight }
                )
            )
            .toList()

        if (sortedSets.size < minSets) {
            return@coroutineScope emptyList()
        }

        fun calculateScore(
            currentCombo: List<ExerciseSet>,
        ): Double {
            val totalVolume = currentCombo.sumOf { it.volume }
            val totalFatigue = currentCombo.mapIndexed { index, set ->
                set.fatigue * (1.0 + 0.05 * index)
            }.sum()
            if(totalVolume < prevVolume * 1.005 || totalVolume > prevVolume * 1.01) return Double.MAX_VALUE

            return totalVolume + totalFatigue
        }

        suspend fun searchChunk(startIdx: Int, endIdx: Int) = coroutineScope {
            flow {
                for (firstSetIdx in startIdx until endIdx) {
                    suspend fun buildCombination(
                        currentCombo: List<ExerciseSet>,
                        currentVolume: Double,
                        startFrom: Int,
                        remainingSetsNeeded: Int,
                        depth: Int = 1
                    ) {
                        // Early termination conditions
                        if (depth >= maxSets) return

                        val remainingSetsAvailable = sortedSets.size - startFrom
                        if (remainingSetsAvailable < remainingSetsNeeded) return

                        val lastSet = currentCombo.last()

                        for (nextIdx in startFrom until sortedSets.size) {
                            val nextSet = sortedSets[nextIdx]

                            val isValidSequence = ((lastSet.weight > nextSet.weight) ||
                                    (lastSet.weight == nextSet.weight && lastSet.reps >= nextSet.reps))

                            if(!isValidSequence) continue

                            val newVolume = currentVolume + nextSet.volume
                            val newCombo = currentCombo + nextSet

                            val newScore = calculateScore(newCombo)

                            // Check if we've found a valid combination
                            if (newCombo.size >= minSets) {
                                emit(Pair(newScore, newCombo))
                            }


                            // Only recurse if we need more sets and can potentially improve the solution
                            if (newCombo.size < maxSets) {
                                buildCombination(
                                    newCombo,
                                    newVolume,
                                    nextIdx,
                                    maxOf(0, maxSets - newCombo.size),
                                    depth + 1
                                )
                            }
                        }
                    }

                    buildCombination(
                        listOf(sortedSets[firstSetIdx]),
                        sortedSets[firstSetIdx].volume,
                        firstSetIdx,
                        maxSets - 1
                    )
                }
            }
                .buffer(100)
                .flowOn(Dispatchers.Default)
                .collect { (currentScore, combo) ->
                    if (currentScore < bestScore.get()) {
                        bestScore.set(currentScore)
                        bestComboRef.set(combo)
                    }
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
            val setsMinWeight = params.currentSets.minOf { it.weight } * 0.8
            val setsMaxWeight = params.currentSets.maxOf { it.weight } * 1.05

            val minWeight = params.oneRepMax * (params.percentLoadRange.first / 100)
            val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)

            val intersectionWeightRange = maxOf(setsMinWeight, minWeight)..minOf(setsMaxWeight, maxWeight)

            val weightRange =  params.availableWeights.filter { it in intersectionWeightRange }

            val setsDeferred = weightRange.map { weight ->
                async(Dispatchers.Default) {
                    val loadPercentage = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - loadPercentage) / 0.0278).roundToInt()

                    params.repsRange
                        .filter { reps ->
                            reps <= expectedReps
                        }
                        .map { reps ->
                            createSet(
                                weight = weight,
                                reps = reps,
                                oneRepMax = params.oneRepMax,
                            )
                        }
                }
            }

            setsDeferred.awaitAll().flatten()
        }

    private fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
    ): ExerciseSet {
        val volume = weight * reps
        val relativeIntensity = weight / oneRepMax
        val percentLoad = relativeIntensity * 100

        val fatigue = reps* relativeIntensity

        return ExerciseSet(
            weight = weight,
            reps = reps,
            volume = volume,
            percentLoad = percentLoad,
            fatigue = fatigue
        )
    }

    suspend fun generateExerciseProgression(
        totalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        currentSets : List<GenericSet>,
    ): ExerciseData? {
        val targetVolumeIncrease = 1.05
        val minimumVolumeIncrease = 1.0025

        val baseParams = WeightExerciseParameters(
            targetTotalVolume = totalVolume * targetVolumeIncrease,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            minimumVolume = totalVolume * minimumVolumeIncrease,
            originalVolume = totalVolume,
            minSets = 3,
            maxSets = 5,
            isDeload = false,
            currentSets = currentSets
        )

        for (sets in 3..5) {
            val params = baseParams.copy(minSets = sets, maxSets = sets)
            val result = getProgression(params)

            if (result != null) return result
        }

        return null
    }

/*    suspend fun redistributeExerciseSets(
        totalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        upperVolumeRange: Double,
        lowerVolumeRange: Double,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        isDeload: Boolean,
        minSets: Int = 3,
        maxSets: Int = 5
    ): ExerciseData? {
        val baseParams = WeightExerciseParameters(
            targetTotalVolume = upperVolumeRange,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            minimumVolume = lowerVolumeRange,
            originalVolume = totalVolume,
            minSets = minSets,
            maxSets = minSets,
            isDeload = isDeload
        )

        for (sets in minSets..maxSets) {
            val params = baseParams.copy(minSets = sets, maxSets = sets)
            val result = distributeVolume(params)

            if (result != null) return result.copy(progressIncrease = 0.0)
        }

        return null
    }*/
}
