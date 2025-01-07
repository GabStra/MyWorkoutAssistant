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
import kotlin.math.roundToInt
import kotlin.math.sqrt

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

    data class ExerciseData(
        val sets: List<ExerciseSet>,
        val totalVolume: Double,
        val totalFatigue: Double,
        val usedOneRepMax: Double,
        val maxRepsUsed: Int,
        val averageFatiguePerSet: Double,
        val averagePercentLoad: Double,
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
        val isDeload : Boolean
    )

    private suspend fun distributeVolume(
        params: WeightExerciseParameters,
    ): ExerciseData? {
        val possibleSets = generatePossibleSets(params)
        if (possibleSets.isEmpty()) return null

        val validSetCombination = findBestCombinationVariant(
            possibleSets,
            params.targetTotalVolume,
            params.minimumVolume,
            params.minSets,
            params.maxSets
        )
        if (validSetCombination.isEmpty()) return null

        val totalVolume = validSetCombination.sumOf { it.volume }

        return ExerciseData(
            sets = validSetCombination,
            totalVolume = totalVolume,
            totalFatigue = validSetCombination.sumOf { it.fatigue },
            usedOneRepMax = params.oneRepMax,
            maxRepsUsed = validSetCombination.maxOf { it.reps },
            averageFatiguePerSet = validSetCombination.sumOf { it.fatigue } / validSetCombination.size,
            progressIncrease = ((totalVolume - params.originalVolume) / params.originalVolume) * 100,
            averagePercentLoad = validSetCombination.sumOf { it.percentLoad } / validSetCombination.size,
            originalVolume = params.originalVolume,
            isDeloading = params.isDeload
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
        val totalFatigue: Double,
        val volumeVariation: Double
    )

    private suspend fun findBestCombinationVariant(
        sets: List<ExerciseSet>,
        targetVolume: Double,
        minimumVolume: Double,
        minSets: Int,
        maxSets: Int,
        maxSolutions: Int = 10
    ) = coroutineScope {
        require(minSets > 0)
        require(minSets <= maxSets)
        require(maxSolutions > 0)

        val solutions = Collections.synchronizedList(ArrayList<Solution>(maxSolutions))

        val maxUsefulVolumePerSet = targetVolume / minSets  // Max useful volume per set

        val sortedSets = sets
            .asSequence()
            .filter { set ->
                set.volume < targetVolume &&
                set.volume <= maxUsefulVolumePerSet
            }
            .sortedByDescending { it.volume }
            .toList()

        if (sortedSets.size < minSets) {
            return@coroutineScope emptyList()
        }

        suspend fun searchChunk(startIdx: Int, endIdx: Int) = coroutineScope {
            flow {
                for (firstSetIdx in startIdx until endIdx) {
                    if (solutions.size >= maxSolutions) break

                    suspend fun buildCombination(
                        currentCombo: List<ExerciseSet>,
                        currentVolume: Double,
                        startFrom: Int,
                        depth: Int = 1
                    ) {
                        if (depth >= maxSets) return

                        val lastSet = currentCombo.last()
                        for (nextIdx in startFrom until sortedSets.size) {
                            if (solutions.size >= maxSolutions) return

                            val nextSet = sortedSets[nextIdx]

                            val isValidSequence = (lastSet.weight > nextSet.weight ||
                                    (lastSet.weight == nextSet.weight && lastSet.reps >= nextSet.reps)) &&
                                    lastSet.fatigue >= nextSet.fatigue

                            if (isValidSequence) {
                                val newVolume = currentVolume + nextSet.volume

                                val newCombo = currentCombo + nextSet
                                if (newCombo.size >= minSets &&
                                    newVolume >= minimumVolume &&
                                    newVolume <= targetVolume) {
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
                .collect { (totalVolume, combo) ->
                    solutions.add(
                        Solution(
                            combination = combo,
                            totalFatigue = combo.sumOf {
                                val i = combo.indexOf(it)
                                val w = 1 + 0.2 * (i - 1)
                                it.fatigue * w
                            },
                            volumeVariation = combo.maxOf { it.volume } - combo.minOf { it.volume }
                        )
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
                    else emptyList<ExerciseSet>() to Double.NEGATIVE_INFINITY
                }
            }
            .awaitAll()

        fun calculateCombinedScore(solutions: List<Solution>): List<Double> {
            // Z-score normalization for better statistical properties
            fun List<Double>.normalizeZScore(): List<Double> {
                val mean = average()
                val stdDev = sqrt(map { (it - mean) * (it - mean) }.average())
                return if (stdDev == 0.0) map { 0.0 } else map { (it - mean) / stdDev }
            }

            // Extract and normalize metrics
            val fatigueNorm = solutions.map { it.totalFatigue }.normalizeZScore()
            val variationNorm = solutions.map { it.volumeVariation }.normalizeZScore()

            // Return combined scores with emphasis on volume distribution
            return List(solutions.size) { index ->
                fatigueNorm[index] + variationNorm[index]
            }
        }

        if(solutions.isEmpty()) return@coroutineScope emptyList()

        val combinationScores = calculateCombinedScore(solutions)

        solutions.minByOrNull {
            combinationScores[solutions.indexOf(it)]
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
    ): ExerciseSet {
        val volume = weight * reps
        val relativeIntensity = weight / oneRepMax
        val percentLoad = relativeIntensity * 100

        // Smoothed intensity multiplier
        val intensityMultiplier = 1.0 + 3.0 / (1.0 + exp(-10.0 * (relativeIntensity - 0.7)))

        // Continuous metabolic stress using logarithmic function
        val metabolicStress = if (reps > 0) {
            0.3 * ln(1.0 + reps / 6.0)
        } else {
            0.0
        }

        // Rep multiplier incorporating metabolic stress
        val repMultiplier = 1 + ln(1.0 + reps) + metabolicStress

        val fatigue = volume  * (intensityMultiplier * repMultiplier)

        return ExerciseSet(
            weight = weight,
            reps = reps,
            fatigue = fatigue,
            volume = volume,
            percentLoad = percentLoad,
        )
    }

    fun calculateTargetVolume(
        totalVolume: Double,
        desiredIncreasePercent: Float
    ): Double {
        val baseRate = (desiredIncreasePercent / 100).toDouble()

        // Volume factor using natural log to create progressive resistance
        val volumeFactor = (1.0 / (1.0 + ln(totalVolume))).coerceIn(0.3, 1.0)

        // Combined progression rate
        val progressionRate = (baseRate * volumeFactor)
            .coerceAtLeast(0.01)
            .coerceAtMost(baseRate)

        return totalVolume * (1 + progressionRate)
    }


    suspend fun generateExerciseProgression(
        totalVolume: Double,
        oneRepMax: Double,
        availableWeights: Set<Double>,
        desiredIncreasePercent: Float,
        percentLoadRange: Pair<Double, Double>,
        repsRange: IntRange,
        minSets: Int = 3,
        maxSets: Int = 5
    ): ExerciseData? {
        if (desiredIncreasePercent < 1) {
            throw IllegalArgumentException("Percentage increase must be higher or equal to 1")
        }

        /*val minimumRequiredVolume = calculateTargetVolume(
            totalVolume = totalVolume,
            desiredIncreasePercent = desiredIncreasePercent,
        )*/

        val params = WeightExerciseParameters(
            targetTotalVolume = totalVolume * 1.02,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            minimumVolume = totalVolume * 1.01,
            originalVolume = totalVolume,
            minSets = minSets,
            maxSets = maxSets,
            isDeload = false
        )

        return distributeVolume(params)
    }

    suspend fun redistributeExerciseSets(
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
        val params = WeightExerciseParameters(
            targetTotalVolume = upperVolumeRange,
            oneRepMax = oneRepMax,
            availableWeights = availableWeights,
            percentLoadRange = percentLoadRange,
            repsRange = repsRange,
            minimumVolume = lowerVolumeRange,
            originalVolume = totalVolume,
            minSets = minSets,
            maxSets = maxSets,
            isDeload = isDeload
        )

        val exerciseData = distributeVolume(params) ?: return null
        return exerciseData.copy(progressIncrease = 0.0)
    }
}
