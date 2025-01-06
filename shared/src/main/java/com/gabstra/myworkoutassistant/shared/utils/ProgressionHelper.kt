package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.pow

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
    data class ExerciseSet(
        val weight: Double,
        val reps: Int,
        val fatigue: Double,
        val volume: Double,
        val percentLoad: Double,
    )

    data class DistributedWorkout(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val totalFatigue: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageFatiguePerSet: Double,
        val averagePercentLoad: Double,
        val progressIncrease: Double,
    )

    data class WeightExerciseParameters(
        val originalVolume: Double,
        val targetTotalVolume: Double,
        val oneRepMax: Double,
        val availableWeights: Set<Double>,
        val percentLoadRange: Pair<Double, Double>,
        val repsRange: IntRange,
        val fatigueFactor: Float,
        val minimumVolume: Double,
    )

    private suspend fun distributeVolume(
        params: WeightExerciseParameters,
    ): DistributedWorkout? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        val validSetCombination = findBestCombinationVariant(possibleSets, params.targetTotalVolume, params.minimumVolume)
        if (validSetCombination.isEmpty()) return null

        val totalVolume = validSetCombination.sumOf { it.volume }

        return DistributedWorkout(
            sets = validSetCombination,
            totalVolume = validSetCombination.sumOf { it.volume },
            totalFatigue = validSetCombination.sumOf { it.fatigue },
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.sumOf { it.fatigue } / validSetCombination.size,
            progressIncrease = ((totalVolume - params.originalVolume) / params.originalVolume) * 100,
            averagePercentLoad = validSetCombination.sumOf { it.percentLoad } / validSetCombination.size
        )
    }

    @OptIn(DelicateCoroutinesApi::class)
    private suspend fun findBestCombination(
        sets: List<ExerciseSet>,
        targetVolume: Double,
        minimumVolume: Double,
        timeoutSeconds: Long = 90,
    ): List<ExerciseSet> = coroutineScope {
        if (sets.isEmpty() || sets.sumOf { it.volume } < targetVolume) {
            Log.d("WorkoutViewModel", "Total volume is less than target")
            return@coroutineScope emptyList()
        }

        val validSets = sets.filter { it.volume < targetVolume }
            .sortedWith(compareBy<ExerciseSet> { it.weight }.thenByDescending { it.reps })

        class Combination(private val capacity: Int) {
            private val indices = IntArray(capacity)
            private var size = 0

            fun add(index: Int) {
                indices[size++] = index
            }

            fun removeLast() {
                size--
            }

            fun size() = size

            fun getVolume(sets: List<ExerciseSet>): Double {
                var volume = 0.0
                for (i in 0 until size) {
                    volume += sets[indices[i]].volume
                }
                return volume
            }

            fun toList(): IntArray = indices.copyOf(size)
        }

        val mutex = Mutex()
        var bestCombination = IntArray(0)
        var bestScore = Double.MIN_VALUE

        fun scoreCombination(indices: Combination): Double {
            val totalVolume = indices.getVolume(validSets)
            if (totalVolume < minimumVolume) return Double.MIN_VALUE

            val combinationSets = indices.toList().map { validSets[it] }

            // Volume score calculation
            val volumeDeviation = abs(totalVolume - targetVolume) / targetVolume
            val volumeScore = 1.0 / (1.0 + volumeDeviation * 10)

            // Ratio calculations
            val repRatio =
                combinationSets.maxOf { it.reps }.toDouble() / combinationSets.minOf { it.reps }
            val weightRatio =
                combinationSets.maxOf { it.weight } / combinationSets.minOf { it.weight }
            val fatigueRatio =
                combinationSets.maxOf { it.fatigue } / combinationSets.minOf { it.fatigue }

            // Individual penalties
            val repPenalty = 1.0 - exp(-50.0 * (repRatio - 1.0))
            val weightPenalty = 1.0 - exp(-50.0 * (weightRatio - 1.0))
            val fatiguePenalty = 1.0 - exp(-50.0 * (fatigueRatio - 1.0))
            val combinationSetsPenalty = 1.0 - exp(-0.5 * (combinationSets.size - 1))

            // Combined scores with their squares included
            val consistencyScore = (1.0 - maxOf(repPenalty, weightPenalty, fatiguePenalty)).pow(2)

            val avgFatigue = combinationSets.sumOf { it.fatigue } / combinationSets.size
            val fatigueEfficiencyScore = (1.0 / (1.0 + avgFatigue * 5)).pow(2)
            val setSizeScore = 1.0 - combinationSetsPenalty

            return volumeScore * consistencyScore * fatigueEfficiencyScore * setSizeScore
        }

        suspend fun backtrack(
            start: Int,
            currentCombination: Combination,
            remainingVolume: Double,
            scope: CoroutineScope
        ) {
            val totalVolume = currentCombination.getVolume(validSets)

            if (remainingVolume < 0 || totalVolume > targetVolume) return

            if (currentCombination.size() >= 3) {
                val combinationScore = scoreCombination(currentCombination)
                mutex.withLock {
                    if (combinationScore > bestScore) {
                        bestScore = combinationScore
                        bestCombination = currentCombination.toList()
                    }
                }
            }

            if (currentCombination.size() == 5) {
                return
            }

            val remainingSets = validSets.subList(start, validSets.size)

            val maxPossibleSetVolume = remainingSets.maxOf { it.volume }
            val minPossibleVolume =
                remainingVolume - (maxPossibleSetVolume * (6 - currentCombination.size()))
            if (minPossibleVolume > 0) return

            for (i in start until validSets.size) {
                if (!scope.isActive) return

                val nextSet = validSets[i]

                if (remainingVolume - nextSet.volume < 0) {
                    continue
                }

                if (currentCombination.size() > 0) {
                    val lastSet =
                        validSets[currentCombination.toList()[currentCombination.size() - 1]]
                    if (nextSet.weight == lastSet.weight && nextSet.reps > lastSet.reps) {
                        continue
                    }
                }

                currentCombination.add(i)

                backtrack(
                    start = i,
                    currentCombination = currentCombination,
                    remainingVolume = remainingVolume - nextSet.volume,
                    scope = scope
                )

                currentCombination.removeLast()
            }
        }

        val runtime = Runtime.getRuntime()
        val supervisorJob = SupervisorJob()
        val scope = CoroutineScope(Dispatchers.IO + supervisorJob)
        val activeJobs = AtomicInteger(0)
        val jobMutex = Mutex()
        val estimatedBytesPerJob = 1 * 1024 * 1024
        val runningJobs = Collections.synchronizedList(mutableListOf<Job>())

        fun calculateMaxJobs(): Int {
            val maxMemoryBytes = runtime.maxMemory()
            val usedMemoryBytes = runtime.totalMemory() - runtime.freeMemory()
            val availableMemoryBytes = maxMemoryBytes - usedMemoryBytes
            val safeMemoryBytes = (availableMemoryBytes * 0.8).toLong()
            val maxJobsByMemory = (safeMemoryBytes / estimatedBytesPerJob).toInt()
            return maxJobsByMemory
        }

        try {
            var currentMaxJobs = calculateMaxJobs()

            while (currentMaxJobs == 0) {
                delay(1000)
                currentMaxJobs = calculateMaxJobs()
            }

            withTimeoutOrNull(timeoutSeconds * 1000) {
                val channel = Channel<Int>(Channel.RENDEZVOUS)
                val completedIndices = AtomicInteger(0)
                val totalIndices = validSets.indices.count()

                scope.launch {
                    validSets.indices.forEach { channel.send(it) }
                    channel.close()
                }

                suspend fun startNewConsumerIfPossible() {
                    jobMutex.withLock {
                        val newMaxJobs = calculateMaxJobs()
                        val currentActive = activeJobs.get()

                        if (currentActive < newMaxJobs && currentActive < currentMaxJobs) {
                            currentMaxJobs = newMaxJobs
                            val job = scope.launch {
                                try {
                                    activeJobs.incrementAndGet()
                                    for (startIndex in channel) {
                                        val currentCombination = Combination(6)
                                        currentCombination.add(startIndex)
                                        val nextSet = validSets[startIndex]

                                        backtrack(
                                            start = startIndex,
                                            currentCombination = currentCombination,
                                            remainingVolume = targetVolume - nextSet.volume,
                                            scope = scope
                                        )

                                        completedIndices.incrementAndGet()
                                        startNewConsumerIfPossible()
                                    }
                                } finally {
                                    activeJobs.decrementAndGet()
                                    runningJobs.remove(coroutineContext[Job])
                                }
                            }
                            runningJobs.add(job)
                        }
                    }
                }

                repeat(currentMaxJobs) {
                    startNewConsumerIfPossible()
                }

                while (completedIndices.get() < totalIndices) {
                    delay(250)
                }
            }
        } finally {
            supervisorJob.cancelAndJoin()
        }

        // Convert best indices back to ExerciseSet list
        return@coroutineScope bestCombination.map { validSets[it] }
    }

    data class Solution(
        val combination: List<ExerciseSet>,
        val totalVolume: Double,
        val maxVolume: Double,
        val weightProgression: Double,
        val maxPercentLoad: Double,
        val maxFatigue: Double,
        val totalFatigue: Double,
        val maxReps: Double,
        val setCount: Int
    )

    private suspend fun findBestCombinationVariant(
        sets: List<ExerciseSet>,
        targetVolume: Double,
        minimumVolume: Double,
    ) = coroutineScope {
        val MAX_SETS = 5
        val MIN_VALID_SETS = 3
        val MAX_SOLUTIONS = 100

        val solutions = Collections.synchronizedList(ArrayList<Solution>(MAX_SOLUTIONS))

        // Improved initial filtering and sorting
        val sortedSets = sets
            .asSequence()
            .filter { set ->
                        set.volume * 3 <= targetVolume &&
                        set.volume * 5 >= minimumVolume
            }
            .sortedByDescending { it.volume }
            .toList()

        // Early return if we don't have enough sets
        if (sortedSets.size < MIN_VALID_SETS) {
            return@coroutineScope emptyList()
        }

        fun calculateWeightProgression(setCombo: List<ExerciseSet>): Double {
            return (1 until setCombo.size)
                .map { i ->
                    val ratio = setCombo[i].weight / setCombo[i - 1].weight
                    when {
                        ratio > 1.0 -> 0.0  // Penalize any volume increase
                        ratio == 1.0 -> 1.0  // Perfect for maintaining volume
                        else -> ratio  // Linear progression for all decreasing ratios
                    }
                }.average()
        }

        suspend fun searchChunk(startIdx: Int, endIdx: Int) = coroutineScope {
            flow {
                for (firstSetIdx in startIdx until endIdx) {
                    if (solutions.size >= MAX_SOLUTIONS) break

                    suspend fun buildCombination(
                        currentCombo: List<ExerciseSet>,
                        currentVolume: Double,
                        startFrom: Int,
                        depth: Int = 1
                    ) {
                        if (depth >= MAX_SETS) return

                        val lastSet = currentCombo.last()
                        for (nextIdx in startFrom until sortedSets.size) {
                            if (solutions.size >= MAX_SOLUTIONS) return

                            val nextSet = sortedSets[nextIdx]
                            val isValidSequence = lastSet.weight > nextSet.weight || (lastSet.weight == nextSet.weight && lastSet.reps >= nextSet.reps)

                            if (isValidSequence) {
                                val newVolume = currentVolume + nextSet.volume
                                //if (newVolume > targetVolume) break

                                val newCombo = currentCombo + nextSet
                                if (newCombo.size >= MIN_VALID_SETS && newVolume >= minimumVolume && newVolume <= targetVolume) {
                                    emit(Pair(newVolume, newCombo))
                                }
                                buildCombination(newCombo, newVolume, nextIdx, depth + 1)
                            }
                        }
                    }

                    buildCombination(
                        listOf(sortedSets[firstSetIdx]),
                        sortedSets[firstSetIdx].volume,
                        firstSetIdx
                    )
                }
            }
                .buffer(100)
                .flowOn(Dispatchers.Default)
                .collect { (volume, combo) ->
                    solutions.add(
                        Solution(
                            combination = combo,
                            totalVolume = volume,
                            maxVolume = combo.maxOf { it.volume },
                            weightProgression = calculateWeightProgression(combo),
                            maxPercentLoad = combo.maxOf { it.percentLoad },
                            maxFatigue = combo.maxOf { it.fatigue },
                            totalFatigue = combo.sumOf { it.fatigue },
                            setCount = combo.size,
                            maxReps = combo.maxOf { it.reps.toDouble() }
                        )
                    )
                }
        }

        // Optimize chunk distribution
        val numThreads = minOf(
            Runtime.getRuntime().availableProcessors(),
            (sortedSets.size + MIN_VALID_SETS - 1) / MIN_VALID_SETS
        )

        val chunkSize = (sortedSets.size + numThreads - 1) / numThreads

        (0 until numThreads)
            .map { threadIdx ->
                async(Dispatchers.Default) {
                    val startIdx = threadIdx * chunkSize
                    val endIdx = minOf(startIdx + chunkSize, sortedSets.size)
                    if (startIdx < endIdx) searchChunk(startIdx, endIdx)
                    else emptyList<ExerciseSet>() to Double.NEGATIVE_INFINITY
                }
            }
            .awaitAll()

        val maxFatigueValues = solutions.map { it.maxFatigue }
        val totalFatiguePerSetValues = solutions.map { it.totalFatigue }
        val maxPercentLoadValues = solutions.map { it.maxPercentLoad }
        val maxVolumeValues = solutions.map { it.maxVolume }
        val maxRepsValues = solutions.map { it.maxReps }

        fun List<Double>.normalizeMinMax(): List<Double> {
            val min = minOrNull() ?: return emptyList()
            val max = maxOrNull() ?: return emptyList()
            val range = max - min
            return if (range == 0.0) map { 0.0 } else map { (it - min) / range }
        }

        val maxFatigueNorm = maxFatigueValues.normalizeMinMax()
        val totalFatigueNorm = totalFatiguePerSetValues.normalizeMinMax()
        val maxPercentLoadNorm = maxPercentLoadValues.normalizeMinMax()
        val maxVolumeNorm = maxVolumeValues.normalizeMinMax()
        val maxRepsNorm = maxRepsValues.normalizeMinMax()

        val scores = solutions.mapIndexed { index, _ ->
            maxFatigueNorm[index] + totalFatigueNorm[index] + maxPercentLoadNorm[index] + maxVolumeNorm[index] + maxRepsNorm[index]
        }

        val target = scores.min()

        solutions.minByOrNull {
            val index = solutions.indexOf(it)
            abs(scores[index] - target)
        }?.combination ?: emptyList()
    }

    private suspend fun generatePossibleSets(params: WeightExerciseParameters): List<ExerciseSet> =
        coroutineScope {
            val minWeight = params.oneRepMax * (params.percentLoadRange.first / 100)
            val maxWeight = params.oneRepMax * (params.percentLoadRange.second / 100)

            val weightRange =  params.availableWeights.filter { it in minWeight..maxWeight }

            val setsDeferred = weightRange.map { weight ->
                async(Dispatchers.Default) {
                    val loadPercentage = weight / params.oneRepMax
                    val expectedReps = ((1.0278 - loadPercentage) / 0.0278).toInt()
                    val tolerance = 1

                    params.repsRange
                        .filter { reps ->
                            reps <= (expectedReps + tolerance)
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

            val sets = setsDeferred.awaitAll().flatten()

            // Filter out sets that exceed the percentage load range
            val filteredSets = sets.filter {
                it.percentLoad >= params.percentLoadRange.first &&
                        it.percentLoad <= params.percentLoadRange.second
            }

            //for sets with the same volume, keep the one with the lowest fatigue
            val setsByVolume = filteredSets.groupBy { it.volume }
            setsByVolume.map { it.value.minByOrNull { it.fatigue }!! }
        }

    private fun createSet(
        weight: Double,
        reps: Int,
        oneRepMax: Double,
        proximityToFailure: Int = 2
    ): ExerciseSet {
        val volume = weight * reps
        val relativeIntensity = weight / oneRepMax
        val percentLoad = relativeIntensity * 100


        // Smoothed intensity multiplier
        val intensityMultiplier = when {
            relativeIntensity > 0.85 -> exp(2.0 + (relativeIntensity - 0.85) * 10.0)
            else -> exp(2.0 * relativeIntensity)
        }

        // Enhanced metabolic stress calculation based on rep ranges
        val metabolicStress = when {
            reps > 20 -> 0.5 + (reps - 20) * 0.03
            reps > 12 -> 0.3 + (reps - 12) * 0.025
            reps > 6 -> (reps - 6) * 0.05
            else -> 0.0
        }

        // Rep multiplier incorporating metabolic stress
        val repMultiplier = 1 + ln(1.0 + reps) + metabolicStress

        // RIR multiplier with exponential scaling near failure
        val rirMultiplier = when {
            proximityToFailure <= 2 -> 1 + exp((2 - proximityToFailure) / 2.0)
            else -> 1 + (10 - proximityToFailure) / 10.0
        }

        val fatigue = volume  * (
                intensityMultiplier *
                        repMultiplier *
                        rirMultiplier
                )

        return ExerciseSet(
            weight = weight,
            reps = reps,
            fatigue = fatigue,
            volume = volume,
            percentLoad = percentLoad,
        )
    }

    suspend fun distributeVolumeWithMinimumIncrease(
        currentVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        percentageIncrease: Float,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        fatigueFactor: Float,
    ): DistributedWorkout? {
        if (percentageIncrease < 0) {
            throw IllegalArgumentException("Percentage increase must be positive")
        }

        val params = WeightExerciseParameters(
            targetTotalVolume = currentVolume,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            fatigueFactor = fatigueFactor,
            minimumVolume = currentVolume,
            originalVolume = currentVolume,
        )

        if (percentageIncrease >= 1) {
            val minimumRequiredVolume = currentVolume * (1 + (percentageIncrease / 100))
            val standardSolution = distributeVolume(
                params.copy(
                    targetTotalVolume = minimumRequiredVolume,
                    minimumVolume = currentVolume * 1.01
                )
            )
            if (standardSolution != null) {
                return standardSolution
            }
        }

        val noIncreaseSolution = distributeVolume(params)

        return noIncreaseSolution
    }
}
